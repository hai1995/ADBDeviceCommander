# -*- coding: utf-8 -*-
"""backend.controller —— 无线调试 / APK 安装 / 设备信息 三组动作的单测。

全部桩掉 subprocess（不真跑 adb），只验证：
  * 命令参数拼得对（-s 有没有、-r/-d/-g 顺序）；
  * 输出解析结果正确翻译成状态栏 / 返回值；
  * 批量安装的汇总账（多台到齐只弹一条、失败清单带上设备号）。
"""
import threading
import time

import pytest

import backend.controller as ctrl
from backend.controller import WebApi


def _seed(api):
    api.devices.device_state = {"A1": "device", "B2": "device"}
    api.devices.device_model = {"A1": "Pixel", "B2": "X10"}
    api.devices.device_checked = {"A1": True, "B2": True}


@pytest.fixture(autouse=True)
def _isolate_prefs(tmp_path, monkeypatch):
    import core.prefs as prefs
    monkeypatch.setattr(prefs, "prefs_path",
                        lambda: str(tmp_path / "config.json"))
    monkeypatch.setattr(prefs, "legacy_prefs_path",
                        lambda: str(tmp_path / "settings.json"))


@pytest.fixture
def api():
    a = WebApi()
    a.state.adb_path = "adb"
    _seed(a)
    return a


class _R:
    def __init__(self, out="", err="", code=0):
        self.stdout, self.stderr, self.returncode = out, err, code


def _patch_run(monkeypatch, fn):
    monkeypatch.setattr(ctrl.subprocess, "run", fn)


def _wait(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def _status_texts(api):
    out = []
    for e in api.bus.take():
        if e["kind"] in ("status", "tool"):
            out.append(e["payload"].get("text", ""))
    return out


# ---------------------------------------------------------------- 无线调试
def test_wifi_state_lists_wireless_and_usb(api):
    api.devices.device_state = {"192.168.1.23:5555": "device", "A1": "device"}
    api.devices.device_checked = {"192.168.1.23:5555": True, "A1": True}
    res = api.wifi_state()
    assert res["ok"] is True
    assert [x["serial"] for x in res["wireless"]] == ["192.168.1.23:5555"]
    assert res["usb"] == ["A1"]
    assert res["port"] == 5555
    assert res["recent"] == []


def test_wifi_connect_normalizes_and_remembers(api, monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return _R("", "connected to 192.168.1.23:5555")

    _patch_run(monkeypatch, fake_run)
    monkeypatch.setattr(api.workers, "spawn", lambda *a, **k: None)

    res = api.wifi_connect("192.168.1.23")
    assert res["ok"] is True
    assert res["address"] == "192.168.1.23:5555"
    assert calls[0] == ["adb", "connect", "192.168.1.23:5555"]
    # 记住最近连接（写进 config.json 的 wifi_recent）
    assert api.wifi_state()["recent"] == ["192.168.1.23:5555"]
    assert any("已连接" in t for t in _status_texts(api))


def test_wifi_connect_rejects_bad_address_without_running_adb(api, monkeypatch):
    calls = []
    _patch_run(monkeypatch, lambda cmd, **kw: calls.append(cmd) or _R())
    res = api.wifi_connect("192.168.1.23; reboot")
    assert res["ok"] is False
    assert calls == []
    assert "非法字符" in res["reason"]


def test_wifi_connect_failure_explains_reason(api, monkeypatch):
    _patch_run(monkeypatch, lambda cmd, **kw: _R(
        "", "failed to connect to '1.2.3.4:5555': Connection refused"))
    res = api.wifi_connect("1.2.3.4")
    assert res["ok"] is False
    assert "无线调试" in res["reason"]
    assert api.wifi_state()["recent"] == []      # 失败不记入最近列表


def test_wifi_disconnect_passes_address(api, monkeypatch):
    calls = []
    _patch_run(monkeypatch, lambda cmd, **kw: calls.append(cmd) or _R(
        "disconnected 192.168.1.23:5555", ""))
    monkeypatch.setattr(api.workers, "spawn", lambda *a, **k: None)
    res = api.wifi_disconnect("192.168.1.23:5555")
    assert res["ok"] is True
    assert calls[0] == ["adb", "disconnect", "192.168.1.23:5555"]


def test_wifi_enable_detects_ip_then_switches_to_tcpip(api, monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if cmd[3] == "shell":
            return _R("default via 192.168.1.1 dev wlan0 proto dhcp "
                      "src 192.168.1.23 metric 600\n")
        return _R("", "restarting in TCP mode port: 5555")

    _patch_run(monkeypatch, fake_run)
    res = api.wifi_enable("A1")
    assert res["ok"] is True
    assert res["address"] == "192.168.1.23:5555"
    assert calls[0][:4] == ["adb", "-s", "A1", "shell"]
    assert calls[1] == ["adb", "-s", "A1", "tcpip", "5555"]


def test_wifi_enable_without_device_does_not_run_adb(api, monkeypatch):
    calls = []
    _patch_run(monkeypatch, lambda cmd, **kw: calls.append(cmd) or _R())
    res = api.wifi_enable("NOPE-ID")
    # 明确指定序列号时照发（由 adb 报错），未勾选且不指定才拦下
    assert res["ok"] is False
    api.devices.device_checked = {}
    res = api.wifi_enable(None)
    assert res["ok"] is False and "勾选" in res["reason"]


def test_wifi_enable_rejects_privileged_port(api, monkeypatch):
    _patch_run(monkeypatch, lambda cmd, **kw: _R())
    res = api.wifi_enable("A1", port=80)
    assert res["ok"] is False
    assert "1024" in res["reason"]


# ---------------------------------------------------------------- APK 安装
def _mk_apk(tmp_path):
    p = tmp_path / "demo.apk"
    p.write_bytes(b"PK\x03\x04fake")
    return str(p)


def test_apk_install_requires_picked_file(api):
    res = api.apk_install()
    assert res["ok"] is False
    assert "选择" in res["reason"]


def test_apk_install_requires_target(api, tmp_path):
    api._apk_path = _mk_apk(tmp_path)
    api.devices.device_checked = {}
    res = api.apk_install()
    assert res["ok"] is False and "勾选" in res["reason"]


def test_apk_install_runs_per_device_with_flags(api, monkeypatch, tmp_path):
    api._apk_path = _mk_apk(tmp_path)
    calls = []
    lock = threading.Lock()

    def fake_run(cmd, **kw):
        with lock:
            calls.append(cmd)
        return _R("Performing Streamed Install\nSuccess\n")

    _patch_run(monkeypatch, fake_run)
    res = api.apk_install(replace=True, downgrade=False, grant=False)
    assert res["ok"] is True and res["count"] == 2
    assert _wait(lambda: len(calls) == 2)
    for cmd in calls:
        assert cmd[:4] == ["adb", "-s", cmd[2], "install"]
        assert "-r" in cmd and "-d" not in cmd and "-g" not in cmd
        assert cmd[-1] == api._apk_path
    # 两台都成功 → 一条汇总 toast
    assert _wait(lambda: any("已安装到 2 台" in t for t in _status_texts(api)))


def test_apk_install_summary_reports_failures(api, monkeypatch, tmp_path):
    api._apk_path = _mk_apk(tmp_path)

    def fake_run(cmd, **kw):
        if cmd[2] == "B2":
            return _R("", "Failure [INSTALL_FAILED_INSUFFICIENT_STORAGE]")
        return _R("Success")

    _patch_run(monkeypatch, fake_run)
    api.apk_install()
    assert _wait(lambda: any("1 成功 / 1 失败" in t for t in _status_texts(api)))


def test_apk_install_retries_test_only_with_t(api, monkeypatch, tmp_path):
    """testOnly 包自动加 -t 重试一次（比让用户查错误码强）。"""
    api._apk_path = _mk_apk(tmp_path)
    calls = []
    lock = threading.Lock()

    def fake_run(cmd, **kw):
        with lock:
            calls.append(list(cmd))
        if "-t" in cmd:
            return _R("Success")
        return _R("Failure [INSTALL_FAILED_TEST_ONLY]")

    _patch_run(monkeypatch, fake_run)
    api.devices.device_checked = {"A1": True}
    api.apk_install(serial="A1")
    assert _wait(lambda: len(calls) == 2)
    assert "-t" not in calls[0] and "-t" in calls[1]
    assert _wait(lambda: any("已安装到 1 台" in t for t in _status_texts(api)))


def test_apk_install_uses_prefs_defaults(api, monkeypatch, tmp_path):
    from core.prefs import save_prefs
    save_prefs({"apk_grant": True, "apk_replace": False})
    api._apk_path = _mk_apk(tmp_path)
    seen = []

    def fake_run(cmd, **kw):
        seen.append(list(cmd))
        return _R("Success")

    _patch_run(monkeypatch, fake_run)
    api.devices.device_checked = {"A1": True}
    api.apk_install()
    assert _wait(lambda: seen)
    assert "-g" in seen[0] and "-r" not in seen[0]


# ---------------------------------------------------------------- 设备信息
_INFO_RAW = """@@PROP
[ro.product.model]: [MI 11]
[ro.build.version.release]: [13]
@@WM
Physical size: 1080x2400
@@BATT
  level: 66
@@DF
Filesystem 1K-blocks Used Available Use% Mounted on
/dev/x 1000 400 600 40% /data
@@MEM
MemTotal: 4000 kB
MemAvailable: 1000 kB
@@UP
60.0 60.0
"""


def test_device_info_returns_rows_and_text(api, monkeypatch):
    calls = []
    _patch_run(monkeypatch, lambda cmd, **kw: calls.append(cmd) or _R(_INFO_RAW))
    res = api.device_info("A1")
    assert res["ok"] is True
    assert calls[0][:4] == ["adb", "-s", "A1", "shell"]
    assert ["型号", "MI 11"] in res["rows"]
    assert "型号: MI 11" in res["text"]


def test_device_info_requires_serial(api):
    assert api.device_info("")["ok"] is False


def test_device_info_reports_adb_failure(api, monkeypatch):
    _patch_run(monkeypatch, lambda cmd, **kw: _R("", "error: device 'A1' not found", 1))
    res = api.device_info("A1")
    assert res["ok"] is False
    assert "not found" in res["reason"] or "失败" in res["reason"]


def test_apk_install_rejects_second_batch_while_running(api, monkeypatch,
                                                       tmp_path):
    """上一批没跑完时再点安装要被拒，不能「假开始」。

    回归：worker 的 key 是 `apk_install_<serial>`，`workers.spawn` 遇到同名
    存活线程会**直接复用、不再启动**；而批次账已被第二次点击重置。结果是
    界面提示「开始安装」，实际一个字节都没装，前一批的结果还被记进后一批的
    账里（提前弹「已完成」、按钮提前恢复）。
    """
    api._apk_path = _mk_apk(tmp_path)
    gate = threading.Event()
    calls = []
    lock = threading.Lock()

    def fake_run(cmd, **kw):
        with lock:
            calls.append(list(cmd))
        gate.wait(5)                      # 卡住第一批，模拟「还在装」
        return _R("Success")

    _patch_run(monkeypatch, fake_run)
    first = api.apk_install()
    assert first["ok"] is True and first["count"] == 2

    second = api.apk_install()
    assert second["ok"] is False
    assert "还没结束" in second["reason"], second

    gate.set()
    assert _wait(lambda: len(calls) == 2), \
        "被拒的那一次不该再起安装（实际命令数 %d）" % len(calls)
    assert _wait(lambda: any("已安装到 2 台" in t for t in _status_texts(api)))


def test_apk_batch_counts_each_device_once(api):
    """同一台设备被记账两次时，只算一台。

    防御的是「worker 重跑 / 重复回调」：账上加两次会让 done 提前到 total，
    批次在另一台还没装完时就宣告结束。
    """
    api._apk_batch = {"total": 2, "done": 0, "ok": 0, "failed": [],
                      "seen": set(), "name": "a.apk"}
    ok = {"ok": True, "code": "", "message": "安装成功"}
    api._apk_batch_done("A1", ok, "/tmp/a.apk")
    api._apk_batch_done("A1", ok, "/tmp/a.apk")        # 重复回调
    assert api._apk_batch["done"] == 1
    assert api._apk_batch["ok"] == 1
    api.bus.clear()


def test_apk_install_allowed_again_after_batch_finishes(api, monkeypatch,
                                                        tmp_path):
    """批次结束后必须能再装一次（拒绝逻辑不能变成永久锁）。"""
    api._apk_path = _mk_apk(tmp_path)
    _patch_run(monkeypatch, lambda cmd, **kw: _R("Success"))
    api.devices.device_checked = {"A1": True}
    assert api.apk_install()["ok"] is True
    assert _wait(lambda: api._apk_batch is None), "批次结束后账要清空"
    assert api.apk_install()["ok"] is True


# ---------------------------------------------------------------- 诊断包
def test_diag_collect_rejects_without_device(api):
    api.devices.device_checked = {}
    res = api.diag_collect(None, True, 2000)
    assert res["ok"] is False and res["reason"] == "no_device"
    assert any("勾选" in t for t in _status_texts(api))


def test_diag_collect_runs_in_background_and_reports(api, monkeypatch, tmp_path):
    """正常路径：后台线程跑完 -> tool 事件带路径 + diag_state 复位 + toast 汇总。"""
    import core.diag as diag_mod

    calls = []

    def fake_collect(adb, serial, out_dir, **kw):
        calls.append((adb, serial, out_dir, kw))
        path = str(tmp_path / ("diag_%s.zip" % serial))
        return path, {"serial": serial, "device": {"model": "Pixel"},
                      "parts": [{"name": "device.txt", "ok": True}]}, None

    # controller 里 import 的是同一个模块对象，改它就是改调用方看到的 collect
    monkeypatch.setattr(diag_mod, "collect", fake_collect)
    api.devices.device_checked = {"A1": True}

    res = api.diag_collect(None, True, 5000)
    assert res["ok"] is True and res["devices"] == ["A1"]
    assert _wait(lambda: not api._diag_running)

    assert len(calls) == 1
    assert calls[0][1] == "A1"
    assert calls[0][3]["with_logcat"] is True
    assert calls[0][3]["logcat_lines"] == 5000

    events = api.bus.take()
    kinds = [e["kind"] for e in events]
    assert "diag_state" in kinds
    diag_states = [e["payload"]["running"] for e in events
                   if e["kind"] == "diag_state"]
    assert diag_states[0] is True and diag_states[-1] is False
    tools = [e["payload"] for e in events
             if e["kind"] == "tool" and e["payload"].get("type") == "diag"]
    assert tools and tools[0]["path"].endswith("diag_A1.zip")


def test_diag_collect_refuses_while_running(api, monkeypatch):
    """已有一批在收集时第二次点击直接拒绝（不要排队出两个时间点不同的包）。"""
    api._diag_running = True
    res = api.diag_collect(None, True, 2000)
    assert res["ok"] is False and res["reason"] == "busy"
    assert any("正在收集" in t for t in _status_texts(api))


def test_diag_collect_failure_reports_and_resets(api, monkeypatch):
    import core.diag as diag_mod

    monkeypatch.setattr(diag_mod, "collect",
                        lambda *a, **kw: (None, None, "保存目录不可写"))
    api.devices.device_checked = {"A1": True}
    api.diag_collect(None, False, 2000)
    assert _wait(lambda: not api._diag_running)
    texts = _status_texts(api)
    assert any("诊断包失败" in t for t in texts)


def test_diag_collect_survives_collect_exception(api, monkeypatch):
    """collect 自己抛异常时也要复位按钮态（否则「收集诊断包」永久锁死）。"""
    import core.diag as diag_mod

    def boom(*a, **kw):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(diag_mod, "collect", boom)
    api.devices.device_checked = {"A1": True}
    api.diag_collect(None, False, 2000)
    assert _wait(lambda: not api._diag_running)
    assert any("内部错误" in t for t in _status_texts(api))


def test_diag_options_reads_prefs(api):
    import core.prefs as prefs
    prefs.save_prefs({"diag_with_logcat": False, "diag_logcat_lines": 5000})
    opt = api.diag_options()
    assert opt["ok"] is True
    assert opt["with_logcat"] is False
    assert opt["logcat_lines"] == 5000
    assert opt["running"] is False
