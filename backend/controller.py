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
from pathlib import Path
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
    resource_path, unique_path,
)
from core.commands import load_commands, save_click_deltas, save_user_commands, merge_builtins
from core.prefs import (load_prefs, load_prefs_checked, save_prefs,
                         save_prefs_checked, apply_adb_dir, get_pref, prefs_path,
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

PERF_THRESHOLDS = DEFAULT_THRESHOLDS
PERF_MAX_DEVICES = 4
PERF_PKG_CACHE_S = 120
_EXIT_RE = re.compile(r"^exit(?:\s+-?\d+)?$", re.IGNORECASE)
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

__all__ = [
    "AUTO_REFRESH_MS",
    "AppState",
    "BackendBus",
    "DEFAULT_INTERVAL",
    "DEFAULT_THRESHOLDS",
    "DeviceAudioCapture",
    "DeviceManager",
    "FileService",
    "FrameServer",
    "KEY_POINTER_LOCATION",
    "KEY_SHOW_TOUCHES",
    "LogcatCapture",
    "LogcatMonitor",
    "MicRecorder",
    "PERF_CRIT_RATIO",
    "PERF_MAX_DEVICES",
    "PERF_MAX_INTERVAL",
    "PERF_MIN_INTERVAL",
    "PERF_PKG_CACHE_S",
    "PERF_THRESHOLDS",
    "Path",
    "PerfMonitor",
    "PipeMirror",
    "REC_DEATH_CHECK_S",
    "SHELL_INTERACTIVE_RE",
    "ScrcpyLauncher",
    "ScreenCapturer",
    "ShellSession",
    "SnapMirror",
    "VERSION",
    "VideoRecorder",
    "Workers",
    "_EXIT_RE",
    "_UPDATE_HOSTS",
    "_have_ffmpeg",
    "_host_allowed",
    "adb_kwargs",
    "apkinfo",
    "apply_adb_dir",
    "clipboard",
    "datetime",
    "device_is_root",
    "devinfo",
    "diag",
    "ffmpeg_mux",
    "find_player",
    "find_scrcpy",
    "get_pref",
    "is_subshell_command",
    "itertools",
    "json",
    "load_commands",
    "load_prefs",
    "load_prefs_checked",
    "merge_adb_shell_commands_detailed",
    "merge_builtins",
    "needs_device",
    "os",
    "perf_build_thresholds",
    "perf_default_threshold_expr",
    "perf_format_thresholds",
    "perf_list_installed",
    "perf_parse_thresholds",
    "perf_pkg_display",
    "perf_rule_text",
    "perf_threshold_items",
    "perf_write_compare",
    "perf_write_report",
    "plan_size",
    "prefs_path",
    "probe_player",
    "program_dir",
    "re",
    "resolve_save_dir",
    "resource_path",
    "root_intent",
    "safe_name",
    "save_click_deltas",
    "save_prefs",
    "save_prefs_checked",
    "save_user_commands",
    "scrcpy_probe_info",
    "subprocess",
    "sys",
    "tempfile",
    "threading",
    "time",
    "tmpfiles",
    "transform",
    "unique_path",
    "updater",
    "uuid",
    "wifi",
    "zipfile",
]

# ---------------------------------------------------------------------------
# WebApi 由 backend.controllers 的各领域 Mixin 组合（方法实现见子模块）
# ---------------------------------------------------------------------------
from backend.controllers import (
    WebApiBase, DeviceMixin, CommandMixin, AutoRefreshMixin,
    LogcatMixin, SettingsMixin, ApkMixin, DeviceInfoMixin,
    UpdateMixin, ScreenshotMixin, RecordMixin, PerfMixin,
    FileMixin
)

class WebApi(WebApiBase, DeviceMixin, CommandMixin, AutoRefreshMixin, LogcatMixin, SettingsMixin, ApkMixin, DeviceInfoMixin, UpdateMixin, ScreenshotMixin, RecordMixin, PerfMixin, FileMixin):
    """pywebview js_api：前端 window.pywebview.api.<method> 的调用面。

    方法按领域拆分到上方各 mixin 类，由本类统一继承；
    方法名与旧版完全一致，RPC 契约不变。
    """
    pass
