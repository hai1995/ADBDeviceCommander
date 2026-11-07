"""LogcatMonitor 在设备安静时也要按时把攒下的行推出去。

回归：worker 原来直接 `for raw in proc.stdout` 阻塞读，批量推送的
「攒够 _BATCH_MAX 行 / 距上次推送超过 _FLUSH_MS」只在**收到下一行**时才会
被检查。设备安静下来后读循环一直阻塞，最后那几条日志（以及启动爆发期尾部）
就一直压着不推 —— 界面上「日志停在半路，一按停止反而全出现了」，用户会
以为监控挂了。现在 stdout 由读线程搬进队列，消费循环用 get(timeout) 等待，
超时即按时刷新/收尾爆发期，不再依赖设备继续吐日志。
"""
import threading
import time

import backend.logcat_service as ls


class _FakeBus:
    def __init__(self):
        self.events = []

    def push(self, kind, payload=None):
        self.events.append({"kind": kind, "payload": payload})

    def pushed_lines(self):
        return sum(len(e["payload"]["lines"]) for e in self.events
                   if e["kind"] == "logcat"
                   and e["payload"].get("status") == "append")


class _QuietProc:
    """按 delays 依次吐行（每行前先睡对应秒数），吐完后无限阻塞模拟设备安静。

    靠 terminate() 结束（stop() 会调它）。
    """

    def __init__(self, delays, line):
        self._delays = list(delays)
        self._line = line
        self._i = 0
        self._stop = False
        self._block = threading.Event()
        self.returncode = 0

    @property
    def stdout(self):
        return self

    def __iter__(self):
        return self

    def __next__(self):
        if self._stop:
            raise StopIteration
        if self._i < len(self._delays):
            time.sleep(self._delays[self._i])
            self._i += 1
            return self._line
        self._block.wait()
        raise StopIteration

    def terminate(self):
        self._stop = True
        self._block.set()

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0


_LINE = "08-29 10:00:00.000  1  1 I Tag: tail\n"


def _wait_lines(bus, n, timeout=0.6):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if bus.pushed_lines() >= n:
            return True
        time.sleep(0.02)
    return False


def _setup(monkeypatch, proc):
    monkeypatch.setattr(ls.subprocess, "Popen", lambda *a, **kw: proc)
    # 缩短窗口，测试不必等默认的 1 秒爆发期
    monkeypatch.setattr(ls, "BOOT_WINDOW_SEC", 0.05)
    monkeypatch.setattr(ls, "_FLUSH_MS", 0.05)


def test_idle_tail_is_flushed_without_stop(monkeypatch):
    """最后一批（未攒满 400 行、且距上次推送不足 50ms）在设备安静后仍要推出。

    时间线：第 2 行落在爆发期结束后（触发一次推送并重置 last），第 3 行仅隔
    10ms 到达，未到刷新窗口；此后设备彻底安静 —— 旧实现下第 3 行要等到用户
    点停止才出现。
    """
    bus = _FakeBus()
    mon = ls.LogcatMonitor(bus, adb_path="adb")
    # 第 1 行落在爆发期内；第 2 行（+60ms）结束爆发期并推送；第 3 行（+10ms）
    # 进入正常批次，随后设备安静。
    _setup(monkeypatch, _QuietProc([0, 0.06, 0.01], _LINE))

    assert mon.start("A1", ["main"]) is True
    try:
        assert _wait_lines(bus, 3), (
            "设备安静后最后一批日志仍被压在 worker 里（停止前只收到 %d 行）"
            % bus.pushed_lines())
    finally:
        mon.stop("A1")


def test_boot_tail_is_flushed_when_stream_goes_quiet(monkeypatch):
    """启动爆发期内只来了几行就安静：到点也要结束爆发期并推送，不能干等下一行。"""
    bus = _FakeBus()
    mon = ls.LogcatMonitor(bus, adb_path="adb")
    _setup(monkeypatch, _QuietProc([0, 0, 0], _LINE))

    assert mon.start("A1", ["main"]) is True
    try:
        assert _wait_lines(bus, 3), (
            "爆发期尾部日志在设备安静后未按时推送（停止前只收到 %d 行）"
            % bus.pushed_lines())
    finally:
        mon.stop("A1")
