# -*- coding: utf-8 -*-
"""backend.screen_service.VideoRecorder —— 录屏收尾单测（不依赖真实设备）。

只验证「停止时是否把设备端 screenrecord 一并收尾」这类进程/资源语义，
adb 调用全部用 subprocess.run 替身拦截。
"""
import threading

import backend.screen_service as ss


class _Bus:
    def push(self, kind, payload=None):
        pass


class _FakeProc:
    def __init__(self):
        self.terminated = False
        self.killed = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return 0


def _recorder(tmp_path):
    vr = ss.VideoRecorder(_Bus(), "adb")
    proc = _FakeProc()
    vr._sessions["A1"] = {
        "remote": "/sdcard/adb_rec_A1.mp4",
        "local": str(tmp_path / "record_A1_x.mp4"),
        "proc": proc, "dir": str(tmp_path),
        "done": threading.Event(),
    }
    return vr, proc


def test_stop_signals_device_side_screenrecord_first(monkeypatch, tmp_path):
    """停止录屏必须先给设备端 screenrecord 发 SIGTERM 优雅收尾，再回收本地 adb。

    只 terminate() 本地 adb 客户端，会导致设备端进程拿到断开的管道、文件未收尾，
    随后 adb pull 读到半成品视频而失败（报「pull 失败」）。
    """
    captured = []

    def fake_run(cmd, **kw):
        captured.append(list(cmd))
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(ss.subprocess, "run", fake_run)
    vr, proc = _recorder(tmp_path)

    vr.stop("A1")

    # 设备端收尾（pkill screenrecord）必须发生
    pkills = [c for c in captured if "pkill" in c]
    assert pkills, "stop() 未对设备端 screenrecord 做收尾（会留下孤儿进程）"
    assert "screenrecord" in pkills[0]
    # 会话被清空，避免重复 stop
    assert vr.is_recording("A1") is False


def test_stop_all_keeps_going_after_one_session_raises(monkeypatch, tmp_path):
    """stop_all 里某台设备收尾抛异常时，其余设备仍必须被收尾。

    回归：stop_all 直接 `for s in serials: self.stop(s)`，`_pull_and_finish` 里的
    `os.makedirs(sess["dir"])` 又没有任何保护 —— 保存目录所在磁盘被拔掉时抛 OSError，
    异常一路冒到 controller（被吞掉），循环中断：**后面的设备完全不被收尾**，
    设备端 screenrecord 继续录到 Android 自带的 3 分钟上限，会话也已 pop 掉无法重试。
    """
    vr = ss.VideoRecorder(_Bus(), "adb")
    stopped = []

    def fake_stop(serial):
        stopped.append(serial)
        if serial == "A1":
            raise OSError("保存目录已不存在")
        return True, None, None

    monkeypatch.setattr(vr, "stop", fake_stop)
    vr._sessions = {"A1": {}, "B2": {}, "C3": {}}
    vr.stop_all()                      # 不得抛出
    assert stopped == ["A1", "B2", "C3"], stopped


def test_pull_and_finish_reports_missing_save_dir_instead_of_raising(monkeypatch, tmp_path):
    """保存目录不可创建时返回明确失败，而不是抛 OSError 中断整个收尾流程。"""
    vr, _proc = _recorder(tmp_path)
    boom_dir = str(tmp_path / "gone")

    def boom(path, exist_ok=False):
        raise OSError("磁盘不可用")

    monkeypatch.setattr(ss.os, "makedirs", boom)
    vr._sessions["A1"]["dir"] = boom_dir
    ok, local, err = vr._pull_and_finish("A1")
    assert ok is False
    assert err and "保存目录" in err, err


def test_stop_pull_retries_on_transient_failure(monkeypatch, tmp_path):
    """收尾/落盘有延迟时，adb pull 应带退避重试而非一次性失败。"""
    pull_attempts = {"n": 0}
    local = tmp_path / "record_A1_x.mp4"

    def fake_run(cmd, **kw):
        # 远端存在性探测：返回非空的 stdout 表示文件已就绪
        if cmd and cmd[0] == "adb" and "ls" in cmd:
            return type("R", (), {"returncode": 0, "stdout": "adb_rec_A1.mp4", "stderr": ""})()
        # 第一次 pull 模拟设备端尚未收尾、pull 失败；之后成功
        if "pull" in cmd:
            pull_attempts["n"] += 1
            if pull_attempts["n"] == 1:
                return type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})()
            open(local, "wb").write(b"\x00" * 100 + b"moov" + b"\x00" * 100)  # 含 moov、>64B
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(ss.subprocess, "run", fake_run)
    vr, _proc = _recorder(tmp_path)
    # 修正 local 指向临时文件，便于断言
    vr._sessions["A1"]["local"] = str(local)

    ok, lp, err = vr.stop("A1")

    assert ok is True, "pull 重试后应成功，实际 err=%r" % err
    assert lp == str(local)
    # 确认确实发生了重试（pull 被调用 ≥2 次）
    assert pull_attempts["n"] >= 2


def test_start_uses_unique_remote_name(monkeypatch, tmp_path):
    """远端文件名应带时间戳，避免上次崩溃残留文件阻断本次 screenrecord 启动。"""
    captured = []
    procs = []

    class _Proc:
        def terminate(self): pass
        def kill(self): pass
        def wait(self, timeout=None): return 0

    def fake_popen(cmd, **kw):
        captured.append(list(cmd))
        procs.append(_Proc())
        return procs[-1]

    def fake_run(cmd, **kw):
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(ss.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(ss.subprocess, "run", fake_run)
    vr = ss.VideoRecorder(_Bus(), "adb")
    vr.start("A1", str(tmp_path))
    # screenrecord 的远端参数里必须含时间戳段（%Y%m%d_%H%M%S），且文件名唯一
    rec_cmds = [c for c in captured if "screenrecord" in c]
    assert rec_cmds, "未发起 screenrecord"
    # 必须以 `adb shell screenrecord` 下发（screenrecord 是设备端命令，非 adb 子命令）
    rec = rec_cmds[0]
    assert rec[:4] == ["adb", "-s", "A1", "shell"], "screenrecord 必须经 adb shell 下发（rec=%r）" % rec
    assert "screenrecord" in rec and rec[rec.index("screenrecord") - 1] == "shell"
    remote = rec[-1]
    assert remote.startswith("/data/local/tmp/adb_rec_A1_") and remote.endswith(".mp4")
    # 同一设备两次录制远端名不应相同
    vr._sessions.clear()
    captured.clear()
    vr.start("A1", str(tmp_path))
    remote2 = [c for c in captured if "screenrecord" in c][0][-1]
    assert remote2 != remote, "两次录制远端文件名应不同（防残留文件冲突）"


def test_start_has_no_time_limit_option(monkeypatch, tmp_path):
    """固定时长功能已移除：screenrecord 命令不得再带 --time-limit。

    录屏只能手动停止（点「停止」由 stop() 优雅收尾）。这条断言锁定移除结果，
    防止哪天又加回来——UI 已无入口，后端也不该再支持。
    """
    captured = []

    class _Proc:
        def poll(self): return None
        def terminate(self): pass
        def kill(self): pass
        def wait(self, timeout=None): return 0

    monkeypatch.setattr(ss.subprocess, "Popen",
                        lambda cmd, **k: (captured.append(list(cmd)), _Proc())[1])
    monkeypatch.setattr(ss.subprocess, "run",
                        lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    vr = ss.VideoRecorder(_Bus(), "adb")
    ok, local = vr.start("A1", str(tmp_path))
    assert ok, local
    rec = [c for c in captured if "screenrecord" in c][0]
    assert "--time-limit" not in rec, "固定时长已移除，不应再下发 --time-limit：%r" % rec
    # start() 签名里也不该再有 duration 参数
    import inspect
    assert "duration" not in inspect.signature(ss.VideoRecorder.start).parameters
    assert not hasattr(vr, "_wait_fixed"), "固定时长的自动收尾线程应一并移除"


def test_start_reports_failure_when_screenrecord_exits_early(monkeypatch, tmp_path):
    """screenrecord 启动即退出（权限/不支持）应被 start() 立即捕获并报启动失败。"""
    import io

    class _Ok:
        returncode = 0
        stdout = stderr = ""

    class _EarlyProc:
        def __init__(self):
            self.stderr = io.StringIO("screenrecord: not permitted")

        def poll(self):
            return 1

        def terminate(self):
            pass

        def kill(self):
            pass

        def wait(self, timeout=None):
            return 1

    monkeypatch.setattr(ss.subprocess, "Popen", lambda *a, **k: _EarlyProc())
    monkeypatch.setattr(ss.subprocess, "run", lambda *a, **k: _Ok())
    vr = ss.VideoRecorder(_Bus(), "adb")
    ok, err = vr.start("A1", str(tmp_path))
    assert ok is False, "screenrecord 提前退出应判为启动失败"
    assert "启动失败" in err
    # 不应注册会话，避免后续 stop 误以为在录制
    assert vr.is_recording("A1") is False


def test_stop_reports_missing_remote_clearly(monkeypatch, tmp_path):
    """远端文件始终不存在时，应给出明确的「设备端未生成录屏文件」提示，而非空泛的 pull 失败。"""

    def fake_run(cmd, **kw):
        if cmd and cmd[0] == "adb" and "ls" in cmd:
            return type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})()
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(ss.subprocess, "run", fake_run)
    vr, _proc = _recorder(tmp_path)
    ok, lp, err = vr.stop("A1")
    assert ok is False
    assert "未生成录屏文件" in err, "应明确提示设备端未生成文件，实际 err=%r" % err


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 录屏可视化 overlay：指针位置 / 触摸圆点（设备系统设置，非录屏参数）
# ---------------------------------------------------------------------------

def _popen_capture(monkeypatch, captured):
    class _Proc:
        def poll(self): return None
        def terminate(self): pass
        def kill(self): pass
        def wait(self, timeout=None): return 0

    monkeypatch.setattr(ss.subprocess, "Popen",
                        lambda cmd, **k: (captured.append(list(cmd)), _Proc())[1])


def test_start_never_passes_show_pointer_to_screenrecord(monkeypatch, tmp_path):
    """回归：录屏命令严禁再带 screenrecord --show-pointer。

    该参数自 Android 10 才有，且定制 ROM / 云手机 / 模拟器上报的 SDK 与
    实际二进制常不一致——传了就是 unrecognized option、整场录屏启动即失败
    （用户实测：SDK 30 仍被拒）。可视化已改为设备系统设置 overlay
    （pointer_location / show_touches），与录屏命令彻底解耦。
    """
    captured = []
    _popen_capture(monkeypatch, captured)
    monkeypatch.setattr(ss.subprocess, "run",
                        lambda *a, **k: type("R", (), {"returncode": 0,
                                                       "stdout": "",
                                                       "stderr": ""})())
    vr = ss.VideoRecorder(_Bus(), "adb")
    ok, _local = vr.start("A1", str(tmp_path))
    assert ok
    rec = [c for c in captured if "screenrecord" in c][0]
    assert "show-pointer" not in " ".join(rec)
    # start() 签名里也不应再有该参数（前端只传 pointer_location / show_touches）
    import inspect
    assert "show_pointer" not in inspect.signature(ss.VideoRecorder.start).parameters


def test_get_system_setting_reads_values(monkeypatch):
    """get_system_setting：读得到返回 (True, 值)；读不到返回 (False, None)。"""
    def ok_run(cmd, **kw):
        assert cmd[1:4] == ["-s", "A1", "shell"]
        assert cmd[4:7] == ["settings", "get", "system"]
        assert cmd[7] in (ss.KEY_POINTER_LOCATION, ss.KEY_SHOW_TOUCHES)
        return type("R", (), {"returncode": 0, "stdout": "1\n", "stderr": ""})()
    monkeypatch.setattr(ss.subprocess, "run", ok_run)
    assert ss.VideoRecorder.get_system_setting(
        "adb", "A1", ss.KEY_SHOW_TOUCHES) == (True, "1")
    assert ss.VideoRecorder.get_system_setting(
        "adb", "A1", ss.KEY_POINTER_LOCATION) == (True, "1")

    def empty_run(cmd, **kw):
        # 老版本 settings 读不存在键时返回空串而非 "null"
        return type("R", (), {"returncode": 0, "stdout": "\n", "stderr": ""})()
    monkeypatch.setattr(ss.subprocess, "run", empty_run)
    assert ss.VideoRecorder.get_system_setting(
        "adb", "A1", ss.KEY_POINTER_LOCATION) == (True, "null")

    def fail_run(cmd, **kw):
        return type("R", (), {"returncode": 1, "stdout": "",
                              "stderr": "device offline"})()
    monkeypatch.setattr(ss.subprocess, "run", fail_run)
    assert ss.VideoRecorder.get_system_setting(
        "adb", "A1", ss.KEY_SHOW_TOUCHES) == (False, None)

    def boom(cmd, **kw):
        raise OSError("adb 不在")
    monkeypatch.setattr(ss.subprocess, "run", boom)
    assert ss.VideoRecorder.get_system_setting(
        "adb", "A1", ss.KEY_SHOW_TOUCHES) == (False, None)


def test_set_system_setting_put_and_delete(monkeypatch):
    """set_system_setting：普通值走 put；None/"null"/空走 delete（恢复「从未设置过」）。"""
    seen = []

    def fake_run(cmd, **kw):
        seen.append(list(cmd))
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(ss.subprocess, "run", fake_run)
    assert ss.VideoRecorder.set_system_setting(
        "adb", "A1", ss.KEY_POINTER_LOCATION, "1") is True
    assert seen[-1][-2:] == ["pointer_location", "1"]
    assert "put" in seen[-1]

    assert ss.VideoRecorder.set_system_setting(
        "adb", "A1", ss.KEY_POINTER_LOCATION, None) is True
    assert "delete" in seen[-1] and seen[-1][-1] == "pointer_location"
    assert ss.VideoRecorder.set_system_setting(
        "adb", "A1", ss.KEY_SHOW_TOUCHES, "null") is True
    assert "delete" in seen[-1]
    assert ss.VideoRecorder.set_system_setting(
        "adb", "A1", ss.KEY_SHOW_TOUCHES, "") is True
    assert "delete" in seen[-1]
    assert ss.VideoRecorder.set_system_setting(
        "adb", "A1", ss.KEY_SHOW_TOUCHES, "0") is True
    assert "put" in seen[-1] and seen[-1][-1] == "0"


def test_set_system_setting_failure_does_not_raise(monkeypatch):
    """settings 命令失败（设备瞬断）时返回 False，不抛异常打断收尾。"""
    def boom(cmd, **kw):
        raise OSError("boom")
    monkeypatch.setattr(ss.subprocess, "run", boom)
    assert ss.VideoRecorder.set_system_setting(
        "adb", "A1", ss.KEY_POINTER_LOCATION, "1") is False

def test_stop_unknown_serial_is_rejected(tmp_path):
    vr, _proc = _recorder(tmp_path)
    ok, lp, err = vr.stop("NOPE")
    assert ok is False and lp is None
    assert "未在录制" in err


def test_stop_device_screenrecord_uses_pid_kill(monkeypatch):
    """停止应优先按 PID 精准结束设备端 screenrecord（比 pkill 更通用），
    确保文件 moov 收尾、录出可播放的 MP4。"""
    captured = []

    def fake_run(cmd, **kw):
        captured.append(list(cmd))
        if "pidof" in cmd and cmd[-1] == "screenrecord":
            return type("R", (), {"returncode": 0, "stdout": "4321\n", "stderr": ""})()
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(ss.subprocess, "run", fake_run)
    vr = ss.VideoRecorder(_Bus(), "adb")
    vr._stop_device_screenrecord("adb", "A1")
    kills = [c for c in captured if "kill" in c and "shell" in c]
    assert kills and kills[0][-3:] == ["kill", "-INT", "4321"], "应按 PID kill -INT 4321（实际 %r）" % kills
    assert not any("pkill" in c for c in captured), "pidof 命中时不应回退 pkill"


def test_mp4_has_moov(tmp_path):
    """_mp4_has_moov 应识别含 moov 头的正常收尾 MP4，拒绝缺失 moov 的残缺文件。"""
    good = tmp_path / "good.mp4"
    good.write_bytes(b"\x00\x00\x00\x1cftypmp42" + b"A" * 80 + b"moov" + b"\x00\x00\x00\x10mvhd")
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"\x00\x00\x00\x1cftypmp42" + b"A" * 80 + b" no metadata atom here at all here")
    assert ss.VideoRecorder._mp4_has_moov(str(good)) is True
    assert ss.VideoRecorder._mp4_has_moov(str(bad)) is False


def test_stop_device_screenrecord_pid_kill_fallback_to_pkill(monkeypatch):
    """pidof / ps 都拿不到 PID 时，应回退到 pkill screenrecord。"""
    captured = []

    def fake_run(cmd, **kw):
        captured.append(list(cmd))
        if "pidof" in cmd or "ps" in cmd:
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(ss.subprocess, "run", fake_run)
    vr = ss.VideoRecorder(_Bus(), "adb")
    vr._stop_device_screenrecord("adb", "A1")
    assert any("pkill" in c and "screenrecord" in c for c in captured), "无 PID 时应回退 pkill screenrecord"


# ---------------------------------------------------------------------------
# 文件名安全：无线 ADB 序列号（IP:端口）含 Windows 非法字符
# ---------------------------------------------------------------------------
def test_screenshot_filename_safe_for_wireless_serial(monkeypatch, tmp_path):
    """无线设备（192.168.1.5:5555）截图文件名必须不含冒号等非法字符。

    回归：直接拼序列号会在 Windows 上抛 FileNotFoundError，截图静默丢失。
    """
    import io

    class _Proc:
        returncode = 0

        def communicate(self, timeout=None):
            return b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, b""

    monkeypatch.setattr(ss.subprocess, "Popen", lambda *a, **k: _Proc())
    path, err = ss.ScreenCapturer.screenshot(
        "adb", "192.168.1.5:5555", str(tmp_path))
    assert err is None, err
    assert path
    name = __import__("os").path.basename(path)
    for ch in '<>:"/\\|?*':
        assert ch not in name, "文件名含非法字符 %r：%s" % (ch, name)
    assert "192.168.1.5_5555" in name, "序列号应被净化为下划线形式：%s" % name
    assert __import__("os").path.exists(path)


def test_screenshot_filename_unique_within_same_second(monkeypatch, tmp_path):
    """同一秒内的两次截图必须落到**不同**文件。

    回归：截图文件名只用 `%Y%m%d_%H%M%S`（秒级），同一秒内的第二张会算出同一个
    路径 —— 轻则后一张覆盖前一张（用户少了一张图），重则两个线程同时往同一文件
    写，PNG 内容交错、文件损坏。录屏的远端文件名早就有同样的序号处理。
    """
    class _Proc:
        returncode = 0

        def communicate(self, timeout=None):
            return b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, b""

    monkeypatch.setattr(ss.subprocess, "Popen", lambda *a, **k: _Proc())
    # 固定时间戳：两次调用必定落在同一秒，才能暴露「同名互相覆盖」
    monkeypatch.setattr(ss.time, "strftime", lambda fmt: "20260928_120000")

    p1, e1 = ss.ScreenCapturer.screenshot("adb", "A1", str(tmp_path))
    p2, e2 = ss.ScreenCapturer.screenshot("adb", "A1", str(tmp_path))
    assert e1 is None and e2 is None, (e1, e2)
    assert p1 != p2, "同一秒的两次截图落到同一路径，会互相覆盖：%r" % p1
    assert __import__("os").path.exists(p1) and __import__("os").path.exists(p2)


def test_video_local_filename_safe_for_wireless_serial(monkeypatch, tmp_path):
    """无线设备录屏的本地文件名同样必须可安全落盘。"""
    class _Proc:
        def poll(self): return None
        def terminate(self): pass
        def kill(self): pass
        def wait(self, timeout=None): return 0

    monkeypatch.setattr(ss.subprocess, "Popen", lambda *a, **k: _Proc())
    monkeypatch.setattr(ss.subprocess, "run",
                        lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    vr = ss.VideoRecorder(_Bus(), "adb")
    ok, local = vr.start("192.168.1.5:5555", str(tmp_path))
    assert ok, local
    name = __import__("os").path.basename(local)
    for ch in '<>:"/\\|?*':
        assert ch not in name, "文件名含非法字符 %r：%s" % (ch, name)


def test_video_remote_path_safe_for_wireless_serial(monkeypatch, tmp_path):
    """远端 screenrecord 落地路径同样必须净化：冒号在设备端 shell 下不稳定。"""
    captured = []

    class _Proc:
        def poll(self): return None
        def terminate(self): pass
        def kill(self): pass
        def wait(self, timeout=None): return 0

    monkeypatch.setattr(ss.subprocess, "Popen",
                        lambda cmd, **k: (captured.append(list(cmd)), _Proc())[1])
    monkeypatch.setattr(ss.subprocess, "run",
                        lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    vr = ss.VideoRecorder(_Bus(), "adb")
    ok, local = vr.start("192.168.1.5:5555", str(tmp_path))
    assert ok, local
    remote = captured[-1][-1]
    # 基名过全部非法字符（/ 是设备端合法目录分隔符，单独放行）
    name = __import__("os").path.basename(remote)
    for ch in '<>:"/\\|?*':
        assert ch not in name, "远端文件名含非法字符 %r：%s" % (ch, remote)
    # 整条路径里冒号尤其危险（部分 ROM 的 shell 会误判为分隔符）
    for ch in '<>:"|?*\\':
        assert ch not in remote, "远端路径含有害字符 %r：%s" % (ch, remote)


# ---------------------------------------------------------------------------
# 进程意外死亡监测（adb root / 设备重启 adbd 杀掉设备端 screenrecord）
# ---------------------------------------------------------------------------
def test_watch_exit_marks_unexpected_death(tmp_path):
    """无人停止却进程退出：必须标记 died，且只汇报一次。

    回归：录屏中途执行 adb root 会杀掉设备端 screenrecord（本地 adb 客户端随之
    退出）。旧实现没有任何监测——界面永远停在「录制中」，用户点停止后才在约
    10 秒的 pull 重试后看到「缺 moov 头」。
    """
    vr, proc = _recorder(tmp_path)
    vr._watch_exit("A1", proc)          # 进程退出、会话未置 stopping
    assert vr.died_serials() == ["A1"], "意外退出必须被标记，否则界面永不复位"
    assert vr.died_serials() == [], "同一台设备只汇报一次，避免被反复收尾"
    # 会话条目仍在（收尾时还要靠它拉残片），只是标记被清掉
    assert vr.is_recording("A1") is True


def test_active_stop_is_not_reported_as_death(tmp_path, monkeypatch):
    """用户主动停止后进程退出：绝不能被误判成「意外死亡」。

    误判的后果：停止录屏会触发一轮多余的自动收尾（重复 pull / 合成 / 打包），
    状态栏出现两套互相矛盾的提示。
    """
    monkeypatch.setattr(ss.subprocess, "run",
                        lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    vr, proc = _recorder(tmp_path)
    # 跳过 9 秒级的 pull 重试：本用例只关心 stopping 标记的语义
    monkeypatch.setattr(vr, "_pull_and_finish", lambda s: (True, "x.mp4", None))
    monkeypatch.setattr(vr, "_stop_device_screenrecord", lambda adb, s: None)

    vr.stop("A1")                        # 主动停止：内部先置 stopping
    vr._watch_exit("A1", proc)           # 停止后的退出不算意外
    assert vr.died_serials() == []


def test_watch_exit_ignores_finished_session(tmp_path, monkeypatch):
    """会话已被收尾弹掉后，watcher 迟到醒来也不得标记（对象都已不存在）。"""
    monkeypatch.setattr(ss.subprocess, "run",
                        lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    vr, proc = _recorder(tmp_path)
    vr._pull_and_finish("A1")            # 真实收尾：弹出会话
    assert vr.is_recording("A1") is False
    vr._watch_exit("A1", proc)           # 迟到醒来：无会话可标
    assert vr.died_serials() == []


def test_watch_exit_ignores_replaced_proc(tmp_path):
    """进程引用被换掉（异常重建场景）时，旧 watcher 不得给新会话标 died。"""
    vr, _proc = _recorder(tmp_path)
    other = _FakeProc()
    vr._watch_exit("A1", other)          # 退出的是另一个进程，不是会话里那个
    assert vr.died_serials() == [], "旧进程的退出不该标记当前会话"


# ---------------------------------------------------------------------------
# 截图落盘的字节归一化（车机 screencap 会在 PNG 前吐杂字节）
# ---------------------------------------------------------------------------
def _tiny_png():
    """最小合法 PNG（1x1 / RGBA / 带 IEND），用来当 screencap 的「正常输出」。"""
    import struct
    import zlib

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00\xff"))
            + chunk(b"IEND", b""))


def test_screenshot_strips_leading_junk_before_saving(monkeypatch, tmp_path):
    """screencap 输出带前导杂字节时，落盘的必须是干净的 PNG。

    回归：真实车机上存出来的文件「开头不是 PNG 签名」——看图软件打不开，
    复制到剪贴板还会连带报「参数无效」。图片本体是完整的，只是前面多了几行。
    """
    png = _tiny_png()

    class _Proc:
        returncode = 0

        def communicate(self, timeout=None):
            return b"\r\nshell@android:/ $ screencap -p\r\n" + png, b""

    monkeypatch.setattr(ss.subprocess, "Popen", lambda *a, **k: _Proc())
    path, err = ss.ScreenCapturer.screenshot("adb", "A1", str(tmp_path))

    assert err is None, err
    with open(path, "rb") as f:
        saved = f.read()
    assert saved.startswith(b"\x89PNG\r\n\x1a\n"), "落盘文件必须以 PNG 签名开头"
    assert saved == png, "前导杂字节不应进入文件"


def test_screenshot_rejects_non_image_payload(monkeypatch, tmp_path):
    """连签名都找不到时给明确原因，不写一个打不开的文件。"""
    class _Proc:
        returncode = 0

        def communicate(self, timeout=None):
            return b"\x00\x01 garbage without any image signature", b""

    monkeypatch.setattr(ss.subprocess, "Popen", lambda *a, **k: _Proc())
    path, err = ss.ScreenCapturer.screenshot("adb", "A1", str(tmp_path))

    assert path is None
    assert err and "无法识别" in err, err
    assert list(tmp_path.iterdir()) == [], "认不出就别落盘，免得留一堆坏图"


def test_screenshot_uses_jpg_ext_when_device_returns_jpeg(monkeypatch, tmp_path):
    """设备若真的返回 JPEG，扩展名要跟着改，不能叫 .png 却存着 JPEG。"""
    jpg = b"\xff\xd8\xff\xe0" + b"\x00" * 32 + b"\xff\xd9"

    class _Proc:
        returncode = 0

        def communicate(self, timeout=None):
            return jpg, b""

    monkeypatch.setattr(ss.subprocess, "Popen", lambda *a, **k: _Proc())
    path, err = ss.ScreenCapturer.screenshot("adb", "A1", str(tmp_path))

    assert err is None, err
    assert path.endswith(".jpg"), path
    with open(path, "rb") as f:
        assert f.read() == jpg
