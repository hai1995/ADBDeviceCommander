# -*- coding: utf-8 -*-
"""指令台多工作区（子 tab）：会话隔离、输出路由、停止与关闭的单测。

需求背景：用户要求「指令台 + 指令输出」能开出 N 个独立工作区，每个子 tab
各干各的。这里的核心不是「多几块面板」，而是**会话隔离**——如果只做面板、
后端仍共用一条 shell，那么在工作区 2 点「执行」只是排到工作区 1 的命令后面
等着，面板半天没有一行输出，用户会以为命令没发出去（正是要避免的静默误导）。

因此本文件的断言全落在行为上：
  * 两个工作区各自一条会话（互不顶替）；
  * 各自输出各进各的面板（事件带 ws，默认工作区不带、与旧载荷一字不差）；
  * 一个工作区卡在长命令里时，另一个仍能立刻开始（真的并行，不是排队）；
  * 「停止」只停自己那一条，不会顺手掐掉别人的活；
  * 关闭工作区真的杀掉它的会话（不留幽灵 powershell）；
  * 状态播报在多工作区时带工作区名，能分清「谁跑完了」。
"""
import threading
import time

import pytest

from backend.controller import WebApi


CMDS = [
    {"id": "pc", "name": "跑脚本", "labels": ["通用"],
     "commands": [{"command": "git status", "delay": 0}]},
    {"id": "dev", "name": "设备时间", "labels": ["设备"],
     "commands": [{"command": "adb shell date", "delay": 0}]},
]


class FakeSession:
    """替身 ShellSession：记录 run 调用，不启动 powershell。"""

    def __init__(self, output_callback=None, on_dir_change=None, **kw):
        self.output_callback = output_callback
        self.on_dir_change = on_dir_change
        self.current_dir = r"C:\adb_ws"
        self.in_interactive_shell = False
        self.calls = []
        self.killed = 0
        self.tag = ""          # 由用例标注是哪个工作区的会话，便于断言

    def run(self, script, timeout=None, interactive=False):
        self.calls.append(
            {"script": script, "interactive": interactive, "timeout": timeout})
        if self.output_callback:
            self.output_callback("输出回显: " + script)
        return True

    def kill(self):
        self.killed += 1
        self.in_interactive_shell = False

    def leave_interactive(self):
        self.in_interactive_shell = False


class BlockingSession(FakeSession):
    """卡在长命令里的会话：run() 阻塞到 kill()（与真实 PowerShell 会话一致）。"""

    def __init__(self, output_callback=None, on_dir_change=None, **kw):
        super().__init__(output_callback, on_dir_change=on_dir_change, **kw)
        self.started = threading.Event()
        self.release = threading.Event()

    def run(self, script, timeout=None, interactive=False):
        self.calls.append(
            {"script": script, "interactive": interactive, "timeout": timeout})
        if self.output_callback:
            self.output_callback("输出回显: " + script)
        self.started.set()
        return self.release.wait(5.0)

    def kill(self):
        super().kill()
        self.release.set()


def _seed_devices(api):
    api.devices.device_state = {"A1": "device"}
    api.devices.device_model = {"A1": "Pixel"}
    api.devices.device_checked = {"A1": True}


def _make_api(session=None):
    made = []

    def factory(**kw):
        s = FakeSession(**kw)
        made.append(s)
        return s

    api = WebApi(session_factory=factory, auto_update=False)
    api.state.commands = list(CMDS)
    api.session = session or FakeSession(output_callback=api._on_session_output)
    api._made_sessions = made        # 便于断言「w2 真的另起了一条会话」
    _seed_devices(api)
    return api


def _wait(cond, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def _events(api):
    out = {}
    for e in api.bus.take():
        out.setdefault(e["kind"], []).append(e["payload"])
    return out


def _console_texts(payloads, ws=None):
    """取某工作区的输出文本；ws=None 表示「不带 ws 字段」的那一路（默认工作区）。"""
    texts = []
    for p in payloads:
        if ws is None:
            if "ws" not in p:
                texts.append(p.get("text", ""))
        elif p.get("ws") == ws:
            texts.append(p.get("text", ""))
    return texts


def _wait_console(api, ws=None, needle=""):
    """边等边收 console 事件（事件被 take 走就没了，不能重复取）。

    返回 (是否等到, 收到的全部 console 载荷)。
    """
    got = []

    def check():
        for e in api.bus.take():
            if e["kind"] == "console":
                got.append(e["payload"])
        return any(needle in t for t in _console_texts(got, ws))

    return _wait(check), got


# ---------------------------------------------------------------- 会话隔离
def test_second_workspace_uses_its_own_session():
    """工作区 2 必须有自己的会话，不能把命令塞进工作区 1 的 shell。"""
    api = _make_api()
    assert api.run_command("pc", "w2") == {"ok": True}
    assert _wait(lambda: not api._ws_busy.get("w2", False)) is True

    assert api.session.calls == [], "工作区 1 的会话不该收到工作区 2 的命令"
    sess2 = api._ws_sessions.get("w2")
    assert sess2 is not None, "工作区 2 应当有一条自己的会话"
    assert [c["script"] for c in sess2.calls] == ["git status"]
    assert sess2 is not api.session


def test_default_workspace_keeps_legacy_payload():
    """默认工作区的输出事件**不带** ws 字段：单工作区时代的载荷一字不差。

    老前端（以及既有测试）按 `{kind, text}` 精确断言过这些事件，多一个字段
    就是破坏性变更，且没有任何收益。
    """
    api = _make_api()
    api._on_session_output("hello")
    payloads = _events(api)["console"]
    assert payloads == [{"kind": "out", "text": "hello"}]


def test_output_is_routed_to_its_own_workspace():
    api = _make_api()
    api.run_command("pc", "w2")
    ok, got = _wait_console(api, "w2", "git status")
    assert ok, "工作区 2 的输出没送到自己那条通道（ws=w2）"

    api.bus.take()          # 清空，单独看默认工作区
    api.run_command("pc")
    ok, got = _wait_console(api, None, "git status")
    assert ok, "默认工作区的输出丢了（不带 ws 的那一路）"
    assert not _console_texts(got, "w2"), "默认工作区的输出不该带 ws 字段"

    api.bus.take()          # 清空，验证不串台
    api.run_command("dev", "w2")
    assert _wait(lambda: not api._ws_busy.get("w2", False))
    ps = _events(api)["console"]
    assert any("date" in t for t in _console_texts(ps, "w2")), ps
    assert not any("date" in t for t in _console_texts(ps)), "不能串到工作区 1"


# ---------------------------------------------------------------- 并行
def test_two_workspaces_run_in_parallel():
    """工作区 1 卡在长命令里时，工作区 2 必须能立刻开始（不是排队）。"""
    api = _make_api(session=BlockingSession(output_callback=None))
    api.session.output_callback = api._on_session_output

    api.run_command("pc")               # w1：阻塞
    assert _wait(lambda: api.session.started.is_set()), "工作区 1 的长命令没起来"

    api.run_command("pc", "w2")         # w2：同一时刻
    sess2 = api._ws_sessions.get("w2")
    t0 = time.time()
    assert _wait(lambda: sess2 is not None
                 and sess2 is not api.session
                 and len(sess2.calls) == 1, timeout=2.0), \
        "工作区 2 的命令被工作区 1 的长命令挡住了（应为各自独立会话）"
    assert time.time() - t0 < 2.0

    api.session.release.set()           # 放行 w1
    assert _wait(lambda: not api._ws_busy.get("w2", False))


# ---------------------------------------------------------------- 停止
def test_stop_only_kills_its_own_workspace():
    api = _make_api()
    api.run_command("pc", "w2")
    assert _wait(lambda: not api._ws_busy.get("w2", False))

    assert api.stop_run("w2") == {"ok": True}
    sess2 = api._ws_sessions["w2"]
    assert sess2.killed >= 1, "停止应当 kill 工作区 2 自己的会话"
    assert api.session.killed == 0, "工作区 1 的会话不能被殃及"


def test_stop_state_is_per_workspace():
    """停止按钮态必须按工作区广播，否则一个 tab 会把另一个的按钮点亮/熄掉。"""
    api = _make_api(session=BlockingSession(output_callback=None))
    api.session.output_callback = api._on_session_output
    api.bus.take()

    api.run_command("pc", "w2")
    assert _wait(lambda: any(p.get("ws") == "w2" and p.get("running") is True
                             for p in _events(api).get("stop_state", []))), \
        "工作区 2 开始执行要广播 running=True 且带 ws"
    assert api.state.is_busy() is False, "工作区 2 在跑不该点亮工作区 1 的停止按钮"
    api.session.release.set()


# ---------------------------------------------------------------- 关闭 / 登记
def test_close_workspace_kills_its_session():
    api = _make_api()
    api.run_command("pc", "w2")
    assert _wait(lambda: "w2" in api._ws_sessions)
    sess2 = api._ws_sessions["w2"]

    assert api.ws_close("w2") == {"ok": True}
    assert "w2" not in api._ws_sessions
    assert sess2.killed >= 1, "关闭工作区必须杀掉它的会话（否则残留 powershell）"


def test_default_workspace_cannot_be_closed():
    api = _make_api()
    res = api.ws_close("w1")
    assert res["ok"] is False and "默认工作区" in res["reason"]
    assert api.session is not None


def test_ws_open_registers_name_and_enforces_limit():
    api = _make_api()
    res = api.ws_open("w2", "抓日志")
    assert res == {"ok": True, "ws": "w2", "name": "抓日志"}
    # 占满上限（w2 已占 1 个，再开 WS_MAX-1 个正好满）
    for i in range(3, 2 + WebApi.WS_MAX):
        assert api.ws_open("w%d" % i)["ok"] is True
    over = api.ws_open("w99")
    assert over["ok"] is False and "上限" in over["reason"]


def test_ws_open_rename_updates_status_prefix():
    """同一个 id 再登记一次 = 改名，状态栏前缀跟着变。

    这是前端「双击 tab 改名后要通知后端」那一步的存在理由：不通知，tab 上写着
    「刷机」、状态栏还是「[工作区 2] ✓ 完成」，用户以为是别人跑完了。
    """
    api = _make_api()
    api.ws_open("w2", "工作区 2")
    assert api._ws_label("w2") == "工作区 2"

    res = api.ws_open("w2", "刷机")
    assert res == {"ok": True, "ws": "w2", "name": "刷机"}, res
    assert api._ws_label("w2") == "刷机"
    # 改名不是「又开了一个」：登记表里仍然只有它自己
    assert list(api._ws_names) == ["w2"], api._ws_names


def test_ws_open_rename_allowed_at_capacity():
    """已开满 8 个时仍能改名 —— 上限只挡新建。

    若把改名当新建走同一个判断，用户开满工作区之后就再也改不了名（点回车
    毫无反应），而这恰恰是最需要靠名字区分的时候。
    """
    api = _make_api()
    for i in range(2, 2 + WebApi.WS_MAX):
        assert api.ws_open("w%d" % i)["ok"] is True
    assert api.ws_open("w99")["ok"] is False, "新建该被上限挡住"
    res = api.ws_open("w2", "刷机")
    assert res["ok"] is True and res["name"] == "刷机", res


def test_ws_open_blank_name_keeps_previous():
    """空名字不改动已有名字：前端拒绝空名，后端也不能被空串抹成「无名字」。"""
    api = _make_api()
    api.ws_open("w2", "抓日志")
    api.ws_open("w2", "   ")
    assert api._ws_label("w2") == "抓日志"


def test_workspace_name_prefixes_status_in_multi_workspace():
    """多工作区时状态播报带工作区名：不然「✓ 完成」根本分不清是谁的。

    默认工作区不加前缀——单工作区时代的文案一字不变（既有断言依赖它）。
    """
    api = _make_api()
    api.ws_open("w2", "工作区 2")
    api.bus.take()

    api.run_command("pc", "w2")
    assert _wait(lambda: not api._ws_busy.get("w2", False))
    texts2 = [p["text"] for p in _events(api).get("status", [])]
    assert any(t.startswith("[工作区 2] ") for t in texts2), texts2
    assert any("完成" in t for t in texts2), texts2

    api.bus.take()
    api.run_command("pc")
    assert _wait(lambda: not api.state.is_busy())
    texts1 = [p["text"] for p in _events(api).get("status", [])]
    assert any(t == "✓ 完成" for t in texts1), "默认工作区不该带任何前缀"
    assert not any(t.startswith("[") for t in texts1), texts1


def test_clear_output_is_scoped_to_workspace():
    api = _make_api()
    api.clear_output("w2")
    api.clear_output()
    payloads = _events(api)["console"]
    assert {"kind": "clear", "ws": "w2"} in payloads
    assert {"kind": "clear"} in payloads


def test_shutdown_kills_every_workspace_session():
    api = _make_api()
    api.run_command("pc", "w2")
    api.run_command("pc", "w3")
    assert _wait(lambda: "w2" in api._ws_sessions and "w3" in api._ws_sessions)
    s2, s3 = api._ws_sessions["w2"], api._ws_sessions["w3"]

    api.shutdown()
    assert s2.killed >= 1 and s3.killed >= 1, "关窗必须收掉所有工作区的会话"
    assert api._ws_sessions == {}


@pytest.fixture(autouse=True)
def _isolate_prefs(tmp_path, monkeypatch):
    """每个用例一份独立的 config.json（避免读到开发机的真实配置）。"""
    import core.prefs as prefs
    cfg = tmp_path / "config.json"
    monkeypatch.setattr(prefs, "prefs_path", lambda: str(cfg), raising=False)
    from conftest import patch_ctrl
    patch_ctrl(monkeypatch, "prefs_path", lambda: str(cfg))
    yield
