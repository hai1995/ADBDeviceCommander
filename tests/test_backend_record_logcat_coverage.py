# -*- coding: utf-8 -*-
"""录屏收尾时对「配套 logcat 覆盖到哪」的校验（backend.controllers.record）。

这组用例锁定两条底线：

1. **只提示、不动产物**：结论写进 `sess["logcat_notes"]` 后逐条播报，日志
   txt 与视频照常保留 / 打包，任何告警都不允许触发删除或跳过打包。
2. **判据必须可证**：只看进程侧事实（抓取起点、是否真的断过、是否回落兼容
   模式），**不**用设备时钟推算缺口——车机没校时、录制期间被人手动改时间，
   那个差值都会失真，进而产生「只录十几秒却说丢了 10 分钟」的假告警。
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


def _fake_facts(api, monkeypatch, **facts):
    """注入抓取会话事实（started_host / compat / data_gap / lines / error）。"""
    monkeypatch.setattr(api.logcat_capture, "capture_facts",
                        lambda s: dict(facts))


def _write_log(path, stamps):
    with open(path, "w", encoding="utf-8") as f:
        f.write("--------- beginning of main\n")
        for s in stamps:
            f.write("%s  1234  1234 I Tag: hi\n" % s)


# ---------------------------------------------------------------------------
# 核心回归：设备时钟不可信时，绝不据此报「日志丢了」
# ---------------------------------------------------------------------------

def test_no_false_alarm_for_unsynced_device_clock(tmp_path, monkeypatch):
    """车机没校时 / 被手动改过时间：日志时间戳再离谱也不许报缺口。

    日志末行比「开始录制」早了 20 分钟，但抓取事实里没有任何中断——这正是
    历史缓冲或设备时钟跳变的表现，不是数据丢失。旧判据会据此弹「只录十几秒
    却丢了 10 分钟」的假告警。
    """
    api = _make_api()
    now = int(time.time())
    p = str(tmp_path / "logcat_A1.txt")
    _write_log(p, [_ts(now - 1300), _ts(now - 1260)])
    _fake_clock(monkeypatch, now)
    _fake_facts(api, monkeypatch, started_host=now - 20)

    notes = api._logcat_coverage_notes(
        {"start_host": now - 20}, {"A1": p})
    assert not [t for lvl, t in notes if lvl == "warn"], \
        "时钟不可信时不能据此推断缺口：%r" % (notes,)


def test_no_false_alarm_when_device_clock_jumps_midway(tmp_path, monkeypatch):
    """录制期间时间被改（前跳/回跳）：末行时间戳与设备当下完全对不上，也不报。"""
    api = _make_api()
    now = int(time.time())
    p = str(tmp_path / "logcat_A1.txt")
    _write_log(p, [_ts(now - 90), _ts(now - 60)])
    _fake_clock(monkeypatch, now + 5400)          # 收尾时设备时间已被人拨快 90 分钟
    _fake_facts(api, monkeypatch, started_host=now - 120)

    notes = api._logcat_coverage_notes(
        {"start_host": now - 120}, {"A1": p})
    assert not [t for lvl, t in notes if lvl == "warn"], notes


def test_no_false_alarm_when_device_timezone_differs_from_host(
        tmp_path, monkeypatch):
    """设备时区 ≠ 主机时区：时间戳解释差异同样不该产生缺口告警。"""
    api = _make_api()
    now = int(time.time())
    p = str(tmp_path / "logcat_A1.txt")
    _write_log(p, [_ts(now - 600, TZ_UTC), _ts(now - 2, TZ_UTC)])
    _fake_clock(monkeypatch, now, TZ_UTC)
    _fake_facts(api, monkeypatch, started_host=now - 620)

    notes = api._logcat_coverage_notes(
        {"start_host": now - 620}, {"A1": p})
    assert not [t for lvl, t in notes if lvl == "warn"], notes


def test_notes_silent_when_everything_normal(tmp_path, monkeypatch):
    """一切正常：一句都不说，别制造噪音。"""
    api = _make_api()
    now = int(time.time())
    p = str(tmp_path / "logcat_A1.txt")
    _write_log(p, [_ts(now - 600), _ts(now - 2)])
    _fake_clock(monkeypatch, now)
    _fake_facts(api, monkeypatch, started_host=now - 602, lines=100)

    assert api._logcat_coverage_notes(
        {"start_host": now - 602}, {"A1": p}) == []


# ---------------------------------------------------------------------------
# 可证事实：抓取晚启动 / 回落兼容 / 真的断过
# ---------------------------------------------------------------------------

def test_notes_warn_when_capture_started_late(tmp_path, monkeypatch):
    """抓取线程比录制晚 2 分钟才启动：录制开头确实没有日志，必须报。"""
    api = _make_api()
    now = int(time.time())
    p = str(tmp_path / "logcat_A1.txt")
    _write_log(p, [_ts(now - 100), _ts(now - 2)])
    _fake_clock(monkeypatch, now)
    _fake_facts(api, monkeypatch, started_host=now - 480)

    warns = [t for lvl, t in api._logcat_coverage_notes(
        {"start_host": now - 600}, {"A1": p}) if lvl == "warn"]
    assert warns and "晚约 2 分钟" in warns[0], warns


def test_notes_info_when_capture_fell_back_to_compat(tmp_path, monkeypatch):
    """设备不认 -T、回落兼容模式：只说清「开头可能是历史缓冲」，不判残缺。"""
    api = _make_api()
    now = int(time.time())
    p = str(tmp_path / "logcat_A1.txt")
    _write_log(p, [_ts(now - 300), _ts(now - 2)])
    _fake_clock(monkeypatch, now)
    _fake_facts(api, monkeypatch, started_host=now - 302, compat=True)

    notes = api._logcat_coverage_notes(
        {"start_host": now - 302}, {"A1": p})
    infos = [t for lvl, t in notes if lvl == "info"]
    assert infos and "历史缓冲" in infos[0], notes
    assert not [t for lvl, t in notes if lvl == "warn"], \
        "回落兼容模式不等于丢数据，不该弹告警：%r" % (notes,)


def test_notes_warn_when_capture_really_broke(tmp_path, monkeypatch):
    """抓取期间真的断过（掉线 / 意外退出）：这才是可确证的时间缺口。"""
    api = _make_api()
    now = int(time.time())
    p = str(tmp_path / "logcat_A1.txt")
    _write_log(p, [_ts(now - 600), _ts(now - 2)])
    _fake_clock(monkeypatch, now)
    _fake_facts(api, monkeypatch, started_host=now - 602, data_gap=True)

    warns = [t for lvl, t in api._logcat_coverage_notes(
        {"start_host": now - 602}, {"A1": p}) if lvl == "warn"]
    assert warns and "中断过" in warns[0] and "[logcat]" in warns[0], warns


def test_notes_facts_still_reported_without_device_clock(tmp_path, monkeypatch):
    """读不到设备时间也要照报真缺口——事实不依赖设备时钟。"""
    api = _make_api()
    now = int(time.time())
    p = str(tmp_path / "logcat_A1.txt")
    _write_log(p, [_ts(now - 600)])
    _fake_clock(monkeypatch, None)
    _fake_facts(api, monkeypatch, started_host=now - 600, data_gap=True)

    warns = [t for lvl, t in api._logcat_coverage_notes(
        {"start_host": now - 600}, {"A1": p}) if lvl == "warn"]
    assert warns and "中断过" in warns[0], warns


# ---------------------------------------------------------------------------
# 文件层面的真实问题
# ---------------------------------------------------------------------------

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


def test_notes_survive_adb_exception(tmp_path, monkeypatch):
    """探测过程抛异常也不能影响收尾：返回已算出的结论即可。"""
    api = _make_api()
    now = int(time.time())
    p = str(tmp_path / "logcat_A1.txt")
    _write_log(p, [_ts(now - 900)])

    def boom(*a, **k):
        raise RuntimeError("adb 炸了")

    monkeypatch.setattr(rec_mod, "device_clock", boom)
    _fake_facts(api, monkeypatch, started_host=now - 900, data_gap=True)
    warns = [t for lvl, t in api._logcat_coverage_notes(
        {"start_host": now - 900}, {"A1": p}) if lvl == "warn"]
    assert warns and "中断过" in warns[0], warns


def test_notes_survive_capture_facts_exception(tmp_path, monkeypatch):
    """capture_facts 抛异常时静默降级，不能把收尾流程带崩。"""
    api = _make_api()
    now = int(time.time())
    p = str(tmp_path / "logcat_A1.txt")
    _write_log(p, [_ts(now - 600)])
    _fake_clock(monkeypatch, now)

    def boom(serial):
        raise RuntimeError("facts 炸了")

    monkeypatch.setattr(api.logcat_capture, "capture_facts", boom)
    assert api._logcat_coverage_notes(
        {"start_host": now - 600}, {"A1": p}) == []


# ---------------------------------------------------------------------------
# 设备时钟只用于「对照参考」，不进完整性判定
# ---------------------------------------------------------------------------

def test_notes_report_device_clock_skew(tmp_path, monkeypatch):
    """设备时钟与本机差 30 分钟：要点出这个事实，但绝不能当成数据残缺。"""
    api = _make_api()
    now = int(time.time())
    dev_now = now + 1800
    p = str(tmp_path / "logcat_A1.txt")
    _write_log(p, [_ts(dev_now - 600), _ts(dev_now - 2)])
    _fake_clock(monkeypatch, dev_now)
    _fake_facts(api, monkeypatch, started_host=now - 602)

    notes = api._logcat_coverage_notes(
        {"start_host": now - 602}, {"A1": p})
    infos = [t for lvl, t in notes if lvl == "info"]
    assert infos and "设备时钟" in infos[0] and "偏快" in infos[0], notes
    assert not [t for lvl, t in notes if lvl == "warn"], notes


# ---------------------------------------------------------------------------
# 播报通道：warn 必须带「不点不消失」的 alert 标记
# ---------------------------------------------------------------------------

def test_teardown_records_notes_and_stop_broadcasts_them(tmp_path, monkeypatch):
    """收尾把结论存进会话，由「停止」在成功提示之后播报出来。

    顺序很关键：先「✓ 录屏已完成」再报日志问题——用户视线停在最后几条提示上，
    反过来的话他会以为这次录得完美无缺。
    """
    api = _make_api()
    now = int(time.time())
    log_path = str(tmp_path / "logcat_A1.txt")
    _write_log(log_path, [_ts(now - 600), _ts(now - 2)])
    _fake_clock(monkeypatch, now)
    _fake_facts(api, monkeypatch, started_host=now - 602, data_gap=True)

    api._rec_session = {
        "ts": "20260101_000000", "dir": str(tmp_path), "with_zip": False,
        "start_host": now - 602,
        "videos": {}, "devaudio": {}, "logcat_captures": {"A1": log_path},
        "pointer_location_prev": {}, "show_touches_prev": {},
    }
    monkeypatch.setattr(api.logcat_capture, "stop", lambda *a, **k: True)
    monkeypatch.setattr(api.logcat_capture, "is_running", lambda s: False)
    monkeypatch.setattr(api.video, "is_recording", lambda s: False)
    monkeypatch.setattr(api, "_zip_paths", lambda *a, **k: None)

    files, zpath = api._session_teardown(api._rec_session)
    assert log_path in files, "覆盖度提示绝不能把日志文件从产物里拿掉"
    notes = api._rec_session.get("logcat_notes") or []
    assert notes, "收尾必须算出覆盖度结论"

    api.bus.take()                     # 清掉收尾过程中的明细播报
    api._push_logcat_notes(api._rec_session)
    texts = [e["payload"].get("text") or "" for e in api.bus.take()
             if e["kind"] == "status"]
    assert any("中断过" in t for t in texts), texts


def test_warn_notes_are_broadcast_as_must_close_alert(tmp_path, monkeypatch):
    """「日志残缺」这类结论必须带 alert 标记（前端弹不点就不消失的弹窗）。"""
    api = _make_api()
    now = int(time.time())
    log_path = str(tmp_path / "logcat_A1.txt")
    _write_log(log_path, [_ts(now - 600), _ts(now - 2)])
    _fake_clock(monkeypatch, now)
    _fake_facts(api, monkeypatch, started_host=now - 602, data_gap=True)

    api._rec_session = {"logcat_captures": {"A1": log_path},
                        "start_host": now - 602}
    api._rec_session["logcat_notes"] = api._logcat_coverage_notes(
        api._rec_session, {"A1": log_path})
    api.bus.take()
    api._push_logcat_notes(api._rec_session)

    warns = [e["payload"] for e in api.bus.take()
             if e["kind"] == "status"
             and (e["payload"].get("text") or "").find("中断过") >= 0]
    assert warns, "必须播报「日志中断过」"
    p = warns[0]
    assert p.get("alert") is True, "数据残缺必须弹「不点不消失」的弹窗：%r" % (p,)
    assert p.get("toast") is True, "toast 也要保留（此刻正看着屏幕的人先看到）"
    assert p.get("alert_title"), "弹窗要有标题说清是哪一类问题：%r" % (p,)


def test_info_notes_do_not_open_alert_popup(tmp_path, monkeypatch):
    """时钟偏差 / 兼容模式是「说明」而非「告警」：只写状态栏，不弹窗。"""
    api = _make_api()
    now = int(time.time())
    dev_now = now + 1800                 # 设备快 30 分钟
    log_path = str(tmp_path / "logcat_A1.txt")
    _write_log(log_path, [_ts(dev_now - 600), _ts(dev_now - 2)])
    _fake_clock(monkeypatch, dev_now)
    _fake_facts(api, monkeypatch, started_host=now - 602, compat=True)

    api._rec_session = {"logcat_captures": {"A1": log_path},
                        "start_host": now - 602}
    api._rec_session["logcat_notes"] = api._logcat_coverage_notes(
        api._rec_session, {"A1": log_path})
    api.bus.take()
    api._push_logcat_notes(api._rec_session)
    events = [e["payload"] for e in api.bus.take() if e["kind"] == "status"]
    assert [p for p in events if "设备时钟" in (p.get("text") or "")], events
    assert [p for p in events if "历史缓冲" in (p.get("text") or "")], events
    assert not [p for p in events if p.get("alert")], \
        "说明类结论不该弹窗（状态栏说清就够了）：%r" % (events,)


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
