# -*- coding: utf-8 -*-
"""
backend.controller —— pywebview js_api 统一动作入口（薄 API 桥）
================================================================
职责只做「转发 + 编排」：
  * 状态            -> backend.state.AppState（集中状态管理）
  * 后台线程        -> backend.workers.Workers（去重 / 记档 / 关闭）
  * 设备列表        -> backend.device_service.DeviceManager（快照 + 刷新）
  * 命令会话        -> core.shell.ShellSession（持久 PowerShell）
  * 前端通知        -> backend.bus.BackendBus（push / take 事件队列）

pywebview 会把本类实例暴露为 window.pywebview.api，前端通过
  * api.boot()            窗口就绪后一次性初始化（命令加载 / 会话 / 自动轮询）
  * api.take_events()     轮询拉取事件增量（模拟 Tk 版 _poll_queue 语义）
  * 其它动作方法          直接返回同步结果，耗时操作一律交给后台线程
完成双向通信。本模块不 import webview，可被单测直接构造（session 可注入假件）。
"""
import os
import sys
import re
import time
import json
import uuid
import threading
import subprocess
import zipfile
import itertools
import datetime
import tempfile

from core.constants import (
    VERSION, AUTO_REFRESH_MS, REC_DEATH_CHECK_S, adb_kwargs, safe_name, program_dir,
)
from core.commands import load_commands, save_click_deltas, save_user_commands, merge_builtins
from core.prefs import (load_prefs, load_prefs_checked, save_prefs,
                         apply_adb_dir, get_pref, prefs_path,
                         resolve_save_dir)
from core import clipboard
from core import tmpfiles
from core.rootguard import root_intent, device_is_root
from core.shell import ShellSession
from core import wireless as wifi
from core import apk as apkinfo
from core import devinfo
from core import diag
from core import update as updater
from adb_inject import (
    transform, needs_device,
    merge_adb_shell_commands_detailed,
    SHELL_INTERACTIVE_RE,
    is_subshell_command,
)
from backend.bus import BackendBus
from backend.state import AppState
from backend.workers import Workers
from backend.device_service import DeviceManager
from backend.logcat_service import LogcatMonitor, LogcatCapture
from backend.screen_service import (
    ScreenCapturer, VideoRecorder, KEY_POINTER_LOCATION, KEY_SHOW_TOUCHES,
)
from backend.audio_service import (
    MicRecorder, DeviceAudioCapture, ffmpeg_mux, _have_ffmpeg,
)
from backend.file_service import FileService
from backend.scrcpy_service import ScrcpyLauncher, find_scrcpy, probe as scrcpy_probe_info
from backend.mirror_service import (
    PipeMirror, SnapMirror, FrameServer, find_player, probe_player, plan_size,
)
from backend.perf_service import (
    PerfMonitor, DEFAULT_INTERVAL, MAX_INTERVAL as PERF_MAX_INTERVAL,
    MIN_INTERVAL as PERF_MIN_INTERVAL, DEFAULT_THRESHOLDS,
    threshold_rule_text as perf_rule_text, write_report as perf_write_report,
    write_compare_report as perf_write_compare,
    parse_thresholds as perf_parse_thresholds,
    build_thresholds as perf_build_thresholds,
    format_thresholds as perf_format_thresholds,
    default_threshold_expr as perf_default_threshold_expr,
    threshold_items as perf_threshold_items, ALERT_CRIT_RATIO as PERF_CRIT_RATIO,
    pkg_display as perf_pkg_display, list_packages as perf_list_installed,
)

# 默认性能阈值随控制器一起暴露（`ctrl.PERF_THRESHOLDS`）：前端「阈值」页与
# 测试都按这个名字读，属于有意对外的常量，不是顺手留下的无用导入。
PERF_THRESHOLDS = DEFAULT_THRESHOLDS

# 同时监控的设备数上限。每台一条采样线程、每 tick 一次 adb shell；超过这个数
# 后新增设备只是在 adb 的调用队列里排队，采样间隔会被拉长、曲线出现假台阶。
PERF_MAX_DEVICES = 4
# 已安装应用列表的缓存时长（秒）：够点几次下拉框都命中，又不会在装/卸应用后
# 一直拿着旧列表（真要立刻刷新，下拉框里有「刷新」按钮）。
PERF_PKG_CACHE_S = 120

# 退出交互式子 shell 的命令（`exit` / `exit 1`，PowerShell 与 sh 都认）。
# 命中后要把会话的直通态复位，否则后续命令再也拿不到输出边界。
_EXIT_RE = re.compile(r"^exit(?:\s+-?\d+)?$", re.IGNORECASE)

# 「打开下载页」允许的主机：只放开 GitHub 自家的下载域名。
# 这个白名单存在的意义不是防用户（用户点的是自己程序给的链接），而是防
# **更新源被换掉之后** 有人拿一条 http://随便什么域名/b.exe 的响应，让程序
# 直接给用户打开一个可执行文件下载——那等于把「装什么」的决定权交出去了。
# 内网自建更新源另有出口：`update_feed` 的主机会自动加入白名单（见 update_open）。
_UPDATE_HOSTS = (
    "github.com", "api.github.com", "codeload.github.com",
    "objects.githubusercontent.com", "raw.githubusercontent.com",
    "github-releases.githubusercontent.com",
)


def _host_allowed(url: str, extra=()) -> bool:
    """URL 是否为 http(s) 且主机在白名单（或 extra）内。"""
    from urllib.parse import urlparse
    try:
        p = urlparse(url or "")
    except Exception:
        return False
    if p.scheme not in ("http", "https"):
        return False
    host = (p.hostname or "").lower()
    if not host:
        return False
    for h in tuple(_UPDATE_HOSTS) + tuple(extra):
        h = (h or "").lower().strip()
        if h and (host == h or host.endswith("." + h)):
            return True
    return False


class WebApi:
    """pywebview js_api：前端 window.pywebview.api.<method> 的调用面。

    所有可能阻塞的方法（设备刷新 / 命令执行）都在后台线程运行，
    主调用线程只做登记与立即返回，结果经 bus 事件异步送达前端。
    """

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
        # 截图请求序号：每次截图用独立 worker key（见 screenshot），
        # 否则同一设备连点两次会被同名去重静默吞掉一次。
        self._shot_seq = itertools.count(1)
        # 批量截图汇总：多设备一次点击各起一个 worker，全部到齐后弹一条
        # 汇总 toast（见 screenshot / _shot_batch_done）。
        self._shot_batch_lock = threading.Lock()
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

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
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
                output_callback=self._on_session_output)
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
        with self._perf_lock:
            mons, self._perfs = list(self._perfs.values()), {}
        for mon in mons:
            try:
                mon.stop()
            except Exception:
                pass
        return {"ok": True}

    # ------------------------------------------------------------------
    # 事件桥（前端轮询拉取）
    # ------------------------------------------------------------------
    # 单次最多取 2000 条事件、且其中日志行合计不超过 2000 行。
    # 行限流是必须的：logcat 启动瞬间一个 append 就带几百行，只按条数限流
    # 会让单次返回达到几十万行，JSON 传输 + 前端解析足以让界面失去响应。
    def take_events(self):
        return self.bus.take(max_n=2000, max_lines=2000)

    # ------------------------------------------------------------------
    # 内部：事件推送
    # ------------------------------------------------------------------
    def _on_session_output(self, text):
        """ShellSession 标准输出回调 -> 指令台 out 事件。"""
        self.bus.push("console", {"kind": "out", "text": text})

    def _push_status(self, type_, text, toast=False):
        """下发一条状态。toast=True 时前端会额外弹 toast 强提醒（高优先级提示语）。

        默认 toast=False：绝大多数状态只写到底部状态栏日志；仅错误级（err）
        与显式 toast 标记的提示才会触发前端弹窗（见 frontend/js/app.js pushStatus）。
        """
        self.bus.push("status", {
            "type": type_, "text": text, "toast": bool(toast)})

    def _push_toast(self, type_, text):
        """高优先级提示语：状态栏照常记录，同时强制前端弹 toast。"""
        self._push_status(type_, text, toast=True)

    def _push_console(self, kind, text):
        self.bus.push("console", {"kind": kind, "text": text})

    def _push_cmd(self, text):
        """CMD 风格命令回显：`<当前路径> 命令`。"""
        path = (getattr(self.session, "current_dir", None) or "").strip()
        self._push_console("cmd", "%s> %s" % (path or "PS", text))

    def _sync_stop_state(self, interactive=None):
        """把 busy 变化广播给前端（stop 按钮态），只在翻转时推一次。"""
        if interactive is None:
            interactive = bool(
                getattr(self.session, "in_interactive_shell", False))
        busy, changed = self.state.sync_stop(interactive)
        if changed:
            self.bus.push("stop_state", {"running": busy})
        return busy

    # ------------------------------------------------------------------
    # 快捷指令点击计数（防抖写回 commands.json）
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # 设备
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # 指令执行
    # ------------------------------------------------------------------
    def run_command(self, cmd_id):
        """下发一条快捷指令（可多设备循环，线程内执行）。"""
        if self.state.shutting_down:
            return {"ok": False}
        cmd_obj = next(
            (c for c in self.state.commands if c.get("id") == cmd_id), None)
        if cmd_obj is None:
            self._push_status("err", "⚠ 未找到命令：%s" % cmd_id)
            return {"ok": False}
        if self.session is None:
            self._push_status("err", "⚠ 会话尚未初始化，请稍后重试。")
            return {"ok": False}
        # 命中一次计一次使用频次（驱动「常用命令靠前」排序）
        self._bump_click(cmd_id)
        self.workers.spawn(None, self._execute, cmd_obj)
        return {"ok": True}

    def save_commands(self, commands):
        """前端维护的命令（界面增删改后）整体回写 commands.json。

        commands 已是归一化结构（仅用户自定义命令；前端已过滤掉内置默认）。
        后端只负责原子写回与内存态同步（state.commands），不重新归一化——
        前端持有的就是界面真实展示的命令，直接写回能完整保留 clickCount，
        避免下次启动「常用命令靠前」排序被重置。失败回 err 状态并 ok=False。
        """
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        ok, err = save_user_commands(commands)
        if not ok:
            self._push_status("err", "⚠ 保存命令失败：%s" % err)
            return {"ok": False, "reason": err}
        # 同步内存态：用户命令并入内置默认，保持与 boot 后一致，使后续
        # run_command / 点击计数基于最新列表（state.commands 是 run_command 的来源）。
        user_cmds = []
        for c in (commands or []):
            if isinstance(c, dict):
                c = dict(c)
                c.pop("builtin", None)
                user_cmds.append(c)
        self.state.commands = merge_builtins(user_cmds)
        self._push_status("ok", "✓ 命令已保存（%d 条）" % len(commands))
        return {"ok": True}

    def export_commands(self):
        """导出用户自定义命令（界面维护的命令，已过滤内置默认），供备份 / 分享。

        返回归一化结构（与 import_commands 互为逆操作）：仅用户命令，
        含 id / name / labels / commands / clickCount / inputOnly。
        """
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        user_cmds = []
        for c in (self.state.commands or []):
            d = c if isinstance(c, dict) else vars(c)
            if d.get("builtin"):
                continue
            user_cmds.append({
                "id": d.get("id"),
                "name": d.get("name"),
                "labels": d.get("labels") or ["其他"],
                "commands": d.get("commands") or [],
                "clickCount": d.get("clickCount") or 0,
                "inputOnly": bool(d.get("inputOnly")),
            })
        return {"ok": True, "commands": user_cmds, "count": len(user_cmds)}

    def export_commands_save(self):
        """把导出的命令写入「程序运行处」目录并返回本地路径（前端可 open_local_file）。

        默认落在程序所在目录（exe 旁 / 开发态项目根），用户不指定路径时
        即可在程序同目录找到备份文件；该目录不可写时回退系统临时目录。
        """
        data = self.export_commands()
        if not data.get("ok"):
            return data
        text = json.dumps(data["commands"], ensure_ascii=False, indent=2)
        out_dir = program_dir()
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception:
            out_dir = tempfile.gettempdir()
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(out_dir, "commands_export_%s.json" % ts)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception as e:
            return {"ok": False, "reason": "写入失败：%s" % e}
        return {"ok": True, "path": path}

    def _dialog_types(self, pairs):
        """把 ((描述, 通配符), ...) 转成当前 pywebview 版本接受的 file_types。

        pywebview 在 5.x 之前 / 之后改了 file_types 格式：

        * 旧版(<5)：期望 ``(('描述', '*.ext'), ...)`` 这样的元组；
        * 新版(>=5)：期望 ``('描述 (*.ext)', ...)`` 这样的字符串，内部用
          ``re.search`` 解析。

        若按旧版元组传给新版，``parse_file_type`` 会对「元组」做正则匹配，
        抛出 ``TypeError: expected string or bytes-like object`` —— 正是
        Windows 下导入报错的根因。这里运行时探测一次，生成正确格式。
        """
        pairs = tuple(pairs)
        try:
            from webview.util import parse_file_type
        except Exception:
            # 拿不到探测函数时，回退到兼容性最好的「字符串格式」
            return tuple("%s (%s)" % (desc, ext) for desc, ext in pairs)
        # 探测新版字符串格式是否可用：能解析字符串就说明是新版
        try:
            parse_file_type("探测 (*.json)")
        except Exception:
            # 解析失败 -> 旧版，用元组格式
            return pairs
        # 新版：拼成 '描述 (*.ext)' 字符串
        return tuple("%s (%s)" % (desc, ext) for desc, ext in pairs)

    def _make_file_types(self):
        """命令导入用的 file_types（JSON / 所有文件）。"""
        return self._dialog_types((("JSON 命令备份", "*.json"),
                                  ("所有文件", "*.*")))

    def _open_dialog(self, pairs, label=""):
        """弹原生「打开文件」对话框，返回选中文件路径；取消 / 不可用返回空串。

        统一收口各版本的 create_file_dialog 签名差异与取消语义，调用方只需
        判断返回是否为空。
        """
        try:
            import webview
        except Exception as e:
            self._push_status("warn", "⚠ 当前环境不支持原生文件对话框：%s" % e)
            return ""
        win = getattr(self, "window", None)
        try:
            if win is None and hasattr(webview, "active_window"):
                win = webview.active_window()
        except Exception:
            win = None
        if win is None or not hasattr(win, "create_file_dialog"):
            self._push_status("warn", "⚠ 当前环境不支持原生文件对话框")
            return ""
        ft = self._dialog_types(pairs)
        directory = str(program_dir())
        try:
            files = win.create_file_dialog(
                webview.OPEN_DIALOG, directory=directory,
                allow_multiple=False, file_types=ft)
        except TypeError:
            # 不同版本签名略有差异，做一次位置参数兜底
            try:
                files = win.create_file_dialog(
                    webview.OPEN_DIALOG, directory, False, None, ft)
            except TypeError:
                files = win.create_file_dialog(
                    webview.OPEN_DIALOG, directory, False)
        except Exception as e:
            self._push_status("warn", "⚠ 打开文件对话框失败：%s" % e)
            return ""
        if not files:
            return ""
        return files[0] if isinstance(files, (list, tuple)) else str(files)

    def import_commands_dialog(self):
        """弹出原生文件选择框（默认定位到程序目录），读取 JSON 并导入合并。

        与 import_commands 互为顺操作：对话框返回选中文件 -> 读取内容 ->
        交给 import_commands 按 id 合并（已存在覆盖、不存在新增）。取消选择
        时返回 reason="cancelled"，调用方可据此静默忽略。
        """
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        try:
            import webview
            # 新版 pywebview 已移除模块级 create_file_dialog，必须走窗口实例。
            # pywebview 会在创建窗口时把 api.window 注入到本对象；此处优先用
            # self.window，再回退到 active_window()，保证跨版本可用。
            win = getattr(self, "window", None)
            if win is None and hasattr(webview, "active_window"):
                win = webview.active_window()
            if win is None or not hasattr(win, "create_file_dialog"):
                return {"ok": False, "reason": "当前环境不支持原生文件对话框"}
            ft = self._make_file_types()
            directory = str(program_dir())  # WinForms 后端要求字符串，确保非 Path
            try:
                files = win.create_file_dialog(
                    webview.OPEN_DIALOG,
                    directory=directory,
                    allow_multiple=False,
                    file_types=ft,
                )
            except TypeError:
                # 不同版本 create_file_dialog 签名略有差异，做一次位置参数兜底：
                # 先带过滤器用 5 参数签名，再退化为不带过滤器的 3 参数签名。
                try:
                    files = win.create_file_dialog(
                        webview.OPEN_DIALOG, directory, False, None, ft
                    )
                except TypeError:
                    files = win.create_file_dialog(
                        webview.OPEN_DIALOG, directory, False
                    )
        except Exception as e:
            return {"ok": False, "reason": "打开文件对话框失败：%s" % e}
        if not files:
            return {"ok": False, "reason": "cancelled"}
        path = files[0]
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception as e:
            return {"ok": False, "reason": "读取文件失败：%s" % e}
        return self.import_commands(text)

    def import_commands(self, payload):
        """导入命令（备份 / 分享文件）。payload 可为：
          * 列表：[{id,name,labels,commands,...}, ...]
          * 字典：{"commands": [...]}
          * 上述结构的 JSON 字符串
        按 id 合并：已存在则覆盖，不存在则新增（缺失 id 自动生成）。
        导入后整体回写 commands.json 并同步内存态。
        """
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception as e:
                return {"ok": False, "reason": "JSON 解析失败：%s" % e}
        if isinstance(payload, dict) and "commands" in payload:
            incoming = payload.get("commands") or []
        elif isinstance(payload, list):
            incoming = payload
        else:
            incoming = []
        incoming = [c for c in (incoming or []) if isinstance(c, dict)]
        if not incoming:
            return {"ok": False, "reason": "没有可导入的命令"}
        existing = {}
        for c in (self.state.commands or []):
            d = c if isinstance(c, dict) else vars(c)
            if d.get("builtin"):
                continue
            existing[d.get("id")] = d
        added = 0
        for c in incoming:
            cid = c.get("id")
            if not cid or cid not in existing:
                if not cid:
                    c = dict(c); c["id"] = "u_" + uuid.uuid4().hex[:10]
                added += 1
            existing[c.get("id")] = c
        merged = list(existing.values())
        ok, err = save_user_commands(merged)
        if not ok:
            return {"ok": False, "reason": err}
        user_cmds = []
        for c in merged:
            cc = c if isinstance(c, dict) else vars(c)
            cc = dict(cc); cc.pop("builtin", None)
            user_cmds.append(cc)
        self.state.commands = merge_builtins(user_cmds)
        self._push_status("ok", "✓ 已导入命令（新增 %d 条，共 %d 条用户命令）"
                          % (added, len(merged)))
        return {"ok": True, "added": added, "total": len(merged)}

    def load_commands(self):
        """返回当前完整命令列表（用户命令 + 内置默认，已 merge_builtins 归一化）。

        前端用于导入 / 外部改动后刷新界面（避免重启应用）。
        """
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        out = []
        for c in (self.state.commands or []):
            d = c if isinstance(c, dict) else vars(c)
            out.append(dict(d))
        return {"ok": True, "commands": out}

    def run_custom(self, text):
        """执行自定义命令：与快捷指令同源——按受控设备逐台循环并通过
        adb_inject.transform 自动注入 `-s <serial>`，彻底告别
        "more than one device/emulator"。纯 PC 脚本（不含 adb/scrcpy）
        走单次执行旁路。"""
        text = (text or "").strip()
        if not text:
            return {"ok": False}
        if self.session is None:
            self._push_status("err", "⚠ 会话尚未初始化，请稍后重试。")
            return {"ok": False}
        # 复用 _execute 的「按设备展开 + transform + shell 合并」完整链路
        self.workers.spawn(None, self._execute, {
            "id": "__custom__", "name": "自定义命令", "commands": [{"command": text}],
        })
        return {"ok": True}

    def stop_run(self):
        """终止当前命令（等价 Tk 版 ctrl+c / 停止）。"""
        if self.session is not None:
            self._push_status("err", "⏹ 已发送停止信号，正在终止当前命令…")
            try:
                self.session.kill()
            except Exception:
                pass
        else:
            self._push_status("warn", "当前没有正在运行的命令。")
        self._sync_stop_state(interactive=False)
        return {"ok": True}

    # ------------------------------------------------------------------
    # 内部：命令执行骨架（线程内运行）
    # ------------------------------------------------------------------
    def _execute(self, cmd_obj):
        """执行一条快捷指令：按需逐设备循环 + 每条命令带 delay。

        用户命令「单飞」：同一时刻只允许一条命令真正执行（_user_lock 排队），
        后续命令等上一条结束后再跑——避免连点多条时输出在指令台交错混淆；
        也保证 stop_run 的语义是「停掉当前这一条」。shutdown 后排队任务直接
        放弃，不再往已终止的会话里写命令。

        整体兜异常：命令下发链路（transform / 会话 / 设备快照）任何未预期错误
        都只转化为一条错误状态，绝不让 worker 线程裸抛到 threading.excepthook
        （那只会落一份崩溃日志，用户在界面上看不到任何反馈）。
        """
        with self._user_lock:
            if self.state.shutting_down:
                return
            busy, changed = self.state.begin_run()
            if changed:
                self.bus.push("stop_state", {"running": busy})
            try:
                try:
                    entries = cmd_obj.get("commands", [])
                    loop = needs_device(cmd_obj)
                    name = cmd_obj.get("name", "命令")
                    if loop:
                        serials = self.devices.selected_serials()
                        if not serials:
                            self._push_status(
                                "err", "⚠ 命令「%s」需要指定设备，请先在左侧勾选设备。" % name)
                            return
                        for serial in serials:
                            self._push_status("info", "──── 设备: %s ────" % serial)
                            if not self._run_entries(entries, serial):
                                break
                    else:
                        self._push_status(
                            "info", "──── 执行「%s」（无需指定设备）────" % name)
                        self._run_entries(entries, None)
                except Exception as ex:
                    self._push_status(
                        "err", "⚠ 命令执行出现异常：%s" % ex)
            finally:
                # 交互式 adb shell（`adb shell` 直通）结束后会话仍是交互态：此时
                # 「停止」按钮必须继续亮着，用户才能把这条交互会话 kill 掉。
                # AppState 的 busy 本就包含交互态，但没人通知它——这里在 end_run
                # 之前按会话实际状态同步一次（交互态下 busy 不变，不会重复广播；
                # 非交互命令照常由 end_run 熄灭按钮）。
                self._sync_stop_state()
                busy, changed = self.state.end_run()
                if changed:
                    self.bus.push("stop_state", {"running": busy})

    def _run_entries(self, entries, serial):
        """逐条下发命令；adb shell 交互 / 合并 / delay 与 legacy 语义一致。
        返回 False 表示执行被中断（超时/停止），上层据此停止后续设备。"""
        # shutdown() 会把 self.session 置空（杀完再清引用），而本方法跑在后台
        # worker 里：不检查就会踩 None 抛 AttributeError，被 _execute 的兜底
        # 翻译成一条「命令执行出现异常：'NoneType' object has no attribute …」——
        # 关窗瞬间用户看到一条毫无意义的报错。这里静默放弃即可。
        if self.session is None:
            return False
        raw_cmds = [e.get("command", "") for e in entries]
        if serial:
            raw_cmds = [transform(c, serial) for c in raw_cmds]
        merged = merge_adb_shell_commands_detailed(raw_cmds)
        timeout = self._cmd_timeout()
        for cmd, end_idx in merged:
            if not cmd.strip():
                continue
            # root / unroot 切换保护（见 _skip_root_switch）：已在目标状态、
            # 或该设备有进行中的录屏 / 抓取时，本条命令不下发。
            if self._skip_root_switch(cmd, serial):
                continue
            stripped = cmd.strip()
            was_interactive = bool(self.session.in_interactive_shell)
            # 交互式（直通）判定的三个来源：
            #   1. 已经在子 shell 里（上一轮 adb shell / powershell 的直通）；
            #   2. 裸 `adb shell`：后面几条已被 merge 合并，只剩单独一条时才直通；
            #   3. 裸 powershell / cmd / bash —— 这类命令没人合并，它在持久会话
            #      里另起一个进程抢走 stdin，后面每条的结束标记都被内层读走；
            #      `exit` 更是连标记一起丢掉再退出，外层永远等不到 → 死锁。
            interactive = (was_interactive
                           or bool(SHELL_INTERACTIVE_RE.match(stripped))
                           or is_subshell_command(stripped))
            self._push_cmd(cmd)
            if interactive and not was_interactive:
                # 推在指令台而不是顶栏：用户此刻盯着就是这块面板，而且「后续命令
                # 去哪了」本身就是命令流的一部分，混进全局跑马灯很容易错过。
                self._push_console(
                    "info",
                    "» 已进入交互式 shell：后续命令直接送入该子 shell，"
                    "输入 exit 可退出并恢复逐条执行")
            if interactive:
                ok = self.session.run(cmd, interactive=True)
                if ok and _EXIT_RE.match(stripped):
                    # `exit` 退出的是内层子 shell，外层会话仍然活着。不复位
                    # 直通态的话，之后每条命令都只能"盲写"（不写结束标记、
                    # 无法判断成败），等于把会话永久降级。
                    self.session.leave_interactive()
                    # 子进程退出是异步生效的：紧接着写的命令有概率仍被投递给
                    # 正在退出的那个 shell，留一点间隔再继续。
                    self._interruptible_sleep(0.15)
                    self._push_console("info", "« 已退出交互式子 shell，恢复逐条执行")
            else:
                # 兜底超时：没有它，任何一条"哑"命令（读 stdin 的工具、卡住的
                # adb）都会永久占用 _user_lock，后续命令全部排队 —— 界面表现
                # 就是「整程序卡死、点不动」。超时由 run() 内部杀会话并返回 False。
                ok = self.session.run(cmd, timeout=timeout)
            if not ok:
                self._push_status("info", "✗ 执行中断")
                return False
            delay = 0
            if not interactive and 0 <= end_idx < len(entries):
                delay = int(entries[end_idx].get("delay", 0) or 0)
            if delay:
                # 旧实现把 Start-Sleep 塞进 powershell 会话：命令间 delay 超过
                # run(timeout=10) 会被误判超时杀掉整个会话，且占用 shell 影响
                # 并发命令。改为 Python 侧可打断 sleep（不占会话、可被停止）。
                self._interruptible_sleep(delay / 1000.0)
        self._push_status("info", "✓ 完成")
        return True

    # 单条非交互命令的兜底超时（秒）。config.json 的 cmd_timeout 可覆盖，
    # 0 表示不限制（自己知道某条命令要跑很久时才这么设）。
    DEFAULT_CMD_TIMEOUT = 120

    def _cmd_timeout(self):
        """本条序列里非交互命令的超时秒数；None 表示不限制。"""
        try:
            v = int(get_pref("cmd_timeout", self.DEFAULT_CMD_TIMEOUT))
        except (TypeError, ValueError):
            v = self.DEFAULT_CMD_TIMEOUT
        return v if v > 0 else None

    # ------------------------------------------------------------------
    # root / unroot 切换保护
    # ------------------------------------------------------------------
    def _skip_root_switch(self, cmd, serial):
        """本条命令是否应跳过（不下发）：root 状态切换的两种「跳过」情形。

        `adb root` / `adb unroot` 会重启设备端 adbd，杀掉经它拉起的
        screenrecord / tinycap（录屏视频缺 moov、不完整），并断开 logcat
        监控 / 抓取与文件操作。而重复切换（已在目标状态）除了重启没有任何
        效果——这是最常见的误伤：用户随手再点一次「root」，在录的屏就断了。
        因此下发前逐设备判断：

          1. 已在目标状态（要 root 的已 root / 要 unroot 的未 root）→ 跳过；
          2. 状态确实要变、但该设备有进行中的任务 → 跳过并说明，避免静默
             数据丢失（想切换请先停止录屏 / 抓取）。

        复合命令（`adb root && adb shell xx`）无法只跳过其中一段，整条跳过。
        返回 True 表示调用方应 `continue`（本条不下发，其 delay 一并跳过）。
        """
        intent = root_intent(cmd)
        if not intent:
            return False
        # 无序列号（纯 PC 旁路）不可能是设备 root 切换，直接放行
        if not serial:
            return False
        adb = self.state.adb_path or "adb"
        try:
            rooted = device_is_root(adb, serial)
        except Exception:
            rooted = False   # 探测失败按「需要切换」：交给下面的任务检查兜底
        # 已在目标状态：切换是零收益的无谓重启
        if (intent == "root") == bool(rooted):
            self._push_status(
                "info",
                "ℹ 设备 %s 已%s，跳过 `%s`（重复切换只会重启 adbd，"
                "可能中断进行中的录屏 / 抓取）"
                % (serial, "处于 root" if rooted else "未 root", cmd.strip()))
            return True
        # 状态确实要变：该设备有进行中的任务则跳过（任务会随 adbd 重启全断）
        busy = self._device_busy_tasks(serial)
        if busy:
            self._push_toast(
                "warn",
                "⚠ 设备 %s 正在%s：`%s` 会重启 adbd 并中断这些任务"
                "（录屏视频将不完整、日志抓取会断）。已跳过执行——"
                "请先停止录屏 / 抓取，再执行 root 状态切换。"
                % (serial, "、".join(busy), cmd.strip()))
            return True
        return False

    def _device_busy_tasks(self, serial):
        """该设备当前进行中、且会随 adbd 重启而中断的任务（中文名列表）。"""
        tasks = []
        try:
            if self.video.is_recording(serial):
                tasks.append("录屏")
            if self.device_audio.is_recording(serial):
                tasks.append("录制设备音频")
            if self.logcat_monitor.is_running(serial):
                tasks.append("logcat 监控")
            if self.logcat_capture.is_running(serial):
                tasks.append("logcat 抓取")
        except Exception:
            pass
        return tasks

    def _interruptible_sleep(self, seconds):
        """Python 侧延时等待，stop_run / 窗口关闭时提前返回。

        以 50ms 步长轮询而非一次性 sleep：kill 会让 ShellSession.aborted 置位，
        延时中的批处理能及时感知停止，关闭时也无需等满整个 delay。
        """
        sess = self.session
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self.state.shutting_down:
                return
            if sess is not None and getattr(sess, "aborted", False):
                return
            time.sleep(0.05)

    # ------------------------------------------------------------------
    # 自动轮询（防拔线 / 状态漂移的静默守护）
    # ------------------------------------------------------------------
    def _start_auto_refresh(self):
        if self._auto_started or self.state.shutting_down:
            return
        self._auto_started = True
        self.workers.spawn("auto_refresh", self._auto_loop)

    def _auto_loop(self):
        """每 AUTO_REFRESH_MS 静默刷一次；无变化不广播。

        采用 0.2s 小步 tick 而不是整段 sleep，保证 shutdown() 后能及时退出。
        另外按 REC_DEATH_CHECK_S 的步长检测「录屏进程意外死亡」（与设备刷新
        解耦：死亡时要尽快自动收尾，不能等下一个 5s 刷新周期）。
        """
        interval = AUTO_REFRESH_MS / 1000.0
        next_run = time.time() + interval
        next_death_check = time.time() + REC_DEATH_CHECK_S
        while not self.state.shutting_down:
            time.sleep(0.2)
            if self.state.shutting_down:
                break
            now = time.time()
            if now >= next_death_check:
                next_death_check = now + REC_DEATH_CHECK_S
                try:
                    self._reap_dead_recordings()
                except Exception:
                    pass
            if now < next_run:
                continue
            next_run = now + interval
            try:
                self.devices.refresh(self.state.adb_path, verbose=False)
            except Exception:
                pass
            # 设备被移除后，停掉它遗留的 logcat 监控 / 抓取（详见 _reap_gone_tools）
            try:
                self._reap_gone_tools()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 录屏进程意外死亡（adb root / 设备重启 adbd）的自动收尾
    # ------------------------------------------------------------------
    def _reap_dead_recordings(self):
        """发现「无人停止却退出」的录屏进程即派后台 worker 自动收尾。

        不处理的后果：界面永远停在「录制中」，用户以为还在录；点「停止」后
        还要经历最多约 10 秒的 pull 重试才看到「缺 moov 头」——而那一刻用户
        早就切到别的页签做别的事了。检测本身极轻（VideoRecorder 内的 watcher
        线程已标记，这里只是取标记），故可放在自动轮询线程里直接跑。
        """
        died = self.video.died_serials()
        if not died:
            return
        self.workers.spawn(
            "rec-reap-dead", self._teardown_dead_recordings, died)

    def _teardown_dead_recordings(self, serials):
        """（后台 worker）收尾意外死亡的录屏：与手动停止同一条完整路径。

        只收尾「仍在当前会话里」的设备；会话已被其他路径（用户点停止 /
        设备移除强停）结束掉时直接返回。残片视频不合成音频、源文件保留在
        保存目录；其余仍在录的设备会被优雅停掉并一并合成/打包。
        """
        with self._rec_lock:
            sess = self._rec_session
            if not sess:
                return
            dead = {s for s in serials if s in (sess.get("videos") or {})}
            if not dead:
                return
            # 记下死亡设备，供 _session_teardown 把失败文案从「收尾失败」
            # 换成更准确的「被意外中断（视频不完整）」。
            sess["dead"] = set(sess.get("dead") or set()) | set(dead)
        self._push_toast(
            "warn",
            "⚠ 检测到录屏进程意外结束（%s）——常见原因是录屏期间执行了 adb root "
            "或设备重启了 adbd。正在自动收尾并复位界面…" % "、".join(sorted(dead)))
        # 完整收尾：停掉其余设备 / 麦 / 设备音频、恢复指针位置/触摸圆点、合成与打包
        # 照常进行（异常由 _screen_record_stop_locked 兜底并清会话）。
        self.screen_record_stop()
        # 前端复位：会话已结束，把「停止」按钮切回「开始录制」。没有这条广播，
        # 界面会一直显示「录制中」（后端停了、前端不知道）。
        self.bus.push("rec_state", {"running": False, "reason": "died"})

    def _reap_gone_tools(self):
        """设备被移除（gone）后，停掉它正在进行的 logcat 监控 / 抓取，以及录屏会话里
        该设备的视频 / 设备音频。

        设备突然断开时 `adb logcat` 通常会退出（stdout EOF，worker 自行收尾推送
        stopped），但无线 / 网络 ADB 或 adb 卡顿时它可能迟迟不退出，留下孤儿 adb
        进程且界面卡在「监控中」。录屏同理：设备端 `screenrecord` / `tinycap` 在 adb
        断开后未必随退出，会残留进程、占用音频输入，且界面停留「录制中」直到用户手动
        点停止（那时 pull 必然失败）。这里以设备快照为权威：凡正在监控 / 抓取 / 录制、
        却已不在设备列表里的 serial 一律强停。处于宽限（短暂失联、仍保留勾选）的设备
        不会被误杀——它们仍留在 device_state 中。
        """
        try:
            known = {d["serial"] for d in self.devices.get_items()}
        except Exception:
            return
        for s in self.logcat_monitor.running_serials():
            if s not in known:
                self.logcat_monitor.stop(s)
        for s in self.logcat_capture.running_serials():
            if s not in known:
                self.logcat_capture.stop(s, zip_on_stop=False)
        # 录屏会话（多设备聚合）：只强停「已移除」的那几台，绝不替用户结束整个会话
        # （其余设备可能仍在正常录制）。停止涉及 adb 调用，设备离线时可能短暂阻塞，
        # 故放到后台 worker，不堵自动轮询线程。
        with self._rec_lock:
            sess = self._rec_session or {}
            rec_gone = [s for s in list(sess.get("videos", {}).keys())
                        + list(sess.get("devaudio", {}).keys())
                        if s not in known]
        if rec_gone:
            self.workers.spawn(
                "rec-reap", self._reap_gone_recording, set(rec_gone))

    def _reap_gone_recording(self, gone_set):
        """后台强停已移除设备的视频 / 设备音频（务必在 rec-reap worker 内调用）。

        被移除设备的录屏 / tinycap 在设备端未必自动退出：强停可释放其占用的音频输入，
        并避免界面一直停留「录制中」。不改动会话其余部分——其余设备照常录，用户对
        仍在录的设备点「停止」时，本处已停止的设备会被判定为「未录制」而安全跳过。

        两处 stop 在未录制时都直接返回（不发 adb、幂等），故无需先 is_recording 判断；
        DeviceAudioCapture 本就没有 is_recording 方法。
        """
        for s in gone_set:
            try:
                self.video.stop(s)
            except Exception:
                pass
            try:
                self.device_audio.stop(s)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 输出区操作
    # ------------------------------------------------------------------
    def clear_output(self):
        self.bus.push("console", {"kind": "clear"})
        return {"ok": True}

    def clear_status(self):
        self.bus.push("status", {"type": "clear"})
        return {"ok": True}

    # ==================================================================
    # Logcat 监控（实时渲染）
    # ==================================================================
    def logcat_start(self, serial, buffers, level_filter=None,
                     keyword="", only_exc=False):
        """对单台设备启动实时 logcat 监控。buffers 为缓冲区名列表。"""
        if not serial:
            return {"ok": False, "reason": "no_device"}
        ok = self.logcat_monitor.start(
            serial, buffers, level_filter=level_filter,
            keyword=keyword or "", only_exc=bool(only_exc))
        if not ok:
            return {"ok": False, "reason": "already_running"}
        self._push_status("info", "开始监控 logcat: %s" % serial)
        return {"ok": True}

    def logcat_stop(self, serial):
        if not serial:
            return {"ok": False, "reason": "no_device"}
        self.logcat_monitor.stop(serial)
        return {"ok": True}

    def logcat_clear(self, serial):
        self.bus.push("logcat", {"serial": serial, "status": "clear"})
        return {"ok": True}

    # ==================================================================
    # Logcat 抓取（落盘 txt / zip）
    # ==================================================================
    def logcat_capture_start(self, serial, save_dir, buffers, level_filter=None):
        if not serial:
            return {"ok": False, "reason": "no_device"}
        # 与截图/录屏/录音保持一致：未指定目录时回退到默认保存目录，
        # 避免 save_dir 为 None 时 os.makedirs(None) 抛 TypeError 直接失败。
        save_dir = save_dir or self._default_save_dir()
        try:
            os.makedirs(save_dir, exist_ok=True)
        except Exception as e:
            return {"ok": False, "reason": "mkdir", "text": str(e)}
        ts = time.strftime("%Y%m%d_%H%M%S")
        # safe_name：无线 ADB 序列号（IP:端口）含冒号，Windows 下文件名非法
        path = os.path.join(
            save_dir, "logcat_%s_%s.txt" % (safe_name(serial), ts))
        ok = self.logcat_capture.start(serial, path, buffers,
                                       level_filter=level_filter)
        if not ok:
            return {"ok": False, "reason": "already_running"}
        self._push_status("info", "开始抓取 logcat: %s -> %s%s"
                          % (serial, path, self._level_filter_desc(level_filter)))
        return {"ok": True, "path": path}

    @staticmethod
    def _level_filter_desc(level_filter):
        """级别过滤的人类可读后缀（全级别 / 未过滤时返回空串，不刷屏）。"""
        if level_filter is None:
            return ""
        picked = [x for x in ("V", "D", "I", "W", "E", "F")
                  if x in set(level_filter)]
        if len(picked) == 6:
            return ""
        if not picked:
            return "（级别: 无 — 不会写入任何日志行）"
        return "（级别: %s）" % "/".join(picked)

    def logcat_capture_stop(self, serial, zip_on_stop=True):
        if not serial:
            return {"ok": False, "reason": "no_device"}
        self.logcat_capture.stop(serial, zip_on_stop=zip_on_stop)
        return {"ok": True}

    # ==================================================================
    # 工具：截图 / 录屏 / 录音
    # ==================================================================
    def _default_save_dir(self):
        """本机实际生效的保存目录。

        优先用 config.json 的 save_dir（用户偏好，跨会话记住）；但该路径是
        绝对路径，配置被拷到另一台电脑后通常在本机并不存在——此时改用默认
        目录（见 core.prefs.resolve_save_dir），绝不让程序往一个不存在的
        路径里写文件。**不回写配置文件**：文件里的原值在源机器上仍然正确。
        """
        # 不建目录：这里读的是「配置里带来的路径」，若它在本机不存在，
        # 多半是从别的电脑同步过来的失效路径（父目录都不在了），
        # 建不出来也不该建 —— 交由 resolve_save_dir 回退默认目录。
        eff, _note = resolve_save_dir(load_prefs())
        return eff

    def default_save_dir(self):
        """把默认保存目录透出给前端（截图/录屏/下载共用同一份定义）。

        浏览器里没有环境变量，前端无法自行推导用户目录，也不该复制一份公式
        （两份必然漂移）。故由后端作为单一数据源提供，前端仅负责回填输入框。
        """
        return {"ok": True, "dir": self._default_save_dir()}

    # ---- 用户配置（config.json：保存目录 / adb 路径 / 全部开关）----
    def save_settings(self, patch):
        """合并保存用户偏好；adb_dir 变更即时生效（前插到进程 PATH）。

        由前端在各偏好控件的 change / 保存时调用；返回合并后的完整设置。
        保存目录改这里后，default_save_dir / 各录制下载默认目录立即生效。
        """
        if not isinstance(patch, dict) or not patch:
            return {"ok": False, "reason": "empty_patch"}
        merged = save_prefs(patch)
        if "adb_dir" in patch:
            apply_adb_dir(merged.get("adb_dir"))
            # 配置变更后立即回测一次，供前端即时更新关于页 / 引导文案
            merged["_adb_ok"] = self._probe_adb()["ok"]
        # 保存目录改动后立刻回报「本机实际生效的目录」：用户填了一个本机
        # 不存在的路径时，界面要马上说清已改用默认目录，而不是等下一次
        # 截图失败才发现（配置文件里的原值保持不动）。
        if "save_dir" in patch:
            # ensure_dir=True：用户在本机新填的路径本就不存在，这是正常
            # 流程 —— 顺手建出来（与旧行为一致：回退目录会被自动创建）。
            eff, note = resolve_save_dir(merged, ensure_dir=True)
            merged["_save_dir_effective"] = eff
            merged["_save_dir_note"] = note
        return {"ok": True, "settings": merged}

    def config_info(self):
        """配置文件信息（关于页展示用）。

        返回 {path, exists, save_dir, save_dir_effective, note}：
          * path —— config.json 的绝对路径，用户拷走它即可在别的电脑同步；
          * exists —— 文件是否已存在（首次运行时尚未生成）；
          * save_dir —— 配置文件里记录的原值（可能是别的电脑的路径）；
          * save_dir_effective —— 本机实际生效的目录（原值不可用时的回退结果）；
          * note —— 回退提示文案（一切正常时为 None）。
        """
        settings = load_prefs()
        eff, note = resolve_save_dir(settings)
        p = prefs_path()
        return {
            "ok": True,
            "path": p,
            "exists": os.path.exists(p),
            "save_dir": settings.get("save_dir", ""),
            "save_dir_effective": eff,
            "note": note,
        }

    def adb_status(self):
        """adb 可用性（路径 / 版本），about 页配置后即时刷新用。"""
        info = self._probe_adb()
        return {"ok": info["ok"], "path": info["path"],
                "version": info["version"]}

    def _probe_adb(self):
        """探测当前 adb 是否可用，返回 {ok, path, version}。"""
        path = getattr(self.state, "adb_path", "") or "adb"
        try:
            r = subprocess.run([path, "version"], **adb_kwargs(8))
            if r.returncode == 0:
                lines = [ln.strip() for ln in (r.stdout or "").splitlines()
                         if ln.strip()]
                ver = next(
                    (ln for ln in lines if ln.lower().startswith("version")),
                    lines[0] if lines else "adb version")
                return {"ok": True, "path": path, "version": ver}
        except Exception:
            pass
        return {"ok": False, "path": path, "version": ""}

    def _prewarm_adb_server(self):
        """启动后台拉起 adb server（幂等）。失败静默——它不是关键路径。

        server 冷启一次要数百 ms，由「启动后第一次截图」承担这笔钱会很莫名；
        在 boot 的后台线程里提前拉起来，用户点截图时它一定已在。
        """
        try:
            subprocess.run(
                [getattr(self.state, "adb_path", "") or "adb", "start-server"],
                **adb_kwargs(10))
        except Exception:
            pass

    def _target_serials(self, serial):
        if serial:
            return [serial]
        return self.devices.selected_serials()

    # ------------------------------------------------------------------
    # 无线调试（Wi-Fi ADB）
    # ------------------------------------------------------------------
    def _adb_argv(self):
        """当前 adb 可执行文件（-s 之外的所有 adb 调用都走这里）。"""
        return getattr(self.state, "adb_path", "") or "adb"

    def _wifi_default_port(self):
        try:
            return int(load_prefs().get("wifi_port", wifi.DEFAULT_PORT))
        except Exception:
            return wifi.DEFAULT_PORT

    def _wifi_recent(self):
        try:
            raw = load_prefs().get("wifi_recent", "")
        except Exception:
            raw = ""
        return wifi.recent_from_pref(raw)

    def _wifi_remember(self, addr):
        """把地址写进「最近连接」（config.json），并记住端口。"""
        recent = wifi.add_recent(self._wifi_recent(), addr)
        try:
            save_prefs({"wifi_recent": wifi.recent_to_pref(recent),
                        "wifi_port": wifi.split_endpoint(addr)[1]})
        except Exception:
            pass                       # 配置只读时不该让连接本身失败
        return recent

    def wifi_state(self):
        """无线调试弹窗的初始数据：已连的无线设备 + 最近地址 + 目标设备。"""
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        items = self.devices.get_items()
        wireless = [{
            "serial": it.get("serial", ""),
            "model": it.get("model", ""),
            "ok": bool(it.get("ok")),
            "state": it.get("state", ""),
        } for it in items if wifi.is_wireless_serial(it.get("serial", ""))]
        return {
            "ok": True,
            "wireless": wireless,
            "usb": [it.get("serial", "") for it in items
                    if not wifi.is_wireless_serial(it.get("serial", ""))],
            "recent": self._wifi_recent(),
            "port": self._wifi_default_port(),
            "selected": self.devices.selected_serials(),
        }

    def wifi_connect(self, address):
        """`adb connect <ip:port>`：连上后立刻刷新设备列表。

        地址由 core.wireless.normalize_endpoint 校验后才拼进参数位——把
        「adb connect 1.2.3.4」整条命令粘进来也能被正确解析。
        """
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        addr, err = wifi.normalize_endpoint(address, self._wifi_default_port())
        if err:
            self._push_status("warn", "⚠ 无线调试地址无效：" + err)
            return {"ok": False, "reason": err}
        try:
            r = subprocess.run([self._adb_argv(), "connect", addr],
                               **adb_kwargs(25))
        except Exception as e:
            return {"ok": False, "reason": "执行 adb connect 失败：%s" % e}
        res = wifi.parse_connect_output(
            (r.stdout or "") + "\n" + (r.stderr or ""))
        if not res["ok"]:
            self._push_status("err", "✗ 无线连接失败（%s）：%s"
                              % (addr, res["message"]), toast=True)
            return {"ok": False, "reason": res["message"], "address": addr}
        recent = self._wifi_remember(addr)
        self._push_status("ok", "✓ 无线调试已连接：%s" % addr, toast=True)
        # 连上不代表 `adb devices` 立刻可见（首次连接要等设备完成认证），
        # 但刷新一次能让已就绪的设备马上出现在左侧列表里。
        # key 独立于常规刷新（refresh）：那个 key 被自动刷新循环与手动刷新
        # 共用，撞上就会「复用存活线程」而这次刷新被静默吞掉——表现是
        # 「提示已连接，但左边列表里没有这台设备」。
        self.workers.spawn("refresh_wifi", self.devices.refresh,
                           self._adb_argv(), True)
        return {"ok": True, "address": addr, "message": res["message"],
                "recent": recent}

    def wifi_disconnect(self, address):
        """`adb disconnect <ip:port>`；也接受 mDNS 序列号原样传入。"""
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        raw = (address or "").strip()
        if not raw:
            return {"ok": False, "reason": "请先选择要断开的无线设备"}
        if wifi.is_wireless_serial(raw) and ":" in raw:
            addr, err = wifi.normalize_endpoint(raw, self._wifi_default_port())
            if err:
                return {"ok": False, "reason": err}
        else:
            addr = raw                      # mDNS 服务名：adb 原样接受
        try:
            r = subprocess.run([self._adb_argv(), "disconnect", addr],
                               **adb_kwargs(20))
        except Exception as e:
            return {"ok": False, "reason": "执行 adb disconnect 失败：%s" % e}
        text = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
        low = text.lower()
        if "error" in low or "no such device" in low:
            self._push_status("err", "✗ 断开失败（%s）：%s"
                              % (addr, text[:160]), toast=True)
            return {"ok": False, "reason": text[:160] or "adb 拒绝断开"}
        self._push_status("ok", "✓ 已断开无线设备：%s" % addr, toast=True)
        self.workers.spawn("refresh_wifi", self.devices.refresh,
                           self._adb_argv(), True)
        return {"ok": True, "address": addr}

    def _device_ip(self, serial):
        """读设备自身 IP（`ip route` + `ip -4 addr`）。返回 (ip, iface)。"""
        script = "ip route 2>/dev/null; echo @@ADDR; ip -4 addr 2>/dev/null"
        try:
            r = subprocess.run(
                [self._adb_argv(), "-s", serial, "shell", script],
                **adb_kwargs(15))
        except Exception:
            return "", ""
        return wifi.parse_device_ip(r.stdout or "")

    def wifi_enable(self, serial=None, port=None):
        """对目标设备执行 `adb tcpip <port>`，顺便把设备 IP 一起取回来。

        车机调试的典型流程是「插一次线 → 开无线 → 拔线」，而手动查 IP
        （设置里翻 WLAN 详情）是最容易被卡住的一步，所以这里一并读出来，
        前端直接填进地址框、点一下就连接。
        """
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        try:
            p = int(port) if port not in (None, "") else self._wifi_default_port()
        except (TypeError, ValueError):
            p = self._wifi_default_port()
        if not 1024 <= p <= 65535:
            return {"ok": False, "reason": "端口号必须是 1024~65535 的整数"}
        targets = self._target_serials(serial)
        if not targets:
            return {"ok": False, "reason": "请先在左侧勾选设备（首次开启必须走 USB）"}
        results = []
        for s in targets:
            ip, iface = self._device_ip(s)
            try:
                r = subprocess.run(
                    [self._adb_argv(), "-s", s, "tcpip", str(p)],
                    **adb_kwargs(20))
                out = ((r.stdout or "") + "\n" + (r.stderr or ""))
            except Exception as e:
                out = str(e)
            res = wifi.parse_tcpip_output(out)
            addr = "%s:%d" % (ip, p) if ip else ""
            results.append({
                "serial": s, "ip": ip, "iface": iface,
                "address": addr, "ok": res["ok"], "message": res["message"],
            })
            if res["ok"]:
                self._push_status(
                    "ok", "✓ %s 已开启无线调试%s（端口 %d）"
                    % (s, "：" + addr if addr else "，但没读到设备 IP，请手动填入",
                       res["port"] or p))
            else:
                self._push_status("err", "✗ %s 开启无线调试失败：%s"
                                  % (s, res["message"]), toast=True)
        ok_any = any(x["ok"] for x in results)
        first_addr = next((x["address"] for x in results if x["address"]), "")
        if ok_any:
            try:
                save_prefs({"wifi_port": p})
            except Exception:
                pass
        return {"ok": ok_any, "port": p, "results": results,
                "address": first_addr}

    # ------------------------------------------------------------------
    # APK 安装
    # ------------------------------------------------------------------
    def apk_pick(self):
        """弹原生文件对话框选一个 APK，只记路径（不读字节）。"""
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        path = self._open_dialog((("APK 安装包", "*.apk"),
                                  ("所有文件", "*.*")), "安装包 (*.apk)")
        if not path:
            return {"ok": False, "reason": "cancelled"}
        try:
            size = os.path.getsize(path)
        except OSError as e:
            return {"ok": False, "reason": "读取安装包失败：%s" % e}
        self._apk_path = path
        return {"ok": True, "path": path, "name": os.path.basename(path),
                "size": size, "size_text": apkinfo.format_size(size)}

    def apk_install(self, serial=None, replace=None, downgrade=None,
                    grant=None):
        """把选好的 APK 装到受控设备（每台一个后台 worker）。

        选项为 None 时取 config.json 里的默认值（界面上的勾选也会即时落盘，
        所以两条来源一致；显式传入则以传入为准）。
        """
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        path = self._apk_path
        if not path or not os.path.isfile(path):
            return {"ok": False, "reason": "请先选择 APK 安装包"}
        prefs = load_prefs()
        if replace is None:
            replace = bool(prefs.get("apk_replace", True))
        if downgrade is None:
            downgrade = bool(prefs.get("apk_downgrade", False))
        if grant is None:
            grant = bool(prefs.get("apk_grant", False))
        targets = self._target_serials(serial)
        if not targets:
            return {"ok": False, "reason": "请先在左侧勾选设备"}
        with self._apk_batch_lock:
            # 同一时刻只允许一批。worker 的 key 是 `apk_install_<serial>`，
            # 同一台设备上一批还没跑完时 spawn 会**复用存活线程**（不会真的
            # 再装一遍），可批次账已经被后一次点击重置——于是前一批的结果
            # 记进后一批的账里，界面提前收到 running=False，实际还在装。
            # 直接从源头拒绝第二次点击，比事后修补账面可靠。
            if self._apk_batch is not None:
                return {"ok": False,
                        "reason": "上一批安装还没结束，请等它完成后再装"}
            self._apk_batch = {
                "total": len(targets), "done": 0, "ok": 0,
                "failed": [], "seen": set(),
                "name": os.path.basename(path),
            }
        self.bus.push("apk_state", {"running": True})
        for s in targets:
            # key 带序列号：同一台设备连点两次不会叠加，不同设备互不阻塞
            self.workers.spawn("apk_install_" + s, self._do_apk_install, s, path,
                               bool(replace), bool(downgrade), bool(grant))
        self._push_status(
            "info", "开始安装 %s → %d 台设备（%s）"
            % (os.path.basename(path), len(targets),
               "、".join(["覆盖" if replace else "全新",
                          "允许降级" if downgrade else "",
                          "授予权限" if grant else ""]).replace("、、", "、").strip("、")),
            toast=False)
        return {"ok": True, "count": len(targets)}

    def _do_apk_install(self, serial, path, replace, downgrade, grant):
        """单台设备的安装（后台线程）：失败不抛，结果进状态栏 + 批次账。"""
        args = apkinfo.install_args(replace=replace, downgrade=downgrade,
                                    grant=grant)
        out, err = "", ""
        try:
            r = subprocess.run(
                [self._adb_argv(), "-s", serial] + args + [path],
                **adb_kwargs(300))
            out, err = r.stdout or "", r.stderr or ""
            res = apkinfo.parse_install_output(out + "\n" + err)
            # testOnly 调试包很常见（CI 出的包默认带 testOnly），遇上了自动
            # 加 -t 重试一次——比让用户自己看错误码再去查参数强得多。
            if (not res["ok"] and res.get("code") == "INSTALL_FAILED_TEST_ONLY"):
                self._push_status(
                    "warn", "… %s 是 testOnly 包，改用 -t 重试" % serial)
                args2 = args + ["-t"]
                r2 = subprocess.run(
                    [self._adb_argv(), "-s", serial] + args2 + [path],
                    **adb_kwargs(300))
                res = apkinfo.parse_install_output(
                    (r2.stdout or "") + "\n" + (r2.stderr or ""))
        except subprocess.TimeoutExpired:
            res = {"ok": False, "code": "",
                   "message": "安装超时（5 分钟）：包太大或设备 IO 卡住，可重试"}
        except Exception as e:
            res = {"ok": False, "code": "", "message": "安装异常：%s" % e}

        if res["ok"]:
            self._push_status("ok", "✓ 安装成功：%s ← %s"
                              % (serial, os.path.basename(path)))
        else:
            self._push_status("err", "✗ 安装失败：%s — %s"
                              % (serial, res["message"]), toast=True)
        self._apk_batch_done(serial, res, path)

    def _apk_batch_done(self, serial, res, path):
        """批次汇总：全部设备到齐后弹一条 toast（不逐台刷屏）。"""
        with self._apk_batch_lock:
            b = self._apk_batch
            if not b:
                return
            seen = b.setdefault("seen", set())
            if serial in seen:
                return                          # 同一台被重复记账（防御）
            seen.add(serial)
            b["done"] += 1
            if res["ok"]:
                b["ok"] += 1
            else:
                b["failed"].append((serial, res["message"]))
            done, total = b["done"], b["total"]
            ok_count = b["ok"]
            failed = list(b["failed"])
            name = b["name"]
            if done < total:
                return
            self._apk_batch = None
        # 批次结束（成功 / 失败都算）：前端据此恢复「安装」按钮的可用态。
        # 不靠「状态文案里含『完成』」来判断——文案随时会改，事件才是契约。
        self.bus.push("apk_state", {"running": False})
        if failed:
            self._push_status(
                "warn", "%s 安装完成：%d 成功 / %d 失败（%s）"
                % (name, ok_count, len(failed),
                   "；".join("%s：%s" % (s, m) for s, m in failed[:3])),
                toast=True)
        else:
            self._push_status("ok", "✓ %s 已安装到 %d 台设备" % (name, ok_count),
                              toast=True)

    # ------------------------------------------------------------------
    # 设备信息快照
    # ------------------------------------------------------------------
    def device_info(self, serial):
        """一次 adb shell 取回型号 / 版本 / 分辨率 / 电量 / 存储 / 内存。"""
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        s = (serial or "").strip()
        if not s:
            return {"ok": False, "reason": "请先选择设备"}
        try:
            r = subprocess.run(
                [self._adb_argv(), "-s", s, "shell", devinfo.SCRIPT],
                **adb_kwargs(20))
        except subprocess.TimeoutExpired:
            return {"ok": False, "reason": "读取设备信息超时（设备可能无响应）"}
        except Exception as e:
            return {"ok": False, "reason": "读取设备信息失败：%s" % e}
        if r.returncode != 0 and not (r.stdout or "").strip():
            detail = ((r.stderr or "").strip() or "设备未返回内容")[:160]
            return {"ok": False, "reason": "读取设备信息失败：%s" % detail}
        info = devinfo.parse_info(r.stdout or "")
        rows = devinfo.rows(info)
        return {"ok": True, "serial": s, "info": info,
                "rows": [[k, v] for k, v in rows],
                "text": devinfo.as_text(info)}

    # ------------------------------------------------------------------
    # 诊断包（一键收集现场证据 -> zip）
    # ------------------------------------------------------------------
    def diag_options(self):
        """诊断包卡的默认值（来自 config.json，单一数据源）。"""
        try:
            lines = get_pref("diag_logcat_lines", diag.DEFAULT_LOGCAT_LINES)
            with_log = bool(get_pref("diag_with_logcat", True))
        except Exception:
            lines, with_log = diag.DEFAULT_LOGCAT_LINES, True
        return {"ok": True,
                "with_logcat": with_log,
                "logcat_lines": diag.clamp_lines(lines),
                "max_lines": diag.MAX_LOGCAT_LINES,
                "running": self._diag_running}

    def diag_collect(self, serial=None, with_logcat=None, logcat_lines=None):
        """对勾选（或指定）设备各收集一个诊断包。

        单设备 3~6 秒（logcat 尾部 2000 行占大头），故整批丢进一条后台线程顺序
        执行，主线程立刻返回；完成/失败经 status + diag_state 事件回报。

        与截图不同，这里**不做多线程并行**：诊断包是 adb 密集操作，多台设备并行
        只会在 adb 的调用队列里互相排队，还会让 logcat 尾部的时间点对不齐。
        """
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        serials = self._target_serials(serial)
        if not serials:
            self._push_status("err", "⚠ 收集诊断包前请先勾选至少一个设备。")
            return {"ok": False, "reason": "no_device"}
        with self._diag_lock:
            if self._diag_running:
                # 已经在收集：直接拒绝并说明，不要排队 —— 排队会让用户以为
                # 「点了两下，出了两个包」，而第二个包的时间点是几分钟后的。
                self._push_status("info", "ℹ 诊断包正在收集中，请等当前这一批完成。")
                return {"ok": False, "reason": "busy"}
            self._diag_running = True
        if with_logcat is None:
            with_logcat = bool(get_pref("diag_with_logcat", True))
        lines = diag.clamp_lines(
            logcat_lines if logcat_lines is not None
            else get_pref("diag_logcat_lines", diag.DEFAULT_LOGCAT_LINES))
        save_dir = self._default_save_dir()
        self.bus.push("diag_state", {"running": True})
        self._push_status(
            "info", "开始收集诊断包：%d 台设备（%s）"
                    % (len(serials),
                       "含 logcat 尾部 %d 行" % lines if with_logcat else "不含 logcat"))
        self.workers.spawn("diag", self._do_diag, serials, save_dir,
                           bool(with_logcat), lines)
        return {"ok": True, "devices": serials}

    def _do_diag(self, serials, save_dir, with_logcat, lines):
        """逐台收集诊断包（后台线程）；每台一条结果，收尾复位按钮态。"""
        ok_count, failed, paths = 0, [], []
        try:
            for s in serials:
                if self.state.shutting_down:
                    return
                try:
                    path, manifest, err = diag.collect(
                        self._adb_argv(), s, save_dir,
                        with_logcat=with_logcat, logcat_lines=lines)
                except Exception as e:      # 兜底：诊断包异常不能拖垮整批
                    path, manifest, err = None, None, "内部错误：%s" % e
                if err or not path:
                    failed.append("%s：%s" % (s, err or "未知原因"))
                    self._push_status("err", "⚠ 诊断包失败 %s：%s"
                                      % (s, err or "未知原因"))
                    continue
                ok_count += 1
                paths.append(path)
                self.bus.push("tool", {"type": "diag", "serial": s,
                                       "path": path})
                self._push_status("ok", diag.summary_line(path, manifest))
        finally:
            with self._diag_lock:
                self._diag_running = False
            self.bus.push("diag_state", {"running": False})
        if ok_count and not failed:
            self._push_toast("ok", "✓ 诊断包已生成 %d 个，保存目录 %s"
                             % (ok_count, save_dir))
        elif ok_count and failed:
            self._push_toast(
                "warn", "⚠ 诊断包：%d 成功 / %d 失败（%s）"
                        % (ok_count, len(failed), "；".join(failed)[:120]))
        elif failed:
            self._push_toast("err", "⚠ 诊断包收集失败：%s" % "；".join(failed)[:160])

    # ------------------------------------------------------------------
    # 版本更新（发现新版本 -> 弹窗提示去下载，见 core/update.py）
    # ------------------------------------------------------------------
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


    def _mic_start(self, save_dir):
        """启动电脑麦克风录音；任何一步失败都返回 (False, 人话原因)，**绝不外抛**。

        早前这里只 try 了构造函数，`MicRecorder.start()` 裸调 —— 而 start() 内部的
        `_open()` 在 `waveInOpen` 失败（无麦克风设备 / 被隐私策略禁用 / 设备被占用）
        时会抛 RuntimeError。异常一路逃出 js_api 调用，且此时 `_screen_record_start_locked`
        已把 `_rec_session` 置为非空：异常跳过 `_cancel_half_started_rec()`，会话残留
        导致之后每次「开始录屏」都被守卫判为 recording 返回 —— 录屏功能永久锁死，
        用户只能重启程序。故这里对 start() 同样兜住，并顺手清掉半初始化的实例
        （否则 `_mic` 非 None 会让下次 `_mic_start` 误报「已在录音」）。
        """
        if self._mic is not None:
            return False, "已在录音"
        try:
            self._mic = MicRecorder()
        except Exception as e:
            self._mic = None
            return False, str(e)
        try:
            ok, p = self._mic.start(save_dir)
        except Exception as e:
            try:
                self._mic.stop()
            except Exception:
                pass
            self._mic = None
            return False, str(e)
        if not ok:
            self._mic = None
            return False, p
        return True, p

    def screenshot(self, serial=None, to_clipboard=None):
        """对勾选（或指定）设备各截一张 PNG。

        to_clipboard：是否同步写入系统剪贴板。前端在开关变化时同时下发这个值
        （即时、不依赖 config.json 是否可写）；未传则读用户偏好
        （shot_to_clipboard，缺省 = 开启）。

        多设备批量时**不自动复制**：剪贴板一次只能放一张，几台设备的后台线程
        互相覆盖后最终是哪一张完全不确定，还不如明确告知（文件照常各存一份）。

        完成通知（toast）分两种形态：单设备——每台完成即弹一条；
        批量——各 worker 只记数，全部到齐后由 _shot_batch_done 弹一条汇总，
        避免 N 台设备弹 N 条 toast 刷屏。

        按钮态：每个截图 worker 入口在途 +1（广播 shot_state
        running=true，前端禁用「立即截图」防连点），收尾时 -1，
        全部结束才恢复——用户点完就看清"在跑了"，不会反复点。
        spawn 本身失败（连线程都起不来的极端情况）不会有 worker 登记，
        由前端按调用失败恢复按钮（见 app.js 点击处理）。
        """
        serials = self._target_serials(serial)
        if not serials:
            self._push_status("err", "⚠ 截图前请先勾选至少一个设备。")
            return {"ok": False, "reason": "no_device"}
        if to_clipboard is None:
            to_clipboard = self._shot_to_clipboard_pref()
        to_clipboard = bool(to_clipboard)
        batch = len(serials) > 1
        save_dir = self._default_save_dir()
        if to_clipboard and batch:
            self._push_status(
                "warn", "⚠ 多设备批量截图不自动写入剪贴板（一次只能放一张），"
                        "图片已分别保存到保存目录。")
        if batch:
            # 批量汇总计数器：_do_screenshot 完成一台记一笔，到齐后弹一条 toast。
            with self._shot_batch_lock:
                self._shot_batch = {"total": len(serials), "ok": 0, "fail": 0,
                                    "dir": save_dir, "errs": []}
        for s in serials:
            # 每次截图一个独立 worker key：固定用 "screenshot_<serial>" 时，上一张
            # 还没截完就再点一次，Workers 会按同名把这次请求**静默丢弃**，而 API
            # 照旧返回 {"ok": True} —— 用户以为连截了两张，实际只有一张。
            # 文件名带序号（ScreenCapturer._seq），并行两次也不会互相覆盖。
            # 在途登记放在 worker 入口（_do_screenshot），这里不碰计数器：
            # +1/-1 同源同宿，任何执行时序（同步/异步 spawn）都自然平衡。
            self.workers.spawn(
                "screenshot_%s_%d" % (s, next(self._shot_seq)),
                self._do_screenshot, s, save_dir, to_clipboard and not batch, batch)
        return {"ok": True}

    def _shot_state_change(self, delta):
        """截图在途任务数 +/-1，越过 0 边界时向前端广播 shot_state。

        前端「立即截图」禁用态的唯一事实来源：点击时乐观禁用只是即时反馈，
        完成 / 异常收尾后的恢复由本事件驱动（与 rec_state 同一套路）。
        计数而非布尔：两次截图请求叠上时（API 直调、禁用生效前的竞态），
        先结束的那个不会把另一个的禁用态提前解开；0<->1 翻转才推事件，
        批量 N 台设备也只推一对 true/false，不刷事件队列。
        """
        with self._shot_state_lock:
            self._shot_inflight += delta
            running = self._shot_inflight > 0
            if running == self._shot_running:
                return
            self._shot_running = running
        self.bus.push("shot_state", {"running": running})

    def _shot_batch_done(self, ok, serial, err=None):
        """批量截图的一台完成：记数，全部到齐时弹一条汇总 toast。

        汇总而非逐台弹：多设备（本工具的主场景）一次点击会给每台设备各起一个
        worker，逐台弹 toast 会瞬间刷屏；成功/失败计数 + 保存目录一条说清。
        """
        with self._shot_batch_lock:
            b = self._shot_batch
            if b is None:                       # 批次已被新一轮重置/从未开启
                return
            if ok:
                b["ok"] += 1
            else:
                b["fail"] += 1
                b["errs"].append("%s：%s" % (serial, err or "未知原因"))
            done = b["ok"] + b["fail"]
            if done < b["total"]:
                return
            self._shot_batch = None             # 先摘计数器，避免与下一批交叉
        if b["fail"]:
            self._push_toast(
                "warn",
                "⚠ 批量截图完成：%d 成功，%d 失败（%s）——保存目录 %s"
                % (b["ok"], b["fail"], "；".join(b["errs"])[:120], b["dir"]))
        else:
            self._push_toast(
                "ok", "✓ 已完成 %d 台设备的截图，保存目录 %s"
                % (b["ok"], b["dir"]))

    def _shot_to_clipboard_pref(self):
        """用户偏好：截图后同步到粘贴板与否（缺省开启）。"""
        try:
            return bool(get_pref("shot_to_clipboard", True))
        except Exception:
            return True

    def _do_screenshot(self, serial, save_dir, to_clipboard=False, batch=False):
        # 在途登记放在 worker 入口：与 finally 的 -1 严格同源，成败甚至抛
        # 异常都平衡；批量 N 台也只在 0<->1 翻转时推事件（见 _shot_state_change）
        self._shot_state_change(1)
        try:
            self._do_screenshot_locked(serial, save_dir, to_clipboard, batch)
        except Exception:
            if batch:
                # 未预期的异常也要记进批次账：否则汇总 toast 永远等不齐，
                # 下一批之前 _shot_batch 一直挂着（按钮态由 finally 保证恢复）
                self._shot_batch_done(ok=False, serial=serial, err="内部错误")
            raise
        finally:
            # 成败甚至抛异常，在途计数都必须回落：漏一次 -1，「立即截图」
            # 会被 shot_state 永远锁在禁用态（按钮假死，只能重启程序）
            self._shot_state_change(-1)

    def _do_screenshot_locked(self, serial, save_dir, to_clipboard=False, batch=False):
        path, err = ScreenCapturer.screenshot(
            self.state.adb_path, serial, save_dir)
        if err:
            self._push_status("err", "⚠ 截图失败 %s: %s" % (serial, err))
            if batch:
                self._shot_batch_done(ok=False, serial=serial, err=err)
            return
        # 主反馈立刻给：图已落盘这个事实不再等剪贴板。写系统剪贴板要解 PNG
        # （1080x2400 纯 Python 约 1~2 秒），让它排在「已保存」提示之后，
        # 用户点击截图后第一时间就看到结果，而不是干等剪贴板。
        # 批量模式例外：N 台设备各弹一条会刷屏，toast 收口到 _shot_batch_done
        # 的一条汇总，这里只写状态栏明细。
        if batch:
            self._push_status("ok", "✓ 已保存截图: %s" % path)
        else:
            self._push_toast("ok", "✓ 已保存截图: %s" % path)
        payload = {"type": "screenshot", "serial": serial, "path": path}
        clip_ok = None
        if to_clipboard:
            # 剪贴板是不可靠的外部资源（被别的程序锁住、远程桌面会话、权限…），
            # 失败只影响「能否直接粘贴」，绝不影响已经落盘的那张图。
            clip_ok, clip_err = clipboard.copy_image(path)
            if clip_ok:
                self._push_status("ok", "✓ 已复制到粘贴板")
                payload["clipboard"] = True
            else:
                self._push_status(
                    "warn", "⚠ 已保存截图: %s（复制到粘贴板失败：%s）"
                            % (path, clip_err or "未知原因"))
                payload["clipboard"] = False
        if batch:
            self._shot_batch_done(ok=True, serial=serial)
        else:
            # 单设备：tool 事件即时推（前端可据此刷新缩略图等）
            self.bus.push("tool", payload)

    # ---- 录屏（视频 + 可选设备音频 + 可选电脑麦克风 + ffmpeg 合成）----
    def screen_record_start(self, serial=None,
                            with_devaudio=False, with_mic=False, save_dir=None,
                            with_logcat=False, zip_on_stop=False,
                            logcat_levels=None,
                            pointer_location=True, show_touches=True):
        """启动录屏会话（可含设备音频 / 麦 / logcat）。

        录屏一律**手动停止**（点「停止」或关窗口）：早期支持过「固定时长」，
        但实际使用中手动停止更直观，该选项已移除。
        _rec_lock 保护整个会话生命周期，与 screen_record_stop / shutdown
        互斥：连点 start、start 与 stop 撞车，都不会再出现会话引用被覆盖、
        漏停漏合成的情况。内部实现见 _screen_record_start_locked。

        logcat_levels：历史参数，已不生效 —— 录屏配套的 logcat 现在**一律全量**
        （`-b all` + 不过滤级别），见下方抓取调用的说明。保留形参只为兼容旧调用方
        （以及留一条接回「按级别抓」的口子），界面上的级别勾选已撤掉。

        with_devaudio / with_mic：同理保留但界面已撤掉 —— 设备端 tinycap 探测与
        ffmpeg 合成两条链路都没做完，开关留着只会让人以为录出来的是有声视频。

        pointer_location：录屏画面常驻指针准星（设备系统设置
        `settings put system pointer_location 1`，画面 overlay，全版本可用；
        停止录屏时自动恢复设备原值）。
        show_touches：开启系统「显示触摸操作」（`settings put system
        show_touches 1`）——触摸时屏幕出现圆点轨迹，回顾录像时能直观看到
        操作轨迹；停止录屏时恢复设备原值。

        整体兜底：启动链路上任何**未预期异常**（不是各服务返回的 ok=False，
        而是真正的抛出）都必须转化为 ok=False + 撤销半启动会话。否则
        `_rec_session` 已置非空、异常又跳过撤销逻辑，之后每次「开始录屏」
        都会被守卫判为「已在录制」而永远无法开始（只能重启程序），前端也只
        看到一次调用失败、没有任何解释。
        """
        with self._rec_lock:
            try:
                return self._screen_record_start_locked(
                    serial, with_devaudio, with_mic, save_dir,
                    with_logcat, zip_on_stop, logcat_levels,
                    pointer_location, show_touches)
            except Exception as ex:
                # 仅撤销「本次调用自己创建的」会话：异常发生时 _rec_session 必然
                # 是刚建的那份（守卫保证进入前它一定为空），撤销它不会误伤他人。
                self._cancel_half_started_rec()
                self._push_toast(
                    "err", "⚠ 录屏启动出现异常：%s（已自动撤销，可重试）" % ex)
                return {"ok": False, "reason": "start_error", "error": str(ex)}

    def _screen_record_start_locked(self, serial=None,
                                    with_devaudio=False, with_mic=False,
                                    save_dir=None, with_logcat=False,
                                    zip_on_stop=False, logcat_levels=None,
                                    pointer_location=True, show_touches=True):
        # 守卫：已有录制会话进行中，避免重复点击覆盖会话引用导致漏停/漏合成
        if self._rec_session:
            return {"ok": False, "reason": "recording"}
        serials = self._target_serials(serial)
        if not serials:
            self._push_status("err", "⚠ 录屏前请先勾选至少一个设备。")
            return {"ok": False, "reason": "no_device"}
        save_dir = save_dir or self._default_save_dir()
        sess_ts = time.strftime("%Y%m%d_%H%M%S")
        self._rec_session = {
            "ts": sess_ts, "dir": save_dir,
            "with_devaudio": with_devaudio, "with_mic": with_mic,
            "with_logcat": bool(with_logcat), "with_zip": bool(zip_on_stop),
            "mic_path": None, "mic_started": False,
            "videos": {}, "devaudio": {},
            "logcat_captures": {},
            # 可视化 overlay 原值备份：serial -> "0"/"1"/"null"（None = delete 恢复）。
            # 只登记「本次真的要恢复」的设备；读不到原值的设备不入表（不动它）。
            "pointer_location_prev": {},
            "show_touches_prev": {},
        }
        if with_mic:
            ok, p = self._mic_start(save_dir)
            if ok:
                self._rec_session["mic_path"] = p
                self._rec_session["mic_started"] = True
            else:
                self._rec_session["mic_started"] = False
                self._push_toast("warn", "⚠ 电脑麦克风启动失败：%s" % p)
        ok_any = False
        for s in serials:
            da = False
            if with_devaudio and DeviceAudioCapture.supported(
                    self.state.adb_path, s):
                # safe_name：无线序列号含冒号，设备端路径同样需要净化，
                # 保证 adb shell 命令与后续 pull 的路径完全一致。
                remote = "/data/local/tmp/adb_rec_%s_%s_audio.wav" % (
                    safe_name(s), sess_ts)
                if self.device_audio.start(s, remote):
                    self._rec_session["devaudio"][s] = remote
                    da = True
                else:
                    self._push_toast("warn", "⚠ 设备 %s 音频采集启动失败" % s)
            ok, local = self.video.start(s, save_dir, extra_name=sess_ts)
            if ok:
                ok_any = True
                self._rec_session["videos"][s] = local
                # 可视化 overlay：录屏真的起来了才开（并在收尾时恢复原值）。
                # 开失败不阻断录屏——可视化是增强，不是必需品。
                if pointer_location:
                    self._enable_overlay(
                        s, KEY_POINTER_LOCATION, "pointer_location_prev")
                if show_touches:
                    self._enable_overlay(s, KEY_SHOW_TOUCHES, "show_touches_prev")
                self._push_status(
                    "info", "录屏: %s%s" % (s, "（含设备音频）" if da else ""))
            else:
                self._push_status("err", "⚠ 录屏启动失败 %s: %s" % (s, local))
        # 同步抓取 logcat（走落盘抓取路径，避免占用实时监控渲染管线）
        if with_logcat:
            for s in serials:
                # safe_name：无线序列号含冒号，Windows 下文件名非法
                lp = os.path.join(
                    save_dir, "logcat_%s_%s.txt" % (safe_name(s), sess_ts))
                # 只有「本次录屏真的启动了这条抓取」才登记进会话。
                # 用户若已手动开着同一台设备的 Logcat 抓取，start() 会返回 False
                # （落在另一个文件上）；旧实现无视返回值照样登记，停止录屏时又把
                # 那条手动抓取一并 stop 掉 —— 用户的抓取被静默掐断，而录屏承诺的
                # txt 还因文件从未创建而不进 zip。
                #
                # 缓冲区用 `-b all`、级别不过滤（level_filter=None）：录屏配套的
                # logcat 是「事后复现问题」的唯一物证，缺一条就可能正好缺在案发现
                # 场上。曾按 main/system/events/crash 四缓冲 + 界面级别勾选抓，
                # 结果是 radio 日志整段不见、用户少勾一级就丢掉整类线索，且事后
                # 无法补救（录屏已经停了）。这里的取舍是「宁可文件大一点」。
                if self.logcat_capture.start(
                        s, lp, ["all"], level_filter=None):
                    self._rec_session["logcat_captures"][s] = lp
                else:
                    self._push_status(
                        "warn", "⚠ %s 已有 logcat 抓取在进行，本次录屏未重复抓取" % s)
            self._push_status(
                "info", "已同步开始 logcat 抓取（全部缓冲区 + 全部级别，随录屏停止）")
        if not ok_any:
            # 全部设备启动失败：撤销本会话残留（麦 / 设备音频 / 同步 logcat
            # 可能已启动）。若不清理，前端看不到「录制中」也就点不到停止，残留
            # 的麦克风/设备端 tinycap 会一直录到程序关闭。
            self._cancel_half_started_rec()
            self._push_status(
                "err", "⚠ 录屏未能启动：已自动撤销本会话，请检查设备与目录权限后重试。")
            return {"ok": False, "reason": "start_failed"}

        return {"ok": ok_any, "mic": self._rec_session.get("mic_path"),
                "ts": sess_ts}

    def _cancel_half_started_rec(self):
        """撤销「启动失败 / 启动异常」的录屏会话残留（须在持有 _rec_lock 时调用）。

        语义是「把本次会话已启动的一切全部收掉」：设备音频、电脑麦克风、同步
        logcat 抓取，以及**已启动的录屏**。早前只管前三项，那是因为唯一的调用
        路径（`if not ok_any`）按定义不可能有视频启动成功；现在启动异常兜底
        （screen_record_start 的 except）也可能在「部分设备的 video.start 已
        成功之后」才炸，不补收视频就会留下设备端 screenrecord 一直录到 Android
        自带的 3 分钟上限、界面却没有任何「录制中」提示的孤儿会话。
        """
        sess = self._rec_session or {}
        for s in list(sess.get("videos", {}).keys()):
            try:
                self.video.stop(s)
            except Exception:
                pass
        for s in list(sess.get("devaudio", {}).keys()):
            try:
                self.device_audio.stop(s)
            except Exception:
                pass
        if self._mic is not None:
            try:
                self._mic.stop()
            except Exception:
                pass
            self._mic = None
        for s in list(sess.get("logcat_captures", {}).keys()):
            try:
                self.logcat_capture.stop(s, zip_on_stop=False)
            except Exception:
                pass
        self._restore_overlays(sess)
        self._rec_session = {}

    # ---- 可视化 overlay（pointer_location 指针位置 / show_touches 触摸圆点）----
    def _enable_overlay(self, serial, key, prev_field):
        """打开设备端 overlay（指针位置 / 触摸圆点），原值备份进会话（须持 _rec_lock）。

        读不到原值（adb 瞬断）时**不入表**：没有备份就不恢复，
        胜过把用户原来的 "0" 误删成默认——防错优先于功能完整。
        """
        ok, old = self.video.get_system_setting(self.state.adb_path, serial, key)
        if not ok:
            return
        self._rec_session.setdefault(prev_field, {})[serial] = old
        self.video.set_system_setting(self.state.adb_path, serial, key, "1")

    def _restore_overlays(self, sess):
        """把会话里备份的 pointer_location / show_touches 原值写回各设备
        （"null" → 删除该键）。

        所有收尾路径（停止 / 启动失败撤销 / 异常撤销）都必须经过这里，
        否则用户设备会一直开着 overlay——下次正常用手机时满屏准星/圆点。
        单台失败不影响其余设备（各自独立 try）。
        """
        for field, key in (("pointer_location_prev", KEY_POINTER_LOCATION),
                           ("show_touches_prev", KEY_SHOW_TOUCHES)):
            for s, old in ((sess or {}).get(field) or {}).items():
                try:
                    # "null"/空 = 设备原本没设过这个键：恢复手段是删除而不是写 0，
                    # 否则会在系统设置里留下一个用户从未创建过的条目。
                    val = None if (old is None or str(old).strip().lower()
                                   in ("null", "")) else str(old).strip()
                    self.video.set_system_setting(self.state.adb_path, s, key, val)
                except Exception:
                    pass

    def screen_record_stop(self):
        """停止录屏：收尾合成 / 打包 / 清理会话（与 start / shutdown 串行）。"""
        with self._rec_lock:
            return self._screen_record_stop_locked()

    def _screen_record_stop_locked(self):
        if not self._rec_session:
            return {"ok": False, "reason": "no_session"}
        sess = self._rec_session
        # 整个收尾过程必须包在 try/finally 里：只要中途抛一次（例如保存目录所在
        # 磁盘掉线 → screen_service._pull_and_finish 里的 os.makedirs 抛错），
        # `self._rec_session = {}` 就永远执行不到，会话标记残留 → 之后每次点「开始
        # 录屏」都被 `_screen_record_start_locked` 的守卫判为 recording，录屏功能
        # 永久锁死且只能重启程序；异常还会逃出 js_api 调用，用户看不到任何提示。
        try:
            files, zpath = self._session_teardown(sess)
            self._push_status("info", "⏹ 录屏已停止")
            # 完成强提醒：收尾可能要拉文件 / 等设备端写 moov / 合成 / 打包，
            # 耗时以秒计，用户很可能已切去别的页签——一条汇总 toast 说清
            # 「存在哪」，明细（逐台合成/保存/打包）留在状态栏。
            if zpath:
                self._push_toast("ok", "✓ 录屏已完成，产物已打包: %s" % zpath)
            elif files:
                self._push_toast(
                    "ok", "✓ 录屏已完成：%d 个文件已保存到 %s"
                    % (len(files), sess.get("dir") or "保存目录"))
            return {"ok": True}
        except Exception as ex:
            self._push_toast("err", "⚠ 录屏收尾出现异常：%s" % ex)
            return {"ok": False, "reason": "stop_error", "error": str(ex)}
        finally:
            self._rec_session = {}

    def _session_teardown(self, sess):
        """录屏会话收尾主体（须在持有 _rec_lock 时调用；异常由调用方兜底）。

        返回 (产出文件列表, zip 路径或 None)，供调用方弹「已完成」汇总 toast；
        全失败的场景文件列表为空，此时明细 warn 已由内部逐条 toast。
        """
        # 可视化 overlay 必须**先于**视频收尾恢复：它们是设备系统设置，
        # 早一点恢复，用户设备就少一瞬处于「开着准星/圆点」的意外状态。
        self._restore_overlays(sess)
        local_videos = {}
        dead = sess.get("dead") or set()
        for s in list(sess.get("videos", {}).keys()):
            local = None
            if self.video.is_recording(s):
                ok, lp, err = self.video.stop(s)
                if ok:
                    local = lp
                elif s in dead:
                    # 进程意外死亡（adb root 等）：文案说清「视频不完整」，
                    # 与普通收尾失败区分开（用户据此知道该重录，而不是怀疑程序坏了）。
                    self._push_toast(
                        "warn",
                        "⚠ %s 录屏被意外中断，视频不完整（%s）。残片已保留在保存目录，"
                        "音频未合成；请完整重录。" % (s, err or "设备端进程已提前退出"))
                else:
                    self._push_toast(
                        "warn", "⚠ 录屏收尾失败 %s：%s" % (s, err or "未知原因"))
            else:
                # 会话已被其他路径收尾弹出（stop_all / 异常清理等）时，
                # 这里再用 stop() 只会得到「该设备未在录制」。必须用启动时记录的
                # 本地路径兜底，否则这段视频既不合成音频、也不进 zip、界面也无提示。
                local = sess.get("videos", {}).get(s)
            if local and os.path.exists(local):
                local_videos[s] = local
        local_devaudio = {}
        for s in list(sess.get("devaudio", {}).keys()):
            lp = self.device_audio.stop(s)
            if lp:
                local_devaudio[s] = lp
        mic_path = None
        if self._mic is not None:
            try:
                mic_path = self._mic.stop()
            except Exception:
                mic_path = None
            self._mic = None
        rec_files = []   # 最终要打包的产出文件
        # 「勾了麦却没声」只在麦克风**确实启动过**时才提示：启动就失败的场景
        # 上面已经 toast 过「电脑麦克风启动失败」，不再重复归因为「全程静音」。
        mic_lost = bool(sess.get("with_mic") and sess.get("mic_started")
                        and not mic_path)
        for s, vlocal in local_videos.items():
            audios = []
            if local_devaudio.get(s):
                audios.append(local_devaudio[s])
            if mic_path:
                audios.append(mic_path)
            if audios:
                final = (vlocal[:-4] + "_final.mp4") if vlocal.endswith(
                    ".mp4") else (vlocal + ".final.mp4")
                merged = ffmpeg_mux(vlocal, audios, final)
                if merged:
                    self._push_status("ok", "✓ 已合成音视频: %s" % merged)
                    rec_files.append(merged)
                else:
                    # 合成失败/产出不可播放时**保留原视频**，并说清原因：
                    # 「未安装 ffmpeg」只是其中一种，音频为空、ffmpeg 过旧同样会走到这里。
                    why = "" if _have_ffmpeg() else "（未检测到 ffmpeg）"
                    self._push_toast(
                        "warn", "⚠ 合成音视频失败%s，原始视频已保存（无音轨）: %s"
                        % (why, vlocal))
                    if os.path.exists(vlocal):
                        rec_files.append(vlocal)
            else:
                self._push_status("ok", "✓ 录屏已保存: %s" % vlocal)
                if os.path.exists(vlocal):
                    rec_files.append(vlocal)
        if mic_lost:
            # 空录音（麦克风被占用 / 全程静音 / 无录音权限）现在会返回 None 并删除坏文件，
            # 这里明确告诉用户「为什么没有声音」，否则用户只看到成片没音轨。
            self._push_toast(
                "warn", "⚠ 未录到电脑麦克风声音（麦克风可能被占用、无权限或全程静音），"
                        "已按无音轨保存视频。")
        # 设备端音频被 pull 到 %TEMP% 的临时 wav（adb_devaudio_*.wav），唯一用途就是
        # 喂给 ffmpeg 合成；合成结束后这些文件已无用，必须清理，否则每次录屏都会在
        # TEMP 留下孤儿文件，长期累积会悄悄占满系统盘。
        for lp in local_devaudio.values():
            try:
                if lp and os.path.exists(lp):
                    os.remove(lp)
            except Exception:
                pass
        # 同步停止 logcat 抓取，等待写盘后收集 txt
        for s, p in sess.get("logcat_captures", {}).items():
            try:
                self.logcat_capture.stop(s, zip_on_stop=False)
            except Exception:
                pass
            for _ in range(20):
                if not self.logcat_capture.is_running(s):
                    break
                time.sleep(0.1)
            if os.path.exists(p):
                rec_files.append(p)
        # 结束录制后自动压缩为 zip（录屏 mp4 + 同步 logcat 一并打包）
        zpath = None
        if sess.get("with_zip") and rec_files:
            z = os.path.join(sess["dir"], "rec_%s.zip" % sess["ts"])
            if self._zip_paths(rec_files, z):
                zpath = z
                self._push_status("ok", "✓ 录制产物已打包: %s" % zpath)
        return rec_files, zpath

    @staticmethod
    def _zip_paths(paths, zip_path):
        """把若干文件打包为一个 zip（以文件名作条目）。失败返回 None。

        打包**完整写出成功后**清理源文件（仅清理本次实际写入 zip 的普通文件，
        目录 / zip 自身 / 写入失败未进包的文件都不会被删）——与 README 承诺的
        「打包完成后清理刚打包的源文件（仅删打包所覆盖的文件）」保持一致。
        """
        written = []
        try:
            if os.path.exists(zip_path):
                os.remove(zip_path)
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
                for p in paths:
                    if (p and p != zip_path and os.path.exists(p)
                            and os.path.isfile(p)):
                        z.write(p, os.path.basename(p))
                        written.append(p)
            if not os.path.exists(zip_path):
                return None
        except Exception:
            # 打包中途失败：清掉可能残留的半成品 zip，源文件一律保留
            try:
                if os.path.exists(zip_path):
                    os.remove(zip_path)
            except Exception:
                pass
            return None
        for p in written:
            try:
                os.remove(p)
            except Exception:
                pass
        return zip_path

    # ---- 投屏（调用用户机器上已安装的 scrcpy，见 backend/scrcpy_service.py）----
    def _scrcpy_pref_path(self):
        """用户配置的 scrcpy 路径（读失败一律当空 = 走自动探测）。"""
        try:
            return str(load_prefs().get("scrcpy_path") or "")
        except Exception:
            return ""

    def scrcpy_probe(self):
        """探测本机 scrcpy（工具页初始化 / 「重新检测」按钮）。

        返回 {ok, path, version, note}：
          * ok=False 时 note 是可执行的安装建议（不是一句"未找到"）；
          * ok=True 时 path/version 直接显示在界面上，用户能确认用的是哪一份。
        """
        return scrcpy_probe_info(self._scrcpy_pref_path())

    def scrcpy_start(self, serial=None):
        """对勾选（或指定）设备各开一个 scrcpy 投屏窗口。

        一台设备一个窗口（scrcpy 的限制：一个实例只能投一台设备）。
        已在投屏的设备不重复开窗；秒退的（未授权 / 版本不兼容 / adb 报错）
        把 scrcpy 自己的报错回显到状态栏，而不是让窗口一闪而过、用户以为没反应。
        """
        serials = self._target_serials(serial)
        if not serials:
            self._push_status("err", "⚠ 投屏前请先勾选至少一台设备。")
            return {"ok": False, "reason": "no_device"}
        exe, note = find_scrcpy(self._scrcpy_pref_path())
        if not exe:
            self._push_status("warn", "⚠ " + note)
            return {"ok": False, "reason": "scrcpy_not_found", "note": note}
        try:
            res = self._scrcpy.launch(serials, exe)
        except Exception as ex:
            self._push_toast("err", "⚠ 投屏启动出现异常：%s" % ex)
            return {"ok": False, "reason": "start_error", "error": str(ex)}
        started = res["started"]
        skipped = res["skipped"]
        failed = res["failed"]
        if started:
            self._push_status("ok", "✓ 已开启投屏：%s" % "、".join(started))
        if skipped:
            self._push_status("info", "ℹ 已在投屏中：%s" % "、".join(skipped))
        for s, reason in failed:
            self._push_status("err", "⚠ %s 投屏失败：%s" % (s, reason))
        return {
            "ok": bool(started or skipped),
            "path": exe,
            "started": started,
            "skipped": skipped,
            "failed": [{"serial": s, "reason": r} for s, r in failed],
        }

    # ---- 备用投屏：没装 scrcpy 时的两条退路（见 backend/mirror_service.py）----
    def _mirror_prefs(self):
        """备用投屏相关配置（读失败一律回退默认值，不让界面卡在异常上）。"""
        try:
            p = load_prefs()
        except Exception:
            p = {}
        return {
            "player_path": str(p.get("mirror_player_path") or ""),
            "size": str(p.get("mirror_size") or ""),
            "bitrate": int(p.get("mirror_bitrate") or 8),
            "fps": int(p.get("mirror_fps") or 2),
        }

    def mirror_probe(self):
        """探测本机投屏能力：scrcpy 与播放器各自的可用状态。

        前端据此决定「备用投屏」按钮的提示文案——有 scrcpy 就主推 scrcpy，
        没有但有播放器就说明会用播放器窗口，两者都没有则预告会退化成低帧率预览。
        """
        return {
            "scrcpy": scrcpy_probe_info(self._scrcpy_pref_path()),
            "player": probe_player(self._mirror_prefs()["player_path"]),
        }

    def _on_mirror_error(self, serial, error):
        """后台转发/抓帧线程结束回调：只报真错误，并把设备从登记表摘掉。

        摘掉是必要的：不摘的话这台设备会一直显示「投屏中」，用户再点一次
        按钮会因为「已在投屏」被跳过，永远开不起来。
        """
        if error:
            self._push_status("err", "⚠ %s 投屏已中断：%s" % (serial, error))
        self._mirror_pipes.pop(serial, None)
        self._mirror_snaps.pop(serial, None)

    def _start_one_mirror(self, serial, pref, mode):
        """对单台设备按 mode 逐级降级地开投屏，返回 {mode, frame_url} 或 {error}。

        降级顺序（只走到第一个能用为止）：
          scrcpy（仅 auto） → screenrecord 管道给播放器 → screencap 低帧率预览
        """
        if mode == "auto":
            exe, _note = find_scrcpy(self._scrcpy_pref_path())
            if exe:
                try:
                    res = self._scrcpy.launch([serial], exe)
                except Exception as ex:
                    res = {"started": [], "skipped": [], "failed": [(serial, str(ex))]}
                if res["started"] or res["skipped"]:
                    return {"mode": "scrcpy", "frame_url": ""}
                # 起不来（未授权 / 版本不兼容）→ 继续往下降级，别轻易放弃

        if mode in ("auto", "pipe"):
            kind, exe, note = find_player(pref["player_path"])
            if exe:
                size = pref["size"] or plan_size(self.state.adb_path, serial)
                m = PipeMirror(self.state.adb_path, serial, kind, exe, size,
                               pref["bitrate"], 60,
                               on_status=self._on_mirror_error)
                ok, err = m.start()
                if ok:
                    self._mirror_pipes[serial] = m
                    return {"mode": "pipe", "frame_url": "", "player": exe,
                            "size": size}
                pipe_err = err
            else:
                pipe_err = note
        else:
            pipe_err = ""

        # 兜底：只要 adb 能截图就一定有画面（帧率很低，但不会「点了没反应」）
        if not self._frame_server.start():
            return {"error": pipe_err or "帧服务启动失败（本地回环端口不可用）"}
        m = SnapMirror(self.state.adb_path, serial, self._frame_server,
                       pref["fps"], on_status=self._on_mirror_error)
        ok, err = m.start()
        if ok:
            self._mirror_snaps[serial] = m
            return {"mode": "snap", "frame_url": self._frame_server.frame_url(serial),
                    "note": pipe_err}
        return {"error": err or "低帧率预览也启动失败"}

    def mirror_start(self, serial=None, mode="pipe"):
        """开启备用投屏（一台设备一个画面源）。

        mode：
          * "auto" —— scrcpy → 管道 → 低帧率预览，逐级降级；
          * "pipe" —— 管道 → 低帧率预览（主按钮已单独负责 scrcpy，故默认不含它）；
          * "snap" —— 只用低帧率预览。
        """
        serials = self._target_serials(serial)
        if not serials:
            self._push_status("err", "⚠ 投屏前请先勾选至少一台设备。")
            return {"ok": False, "reason": "no_device"}
        pref = self._mirror_prefs()
        started, skipped, failed = [], [], []
        for s in serials:
            if s in self._mirror_pipes or s in self._mirror_snaps:
                skipped.append(s)
                continue
            try:
                res = self._start_one_mirror(s, pref, mode)
            except Exception as ex:
                res = {"error": str(ex)}
            if res.get("mode"):
                started.append({"serial": s, "mode": res["mode"],
                                "frame_url": res.get("frame_url") or ""})
            else:
                failed.append({"serial": s, "reason": res.get("error") or "未知原因"})

        label = {"scrcpy": "scrcpy 窗口", "pipe": "播放器窗口（screenrecord 管道）",
                 "snap": "低帧率预览（screencap 轮询）"}
        if started:
            self._push_status("ok", "✓ 已开启投屏：" + "、".join(
                "%s（%s）" % (x["serial"], label.get(x["mode"], x["mode"]))
                for x in started))
        for x in failed:
            self._push_status("err", "⚠ %s 投屏失败：%s" % (x["serial"], x["reason"]))
        if skipped:
            self._push_status("info", "ℹ 已在投屏中：%s" % "、".join(skipped))
        return {"ok": bool(started or skipped), "started": started,
                "skipped": skipped, "failed": failed}

    def mirror_stop(self, serial=None):
        """停止备用投屏（管道 / 低帧率预览），不含 scrcpy 窗口（由用户自己关）。"""
        targets = self._target_serials(serial)
        stopped = []
        for s, m in list(self._mirror_pipes.items()):
            if targets and s not in targets:
                continue
            try:
                m.stop()
            except Exception:
                pass
            self._mirror_pipes.pop(s, None)
            stopped.append(s)
        for s, m in list(self._mirror_snaps.items()):
            if targets and s not in targets:
                continue
            try:
                m.stop()
            except Exception:
                pass
            self._mirror_snaps.pop(s, None)
            stopped.append(s)
        if stopped:
            self._push_status("info", "ℹ 已停止投屏：%s" % "、".join(stopped))
        return {"ok": True, "stopped": stopped}

    def mirror_status(self):
        """当前备用投屏状态（前端用来刷新按钮与预览区可见性）。"""
        return {
            "pipe": [s for s, m in self._mirror_pipes.items() if m.alive()],
            "snap": [s for s, m in self._mirror_snaps.items() if m.alive()],
        }

    # ---------------- 性能监控（CPU / 内存 / FPS / 电量 / 温度） ----------------
    @staticmethod
    def _perf_label(info, serial):
        """报告里用的设备短名：型号 + 序列号尾部。

        同型号批量测试（一次 4 台 Pixel）时，只写型号会让对比报告的图例与表头
        出现四个一模一样的名字 —— 那就等于没有图例。
        """
        serial = str(serial or "")
        model = (info or {}).get("model") or ""
        tail = serial[-4:] if len(serial) > 10 else serial
        return ("%s · %s" % (model, tail)) if model else (tail or "device")

    def _perf_interval(self, interval_ms):
        """采样间隔：前端可能传空 / 字符串 / 越界值，一律夹到安全区间。

        下限 0.2s 是防止手抖填 0 把 adb 打满（一次采样本就要 200~400ms，
        再快只是在排队，采到的还是同一时刻的数据）；上限 10s 避免「点完
        开始，半分钟没反应」。
        """
        try:
            ms = int(interval_ms)
        except (TypeError, ValueError):
            ms = int(DEFAULT_INTERVAL * 1000)
        sec = ms / 1000.0
        return min(PERF_MAX_INTERVAL, max(PERF_MIN_INTERVAL, sec))

    def perf_list_packages(self, serial=None, refresh=False):
        """读设备上已安装的应用包名，供「应用包名」下拉框使用。

        serial 为空时取第一台受控设备（与 perf-start 的默认目标一致）：应用
        列表在几台设备之间通常一致，没必要每台都拉一遍再拼起来。

        结果缓存 PERF_PKG_CACHE_S 秒：下拉框每次打开都会问一次，而 `pm list
        packages` 在应用多的机器上要 1~3 秒 —— 不缓存的话「点开下拉框」这件
        事会稳定地卡两秒。点「刷新」或换设备时 refresh=True 绕过缓存。
        """
        if serial:
            target = serial
        else:
            controlled = self._target_serials(None)
            target = controlled[0] if controlled else ""
        if not target:
            return {"ok": False, "reason": "no_device",
                    "message": "请先在左侧勾选一台设备"}
        now = time.time()
        with self._perf_pkg_lock:
            cached = self._perf_pkg_cache.get(target)
            if (not refresh) and cached and (now - cached.get("at", 0) < PERF_PKG_CACHE_S):
                out = dict(cached["data"])
                out["cached"] = True
                return out
        res = perf_list_installed(self.state.adb_path, target)
        res["serial"] = target
        res["cached"] = False
        if res.get("ok"):
            with self._perf_pkg_lock:
                self._perf_pkg_cache[target] = {"at": now, "data": dict(res)}
        return res

    def perf_start(self, serial=None, interval_ms=None, pkg=None):
        """开始性能监控。

        不传 serial 时监控**全部受控设备**（多台即进入对比模式），上限
        PERF_MAX_DEVICES 台：每台一条采样线程、每 1s 一次 `adb shell`，
        再多就只是在 adb 的调用队列里排队，换不来更多信息。
        """
        serials = self._target_serials(serial)
        if not serials:
            self._push_status("err", "⚠ 性能监控前请先勾选至少一台设备。")
            return {"ok": False, "reason": "no_device"}
        if len(serials) > PERF_MAX_DEVICES:
            skipped = serials[PERF_MAX_DEVICES:]
            serials = serials[:PERF_MAX_DEVICES]
            self._push_status(
                "warn", "⚠ 性能监控最多同时监控 %d 台设备，已忽略：%s"
                % (PERF_MAX_DEVICES, "、".join(skipped)))
        interval = self._perf_interval(interval_ms)
        pkg = (pkg or "").strip()
        started, infos, failed = {}, {}, {}
        for s in serials:
            mon = PerfMonitor(self.state.adb_path, s, interval, pkg,
                              on_status=self._push_status)
            ok, err = mon.start()
            if not ok:
                try:
                    mon.stop()
                except Exception:
                    pass
                failed[s] = err
                continue
            started[s] = mon
            infos[s] = dict(mon.info)
        if not started:
            err = next(iter(failed.values()), "启动失败")
            self._push_status("err", "⚠ 性能监控启动失败：%s" % err)
            return {"ok": False, "reason": "start_failed", "error": err,
                    "failed": failed}
        # 新会话就位后再关旧会话：启动失败时旧数据还在，用户不会白丢一段曲线。
        with self._perf_lock:
            old, self._perfs = dict(self._perfs), started
        for mon in old.values():
            try:
                mon.stop()
            except Exception:
                pass
        primary = serials[0] if serials[0] in started else next(iter(started))
        info = infos[primary]
        if len(started) == 1:
            self._push_status(
                "ok", "✓ 已开始性能监控：%s（%s · 每 %.1f 秒采样一次）"
                % (info.get("model") or primary, perf_pkg_display(info), interval))
        else:
            self._push_status(
                "ok", "✓ 已开始性能监控：%d 台设备（%s · 每 %.1f 秒采样一次）"
                % (len(started), perf_pkg_display(info), interval))
        return {"ok": True, "serial": primary, "info": info,
                "interval": interval, "sessions": infos, "failed": failed}

    def perf_stop(self, serial=None):
        """停止采样。会话对象**保留**：停完还能导出刚才那段报告。

        serial 为空 = 全部停止；指定则只停那一台（对比时想先收掉一台的情况）。
        """
        with self._perf_lock:
            if serial:
                targets = ({serial: self._perfs[serial]}
                           if serial in self._perfs else {})
            else:
                targets = dict(self._perfs)
        if not targets:
            return {"ok": True, "samples": 0, "sessions": {}}
        per, total = {}, 0
        for s, mon in targets.items():
            if mon.alive():
                mon.stop()
            per[s] = mon.count()
            total += per[s]
        if len(per) == 1:
            self._push_status("info", "⏹ 已停止性能监控（本次共 %d 个采样点）" % total)
        else:
            self._push_status("info", "⏹ 已停止 %d 台设备的性能监控（共 %d 个采样点）"
                              % (len(per), total))
        return {"ok": True, "samples": total, "sessions": per}

    def perf_poll(self, since=0):
        """增量拉取采样点。前端按 0.6s 轮询，不用事件总线。

        since 可以是 {serial: seq}（多设备各自维护游标），也可以是单个 int
        （首次调用 / 旧前端：所有会话都从该 seq 之后取）。顶层 samples 是各
        会话合并后按时间排序的结果，仅为兼容旧前端；新前端读 sessions。
        """
        with self._perf_lock:
            sessions = dict(self._perfs)
        if not sessions:
            return {"running": False, "seq": 0, "samples": [], "info": {},
                    "sessions": {}}
        out, seqs, merged = {}, {}, []
        running = False
        for s, mon in sessions.items():
            try:
                cursor = since.get(s, 0) if isinstance(since, dict) else int(since or 0)
            except (TypeError, ValueError, AttributeError):
                cursor = 0
            snap = mon.snapshot(cursor)
            running = running or bool(snap.get("running"))
            seqs[s] = snap.get("seq", 0)
            merged.extend(snap.get("samples") or [])
            out[s] = snap
        merged.sort(key=lambda x: x.get("t") or 0)
        first = next(iter(sessions))
        return {"running": running, "seq": seqs, "samples": merged,
                "info": dict(sessions[first].info), "sessions": out,
                "count": sum(len(v.get("samples") or []) for v in out.values())}

    def _perf_thresholds(self):
        """当前生效的告警阈值（读 config.json，留空 = 内置基线）。

        每次现读而不是缓存到 self：用户可以边监控边在界面上改阈值，也可以
        直接编辑 config.json 后重启监控 —— 缓存一份就得处理失效，而这里读
        文件的开销（几 KB JSON）在「点一次按钮」「导一次报告」的量级上无所谓。
        返回 (阈值 dict, 解析错误列表, 原始表达式)。
        """
        try:
            expr = (load_prefs() or {}).get("perf_thresholds")
        except Exception:
            expr = ""
        th, errs = perf_parse_thresholds(expr)
        return th, errs, (expr or "").strip() if isinstance(expr, str) else ""

    def _perf_threshold_payload(self):
        th, errs, expr = self._perf_thresholds()
        return {
            "thresholds": dict((k, dict(v)) for k, v in th.items()),
            "rules": dict((k, perf_rule_text(k, v)) for k, v in th.items()),
            "items": perf_threshold_items(th),
            "crit_ratio": PERF_CRIT_RATIO,
            "expr": perf_format_thresholds(th) if th else "",
            "default_expr": perf_default_threshold_expr(),
            "custom": bool(expr),
            "off": not th,
            "errors": errs,
        }

    def perf_thresholds(self):
        """下发告警阈值：界面实时标红与报告里的告警卡片共用同一份定义。

        阈值只有一份来源（config.json 的 perf_thresholds，缺省回落
        backend/perf_service.DEFAULT_THRESHOLDS）：前端不再抄一份 ——
        两份常量一定会漂移，最后报告说「没超标」而界面标红。
        """
        return self._perf_threshold_payload()

    def perf_set_thresholds(self, values=None):
        """保存界面提交的阈值（{key: 数值或 None}，None = 关闭该条）。

        提交值先过与手改 config.json 相同的校验，非法时**不写盘**并把原因
        返回给界面：静默存下一份非法配置，用户下次启动只会看到告警莫名消失。
        """
        if not isinstance(values, dict):
            return {"ok": False, "reason": "bad_args",
                    "errors": ["阈值参数格式不正确"]}
        th, errs = perf_build_thresholds(values)
        if errs:
            return {"ok": False, "reason": "invalid", "errors": errs}
        expr = perf_format_thresholds(th) if th else "off"
        try:
            save_prefs({"perf_thresholds": expr})
        except Exception as ex:
            return {"ok": False, "reason": "save_failed", "errors": [str(ex)]}
        payload = self._perf_threshold_payload()
        payload["ok"] = True
        if th:
            self._push_status("ok", "✓ 告警阈值已更新：%s" % " · ".join(
                perf_rule_text(k, v) for k, v in th.items()), toast=True)
        else:
            self._push_status("info", "告警阈值已全部关闭（不再标红 / 不再告警）",
                              toast=True)
        return payload

    def perf_status(self):
        with self._perf_lock:
            sessions = dict(self._perfs)
        if not sessions:
            return {"running": False, "serial": "", "info": {}, "seq": 0,
                    "count": 0, "sessions": {}}
        first = next(iter(sessions))
        detail = {}
        running = False
        total = 0
        for s, mon in sessions.items():
            n = mon.count()
            alive = mon.alive()
            running = running or alive
            total += n
            detail[s] = {"running": alive, "seq": mon.seq, "count": n,
                         "info": dict(mon.info), "error": mon.error}
        return {"running": running, "serial": first, "info": dict(sessions[first].info),
                "seq": {s: d["seq"] for s, d in detail.items()}, "count": total,
                "error": sessions[first].error, "sessions": detail}

    def perf_export(self):
        """把本次采到的全部样本导出为 HTML 报告 + CSV（每台设备一份）。"""
        with self._perf_lock:
            sessions = dict(self._perfs)
        if not sessions:
            self._push_status("err", "⚠ 还没有采样数据，先开始监控再导出报告。")
            return {"ok": False, "reason": "no_data"}
        saved, errors, total_rows, total_samples = [], {}, 0, 0
        th, _th_errs, _expr = self._perf_thresholds()
        compare_entries = []
        for s, mon in sessions.items():
            samples = mon.all_samples()
            if not samples:
                continue
            info = dict(mon.info)
            info["interval"] = mon.interval
            compare_entries.append({
                "serial": s, "label": self._perf_label(info, s),
                "samples": samples, "info": info, "interval": mon.interval,
            })
            try:
                res = perf_write_report(samples, info, self._default_save_dir(), th)
            except Exception as ex:
                errors[s] = str(ex)
                continue
            res["serial"] = s
            res["samples"] = len(samples)
            saved.append(res)
            total_rows += res.get("rows", 0)
            total_samples += len(samples)
        if not saved:
            why = next(iter(errors.values()), "没有采样数据")
            self._push_status("err", "⚠ 报告生成失败：%s" % why)
            return {"ok": False, "reason": why, "errors": errors}
        # 多设备时再出一份「横向对比」报告：三份独立报告摊在桌上自己对照，
        # 是导出这件事里最费劲的一步，合并成一份能省掉全部来回翻页。
        compare = ""
        if len(compare_entries) > 1:
            try:
                res = perf_write_compare(compare_entries, self._default_save_dir(), th)
                compare = res.get("html") or ""
            except Exception as ex:
                errors["compare"] = str(ex)
        if len(saved) == 1:
            msg = "✓ 性能报告已生成：%s（%d 个采样点）" % (
                saved[0]["html"], total_rows)
        elif compare:
            msg = "✓ 已生成 %d 份设备报告 + 1 份对比报告（共 %d 个采样点）：%s" % (
                len(saved), total_rows, os.path.dirname(compare) or ".")
        else:
            msg = "✓ 已生成 %d 份性能报告（共 %d 个采样点）：%s" % (
                len(saved), total_rows, os.path.dirname(saved[0]["html"]) or ".")
        self._push_status("ok", msg, toast=True)
        return {"ok": True, "files": saved, "html": saved[0]["html"],
                "csv": saved[0]["csv"], "rows": total_rows,
                "samples": total_samples, "sessions": len(saved),
                "compare": compare, "errors": errors}

    def open_save_dir(self, dir_path=None):
        """在系统文件管理器打开保存目录（Windows 用 explorer / startfile）。"""
        d = (dir_path or "").strip() or self._default_save_dir()
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass
        if not os.path.isdir(d):
            self._push_status("err", "⚠ 目录不存在：%s" % d)
            return {"ok": False}
        try:
            if sys.platform.startswith("win"):
                os.startfile(d)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", d])
            else:
                subprocess.Popen(["xdg-open", d])
            self._push_status("info", "📂 已打开目录：%s" % d)
            return {"ok": True}
        except Exception as e:
            self._push_status("err", "⚠ 无法打开目录 %s: %s" % (d, e))
            return {"ok": False, "text": str(e)}

    # ==================================================================
    # 文件管理
    # ==================================================================
    @staticmethod
    def _parent_dir(path):
        p = (path or "/").rstrip("/")
        if "/" not in p:
            return "/"
        return p.rsplit("/", 1)[0] or "/"

    def file_list(self, serial, path):
        if not serial:
            return {"ok": False, "reason": "no_device"}
        # 每次列目录用**唯一** worker key + 记录「该设备最新一次请求」：
        #  · 唯一 key：旧实现固定用 "file_<serial>"，上一次 `ls -la` 还没结束时
        #    （大目录 / 慢设备）用户再点进另一个目录，Workers 会按同名去重直接
        #    丢弃新请求且不报错 —— 界面停在旧目录，看起来「点了没反应」；
        #  · 最新序号：新请求发起后，先前那次迟到的响应会被丢弃，避免旧目录的
        #    内容覆盖刚打开的目录。
        seq = next(self._file_seq)
        self._file_req[serial] = seq
        self.workers.spawn("filelist_%s_%d" % (serial, seq),
                           self._run_file_op, self._do_file_list,
                           serial, path, seq)
        return {"ok": True}

    def _do_file_list(self, serial, path, seq=None):
        entries, err = self.file_svc.list_dir(serial, path)
        if seq is not None and self._file_req.get(serial) != seq:
            return          # 已有更新的一次列目录请求，丢弃这次迟到的结果
        if err:
            self._push_status("err", "⚠ 列出目录失败 %s: %s" % (path, err))
            self.bus.push("file", {"serial": serial, "path": path,
                                   "error": err})
        else:
            self.bus.push("file", {"serial": serial, "path": path,
                                   "entries": entries})

    def _file_refresh(self, serial, path):
        self.file_list(serial, self._parent_dir(path))

    def _file_op(self, serial, do_fn, *args, key=None):
        """文件操作公共入口：无设备兜底 + 后台线程派发 + 立即返回。

        key 为空时退化为 "fileop_<serial>"（同名存活任务不重复启动，用于
        mkdir/touch/remove/rename 等互斥场景）；key 非空时作为后台线程去重键。
        批量下载必须用唯一 key（见 file_download），否则同一设备的多个文件会被
        Workers 去重掉、只剩第一个真正下载。

        被去重挡下时**不再谎报成功**：返回 busy 并给出提示，否则用户点了「新建
        文件夹」却什么都没发生、也没有任何解释。
        """
        if not serial:
            return {"ok": False, "reason": "no_device"}
        k = key or ("fileop_%s" % serial)
        if self.workers.is_running(k):
            self._push_status("warn", "⚠ 上一项文件操作尚未完成，请稍候再试。")
            return {"ok": False, "reason": "busy"}
        self.workers.spawn(k, self._run_file_op, do_fn, serial, *args)
        return {"ok": True}

    # 文件操作的中文标签（仅用于把未预期异常翻译成人话）
    _FILE_OP_LABELS = {
        "_do_file_list": "列出目录", "_do_file_mkdir": "创建目录",
        "_do_file_touch": "创建文件", "_do_file_remove": "删除",
        "_do_file_rename": "重命名", "_do_file_upload_data": "上传",
        "_do_file_download": "下载", "_do_file_view": "查看",
    }

    def _run_file_op(self, do_fn, serial, *args):
        """后台执行文件操作，并把未预期异常转成用户可见的状态。

        没有这层兜底时，`subprocess.TimeoutExpired`（adb push/pull 大文件超过
        120s 超时）会直接杀死 worker 线程，只落一份用户看不到的 crash 日志：
        界面上表现为「点了下载/刷新/查看毫无反应」，且该设备的同名任务一直占着
        去重键，后续同类操作全被静默吞掉。
        """
        try:
            do_fn(serial, *args)
        except Exception as ex:
            label = self._FILE_OP_LABELS.get(
                getattr(do_fn, "__name__", ""), "文件操作")
            self._push_status("err", "⚠ %s失败 %s：%s" % (label, serial, ex))

    def file_mkdir(self, serial, path):
        return self._file_op(serial, self._do_file_mkdir, path)

    def _do_file_mkdir(self, serial, path):
        ok, err = self.file_svc.make_dir(serial, path)
        if ok:
            self._push_status("ok", "✓ 已创建目录: %s" % path)
        else:
            self._push_status("err", "⚠ 创建目录失败 %s: %s" % (path, err))
        self._file_refresh(serial, path)

    def file_touch(self, serial, path):
        return self._file_op(serial, self._do_file_touch, path)

    def _do_file_touch(self, serial, path):
        ok, err = self.file_svc.touch(serial, path)
        if ok:
            self._push_status("ok", "✓ 已创建文件: %s" % path)
        else:
            self._push_status("err", "⚠ 创建文件失败 %s: %s" % (path, err))
        self._file_refresh(serial, path)

    def file_remove(self, serial, paths):
        paths = paths if isinstance(paths, list) else [paths]
        if not paths:
            return {"ok": False, "reason": "empty"}
        return self._file_op(serial, self._do_file_remove, list(paths))

    def _do_file_remove(self, serial, paths):
        ok, err = self.file_svc.remove(serial, paths)
        if ok:
            self._push_status("ok", "✓ 已删除 %d 个项" % len(paths))
        else:
            self._push_status("err", "⚠ 删除失败: %s" % err)
        if paths:
            self._file_refresh(serial, paths[0])

    def file_rename(self, serial, old, new):
        return self._file_op(serial, self._do_file_rename, old, new)

    def _do_file_rename(self, serial, old, new):
        ok, err = self.file_svc.rename(serial, old, new)
        if ok:
            self._push_status("ok", "✓ 重命名: %s -> %s" % (old, new))
        else:
            self._push_status("err", "⚠ 重命名失败: %s" % err)
        self._file_refresh(serial, old)

    def file_upload_data(self, serial, name, b64, remote):
        """前端以 base64 传文件内容（浏览器不暴露本地路径），后端落地后 push。

        与下载同理：每个文件一个独立 worker key，否则「一次选多个文件上传」会
        被 "fileop_<serial>" 去重吞掉 —— 只有第一个真正传到设备。
        """
        return self._file_op(serial, self._do_file_upload_data, name, b64, remote,
                             key="fileup_%s_%d" % (serial, next(self._file_seq)))

    def _do_file_upload_data(self, serial, name, b64, remote):
        import base64
        import tempfile
        import uuid
        # 临时文件名带随机串：多设备/多文件并行上传同名文件时，固定名会互相覆盖，
        # 导致其中一个线程上传的是别人的内容（或中途被删而上传失败）。
        # 前端传来的 name 一律先取 basename 并净化：它若含路径分隔符，会把临时文件
        # 写到 %TEMP% 之外（甚至覆盖任意可写文件）。
        tmp = os.path.join(
            tempfile.gettempdir(),
            "adb_up_%s_%s" % (uuid.uuid4().hex[:8],
                              safe_name(os.path.basename(name or ""))))
        try:
            with open(tmp, "wb") as f:
                f.write(base64.b64decode(b64 or ""))
        except Exception as e:
            self._push_status("err", "⚠ 解码上传文件失败：%s" % e)
            return
        # try/finally：upload 抛异常（大文件 push 超过 120s 超时、adb 中途消失）时
        # 旧实现会跳过 os.remove，每次失败都在 %TEMP% 留下一个多 MB 的孤儿文件。
        try:
            ok, err = self.file_svc.upload(serial, tmp, remote)
        finally:
            try:
                os.remove(tmp)
            except Exception:
                pass
        if ok:
            self._push_status("ok", "✓ 上传完成: %s" % remote)
        else:
            self._push_status("err", "⚠ 上传失败 %s: %s" % (remote, err))
        self._file_refresh(serial, remote)

    def file_download(self, serial, remote, local_dir):
        # 每个文件一个独立 worker key（含序列号），保证同一设备批量「下载选中」
        # 时所有文件各自成线程并行 pull，不会被 "fileop_<serial>" 去重吞掉。
        return self._file_op(
            serial, self._do_file_download, remote,
            local_dir or self._default_save_dir(),
            key="filedl_%s_%d" % (serial, next(self._file_seq)))

    def _do_file_download(self, serial, remote, local_dir):
        path, err = self.file_svc.download(serial, remote, local_dir)
        if path:
            self._push_status("ok", "✓ 已下载: %s" % path)
        else:
            self._push_status("err", "⚠ 下载失败 %s: %s" % (remote, err))

    def file_view(self, serial, path):
        # 查看同样用唯一 key：连续点开两个文件的「查看」时，固定 key 会让第二个
        # 请求被去重静默丢弃（用户看到的是上一个文件的内容 / 什么都没发生）。
        return self._file_op(serial, self._do_file_view, path,
                             key="fileview_%s_%d" % (serial,
                                                     next(self._file_seq)))

    def open_local_file(self, path):
        """用系统默认程序打开本地文件（大文件查看弹窗的「查看」按钮）。

        路径来自本程序 pull 落地的临时文件；仍做存在性校验，
        避免把明显非法的输入透传给系统打开机制。
        """
        try:
            if not path or not os.path.isfile(path):
                return {"ok": False, "reason": "文件不存在或已被清理"}
            if os.name == "nt":
                os.startfile(path)                    # Windows：文件关联程序
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "reason": str(e)}

    def _do_file_view(self, serial, path):
        res, err = self.file_svc.view(serial, path)
        if err:
            self._push_status("err", "⚠ 查看失败 %s: %s" % (path, err))
            return
        self.bus.push("file_view", {
            "serial": serial, "path": path,
            "text": res.get("text"), "local": res.get("local"),
            "note": res.get("note"),
        })

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def get_state(self):
        """调试 / 对账用：一次性取后端状态快照。"""
        snapshot = self.state.snapshot()
        snapshot["devices"] = self.devices.get_items()
        snapshot["workers"] = self.workers.running_keys()
        return snapshot
