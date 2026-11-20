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
        def __init__(self, owner):
            self.owner = owner

        def stop(self):
            self.owner.calls.append(("worker_stop",))

    def __init__(self, available=True, fail_serial=None):
        self._available = available
        self.error = "未找到 adc_mf_sink.dll（测试替身）"
        self.worker = self.FakeWorker(self)
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


# ------------------------- 第三轮审查修复回归 ---------------------------

def test_mic_format_zero_rejected(monkeypatch):
    """native 回读 (0,0,0)（格式未就绪/无设备）时必须明确失败，不建会话。"""
    fake = FakeNative(available=True)
    fake.mic = (0, 0, 0)

    def fake_popen(cmd, **kw):
        return FakeProc([b"\x00\x00\x01\x65" + b"\xaa" * 8])

    monkeypatch.setattr(mcs.subprocess, "Popen", fake_popen)
    svc = mcs.MFCaptureService(native=fake)
    ok, reason, firsts = svc.start_all(["s1"], "/tmp", {}, {}, None)
    assert ok is False
    assert "麦克风格式" in reason
    assert not any(c[0] == "session_create" for c in fake.calls)
    # 失败路径必须停麦克风 + 停 worker，不能留后台采集线程
    assert any(c[0] == "mic_stop" for c in fake.calls)


def test_mic_format_exception_becomes_reason(monkeypatch):
    """native mic_format 抛异常（错误码）要转成可读 reason，不冒泡成 500。"""
    fake = FakeNative(available=True)

    def boom():
        raise RuntimeError("native 3s 内无 PCM 格式")

    fake.mic_format = boom
    svc = mcs.MFCaptureService(native=fake)
    ok, reason, firsts = svc.start_all(["s1"], "/tmp", {}, {}, None)
    assert ok is False
    assert "读取麦克风格式失败" in reason


def test_write_video_error_is_reported(monkeypatch):
    """native session_write_video 报错必须上报，不能吞成假成功。

    回归：旧实现用 contextlib.suppress 吞掉写入异常，会话"看起来成功"，
    但 native 已 overflow 丢弃音频/视频，最终产出残缺文件还报成功。
    """
    fake = FakeNative(available=True)
    two_nals = b"\x00\x00\x01\x65" + b"\xaa" * 8 + b"\x00\x00\x01\x41" + b"\xbb" * 8

    def fake_popen(cmd, **kw):
        return FakeProc([two_nals])

    monkeypatch.setattr(mcs.subprocess, "Popen", fake_popen)

    def boom_write(h, data):
        raise RuntimeError("overflow：队列超过 5s")

    fake.session_write_video = boom_write
    svc = mcs.MFCaptureService(native=fake)
    # 首块写入即报错 → _error 记录 → start 返回失败并带出可读原因，
    # 而不是静默成功。
    ok, reason, firsts = svc.start_all(["s1"], "/tmp", {}, {}, None)
    assert ok is False
    assert "overflow" in reason
    assert firsts == {}


def test_finalize_error_is_reported(monkeypatch):
    """native finalize 报错要转成可读 err，不能返回 paths=[] + err=''。"""
    fake = FakeNative(available=True)

    def fake_popen(cmd, **kw):
        return FakeProc([b"\x00\x00\x01\x65" + b"\xaa" * 8])

    monkeypatch.setattr(mcs.subprocess, "Popen", fake_popen)

    def boom_finalize(h):
        raise RuntimeError("0xC00D4A45 Finalize 失败")

    fake.session_finalize = boom_finalize
    svc = mcs.MFCaptureService(native=fake)
    ok, _, _ = svc.start_all(["s1"], "/tmp", {}, {}, None)
    assert ok is True
    out = svc.stop_all()
    assert out["s1"][0] == []
    assert "Finalize 失败" in out["s1"][1]


def test_tail_nal_written_on_normal_stop(monkeypatch):
    """正常 stop 时缓冲里的最后一帧 NAL 必须写入（不能被 _stop 挡掉）。"""
    fake = FakeNative(available=True)

    def fake_popen(cmd, **kw):
        # 只有一条 NAL：它留在 NalBuffer 里直到 flush()
        return FakeProc([b"\x00\x00\x01\x65" + b"\xaa" * 16])

    monkeypatch.setattr(mcs.subprocess, "Popen", fake_popen)
    svc = mcs.MFCaptureService(native=fake)
    ok, _, _ = svc.start_all(["s1"], "/tmp", {}, {}, None)
    assert ok is True
    sess = svc._sessions["s1"]
    # 等读线程把数据读完、进入 finally 写入尾帧
    sess._read_thread.join(timeout=3)
    writes = [c for c in fake.calls if c[0] == "write_video"]
    assert len(writes) >= 1, "最后一帧 NAL 应在 stop 前经 flush 写入"


# ------------------------- 第四轮审查修复回归 ---------------------------

def test_stderr_does_not_overwrite_real_error(monkeypatch):
    """stderr 退出日志不能覆盖读线程记录的首个真实错误（如 overflow）。

    第三轮修了写入异常要上报；但若 stderr 线程退出时无条件覆盖 _error，
    真实原因仍会被吞掉，用户只看到一句无关的 "screenrecord exited"。
    """
    fake = FakeNative(available=True)
    two_nals = b"\x00\x00\x01\x65" + b"\xaa" * 8 + b"\x00\x00\x01\x41" + b"\xbb" * 8

    class ProcWithStderr(FakeProc):
        def __init__(self, chunks, err_bytes):
            super().__init__(chunks)
            import io
            self.stderr = io.BytesIO(err_bytes)

    def fake_popen(cmd, **kw):
        return ProcWithStderr([two_nals], b"screenrecord: encoder stopped\n")

    monkeypatch.setattr(mcs.subprocess, "Popen", fake_popen)

    def boom_write(h, data):
        raise RuntimeError("overflow：队列超过 5s")

    fake.session_write_video = boom_write
    svc = mcs.MFCaptureService(native=fake)
    ok, reason, _ = svc.start_all(["s1"], "/tmp", {}, {}, None)
    assert ok is False
    assert "overflow" in reason, "真实错误必须保留，不能被 stderr 覆盖"
    assert "encoder stopped" not in reason


def test_normal_stop_does_not_report_stderr_as_error(monkeypatch):
    """正常停止时 stderr 的退出日志不能被误报成收尾错误。

    stop() 会 terminate adb 进程，stderr 线程读到 EOF 后拿到非空 tail；
    旧实现把它写进 _error → controller 弹无关的"收尾提示"warn。
    """
    fake = FakeNative(available=True)

    class ProcWithStderr(FakeProc):
        def __init__(self, chunks, err_bytes):
            super().__init__(chunks)
            import io
            self.stderr = io.BytesIO(err_bytes)

    def fake_popen(cmd, **kw):
        return ProcWithStderr([b"\x00\x00\x01\x65" + b"\xaa" * 16],
                              b"screenrecord: signal 15 (SIGTERM)\n")

    monkeypatch.setattr(mcs.subprocess, "Popen", fake_popen)
    svc = mcs.MFCaptureService(native=fake)
    ok, reason, _ = svc.start_all(["s1"], "/tmp", {}, {}, None)
    assert ok is True
    _, err = svc.stop_all()["s1"]
    assert err == "", f"正常停止不应有错误提示，实际: {err!r}"


def test_mic_start_failure_stops_worker(monkeypatch):
    """mic_start 失败（错误码/异常）必须停掉 worker，不能留常驻 MTA 线程。"""
    fake = FakeNative(available=True)

    def fail_mic(endpoint, rate, bits, channels):
        fake.calls.append(("mic_start", endpoint, rate, bits, channels))
        return 0x80070005  # E_ACCESSDENIED

    fake.mic_start = fail_mic
    svc = mcs.MFCaptureService(native=fake)
    ok, reason, firsts = svc.start_all(["s1"], "/tmp", {}, {}, None)
    assert ok is False
    assert "worker_stop" in [c[0] for c in fake.calls], "失败路径必须停 worker"
    assert fake.worker is None


def test_mic_start_exception_stops_worker(monkeypatch):
    """mic_start 抛异常同样要停 worker + 停麦克风。"""
    fake = FakeNative(available=True)

    def boom(endpoint, rate, bits, channels):
        raise RuntimeError("native 崩溃")

    fake.mic_start = boom
    svc = mcs.MFCaptureService(native=fake)
    ok, reason, firsts = svc.start_all(["s1"], "/tmp", {}, {}, None)
    assert ok is False
    assert "启动麦克风采集失败" in reason
    assert "worker_stop" in [c[0] for c in fake.calls]
