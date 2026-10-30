#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ADB 设备指令台 —— PyInstaller 打包脚本（替代原 `build_windows.bat`）。

为什么用 Python 而不是 bat：

* 与项目同一套编码（UTF-8）与同一个解释器（不依赖 PATH 里的 `python` 是谁，
  避免命中 WindowsApps 占位程序）；
* 打包前后都能做校验（资源是否齐全 / exe 是否真的产出），失败有明确退出码；
* 参数化（`--onedir` / `--console` / `--bump` …），不必改脚本内容。

用法
----
    python build.py                 # 单文件 exe（默认，分发给同事用）
    python build.py --onedir        # 目录模式：启动更快、缺文件时更好排查
    python build.py --console       # 保留控制台窗口（排查「闪一下就没」）
    python build.py --bump          # 打包前先用 tools/bump_version.py 递增版本号
    python build.py --no-deps       # 跳过依赖检查与自动安装
    python build.py --dry-run       # 只打印将要执行的 PyInstaller 命令，不真打
    python build.py --dist-dir DIR  # 改产物目录（默认 dist/）
    python build.py --zip           # exe 打完后，额外产出干净源码分发 zip
    python build.py --zip-only      # 跳过 PyInstaller，只产出源码分发 zip
    python build.py --package       # exe 打完后，额外产出「双击即用」的 Windows 分发 zip
                                    # （ADBDeviceCommander_v<版本>_win64.zip，CI 发的就是它）

产物（`dist/` 整个目录拷给同事即可）：

| 文件              | 说明                                       |
| ----------------- | ------------------------------------------ |
| ADB设备指令台.exe | 主程序（双击运行，无需 Python）            |
| 使用说明.txt      | 给使用同事的简明说明                       |

`frontend/`（界面代码）只打进 exe 内部，使用者无需也不会去改。

`commands.json`（快捷指令库）与 `config.json`（各项配置）**刻意不随版本分发**：
它们都是「用户使用后才在 exe 同目录产生的个人数据」——前者首次打开自动生成默认
指令库，后者在用户第一次改动设置时落盘（启动时若缺失则全部走界面默认值）。把它们
打进每个版本，同事重装 / 升级就会覆盖掉自己先前调好的命令库与设置，这正是要避免的。
运行时缺失时程序均会自动重建默认值，无需打包自带。

Windows 打包被占用（杀毒扫描 / exe 还在运行）时的行为
--------------------------------------------------
PyInstaller 收尾会给 exe 打构建时间戳，文件被瞬时占用时这步会失败并让整个构建
判负（退出前甩一段英文 PermissionError traceback）。本脚本对此有三层处理：
构建前预检暂存文件占用（提前中文提示并退出）；失败时按日志定性——exe 本体已
完整落盘就只警告、继续发布（时间戳不影响运行），否则给出「退出运行中的程序 /
加杀毒排除项」的中文指引。
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
import shlex
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENTRY = "main.py"
APP_NAME = "ADB设备指令台"

# 打进 exe 内部的数据文件：(源路径, 包内目标目录)，PyInstaller --add-data 语法。
# frontend 必须进包：否则打包后 resource_path() 找不到 index.html，窗口会空白。
BUNDLED_DATA = [
    ("使用说明.txt", "."),
    ("frontend", "frontend"),
]

# ⚠️ config.json（用户配置）刻意**不进** BUNDLED_DATA、也不在打包时生成：它完全是
# 「用户使用后才产生」的个人数据（首次改动设置时由 core.prefs 落盘；启动时缺失
# 则全部走界面默认值）。一旦打进 exe 内部，当同目录那份缺失时 resource_path() 会
# 回退返回 _MEIPASS 里的内置副本——而 _MEIPASS 是每次运行解压出来的临时目录，
# save_prefs() 写进去「重启即丢」，用户设置看起来保存成功、下次启动却全部复位。
# 配置必须只有一个可写位置：exe 同目录（tests/test_build.py 有回归断言守着这条）。

# 构建后再拷一份到 dist 的「可编辑 / 可见」文件：同目录优先于 exe 内置副本。
# 仅 使用说明.txt：commands.json / config.json 都是「用户使用后才产生」的个人数据，
# 刻意不随版本分发（否则同事重装会覆盖自己先前调好的命令库 / 设置）；运行时
# core.commands / core.prefs 在缺失时自动生成默认值，无需打包自带。
SIDE_FILES = ["使用说明.txt"]
SIDE_DIRS = []

# 构建期不需要进包的模块（缩小体积）：pytest 只在 tests/ 用，PIL 仅用于重生成图标。
# cryptography：本项目不启用 pywebview 的 SSL 模式（webview.start 从不传 ssl=True），
# 而 pywebview 只在 SSL 模式下才 import 它生成自签名证书。但 PyInstaller 静态分析会把
# 该函数级 import 拖进依赖图，触发 cryptography 的 hook 执行
# collect_submodules('cryptography.hazmat.backends')——其隔离子进程在个别 Windows
# 环境（cryptography 轮子损坏 / 架构混杂 /  PATH 里 DLL 冲突）会以堆损坏
# （0xC0000374）崩溃，导致整个打包失败。排除它既避开这个坑，exe 也更小。
# ⚠️ 若将来项目真的要 import cryptography（或给 webview.start 传 ssl=True），
#    必须先从这里移除——tests/test_build.py 的源码安全测试会拦住这种改动。
EXCLUDE_MODULES = ["pytest", "PIL", "cryptography"]

# 构建前清掉的缓存目录：删了会自动再生，但会让源码分发包凭空胖几 MB。
# 注意不含 node_modules——那是前端测试依赖，删了要重装，分发性排除
# 由 make_source_zip 的规则负责（只不进包，不从开发机删除）。
JUNK_CACHE_DIRS = ("__pycache__", ".pytest_cache")

# 源码分发 zip 的排除规则（目录名精确匹配 / 文件名 fnmatch）。
# 复发防护：tests/frontend/node_modules 单个就 ~26MB，__pycache__ 若干 MB——
# 它们只属于开发机，不属于分发包。
SOURCE_ZIP_EXCLUDE_DIRS = (
    "node_modules", "__pycache__", ".pytest_cache", "build", "dist",
    "dist_stage", ".git", ".svn", ".venv", "venv", "__pypackages__",
    ".idea", ".vscode",
)
SOURCE_ZIP_EXCLUDE_FILES = (
    "*.pyc", "*.pyo", "*.spec", ".DS_Store", "Thumbs.db", "desktop.ini",
    # 构建产物：产物目录默认叫 dist（已在目录排除里），但 --dist-dir 可以指到任何
    # 地方（如 release/），那样整个 20~35MB 的 exe 会被当成「源码」打进去。
    "*.exe", "*.pdb",
    # 开发期崩溃日志：含完整 traceback、本机路径、设备序列号，不该随源码分发。
    "crash_*.log",
    # config.json 是运行时个人配置（全部开关 / 过滤 / 保存路径等），
    # 不应随源码分发（它是用户自己的设置，含本机绝对路径）
    "config.json",
    # 旧版配置文件名：同样属于个人配置，且在自动迁移后会被用户当作备份保留
    "settings.json",
    # 开发期设备音频调试产物（用户机器上真实录音留下的临时文件）
    "adb_devaudio_*.wav",
    # commands.json 是用户个人命令库（含私人 / 内部指令），刻意不进 git
    # （见 .gitignore 与 README）。os.walk 只认 .gitignore 挡不住它，这里单独
    # 排除，避免把私人命令库随源码分发包发给别人（与 config.json 同类处理）。
    "commands.json",
    # 开发期截图脚本（用 playwright 渲染界面出预览图，依赖本机 chromium，
    # 用户机器上跑不起来，也不属于运行时资产）
    "preview_*.cjs",
    # 推送凭证（GitHub token 明文）。.gitignore 只作用于 git，源码包走的是 os.walk，
    # 是**另一条独立路径**——只写 .gitignore 挡不住它。这条不写，每次 --zip-only
    # 都会把 token 一起打进分发包发给别人。
    ".git-credential",
    ".git-push-log.txt",
)

# 版本号源码位置（与 tools/bump_version.py 保持一致）
VERSION_FILES = ("core/constants.py", "main.py")
VERSION_RE = re.compile(r'^VERSION\s*=\s*"(\d{4}\.\d{4}\.\d{4})"', re.M)

# ---------------------------------------------------------------------------
# Windows 构建产物被占用（用户实报的打包崩溃）
# ---------------------------------------------------------------------------
# PyInstaller 把 exe 完全写盘后，收尾会调 set_exe_build_timestamp 给它打「构建
# 时间戳」（可复现构建用的装饰字段，不影响运行）。该步骤要以 'wb' 重新打开 exe——
# 文件被杀毒软件实时扫描 / 网盘同步 / exe 自身还在运行时抛 PermissionError，
# 内部重试若干次后整个构建判失败：
#   RuntimeError: Execution of 'set_exe_build_timestamp' failed - no more
#   attempts left!
# 此时 exe 本体其实已经完整落盘。下面两个常量 + diagnose_build_failure 把这类
# 失败与「真·打包错误」区分开：产物完整就容忍（只缺个时间戳），否则给出
# 中文可操作提示，而不是甩给用户一段英文 traceback。
_TIMESTAMP_SIGNATURES = (
    "set_exe_build_timestamp",
    "Execution of 'set_exe_build_timestamp' failed",
)
# onefile 产物体积下限（MB）：本程序含 pywebview + 前端资源，正常 15MB+；
# 暂存 exe 小于此值视为「没真正打出产物」，时间戳失败不予容忍。
_MIN_EXE_MB = 1.0


# ---------------------------------------------------------------------------
# 依赖
# ---------------------------------------------------------------------------
def _installed(dist_name: str) -> bool:
    try:
        from importlib import metadata
        metadata.version(dist_name)
        return True
    except Exception:
        return False


def ensure_deps(required, auto_install: bool) -> None:
    """检查构建依赖；缺失时默认用当前解释器 pip 安装（--no-deps 则直接报错退出）。"""
    for dist_name, why in required:
        if _installed(dist_name):
            continue
        if not auto_install:
            sys.exit("[错误] 缺少依赖 %s（%s）。请先 pip install %s，"
                     "或去掉 --no-deps 让脚本自动安装。" % (dist_name, why, dist_name))
        print("[1/4] 安装 %s（%s）…" % (dist_name, why))
        subprocess.check_call([sys.executable, "-m", "pip", "install", dist_name])


# ---------------------------------------------------------------------------
# 命令构造
# ---------------------------------------------------------------------------
def pyinstaller_args(args) -> list:
    """把命令行参数翻译成 PyInstaller 参数列表。"""
    out = ["--noconfirm"]
    if args.clean:
        out.append("--clean")
    out.append("--onefile" if args.mode == "onefile" else "--onedir")
    if not args.console:
        out.append("--windowed")          # 无控制台窗口（GUI 程序）
    out += ["--name", APP_NAME]
    icon = ROOT / "assets" / "app.ico"
    if icon.exists():
        out += ["--icon", str(icon)]
    # 注意：PyInstaller 会把相对路径按「spec 所在目录」解析，而 spec 落在 build/ 下，
    # 所以这里一律传绝对路径，避免把工程根的文件找成 build/ 下的同名文件。
    for src, dst in BUNDLED_DATA:
        out += ["--add-data", "%s%s%s" % (ROOT / src, os.pathsep, dst)]
    for mod in EXCLUDE_MODULES:
        out += ["--exclude-module", mod]
    # 先打进 build/ 下的暂存目录，再由本脚本拷进 dist/：
    # 直接把 dist/ 当 --distpath 时，PyInstaller 会先 os.remove 旧 exe —— 一旦那一步
    # 失败（文件被占用，或被「安全删除」类钩子拦截）整个构建就白跑了。
    out += ["--distpath", str(stage_dir(args.work_dir)),
            "--workpath", str(Path(args.work_dir).resolve()),
            "--specpath", str(Path(args.work_dir).resolve()),  # spec 只在 build/ 里
            "--log-level", args.log_level,
            str(ROOT / ENTRY)]
    return out


def stage_dir(work_dir) -> Path:
    """PyInstaller 的真正输出目录（build/ 下的暂存区，不直接落在 dist/）。"""
    return Path(work_dir).resolve() / "dist_stage"


def check_sources() -> list:
    """打包前校验入口与数据文件都在；返回缺失项列表。"""
    missing = [p for p in [ENTRY] + [src for src, _ in BUNDLED_DATA]
               if not (ROOT / p).exists()]
    return missing


def app_version(root: Path = ROOT) -> str:
    """从源码读取版本号（避免 import 业务模块，保持构建脚本零依赖）。"""
    for rel in VERSION_FILES:
        p = root / rel
        if p.exists():
            m = VERSION_RE.search(p.read_text(encoding="utf-8"))
            if m:
                return m.group(1)
    return "dev"


def clean_junk(root: Path = ROOT) -> list:
    """删除工程内的构建缓存目录（__pycache__ / .pytest_cache），返回被删路径。

    这些目录删了会自动再生，但混进源码分发包就是白胖几 MB。
    刻意不动 tests/frontend/node_modules：前端测试依赖，删了要重装。
    """
    removed = []
    for dirpath, dirnames, _filenames in os.walk(root):
        for d in list(dirnames):
            if d in JUNK_CACHE_DIRS:
                target = Path(dirpath) / d
                shutil.rmtree(target, ignore_errors=True)
                if not target.exists():
                    removed.append(target)
                dirnames.remove(d)      # 已删掉，不必再往下走
    return removed


# ---------------------------------------------------------------------------
# 源码分发 zip
# ---------------------------------------------------------------------------
def _excluded_file(name: str) -> bool:
    return any(fnmatch.fnmatch(name, pat) for pat in SOURCE_ZIP_EXCLUDE_FILES)


def make_source_zip(root: Path = ROOT, dest_dir: Path = None) -> Path:
    """把工程打成干净的源码分发 zip，返回产物路径。

    手工「整个文件夹压 zip」是 6MB 分发元凶：tests/frontend/node_modules
    ~26MB + 各处 __pycache__。这里用显式排除规则固化「什么不该进包」，
    之后一条命令即可复现干净分发包：`python build.py --zip`。

    包内所有文件都挂在一个与 zip 同名的顶层目录下（`ADBDeviceCommander_v*/`）：
    解压时不会把 main.py / core / frontend 散落一地；同时顶层目录里没有
    index.html，云端导入时不会被误判成「网页包」而解包成一个空壳页面。
    """
    dest_dir = Path(dest_dir or root / "dist")
    dest_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dest_dir / ("ADBDeviceCommander_v%s.zip" % app_version(root))
    # 顶层目录名 = zip 文件名去扩展名，解压后一眼看出是哪个版本
    top = zip_path.stem
    # 排除规则按「目录名」匹配，只能挡住名为 dist 的那个默认目录；
    # --dist-dir 一旦指到别的名字（release/、out/…），产物目录会被整棵遍历，
    # 把刚打好的 exe 一起塞进「干净源码包」。这里按解析后的绝对路径再挡一次。
    dest_resolved = dest_dir.resolve()
    zip_resolved = zip_path.resolve()
    count = 0
    total = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(
                d for d in dirnames
                if d not in SOURCE_ZIP_EXCLUDE_DIRS
                and (Path(dirpath) / d).resolve() != dest_resolved)
            for fn in sorted(filenames):
                if _excluded_file(fn):
                    continue
                p = Path(dirpath) / fn
                if not p.is_file():
                    continue
                rel = p.relative_to(root).as_posix()
                # zip 落在 dest（dist/）下、且 dist 已被排除，正常不会自收录；
                # 这里再兜一层，防止 dest_dir 传入非排除目录时把 zip 自己打进去。
                if p.resolve() == zip_resolved:
                    continue
                zf.write(p, top + "/" + rel)
                count += 1
                total += p.stat().st_size
    print("源码分发包：%s（%d 个文件，%.1f KB，顶层目录 %s/）"
          % (zip_path, count, total / 1024, top))
    return zip_path


def win_package_name(root: Path = ROOT) -> str:
    """分发给同事的 Windows 包名。

    `_win64` 后缀不是装饰：core.update.ASSET_SUFFIX 靠它从 Release 资产里挑
    出「该给 Windows 用户下哪一个」，改名会让更新检查退化成「随便挑一个 zip」。
    tests/test_build.py 有断言盯着这两个常量一致。
    """
    return "ADBDeviceCommander_v%s_win64.zip" % app_version(root)


def make_win_package(target: Path, dist_dir: Path = None,
                     root: Path = ROOT) -> Path:
    """把 dist/ 里「双击即用」的那一套打成 zip，返回产物路径。

    与 make_source_zip 的分工：
      * 源码包给「要看代码 / 想自己跑起来」的人，里面是 .py 与测试；
      * 这个包给「只想用」的同事，里面只有 exe + 使用说明.txt。
    commands.json / config.json 是用户使用后产生的个人数据，刻意不进分发包，
    避免同事重装覆盖自己先前的命令库与设置；运行时缺失会自动重建默认值。

    包内同样套一层与 zip 同名的顶层目录：解压后不会把 exe 和一堆 json
    散落在下载文件夹里，也就不会出现「exe 与 json 不同目录、json 不生效」。
    """
    dist_dir = Path(dist_dir or root / "dist")
    dist_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dist_dir / win_package_name(root)
    top = zip_path.stem
    exe_name = APP_NAME + (".exe" if os.name == "nt" else "")
    count = 0
    missing = []
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        exe = target / exe_name
        if exe.is_file():
            zf.write(exe, top + "/" + exe_name)
            count += 1
        else:
            missing.append(exe_name)
        for rel in SIDE_FILES:
            p = target / rel
            if p.is_file():
                zf.write(p, top + "/" + rel)
                count += 1
        for rel in SIDE_DIRS:
            d = target / rel
            if not d.is_dir():
                continue
            for dirpath, dirnames, filenames in os.walk(d):
                dirnames.sort()
                for fn in sorted(filenames):
                    p = Path(dirpath) / fn
                    zf.write(p, top + "/" + p.relative_to(target).as_posix())
                    count += 1
    if missing:
        print("[警告] 分发件里缺少 %s（产物目录里没有）" % "、".join(missing),
              file=sys.stderr)
    print("分发件：%s（%d 个文件，%.1f MB，顶层目录 %s/）"
          % (zip_path, count, zip_path.stat().st_size / 1024 / 1024, top))
    return zip_path


def _file_locked(path: Path) -> bool:
    """探测文件是否被其他进程占用（Windows：以读写方式打不开即被锁）。

    构建前预检用：旧实现没有这一步，暂存 exe 被占用时要等 PyInstaller 跑完
    几分钟才在收尾步骤爆炸，错误信息还是英文 PermissionError，用户完全看不出
    该干什么。只读属性的文件同样打不开——两种情况都该在构建前拦下来。
    """
    if not path.exists():
        return False
    try:
        with open(path, "r+b"):
            return False
    except OSError:
        return True


def run_pyinstaller(pyi_args, dry_run: bool):
    """跑 PyInstaller：实时回显输出并缓存全文，返回 (退出码, 日志)。

    旧实现用 subprocess.call 直接继承 stdio——输出倒是实时，但失败后拿不到
    日志，无法区分「时间戳补丁被占用」与「真·打包错误」，只能甩一句退出码。
    这里逐行读、逐行回显（行为与旧版一致），同时攒全文供 diagnose_build_failure
    做失败定性。PYTHONUTF8 依旧强制：PyInstaller 内部按文本模式读子进程输出，
    中文 Windows 默认 gbk 解码遇到中文路径会抛 UnicodeDecodeError 噪音。
    """
    cmd = [sys.executable, "-m", "PyInstaller"] + pyi_args
    print("[3/4] " + " ".join(shlex.quote(str(c)) for c in cmd))
    if dry_run:
        print("（--dry-run：未真正执行）")
        return 0, ""
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    chunks = []
    if proc.stdout is not None:
        for line in proc.stdout:            # 逐行回显：与旧版一样的实时观感
            chunks.append(line)
            print(line, end="", flush=True)
        proc.stdout.close()
    return proc.wait(), "".join(chunks)


def diagnose_build_failure(log: str, staged_exe: Path) -> tuple:
    """PyInstaller 失败定性，返回 (verdict, 中文说明)。

    verdict 三选一：
      tolerable — 只有「给 exe 打构建时间戳」这步失败（文件被瞬时占用），
                  exe 本体已完整写出 → 按成功继续（时间戳纯装饰，不影响运行）；
      locked    — 同类占用、但没拿到完整产物 → 先解锁再重跑；
      fatal     — 其他错误 → 原样回报退出码，说明为空。
    """
    hit = any(sig in (log or "") for sig in _TIMESTAMP_SIGNATURES)
    if hit:
        try:
            size_mb = staged_exe.stat().st_size / 1024 / 1024
        except OSError:
            size_mb = 0.0
        if size_mb >= _MIN_EXE_MB:
            return "tolerable", (
                "PyInstaller 收尾时给 exe 打构建时间戳失败（文件被杀毒软件 / "
                "网盘同步瞬时占用），但 exe 本体已完整写出（%.1f MB）。"
                % size_mb)
        return "locked", (
            "构建输出被占用且未生成完整产物。请先在任务管理器退出正在运行的 "
            "「ADB设备指令台.exe」（确认无残留进程），并把工程目录加入杀毒软件 "
            "排除项（或临时关闭实时保护）后重跑；暂存目录 %s 下的旧文件也可先删掉。"
            % staged_exe.parent)
    return "fatal", ""


# ---------------------------------------------------------------------------
# 收尾
# ---------------------------------------------------------------------------
def exe_dir(dist_dir: Path, mode: str) -> Path:
    """onefile → dist 本身；onedir → dist/<APP_NAME>/。"""
    return dist_dir / APP_NAME if mode == "onedir" else dist_dir


def copy_side_files(target: Path) -> list:
    """把可编辑 / 可见文件拷到 exe 同目录，返回拷贝项名称。"""
    target.mkdir(parents=True, exist_ok=True)
    done = []
    for rel in SIDE_FILES:
        src = ROOT / rel
        if src.exists():
            shutil.copy2(src, target / rel)
            done.append(rel)
    for rel in SIDE_DIRS:
        src = ROOT / rel
        if src.is_dir():
            shutil.copytree(src, target / rel, dirs_exist_ok=True)
            done.append(rel + "/")
    return done


def verify_dist(target, mode, exe):
    """产物完整性自检：确认 exe 与可编辑同目录文件（使用说明.txt）都确实落盘。

    手工分发包最易漏 使用说明.txt 或 exe 本体，这里在打包收尾自动核对一遍，
    缺项返回给 main 打印告警，避免发出缺文件的残包。返回空列表即视为通过。
    """
    problems = []
    if not exe.exists():
        problems.append("主程序缺失：%s" % exe)
    else:
        try:
            mb = exe.stat().st_size / 1024 / 1024
        except OSError:
            mb = 0.0
        if mb < _MIN_EXE_MB:
            problems.append("主程序体积异常（%.2f MB，疑似未完整生成）：%s" % (mb, exe))
    for rel in SIDE_FILES:
        if not (target / rel).is_file():
            problems.append("同目录文件缺失：%s" % rel)
    for rel in SIDE_DIRS:
        d = target / rel
        if not d.is_dir() or not any(d.iterdir()):
            problems.append("资源目录缺失或为空：%s/" % rel)
    return problems

def publish_from_stage(src_dir: Path, target: Path, exe: Path, mode: str):
    """把暂存区的产物拷进 dist/，返回最终 exe 路径（失败返回 None）。

    为什么多这一步：PyInstaller 直接写 dist/ 时会先删掉旧 exe，而删除这一步在
    某些环境会失败（文件被占用 / 被「安全删除」钩子拦截），整个构建就白跑了。
    拷入（覆盖写）不需要删除旧文件，重复打包因此始终可用。
    """
    src_exe = src_dir / exe.name
    if not src_exe.exists():
        print("[错误] 未找到产物 %s" % src_exe, file=sys.stderr)
        return None
    try:
        target.mkdir(parents=True, exist_ok=True)
        if mode == "onedir":
            shutil.copytree(src_dir, target, dirs_exist_ok=True)
        else:
            shutil.copy2(src_exe, exe)
    except Exception as e:
        # 覆盖写 dist/ 里的旧 exe 时最常见的失败就是它被占用：用户开着上一版
        # 程序直接重打包。给一句人话，别让用户对着一句英文 PermissionError 猜。
        hint = ""
        if isinstance(e, PermissionError) or "being used by another process" in str(e):
            hint = ("（目标文件被占用：请先退出正在运行的「ADB设备指令台.exe」"
                    "——任务管理器里确认无残留进程——或把 dist/ 加入杀毒排除项）")
        print("[错误] 拷入 dist 失败：%s%s" % (e, hint), file=sys.stderr)
        return None
    return exe


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="用 PyInstaller 打包 ADB 设备指令台")
    ap.add_argument("--mode", choices=("onefile", "onedir"), default="onefile",
                    help="onefile=单文件 exe（默认，便于分发）；onedir=目录模式（启动更快）")
    # 文档（本文件头部说明与 README）一直写着 `--onedir` / `--onefile`，但实际只存在
    # `--mode`：照文档执行会直接 `error: unrecognized arguments: --onedir` 退出码 2。
    # 这里补成同义开关，两条路都能走。
    ap.add_argument("--onedir", dest="mode", action="store_const", const="onedir",
                    help="等价于 --mode onedir（目录模式）")
    ap.add_argument("--onefile", dest="mode", action="store_const", const="onefile",
                    help="等价于 --mode onefile（单文件，默认）")
    ap.add_argument("--console", action="store_true",
                    help="保留控制台窗口（排查崩溃时用；默认 --windowed 无控制台）")
    ap.add_argument("--bump", action="store_true",
                    help="打包前用 tools/bump_version.py 递增版本号并写回源码")
    ap.add_argument("--no-deps", action="store_true",
                    help="不检查 / 不自动安装 pyinstaller 与 pywebview")
    ap.add_argument("--no-clean", dest="clean", action="store_false",
                    help="不清理上次构建缓存（增量构建，更快）")
    ap.add_argument("--dry-run", action="store_true",
                    help="只打印 PyInstaller 命令，不真正打包")
    ap.add_argument("--dist-dir", default=str(ROOT / "dist"), help="产物目录（默认 dist/）")
    ap.add_argument("--work-dir", default=str(ROOT / "build"), help="构建缓存目录（默认 build/）")
    ap.add_argument("--log-level", default="WARN",
                    help="PyInstaller 日志级别（默认 WARN；排错可传 INFO/DEBUG）")
    ap.add_argument("--zip", action="store_true",
                    help="exe 打完后，额外产出干净源码分发 zip（排除测试/构建垃圾）")
    ap.add_argument("--zip-only", action="store_true",
                    help="跳过 PyInstaller，只产出源码分发 zip（不发 exe 时用）")
    ap.add_argument("--package", action="store_true",
                    help="exe 打完后，额外产出「双击即用」的 Windows 分发 zip"
                         "（ADBDeviceCommander_v<版本>_win64.zip）")
    ap.set_defaults(clean=True)
    args = ap.parse_args(argv)

    args.dist_dir = Path(args.dist_dir).resolve()
    args.work_dir = Path(args.work_dir).resolve()

    print("=" * 64)
    print("ADB 设备指令台 · PyInstaller 打包（%s / %s）"
          % (args.mode, "console" if args.console else "windowed"))
    print("工程目录：%s" % ROOT)
    print("=" * 64)

    # 1) 依赖
    if args.zip_only:
        print("[1/4] --zip-only：跳过依赖检查与 PyInstaller，只打源码分发包")
    elif args.no_deps:
        print("[1/4] 跳过依赖检查（--no-deps）")
    else:
        ensure_deps([("pyinstaller", "打包工具"), ("pywebview", "运行时宿主，打包期需可导入")],
                    auto_install=True)


    # 2) 资源自检（缺 frontend 会导致打包后窗口空白，必须拦住）
    missing = check_sources()
    if missing:
        print("[错误] 以下打包所需文件缺失：%s" % "、".join(missing), file=sys.stderr)
        return 2
    print("[2/4] 资源自检通过（入口 + %d 项数据文件齐全）" % len(BUNDLED_DATA))

    # --zip-only：只打源码分发包，不进 PyInstaller
    if args.zip_only:
        zp = make_source_zip(ROOT, args.dist_dir)
        print("\n源码分发包完成：%s" % zp)
        return 0

    # 清理构建缓存（__pycache__ / .pytest_cache）：删了会自动再生，
    # 但留着会让源码分发 zip 白胖几 MB。
    junk = clean_junk(ROOT)
    if junk:
        print("[2.5/4] 已清理构建缓存：%d 个目录" % len(junk))

    # 3) 版本号（可选）
    if args.bump and not args.dry_run:
        try:
            subprocess.check_call([sys.executable,
                                   str(ROOT / "tools" / "bump_version.py"),
                                   "--apply"])
        except subprocess.CalledProcessError as e:
            # 典型触发：core/constants.py 与 main.py 的 VERSION 不一致（版本号工具
            # 会以退出码 2 报「版本号不一致」）。旧实现直接把 CalledProcessError 抛出去，
            # 用户看到的是一段英文 traceback 而不是中文原因。
            print("[错误] 版本号递增失败（退出码 %s）。请先检查 core/constants.py 与 "
                  "main.py 的 VERSION 是否一致，或省掉 --bump 用现有版本号打包。"
                  % e.returncode, file=sys.stderr)
            return 4

    # 4) 打包前预检：暂存区旧 exe 若被占用（上次的产物还在跑 / 被杀毒锁着），
    # 立刻拦下。不预检的代价：PyInstaller 白跑几分钟，最后在收尾步骤以一句
    # 英文 PermissionError 爆炸，用户不知道该干什么（用户实报的打包崩溃）。
    staged_exe = (stage_dir(args.work_dir)
                  / (APP_NAME + (".exe" if os.name == "nt" else "")))
    if not args.dry_run and _file_locked(staged_exe):
        print("[错误] 构建暂存文件被占用：%s\n"
              "        常见原因：上一次打好的 exe 还在运行（请先在任务管理器\n"
              "        退出，确认无残留进程），或杀毒软件 / 网盘同步正在扫描它。\n"
              "        处理后再重跑即可（也可先删掉整个 build/ 目录）。"
              % staged_exe, file=sys.stderr)
        return 5

    # 5) 打包（输出到 build/ 下的暂存区，随后再拷进 dist/）
    rc, log = run_pyinstaller(pyinstaller_args(args), args.dry_run)
    if rc != 0:
        verdict, why = diagnose_build_failure(log, staged_exe)
        if verdict == "tolerable":
            # exe 已完整落盘，只差一个装饰性时间戳——按构建成功继续，
            # 否则用户要为「面子字段」重打一遍（还得再赌一次杀毒不扫描）。
            print("[警告] %s" % why)
            print("        exe 本体完整可用，仅嵌入的构建时间戳缺失（不影响运行），"
                  "按「构建成功」继续发布。")
        else:
            print("[错误] PyInstaller 退出码 %d，打包失败。%s" % (rc, why),
                  file=sys.stderr)
            return rc

    target = exe_dir(args.dist_dir, args.mode)
    exe = target / (APP_NAME + (".exe" if os.name == "nt" else ""))
    if args.dry_run:
        print("\n目标产物：%s" % exe)
        return 0

    exe = publish_from_stage(exe_dir(stage_dir(args.work_dir), args.mode),
                             target, exe, args.mode)
    if exe is None:
        return 3

    copied = copy_side_files(target)
    print("[4/4] 已拷贝同目录文件：%s" % "、".join(copied))

    # 6) 产物完整性自检（仅告警）：确认 exe 与「可编辑同目录文件」都确实落盘。
    # 核对 exe 本体与 使用说明.txt 是否落盘，避免发出缺文件的残包。
    # 这里自动核对一遍，缺项直接提示，避免发出残包。
    problems = verify_dist(target, args.mode, exe)
    if problems:
        print("[警告] 产物完整性自检发现 %d 项问题：" % len(problems))
        for _p in problems:
            print("        - %s" % _p)

    if args.zip:
        make_source_zip(ROOT, args.dist_dir)
    if args.package:
        make_win_package(target, args.dist_dir)

    print("\n打包完成：%s（%.1f MB）" % (exe, exe.stat().st_size / 1024 / 1024))
    print("把整个 %s 目录一起拷给同事（ADB设备指令台.exe 与 使用说明.txt 必须同目录）。" % target)
    print("提示：同事机器若报「WebView2 Runtime 未安装 / 过旧」，到 "
          "https://developer.microsoft.com/microsoft-edge/webview2/ 装运行库即可。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
