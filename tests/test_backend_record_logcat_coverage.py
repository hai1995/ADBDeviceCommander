# -*- coding: utf-8 -*-
"""录屏收尾时对「配套 logcat 覆盖到哪」的校验（backend.controllers.record）。

用户实况：视频录到 11:14，同步抓的 logcat 最后一条却停在 10:50 —— 后 24 分钟
一条日志都没有，而收尾只弹了一句「✓ 录屏已完成」。直到事后拿视频时间轴对日志
才发现日志是残缺的，那时既补不回来也说不清断在哪。这组用例锁定：收尾必须把
「日志比视频短了多少」讲到脸上，且不能用主机时钟误判。
"""
import time

from backend.controller import WebApi
from backend.controllers import record as rec_mod


def _make_api():
    api = WebApi()
    api.state.adb_path = "adb"
    return api


# 设备时区偏移（秒）。默认 0 = UTC，这是**故意**的：日志时间戳按给定偏移生成、
# device_clock 也返回同一偏移，两边必须自洽。写成「主机本地时间 + 主机时区」
# 会让用例在跑测机器时区不是 +0800 时莫名其妙地失败（本地过、CI 挂的经典形态）。
TZ_UTC = 0
TZ_CST = 8 * 3600


def _ts(at_epoch, tz_off=TZ_UTC):
    """把 epoch 秒转成该时区下的 logcat 'MM-DD HH:MM:SS.mmm'。"""
    return time.strftime("%m-%d %H:%M:%S", time.gmtime(at_epoch + tz_off)) + ".000"


def _fake_clock(monkeypatch, epoch, tz_off=TZ_UTC):
    """把 device_clock 打成固定值；epoch 为 None 表示「读不到设备时钟」。"""
    val = None if epoch is None else (epoch, tz_off)
    monkeypatch.setattr(rec_mod, "device_clock", lambda *a, **k: val)


def _write_log(path, stamps):
    with open(path, "w", encoding="utf-8") as f:
        f.write("--------- beginning of main\n")
        for s in stamps:
            f.write("%s  1234  1234 I Tag: hi\n" % s)


def test_notes_warn_when_log_stops_24_minutes_before_recording_ends(tmp_path, monkeypatch):
    """日志比录屏早结束 24 分钟：必须给出 warn，并带上具体时刻与时长。"""
    api = _make_api()
    now = int(time.time())
    p = str(tmp_path / "logcat_A1.txt")
    _write_log(p, [_ts(now - 1500), _ts(now - 1440)])
    _fake_clock(monkeypatch, now)

    notes = api._logcat_coverage_notes({}, {"A1": p})
    warns = [t for lvl, t in notes if lvl == "warn"]
    assert warns, notes
    msg = warns[0]
    assert "只跟到" in msg and "24 分钟" in msg, msg
    assert _ts(now - 1440)[:8] in msg, "要写明日志停在哪一刻：%s" % msg


def test_notes_silent_when_log_covers_recording(tmp_path, monkeypatch):
    """日志跟到最后一刻（差几秒）：正常场景一句都不该说，别制造噪音。"""
    api = _make_api()
    now = int(time.time())
    p = str(tmp_path / "logcat_A1.txt")
    _write_log(p, [_ts(now - 600), _ts(now - 2)])
    _fake_clock(monkeypatch, now)

    assert api._logcat_coverage_notes({}, {"A1": p}) == []


def test_notes_warn_when_file_has_no_log_lines(tmp_path, monkeypatch):
    """文件里一条 threadtime 都没有：说明整场录制都没抓到日志，必须说清。"""
    api = _make_api()
    p = str(tmp_path / "logcat_A1.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write("--------- beginning of main\n")
    _fake_clock(monkeypatch, int(time.time()))

    notes = api._logcat_coverage_notes({}, {"A1": p})
    assert notes and notes[0][0] == "warn"
    assert "没有任何日志行" in notes[0][1], notes


def test_notes_warn_when_file_missing(tmp_path, monkeypatch):
    """抓取登记了路径、文件却不存在（目录被删 / 被移走）：产物里没有日志。"""
    api = _make_api()
    _fake_clock(monkeypatch, int(time.time()))
    notes = api._logcat_coverage_notes(
        {}, {"A1": str(tmp_path / "gone.txt")})
    assert notes and notes[0][0] == "warn"
    assert "文件不存在" in notes[0][1], notes


def test_notes_report_device_clock_skew(tmp_path, monkeypatch):
    """设备时钟与本机差 30 分钟：要把这个事实点出来。

    这种场景下视频（按本机时间命名）与日志（设备时间戳）天然差出半小时，
    用户很容易把它当成「日志丢了一段」。说清是时钟偏差，比让他去猜有用。
    """
    api = _make_api()
    now = int(time.time())
    dev_now = now + 1800
    p = str(tmp_path / "logcat_A1.txt")
    _write_log(p, [_ts(dev_now - 600), _ts(dev_now - 2)])
    _fake_clock(monkeypatch, dev_now)

    notes = api._logcat_coverage_notes({}, {"A1": p})
    infos = [t for lvl, t in notes if lvl == "info"]
    assert infos, notes
    assert "设备时钟" in infos[0] and "偏快" in infos[0], infos
    # 日志本身是跟到最后一刻的，不该误报「后段日志丢失」
    assert not [t for lvl, t in notes if lvl == "warn"], notes


def test_notes_skip_quietly_when_device_time_unavailable(tmp_path, monkeypatch):
    """读不到设备时间（已拔线 / shell 被拦）：安静跳过，不给基于猜测的结论。"""
    api = _make_api()
    now = int(time.time())
    p = str(tmp_path / "logcat_A1.txt")
    _write_log(p, [_ts(now - 900)])
    _fake_clock(monkeypatch, None)
    assert api._logcat_coverage_notes({}, {"A1": p}) == []


def test_notes_do_not_count_teardown_elapsed_as_log_gap(tmp_path, monkeypatch):
    """收尾耗时（拉段 / 合并 / 打包 / 等设备回来）不能被算成日志缺口。

    回归：日志恰在「点停止」那一刻结束，但收尾合并可能再花几十秒；用「现在」
    减最后一条时间戳，会把这段耗时误报成「后段日志丢失」，用户以为日志残缺。
    since_ts 是下发停止的时刻，必须把它之后的耗时扣掉。
    """
    api = _make_api()
    now = int(time.time())
    p = str(tmp_path / "logcat_A1.txt")
    _write_log(p, [_ts(now - 300), _ts(now - 65)])
    _fake_clock(monkeypatch, now)

    # 65 秒前下发停止，日志恰停在那里：收尾耗时 65 秒，不该报警。
    assert api._logcat_coverage_notes({}, {"A1": p}, since_ts=now - 65) == []


def test_notes_still_warn_when_log_died_before_stop(tmp_path, monkeypatch):
    """扣收尾耗时只影响「停止之后」的时间，停止前就断掉的日志照样必须报。"""
    api = _make_api()
    now = int(time.time())
    p = str(tmp_path / "logcat_A1.txt")
    _write_log(p, [_ts(now - 1500), _ts(now - 1440)])
    _fake_clock(monkeypatch, now)

    notes = api._logcat_coverage_notes({}, {"A1": p}, since_ts=now - 30)
    warns = [t for lvl, t in notes if lvl == "warn"]
    assert warns and "后段日志已丢失" in warns[0], notes


def test_notes_survive_adb_exception(tmp_path, monkeypatch):
    """探测过程抛异常也不能影响收尾：返回空列表即可。"""
    api = _make_api()
    now = int(time.time())
    p = str(tmp_path / "logcat_A1.txt")
    _write_log(p, [_ts(now - 900)])

    def boom(*a, **k):
        raise RuntimeError("adb 炸了")

    monkeypatch.setattr(rec_mod, "device_clock", boom)
    assert api._logcat_coverage_notes({}, {"A1": p}) == []


def test_teardown_records_notes_and_stop_broadcasts_them(tmp_path, monkeypatch):
    """收尾把结论存进会话，由「停止」在成功提示之后播报出来。

    顺序很关键：先「✓ 录屏已完成」再「日志少了 24 分钟」—— 用户视线停在最后
    几条提示上，反过来的话他会以为这次录得完美无缺。
    """
    api = _make_api()
    now = int(time.time())
    log_path = str(tmp_path / "logcat_A1.txt")
    _write_log(log_path, [_ts(now - 1500), _ts(now - 1440)])
    _fake_clock(monkeypatch, now)

    api._rec_session = {
        "ts": "20260101_000000", "dir": str(tmp_path), "with_zip": False,
        "videos": {}, "devaudio": {}, "logcat_captures": {"A1": log_path},
        "pointer_location_prev": {}, "show_touches_prev": {},
    }
    monkeypatch.setattr(api.logcat_capture, "stop", lambda *a, **k: True)
    monkeypatch.setattr(api.logcat_capture, "is_running", lambda s: False)
    monkeypatch.setattr(api.video, "is_recording", lambda s: False)
    monkeypatch.setattr(api, "_zip_paths", lambda *a, **k: None)

    files, zpath = api._session_teardown(api._rec_session)
    assert log_path in files
    notes = api._rec_session.get("logcat_notes") or []
    assert notes, "收尾必须算出覆盖度结论"

    api.bus.take()                     # 清掉收尾过程中的明细播报
    api._push_logcat_notes(api._rec_session)
    texts = [e["payload"].get("text") or "" for e in api.bus.take()
             if e["kind"] == "status"]
    assert any("只跟到" in t for t in texts), texts


def test_warn_notes_are_broadcast_as_must_close_alert(tmp_path, monkeypatch):
    """「日志残缺」这类结论必须带 alert 标记（前端弹不点就不消失的弹窗）。

    回归用户实况：这条结论当时是 toast，6 秒后自动消失，人正在别处，等他回来
    只看得到「✓ 录屏已完成」—— 日志塌了 24 分钟这件事就这么过去了。数据残缺
    不能依赖一条会自己消失的提示。
    """
    api = _make_api()
    now = int(time.time())
    log_path = str(tmp_path / "logcat_A1.txt")
    _write_log(log_path, [_ts(now - 1500), _ts(now - 1440)])
    _fake_clock(monkeypatch, now)

    api._rec_session = {"logcat_captures": {"A1": log_path}}
    api._rec_session["logcat_notes"] = api._logcat_coverage_notes(
        api._rec_session, {"A1": log_path})
    api.bus.take()
    api._push_logcat_notes(api._rec_session)

    warns = [e["payload"] for e in api.bus.take()
             if e["kind"] == "status"
             and (e["payload"].get("text") or "").find("只跟到") >= 0]
    assert warns, "必须播报「日志只跟到几点」"
    p = warns[0]
    assert p.get("alert") is True, "数据残缺必须弹「不点不消失」的弹窗：%r" % (p,)
    assert p.get("toast") is True, "toast 也要保留（此刻正看着屏幕的人先看到）"
    assert p.get("alert_title"), "弹窗要有标题说清是哪一类问题：%r" % (p,)


def test_info_notes_do_not_open_alert_popup(tmp_path, monkeypatch):
    """设备时钟偏差是「说明」而非「告警」：只写状态栏，不弹窗。

    否则每条收尾提示都要点一次「我知道了」，用户很快就会盲点 —— 那时真正要紧
    的那条也就没人看了。
    """
    api = _make_api()
    now = int(time.time())
    dev_now = now + 1800                 # 设备快 30 分钟
    log_path = str(tmp_path / "logcat_A1.txt")
    _write_log(log_path, [_ts(dev_now - 600), _ts(dev_now - 2)])
    _fake_clock(monkeypatch, dev_now)

    api._rec_session = {"logcat_captures": {"A1": log_path}}
    api._rec_session["logcat_notes"] = api._logcat_coverage_notes(
        api._rec_session, {"A1": log_path})
    api.bus.take()
    api._push_logcat_notes(api._rec_session)
    events = [e["payload"] for e in api.bus.take() if e["kind"] == "status"]
    clock = [p for p in events if "设备时钟" in (p.get("text") or "")]
    assert clock, events
    assert not [p for p in events if p.get("alert")], \
        "时钟偏差不该弹窗（状态栏说清就够了）：%r" % (events,)


def test_push_alert_marks_payload_while_push_toast_does_not():
    """两个播报入口的分工：只有 _push_alert 带 alert 标记。

    这条守的是「别把所有 toast 都升级成弹窗」—— 一旦弹窗满天飞，用户会连看都
    不看就关，那时真正要紧的那条也一起被关掉了。
    """
    api = _make_api()
    api.bus.take()
    api._push_toast("warn", "⚠ 普通警告")
    api._push_alert("warn", "⚠ 数据残缺", title="⚠ 本次录制的日志不完整")
    got = [e["payload"] for e in api.bus.take() if e["kind"] == "status"]
    plain, alert = got[0], got[1]
    assert plain.get("toast") is True and not plain.get("alert"), plain
    assert alert.get("toast") is True and alert.get("alert") is True, alert
    assert alert.get("alert_title") == "⚠ 本次录制的日志不完整", alert


def test_no_false_alarm_when_device_timezone_differs_from_host(
        tmp_path, monkeypatch):
    """设备时区 ≠ 主机时区时，绝不能算出「平白少了几小时」的假缺口。

    这是这条校验最容易被误伤的地方：logcat 的 threadtime 是**设备本地墙上
    时间**，不含时区。如果按主机时区去解释，主机 +0800、设备 UTC（车机与部分
    定制 ROM 出厂默认）时，设备写的 03:14 会被当成「+0800 的 03:14」，即
    UTC 前一天 19:14 —— 比设备此刻整整早 8 小时。于是每次录屏收尾都弹窗
    「日志丢了 8 小时」，而实际一条没少。

    假告警的代价不是「多看一眼」：用户被坑过两次之后，真丢日志那次他也会
    直接点掉。所以这里必须以设备自报的 tz 偏移解析。
    """
    api = _make_api()
    now = int(time.time())
    p = str(tmp_path / "logcat_A1.txt")
    # 设备在 UTC，日志刚写到设备本地此刻（差 2 秒）
    _write_log(p, [_ts(now - 600, TZ_UTC), _ts(now - 2, TZ_UTC)])
    _fake_clock(monkeypatch, now, TZ_UTC)

    notes = api._logcat_coverage_notes({}, {"A1": p})
    assert not [t for lvl, t in notes if lvl == "warn"], \
        "时区不同不该产生缺口告警：%r" % (notes,)


def test_real_gap_still_detected_on_utc_device(tmp_path, monkeypatch):
    """同一套修复不能把真缺口一起放过：UTC 设备真的少 24 分钟，照样要报。"""
    api = _make_api()
    now = int(time.time())
    p = str(tmp_path / "logcat_A1.txt")
    _write_log(p, [_ts(now - 3000, TZ_UTC), _ts(now - 1440, TZ_UTC)])
    _fake_clock(monkeypatch, now, TZ_UTC)

    notes = api._logcat_coverage_notes({}, {"A1": p})
    warns = [t for lvl, t in notes if lvl == "warn"]
    assert warns and "24 分钟" in warns[0], notes


def test_skip_gap_when_device_timezone_unknown(tmp_path, monkeypatch):
    """取不到设备时区时宁可不报缺口，但时钟偏差仍要说。

    老 shell 不支持 `date +%z` 时，日志时间戳只能按主机时区猜。猜出来的差值
    恰好是整小时（时区差一定是 15 分钟的整数倍），没法与真缺口区分 —— 那就
    不说。时钟偏差那条只比 epoch，不受时区影响，仍可给出。
    """
    api = _make_api()
    now = int(time.time())
    p = str(tmp_path / "logcat_A1.txt")
    _write_log(p, [_ts(now - 1440, TZ_UTC)])
    _fake_clock(monkeypatch, now + 1800, None)      # 时区未知 + 设备快 30 分钟

    notes = api._logcat_coverage_notes({}, {"A1": p})
    assert not [t for lvl, t in notes if lvl == "warn"], \
        "时区未知时不该猜一个缺口出来：%r" % (notes,)
    infos = [t for lvl, t in notes if lvl == "info"]
    assert infos and "设备时钟" in infos[0], notes
