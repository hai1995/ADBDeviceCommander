"""tools/check_native_dll.py 的单测：CI 产物指纹闸门。

不依赖真实 Windows DLL：用假 loader 覆盖「读到指纹 / 旧 DLL 无符号 / 加载失败」
等分支，确保「旧 DLL 混进产物」一定被测出、新 DLL 一定放行。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.check_native_dll as chk  # noqa: E402


# ---- source_build_id -------------------------------------------------------
def test_source_build_id_parses_constant(tmp_path):
    cpp = tmp_path / "adc_mf_sink.cpp"
    cpp.write_text('static const char* const kBuildId = "mf-20261123-esdsdiag-v4";\n',
                   encoding="utf-8")
    assert chk.source_build_id(cpp) == "mf-20261123-esdsdiag-v4"


def test_source_build_id_missing_returns_empty(tmp_path):
    cpp = tmp_path / "x.cpp"
    cpp.write_text("int main() { return 0; }\n", encoding="utf-8")
    assert chk.source_build_id(cpp) == ""


# ---- dll_build_id（假 loader）---------------------------------------------
class _FakeLib:
    def __init__(self, value=b"mf-test-v1"):
        self._value = value

    def adc_build_id(self):
        return self._value


def test_dll_build_id_from_bytes():
    assert chk.dll_build_id("fake.dll", load=lambda p: _FakeLib(b"mf-v2")) == "mf-v2"


def test_dll_build_id_from_str():
    assert chk.dll_build_id("fake.dll", load=lambda p: _FakeLib("mf-v3")) == "mf-v3"


def test_dll_build_id_old_dll_no_symbol():
    class NoSymbol:
        pass
    assert chk.dll_build_id("old.dll", load=lambda p: NoSymbol()) == ""


def test_dll_build_id_load_failure_is_empty():
    def boom(p):
        raise OSError("bad dll")
    assert chk.dll_build_id("bad.dll", load=boom) == ""


def test_dll_build_id_bad_type_is_empty():
    assert chk.dll_build_id("x.dll", load=lambda p: _FakeLib(12345)) == ""


# ---- verify ----------------------------------------------------------------
def _cpp_with(tmp_path, stamp):
    cpp = tmp_path / "adc_mf_sink.cpp"
    cpp.write_text(f'static const char* const kBuildId = "{stamp}";\n', encoding="utf-8")
    dll = tmp_path / "adc_mf_sink.dll"
    dll.write_bytes(b"MZ")
    return cpp, dll


def test_verify_missing_cpp(tmp_path):
    ok, code, msg = chk.verify(tmp_path / "no.cpp", tmp_path / "x.dll")
    assert not ok and code == 1 and "源码" in msg


def test_verify_missing_dll(tmp_path):
    cpp, _ = _cpp_with(tmp_path, "mf-v1")
    ok, code, msg = chk.verify(cpp, tmp_path / "no.dll")
    assert not ok and code == 1 and "cmake" in msg.lower()


def test_verify_source_without_stamp(tmp_path):
    cpp = tmp_path / "x.cpp"
    cpp.write_text("no stamp here", encoding="utf-8")
    dll = tmp_path / "x.dll"
    dll.write_bytes(b"MZ")
    ok, code, msg = chk.verify(cpp, dll)
    assert not ok and code == 1 and "kBuildId" in msg


def test_verify_dll_stamp_unreadable_is_rejected(tmp_path):
    """旧 DLL（无符号）必须被判失败——这正是要拦的场景。"""
    cpp, dll = _cpp_with(tmp_path, "mf-v1")
    ok, code, msg = chk.verify(cpp, dll, load=lambda p: _FakeLib(b""))
    assert not ok and code == 3 and "旧 DLL" in msg


def test_verify_mismatch_is_rejected(tmp_path):
    """DLL 指纹与源码不一致 = 旧 DLL 混进产物，必须失败。"""
    cpp, dll = _cpp_with(tmp_path, "mf-new")
    ok, code, msg = chk.verify(cpp, dll, load=lambda p: _FakeLib(b"mf-old"))
    assert not ok and code == 2 and "不一致" in msg and "mf-new" in msg and "mf-old" in msg


def test_verify_match_passes(tmp_path):
    cpp, dll = _cpp_with(tmp_path, "mf-good")
    ok, code, msg = chk.verify(cpp, dll, load=lambda p: _FakeLib(b"mf-good"))
    assert ok and code == 0 and "mf-good" in msg


def test_main_exit_codes(tmp_path, capsys):
    cpp, dll = _cpp_with(tmp_path, "mf-x")
    assert chk.main(["--source", str(cpp), "--dll", str(dll)]) in (0, 2, 3)
    # 真实加载 fake dll 在 Linux 上失败 → 非 0；这里只确认不抛异常即可。
