"""CI 发版链路守卫：确保 release / build 两个工作流都把 native 修复编进产物。

用户只从 GitHub Release 下载 exe、从不本地编译。同源录制的修复全在 C++
（native/adc_mf_sink.cpp），只有 CI 重新编译并嵌进包才生效。这些测试把
「编译 → 指纹自证 → 缺 dll 硬失败」三步锁进 YAML，任何一步被误删都会变红，
从配置层面根治「改了代码却没进产物、用户反复测到老错误」。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WF = ROOT / ".github" / "workflows"


def _windows_job_block(name):
    """截出 windows job（含 native 编译与构建命令）那段，避免匹配到 test job。"""
    text = (WF / name).read_text(encoding="utf-8")
    return text[text.index("windows:"):]


def _assert_native_gate(name):
    block = _windows_job_block(name)
    # 1) 必须编译 native（cmake 配置 / build / install 三步）
    assert "cmake -S native -B native/build -A x64" in block, name
    assert "cmake --build native/build --config Release" in block, name
    assert "cmake --install native/build --prefix backend" in block, name
    # 2) 编译产物存在性检查
    assert "backend/adc_mf_sink.dll" in block, name
    # 3) 指纹自证闸门：DLL 指纹必须等于源码，防止旧 DLL 混进产物
    assert "tools/check_native_dll.py" in block, name
    # 4) 构建命令必须开 --require-native，缺 dll 直接失败不静默降级
    assert "python build.py --onefile --package --zip --require-native" in block, name


def test_release_workflow_native_gate():
    _assert_native_gate("release.yml")


def test_build_workflow_native_gate():
    _assert_native_gate("build.yml")


def test_check_native_dll_script_exists():
    """守卫脚本本身必须在仓库里，且是纯标准库实现（CI 无需额外依赖）。"""
    p = ROOT / "tools" / "check_native_dll.py"
    assert p.is_file()
    src = p.read_text(encoding="utf-8")
    assert "ctypes" in src and "kBuildId" in src and "adc_build_id" in src


def test_build_py_has_require_native_flag():
    """build.py 必须定义 --require-native 开关及失败码。"""
    src = (ROOT / "build.py").read_text(encoding="utf-8")
    assert '"--require-native"' in src
    assert "return 7" in src
