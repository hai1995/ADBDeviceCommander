"""
main.py —— ADB 设备指令台（Web 版入口 / pywebview 宿主）
=========================================================
界面由 frontend/ 下的 HTML/CSS/JS 渲染，后端业务由 backend/ + core/ 提供。
"""
import argparse
import os
import sys
import time

_MODULE_T0 = time.perf_counter()

from backend.controller import WebApi
from core.constants import PROJECT_ROOT, unique_path
from core.envcheck import (
    WEBVIEW2_CLIENT_GUID,
    WEBVIEW2_DOWNLOAD_URL,
    WEBVIEW2_PV_SUBKEYS,
    run_all,
)
from core.longpath import long_path, path_isdir, path_isfile

os.environ.setdefault("PYWEBVIEW_GUI", "edgechromium")


def _refresh_system_path():
    """从注册表同步用户/系统 PATH 到当前进程。"""
    try:
        import winreg
        keys = [
            (winreg.HKEY_CURRENT_USER, r"Environment"),
            (winreg.HKEY_LOCAL_MACHINE,
             r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
        ]
        extra = []
        for hkey, sub in keys:
            try:
                with winreg.OpenKey(hkey, sub) as k:
                    try:
                        extra.append(winreg.QueryValueEx(k, "Path")[0])
                    except OSError:
                        pass
            except OSError:
                pass
        new = ";".join(filter(None, [os.environ.get("PATH", "")] + extra))
        if new:
            os.environ["PATH"] = new
    except Exception:
        pass


def _resolve_index_url():
    """frontend/index.html -> file:// URL（中文 / 空格 / # % ? 等都能正确处理）。"""
    from pathlib import Path
    index = os.path.join(PROJECT_ROOT, "frontend", "index.html")
    if not path_isfile(index):
        print("[main] 警告：未找到 {}，窗口可能显示空白（前端尚未就绪）。".format(index), file=sys.stderr)
    return Path(index).resolve().as_uri()


def _collect_pv_list():
    """读取已安装 WebView2 Runtime 版本（pv），返回 pv 版本串列表。"""
    try:
        import winreg
    except ImportError:
        return []
    found = []
    subkeys = [sub.format(GUID=WEBVIEW2_CLIENT_GUID)
               for sub in WEBVIEW2_PV_SUBKEYS]
    for hkey, sub in (
        (winreg.HKEY_LOCAL_MACHINE, subkeys[0]),
        (winreg.HKEY_CURRENT_USER, subkeys[1]),
    ):
        try:
            with winreg.OpenKey(hkey, sub) as k:
                val, _ = winreg.QueryValueEx(k, "pv")
                text = str(val).strip() if val is not None else ""
                if text:
                    found.append(text)
        except OSError:
            continue
    return found


def _pywebview_version():
    """返回已安装 pywebview 的版本串；未安装 / 查询异常返回 None。"""
    try:
        from importlib import metadata
        return metadata.version("pywebview")
    except Exception:
        return None


def _adb_on_path():
    """返回 PATH 中 adb 的可执行路径；找不到返回空串。"""
    import shutil
    return shutil.which("adb") or ""


def _apply_user_adb_dir():
    """把 config.json 配置的 adb 所在目录前插到 PATH（幂等，失败静默）。"""
    try:
        from core.prefs import apply_adb_dir, load_prefs
        apply_adb_dir(load_prefs().get("adb_dir"))
    except Exception:
        pass


def _ensure_config_file():
    """确保 exe 同目录有 config.json（缺失则按默认值补建，尽力而为）。"""
    try:
        from core.prefs import ensure_prefs_file
        ensure_prefs_file()
    except Exception:
        pass


def _win32():
    """取得本文件用到的 Win32 对象，并**显式声明它们的原型**。"""
    if os.name != "nt":
        return None, None, None
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        k32 = ctypes.windll.kernel32
    except Exception:
        return None, None, None
    user32.MessageBoxW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                   ctypes.c_wchar_p, ctypes.c_uint]
    user32.MessageBoxW.restype = ctypes.c_int
    shell32.ShellExecuteW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                     ctypes.c_wchar_p, ctypes.c_wchar_p,
                                     ctypes.c_wchar_p, ctypes.c_int]
    shell32.ShellExecuteW.restype = ctypes.c_void_p
    k32.GetCurrentProcess.argtypes = []
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.GetProcessTimes.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME)]
    k32.GetProcessTimes.restype = ctypes.c_int
    return user32, shell32, k32


def _show_native_error(title, lines, url=None):
    """用不依赖 WebView2/Tk 的原生方式展示错误并退出前调用。"""
    text_lines = list(lines)
    if url:
        text_lines.append("点击「确定」将打开浏览器前往下载页面；「取消」关闭此窗口。")
    text = "\n\n".join(text_lines)
    is_win = sys.platform.startswith("win")
    shown = False
    if is_win:
        try:
            MB_ICONERROR = 0x10
            MB_SYSTEMMODAL = 0x1000
            MB_OKCANCEL = 0x01
            IDOK = 1
            if url:
                flags = MB_OKCANCEL | MB_ICONERROR | MB_SYSTEMMODAL
            else:
                flags = MB_ICONERROR | MB_SYSTEMMODAL
            user32, shell32, _k32 = _win32()
            if user32 is None:
                raise RuntimeError("MessageBoxW 不可用")
            res = user32.MessageBoxW(None, text, title, flags)
            shown = True
            if url and res == IDOK:
                try:
                    shell32.ShellExecuteW(None, "open", url, None, None, 1)
                except Exception:
                    pass
        except Exception:
            shown = False
    if not shown:
        print("\n[环境检查未通过] {}\n{}\n".format(title, text), file=sys.stderr)
    return shown


def _write_crash_log(title, exc_type, exc, tb):
    """把一次未捕获异常写入 crash_<时间戳>.log，返回日志路径（失败返回 None）。"""
    try:
        import io
        import traceback
        buf = io.StringIO()
        traceback.print_exception(exc_type, exc, tb, file=buf)
        body = buf.getvalue().rstrip()
    except Exception:
        body = "{}: {}".format(getattr(exc_type, "__name__", exc_type), exc)
    text = "\n".join([
        "=" * 64,
        "ADB 设备指令台 崩溃日志",
        "时间  : " + time.strftime("%Y-%m-%d %H:%M:%S"),
        "平台  : {} / Python {} / 打包态: {}".format(sys.platform, sys.version.split()[0], getattr(sys, "frozen", False)),
        "原因  : " + title,
        "-" * 64,
        body,
        "",
    ])
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = PROJECT_ROOT
    candidates = [base]
    import tempfile
    candidates.append(tempfile.gettempdir())
    for d in candidates:
        try:
            os.makedirs(long_path(d), exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            path = unique_path(os.path.join(d, "crash_{}.log".format(stamp)))
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            return path
        except Exception:
            continue
    return None


def _notify_crash(log_path):
    """主线程致命崩溃时弹原生提示，附日志位置（失败则静默打印）。"""
    try:
        MB_ICONERROR = 0x10
        MB_SYSTEMMODAL = 0x1000
        lines = "程序发生未预期的错误，即将退出。"
        if log_path:
            lines += "\n\n崩溃详情已写入：\n{}\n\n请把该日志文件发给维护者以定位问题。".format(log_path)
        _user32, _shell32, _k32b = _win32()
        _user32.MessageBoxW(
            None, lines, "ADB 设备指令台 · 崩溃提示",
            MB_ICONERROR | MB_SYSTEMMODAL)
    except Exception:
        print("[崩溃] {}".format(log_path), file=sys.stderr)


def _install_crash_hooks():
    """注册 sys.excepthook（主线程）与 threading.excepthook（后台线程）。"""
    import threading

    def _sys_hook(exc_type, exc, tb):
        if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            return
        log = _write_crash_log("主线程未捕获异常", exc_type, exc, tb)
        _notify_crash(log)

    def _thread_hook(args):
        log = _write_crash_log(
            "后台线程异常（{}）".format(getattr(args.thread, "name", "?")),
            args.exc_type, args.exc_value, args.exc_traceback)
        if log:
            try:
                print("[崩溃日志] {}".format(log), file=sys.stderr)
            except Exception:
                pass

    sys.excepthook = _sys_hook
    if hasattr(threading, "excepthook"):
        threading.excepthook = _thread_hook


def _preflight():
    """启动前环境预检：任一阻断项不通过即弹窗提示并退出（码 2）。"""
    problems = run_all(
        get_pv=_collect_pv_list,
        pywebview_version=_pywebview_version(),
        adb_path=_adb_on_path(),
    )
    problems = [p for p in problems if p.blocking]
    if not problems:
        return
    lines = ["检测到以下问题，请处理后重新运行本程序："]
    for p in problems:
        lines.append("• {}\n  {}\n  → {}".format(p.name, p.detail, p.fix))
    url = None
    for p in problems:
        if "WebView2" in p.name:
            url = WEBVIEW2_DOWNLOAD_URL
            break
    _show_native_error("启动环境检查未通过", lines, url=url)
    sys.exit(2)


def _boot_timing_path():
    """启动分段耗时日志的位置：系统临时目录。"""
    import tempfile
    return os.path.join(tempfile.gettempdir(), "adbdc_boot_timing.log")


def _reset_boot_timing_log():
    """每次启动重新起一份耗时日志。"""
    try:
        with open(long_path(_boot_timing_path()), "w", encoding="utf-8") as f:
            f.write("=== {} 启动 ===\n".format(time.strftime("%Y-%m-%d %H:%M:%S")))
    except Exception:
        pass


def _make_boot_mark(t0):
    """返回启动分段打点函数。"""
    def mark(tag):
        line = "[boot {:5.2f}s] {}".format(time.perf_counter() - t0, tag)
        try:
            print(line, file=sys.stderr, flush=True)
        except Exception:
            pass
        try:
            with open(long_path(_boot_timing_path()), "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass
    return mark


def _process_age_seconds():
    """进程创建到现在过了多少秒；取不到返回 None（非 Windows）。"""
    if not sys.platform.startswith("win"):
        return None
    try:
        import ctypes
        from ctypes import wintypes
        _u, _s, k32 = _win32()
        if k32 is None:
            return None
        created, exited = wintypes.FILETIME(), wintypes.FILETIME()
        kernel, user = wintypes.FILETIME(), wintypes.FILETIME()
        ok = k32.GetProcessTimes(k32.GetCurrentProcess(),
                                 ctypes.byref(created), ctypes.byref(exited),
                                 ctypes.byref(kernel), ctypes.byref(user))
        if not ok:
            return None
        ft = (created.dwHighDateTime << 32) | created.dwLowDateTime
        return max(0.0, time.time() - (ft / 1e7 - 11644473600))
    except Exception:
        return None


_MOTW_BINARY_SUFFIXES = (".dll", ".pyd", ".exe", ".manifest")


def _motw_needed():
    """只有「Windows + PyInstaller 打包态」才需要清理。"""
    return os.name == "nt" and bool(getattr(sys, "frozen", False))


def _motw_cleanup_dirs():
    """需要递归清理的根目录。"""
    roots = []
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass and path_isdir(meipass):
        roots.append(meipass)
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    if exe_dir and path_isdir(exe_dir) and exe_dir not in roots:
        if any(_is_under(exe_dir, r) for r in roots):
            roots.append(exe_dir)
    return roots


def _is_under(parent, child):
    """child 是否在 parent 之内（含相等）。用于避免重复扫描同一棵树。"""
    try:
        parent = os.path.normcase(os.path.abspath(parent))
        child = os.path.normcase(os.path.abspath(child))
    except (OSError, ValueError):
        return False
    if parent == child:
        return True
    return child.startswith(parent + os.sep)


def _iter_motw_files(root):
    """递归遍历 root，产出其中所有「二进制」文件的路径。"""
    stack = [root]
    seen = set()
    while stack:
        current = stack.pop()
        try:
            key = os.path.realpath(current)
        except OSError:
            continue
        if key in seen:
            continue
        seen.add(key)
        try:
            entries = list(os.scandir(long_path(current)))
        except (OSError, ValueError):
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(entry.path)
                    continue
                if not entry.name.lower().endswith(_MOTW_BINARY_SUFFIXES):
                    continue
            except OSError:
                continue
            yield entry.path


def _delete_zone_identifier(ads_path):
    """删除一条 :Zone.Identifier 备用数据流路径，非 Windows / 失败静默返回 False。"""
    if os.name != "nt":
        return False
    try:
        import ctypes
        fn = ctypes.windll.kernel32.DeleteFileW
        fn.argtypes = [ctypes.c_wchar_p]
        fn.restype = ctypes.c_int
        return bool(fn(ads_path))
    except Exception:
        return False


def _strip_mark_of_the_web():
    """清掉运行时目录树下所有二进制的「来自网络」标记，返回清理的文件数。"""
    if not _motw_needed():
        return 0
    count = 0
    try:
        for root in _motw_cleanup_dirs():
            for path in _iter_motw_files(root):
                _delete_zone_identifier(path + ":Zone.Identifier")
                count += 1
    except Exception:
        pass
    return count


def _gui_failure_lines(exc):
    """GUI 初始化失败的中文提示行：pythonnet/MOTW 场景给可自救的步骤。"""
    msg = "{}: {}".format(type(exc).__name__, exc)
    lines = ["窗口启动失败：{}".format(msg), ""]
    if ("Python.Runtime" in msg or "pythonnet" in msg.lower()
            or "Loader.Initialize" in msg or "CLR" in msg):
        lines += [
            "这通常是 Windows 把程序文件夹标记为「来自网络」后，.NET Framework",
            "拒绝加载其中组件导致的（多发于从浏览器 / IM 下载的 zip 直接解压）。",
            "",
            "请按顺序重试：",
            "  1. 关闭本程序，删除当前解压出来的整个文件夹；",
            "  2. 右键下载的 zip → 属性 → 勾选「解除锁定 / 取消锁定」→ 确定；",
            "  3. 重新解压到一个全新目录，再双击运行。",
            "  也可在该目录用 PowerShell 执行：Get-ChildItem -Recurse | Unblock-File",
        ]
    else:
        lines.append("请把下面的崩溃日志发给维护者以定位问题。")
    return lines


def _report_gui_init_failure(exc):
    """GUI 初始化失败：留一份完整崩溃日志 + 中文自救弹窗 + 一行启动打点。"""
    lines = _gui_failure_lines(exc)
    try:
        log = _write_crash_log("窗口启动失败（GUI 初始化）", type(exc), exc,
                               exc.__traceback__)
    except Exception:
        log = None
    if log:
        lines += ["", "崩溃详情已写入：{}".format(log)]
    try:
        with open(long_path(_boot_timing_path()), "a", encoding="utf-8") as f:
            f.write("[启动失败] {}: {}\n".format(type(exc).__name__, exc))
    except Exception:
        pass
    try:
        _show_native_error("ADB 设备指令台 · 启动失败", lines)
    except Exception:
        pass


def main():
    _T0 = _MODULE_T0
    _reset_boot_timing_log()
    _MARK = _make_boot_mark(_T0)
    _MARK("main_enter（以上为 import backend/core）")
    age = _process_age_seconds()
    if age is not None:
        _MARK("process_age {:.2f}s（进程创建 → Python 代码，含 onefile 解压）".format(age))

    _install_crash_hooks()
    _MARK("crash_hooks_done")

    n_motw = _strip_mark_of_the_web()
    if n_motw:
        _MARK("motw_cleared %d binaries" % n_motw)

    parser = argparse.ArgumentParser(description="ADB 设备指令台（Web 版）")
    parser.add_argument("--debug", action="store_true",
                        help="开启 WebView2 开发者工具（前端调试用）")
    parser.add_argument("--no-path-sync", action="store_true",
                        help="跳过注册表 PATH 同步（排查 adb 找不到时用）")
    args = parser.parse_args()

    if not args.no_path_sync:
        _refresh_system_path()

    _ensure_config_file()
    _apply_user_adb_dir()
    _MARK("path_ready")

    _preflight()
    _MARK("preflight_done")

    api = WebApi()
    _MARK("WebApi_built")
    url = _resolve_index_url()
    return _launch(args, api, url, _T0=_T0)


def _theme_window(window):
    """窗口就绪后把原生标题栏改成与界面一致的主题（非 Windows / 失败静默）。"""
    try:
        from core import win_theme
        from core.prefs import load_prefs
        mode = "dark"
        try:
            m = load_prefs().get("theme")
            if m in ("dark", "light", "system"):
                mode = m
        except Exception:
            pass
        win_theme.attach(getattr(window, "native", None), mode=mode)
    except Exception:
        pass


def _launch(args, api, url, _T0=None):
    """预检通过后真正拉起窗口。webview 在此函数内局部导入。"""
    _T0 = _T0 or time.perf_counter()
    _MARK = _make_boot_mark(_T0)

    import webview
    _MARK("webview_imported")

    window = webview.create_window(
        "ADB 设备指令台",
        url=url,
        js_api=api,
        width=1380,
        height=880,
        min_size=(980, 620),
        background_color="#0b0f14",
        maximized=True,
    )
    _MARK("window_created")

    try:
        window.events.shown += lambda: _MARK("window_shown")
        window.events.loaded += lambda: _MARK("dom_loaded")
    except Exception:
        pass

    try:
        webview.start(debug=args.debug, func=_theme_window, args=(window,))
    except KeyboardInterrupt:
        print("[main] 收到中断信号，正在退出…", file=sys.stderr)
    except Exception as exc:
        _report_gui_init_failure(exc)
        sys.exit(3)
    finally:
        try:
            api.shutdown()
        except Exception as ex:
            print("[main] 退出清理异常：{}".format(ex), file=sys.stderr)
    return window


if __name__ == "__main__":
    main()
