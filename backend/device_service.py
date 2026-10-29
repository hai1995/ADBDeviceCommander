# -*- coding: utf-8 -*-
"""
backend.device_service —— 设备服务（状态保持 + 刷新 + 差异播报）
================================================================
把设备列表的「快照 / 增量勾选保留 / 变化播报」从 controller 中拆出独立成服务，
controller / 自动轮询 / 未来的文件管理、录屏服务共用同一份设备快照。

对外接口：
  DeviceManager.refresh(adb, verbose)  —— 执行 adb devices -l 并广播变化
  DeviceManager.toggle / toggle_all    —— 勾选操作
  DeviceManager.selected_serials()     —— 当前有效下发目标
  DeviceManager.get_items()            —— 快照（序列化给前端）

防「误报断连」设计（v2026.1005 起）
----------------------------------
Windows 上 adb server 会被其他工具（Android Studio / 另一份 adb 客户端）重启，
USB 设备也会周期性重枚举，`adb devices -l` 偶发返回空列表或超时。若把单次轮询
结果当作事实，全部设备卡片会瞬间从界面消失——用户看到的就是「程序自动断连」。
因此 refresh 具备：

  * **可疑结果重试**：本次解析为空、但上一轮还有已知设备时，立即原样重试
    （DEVICE_RETRY_MAX 次，间隔 DEVICE_RETRY_GAP_S 秒）；
  * **失败保留快照**：重试后仍超时/异常时，不清空列表、不播报 gone，界面继续
    展示上一次的设备（按限频播报一条提示，避免每 5s 刷屏）；
  * **server 自愈**：连续失败 DEVICE_SERVER_HEAL_AFTER 次后，先执行一次
    `adb start-server` 再轮询——server 被杀死后不自愈则每次调用都会立刻失败；
  * **宽限设备置灰展示**：短暂失联（未超宽限）的设备以 state=reconnecting
    留在快照里（见 core.devices.plan_devices），卡片置灰、保留勾选，重连后
    自动恢复，不再「瞬间消失又出现」。
"""
import subprocess
import threading
import time

from core.constants import (
    adb_kwargs, state_label, is_usable, ABSENT_STATE,
    DEVICE_POLL_TIMEOUT, DEVICE_RETRY_MAX, DEVICE_RETRY_GAP_S,
    DEVICE_SERVER_HEAL_AFTER, FAIL_NOTICE_INTERVAL_S,
)
from core.devices import parse_devices, plan_devices


class DeviceManager:
    """设备列表状态与刷新（可被 WebApi / 自动轮询 / 其它服务共享）。

    线程安全约定：`adb devices` 这类 I/O 在锁外执行，但「读旧快照 -> 规划 ->
    写新快照 -> 广播」必须在同一把锁内完成，且所有公开的读（勾选/快照）
    与写（toggle / toggle_all）同样加锁——自动轮询线程与用户在 js_api
    线程的并发操作就不会产生不一致的中间快照。
    """

    def __init__(self, bus=None):
        self.bus = bus
        self._lock = threading.RLock()
        self.device_checked = {}   # serial -> bool（勾选保留，粘性）
        self.device_state = {}     # serial -> adb state（仅含在列表中的设备）
        self.device_model = {}     # serial -> model（含宽限内设备的最后已知型号）
        self._absent = {}          # serial -> int（宽限内「消失」的连续缺失计数）
        self._busy = False         # 刷新互斥（adb 卡顿时不叠加刷新线程）
        # ---- 防误报断连的运行态 ----
        self._had_devices = False  # 上一次成功轮询是否解析出过设备
        self._polled_once = False  # 是否已成功轮询过至少一次（见 refresh 里的 first_load）
        self._fail_streak = 0      # 连续刷新失败次数（驱动 start-server 自愈）
        self._heal_pending = False # 本次连续失败是否已尝试过自愈（只试一次）
        self._last_fail_notice = 0.0   # 上次失败播报时间戳（限频用）

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _update_snapshot(self, plan):
        self.device_state = dict(plan["states"])
        models = dict(plan["models"])
        # 宽限内消失的设备不在 plan["models"]（只含在列表设备）里，从上一轮
        # 快照继承型号，保证 UI 置灰卡片仍显示型号而不是 "unknown model"。
        for s in plan["absent_streak"]:
            if s not in models and s in self.device_model:
                models[s] = self.device_model[s]
        self.device_model = models
        self.device_checked = dict(plan["checked"])
        self._absent = dict(plan["absent_streak"])

    # ------------------------------------------------------------------
    # 刷新
    # ------------------------------------------------------------------
    def refresh(self, adb="adb", verbose=False):
        """执行 `adb devices -l` 并广播结果。

        返回 True 表示列表有实质变化（前端据此重建设备卡片）。
        verbose=True 用于手动刷新：无论有无变化都补一条“完成”状态；
        自动轮询传 verbose=False，无变化时完全静默，避免每 5 秒刷屏。

        刷新失败（超时 / 异常 / 可疑空结果重试后仍失败）时返回 False 且
        **不清空快照**：界面继续展示上一次的设备列表，防止 adb 偶发抖动被
        用户当成「程序自动断连」。
        """
        with self._lock:
            if self._busy:
                return False
            self._busy = True
        try:
            # adb 的 I/O 放在锁外：即便 adb 卡满 10s，用户勾选设备也不被阻塞
            raw = self._poll_devices(adb, verbose)
            if raw is None:
                return False        # 失败：保留上一轮快照，不广播、不清空
            devices = parse_devices(raw)
            # 读旧快照 + 规划 + 写新快照 + 广播必须原子化，与 toggle 等互斥
            with self._lock:
                self._had_devices = bool(devices)
                plan = plan_devices(
                    self.device_checked, self.device_state,
                    self.device_model, devices, prev_absent=self._absent)
                # 「首次加载」只在**第一次成功轮询**时成立。
                # core.devices.plan_devices 判定 first_load 的依据是「勾选 / 状态 /
                # 消失记忆全为空」—— 一台设备都没有时这三者永远为空，于是每一轮
                # 轮询都会被当成首次加载，`changed` 恒为 True：程序开着但还没插设备
                # （最常见的空闲状态）每 5 秒就广播一次 devices，前端跟着整表重建，
                # 与 verbose=False「无变化完全静默」的承诺、以及注释里
                # 「一打开程序不冒提示」都相矛盾。
                first_load = plan["first_load"] and not self._polled_once
                self._polled_once = True
                changed = bool(plan["changed"] or first_load)
                self._update_snapshot(plan)
                if self.bus:
                    # 差异播报：首次加载不播“新增”（一打开程序不冒提示）
                    if not first_load:
                        for s in plan["recovered"]:
                            self.bus.push("status", {
                                "type": "info", "text": "✓ 设备已重连：%s" % s})
                        for s in plan["newly_absent"]:
                            self.bus.push("status", {
                                "type": "warn",
                                "text": "⚠ 设备短暂失联：%s（保留勾选，重连后自动恢复）" % s})
                        for s in plan["gone"]:
                            self.bus.push("status", {
                                "type": "warn",
                                "text": "⚠ 设备已断开：%s（已移除）" % s})
                        for s in plan["added"]:
                            if s in plan["recovered"]:
                                continue
                            self.bus.push("status", {
                                "type": "info", "text": "✓ 检测到新设备：%s" % s})
                        for s in plan["stat_changed"]:
                            self.bus.push("status", {
                                "type": "warn",
                                "text": "⚠ 设备 %s 状态变为「%s」"
                                        % (s, state_label(plan["states"].get(s, "")))})
                    if changed:
                        self.bus.push("devices", {
                            "items": plan["items"],
                            "usable": list(plan["usable_serials"]),
                            "added": [] if first_load else plan["added"],
                            "gone": [] if first_load else plan["gone"],
                            "stat_changed": [] if first_load else plan["stat_changed"],
                            "dropped": plan["dropped"],
                            "changed": changed,
                            "count": len(devices),
                        })
                    if verbose:
                        self.bus.push("status", {
                            "type": "info",
                            "text": "刷新完成：当前 %d 台设备" % len(devices)})
                return changed
        finally:
            with self._lock:
                self._busy = False

    # ------------------------------------------------------------------
    # 防误报断连：轮询 + 重试 + 自愈（I/O 均在锁外执行）
    # ------------------------------------------------------------------
    def _poll_devices(self, adb, verbose):
        """执行 `adb devices -l`，带可疑结果重试与 server 自愈。

        返回原始输出文本；返回 None 表示本轮刷新失败（调用方应保留快照）。
        """
        # 连续失败达到阈值：先尝试拉起 adb server 再轮询。server 被其他工具
        # 杀掉后，不自愈则之后每次调用都会立刻失败，只能等用户手动干预。
        # _heal_pending 保证一段连续失败里只自愈一次（start-server 在 server
        # 存活时虽便宜，也没必要每 5s 调一次）。
        with self._lock:
            heal_now = (self._fail_streak >= DEVICE_SERVER_HEAL_AFTER
                        and not self._heal_pending)
            if heal_now:
                self._heal_pending = True
        if heal_now:
            self._start_server(adb)

        had = self._had_devices
        last_raw = None
        last_err = ""
        for attempt in range(DEVICE_RETRY_MAX + 1):
            if attempt:
                time.sleep(DEVICE_RETRY_GAP_S)
            try:
                out = subprocess.run(
                    [adb, "devices", "-l"], **adb_kwargs(DEVICE_POLL_TIMEOUT))
                raw, err = out.stdout or "", ""
            except subprocess.TimeoutExpired:
                raw, err = None, "timeout"
            except Exception as ex:
                raw, err = None, str(ex) or ex.__class__.__name__
            if raw is not None:
                if parse_devices(raw) or not had:
                    # 正常结果：解析出设备，或本来就没有设备（首刷 / 确实全拔了）
                    with self._lock:
                        self._fail_streak = 0
                        self._heal_pending = False
                    return raw
                # 可疑：上一轮还有设备，这次一个都没有——adb server 重启 /
                # USB 重枚举的典型瞬间表现。落到重试逻辑。
                err = "empty"
            last_raw, last_err = raw, err
        if last_raw is not None:
            # 拿到了文本、但重试后仍为空：接受「设备确实都不在了」的事实，
            # 交由 plan_devices 走宽限流程（置灰保留勾选，超宽限才遗忘），
            # 与「真拔线」同路径，不误报为刷新失败。
            with self._lock:
                self._fail_streak = 0
                self._heal_pending = False
            return last_raw
        # 全部尝试均为超时 / 异常：保留上一轮快照（不清空、不播 gone），
        # 按限频提示。
        with self._lock:
            self._fail_streak += 1
            due = verbose or (
                time.time() - self._last_fail_notice >= FAIL_NOTICE_INTERVAL_S)
            if due and self.bus:
                self._last_fail_notice = time.time()
                self.bus.push("status", {
                    "type": "warn",
                    "text": self._fail_text(last_err, had)})
        return None

    @staticmethod
    def _fail_text(err, had_devices):
        """刷新失败的提示文案（区分超时 / 空结果 / 其它异常）。"""
        if not had_devices:
            # 本来就没有设备（或已全部拔掉）：失败只是「没刷到」，不断连误报
            return "设备刷新未完成（%s）。" % (
                "adb 无响应" if err == "timeout" else err or "未知原因")
        return ("设备刷新超时（adb 无响应），已保留上次的设备列表。"
                if err == "timeout" else
                "设备刷新未返回列表（adb 可能正被其他程序占用），已保留上次的设备列表。"
                if err == "empty" else
                "设备刷新失败：%s（已保留上次的设备列表）。" % (err or "未知原因"))

    @staticmethod
    def _start_server(adb):
        """尝试拉起 adb server（自愈）；失败静默（下次轮询会再次尝试）。"""
        try:
            subprocess.run([adb, "start-server"], **adb_kwargs(8))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 勾选操作（全部加锁，与自动轮询的 refresh 并发安全）
    # ------------------------------------------------------------------
    def toggle(self, serial, on):
        """勾选/取消一台设备；不可操作设备一律忽略。返回是否生效。"""
        with self._lock:
            if serial in self.device_state and is_usable(self.device_state.get(serial, "")):
                self.device_checked[serial] = bool(on)
                return True
            return False

    def toggle_all(self):
        """全选 / 取消全部（仅作用于可操作设备）。
        返回 (new_state, changed)；new_state 为全部勾选后的 bool。
        """
        with self._lock:
            usable = [s for s, st in self.device_state.items() if is_usable(st)]
            if not usable:
                return False, False
            want_all = not all(self.device_checked.get(s) for s in usable)
            changed = any(
                bool(self.device_checked.get(s)) != want_all for s in usable)
            for s in usable:
                self.device_checked[s] = want_all
            return want_all, changed

    def selected_serials(self):
        """当前勾选且可操作（state==device）的设备序列号（下发目标）。

        勾选态是「粘性」的：一台曾勾选的设备即便短暂失联/状态异常也会保留勾选记忆，
        但其不在 device_state（或状态不可用）时一律不能作为下发目标，避免把命令
        发给一台当前不可达的设备。宽限内设备的虚拟 state=reconnecting 同样不可用。
        """
        with self._lock:
            return [
                s for s in self.device_checked
                if self.device_checked.get(s)
                and is_usable(self.device_state.get(s, ""))
            ]

    # ------------------------------------------------------------------
    # 快照
    # ------------------------------------------------------------------
    def get_items(self):
        """序列化当前设备快照（前端 / 事件共用）。

        含宽限内「短暂失联」的设备（state=reconnecting、ok=False、置灰展示），
        与 plan_devices 产出的 items 语义一致；顺序为在列表设备 + 宽限设备。
        """
        with self._lock:
            items = [
                {
                    "serial": s, "state": self.device_state.get(s, ""),
                    "model": self.device_model.get(s, ""),
                    "ok": is_usable(self.device_state.get(s, "")),
                    "checked": bool(self.device_checked.get(s)),
                }
                for s in self.device_state
            ]
            for s in sorted(self._absent):
                if s in self.device_state:
                    continue
                items.append({
                    "serial": s, "state": ABSENT_STATE,
                    "model": self.device_model.get(s, ""),
                    "ok": False, "checked": bool(self.device_checked.get(s)),
                })
            return items
