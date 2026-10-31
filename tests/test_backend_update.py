# -*- coding: utf-8 -*-
"""backend.controller —— 版本更新动作（检查 / 跳过 / 打开下载页）的单测。

全部桩掉 `core.update.check`（不发真实 HTTPS），只验证控制器这一层的账：
  * 开关关掉 / 12 小时没到 → 不查（否则用户关掉的开关形同虚设）；
  * force=True 必须真查（用户主动点「检查更新」，不能没反应）；
  * 查完必须把 update_state 的 running 置回 false —— 这个布尔漏掉，
    按钮就永久停在「检查中」，再也点不动；
  * 「跳过此版本」只压制自动弹窗，手动检查仍要如实回报；
  * 打开下载页只放行白名单域名（更新源被换掉时不能变成「打开任意 exe 下载」）。
"""
import time

import pytest

import backend.controller as ctrl
from backend.controller import WebApi

V_OLD = "2026.1029.1931"
V_NEW = "2026.1103.1200"


@pytest.fixture(autouse=True)
def _isolate_prefs(tmp_path, monkeypatch):
    import core.prefs as prefs
    monkeypatch.setattr(prefs, "prefs_path",
                        lambda: str(tmp_path / "config.json"))
    monkeypatch.setattr(prefs, "legacy_prefs_path",
                        lambda: str(tmp_path / "settings.json"))


@pytest.fixture
def api():
    # 不调 boot()：这些用例只测更新动作本身，不需要拉起设备轮询与会话
    return WebApi()


def _wait(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def _drain(api, need="update", timeout=3.0, settle=0.3):
    """一直取事件，直到出现 `need` 类事件；再多收 `settle` 秒把随后的 status 收齐。

    不能用「轮询 api._update_last 是否已赋值」来判断完成：那个赋值发生在
    广播 update 事件**之前**，等到它变非空时事件可能还没进队列，断言会随机失败。
    """
    out = []
    end = time.time() + timeout
    seen = False
    while time.time() < end:
        out.extend(api.bus.take() or [])
        if not seen and any(e["kind"] == need for e in out):
            seen = True
            end = time.time() + settle
        time.sleep(0.01)
    return out


def _wait_done(api, timeout=3.0):
    assert _wait(lambda: api._update_last is not None, timeout), "检查更新未完成"


def _fake_check(result):
    def fn(current, feed=None, opener=None, timeout=None):
        return dict(result, current=current)
    return fn


OK_UPDATE = {"status": "update", "version": V_NEW, "notes": "修了几个问题",
             "url": "https://github.com/hai1995/ADBDeviceCommander/releases/tag/v" + V_NEW,
             "asset": {"name": "x_win64.zip", "url": "https://e/x.zip", "size": 1024},
             "error": "", "feed": "f"}
OK_LATEST = {"status": "latest", "version": V_OLD, "notes": "", "url": "",
             "asset": {}, "error": "", "feed": "f"}
BAD = {"status": "error", "version": "", "notes": "", "url": "", "asset": {},
       "error": "检查更新失败：连不上 github.com（timed out）", "feed": "f"}


# --------------------------------------------------------------------------- #
# 版本信息（只读）
# --------------------------------------------------------------------------- #
def test_update_info_reports_current_version(api):
    info = api.update_info()
    assert info["ok"] is True
    assert info["version"] == ctrl.VERSION
    assert info["enabled"] is True                     # 默认开启
    assert info["feed"] == ctrl.updater.FEED_URL       # 默认 GitHub
    assert info["checking"] is False
    assert info["last"] is None


def test_update_info_reads_feed_and_switch_from_prefs(api):
    ctrl.save_prefs({"update_feed": "https://intra.example.com/version.json",
                     "update_check": False})
    info = api.update_info()
    assert info["feed"] == "https://intra.example.com/version.json"
    assert info["enabled"] is False


def test_update_info_blank_feed_falls_back_to_github(api):
    ctrl.save_prefs({"update_feed": "   "})
    assert api.update_info()["feed"] == ctrl.updater.FEED_URL


# --------------------------------------------------------------------------- #
# 是否去查
# --------------------------------------------------------------------------- #
def test_update_check_respects_disabled_switch(api, monkeypatch):
    ctrl.save_prefs({"update_check": False})
    called = []
    monkeypatch.setattr(ctrl.updater, "check", lambda *a, **k: called.append(1))
    assert api.update_check() == {"ok": True, "status": "disabled"}
    assert called == []


def test_update_check_throttles_within_interval(api, monkeypatch):
    called = []
    monkeypatch.setattr(ctrl.updater, "check", lambda *a, **k: called.append(1))
    api._update_last_ts = time.time()
    assert api.update_check() == {"ok": True, "status": "skipped"}
    assert called == []


def test_update_check_force_ignores_switch_and_throttle(api, monkeypatch):
    ctrl.save_prefs({"update_check": False})
    monkeypatch.setattr(ctrl.updater, "check", _fake_check(OK_LATEST))
    api._update_last_ts = time.time()
    res = api.update_check(True)
    assert res == {"ok": True, "status": "started"}
    _wait_done(api)


def test_update_check_refuses_while_busy(api):
    api._update_busy = True
    assert api.update_check(True) == {"ok": False, "reason": "busy"}
    api._update_busy = False


def test_update_check_rejects_after_shutdown(api):
    api.state.mark_shutdown()
    assert api.update_check(True) == {"ok": False, "reason": "shutting_down"}


# --------------------------------------------------------------------------- #
# 结果广播
# --------------------------------------------------------------------------- #
def test_new_version_broadcasts_running_and_result(api, monkeypatch):
    monkeypatch.setattr(ctrl.updater, "check", _fake_check(OK_UPDATE))
    api.update_check(True)
    evs = _drain(api)

    states = [e["payload"] for e in evs if e["kind"] == "update_state"]
    assert states[0] == {"running": True}
    assert states[-1] == {"running": False}

    results = [e["payload"] for e in evs if e["kind"] == "update"]
    assert len(results) == 1
    assert results[0]["status"] == "update"
    assert results[0]["version"] == V_NEW
    assert results[0]["silenced"] is False
    assert api._update_busy is False


def test_auto_check_with_new_version_writes_status_line(api, monkeypatch):
    monkeypatch.setattr(ctrl.updater, "check", _fake_check(OK_UPDATE))
    api.update_check()                 # 自动检查
    evs = _drain(api)
    texts = [e["payload"].get("text", "") for e in evs if e["kind"] == "status"]
    assert any("发现新版本" in t for t in texts)


def test_auto_check_when_latest_stays_silent(api, monkeypatch):
    monkeypatch.setattr(ctrl.updater, "check", _fake_check(OK_LATEST))
    api.update_check()
    evs = _drain(api)
    assert [e for e in evs if e["kind"] == "status"] == []      # 自动检查没动静
    assert [e["payload"] for e in evs if e["kind"] == "update"][0]["status"] == "latest"


def test_manual_check_reports_failure(api, monkeypatch):
    monkeypatch.setattr(ctrl.updater, "check", _fake_check(BAD))
    api.update_check(True)
    evs = _drain(api)
    texts = [e["payload"].get("text", "") for e in evs if e["kind"] == "status"]
    assert any("连不上" in t for t in texts)


def test_check_exception_does_not_leave_busy_flag(api, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("解析炸了")
    monkeypatch.setattr(ctrl.updater, "check", boom)
    api.update_check(True)
    _wait_done(api)
    assert api._update_last["status"] == "error"
    assert "内部错误" in api._update_last["error"]
    assert api._update_busy is False          # 否则按钮永久转圈


def test_error_result_retries_in_an_hour_not_twelve(api, monkeypatch):
    """失败后只等 1 小时再试（而不是整个 12 小时间隔）。

    断言的是「距下次可查还剩多久」= 间隔 - 已过去的时间；写错方向会得到
    39600（12h 里已经过去 11h），那条断言永远为假。
    """
    monkeypatch.setattr(ctrl.updater, "check", _fake_check(BAD))
    api.update_check(True)
    _wait_done(api)
    remaining = ctrl.updater.CHECK_INTERVAL_S - (time.time() - api._update_last_ts)
    assert 3500 < remaining < 3700


def test_success_result_advances_throttle_fully(api, monkeypatch):
    monkeypatch.setattr(ctrl.updater, "check", _fake_check(OK_LATEST))
    api.update_check(True)
    _wait_done(api)
    assert time.time() - api._update_last_ts < 5


# --------------------------------------------------------------------------- #
# 跳过此版本
# --------------------------------------------------------------------------- #
def test_skipped_version_silences_auto_popup_only(api, monkeypatch):
    ctrl.save_prefs({"update_skipped_version": V_NEW})
    monkeypatch.setattr(ctrl.updater, "check", _fake_check(OK_UPDATE))
    api.update_check()                        # 自动：不弹
    evs = _drain(api)
    assert [e["payload"] for e in evs if e["kind"] == "update"][0]["silenced"] is True
    assert [e for e in evs if e["kind"] == "status"] == []

    api._update_last = None
    api._update_last_ts = 0
    api.update_check(True)                    # 手动：照实回报
    evs = _drain(api)
    assert [e["payload"] for e in evs if e["kind"] == "update"][0]["silenced"] is False


def test_update_skip_persists_version(api):
    assert api.update_skip(V_NEW) == {"ok": True, "version": V_NEW}
    assert ctrl.get_pref("update_skipped_version") == V_NEW


def test_update_skip_defaults_to_last_checked_version(api):
    api._update_last = {"version": V_NEW}
    assert api.update_skip()["version"] == V_NEW


def test_update_skip_rejects_garbage(api):
    res = api.update_skip("不是版本号")
    assert res["ok"] is False
    assert "版本号" in res["reason"]


def test_update_unskip_clears(api):
    ctrl.save_prefs({"update_skipped_version": V_NEW})
    assert api.update_unskip()["ok"] is True
    assert ctrl.get_pref("update_skipped_version") == ""


# --------------------------------------------------------------------------- #
# 打开下载页
# --------------------------------------------------------------------------- #
def test_update_open_uses_last_result_url(api, monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda u: opened.append(u) or True)
    api._update_last = dict(OK_UPDATE)
    res = api.update_open()
    assert res["ok"] is True and res["opened"] is True
    assert opened == [OK_UPDATE["url"]]


def test_update_open_without_url_says_check_first(api):
    res = api.update_open()
    assert res["ok"] is False
    assert "检查更新" in res["reason"]


def test_update_open_rejects_foreign_host(api, monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda u: opened.append(u) or True)
    res = api.update_open("http://evil.example.com/setup.exe")
    assert res["ok"] is False
    assert "拒绝打开" in res["reason"]
    assert opened == []


def test_update_open_rejects_non_http_scheme(api, monkeypatch):
    monkeypatch.setattr("webbrowser.open", lambda u: True)
    assert api.update_open("file:///C:/Windows/System32/calc.exe")["ok"] is False


def test_update_open_allows_configured_internal_feed_host(api, monkeypatch):
    """内网自建更新源时，它配置的域名也必须能打开（否则内网部署走不通）。"""
    ctrl.save_prefs({"update_feed": "https://intra.example.com/version.json"})
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda u: opened.append(u) or True)
    res = api.update_open("https://intra.example.com/dl/v.zip")
    assert res["ok"] is True
    assert opened == ["https://intra.example.com/dl/v.zip"]


def test_update_open_reports_browser_failure(api, monkeypatch):
    def boom(u):
        raise OSError("没有默认浏览器")
    monkeypatch.setattr("webbrowser.open", boom)
    res = api.update_open("https://github.com/x/y")
    assert res["ok"] is False
    assert "打开浏览器失败" in res["reason"]


def test_update_open_does_not_claim_success_when_browser_refuses(api, monkeypatch):
    """webbrowser.open 返回 False（但不抛）时不能说「已打开」。

    回归：没有默认浏览器 / 远程桌面会话没有浏览器关联 / 被安全软件或组策略
    拦下时，webbrowser.open 是**返回 False**而不是抛异常。旧实现不看返回值，
    照样推一条「已在浏览器中打开下载页」并回 ok=True —— 用户盯着毫无反应的
    屏幕，只能猜是程序卡了还是浏览器崩了；而地址就握在手里，抄下来手开就完了。
    """
    api.bus.take()                                  # 清掉构造期的事件
    monkeypatch.setattr("webbrowser.open", lambda u: False)
    api._update_last = dict(OK_UPDATE)
    res = api.update_open()
    assert res["ok"] is False
    assert res["opened"] is False
    assert OK_UPDATE["url"] in res["reason"], "失败原因里必须给出可手动打开的地址"
    evs = api.bus.take() or []
    texts = [e["payload"].get("text", "") for e in evs
             if e.get("kind") == "status" and isinstance(e.get("payload"), dict)]
    assert any("没能唤起浏览器" in x for x in texts), texts


# --------------------------------------------------------------------------- #
# 后台循环的等待
# --------------------------------------------------------------------------- #
def test_update_sleep_exits_on_shutdown(api):
    api.state.mark_shutdown()
    t0 = time.time()
    api._update_sleep(30)
    assert time.time() - t0 < 1.0      # 关闭时不能还睡满 30 秒
