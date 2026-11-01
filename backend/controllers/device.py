# -*- coding: utf-8 -*-
"""backend.controllers.device —— 设备刷新、开关、选中"""

class DeviceMixin:
    """设备：刷新、开关、选中。"""

    def refresh_devices(self):
        """手动刷新（后台执行，完成/失败以 status 事件回报）。"""
        if self.state.shutting_down:
            return {"ok": False}
        # 已有同名 worker 在跑时，Workers.spawn 会**复用存活线程**（不会真的
        # 再刷一次），而这里照样返回 ok —— 用户点「刷新」看不到任何回音。
        # 启动首刷（boot）用的也是 "refresh"，撞上的概率不低。
        # 直接说明「有一轮正在跑、结果马上就来」，比静默丢弃诚实。
        if self.workers.is_running("refresh"):
            self._push_status(
                "info", "ℹ 设备刷新正在进行中，完成后列表会自动更新。")
            return {"ok": True, "running": True}
        # 刷新完成后顺带回收「已移除设备」遗留的 logcat 监控 / 抓取（见
        # _reap_gone_tools），避免设备热插拔时留下孤儿 adb 进程与卡死的界面态。
        self.workers.spawn(
            "refresh", self._refresh_and_reap, self.state.adb_path, True)
        return {"ok": True}

    def _refresh_and_reap(self, adb, verbose):
        try:
            # wait=True：自动轮询正占着刷新时，等它结束再刷一轮，而不是
            # 立刻返回 False（那样「刷新完成」提示永远不会出现）。
            self.devices.refresh(adb, verbose, wait=True)
        finally:
            self._reap_gone_tools()

    def toggle_device(self, serial, on):
        """勾选/取消一台设备。不可操作设备返回 ok=False（前端据此回滚 UI）。
        生效后立即广播设备快照，让 Logcat / 文件 tab 的「选中设备」实时跟随左侧勾选。"""
        applied = self.devices.toggle(serial, bool(on))
        if applied:
            items = self.devices.get_items()
            self.bus.push("devices", {
                "items": items,
                "changed": True,
                "count": len(items),
            })
        return {"ok": applied, "checked": self.devices.selected_serials()}

    def toggle_all(self):
        """全选 / 取消全部。状态变化后广播设备快照。"""
        want_all, changed = self.devices.toggle_all()
        if changed:
            items = self.devices.get_items()
            self.bus.push("devices", {
                "items": items,
                "changed": True,
                "count": len(items),
            })
        return {"all": want_all, "changed": changed}

    def selected_serials(self):
        return self.devices.selected_serials()
