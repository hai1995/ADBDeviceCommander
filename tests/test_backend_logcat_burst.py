"""LogcatMonitor 启动爆发期（历史 dump）限流测试。

adb logcat 不带 -t 时，启动瞬间会把设备缓冲区里的历史日志（动辄上万行）一次性
吐出来。曾经前端把这些全量灌进来，直接导致「一开始监控就卡死、滚动没反应」。
这里验证：burst 阶段只保留最近若干行（BOOT_KEEP_LINES），其余丢弃并提示。
"""
import threading
import time


import backend.logcat_service as ls


class _FakeBus:
    def __init__(self):
        self.events = []

    def push(self, kind, payload=None):
        self.events.append({"kind": kind, "payload": payload})


class _BurstStreamProc:
    """先瞬时吐出 burst 行（模拟历史 dump），之后缓慢持续产出（模拟实时日志）。
    无限循环，靠 terminate() 结束。"""

    def __init__(self, burst_lines, stream_delay=0.02, block_after_stream=None):
        self._burst = list(burst_lines)
        self._bi = 0
        self._streamed = 0
        self._stream_delay = stream_delay
        self._block_after = block_after_stream
        self._stop = False
        self._block = threading.Event()
        self._parked = threading.Event()
        self.returncode = 0

    @property
    def stdout(self):
        return self

    def __iter__(self):
        return self

    def __next__(self):
        if self._stop:
            raise StopIteration
        if self._bi < len(self._burst):
            line = self._burst[self._bi % len(self._burst)]
            self._bi += 1
            return line
        if self._block_after is not None and self._streamed >= self._block_after:
            self._parked.set()
            self._block.wait()
            raise StopIteration
        time.sleep(self._stream_delay)
        self._streamed += 1
        return self._burst[self._streamed % len(self._burst)]

    def parked(self, timeout=5.0):
        return self._parked.wait(timeout)

    def terminate(self):
        self._stop = True
        self._block.set()

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0


def test_monitor_skips_history_burst(monkeypatch):
    """启动瞬间大量历史日志只保留最近若干行，不一次性灌进前端（卡顿主因）。"""
    bus = _FakeBus()
    mon = ls.LogcatMonitor(bus, adb_path="adb")

    # 3000 行历史 dump（threadtime 格式，能被 classify_line 识别为 I 级）
    burst = ["08-29 10:00:00.%03d  1  1 I Tag: hist %d\n" % (i % 1000, i)
             for i in range(3000)]

    def fake_popen(cmd, **kw):
        return _BurstStreamProc(burst, stream_delay=0.02)

    monkeypatch.setattr(ls.subprocess, "Popen", fake_popen)

    assert mon.start("A1", ["main"]) is True

    # 等过爆发期（BOOT_WINDOW_SEC=1.0s）让其 flush 并进入正常模式
    time.sleep(1.6)
    mon.stop("A1")

    append_lines = 0
    last_total = 0
    for e in bus.events:
        if e["kind"] == "logcat" and e["payload"].get("status") == "append":
            append_lines += len(e["payload"]["lines"])
            last_total = max(last_total, e["payload"].get("total", 0))

    # 关键：前端实际收到的行数远小于历史总量（否则依旧会卡死）
    assert append_lines < 3000, (
        "历史日志未限流：前端收到 %d 行，等于全部历史" % append_lines)
    assert append_lines >= 500, "至少应保留最近若干行"
    assert last_total >= 3000, "worker 应处理完所有历史行（total=%d）" % last_total

    info = [e for e in bus.events
            if e["kind"] == "status"
            and "已跳过" in (e["payload"].get("text") or "")
            and "历史日志" in (e["payload"].get("text") or "")]
    assert info, "缺少「已跳过 N 行历史日志」提示"
