# -*- coding: utf-8 -*-
"""
core.devices —— 设备列表解析与增量差异决策（纯逻辑，无 UI 依赖）。

决策规则与 旧 Tk 版（已移除） 的 App._apply_devices 一致：
  * 设备还在且可操作（state == device）   -> 保留原有勾选；
  * 设备不可操作                          -> 强制取消勾选；
  * 设备已从列表消失（拔线）              -> 移除；
  * 列表无变化                            -> changed=False（定时轮询常态，不重建）。

宽限期内「短暂失联」的设备（adb 轮询抖动 / server 重启 / USB 重枚举）不立即从
UI 消失：以虚拟 state=reconnecting 继续留在 items 里（置灰展示、保留勾选记忆），
超过 DEVICE_GONE_GRACE_CYCLES 个周期仍未回来才视为真正断开并遗忘勾选。

上层（Tk 版 / Web 版）根据 plan 渲染 UI 即可。
"""
import re

from core.constants import (
    is_usable, DEVICE_GONE_GRACE_CYCLES, ABSENT_STATE,
)

# `adb devices -l` 的 state 字段是有限集合；其中 `no permissions` 含空格。
# 必须按「已知状态词」切分，不能简单 split()[1]：adb 在 mDNS 服务名冲突时会打印
# 形如 `adb-XXXX (2)._adb-tls-connect._tcp` 的序列号（**序列号本身含空格**，
# 见 adb transport.cpp 的 `%-22s %s` 与 flutter#187092/#189972），按空白切会把
# 序列号截成 `adb-XXXX`、状态变成 `(2)`，设备既显示成乱码状态又永远无法勾选下发。
# 长词在前，避免 `no` 之类前缀先匹配。
_DEVICE_STATES = (
    "no permissions", "device", "offline", "unauthorized", "bootloader",
    "recovery", "sideload", "rescue", "connecting", "authorizing", "host",
    "unknown", "detached",
)
_DEVICE_LINE_RE = re.compile(
    r"^(?P<serial>.+?)\s+(?P<state>%s)\b(?P<rest>.*)$"
    % "|".join(re.escape(s) for s in _DEVICE_STATES)
)


def _split_device_line(line):
    """把一行 `adb devices -l` 切成 (serial, state, rest)；无法识别返回 None。"""
    m = _DEVICE_LINE_RE.match(line)
    if m:
        return m.group("serial").strip(), m.group("state"), m.group("rest")
    # 兜底：状态不在已知集合里（未来 adb 新增状态）时仍按旧的空白切分，
    # 保证「认不出来也别把设备整条丢掉」。
    parts = line.split()
    if len(parts) < 2:
        return None
    return parts[0], parts[1], " ".join(parts[2:])


def parse_devices(raw: str):
    """解析 `adb devices -l` 输出 -> [(serial, state, model), ...]"""
    devices = []
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices") or line.startswith("*"):
            continue
        parsed = _split_device_line(line)
        if parsed is None:
            continue
        serial, state, rest = parsed
        model = ""
        for kv in rest.split():
            if kv.startswith("model:"):
                model = kv.split(":", 1)[1]
        devices.append((serial, state, model))
    return devices


def plan_devices(prev_checked, prev_state, prev_model, devices, prev_absent=None):
    """根据设备列表增量计算 UI 需要的差异信息。

    勾选态「粘性」规则（修复「多设备自动刷新误取消勾选」）：
      * 设备还在列表里（无论当前是否可用）-> 保留上一次的勾选；
      * 设备短暂从列表消失（adb 轮询抖动）-> 在宽限周期内保留勾选记忆，不在列表
        展示，但重连后自动恢复勾选；超过宽限周期仍未重连才视为真正断开、遗忘勾选；
      * 只有「用户手动取消」或「真正断开（超宽限）」才会遗忘勾选。

    参数：
      prev_checked: {serial: bool}   上一次勾选状态
      prev_state:   {serial: state}  上一次设备状态（快照只含在列表中的设备）
      prev_model:   {serial: model}  上一次设备型号
      devices:      [(serial, state, model), ...]  本次原始列表（可含重复，已按序）
      prev_absent:  {serial: int}    上一轮「已消失但在宽限内」的设备连续缺失计数

    返回 dict：
      {
        "changed": bool,              # 列表是否有实质变化
        "first_load": bool,           # 是否首次加载（无历史）
        "gone": [serial],             # 真正断开（超宽限）的设备
        "added": [serial],            # 本轮新出现在列表的设备
        "recovered": [serial],        # 上一轮消失、本轮重连的设备
        "newly_absent": [serial],     # 本轮刚消失（仅首次播报，宽限内保留勾选）
        "stat_changed": [serial],     # 状态/型号变化设备（不再强制取消勾选）
        "dropped": [serial],          # 兼容字段：新版不再因「不可用」强制取消勾选
        "auto_serial": str|None,      # 需要自动勾选的设备（唯一可用且从未勾选）
        "usable_serials": [serial],   # 当前可用设备
        "states": {serial: state},    # 当前在列表设备的最新状态（供上层保存）
        "models":  {serial: model},
        "checked": {serial: bool},    # 粘性勾选（在列表 + 宽限内消失的设备）
        "items": [ {serial, state, model, ok, checked} ]  # 在列表设备 + 宽限内消失设备
        "absent_streak": {serial: int},  # 本轮「消失但宽限内」的设备 -> 计数（持久化）
      }

    注意：items 里宽限内消失设备的 state 为 ABSENT_STATE（"reconnecting"）、
    ok=False；states/models 仍只含「在列表中的设备」（与旧版语义一致，供上层
    判定 present 集合），宽限设备的型号由上层从上一轮快照继承后一并展示。
    """
    prev_checked = dict(prev_checked or {})
    prev_state = dict(prev_state or {})
    prev_model = dict(prev_model or {})
    prev_absent = dict(prev_absent or {})

    cur = {s: (st, m) for s, st, m in devices}
    cur_serials = set(cur)
    # 上一轮「在列表中」的设备 = 上一次快照的 state 键（快照只保留在列表中的设备）
    prev_present = set(prev_state)

    # 基于 present 集合的真实新增 / 移除（决定列表是否变化、是否需重渲染）
    added = sorted(cur_serials - prev_present)
    removed = sorted(prev_present - cur_serials)

    # 本轮「已知但不在列表中」的设备 = 上一轮在列表 + 上一轮宽限内消失，减去本轮在列。
    # 这些设备的勾选记忆需要继续累加「连续缺失」计数，超过宽限才遗忘。
    absent_now = sorted((prev_present | set(prev_absent)) - cur_serials)
    gone = []
    newly_absent = []
    kept_absent = {}
    for s in absent_now:
        streak = prev_absent.get(s, 0) + 1
        if streak >= DEVICE_GONE_GRACE_CYCLES:
            gone.append(s)             # 超宽限：真正断开，遗忘勾选
        else:
            kept_absent[s] = streak
            if prev_absent.get(s, 0) == 0:
                newly_absent.append(s)  # 本轮刚消失（仅首次播报，宽限内保留勾选）

    # 重连：上一轮处于「宽限内消失（prev_absent）」且本轮重新出现在列表中
    recovered = sorted(s for s in added if s in prev_absent)

    # 状态/型号变化（仅本轮在列表中的设备）
    stat_changed = sorted(
        s for s in (cur_serials & prev_present)
        if prev_state.get(s) != cur[s][0] or prev_model.get(s) != cur[s][1]
    )

    changed = bool(added or removed or stat_changed)

    # 首次加载：之前完全没有设备历史（勾选 / 状态 / 消失记忆都为空）
    first_load = not prev_checked and not prev_state and not prev_absent

    # 一个都没勾选、且只有一台可用设备时自动勾选（多设备不会自动勾选）
    usable_list = [s for s, st, _m in devices if is_usable(st)]
    auto_serial = None
    if len(usable_list) == 1 and not any(prev_checked.values()):
        auto_serial = usable_list[0]

    # 勾选态粘性合并：在列表中的设备先按 devices 顺序保留勾选记忆（保证顺序确定），
    # 再补入宽限内消失的设备（sorted，同样确定）；真正断开（gone）遗忘勾选。
    next_checked = {}
    for serial, _st, _m in devices:
        keep = bool(prev_checked.get(serial, False))
        next_checked[serial] = keep or (serial == auto_serial)
    for serial in sorted(kept_absent):
        if serial in gone:
            continue
        next_checked.setdefault(serial, bool(prev_checked.get(serial, False)))

    # 仅「在列表中的设备」进入状态/型号/列表快照；消失设备不展示但勾选记忆保留
    states = {s: st for s, st, _m in devices}
    models = {s: m for s, _st, m in devices}

    items = []
    for serial, state, model in devices:
        ok = is_usable(state)
        checked = bool(next_checked.get(serial, False))
        items.append({
            "serial": serial, "state": state, "model": model,
            "ok": ok, "checked": checked,
        })
    # 宽限内「短暂失联」的设备继续留在 items 里（置灰展示、保留勾选记忆），
    # 避免一次轮询抖动就让卡片从界面上消失、被用户当成「程序自动断连」。
    # 型号用上一轮快照的 prev_model（在列表设备已覆盖不到它们）。
    for serial in sorted(kept_absent):
        if serial in gone:
            continue
        items.append({
            "serial": serial, "state": ABSENT_STATE,
            "model": prev_model.get(serial, ""),
            "ok": False, "checked": bool(next_checked.get(serial, False)),
        })

    return {
        "changed": changed,
        "first_load": first_load,
        "gone": gone,
        "added": added,
        "recovered": recovered,
        "newly_absent": newly_absent,
        "stat_changed": stat_changed,
        "dropped": [],
        "auto_serial": auto_serial,
        "usable_serials": usable_list,
        "states": states,
        "models": models,
        "checked": next_checked,
        "items": items,
        "absent_streak": kept_absent,
    }
