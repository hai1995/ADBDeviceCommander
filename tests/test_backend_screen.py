# -*- coding: utf-8 -*-
"""backend.screen_service.VideoRecorder —— 录屏收尾单测（不依赖真实设备）。

只验证「停止时是否把设备端 screenrecord 一并收尾」这类进程/资源语义，
adb 调用全部用 subprocess.run 替身拦截。
"""
import io
import threading
import time

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

    # 设备端收尾必须发生，但只能按本次录屏文件名（-f）精确匹配：
    # 按进程名 `pkill screenrecord` 会连投屏那条同名进程一起杀掉。
    pkills = [c for c in captured if "pkill" in c]
    assert pkills, "stop() 未对设备端 screenrecord 做收尾（会留下孤儿进程）"
    assert "-f" in pkills[0] and "adb_rec_A1.mp4" in pkills[0], pkills[0]
    assert "screenrecord" not in pkills[0], pkills[0]
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


def test_start_passes_segment_time_limit(monkeypatch, tmp_path):
    """每段必须显式下发 --time-limit：到点由 screenrecord 自己优雅收尾后接下一段。

    这里锁定的是「自动分段」的实现方式，而不是早年被移除的「固定时长」：
    那时到点会**结束整场录制**，现在到点只结束**这一段**，紧接着自动接下一段，
    用户完全不用操作（见 _roll_segment_locked / rolled_serials）。
    为什么不依赖 180 秒硬上限：硬上限到点是被系统掐断，慢设备上来不及写完
    moov，产物没有时长、播放不了。故取 REC_SEGMENT_S（留 10 秒余量）。
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
    assert "--time-limit" in rec, "每段都要带 --time-limit（自动分段的前提）：%r" % rec
    assert str(ss.REC_SEGMENT_S) in rec, rec
    from core.constants import REC_MAX_S as _HARD_MAX
    assert ss.REC_SEGMENT_S < _HARD_MAX, "段长必须留出余量，别撞 180 秒硬上限"
    # 整场录制仍然只由用户停止：start() 不接受 duration，也没有「到点自动收尾整场」
    import inspect
    assert "duration" not in inspect.signature(ss.VideoRecorder.start).parameters
    assert not hasattr(vr, "_wait_fixed"), "固定时长（到点收尾整场）的线程不应回来"


def test_old_rom_without_time_limit_is_retried(monkeypatch, tmp_path):
    """设备不认 --time-limit：去掉该参数重试一次，仍要能录。

    极老 ROM / 定制机上 screenrecord 会直接报 `unrecognized option`，整台设备
    就此完全录不了 —— 而分段只是体验优化，不能因为它把录屏功能本身弄挂。
    去掉参数后退化到 180 秒硬上限，自动分段照旧（180 > 170，判据不受影响）。
    """
    calls = []
    state = {"n": 0}

    class _Bad:
        def __init__(self):
            self.stdout = io.StringIO(
                "screenrecord: unrecognized option '--time-limit'\n")
            self.stderr = io.StringIO("")

        def poll(self):
            return 1

        def wait(self, timeout=None):
            return 1

        def kill(self):
            pass

    class _Good:
        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    def fake_popen(cmd, **kw):
        calls.append(list(cmd))
        state["n"] += 1
        return _Bad() if state["n"] == 1 else _Good()

    monkeypatch.setattr(ss.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(ss.subprocess, "run", lambda *a, **k: type(
        "R", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    vr = ss.VideoRecorder(_Bus(), "adb")

    ok, local = vr.start("A1", str(tmp_path))

    assert ok, local
    assert len(calls) == 2, calls
    assert "--time-limit" in calls[0]
    assert "--time-limit" not in calls[1], (
        "老 ROM 上必须去掉该选项重试：%r" % calls[1])
    assert calls[0][-1] != calls[1][-1], "重试要换新的远端文件名（防残留文件阻断）"
    assert vr._sessions["A1"]["no_lim"] is True


def test_full_segment_rolls_to_next_part(monkeypatch, tmp_path):
    """一段录满后**自动接下一段**，用户不需要做任何操作。

    回归：录满时只标一个「到上限」，整场录制就此收尾 —— 用户想录 8 分钟，得自己
    盯着表、到 3 分钟手动停一次再点开始，还要自己把几个文件对应起来。现在这一段
    到点即自动续录，产物仍归同一个会话、文件名带 _pN 顺序。
    """
    captured = []

    class _Proc:
        def poll(self): return None

        def terminate(self): pass

        def kill(self): pass

        def wait(self, timeout=None): return 0

    monkeypatch.setattr(ss.subprocess, "Popen",
                        lambda cmd, **k: (captured.append(list(cmd)), _Proc())[1])
    vr, proc = _recorder(tmp_path)
    vr._sessions["A1"].update({"ts": "T1", "extra": "T1", "seg": 1,
                               "segments": []})
    # 拉取另有测试，这里只关心续段本身（避免后台线程去跑真实 adb）
    monkeypatch.setattr(vr, "_pull_segment_bg",
                        lambda seg: seg["done"].set())
    monkeypatch.setattr(vr, "_confirm_segment", lambda *a: None)
    # 续段会为新的一段再起一个 watcher（真实环境里它会阻塞在 proc.wait() 上，
    # 直到那一段真的录满/被杀）。这里 Popen 是假的，_Proc.wait() 立刻返回 0 ——
    # 那条 watcher 随即判定「远未到点就退出」，把 died 标上，与本用例的断言
    # 抢跑（高负载时偶发失败）。所以把类上的 _watch_exit 换成只记调用的假函数，
    # 再由本用例直接调用**原函数对象**跑一次真实的判定逻辑。
    real_watch = ss.VideoRecorder.__dict__["_watch_exit"]
    spawned = []
    monkeypatch.setattr(ss.VideoRecorder, "_watch_exit",
                        lambda self, s, p: spawned.append((s, p)))
    vr._sessions["A1"]["started"] = time.time() - (ss.REC_SEGMENT_S + 1)

    real_watch(vr, "A1", proc)

    assert vr.died_serials() == [], "录满不是死亡"
    assert vr.limit_serials() == [], "录满不该结束整场录制"
    assert vr.rolled_serials() == [("A1", 2)]
    sess = vr._sessions["A1"]
    assert sess["seg"] == 2
    assert sess["local"].endswith("_p2.mp4"), sess["local"]
    assert len(sess["segments"]) == 1 and sess["segments"][0]["n"] == 1
    # 新那一段也要有自己的 watcher，否则它录满后没人接第 3 段
    assert len(spawned) == 1 and spawned[0][0] == "A1", spawned
    rec = [c for c in captured if "screenrecord" in c][0]
    assert rec[-1] != sess["segments"][0]["remote"], (
        "新段必须用新的远端文件名（重名会让 screenrecord 拒绝启动）：%r" % rec)


def test_segment_limit_ends_session_as_normal(monkeypatch, tmp_path):
    """到段数上限后不再续录，但仍是**正常收尾**（不能报成意外中断）。"""
    vr, proc = _recorder(tmp_path)
    vr._sessions["A1"].update({"ts": "T1", "extra": "T1",
                               "seg": ss.REC_MAX_SEGMENTS, "segments": []})
    vr._sessions["A1"]["started"] = time.time() - (ss.REC_SEGMENT_S + 1)

    vr._watch_exit("A1", proc)

    assert vr.limit_serials() == ["A1"]
    assert vr.died_serials() == []
    assert vr.rolled_serials() == []


def test_roll_failure_keeps_previous_segment(monkeypatch, tmp_path):
    """下一段起不来：录制到此为止，但**上一段必须完好保留**并说明是哪一段断了。

    只标一个 died 的话，用户会以为整场录制都废了，把本来完整的前几段一并扔掉。
    """
    def boom(cmd, **k):
        raise OSError("编码器被占用")

    monkeypatch.setattr(ss.subprocess, "Popen", boom)
    vr, proc = _recorder(tmp_path)
    vr._sessions["A1"].update({"ts": "T1", "extra": "T1", "seg": 1,
                               "segments": []})
    monkeypatch.setattr(vr, "_pull_segment_bg", lambda seg: seg["done"].set())
    vr._sessions["A1"]["started"] = time.time() - (ss.REC_SEGMENT_S + 1)

    vr._watch_exit("A1", proc)

    assert vr.died_serials() == ["A1"], "续不上就是中断，要触发收尾"
    note = vr.seg_notes().get("A1") or ""
    assert "第 2 段" in note and "编码器被占用" in note, note
    segs = vr._sessions["A1"]["segments"]
    assert [x["n"] for x in segs] == [1], "上一段必须留在待收尾列表里"


def test_stop_ex_returns_all_segments(monkeypatch, tmp_path):
    """停止时必须把**所有段**都拉回来，不能只回最后一段。

    回归：分段后 stop 只返回当前段，先前几段既不合成也不进 zip，用户拿到一个
    只有 3 分钟的视频，以为自己录的 8 分钟根本没录上。
    """
    monkeypatch.setattr(ss.subprocess, "run",
                        lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    vr, proc = _recorder(tmp_path)
    p1 = tmp_path / "record_A1_T1.mp4"
    p1.write_bytes(b"seg1")
    p2 = tmp_path / "record_A1_T1_p2.mp4"
    p2.write_bytes(b"seg2")
    done = threading.Event()
    done.set()
    vr._sessions["A1"].update({
        "ts": "T1", "extra": "T1", "seg": 2, "local": str(p2),
        "segments": [{"n": 1, "serial": "A1", "remote": "/r1",
                      "local": str(p1), "dir": str(tmp_path),
                      "ok": True, "err": None, "done": done}],
    })
    monkeypatch.setattr(vr, "_pull_one", lambda sess: (True, sess["local"], None))

    ok, paths, err = vr.stop_ex("A1")

    assert ok and err is None, (ok, err)
    assert paths == [str(p1), str(p2)], paths

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
    确保文件 moov 收尾、录出可播放的 MP4。

    设备上同时可能有投屏那条同名 screenrecord，因此只认「命令行里带本次
    录屏文件名」的那一行。
    """
    captured = []
    remote = "/data/local/tmp/adb_rec_A1_20261102_1.mp4"

    def fake_run(cmd, **kw):
        captured.append(list(cmd))
        if "ps" in cmd:
            return type("R", (), {"returncode": 0, "stdout": (
                "  PID ARGS\n"
                " 4321 /system/bin/screenrecord --output-format=h264 -\n"
                " 4322 /system/bin/screenrecord %s\n" % remote), "stderr": ""})()
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(ss.subprocess, "run", fake_run)
    vr = ss.VideoRecorder(_Bus(), "adb")
    vr._stop_device_screenrecord("adb", "A1", remote)
    kills = [c for c in captured if "kill" in c and "shell" in c]
    assert kills and kills[0][-3:] == ["kill", "-INT", "4322"], \
        "应按 PID kill -INT 4322（本次录屏），实际 %r" % (kills,)
    assert not any("4321" in c for c in kills), \
        "绝不能杀掉投屏那条（4321）：%r" % (kills,)
    assert not any("pkill" in c for c in captured), "精准命中时不应回退 pkill"


def test_mp4_has_moov(tmp_path):
    """_mp4_has_moov 应识别含 moov 头的正常收尾 MP4，拒绝缺失 moov 的残缺文件。"""
    good = tmp_path / "good.mp4"
    good.write_bytes(b"\x00\x00\x00\x1cftypmp42" + b"A" * 80 + b"moov" + b"\x00\x00\x00\x10mvhd")
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"\x00\x00\x00\x1cftypmp42" + b"A" * 80 + b" no metadata atom here at all here")
    assert ss.VideoRecorder._mp4_has_moov(str(good)) is True
    assert ss.VideoRecorder._mp4_has_moov(str(bad)) is False


def test_stop_device_screenrecord_pid_kill_fallback_to_pkill(monkeypatch):
    """pidof / ps 都拿不到 PID 时，只能按命令行特征 `pkill -f`，绝不按进程名杀。

    回归：按名字 `pkill screenrecord` 会把投屏那条同名进程一起掐断 —— 设备
    完全正常，用户正看着的投屏却黑了。
    """
    captured = []
    remote = "/data/local/tmp/adb_rec_A1_20261102_1.mp4"

    def fake_run(cmd, **kw):
        captured.append(list(cmd))
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(ss.subprocess, "run", fake_run)
    vr = ss.VideoRecorder(_Bus(), "adb")
    vr._stop_device_screenrecord("adb", "A1", remote)
    pkills = [c for c in captured if "pkill" in c]
    assert pkills, "无 PID 时应回退 pkill 清理自己的残留"
    for c in pkills:
        assert "-f" in c and "adb_rec_A1_20261102_1.mp4" in c, c
        assert "screenrecord" not in c, "不得按进程名杀同名进程：%r" % (c,)


# ---------------------------------------------------------------------------
# 文件名安全：无线 ADB 序列号（IP:端口）含 Windows 非法字符
# ---------------------------------------------------------------------------
def test_screenshot_filename_safe_for_wireless_serial(monkeypatch, tmp_path):
    """无线设备（192.168.1.5:5555）截图文件名必须不含冒号等非法字符。

    回归：直接拼序列号会在 Windows 上抛 FileNotFoundError，截图静默丢失。
    """

    class _Proc:
        returncode = 0

        def communicate(self, timeout=None):
            return _tiny_png(), b""

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
            return _tiny_png(), b""

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
    monkeypatch.setattr(vr, "_stop_device_screenrecord",
                        lambda adb, s, remote=None: None)

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
# 录屏中途设备重启（车机重启 / adbd 重启）：等待 → 自动续录
# ---------------------------------------------------------------------------
def _sess_for_roll(vr, tmp_path, seg=1):
    """补齐自动分段需要的会话字段（_recorder 的最小会话只是为停止路径准备的）。"""
    sess = vr._sessions["A1"]
    sess.update({
        "started": 0, "ts": "20260101_000000", "extra": "20260101_000000",
        "seg": seg, "dir": str(tmp_path), "segments": [],
    })
    return sess


def test_watch_exit_enters_reboot_wait_when_device_clearly_gone(tmp_path, monkeypatch):
    """设备明确掉线（重启中）：进等待，不能立刻判死。

    判死的后果就是老毛病：已录段还躺在 /data/local/tmp 就被放弃，logcat 的
    重连等待也被收尾一并掐断。
    """
    vr, proc = _recorder(tmp_path)
    monkeypatch.setattr(vr, "_device_online", lambda s: False)
    # 不真起等待线程，只验证状态翻转
    monkeypatch.setattr(vr, "_wait_reboot_and_resume", lambda *a: None)
    vr._watch_exit("A1", proc)
    assert vr.died_serials() == [], "设备重启不该被当成录屏意外结束"
    assert vr.reboot_wait_serials() == ["A1"]
    assert vr.reboot_wait_notes() == ["A1"], "进入等待要播报一次"


def test_watch_exit_still_marks_death_when_adb_probe_fails(tmp_path, monkeypatch):
    """探测本身失败（adb 不可用）时按老行为判死，不能白等 5 分钟。"""
    vr, proc = _recorder(tmp_path)
    monkeypatch.setattr(vr, "_device_online", lambda s: None)
    vr._watch_exit("A1", proc)
    assert vr.died_serials() == ["A1"]


def test_watch_exit_marks_death_when_device_still_online(tmp_path, monkeypatch):
    """设备还在、只是 screenrecord 自己崩了：直接判死，不进入等待。"""
    vr, proc = _recorder(tmp_path)
    monkeypatch.setattr(vr, "_device_online", lambda s: True)
    vr._watch_exit("A1", proc)
    assert vr.died_serials() == ["A1"]


def test_confirm_segment_does_not_kill_reboot_wait(tmp_path):
    """新段秒退但设备已离线：watcher 转入等待重启后，confirm 不能再补一刀判死。

    典型场景：刚好录满一段时车机重启，自动换段拉起的下一段在还没连上的设备上
    立刻退出。此时若再标 died，controller 会马上收尾、等待线程也会 abort，
    自动续录就被掐断了（数据虽在，但「设备回来后自动继续录制」的承诺失效）。
    """
    vr, _unused = _recorder(tmp_path)
    sess = _sess_for_roll(vr, tmp_path)
    dead = _FakeProc()
    dead.poll = lambda: 0
    sess["proc"] = dead
    sess["reboot_wait"] = True

    vr._confirm_segment("A1", dead, 2)

    assert sess.get("died") is None, "等待重启期间不该判死"
    assert not sess.get("seg_err"), "等待重启期间不该写「段启动后立即退出」"


def test_reboot_wait_resumes_next_segment_when_device_returns(tmp_path, monkeypatch):
    """设备回来：先收好重启前那一段，再自动接下一段，整场录制不中断。"""
    vr, proc = _recorder(tmp_path)
    sess = _sess_for_roll(vr, tmp_path)
    new_proc = _FakeProc()

    monkeypatch.setattr(ss.subprocess, "Popen", lambda *a, **k: new_proc)
    monkeypatch.setattr(vr, "_pull_segment_bg", lambda seg: None)
    monkeypatch.setattr(vr, "_confirm_segment", lambda *a: None)
    monkeypatch.setattr(vr, "_wait_device_back", lambda *a, **k: True)
    monkeypatch.setattr(ss.threading, "Thread",
                        lambda *a, **k: type("T", (), {"start": lambda self: None})())

    vr._wait_reboot_and_resume("A1", sess)

    assert sess["seg"] == 2, "重启后必须接着录第 2 段"
    assert sess["local"].endswith("_p2.mp4"), sess["local"]
    assert sess["segments"] and sess["segments"][0]["n"] == 1
    assert sess["segments"][0]["local"] == str(tmp_path / "record_A1_x.mp4")
    assert vr.resumed_serials() == ["A1"], "恢复续录要播报一次"
    assert vr.is_recording("A1") is True


def test_reboot_wait_timeout_marks_died(tmp_path, monkeypatch):
    """等满窗口设备仍未回来：才判死，交给正常收尾（已录段照样进包）。"""
    vr, proc = _recorder(tmp_path)
    sess = _sess_for_roll(vr, tmp_path)
    sess["reboot_wait"] = True
    monkeypatch.setattr(vr, "_wait_device_back", lambda *a, **k: False)

    vr._wait_reboot_and_resume("A1", sess)

    assert vr.died_serials() == ["A1"]
    assert vr.reboot_wait_serials() == []
    assert "等待重启超时" in (sess.get("seg_err") or "")


def test_stop_during_reboot_wait_aborts_wait_immediately(tmp_path, monkeypatch):
    """等待期间用户点停止：必须立刻退出等待，交给正常收尾（数据不丢）。"""
    vr = ss.VideoRecorder(_Bus(), "adb")
    monkeypatch.setattr(ss.subprocess, "run",
                        lambda *a, **k: type("R", (), {
                            "returncode": 1, "stdout": "",
                            "stderr": "error: device 'A1' not found"})())
    t0 = time.time()
    ok = vr._wait_device_back(
        "A1", max_wait_s=30, interval_s=1,
        should_abort=lambda: time.time() - t0 > 0.6)
    assert ok is False
    assert time.time() - t0 < 4, "用户已停止却还要等满整个窗口"


def test_stop_during_reboot_wait_keeps_session_for_teardown(tmp_path, monkeypatch):
    """用户停止时若设备还没回来：不标 died（由 active-stop 收尾路径负责拉残片）。"""
    vr, proc = _recorder(tmp_path)
    sess = _sess_for_roll(vr, tmp_path)
    sess["reboot_wait"] = True
    # 模拟：等待线程正阻塞在 _wait_device_back，用户在此时点了停止
    monkeypatch.setattr(vr, "_wait_device_back", lambda *a, **k: False)
    sess["stopping"] = True

    vr._wait_reboot_and_resume("A1", sess)

    assert vr.died_serials() == [], "主动停止不该被报成意外中断"
    assert sess.get("reboot_wait") is True, "主动停止时不改状态，交 stop_ex 收尾"


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


def _stub_fallback(monkeypatch, state="ok", detail="", pull=(b"", "落盘取图也失败")):
    """钉住「shell 探测 + 落盘取图」两条降级路径。

    exec-out 之外的两步都要走 adb，单测里不能真的调用；替身化之后，测试
    才能只针对被测的那一层做断言（坏图拒绝 / 降级成功 / 提示文案）。
    """
    monkeypatch.setattr(
        ss.ScreenCapturer, "_probe_shell",
        staticmethod(lambda adb, serial, timeout=8: (state, detail)))
    monkeypatch.setattr(
        ss.ScreenCapturer, "_pull_capture",
        staticmethod(lambda adb, serial, local_hint, timeout=60: pull))

def test_screenshot_rejects_non_image_payload(monkeypatch, tmp_path):
    """连签名都找不到时给明确原因，不写一个打不开的文件。"""
    class _Proc:
        returncode = 0

        def communicate(self, timeout=None):
            return b"\x00\x01 garbage without any image signature", b""

    monkeypatch.setattr(ss.subprocess, "Popen", lambda *a, **k: _Proc())
    _stub_fallback(monkeypatch)
    path, err = ss.ScreenCapturer.screenshot("adb", "A1", str(tmp_path))

    assert path is None
    assert err and "无法识别" in err, err
    assert list(tmp_path.iterdir()) == [], "认不出就别落盘，免得留一堆坏图"


def test_screenshot_rejects_truncated_png(monkeypatch, tmp_path):
    """PNG 只传了一半（有 IHDR、缺 IEND）时拒绝，不把半张图当成功。

    车机 4K 截图几 MB，adb 管道偶发超时 / 断连会停在中途。这类字节能通过
    头部校验，落盘后却打不开或只画出上半张 —— 与「分辨率有问题」同属那类
    看不出原因的失败。
    """
    png = _tiny_png()[:-8]           # 去掉 IEND 块（类型 + CRC）

    class _Proc:
        returncode = 0

        def communicate(self, timeout=None):
            return png, b""

    monkeypatch.setattr(ss.subprocess, "Popen", lambda *a, **k: _Proc())
    _stub_fallback(monkeypatch)
    path, err = ss.ScreenCapturer.screenshot("adb", "A1", str(tmp_path))

    assert path is None
    assert err and "不完整" in err and "IEND" in err, err
    assert list(tmp_path.iterdir()) == [], "半张图不许落盘"


def test_screenshot_rejects_png_with_broken_ihdr(monkeypatch, tmp_path):
    """PNG 头被污染时当场拒绝，不留一张「分辨率不对」的坏图。

    回归：个别 Windows adb / 车机把 0x0A 换成 0x0D 0x0A —— 签名照样认得出、
    normalize 也照旧返回，但 IHDR 的宽高与 CRC 已被改坏。落盘后看图软件只报
    「分辨率无效」，用户完全不知道是传输环节的问题，容易怀疑成「没 root」。
    """
    png = bytearray(_tiny_png())
    png[16:20] = b"\x00\x00\x00\x00"          # 宽改成 0（同时破坏 IHDR 的 CRC）

    class _Proc:
        returncode = 0

        def communicate(self, timeout=None):
            return bytes(png), b""

    monkeypatch.setattr(ss.subprocess, "Popen", lambda *a, **k: _Proc())
    _stub_fallback(monkeypatch)
    path, err = ss.ScreenCapturer.screenshot("adb", "A1", str(tmp_path))

    assert path is None
    assert err and "PNG" in err and "损坏" in err, err
    assert "两条取图通道都没成功" in err, "两条通道都试过之后才报失败"
    assert list(tmp_path.iterdir()) == [], "坏图不许落盘"


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


def test_exec_out_reports_adb_error_from_stdout(monkeypatch):
    """截图失败时要说清原因：adb 的报错在 stdout，只读 stderr 就会变成「空数据」。

    设备未连接时 `adb exec-out screencap -p` 把 `error: device 'A1' not found`
    打到 stdout 然后退出。旧实现只解 stderr（空），界面显示「截图失败：空数据」
    —— 用户完全看不出是设备没连上，只能反复重试。
    """
    class _Proc:
        returncode = 1

        def communicate(self, timeout=None):
            return b"error: device 'A1' not found\n", b""

        def kill(self):
            pass

    monkeypatch.setattr(ss.subprocess, "Popen", lambda *a, **k: _Proc())
    data, why = ss.ScreenCapturer._exec_out("adb", "A1")
    assert data == b""
    assert "not found" in why, why


def test_screenshot_falls_back_to_pull_when_exec_out_is_corrupted(monkeypatch, tmp_path):
    """exec-out 的字节被换行转换改坏时，自动改走「落盘 + pull」，用户无感。

    回归：个别 Windows adb / 车机在 exec-out 管道上做 0x0A → 0x0D 0x0A 的
    转换，PNG 头因此读不出宽高。旧实现直接报错、让用户自己去敲 adb pull；
    现在应当换一条二进制安全的通道再取一次，而不是把补救推给人。
    """
    broken = bytearray(_tiny_png())
    broken[16:20] = b"\x00\x00\x00\x00"      # 宽被改坏（CRC 同时失效）
    good = _tiny_png()

    class _Proc:
        returncode = 0

        def communicate(self, timeout=None):
            return bytes(broken), b""

    monkeypatch.setattr(ss.subprocess, "Popen", lambda *a, **k: _Proc())
    _stub_fallback(monkeypatch, pull=(good, ""))
    path, err = ss.ScreenCapturer.screenshot("adb", "A1", str(tmp_path))

    assert err is None, err
    with open(path, "rb") as f:
        assert f.read() == good, "降级取回的原图必须原样落盘"
    assert len(list(tmp_path.iterdir())) == 1, "不能留下 .part 之类的中间文件"


def test_screenshot_stops_and_explains_when_shell_needs_password(monkeypatch, tmp_path):
    """车机 adb shell 要授权密码：必须说清是「要密码」，而不是让人怀疑 root。

    这类失败在 adb 侧往往只是「没有输出」—— adbd 停在 Password: 等输入，
    而本工具没有终端可输入。不单独探测的话，界面只会显示「设备未返回图像」，
    用户根本无法从这句话推出「要先去车机上输密码」。
    """
    class _Proc:
        returncode = 0

        def communicate(self, timeout=None):
            return b"", b""

    monkeypatch.setattr(ss.subprocess, "Popen", lambda *a, **k: _Proc())
    _stub_fallback(monkeypatch, state="password", detail="Password:")
    path, err = ss.ScreenCapturer.screenshot("adb", "A1", str(tmp_path))

    assert path is None
    assert "授权密码" in err, err
    assert "Password:" in err, "要把 adb 原话带出来，便于用户对照"
    assert "shell echo hi" in err, "要给出可照抄的自查命令"
    assert list(tmp_path.iterdir()) == [], "取不到图时不许留下任何文件"


def test_screenshot_shell_timeout_points_at_password_first(monkeypatch, tmp_path):
    """shell 无响应（超时）：首要怀疑密码校验，并说明另一种可能。"""
    class _Proc:
        returncode = 0

        def communicate(self, timeout=None):
            return b"", b""

    monkeypatch.setattr(ss.subprocess, "Popen", lambda *a, **k: _Proc())
    _stub_fallback(monkeypatch, state="timeout", detail="")
    path, err = ss.ScreenCapturer.screenshot("adb", "A1", str(tmp_path))

    assert path is None
    assert "8 秒" in err and "Password" in err, err
    assert "echo hi" in err, "要给出可照抄的自查命令"


def test_screenshot_does_not_blame_root_when_shell_is_denied(monkeypatch, tmp_path):
    """shell 被车机拒绝时，别再让人以为是「没 root」。"""
    class _Proc:
        returncode = 0

        def communicate(self, timeout=None):
            return b"", b""

    monkeypatch.setattr(ss.subprocess, "Popen", lambda *a, **k: _Proc())
    _stub_fallback(monkeypatch, state="denied", detail="Permission denied")
    path, err = ss.ScreenCapturer.screenshot("adb", "A1", str(tmp_path))

    assert path is None
    assert "Permission denied" in err, err
    assert "不需要 root" in err, "screencap 不需要 root，这句话必须点明"


def test_screenshot_reports_both_channels_when_pull_also_fails(monkeypatch, tmp_path):
    """两条通道都失败时，两条原因都要给出来（否则用户只看到半截）。"""
    class _Proc:
        returncode = 0

        def communicate(self, timeout=None):
            return b"", b""

    monkeypatch.setattr(ss.subprocess, "Popen", lambda *a, **k: _Proc())
    _stub_fallback(monkeypatch, pull=(b"", "adb pull 没有取回截图：Permission denied"))
    path, err = ss.ScreenCapturer.screenshot("adb", "A1", str(tmp_path))

    assert path is None
    assert "两条取图通道都没成功" in err, err
    assert "exec-out" in err, "第一条通道的原因不能丢"
    assert "Permission denied" in err, "第二条通道的原因也不能丢"


def test_pull_capture_cleans_remote_and_part_file(monkeypatch, tmp_path):
    """落盘 + pull 必须按「截图 → 拉回 → 删远端」走，本地不留 .part。"""
    png = _tiny_png()
    calls = []

    def fake_run(cmd, **kw):
        calls.append(list(cmd))
        if "pull" in cmd:
            with open(cmd[-1], "wb") as f:
                f.write(png)
        return ss.subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(ss.subprocess, "run", fake_run)
    local = str(tmp_path / "shot.png")
    data, why = ss.ScreenCapturer._pull_capture("adb", "A1", local)

    assert why == "" and data == png
    assert not (tmp_path / "shot.png.part").exists(), "中间文件必须清掉"
    assert calls[0][3:5] == ["shell", "screencap"], calls
    assert calls[1][3] == "pull", calls
    assert calls[2][3:5] == ["shell", "rm"], "设备端临时文件要删掉"
    assert calls[2][-1].startswith("/sdcard/"), calls

def test_early_exit_reports_device_side_error_from_stdout(monkeypatch, tmp_path):
    """screenrecord 提前退出时，原因在 stdout（设备端输出），不能只读 stderr。

    `adb shell screenrecord` 的报错（Unable to open file / Permission denied）
    是远端命令的输出，落在 stdout；stderr 往往为空。旧实现只读 stderr，用户
    永远只看到一句「screenrecord 提前退出」，没有任何原因 —— 而这一刻恰恰最
    需要原因（是权限、是文件被占用、还是这台设备根本没有 screenrecord）。
    """
    import io

    class _Ok:
        returncode = 0
        stdout = stderr = ""

    class _EarlyProc:
        def __init__(self):
            self.stdout = io.StringIO("Unable to open file: /data/local/tmp/x.mp4\n")

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
    assert ok is False
    assert "Unable to open file" in err, err


def test_remote_probe_tells_device_gone_apart_from_missing_file(monkeypatch):
    """`ls` 失败有两种原因：设备不在了 vs 文件还没写好，必须分开。

    旧实现只回一个布尔，两者长得一模一样；收尾循环于是对「设备掉线」也老老实实
    退避 9 秒，最后报「设备端未生成录屏文件（screenrecord 可能未启动/提前退出）」。
    """
    class _R:
        def __init__(self, rc, out="", err=""):
            self.returncode, self.stdout, self.stderr = rc, out, err

    cases = [
        ("error: device 'A1' not found\n", True),
        ("error: device offline\n", True),
        ("error: no devices/emulators found\n", True),
        ("ls: /sdcard/x.mp4: No such file or directory\n", False),
    ]
    for text, gone in cases:
        monkeypatch.setattr(ss.subprocess, "run",
                            lambda *a, **k: _R(1, text, ""))
        ready, why, got_gone = ss.VideoRecorder._remote_probe(
            "adb", "A1", "/sdcard/x.mp4")
        assert ready is False
        assert got_gone is gone, (text, got_gone)
        assert why, "说明不能为空：否则界面上只剩一句「失败」"


def test_pull_gives_up_at_once_when_device_is_gone(monkeypatch, tmp_path):
    """设备掉线时不该白等 9 秒、更不该报成「screenrecord 可能没启动」。

    拔线 / 无线设备换 IP / 锁屏后 adb 掉线，都会让 `ls` 一直返回
    `error: device 'A1' not found`。旧实现对此毫无区分：6 次退避（0.6+1.2+…+3.0
    ≈ 9 秒）后报「设备端未生成录屏文件（screenrecord 可能未启动/提前退出）」，
    用户于是去查 screenrecord / 录屏参数，而设备早就不在电脑上了。

    现在的改进：设备掉线时先等 60 秒看设备能不能回来（给重启窗口），
    等不到才返回。mock `_wait_device_back` 让它立即返回 False，验证
    「返回 False 后立即退出、不走 6 次 ls 退避」的主路径。
    """
    sleeps = []
    monkeypatch.setattr(ss.time, "sleep", lambda s: sleeps.append(s))

    def fake_run(cmd, **kw):
        if "ls" in cmd:
            return type("R", (), {"returncode": 1, "stdout":
                                  "error: device 'A1' not found\n", "stderr": ""})()
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(ss.subprocess, "run", fake_run)
    vr, _proc = _recorder(tmp_path)
    # 不让它真等 60 秒：设备真的拔线了，等它回来永远不会发生
    monkeypatch.setattr(vr, "_wait_device_back", lambda serial, max_wait_s=60: False)
    ok, lp, err = vr._pull_and_finish("A1")

    assert ok is False
    assert "设备已断开" in err, err
    assert "not found" in err, "必须带上 adb 的原话，否则用户不知道该查什么：%r" % err
    # _wait_device_back 已经 mock 返回 False，没有进退避循环；
    # 这一次调用里 ls 没触发退避 sleep（只有 gone → wait → 立即返回，不进 attempt 循环）
    assert any("等待设备重启超时" in err for _ in [None]), err


def test_pull_succeeds_after_device_reboots_and_file_survives(monkeypatch, tmp_path):
    """设备重启回来后临时文件还在 → 必须真的把文件 pull 回本地。

    回归：掉线分支等到设备回来、二次 probe 也确认文件还在之后写了 `break`，
    直接跳出整个重试循环，连本轮该执行的 pull 都跳过了；最终只返回一句
    「pull 失败」。功能上等于「车机重启后录好的视频取不回来」，而这正是本工具
    必须保住的核心场景。
    """
    local = tmp_path / "record_A1_x.mp4"
    probes = {"n": 0}
    pulled = {"n": 0}

    def fake_run(cmd, **kw):
        if "ls" in cmd:
            probes["n"] += 1
            if probes["n"] == 1:
                return type("R", (), {"returncode": 1, "stdout":
                                      "error: device 'A1' not found\n",
                                      "stderr": ""})()
            return type("R", (), {"returncode": 0, "stdout":
                                  "/sdcard/adb_rec_A1.mp4\n",
                                  "stderr": ""})()
        if "pull" in cmd:
            pulled["n"] += 1
            local.write_bytes(b"\x00\x00\x00\x08moov" + b"0" * 200)
            return type("R", (), {"returncode": 0, "stdout": "",
                                  "stderr": ""})()
        return type("R", (), {"returncode": 0, "stdout": "",
                              "stderr": ""})()

    monkeypatch.setattr(ss.subprocess, "run", fake_run)
    vr, _proc = _recorder(tmp_path)
    monkeypatch.setattr(vr, "_wait_device_back", lambda *a, **k: True)
    ok, lp, err = vr._pull_and_finish("A1")

    assert ok is True, err
    assert pulled["n"] >= 1, "设备回来后没有执行 pull，文件没取回来"
    assert lp == str(local)


def test_pull_gives_up_at_once_when_ls_is_permission_denied(monkeypatch, tmp_path):
    """`ls` 报权限不足：不该白等 9 秒，更不能说成「未生成录屏文件」。

    保存目录落在 /sdcard/Android/data/... 这类受限路径、或设备策略收紧时，
    `ls` 会返回 `Permission denied`。文件其实**存在**，只是读不到。旧实现把它
    与「还没写好」一视同仁：6 次退避约 9 秒，最后报「设备端未生成录屏文件
    （screenrecord 可能未启动/提前退出）」—— 用户于是去查 screenrecord，而真正
    要处理的是路径权限。
    """
    sleeps = []
    monkeypatch.setattr(ss.time, "sleep", lambda s: sleeps.append(s))

    def fake_run(cmd, **kw):
        if "ls" in cmd:
            return type("R", (), {"returncode": 1, "stdout":
                                  "ls: /sdcard/x.mp4: Permission denied\n",
                                  "stderr": ""})()
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(ss.subprocess, "run", fake_run)
    vr, _proc = _recorder(tmp_path)
    ok, lp, err = vr._pull_and_finish("A1")

    assert ok is False
    assert "Permission denied" in err, "必须带上 adb 的原话：%r" % err
    assert "未生成" not in err, "文件可能存在只是读不到，不能报成「未生成」：%r" % err
    assert not sleeps, "权限不足不会自愈，不该再退避等待：%r" % sleeps


def test_pull_still_waits_when_file_is_simply_not_written_yet(monkeypatch, tmp_path):
    """文件还没写好（No such file or directory）必须继续等，不能误判成设备掉线。

    screenrecord 收到 SIGINT 后要几百毫秒才写回 moov 并关闭文件，这段窗口里
    `ls` 就是「不存在」。把它当成设备掉线会直接丢掉一段正常的录制。
    """
    monkeypatch.setattr(ss.time, "sleep", lambda s: None)
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if "ls" in cmd:
            return type("R", (), {"returncode": 1, "stdout":
                                  "ls: /sdcard/x.mp4: No such file or directory\n",
                                  "stderr": ""})()
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(ss.subprocess, "run", fake_run)
    vr, _proc = _recorder(tmp_path)
    ok, lp, err = vr._pull_and_finish("A1")

    assert ok is False
    assert "设备已断开" not in err, err
    assert "未生成录屏文件" in err, err
    assert len([c for c in calls if "ls" in c]) == 6, "应当退避重试满 6 次"


def test_set_system_setting_reports_rejection_even_with_zero_exit(monkeypatch):
    """`settings put` 被系统策略拒绝时 rc 仍为 0：不能当成功。

    `settings put` 碰到 SecurityException / Permission denial 时，报错打在
    stdout 上、退出码却是 0（国产定制系统的「安全策略」尤其常见）。只看
    returncode 会把它当成「改好了」：

      * 录屏开始时 → 用户勾了「指针位置 / 触摸圆点」，录像里什么都没有；
      * 录屏结束时 → 以为恢复了原值，实际 overlay 一直开着，用户下次正常用
        手机时满屏准星，却不知道是谁开的。
    """
    def fake_run(cmd, **kw):
        return type("R", (), {
            "returncode": 0,
            "stdout": "Exception occurred while executing 'put':\n"
                      "java.lang.SecurityException: Permission denial: writing "
                      "to settings requires android.permission.WRITE_SECURE_SETTINGS\n",
            "stderr": ""})()

    monkeypatch.setattr(ss.subprocess, "run", fake_run)
    ok, err = ss.VideoRecorder.set_system_setting_ex(
        "adb", "A1", ss.KEY_POINTER_LOCATION, "1")
    assert ok is False
    assert "SecurityException" in err or "Permission denial" in err, err


def test_set_system_setting_success_has_no_error_text(monkeypatch):
    """正常写入（两路输出皆空、rc=0）必须判成功，不能误报。"""
    monkeypatch.setattr(ss.subprocess, "run",
                        lambda cmd, **kw: type("R", (), {
                            "returncode": 0, "stdout": "", "stderr": ""})())
    ok, err = ss.VideoRecorder.set_system_setting_ex(
        "adb", "A1", ss.KEY_SHOW_TOUCHES, "1")
    assert ok is True and err == ""

def test_pull_gives_up_at_once_on_permission_denied(monkeypatch, tmp_path):
    """`pull` 报权限错误时不该再退避 9 秒 —— 它不会自己变好。

    /sdcard 被策略锁住、目标位置只读时，adb 每次都给同一句 Permission denied。
    旧实现照样跑满 6 次退避（0.6+1.2+…+3.0 ≈ 9 秒），最后报的还是同一句话；
    用户面对的就是「点停止后程序卡了十几秒，然后说了一句没头没尾的失败」。
    """
    sleeps = []
    armed = threading.Event()
    me = threading.current_thread()

    def fake_sleep(s):
        # 只统计 _pull_and_finish **执行期间**、且发生在**当前线程**的 sleep。
        # `ss.time` 是共享模块，其它线程（上一条用例遗留的收尾、后台 watcher）
        # 的 sleep 也会打进来；只靠 armed 这个全局开关挡不住它们 —— 整套跑时
        # 那些线程正好在这段窗口里睡，就会被误判成「这条路径在退避」。
        # 本地单跑快、整套跑慢，正是这类 flaky 的典型形态。
        if armed.is_set() and threading.current_thread() is me:
            sleeps.append(s)

    monkeypatch.setattr(ss.time, "sleep", fake_sleep)
    pulls = []

    def fake_run(cmd, **kw):
        if "pull" in cmd:
            pulls.append(cmd)
            return type("R", (), {
                "returncode": 1, "stdout":
                "adb: error: failed to copy '/sdcard/x.mp4' to 'x.mp4': "
                "remote Permission denied\n", "stderr": ""})()
        # ls 探测：文件就在那里（所以问题不在「还没写好」）
        return type("R", (), {"returncode": 0, "stdout": "-rw-rw---- 1 x.mp4\n",
                              "stderr": ""})()

    monkeypatch.setattr(ss.subprocess, "run", fake_run)
    vr, _proc = _recorder(tmp_path)
    armed.set()
    try:
        ok, lp, err = vr._pull_and_finish("A1")
    finally:
        armed.clear()

    assert ok is False
    assert "Permission denied" in err, err
    assert len(pulls) == 1, "不可恢复的错误只该尝试一次：%d" % len(pulls)
    assert not sleeps, "已知拿不到，就不该再退避等待：%r" % sleeps


def test_stop_recording_never_kills_mirror_by_process_name(monkeypatch, tmp_path):
    """停止录屏绝不能 `pkill screenrecord` —— 投屏用的是同名进程。

    回归：设备端 ps 拿不到完整命令行（老 ROM 只打印 comm）时会退化为按名字
    pkill，把用户眼前正在看的投屏一起掐断。设备一切正常，画面却黑了，用户
    根本想不到是「停止录屏」干的。
    """
    captured = []

    def fake_run(cmd, **kw):
        captured.append(list(cmd))
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(ss.subprocess, "run", fake_run)
    vr, _proc = _recorder(tmp_path)
    monkeypatch.setattr(vr, "_pull_and_finish", lambda s: (True, "x.mp4", None))
    vr.stop("A1")

    pkills = [c for c in captured if "pkill" in c]
    assert pkills, "自己的残留仍应被清理（不能什么都不做）"
    for c in pkills:
        assert "-f" in c, "兜底清理必须按命令行特征（-f）：%r" % (c,)
        assert "screenrecord" not in c, "不得按进程名杀同名进程：%r" % (c,)

def test_early_exit_is_still_death(tmp_path):
    """录到一半就退出（远未录满一段）仍按意外死亡处理，不能被续段判定吞掉。"""
    vr, proc = _recorder(tmp_path)
    vr._sessions["A1"]["started"] = time.time() - 30

    vr._watch_exit("A1", proc)

    assert vr.died_serials() == ["A1"]
    assert vr.limit_serials() == []


def test_discard_ex_does_not_pull_current_segment(monkeypatch, tmp_path):
    """取消录屏：停掉设备端进程，但**不**把当前段拉回来。

    回归背景：取消以前只能靠「停止」实现，而 stop_ex 一定会 pull —— 用户明确
    不要这段录像，程序还是把几百 MB 从设备搬回来再删掉（弱网下几十秒），
    取消本该是「立刻止损」。
    """
    calls = []

    def fake_run(cmd, **kw):
        calls.append(list(cmd))
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(ss.subprocess, "run", fake_run)
    vr, proc = _recorder(tmp_path)

    def boom(sess):
        raise AssertionError("discard_ex 不该 pull 当前段")

    monkeypatch.setattr(vr, "_pull_one", boom)

    ok, paths, err = vr.discard_ex("A1")

    assert ok is True, (ok, err)
    assert paths == [], paths
    assert "A1" not in vr._sessions, "会话必须清掉（否则界面永远显示录制中）"
    # 设备端临时文件要删：残留会让下一次 screenrecord 因同名文件直接启动失败
    rms = [c for c in calls if "rm" in c]
    assert rms and any("/sdcard/adb_rec_A1.mp4" in c for c in rms), calls


def test_discard_ex_returns_already_pulled_segments(monkeypatch, tmp_path):
    """自动分段时，先几段已经在后台拉回本地 —— 它们的路径要交回调用方删除。"""
    monkeypatch.setattr(
        ss.subprocess, "run",
        lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    vr, proc = _recorder(tmp_path)
    p1 = tmp_path / "record_A1_T1.mp4"
    p1.write_bytes(b"seg1")
    done = threading.Event()
    done.set()
    vr._sessions["A1"].update({
        "segments": [{"n": 1, "serial": "A1", "remote": "/r1",
                      "local": str(p1), "dir": str(tmp_path),
                      "ok": True, "err": None, "done": done}],
    })

    ok, paths, err = vr.discard_ex("A1")

    assert ok and err is None, (ok, err)
    assert paths == [str(p1)], paths


def test_discard_ex_is_not_reported_as_unexpected_death(monkeypatch, tmp_path):
    """取消是用户主动停止：不许被 _watch_exit 当成「录屏意外中断」。

    误判的代价是触发一轮多余自动收尾（会话已不在，收不到任何东西），
    状态栏却留下一条「录屏被中断、视频不完整」的告警，用户以为出了问题。
    """
    monkeypatch.setattr(
        ss.subprocess, "run",
        lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    vr, proc = _recorder(tmp_path)
    sess = vr._sessions["A1"]

    vr.discard_ex("A1")
    vr._watch_exit("A1", sess["proc"])

    assert vr.died_serials() == [], "取消不该被标记成意外中断"


def test_discard_ex_closes_adb_pipes(monkeypatch, tmp_path):
    """取消录屏也要主动关闭 adb 进程的 stdout/stderr（与 stop_ex 同一处理）。

    回归：stop_ex 早已补了关管道，discard_ex 是后加的独立路径却漏了同一处理。
    Popen 的管道句柄要等对象被 GC 才回收；反复「录制 → 取消」会累积句柄，
    Windows 上最终表现为后续 Popen 失败。
    """
    monkeypatch.setattr(
        ss.subprocess, "run",
        lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())

    class _Pipe:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class _Proc(_FakeProc):
        def __init__(self):
            super().__init__()
            self.stdout = _Pipe()
            self.stderr = _Pipe()

    vr = ss.VideoRecorder(_Bus(), "adb")
    proc = _Proc()
    vr._sessions["A1"] = {
        "remote": "/sdcard/adb_rec_A1.mp4",
        "local": str(tmp_path / "record_A1_x.mp4"),
        "proc": proc, "dir": str(tmp_path), "done": threading.Event(),
    }

    ok, _paths, err = vr.discard_ex("A1")

    assert ok and err is None, (ok, err)
    assert proc.stdout.closed and proc.stderr.closed, "取消后 adb 管道必须关闭"


def test_discard_unknown_serial_is_rejected(tmp_path):
    """没在录的设备点取消：返回「未在录制」，不抛异常。"""
    vr = ss.VideoRecorder(_Bus(), "adb")
    ok, paths, err = vr.discard_ex("NOPE")
    assert ok is False and paths == [] and "未在录制" in err, (ok, paths, err)
