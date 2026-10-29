# -*- coding: utf-8 -*-
"""core.tmpfiles 的单测：清理边界必须「宁可留，也不误删」。

这些文件是「查看大文件」时 pull 到系统临时目录的副本，堆积起来能吃掉几个 GB；
但同一目录下还有别的程序的文件、以及用户正在看的那一份 —— 删错比不删更糟。
本文件的用例即把「什么必须留着」钉死。
"""
import os
import time

from core import tmpfiles


def _mk(dirp, name, age_s=0, size=10):
    p = os.path.join(str(dirp), name)
    with open(p, "wb") as f:
        f.write(b"x" * size)
    t = time.time() - age_s
    os.utime(p, (t, t))
    return p


def test_removes_old_view_files(tmp_path):
    old = _mk(tmp_path, "adb_view_aaaa_a.log", age_s=7200)
    stat = tmpfiles.sweep_view_files(keep_newest=0, min_age_s=0,
                                     directory=str(tmp_path))
    assert stat["removed"] == 1 and not os.path.exists(old)
    assert stat["freed"] == 10


def test_keeps_newest_n(tmp_path):
    paths = [_mk(tmp_path, "adb_view_%d_a.log" % i, age_s=1000 * (i + 1))
             for i in range(5)]
    # 最新的 2 个（age 最小）必须留着
    stat = tmpfiles.sweep_view_files(keep_newest=2, min_age_s=0,
                                     directory=str(tmp_path))
    assert stat["removed"] == 3
    alive = [p for p in paths if os.path.exists(p)]
    assert len(alive) == 2
    assert paths[0] in alive and paths[1] in alive


def test_respects_min_age(tmp_path):
    """刚生成的文件一律不删：系统查看器可能正开着它。"""
    fresh = _mk(tmp_path, "adb_view_fresh_a.log", age_s=5)
    stat = tmpfiles.sweep_view_files(keep_newest=0, min_age_s=600,
                                     directory=str(tmp_path))
    assert stat["removed"] == 0
    assert os.path.exists(fresh)


def test_ignores_other_files_and_dirs(tmp_path):
    other = _mk(tmp_path, "report.docx", age_s=99999)
    d = os.path.join(str(tmp_path), "adb_view_iamadir")
    os.makedirs(d)
    stat = tmpfiles.sweep_view_files(keep_newest=0, min_age_s=0,
                                     directory=str(tmp_path))
    assert stat["removed"] == 0
    assert os.path.exists(other) and os.path.isdir(d)


def test_default_prefixes_only_touch_view_files(tmp_path):
    mine = _mk(tmp_path, "adb_view_x", age_s=99999)
    stat = tmpfiles.sweep(prefixes=(tmpfiles.VIEW_PREFIX,), keep_newest=0,
                          min_age_s=0, directory=str(tmp_path))
    assert stat["removed"] == 1 and not os.path.exists(mine)


def test_failed_removal_is_counted_not_raised(tmp_path, monkeypatch):
    """Windows 上文件被查看器占用时删除会抛 OSError：只跳过，不影响调用方。"""
    _mk(tmp_path, "adb_view_locked", age_s=99999)

    def boom(path):
        raise OSError(13, "in use")

    monkeypatch.setattr(tmpfiles.os, "remove", boom)
    stat = tmpfiles.sweep_view_files(keep_newest=0, min_age_s=0,
                                     directory=str(tmp_path))
    assert stat["failed"] == 1 and stat["removed"] == 0


def test_missing_dir_is_silent(tmp_path):
    stat = tmpfiles.sweep_view_files(directory=str(tmp_path / "nope"))
    assert stat["removed"] == 0 and stat["scanned"] == 0


def test_boot_sweep_keeps_recent_leftovers(tmp_path):
    """启动清理只动「一小时前的」：上一轮刚导出的文件可能还在被别的程序打开。"""
    recent = _mk(tmp_path, "adb_view_recent", age_s=60)
    old = _mk(tmp_path, "adb_view_old", age_s=7200)
    stat = tmpfiles.boot_sweep(directory=str(tmp_path))
    assert stat["removed"] == 1
    assert os.path.exists(recent) and not os.path.exists(old)


def test_stats_keys(tmp_path):
    stat = tmpfiles.sweep_view_files(directory=str(tmp_path))
    assert set(stat) == {"removed", "freed", "kept", "failed", "scanned"}


def test_symlink_is_not_followed(tmp_path):
    """临时目录里可能有指向别处的符号链接：绝不跟进去删。"""
    target = _mk(tmp_path, "real_file", age_s=99999)
    link = os.path.join(str(tmp_path), "adb_view_link")
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        return          # 平台不支持符号链接（无权限的 Windows）时跳过
    stat = tmpfiles.sweep_view_files(keep_newest=0, min_age_s=0,
                                     directory=str(tmp_path))
    assert stat["removed"] == 0
    assert os.path.exists(target)
