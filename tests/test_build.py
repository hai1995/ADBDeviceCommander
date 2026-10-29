"""build.py（PyInstaller 打包脚本）的单元测试。

只测「参数构造 / 资源自检 / 产物目录推断 / 分发清理」这些纯逻辑，不真的跑 PyInstaller。
"""
import json
import os
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import build  # noqa: E402


def _args(**kw):
    """构造一个 argparse 命名空间（只含 pyinstaller_args 用到的字段）。"""
    base = dict(mode="onefile", console=False, clean=True,
                dist_dir=Path("dist"), work_dir=Path("build"), log_level="WARN")
    base.update(kw)
    return type("Args", (), base)()


def test_default_is_onefile_windowed_with_icon():
    args = build.pyinstaller_args(_args())
    assert "--onefile" in args
    assert "--windowed" in args
    assert "--clean" in args
    assert "--noconfirm" in args
    assert args[args.index("--name") + 1] == build.APP_NAME
    assert "--icon" in args


def test_console_mode_drops_windowed():
    args = build.pyinstaller_args(_args(console=True))
    assert "--console" not in args          # 不加 --windowed 即等价控制台模式
    assert "--windowed" not in args


def test_onedir_mode():
    args = build.pyinstaller_args(_args(mode="onedir", clean=False))
    assert "--onedir" in args
    assert "--onefile" not in args
    assert "--clean" not in args


@pytest.mark.parametrize("src,dst", build.BUNDLED_DATA)
def test_every_bundled_data_is_passed(src, dst):
    """frontend 必须进包——旧 bat 漏了它，打包后窗口会空白（回归锁定）。"""
    # 必须传绝对路径：相对路径会被 PyInstaller 按 spec 目录（build/）解析而找不到
    sep = ";" if sys.platform.startswith("win") else ":"
    assert "%s%s%s" % (ROOT / src, sep, dst) in build.pyinstaller_args(_args())


def test_excludes_and_paths():
    args = build.pyinstaller_args(_args(dist_dir=Path("out"), work_dir=Path("tmp")))
    for mod in build.EXCLUDE_MODULES:
        assert mod in args
    # 先打到 build/ 下的暂存区，再由脚本拷进 dist/：避免 PyInstaller 删除旧 exe 失败
    assert Path(args[args.index("--distpath") + 1]).name == "dist_stage"
    assert Path(args[args.index("--workpath") + 1]).name == "tmp"
    # .spec 落在 work_dir，不污染工程根
    assert Path(args[args.index("--specpath") + 1]).name == "tmp"
    assert args[-1] == str(ROOT / build.ENTRY)


def test_publish_from_stage_copies_exe(tmp_path):
    """暂存区产物被拷进 dist（覆盖写，不删旧文件 → 重复打包始终可用）。"""
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "app.exe").write_bytes(b"MZ")
    dist = tmp_path / "dist"
    dist.mkdir()
    old = dist / "app.exe"
    old.write_bytes(b"OLD")            # 旧产物：不应被删除，只被覆盖

    exe = build.publish_from_stage(stage, dist, old, "onefile")
    assert exe == old
    assert old.read_bytes() == b"MZ", "旧 exe 应被新产物覆盖"


def test_publish_from_stage_missing_product(tmp_path):
    assert build.publish_from_stage(tmp_path / "nope", tmp_path / "dist",
                                    tmp_path / "dist" / "app.exe", "onefile") is None


def test_stage_dir_is_under_work_dir():
    assert build.stage_dir(Path("build")) == Path("build").resolve() / "dist_stage"


def test_real_project_sources_are_complete():
    """真实工程下入口与全部数据文件都必须存在。"""
    assert build.check_sources() == []


def test_check_sources_reports_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "ROOT", tmp_path)
    (tmp_path / build.ENTRY).write_text("print(1)", encoding="utf-8")
    assert build.check_sources() == [src for src, _ in build.BUNDLED_DATA]


def test_exe_dir_differs_by_mode():
    dist = Path("dist")
    assert build.exe_dir(dist, "onefile") == dist
    assert build.exe_dir(dist, "onedir") == dist / build.APP_NAME


# ---------------------------------------------------------------------------
# 分发清理（复发防护：node_modules / __pycache__ 不进源码分发包）
# ---------------------------------------------------------------------------
def test_app_version_reads_from_source(tmp_path):
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "constants.py").write_text(
        '# -*- coding: utf-8 -*-\nVERSION = "2026.1013.2244"\n', encoding="utf-8")
    assert build.app_version(tmp_path) == "2026.1013.2244"


def test_app_version_falls_back_to_dev(tmp_path):
    assert build.app_version(tmp_path) == "dev"


def test_clean_junk_removes_caches_but_keeps_node_modules(tmp_path):
    (tmp_path / "backend" / "__pycache__").mkdir(parents=True)
    (tmp_path / "backend" / "__pycache__" / "x.pyc").write_bytes(b"x")
    (tmp_path / "core" / "__pycache__").mkdir(parents=True)
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / "backend" / "keep.py").write_text("print(1)")
    node = tmp_path / "tests" / "frontend" / "node_modules"
    node.mkdir(parents=True)

    removed = build.clean_junk(tmp_path)

    assert not (tmp_path / "backend" / "__pycache__").exists()
    assert not (tmp_path / "core" / "__pycache__").exists()
    assert not (tmp_path / ".pytest_cache").exists()
    assert (tmp_path / "backend" / "keep.py").exists()
    # node_modules 是前端测试依赖：清缓存不能顺手把它删了（删了要重装）
    assert node.is_dir()
    assert len(removed) == 3


def test_source_zip_excludes_junk(tmp_path):
    root = tmp_path / "proj"
    (root / "backend").mkdir(parents=True)
    (root / "backend" / "a.py").write_text("print(1)")
    (root / "backend" / "__pycache__").mkdir()
    (root / "backend" / "__pycache__" / "a.pyc").write_bytes(b"x")
    nm = root / "tests" / "frontend" / "node_modules" / "jsdom"
    nm.mkdir(parents=True)
    (nm / "big.js").write_text("x" * 4096)
    (root / "settings.json").write_text('{"save_dir": "D:\\\\BUG"}')
    (root / "config.json").write_text('{"save_dir": "D:\\\\BUG2"}')
    (root / "core").mkdir()
    (root / "core" / "constants.py").write_text(
        'VERSION = "2026.1013.2244"\n', encoding="utf-8")

    zp = build.make_source_zip(root, tmp_path / "dist")

    assert zp is not None and zp.exists()
    assert zp.name == "ADBDeviceCommander_v2026.1013.2244.zip"
    names = zipfile.ZipFile(zp).namelist()
    top = zp.stem + "/"
    assert top + "backend/a.py" in names
    assert top + "core/constants.py" in names
    for bad in ("backend/__pycache__/a.pyc",
                "tests/frontend/node_modules/jsdom/big.js",
                "settings.json",
                "config.json"):
        assert bad not in names, "分发包不应包含 %s" % bad
    # 所有条目都挂在同一个顶层目录下：解压不会散落一地，
    # 顶层也没有 index.html（否则云端导入会把它当网页包解包成空壳页面）
    assert all(n.startswith(top) for n in names), names
    assert "index.html" not in names


def test_source_zip_excludes_build_outputs_and_crash_logs(tmp_path):
    """源码分包必须同时挡掉「自定义产物目录 / exe / 崩溃日志」。

    回归：目录排除只按名字匹配（dist / build），`--dist-dir release` 时整个产物目录
    会被整棵遍历，把 20~35MB 的 exe 当成「源码」打进去；`crash_<时间戳>.log`
    （含完整 traceback、本机路径、设备序列号）也没有排除规则。
    """
    root = tmp_path / "proj"
    root.mkdir()
    (root / "main.py").write_text("print(1)", encoding="utf-8")
    (root / "core").mkdir()
    (root / "core" / "constants.py").write_text(
        'VERSION = "2026.1013.2244"\n', encoding="utf-8")
    # 自定义产物目录（名字不是 dist/build）
    out = root / "release"
    out.mkdir()
    (out / "ADB设备指令台.exe").write_bytes(b"MZ" + b"\x00" * 4096)
    # 工程根下的崩溃日志
    (root / "crash_20261014_210600.log").write_text("Traceback ...", encoding="utf-8")

    zp = build.make_source_zip(root, out)

    names = zipfile.ZipFile(zp).namelist()
    top = zp.stem + "/"
    assert top + "main.py" in names
    assert not any(n.endswith(".exe") for n in names), names
    assert not any((top + "release/") in n for n in names), \
        "自定义产物目录不该进源码包：%r" % names
    assert not any("crash_" in n for n in names), \
        "崩溃日志不该进源码包：%r" % names


def test_real_source_zip_is_lean(tmp_path):
    """真实工程打源码包：必须排除 node_modules/__pycache__，且总体积受控。"""
    zp = build.make_source_zip(build.ROOT, tmp_path)
    names = zipfile.ZipFile(zp).namelist()
    top = zp.stem + "/"
    assert names, "源码包不能为空"
    assert top + "main.py" in names
    assert top + "frontend/index.html" in names, "界面文件必须随源码分发"
    assert not any("__pycache__" in n for n in names)
    assert not any("node_modules" in n for n in names)
    assert not any(n.endswith(".pyc") for n in names)
    assert "settings.json" not in names, "个人运行配置不进分发包"
    assert "config.json" not in names, "个人运行配置不进分发包"
    assert all(n.startswith(top) for n in names), \
        "所有条目必须挂在同一个顶层目录下：%r" % names[:5]
    size_kb = zp.stat().st_size / 1024
    assert size_kb < 1024, "源码分发包应控制在 1MB 以内，实际 %.1f KB" % size_kb


# ---------------------------------------------------------------------------
# cryptography 排除（修复 Windows 打包 SubprocessDiedError）
# ---------------------------------------------------------------------------
def test_cryptography_is_excluded_from_pyinstaller():
    """cryptography 必须被 --exclude-module 排除。

    背景：pywebview 只在 ssl=True 时 import 它，但 PyInstaller 静态分析仍会把
    它拖进依赖图并执行其 hook 的 collect_submodules——隔离子进程在个别 Windows
    环境以堆损坏（0xC0000374）崩溃，整个打包失败（回归锁定）。
    """
    args = build.pyinstaller_args(_args())
    assert "cryptography" in build.EXCLUDE_MODULES
    idx = args.index("cryptography")
    assert idx > 0 and args[idx - 1] == "--exclude-module"


def test_project_source_never_imports_cryptography():
    """安全网：项目自身代码不 import cryptography，排除它才是安全的。

    pywebview 的函数级 import 在 site-packages 里、不受影响；这里用 AST 精确
    解析工程源码里的 import 语句（注释 / 字符串里的字样不算）。一旦将来项目
    真的需要 cryptography，本测试失败，提醒先从 EXCLUDE_MODULES 移除排除项，
    否则打出的 exe 运行时会 ImportError。
    """
    import ast
    # 只扫「工程自身」的源码：虚拟环境 / node_modules / 构建产物里全是第三方
    # 模块——.venv 就放在工程根目录下时，site-packages 里的 cryptography hook
    # 会被一并扫到，测试将永远失败（与工程代码无关）。排除目录与
    # build.SOURCE_ZIP_EXCLUDE_DIRS 保持一致。
    skip_dirs = {"__pycache__", "tests", ".venv", "venv", "site-packages",
                 "node_modules", "build", "dist", ".git", ".pytest_cache"}
    srcs = [p for p in sorted(build.ROOT.glob("**/*.py"))
            if not (set(p.parts) & skip_dirs)]
    assert srcs, "未找到工程源码"
    for p in srcs:
        if "__pycache__" in p.parts or "tests" in p.parts:
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for n in names:
                assert n.split(".")[0] != "cryptography", \
                    "%s import 了 cryptography，须先从 EXCLUDE_MODULES 移除排除" % p


def test_webview_start_never_uses_ssl():
    """pywebview 的 SSL 模式才会用到 cryptography；本项目不启用。"""
    main_py = (build.ROOT / build.ENTRY).read_text(encoding="utf-8")
    assert "ssl=True" not in main_py, "启用了 SSL 模式就必须把 cryptography 加回依赖"


# ---------------------------------------------------------------------------
# 命令行开关：文档里写过的写法必须真的可用
# ---------------------------------------------------------------------------
def test_documented_onedir_flag_is_accepted(monkeypatch):
    """`python build.py --onedir` 必须能跑。

    回归：build.py 头部说明与 README 一直写 `--onedir`，但实际只存在
    `--mode {onefile,onedir}` —— 照文档执行会立刻 `unrecognized arguments` 退出码 2，
    而这正是文档推荐用来「排查缺文件」的模式。
    """
    monkeypatch.setattr(build, "check_sources", lambda: [])
    monkeypatch.setattr(build, "clean_junk", lambda root: [])
    monkeypatch.setattr(build, "run_pyinstaller", lambda args, dry: (0, ""))
    assert build.main(["--onedir", "--dry-run", "--no-deps"]) == 0
    assert build.main(["--onefile", "--dry-run", "--no-deps"]) == 0
    assert build.main(["--mode", "onedir", "--dry-run", "--no-deps"]) == 0


def test_bump_failure_reports_chinese_instead_of_traceback(monkeypatch, capsys):
    """`--bump` 在版本号工具报错时给出中文原因，而不是 CalledProcessError 堆栈。"""
    import subprocess as sp

    monkeypatch.setattr(build, "check_sources", lambda: [])
    monkeypatch.setattr(build, "clean_junk", lambda root: [])
    monkeypatch.setattr(build, "run_pyinstaller", lambda args, dry: (0, ""))

    def boom(cmd):
        raise sp.CalledProcessError(2, cmd)

    monkeypatch.setattr(build.subprocess, "check_call", boom)
    rc = build.main(["--bump", "--no-deps"])
    assert rc == 4, "版本号递增失败应返回专用退出码，实际 %r" % rc
    err = capsys.readouterr().err
    assert "版本号递增失败" in err
    assert "VERSION" in err


# ---------------------------------------------------------------------------
# Windows 构建产物被占用：预检 + 失败定性（用户实报的打包崩溃回归）
#    旧行为：暂存 exe 被占用时 PyInstaller 白跑几分钟，收尾步骤
#   set_exe_build_timestamp 抛 PermissionError，用户看到一段英文 traceback。
# ---------------------------------------------------------------------------
def test_file_locked_detects_occupied_file(tmp_path, monkeypatch):
    """被占用的文件（打不开读写）必须被认出；普通文件不误报。"""
    locked = tmp_path / "locked.exe"
    locked.write_bytes(b"MZ")
    free = tmp_path / "free.exe"
    free.write_bytes(b"MZ")
    real_open = open

    def fake_open(p, *a, **kw):
        if str(p) == str(locked):
            raise PermissionError(13, "Permission denied")
        return real_open(p, *a, **kw)

    monkeypatch.setattr("builtins.open", fake_open)
    assert build._file_locked(locked) is True
    assert build._file_locked(free) is False
    assert build._file_locked(tmp_path / "not-exist.exe") is False


class _FakeStdout:
    def __init__(self, lines):
        self._it = iter(lines)

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._it)

    def close(self):
        pass


class _FakePopen:
    def __init__(self, lines, rc):
        self.stdout = _FakeStdout(lines)
        self._rc = rc

    def wait(self):
        return self._rc


def test_run_pyinstaller_echoes_live_and_returns_log(monkeypatch, capsys):
    """输出必须实时回显（旧版观感），同时缓存全文供失败诊断。"""
    monkeypatch.setattr(build.subprocess, "Popen",
                        lambda cmd, **kw: _FakePopen(["building...\n", "done\n"], 0))
    rc, log = build.run_pyinstaller(["--onefile"], False)
    assert rc == 0
    assert "building..." in log and "done" in log
    out = capsys.readouterr().out
    assert "building..." in out and "done" in out, "输出必须实时回显"
    assert "[3/4]" in out


def test_run_pyinstaller_dry_run_returns_empty_log():
    rc, log = build.run_pyinstaller(["--onefile"], True)
    assert (rc, log) == (0, "")


def test_diagnose_tolerable_when_only_timestamp_fails_but_exe_complete(tmp_path):
    """时间戳补丁失败 + exe 完整落盘 → 容忍（继续发布，时间戳不影响运行）。

    这正是用户实报的崩溃：PermissionError: '...dist_stage\\ADB设备指令台.exe'
    → RuntimeError: Execution of 'set_exe_build_timestamp' failed。
    """
    staged = tmp_path / "dist_stage" / "ADB设备指令台.exe"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"MZ" * (2 * 1024 * 1024))       # 2MB，超过下限
    log = ("... PermissionError: [Errno 13] Permission denied: %s\n"
           "RuntimeError: Execution of 'set_exe_build_timestamp' failed "
           "- no more attempts left!\n" % staged)
    verdict, why = build.diagnose_build_failure(log, staged)
    assert verdict == "tolerable"
    assert "时间戳" in why


def test_diagnose_locked_when_timestamp_fails_without_product(tmp_path):
    """同类占用但没拿到完整产物 → 判 locked，提示先解锁再重跑。"""
    staged = tmp_path / "dist_stage" / "ADB设备指令台.exe"
    log = "RuntimeError: Execution of 'set_exe_build_timestamp' failed - no more attempts left!\n"
    verdict, why = build.diagnose_build_failure(log, staged)
    assert verdict == "locked"
    assert "任务管理器" in why and "杀毒" in why


def test_diagnose_fatal_for_unrelated_errors():
    verdict, why = build.diagnose_build_failure("ModuleNotFoundError: No module named 'x'\n",
                                                Path("no-such.exe"))
    assert verdict == "fatal"
    assert why == ""


def test_preflight_aborts_with_chinese_hint_when_stage_exe_locked(monkeypatch, capsys):
    """主流程：暂存 exe 被占用时提前退出（退出码 5），根本不启动 PyInstaller。"""
    called = []
    monkeypatch.setattr(build, "check_sources", lambda: [])
    monkeypatch.setattr(build, "clean_junk", lambda root: [])
    monkeypatch.setattr(build, "_file_locked", lambda p: True)
    monkeypatch.setattr(build, "run_pyinstaller",
                        lambda args, dry: called.append(args) or (0, ""))
    rc = build.main(["--no-deps", "--work-dir", "build", "--dist-dir", "dist"])
    assert rc == 5, "占用预检应返回专用退出码，实际 %r" % rc
    assert called == [], "预检失败时不应启动 PyInstaller"
    err = capsys.readouterr().err
    assert "被占用" in err and "任务管理器" in err


def test_tolerable_timestamp_failure_still_publishes(tmp_path, monkeypatch, capsys):
    """主流程：时间戳失败但 exe 完整 → 打警告后继续走发布（不返回失败码）。"""
    exe_name = build.APP_NAME + (".exe" if os.name == "nt" else "")
    staged = tmp_path / "build" / "dist_stage"
    staged.mkdir(parents=True)
    (staged / exe_name).write_bytes(b"MZ" * (2 * 1024 * 1024))   # 4MB，过体积下限
    monkeypatch.setattr(build, "check_sources", lambda: [])
    monkeypatch.setattr(build, "clean_junk", lambda root: [])
    monkeypatch.setattr(build, "_file_locked", lambda p: False)
    monkeypatch.setattr(build, "run_pyinstaller",
                        lambda args, dry: (1, "Execution of 'set_exe_build_timestamp' failed - no more attempts left!\n"))
    rc = build.main(["--no-deps", "--work-dir", str(tmp_path / "build"),
                     "--dist-dir", str(tmp_path / "dist")])
    assert rc == 0, "时间戳失败但产物完整时应按成功继续，实际 %r" % rc
    out = capsys.readouterr().out
    assert "警告" in out and "时间戳" in out
    assert (tmp_path / "dist" / exe_name).exists(), "产物应已发布到 dist"


def test_publish_from_stage_lock_error_is_actionable(tmp_path, monkeypatch, capsys):
    """拷入 dist 时目标被占用 → 错误信息带「退出运行中的程序」的人话提示。"""
    import shutil as sh

    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "app.exe").write_bytes(b"MZ")
    dist = tmp_path / "dist"
    dist.mkdir()
    old = dist / "app.exe"
    old.write_bytes(b"OLD")

    def locked_copy(src, dst):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(sh, "copy2", locked_copy)
    assert build.publish_from_stage(stage, dist, old, "onefile") is None
    err = capsys.readouterr().err
    assert "占用" in err and "退出正在运行" in err


# ---------------------------------------------------------------------------
# 默认 config.json：打包产物自带配置文件（用户设置跨启动记忆的载体）
# ---------------------------------------------------------------------------
def test_ensure_default_config_creates_defaults(tmp_path):
    """dist/ 里没有 config.json → 生成一份全量默认值模板（不缺项）。"""
    from core.prefs import PREFS_DEFAULTS

    cfg = build.ensure_default_config(tmp_path)
    assert cfg is not None and cfg.exists()
    assert cfg.name == "config.json"
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data == PREFS_DEFAULTS


def test_ensure_default_config_never_overwrites_user_settings(tmp_path):
    """已有 config.json → 原样保留（重打包不能把用户的设置打回默认值）。"""
    cfg = tmp_path / "config.json"
    cfg.write_text('{"save_dir": "D:\\\\mine", "keep_input": false}',
                   encoding="utf-8")
    assert build.ensure_default_config(tmp_path) is None
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data == {"save_dir": "D:\\mine", "keep_input": False}


def test_config_json_is_not_bundled_inside_exe():
    """config.json 只放 exe 同目录，绝不进 BUNDLED_DATA / SIDE_FILES。

    打进 exe 内部会让 resource_path() 在同目录文件缺失时回退到 _MEIPASS
    临时目录——save_prefs 写进去「重启即丢」，且毫无报错（最坏的 bug 形态）。
    """
    bundled = [src for src, _ in build.BUNDLED_DATA]
    assert "config.json" not in bundled
    assert "config.json" not in build.SIDE_FILES


def test_main_publishes_default_config_into_dist(monkeypatch, tmp_path):
    """主流程：打包完成后 dist/ 里必须有一份默认 config.json。"""
    exe_name = build.APP_NAME + (".exe" if os.name == "nt" else "")
    staged = tmp_path / "build" / "dist_stage"
    staged.mkdir(parents=True)
    (staged / exe_name).write_bytes(b"MZ" * (2 * 1024 * 1024))
    monkeypatch.setattr(build, "check_sources", lambda: [])
    monkeypatch.setattr(build, "clean_junk", lambda root: [])
    monkeypatch.setattr(build, "_file_locked", lambda p: False)
    monkeypatch.setattr(build, "run_pyinstaller", lambda args, dry: (0, ""))
    rc = build.main(["--no-deps", "--work-dir", str(tmp_path / "build"),
                     "--dist-dir", str(tmp_path / "dist")])
    assert rc == 0
    cfg = tmp_path / "dist" / "config.json"
    assert cfg.exists(), "dist/ 必须自带默认 config.json"
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["save_dir"] == "" and data["keep_input"] is True
    # 与 commands.json 等同目录文件一起发布
    assert (tmp_path / "dist" / "commands.json").exists()


def test_main_keeps_existing_dist_config(monkeypatch, tmp_path):
    """主流程：dist/ 已有 config.json 时不被默认模板覆盖（用户的设置优先）。"""
    exe_name = build.APP_NAME + (".exe" if os.name == "nt" else "")
    staged = tmp_path / "build" / "dist_stage"
    staged.mkdir(parents=True)
    (staged / exe_name).write_bytes(b"MZ" * (2 * 1024 * 1024))
    dist = tmp_path / "dist"
    dist.mkdir(parents=True)
    (dist / "config.json").write_text('{"save_dir": "D:\\\\kept"}',
                                      encoding="utf-8")
    monkeypatch.setattr(build, "check_sources", lambda: [])
    monkeypatch.setattr(build, "clean_junk", lambda root: [])
    monkeypatch.setattr(build, "_file_locked", lambda p: False)
    monkeypatch.setattr(build, "run_pyinstaller", lambda args, dry: (0, ""))
    rc = build.main(["--no-deps", "--work-dir", str(tmp_path / "build"),
                     "--dist-dir", str(dist)])
    assert rc == 0
    data = json.loads((dist / "config.json").read_text(encoding="utf-8"))
    assert data == {"save_dir": "D:\\kept"}
