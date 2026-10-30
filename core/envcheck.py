# -*- coding: utf-8 -*-
"""
core.envcheck —— 启动前环境预检（纯逻辑，headless 可测）
==========================================================
Web 版依赖 pywebview（Windows 宿主为 WebView2 Runtime）。在同事电脑上若这些
环境件缺失/过旧，程序会在创建窗口时直接失败、只抛英文底层异常，用户无从下手。
本模块把「该检查什么、版本门槛是多少、没满足该提示什么」集中为纯函数，
供 main.py 在创建窗口**之前**调用；任一阻断项失败即以友好中文弹窗阻止启动。

设计约束：
  * 本模块不 import tkinter / ctypes / webview / winreg —— 只做判定与文案，
    不做任何平台副作用，因此可在无头环境 / CI 下被干净 import 并单测。
  * 真正的「平台取值」由调用方（main.py）注入：注册表里读到的 pv 版本串、
    pywebview 的已装版本、adb 的可执行路径 —— 都以原始值传进来，本模块据此
    返回 DepProblem（问题描述 + 中文修复指引）。这样 headless 测试无需真实
    注册表 / shutil，直接注入桩即可覆盖各分支。

版本门槛依据（Microsoft Learn）：
  pywebview 创建控件时调用 CreateCoreWebView2ControllerOptions()，其依赖的
  ICoreWebView2Environment10 接口自 WebView2 Runtime 1.0.1210.39（即 121.x）
  起才提供。因此 WebView2 Runtime 主版本需 >= 121，否则初始化报
  「Unable to cast to ICoreWebView2Environment10 / E_NOINTERFACE」。
"""
from typing import List, NamedTuple, Optional

# WebView2 Runtime 最低主版本（pywebview >= 6 创建控件所需接口的门槛）。
MIN_WEBVIEW2_MAJOR = 121

# pywebview 最低要求主版本（requirements.txt 写的是 >=6.0）。
MIN_PYWEBVIEW = (6, 0)

# 官方修复入口：下载 / 更新 WebView2 Runtime。
WEBVIEW2_DOWNLOAD_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"

# 检测 WebView2 Runtime 版本的注册表位置（64 位 Windows，本工具面向桌面 64 位）。
# 键下读取 REG_SZ 值 `pv`（形如 150.0.4078.48）。HKLM 为按机器安装，HKCU 为按用户
# 安装；两者至少一处存在且版本 > 0.0.0.0 即视为已安装（Microsoft Learn 官方方法）。
WEBVIEW2_CLIENT_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
WEBVIEW2_PV_SUBKEYS = (
    # HKLM：64 位进程从 WOW6432Node 读到 64 位注册表视图
    r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{GUID}",
    # HKCU：按用户安装
    r"Software\Microsoft\EdgeUpdate\Clients\{GUID}",
)


def parse_version(s: Optional[str]):
    """把形如 '100.0.1185.36' 的版本串解析为 int 元组 (major, minor, build, patch)。

    非字符串 / None / 含非数字段 / 为空 -> 返回 None（视为无法解析）。
    解析只取开头连续的数字点分，忽略 'v' 前缀之类脏字符前后。
    """
    if s is None:
        return None
    text = str(s).strip()
    # 兼容 'v123.0' 等：剥掉前导的非数字字符（如 'v'），再取数字点分前缀；
    # 尾部如 '(x64)' 之类非数字内容在遇到时自然停止。
    start = 0
    while start < len(text) and not text[start].isdigit():
        start += 1
    cleaned = ""
    for ch in text[start:]:
        if ch.isdigit() or ch == ".":
            cleaned += ch
        else:
            break
    if not cleaned:
        return None
    parts = cleaned.split(".")
    out = []
    for p in parts:
        if p == "":
            continue
        # 注意：str.isdigit() 对「非十进制数字」也返回 True（如 '²'、'²' 是
        # Unicode 上标数字），随后 int() 会抛 ValueError —— 而调用链
        # （run_all -> main._preflight）没有任何兜底，用户看到的会是一份崩溃日志
        # 而不是「WebView2 缺失」的中文引导。这里统一转成「无法解析」。
        try:
            out.append(int(p))
        except ValueError:
            return None
    if not out:
        return None
    return tuple(out)


def _at_least(version, minimum) -> bool:
    """version 是否 >= minimum（均为 int 元组，逐位比较，缺位视为 0）。"""
    v = list(version)
    m = list(minimum)
    n = max(len(v), len(m))
    v += [0] * (n - len(v))
    m += [0] * (n - len(m))
    return tuple(v) >= tuple(m)


def _fmt_version(t):
    return ".".join(str(x) for x in t)


class DepProblem(NamedTuple):
    """一条环境检查问题。name 为显示名，detail 为现状描述，fix 为中文修复指引。

    blocking 表示「是否阻断启动」：
      * True  —— 缺失/过旧时程序根本无法运行（WebView2 / pywebview），必须拦住；
      * False —— 不影响启动、只影响功能可用性（adb 缺失），采用「可启动 +
                  界面内引导配置」策略（见 main._preflight 与 WebApi.boot）。
    调用方据此过滤，**不要**用 name 字符串去匹配（文案一改过滤就静默失效）。
    """

    name: str
    detail: str
    fix: str
    blocking: bool = True

    def message(self) -> str:
        """展示用多行文案（弹窗/日志共用）。"""
        return "%s\n  现状：%s\n  处理：%s" % (self.name, self.detail, self.fix)


def _best_pv(get_pv):
    """从 get_pv() 返回的版本串列表里挑出**最大**版本；一个都没有返回 None。

    同时存在按机器(HKLM)与按用户(HKCU)安装时版本可能不同，取较大者最稳妥——
    界面实际用的是较大的那个 Runtime。
    """
    if get_pv is None:
        return None
    best = None
    try:
        raw = list(get_pv() or [])
    except Exception:
        raw = []
    for s in raw:
        t = parse_version(s)
        if t is None:
            continue
        if best is None or t > best:
            best = t
    return best


def check_webview2(get_pv=None) -> Optional[DepProblem]:
    """检查 WebView2 Runtime 是否已安装且版本达标。

    get_pv: () -> List[str]，返回收集到的 pv 版本串；默认 None 表示非 Windows / 无法
    读取（视为未安装，给出引导）。达标（主版本 >= MIN_WEBVIEW2_MAJOR）返回 None。
    """
    best = _best_pv(get_pv)
    if best is None:
        return DepProblem(
            name="WebView2 Runtime",
            detail="未检测到已安装的 WebView2 Runtime（本程序界面渲染必需）。",
            fix=("请联网下载并安装「WebView2 Runtime」（%d.0 及以上版本）后重新启动本程序：\n"
                 + "      %s\n"
                 + "   安装包需以【管理员身份】运行；装完无需改任何代码。")
            % (MIN_WEBVIEW2_MAJOR, WEBVIEW2_DOWNLOAD_URL),
        )
    if _at_least(best, (MIN_WEBVIEW2_MAJOR, 0, 0, 0)):
        return None  # 已达标
    return DepProblem(
        name="WebView2 Runtime 版本过旧",
        detail=("当前版本 %s，低于本程序所需的 %d.0 及以上版本。"
                "版本过旧会导致界面初始化失败"
                "（报错：Unable to cast to ICoreWebView2Environment10）。")
        % (_fmt_version(best), MIN_WEBVIEW2_MAJOR),
        fix=("请把 WebView2 Runtime 升级到 %d.0 及以上（推荐升级到最新版）后重启本程序：\n"
             "      %s\n"
             "   下载后以【管理员身份】运行安装即可覆盖旧版本。")
        % (MIN_WEBVIEW2_MAJOR, WEBVIEW2_DOWNLOAD_URL),
    )


def check_pywebview(version=None) -> Optional[DepProblem]:
    """检查 pywebview 是否已安装且版本达标。

    version: 已装的 pywebview 版本串（由调用方经 importlib.metadata 取）；None 视为未装。
    """
    if not version:
        return DepProblem(
            name="pywebview 依赖缺失",
            detail="未检测到 pywebview（Web 版界面宿主库）。",
            fix=("请在命令行进入本项目目录后执行：\n"
                 "      pip install -r requirements.txt\n"
                 "   然后重新启动本程序。"),
        )
    t = parse_version(version)
    if t is not None and _at_least(t, MIN_PYWEBVIEW):
        return None
    return DepProblem(
        name="pywebview 版本过旧",
        detail="当前版本 %s，低于所需 %s 及以上。" % (
            version,
            ".".join(str(x) for x in MIN_PYWEBVIEW)),
        fix="请执行：pip install -U pywebview，然后重新启动本程序。",
    )


def check_adb(adb_path=None) -> Optional[DepProblem]:
    """检查 adb 是否可调用。

    adb_path: shutil.which('adb') 结果；空 / None 视为不在 PATH（不可用）。

    adb 缺失**不阻断启动**（blocking=False）：工具采用「可启动 + 界面内引导
    配置」策略——同事没装 adb 也能先打开界面浏览命令，再到「关于」页填 adb
    目录保存即注入 PATH 生效（见 WebApi.save_settings / boot 的 adb_ok 引导）。
    """
    if adb_path:
        return None
    return DepProblem(
        name="adb 未找到",
        detail="系统 PATH 中未找到 adb（Android 调试桥，连接设备必需）。",
        fix=("请确认已安装 adb 并把它加入系统环境变量 PATH，"
             "然后【重新打开】本程序；\n"
             "   命令行里能执行 `adb devices` 即表示可用。"),
        blocking=False,
    )


def run_all(get_pv=None, pywebview_version=None, adb_path=None) -> List[DepProblem]:
    """汇总执行全部检查，返回所有未通过项（可能为空）。

    各参数含义与单检查一致：由调用方收集平台原始值注入。返回顺序固定：
    WebView2 Runtime -> pywebview -> adb。
    """
    problems = []
    for fn in (
        lambda: check_webview2(get_pv),
        lambda: check_pywebview(pywebview_version),
        lambda: check_adb(adb_path),
    ):
        p = fn()
        if p is not None:
            problems.append(p)
    return problems
