# -*- coding: utf-8 -*-
"""
core.constants —— 全局常量、正则、纯函数（不依赖任何 UI）。
与 旧 Tk 版（已移除）（Tk 版）顶部同源；Web 版统一引用此处。
"""
import os
import re
import sys
import ctypes

# 项目根目录（core 位于 <root>/core/）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
# 设备连接状态自动轮询间隔（毫秒）。
AUTO_REFRESH_MS = 5000
# 设备「断开宽限周期」：自动轮询里某台设备从列表消失后，先保留其勾选记忆若干个
# 刷新周期（不在列表里展示，但重连后自动恢复勾选）；超过该周期仍未重连才当作
# 真正断开、遗忘其勾选。用于消除 adb 轮询偶发抖动（设备短暂失联）导致的误取消勾选。
# 3 周期 × 5s = 15s。
DEVICE_GONE_GRACE_CYCLES = 3
# 宽限期内「消失但未真正断开」的设备在 UI 快照里的虚拟 state。
# 该设备此刻不在 `adb devices` 列表里（轮询抖动 / adb server 重启 / USB 重枚举），
# 但仍保留勾选记忆并继续以「置灰卡片」展示，避免用户看到设备瞬间消失、误以为
# 「程序自动断连」。is_usable() 对其恒为 False，不会成为命令下发目标。
ABSENT_STATE = "reconnecting"
# adb devices 单次轮询超时（秒）。轮询间隔仅 5s，超时不宜太长，否则一次卡死
# 会占满后续多个轮询周期（_busy 互斥虽防叠加，但用户侧感知为「列表长时间不动」）。
DEVICE_POLL_TIMEOUT = 10
# adb devices 结果可疑时的重试次数：本次解析结果为空、但上一轮还有已知设备时，
# 立即原样重试（间隔 DEVICE_RETRY_GAP_S 秒）。adb server 被其他工具（Android
# Studio / 另一份 adb 客户端）重启的瞬间，首次调用常返回空列表或超时。
DEVICE_RETRY_MAX = 1
DEVICE_RETRY_GAP_S = 0.6
# 连续刷新失败达到此次数后，尝试 `adb start-server` 自愈一次（server 被杀死时
# 后续所有调用都会立刻失败，不自愈则要等到用户手动干预）。
DEVICE_SERVER_HEAL_AFTER = 2
# 自动轮询刷新失败的提示最小间隔（秒）：失败时保留上次列表并按此间隔限频播报，
# 避免每 5s 一条把状态栏刷爆（手动刷新不受限，立即播报）。
FAIL_NOTICE_INTERVAL_S = 30.0
VERSION = "2026.1030.1454"

# 全局强调色（iOS 系统蓝），Web 版通过 CSS 变量使用
ACCENT = "#0A84FF"

# logcat 缓冲区可选范围。-b 后跟的缓冲区名；crash/system 在某些设备上需要
# 额外权限，采集失败会单独告警而不影响其它缓冲区。
LOGCAT_BUFFERS = {
    "main（主日志）": ["main"],
    "system（系统）": ["system"],
    "events（事件）": ["events"],
    "crash（崩溃）": ["crash"],
    "全部（main+system+events+crash）": ["main", "system", "events", "crash"],
}

# threadtime 格式：日期 时间 PID TID 级别 Tag: 消息
#   08-29 10:23:45.123  1234  1234 E TagName: the message
#
# tag 按 aosp 的 "%-8s: " 左对齐补空格到 8 列，所以短 tag 的冒号前必有若干空格：
#   08-29 10:23:45.123  1234  1234 I chatty  : uid=1000 expire 5 lines
#   08-29 10:23:45.123  1234  1234 E libc    : Fatal signal 11 (SIGSEGV)
# 因此 tag 与冒号之间必须允许空白（\s*），否则这类行整行判成「非 threadtime」
# 而走原样透传分支 —— 级别 / 仅异常 / 关键字过滤会对它们全部失效，libc 的
# native crash 也不再被识别为异常。
LOGCAT_RE = re.compile(
    r"^\d\d-\d\d \d\d:\d\d:\d\d\.\d+\s+\d+\s+\d+\s+([VDIWEF])\s+(\S+?)\s*:(.*)$"
)

# 异常/崩溃特征：Java 堆栈、AndroidRuntime、Native crash、信号量崩溃、ANR 等。
LOGCAT_EXC_RE = re.compile(
    r"(FATAL EXCEPTION|AndroidRuntime|java\.lang\.|j\.?ni\.|Caused by\s|"
    r"at [a-zA-Z][\w.$]*\(|Native crash|signal \d+ \(|tombstone|"
    r"Stack trace|backtrace|"
    r"\b(OutOfMemory|NullPointer|IllegalState|Runtime|IndexOutOfBound|"
    r"Security|ClassNotFound|ActivityNotFound|ServiceNotFound)"
    r"[A-Za-z]*Exception\b|\bANR\b|\bcrash\b|\bFATAL\b)",
    re.IGNORECASE,
)

# logcat 文本最多保留的行数（环形缓存，防止内存膨胀）
LOGCAT_MAX_LINES = 20000
# 单次轮询最多消费/分类多少条
LOGCAT_BATCH_MAX = 2000
# 渲染轮询间隔（毫秒）
LOGCAT_POLL_MS = 40
# 过滤输入防抖（毫秒）
LOGCAT_RERENDER_DEBOUNCE_MS = 250

# 实时监控「展示行数」软上限（行/秒，滑动窗口）。
# 设备日志洪流（嘈杂应用/chatty 刷屏）下，即便总线有积压背压，主线程也会被
# 「JSON 跨进程传输 + 解析 + 分帧渲染」持续占满 —— 表现为一开始监控整个
# 程序就卡顿。超出上限的行在源头直接丢弃（计数并在状态栏节流提示），
# 优先保住交互流畅；抓取（落盘）模式不受此限，文件里仍是全量。
LOGCAT_DISPLAY_MAX_LPS = 2500
# 「已丢弃 N 行」提示的最小间隔（秒）：高频丢弃时不要把状态栏也刷爆
LOGCAT_DROP_NOTICE_SEC = 3.0
# 两次提示之间至少累积多少丢弃行才值得再提示一次
LOGCAT_DROP_NOTICE_MIN = 50

# 录屏进程「意外死亡」检测步长（秒）：自动轮询线程按此间隔询问 VideoRecorder
# 是否有设备的 screenrecord 在无人停止的情况下退出（adb root / 设备重启 adbd
# 的典型后果）。检测到即自动收尾会话并让前端复位界面，否则界面会一直停在
# 「录制中」，用户点停止后才在约 10 秒的 pull 重试后看到「缺 moov 头」。
REC_DEATH_CHECK_S = 1.0

# adb devices 输出的 state 字段 -> 中文说明
STATE_LABEL = {
    "device": "在线",
    "unauthorized": "未授权（请在设备屏幕上确认调试授权）",
    "offline": "离线（adb 已失去连接）",
    "recovery": "Recovery 模式",
    "sideload": "Sideload 模式",
    "no permissions": "无权限（注意 udev / 驱动）",
    # 宽限期内短暂失联的虚拟状态（设备卡置灰展示，见 core.devices.plan_devices）
    "reconnecting": "短暂失联（重连中）",
}

# WinMM waveIn 录音用到的 WAVEHDR 结构（模块级定义，保证录音器与测试共用同一内存布局）
class _WAVEHDR(ctypes.Structure):
    _fields_ = [
        ("lpData", ctypes.c_void_p),
        ("dwBufferLength", ctypes.c_uint32),
        ("dwBytesRecorded", ctypes.c_uint32),
        ("dwUser", ctypes.c_void_p),
        ("dwFlags", ctypes.c_uint32),
        ("dwLoops", ctypes.c_uint32),
        ("reserved", ctypes.c_void_p),
    ]


def state_label(state: str) -> str:
    """把 adb 的 state 字段翻译成中文说明；未知状态原样返回。"""
    return STATE_LABEL.get((state or "").strip(), state or "未知")


# Windows 文件名非法字符 + 控制字符（无线 ADB 的序列号形如 192.168.1.5:5555，
# 冒号正踩中；直接拼进文件名会让 open() 抛 FileNotFoundError，功能静默失败）。
_UNSAFE_NAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(text, fallback: str = "device") -> str:
    """把任意字符串（设备序列号等）净化为可安全用于文件名的片段。

    替换 Windows 非法字符为 `_`，并去掉 Windows 同样不接受的首尾空白与
    尾部点/空格；净化后不含任何字母数字（如全是非法字符）时回退 fallback。
    设备名仅用于展示/文件名，不影响 adb 命令里使用的原始序列号。
    """
    s = _UNSAFE_NAME_RE.sub("_", str(text if text is not None else ""))
    s = s.strip().rstrip(". ")
    if not any(ch.isalnum() for ch in s):
        return fallback
    return s


def is_usable(state: str) -> bool:
    """只有 state == "device" 才能下发命令"""
    return (state or "").strip() == "device"


def posix_join(a: str, b: str) -> str:
    """按 POSIX 语义拼接两段路径并规范化斜杠。"""
    if not a or a == "/":
        return "/" + (b or "").lstrip("/")
    a = a.rstrip("/")
    b = (b or "").lstrip("/")
    if not b:
        return a or "/"
    return a + "/" + b


def fmt_size(n: int) -> str:
    """把字节数格式化为人类可读字符串。"""
    if n < 0:
        return ""
    if n < 1024:
        return "%d B" % n
    for unit in ("KB", "MB", "GB", "TB"):
        n /= 1024.0
        if n < 1024:
            if abs(n - int(n)) < 1e-6:
                return "%d %s" % (int(n), unit)
            if n >= 10:
                return "%d %s" % (int(n), unit)
            return "%.1f %s" % (n, unit)
    return "%d TB" % int(n)


def parse_ls_output(text: str):
    """解析 `ls -la` / `ls -la --time-style=long-iso` 输出。

    返回列表，每项为 dict：
      perm, links, owner, group, size, date, name, target, is_dir, is_link
    """
    out = []
    if not text:
        return out
    for line in text.splitlines():
        line = line.rstrip("\n")
        if not line.strip():
            continue
        parts = line.split()
        if not parts:
            continue
        if parts[0] in ("total", "Total"):
            continue
        perm = parts[0]
        if len(perm) < 2 or perm[0] not in "bcdlsp-":
            continue
        if len(parts) < 6:
            continue
        try:
            size = int(parts[4])
        except ValueError:
            continue
        # 日期有两种常见格式：
        #   1) 2024-01-01 12:00  (long-iso)
        #   2) Jan  1 12:00  或  Jan  1  2024
        if re.match(r"\d{4}-\d{2}-\d{2}", parts[5]):
            if len(parts) >= 7 and re.match(r"\d{2}:\d{2}", parts[6]):
                date = parts[5] + " " + parts[6]
                name_idx = 7
            else:
                date = parts[5]
                name_idx = 6
        else:
            # Mon D HH:MM 或 Mon D YYYY
            if len(parts) >= 8:
                date = " ".join(parts[5:8])
                name_idx = 8
            elif len(parts) >= 7:
                date = " ".join(parts[5:7])
                name_idx = 7
            else:
                continue
        if name_idx >= len(parts):
            continue
        name = " ".join(parts[name_idx:])
        target = None
        if " -> " in name:
            name, target = name.split(" -> ", 1)
        out.append({
            "perm": perm,
            "links": parts[1],
            "owner": parts[2],
            "group": parts[3],
            "size": size,
            "date": date,
            "name": name,
            "target": target,
            "is_dir": perm.startswith("d"),
            "is_link": perm.startswith("l"),
        })
    return out


def no_window_flags() -> int:
    """Windows 下隐藏子进程控制台窗口的 creationflags（非 Windows 恒为 0）。

    打包成 --windowed 的 GUI 进程本身没有控制台，而 adb / ffmpeg 都是控制台程序，
    默认会新建一个黑窗：设备轮询每 5s 一次，表现为「一闪一闪的黑框」。
    """
    import subprocess as _sp
    if sys.platform.startswith("win"):
        return getattr(_sp, "CREATE_NO_WINDOW", 0)
    return 0


def adb_kwargs(timeout=None, **extra) -> dict:
    """adb / ffmpeg 子进程的统一参数：UTF-8 解码 + 隐藏控制台窗口。

    * adb 输出固定为 UTF-8（设备端中文文件名/日志），而中文 Windows 的默认编码
      是 cp936；不显式指定 encoding 就会解码成乱码。
    * 一并带上 no_window_flags()，避免打包 GUI 下每次调用闪黑窗。
    """
    kw = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "creationflags": no_window_flags(),
    }
    if timeout is not None:
        kw["timeout"] = timeout
    kw.update(extra)
    return kw


def adb_popen_kwargs(**extra) -> dict:
    """Popen 版统一参数（管道输出场景：logcat 监控 / 抓取 / 录屏）。"""
    kw = {
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "creationflags": no_window_flags(),
    }
    kw.update(extra)
    return kw


def program_dir() -> str:
    """程序自身所在目录（exe 旁目录 / 开发态项目根）。

    命令导入 / 导出默认值落到此处：用户不指定路径时，备份文件就生成在
    程序同目录，方便随程序一起拷贝分发，也符合「程序运行处的路径」直觉。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return PROJECT_ROOT


def resource_path(rel: str) -> str:
    """解析打包态 / 开发态下的资源路径。

    优先级：运行文件（exe 或脚本）同目录  >  PyInstaller 解包目录(_MEIPASS)。

    打包后，可编辑资源（commands.json / assets / frontend）优先使用 exe
    旁那份；不存在时才回退到内置解包副本。
    """
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base_dir = PROJECT_ROOT
    local = os.path.join(base_dir, rel)
    if os.path.exists(local):
        return local
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return os.path.join(meipass, rel)
    return local
