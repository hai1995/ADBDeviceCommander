"""backend.controllers.base —— 共享状态 / 生命周期 / 事件桥 / 点击计数 / 手册"""

from backend.controller import (
    AppState, BackendBus, DeviceAudioCapture, DeviceManager,
    FileService, FrameServer, LogcatCapture, LogcatMonitor,
    Path, ScrcpyLauncher, ShellSession, VideoRecorder,
    Workers, itertools, load_commands, load_prefs_checked, perf_stop_monitors,
    prefs_path, program_dir, resolve_save_dir, resource_path, save_click_deltas,
    threading, tmpfiles,
)

class WebApiBase:
    """WebApi 基：共享状态/生命周期/事件桥/点击计数/状态查询/手册。"""

    def __init__(self, bus=None, state=None, workers=None, devices=None,
                 session_factory=ShellSession, auto_update=True):
        self.bus = bus or BackendBus()
        self.state = state or AppState()
        self.workers = workers or Workers()
        self._auto_update = bool(auto_update)
        self.devices = devices or DeviceManager(self.bus)
        self.devices.bus = self.bus
        self.devices.inflight_guard = self._has_inflight_adb_sessions
        self.session = None
        self._session_factory = session_factory
        self._auto_started = False
        self.logcat_monitor = LogcatMonitor(self.bus, self.state.adb_path)
        self.logcat_capture = LogcatCapture(self.bus, self.state.adb_path)
        self.video = VideoRecorder(self.bus, self.state.adb_path)
        self.device_audio = DeviceAudioCapture(self.state.adb_path)
        self.file_svc = FileService(self.state.adb_path)
        self._scrcpy = ScrcpyLauncher()
        self._mirror_pipes = {}
        self._mirror_snaps = {}
        self._frame_server = FrameServer()
        self._mirror_starting = set()
        self._mirror_lock = threading.Lock()
        self._perfs = {}
        self._perf_lock = threading.Lock()
        self._perf_pkg_cache = {}
        self._perf_pkg_lock = threading.Lock()
        self._mic = None
        self._rec_session = {}
        self._user_lock = threading.Lock()
        self._ws_sessions = {}
        self._ws_locks = {}
        self._ws_busy = {}
        self._ws_stop_flag = {}
        self._ws_names = {}
        self._ws_guard = threading.RLock()
        self._ws_tls = threading.local()
        self._rec_lock = threading.Lock()
        self._file_seq = itertools.count(1)
        self._file_req = {}
        self._file_dir = {}
        self._file_refresh_timers = {}
        self._file_refresh_lock = threading.Lock()
        self._shot_seq = itertools.count(1)
        self._shot_batch_lock = threading.Lock()
        self._shot_batch = None
        self._shot_state_lock = threading.Lock()
        self._shot_inflight = 0
        self._shot_running = False
        self._apk_path = ""
        self._apk_batch_lock = threading.Lock()
        self._apk_batch = None
        self._click_lock = threading.Lock()
        self._click_bumps = {}
        self._click_timer = None
        self._diag_lock = threading.Lock()
        self._diag_running = False
        self._update_lock = threading.Lock()
        self._update_busy = False
        self._update_last = None
        self._update_last_ts = 0.0

    def _has_inflight_adb_sessions(self):
        """是否有「长连接」adb 会话在跑：录屏 / 落盘抓取 / 实时监控。"""
        video = getattr(self, "video", None)
        if video is not None:
            try:
                if video.any_recording():
                    return True
            except Exception:
                pass
        for name in ("logcat_capture", "logcat_monitor"):
            svc = getattr(self, name, None)
            if svc is None:
                continue
            try:
                if svc.running_serials():
                    return True
            except Exception:
                pass
        return False

    def boot(self):
        """前端加载完成后调用：加载命令、建立会话、启动自动轮询、首刷设备。"""
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        if self.state.booted:
            payload = self.state.mark_booted(
                self.state.commands, self.state.cmd_warnings)
            self._push_boot_events(self._boot_extras(payload))
            return {"ok": True, "replayed": True}
        commands, warnings = load_commands()
        payload = self.state.mark_booted(
            commands, warnings, adb_path=self.state.adb_path)
        if self.session is None:
            self.session = self._session_factory(
                output_callback=self._on_session_output,
                on_dir_change=self._on_session_dir_change,
                start_dir=program_dir())
        self._push_boot_events(self._boot_extras(payload))
        self._start_auto_refresh()
        self.workers.spawn("refresh", self.devices.refresh,
                           self.state.adb_path, True)
        self.workers.spawn(None, self._prewarm_adb_server)
        self.workers.spawn(None, tmpfiles.boot_sweep)
        if self._auto_update:
            self.workers.spawn("update_loop", self._update_loop)
        return {"ok": True}

    def _boot_extras(self, payload):
        """补齐 booted 载荷里的环境 / 配置字段（首次启动与重发共用）。"""
        settings, settings_warnings = load_prefs_checked()
        adb_ok = self._adb_found()
        payload["adb_ok"] = adb_ok
        cached_ver = settings.get("adb_version_cache", "")
        payload["adb"] = ((cached_ver or getattr(self.state, "adb_path", "")
                           or "adb")
                          if adb_ok else "adb 未就绪（未在 PATH 中找到）")
        payload["settings"] = settings
        payload["settings_warnings"] = settings_warnings
        payload["config_path"] = prefs_path()
        eff_dir, eff_note = resolve_save_dir(settings)
        payload["save_dir_effective"] = eff_dir
        payload["save_dir_note"] = eff_note
        return payload

    def _push_boot_events(self, payload):
        """广播 booted（命令 / 配置）+ 初始设备快照（可能为空，前端照常渲染）。"""
        items = self.devices.get_items()
        self.bus.push("booted", payload)
        self.bus.push("devices", {
            "items": items,
            "usable": [i["serial"] for i in items if i["ok"]],
            "added": [], "gone": [], "stat_changed": [],
            "dropped": [], "changed": True, "count": len(items),
        })

    def shutdown(self):
        """窗口关闭：幂等收尾——停全部后台任务、杀会话、等线程退出。"""
        if self.state.shutting_down:
            return {"ok": True}
        self.state.mark_shutdown()
        self._flush_clicks()
        sess, self.session = self.session, None
        if sess is not None:
            try:
                sess.kill()
            except Exception:
                pass
        with self._ws_guard:
            extra = list(self._ws_sessions.values())
            self._ws_sessions.clear()
            self._ws_locks.clear()
            self._ws_busy.clear()
            self._ws_stop_flag.clear()
            self._ws_names.clear()
        for s in extra:
            try:
                s.kill()
            except Exception:
                pass
        try:
            self.logcat_monitor.stop_all()
        except Exception:
            pass
        try:
            self.logcat_capture.stop_all(zip_on_stop=False)
        except Exception:
            pass
        with self._rec_lock:
            try:
                self.video.stop_all()
            except Exception:
                pass
            try:
                for s in list(self._rec_session.get("devaudio", {}).keys()):
                    self.device_audio.stop(s)
            except Exception:
                pass
            try:
                if self._mic is not None:
                    self._mic.stop()
                    self._mic = None
            except Exception:
                pass
            self._rec_session = {}
        with self._file_refresh_lock:
            pending = list(self._file_refresh_timers.values())
            self._file_refresh_timers.clear()
        for t in pending:
            try:
                t.cancel()
            except Exception:
                pass
        self.workers.shutdown(timeout=2.0)
        try:
            self._scrcpy.close_all()
        except Exception:
            pass
        for m in list(self._mirror_pipes.values()):
            try:
                m.stop()
            except Exception:
                pass
        for m in list(self._mirror_snaps.values()):
            try:
                m.stop()
            except Exception:
                pass
        self._mirror_pipes.clear()
        self._mirror_snaps.clear()
        try:
            self._frame_server.stop()
        except Exception:
            pass
        with self._perf_lock:
            mons, self._perfs = list(self._perfs.values()), {}
        perf_stop_monitors(mons)
        return {"ok": True}

    def take_events(self):
        return self.bus.take(max_n=2000, max_lines=2000)

    WS_DEFAULT = "w1"
    WS_MAX = 8

    def _ws_id(self, ws=None):
        """工作区 id 归一化：空 / 非法一律回落到默认工作区。"""
        if ws is None:
            return self.WS_DEFAULT
        wid = str(ws).strip()[:16]
        return wid or self.WS_DEFAULT

    def _ws_cur(self):
        """当前线程正在为哪个工作区执行命令（线程局部；无则默认工作区）。"""
        return getattr(self._ws_tls, "ws", None) or self.WS_DEFAULT

    def _ws_set_cur(self, ws):
        wid = self._ws_id(ws)
        self._ws_tls.ws = wid
        return wid

    def _ws_clear_cur(self):
        self._ws_tls.ws = None

    def _ws_label(self, ws=None):
        """状态栏前缀：默认工作区返回空串（单工作区时代文案完全不变）。"""
        wid = self._ws_id(ws)
        if wid == self.WS_DEFAULT:
            return ""
        return self._ws_names.get(wid) or wid

    def _ws_session(self, ws=None, create=True):
        """取某工作区的持久会话；不存在时按需创建（首次执行才拉起 shell）。"""
        wid = self._ws_id(ws)
        if wid == self.WS_DEFAULT:
            return self.session
        sess = self._ws_sessions.get(wid)
        if sess is None and create and not self.state.shutting_down:
            with self._ws_guard:
                sess = self._ws_sessions.get(wid)
                if sess is None and not self.state.shutting_down:
                    sess = self._session_factory(
                        output_callback=lambda text, w=wid:
                            self._on_session_output(text, w),
                        on_dir_change=lambda path, w=wid:
                            self._on_session_dir_change(path, w),
                        start_dir=program_dir())
                    self._ws_sessions[wid] = sess
        return sess

    def _ws_lock(self, ws=None):
        wid = self._ws_id(ws)
        if wid == self.WS_DEFAULT:
            return self._user_lock
        lk = self._ws_locks.get(wid)
        if lk is None:
            with self._ws_guard:
                lk = self._ws_locks.get(wid)
                if lk is None:
                    lk = threading.Lock()
                    self._ws_locks[wid] = lk
        return lk

    def _ws_interactive(self, wid):
        return bool(getattr(self._ws_sessions.get(wid), "in_interactive_shell", False))

    def _ws_publish_stop(self, wid):
        """广播某工作区的「停止」按钮态（仅在翻转时推一条）。"""
        busy = bool(self._ws_busy.get(wid)) or self._ws_interactive(wid)
        if busy != self._ws_stop_flag.get(wid, False):
            self._ws_stop_flag[wid] = busy
            self.bus.push("stop_state", {"running": busy, "ws": wid})
        return busy

    def _ws_begin(self, ws=None):
        """工作区开始执行一条命令。返回 (busy, changed)。"""
        wid = self._ws_id(ws)
        if wid == self.WS_DEFAULT:
            return self.state.begin_run()
        self._ws_busy[wid] = True
        return self._ws_publish_stop(wid), False

    def _ws_end(self, ws=None):
        wid = self._ws_id(ws)
        if wid == self.WS_DEFAULT:
            return self.state.end_run()
        self._ws_busy[wid] = False
        return self._ws_publish_stop(wid), False

    def ws_open(self, ws, name=""):
        """登记一个工作区（前端新建子 tab / 改名时调用）。"""
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        wid = self._ws_id(ws)
        if wid == self.WS_DEFAULT:
            return {"ok": True, "ws": wid, "name": self._ws_names.get(wid, "")}
        if wid not in self._ws_names and len(self._ws_names) >= self.WS_MAX:
            return {"ok": False, "reason": "工作区数量已达上限（%d 个）" % self.WS_MAX}
        nm = str(name or "").strip()[:24]
        if nm:
            self._ws_names[wid] = nm
        else:
            self._ws_names.setdefault(wid, "")
        return {"ok": True, "ws": wid, "name": self._ws_names.get(wid, "")}

    def ws_close(self, ws):
        """关闭工作区：杀掉它的会话并清掉全部运行态。"""
        wid = self._ws_id(ws)
        if wid == self.WS_DEFAULT:
            return {"ok": False, "reason": "默认工作区不能关闭"}
        sess = None
        with self._ws_guard:
            sess = self._ws_sessions.pop(wid, None)
            for d in (self._ws_locks, self._ws_busy, self._ws_stop_flag,
                      self._ws_names):
                d.pop(wid, None)
        if sess is not None:
            try:
                sess.kill()
            except Exception:
                pass
        return {"ok": True}

    def _on_session_output(self, text, ws=None):
        """ShellSession 标准输出回调 -> 指令台 out 事件。"""
        payload = {"kind": "out", "text": text}
        wid = self._ws_id(ws)
        if wid != self.WS_DEFAULT:
            payload["ws"] = wid
        self.bus.push("console", payload)

    def _on_session_dir_change(self, path, ws=None):
        """ShellSession 工作目录变化回调 -> prompt 事件。"""
        payload = {"kind": "prompt", "cwd": path}
        wid = self._ws_id(ws)
        if wid != self.WS_DEFAULT:
            payload["ws"] = wid
        self.bus.push("console", payload)

    def _push_status(self, type_, text, toast=False, alert=False, alert_title=""):
        """下发一条状态。toast=True 时前端会额外弹 toast 强提醒（高优先级提示语）。"""
        payload = {"type": type_, "text": text, "toast": bool(toast)}
        if alert:
            payload["alert"] = True
            if alert_title:
                payload["alert_title"] = alert_title
        self.bus.push("status", payload)

    def _push_toast(self, type_, text):
        """高优先级提示语：状态栏照常记录，同时强制前端弹 toast。"""
        self._push_status(type_, text, toast=True)

    def _push_alert(self, type_, text, title=""):
        """关键告警：状态栏 + toast + 不点不消失的弹窗。"""
        self._push_status(type_, text, toast=True, alert=True, alert_title=title)

    def _ws_status(self, type_, text, toast=False):
        """命令执行流程里的状态播报：多工作区时带上工作区名做前缀。"""
        tag = self._ws_label(self._ws_cur())
        self._push_status(type_, ("[%s] %s" % (tag, text)) if tag else text, toast)

    def _ws_toast(self, type_, text):
        self._ws_status(type_, text, toast=True)

    def _push_console(self, kind, text, ws=None):
        wid = self._ws_id(ws if ws is not None else self._ws_cur())
        payload = {"kind": kind, "text": text}
        if wid != self.WS_DEFAULT:
            payload["ws"] = wid
        self.bus.push("console", payload)

    def _push_cmd(self, text, ws=None):
        """CMD 风格命令回显：`<当前路径> 命令`。"""
        wid = self._ws_id(ws if ws is not None else self._ws_cur())
        sess = self.session if wid == self.WS_DEFAULT else self._ws_sessions.get(wid)
        path = (getattr(sess, "current_dir", None) or "").strip()
        self._push_console("cmd", "%s> %s" % (path or "PS", text), ws=wid)

    def _sync_stop_state(self, interactive=None, ws=None):
        """把 busy 变化广播给前端（stop 按钮态），只在翻转时推一次。"""
        wid = self._ws_id(ws if ws is not None else self._ws_cur())
        if wid == self.WS_DEFAULT:
            if interactive is None:
                interactive = bool(
                    getattr(self.session, "in_interactive_shell", False))
            busy, changed = self.state.sync_stop(interactive)
            if changed:
                self.bus.push("stop_state", {"running": busy})
            return busy
        return self._ws_publish_stop(wid)

    def _bump_click(self, cmd_id):
        """一次快捷指令点击 -> 内存 +1，并确保存在防抖落盘 Timer。"""
        with self._click_lock:
            self._click_bumps[cmd_id] = self._click_bumps.get(cmd_id, 0) + 1
            if self._click_timer is None:
                t = threading.Timer(1.0, self._flush_clicks)
                t.daemon = True
                t.start()
                self._click_timer = t

    def _flush_clicks(self):
        """把积攒的点击增量写回 json（关闭前由 shutdown 直接调用，立即落盘）。"""
        with self._click_lock:
            if not self._click_bumps:
                self._click_timer = None
                return
            bumps, self._click_bumps = self._click_bumps, {}
            self._click_timer = None
        try:
            save_click_deltas(bumps)
        except Exception:
            pass

    def get_state(self):
        """调试 / 对账用：一次性取后端状态快照。"""
        snapshot = self.state.snapshot()
        snapshot["devices"] = self.devices.get_items()
        snapshot["workers"] = self.workers.running_keys()
        return snapshot

    def get_manual(self):
        """读使用说明文本（README 风格、随 exe 内置副本，不再以独立文件随包分发）。"""
        try:
            path = resource_path("使用说明.txt")
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except Exception as ex:
            return {"ok": False, "reason": "使用说明读取失败：%s" % ex}
        return {"ok": True, "text": text}
