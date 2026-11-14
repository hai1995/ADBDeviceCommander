"""
backend.state —— 集中状态管理（前端可见状态的唯一数据源，线程安全）
====================================================================
职责：
  * 生命周期：booted / shutting_down；
  * 启动加载内容：快捷命令列表与其解析警告；
  * 运行态：正在执行的后台命令数、前端「停止」按钮可用性。

所有方法都在锁内完成读改写并返回「是否发生变化」，供 controller 层决定
要不要向事件总线广播，避免重复/冗余事件刷屏。
本模块不 import controller / webview，可被任何前端实现（Web / CLI）复用。
"""
import threading

from core.constants import LOGCAT_BUFFERS, STATE_LABEL, VERSION


class AppState:
    """应用级状态的线程安全容器。

    约定：busy = 正在执行的后台命令数 > 0 或 处于 adb shell 交互态。
    busy 变化时前端需要同步「停止」按钮，故所有变更方法都返回
    (busy, changed)，changed 为 True 表示 busy 相对上一次有翻转。
    """

    def __init__(self, adb_path: str = "adb"):
        self._lock = threading.Lock()
        self.booted = False
        self.shutting_down = False
        self.adb_path = adb_path
        self.version = VERSION
        self.commands = []
        self.cmd_warnings = []
        self._running = 0
        self._interactive = False
        self._busy = False

    def mark_booted(self, commands, warnings, adb_path=None, version=None):
        """boot 完成：写入命令列表/警告与配置，并返回 booted 事件载荷。"""
        with self._lock:
            self.commands = list(commands or [])
            self.cmd_warnings = list(warnings or [])
            if adb_path is not None:
                self.adb_path = adb_path
            if version is not None:
                self.version = version
            self.booted = True
            return {
                "warnings": list(self.cmd_warnings),
                "adb": self.adb_path,
                "version": self.version,
                "state_labels": dict(STATE_LABEL),
                "lc_buffers": {k: list(v) for k, v in LOGCAT_BUFFERS.items()},
                "commands": [
                    {
                        "id": c.get("id", ""),
                        "name": c.get("name", ""),
                        "labels": list(c.get("labels", [])),
                        "commands": [
                            {"command": e.get("command", ""), "delay": e.get("delay", 0)}
                            for e in (c.get("commands") or [])
                        ],
                        "clickCount": c.get("clickCount", 0),
                        "inputOnly": bool(c.get("inputOnly")),
                        "builtin": bool(c.get("builtin")),
                        "section": c.get("section", ""),
                        "scope": c.get("scope", ""),
                    }
                    for c in self.commands
                ],
            }

    def mark_shutdown(self):
        """窗口关闭：置 shutting_down，供后台轮询线程退出。"""
        with self._lock:
            self.shutting_down = True

    def begin_run(self):
        """一条后台命令开始执行。返回 (busy, changed)。"""
        with self._lock:
            self._running += 1
            return self._sync_busy_locked()

    def end_run(self):
        """一条后台命令执行结束。返回 (busy, changed)。"""
        with self._lock:
            self._running = max(0, self._running - 1)
            return self._sync_busy_locked()

    def sync_stop(self, interactive: bool = False):
        """外部会话交互态变化时主动同步一次。返回 (busy, changed)。"""
        with self._lock:
            self._interactive = bool(interactive)
            return self._sync_busy_locked()

    def _sync_busy_locked(self):
        busy = self._running > 0 or self._interactive
        changed = busy != self._busy
        if changed:
            self._busy = busy
        return busy, changed

    def is_busy(self):
        with self._lock:
            return self._busy

    def running_count(self):
        with self._lock:
            return self._running

    def snapshot(self):
        """一次性取前端常用状态（供调试 / 对账）。"""
        with self._lock:
            return {
                "booted": self.booted,
                "shutting_down": self.shutting_down,
                "adb": self.adb_path,
                "version": self.version,
                "busy": self._busy,
                "running": self._running,
                "interactive": self._interactive,
                "command_count": len(self.commands),
            }