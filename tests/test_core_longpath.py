# -*- coding: utf-8 -*-
r"""core.longpath —— Windows 长路径（>260 字符）支持的单测 + 两条全库门禁。

三条门禁（都是 AST 扫描，不依赖 Windows）：
  1. **本地文件 I/O 必须走 long_path()**：core/ backend/ main.py 里凡是做
     open(写) / os.makedirs / os.remove / os.replace / zipfile 的函数，必须
     引用 long_path —— 否则那条路径超过 260 字符时就会「静默丢失」。
  2. **交给 adb 的参数绝不能带前缀**：adb.exe 不认 `\\?\`，带上去必然失败。
  3. 长路径本身的行为（加不加前缀、UNC、幂等）。
"""
import ast
import os
import pathlib

import pytest

from core import longpath

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCAN_DIRS = ("core", "backend")
SCAN_FILES = ("main.py",)


# ---------------------------------------------------------------------------
# 1. long_path 的行为
# ---------------------------------------------------------------------------
def test_short_path_stays_untouched():
    """短路径不加前缀：异常信息与用户看到的路径都保持原样。"""
    p = r"C:\Users\dev\Pictures\ADB\a.png"
    assert longpath.win_long_path(p) == p


def test_long_path_gets_device_prefix():
    """超过阈值的路径加 \\\\?\\ 前缀（Win32 的设备路径形式）。"""
    p = ("C:\\Users\\dev\\work\\2026\\客户A\\车机项目\\第二期\\录屏\\"
         + "很深的归档目录\\" * 24 + "A1_20261112_093000.png")
    assert len(p) >= longpath.LONG_PATH_THRESHOLD
    got = longpath.win_long_path(p)
    assert got.startswith("\\\\?\\")
    assert got.endswith("A1_20261112_093000.png")
    # 前缀后面是完整的原路径（不能被截断或改写）
    assert got[4:] == p


def test_unc_path_uses_unc_prefix():
    """UNC（\\\\server\\share）要写成 \\\\?\\UNC\\server\\share。

    直接加 \\\\?\\ 会变成 \\\\?\\\\server\\share（多一个反斜杠），Win32 认不出。
    """
    p = ("\\\\server\\share\\团队\\2026\\" + "很深的归档目录\\" * 30
         + "a.mp4")
    got = longpath.win_long_path(p)
    assert got.startswith("\\\\?\\UNC\\server\\share\\")


def test_already_prefixed_is_idempotent():
    """已经带前缀的路径不重复加（否则会变成 \\\\?\\UNC?\\...）。"""
    p = r"\\?\C:\very\long\path\a.bin"
    assert longpath.win_long_path(p) == p


def test_empty_and_none_are_safe():
    assert longpath.win_long_path("") == ""
    assert longpath.win_long_path(None) is None


def test_long_path_is_noop_off_windows():
    """非 Windows 上 long_path 原样返回（开发态 / CI 都在 Linux 上跑）。"""
    if os.name == "nt":
        pytest.skip("本用例针对非 Windows")
    p = r"C:\Users\dev\work\2026\客户A\a.png"
    assert longpath.long_path(p) == p


def test_is_too_long_uses_the_real_windows_limit():
    """is_too_long 按 260 判定（问的是「交给 adb 会不会失败」）。"""
    short = r"C:\a\b.bin"
    long_ = "C:\\" + ("x" * 300) + "\\b.bin"
    assert longpath.is_too_long(short) is False
    assert longpath.is_too_long(long_) is True
    assert "260" in longpath.explain_long_path(long_)
    assert "保存目录" in longpath.explain_long_path(long_)


# ---------------------------------------------------------------------------
# 2. 门禁一：本地文件 I/O 必须走 long_path
# ---------------------------------------------------------------------------
def _scan_files():
    for d in SCAN_DIRS:
        for p in sorted((ROOT / d).rglob("*.py")):
            yield p
    for name in SCAN_FILES:
        yield ROOT / name


def _is_os_call(node, names):
    fn = node.func
    if not isinstance(fn, ast.Attribute):
        return False
    if fn.attr not in names:
        return False
    return isinstance(fn.value, ast.Name) and fn.value.id == "os"


def _local_io_calls(fn):
    """函数体内的「本地文件 I/O」调用点。"""
    out = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Name) and f.id == "open":
            mode = "r"
            cand = list(node.args[1:2]) + [k.value for k in node.keywords if k.arg == "mode"]
            for a in cand:
                if isinstance(a, ast.Constant):
                    mode = a.value or "r"
            if any(c in mode for c in "wax+"):
                out.append((node.lineno, "open(%s)" % mode))
        elif _is_os_call(node, ("makedirs", "mkdir", "remove", "unlink", "rmtree",
                                "replace", "copy", "copy2", "copyfile", "move",
                                "rmdir")):
            out.append((node.lineno, "os." + f.attr))
        elif isinstance(f, ast.Name) and f.id == "ZipFile":
            out.append((node.lineno, "ZipFile"))
    return out


def test_all_local_file_io_goes_through_long_path():
    """凡是做本地文件 I/O 的函数，都必须引用 long_path()。

    这条门禁守的是「路径超过 260 字符时静默丢文件」：Windows 的 MAX_PATH 是
    260，用户的归档目录 + 设备名 + 时间戳很容易超；不加 `\\?\\` 前缀的
    open/os.makedirs 会直接失败，而症状是「系统找不到指定的文件」——用户会去
    查权限、查文件存不存在，根本想不到是长度。
    """
    bad = []
    for path in _scan_files():
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for fn in [n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            ios = _local_io_calls(fn)
            if not ios:
                continue
            uses = any(isinstance(n, ast.Name) and n.id == "long_path"
                       for n in ast.walk(fn))
            if not uses:
                bad.append("%s:%d %s() → %s" % (
                    path.relative_to(ROOT), fn.lineno, fn.name,
                    ", ".join("%d:%s" % x for x in ios)))
    assert not bad, ("这些函数做本地文件 I/O 却没走 long_path()：\n  "
                     + "\n  ".join(bad))


# ---------------------------------------------------------------------------
# 3. 门禁二：交给 adb 的参数不能带 \\?\ 前缀
# ---------------------------------------------------------------------------
def test_no_long_path_in_subprocess_arguments():
    r"""subprocess 的参数里不得出现 long_path(...)。

    adb.exe 不认 Win32 的设备路径：`\\?\C:\...` 会被它当成一个名字里带
    反斜杠的怪路径，pull / push 必然失败。所以凡是交给外部程序的路径
    （adb pull 的目标、adb push 的源）必须保持「人话」形式 —— 长路径问题
    改用**预检 + 中文提示**来解决（见 core/longpath.is_too_long）。
    """
    bad = []
    for path in _scan_files():
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if not (isinstance(f, ast.Attribute) and f.attr in ("run", "Popen")
                    and isinstance(f.value, ast.Name)
                    and f.value.id == "subprocess"):
                continue
            if not node.args:
                continue
            argv = node.args[0]
            for n in ast.walk(argv):
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                        and n.func.id == "long_path"):
                    bad.append("%s:%d" % (path.relative_to(ROOT), node.lineno))
    assert not bad, ("这些 subprocess 调用把 \\?\\ 前缀传给了外部程序：\n  "
                     + "\n  ".join(bad))
