"""backend.controllers.update —— 版本更新检查 / 下载 / 跳过"""

from backend.controller import (
    VERSION,
    _host_allowed,
    get_pref,
    save_prefs_checked,
    time,
    updater,
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
        try:
            skipped = str(get_pref("update_skipped_version", "") or "").strip()
        except Exception:
            skipped = ""
        last = self._update_last
        return {"ok": True,
                "version": VERSION,
                "enabled": enabled,
                "feed": self._update_feed() or updater.FEED_URL,
                "interval_s": updater.CHECK_INTERVAL_S,
                "checking": self._update_busy,
                "last": dict(last) if isinstance(last, dict) else None,
                "skipped": skipped}

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
                if force:
                    self._push_status("info", "ℹ 正在检查更新，请稍等…")
                return {"ok": False, "reason": "busy"}
            self._update_busy = True
        self.bus.push("update_state", {"running": True})
        try:
            self.workers.spawn("update", self._do_update_check,
                               self._update_feed(), force)
        except Exception as e:
            with self._update_lock:
                self._update_busy = False
            self.bus.push("update_state", {"running": False})
            self._push_toast("err", "⚠ 无法启动检查更新：{}".format(e))
            return {"ok": False, "reason": "spawn_error", "error": str(e)}
        return {"ok": True, "status": "started"}

    def _do_update_check(self, feed, manual):
        """真正的检查（后台线程）：广播结果；自动检查失败时保持沉默。"""
        try:
            res = updater.check(VERSION, feed or None)
        except Exception as e:
            res = {"status": "error", "current": VERSION, "feed": feed,
                   "version": "", "notes": "", "url": "", "asset": {},
                   "error": "检查更新时发生内部错误：{}".format(e)}
        finally:
            with self._update_lock:
                self._update_busy = False
            self.bus.push("update_state", {"running": False})

        self._update_last = res
        now = time.time()
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
            self.bus.push("update", dict(res, silenced=True))
            return
        self.bus.push("update", dict(res, silenced=False))
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
            why = ("拒绝打开这个地址：{}（只允许 GitHub 域名，"
                   "或 config.json 里 update_feed 所配置的域名）".format(target[:100]))
            self._push_status("err", "⚠ " + why)
            return {"ok": False, "reason": why}
        try:
            import webbrowser
            opened = webbrowser.open(target)
        except Exception as e:
            why = "打开浏览器失败：{}".format(e)
            self._push_status("err", "⚠ " + why)
            return {"ok": False, "reason": why}
        if not opened:
            self._push_status("warn", "⚠ 没能唤起浏览器，请手动访问：{}".format(target))
            return {"ok": False, "url": target, "opened": False,
                    "reason": ("没能唤起系统浏览器（没有默认浏览器，或被安全策略"
                               "拦下）。请手动访问：{}".format(target))}
        self._push_status("info", "已在浏览器中打开下载页（{}）".format(target))
        return {"ok": True, "url": target, "opened": True}

    def update_skip(self, version=None):
        """记住「跳过此版本」：该版本不再自动弹窗（手动检查仍如实显示）。"""
        ver = (version or "").strip()
        if not ver and isinstance(self._update_last, dict):
            ver = str(self._update_last.get("version") or "").strip()
        if not ver:
            return {"ok": False, "reason": "没有可跳过的版本号"}
        if updater.parse_version(ver) is None:
            return {"ok": False, "reason": "版本号格式不认识：{}".format(ver[:40])}
        _merged, wrote = save_prefs_checked({"update_skipped_version": ver})
        if not wrote:
            msg = "配置无法写入（程序目录是否只读？），未能记住跳过版本"
            self._push_status("err", "⚠ " + msg)
            return {"ok": False, "reason": msg, "version": ver}
        self._push_status("info", "已跳过版本 {}（更新到更新版本时仍会提示）".format(ver))
        return {"ok": True, "version": ver}

    def update_unskip(self):
        """取消「跳过此版本」（关于页提供一个「恢复提示」出口）。"""
        _merged, wrote = save_prefs_checked({"update_skipped_version": ""})
        if not wrote:
            msg = "配置无法写入（程序目录是否只读？），未能恢复更新提示"
            self._push_status("err", "⚠ " + msg)
            return {"ok": False, "reason": msg}
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
                pass
            wait_s = updater.next_wait_s(self._update_last_ts)
            self._update_sleep(wait_s if wait_s > 0 else updater.CHECK_INTERVAL_S)