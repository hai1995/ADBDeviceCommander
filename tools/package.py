#!/usr/bin/env python3
"""一键打包交付物：自动生成新版本号 + 打成**扁平** zip。

- 版本号：默认先调用 tools/bump_version.py 递增（保证每次交付都是新版本，
  严格递增、不会撞号）；`--no-bump` 可跳过（用现有版本号打包）。
- 结构：zip 内**不套顶层目录**，解压后直接是 main.py / backend/ / frontend/ …
- 位置：默认输出到工程根的上一级（避免把产物打进自己），可用 --out-dir 改。

用法
----
    python tools/package.py                  # 递增版本 + 打包 + 清理旧 zip
    python tools/package.py --no-bump        # 用现有版本号打包
    python tools/package.py --keep-old       # 保留旧版本 zip
    python tools/package.py --reset-to-now   # 本次同时修正基线为真实时间
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bump_version import read_version, next_version, write_version, VersionError  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NAME = "ADBDeviceCommander"

# 只属于开发机、不属于分发包的目录（按目录名精确匹配）。
# 必须与 build.py 的 SOURCE_ZIP_EXCLUDE_DIRS 保持一致：这里曾漏掉 .venv / venv，
# 于是 `python tools/package.py` 会把整个虚拟环境（本案 ~3300 个文件、60+MB）
# 打进「干净源码包」，既让产物膨胀 200 倍，又把开发机上的第三方依赖散播出去；
# tests/test_version_tools.py 里那条「用真实工程打包」的用例也因此要跑 2 分钟。
EXCLUDE_DIRS = {"node_modules", "__pycache__", ".pytest_cache", "build",
                "dist", "dist_stage", ".git", ".svn", ".venv", "venv",
                "__pypackages__", ".idea", ".vscode", ".mypy_cache"}
EXCLUDE_FILES = {".DS_Store", "Thumbs.db", "desktop.ini",
                 # 调试/构建残留：绝不打进交付物（.txt 不在 EXCLUDE_SUFFIX 内，
                 # 这些临时文件曾意外随 zip 泄露给同事）。新增调试产物时在此登记。
                 "_final_be.txt", "pytest_out.txt",
                 # 运行时个人配置（全部开关 / 过滤 / 保存路径等），与 build.py 的
                 # SOURCE_ZIP_EXCLUDE_FILES 保持一致，不该随源码分发出去。
                 "config.json",
                 # 旧版配置文件名（自动迁移后作为用户备份保留），同样排除
                 "settings.json"}
EXCLUDE_SUFFIX = (".pyc", ".pyo", ".pyd", ".spec", ".log", ".tmp")
# 需要通配匹配的排除项（文件名模式），与 build.py 的规则对齐。
EXCLUDE_GLOBS = ("adb_devaudio_*.wav",)
ZIP_RE = re.compile(rf"^{re.escape(NAME)}_v(\d{{4}}\.\d{{4}}\.\d{{4}})\.zip$")


def _excluded(fname: str) -> bool:
    """该文件名是否属于「不进分发包」的排除项。"""
    if fname in EXCLUDE_FILES or fname.endswith(EXCLUDE_SUFFIX):
        return True
    return any(fnmatch.fnmatch(fname, pat) for pat in EXCLUDE_GLOBS)


def iter_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)
        for f in sorted(filenames):
            if _excluded(f):
                continue
            yield Path(dirpath) / f


def build_zip(root: Path, out: Path, force: bool = False) -> tuple[int, int]:
    """打包，返回 (文件数, 字节数)。

    同名产物默认拒绝覆盖 —— 出现即说明版本号没递增；确需重打同一版本（例如
    打包后又改了 README）时用 --force。
    """
    if out.exists() and not force:
        raise SystemExit(
            f"[错误] 产物已存在，拒绝覆盖：{out}\n"
            f"       （说明版本号未递增；确认要重打同一版本请加 --force）")
    out.parent.mkdir(parents=True, exist_ok=True)
    # 自收录防护：ZipFile(out, "w") 会**先创建**产物文件，之后 os.walk 才遍历目录树
    # —— 若 out 落在 root 之内（--out-dir 指向工程内部，或把 pytest basetemp 设在
    # 工程里），遍历到产物所在目录时它已经存在，zip 便开始把自己往里塞，体积无限
    # 膨胀（实测涨到数 GB 才停）。显式跳过产物自身，与 build.py 的 make_source_zip
    # 保持同一道防线。
    out_resolved = out.resolve()
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for fp in iter_files(root):
            if fp.resolve() == out_resolved:
                continue          # 绝不把正在写的产物打进它自己
            # relpath = 扁平化关键：不套 NAME/ 顶层目录
            z.write(fp, fp.relative_to(root).as_posix())
            n += 1
    return n, out.stat().st_size


def clean_old(out_dir: Path, keep: Path | None) -> list[str]:
    removed = []
    for p in out_dir.glob(f"{NAME}_v*.zip"):
        if keep and p.resolve() == keep.resolve():
            continue
        p.unlink()
        removed.append(p.name)
    return removed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="打包 ADBDeviceCommander 为扁平 zip")
    ap.add_argument("--no-bump", action="store_true", help="不递增版本号")
    ap.add_argument("--reset-to-now", action="store_true", help="本次修正版本基线为真实时间")
    ap.add_argument("--keep-old", action="store_true", help="保留旧版本 zip（默认清理）")
    ap.add_argument("--force", action="store_true",
                    help="允许覆盖同名产物（重打同一版本时用）")
    ap.add_argument("--out-dir", default=str(ROOT.parent), help="产物输出目录")
    args = ap.parse_args(argv)

    try:
        current = read_version(ROOT)
    except VersionError as e:
        print(f"[错误] {e}", file=sys.stderr)
        return 2

    if args.no_bump:
        version = current
        print(f"使用现有版本号：{version}")
    else:
        version = next_version(current, reset=args.reset_to_now)
        try:
            changed = write_version(version, ROOT)
        except VersionError as e:
            print(f"[错误] {e}", file=sys.stderr)
            return 2
        tag = "（基线修正）" if args.reset_to_now else ""
        print(f"版本号：{current} -> {version}{tag}")
        for rel in changed:
            print(f"  已更新 {rel}")

    out_dir = Path(args.out_dir).resolve()
    out = out_dir / f"{NAME}_v{version}.zip"

    if args.force and out.exists():
        out.unlink()
        print(f"  已删除同名旧产物 {out.name}（--force）")

    n, size = build_zip(ROOT, out, force=args.force)
    print(f"\n产物：{out}")
    print(f"文件数：{n}   大小：{size / 1024:.1f} KB")

    # 结构自检：不允许出现顶层 NAME/ 目录
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
    bad = [p for p in names if p.split("/")[0] == NAME]
    if bad:
        print(f"[警告] zip 内存在顶层目录 {NAME}/，共 {len(bad)} 项 —— 结构不符合预期",
              file=sys.stderr)
        return 1
    print(f"结构自检：扁平 ✓（共 {len(names)} 项，无顶层 {NAME}/ 目录）")

    if not args.keep_old:
        removed = clean_old(out_dir, keep=out)
        for r in removed:
            print(f"  已清理旧包 {r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
