"""backend.mf_native / mf_capture_service 的纯逻辑测试（不依赖 dll / Windows）。

验证：NalBuffer 跨块切分、MFNative 不可用时的可读原因、MFCaptureService
多设备启动/停止/取消的调用序列与"任一失败全撤销"。真机 native 行为不在
本测试覆盖范围（见 native/README.md 的 [NEEDS-VERIFY]）。
"""
import importlib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

mn = importlib.import_module("backend.mf_native")
mcs = importlib.import_module("backend.mf_capture_service")


class FakeNative:
    """记录调用序列的 native 替身；available 可控。"""

    class FakeWorker:
        def stop(self):
            pass

    def __init__(self, available=True, fail_serial=None):
        self._available = available
        self.error = "未找到 adc_mf_sink.dll（测试替身）"
        self.worker = self.FakeWorker()
        self.calls = []
        self._h = 0
        self.fail_serial = fail_serial
        self.mic = (48000, 16, 2)  # (rate, bits, channels)

    @property
    def available(self):
        return self._available

    def start_worker(self):
        self.calls.append(("start_worker",))
        return self.worker

    def last_error(self):
        return "native 错误（测试替身）"

    def mic_start(self, endpoint, rate, bits, channels):
        self.calls.append(("mic_start", endpoint, rate, bits, channels))
        return 0

    def mic_stop(self):
        self.calls.append(("mic_stop",))

    def mic_format(self):
        return self.mic  # (rate, bits, channels)

    def session_create(self, out_dir, stem, w, h, fn, fd, arate, abits, ach):
        self.calls.append(("session_create", stem, w, h, arate, abits, ach))
        self._h += 1
        return self._h, f"{out_dir}\\{stem}.tmp.mp4"

    def session_write_video(self, h, data):
        self.calls.append(("write_video", h, len(data)))

    def session_mark_mic_stop(self, h):
        self.calls.append(("mark_mic_stop", h))

    def session_finalize(self, h):
        self.calls.append(("finalize", h))
        return [f"out_{h}.mp4"]

    def session_discard(self, h):
        self.calls.append(("discard", h))

    def session_destroy(self, h):
        self.calls.append(("destroy", h))


class FakeProc:
    def __init__(self, chunks):
        import io
        self.stdout = io.BytesIO(b"".join(chunks))
        self.stderr = io.BytesIO(b"")
        self._poll = [None]

    def poll(self):
        return None

    def terminate(self):
        pass

    def wait(self, timeout=None):
        self._poll[0] = 0
        return 0

    def kill(self):
        pass


# ------------------------- NalBuffer ------------------------------------

def test_nal_buffer_splits_across_chunks():
    """单条 NAL 跨两块时，只在完整边界吐出，不截断。"""
    sc4 = b"\x00\x00\x00\x01"
    nal1 = sc4 + b"\x67SPS" + sc4 + b"\x68PPS"
    data = nal1 + sc4 + b"\x65IDR"
    nb = mn.NalBuffer()
    cut = 8
    out = nb.feed(data[:cut]) + nb.feed(data[cut:]) + nb.flush()
    joined = b"".join(out)
    assert sc4 in joined
    assert b"IDR" in joined
    # 每条吐出的段都以起始码开头（不产生起始码残缺的半条）
    for seg in out:
        assert seg.startswith(b"\x00\x00\x01")


def test_nal_buffer_ignores_noise_before_first_startcode():
    nb = mn.NalBuffer()
    # 末条 NAL 保留在缓冲直到下一起始码或 flush，避免重复发送。
    out = nb.feed(b"NOISE" + b"\x00\x00\x01\x65\xaa\xbb") + nb.flush()
    assert len(out) == 1
    assert out[0].startswith(b"\x00\x00\x01")


def test_nal_buffer_no_duplicate_last_nal():
    """回归：末条 NAL 不能在 feed 和 flush 里各发一次（会破坏 H264 参考帧）。"""
    sc = b"\x00\x00\x00\x01"
    nb = mn.NalBuffer()
    first = nb.feed(sc + b"\x65AAA")
    assert first == []                       # 只有一条起始码 → 未完整，不吐
    # 下一条起始码到来，第一条才完整吐出；末条仍留缓冲。
    second = nb.feed(sc + b"\x41BBB")
    assert len(second) == 1 and b"AAA" in second[0]
    tail = nb.flush()
    assert len(tail) == 1 and b"BBB" in tail[0]
    joined = b"".join(second + tail)
    assert joined.count(b"AAA") == 1 and joined.count(b"BBB") == 1


# ------------------------- MFNative 可用性 -------------------------------

def test_mf_native_unavailable_on_non_windows(monkeypatch):
    monkeypatch.setattr(os, "name", "posix")
    n = mn.MFNative()
    assert n.available is False
    assert "Windows" in n.error


# ------------------------- MFCaptureService 编排 -------------------------

def test_service_unavailable_returns_reason(monkeypatch):
    fake = FakeNative(available=False)
    svc = mcs.MFCaptureService(native=fake)
    ok, reason, firsts = svc.start_all(["s1"], "/tmp", {}, {}, None)
    assert ok is False
    assert "dll" in reason
    assert firsts == {}


def test_service_multi_device_mic_started_once_and_broadcast(monkeypatch):
    """多设备：麦克风只启动一次，两个 session 都创建，stop 都 finalize。"""
    fake = FakeNative(available=True)

    def fake_popen(cmd, **kw):
        return FakeProc([b"\x00\x00\x01\x65" + b"\xaa" * 16])

    monkeypatch.setattr(mcs.subprocess, "Popen", fake_popen)
    svc = mcs.MFCaptureService(native=fake)
    ok, reason, firsts = svc.start_all(
        ["s1", "s2"], "/tmp", {}, {}, None)
    assert ok is True, reason
    assert len(firsts) == 2
    mic_starts = [c for c in fake.calls if c[0] == "mic_start"]
    assert len(mic_starts) == 1
    creates = [c for c in fake.calls if c[0] == "session_create"]
    assert len(creates) == 2
    # 音频格式用 native 回读的真实值 (rate, bits, channels)
    assert creates[0][4:] == (48000, 16, 2)
    out = svc.stop_all()
    assert set(out.keys()) == {"s1", "s2"}
    for s, (paths, err) in out.items():
        assert paths and paths[0].startswith("out_")
    assert any(c[0] == "mark_mic_stop" for c in fake.calls)
    assert any(c[0] == "mic_stop" for c in fake.calls)


def test_service_cancel_discards_without_publish(monkeypatch):
    fake = FakeNative(available=True)

    def fake_popen(cmd, **kw):
        return FakeProc([b"\x00\x00\x01\x65" + b"\xbb" * 8])

    monkeypatch.setattr(mcs.subprocess, "Popen", fake_popen)
    svc = mcs.MFCaptureService(native=fake)
    ok, reason, _ = svc.start_all(["s1"], "/tmp", {}, {}, None)
    assert ok is True
    svc.cancel_all()
    assert any(c[0] == "discard" for c in fake.calls)
    assert not any(c[0] == "finalize" for c in fake.calls)


def test_h264_cmd_has_no_ffmpeg_and_explicit_format():
    cmd = mcs.h264_cmd("adb", "s1", size="1080x1920", bitrate_mbps=12)
    assert "exec-out" in cmd
    assert "--output-format=h264" in cmd
    assert "--bit-rate" in cmd and "12000000" in cmd
    assert "-" == cmd[-1]
    assert all("ffmpeg" not in str(x) for x in cmd)
