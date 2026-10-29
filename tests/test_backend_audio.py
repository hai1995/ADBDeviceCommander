# -*- coding: utf-8 -*-
"""backend.audio_service.MicRecorder —— 录音资源释放单测。

用假的 WinMM 句柄替身绕过真实的 waveInOpen（不需要声卡、不限 Windows），
只验证 stop() 的释放顺序与失败兜底。
"""
import ctypes
import os
import threading

from core.constants import _WAVEHDR


class _FakeWinMM:
    """WinMM 替身：记录调用序列；可令 waveInUnprepareHeader 抛异常。"""

    def __init__(self, fail_unprepare=False):
        self.calls = []
        self.fail_unprepare = fail_unprepare

    def waveInStop(self, h):
        self.calls.append("stop")

    def waveInReset(self, h):
        self.calls.append("reset")

    def waveInUnprepareHeader(self, h, hdr, n):
        if self.fail_unprepare:
            raise OSError("模拟 unprepare 失败")
        self.calls.append("unprepare")

    def waveInClose(self, h):
        self.calls.append("close")


def _make_recorder(tmp_path, winmm):
    """构造一个「已处于录音中」的 MicRecorder，但不触碰任何真实设备。"""
    import backend.audio_service as au

    mr = au.MicRecorder.__new__(au.MicRecorder)      # 绕过 __init__ 的 _open()
    mr.channels, mr.rate, mr.sample_bits = 2, 44100, 16
    mr._chunks = [b"\x01\x02\x03\x04"]
    mr._collected = set()
    mr._lock = threading.Lock()
    mr._stop = threading.Event()
    mr._running = True
    mr._path = str(tmp_path / "mic.wav")
    mr._winmm = winmm
    mr._wavein = 0x1234
    hdrs = []
    for _ in range(4):
        buf = ctypes.create_string_buffer(16)
        hdr = _WAVEHDR()
        hdr.lpData = ctypes.cast(buf, ctypes.c_void_p)
        hdr.dwBufferLength = 16
        hdrs.append((hdr, buf))
    mr._hdrs = hdrs
    return mr


def test_ctypes_is_available_in_stop_scope(tmp_path):
    """stop() 里要用到 ctypes.byref / ctypes.sizeof。

    回归：早期把 `import ctypes` 写在 MicRecorder._open() 内部，stop() 作用域里
    根本没有这个名字 —— 抛出的 NameError 又被 try/except 吞掉，结果
    waveInUnprepareHeader 从未被调用，音频缓冲区一直泄漏。
    """
    mr = _make_recorder(tmp_path, _FakeWinMM())
    mr.stop()
    # 没抛 NameError 就说明 ctypes 在 stop() 里可用；下面再确认真的 unprepare 了
    assert mr._winmm.calls.count("unprepare") == 4


def test_stop_unprepares_all_headers_then_closes(tmp_path):
    """释放顺序：stop → reset → 逐个 unprepare → close，并写出 WAV。"""
    winmm = _FakeWinMM()
    mr = _make_recorder(tmp_path, winmm)

    assert mr.stop() == mr._path
    assert winmm.calls == ["stop", "reset"] + ["unprepare"] * 4 + ["close"]
    assert mr._running is False
    assert os.path.exists(mr._path), "stop() 应把已录内容写成 WAV"
    with open(mr._path, "rb") as f:
        assert f.read(4) == b"RIFF"


def test_close_still_runs_when_unprepare_fails(tmp_path):
    """单个缓冲区释放失败不能阻断 waveInClose，否则麦克风被进程一直占用。"""
    winmm = _FakeWinMM(fail_unprepare=True)
    mr = _make_recorder(tmp_path, winmm)

    mr.stop()
    assert "stop" in winmm.calls and "reset" in winmm.calls
    assert "close" in winmm.calls, "unprepare 失败也必须走到 waveInClose"
    assert mr._running is False


def test_stop_is_noop_when_not_recording(tmp_path):
    mr = _make_recorder(tmp_path, _FakeWinMM())
    mr._running = False
    assert mr.stop() is None
    assert mr._winmm.calls == []


# ---------------------------------------------------------------------------
# DeviceAudioCapture：停止时必须连设备端 tinycap 一起收尾
# ---------------------------------------------------------------------------
def test_device_audio_stop_kills_device_side_tinycap(monkeypatch):
    """只杀本地 adb 客户端会留下设备端 tinycap 孤儿进程（持续占用音频输入）。"""
    import backend.audio_service as au

    captured = []

    def fake_run(cmd, **kw):
        captured.append(list(cmd))
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(au.subprocess, "run", fake_run)
    cap = au.DeviceAudioCapture("adb")
    cap._procs = {"A1": (object(), "/sdcard/a.wav")}

    cap.stop("A1")
    pkills = [c for c in captured if "pkill" in c]
    assert pkills, "stop() 未对设备端 tinycap 做收尾（会留下孤儿进程）"
    assert "tinycap" in pkills[0]


def _wav_bytes(pcm=b"\x00\x01" * 64, channels=2, rate=44100, bits=16):
    """构造一个**合法**的 PCM WAV（标准 44 字节头 + 真实数据）。

    回归背景：早前的测试样本是 `RIFF + WAVE + 36个0 + data + 长度0`，既没有 fmt 块、
    data 段也是空的 —— 那样的文件恰恰是「播放不了」的坏文件，不该被当作合法样本。
    """
    import struct
    block_align = channels * (bits // 8)
    size = len(pcm)
    return (b"RIFF" + struct.pack("<I", 36 + size) + b"WAVEfmt "
            + struct.pack("<IHHIIHH", 16, 1, channels, rate,
                          rate * block_align, block_align, bits)
            + b"data" + struct.pack("<I", size) + pcm)


def test_wav_ok(tmp_path):
    """_wav_ok 应识别合法 RIFF/WAVE **且含真实音频数据**，拒绝坏文件 / 空音频 / 缺失文件。"""
    import backend.audio_service as au
    good = tmp_path / "g.wav"
    good.write_bytes(_wav_bytes())
    bad = tmp_path / "b.wav"
    bad.write_bytes(b"not a wav at all here")
    empty = tmp_path / "e.wav"
    empty.write_bytes(b"")
    # 只有 44 字节头、data 长度为 0 的「空音频」：最关键的一条回归。
    # 它曾被 _wav_ok 判为可用 → 喂给 ffmpeg → 产出 258 字节 duration=N/A 的空壳 mp4，
    # 用户表现为「合成出来的视频打不开」。
    silent = tmp_path / "silent.wav"
    silent.write_bytes(_wav_bytes(pcm=b""))
    assert au._wav_ok(str(good)) is True
    assert au._wav_ok(str(bad)) is False
    assert au._wav_ok(str(empty)) is False
    assert au._wav_ok(str(silent)) is False, "零长度音频必须判为不可用（否则产出空壳视频）"
    assert au._wav_ok(str(tmp_path / "missing.wav")) is False


def test_ffmpeg_mux_avoids_shortest_truncating_video(monkeypatch, tmp_path):
    """合成**不能**用全局 -shortest：它会按最短流截断，把视频一起砍短。

    回归：6s 视频 + 2s 音频时，旧命令（-shortest + amix duration=shortest）产出
    只有 2s 的成片 —— 用户「录了 1 分钟的视频，成片只剩几秒」。
    """
    import backend.audio_service as au
    monkeypatch.setattr(au, "_have_ffmpeg", lambda: True)
    monkeypatch.setattr(au, "_media_duration", lambda p: "6.0")
    monkeypatch.setattr(au, "_mp4_playable", lambda p: True)
    captured = []

    def fake_run(cmd, **kw):
        captured.append(list(cmd))
        open(cmd[-1], "wb").write(b"fake" * 2048)
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(au.subprocess, "run", fake_run)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake video")
    a1 = tmp_path / "a.wav"
    a1.write_bytes(_wav_bytes())
    out = tmp_path / "out.mp4"
    res = au.ffmpeg_mux(str(video), [str(a1)], str(out))
    assert res == str(out), "应返回合成输出路径"
    cmd = captured[0]
    assert "-shortest" not in cmd, "不得使用 -shortest（会按最短流截断整段输出）"
    amix = [c for c in cmd if c.startswith("amix=")]
    assert amix and ":duration=longest" in amix[0], \
        "amix 应用 duration=longest，再由 -t 按视频时长收尾"
    assert "apad" in amix[0], "音频不足时应 apad 补静音，避免末尾无声冻帧"
    assert cmd[cmd.index("-map") + 1] == "0:v:0", "视频流应直接 copy，不进滤镜图"
    assert "-t" in cmd, "应按视频时长截断，避免音频更长时拖出冻帧尾巴"


def test_ffmpeg_mux_rejects_unplayable_output(monkeypatch, tmp_path):
    """ffmpeg 退出码 0 也可能产出空壳 mp4；必须复核并回退（返回 None + 删除坏文件）。"""
    import backend.audio_service as au
    monkeypatch.setattr(au, "_have_ffmpeg", lambda: True)
    monkeypatch.setattr(au, "_media_duration", lambda p: "6.0")
    monkeypatch.setattr(au, "_mp4_playable", lambda p: False)   # 复核不通过

    def fake_run(cmd, **kw):
        open(cmd[-1], "wb").write(b"tiny")   # 258 字节空壳那种
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(au.subprocess, "run", fake_run)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake video")
    a1 = tmp_path / "a.wav"
    a1.write_bytes(_wav_bytes())
    out = tmp_path / "out.mp4"
    assert au.ffmpeg_mux(str(video), [str(a1)], str(out)) is None
    assert not out.exists(), "坏产物应被删除，不留给用户"


def test_ffmpeg_mux_skips_silent_audio(monkeypatch, tmp_path):
    """空音频应被直接过滤掉：没有可用音频时返回 None，调用方回退「保留无音轨视频」。"""
    import backend.audio_service as au
    monkeypatch.setattr(au, "_have_ffmpeg", lambda: True)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake video")
    silent = tmp_path / "silent.wav"
    silent.write_bytes(_wav_bytes(pcm=b""))
    out = tmp_path / "out.mp4"
    assert au.ffmpeg_mux(str(video), [str(silent)], str(out)) is None
    assert au.ffmpeg_mux(str(video), [], str(out)) is None


# ---------------------------------------------------------------------------
# 视频时长解析：ffprobe 缺失时不能传 `-t 0`（会产出空壳 mp4、音频全丢）
# ---------------------------------------------------------------------------
def _mp4_box(btype: bytes, body: bytes) -> bytes:
    return (8 + len(body)).to_bytes(4, "big") + btype + body


def _mvhd_v0(timescale: int, duration: int) -> bytes:
    """version 0 的 mvhd 盒（version+flags+creation+modification+timescale+duration）。"""
    body = (b"\x00\x00\x00\x00"
            + (0).to_bytes(4, "big") * 2
            + timescale.to_bytes(4, "big")
            + duration.to_bytes(4, "big"))
    return _mp4_box(b"mvhd", body)


def _mvhd_v1(timescale: int, duration: int) -> bytes:
    """version 1 的 mvhd 盒（创建/修改时间为 64 位，时长为 64 位）。"""
    body = (b"\x01\x00\x00\x00"
            + (0).to_bytes(8, "big") * 2
            + timescale.to_bytes(4, "big")
            + duration.to_bytes(8, "big"))
    return _mp4_box(b"mvhd", body)


def test_mp4_duration_parses_moov_at_file_head(tmp_path):
    """moov 在文件头部（ftyp 之后）时应正确解析出时长。"""
    import backend.audio_service as au
    data = (_mp4_box(b"ftyp", b"isom" + b"\x00" * 8)
            + _mp4_box(b"moov", _mvhd_v0(1000, 6000)))
    p = tmp_path / "head.mp4"
    p.write_bytes(data)
    assert au._mp4_duration(str(p)) == "6.000"


def test_mp4_duration_parses_moov_at_file_tail(tmp_path):
    """screenrecord 的 moov 写在文件**尾部**（mdat 之后），也必须能解析。"""
    import backend.audio_service as au
    data = (_mp4_box(b"ftyp", b"isom" + b"\x00" * 8)
            + _mp4_box(b"mdat", b"\x00" * 4096)
            + _mp4_box(b"moov", _mvhd_v1(90000, 270000)))
    p = tmp_path / "tail.mp4"
    p.write_bytes(data)
    assert au._mp4_duration(str(p)) == "3.000"


def test_mp4_duration_returns_none_on_garbage(tmp_path):
    """非 MP4 / 缺 moov / 时长为 0 的文件必须返回 None（绝不抛异常）。"""
    import backend.audio_service as au
    assert au._mp4_duration(str(tmp_path / "missing.mp4")) is None
    p = tmp_path / "no_moov.mp4"
    p.write_bytes(_mp4_box(b"ftyp", b"isom" + b"\x00" * 8) + b"\x00" * 64)
    assert au._mp4_duration(str(p)) is None
    zero = tmp_path / "zero.mp4"
    zero.write_bytes(_mp4_box(b"moov", _mvhd_v0(1000, 0)))
    assert au._mp4_duration(str(zero)) is None


def test_ffmpeg_mux_falls_back_to_header_duration(monkeypatch, tmp_path):
    """ffprobe 取不到时长（只装了 ffmpeg）时，应本地解析 MP4 头拿到时长再合成。"""
    import backend.audio_service as au
    monkeypatch.setattr(au, "_have_ffmpeg", lambda: True)
    monkeypatch.setattr(au, "_media_duration", lambda p: None)   # ffprobe 缺失
    monkeypatch.setattr(au, "_mp4_playable", lambda p: True)
    captured = []

    def fake_run(cmd, **kw):
        captured.append(list(cmd))
        open(cmd[-1], "wb").write(b"fake" * 2048)
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(au.subprocess, "run", fake_run)
    video = tmp_path / "v.mp4"
    video.write_bytes(_mp4_box(b"ftyp", b"isom" + b"\x00" * 8)
                      + _mp4_box(b"moov", _mvhd_v0(1000, 6000)))
    a1 = tmp_path / "a.wav"
    a1.write_bytes(_wav_bytes())
    out = tmp_path / "out.mp4"
    assert au.ffmpeg_mux(str(video), [str(a1)], str(out)) == str(out)
    cmd = captured[0]
    assert cmd[cmd.index("-t") + 1] == "6.000", "应使用本地解析出的视频时长"


def test_ffmpeg_mux_aborts_when_duration_unknown(monkeypatch, tmp_path):
    """时长彻底取不到时**不得**调用 ffmpeg：`-t 0` 会截出空壳、没有 `-t` 则
    apad 无限补静音导致 ffmpeg 永不收尾。应直接返回 None，保留无音轨原视频。"""
    import backend.audio_service as au
    monkeypatch.setattr(au, "_have_ffmpeg", lambda: True)
    monkeypatch.setattr(au, "_media_duration", lambda p: None)
    called = []

    def fake_run(cmd, **kw):
        called.append(list(cmd))
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(au.subprocess, "run", fake_run)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"not an mp4 at all")
    a1 = tmp_path / "a.wav"
    a1.write_bytes(_wav_bytes())
    out = tmp_path / "out.mp4"
    assert au.ffmpeg_mux(str(video), [str(a1)], str(out)) is None
    assert not called, "时长未知时不应调用 ffmpeg（避免空壳产物/挂死）"
    assert not out.exists()


def test_device_audio_stop_uses_int_then_term(monkeypatch, tmp_path):
    """设备端 tinycap 应按 PID/进程 -INT 优先收尾（写回 wav 头），并校验 pull 到的 wav。"""
    import backend.audio_service as au
    WAV = _wav_bytes()
    captured = []

    def fake_run(cmd, **kw):
        captured.append(list(cmd))
        c = cmd
        if c[0] == "adb" and "pull" in c:
            dst = c[-1]
            with open(dst, "wb") as f:
                f.write(WAV)
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(au.subprocess, "run", fake_run)
    cap = au.DeviceAudioCapture("adb")
    cap._procs = {"A1": (object(), "/data/local/tmp/a_audio.wav")}
    local = cap.stop("A1")
    pkills = [c for c in captured if "pkill" in c]
    assert pkills and pkills[0][-2:] == ["-INT", "tinycap"], "应先 pkill -INT tinycap"
    assert local and local.endswith(".wav"), "应返回本地 wav 路径"
    assert au._wav_ok(local), "返回的 wav 应通过校验"


def test_device_audio_stop_discards_empty_wav(monkeypatch, tmp_path):
    """pull 回一个零长度空 wav 时应判为失败（返回 None），不产出播放不了的文件。"""
    import backend.audio_service as au
    EMPTY_WAV = _wav_bytes(pcm=b"")
    monkeypatch.setenv("TEMP", str(tmp_path))

    def fake_run(cmd, **kw):
        if cmd[0] == "adb" and "pull" in cmd:
            with open(cmd[-1], "wb") as f:
                f.write(EMPTY_WAV)
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(au.subprocess, "run", fake_run)
    cap = au.DeviceAudioCapture("adb")
    cap._procs = {"A1": (object(), "/data/local/tmp/a.wav")}
    assert cap.stop("A1") is None, "空 wav 应被丢弃"


def test_device_audio_start_detects_early_exit(monkeypatch):
    """tinycap 启动即退出时必须判为失败。

    回归：start() 只要 Popen 成功就返回 True，而 supported() 只查了
    `command -v tinycap`。可是 tinycap 在很多 ROM 上需要 root，会立刻退出：
    状态栏照样显示「（含设备音频）」，停止时 pull 必然失败，用户最终拿到一段
    没有声音的视频，且完全不知道原因。
    """
    import backend.audio_service as au
    import subprocess as sp

    class _DeadProc:
        def poll(self):
            return 1                     # 立刻已退出
        def terminate(self):
            pass
        def wait(self, timeout=None):
            return 1
        def kill(self):
            pass

    captured = {}

    def fake_popen(cmd, **kw):
        captured["kw"] = kw
        return _DeadProc()

    monkeypatch.setattr(au.subprocess, "Popen", fake_popen)
    cap = au.DeviceAudioCapture("adb")
    assert cap.start("A1", "/data/local/tmp/a.wav") is False, "启动即退出必须报失败"
    assert cap._procs == {}, "失败时不得登记进程（否则停止时会走一遍注定失败的 pull）"
    # 输出必须丢弃而不是挂管道：录制期间没有任何代码读它，写满 64KB 会把采集链路阻塞
    assert captured["kw"].get("stdout") is sp.DEVNULL, "stdout 不能挂管道"
    assert captured["kw"].get("stderr") is sp.DEVNULL, "stderr 不能挂管道"


def test_device_audio_start_registers_live_process(monkeypatch):
    """tinycap 正常存活时 start() 返回 True 并登记进程，stop() 才能收尾。"""
    import backend.audio_service as au

    class _AliveProc:
        def poll(self):
            return None
        def terminate(self):
            pass
        def wait(self, timeout=None):
            return 0
        def kill(self):
            pass

    monkeypatch.setattr(au.subprocess, "Popen", lambda cmd, **kw: _AliveProc())
    monkeypatch.setattr(au.time, "sleep", lambda s: None)     # 跳过 1s 探测等待
    cap = au.DeviceAudioCapture("adb")
    assert cap.start("A1", "/data/local/tmp/a.wav") is True
    assert "A1" in cap._procs
    assert cap.start("A1", "/data/local/tmp/a.wav") is False, "同一设备不得重复启动"
    # is_recording：root 切换保护据此判断「该设备有进行中的采集」
    assert cap.is_recording("A1") is True
    assert cap.is_recording("B2") is False
    cap._procs.pop("A1")
    assert cap.is_recording("A1") is False, "进程被弹出后应视为未在采集"


# ---------------------------------------------------------------------------
# MicRecorder：残余数据排空 / 空录音不产出坏文件
# ---------------------------------------------------------------------------
def test_stop_drains_undelivered_buffer_data(tmp_path):
    """回归：stop() 直接 waveInReset 会丢弃「正填充、尚未回调」的缓冲数据。

    录音刚开始就停止时，整段音频可能全丢 → 写出 44 字节空 wav → 播放不了。
    修复：waveInStop 之后先 _drain_buffers() 排空残余数据，再 reset。
    """
    mr = _make_recorder(tmp_path, _FakeWinMM())
    mr._chunks = []
    mr._collected = set()
    # 第 2 块缓冲区有一份「已录到但回调还没来得及触发」的数据
    hdr, _buf = mr._hdrs[1]
    hdr.dwBytesRecorded = 8
    assert mr.stop() == str(tmp_path / "mic.wav")
    import struct
    raw = (tmp_path / "mic.wav").read_bytes()
    size = struct.unpack("<I", raw[40:44])[0]
    assert size == 8, "reset 前的残余数据应被写入 wav，否则录音整段丢失"


def test_stop_does_not_duplicate_collected_buffers(tmp_path):
    """同一块数据若已由 WIM_DATA 回调收集，_drain_buffers 不得重复叠加（否则重影/音量翻倍）。"""
    mr = _make_recorder(tmp_path, _FakeWinMM())
    # 回调已收集的缓冲区 + 一份**未**收集的残余数据：后者应被写入
    mr._chunks = []
    hdr0, _b0 = mr._hdrs[0]
    hdr0.dwBytesRecorded = 8
    mr._collected = {int(hdr0.lpData)}
    hdr1, _b1 = mr._hdrs[1]
    hdr1.dwBytesRecorded = 4
    assert mr.stop() == str(tmp_path / "mic.wav")
    import struct
    raw = (tmp_path / "mic.wav").read_bytes()
    size = struct.unpack("<I", raw[40:44])[0]
    assert size == 4, "只应写入未收集过的缓冲区（4B）；重复叠加会变成 12B 且音频重影"


def test_stop_discards_empty_recording(tmp_path):
    """没录到任何声音时返回 None 且不留坏文件（44 字节空 wav 播放不了）。"""
    mr = _make_recorder(tmp_path, _FakeWinMM())
    mr._chunks = []
    mr._collected = set()
    for hdr, _buf in mr._hdrs:
        hdr.dwBytesRecorded = 0
    assert mr.stop() is None
    assert not (tmp_path / "mic.wav").exists(), "空录音不应留下文件"



def test_wav_without_fmt_chunk_is_rejected(tmp_path):
    """RIFF/WAVE + data 但**缺 fmt 块**：不是可解码的 PCM，必须判不可用。

    回归：`_wav_duration` 里有一个 `fmt_seen` 标志，赋了值却从没读过 ——
    也就是「见到 data 就往回返」，缺 fmt 的坏文件同样被当成合法音频。
    """
    import backend.audio_service as au
    import struct

    pcm = b"\x00\x01" * 64
    broken = tmp_path / "nofmt.wav"
    broken.write_bytes(b"RIFF" + struct.pack("<I", 4 + 8 + len(pcm)) + b"WAVE"
                       + b"data" + struct.pack("<I", len(pcm)) + pcm)

    assert au._wav_duration(str(broken)) is None
    assert au._wav_ok(str(broken)) is False


def test_wav_with_fmt_still_accepted(tmp_path):
    """补上 fmt 校验后，正常文件不受影响。"""
    import backend.audio_service as au
    good = tmp_path / "g.wav"
    good.write_bytes(_wav_bytes())
    assert au._wav_duration(str(good)) == len(b"\x00\x01" * 64)
    assert au._wav_ok(str(good)) is True
