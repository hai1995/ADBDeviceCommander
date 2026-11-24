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

    def session_drain_audio(self, h):
        self.calls.append(("drain_audio", h))

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


# ------------------------- build_id 构建指纹 ----------------------------

def test_build_id_returns_empty_when_unavailable():
    """DLL 不可用时构建指纹为空，绝不抛异常。"""
    n = mn.MFNative()
    assert n.available is False
    assert n.build_id() == ""


def test_build_id_reads_stamp_from_lib():
    """新 DLL：从 adc_build_id() 读到构建指纹。"""
    n = mn.MFNative()
    n._lib = type("Lib", (), {
        "adc_build_id": staticmethod(lambda: b"mf-20261123-esdsdiag-v4"),
    })()
    assert n.build_id() == "mf-20261123-esdsdiag-v4"


def test_build_id_tolerates_old_dll_without_symbol():
    """老 DLL 没有 adc_build_id 导出：build_id 返回空串，不能 AttributeError。"""
    n = mn.MFNative()
    n._lib = object()  # 无任何 adc_build_id 属性
    assert n.build_id() == ""


def test_build_id_tolerates_stamp_exception():
    """adc_build_id 调用异常时降级为空串，诊断信息不影响主流程。"""
    n = mn.MFNative()

    def boom():
        raise RuntimeError("导出调用失败")

    n._lib = type("Lib", (), {"adc_build_id": staticmethod(boom)})()
    assert n.build_id() == ""


def test_service_build_id_passthrough():
    """MFCaptureService.build_id 透传 native 指纹；替身无接口时降级为空。"""
    class WithStamp:
        def build_id(self):
            return "mf-v4"

    class WithoutStamp:
        pass

    svc = mcs.MFCaptureService(native=WithStamp())
    assert svc.build_id == "mf-v4"
    svc2 = mcs.MFCaptureService(native=WithoutStamp())
    assert svc2.build_id == ""


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


def test_unsupported_aac_sample_rate_rejected():
    """96000Hz 等 AAC 不支持的采样率必须启动前拒绝，避免 Finalize 0xC00D4A45。"""
    fake = FakeNative(available=True)
    fake.mic = (96000, 16, 2)
    svc = mcs.MFCaptureService(native=fake)
    ok, reason, firsts = svc.start_all(["s1"], "/tmp", {}, {}, None)
    assert ok is False
    assert "AAC 编码器支持范围" in reason
    assert not any(c[0] == "session_create" for c in fake.calls)
    assert any(c[0] == "mic_stop" for c in fake.calls)


def test_unsupported_aac_channels_rejected():
    """非 1/2/6 声道必须启动前拒绝（AAC MFT 不支持，会导致音频流 0 sample）。"""
    fake = FakeNative(available=True)
    fake.mic = (48000, 16, 4)
    svc = mcs.MFCaptureService(native=fake)
    ok, reason, firsts = svc.start_all(["s1"], "/tmp", {}, {}, None)
    assert ok is False
    assert "AAC 编码器支持范围" in reason
    assert not any(c[0] == "session_create" for c in fake.calls)


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


# ------------------------- 第五轮：音频排空定时器（真机 overflow 修复） ------
def test_audio_drain_timer_runs_independent_of_video(monkeypatch):
    """音频排空定时器独立于视频帧周期运行。

    真机故障：视频流稀疏（1min+ 只有几十KB）→ write_video 几乎不被调用 →
    音频队列无人排空 → 5s overflow → finalize 失败 → 不可播放的 .tmp.mp4。
    修复后定时器每 200ms 主动 drain，即使视频帧不来音频也持续写入。
    """
    import time as _t
    fake = FakeNative(available=True)

    def fake_popen(cmd, **kw):
        # 一段 H264 后 stdout 立即 EOF：模拟视频流很快中断，write_video 只 1 次。
        return FakeProc([b"\x00\x00\x00\x01\x65" + b"\xaa" * 16])

    monkeypatch.setattr(mcs.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(mcs, "AUDIO_DRAIN_INTERVAL_S", 0.01)
    svc = mcs.MFCaptureService(native=fake)
    ok, reason, _ = svc.start_all(["s1"], "/tmp", {}, {}, None)
    assert ok is True, reason
    # 视频读线程早已 EOF，但定时器应持续 drain（≥2 次说明周期运行）。
    _t.sleep(0.08)
    drains = [c for c in fake.calls if c[0] == "drain_audio"]
    assert len(drains) >= 2, f"音频排空定时器应独立于视频帧运行，实际 drain {len(drains)} 次"
    svc.stop_all()


def test_audio_drain_timer_stops_on_cancel(monkeypatch):
    """取消后定时器必须停止，不能再往已 discard 的 writer 写音频。"""
    import time as _t
    fake = FakeNative(available=True)

    def fake_popen(cmd, **kw):
        return FakeProc([b"\x00\x00\x00\x01\x65" + b"\xaa" * 16])

    monkeypatch.setattr(mcs.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(mcs, "AUDIO_DRAIN_INTERVAL_S", 0.01)
    svc = mcs.MFCaptureService(native=fake)
    ok, reason, _ = svc.start_all(["s1"], "/tmp", {}, {}, None)
    assert ok is True, reason
    svc.cancel_all()  # 内部会 _stop_drain + discard
    before = len([c for c in fake.calls if c[0] == "drain_audio"])
    _t.sleep(0.08)
    after = len([c for c in fake.calls if c[0] == "drain_audio"])
    assert after == before, f"取消后不应再有 drain 调用（{before} -> {after}）"


def test_sparse_h264_uses_read1_not_read(monkeypatch):
    """回归：车机静止画面 H264 输出极慢时，read(64KB) 会阻塞到攒满才返回，
    6s 首帧判定内一个字节都拿不到 → 误报「screenrecord 未在 6s 内输出 H264
    数据（退出码 None）」，而进程其实还活着、数据只是被憋在管道缓冲里。
    必须用 read1 有多少读多少，首字节到达即置位 _first_data。投屏路径
    mirror_service._feed_loop 同样用 read1，这里锁死该行为防回归。"""
    import io as _io

    fake = FakeNative(available=True)
    sc = b"\x00\x00\x00\x01"
    data = sc + b"\x67SPS" + sc + b"\x68PPS" + sc + b"\x65IDR" + b"\xaa" * 32

    class TrickleStdout(_io.BytesIO):
        def read(self, n=-1):
            # 真实管道下 read(n) 要凑满 n；这里直接失败，让「改回 read」的
            # 回归立刻可断言，而不是让测试线程挂满 6s。
            raise AssertionError(
                "必须用 read1：稀疏 H264 下 read() 会阻塞过首帧超时")

        def read1(self, n=-1):
            return super().read(min(n, 7))  # 每次仅吐 7 字节，模拟极低码率

    class TrickleProc(FakeProc):
        def __init__(self):
            super().__init__([data])
            self.stdout = TrickleStdout(data)

    monkeypatch.setattr(mcs.subprocess, "Popen", lambda cmd, **kw: TrickleProc())
    monkeypatch.setattr(mcs, "FIRST_DATA_TIMEOUT_S", 1.0)  # 回归时快速失败
    sess = mcs.MFCaptureSession(fake, "s1", "/tmp", "rec", 1920, 1080)
    ok, err = sess.start()
    assert ok is True, err
    assert sess._first_data.is_set() is True
    sess.cancel()


# ------------------------- MFWorker 生命周期 -----------------------------

class _BlockingLib:
    """native 替身：adc_init 成功；提供一个可阻塞的函数验证悬挂修复。"""

    def __init__(self):
        import threading as _th
        self._gate = _th.Event()
        self.release = _th.Event()

    def adc_init(self):
        return 0  # ADC_OK

    def adc_shutdown(self):
        pass

    def adc_last_error(self, buf, n):
        pass

    def block_forever(self):
        self._gate.set()
        self.release.wait(3)
        return 99


def test_worker_call_timeout_raises_instead_of_hanging():
    """worker 执行的 fn 卡住时，call 必须超时抛错，不能无限期挂住界面线程。"""
    lib = _BlockingLib()
    w = mn.MFWorker(lib)
    w.start()
    import threading as _th
    result = {}
    th = _th.Thread(target=lambda: result.setdefault(
        "exc", _call_and_catch(w, lib.block_forever, timeout=0.3)))
    th.start()
    assert lib._gate.wait(2), "fn 应已开始执行"
    th.join(3)
    assert not th.is_alive(), "call 必须超时返回，不能悬挂"
    assert isinstance(result.get("exc"), mn.MFNativeError)
    assert "超时" in str(result["exc"])
    lib.release.set()
    w.stop()


def test_cancelable_timeout_skips_zombie_task():
    """[收尾慢回归·v17] cancelable 调用超时后，僵尸 task 不得在 worker 中执行。

    根因：旧 call() 超时只让调用方抛错，task 仍留在队列被 worker 执行。长录制
    下 drain 每 200ms 一次、频繁超时，每次超时都堆一个僵尸 drain 占住 worker，
    堆积后收尾的 finalize 排到队尾 → 收尾超 1 分钟。修复：cancelable=True 的
    调用超时后打 cancelled 标记，worker 出队时跳过。这里用阻塞 fn 占住 worker，
    排队一个 cancelable 调用使其超时，放行后断言它从未真正执行。
    """
    import threading as _th

    lib = _BlockingLib()
    w = mn.MFWorker(lib)
    w.start()
    lib._gate.clear()
    blocker = _th.Thread(target=lambda: _call_and_catch(w, lib.block_forever, timeout=5))
    blocker.start()
    assert lib._gate.wait(2), "blocker 应已占用 worker"

    executed = []
    def would_be_zombie():
        executed.append(1)
        return 1

    # 排队一个 cancelable 调用，超时（0.3s）后被标记跳过
    result = {}
    zt = _th.Thread(target=lambda: result.setdefault(
        "exc", _call_and_catch_cancelable(w, would_be_zombie, 0.3)))
    zt.start()
    zt.join(1.5)
    assert isinstance(result.get("exc"), mn.MFNativeError), "cancelable 超时也应抛错"
    lib.release.set()                     # 放行 blocker，worker 继续消费队列
    blocker.join(3)
    import time as _t
    _t.sleep(0.2)                         # 给 worker 时间跑到那个被标记的 task
    assert not executed, "超时 cancelable task 不得被执行（僵尸应被跳过）"
    w.stop()


def _call_and_catch_cancelable(worker, fn, timeout):
    try:
        worker.call(fn, timeout=timeout, cancelable=True)
    except Exception as e:  # noqa: BLE001
        return e
    return None


def _call_and_catch(worker, fn, timeout):
    try:
        worker.call(fn, timeout=timeout)
    except Exception as e:  # noqa: BLE001  测试里收集异常
        return e
    return None


def test_worker_stop_drains_queued_calls():
    """stop 时队列里排队的 call 必须被回写错误并唤醒，否则 caller 永久挂起。"""
    import threading as _th

    lib = _BlockingLib()
    w = mn.MFWorker(lib)
    w.start()
    lib._gate.clear()
    # 第一个 call 卡住 worker；第二个 call 排队
    blocker = _th.Thread(target=lambda: _call_and_catch(w, lib.block_forever, timeout=5))
    blocker.start()
    assert lib._gate.wait(2), "blocker 应已占用 worker"

    queued_result = {}
    queued = _th.Thread(target=lambda: queued_result.setdefault(
        "exc", _call_and_catch(w, lambda: 123, timeout=3)))
    queued.start()
    _th.Event().wait(0.1)                 # 让第二个 call 确实排进队列

    lib.release.set()                     # 放行第一个 call，worker 继续消费队列
    w.stop()                              # 停 worker（哨兵在排队调用之后）

    blocker.join(3)
    queued.join(3)
    assert not queued.is_alive(), "排队的 call 不能被悬挂"
    # 哨兵在排队 call 之后入队：FIFO 保证它先被正常执行，stop 不丢弃在途调用。
    assert queued_result.get("exc") is None, "排队的 call 应被正常执行而非被丢弃"


# ---------------- 第六轮：分级超时 + 排空容错（收尾慢修复） --------------
def test_graded_call_timeouts():
    """[收尾慢回归·v14/v17] drain 用中等超时、finalize 用长超时，不能都是 15s 默认值。

    v14 曾把 drain 压到 5s，真机 3 分钟长录制实证太激进：worker 被海量 write_video
    占满时 drain 排队 >5s 是常态，被误判超时堆积僵尸。v17 放宽到 10s，并要求
    cancelable=True（超时 task 可撤销、不留僵尸）。finalize 含编码器 flush，长录制
    本就慢，给足 60s 避免误报"合成失败"。
    """
    assert mn.DRAIN_CALL_TIMEOUT_S < mn.FINALIZE_CALL_TIMEOUT_S
    assert 8 <= mn.DRAIN_CALL_TIMEOUT_S <= 15, "drain 超时过短会误报、过长会拖慢发现卡死"
    assert mn.FINALIZE_CALL_TIMEOUT_S >= 30, "finalize 要给编码器 flush 留足时间"
    # 便捷方法必须真的把常量传给 call（防止定义了却没用）
    import inspect
    drain_src = inspect.getsource(mn.MFNative.session_drain_audio)
    fin_src = inspect.getsource(mn.MFNative.session_finalize)
    assert "DRAIN_CALL_TIMEOUT_S" in drain_src
    assert "FINALIZE_CALL_TIMEOUT_S" in fin_src
    # v17 关键：drain 必须 cancelable，超时不留僵尸拖垮收尾
    assert "cancelable=True" in drain_src


def test_drain_loop_survives_transient_timeout(monkeypatch):
    """[排空超时回归·v14] 单次 drain 超时不能永久停掉排空。

    旧实现一次异常就 break：高负载下偶发一次超时，剩余整段录制音频队列无人排空
    → overflow/音频丢失。修复为连续失败计数，成功即清零；这里用替身让前 2 次
    drain 抛超时、第 3 次恢复，断言后续仍持续 drain 且未记错误。
    """
    import time as _t
    fake = FakeNative(available=True)
    state = {"n": 0}

    orig_drain = fake.session_drain_audio

    def flaky_drain(h):
        state["n"] += 1
        if state["n"] in (1, 2):
            raise mn.MFNativeError("MF worker 调用超时（5s 未返回）")
        return orig_drain(h)

    fake.session_drain_audio = flaky_drain
    monkeypatch.setattr(mcs.subprocess, "Popen",
                        lambda cmd, **kw: FakeProc([b"\x00\x00\x00\x01\x65" + b"\xaa" * 16]))
    monkeypatch.setattr(mcs, "AUDIO_DRAIN_INTERVAL_S", 0.01)

    svc = mcs.MFCaptureService(native=fake)
    ok, reason, _ = svc.start_all(["s1"], "/tmp", {}, {}, None)
    assert ok is True, reason
    _t.sleep(0.12)
    # 经历 2 次超时后仍继续 drain（成功清零），不会被永久停掉
    drains = state["n"]
    assert drains > 2, f"偶发超时后应继续排空，实际调用 {drains} 次"
    # v17：任何次数的 drain 超时都不写入 _error（收尾不得误报失败）
    sess = svc._sessions["s1"]
    assert "排空失败" not in sess._error, f"drain 超时不应上报致命错误：{sess._error}"
    svc.stop_all()


def test_drain_loop_never_stops_on_persistent_timeout(monkeypatch):
    """[排空容错·v17] 即使持续超时也不永久停排空、不记致命错误。

    v14 旧行为：连续 3 次超时 → break + 记 _error → 剩余录制音频无人排空
    （native 队列 overflow 丢失）且收尾误报失败。真机 3 分钟长录制触发此路径。
    v17：超时只丢本轮、下个 tick 继续；_error 始终为空；连续失败数只进 stats
    作诊断。真正失败由 finalize 裁决（worker 真死时 finalize 自身会超时上报）。
    """
    import time as _t
    fake = FakeNative(available=True)
    state = {"n": 0}

    def always_fail(h):
        state["n"] += 1
        raise mn.MFNativeError("MF worker 调用超时（10s 未返回）")

    fake.session_drain_audio = always_fail
    monkeypatch.setattr(mcs.subprocess, "Popen",
                        lambda cmd, **kw: FakeProc([b"\x00\x00\x00\x01\x65" + b"\xaa" * 16]))
    monkeypatch.setattr(mcs, "AUDIO_DRAIN_INTERVAL_S", 0.01)

    svc = mcs.MFCaptureService(native=fake)
    ok, reason, _ = svc.start_all(["s1"], "/tmp", {}, {}, None)
    assert ok is True, reason
    _t.sleep(0.15)
    sess = svc._sessions["s1"]
    # 持续失败也不写 _error（收尾不得报"排空失败"）
    assert "排空失败" not in sess._error, "持续 drain 超时不应上报致命错误"
    first = state["n"]
    assert first >= 3, f"应已多次尝试排空，实际 {first} 次"
    # 关键：不停止——后续仍在持续排空（不再 break 空转停止）
    _t.sleep(0.08)
    assert state["n"] > first, "持续超时也必须继续尝试排空，不得永久停止"
    # 连续失败数进 stats 供诊断
    assert sess._stats.get("drain_fail_streak", 0) >= 3
    svc.stop_all()


# ---------------- 第七轮：worker 僵尸 task 清理（长录制收尾慢·v17） --------------
def _code_without_docstring(fn):
    """取函数源码，剥离 docstring 与注释，只留可执行代码行（供源码守卫断言）。"""
    import ast as _ast
    import inspect as _inspect
    import textwrap as _tw
    src = _tw.dedent(_inspect.getsource(fn))
    tree = _ast.parse(src)
    body = tree.body[0].body
    lines = src.splitlines()
    skip_to = 0
    if (body and isinstance(body[0], _ast.Expr)
            and isinstance(getattr(body[0], "value", None), _ast.Constant)
            and isinstance(body[0].value.value, str)):
        skip_to = body[0].end_lineno
    code_lines = []
    for ln in lines[skip_to:]:
        code = ln.split("#")[0].strip()
        if code:
            code_lines.append(code)
    return "\n".join(code_lines)


def test_worker_loop_skips_cancelled_tasks():
    """[收尾慢根因回归·v17] worker 出队必须跳过 cancelled task（僵尸回收）。

    MFWorker.call(cancelable=True) 超时后只打标记，真正"不执行僵尸"依赖 worker
    _loop 出队时检查 done['cancelled']。缺了这段，超时 drain 仍会在 worker 被执行、
    堆积拖垮 finalize——这是 3 分钟录制收尾超 1 分钟的根因。
    """
    loop_src = _code_without_docstring(mn.MFWorker._loop)
    assert 'done.get("cancelled")' in loop_src, "worker 出队须检查 cancelled 标记"
    assert "continue" in loop_src, "cancelled task 须跳过执行"


def test_call_supports_cancelable_keyword():
    """[收尾慢根因回归·v17] call() 必须支持 cancelable 并在超时时打标。"""
    call_src = _code_without_docstring(mn.MFWorker.call)
    assert "cancelable" in call_src, "call 须支持 cancelable 参数"
    assert 'done["cancelled"] = True' in call_src, "超时时须给 task 打 cancelled 标记"


def test_drain_loop_never_records_fatal_error():
    """[收尾慢根因回归·v17] drain 循环不得再写 _error 或永久 break。

    真机 3 分钟录制因 drain 超时写 _error 而误报"音频排空失败"（文件其实已保存）。
    收尾失败只应由 finalize 裁决。源码中不得出现旧的 break + _error 赋值。
    """
    loop_src = _code_without_docstring(mcs.MFCaptureSession._drain_loop)
    # 不得把 drain 超时写入致命错误通道
    assert "音频排空失败" not in loop_src, "drain 超时不得写入 _error 误报收尾失败"
    assert "self._error" not in loop_src, "drain 循环不得触碰 _error"
    # 不得再因失败计数 break（旧 DRAIN_FAIL_STREAK_LIMIT 逻辑已废除）
    assert "DRAIN_FAIL_STREAK_LIMIT" not in loop_src
    assert "break" not in loop_src, "drain 超时不得永久停止排空"


def test_write_video_has_independent_timeout():
    """[收尾慢根因回归·v18] write_video 须用独立放宽的超时，不走默认 15s。

    真机 v17 包仍报"写入 H264 流失败：MF worker 调用超时（15s 未返回）"，超时
    点已从 drain 转移到 write_video 本身。兜底修复须定义专用常量并在调用中传入。
    """
    assert hasattr(mn, "VIDEO_WRITE_CALL_TIMEOUT_S"), "须定义 write_video 专用超时常量"
    assert mn.VIDEO_WRITE_CALL_TIMEOUT_S == 30.0, "write_video 超时应放宽到 30s"
    src = _code_without_docstring(mn.MFNative.session_write_video)
    assert "timeout=VIDEO_WRITE_CALL_TIMEOUT_S" in src, (
        "session_write_video 须传入专用超时，不再用默认 15s")


def test_rotate_signal_and_independent_call():
    """[收尾慢根治回归·v20] write_video 透传切段信号 + session_rotate 独立长超时。"""
    assert mn.ADC_ROTATE_PENDING == 1, "须定义切段请求返回码"
    assert mn.ROTATE_CALL_TIMEOUT_S == 120.0, "切段重量操作须有独立长超时"
    # session_write_video 必须把 PENDING 信号透传为 True，而非当成错误抛出
    wv = _code_without_docstring(mn.MFNative.session_write_video)
    assert "rc == ADC_ROTATE_PENDING" in wv, "须识别切段请求返回码"
    assert "return True" in wv, "须透传切段请求给调用方"
    # session_rotate 存在、可选符号容错、用独立超时
    assert hasattr(mn.MFNative, "session_rotate"), "须提供 session_rotate"
    rot = _code_without_docstring(mn.MFNative.session_rotate)
    assert 'getattr(self._lib, "adc_session_rotate", None)' in rot, "老 DLL 缺符号须 no-op"
    assert "timeout=ROTATE_CALL_TIMEOUT_S" in rot, "切段须用独立长超时"
    # 符号绑定须为可选（缺符号不判定 DLL 不可用）
    bind = mn.MFNative._bind_signatures
    import inspect
    bind_src = inspect.getsource(bind)
    assert 'getattr(lib, "adc_session_rotate", None)' in bind_src, "符号绑定须可选"


def test_read_loop_drives_rotate_on_signal():
    """[收尾慢根治回归·v20] _read_loop 收到切段信号须显式调 session_rotate。"""
    loop = _code_without_docstring(mcs.MFCaptureSession._read_loop)
    assert "need_rotate = self.native.session_write_video" in loop, "须接收 write_video 返回信号"
    assert "if need_rotate:" in loop, "须判断切段请求"
    assert "self.native.session_rotate(self._handle)" in loop, "须显式驱动重量切段"
    assert '"rotations"' in loop, "须统计切段次数供诊断"


def test_write_video_timeout_is_not_fatal():
    """[长录制收尾根治回归·v21] write_video 调用超时不得当致命错误终止录制。

    真机 v20：长录制跨切段后报"写入 H264 流失败：MF worker 调用超时（30s）"。
    根因是单 worker 被重量 rotate/finalize 挤占，write_video 排队超时；该 task
    非 cancelable、最终仍会执行、数据不丢。旧实现把超时当致命错误 → 提前终止、
    误报失败（超时点 v17~v20 反复转移）。真 native 错误(overflow 等)仍须上报。
    """
    loop = _code_without_docstring(mcs.MFCaptureSession._read_loop)
    assert '"MF worker 调用超时" in str(ex)' in loop, (
        "须把 worker 调用超时与真 native 错误区分开")
    assert "write_timeout_streak" in loop, "超时须记入诊断统计"
    # 超时分支不得再写 _error / set _stop / break（这些只在 else 的真错误分支）
    timeout_branch = loop[loop.index('if "MF worker 调用超时" in str(ex)'):
                          loop.index("else:")]
    assert "self._error" not in timeout_branch, "超时分支不得写 _error 误报失败"
    assert "self._stop.set()" not in timeout_branch, "超时分支不得终止录制"
    assert "break" not in timeout_branch, "超时分支不得跳出读取循环"


def test_stop_waits_for_read_thread_done():
    """[长录制收尾根治回归·v21] stop 须等读线程真正退出后才 finalize。

    旧实现 _join_threads 对读线程只 join 6s；切段时读线程正阻塞在 120s 的
    session_rotate，6s 后 stop 就投递 finalize，迟到的尾刷 write_video 排在
    finalize 后顶过 30s。修复：读线程在 finally 置 _read_done，_join_threads
    等该信号（预算覆盖 rotate），保证 write_video 排在 finalize 之前。
    """
    import inspect
    init_src = inspect.getsource(mcs.MFCaptureSession.__init__)
    assert "self._read_done = threading.Event()" in init_src, "须有读线程完成信号"
    loop = _code_without_docstring(mcs.MFCaptureSession._read_loop)
    assert "self._read_done.set()" in loop, "读线程 finally 须置完成信号"
    join_src = inspect.getsource(mcs.MFCaptureSession._join_threads)
    assert "self._read_done.wait(" in join_src, "_join_threads 须等读线程完成信号"
    assert "READ_DONE_BUDGET_S" in join_src, "等待须用覆盖 rotate 的预算"
    assert mcs.READ_DONE_BUDGET_S >= 120.0, (
        "等待预算须覆盖一次最坏 session_rotate(120s)")
