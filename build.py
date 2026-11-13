#!/usr/bin/env python
"""ADB 设备指令台 —— PyInstaller 打包脚本（替代原 `build_windows.bat`）。

为什么用 Python 而不是 bat：

* 与项目同一套编码（UTF-8）与同一个解释器（不依赖 PATH 里的 `python` 是谁，
  避免命中 WindowsApps 占位程序）；
* 打包前后都能做校验（资源是否齐全 / exe 是否真的产出），失败有明确退出码；
* 参数化（`--onedir` / `--console` / `--bump` …），不必改脚本内容。

用法
----
    python build.py                 # 单文件 exe（默认）：分发件就是**一个 exe**
    python build.py --onedir        # 目录模式（仅供本机排查：启动快，但分发要整目录）
    python build.py --console       # 保留控制台窗口（排查「闪一下就没」）
    python build.py --bump          # 打包前先用 tools/bump_version.py 递增版本号
    python build.py --no-deps       # 跳过依赖检查与自动安装
    python build.py --dry-run       # 只打印将要执行的 PyInstaller 命令，不真打
    python build.py --dist-dir DIR  # 改产物目录（默认 dist/）
    python build.py --zip           # exe 打完后，额外产出干净源码分发 zip
    python build.py --zip-only      # 跳过 PyInstaller，只产出源码分发 zip
    python build.py --package       # exe 打完后，额外产出「双击即用」的 Windows 分发 zip
                                    # （ADBDeviceCommander_v<版本>_win64.zip，CI 发的就是它）
    python build.py --with-numpy    # 把 numpy 也打进 exe（默认不打，见下）

产物（`dist/` 整个目录拷给同事即可）：

单文件模式下 `dist/` 里只有**一个** `ADB设备指令台.exe`，双击即用：

| 文件                    | 说明                                     |
| ----------------------- | ---------------------------------------- |
| ADB设备指令台.exe       | 主程序（双击运行，无需 Python）          |

为什么默认单文件（而不是「目录 + _internal/」）
----------------------------------------------
上一版发的是**目录模式**：exe 只是启动器，真正的运行时（Python 标准库 /
pywebview / pythonnet / WebView2 托管 DLL）全在旁边的 `_internal/` 里。
同事把整个文件夹拷过去、**从网上下载再解压**后，Windows 会给解压出来的每个
文件挂一条 NTFS 备用数据流 Zone.Identifier（ZoneId=3 = Internet）。.NET
Framework 的程序集加载器**拒绝加载**带此标记的托管 DLL，于是 WebView2 的
`Microsoft.Web.WebView2.Core.dll` 一加载就炸：

    System.IO.FileLoadException: 未能加载文件或程序集
      "file:///...\\webview\\lib\\Microsoft.Web.WebView2.Core.dll" ... 不支持操作。
      (异常来自 HRESULT: 0x80131515)
    ---> System.NotSupportedException: 尝试从一个网络位置加载程序集 ...

单文件模式**从结构上根除**这个问题：exe 每次启动把内置归档解压到
%TEMP% 下新建的目录，那些文件是**当场创建**的，没有也不可能有
Zone.Identifier —— .NET 不会再拒绝加载。代价是每次启动都要解压整包
（见下节「启动速度」）。

启动速度：单文件模式怎么把解压耗时压下来
------------------------------------------
单文件模式每次启动都要把整包解压到 %TEMP%，这一步完全在 Python 代码
之前发生（程序内部任何计时都看不到），是「双击到窗口出现」的主要成本。
三件事一起做，把它压到可接受：

1. **默认不把 numpy 打进包**（`--with-numpy` 可显式打开）。numpy 在
   requirements.txt 里本就是**可选**加速项（PNG filter 还原 / BGR 换位
   向量化），缺它时 core/clipboard.py 自动回退纯 Python，**结果逐字节
   一致**（tests/test_core_clipboard.py 有对拍用例）。而 numpy 的 Windows
   轮子装完约 40MB、1184 个文件 —— 实测单文件 exe 从 68.7MB 降到 54.2MB
   （-21%），解压的文件数也少一大截，杀毒软件的逐文件扫描同步变快。
2. **前端分步加载**：窗口先出加载页，再按「上次停留的 tab → 用户切到
   哪个 tab 就加载哪个」逐块加载（见 frontend/js/app.js 的 prepareTab）。
   指令库、Logcat 包列表（一次设备调用）等重活不再挤在启动关键路径上。
3. **exe 同目录优先的资源查找**：frontend/ 等资源仍打进包内（走
   resource_path 的 _MEIPASS 回退），不依赖 exe 旁边的任何文件。

`frontend/`（界面代码）与使用说明都只打进 exe 内部，使用者无需也不会去改；
使用说明在程序「关于」页的「使用说明」子 tab 内直接阅读。

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

# 必须存在、但不在 BUNDLED_DATA 顶层列出的关键资源（随某个目录整体进包）。
# 报告图表默认内联 ECharts；缺了它报告会降级成静态 SVG —— 属于「打包漏文件」，
# 构建期就该拦下，而不是等用户导出报告时才发现没有交互。
REQUIRED_ASSETS = [
    "frontend/vendor/echarts.min.js",
]

# ⚠️ config.json（用户配置）刻意**不进** BUNDLED_DATA、也不在打包时生成：它完全是
# 「用户使用后才产生」的个人数据（首次改动设置时由 core.prefs 落盘；启动时缺失
# 则全部走界面默认值）。一旦打进 exe 内部，当同目录那份缺失时 resource_path() 会
# 回退返回 _MEIPASS 里的内置副本——而 _MEIPASS 是每次运行解压出来的临时目录，
# save_prefs() 写进去「重启即丢」，用户设置看起来保存成功、下次启动却全部复位。
# 配置必须只有一个可写位置：exe 同目录（tests/test_build.py 有回归断言守着这条）。

# 构建后再拷一份到 dist 的「可编辑 / 可见」文件：同目录优先于 exe 内置副本。
# 现在为空：使用说明已移入程序内（关于页「使用说明」子 tab 直接渲染，由 exe 内置
# 副本经 resource_path 读取），不再以独立文件形式随包分发；commands.json / config.json
# 仍是「用户使用后才产生」的个人数据，刻意不随版本分发（否则同事重装会覆盖自己先前
# 调好的命令库 / 设置）。dist 目录因此只剩 exe 本体，最干净、最不会误伤用户数据。
SIDE_FILES = []
SIDE_DIRS = []

# 分发件（--package）里绝不允许出现的文件：用户个人数据 + 开发期临时产物。
# 目录模式要把整个产物目录（exe + _internal）打包，而这些文件恰好就落在 exe
# 同目录（用户运行过一次就会生成 config.json / commands.json / 崩溃日志），
# 不排除就会把同事自己的命令库、配置、设备序列号随包发给别人。
_PACKAGE_EXCLUDE_FILES = (
    "config.json", "settings.json", "commands.json",
    "crash_*.log", "adb_devaudio_*.wav",
)


def _package_excluded(name: str) -> bool:
    return any(fnmatch.fnmatch(name, pat) for pat in _PACKAGE_EXCLUDE_FILES)


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

# 可选加速依赖，默认**不进包**（用 --with-numpy 才带上）。
#
# numpy 在 requirements.txt 里本就标着「可选」：core/clipboard.py 只在真正
# 写剪贴板时惰性 import 它，导入失败就自动回退纯 Python 实现，**结果逐字节
# 一致**（tests/test_core_clipboard.py 有 numpy 路径 vs 纯 Python 的对拍用例）。
#
# 而它的代价在单文件模式下被放大：Windows 轮子装完约 40MB、1184 个文件。
# 单文件 exe 每次启动都要把整包解压到 %TEMP%，文件数直接决定解压耗时，
# 还要被杀毒软件逐个扫描。实测（Linux + PyInstaller 6，同一份源码）：
#   带 numpy：68.7 MB    不带 numpy：54.2 MB（-21%）
# 这 21% 直接换成「双击到窗口出现」的时间，故默认排除。
#
# 想要 numpy 加速（截图写剪贴板时 PNG filter 还原快 2 倍以上）就加 --with-numpy。
OPTIONAL_EXCLUDE_MODULES = ["numpy"]

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
    # 开发期上传的截图 / 临时素材（几 MB 的 png），只属于本机会话，
    # 一旦混进源码包会让分发包凭空膨胀数 MB。
    ".uploads",
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

# 版本号源码位置：**唯一真源** core/constants.py（与 tools/bump_version.py 一致）。
# 曾把 main.py 也列进来 —— 那是「双写时代」的遗留：两份 VERSION 靠工具同步，
# 一旦漏写就出现「程序自报版本 ≠ 包名版本」。现在 main.py 里不允许再有副本
# （bump_version.py 检出即报错），这里再留着它只会让下一个人以为「要改两处」。
VERSION_FILES = ("core/constants.py",)
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
# 产物 exe 体积下限（MB）：目录模式下 exe 只是启动器（约 1MB+），onefile 则
# 15MB+。低于此值视为「没真正打出产物」，时间戳失败不予容忍。
_MIN_EXE_MB = 0.5


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
    # numpy 默认不进包（见 OPTIONAL_EXCLUDE_MODULES 的说明）：
    # 单文件模式每次启动都要解压整包，numpy 的 ~40MB / 1184 个文件直接
    # 变成解压耗时与杀毒扫描次数。--with-numpy 才带上它。
    if not getattr(args, "with_numpy", False):
        for mod in OPTIONAL_EXCLUDE_MODULES:
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
    return [p for p in ([ENTRY] + [src for src, _ in BUNDLED_DATA]
                           + REQUIRED_ASSETS)
               if not (ROOT / p).exists()]


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
                     root: Path = ROOT, mode: str = "onefile") -> Path:
    """把产物目录里「双击即用」的那一套打成 zip，返回产物路径。

    与 make_source_zip 的分工：
      * 源码包给「要看代码 / 想自己跑起来」的人，里面是 .py 与测试；
      * 这个包给「只想用」的同事，里面是可直接运行的应用（使用说明已移入程序内）。

    **单文件模式（默认）只拷 exe 本体**：分发件里就一个 exe，解压出来双击
    即用，不需要再带一堆 DLL。**目录模式必须整目录打包**：exe 只是启动器，
    运行时依赖（python 标准库 / pywebview / `_internal`）都在同目录，只拷 exe
    会双击即报「找不到 DLL / 无法加载 Python 运行时」。

    commands.json / config.json 是用户使用后产生的个人数据，会与 exe 同目录出现；
    整树遍历时必须显式排除，避免把同事自己的命令库 / 配置打进分发包里泄漏。
    """
    dist_dir = Path(dist_dir or root / "dist")
    dist_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dist_dir / win_package_name(root)
    top = zip_path.stem
    exe_name = APP_NAME + (".exe" if os.name == "nt" else "")
    count = 0
    missing = []

    def _add(zf, path: Path, base: Path):
        nonlocal count
        zf.write(path, top + "/" + path.relative_to(base).as_posix())
        count += 1

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        exe = target / exe_name
        if mode == "onedir":
            if target.is_dir():
                for dirpath, dirnames, filenames in os.walk(target):
                    dirnames[:] = sorted(
                        d for d in dirnames if not _package_excluded(d))
                    for fn in sorted(filenames):
                        if _package_excluded(fn):
                            continue
                        _add(zf, Path(dirpath) / fn, target)
            if not exe.is_file():
                # 整树遍历会把「随便什么文件」都打进去，exe 缺失时不能静默出包
                missing.append(exe_name)
        else:
            if exe.is_file():
                zf.write(exe, top + "/" + exe_name)
                count += 1
            else:
                missing.append(exe_name)
            for rel in SIDE_FILES:
                p = target / rel
                if p.is_file():
                    _add(zf, p, target)
            for rel in SIDE_DIRS:
                d = target / rel
                if not d.is_dir():
                    continue
                for dirpath, dirnames, filenames in os.walk(d):
                    dirnames.sort()
                    for fn in sorted(filenames):
                        _add(zf, Path(dirpath) / fn, target)
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
    """把可编辑 / 可见文件拷到 exe 同目录，返回拷贝项名称。

    现已无随包外发的可见文件（使用说明移入程序内；config.json / commands.json
    是用户使用后才产生的个人数据），故正常返回空列表——保留函数以兼容 main 调用。
    """
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
    """产物完整性自检：确认 exe 本体（及目录模式的运行时依赖）确实落盘。

    目录模式下 exe 只是启动器，缺 `_internal/` 会双击即报「找不到 DLL / 无法加载
    Python 运行时」——这类残包必须拦在发布前，而不是等同事打不开才反查。
    返回空列表即视为通过。
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
    if mode == "onedir" and target.is_dir():
        # PyInstaller 6 起依赖收在 _internal/；更早版本直接平铺在 exe 同目录。
        # 两种情况都要求「exe 之外还有东西」，否则就是只拷了 exe 的残包。
        others = [p for p in target.iterdir() if p.name != exe.name]
        if not others:
            problems.append("目录模式缺少运行时依赖（_internal / DLL）：%s" % target)
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
                    help="onefile=单文件 exe（默认）：分发件就是一个 exe，"
                         "从结构上根除「解压出来的 DLL 带 Zone.Identifier → "
                         ".NET 拒绝加载」的崩溃；onedir=目录模式（仅供本机"
                         "排查：启动快，但分发要整目录，且会带上那个崩溃）")
    # 文档（本文件头部说明与 README）一直写着 `--onedir` / `--onefile`，但实际只存在
    # `--mode`：照文档执行会直接 `error: unrecognized arguments: --onedir` 退出码 2。
    # 这里补成同义开关，两条路都能走。
    ap.add_argument("--onedir", dest="mode", action="store_const", const="onedir",
                    help="等价于 --mode onedir（目录模式：仅供本机排查）")
    ap.add_argument("--onefile", dest="mode", action="store_const", const="onefile",
                    help="等价于 --mode onefile（单文件 exe：默认）")
    ap.add_argument("--with-numpy", dest="with_numpy", action="store_true",
                    help="把 numpy 也打进 exe（默认不打：单文件模式每次启动"
                         "都要解压整包，numpy 的 ~40MB/1184 个文件直接变成"
                         "解压耗时；缺它时剪贴板 PNG 还原自动回退纯 Python，"
                         "结果一致）")
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
            # 典型触发：main.py 里又出现了硬编码 VERSION 副本（bump_version.py
            # 检出即退出 2），或 core/constants.py 的版本号格式不合规。旧实现直接把
            # CalledProcessError 抛出去，用户看到的是一段英文 traceback 而不是原因。
            print("[错误] 版本号递增失败（退出码 %s）。请检查 core/constants.py 里的 "
                  "VERSION 格式是否为 YYYY.MMDD.HHMM、main.py 里有没有残留的 "
                  "VERSION 副本（那是唯一真源之外的重复），或省掉 --bump "
                  "用现有版本号打包。" % e.returncode, file=sys.stderr)
            return 4

    # 4) 打包前预检：暂存区旧 exe 若被占用（上次的产物还在跑 / 被杀毒锁着），
    # 立刻拦下。不预检的代价：PyInstaller 白跑几分钟，最后在收尾步骤以一句
    # 英文 PermissionError 爆炸，用户不知道该干什么（用户实报的打包崩溃）。
    # 路径必须跟着模式走：目录模式的产物在 dist_stage/<APP_NAME>/ 下，不是根。
    staged_exe = (exe_dir(stage_dir(args.work_dir), args.mode)
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
    # 核对 exe 本体是否落盘，避免发出缺文件的残包。
    # 这里自动核对一遍，缺项直接提示，避免发出残包。
    problems = verify_dist(target, args.mode, exe)
    if problems:
        print("[警告] 产物完整性自检发现 %d 项问题：" % len(problems))
        for _p in problems:
            print("        - %s" % _p)

    if args.zip:
        make_source_zip(ROOT, args.dist_dir)
    if args.package:
        make_win_package(target, args.dist_dir, mode=args.mode)

    print("\n打包完成：%s（%.1f MB）" % (exe, exe.stat().st_size / 1024 / 1024))
    if args.mode == "onedir":
        print("把整个 %s 目录一起拷给同事（exe 只是启动器，_internal/ 缺一不可）。"
              % target)
    else:
        print("把整个 %s 目录一起拷给同事（dist 仅含 exe 本体；使用说明见程序内「关于 → 使用说明」）。"
              % target)
    print("提示：同事机器若报「WebView2 Runtime 未安装 / 过旧」，到 "
          "https://developer.microsoft.com/microsoft-edge/webview2/ 装运行库即可。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())