"""core.constants 里「子进程统一参数」助手的单元测试。

adb 输出固定为 UTF-8，而中文 Windows 的默认编码是 cp936：不显式指定 encoding
就会把设备端的中文文件名/日志解成乱码。打包成 GUI（--windowed）后，控制台子
进程还会一闪一个黑窗，故需要 CREATE_NO_WINDOW。
"""
import subprocess as sp
import sys

from core.constants import (
    adb_kwargs, adb_popen_kwargs, no_window_flags, safe_name,
    unique_path,
)


def test_adb_kwargs_uses_utf8_and_hides_window():
    kw = adb_kwargs(15)
    assert kw["encoding"] == "utf-8", "adb 输出必须按 UTF-8 解码，否则中文文件名乱码"
    assert kw["errors"] == "replace"
    assert kw["text"] is True
    assert kw["capture_output"] is True
    assert kw["timeout"] == 15
    assert "creationflags" in kw


def test_adb_kwargs_without_timeout_and_extra():
    kw = adb_kwargs(cwd="/tmp")
    assert "timeout" not in kw, "不给 timeout 就不应带上（否则会顶掉调用方默认）"
    assert kw["cwd"] == "/tmp"


def test_adb_popen_kwargs_uses_utf8():
    kw = adb_popen_kwargs()
    assert kw["encoding"] == "utf-8"
    assert kw["errors"] == "replace"
    assert kw["creationflags"] == no_window_flags()


def test_no_window_flags_is_valid_for_platform():
    flags = no_window_flags()
    if sys.platform.startswith("win"):
        assert flags == getattr(sp, "CREATE_NO_WINDOW", 0)
        assert flags != 0, "Windows 下应带上 CREATE_NO_WINDOW，避免闪黑窗"
    else:
        assert flags == 0, "非 Windows 不应传 Windows 专属 flags"


# ---------------------------------------------------------------------------
# safe_name：设备序列号拼进文件名前的净化（无线 ADB 序列号含冒号）
# ---------------------------------------------------------------------------
def test_safe_name_replaces_windows_illegal_chars():
    """Windows 文件名非法字符（<>:"/\\|?*）必须全部被替换。

    回归：无线 ADB 序列号形如 192.168.1.5:5555，冒号是 Windows 文件名非法
    字符——截图/录屏/logcat 文件名直接拼它会 open() 失败，功能静默丢失。
    """
    assert safe_name("192.168.1.5:5555") == "192.168.1.5_5555"
    for ch in '<>:"/\\|?*':
        assert ch not in safe_name("a%sb" % ch), "非法字符 %r 未被替换" % ch


def test_safe_name_keeps_normal_serial_unchanged():
    """普通 USB 序列号（字母数字 + . - _）应原样保留，可读性不受影响。"""
    assert safe_name("0612333ABCD") == "0612333ABCD"
    assert safe_name("emulator-5554") == "emulator-5554"


def test_safe_name_strips_trailing_dots_and_spaces():
    """Windows 同样不接受首尾空白与尾部点/空格，必须去掉。"""
    assert safe_name("  A1  ") == "A1"
    assert safe_name("A1.") == "A1"
    assert safe_name("A1... ") == "A1"


def test_safe_name_falls_back_when_empty():
    """净化后为空（空串 / 全是非法字符）时回退默认名，绝不返回空文件名。"""
    assert safe_name("") == "device"
    assert safe_name(None) == "device"
    assert safe_name(':::') == "device"
    assert safe_name("", fallback="x") == "x"


# ---------------------------------------------------------------------------
# unique_path：同一秒内的第二份产物不能覆盖第一份
# ---------------------------------------------------------------------------
def test_unique_path_returns_path_when_free(tmp_path):
    p = str(tmp_path / "a.txt")
    assert unique_path(p) == p


def test_unique_path_appends_counter_instead_of_overwriting(tmp_path):
    """已存在就补 _2 / _3：时间戳只到秒，「停止 → 立刻再开始」很容易撞名。"""
    p = str(tmp_path / "a.txt")
    (tmp_path / "a.txt").write_text("旧内容", encoding="utf-8")
    assert unique_path(p) == str(tmp_path / "a_2.txt")
    (tmp_path / "a_2.txt").write_text("x", encoding="utf-8")
    assert unique_path(p) == str(tmp_path / "a_3.txt")
    # 原文件一个字节都没被动过
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "旧内容"


def test_unique_path_considers_related_suffixes(tmp_path):
    """勾了「结束后打包」时源 txt 已被删，只剩同名 .zip —— 也必须算作已占用。

    只查 txt 会误判为空位，停止时 ZipFile(..., "w") 又把那份唯一的压缩包覆盖掉。
    """
    p = str(tmp_path / "a.txt")
    (tmp_path / "a.txt.zip").write_bytes(b"PK")
    assert unique_path(p, suffixes=(".zip",)) == str(tmp_path / "a_2.txt")
    # 不传 suffixes 时不看 .zip（调用方明确知道自己只产这一个文件）
    assert unique_path(p) == p


def test_unique_path_handles_no_extension(tmp_path):
    """报告一类「共用一个基名、各自加扩展名」的场合，基名本身没有扩展名。"""
    p = str(tmp_path / "perf_X_20260101")
    (tmp_path / "perf_X_20260101.csv").write_text("x", encoding="utf-8")
    assert unique_path(p, suffixes=(".html", ".csv")) == str(tmp_path / "perf_X_20260101_2")
