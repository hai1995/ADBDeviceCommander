# -*- coding: utf-8 -*-
"""backend.controllers.device —— 设备刷新、开关、选中"""

class DeviceMixin:
    """设备：刷新、开关、选中。"""

    def refresh_devices(self):
        """手动刷新（后台执行，完成/失败以 status 事件回报）。"""
        if self.state.shutting_down:
            return {"ok": False}
        # 刷新完成后顺带回收「已移除设备」遗留的 logcat 监控 / 抓取（见
        # _reap_gone_tools），避免设备热插拔时留下孤儿 adb 进程与卡死的界面态。
        self.workers.spawn(
            "refresh", self._refresh_and_reap, self.state.adb_path, True)
        return {"ok": True}

    def _refresh_and_reap(self, adb, verbose):
        try:
            self.devices.refresh(adb, verbose)
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
