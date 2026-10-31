# -*- coding: utf-8 -*-
"""
core.tmpfiles —— 系统临时目录里「本程序遗留文件」的保守清理。
====================================================================
为什么需要专门一只：文件页的「查看」在遇到大文件 / 二进制时，唯一正确的做法
是把文件 pull 到系统临时目录（%TEMP%），再交给系统默认程序打开 —— 大文件经
事件总线直传前端会把界面卡死。但那些 pull 下来的副本没人删：每看一次大文件
就在 TEMP 里留一份，几百 MB 的日志看几次就能吃掉几个 GB，而用户根本不知道
它们在哪、叫什么。

清理策略刻意保守（宁可留，也不误删）：
  * 只碰调用方显式给的前缀（默认 adb_view_ / adb_up_ / adb_devaudio_），
    绝不递归、绝不删别人的文件；
  * ``keep_newest``：按 mtime 保留最新的 N 个 —— 用户刚打开、系统查看器可能还
    在读的那一份一定在保留集合里；
  * ``min_age_s``：只删「足够旧」的，刚生成的文件一律跳过（同样是为了避免删掉
    正在被查看的副本）；
  * 单个文件失败（被占用 / 无权限 / 已消失）只跳过并计数，绝不影响调用方。

返回值是统计字典，便于日志 / 单测断言；本模块不抛异常。
"""
import os
import tempfile
import time

# 本程序在系统临时目录里留下的文件前缀（新增此类文件时记得加到这里）。
#   adb_view_     「查看」大文件时 pull 下来的副本（本模块的主要目标）
#   adb_up_       上传时前端字节落地的中转文件（正常路径由调用方 finally 删除，
#                 只在进程被强杀 / 崩溃时残留）
#   adb_devaudio_ 录屏时设备端音频 pull 回来的 wav（合成后由调用方删除，
#                 同上，异常路径会残留）
# 后两个早前没纳入清理：一次崩溃就会在 TEMP 里留下几百 MB 的孤儿文件，
# 而用户既不知道文件名也不知道它们在哪，只能等系统清理工具。
VIEW_PREFIX = "adb_view_"
UPLOAD_PREFIX = "adb_up_"
DEVAUDIO_PREFIX = "adb_devaudio_"
DEFAULT_PREFIXES = (VIEW_PREFIX, UPLOAD_PREFIX, DEVAUDIO_PREFIX)


def _candidates(directory, prefixes):
    """列出目录下符合前缀的普通文件 -> [(path, mtime, size)]。"""
    out = []
    try:
        names = os.listdir(directory)
    except Exception:
        return out
    for name in names:
        if not any(name.startswith(p) for p in prefixes if p):
            continue
        path = os.path.join(directory, name)
        try:
            # isfile 而非 exists / 不跟随符号链接：目录与其他特殊文件一律不碰
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            st = os.stat(path)
            out.append((path, st.st_mtime, st.st_size))
        except OSError:
            continue
    return out


def sweep(prefixes=DEFAULT_PREFIXES, keep_newest=8, min_age_s=600.0,
          directory=None, now=None):
    """删除本程序遗留在临时目录里的文件，返回统计 dict。

    参数
    ----
    prefixes    只处理文件名以这些前缀开头的文件（默认 DEFAULT_PREFIXES：
                adb_view_ / adb_up_ / adb_devaudio_）
    keep_newest 按 mtime 降序保留最新 N 个；传 0 表示不按数量保留（只按年龄）
    min_age_s   只删除「修改时间早于 now - min_age_s」的文件
    directory   目标目录，默认系统临时目录
    now         当前时间戳（单测注入用）

    返回 ``{"removed": n, "freed": bytes, "kept": n, "failed": n, "scanned": n}``。
    """
    d = directory or tempfile.gettempdir()
    t = time.time() if now is None else float(now)
    items = _candidates(d, prefixes)
    items.sort(key=lambda it: it[1], reverse=True)     # 最新在前
    keep = max(0, int(keep_newest or 0))
    stats = {"removed": 0, "freed": 0, "kept": 0, "failed": 0,
             "scanned": len(items)}
    for idx, (path, mtime, size) in enumerate(items):
        if idx < keep:
            stats["kept"] += 1
            continue
        if min_age_s and (t - mtime) < float(min_age_s):
            stats["kept"] += 1
            continue
        try:
            os.remove(path)
            stats["removed"] += 1
            stats["freed"] += max(0, int(size or 0))
        except OSError:
            # 被别的进程占用（Windows 上查看器正开着）时删除会失败：跳过即可，
            # 下次查看或下次启动会再清一遍。
            stats["failed"] += 1
            stats["kept"] += 1
    return stats


def sweep_view_files(keep_newest=8, min_age_s=600.0, directory=None, now=None):
    """专用入口：清理「查看大文件」留下的临时副本（语义见 sweep）。"""
    return sweep(prefixes=(VIEW_PREFIX,), keep_newest=keep_newest,
                 min_age_s=min_age_s, directory=directory, now=now)


def boot_sweep(min_age_s=3600.0, directory=None, now=None):
    """启动时清理上一轮会话遗留的临时副本。

    上一轮程序已经退出，它 pull 下来的副本再没人会去打开，但也不能「无条件全删」
    —— 用户可能正在用别的程序看那次导出的文件。给一小时宽限：正常使用不会受影响，
    而长期堆积的垃圾一定能清掉。
    """
    return sweep(prefixes=DEFAULT_PREFIXES, keep_newest=0,
                 min_age_s=min_age_s, directory=directory, now=now)
