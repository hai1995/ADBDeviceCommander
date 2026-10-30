"""LogcatMonitor 展示行数软上限（滑动窗口限流）测试。

设备日志洪流（嘈杂应用 / chatty 刷屏）下，即便总线有积压背压，主线程仍会被
持续的「JSON 跨进程传输 + 解析 + 分帧渲染」占满 —— 一开始监控整个程序就
卡顿（用户实报）。这里验证 worker 按 LOGCAT_DISPLAY_MAX_LPS（行/秒）从源头
节流：
  1. 高频流下推给前端的行数被压在上限以内（不是来多少收多少）；
  2. 丢弃量有节流提示（不会把状态栏也刷爆）；
  3. 停止时补报未提示的丢弃量（计数可解释的闭环）；
  4. 抓取（落盘）模式不受此限 —— 文件里仍是全量。
"""
import time


import backend.logcat_service as ls
from core.constants import LOGCAT_DISPLAY_MAX_LPS


class _FakeBus:
    def __init__(self):
        self.events = []

    def push(self, kind, payload=None):
        self.events.append({"kind": kind, "payload": payload})


class _FastStreamProc:
    """无延迟持续吐行（模拟嘈杂设备的高频日志），靠 terminate() 结束。"""

    def __init__(self, line):
        self._line = line
        self._stop = False
        self.returncode = 0

    @property
    def stdout(self):
        return self

    def __iter__(self):
        return self

    def __next__(self):
        if self._stop:
            raise StopIteration
        return self._line

    def terminate(self):
        self._stop = True

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0


def _append_pushes(bus):
    out = []
    for e in bus.events:
        if e["kind"] == "logcat" and e["payload"].get("status") == "append":
            out.append(e["payload"])
    return out


def _status_texts(bus):
    return [e["payload"].get("text") or ""
            for e in bus.events if e["kind"] == "status"]


def test_display_rate_cap_drops_excess(monkeypatch):
    """高频日志下，推给前端的行数被压在 LOGCAT_DISPLAY_MAX_LPS 以内，
    丢弃有提示，停止时补报。"""
    bus = _FakeBus()
    mon = ls.LogcatMonitor(bus, adb_path="adb")

    line = "08-29 10:00:00.000  1  1 I Tag: flood\n"

    def fake_popen(cmd, **kw):
        return _FastStreamProc(line)

    monkeypatch.setattr(ls.subprocess, "Popen", fake_popen)
    # 爆发期压到最短，尽快进入正常限流路径；提示阈值放低，让周期性提示也触发
    monkeypatch.setattr(ls, "BOOT_WINDOW_SEC", 0.2)
    monkeypatch.setattr(ls, "BOOT_KEEP_LINES", 10)
    monkeypatch.setattr(ls, "LOGCAT_DROP_NOTICE_SEC", 0.3)
    monkeypatch.setattr(ls, "LOGCAT_DROP_NOTICE_MIN", 5)

    assert mon.start("A1", ["main"]) is True
    time.sleep(2.2)          # 跨过爆发期 + 至少一个完整限流窗口
    mon.stop("A1")
    time.sleep(0.3)          # 等 worker 收尾（finally 里补报丢弃）

    pushes = _append_pushes(bus)
    pushed = sum(len(p["lines"]) for p in pushes)
    last_total = max((p.get("total", 0) for p in pushes), default=0)

    # 洪流是真的：worker 处理了远超推送量的行（否则本测试没测到限流）
    assert last_total >= 10000, (
        "测试流量不足：worker 只处理了 %d 行，限流未被触发" % last_total)
    # 限流是真的：推送量压在「窗口数 × 上限 + 余量」以内。约 2.2s 的流横跨
    # 3 个 1 秒窗口（最后一个不满的窗口也拿满当窗预算），+400 覆盖启动爆发期
    # 保留行与批尾残量；未限流时这里会是几十万行。
    assert pushed <= LOGCAT_DISPLAY_MAX_LPS * 3 + 400, (
        "展示行数未限流：推送 %d 行，超过 %d 行/秒的软上限" % (pushed, LOGCAT_DISPLAY_MAX_LPS))
    # 上限确实咬住了一大截：至少 2000 行被丢在源头
    assert pushed <= last_total - 2000, (
        "丢弃比例异常：推送 %d / 处理 %d" % (pushed, last_total))

    texts = _status_texts(bus)
    assert any("日志流量过高" in t and "已丢弃约" in t for t in texts), (
        "缺少周期性丢弃提示：%r" % texts)
    assert any("监控结束" in t and "限速丢弃" in t for t in texts), (
        "缺少停止时的丢弃补报：%r" % texts)


def test_capture_not_rate_limited(monkeypatch, tmp_path):
    """抓取（落盘）模式不受展示限流影响：写入文件的行数就是全量。"""
    bus = _FakeBus()
    cap = ls.LogcatCapture(bus, adb_path="adb")

    path = str(tmp_path / "logcat_A1.txt")
    line = "08-29 10:00:00.000  1  1 I Tag: flood\n"
    n_lines = 3000

    class _CountingProc(_FastStreamProc):
        def __init__(self, line, n):
            super().__init__(line)
            self._n = n
            self._i = 0

        def __next__(self):
            if self._stop or self._i >= self._n:
                raise StopIteration
            self._i += 1
            return self._line

    def fake_popen(cmd, **kw):
        return _CountingProc(line, n_lines)

    monkeypatch.setattr(ls.subprocess, "Popen", fake_popen)

    assert cap.start("A1", path, ["main"]) is True
    # 等 worker 把 3000 行写完并收尾（_CountingProc 吐完即 EOF）
    deadline = time.time() + 5
    while time.time() < deadline:
        stopped = [e for e in bus.events
                   if e["kind"] == "logcat_capture"
                   and e["payload"].get("status") == "stopped"]
        if stopped:
            break
        time.sleep(0.05)
    assert stopped, "抓取未正常结束"

    import os
    assert os.path.exists(path), "抓取文件不存在"
    with open(path, "r", encoding="utf-8") as f:
        written = sum(1 for _ in f)
    assert written == n_lines, (
        "抓取模式被误限流：写入 %d 行，应为全量 %d 行" % (written, n_lines))
