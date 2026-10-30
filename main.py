# -*- coding: utf-8 -*-
"""
main.py —— ADB 设备指令台（Web 版入口 / pywebview 宿主）
=========================================================
界面由 frontend/ 下的 HTML/CSS/JS 渲染，后端业务由 backend/ + core/ 提供：

  * core/            纯逻辑（shell 会话 / 命令 / 设备 / logcat / 常量）
  * backend/         服务层：state（状态）/ workers（线程）/ device_service /
                     bus（事件队列）/ controller（pywebview js_api 桥）
  * main.py          本文件只负责「创建窗口 + 托管生命周期」

启动：
    python main.py            # 正常运行
    python main.py --debug    # 打开 WebView2 开发者工具（调 UI 用）

注意：
  * 本项目已全面转向 Web 版（pywebview + backend/* + core/*），不再维护 Tk 版。
  * backend / core 为纯逻辑，配有独立单测（tests/ 下以 test_backend_* / test_core_* 开头）。
"""
import argparse
import os
import sys
import time

from core.constants import PROJECT_ROOT
from backend.controller import WebApi
from core.envcheck import (
    run_all, WEBVIEW2_DOWNLOAD_URL, WEBVIEW2_CLIENT_GUID, WEBVIEW2_PV_SUBKEYS,
)

# 注意：webview 不在模块顶层导入。它在预检通过后才于 _launch() 内局部导入——
# 这样 pywebview 未安装时，能先弹友好中文提示，而不是裸 ImportError。

VERSION = "2026.1030.0937"


def _refresh_system_path():
    """从注册表同步用户/系统 PATH 到当前进程（保证子进程能找到 adb / powershell）。"""
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
    """frontend/index.html -> file:// URL（中文 / 空格 / # % ? 等都能正确处理）。

    不要手工拼 "file:///" 再 replace(" ", "%20")：路径里出现 `#`（会被当作片段
    分隔符，后面全部截断）、`%`、`?` 时 URL 会被改错，窗口直接空白；而打包成
    --windowed 时又没有任何控制台可看。pathlib 的 as_uri() 会按 RFC 3986 正确
    转义与规范化。
    """
    from pathlib import Path
    index = os.path.join(PROJECT_ROOT, "frontend", "index.html")
    if not os.path.exists(index):
        print("[main] 警告：未找到 %s，窗口可能显示空白（前端尚未就绪）。"
              % index, file=sys.stderr)
    return Path(index).resolve().as_uri()


# ---------------------------------------------------------------------------
# 启动前环境预检：收集平台原始值（注册表 / importlib.metadata / PATH）注入纯逻辑
# core.envcheck，任一阻断项失败即弹友好中文提示并退出。避免同事电脑上因
# WebView2 过旧 / 依赖缺失 / adb 缺失而只抛英文底层异常、无从下手。
# ---------------------------------------------------------------------------
def _collect_pv_list():
    """读取已安装 WebView2 Runtime 版本（pv），返回 pv 版本串列表。

    仅 Windows 生效：按官方 Microsoft Learn 方法，读 HKLM(WOW6432Node)+HKCU
    两处注册表键的 pv(REG_SZ)。任一成功即视为已安装；读取不到返回 []（非 Windows
    或键不存在都会落回这里，由 core.envcheck 判定为未安装）。

    注册表位置取自 core.envcheck 的**单一来源**：早前这里自己抄了一份 GUID 与路径，
    两处一旦漂移，改 envcheck 里的常量就会毫无效果。
    """
    try:
        import winreg
    except ImportError:
        return []
    found = []
    subkeys = [sub.format(GUID=WEBVIEW2_CLIENT_GUID)
               for sub in WEBVIEW2_PV_SUBKEYS]
    for hkey, sub in (
        # HKLM（64 位进程从 WOW6432Node 读到 64 位注册表视图）
        (winreg.HKEY_LOCAL_MACHINE, subkeys[0]),
        # HKCU（按用户安装）
        (winreg.HKEY_CURRENT_USER, subkeys[1]),
    ):
        try:
            with winreg.OpenKey(hkey, sub) as k:
                val, _ = winreg.QueryValueEx(k, "pv")
                # pv 官方为 REG_SZ；万一被写成别的类型（REG_DWORD），val 就不是 str，
                # 直接 .strip() 会抛 AttributeError 并被上层吞成「没读到 pv」——
                # 于是「装了 WebView2」被误判成「没装」而挡住启动。统一转字符串。
                text = str(val).strip() if val is not None else ""
                if text:
                    found.append(text)
        except OSError:
            continue  # 键不存在 / 无权限，尝试下一处
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
    """把 config.json 配置的 adb 所在目录前插到 PATH（幂等，失败静默）。

    同事机器上 adb 不一定在系统 PATH。这里让「关于」页填写的 adb 目录在启动
    阶段即生效，后续 preflight 的 adb 检测与所有子进程（adb/shell）都能找到；
    运行中在关于页改配置则走 WebApi.save_settings（同一条注入逻辑）。
    """
    try:
        from core.prefs import load_prefs, apply_adb_dir
        apply_adb_dir(load_prefs().get("adb_dir"))
    except Exception:
        pass


def _ensure_config_file():
    """确保 exe 同目录有 config.json（缺失则按默认值补建，尽力而为）。

    build.py 会在 dist/ 放一份默认配置，但用户可能手动删掉它、或从源码直接
    跑（工程根没有该文件）。启动即补建后，load/save 始终有同一个文件可依，
    「每次启动都加载以往的设置」才有着落；写不进去（只读目录等）时静默跳过，
    行为与从前一致——首次改动设置时才由 save_prefs 尝试创建。
    """
    try:
        from core.prefs import ensure_prefs_file
        ensure_prefs_file()
    except Exception:
        pass


def _show_native_error(title, lines, url=None):
    """用不依赖 WebView2/Tk 的原生方式展示错误并退出前调用。

    Windows：Win32 MessageBoxW（MB_ICONERROR|MB_SYSTEMMODAL，置顶模态）。
    若传了 url，按钮改为「确定 / 取消」，点击「确定」会用系统默认浏览器打开
    该链接，方便同事直接跳转下载页，无需手动复制链接。
    非 Windows / 调用失败：回退为逐行打印到 stderr（不阻塞正常控制台用户）。
    """
    text_lines = list(lines)
    if url:
        text_lines.append("点击「确定」将打开浏览器前往下载页面；「取消」关闭此窗口。")
    text = "\n\n".join(text_lines)
    is_win = sys.platform.startswith("win")
    shown = False
    if is_win:
        try:
            import ctypes
            MB_ICONERROR = 0x10
            MB_SYSTEMMODAL = 0x1000
            MB_OKCANCEL = 0x01
            IDOK = 1
            if url:
                flags = MB_OKCANCEL | MB_ICONERROR | MB_SYSTEMMODAL
            else:
                flags = MB_ICONERROR | MB_SYSTEMMODAL
            res = ctypes.windll.user32.MessageBoxW(None, text, title, flags)
            shown = True
            if url and res == IDOK:
                try:
                    ctypes.windll.shell32.ShellExecuteW(
                        None, "open", url, None, None, 1)
                except Exception:
                    pass
        except Exception:
            shown = False
    if not shown:
        print("\n[环境检查未通过] %s\n%s\n" % (title, text), file=sys.stderr)
    return shown


# ---------------------------------------------------------------------------
# 全局崩溃兜底：--windowed 打包的 exe 没有控制台，未捕获异常若只抛到 stderr
# 表现为「闪一下就没」，同事无从排查。这里把 主线程 + 所有后台线程 的未捕获
# 异常统一落盘为 crash_*.log（程序目录，不可写时退回系统临时目录），主线程
# 的致命崩溃再补一个原生弹窗提示日志位置。钩子本身保证绝不二次抛异常。
# ---------------------------------------------------------------------------
def _write_crash_log(title, exc_type, exc, tb):
    """把一次未捕获异常写入 crash_<时间戳>.log，返回日志路径（失败返回 None）。"""
    try:
        import io
        import traceback
        buf = io.StringIO()
        traceback.print_exception(exc_type, exc, tb, file=buf)
        body = buf.getvalue().rstrip()
    except Exception:
        body = "%s: %s" % (getattr(exc_type, "__name__", exc_type), exc)
    text = "\n".join([
        "=" * 64,
        "ADB 设备指令台 崩溃日志",
        "时间  : " + time.strftime("%Y-%m-%d %H:%M:%S"),
        "平台  : %s / Python %s / 打包态: %s"
        % (sys.platform, sys.version.split()[0], getattr(sys, "frozen", False)),
        "原因  : " + title,
        "-" * 64,
        body,
        "",
    ])
    # 优先写程序（exe / 脚本）所在目录，方便同事把崩溃日志随包发回；
    # 目录不存在 / 无写权限时退回系统临时目录兜底。
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = PROJECT_ROOT
    candidates = [base]
    import tempfile
    candidates.append(tempfile.gettempdir())
    for d in candidates:
        try:
            os.makedirs(d, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            path = os.path.join(d, "crash_%s.log" % stamp)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            return path
        except Exception:
            continue
    return None


def _notify_crash(log_path):
    """主线程致命崩溃时弹原生提示，附日志位置（失败则静默打印）。"""
    try:
        import ctypes
        MB_ICONERROR = 0x10
        MB_SYSTEMMODAL = 0x1000
        lines = "程序发生未预期的错误，即将退出。"
        if log_path:
            lines += "\n\n崩溃详情已写入：\n%s\n\n请把该日志文件发给维护者以定位问题。" % log_path
        ctypes.windll.user32.MessageBoxW(
            None, lines, "ADB 设备指令台 · 崩溃提示",
            MB_ICONERROR | MB_SYSTEMMODAL)
    except Exception:
        print("[崩溃] %s" % log_path, file=sys.stderr)


def _install_crash_hooks():
    """注册 sys.excepthook（主线程）与 threading.excepthook（后台线程）。"""
    import threading

    def _sys_hook(exc_type, exc, tb):
        if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            return  # 主动退出路径不需要记录
        log = _write_crash_log("主线程未捕获异常", exc_type, exc, tb)
        _notify_crash(log)

    def _thread_hook(args):
        log = _write_crash_log(
            "后台线程异常（%s）" % getattr(args.thread, "name", "?"),
            args.exc_type, args.exc_value, args.exc_traceback)
        if log:
            try:
                print("[崩溃日志] %s" % log, file=sys.stderr)
            except Exception:
                pass

    sys.excepthook = _sys_hook
    if hasattr(threading, "excepthook"):      # Python 3.8+
        threading.excepthook = _thread_hook


def _preflight():
    """启动前环境预检：任一阻断项不通过即弹窗提示并退出（码 2）。

    adb 缺失**不阻断启动**：工具采用「可启动 + 引导配置」策略——启动后界面
    （boot 广播）会提示到「关于」页填写 adb 所在目录并保存，避免只想先浏览
    界面/命令的同事被挡在门外。
    """
    problems = run_all(
        get_pv=_collect_pv_list,
        pywebview_version=_pywebview_version(),
        adb_path=_adb_on_path(),
    )
    # adb 缺失为非阻断项（界面内引导配置）：按 DepProblem.blocking 过滤，而不是
    # 匹配 name 字符串——文案一改，字符串过滤就会静默失效，把「不阻断」悄悄变回
    # 「阻断」（同事没装 adb 时连界面都打不开）。
    problems = [p for p in problems if p.blocking]
    if not problems:
        return
    lines = ["检测到以下问题，请处理后重新运行本程序："]
    for p in problems:
        lines.append("• %s\n  %s\n  → %s" % (p.name, p.detail, p.fix))
    # 如果问题涉及 WebView2，给弹窗附带可点击跳转的下载链接。
    url = None
    for p in problems:
        if "WebView2" in p.name:
            url = WEBVIEW2_DOWNLOAD_URL
            break
    _show_native_error("启动环境检查未通过", lines, url=url)
    sys.exit(2)


def main():
    # 崩溃兜底最先注册：保证后续任何阶段（含后台线程）的未捕获异常都有日志
    _install_crash_hooks()

    parser = argparse.ArgumentParser(description="ADB 设备指令台（Web 版）")
    parser.add_argument("--debug", action="store_true",
                        help="开启 WebView2 开发者工具（前端调试用）")
    parser.add_argument("--no-path-sync", action="store_true",
                        help="跳过注册表 PATH 同步（排查 adb 找不到时用）")
    args = parser.parse_args()

    if not args.no_path_sync:
        _refresh_system_path()

    # 先补建配置文件（缺失时按默认值生成），再读其中的 adb 目录注入 PATH，
    # 最后进入 preflight 的 adb 检测。
    _ensure_config_file()
    _apply_user_adb_dir()

    # 预检在创建窗口之前；adb 检查需在 PATH 同步之后，故放这里。
    # 注意：依赖缺失时此处弹窗后即 sys.exit(2)，不会往下走到 import webview。
    # adb 缺失为非阻断项（界面内引导配置），见 core.envcheck / WebApi.boot。
    _preflight()

    api = WebApi()
    url = _resolve_index_url()
    return _launch(args, api, url)


def _theme_window(window):
    """窗口就绪后把原生标题栏改成与界面一致的深色（非 Windows / 失败静默）。

    标题栏是系统绘制的（本程序用原生标题栏，没有自绘），默认跟随 Windows 的
    「应用主题」：系统是浅色时，深色界面顶着一根近白的标题栏，割裂感很强。
    具体的 DWM 调用在 core/win_theme.py（可 headless 单测），这里只负责在
    合适的时机（窗口对象已经存在）把它叫起来。
    """
    try:
        from core import win_theme
        win_theme.attach(getattr(window, "native", None))
    except Exception:
        pass                      # 配色是锦上添花，任何异常都不能挡住启动


def _launch(args, api, url):
    """预检通过后真正拉起窗口。webview 在此函数内局部导入，保证即使 pywebview
    缺失，上面的 _preflight 也已先给出友好提示而非裸 ImportError。"""
    import webview

    window = webview.create_window(
        "ADB 设备指令台",
        url=url,
        js_api=api,
        width=1380,
        height=880,
        min_size=(980, 620),
        # 与前端画布同色（frontend/css/app.css 的 --bg #0b0f14）：
        # 窗口未渲染出内容前的底色不再闪一下旧灰，启动观感与界面一致。
        background_color="#0b0f14",
        maximized=True,   # 启动时即最大化（创建时直接置窗体状态，避免先小窗再放大）
    )

    # 采用原生标题栏：启动即最大化（maximized=True），用户可随时用原生标题栏
    # 的「还原」按钮将窗口缩小为可自由调整的大小——不再需要自绘标题栏与
    # Win32 拖拽（相关遗留代码已随 v2026.0908.2228 清理，见 README）。
    # 配色用 DWM 属性改成与界面同色（core/win_theme.py），既保留系统的窗口
    # 行为（贴边分屏 / 双击最大化 / 高 DPI），又不让浅色标题栏压在深色界面上。

    # 窗口生命周期：webview.start() 在全部窗口关闭后返回，这里兜底做优雅收尾
    # （杀 PowerShell 会话、停自动轮询线程），避免残留后台进程。
    try:
        # start(func=...) 会在 GUI 循环起来后另开一个线程执行 func：那一刻窗口
        # 才真正存在，正好用来套用深色标题栏（见 _theme_window）。
        webview.start(debug=args.debug, func=_theme_window, args=(window,))
    except KeyboardInterrupt:
        print("[main] 收到中断信号，正在退出…", file=sys.stderr)
    finally:
        try:
            api.shutdown()
        except Exception as ex:
            print("[main] 退出清理异常：%s" % ex, file=sys.stderr)
    return window


if __name__ == "__main__":
    main()
