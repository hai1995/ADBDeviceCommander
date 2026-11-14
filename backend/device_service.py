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
    ABSENT_STATE,
    DEVICE_POLL_TIMEOUT,
    DEVICE_RETRY_GAP_S,
    DEVICE_RETRY_MAX,
    DEVICE_SERVER_HEAL_AFTER,
    FAIL_NOTICE_INTERVAL_S,
    adb_kwargs,
    is_usable,
    state_label,
)
from core.devices import parse_devices, plan_devices

BUSY_WAIT_S = 12.0

BUSY_FORCE_RELEASE_S = 60.0


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
        self.device_checked = {}
        self.device_state = {}
        self.device_model = {}
        self._absent = {}
        self._busy = False
        self._busy_since = 0.0
        self._busy_owner = 0
        self._next_owner = 1
        self._idle = threading.Event()
        self._idle.set()
        self._had_devices = False
        self._polled_once = False
        self._fail_streak = 0
        self._heal_pending = False
        self._last_fail_notice = 0.0
        self.inflight_guard = None

    def _update_snapshot(self, plan):
        self.device_state = dict(plan["states"])
        models = dict(plan["models"])
        for s in plan["absent_streak"]:
            if s not in models and s in self.device_model:
                models[s] = self.device_model[s]
        self.device_model = models
        self.device_checked = dict(plan["checked"])
        self._absent = dict(plan["absent_streak"])

    def refresh(self, adb="adb", verbose=False, wait=False):
        """执行 `adb devices -l` 并广播结果。

        返回 True 表示列表有实质变化（前端据此重建设备卡片）。
        verbose=True 用于手动刷新：无论有无变化都补一条“完成”状态；
        自动轮询传 verbose=False，无变化时完全静默，避免每 5 秒刷屏。
        wait=True 用于**用户在等结果**的场合（手动点「刷新」）：撞上正在进行的
        一轮时先等它结束（上限 BUSY_WAIT_S）再自己刷一次，等不到就明确告知；
        wait=False 时维持旧行为（立刻放弃，供自动轮询——它下一秒还会再来，
        排队没有意义）。

        刷新失败（超时 / 异常 / 可疑空结果重试后仍失败）时返回 False 且
        **不清空快照**：界面继续展示上一次的设备列表，防止 adb 偶发抖动被
        用户当成「程序自动断连」。
        """
        owner = self._acquire(wait, verbose)
        if not owner:
            return False
        try:
            raw = self._poll_devices(adb, verbose)
            if raw is None:
                return False
            devices = parse_devices(raw)
            with self._lock:
                self._had_devices = bool(devices)
                plan = plan_devices(
                    self.device_checked, self.device_state,
                    self.device_model, devices, prev_absent=self._absent)
                first_load = plan["first_load"] and not self._polled_once
                self._polled_once = True
                changed = bool(plan["changed"] or first_load)
                self._update_snapshot(plan)
                if self.bus:
                    if not first_load:
                        for s in plan["recovered"]:
                            self.bus.push("status", {
                                "type": "info", "text": "✓ 设备已重连：{}".format(s)})
                        for s in plan["newly_absent"]:
                            self.bus.push("status", {
                                "type": "warn",
                                "text": "⚠ 设备短暂失联：{}（保留勾选，重连后自动恢复）".format(s)})
                        for s in plan["gone"]:
                            self.bus.push("status", {
                                "type": "warn",
                                "text": "⚠ 设备已断开：{}（已移除）".format(s)})
                        for s in plan["added"]:
                            if s in plan["recovered"]:
                                continue
                            self.bus.push("status", {
                                "type": "info", "text": "✓ 检测到新设备：{}".format(s)})
                        for s in plan["state_changed"]:
                            self.bus.push("status", {
                                "type": "warn",
                                "text": "⚠ 设备 {} 状态变为「{}」".format(s, state_label(plan["states"].get(s, "")))})
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
                if self._busy_owner == owner:
                    self._busy = False
                    self._busy_since = 0.0
            self._idle.set()

    def _acquire(self, wait, verbose):
        """尝试占用刷新互斥；占用成功返回 owner id（>0），失败返回 0。

        wait=True 时若已被占用，就等上一轮结束（上限 BUSY_WAIT_S）再抢；
        等不到（或 wait=False 直接放弃）时，**手动刷新必须给出回音** ——
        否则用户点「刷新」看到的是彻底的静默，只能反复点。自动轮询
        （verbose=False）保持静默放弃，它下一秒还会再来。

        强制释放：若 _busy 持续超过 BUSY_FORCE_RELEASE_S，认为上一轮
        refresh 已经僵尸化（adb 卡死、进程异常退出等），强制解锁让下一轮
        刷新能跑起来——而不是让「刷新正在进行中」这个假信号永远堵着。
        强制释放时会分配新的 owner id，僵死线程回来后不会误释放新的
        持有者（finally 里检查 owner 匹配才释放）。
        """
        deadline = time.time() + (BUSY_WAIT_S if wait else 0)
        while True:
            now = time.time()
            with self._lock:
                if not self._busy:
                    self._busy = True
                    self._busy_since = now
                    owner = self._next_owner
                    self._next_owner += 1
                    self._busy_owner = owner
                    self._idle.clear()
                    return owner
                if now - self._busy_since > BUSY_FORCE_RELEASE_S:
                    if self.bus:
                        self.bus.push("status", {
                            "type": "warn",
                            "text": "⚠ 上一轮设备刷新已超时卡死（%.0fs），"
                                    "已强制解锁，本轮将重新执行刷新。"
                                    % (now - self._busy_since)})
                    owner = self._next_owner
                    self._next_owner += 1
                    self._busy_since = now
                    self._busy_owner = owner
                    self._idle.clear()
                    return owner
            remain = deadline - time.time()
            if remain <= 0:
                break
            self._idle.wait(remain)
        if verbose and self.bus:
            self.bus.push("status", {
                "type": "warn",
                "text": "设备刷新正在进行中（上一轮 adb devices 还没返回），"
                        "请稍后再点一次「刷新」。"})
        return 0

    def _poll_devices(self, adb, verbose):
        """执行 `adb devices -l`，带可疑结果重试与 server 自愈。

        返回原始输出文本；返回 None 表示本轮刷新失败（调用方应保留快照）。
        """
        with self._lock:
            heal_now = (self._fail_streak >= DEVICE_SERVER_HEAL_AFTER
                        and not self._heal_pending)
        if heal_now and self._inflight_blocks_heal():
            heal_now = False
        if heal_now:
            with self._lock:
                self._heal_pending = True
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
                    with self._lock:
                        self._fail_streak = 0
                        self._heal_pending = False
                    return raw
                err = "empty"
            last_raw, last_err = raw, err
        if last_raw is not None:
            with self._lock:
                self._fail_streak = 0
                self._heal_pending = False
            return last_raw
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

    def _inflight_blocks_heal(self):
        """是否有长连接会话在跑，从而必须暂缓 adb server 自愈。

        守卫由上层（WebApi）注入：它知道有没有设备正在录屏 / 抓取日志。取不到
        结论时报 False（保持旧行为：该自愈就自愈），避免因为查询异常而让卡死的
        adb server 永远得不到恢复。
        """
        guard = self.inflight_guard
        if guard is None:
            return False
        try:
            return bool(guard())
        except Exception:
            return False

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