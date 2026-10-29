#!/usr/bin/env python3
"""版本号管理：自动生成**严格递增**的版本号，并写回所有硬编码位置。

版本号格式：`YYYY.MMDD.HHMM`（本地时间 = 构建时刻），与项目既有风格一致。

规则
----
1. 默认取**真实当前时间**作为候选号。
2. 若候选号 <= 当前版本号（跨会话/跨天时可能发生），则在当前版本号基础上
   +1 分钟，直到严格大于为止 —— 保证任何情况下都**不会撞号、不会倒退**。
3. `--reset-to-now`：忽略单调约束，直接把基线修正为真实当前时间。
   仅在历史版本号被误写成未来时间等异常情况下一次性使用。

⚠️ 请不要手工编辑版本号 —— 一律走本脚本，避免多处硬编码不同步。

用法
----
    python tools/bump_version.py                      # 预览新版本号（不写入）
    python tools/bump_version.py --apply              # 写入并打印新版本号
    python tools/bump_version.py --apply --reset-to-now   # 修正基线为真实时间
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 硬编码 VERSION = "..." 的源码文件（两处必须保持一致）
VERSION_FILES = ["core/constants.py", "main.py"]
VERSION_RE = re.compile(r'^(VERSION\s*=\s*)"(\d{4}\.\d{4}\.\d{4})"', re.M)

# README 里的架构标题：## 架构（vXXXX Web 版）
README_FILE = "README.md"
README_TITLE_RE = re.compile(r"(## 架构（v)(\d{4}\.\d{4}\.\d{4})( Web 版）)")

FMT = "%Y.%m%d.%H%M"
VER_RE = re.compile(r"^\d{4}\.\d{4}\.\d{4}$")


class VersionError(RuntimeError):
    pass


def read_version(root: Path = ROOT) -> str:
    """读取当前版本号；两处硬编码不一致时直接报错（避免静默发散）。"""
    found: dict[str, str] = {}
    for rel in VERSION_FILES:
        p = root / rel
        if not p.exists():
            raise VersionError(f"缺少版本文件：{p}")
        m = VERSION_RE.search(p.read_text(encoding="utf-8"))
        if not m:
            raise VersionError(f"{rel} 中未找到 VERSION = \"...\" 定义")
        found[rel] = m.group(2)
    vals = set(found.values())
    if len(vals) != 1:
        detail = "、".join(f"{k}={v}" for k, v in sorted(found.items()))
        raise VersionError(f"各处 VERSION 不一致（{detail}），请先手工统一")
    return vals.pop()


def parse_version(v: str) -> datetime:
    if not VER_RE.match(v):
        raise VersionError(f"版本号格式非法：{v!r}（应为 YYYY.MMDD.HHMM）")
    try:
        return datetime.strptime(v, FMT)
    except ValueError as e:
        raise VersionError(f"版本号不是合法时间：{v!r}（{e}）") from e


def next_version(current: str, now: datetime | None = None, reset: bool = False) -> str:
    """计算新版本号。

    reset=True  -> 直接用真实当前时间（一次性基线修正）。
    reset=False -> max(真实当前时间, 当前版本 +1 分钟)，保证严格递增。
    """
    now = now or datetime.now()
    cur_dt = parse_version(current)
    candidate = now.strftime(FMT)

    if reset:
        if candidate == current:
            # 同一分钟内重复修正，退化为 +1 分钟，仍保证不撞号
            return (cur_dt + timedelta(minutes=1)).strftime(FMT)
        return candidate

    if candidate > current:
        return candidate
    # 当前时间落后于已有版本号：在已有基础上按分钟递增，保证严格递增
    new_dt = cur_dt + timedelta(minutes=1)
    while new_dt.strftime(FMT) <= current:
        new_dt += timedelta(minutes=1)
    return new_dt.strftime(FMT)


def write_version(new: str, root: Path = ROOT) -> list[str]:
    """把新版本号写入源码与 README 标题，返回改动文件列表。"""
    parse_version(new)  # 先校验格式
    changed: list[str] = []

    for rel in VERSION_FILES:
        p = root / rel
        text = p.read_text(encoding="utf-8")
        new_text, n = VERSION_RE.subn(lambda m: f'{m.group(1)}"{new}"', text)
        if n != 1:
            raise VersionError(f"{rel} 中 VERSION 替换异常（匹配 {n} 处，应为 1 处）")
        if new_text != text:
            p.write_text(new_text, encoding="utf-8")
            changed.append(rel)

    rp = root / README_FILE
    if rp.exists():
        text = rp.read_text(encoding="utf-8")
        new_text, n = README_TITLE_RE.subn(lambda m: f"{m.group(1)}{new}{m.group(3)}", text)
        if n > 0 and new_text != text:
            rp.write_text(new_text, encoding="utf-8")
            changed.append(README_FILE)

    return changed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="版本号递增（YYYY.MMDD.HHMM，严格递增）")
    ap.add_argument("--apply", action="store_true", help="真正写入文件（默认只预览）")
    ap.add_argument("--reset-to-now", action="store_true",
                    help="忽略单调约束，把基线修正为真实当前时间（一次性用）")
    ap.add_argument("--set", metavar="YYYY.MMDD.HHMM",
                    help="直接指定版本号（仍会校验格式与严格递增）")
    args = ap.parse_args(argv)

    try:
        current = read_version()
    except VersionError as e:
        print(f"[错误] {e}", file=sys.stderr)
        return 2

    now = datetime.now()
    # parse_version / next_version 都在 try 里：`--set 2026.0230.1200` 这类
    # 「正则合法但不是真实日期」的取值会抛 VersionError，而 year 9999 的版本号还会让
    # `cur_dt + timedelta(minutes=1)` 抛 OverflowError —— 两处旧实现都在 try 之外，
    # 用户看到的是英文 traceback（退出码 1），而不是本脚本约定的中文提示 + 退出码 2。
    try:
        if args.set:
            new = args.set
            parse_version(new)          # 格式校验
            if new <= current:
                print(f"[错误] 指定版本号 {new} 未严格大于当前 {current}", file=sys.stderr)
                return 2
        else:
            new = next_version(current, now, reset=args.reset_to_now)
    except VersionError as e:
        print(f"[错误] {e}", file=sys.stderr)
        return 2
    except (OverflowError, OSError) as e:
        print(f"[错误] 版本号超出可表示范围：{e}", file=sys.stderr)
        return 2

    flag = "（基线修正）" if args.reset_to_now else ""
    print(f"当前版本: {current}")
    print(f"真实时间: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"新版本号: {new}{flag}")

    if not args.apply:
        print("\n（预览模式，未写入。加 --apply 生效）")
        return 0

    try:
        changed = write_version(new)
    except VersionError as e:
        print(f"[错误] {e}", file=sys.stderr)
        return 2

    for rel in changed:
        print(f"  已更新 {rel}")
    if not changed:
        print("  （无文件需要改动）")
    print(f"\n完成，当前版本 = {new}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
