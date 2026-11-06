# -*- coding: utf-8 -*-
"""backend.controllers.base —— 共享状态 / 生命周期 / 事件桥 / 点击计数 / 手册"""

from backend.controller import (
    AppState, BackendBus, DeviceAudioCapture, DeviceManager,
    FileService, FrameServer, LogcatCapture, LogcatMonitor,
    Path, ScrcpyLauncher, ShellSession, VideoRecorder,
    Workers, itertools, load_commands, load_prefs_checked, perf_stop_monitors,
    prefs_path, resolve_save_dir, resource_path, save_click_deltas,
    threading, tmpfiles
)

class WebApiBase:
    """WebApi 基：共享状态/生命周期/事件桥/点击计数/状态查询/手册。"""

    def __init__(self, bus=None, state=None, workers=None, devices=None,
                 session_factory=ShellSession, auto_update=True):
        self.bus = bus or BackendBus()
        self.state = state or AppState()
        self.workers = workers or Workers()
        # 是否在 boot() 里启动「自动检查更新」后台线程。
        # 单测默认关掉：那条线程会真的发 HTTPS 请求（无网络时还要等超时），
        # 让一个「测 boot 有没有广播事件」的用例变成网络用例既慢又随机失败。
        self._auto_update = bool(auto_update)
        self.devices = devices or DeviceManager(self.bus)
        self.devices.bus = self.bus          # 确保设备服务事件指向同一总线
        # 录屏 / 落盘抓取期间禁止自动重启 adb server（见 DeviceManager._poll_devices）：
        # start-server 遇到「活着但不应答」的 server 会先 kill 再拉起，把在途的
        # `adb shell screenrecord` 一起掐断 —— 设备正常，录屏却被程序自己搞断。
        self.devices.inflight_guard = self._has_inflight_adb_sessions
        self.session = None                  # boot() 后创建（依赖 adb 环境）
        self._session_factory = session_factory
        self._auto_started = False           # 自动轮询只启动一次
        # ---- 工具服务（截图 / 录屏 / 音频 / 文件 / logcat）----
        self.logcat_monitor = LogcatMonitor(self.bus, self.state.adb_path)
        self.logcat_capture = LogcatCapture(self.bus, self.state.adb_path)
        self.video = VideoRecorder(self.bus, self.state.adb_path)
        self.device_audio = DeviceAudioCapture(self.state.adb_path)
        self.file_svc = FileService(self.state.adb_path)
        # 投屏：只负责「找 scrcpy + 拉起窗口」，进程句柄留在这里用于去重与收尾
        self._scrcpy = ScrcpyLauncher()
        # 备用投屏（没装 scrcpy 时）：① screenrecord 管道给播放器 ② screencap
        # 低帧率预览。帧服务是全进程共享的（前端 <img> 按 serial 各取各的）。
        self._mirror_pipes = {}                 # serial -> PipeMirror
        self._mirror_snaps = {}                 # serial -> SnapMirror
        self._frame_server = FrameServer()
        # 「正在启动中」的设备：_start_one_mirror 是同步的（要等首帧，最长
        # FIRST_DATA_TIMEOUT=6s），这段时间设备还没登记进上面两张表。不占位
        # 的话，连点两次「投屏」会各走一遍启动流程（scrcpy 那边已修过同一个
        # 坑，这里当时漏了）。
        self._mirror_starting = set()
        self._mirror_lock = threading.Lock()
        # 性能监控：可同时监控多台受控设备（用于横向对比），上限 PERF_MAX_DEVICES。
        # 每台一条独立采样线程 + 一份环形缓冲，前端按 serial 分色画多线。
        # 会话对象在 perf_start 时创建，perf_stop / shutdown 时收尾。
        self._perfs = {}                        # serial -> PerfMonitor
        self._perf_lock = threading.Lock()
        # 「应用包名」下拉框的已安装应用缓存：serial -> {at, data}。
        # pm list packages 在应用多的机器上要 1~3 秒，而下拉框每次打开都会问一次。
        self._perf_pkg_cache = {}
        self._perf_pkg_lock = threading.Lock()
        self._mic = None                      # 录制中的 MicRecorder 实例
        self._rec_session = {}                # 录屏会话：serial -> {devaudio, ...}
        self._user_lock = threading.Lock()    # 用户命令单飞锁（一次只跑一条）
        # ---- 指令台多工作区（子 tab）----
        # 每个工作区一套**独立的持久会话 + 执行锁 + 停止按钮态**：用户在工作区 2
        # 里挂着一条 10 分钟的 logcat 时，工作区 1 仍能立刻执行别的命令，两边的
        # 输出各进各的面板。只做「多个输出面板」而不分会话是不够的 —— 那样工作区
        # 2 点「执行」只是排到工作区 1 的命令后面等着，面板半天没有一行输出，
        # 用户会以为命令没发出去。
        # 默认工作区（W1）沿用历史字段 self.session / _user_lock / state.busy，
        # 故单工作区路径（含全部既有测试与全部既有事件文案）零变化。
        self._ws_sessions = {}       # ws_id -> ShellSession（不含 W1，懒创建）
        self._ws_locks = {}          # ws_id -> Lock（不含 W1）
        self._ws_busy = {}           # ws_id -> bool（不含 W1）：是否有命令在跑
        self._ws_stop_flag = {}      # ws_id -> bool（不含 W1）：上次广播的停止按钮态
        self._ws_names = {}          # ws_id -> 用户可见名称（播报用）
        self._ws_guard = threading.RLock()  # 保护上面几个 dict 的建/删（见 _ws_session）
        self._ws_tls = threading.local()   # 本线程正在为哪个工作区执行
        self._rec_lock = threading.Lock()     # 录屏/录音会话独占锁（start/stop/shutdown）
        # 文件下载序列号：批量下载同一设备的多个文件时，每个文件需要独立后台线程，
        # 故 file_download 用此计数器构造唯一 worker key，避免被 Workers 按
        # "fileop_<serial>" 去重掉、只剩第一个真正下载（「下载选中只下 1 个」的根因）。
        # 列目录 / 查看同理由此取唯一 key（见 file_list），否则「上一次还没跑完时
        # 再点进另一个目录」会被同名去重静默丢弃。
        self._file_seq = itertools.count(1)
        # 每台设备「最新一次列目录请求」的序号：迟到的旧响应据此丢弃，
        # 避免它把刚打开的目录内容覆盖回上一个目录。
        self._file_req = {}
        # 每台设备「当前正在看的目录」（file_list 时记录）：批量上传的合并
        # 刷新据此判断用户是否已经切走，防止把界面弹回上传时的目录。
        self._file_dir = {}
        # 批量上传的目录刷新合并：serial -> 待触发的 Timer（见 file.py 的
        # _schedule_file_refresh）。同一设备只留一个，关闭时统一 cancel。
        self._file_refresh_timers = {}
        self._file_refresh_lock = threading.Lock()
        # 截图请求序号：每次截图用独立 worker key（见 screenshot），
        # 否则同一设备连点两次会被同名去重静默吞掉一次。
        self._shot_seq = itertools.count(1)
        # 批量截图汇总：多设备一次点击各起一个 worker，全部到齐后弹一条
        # 汇总 toast（见 screenshot / _shot_batch_done）。
        self._shot_batch_lock = threading.Lock()
        # 「最近一批」批量截图的计数器（仅供外部查询）。计数本身按批传递，
        # 见 screenshot.py：连点两次时两批各算各的账，互不覆盖。
        self._shot_batch = None
        # 截图在途计数：「立即截图」禁用态的事实来源——+1 广播 running=true
        # （前端禁用按钮），全部 worker 收尾回落 0 时广播 running=false（恢复）。
        # 计数而非布尔：请求叠加上先结束的不会提前解开另一个的禁用态；
        # 只在 0<->1 翻转时推事件，批量 N 台设备也不会推 N 条（见 _shot_state_change）。
        self._shot_state_lock = threading.Lock()
        self._shot_inflight = 0
        self._shot_running = False
        # ---- APK 安装 ----
        # 待安装的本地安装包（apk_pick 选定，apk_install 使用）。只记路径：
        # 前端不需要也不应该把几百 MB 的字节搬过 js_api 桥。
        self._apk_path = ""
        # 批量汇总（多设备一次点击各起一个 worker，全部到齐弹一条 toast）。
        self._apk_batch_lock = threading.Lock()
        self._apk_batch = None
        # ---- 快捷指令点击计数（「常用命令靠前」排序的数据来源，防抖落盘）----
        self._click_lock = threading.Lock()
        self._click_bumps = {}     # cmd_id -> 本次会话累计点击增量
        self._click_timer = None   # 防抖 Timer（1s 无新点击后写回 json）
        # ---- 诊断包（一键收集设备信息 / 日志 / 进程 / 应用 / ANR）----
        # 收集是「一串 adb 调用 + 写盘 + 打包」，全部在一条后台线程里顺序做完：
        # 单设备 3~6 秒。同一时刻只允许一批在跑（按钮据此禁用），故不用批次计数，
        # 只要一个 running 布尔 + 一个 worker key。
        self._diag_lock = threading.Lock()
        self._diag_running = False
        # ---- 版本更新（检查新版本 -> 前端弹窗提示去下载，见 core/update.py）----
        # 同一时刻只查一次：自动检查与手动点击可能撞在一起，两次请求除了浪费
        # 一次额度没有任何好处。_update_last 留着上一次结果，「关于」页随时可看。
        self._update_lock = threading.Lock()
        self._update_busy = False
        self._update_last = None
        # 上次检查完成的时间戳（节流依据）。0 = 本会话还没查过。
        self._update_last_ts = 0.0

    def _has_inflight_adb_sessions(self):
        """是否有「长连接」adb 会话在跑：录屏 / 落盘抓取 / 实时监控。

        这些会话靠一条常驻的 `adb shell` 连接活着。自动重启 adb server 会把
        在途连接全部掐断：正在录的 screenrecord 直接死掉、正在写盘的 logcat
        EOF。设备明明正常，却是程序自己的自愈动作把录屏搞断的 —— 所以录屏 /
        抓取期间暂缓自愈（见 DeviceManager._poll_devices）。

        查询异常时返回 False：宁可让它照旧自愈，也不要想当然地永久压住自愈。
        """
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
            return {"ok": False, "reason": "already_booted"}
        commands, warnings = load_commands()
        payload = self.state.mark_booted(
            commands, warnings, adb_path=self.state.adb_path)
        # 会话延迟创建：避免无 GUI 环境（单测/无头）也拉起 powershell
        if self.session is None:
            self.session = self._session_factory(
                output_callback=self._on_session_output,
                on_dir_change=self._on_session_dir_change)
        # adb 就绪状态：about 页展示用；缺失时不阻断启动，改用引导提示
        adb_info = self._probe_adb()
        payload["adb_ok"] = adb_info["ok"]
        payload["adb"] = (adb_info["version"] or adb_info["path"]
                          if adb_info["ok"] else "adb 未就绪（未在 PATH 中找到）")
        # 用户配置（config.json）随 booted 下发，前端回填相关控件；
        # 被防错机制纠正过的字段（手写错类型 / 非法级别等）一并带上下发提示，
        # 让用户知道「某项配置没生效、已恢复默认」，而不是莫名发现开关复位。
        settings, settings_warnings = load_prefs_checked()
        payload["settings"] = settings
        payload["settings_warnings"] = settings_warnings
        # 配置文件位置（本机实际落盘路径）与本机实际生效的保存目录。
        # 前者让用户能在「关于」页看到并拷贝 config.json 去别的电脑同步；
        # 后者用于路径失效时告知「已改用默认目录」（配置文件里的原值不动）。
        payload["config_path"] = prefs_path()
        eff_dir, eff_note = resolve_save_dir(settings)
        payload["save_dir_effective"] = eff_dir
        payload["save_dir_note"] = eff_note
        # 广播：booted（命令列表）+ 初始设备快照（可能为空，前端照常渲染）
        items = self.devices.get_items()
        self.bus.push("booted", payload)
        self.bus.push("devices", {
            "items": items,
            "usable": [i["serial"] for i in items if i["ok"]],
            "added": [], "gone": [], "stat_changed": [],
            "dropped": [], "changed": True, "count": len(items),
        })
        self._start_auto_refresh()
        # 首刷设备（后台线程，失败也会自行广播错误状态）
        self.workers.spawn("refresh", self.devices.refresh,
                           self.state.adb_path, True)
        # adb server 预热：server 不在时要拉起来（冷启一次数百 ms），
        # 不该由「启动后第一次截图」替它付这笔钱。幂等——server 已在时
        # 立即返回；失败静默（首刷设备的 adb devices 同样会拉 server）。
        self.workers.spawn(None, self._prewarm_adb_server)
        # 清理上一轮「查看大文件」遗留在系统临时目录里的副本（见 core.tmpfiles）。
        # 放在后台线程：列目录本身可能很慢（TEMP 里堆了几万个文件），
        # 不能让它挡住窗口显示。
        self.workers.spawn(None, tmpfiles.boot_sweep)
        # 版本检查：后台线程里「等 8 秒再查首次」——启动瞬间 adb 探测、命令加载、
        # 设备首刷都在抢时间，再叠一个网络请求会让窗口第一秒的响应变钝。
        # 之后每 CHECK_INTERVAL_S 复查一次（见 _update_loop）。
        if self._auto_update:
            self.workers.spawn("update_loop", self._update_loop)
        # adb 缺失的引导提示由前端 onBooted（adb_ok=false）统一弹出
        return {"ok": True}

    def shutdown(self):
        """窗口关闭：幂等收尾——停全部后台任务、杀会话、等线程退出。"""
        if self.state.shutting_down:
            return {"ok": True}
        self.state.mark_shutdown()
        self._flush_clicks()   # 关闭前把未落盘的点击计数写回
        sess, self.session = self.session, None
        if sess is not None:
            try:
                sess.kill()
            except Exception:
                pass
        # 多工作区的会话同样要收：每个背后都是一条常驻的 powershell / adb 子进程，
        # 漏掉就会在关窗后残留，用户下次开会看到一堆来路不明的进程。
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
        # 工具类后台任务一并收尾
        try:
            self.logcat_monitor.stop_all()
        except Exception:
            pass
        try:
            self.logcat_capture.stop_all(zip_on_stop=False)
        except Exception:
            pass
        # 与 screen_record_stop 共享同一把锁：避免关闭瞬间用户恰好点「停止」，
        # 两处同时遍历 videos / devaudio / 停麦导致状态互相踩踏。
        # 注意 video.stop_all() 也必须在锁内：它和 _screen_record_stop_locked 会处理
        # 同一台设备（前者走 stop_all 的旧路径、后者走会话记录路径），并发时会各自
        # pull / 合成同一个文件，出现重复合成甚至互相覆盖的半截 zip。
        with self._rec_lock:
            try:
                self.video.stop_all()
            except Exception:
                pass
            try:
                # 注意：序列号在 _rec_session["devaudio"] 里，_rec_session 本身是
                # 会话字段字典（ts/dir/videos/...）。早期实现直接遍历 _rec_session
                # 的键，拿到的是字段名而非序列号，导致设备端 tinycap 从未被停止。
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
            # 收尾完毕即清空会话：否则关闭过程中用户再点一次「停止录屏」，
            # _screen_record_stop_locked 会拿残留的 videos 路径再合成/打包一遍。
            self._rec_session = {}
        # 待触发的「合并刷新」定时器：关闭时先取消，否则它会在 workers 收尾
        # 之后再去起一个 adb ls（窗口都关了，日志里只剩一条来源不明的错误）。
        with self._file_refresh_lock:
            pending = list(self._file_refresh_timers.values())
            self._file_refresh_timers.clear()
        for t in pending:
            try:
                t.cancel()
            except Exception:
                pass
        self.workers.shutdown(timeout=2.0)
        # 投屏窗口由本程序拉起，关闭时一并收掉（用户早已自己关掉的不会受影响）
        try:
            self._scrcpy.close_all()
        except Exception:
            pass
        # 备用投屏：管道投屏要在设备端留下 screenrecord，不收尾会一直占着编码器
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
        # 性能监控线程：不主动停的话它会一直每隔 N 秒调一次 adb，并且在窗口
        # 关闭后继续向已销毁的 webview 推事件（pywebview 侧会报 evaluate_js 失败）。
        #   批量停：先统一置停止信号再等，否则每台都要等满 join 超时（采样线程
        #   多数时间卡在 adb shell 里），4 台设备就让窗口多挂十几秒才消失。
        with self._perf_lock:
            mons, self._perfs = list(self._perfs.values()), {}
        perf_stop_monitors(mons)
        return {"ok": True}

    def take_events(self):
        return self.bus.take(max_n=2000, max_lines=2000)

    # ---------------- 指令台多工作区（子 tab） ----------------
    # 一句话说清这个功能的边界：**会话隔离**，不是「多个输出面板」。同一时刻
    # 每个工作区各有一条自己的 adb/powershell 会话，因此两边可以真的同时在跑；
    # 只做面板的话，工作区 2 点「执行」只是排在别人的命令后面等着，面板半天
    # 没有一行输出 —— 用户会以为命令没发出去（这正是最要避免的静默误导）。
    WS_DEFAULT = "w1"      # 默认工作区（历史唯一的那一个）
    WS_MAX = 8             # 工作区数量上限（后端兜底；界面另有一道）

    def _ws_id(self, ws=None):
        """工作区 id 归一化：空 / 非法一律回落到默认工作区。

        id 由前端生成（w1、w2…）。它既会进事件载荷又当字典键用，顺手截断
        比在下游各处防御便宜。
        """
        if ws is None:
            return self.WS_DEFAULT
        wid = str(ws).strip()[:16]
        return wid or self.WS_DEFAULT

    def _ws_cur(self):
        """当前线程正在为哪个工作区执行命令（线程局部；无则默认工作区）。

        `_push_console` / `_push_cmd` / `_sync_stop_state` 都靠它定位：命令执行
        链路上几十处播报因此不必逐个加参数，也就不会漏掉某处而把工作区 2 的
        输出写进工作区 1。
        """
        return getattr(self._ws_tls, "ws", None) or self.WS_DEFAULT

    def _ws_set_cur(self, ws):
        wid = self._ws_id(ws)
        self._ws_tls.ws = wid
        return wid

    def _ws_clear_cur(self):
        self._ws_tls.ws = None

    def _ws_label(self, ws=None):
        """状态栏前缀：默认工作区返回空串（单工作区时代文案完全不变）。

        顶栏跑马灯是**全局唯一**的流水账：两个工作区同时跑命令时，「✓ 完成」
        「──── 设备: A1 ────」会混成一片，用户看不出是谁的 —— 而「哪条命令
        跑完了」正是他此刻要判断的事。
        """
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
            # 持锁建：用户连点两下「执行」时，两条线程会同时走到这里，不加锁
            # 就各建一条 powershell，后写的那条把前一条从字典里挤掉 —— 泄漏一个
            # 常驻子进程，且它的输出还在往这个工作区推（关闭工作区也杀不掉它）。
            with self._ws_guard:
                sess = self._ws_sessions.get(wid)
                if sess is None and not self.state.shutting_down:
                    # 回调里绑定建会话时的 wid：读线程不是执行线程，线程局部取不到
                    sess = self._session_factory(
                        output_callback=lambda text, w=wid:
                            self._on_session_output(text, w),
                        on_dir_change=lambda path, w=wid:
                            self._on_session_dir_change(path, w))
                    self._ws_sessions[wid] = sess
        return sess

    def _ws_lock(self, ws=None):
        wid = self._ws_id(ws)
        if wid == self.WS_DEFAULT:
            return self._user_lock
        lk = self._ws_locks.get(wid)
        if lk is None:
            lk = threading.Lock()
            self._ws_locks[wid] = lk
        return lk

    def _ws_interactive(self, wid):
        return bool(getattr(self._ws_sessions.get(wid), "in_interactive_shell", False))

    def _ws_publish_stop(self, wid):
        """广播某工作区的「停止」按钮态（仅在翻转时推一条）。

        非默认工作区的 busy = 有命令在跑 or 处于交互式子 shell：后者下命令已经
        跑完了，但用户必须还能点「停止」把那个子 shell 杀掉，否则会话永久卡在
        直通态。
        """
        busy = bool(self._ws_busy.get(wid)) or self._ws_interactive(wid)
        if busy != self._ws_stop_flag.get(wid, False):
            self._ws_stop_flag[wid] = busy
            self.bus.push("stop_state", {"running": busy, "ws": wid})
        return busy

    def _ws_begin(self, ws=None):
        """工作区开始执行一条命令。返回 (busy, changed)。

        非默认工作区返回 changed=False：广播已在本方法内完成，调用方别再推一遍
        （重复推同值事件只会让前端多做一次无意义的按钮态刷新）。
        """
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
        """登记一个工作区（前端新建子 tab / 改名时调用）。

        只登记名字与上限校验，**不预建会话**：开 8 个 tab 就拉起 8 个 powershell
        是纯粹的浪费，多数工作区开出来只是摆着。会话在第一次真正执行时才建。
        """
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
        """关闭工作区：杀掉它的会话并清掉全部运行态。

        调用方（前端）会先 stop_run(ws) 再调本方法；即便此刻还有命令在跑，kill
        也会让它的 run() 立刻返回 False，线程随即退出 —— 不会留下一个「界面上
        已经没有这个 tab，却还在往里写输出」的幽灵会话。
        """
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
        """ShellSession 标准输出回调 -> 指令台 out 事件。

        ws 为默认工作区时**不带**该字段：单工作区时代的载荷一字不差，前端与
        既有测试都按 p.ws || "w1" 兜底。
        """
        payload = {"kind": "out", "text": text}
        wid = self._ws_id(ws)
        if wid != self.WS_DEFAULT:
            payload["ws"] = wid
        self.bus.push("console", payload)

    def _on_session_dir_change(self, path, ws=None):
        """ShellSession 工作目录变化回调 -> prompt 事件。

        前端 cmd-prompt span 实时更新成新路径，就像 PowerShell 那样。
        默认工作区不带 ws 字段（兼容老前端）。
        """
        payload = {"kind": "prompt", "cwd": path}
        wid = self._ws_id(ws)
        if wid != self.WS_DEFAULT:
            payload["ws"] = wid
        self.bus.push("console", payload)

    def _push_status(self, type_, text, toast=False, alert=False, alert_title=""):
        """下发一条状态。toast=True 时前端会额外弹 toast 强提醒（高优先级提示语）。

        默认 toast=False：绝大多数状态只写到底部状态栏日志；仅错误级（err）
        与显式 toast 标记的提示才会触发前端弹窗（见 frontend/js/app.js pushStatus）。

        alert=True 再多走一层：前端弹一个**必须手动关闭**的告警弹窗（showAlert）。
        toast 几秒后自己就没了，而「本次产物可能已经残缺」这种事必须挡在人面前，
        让他亲手关掉才算看见（实况：日志少了 24 分钟，收尾只弹过会消失的 toast，
        用户直到事后对时间轴才发现）。
        """
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
        """关键告警：状态栏 + toast + 不点不消失的弹窗。

        只用在「产物已经残缺、但流程本身没失败」的情形 —— 录屏配套日志跟不上
        视频、抓取文件带时间缺口这类。普通错误（截图失败、命令未找到）继续走
        _push_toast：那些当场就有结论，不需要用户再确认一次。
        """
        self._push_status(type_, text, toast=True, alert=True, alert_title=title)

    def _ws_status(self, type_, text, toast=False):
        """命令执行流程里的状态播报：多工作区时带上工作区名做前缀。

        只用于「某条命令跑得怎么样」这类播报。工具类（截图 / 录屏 / 抓包）的
        状态没有归属工作区，照旧走 _push_status。
        """
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
        """读使用说明文本（README 风格、随 exe 内置副本，不再以独立文件随包分发）。

        关于页的「使用说明」子 tab 直接渲染这里返回的内容，避免再维护一份
        与仓库 使用说明.txt 脱节的硬编码文案。路径优先 exe 同目录那份、
        否则回退到 PyInstaller 解包副本（resource_path 统一处理）。
        """
        try:
            path = resource_path("使用说明.txt")
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except Exception as ex:  # noqa: BLE001 — 兜底给前端一个可读错误，不抛异常卡住桥接
            return {"ok": False, "reason": "使用说明读取失败：%s" % ex}
        return {"ok": True, "text": text}
