# -*- coding: utf-8 -*-
"""backend.mirror_service —— 没装 scrcpy 时的备用投屏单测。

与 scrcpy 测试同一套思路：**不要求本机真装播放器、也不连真机**。
  * 探测（find_player / probe_player）用临时目录造假执行文件，验证查找顺序；
  * 进程链路（PipeMirror / SnapMirror）用 Popen 替身拦截，只验证语义：
    命令参数对不对、首帧判定、无数据时报错、180s 续流、收尾清理；
  * 帧服务（FrameServer）是真的起在本机回环端口上跑一次 HTTP 请求 —— 它
    是纯标准库、无外部依赖，值得真验一次「前端 <img> 真能拉到 PNG」。
"""
import os
import urllib.request

import pytest

import backend.mirror_service as svc


def _fake_exe(dir_path, kind="ffplay"):
    """在目录里造一个「假播放器」可执行文件（名字必须能被探测认出来）。"""
    name = kind + (".exe" if os.name == "nt" else "")
    p = dir_path / name
    p.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------- 探测


def test_find_prefers_configured_dir(tmp_path):
    """配置项填目录时，在目录里找到哪个就用哪个。"""
    exe = _fake_exe(tmp_path, "mpv")
    _kind, found, note = svc.find_player(str(tmp_path))
    assert found == exe
    assert "配置" in note


def test_find_accepts_exe_full_path_and_guesses_kind(tmp_path):
    """填 exe 全路径时，要从文件名认出播放器类型 —— 不同播放器参数完全不同，
    认错了就是「窗口起来了但没画面」。"""
    exe = _fake_exe(tmp_path, "mpv")
    kind, found, _ = svc.find_player(exe)
    assert found == exe and kind == "mpv"


def test_find_invalid_config_falls_back_and_explains(monkeypatch, tmp_path):
    """配置了个不存在的路径：继续自动探测，但必须说明「配置无效」——
    否则用户以为填了却没生效。"""
    monkeypatch.setattr(svc, "_player_extra_dirs", lambda: [])
    monkeypatch.setattr(svc.shutil, "which", lambda name: None)
    kind, found, note = svc.find_player(str(tmp_path / "nope"))
    assert found is None and kind == ""
    assert "配置的播放器路径无效" in note
    assert "winget" in note and "brew" in note      # 三平台都给可执行的建议


def test_find_order_prefers_ffplay(monkeypatch, tmp_path):
    """PATH 里同时有 mpv 与 ffplay 时应选 ffplay（延迟表现最好）。"""
    mpv = _fake_exe(tmp_path, "mpv")
    ff = str(tmp_path / "ffplay-only")
    monkeypatch.setattr(svc, "_player_extra_dirs", lambda: [])
    monkeypatch.setattr(svc.shutil, "which",
                        lambda name: mpv if name == "mpv" else
                        (ff if name == "ffplay" else None))
    kind, found, _ = svc.find_player("")
    assert kind == "ffplay" and found == ff


def test_find_scans_extra_dirs(monkeypatch, tmp_path):
    d = tmp_path / "ffmpeg-bin"
    d.mkdir()
    exe = _fake_exe(d, "ffplay")
    monkeypatch.setattr(svc.shutil, "which", lambda name: None)
    monkeypatch.setattr(svc, "_player_extra_dirs", lambda: [str(d)])
    kind, found, note = svc.find_player("")
    assert found == exe and kind == "ffplay"
    assert "常见安装目录" in note


def test_probe_player_returns_kind_and_path(tmp_path):
    exe = _fake_exe(tmp_path, "mpv")
    info = svc.probe_player(exe)
    assert info["ok"] is True and info["kind"] == "mpv" and info["path"] == exe


def test_probe_player_missing_is_not_exception(monkeypatch):
    monkeypatch.setattr(svc, "find_player", lambda pref: ("", "", "未找到播放器"))
    info = svc.probe_player("")
    assert info["ok"] is False and info["note"] == "未找到播放器"


def test_player_args_use_stdin():
    """四种播放器都必须以 `-` 结尾（从 stdin 读裸流），否则管道投屏无从谈起。"""
    for kind in svc.PLAYER_ORDER:
        args = svc._player_args(kind)
        assert args and args[-1] == "-", kind


# ---------------------------------------------------------------- 分辨率


def test_plan_size_scales_long_edge(monkeypatch):
    """2340 长边缩到 1080，且宽高取偶数（H.264 编码器对奇数宽高支持不一）。"""
    monkeypatch.setattr(svc, "device_size", lambda adb, serial: (1080, 2340))
    got = svc.plan_size("adb", "S")
    w, h = (int(x) for x in got.split("x"))
    assert max(w, h) == 1080
    assert w % 2 == 0 and h % 2 == 0


def test_plan_size_keeps_already_small_device(monkeypatch):
    """长边本来就没超标的设备原样返回，不做无谓缩放（缩放只会更糊）。"""
    monkeypatch.setattr(svc, "device_size", lambda adb, serial: (720, 1080))
    assert svc.plan_size("adb", "S") == "720x1080"


def test_plan_size_unknown_returns_empty(monkeypatch):
    """读不到分辨率就别传 --size：让 screenrecord 用设备默认值最稳。"""
    monkeypatch.setattr(svc, "device_size", lambda adb, serial: (0, 0))
    assert svc.plan_size("adb", "S") == ""


# ---------------------------------------------------------------- 命令构造


def test_adb_cmd_has_h264_and_stdin():
    m = svc.PipeMirror("adb", "S1", "ffplay", "/bin/ffplay")
    cmd = m._adb_cmd()
    assert "exec-out" in cmd and "screenrecord" in cmd
    assert "--output-format=h264" in cmd
    assert cmd[-1] == "-"


def test_adb_cmd_bit_rate_is_bps_not_mbps():
    """--bit-rate 的单位是 bps：把 8（Mbps）直接传过去等于 8bps，画面必糊。"""
    m = svc.PipeMirror("adb", "S1", "ffplay", "/bin/ffplay", bitrate_mbps=8)
    i = m._adb_cmd().index("--bit-rate")
    assert m._adb_cmd()[i + 1] == "8000000"


def test_adb_cmd_omits_size_when_unset():
    m = svc.PipeMirror("adb", "S1", "ffplay", "/bin/ffplay", size="")
    assert "--size" not in m._adb_cmd()


# ---------------------------------------------------------------- 进程替身


class _FakeStream:
    """stdout / stderr 替身：read1 按序吐块，吐完返回 b''（= EOF）。"""

    def __init__(self, chunks=()):
        self._chunks = list(chunks)

    def read1(self, n=-1):
        return self._chunks.pop(0) if self._chunks else b""

    def read(self, n=-1):
        return b"".join(self._chunks) if self._chunks else b""

    def close(self):
        pass


class _FakeStdin:
    def __init__(self):
        self.written = 0

    def write(self, b):
        self.written += len(b)

    def flush(self):
        pass


class _FakeProc:
    def __init__(self, out=(), err=b""):
        self.stdout = _FakeStream(out)
        self.stderr = _FakeStream([err] if err else [])
        self.stdin = _FakeStdin()
        self.returncode = 0
        self.killed = False
        self.terminated = False

    def poll(self):
        return None

    def wait(self, timeout=None):
        return 0

    def communicate(self, timeout=None):
        """低帧率预览走的是 communicate()（一次性取回整帧 PNG）。"""
        return self.stdout.read(), b""

    def kill(self):
        self.killed = True

    def terminate(self):
        self.terminated = True


class _PopenFactory:
    """按命令区分「播放器」与「adb screenrecord」，各自记账。"""

    def __init__(self, adb_rounds):
        self.adb_rounds = list(adb_rounds)      # 每轮 screenrecord 的输出块
        self.adb_procs = []
        self.players = []
        self.adb_cmds = []

    def __call__(self, cmd, **kw):
        if "screenrecord" in cmd:
            self.adb_cmds.append(list(cmd))
            chunks = self.adb_rounds.pop(0) if self.adb_rounds else []
            p = _FakeProc(out=chunks)
            self.adb_procs.append(p)
            return p
        self.players.append(_FakeProc())
        return self.players[-1]


def _pipe(monkeypatch, factory, kill_hook=None, **kw):
    monkeypatch.setattr(svc, "FIRST_DATA_TIMEOUT", 0.4)
    monkeypatch.setattr(svc.subprocess, "Popen", factory)
    monkeypatch.setattr(svc, "kill_device_process",
                        kill_hook or (lambda *a, **k: None))
    m = svc.PipeMirror("adb", "S1", "ffplay", "/bin/ffplay", **kw)
    return m


def test_pipe_start_ok_and_forwards_bytes(monkeypatch):
    """首帧到达即视为可用，且字节真的写进了播放器 stdin。"""
    factory = _PopenFactory([[b"\x00\x00\x00\x01-frame"]])
    m = _pipe(monkeypatch, factory)
    ok, err = m.start()
    assert ok is True and err == "", err
    assert factory.players[0].stdin.written == len(b"\x00\x00\x00\x01-frame")
    m.stop()


def test_pipe_start_fails_when_no_data(monkeypatch):
    """设备端 screenrecord 秒退（ROM 删了该命令）：必须报出原因并收掉播放器，
    否则用户只看到一个没画面的窗口。"""
    factory = _PopenFactory([[b""]])
    m = _pipe(monkeypatch, factory)
    ok, err = m.start()
    assert ok is False
    assert "screenrecord" in err
    assert factory.players[0].terminated is True      # 播放器不该留着


def test_pipe_restarts_after_screenrecord_limit(monkeypatch):
    """180s 上限：一轮正常结束（有数据）后要自动重开，不能投 3 分钟就黑屏。"""
    factory = _PopenFactory([[b"chunk-a"], [b"chunk-b"], []])
    m = _pipe(monkeypatch, factory)
    ok, _ = m.start()
    assert ok is True
    m._thread.join(timeout=5)
    assert len(factory.adb_procs) >= 2, "应在 screenrecord 退出后重开续流"
    assert m.restarts >= 1
    m.stop()


def test_pipe_stop_kills_and_clears_device(monkeypatch):
    """停止时既要杀本地 adb，也要清设备端 screenrecord —— 后者会一直占着
    编码器，残留着下次连录屏都起不来。"""
    killed = {}
    factory = _PopenFactory([[b"x"]])
    m = _pipe(monkeypatch, factory,
              kill_hook=lambda adb, serial, name: killed.setdefault("name", name))
    assert m.start()[0] is True
    m.stop()
    # 用「最后一轮」判断：180s 续流可能已经换了新的 adb 进程
    assert any(p.killed for p in factory.adb_procs)
    assert killed.get("name") == "screenrecord"


def test_pipe_alive_reflects_stop(monkeypatch):
    factory = _PopenFactory([[b"x"]])
    m = _pipe(monkeypatch, factory)
    m.start()
    assert m.alive() is True
    m.stop()
    assert m.alive() is False


# ---------------------------------------------------------------- 帧服务


def test_frame_server_serves_latest_png():
    """前端 <img> 真的能从回环地址拉到最新一帧（Content-Type 必须是 image/png）。"""
    srv = svc.FrameServer()
    port = srv.start()
    assert port > 0
    try:
        srv.set_frame("S1:5555", b"\x89PNG\r\n\x1a\nfirst")
        url = srv.frame_url("S1:5555")
        assert url.startswith("http://127.0.0.1:%d/frame?serial=" % port)
        with urllib.request.urlopen(url, timeout=5) as r:
            assert r.status == 200
            assert r.headers.get("Content-Type") == "image/png"
            assert r.read().startswith(b"\x89PNG")
        srv.set_frame("S1:5555", b"\x89PNG\r\n\x1a\nsecond")
        with urllib.request.urlopen(url, timeout=5) as r:
            assert r.read().endswith(b"second")     # 只给最新一帧
        # 没帧的设备应 404，而不是返回别人的画面
        try:
            urllib.request.urlopen(srv.frame_url("NOPE"), timeout=5)
            assert False, "无帧时应 404"
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        srv.stop()


def test_frame_server_url_encodes_serial():
    """无线序列号含冒号，不做编码会让 URL 变成非法、前端拉不到帧。"""
    srv = svc.FrameServer()
    srv.start()
    try:
        assert "%3A" in srv.frame_url("192.168.1.5:5555")
    finally:
        srv.stop()


# ---------------------------------------------------------------- 低帧率预览


def _snap(monkeypatch, chunks, server=None, fps=2):
    monkeypatch.setattr(svc.subprocess, "Popen",
                        lambda cmd, **kw: _FakeProc(out=chunks))
    return svc.SnapMirror("adb", "S1", server or svc.FrameServer(), fps)


def test_snap_start_ok_publishes_frame(monkeypatch):
    """抓到第一帧才会起后台循环：否则「启动了」却没有画面，比直接报错更迷惑。"""
    srv = svc.FrameServer()
    m = _snap(monkeypatch, [b"\x89PNG"], srv)
    ok, err = m.start()
    assert ok is True and not err
    assert srv.get_frame("S1") == b"\x89PNG"
    m.stop()


def test_snap_start_fails_without_data(monkeypatch):
    m = _snap(monkeypatch, [b""])
    ok, err = m.start()
    assert ok is False
    assert err


def test_snap_interval_clamps_fps():
    """帧率必须夹在 1~10：给 100 等于每 10ms 抓一次截图，只会白烧 CPU 与
    adb 带宽；给 0 / 空则回退默认 2fps（不能让它变成除零或疯狂抓帧）。"""
    srv = svc.FrameServer()
    assert svc.SnapMirror("adb", "S1", srv, 100).interval == pytest.approx(0.1)
    assert svc.SnapMirror("adb", "S1", srv, 4).interval == pytest.approx(0.25)
    assert svc.SnapMirror("adb", "S1", srv, 0).interval == pytest.approx(0.5)


def test_snap_stop_drops_frame():
    srv = svc.FrameServer()
    m = svc.SnapMirror("adb", "S1", srv, 2)
    srv.set_frame("S1", b"x")
    m.stop()
    assert srv.get_frame("S1") is None


# ---------------------------------------------------------------- 播放器消失


class _DeadPlayerFactory(_PopenFactory):
    """播放器一拉起来就已经「没了」（模拟用户把窗口关掉 / 播放器自己崩了）。"""

    def __call__(self, cmd, **kw):
        p = super().__call__(cmd, **kw)
        if "screenrecord" not in cmd:
            p.poll = lambda: 1
        return p


def test_pipe_stops_when_player_window_closed(monkeypatch):
    """播放器窗口被关掉后必须收手，不能继续重开 screenrecord。

    回归：转发循环只在「adb 退出」时判断要不要续流，从不看播放器。用户关掉
    ffplay 之后，每轮都是「读到一块 → 写 stdin 失败 → 重开 screenrecord」，
    能一路刷到 MAX_RESTARTS（500）次：设备端编码器被反复抢占、adb 进程成串
    泄漏，而状态栏只报一句「转发中断」，没人能看出是「窗口关了」。
    """
    factory = _DeadPlayerFactory([[b"frame-1"], [b"frame-2"], [b"frame-3"]])
    m = _pipe(monkeypatch, factory)
    m._player_err = "Failed to initialize video output"
    ok, _ = m.start()
    assert ok is True, "首帧确实写进去了（写失败才算失败）"
    m._thread.join(timeout=5)
    assert "播放器窗口已关闭" in m.error
    assert len(factory.adb_procs) == 1, "窗口已关就不该再重开 screenrecord"


def test_pipe_first_data_requires_successful_write(monkeypatch):
    """「出画面」的判定必须发生在写进播放器之后。

    旧顺序是「先置 first_data 再 write」：写失败时 start() 依然返回成功，
    用户拿到的是一个黑窗口 + 一句 6 秒后的超时错误。
    """
    class _BrokenStdin(_FakeStdin):
        def write(self, b):
            raise BrokenPipeError("player gone")

    factory = _PopenFactory([[b"frame"]])
    m = _pipe(monkeypatch, factory)
    orig_popen = factory.__call__

    def _popen(cmd, **kw):
        p = orig_popen(cmd, **kw)
        if "screenrecord" not in cmd:
            p.stdin = _BrokenStdin()
        return p

    monkeypatch.setattr(svc.subprocess, "Popen", _popen)
    ok, err = m.start()
    assert ok is False
    assert err, "写失败必须报错，而不是当作已出画面"
    m.stop()


def test_device_size_prefers_physical_over_override(monkeypatch):
    """`wm size` 同时给出 Override 与 Physical 时必须取 Physical。

    回归：判断条件写成 `if "Physical size" in line or "size" in line.lower():`
    —— 后半个条件让前半个失效，谁先出现就用谁。用户设过 `wm size 1000x1000`
    的机器上会拿临时分辨率去算缩放，投屏结束后 SetClipboard 式的「临时值」
    就被固化进了命令参数。
    """
    class _R:
        stdout = "Override size: 1000x1000\nPhysical size: 1080x2400"
        returncode = 0

    monkeypatch.setattr(svc.subprocess, "run", lambda *a, **k: _R())
    assert svc.device_size("adb", "S") == (1080, 2400)


def test_device_size_falls_back_to_lone_size_line(monkeypatch):
    """个别 ROM 只打一行 `Override size`：没有 Physical 时仍要能读出分辨率。"""
    class _R:
        stdout = "Override size: 720x1280\n"
        returncode = 0

    monkeypatch.setattr(svc.subprocess, "run", lambda *a, **k: _R())
    assert svc.device_size("adb", "S") == (720, 1280)

def test_pipe_failed_start_does_not_announce_interrupt(monkeypatch):
    """启动失败**不要**回调 on_status —— 那一档由 start() 的返回值负责。

    回归：启动失败路径也会走到 _emit()，controller 收到后推一条「投屏已中断」；
    紧接着它按降级链拉起低帧率预览并提示「已开启投屏」。用户于是先看到红字
    中断、再看到绿字开启，同一台设备在两条消息里既中断又开启，像是程序在乱报。
    """
    calls = []
    factory = _PopenFactory([[b""]])          # 设备端 screenrecord 秒退、零字节
    m = _pipe(monkeypatch, factory,
              on_status=lambda s, e: calls.append((s, e)))
    ok, err = m.start()
    assert ok is False and err
    assert calls == [], "没投起来的链路不该报告「已中断」"


def test_pipe_announces_after_started_then_player_closed(monkeypatch):
    """上面那条守卫不能把真正的中断也一起静音：投起来之后再断，必须照常回调。"""
    calls = []
    factory = _DeadPlayerFactory([[b"frame-1"]])
    m = _pipe(monkeypatch, factory,
              on_status=lambda s, e: calls.append((s, e)))
    ok, _ = m.start()
    assert ok is True
    m._thread.join(timeout=5)
    assert calls, "投屏中断必须通知界面"
    assert "播放器窗口已关闭" in calls[0][1]


def test_pipe_reports_reason_when_restarts_exhausted(monkeypatch):
    """重连到上限后要留下原因，不能静默停下（画面停住、状态栏一个字都没有）。"""
    chunks = [[b"chunk"]] * (svc.MAX_RESTARTS + 2)   # 每一轮都有一块数据、随即退出
    factory = _PopenFactory(chunks)
    m = _pipe(monkeypatch, factory)
    monkeypatch.setattr(svc, "MAX_RESTARTS", 2)      # 缩短到 2 轮，别真跑 500 次
    ok, _ = m.start()
    assert ok is True
    m._thread.join(timeout=10)
    assert "重连" in m.error and "screenrecord" in m.error
