# -*- coding: utf-8 -*-
"""backend.device_service.DeviceManager —— 设备刷新 / 勾选 / 差异播报单测。"""
import subprocess

import backend.device_service as ds
from backend.bus import BackendBus


def _adb_lines(devs):
    """构造 `adb devices -l` 风格输出。devs: [(serial, state, model), ...]"""
    out = ["List of devices attached"]
    for serial, state, model in devs:
        tail = " model:%s" % model if model else ""
        out.append("%s\t%s%s" % (serial, state, tail))
    return "\n".join(out) + "\n"


def _fake_run_factory(lines=None, exc=None):
    def fake_run(cmd, **kw):
        if exc is not None:
            raise exc
        return type("R", (), {"stdout": lines or "", "stderr": ""})()
    return fake_run


class _SeqRun:
    """按调用顺序返回预置结果的假 subprocess.run，并记录每次调用的命令。

    results 元素：("lines", 文本) 或 ("exc", 异常)。用尽后**重复最后一个**
    结果（如只给一条 exc 即表示「每次都抛」）。sleeps 记录 time.sleep 的调用
    （测试里把 ds.time.sleep 换成它，避免真等 0.6s 重试间隔）。
    """

    def __init__(self, results):
        self._results = list(results)
        self._i = 0
        self.calls = []
        self.sleeps = []

    def _next(self):
        if self._i < len(self._results):
            item = self._results[self._i]
        else:
            item = self._results[-1]
        self._i += 1
        return item

    def __call__(self, cmd, **kw):
        self.calls.append(list(cmd))
        kind, val = self._next()
        if kind == "exc":
            raise val
        return type("R", (), {"stdout": val, "stderr": ""})()

    def sleep(self, sec):
        self.sleeps.append(sec)


def _fresh(monkeypatch, devs):
    bus = BackendBus()
    mgr = ds.DeviceManager(bus)
    monkeypatch.setattr(ds.subprocess, "run",
                        _fake_run_factory(lines=_adb_lines(devs)))
    return bus, mgr


def _kinds(events):
    return [e["kind"] for e in events]


def test_first_load_auto_checks_single_usable_device(monkeypatch):
    bus, mgr = _fresh(monkeypatch, [("A1", "device", "Pixel"), ("B2", "device", "")])
    changed = mgr.refresh("adb", verbose=False)
    assert changed is True
    events = bus.take()
    # 只广播 devices 事件；首次加载不播“新增”状态
    assert _kinds(events) == ["devices"]
    payload = events[0]["payload"]
    assert payload["changed"] is True
    assert payload["count"] == 2
    # 有 2 台可用但不全勾（策略：只有唯一可用才自动勾）
    assert payload["items"][0]["checked"] is False
    assert mgr.selected_serials() == []


def test_second_refresh_unchanged_is_silent(monkeypatch):
    bus, mgr = _fresh(monkeypatch, [("A1", "device", "Pixel")])
    mgr.refresh(verbose=False)
    bus.take()
    # 无变化：自动轮询不产生任何事件
    assert mgr.refresh(verbose=False) is False
    assert bus.take() == []


def test_manual_refresh_unchanged_pushes_completion(monkeypatch):
    bus, mgr = _fresh(monkeypatch, [("A1", "device", "Pixel")])
    mgr.refresh(verbose=True)
    bus.take()
    assert mgr.refresh(verbose=True) is False
    events = bus.take()
    assert _kinds(events) == ["status"]
    assert events[0]["payload"]["type"] == "info"
    assert "刷新完成" in events[0]["payload"]["text"]


def test_new_device_added_broadcast(monkeypatch):
    bus, mgr = _fresh(monkeypatch, [("A1", "device", "Pixel")])
    mgr.refresh(verbose=False)
    bus.take()
    # A1 保持，接入 B2
    monkeypatch.setattr(ds.subprocess, "run",
                        _fake_run_factory(lines=_adb_lines(
                            [("A1", "device", "Pixel"), ("B2", "device", "X10")])))
    assert mgr.refresh(verbose=False) is True
    events = bus.take()
    kinds = _kinds(events)
    assert "devices" in kinds and "status" in kinds
    dev_ev = next(e for e in events if e["kind"] == "devices")
    assert dev_ev["payload"]["added"] == ["B2"]
    assert any(e["kind"] == "status" and "新设备" in e["payload"]["text"]
               for e in events)


def test_device_unplugged_grace_remembers_selection(monkeypatch):
    bus, mgr = _fresh(monkeypatch, [("A1", "device", "Pixel"), ("B2", "device", "X10")])
    mgr.refresh(verbose=False)
    mgr.toggle("A1", True)
    mgr.toggle("B2", True)
    bus.take()
    # B2 拔线：单轮刷新仍处宽限内——保留勾选、不在 gone，列表只显示 A1
    monkeypatch.setattr(ds.subprocess, "run",
                        _fake_run_factory(lines=_adb_lines([("A1", "device", "Pixel")])))
    assert mgr.refresh(verbose=False) is True
    events = bus.take()
    dev_ev = next(e for e in events if e["kind"] == "devices")
    assert dev_ev["payload"]["gone"] == []             # 宽限内不视为真正断开
    assert any("短暂失联" in e["payload"]["text"]
               for e in events if e["kind"] == "status")
    # A1 仍在、B2 仅临时失联：两者勾选记忆都应保留，B2 不作为下发目标
    assert sorted(mgr.selected_serials()) == ["A1"]
    assert mgr.device_checked.get("B2") is True        # 勾选记忆保留

    # 宽限 = 3 轮；refresh1 已是第 1 轮（streak=1）。第 2 轮仍在宽限内，
    # 列表无变化（changed=False）但勾选记忆与 absent 计数持续推进。
    assert mgr.refresh(verbose=False) is False
    bus.take()
    assert mgr.device_checked.get("B2") is True        # 第 2 轮：宽限内仍保留勾选
    # 第 3 轮（超过宽限）B2 真正断开：遗忘勾选、播报「已断开」，并广播新列表。
    # changed 必须为 True —— 这一轮 items 里已经没有 B2 了，不广播的话界面上那张
    # reconnecting 灰卡会一直挂着，而状态栏同时显示「已断开」，两边自相矛盾。
    assert mgr.refresh(verbose=False) is True
    ev3 = bus.take()
    assert any("已断开" in e["payload"]["text"]
               for e in ev3 if e["kind"] == "status")
    dev3 = next(e for e in ev3 if e["kind"] == "devices")
    assert dev3["payload"]["gone"] == ["B2"]
    assert [it["serial"] for it in dev3["payload"]["items"]] == ["A1"]
    assert mgr.device_checked.get("B2") is not True    # 勾选已遗忘


def test_transient_drop_recovers_selection(monkeypatch):
    bus, mgr = _fresh(monkeypatch, [("A1", "device", "Pixel"), ("B2", "device", "X10")])
    mgr.refresh(verbose=False)
    mgr.toggle("A1", True)
    mgr.toggle("B2", True)
    bus.take()
    # B2 短暂失联 2 轮（仍在宽限内），然后重连
    monkeypatch.setattr(ds.subprocess, "run",
                        _fake_run_factory(lines=_adb_lines([("A1", "device", "Pixel")])))
    assert mgr.refresh(verbose=False) is True          # 第 1 轮：列表变化
    bus.take()
    monkeypatch.setattr(ds.subprocess, "run",
                        _fake_run_factory(lines=_adb_lines([("A1", "device", "Pixel")])))
    assert mgr.refresh(verbose=False) is False         # 第 2 轮：列表未变，仅推进宽限
    bus.take()
    assert mgr.device_checked.get("B2") is True        # 宽限内勾选记忆仍在
    # 重连：B2 回到列表，应恢复为已勾选且可下发
    monkeypatch.setattr(ds.subprocess, "run",
                        _fake_run_factory(lines=_adb_lines(
                            [("A1", "device", "Pixel"), ("B2", "device", "X10")])))
    assert mgr.refresh(verbose=False) is True
    events = bus.take()
    # 重连：B2 回到列表，播报“已重连”，并恢复为已勾选且可下发
    assert any("已重连" in e["payload"]["text"]
               for e in events if e["kind"] == "status")
    assert mgr.device_checked.get("B2") is True
    assert sorted(mgr.selected_serials()) == ["A1", "B2"]


def test_unusable_device_keeps_selection_sticky(monkeypatch):
    bus, mgr = _fresh(monkeypatch, [("A1", "device", "Pixel")])
    mgr.refresh(verbose=False)
    mgr.toggle("A1", True)
    bus.take()
    # A1 变为 unauthorized（仍在列表中，只是暂不可用）：勾选记忆保留、置为不可用、
    # 状态变化播报，但不再强制取消勾选。
    monkeypatch.setattr(ds.subprocess, "run",
                        _fake_run_factory(lines=_adb_lines(
                            [("A1", "unauthorized", "Pixel")])))
    assert mgr.refresh(verbose=False) is True
    events = bus.take()
    dev_ev = next(e for e in events if e["kind"] == "devices")
    item = dev_ev["payload"]["items"][0]
    assert item["ok"] is False and item["checked"] is True
    assert dev_ev["payload"]["stat_changed"] == ["A1"]
    assert any("状态变为" in e["payload"]["text"]
               for e in events if e["kind"] == "status")
    # 暂不可用设备不能作为下发目标，但仍记住勾选
    assert mgr.selected_serials() == []
    assert mgr.device_checked.get("A1") is True


def test_sticky_selection_recovers_after_transient_state_flicker(monkeypatch):
    bus, mgr = _fresh(monkeypatch, [("A1", "device", "Pixel"), ("B2", "device", "X10")])
    mgr.refresh(verbose=False)
    mgr.toggle("A1", True)
    mgr.toggle("B2", True)
    bus.take()
    # A1 短暂变为 offline（多设备场景：无自动勾选兜底），B2 不变
    monkeypatch.setattr(ds.subprocess, "run",
                        _fake_run_factory(lines=_adb_lines(
                            [("A1", "offline", "Pixel"), ("B2", "device", "X10")])))
    assert mgr.refresh(verbose=False) is True
    bus.take()
    # A1 仍是选中态（粘性），仅暂不可用；B2 不受影响
    devs = {it["serial"]: it for it in mgr.get_items()}
    assert devs["A1"]["checked"] is True and devs["A1"]["ok"] is False
    assert devs["B2"]["checked"] is True and devs["B2"]["ok"] is True
    # A1 恢复为 device 后自动恢复为可下发目标
    monkeypatch.setattr(ds.subprocess, "run",
                        _fake_run_factory(lines=_adb_lines(
                            [("A1", "device", "Pixel"), ("B2", "device", "X10")])))
    assert mgr.refresh(verbose=False) is True
    bus.take()
    assert sorted(mgr.selected_serials()) == ["A1", "B2"]


def test_toggle_ignores_unusable_and_toggle_all_scopes(monkeypatch):
    bus, mgr = _fresh(monkeypatch,
                      [("A1", "device", "P"), ("B2", "device", "X"),
                       ("C3", "unauthorized", "Z")])
    mgr.refresh(verbose=False)
    bus.take()
    # 不可操作设备勾选被忽略
    assert mgr.toggle("C3", True) is False
    assert mgr.toggle("A1", True) is True
    # 全选只作用于可操作设备（A1 已勾、B2 未勾 -> 全选）
    want, changed = mgr.toggle_all()
    assert want is True and changed is True
    assert set(mgr.selected_serials()) == {"A1", "B2"}
    # 已全选 -> 再点 = 取消选择
    want2, changed2 = mgr.toggle_all()
    assert want2 is False and changed2 is True
    assert mgr.selected_serials() == []
    # 未全选 -> 再点 = 全选（toggle_all 本质是“补全/取反”，有可用设备就会变）
    want3, changed3 = mgr.toggle_all()
    assert want3 is True and changed3 is True
    assert set(mgr.selected_serials()) == {"A1", "B2"}


def test_toggle_all_no_usable_is_noop(monkeypatch):
    bus, mgr = _fresh(monkeypatch, [("C3", "unauthorized", "Z")])
    mgr.refresh(verbose=False)
    bus.take()
    want, changed = mgr.toggle_all()
    assert want is False and changed is False
    assert mgr.selected_serials() == []


def test_refresh_timeout_reports_and_recovers(monkeypatch):
    bus, mgr = _fresh(monkeypatch, [("A1", "device", "Pixel")])
    mgr.refresh(verbose=False)
    bus.take()
    monkeypatch.setattr(ds.subprocess, "run",
                        _fake_run_factory(exc=subprocess.TimeoutExpired(
                            cmd=["adb", "devices", "-l"], timeout=15)))
    assert mgr.refresh(verbose=False) is False
    events = bus.take()
    assert any(e["kind"] == "status" and "超时" in e["payload"]["text"]
               for e in events)
    # 失败后 _busy 复位，下一次刷新恢复正常
    monkeypatch.setattr(ds.subprocess, "run",
                        _fake_run_factory(lines=_adb_lines(
                            [("A1", "device", "Pixel"), ("B2", "device", "X")])))
    assert mgr.refresh(verbose=False) is True


def test_first_load_zero_devices_still_broadcasts(monkeypatch):
    bus, mgr = _fresh(monkeypatch, [])
    assert mgr.refresh(verbose=False) is True
    events = bus.take()
    assert _kinds(events) == ["devices"]
    assert events[0]["payload"]["items"] == []
    assert events[0]["payload"]["count"] == 0


def test_zero_device_polls_are_silent_after_the_first(monkeypatch):
    """一台设备都没有时，只有**第一次**轮询播报；之后自动轮询必须完全静默。

    回归：core.devices 判定 first_load 的依据是「勾选 / 状态 / 消失记忆全为空」，
    没插设备时这三者永远为空 —— 于是每一轮轮询都算「首次加载」、`changed` 恒为 True，
    程序开着等设备（最常见的空闲状态）每 5 秒广播一次 devices，前端跟着整表重建，
    与 verbose=False「无变化完全静默」的承诺相矛盾。
    """
    bus, mgr = _fresh(monkeypatch, [])
    assert mgr.refresh(verbose=False) is True     # 首轮仍要广播（前端需要空列表）
    assert _kinds(bus.take()) == ["devices"]
    for _ in range(4):
        assert mgr.refresh(verbose=False) is False, "无设备时空转轮询不该再播报"
        assert bus.take() == []


def test_first_device_after_idle_is_announced(monkeypatch):
    """从「一直没有设备」到接入第一台：要广播，并提示「检测到新设备」。"""
    bus, mgr = _fresh(monkeypatch, [])
    mgr.refresh(verbose=False)
    bus.take()
    monkeypatch.setattr(ds.subprocess, "run",
                        _fake_run_factory(lines=_adb_lines([("A1", "device", "Pixel")])))
    assert mgr.refresh(verbose=False) is True
    events = bus.take()
    assert "devices" in _kinds(events)
    texts = [e["payload"].get("text", "") for e in events if e["kind"] == "status"]
    assert any("检测到新设备" in t for t in texts), texts


# ---------------------------------------------------------------------------
# 防「误报断连」：可疑空结果重试 / 失败保留快照 / server 自愈 / 宽限设备展示
# ---------------------------------------------------------------------------

def test_suspicious_empty_result_is_retried_and_absorbed(monkeypatch):
    """上一轮还有设备时，本轮 `adb devices` 返回空 = 可疑，重试后恢复即完全吸收：
    不播 gone、不播短暂失联、列表无感。"""
    bus, mgr = _fresh(monkeypatch, [("A1", "device", "Pixel")])
    assert mgr.refresh(verbose=False) is True
    bus.take()
    # 第 1 次调用返回空（adb server 重启的典型瞬间），重试恢复
    seq = _SeqRun([
        ("lines", "List of devices attached\n"),
        ("lines", _adb_lines([("A1", "device", "Pixel")])),
    ])
    monkeypatch.setattr(ds.subprocess, "run", seq)
    monkeypatch.setattr(ds.time, "sleep", seq.sleep)
    assert mgr.refresh(verbose=False) is False      # 无变化
    assert bus.take() == []                          # 不播报任何异常
    assert [c for c in seq.calls if c[1] == "devices"].__len__() == 2  # 确有一次重试
    assert mgr.get_items()[0]["serial"] == "A1"
    assert mgr.get_items()[0]["ok"] is True


def test_persistent_failure_keeps_last_snapshot(monkeypatch):
    """持续超时：保留上次快照（不播 gone、不清空），提示限频（手动刷新立即播）。"""
    bus, mgr = _fresh(monkeypatch, [("A1", "device", "Pixel")])
    mgr.refresh(verbose=False)
    mgr.toggle("A1", True)
    bus.take()
    seq = _SeqRun([("exc", subprocess.TimeoutExpired(cmd=["adb"], timeout=10))])
    monkeypatch.setattr(ds.subprocess, "run", seq)
    monkeypatch.setattr(ds.time, "sleep", seq.sleep)
    # 第 1 次失败：立即播报一条（含「超时」「保留」），不广播 devices/gone
    assert mgr.refresh(verbose=False) is False
    ev1 = bus.take()
    assert _kinds(ev1) == ["status"]
    assert "超时" in ev1[0]["payload"]["text"]
    assert "保留" in ev1[0]["payload"]["text"]
    assert mgr.get_items() == [{
        "serial": "A1", "state": "device", "model": "Pixel",
        "ok": True, "checked": True}]
    assert mgr.selected_serials() == ["A1"]          # 快照保留：仍可下发
    # 紧接着再失败：限频生效，不再刷屏
    assert mgr.refresh(verbose=False) is False
    assert bus.take() == []
    # 手动刷新不受限频约束，立即播报
    assert mgr.refresh(verbose=True) is False
    assert any("超时" in e["payload"]["text"]
               for e in bus.take() if e["kind"] == "status")


def test_empty_result_with_prior_devices_after_retry_enters_grace(monkeypatch):
    """可疑空结果重试后仍为空（设备确实全拔了）：走宽限流程而不是直接消失。"""
    bus, mgr = _fresh(monkeypatch, [("A1", "device", "Pixel")])
    mgr.refresh(verbose=False)
    bus.take()
    seq = _SeqRun([("lines", "List of devices attached\n"),
                   ("lines", "List of devices attached\n")])
    monkeypatch.setattr(ds.subprocess, "run", seq)
    monkeypatch.setattr(ds.time, "sleep", seq.sleep)
    assert mgr.refresh(verbose=False) is True
    events = bus.take()
    dev_ev = next(e for e in events if e["kind"] == "devices")
    # 宽限内：不视为 gone，但以 reconnecting 置灰留在快照里
    assert dev_ev["payload"]["gone"] == []
    absent = [i for i in dev_ev["payload"]["items"] if i["serial"] == "A1"]
    assert absent and absent[0]["state"] == "reconnecting"
    assert absent[0]["ok"] is False


def test_absent_device_stays_visible_with_sticky_check(monkeypatch):
    """宽限内设备：置灰展示、保留勾选与型号、不作为下发目标；重连后自动恢复。"""
    bus, mgr = _fresh(monkeypatch, [("A1", "device", "Pixel"),
                                    ("B2", "device", "X10")])
    mgr.refresh(verbose=False)
    mgr.toggle("A1", True)
    mgr.toggle("B2", True)
    bus.take()
    monkeypatch.setattr(ds.subprocess, "run",
                        _fake_run_factory(lines=_adb_lines(
                            [("A1", "device", "Pixel")])))
    assert mgr.refresh(verbose=False) is True
    bus.take()
    items = {i["serial"]: i for i in mgr.get_items()}
    b2 = items["B2"]
    assert b2["state"] == "reconnecting" and b2["ok"] is False
    assert b2["checked"] is True                     # 勾选记忆保留
    assert b2["model"] == "X10"                      # 最后已知型号保留（不变 unknown）
    assert mgr.selected_serials() == ["A1"]          # 宽限设备不是下发目标


def test_start_server_self_heals_after_consecutive_failures(monkeypatch):
    """连续失败 2 次后自动 `adb start-server` 自愈，恢复后失败计数清零。"""
    bus, mgr = _fresh(monkeypatch, [("A1", "device", "Pixel")])
    mgr.refresh(verbose=False)
    bus.take()
    ok_lines = _adb_lines([("A1", "device", "Pixel")])
    state = {"n": 0}

    def fake_run(cmd, **kw):
        if cmd[1] == "start-server":
            return type("R", (), {"stdout": "", "stderr": ""})()
        state["n"] += 1
        if state["n"] <= 4:      # 前 4 次 devices 调用（2 轮刷新 × 重试）全失败
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=10)
        return type("R", (), {"stdout": ok_lines, "stderr": ""})()

    monkeypatch.setattr(ds.subprocess, "run", fake_run)
    monkeypatch.setattr(ds.time, "sleep", lambda s: None)
    assert mgr.refresh(verbose=False) is False       # 失败轮 1（streak=1）
    assert mgr.refresh(verbose=False) is False       # 失败轮 2（streak=2）
    assert bus.take()                                # 吞掉失败播报
    assert mgr.refresh(verbose=False) is False       # 轮 3：先自愈再轮询 -> 恢复
    assert state["n"] == 5                           # 自愈后的那次 devices 成功
    assert mgr._fail_streak == 0
    assert mgr.get_items()[0]["ok"] is True
