# -*- coding: utf-8 -*-
"""backend.workers.Workers —— 工作线程管理单测（去重 / 记档 / 关闭）。"""
import threading
import time

from backend.workers import Workers


def _sleep_fn(events, marker, seconds=0.3):
    time.sleep(seconds)
    events.append(marker)


def test_spawn_named_dedup_while_alive():
    w = Workers()
    events = []
    t1 = w.spawn("job", _sleep_fn, events, "a", 0.3)
    # 同名任务在 t1 存活期间再次 spawn：直接返回同一个线程，不叠加
    t2 = w.spawn("job", _sleep_fn, events, "b", 0.3)
    assert t1 is t2
    assert w.is_running("job") is True
    assert w.alive_count() == 1
    w.shutdown(timeout=2.0)
    assert w.is_running("job") is False
    assert events == ["a"]  # 只执行了第一份


def test_spawn_named_after_finish_allows_new_run():
    w = Workers()
    events = []
    t1 = w.spawn("job", _sleep_fn, events, "1", 0.05)
    t1.join(1.0)
    assert not t1.is_alive()
    t2 = w.spawn("job", _sleep_fn, events, "2", 0.05)
    assert t1 is not t2
    t2.join(1.0)
    assert events == ["1", "2"]


def test_anonymous_always_new_thread():
    w = Workers()
    started = []
    both_started = threading.Event()
    release = threading.Event()

    def fn():
        # 线程真正开始执行时才落下标记，随后阻塞保活以便并发确权
        started.append(threading.current_thread())
        if len(started) >= 2:
            both_started.set()
        release.wait(1.0)

    t1 = w.spawn(None, fn)
    t2 = w.spawn(None, fn)
    # 关键断言：匿名任务每次都新开线程（对象不同）
    assert t1 is not t2
    # 确权：两个线程都确实已经开始执行（消除 is_alive() 时序竞态）
    assert both_started.wait(1.0)
    assert len(started) == 2
    release.set()
    w.shutdown(timeout=2.0)


def test_shutdown_waits_and_is_idempotent():
    w = Workers()
    ev = threading.Event()

    def hold_fn():
        ev.wait(0.3)          # 保活 0.3s，确保 shutdown 有可等待的目标

    w.spawn("a", hold_fn)
    w.spawn("b", hold_fn)
    w.spawn(None, hold_fn)
    # 等待三个线程都真正启动（消除 start() 后 is_alive 时序竞态）
    deadline = time.time() + 2.0
    while w.alive_count() < 3 and time.time() < deadline:
        time.sleep(0.01)
    assert w.alive_count() == 3
    assert w.shutdown(timeout=2.0) == 0
    assert w.shutdown(timeout=0.01) == 0
    assert w.alive_count() == 0
    assert w.running_keys() == []
    assert w.is_running() is False
    ev.set()


def test_short_lived_thread_does_not_count():
    w = Workers()
    ev = threading.Event()

    def quick():
        ev.set()

    w.spawn("quick", quick)
    assert ev.wait(1.0) is True
    w.shutdown(timeout=1.0)
    assert w.alive_count() == 0
