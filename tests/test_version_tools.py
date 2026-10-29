"""tools/bump_version.py（版本号递增）与 tools/package.py（打包）的单元测试。"""
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import bump_version as bv  # noqa: E402
from tools import package as pkg      # noqa: E402

VER_RE = re.compile(r"^\d{4}\.\d{4}\.\d{4}$")


# ---------------- next_version：严格递增 ----------------
def test_next_version_uses_real_time_when_ahead():
    """真实时间领先于当前版本 -> 直接用真实时间。"""
    now = datetime(2026, 9, 4, 15, 30)
    assert bv.next_version("2026.0904.1400", now) == "2026.0904.1530"


def test_next_version_bumps_by_one_minute_when_clock_behind():
    """真实时间落后（如历史版本被写成未来）-> 在现有版本上 +1 分钟，不倒退。"""
    now = datetime(2026, 9, 4, 14, 3)
    assert bv.next_version("2026.0904.2100", now) == "2026.0904.2101"


def test_next_version_never_returns_same_or_lower():
    """任意组合下都必须严格递增（同一分钟内重复调用也不能撞号）。"""
    now = datetime(2026, 9, 4, 14, 3)
    for cur in ["2026.0904.1403", "2026.0904.1404", "2026.0904.2359",
                "2026.0905.0000", "2026.1231.2359"]:
        new = bv.next_version(cur, now)
        assert VER_RE.match(new), f"格式非法：{new}"
        assert new > cur, f"未递增：{cur} -> {new}"


def test_next_version_rolls_over_midnight():
    """跨天边界：23:59 后 +1 分钟应正确进位到次日 00:00。"""
    now = datetime(2026, 9, 4, 14, 3)
    assert bv.next_version("2026.0904.2359", now) == "2026.0905.0000"


def test_reset_to_now_restores_real_time_baseline():
    """--reset-to-now：忽略单调约束，回到真实时间（一次性基线修正）。"""
    now = datetime(2026, 9, 4, 14, 7)
    assert bv.next_version("2026.0904.2100", now, reset=True) == "2026.0904.1407"


def test_reset_to_now_same_minute_still_increases():
    """同一分钟内重复修正，也不能撞号。"""
    now = datetime(2026, 9, 4, 14, 7)
    assert bv.next_version("2026.0904.1407", now, reset=True) == "2026.0904.1408"


def test_next_version_default_now_is_monotonic():
    """不传 now 时（走真实时钟），结果也必须严格大于当前版本。"""
    cur = "2026.0904.2359"
    new = bv.next_version(cur)
    assert new > cur


# ---------------- 格式校验 ----------------
@pytest.mark.parametrize("bad", ["", "2026-09-04.1400", "26.0904.1400",
                                 "2026.0904.140", "abcdefghijkl", "2026.0904.9999"])
def test_parse_version_rejects_invalid(bad):
    with pytest.raises(bv.VersionError):
        bv.parse_version(bad)


def test_parse_version_accepts_valid():
    assert bv.parse_version("2026.0904.1407") == datetime(2026, 9, 4, 14, 7)


# ---------------- read / write ----------------
def _make_project(tmp_path: Path, const_ver: str, main_ver: str) -> Path:
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "constants.py").write_text(
        f'VERSION = "{const_ver}"\nOTHER = 1\n', encoding="utf-8")
    (tmp_path / "main.py").write_text(
        f'import sys\nVERSION = "{main_ver}"\n', encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "## 架构（v2026.0101.0000 Web 版）\n\n正文\n", encoding="utf-8")
    return tmp_path


def test_read_version_ok(tmp_path):
    root = _make_project(tmp_path, "2026.0904.1407", "2026.0904.1407")
    assert bv.read_version(root) == "2026.0904.1407"


def test_read_version_mismatch_raises(tmp_path):
    root = _make_project(tmp_path, "2026.0904.1407", "2026.0904.1408")
    with pytest.raises(bv.VersionError) as e:
        bv.read_version(root)
    assert "不一致" in str(e.value)


def test_write_version_updates_all_hardcoded_spots(tmp_path):
    root = _make_project(tmp_path, "2026.0904.1407", "2026.0904.1407")
    changed = bv.write_version("2026.0904.1500", root)

    assert set(changed) == {"core/constants.py", "main.py", "README.md"}
    assert bv.read_version(root) == "2026.0904.1500"
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "## 架构（v2026.0904.1500 Web 版）" in readme
    # 不应误伤其它 VERSION 之外的行
    assert "OTHER = 1" in (root / "core" / "constants.py").read_text(encoding="utf-8")
    assert "import sys" in (root / "main.py").read_text(encoding="utf-8")


def test_write_version_rejects_bad_format(tmp_path):
    root = _make_project(tmp_path, "2026.0904.1407", "2026.0904.1407")
    with pytest.raises(bv.VersionError):
        bv.write_version("not-a-version", root)


# ---------------- 打包结构（扁平、无顶层目录） ----------------
def test_project_version_files_are_in_sync():
    """工程真实文件的两处 VERSION 必须一致（防止手改发散）。"""
    assert bv.read_version(ROOT)  # 不一致会抛 VersionError


def test_packaged_zip_is_flat_and_named_by_version(tmp_path):
    """用真实工程打一个临时包，校验：扁平结构 + 命名带版本号。"""
    from tools import package as pkg

    out = tmp_path / "ADBDeviceCommander_v9999.1231.2359.zip"
    n, size = pkg.build_zip(ROOT, out)
    assert n > 0 and size > 0

    with zipfile.ZipFile(out) as z:
        names = z.namelist()
    # 扁平：顶层直接是工程文件，不能多套一层 ADBDeviceCommander/
    assert not any(p.split("/")[0] == "ADBDeviceCommander" for p in names)
    assert "main.py" in names
    assert "core/constants.py" in names
    assert "frontend/index.html" in names
    # 排除项不应进包
    assert not any("__pycache__" in p or p.endswith(".pyc") for p in names)
    # 命名规则可被解析
    assert pkg.ZIP_RE.match(out.name)


def test_package_excludes_dev_only_dirs(tmp_path):
    """package.py 的排除规则必须挡住虚拟环境等「只属于开发机」的目录。

    回归：EXCLUDE_DIRS 曾漏掉 .venv / venv，于是 `python tools/package.py` 会把
    整个虚拟环境打进「干净源码包」（本案 ~3300 个文件、60+MB），产物凭空膨胀
    两百倍，还把开发机上的第三方依赖一并散播出去。
    """
    root = tmp_path / "proj"
    (root / "core").mkdir(parents=True)
    (root / "core" / "constants.py").write_text('VERSION = "2026.0904.1407"\n',
                                                encoding="utf-8")
    (root / "main.py").write_text('VERSION = "2026.0904.1407"\n', encoding="utf-8")
    for d in (".venv", "venv", "node_modules", "__pycache__", "dist", ".git"):
        p = root / d
        p.mkdir()
        (p / "junk.py").write_text("x = 1\n", encoding="utf-8")
    (root / "settings.json").write_text("{}", encoding="utf-8")
    (root / "adb_devaudio_A1.wav").write_bytes(b"RIFF")

    names = [p.relative_to(root).as_posix() for p in pkg.iter_files(root)]
    assert "core/constants.py" in names and "main.py" in names
    for d in (".venv", "venv", "node_modules", "__pycache__", "dist", ".git"):
        assert not any(n.startswith(d + "/") for n in names), \
            "%s 不该进源码分发包：%r" % (d, names)
    assert "settings.json" not in names, "运行时个人配置不该进包"
    assert not any(n.endswith(".wav") for n in names), "调试录音残留不该进包"


def test_package_never_includes_its_own_output(tmp_path):
    """产物落在工程目录内时，zip 绝不能把自己收录进去。

    回归：`ZipFile(out, "w")` 会先创建产物文件，之后 os.walk 才遍历目录树 ——
    若 out 在 root 之内，遍历到产物所在目录时它已存在，zip 便不断把自身往里塞，
    体积无限膨胀（实测涨到数 GB 才因磁盘满 / 超时停下）。
    """
    root = tmp_path / "proj"
    root.mkdir()
    (root / "main.py").write_text("x = 1\n", encoding="utf-8")
    out = root / "sub" / "ADBDeviceCommander_v9999.1231.2359.zip"
    out.parent.mkdir()
    n, size = pkg.build_zip(root, out)
    assert n == 1, "只应打进 main.py 本身（实际 %d 个文件）" % n
    assert size < 4096, "产物不得自我收录而膨胀（实际 %d 字节）" % size
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
    assert names == ["main.py"], names


# ---------------- 命令行错误路径：必须是中文提示 + 退出码 2，不是 traceback -------
def test_set_invalid_date_reports_error_not_traceback(capsys):
    """`--set 2026.0230.1200`（正则合法但不是真实日期）要给出中文错误。

    回归：parse_version / next_version 调用点落在 try/except 之外，这类取值会以
    未捕获的 VersionError 直接抛出去（英文 traceback + 退出码 1），与本脚本约定的
    「[错误] …」+ 退出码 2 不一致。
    """
    assert bv.main(["--set", "2026.0230.1200"]) == 2
    err = capsys.readouterr().err
    assert "不是合法时间" in err, err
    assert "Traceback" not in err


def test_next_version_overflow_is_reported(monkeypatch, capsys):
    """版本号递增溢出（year 9999 再 +1 分钟）必须转成中文错误而不是 OverflowError。

    注意：main() 读写的是工程真实的 ROOT，所以这里只替换 next_version —— 
    绝不能真的去改本仓库的 VERSION 文件。
    """
    monkeypatch.setattr(bv, "read_version", lambda *a, **kw: "9999.1231.2359")

    def overflow(*a, **kw):
        raise OverflowError("date value out of range")

    monkeypatch.setattr(bv, "next_version", overflow)
    assert bv.main(["--apply"]) == 2
    err = capsys.readouterr().err
    assert "超出可表示范围" in err, err
    assert "Traceback" not in err
