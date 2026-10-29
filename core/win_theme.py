# -*- coding: utf-8 -*-
"""
core.win_theme —— 让原生窗口标题栏跟随界面的深色主题（Windows）
====================================================================
背景
----
本程序用 **原生标题栏**（系统绘制，没有自绘标题栏）。它的配色默认跟随
Windows 的「应用主题」：用户系统是浅色时，深色界面顶上就压着一根白/浅灰
的标题栏，和整屏深蓝黑格格不入。

做法
----
Windows 10 1809+ 的 DWM 提供了改标题栏配色的属性：

  * DWMWA_USE_IMMERSIVE_DARK_MODE (20；1809~1903 上是 19) —— 深色标题栏
  * DWMWA_CAPTION_COLOR (35，Win11 22000+) —— 标题栏底色（COLORREF）
  * DWMWA_TEXT_COLOR    (36，Win11 22000+) —— 标题文字颜色
  * DWMWA_BORDER_COLOR  (34，Win11 22000+) —— 窗口外框颜色

只调 20 也能让标题栏变深，但 Win11 下仍是系统默认的深灰（#202020 附近），
和界面的 #0b0f14 差一截，还是会看出「两块拼在一起」。所以三个颜色属性一并
写，老系统写不进去（返回失败）就只留深色模式这一档，属于渐进降级。

为什么不改成无边框自绘标题栏
----------------------------
自绘要自己实现拖动 / 双击最大化 / 贴边分屏 / 高 DPI 缩放 / 系统菜单，
每一项都要在 Win32 层踩一遍坑，收益只是「颜色完全可控」。改 DWM 属性
只有十几行，且保留系统的全部窗口行为。

可测性
------
本模块把「算什么值」和「怎么调系统」分开：colorref / title_attributes
是纯函数，apply_to_hwnd 接受可注入的 setter，attach 负责找窗口句柄并重试。
非 Windows 平台全程 no-op（找不到 dwmapi 直接返回 unsupported），
Linux CI 上跑单测不会有任何副作用。
"""
import os
import sys
import time

# 与 frontend/css/app.css 的 :root 保持一致（单一视觉来源在 CSS，这里是它的
# 镜像）。改主题色时两处一起改：标题栏底色 = 画布色，标题文字 = --text。
TITLE_BG = "#0b0f14"        # --bg
TITLE_TEXT = "#e9f0f8"      # --text
TITLE_BORDER = "#1b2532"    # 比 --surface-2 略深：外框要能看出边界，又不能抢眼

# DWM 属性编号（见 dwmapi.h）。19 是 Windows 10 1809~1903 的旧编号，
# 20 从 1909 起沿用；两个都试，写不进去的那个会被忽略。
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36


def colorref(hex_color):
    """'#rrggbb' → COLORREF（0x00BBGGRR）。

    Windows 的 COLORREF 是 **BGR** 顺序且高位为 0，直接把 RGB 整数塞进去
    会得到「红蓝互换」的颜色（深蓝黑 #0b0f14 会变成 #140f0b 的暗红）。
    非法输入返回 None，由调用方跳过该属性而不是整条失败。
    """
    if not isinstance(hex_color, str):
        return None
    s = hex_color.strip().lstrip("#")
    if len(s) == 3:                       # #abc → #aabbcc
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        return None
    try:
        r = int(s[0:2], 16)
        g = int(s[2:4], 16)
        b = int(s[4:6], 16)
    except ValueError:
        return None
    return (b << 16) | (g << 8) | r


def title_attributes(bg=TITLE_BG, text=TITLE_TEXT, border=TITLE_BORDER):
    """要写入的 (属性, 值) 列表；颜色非法时跳过对应项。

    顺序有意为之：深色模式先写（老系统只有它生效），颜色后写。
    """
    out = [(DWMWA_USE_IMMERSIVE_DARK_MODE, 1)]
    for attr, color in ((DWMWA_CAPTION_COLOR, bg),
                        (DWMWA_TEXT_COLOR, text),
                        (DWMWA_BORDER_COLOR, border)):
        v = colorref(color)
        if v is not None:
            out.append((attr, v))
    return out


def _dwm_setter():
    """返回一个 (hwnd, attr, value) -> None 的写入器；非 Windows 返回 None。

    用之前才 import ctypes 的 windll：Linux/macOS 上没有 windll，
    模块顶层直接摸它会让 import 本模块就崩（单测在 Linux 上跑）。
    """
    if not sys.platform.startswith("win"):
        return None
    try:
        import ctypes
        dwmapi = ctypes.windll.dwmapi
    except Exception:
        return None

    def _set(hwnd, attr, value):
        import ctypes
        v = ctypes.c_int(int(value))
        rc = dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(int(hwnd)), ctypes.c_uint(int(attr)),
            ctypes.byref(v), ctypes.sizeof(v))
        # 非 0 = 该系统版本不认识这个属性（老 Windows 上没有 34/35/36）
        if rc != 0:
            raise OSError("DwmSetWindowAttribute(%d) 返回 %d" % (attr, rc))

    return _set


def apply_to_hwnd(hwnd, bg=TITLE_BG, text=TITLE_TEXT, border=TITLE_BORDER,
                  setter=None):
    """把深色标题栏属性写到窗口句柄上。

    返回 {"ok": bool, "applied": [属性], "failed": [属性], "reason": str}。
    ok 的判据是「至少写进去一项」：Win10 只认 20，Win11 认全套，两者都算成功。
    """
    if not hwnd:
        return {"ok": False, "applied": [], "failed": [], "reason": "no_window"}
    setter = setter or _dwm_setter()
    if setter is None:
        return {"ok": False, "applied": [], "failed": [], "reason": "unsupported"}
    applied, failed = [], []
    for attr, val in title_attributes(bg, text, border):
        try:
            setter(hwnd, attr, val)
            applied.append(attr)
        except Exception:
            failed.append(attr)
        # 深色模式的新编号不被认识时补一次旧编号（1809~1903）
        if attr == DWMWA_USE_IMMERSIVE_DARK_MODE and attr in failed:
            try:
                setter(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE_OLD, val)
                applied.append(DWMWA_USE_IMMERSIVE_DARK_MODE_OLD)
                failed.remove(attr)
            except Exception:
                pass
    return {"ok": bool(applied), "applied": applied, "failed": failed,
            "reason": "" if applied else "dwm_rejected"}


def _hwnd_of(native):
    """从 pywebview 的 window.native（WinForms Form）取 HWND；取不到返回 0。"""
    if native is None:
        return 0
    for getter in (lambda: getattr(native, "Handle"),
                   lambda: getattr(native, "handle"),
                   lambda: native):
        try:
            v = getter()
        except Exception:
            continue
        try:
            # pythonnet 的 IntPtr 不能直接 int()，它有 ToInt64()
            return int(v.ToInt64()) if hasattr(v, "ToInt64") else int(v)
        except Exception:
            continue
    return 0


def find_window(pid=None, title_hint=""):
    """按进程号找本进程的顶层可见窗口句柄；找不到返回 0。

    不写死窗口标题：多开时标题相同，按 pid 找才不会误改另一个实例的标题栏。
    title_hint 只用于「同进程有多个可见窗口」时优先挑标题匹配的那个
    （pywebview 会额外建隐藏的辅助窗口）。
    """
    if not sys.platform.startswith("win"):
        return 0
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
    except Exception:
        return 0
    pid = int(pid or os.getpid())
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value != pid:
                return True
            n = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            found.append((int(hwnd), buf.value or ""))
        except Exception:
            pass
        return True

    try:
        user32.EnumWindows(_cb, 0)
    except Exception:
        return 0
    if not found:
        return 0
    if title_hint:
        for hwnd, title in found:
            if title_hint in title:
                return hwnd
    # 没有指定标题 / 没匹配上时取第一个：主窗口总是最先创建的那个可见窗口
    return found[0][0]


def attach(native=None, timeout=4.0, interval=0.12, pid=None,
           title_hint="ADB"):
    """等待窗口出现后套用深色标题栏（阻塞至多 timeout 秒）。

    在 pywebview 的 start(func=...) 线程里调用：那一刻 GUI 循环刚起，
    窗口对象可能还没建出来，所以要轮询。整体 silent —— 配色是锦上添花，
    任何异常都不该影响启动（最坏情况：标题栏保持系统默认色）。
    """
    if not sys.platform.startswith("win"):
        return {"ok": False, "reason": "unsupported"}
    deadline = time.time() + max(0.1, float(timeout))
    last = {"ok": False, "reason": "no_window"}
    while time.time() < deadline:
        hwnd = 0
        try:
            hwnd = _hwnd_of(native)
        except Exception:
            hwnd = 0
        if not hwnd:
            hwnd = find_window(pid, title_hint)
        if hwnd:
            last = apply_to_hwnd(hwnd)
            if last.get("ok"):
                return last
        time.sleep(max(0.02, float(interval)))
    return last
