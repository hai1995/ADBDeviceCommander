# -*- coding: utf-8 -*-
"""backend.controllers.update —— 版本更新检查 / 下载 / 跳过"""

from backend.controller import (
    VERSION, _host_allowed, get_pref, save_prefs,
    time, updater
)

class UpdateMixin:
    """版本更新检查/下载/跳过。"""

    def _update_feed(self):
        """用户配置的更新源；返回空串表示「用内置的多源列表」。

        内置列表是「静态 latest.json → REST API」两个（见 core.update.FEEDS）：
        静态那份走 GitHub CDN、没有匿名接口那 60 次/小时/IP 的限流，同事多人
        共用一个公司出口 IP 时不会集体查到「限流」。
        """
        try:
            return (get_pref("update_feed", "") or "").strip()
        except Exception:
            return ""

    def update_info(self):
        """「关于」页要的版本信息：当前版本 / 是否自动检查 / 上次结果（不发请求）。"""
        try:
            enabled = bool(get_pref("update_check", True))
        except Exception:
            enabled = True
        last = self._update_last
        return {"ok": True,
                "version": VERSION,
                "enabled": enabled,
                # 展示用：没配就显示内置首选地址（静态 latest.json）
                "feed": self._update_feed() or updater.FEED_URL,
                "interval_s": updater.CHECK_INTERVAL_S,
                "checking": self._update_busy,
                "last": dict(last) if isinstance(last, dict) else None}

    def update_check(self, force=None):
        """检查更新：主线程立即返回，结果经 `update` 事件异步送达。

        force=True（用户在关于页点「检查更新」）时跳过开关与 12 小时节流 ——
        用户主动点了就必须真去查，否则「点了没反应」比不提供按钮更糟。
        """
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        force = bool(force)
        if not force:
            try:
                if not bool(get_pref("update_check", True)):
                    return {"ok": True, "status": "disabled"}
            except Exception:
                pass
            if not updater.due(self._update_last_ts):
                return {"ok": True, "status": "skipped"}
        with self._update_lock:
            if self._update_busy:
                # 已经有一次在查：不排队（排队会让用户看到过期的结果被当成新的）
                if force:
                    self._push_status("info", "ℹ 正在检查更新，请稍等…")
                return {"ok": False, "reason": "busy"}
            self._update_busy = True
        self.bus.push("update_state", {"running": True})
        self.workers.spawn("update", self._do_update_check, self._update_feed(), force)
        return {"ok": True, "status": "started"}

    def _do_update_check(self, feed, manual):
        """真正的检查（后台线程）：广播结果；自动检查失败时保持沉默。"""
        try:
            # feed 为空串 = 用 core.update.FEEDS（静态 → API 依次尝试）
            res = updater.check(VERSION, feed or None)
        except Exception as e:      # 兜底：这条线程不能带着 _update_busy=True 死掉，
            res = {"status": "error", "current": VERSION, "feed": feed,   # 否则按钮永久转圈
                   "version": "", "notes": "", "url": "", "asset": {},
                   "error": "检查更新时发生内部错误：%s" % e}
        finally:
            with self._update_lock:
                self._update_busy = False
            self.bus.push("update_state", {"running": False})

        self._update_last = res
        now = time.time()
        # 节流时间戳：查成功（含「已是最新」）按整间隔算；查失败只等 1 小时再试 ——
        # 开会切网 / VPN 掉线这类短暂断网，不该让更新提示消失半天。
        if res.get("status") == "error":
            self._update_last_ts = now - updater.CHECK_INTERVAL_S + 3600
        else:
            self._update_last_ts = now

        skipped = ""
        try:
            skipped = str(get_pref("update_skipped_version", "") or "").strip()
        except Exception:
            skipped = ""
        if (res.get("status") == "update" and not manual and skipped
                and updater.parse_version(skipped) == updater.parse_version(
                    res.get("version"))):
            # 用户点过「跳过此版本」：不弹窗，但结果照常广播（关于页仍能看到）
            self.bus.push("update", dict(res, silenced=True))
            return
        self.bus.push("update", dict(res, silenced=False))
        # 手动查：无论什么结果都说一句（否则用户不知道点没点上）；
        # 自动查：只有真有新版才说，其余情况（已是最新 / 网络不通）一律闭嘴。
        if manual or res.get("status") == "update":
            kind = {"update": "info", "latest": "ok", "ahead": "info"}.get(
                res.get("status"), "err")
            self._push_status(kind, updater.summary(res))

    def update_open(self, url=None):
        """用系统默认浏览器打开下载页（只允许白名单主机，见 _UPDATE_HOSTS）。"""
        target = (url or "").strip()
        if not target and isinstance(self._update_last, dict):
            target = (self._update_last.get("url") or "").strip()
        if not target:
            return {"ok": False, "reason": "还没有可打开的下载页，请先点「检查更新」"}
        extra = ()
        try:
            from urllib.parse import urlparse
            h = urlparse(self._update_feed()).hostname
            extra = (h,) if h else ()
        except Exception:
            extra = ()
        if not _host_allowed(target, extra):
            return {"ok": False,
                    "reason": ("拒绝打开这个地址：%s（只允许 GitHub 域名，"
                               "或 config.json 里 update_feed 所配置的域名）"
                               % target[:100])}
        try:
            import webbrowser
            opened = webbrowser.open(target)
        except Exception as e:
            return {"ok": False, "reason": "打开浏览器失败：%s" % e}
        self._push_status("info", "已在浏览器中打开下载页（%s）" % target)
        return {"ok": True, "url": target, "opened": bool(opened)}

    def update_skip(self, version=None):
        """记住「跳过此版本」：该版本不再自动弹窗（手动检查仍如实显示）。"""
        ver = (version or "").strip()
        if not ver and isinstance(self._update_last, dict):
            ver = str(self._update_last.get("version") or "").strip()
        if not ver:
            return {"ok": False, "reason": "没有可跳过的版本号"}
        if updater.parse_version(ver) is None:
            return {"ok": False, "reason": "版本号格式不认识：%s" % ver[:40]}
        try:
            save_prefs({"update_skipped_version": ver})
        except Exception as e:
            return {"ok": False, "reason": "保存失败：%s" % e}
        self._push_status("info", "已跳过版本 %s（更新到更新版本时仍会提示）" % ver)
        return {"ok": True, "version": ver}

    def update_unskip(self):
        """取消「跳过此版本」（关于页提供一个「恢复提示」出口）。"""
        try:
            save_prefs({"update_skipped_version": ""})
        except Exception as e:
            return {"ok": False, "reason": "保存失败：%s" % e}
        return {"ok": True, "version": ""}

    def _update_sleep(self, seconds):
        """更新检查专用的可中断等待（只在程序关闭时提前退出）。

        刻意不复用 _interruptible_sleep：那个函数还会因「用户点了停止」把休眠
        提前打断，而这里是 12 小时级的等待 —— 一旦 aborted 长期为真，整个循环
        会退化成满速空转（每轮都立刻返回 → 立刻又检查 → 再立刻返回）。
        """
        deadline = time.time() + max(0.0, float(seconds))
        while not self.state.shutting_down:
            left = deadline - time.time()
            if left <= 0:
                return
            time.sleep(min(0.5, left))

    def _update_loop(self):
        """后台定期检查更新：首查延迟 8 秒，之后按 CHECK_INTERVAL_S 复查。"""
        self._update_sleep(8.0)
        while not self.state.shutting_down:
            try:
                self.update_check(False)
            except Exception:
                pass        # 检查更新出任何问题都不能拖垮这条后台线
            self._update_sleep(updater.CHECK_INTERVAL_S)
