"""backend.controllers.device —— 设备刷新、开关、选中"""

class DeviceMixin:
    """设备：刷新、开关、选中。"""

    def refresh_devices(self):
        """手动刷新（后台执行，完成/失败以 status 事件回报）。

        不再用 Workers.is_running 拦截——DeviceManager._acquire 内部已有
        完善的「等待上一轮结束（12s）+ 超时强制解锁（60s）」机制。Workers.spawn
        用 key=None（匿名线程），每次点击都能真正触发一轮刷新，DeviceManager
        负责排队互斥。
        """
        if self.state.shutting_down:
            return {"ok": False}
        # spawn key=None：每次点击都真正启动一个 worker；DeviceManager._acquire
        # 内部排队/强制释放保证不会并发执行
        self.workers.spawn(
            None, self._refresh_and_reap, self.state.adb_path, True)
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
