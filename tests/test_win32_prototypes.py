# -*- coding: utf-8 -*-
"""门禁：所有 Win32 / WinMM 调用点都必须**显式声明 ctypes 原型**。

为什么这是硬要求
----------------
ctypes 在**没有 argtypes** 时按「默认转换」传参：byref 对象被当成一个整数
（它指向的地址）传下去，而 C int 只有 32 位 —— 64 位下指针就此被截断。
实测（Python 3.11 / x86-64）：

    libc.abs(ctypes.byref(buf))   -> 1210559696   # 不报错，但传的是截断后的地址

于是本项目曾经真实坏掉的功能（第八轮审查逐个查出并修复）：

  * `backend/audio_service.py` 的 waveInOpen / waveInPrepareHeader —— **Windows
    上的电脑麦克风录音根本起不来**（拿到野指针，报出来的是「设备被占用」）；
  * `core/win_theme.py` 的 EnumWindows / IsWindowVisible —— 窗口句柄被截断，
    标题栏配色静默失效；
  * `backend/controllers/file.py` 的 SHBrowseForFolder —— PIDL 指针被截断，
    「选择目录」的兜底路径必然失败；
  * `main.py` 的 GetProcessTimes —— 往被截断的野指针写 FILETIME（内存破坏），
    启动日志里的 process_age 永远拿不到。

这些代码在 Linux CI 上跑不到，纯靠人 review 必然漏。本门禁用 AST 扫描把这条
规则固定下来：新增 Win32 调用若忘了声明原型，测试立刻红。

怎么认出「这是 Win32 调用」
------------------------
基对象（调用点里的 `X.func` 里的 X）满足其一即是：

  * 它是 `ctypes.windll.<dll>` / `ctypes.WinDLL("<dll>")` 之类的赋值结果；
  * 它的名字在常见 Win32 DLL 名单里（user32 / kernel32 / shell32 / ole32 /
    winmm / dwmapi …）—— 覆盖「DLL 对象是函数参数传进来」的情形
    （例如 core/clipboard.py 的 `_bind_win(user32, kernel32)`）。

判定键统一取「基对象的源码写法 + 函数名」：调用 `user32.OpenClipboard(...)` 与
声明 `user32.OpenClipboard.argtypes = ...` 必须用**同一个基对象写法**。
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCAN = [ROOT / "core", ROOT / "backend", ROOT / "main.py"]

# 常见 Win32 DLL 名：基对象用了这些名字就按 Win32 调用处理（覆盖「DLL 对象由
# 函数参数传入」的写法 —— 那种情况静态分析看不出它的真实身份）。
WIN32_DLL_NAMES = {
    "user32", "kernel32", "shell32", "ole32", "oleaut32", "winmm", "dwmapi",
    "gdi32", "advapi32", "ntdll", "ws2_32", "psapi", "comctl32", "shlwapi",
    "wininet", "iphlpapi", "dbghelp", "crypt32", "secur32", "msvcrt",
}


def _files():
    for entry in SCAN:
        if entry.is_dir():
            for p in sorted(entry.rglob("*.py")):
                yield p
        else:
            yield entry


def _dll_like_vars(tree):
    """由 `ctypes.windll.X` / `ctypes.WinDLL(...)` 赋值的变量名。"""
    names = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            v = node.value
            if isinstance(v, ast.Attribute) and v.attr != "windll" \
                    and isinstance(v.value, ast.Attribute) \
                    and v.value.attr == "windll" \
                    and isinstance(v.value.value, ast.Name) \
                    and v.value.value.id == "ctypes":
                names.add(node.targets[0].id)
            elif (isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute)
                  and isinstance(v.func.value, ast.Name)
                  and v.func.value.id == "ctypes"
                  and v.func.attr in ("WinDLL", "CDLL", "OleDLL", "oledll")):
                names.add(node.targets[0].id)
    return names


def _calls_and_decls(tree):
    """返回 (Win32 调用点集合, 已声明原型的集合)。键 = (基对象写法, 函数名)。"""
    dll_vars = _dll_like_vars(tree)
    calls, decls = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            base = node.func.value
            if isinstance(base, ast.Name):
                if base.id in dll_vars or base.id in WIN32_DLL_NAMES:
                    calls.add((ast.unparse(base), node.func.attr))
            elif isinstance(base, ast.Attribute):
                text = ast.unparse(base)
                if text.startswith("ctypes.windll.") or text.startswith("ctypes.WinDLL"):
                    calls.add((text, node.func.attr))
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if (isinstance(tgt, ast.Attribute)
                        and tgt.attr in ("argtypes", "restype")
                        and isinstance(tgt.value, ast.Attribute)):
                    decls.add((ast.unparse(tgt.value.value), tgt.value.attr))
    return calls, decls


def test_all_win32_calls_declare_prototypes():
    """每个 Win32 调用点都要有对应的 argtypes / restype 声明。"""
    problems = []
    for path in _files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls, decls = _calls_and_decls(tree)
        for base, func in sorted(calls - decls):
            problems.append("%s：%s.%s(...) 没有声明 argtypes / restype"
                            % (path.relative_to(ROOT), base, func))
    assert not problems, ("\n".join(problems))


def test_the_guard_detects_an_undeclared_call():
    """门禁本身要有效：构造一个没声明原型的 Win32 调用，必须被判出来。"""
    src = (
        "import ctypes\n"
        "user32 = ctypes.windll.user32\n"
        "def f():\n"
        "    return user32.OpenClipboard(None)\n"
    )
    tree = ast.parse(src)
    calls, decls = _calls_and_decls(tree)
    assert ("user32", "OpenClipboard") in calls
    assert ("user32", "OpenClipboard") not in decls
