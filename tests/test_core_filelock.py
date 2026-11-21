# -*- coding: utf-8 -*-
"""core.filelock —— 跨进程独占文件锁单测（标准库实现）。

flock(POSIX) / msvcrt.locking(Windows) 在**同一进程内的不同 fd** 之间也会
互斥，因此用多线程即可稳定覆盖加锁/阻塞/释放语义，无需真的起子进程。
跨进程不丢更新的端到端验证见 tests/test_core_prefs.py 的并发写用例。
"""
import os
import threading
import time

import pytest

import core.filelock as fl


def test_lock_path_derived_from_target(tmp_path):
    """锁文件路径 = 被保护文件路径 + .lock（同目录，不同安装位置互不干扰）。"""
    target = str(tmp_path / "config.json")
    lp = fl.lock_path_for(target)
    assert lp == target + ".lock"
    assert os.path.dirname(lp) == os.path.dirname(target)
    assert fl.lock_path_for(str(tmp_path / "other" / "config.json")) != fl.lock_path_for(target)


def test_exclusive_lock_blocks_second_holder(tmp_path):
    """同一把锁被占时，第二个持有者必须等待，直到第一个释放。"""
    lp = str(tmp_path / "config.json.lock")
    entered_first = threading.Event()
    release_first = threading.Event()
    got_second = threading.Event()
    result = {}

    def first():
        with fl.exclusive_file_lock(lp):
            result["first_acquired"] = True
            entered_first.set()
            release_first.wait(3)

    def second():
        entered_first.wait(3)
        with fl.exclusive_file_lock(lp, timeout=5):
            result["second_acquired"] = True
        got_second.set()

    t1 = threading.Thread(target=first)
    t2 = threading.Thread(target=second)
    t1.start()
    assert entered_first.wait(3), "第一个持有者应已进入临界区"
    t2.start()
    # 第一个未释放前，第二个不应进入（短暂等待足以暴露「没上锁」的情况）
    time.sleep(0.15)
    assert not got_second.is_set(), "锁被占时第二个持有者不应进入临界区"
    release_first.set()
    t1.join(3)
    t2.join(5)
    assert result.get("first_acquired") and result.get("second_acquired")


def test_lock_is_reentrant_same_instance(tmp_path):
    """同一 FileLock 实例嵌套进入不应自锁死（threading.RLock 语义）。"""
    lp = str(tmp_path / "config.json.lock")
    with fl.FileLock(lp) as lk:
        assert lk.acquired
        with lk as inner:
            assert inner is lk
            assert lk.acquired
        # 内层退出后仍持有，外层可继续
        assert lk._depth == 1
    assert lk._depth == 0


def test_lock_timeout_degrades_without_hanging(tmp_path):
    """拿不到锁时按超时降级（acquired=False），绝不无限等待。"""
    lp = str(tmp_path / "config.json.lock")
    hold = threading.Event()

    def holder():
        with fl.exclusive_file_lock(lp):
            hold.set()
            time.sleep(1.2)

    t = threading.Thread(target=holder)
    t.start()
    assert hold.wait(3)
    t0 = time.monotonic()
    with fl.exclusive_file_lock(lp, timeout=0.1) as lk:
        elapsed = time.monotonic() - t0
        assert lk.acquired is False, "竞争超时必须降级为无锁"
        assert elapsed < 0.8, "降级必须及时，不能卡住界面"
    t.join(3)


def test_lock_survives_exception_in_critical_section(tmp_path):
    """临界区内抛异常时也必须释放锁（否则后续全部阻塞）。"""
    lp = str(tmp_path / "config.json.lock")
    with pytest.raises(ValueError):
        with fl.exclusive_file_lock(lp) as lk:
            assert lk.acquired
            raise ValueError("boom")
    # 再次进入应立即成功——证明异常路径已释放
    with fl.exclusive_file_lock(lp, timeout=1) as lk2:
        assert lk2.acquired is True
