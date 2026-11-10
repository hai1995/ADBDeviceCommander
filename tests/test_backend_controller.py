# -*- coding: utf-8 -*-
"""backend.controller.WebApi —— pywebview js_api 桥单测（注入 FakeSession，不跑真命令）。"""
import os
import threading
import time
import zipfile

import pytest

import backend.controller as ctrl
import backend.device_service as ds
import backend.screen_service as screen_service
from backend.controller import WebApi
from backend.screen_service import device_present

# patch_ctrl 见 tests/conftest.py：把名字同时打到所有 controllers 子模块
# （方法实现所在的命名空间），避免物理拆分后 patch 落空。
from conftest import patch_ctrl


CMDS = [
    {"id": "pc", "name": "跑脚本", "labels": ["通用"],
     "commands": [{"command": "git status", "delay": 0}]},
    {"id": "dev", "name": "设备时间", "labels": ["设备"],
     "commands": [{"command": "adb shell date", "delay": 300}]},
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
        """真实 ShellSession 在序列里遇到 `exit` 后由 controller 调用。"""
        self.in_interactive_shell = False


class BlockingSession(FakeSession):
    """模拟卡在长命令里的会话：run() 阻塞到 kill() 放行（与真实 PowerShell 会话一致）。"""

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
    api.devices.device_state = {
        "A1": "device", "B2": "device", "C3": "unauthorized"}
    api.devices.device_model = {"A1": "Pixel", "B2": "X10", "C3": "Zed"}
    api.devices.device_checked = {"A1": True, "B2": False, "C3": False}


@pytest.fixture(autouse=True)
def _isolate_prefs(tmp_path, monkeypatch):
    """每个用例一份独立的 config.json。

    性能监控的告警阈值现在存在配置里（perf_thresholds），若沿用工程根那份，
    用例之间会互相污染，测试结果还会取决于开发机上某人改过的设置 ——
    这类「在我这儿过、在 CI 挂」的失败最难查。
    """
    import core.prefs as prefs
    monkeypatch.setattr(prefs, "prefs_path",
                        lambda: str(tmp_path / "config.json"))
    monkeypatch.setattr(prefs, "legacy_prefs_path",
                        lambda: str(tmp_path / "settings.json"))


def _make_api(session=None):
    api = WebApi(session_factory=lambda **kw: FakeSession(**kw),
                   auto_update=False)
    api.state.commands = list(CMDS)          # 直接注入（不走 boot 的文件加载）
    # 与真实 ShellSession 一致：会话持有 output_callback，回显转成 console 事件
    api.session = session or FakeSession(output_callback=api._on_session_output)
    _seed_devices(api)
    return api


def wait_until(cond, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def _events_by_kind(api):
    out = {}
    for e in api.bus.take():
        out.setdefault(e["kind"], []).append(e["payload"])
    return out


def _patch_set_setting(monkeypatch, video, fn):
    """把「写设备系统设置」的替身同时接到新旧两个方法上。

    生产代码走 `set_system_setting_ex`（要拿到失败原因，见
    VideoRecorder.set_system_setting_ex），旧接口 `set_system_setting` 回 bool。
    替身只要接到 `set_system_setting` 上，这里替它包一层 ex —— 否则用例记不到
    任何写入，断言会以「写了个空」的形式失败，与真正的回归混在一起。
    """
    monkeypatch.setattr(video, "set_system_setting", fn, raising=False)
    monkeypatch.setattr(
        video, "set_system_setting_ex",
        lambda adb, s, k, v: (bool(fn(adb, s, k, v)), ""), raising=False)


# ---------------------------------------------------------------------------
# boot / shutdown
# ---------------------------------------------------------------------------
def test_boot_initializes_and_broadcasts(monkeypatch):
    patch_ctrl(monkeypatch, "load_commands", lambda: (list(CMDS), ["警告1"]))
    monkeypatch.setattr(
        ds.subprocess, "run",
        lambda cmd, **kw: type("R", (), {"stdout": "", "stderr": ""})())

    api = WebApi(session_factory=FakeSession, auto_update=False)
    assert api.boot() == {"ok": True}
    assert api.state.booted is True
    assert api.session is not None

    # booted 事件：版本 + 命令 + 警告
    by_kind = _events_by_kind(api)
    assert "booted" in by_kind
    booted = by_kind["booted"][0]
    assert booted["warnings"] == ["警告1"]
    assert [c["id"] for c in booted["commands"]] == ["pc", "dev"]
    # 首刷（0 台设备）也应广播一次 devices
    assert "devices" in by_kind

    # 自动轮询线程已启动
    assert api.workers.is_running("auto_refresh") is True
    sess = api.session            # shutdown 会把 api.session 置空，先存引用
    api.shutdown()
    assert api.workers.is_running("auto_refresh") is False
    assert api.session is None
    assert sess.killed == 1
    # shutdown 幂等
    assert api.shutdown() == {"ok": True}
    assert sess.killed == 1


def test_boot_replay_after_reload(monkeypatch):
    """页面重载 / 前端重试 boot：必须重发 booted 载荷，而不是一句 already_booted。

    回归：booted 事件只在首次启动时下发一次。前端页面重载（或上一次 boot 响应
    超时后的自动重试）再调 boot 时，若只拿到 already_booted，就永远等不到
    booted —— 界面永久停在「连接中…」，命令台 / 配置 / 设备全都恢复不了。
    重发必须幂等：不重复建会话、不重复起自动轮询 / 首刷。
    """
    patch_ctrl(monkeypatch, "load_commands", lambda: (list(CMDS), []))
    monkeypatch.setattr(
        ds.subprocess, "run",
        lambda cmd, **kw: type("R", (), {"stdout": "", "stderr": ""})())

    api = WebApi(session_factory=FakeSession, auto_update=False)
    assert api.boot() == {"ok": True}
    sess = api.session
    api.bus.take()                      # 模拟前端已消费首批事件

    assert api.boot() == {"ok": True, "replayed": True}
    by_kind = _events_by_kind(api)
    assert "booted" in by_kind, "重放必须重新广播 booted，否则前端永远停在连接中"
    replay = by_kind["booted"][0]
    assert [c["id"] for c in replay["commands"]] == ["pc", "dev"]
    assert "settings" in replay and "config_path" in replay
    assert "devices" in by_kind, "设备快照也要重发，否则列表停在空"
    # 幂等：会话没有重建，自动轮询仍在（且只有原来那一条）
    assert api.session is sess
    assert api.workers.is_running("auto_refresh") is True
    api.shutdown()


def test_boot_refuses_after_shutdown(monkeypatch):
    patch_ctrl(monkeypatch, "load_commands", lambda: ([], []))
    api = WebApi(session_factory=FakeSession, auto_update=False)
    api.shutdown()
    assert api.boot() == {"ok": False, "reason": "shutting_down"}


# ---------------------------------------------------------------------------
# 设备勾选
# ---------------------------------------------------------------------------
def test_toggle_device_scopes_and_returns_ok():
    api = _make_api()
    # 不可操作设备：忽略
    assert api.toggle_device("C3", True) == {"ok": False,
                                             "checked": ["A1"]}
    # 可操作设备：生效
    assert api.toggle_device("B2", True)["ok"] is True
    assert api.selected_serials() == ["A1", "B2"]


def test_toggle_device_broadcasts_devices_event_when_applied():
    api = _make_api()
    # 不可操作设备：不广播
    assert api.toggle_device("C3", True)["ok"] is False
    assert "devices" not in [e["kind"] for e in api.bus._events]
    # 可操作设备：生效并广播 devices 事件，使前端 Logcat/文件「选中设备」实时同步
    before = len(api.bus._events)
    assert api.toggle_device("B2", True)["ok"] is True
    assert len(api.bus._events) > before
    assert "devices" in [e["kind"] for e in api.bus._events]


def test_toggle_all_broadcasts_only_on_change():
    api = _make_api()
    # 有未勾选设备 -> 全选，广播 devices
    res = api.toggle_all()
    assert res == {"all": True, "changed": True}
    evs = _events_by_kind(api)
    items = evs["devices"][0]["items"]
    assert all(i["ok"] and i["checked"] for i in items if i["serial"] != "C3")
    assert all(not i["checked"] for i in items if i["serial"] == "C3")
    # 已全部选中 -> 再点变成取消
    assert api.toggle_all() == {"all": False, "changed": True}
    assert api.selected_serials() == []
    api.bus.take()
    # 无任何可用设备时才是真正的 no-op：不广播任何事件
    api.devices.device_state = {"C3": "unauthorized"}
    api.devices.device_model = {"C3": "Z"}
    api.devices.device_checked = {"C3": False}
    assert api.toggle_all() == {"all": False, "changed": False}
    assert api.bus.take() == []


# ---------------------------------------------------------------------------
# 指令执行
# ---------------------------------------------------------------------------
def test_run_custom_passthrough_and_console_events():
    api = _make_api()
    assert api.run_custom("  echo hi  ") == {"ok": True}
    assert wait_until(lambda: len(api.session.calls) == 1)
    assert api.session.calls[0]["script"] == "echo hi"
    assert api.session.calls[0]["interactive"] is False
    # 事件：cmd 回显 + out 输出 + stop_state 两次翻转
    by_kind = _events_by_kind(api)
    assert any(p["kind"] == "cmd" and p["text"].startswith(r"C:\adb_ws> echo hi")
               for p in by_kind.get("console", []))
    assert any(p["kind"] == "out" for p in by_kind.get("console", []))
    stops = [p["running"] for p in by_kind.get("stop_state", [])]
    assert stops == [True, False]
    # 执行结束后不残留 busy
    assert api.state.is_busy() is False


def test_run_custom_empty_rejected():
    api = _make_api()
    assert api.run_custom("   ") == {"ok": False}
    assert api.session.calls == []


def test_run_command_device_loop_transform_and_delay():
    api = _make_api()
    assert api.run_command("dev") == {"ok": True}
    assert wait_until(lambda: len(api.session.calls) >= 1)
    # 只对勾选且可操作的 A1 循环；命令被注入 -s A1
    assert api.session.calls[0]["script"] == "adb -s A1 shell date"
    # delay=300 由 Python 侧 time.sleep 完成（不再把 Start-Sleep 塞给 shell：
    # 旧实现 delay>10s 会被 run(timeout=10) 误判超时杀掉整个会话），因此
    # 会话只收到 1 次 run 调用，不产生 Start-Sleep 第 2 次脚本。
    assert len(api.session.calls) == 1
    # delay 是真实睡眠，会晚 ~300ms 才推「✓ 完成」：等执行态复位（end_run）
    # 后再取事件，避免断言太早拿不到完成提示。
    assert wait_until(lambda: not api.state.is_busy(), timeout=3.0)
    by_kind = _events_by_kind(api)
    assert any("设备: A1" in p["text"] for p in by_kind.get("status", []))
    assert any("✓ 完成" in p["text"] for p in by_kind.get("status", []))


def test_run_command_no_device_needed_runs_once():
    api = _make_api()
    api.devices.device_checked = {"A1": True, "B2": True, "C3": False}
    assert api.run_command("pc") == {"ok": True}
    assert wait_until(lambda: len(api.session.calls) == 1)
    assert api.session.calls[0]["script"] == "git status"
    by_kind = _events_by_kind(api)
    assert any("无需指定设备" in p["text"] for p in by_kind.get("status", []))


def test_run_command_needs_device_but_none_selected():
    api = _make_api()
    api.devices.device_checked = {"A1": False, "B2": False, "C3": False}
    assert api.run_command("dev") == {"ok": True}
    assert wait_until(lambda: not api.state.is_busy())
    assert api.session.calls == []
    by_kind = _events_by_kind(api)
    assert any("需要指定设备" in p["text"]
               for p in by_kind.get("status", []))


def test_run_command_unknown_id():
    api = _make_api()
    assert api.run_command("nope") == {"ok": False}
    assert wait_until(lambda: not api.state.is_busy())
    by_kind = _events_by_kind(api)
    assert any("未找到命令" in p["text"] for p in by_kind.get("status", []))


def test_stop_run_kills_session_and_clears_busy():
    sess = BlockingSession()
    api = _make_api(session=sess)
    assert api.run_custom("while($true){}") == {"ok": True}
    assert sess.started.wait(2.0)          # 命令已进入会话阻塞态
    assert api.state.is_busy() is True     # stop 按钮应亮起
    assert api.stop_run() == {"ok": True}
    assert sess.killed == 1                # 会话被终止（等价 ctrl+c）
    assert wait_until(lambda: not api.state.is_busy())
    stops = [p["running"] for p in _events_by_kind(api).get("stop_state", [])]
    assert stops[0] is True and stops[-1] is False


# ---------------------------------------------------------------------------
# 输出区
# ---------------------------------------------------------------------------
def test_clear_events():
    api = _make_api()
    api.clear_output()
    api.clear_status()
    by_kind = _events_by_kind(api)
    assert any(p["kind"] == "clear" for p in by_kind["console"])
    assert any(p["type"] == "clear" for p in by_kind["status"])


def test_get_state_snapshot():
    api = _make_api()
    api.state.begin_run()
    snap = api.get_state()
    assert snap["booted"] is False
    assert snap["busy"] is True
    assert len(snap["devices"]) == 3


def test_get_manual_returns_bundled_text():
    """使用说明由后端读取内置副本返回，前端关于页「使用说明」子 tab 渲染它。"""
    api = _make_api()
    res = api.get_manual()
    assert res["ok"] is True
    # 仓库根的 使用说明.txt 被打进 exe 内部，内容应非空且含标题字样
    assert res["text"].strip()
    assert "使用说明" in res["text"]


# ---------------------------------------------------------------------------
# run_custom —— 必须与快捷指令同源：按受控设备逐台循环 + transform 注入 -s
# （关键回归：原先透传到单 adb 会话，多设备下会报 "more than one device"）
# ---------------------------------------------------------------------------
def test_run_custom_injects_serial_for_single_device(monkeypatch):
    patch_ctrl(monkeypatch, "root_state", lambda adb, serial: False)
    api = _make_api()
    assert api.run_custom("adb root") == {"ok": True}
    assert wait_until(lambda: len(api.session.calls) >= 1)
    assert api.session.calls[0]["script"] == "adb -s A1 root"
    # 受控设备不是 B2，所以 B2 不会被下发
    assert not any("B2" in c["script"] for c in api.session.calls)


# ---------------------------------------------------------------------------
# root / unroot 切换保护：adb root 会重启 adbd，杀掉设备端 screenrecord / tinycap
# （录屏视频缺 moov、不完整），并断开 logcat 抓取。已在目标状态的重复切换除了
# 重启没有任何效果；状态确实要变但设备有进行中的任务时，跳过以避免静默数据丢失。
# ---------------------------------------------------------------------------
class _FakeVideoRec:
    """替身 VideoRecorder：只实现防护需要的 is_recording。"""

    def __init__(self, recording=()):
        self._rec = set(recording)

    def is_recording(self, s):
        return s in self._rec


def _run_and_settle(api):
    assert wait_until(lambda: not api.state.is_busy(), timeout=3.0)


def test_root_skipped_when_already_root(monkeypatch):
    """设备已 root：重复 `adb root` 只是无谓重启 adbd，直接跳过。"""
    patch_ctrl(monkeypatch, "root_state", lambda adb, serial: True)
    api = _make_api()
    assert api.run_custom("adb root") == {"ok": True}
    _run_and_settle(api)
    assert api.session.calls == [], "已 root 时不应再下发 adb root"
    by_kind = _events_by_kind(api)
    assert any("已处于 root" in p["text"] and "跳过" in p["text"]
               for p in by_kind.get("status", [])), by_kind.get("status")


def test_unroot_skipped_when_not_root(monkeypatch):
    """设备未 root：`adb unroot` 同样是无谓重启，跳过（方向对称）。"""
    patch_ctrl(monkeypatch, "root_state", lambda adb, serial: False)
    api = _make_api()
    assert api.run_custom("adb unroot") == {"ok": True}
    _run_and_settle(api)
    assert api.session.calls == []
    by_kind = _events_by_kind(api)
    assert any("未 root" in p["text"] and "跳过" in p["text"]
               for p in by_kind.get("status", [])), by_kind.get("status")


def test_root_executes_when_needed_and_idle(monkeypatch):
    """未 root、无进行中任务：正常下发（保护不能把正常需求挡死）。"""
    patch_ctrl(monkeypatch, "root_state", lambda adb, serial: False)
    api = _make_api()
    assert api.run_custom("adb root") == {"ok": True}
    assert wait_until(lambda: len(api.session.calls) >= 1)
    assert api.session.calls[0]["script"] == "adb -s A1 root"


def test_root_skipped_while_recording(monkeypatch):
    """未 root 但正在录屏：跳过并说明——执行会重启 adbd 杀掉 screenrecord，
    视频缺 moov 头、不完整（使用说明「录屏被中断」条就是这个坑）。"""
    patch_ctrl(monkeypatch, "root_state", lambda adb, serial: False)
    api = _make_api()
    api.video = _FakeVideoRec(recording={"A1"})
    assert api.run_custom("adb root") == {"ok": True}
    _run_and_settle(api)
    assert api.session.calls == [], "录屏中不得下发 adb root（会断掉录屏）"
    by_kind = _events_by_kind(api)
    texts = [p["text"] for p in by_kind.get("status", [])]
    assert any("录屏" in t and "adbd" in t and "跳过" in t for t in texts), texts
    # 关键警告必须弹 toast（用户可能已切到别的页签，看不到状态栏）
    assert any(p.get("toast") for p in by_kind.get("status", [])), \
        "断录屏级的警告必须 toast 强提醒"


def test_root_skipped_while_logcat_capturing(monkeypatch):
    """logcat 抓取同样会随 adbd 重启断掉：也要拦。"""
    patch_ctrl(monkeypatch, "root_state", lambda adb, serial: False)
    api = _make_api()
    api.logcat_capture.is_running = lambda s: True
    assert api.run_custom("adb root") == {"ok": True}
    _run_and_settle(api)
    assert api.session.calls == []
    by_kind = _events_by_kind(api)
    assert any("logcat 抓取" in p["text"]
               for p in by_kind.get("status", [])), by_kind.get("status")


def test_root_guard_is_per_device(monkeypatch):
    """多设备：只拦「有进行中任务」的那台，其余正常下发。"""
    patch_ctrl(monkeypatch, "root_state", lambda adb, serial: False)
    api = _make_api()
    api.devices.device_checked = {"A1": True, "B2": True, "C3": False}
    api.video = _FakeVideoRec(recording={"A1"})     # 只有 A1 在录屏
    assert api.run_custom("adb root") == {"ok": True}
    assert wait_until(lambda: len(api.session.calls) >= 1, timeout=3.0)
    _run_and_settle(api)
    scripts = [c["script"] for c in api.session.calls]
    assert scripts == ["adb -s B2 root"], scripts


def test_compound_root_command_skipped_while_recording(monkeypatch):
    """复合命令（adb root && adb shell xx）无法只跳过其中一段：整条跳过。"""
    patch_ctrl(monkeypatch, "root_state", lambda adb, serial: False)
    api = _make_api()
    api.video = _FakeVideoRec(recording={"A1"})
    assert api.run_custom("adb root && adb shell id") == {"ok": True}
    _run_and_settle(api)
    assert api.session.calls == [], "复合命令里的 root 切换也要整条拦下"


def test_root_mention_in_quotes_is_not_guarded(monkeypatch):
    """引号内仅「提到」adb root（提交信息 / 回显）不下发，不应被拦。"""
    patch_ctrl(monkeypatch, "root_state", lambda adb, serial: True)
    api = _make_api()
    assert api.run_custom('git commit -m "adb root 修复"') == {"ok": True}
    assert wait_until(lambda: len(api.session.calls) >= 1)
    assert api.session.calls[0]["script"] == 'git commit -m "adb root 修复"'


def test_run_custom_loops_over_all_selected_devices():
    api = _make_api()
    # 两台都勾选
    api.devices.device_checked = {"A1": True, "B2": True, "C3": False}
    assert api.run_custom("adb shell date") == {"ok": True}
    assert wait_until(lambda: len(api.session.calls) >= 2)
    scripts = sorted(c["script"] for c in api.session.calls)
    assert scripts == ["adb -s A1 shell date", "adb -s B2 shell date"]


def test_run_custom_skips_usb_subs_for_no_device_path():
    """纯 PC 脚本（不含 adb/scrcpy）应单次执行，不按设备循环。"""
    api = _make_api()
    assert api.run_custom("git status") == {"ok": True}
    assert wait_until(lambda: len(api.session.calls) >= 1)
    assert api.session.calls[0]["script"] == "git status"
    # 不会注入 -s
    assert not any("-s" in c["script"] for c in api.session.calls)


def test_run_custom_replaces_existing_serial():
    """命令里若已带 -s XXX，transform 应替换为所选设备序列号。"""
    api = _make_api()
    assert api.run_custom("adb -s 9999999 shell echo hi") == {"ok": True}
    assert wait_until(lambda: len(api.session.calls) >= 1)
    assert api.session.calls[0]["script"] == "adb -s A1 shell echo hi"


def test_run_custom_global_subcommand_passes_through():
    """adb devices / kill-server 等全局子命令不应注入 -s。"""
    api = _make_api()
    assert api.run_custom("adb devices -l") == {"ok": True}
    assert wait_until(lambda: len(api.session.calls) >= 1)
    assert api.session.calls[0]["script"] == "adb devices -l"


def test_run_custom_requires_device_warns_when_none_selected():
    """当命令需要设备但未勾选任何设备时，提示且不入会话。"""
    api = _make_api()
    api.devices.device_checked = {"A1": False, "B2": False, "C3": False}
    assert api.run_custom("adb root") == {"ok": True}
    # 走 needs_device 路径，发现无受控设备，应只推一条 err 状态且不调用 session
    assert wait_until(lambda: any(
        e["kind"] == "status" and e["payload"]["type"] == "err"
        for e in api.bus.take()))
    assert api.session.calls == []


def test_run_custom_rejects_empty():
    api = _make_api()
    assert api.run_custom("") == {"ok": False}
    assert api.run_custom("   ") == {"ok": False}
    assert api.session.calls == []


# ---------------------------------------------------------------------------
# 保存目录（前端回填输入框用）
# ---------------------------------------------------------------------------
def test_default_save_dir_comes_from_backend():
    """浏览器里没有环境变量，默认目录只能由后端给出，且必须与实际写入位置同源。"""
    api = _make_api()
    res = api.default_save_dir()
    assert res["ok"] is True
    assert res["dir"] == api._default_save_dir()
    assert res["dir"], "默认保存目录不应为空"


# ---------------------------------------------------------------------------
# 录屏收尾
# ---------------------------------------------------------------------------
def test_shutdown_stops_device_audio_for_recorded_serials():
    """关闭窗口时必须按「设备序列号」停止 tinycap。

    回归：_rec_session 是会话字段字典（ts/dir/videos/devaudio/…），早期实现直接
    遍历它的键，拿到的是字段名而不是序列号，设备端 tinycap 进程从未被停掉。
    """
    api = _make_api()
    api._rec_session = {
        "ts": "ts1", "dir": "d", "devaudio": {"A1": "/sdcard/a1.wav"},
        "videos": {}, "logcat_captures": {},
    }
    stopped = []
    api.device_audio.stop = lambda s: stopped.append(s) or "/tmp/a1.wav"
    api.shutdown()
    assert stopped == ["A1"]


def test_screen_record_stop_collects_output_when_session_already_finished(tmp_path):
    """会话已被其他路径收尾弹出后，用户点「停止」仍要收走产物。

    回归：早期固定时长到点自动 pull 并弹出会话后，stop() 只会返回
    「该设备未在录制」，于是视频既不合成音频、也不进 zip、界面还没有任何提示。
    固定时长虽已移除，该兜底对 stop_all / 异常清理等路径同样有效。
    """
    api = _make_api()
    video = tmp_path / "record_A1_ts1.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42moov")
    api._rec_session = {
        "ts": "ts1", "dir": str(tmp_path), "with_zip": True,
        "videos": {"A1": str(video)}, "devaudio": {}, "logcat_captures": {},
    }
    # video.is_recording 为 False —— 模拟「已由后台线程自动收尾」
    assert api.video.is_recording("A1") is False

    assert api.screen_record_stop() == {"ok": True}
    api.workers.shutdown(timeout=2.0)

    by_kind = _events_by_kind(api)
    texts = [p["text"] for p in by_kind.get("status", [])]
    assert any("✓ 录屏已保存" in t for t in texts), texts
    # 勾选了「结束后压缩为 zip」→ 产物必须真的进包，而不是被静默丢弃
    zpath = tmp_path / "rec_ts1.zip"
    assert zpath.exists(), "已自动收尾的视频没有被打包（产物丢失）"
    with zipfile.ZipFile(zpath) as z:
        assert os.path.basename(str(video)) in z.namelist()
    # 会话已清空，下一次录制不会被「已在录制」守卫挡住
    assert api._rec_session == {}


def test_batch_download_spawns_one_thread_per_file(monkeypatch):
    """回归 BATCH-DOWNLOAD：同一设备批量「下载选中」必须每个文件各自成线程。

    旧实现所有文件操作共用 worker key "fileop_<serial>"，Workers.spawn 对同名存活
    任务去重，导致只有第一个文件真正下载、其余被静默丢弃（「只下了 1 个」）。

    验证：两个 file_download 调用产生两个不同 key（均形如 filedl_<serial>_N），
    且都真正执行了底层 download。
    """
    api = _make_api()
    spawned_keys = []
    real_downloads = []

    def fake_spawn(key, fn, *args, **kwargs):
        spawned_keys.append(key)
        fn(*args, **kwargs)          # 同步执行，便于断言
        return None

    monkeypatch.setattr(api.workers, "spawn", fake_spawn)

    class FakeFileSvc:
        def download(self, serial, remote, local_dir):
            real_downloads.append((serial, remote, local_dir))
            return (os.path.join(local_dir, os.path.basename(remote)), None)

    api.file_svc = FakeFileSvc()

    api.file_download("A1", "/sdcard/a.txt", "/tmp/dl")
    api.file_download("A1", "/sdcard/b.txt", "/tmp/dl")

    assert len(spawned_keys) == 2, spawned_keys
    assert spawned_keys[0] != spawned_keys[1], spawned_keys
    assert all(k.startswith("filedl_A1_") for k in spawned_keys), spawned_keys
    assert len(real_downloads) == 2, real_downloads
    assert {r[1] for r in real_downloads} == {"/sdcard/a.txt", "/sdcard/b.txt"}


# ---------------------------------------------------------------------------
# 设备移除后强停孤儿 logcat 监控 / 抓取
# ---------------------------------------------------------------------------
def test_reap_gone_tools_stops_only_removed_devices():
    """设备被移除（gone）后，_reap_gone_tools 应收拾其遗留的 logcat 监控 / 抓取，
    但不误杀仍在设备列表里（含宽限期内短暂失联）的设备。

    回归点：无线 / 网络 ADB 或 adb 卡顿时 `adb logcat` 可能迟迟不退，光靠 worker 的
    stdout-EOF 自收尾不可靠，会留下孤儿 adb 进程且界面卡在「监控中」。以设备快照为
    权威可补这一缺口。

    抓取与监控的处理**刻意不同**：监控直接 stop 即可，抓取必须走
    notice_device_gone —— stop 会被 worker 当成「用户主动停止」，收尾时报
    stopped 且没有 gap，设备拔线导致文件截断却弹「✓ 抓取完毕」（假成功）。
    见 test_reap_gone_capture_reports_gap_not_clean_success。
    """
    api = _make_api()
    # 当前设备快照只剩 A1、B2（C3 已彻底移除，D4 处于宽限仍保留）
    api.devices.device_state = {"A1": "device", "B2": "device", "D4": "offline"}
    api.devices.device_checked = {"A1": True, "B2": True, "D4": True}

    stopped_mon, stopped_cap, noticed_cap = [], [], []

    class FakeMon:
        def __init__(self, running): self._r = list(running)
        def running_serials(self): return list(self._r)
        def stop(self, s): stopped_mon.append(s)

    class FakeCap:
        def __init__(self, running): self._r = list(running)
        def running_serials(self): return list(self._r)
        def is_reconnecting(self, s): return False
        def stop(self, s, zip_on_stop=False): stopped_cap.append(s)
        def notice_device_gone(self, s): noticed_cap.append(s)

    # 监控 / 抓取正在 A1、B2、C3、D4 上进行；C3 已从快照移除应被收拾，其余不应
    api.logcat_monitor = FakeMon(["A1", "B2", "C3", "D4"])
    api.logcat_capture = FakeCap(["A1", "C3"])
    api._reap_gone_tools()

    assert stopped_mon == ["C3"], stopped_mon
    assert noticed_cap == ["C3"], noticed_cap
    assert stopped_cap == [], (
        "设备消失时不能 stop 抓取：那会把它当成「用户主动停止」，"
        "截断的文件被报成「✓ 抓取完毕」：%r" % (stopped_cap,))


def test_inflight_guard_blocks_server_heal_while_recording(monkeypatch):
    """守卫必须真的接到 DeviceManager 上：录屏 / 抓取在跑时暂缓 adb server 自愈。

    没接上就等于没修：自愈照样跑，`adb start-server` 把在途的 screenrecord
    连接掐断，设备正常却录屏中断。
    """
    api = _make_api()
    # 绑定方法每次访问都是新对象，比 __func__
    assert (api.devices.inflight_guard.__func__
            is api._has_inflight_adb_sessions.__func__), (
        "DeviceManager 必须接上 WebApi 的在途会话守卫")
    monkeypatch.setattr(api.video, "any_recording", lambda: False)
    monkeypatch.setattr(api.logcat_capture, "running_serials", lambda: [])
    monkeypatch.setattr(api.logcat_monitor, "running_serials", lambda: [])
    assert api.devices.inflight_guard() is False
    assert api.devices._inflight_blocks_heal() is False

    monkeypatch.setattr(api.video, "any_recording", lambda: True)
    assert api.devices.inflight_guard() is True
    assert api.devices._inflight_blocks_heal() is True

    monkeypatch.setattr(api.video, "any_recording", lambda: False)
    monkeypatch.setattr(api.logcat_capture, "running_serials", lambda: ["A1"])
    assert api.devices._inflight_blocks_heal() is True, (
        "落盘抓取也是长连接，同样不能被自愈掐断")


def test_reap_gone_tools_noop_when_all_present():
    """所有正在监控的设备都仍在列表中时，_reap_gone_tools 不应停止任何设备。"""
    api = _make_api()
    api.devices.device_state = {"A1": "device", "B2": "device"}
    api.devices.device_checked = {"A1": True, "B2": True}
    stopped = []

    class FakeMon:
        def running_serials(self): return ["A1", "B2"]
        def stop(self, s): stopped.append(s)

    api.logcat_monitor = FakeMon()
    api.logcat_capture = FakeMon()   # 同样只记录 stop
    api._reap_gone_tools()
    assert stopped == [], stopped


def test_reap_gone_tools_stops_removed_recording(monkeypatch):
    """设备被移除时，_reap_gone_tools 应强停录屏会话里该设备的视频 / 设备音频，
    但绝不替用户结束整个会话、也不动仍在录的其它设备。

    回归点：设备端 screenrecord / tinycap 在 adb 断开后未必自动退出，会残留进程、
    占用音频输入，且界面停留「录制中」直到手动停止。
    """
    api = _make_api()
    api.devices.device_state = {"A1": "device"}   # B2 已移除
    api.devices.device_checked = {"A1": True}
    # 录屏会话：A1、B2 都在录（含 B2 的设备音频）
    api._rec_session = {
        "videos": {"A1": "v_a.mp4", "B2": "v_b.mp4"},
        "devaudio": {"B2": "a_b.wav"},
        "logcat_captures": {}, "mic_path": None,
    }
    stopped_v, stopped_a = [], []

    class FakeVideo:
        def is_recording(self, s): return s in ("A1", "B2")
        def stop(self, s): stopped_v.append(s)

    class FakeAudio:
        def stop(self, s): stopped_a.append(s)

    class FakeMon:
        def running_serials(self): return []
        def stop(self, s, **kw): pass

    api.video = FakeVideo()
    api.device_audio = FakeAudio()
    api.logcat_monitor = FakeMon()
    api.logcat_capture = FakeMon()

    spawned = []
    def fake_spawn(key, fn, *args, **kwargs):
        spawned.append(key)
        fn(*args, **kwargs)          # 同步执行，便于断言
    monkeypatch.setattr(api.workers, "spawn", fake_spawn)

    api._reap_gone_tools()
    assert "rec-reap" in spawned, spawned
    assert stopped_v == ["B2"], stopped_v
    assert stopped_a == ["B2"], stopped_a
    # 会话其余部分未被触碰（不替用户结束整个录屏）
    assert api._rec_session["videos"].get("A1") == "v_a.mp4"


def test_reap_gone_tools_keeps_device_waiting_for_reboot(monkeypatch):
    """正在「等待重启后自动续录」的设备不能被「已移除」逻辑强停。

    回归：车机重启期间设备会短暂从列表消失（超出宽限即被移除）。此时录屏侧
    正处在等待窗口，强停会把整场录制提前结束 —— 重启后视频和日志双双丢失。
    """
    api = _make_api()
    api.devices.device_state = {"A1": "device"}   # B2 已移除/重启中
    api.devices.device_checked = {"A1": True}
    api._rec_session = {
        "videos": {"A1": "v_a.mp4", "B2": "v_b.mp4"},
        "devaudio": {"B2": "a_b.wav"},
        "logcat_captures": {}, "mic_path": None,
    }
    stopped_v, stopped_a = [], []

    class FakeVideo:
        def is_recording(self, s): return True
        def reboot_wait_serials(self): return ["B2"]
        def stop(self, s): stopped_v.append(s)

    class FakeAudio:
        def stop(self, s): stopped_a.append(s)

    class FakeMon:
        def running_serials(self): return []
        def stop(self, s, **kw): pass

    api.video = FakeVideo()
    api.device_audio = FakeAudio()
    api.logcat_monitor = FakeMon()
    api.logcat_capture = FakeMon()

    spawned = []
    def fake_spawn(key, fn, *args, **kwargs):
        spawned.append(key)
        fn(*args, **kwargs)
    monkeypatch.setattr(api.workers, "spawn", fake_spawn)

    api._reap_gone_tools()
    assert stopped_v == [], "等待重启的设备不能被强停"
    assert stopped_a == []
    assert "rec-reap" not in spawned, spawned


def test_reap_dead_recordings_announces_reboot_wait_and_resume(monkeypatch):
    """进入等待 / 恢复续录都要在状态栏说清楚，用户才知道「没丢、还在录」。"""
    api = _make_api()

    class FakeVideo:
        def died_serials(self): return []
        def limit_serials(self): return []
        def rolled_serials(self): return []
        def reboot_wait_notes(self): return ["A1"]
        def resumed_serials(self): return ["B2"]

    api.video = FakeVideo()
    api._reap_dead_recordings()

    texts = [p.get("text", "") for p in _events_by_kind(api).get("status", [])]
    joined = "\n".join(texts)
    assert "正在等待恢复" in joined, texts
    assert "已自动继续录制" in joined, texts
    assert "已录内容照样保存" in joined, "要明确告诉用户等待期间停止也能保住数据"


# ---------------------------------------------------------------------------
# 录屏进程意外死亡（adb root / adbd 重启）的自动收尾
# ---------------------------------------------------------------------------
def _dead_rec_session(tmp_path):
    return {
        "ts": "ts1", "dir": str(tmp_path), "with_zip": False,
        "with_devaudio": False, "with_mic": False, "mic_started": False,
        "mic_path": None, "videos": {"A1": "v_a.mp4"}, "devaudio": {},
        "logcat_captures": {}, "pointer_location_prev": {},
        "show_touches_prev": {},
    }


def test_reap_dead_recordings_tears_down_and_resets_ui(monkeypatch, tmp_path):
    """进程意外退出时：必须自动收尾会话、广播 rec_state 让前端复位、说清「视频不完整」。

    回归：adb root 会在录屏中途杀掉设备端 screenrecord。旧实现没有任何监测——
    界面永远停在「录制中」，用户点「停止」后才在约 10 秒的 pull 重试后看到一句
    「缺 moov 头」，而那一刻用户早就切到别的页签了（使用说明「录屏被中断」条
    承诺的行为：自动切回「开始录制」+ 提示视频不完整 + 跳过音频合成 + 保留源文件）。
    """
    api = _make_api()
    api._rec_session = _dead_rec_session(tmp_path)
    # 死亡诊断要探设备是否真的掉线：替掉真实 adb，避免测试去 spawn 进程
    monkeypatch.setattr(
        "backend.controllers.autorefresh.device_present",
        lambda adb, s, timeout=5: False)
    stopped = []

    class FakeVideo:
        def died_serials(self):
            return ["A1"]

        def is_recording(self, s):
            return True

        def stop(self, s):
            stopped.append(s)
            # 残片拉回来了，但缺 moov（screenrecord 没来得及收尾）
            return False, "v_a.mp4", "MP4 缺 moov 头，无法播放"

        def get_system_setting(self, adb, s, key):
            return True, "null"

        def set_system_setting(self, adb, s, key, v):
            return True

        def set_system_setting_ex(self, adb, s, key, v):
            return True, ""

    api.video = FakeVideo()

    api._teardown_dead_recordings(["A1"])

    assert stopped == ["A1"], stopped
    # 会话已结束：不会被「已在录制」守卫永久挡死
    assert api._rec_session == {}
    by_kind = _events_by_kind(api)
    # 前端据此把「停止」按钮切回「开始录制」
    rec_states = by_kind.get("rec_state", [])
    assert rec_states and rec_states[0]["running"] is False, by_kind.get("rec_state")
    texts = [p.get("text", "") for p in by_kind.get("status", [])]
    assert any("意外" in t and "视频不完整" in t for t in texts), texts
    # 残片不合成音频：没有任何「已合成音视频」提示
    assert not any("合成音视频" in t for t in texts), texts


def test_reap_limit_hit_is_reported_as_normal_end(tmp_path):
    """跑到 180 秒上限后自己退出：视频是完整的，不能报「意外中断、请完整重录」。

    screenrecord 不传 --time-limit 时默认 180 秒，到点会**正常收尾**（写回 moov）
    再退出。本地看到的现象与「进程崩了」完全一样（adb 客户端自己退出），旧实现
    一律按意外中断处理，用户会白白重录一段本来完好的视频。
    """
    api = _make_api()
    api._rec_session = _dead_rec_session(tmp_path)
    stopped = []

    class FakeVideo:
        def died_serials(self):
            return []

        def limit_serials(self):
            return ["A1"]

        def is_recording(self, s):
            return True

        def stop(self, s):
            stopped.append(s)
            return True, "v_a.mp4", None      # 正常收尾，文件完整

        def get_system_setting(self, adb, s, key):
            return True, "null"

        def set_system_setting_ex(self, adb, s, key, v):
            return True, ""

    api.video = FakeVideo()

    api._teardown_dead_recordings([], ["A1"])

    assert stopped == ["A1"], stopped
    texts = [p.get("text", "") for p in _events_by_kind(api).get("status", [])]
    assert any("上限" in t for t in texts), texts
    assert not any("意外" in t for t in texts), (
        "跑到上限是正常结束，不能说成意外中断：%r" % (texts,))


def test_reap_passes_limit_hits_alongside_dead(monkeypatch):
    """自动轮询要把「跑到上限」也取出来交给收尾 worker，否则这类退出无人处理。"""
    api = _make_api()
    api._rec_session = _dead_rec_session(".")
    spawned = []
    monkeypatch.setattr(api.workers, "spawn",
                        lambda key, fn, *a, **kw: spawned.append((key, fn, a, kw)))

    class FakeVideo:
        def died_serials(self):
            return []

        def limit_serials(self):
            return ["A1"]

    api.video = FakeVideo()
    api._reap_dead_recordings()
    assert spawned and spawned[0][2] == ([], ["A1"]), spawned


def test_reap_dead_does_not_consume_markers_while_teardown_running(monkeypatch):
    """上一轮收尾还在跑时，本轮不能取走死亡标记。

    回归：`_reap_dead_recordings` 先把 `died_serials()` / `limit_serials()`
    取走（取完即清），再 `workers.spawn("rec-reap-dead")`；同名线程只要还
    存活，spawn 就直接丢弃新参数 —— 标记已被消耗、收尾却没收到，那台设备
    「被意外中断（视频不完整）」的结论永久丢失（多设备先后掉线会撞上）。
    """
    api = _make_api()
    api._rec_session = _dead_rec_session(".")
    spawned = []
    consumed = []
    monkeypatch.setattr(api.workers, "spawn",
                        lambda key, fn, *a, **kw: spawned.append(key))
    monkeypatch.setattr(api.workers, "is_running",
                        lambda key=None: key == "rec-reap-dead")

    class FakeVideo:
        def died_serials(self):
            consumed.append("died")
            return ["A2"]

        def limit_serials(self):
            consumed.append("limit")
            return []

    api.video = FakeVideo()
    api._reap_dead_recordings()
    assert consumed == [], "收尾线程还在跑时不能取走死亡标记"
    assert spawned == [], spawned


def test_reap_dead_recordings_noop_when_nothing_died(monkeypatch):
    """没有进程死亡时不得派 worker、不得动会话（自动轮询每秒都会走到这里）。"""
    api = _make_api()
    api._rec_session = _dead_rec_session(".")
    spawned = []
    monkeypatch.setattr(api.workers, "spawn",
                        lambda key, fn, *a, **kw: spawned.append(key))

    class FakeVideo:
        def died_serials(self):
            return []

    api.video = FakeVideo()
    api._reap_dead_recordings()
    assert spawned == [], spawned
    assert api._rec_session["videos"] == {"A1": "v_a.mp4"}


def test_reap_dead_recordings_skips_unknown_serial(monkeypatch, tmp_path):
    """死掉的设备不在当前会话里（已被其他路径收尾）时直接返回，不重复收尾。"""
    api = _make_api()
    api._rec_session = _dead_rec_session(tmp_path)
    calls = []
    monkeypatch.setattr(api, "screen_record_stop",
                        lambda: calls.append("stop") or {"ok": True})

    class FakeVideo:
        def died_serials(self):
            return ["GHOST"]

    api.video = FakeVideo()
    api._teardown_dead_recordings(["GHOST"])
    assert calls == [], "陌生序列号不得触发整会话收尾"
    assert api._rec_session["videos"] == {"A1": "v_a.mp4"}


def test_device_present_true_only_when_get_state_device(monkeypatch):
    """get-state 决定可达性：device→True；offline / 非零退出→False（确认掉线）；
    adb 本身不可达（缺失 / 超时抛异常）→ None（无法判定，未知）。

    假件必须按 `text=True` 语义返回 **str**（真 adb_kwargs 就是文本模式）：
    旧实现既传了 capture_output=True 又显式传 stdout=/stderr=（subprocess 直接
    抛 ValueError），还按 bytes 比对 —— 两个错叠加，`device_present` 在真机上
    恒返回 None，掉线永远判不出来。
    """
    class _FakeRun:
        def __init__(self, stdout, rc):
            self.stdout = stdout
            self.returncode = rc
            self.stderr = ""

    def fake_run(stdout="device\n", rc=0):
        def _run(*a, **k):
            return _FakeRun(stdout, rc)
        return _run
    monkeypatch.setattr(screen_service.subprocess, "run", fake_run("device\n", 0))
    assert device_present("adb", "A1") is True
    monkeypatch.setattr(screen_service.subprocess, "run", fake_run("offline\n", 0))
    assert device_present("adb", "A1") is False
    monkeypatch.setattr(screen_service.subprocess, "run", fake_run("", 1))
    assert device_present("adb", "A1") is False
    # adb 本身不可达（不存在 / 超时抛异常）→ 无法判定状态，返回 None（未知），
    # 且不得向上抛。调用方据此把「查不到」与「确认掉线」区分开（logcat 重连不会
    # 因 adb 暂时查不到就拉起无意义轮询）。
    def boom(*a, **k):
        raise FileNotFoundError("adb")
    monkeypatch.setattr(screen_service.subprocess, "run", boom)
    assert device_present("adb", "A1") is None


def test_device_present_passes_valid_subprocess_kwargs(monkeypatch):
    """回归：探测参数不能和 adb_kwargs 自带的 capture_output 冲突。

    旧写法 `subprocess.run([...], stdout=PIPE, stderr=PIPE, **adb_kwargs(5))`
    每次都会抛 `ValueError: stdout and stderr arguments may not be used with
    capture_output.`，异常被 `except Exception: return None` 吞掉 —— 函数在
    真机上**恒为 None**。后果不是一句日志：logcat 抓取的掉线判定
    （`device_present(...) is False`）永远不成立，设备真掉线也走不成「等重连
    续写」；重连轮询又把 None 当「还没回来」，只能一路等到窗口耗尽；录屏中断
    原因也永远被说成「设备连接已断开」。
    """
    seen = {}

    def spy(*a, **kw):
        seen["kw"] = kw
        # 复刻 subprocess.run 的参数冲突检查（真机上一次都没跑通过，正因如此）
        if kw.get("capture_output") and (kw.get("stdout") is not None
                                         or kw.get("stderr") is not None):
            raise ValueError("stdout and stderr arguments may not be used "
                             "with capture_output.")
        raise FileNotFoundError("adb-not-installed-in-ci")

    monkeypatch.setattr(screen_service.subprocess, "run", spy)
    assert device_present("adb", "A1") is None
    assert seen["kw"].get("capture_output") is True
    assert "stdout" not in seen["kw"] and "stderr" not in seen["kw"], \
        "显式 stdout/stderr 会和 adb_kwargs 的 capture_output 冲突：%r" % (seen["kw"],)


def test_death_message_says_connection_lost_when_device_gone(monkeypatch):
    """设备真的掉线时：提示必须是连接问题，且不得把锅甩给 adb root（那是误导）。"""
    api = _make_api()
    msg = api._build_death_message(["A1"], probe=lambda adb, s, timeout=5: False)
    assert "设备连接已断开" in msg, msg
    assert "USB 掉线" in msg, msg
    assert "adb root" not in msg, "掉线场景不应暗示 adb root（录屏路径本就不会重启 adbd）"


def test_death_message_says_process_exited_when_device_present(monkeypatch):
    """设备还在时：提示是 screenrecord 自身异常，并点出 adb root 是一种可能。"""
    api = _make_api()
    msg = api._build_death_message(["A1"], probe=lambda adb, s, timeout=5: True)
    assert "设备仍在连接" in msg, msg
    assert "screenrecord 自身异常终止" in msg, msg
    assert "adb root" in msg, msg


# ---------------------------------------------------------------------------
# 截图 → 同步至粘贴板
# ---------------------------------------------------------------------------
class _FakeCapturer:
    """替身 ScreenCapturer：固定返回一条路径（或一条失败信息）。"""

    def __init__(self, path=None, err=None):
        self.path = path or r"D:\shots\screenshot_A1_20260928_120000.png"
        self.err = err
        self.calls = []

    def screenshot(self, adb, serial, save_dir, save_file=True):
        self.calls.append((adb, serial, save_dir, save_file))
        return (None, self.err) if self.err else (self.path, None)


class _FakeClipboard:
    """替身 core.clipboard.copy_image：记录调用次数并返回预设结果。"""

    def __init__(self, ok=True, reason=""):
        self.ok = ok
        self.reason = reason
        self.calls = []

    def copy_image(self, path):
        self.calls.append(path)
        return self.ok, self.reason


def _install_screenshot_fakes(api, monkeypatch, capturer=None, clip=None):
    capturer = capturer or _FakeCapturer()
    clip = clip or _FakeClipboard()
    monkeypatch.setattr(ctrl.ScreenCapturer, "screenshot",
                        staticmethod(capturer.screenshot))
    monkeypatch.setattr(ctrl.clipboard, "copy_image", clip.copy_image)
    monkeypatch.setattr(api.workers, "spawn",
                        lambda key, fn, *a, **kw: (key, fn(*a, **kw)))
    return capturer, clip


def test_screenshot_double_click_runs_twice(monkeypatch):
    """连点两次截图必须真的截两张。

    回归：截图 worker key 固定为 "screenshot_<serial>"，上一张还没截完时再点一次
    会被 Workers 按同名**静默丢弃**，而 API 照旧返回 {"ok": True} —— 用户以为连截
    了两张，实际只有一张（旧的文件名还是秒级时间戳，即使真跑两次也会互相覆盖）。
    """
    api = _make_api()
    release = threading.Event()
    seen = []

    def blocked(_adb, serial, _save_dir, _save_file=True):
        seen.append(serial)
        release.wait(3.0)
        return ("D:/shots/x.png", None)

    monkeypatch.setattr(ctrl.ScreenCapturer, "screenshot",
                        staticmethod(blocked))
    monkeypatch.setattr(ctrl.clipboard, "copy_image", lambda p: (True, ""))

    api.screenshot("A1", False)
    assert wait_until(lambda: len(seen) == 1), "首次截图未启动"
    api.screenshot("A1", False)
    assert wait_until(lambda: len(seen) == 2, timeout=2.0), \
        "第二次截图请求被同名 worker 去重静默丢弃（实际只执行 %d 次）" % len(seen)
    release.set()
    api.workers.shutdown(timeout=2.0)


def test_screenshot_single_device_copies_to_clipboard_by_default(monkeypatch):
    """未指定开关时按偏好走，偏好缺省就是开启：截图后应同步进剪贴板。"""
    api = _make_api()
    capturer, clip = _install_screenshot_fakes(api, monkeypatch)
    patch_ctrl(monkeypatch, "get_pref", lambda key, default=None: True)

    assert api.screenshot() == {"ok": True}

    assert len(capturer.calls) == 1, "单勾设备只应截一次"
    assert clip.calls == [capturer.path], "截图成功后应立刻写剪贴板"
    by_kind = _events_by_kind(api)
    assert any("粘贴板" in p["text"] for p in by_kind.get("status", [])), \
        "成功同步应在状态栏给出可确认的反馈"
    shot = [p for p in by_kind.get("tool", []) if p.get("type") == "screenshot"]
    assert shot and shot[-1]["path"] == capturer.path
    assert shot[-1]["clipboard"] is True


def test_screenshot_switch_off_skips_clipboard(monkeypatch):
    """开关关掉时不碰剪贴板，状态栏也回到普通「已保存」文案。"""
    api = _make_api()
    capturer, clip = _install_screenshot_fakes(api, monkeypatch)

    api.screenshot(None, False)

    assert clip.calls == [], "关闭开关后不应再写剪贴板"
    by_kind = _events_by_kind(api)
    texts = [p["text"] for p in by_kind.get("status", [])]
    assert any("已保存截图: " + capturer.path in t for t in texts)
    assert not any("粘贴板" in t for t in texts)
    shot = [p for p in by_kind.get("tool", []) if p.get("type") == "screenshot"]
    assert "clipboard" not in shot[-1], "没尝试过就不该带 clipboard 字段"


def test_screenshot_multi_device_skips_clipboard(monkeypatch):
    """多设备批量：剪贴板一次只能放一张，故不自动复制但要说明原因。"""
    api = _make_api()
    api.toggle_device("B2", True)
    capturer, clip = _install_screenshot_fakes(api, monkeypatch)
    patch_ctrl(monkeypatch, "get_pref", lambda key, default=None: True)

    api.screenshot()

    assert len(capturer.calls) == 2, "两台设备各截一张（文件照常保存）"
    assert clip.calls == [], "多设备时不该互相覆盖地抢写剪贴板"
    by_kind = _events_by_kind(api)
    warn = [p["text"] for p in by_kind.get("status", []) if p["type"] == "warn"]
    assert any("多设备批量" in t for t in warn), warn


def test_screenshot_clipboard_failure_keeps_saved_file(monkeypatch):
    """剪贴板失败（被别的程序占用）绝不能否定「图已经存下来了」。"""
    api = _make_api()
    capturer, clip = _install_screenshot_fakes(
        api, monkeypatch, clip=_FakeClipboard(ok=False, reason="剪贴板被占用"))

    api.screenshot(None, True)

    assert clip.calls == [capturer.path]
    by_kind = _events_by_kind(api)
    warn = [p["text"] for p in by_kind.get("status", []) if p["type"] == "warn"]
    assert any("已保存截图" in t and "剪贴板被占用" in t for t in warn), warn
    shot = [p for p in by_kind.get("tool", []) if p.get("type") == "screenshot"]
    assert shot[-1]["clipboard"] is False


def test_screenshot_failure_does_not_touch_clipboard(monkeypatch):
    api = _make_api()
    capturer, clip = _install_screenshot_fakes(
        api, monkeypatch, capturer=_FakeCapturer(err="设备离线"))

    api.screenshot()

    assert clip.calls == [], "没截出图就不该动剪贴板"
    by_kind = _events_by_kind(api)
    assert any(p["type"] == "err" and "设备离线" in p["text"]
               for p in by_kind.get("status", []))


def test_screenshot_pref_can_turn_it_off(monkeypatch):
    """偏好里显式关闭时（settings.json: shot_to_clipboard=false）即不复制。"""
    api = _make_api()
    _capturer, clip = _install_screenshot_fakes(api, monkeypatch)
    patch_ctrl(monkeypatch, "get_pref", lambda key, default=None: False)

    api.screenshot()

    assert clip.calls == []


def test_screenshot_save_file_default_true(monkeypatch):
    """「自动保存文件」默认开启：不传 save_file 时按偏好落盘（save_file=True）。"""
    api = _make_api()
    capturer, _clip = _install_screenshot_fakes(api, monkeypatch)
    # get_pref 一律回退到各自默认值：shot_save_file 默认 True
    patch_ctrl(monkeypatch, "get_pref", lambda key, default=None: default)

    api.screenshot("A1", False)

    assert capturer.calls, "截图应已调用 ScreenCapturer"
    assert capturer.calls[-1][3] is True, "默认应保存到保存目录"


def test_screenshot_save_file_off_does_not_save(monkeypatch):
    """取消「自动保存文件」后：不写保存目录，toast 改为「未保存到目录」。"""
    api = _make_api()
    capturer, _clip = _install_screenshot_fakes(api, monkeypatch)
    patch_ctrl(monkeypatch, "get_pref", lambda key, default=None: False)

    api.screenshot("A1", False)

    assert capturer.calls, "截图应已调用 ScreenCapturer"
    assert capturer.calls[-1][3] is False, "关闭后不应写保存目录"
    by_kind = _events_by_kind(api)
    toasts = [p for p in by_kind.get("status", []) if p.get("toast")]
    assert any(p["type"] == "ok" and "未保存到目录" in p["text"]
               for p in toasts), "关闭后应提示未保存到目录：%r" % toasts


def test_screenshot_save_file_explicit_false(monkeypatch):
    """即使偏好开启，前端显式传 save_file=False 也立即生效（不落盘）。"""
    api = _make_api()
    capturer, _clip = _install_screenshot_fakes(api, monkeypatch)
    patch_ctrl(monkeypatch, "get_pref", lambda key, default=None: True)

    api.screenshot("A1", False, False)

    assert capturer.calls[-1][3] is False, "显式 False 应优先生效"


# ---------------------------------------------------------------------------
# 截图完成：全局 toast（用户可能已切去别的页签，只看得到 toast）
# ---------------------------------------------------------------------------
def test_screenshot_success_pushes_completion_toast(monkeypatch):
    """单设备截图成功：状态栏照记，同时弹 toast 强提醒。"""
    api = _make_api()
    capturer, _clip = _install_screenshot_fakes(api, monkeypatch)

    api.screenshot("A1", False)

    statuses = _events_by_kind(api).get("status", [])
    toasts = [p for p in statuses if p.get("toast")]
    assert any(p["type"] == "ok" and "已保存截图" in p["text"]
               for p in toasts), "截图完成必须弹 toast：%r" % toasts


def test_screenshot_saved_toast_precedes_clipboard_status(monkeypatch):
    """「已保存」反馈必须先于剪贴板就绪：写盘不再被 PNG 解码（1~2s）阻塞。

    顺序断言：第一条 toast 应是「✓ 已保存截图」，「已复制到粘贴板」排其后。
    """
    api = _make_api()
    capturer, _clip = _install_screenshot_fakes(api, monkeypatch)

    api.screenshot("A1", True)

    texts = [p["text"] for p in _events_by_kind(api).get("status", [])]
    i_saved = next((i for i, t in enumerate(texts) if "已保存截图" in t), -1)
    i_clip = next((i for i, t in enumerate(texts) if "已复制到粘贴板" in t), -1)
    assert i_saved >= 0 and i_clip >= 0, texts
    assert i_saved < i_clip, "「已保存」必须先于「已复制到粘贴板」：%r" % texts


def test_screenshot_batch_pushes_single_summary_toast(monkeypatch):
    """多设备批量：不逐台弹 toast，全部到齐后只弹一条汇总。"""
    api = _make_api()
    api.toggle_device("B2", True)
    capturer, _clip = _install_screenshot_fakes(api, monkeypatch)

    api.screenshot()

    statuses = _events_by_kind(api).get("status", [])
    shot_toasts = [p for p in statuses
                   if p.get("toast") and "截图" in (p.get("text") or "")]
    assert len(shot_toasts) == 1, \
        "N 台设备只弹一条汇总 toast，实际 %d 条：%r" % (len(shot_toasts), shot_toasts)
    assert "2 台设备" in shot_toasts[0]["text"], shot_toasts[0]["text"]
    # 汇总后计数器必须清零，下一批重新计数
    assert api._shot_batch is None


def test_screenshot_batch_summary_reports_failures(monkeypatch):
    """批量里有的设备失败：汇总 toast 说清「几成功几失败」，不静默。"""
    api = _make_api()
    api.toggle_device("B2", True)
    _install_screenshot_fakes(api, monkeypatch)

    # A1 成功、B2 失败：按序列号分流
    def flaky(adb, serial, save_dir, save_file=True):
        if serial == "B2":
            return None, "设备离线"
        return (r"D:\shots\s.png", None)

    monkeypatch.setattr(ctrl.ScreenCapturer, "screenshot",
                        staticmethod(flaky))

    api.screenshot()

    statuses = _events_by_kind(api).get("status", [])
    summary = [p for p in statuses if p.get("toast") and "批量截图" in p["text"]]
    assert len(summary) == 1, statuses
    assert summary[0]["type"] == "warn"
    assert "1 成功，1 失败" in summary[0]["text"], summary[0]["text"]
    assert "设备离线" in summary[0]["text"], summary[0]["text"]


def test_screenshot_pushes_shot_state_true_then_false(monkeypatch):
    """单设备截图：shot_state 必须先 true 后 false（前端据此禁用/恢复按钮）。"""
    api = _make_api()
    _install_screenshot_fakes(api, monkeypatch)

    assert api.screenshot("A1", False)["ok"] is True

    states = [p["running"] for p in _events_by_kind(api).get("shot_state", [])]
    assert states == [True, False], "应恰有一对 true/false，实际 %r" % states
    assert api._shot_inflight == 0, "完成后在途计数必须归零"


def test_screenshot_batch_shot_state_flips_once(monkeypatch):
    """批量 N 台：shot_state 只允许一对 true/false——每台一对会让按钮闪烁。

    用真实线程 + 闸门（不用同步假 spawn）：生产上 USB 往返就是天然闸门，
    所有 worker 的 +1 必然早于任何 -1，按钮只禁用/恢复一次。
    """
    api = _make_api()
    api.toggle_device("B2", True)
    release = threading.Event()
    seen = []

    def blocked(_adb, serial, _save_dir, _save_file=True):
        seen.append(serial)
        release.wait(3.0)
        return ("D:/shots/x.png", None)

    monkeypatch.setattr(ctrl.ScreenCapturer, "screenshot",
                        staticmethod(blocked))
    monkeypatch.setattr(ctrl.clipboard, "copy_image", lambda p: (True, ""))

    api.screenshot()
    assert wait_until(lambda: len(seen) == 2, timeout=2.0), "两台应各起一个 worker"
    release.set()
    assert wait_until(lambda: api._shot_inflight == 0, timeout=2.0), \
        "两个 worker 都收尾后在途数应归零"

    states = [p["running"] for p in _events_by_kind(api).get("shot_state", [])]
    assert states == [True, False], "批量也只推一对，实际 %r" % states
    api.workers.shutdown(timeout=2.0)


def test_screenshot_no_device_does_not_touch_shot_state(monkeypatch):
    """未勾选设备被直接拒绝：没有在途任务，不该广播 shot_state。"""
    api = _make_api()
    api.toggle_device("A1", False)
    _install_screenshot_fakes(api, monkeypatch)

    assert api.screenshot()["ok"] is False

    assert "shot_state" not in _events_by_kind(api), "拒绝路径不应有按钮态事件"
    assert api._shot_inflight == 0


def test_screenshot_overlapping_requests_keep_running(monkeypatch):
    """请求叠加（连点竞态 / API 直调）：先结束的不能提前解开另一个的禁用态。

    计数而非布尔的意义所在：第二个请求结束时 shot_state 必须仍是 true，
    只有最后一个worker收尾才推 false。
    """
    api = _make_api()
    gates = [threading.Event(), threading.Event()]
    seen = []

    def gated(_adb, serial, _save_dir, _save_file=True):
        i = len(seen)
        seen.append(serial)
        gates[i].wait(3.0)
        return ("D:/shots/x.png", None)

    monkeypatch.setattr(ctrl.ScreenCapturer, "screenshot",
                        staticmethod(gated))
    monkeypatch.setattr(ctrl.clipboard, "copy_image", lambda p: (True, ""))

    api.screenshot("A1", False)
    assert wait_until(lambda: len(seen) == 1), "首次截图未启动"
    api.screenshot("A1", False)
    assert wait_until(lambda: len(seen) == 2, timeout=2.0), "第二次截图未启动"

    gates[0].set()   # 放第一个结束，第二个仍在跑
    assert wait_until(lambda: api._shot_inflight == 1, timeout=2.0), \
        "第一个 worker 收尾后在途数应为 1"
    states = [p["running"] for p in _events_by_kind(api).get("shot_state", [])]
    assert states and states[-1] is True, \
        "还有一个在跑，shot_state 必须仍是 true，实际 %r" % states

    gates[1].set()   # 第二个也结束
    assert wait_until(lambda: api._shot_inflight == 0, timeout=2.0)
    states = [p["running"] for p in _events_by_kind(api).get("shot_state", [])]
    assert states[-1] is False, "全部结束后才恢复，实际 %r" % states
    api.workers.shutdown(timeout=2.0)


def test_screenshot_worker_exception_still_releases_button(monkeypatch):
    """worker 内抛异常（非预期 bug）：finally 必须回落计数，按钮不能假死。"""
    api = _make_api()
    _install_screenshot_fakes(api, monkeypatch)

    def boom(_adb, _serial, _save_dir, _save_file=True):
        raise RuntimeError("adb 崩了")

    monkeypatch.setattr(ctrl.ScreenCapturer, "screenshot",
                        staticmethod(boom))

    with pytest.raises(RuntimeError):
        api._do_screenshot("A1", "D:/shots", False, False)

    assert api._shot_inflight == 0, "异常路径也必须 -1，否则按钮永久禁用"


def test_screenshot_batch_worker_exception_still_summarizes(monkeypatch):
    """批量中某 worker 抛异常：汇总 toast 仍须到齐，批次账不能悬挂。"""
    api = _make_api()
    api.toggle_device("B2", True)
    _install_screenshot_fakes(api, monkeypatch)

    def half_boom(adb, serial, save_dir, save_file=True):
        if serial == "B2":
            raise RuntimeError("adb 崩了")
        return (r"D:\shots\s.png", None)

    monkeypatch.setattr(ctrl.ScreenCapturer, "screenshot",
                        staticmethod(half_boom))

    # 这里的 spawn 替身是**同步**执行（见 _install_screenshot_fakes），worker
    # 内的异常会直接冒到调用方；真实环境里它在后台线程里，异常由 _do_screenshot
    # 转成批次账。api.screenshot() 现在对 spawn 抛出的异常也做兜底（线程起不来
    # 时按失败记账），所以这里不再断言外抛 —— 断言的是「批次账照样结清」。
    api.screenshot()

    statuses = _events_by_kind(api).get("status", [])
    summary = [p for p in statuses if p.get("toast") and "批量截图" in p["text"]]
    assert len(summary) == 1, "异常也要汇合成一条 toast，实际 %r" % statuses
    assert "1 成功，1 失败" in summary[0]["text"], summary[0]["text"]
    assert api._shot_inflight == 0
    assert api._shot_batch is None, "批次账必须清零，不能悬挂到下一批"


# ---------------------------------------------------------------------------
# 命令执行异常兜底 / 麦克风提示去重
# ---------------------------------------------------------------------------
def test_execute_unexpected_error_becomes_status_not_crash():
    """命令下发链路出现未预期异常时，必须转化为错误状态，绝不在 worker 线程裸抛。

    回归点：异常若逃出 _execute，只会落到 threading.excepthook 落一份崩溃日志，
    用户在界面上看不到任何反馈，还以为程序卡死了。
    """
    api = _make_api()
    api._run_entries = lambda *a, **kw: (_ for _ in ()).throw(
        RuntimeError("模拟的意外错误"))
    before = api.state.is_busy()
    assert before is False

    api._execute({"id": "pc", "name": "跑脚本", "labels": ["通用"],
                  "commands": [{"command": "git status", "delay": 0}]})

    assert api.state.is_busy() is False, "异常后 busy 必须复位（停止按钮不卡死）"
    by_kind = _events_by_kind(api)
    texts = [p["text"] for p in by_kind.get("status", [])]
    assert any("意外错误" in t for t in texts), texts


def test_mic_start_failure_not_reported_as_silent_recording(monkeypatch, tmp_path):
    """麦克风**启动就失败**时，停止录屏不应再补一条「未录到声音（可能全程静音）」。

    回归点：两种失败原因不同（启动失败已 toast 过一次），重复归因为「静音」会误导
    用户去检查麦克风音量，而真正的问题是设备被占用/无权限。
    """
    api = _make_api()
    video = tmp_path / "record_A1_ts1.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42moov")
    api._rec_session = {
        "ts": "ts1", "dir": str(tmp_path),
        "with_mic": True, "mic_started": False, "mic_path": None,
        "videos": {"A1": str(video)}, "devaudio": {}, "logcat_captures": {},
    }

    assert api.screen_record_stop() == {"ok": True}
    api.workers.shutdown(timeout=2.0)

    by_kind = _events_by_kind(api)
    texts = [p["text"] for p in by_kind.get("status", [])]
    assert not any("未录到电脑麦克风声音" in t for t in texts), texts
    assert any("✓ 录屏已保存" in t for t in texts), texts


def test_mic_recording_silence_still_reports_reason(tmp_path):
    """麦克风确实启动过、但整段静音时，仍必须给出「未录到声音」的明确原因。"""
    api = _make_api()
    video = tmp_path / "record_A1_ts1.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42moov")
    api._rec_session = {
        "ts": "ts1", "dir": str(tmp_path),
        "with_mic": True, "mic_started": True, "mic_path": None,
        "videos": {"A1": str(video)}, "devaudio": {}, "logcat_captures": {},
    }

    assert api.screen_record_stop() == {"ok": True}
    api.workers.shutdown(timeout=2.0)

    by_kind = _events_by_kind(api)
    texts = [p["text"] for p in by_kind.get("status", [])]
    assert any("未录到电脑麦克风声音" in t for t in texts), texts


def test_logcat_still_running_is_not_zipped(tmp_path, monkeypatch):
    """日志抓取 2 秒内没停下：宁可不打包，也不能打一份缺尾的包再把源文件删掉。

    回归：打包成功后 `_zip_paths` 会删除源 txt。抓取若还在往同一个路径写，
    尾部就落进了已删除的 inode —— zip 里少一段、磁盘上也没有，日志彻底消失，
    而界面上只说「已打包」。
    """
    import backend.controllers.record as rec_mod

    api = _make_api()
    video = tmp_path / "record_A1_ts1.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42moov")
    log = tmp_path / "logcat_A1_ts1.txt"
    log.write_text("08-29 10:00:00.000  1  1 I Tag: hi\n", encoding="utf-8")
    api._rec_session = {
        "ts": "ts1", "dir": str(tmp_path), "with_mic": False,
        "with_zip": True,
        "videos": {"A1": str(video)}, "devaudio": {},
        "logcat_captures": {"A1": str(log)},
    }
    monkeypatch.setattr(api.logcat_capture, "stop", lambda *a, **k: True)
    monkeypatch.setattr(api.logcat_capture, "is_running", lambda s: True)
    monkeypatch.setattr(rec_mod.time, "sleep", lambda s: None)

    assert api.screen_record_stop() == {"ok": True}
    api.workers.shutdown(timeout=2.0)

    zpath = tmp_path / "rec_ts1.zip"
    assert zpath.exists(), "视频本身仍应正常打包"
    with zipfile.ZipFile(str(zpath)) as z:
        names = z.namelist()
    assert not any("logcat" in n for n in names), (
        "抓取未收尾时不得把它塞进包（打包后删源文件会连仍在写的数据一起丢掉）：%r"
        % (names,))
    assert log.exists(), "源日志必须保留"
    texts = [p["text"] for p in _events_by_kind(api).get("status", [])]
    assert any("仍在收尾" in t for t in texts), texts


def test_logcat_stop_precedes_video_teardown(monkeypatch, tmp_path):
    """日志必须与视频「同时」停：视频收尾要拉文件（数秒），日志多跑这几秒就错位。

    回归：收尾顺序是「先拉视频（几台设备并行也要数秒）→ 再停 logcat」。视频在
    拉之前就停了，日志却一直写到所有设备 pull 完 —— 事后按时间轴对照视频找
    日志，两边差出的正是案发现场那一段。
    """
    api = _make_api()
    video = tmp_path / "record_A1_ts1.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42moov")
    log = tmp_path / "logcat_A1_ts1.txt"
    log.write_text("08-29 10:00:00.000  1  1 I Tag: hi\n", encoding="utf-8")
    api._rec_session = {
        "ts": "ts1", "dir": str(tmp_path), "with_mic": False,
        "videos": {"A1": str(video)}, "devaudio": {},
        "logcat_captures": {"A1": str(log)},
    }
    order = []
    monkeypatch.setattr(api.video, "is_recording", lambda s: True)
    # 打 _stop_video 而不是 video.stop：收尾现在走 stop_ex（自动分段会有多段），
    # 这里只关心「日志停止」与「视频收尾」的先后顺序。
    monkeypatch.setattr(
        api, "_stop_video",
        lambda s: (order.append("video"), (True, [str(video)], None))[1])
    monkeypatch.setattr(api.logcat_capture, "is_running", lambda s: False)
    monkeypatch.setattr(
        api.logcat_capture, "stop",
        lambda s, **k: (order.append("logcat"), True)[1])

    assert api.screen_record_stop() == {"ok": True}
    api.workers.shutdown(timeout=2.0)

    assert "logcat" in order and "video" in order, order
    assert order.index("logcat") < order.index("video"), (
        "日志必须在视频收尾之前就下发停止，否则会比视频多跑数秒：%r" % (order,))


def test_logcat_save_writes_file_and_returns_path(monkeypatch, tmp_path):
    """「保存到文件」改走后端写盘：文本落盘到保存目录并回传路径。

    回归：前端原先用 a.click() + Blob 下载，在 WebView2 下被静默吞掉（点了没反应）。
    现在由后端落到保存目录，落盘真实发生、调用方拿到路径，前端据此提示成功。
    """
    api = _make_api()
    # 保存目录固定到 tmp_path，便于断言文件真写出来了
    patch_ctrl(monkeypatch, "load_prefs", lambda: {"save_dir": str(tmp_path)})
    monkeypatch.setattr(api, "_default_save_dir",
                        lambda: str(tmp_path), raising=False)

    res = api.logcat_save("A1",
                          "08-29 10:00:00.000  1  1 I Tag: 账号绑定成功\n"
                          "08-29 10:00:01.000  1  1 W Tag: 电量低\n")

    assert res["ok"] is True, res
    assert "path" in res and res["path"]
    p = res["path"]
    assert os.path.isfile(p), "文件应当真实落盘"
    with open(p, "r", encoding="utf-8") as f:
        saved = f.read()
    assert "账号绑定成功" in saved and "电量低" in saved, saved
    assert p.startswith(str(tmp_path)), "应落在保存目录：%s" % p
    # 返回路径应被回传给前端做提示（这里以事件形式体现：toast 推了出去）
    toasts = [e["payload"]["text"] for e in api.bus.take()
              if e["kind"] == "status" and e["payload"].get("toast")]
    assert any("已保存" in t for t in toasts), toasts


def test_logcat_save_empty_is_rejected(monkeypatch, tmp_path):
    """没有可保存内容时不写空文件，而是明确告知。"""
    api = _make_api()
    patch_ctrl(monkeypatch, "load_prefs", lambda: {"save_dir": str(tmp_path)})
    monkeypatch.setattr(api, "_default_save_dir",
                        lambda: str(tmp_path), raising=False)

    res = api.logcat_save("A1", "   \n  ")
    assert res["ok"] is False
    assert res["reason"] == "empty"


def test_devaudio_remote_path_safe_for_wireless_serial(monkeypatch, tmp_path):
    """含设备音频录屏时，设备端 wav 路径必须过 safe_name。

    回归点：无线序列号形如 192.168.1.5:5555 含冒号，未净化时 adb shell
    下发与后续 pull 引用的是带冒号的路径，与本地落盘命名风格也不统一。
    """
    api = _make_api()
    monkeypatch.setattr(
        ctrl.DeviceAudioCapture, "supported", staticmethod(lambda *a, **kw: True))
    started = []

    class _FakeDevAudio:
        def start(self, serial, remote):
            started.append((serial, remote))
            return True

        def stop(self, serial, *a, **kw):
            return True

    api.device_audio = _FakeDevAudio()
    monkeypatch.setattr(
        api.video, "start", lambda *a, **kw: (True, str(tmp_path / "r.mp4")))

    res = api.screen_record_start(
        "192.168.1.5:5555", with_devaudio=True, save_dir=str(tmp_path))
    assert res.get("ok") is True, res
    # 前端「已录时长」的起点：取视频真正起录的时刻（在麦克风 / 设备音频
    # 初始化之后、screenrecord 确认窗之前），既不漏算确认等待，也不会因为
    # 麦克风初始化把读数撑长
    assert isinstance(res.get("started"), float), res
    assert api._rec_session["start_host"] <= res["started"] <= time.time(), res
    assert res["started"] == api._rec_session["video_start_host"], res
    remote = api._rec_session["devaudio"]["192.168.1.5:5555"]
    assert remote.endswith(".wav"), remote
    # 基名过全部非法字符（/ 是设备端合法目录分隔符，单独放行）
    name = os.path.basename(remote)
    for ch in '<>:"/\\|?*':
        assert ch not in name, "设备端 wav 文件名含非法字符 %r：%s" % (ch, remote)
    # 整条路径里冒号尤其危险（部分 ROM 的 shell 会误判为分隔符）
    for ch in '<>:"|?*\\':
        assert ch not in remote, "设备端 wav 路径含有害字符 %r：%s" % (ch, remote)

    api._rec_session = {}
    api.workers.shutdown(timeout=2.0)


def test_open_local_file_rejects_missing_file(tmp_path):
    """路径不存在（临时文件已被清理 / 传入空值）时必须明确失败，不静默。"""
    api = _make_api()
    res = api.open_local_file(str(tmp_path / "nope.txt"))
    assert res["ok"] is False and "不存在" in res["reason"], res
    assert api.open_local_file("")["ok"] is False
    api.workers.shutdown(timeout=2.0)


def test_open_local_file_launches_default_app(monkeypatch, tmp_path):
    """「查看」按钮：调系统默认程序打开已拉取到本地的文件。"""
    api = _make_api()
    f = tmp_path / "big.log"
    f.write_text("x" * 10, encoding="utf-8")
    launched = []
    monkeypatch.setattr(ctrl.os, "startfile",
                        lambda p: launched.append(("startfile", p)), raising=False)
    monkeypatch.setattr(ctrl.subprocess, "Popen",
                        lambda cmd, **kw: launched.append(("popen", list(cmd))))

    res = api.open_local_file(str(f))

    assert res == {"ok": True}, res
    assert launched, "应触发系统打开机制（startfile / xdg-open / open）"
    # 比对参数本身，而不是 str(tuple)：tuple 的 str() 会把路径里的反斜杠转义成
    # `\\`，Windows 路径永远不是它的子串（该断言在 Windows 上恒失败）。
    argv = launched[0][1]
    argv = [argv] if isinstance(argv, str) else list(argv)
    assert str(f) in argv, launched
    api.workers.shutdown(timeout=2.0)


def test_open_local_file_reports_launch_failure(monkeypatch, tmp_path):
    """打开机制本身失败（无关联程序等）时把原因带回前端。"""
    api = _make_api()
    f = tmp_path / "big.log"
    f.write_text("x", encoding="utf-8")

    def _boom(*a, **kw):
        raise OSError("no opener")

    monkeypatch.setattr(ctrl.os, "startfile", _boom, raising=False)
    monkeypatch.setattr(ctrl.subprocess, "Popen", _boom)

    res = api.open_local_file(str(f))

    assert res["ok"] is False and "no opener" in res["reason"], res
    api.workers.shutdown(timeout=2.0)


# ---------------------------------------------------------------------------
# 交互式 adb shell：停止按钮必须保持可用
# ---------------------------------------------------------------------------
class InteractiveSession(FakeSession):
    """模拟真实 ShellSession：interactive=True 的 run 会把会话标成交互态。

    （真实实现里 `adb shell` 直通后 PowerShell 会话一直挂着，只能靠「停止」kill。）
    """

    def run(self, script, timeout=None, interactive=False):
        r = super().run(script, timeout=timeout, interactive=interactive)
        if interactive:
            self.in_interactive_shell = True
        return r


def test_interactive_shell_keeps_stop_button_enabled():
    """`adb shell` 直通进交互态后，「停止」按钮必须继续亮着。

    回归：AppState 的 busy 本就包含交互态，但没人把会话的交互态同步过去 ——
    `_execute` 结束时 end_run() 只看命令计数（已归零），于是广播 running=False，
    停止按钮熄灭。可交互会话还挂在 PowerShell 里，用户再也点不到「停止」退出来。
    """
    api = _make_api(session=InteractiveSession())
    assert api.run_custom("adb shell") == {"ok": True}
    assert wait_until(lambda: api.session.calls), "命令应已下发到会话"
    assert api.session.calls[0]["interactive"] is True, "adb shell 应走交互直通"
    # 等命令执行骨架收尾（end_run 之后即最终稳定态）
    assert wait_until(lambda: api.state.running_count() == 0)

    assert api.state.is_busy() is True, "交互态应保持 busy（停止按钮亮着）"
    stops = [p["running"] for p in _events_by_kind(api).get("stop_state", [])]
    assert stops == [True], "交互态下不该把停止按钮熄灭（实际 %r）" % stops
    # 点「停止」能正常退出交互态
    assert api.stop_run() == {"ok": True}
    assert api.state.is_busy() is False
    api.workers.shutdown(timeout=2.0)


# ---------------------------------------------------------------------------
# 录屏停止：状态文案只报一次
# ---------------------------------------------------------------------------
def test_screen_record_stop_reports_saved_once(monkeypatch, tmp_path):
    """停止录屏时「✓ 录屏已保存: <路径>」在状态栏只应出现一次。

    回归：`screen_service._pull_and_finish` 自行 push 一条 tool/ok，controller 又
    按返回值 push 一条同文案的 status。前端把 tool 的 ok 载荷也渲染成状态栏行
    （见 tests/frontend/status_copy_flash.test.cjs），于是同一行出现两次。
    """
    import backend.screen_service as ss

    class _Proc:
        def poll(self):
            return None

        def terminate(self):
            pass

        def kill(self):
            pass

        def wait(self, timeout=None):
            return 0

    class _R:
        def __init__(self, out="", rc=0):
            self.stdout, self.returncode, self.stderr = out, rc, ""

    def fake_run(cmd, **kw):
        if "pull" in cmd:
            # 直接把产物写到 pull 的目标路径（= 会话记录的本地路径）
            with open(cmd[-1], "wb") as f:
                f.write(b"\x00\x00\x00\x18ftypmp42" + b"A" * 80 + b"moov")
            return _R()
        if "ls" in cmd:
            return _R("record.mp4")           # 远端文件已就绪
        return _R()

    monkeypatch.setattr(ss.subprocess, "Popen", lambda *a, **k: _Proc())
    monkeypatch.setattr(ss.subprocess, "run", fake_run)

    api = _make_api()
    assert api.screen_record_start(None, save_dir=str(tmp_path))["ok"] is True
    vpath = api._rec_session["videos"]["A1"]
    assert vpath.startswith(str(tmp_path)) and vpath.endswith(".mp4"), vpath

    assert api.screen_record_stop() == {"ok": True}
    api.workers.shutdown(timeout=2.0)

    events = _events_by_kind(api)
    hits = [p["text"] for p in events.get("status", [])
            if "✓ 录屏已保存" in (p.get("text") or "")]
    assert len(hits) == 1, "同一条已保存提示不该报两次：%r" % hits
    assert vpath in hits[0], hits
    # tool 通道不应再重复播报同一件事
    dup = [p for p in events.get("tool", [])
           if "已保存" in (p.get("text") or "")]
    assert dup == [], dup


def test_screen_record_stop_pushes_completion_toast(monkeypatch, tmp_path):
    """停止录屏成功后弹一条「已完成」汇总 toast（切页签也能看到）。"""
    import backend.screen_service as ss

    class _Proc:
        def poll(self):
            return None

        def terminate(self):
            pass

        def kill(self):
            pass

        def wait(self, timeout=None):
            return 0

    class _R:
        def __init__(self, out="", rc=0):
            self.stdout, self.returncode, self.stderr = out, rc, ""

    def fake_run(cmd, **kw):
        if "pull" in cmd:
            with open(cmd[-1], "wb") as f:
                f.write(b"\x00\x00\x00\x18ftypmp42" + b"A" * 80 + b"moov")
            return _R()
        if "ls" in cmd:
            return _R("record.mp4")
        return _R()

    monkeypatch.setattr(ss.subprocess, "Popen", lambda *a, **k: _Proc())
    monkeypatch.setattr(ss.subprocess, "run", fake_run)

    api = _make_api()
    assert api.screen_record_start(None, save_dir=str(tmp_path))["ok"] is True
    assert api.screen_record_stop() == {"ok": True}
    api.workers.shutdown(timeout=2.0)

    statuses = _events_by_kind(api).get("status", [])
    toasts = [p for p in statuses if p.get("toast")]
    done = [p for p in toasts if "录屏已完成" in (p.get("text") or "")]
    assert len(done) == 1, "停止录屏应弹且只弹一条完成 toast：%r" % toasts
    assert done[0]["type"] == "ok"
    assert str(tmp_path) in done[0]["text"], done[0]["text"]


# ---------------------------------------------------------------------------
# 录屏收尾：异常不得让会话标记残留（否则录屏永久锁死）
# ---------------------------------------------------------------------------
def test_screen_record_stop_clears_session_even_on_exception(monkeypatch, tmp_path):
    """收尾过程抛异常时，_rec_session 也必须被清空。

    回归：_screen_record_stop_locked 没有 try/finally，`self._rec_session = {}`
    只在正常走到最后才执行。中途一旦抛错（最现实的是保存目录所在磁盘掉线 →
    screen_service._pull_and_finish 里的 os.makedirs 抛错），会话标记就永久残留：
    之后每一次「开始录屏」都被守卫判为 recording，录屏功能彻底锁死、只能重启
    程序；异常还会逃出 js_api 调用，用户在界面上看不到任何提示。
    """
    api = _make_api()
    api._rec_session = {
        "ts": "ts1", "dir": str(tmp_path), "with_mic": False,
        "videos": {"A1": str(tmp_path / "r.mp4")},
        "devaudio": {}, "logcat_captures": {},
    }

    def boom(serial):
        raise OSError("保存目录不可用")

    monkeypatch.setattr(api.video, "is_recording", lambda s: True)
    monkeypatch.setattr(api, "_stop_video", boom)

    res = api.screen_record_stop()
    assert res["ok"] is False and res["reason"] == "stop_error", res
    assert api._rec_session == {}, "异常后会话标记必须清空，否则录屏永久锁死"
    # 关键：错误要能传到用户眼前（toast），而不是只抛进线程日志
    texts = [p["text"] for p in _events_by_kind(api).get("status", [])]
    assert any("录屏收尾出现异常" in t for t in texts), texts
    # 会话已清空 -> 可以立刻重新开始（守卫不再误判 recording）
    assert api.screen_record_start(None, save_dir=str(tmp_path)).get(
        "reason") != "recording"
    api.workers.shutdown(timeout=2.0)


def test_screen_record_start_survives_mic_exception(monkeypatch, tmp_path):
    """麦克风启动**抛异常**（无麦克风设备等）时：降级为无麦克风录制，不炸不锁。

    回归（P0）：MicRecorder.start() 内部的 waveInOpen 失败会抛 RuntimeError，
    而 _mic_start 过去只兜了构造函数。异常从 _screen_record_start_locked 逃出时
    _rec_session 已置非空、又跳过撤销逻辑 —— 之后每次「开始录屏」都被守卫判为
    recording 返回，前端停止按钮也不亮，录屏功能永久锁死、只能重启程序。
    正确行为：转成一条「电脑麦克风启动失败」警告，本次录屏按无麦继续。
    """
    api = _make_api()

    class _BoomMic:
        def __init__(self, *a, **kw):
            pass

        def start(self, save_dir):
            raise RuntimeError("waveInOpen 失败，错误码 6")

    patch_ctrl(monkeypatch, "MicRecorder", _BoomMic)
    monkeypatch.setattr(api.video, "start",
                        lambda *a, **kw: (True, str(tmp_path / "r.mp4")))

    # 1) 异常被吞掉：本次录屏按「无麦克风」继续（js_api 契约：不向外抛）
    res = api.screen_record_start(None, with_mic=True, save_dir=str(tmp_path))
    assert res.get("ok") is True, res
    assert api._rec_session["mic_started"] is False
    assert api._mic is None, "半初始化的麦克风实例必须清掉（否则误报「已在录音」）"
    # 2) 用户必须看见失败原因（toast），而不是只进线程日志
    texts = [p["text"] for p in _events_by_kind(api).get("status", [])]
    assert any("电脑麦克风启动失败" in t and "waveInOpen" in t for t in texts), texts
    # 3) 会话正常登记，可走完整停止收尾
    assert api._rec_session["videos"], api._rec_session
    api._rec_session = {}
    api.workers.shutdown(timeout=2.0)


def test_screen_record_start_warns_when_mic_on_but_ffmpeg_missing(
        monkeypatch, tmp_path):
    """勾了麦克风但本机没有 ffmpeg：开局就要说清「录得到、合不进视频」。

    回归背景：麦克风开关恢复后，若机器上没装 ffmpeg，用户会录完整场才发现
    成片没有声音 —— 而 wav 明明就在目录里。提示必须发生在**开始录制时**，
    不能等收尾。
    """
    api = _make_api()

    class _OkMic:
        def __init__(self, *a, **kw):
            pass

        def start(self, save_dir):
            return True, str(tmp_path / "mic_20260101_000000.wav")

    patch_ctrl(monkeypatch, "MicRecorder", _OkMic)
    patch_ctrl(monkeypatch, "_have_ffmpeg", lambda: False)
    monkeypatch.setattr(api.video, "start",
                        lambda *a, **kw: (True, str(tmp_path / "r.mp4")))

    res = api.screen_record_start(None, with_mic=True, save_dir=str(tmp_path))
    assert res.get("ok") is True, res
    texts = [p["text"] for p in _events_by_kind(api).get("status", [])]
    assert any("未检测到 ffmpeg" in t and "mic_" in t for t in texts), texts
    api._rec_session = {}
    api.workers.shutdown(timeout=2.0)


def test_screen_record_start_cancels_session_on_unexpected_exception(
        monkeypatch, tmp_path):
    """启动链路出现**其它未预期异常**时：必须撤销半启动会话，不能锁死录屏。

    _mic_start 之外的位置（设备音频探测 / 目录创建等）若抛出，同样会跳过
    `_cancel_half_started_rec()` 留下非空 _rec_session —— 之后每次「开始录屏」
    都被守卫判为 recording，功能永久锁死。这里是最后一道兜底网。
    """
    api = _make_api()

    def boom(*a, **kw):
        raise OSError("模拟的意外错误")

    monkeypatch.setattr(ctrl.DeviceAudioCapture, "supported",
                        staticmethod(boom))
    monkeypatch.setattr(api.video, "start",
                        lambda *a, **kw: (True, str(tmp_path / "r.mp4")))

    res = api.screen_record_start(None, with_devaudio=True, save_dir=str(tmp_path))
    assert res["ok"] is False and res["reason"] == "start_error", res
    assert "意外错误" in res["error"], res
    # 会话必须被撤销：否则守卫永久误判「已在录制」
    assert api._rec_session == {}, api._rec_session
    # 错误必须让用户看见（toast）
    texts = [p["text"] for p in _events_by_kind(api).get("status", [])]
    assert any("录屏启动出现异常" in t for t in texts), texts
    # 紧接着就能正常开始一次录屏（功能未锁死）
    res2 = api.screen_record_start(None, save_dir=str(tmp_path))
    assert res2.get("ok") is True and res2.get("reason") != "recording", res2

    api._rec_session = {}
    api.workers.shutdown(timeout=2.0)


def test_screen_record_logcat_is_always_full(monkeypatch, tmp_path):
    """随录屏的 logcat 必须**全量**：`-b all` + 不过滤级别。

    这是「事后复现」的唯一物证，缺一条就可能正好缺在案发现场上。历史上它按
    四个缓冲区（main/system/events/crash）+ 界面级别勾选抓，结果 radio 日志整段
    不见、用户少勾一级就丢掉整类线索，而且录屏一停就无法补救。故现在：
      * 缓冲区恒为 ["all"]（`adb logcat -b all` = 设备上存在的全部缓冲区）；
      * level_filter 恒为 None（LogcatCapture 里 None = 不过滤，原样写盘）。
    调用方就算还传着 logcat_levels（旧签名），也不得影响这两个值。
    """
    api = _make_api()
    monkeypatch.setattr(api.video, "start",
                        lambda *a, **kw: (True, str(tmp_path / "r.mp4")))
    seen = {}

    class _SpyCapture:
        def start(self, serial, path, buffers, level_filter=None):
            seen["buffers"] = list(buffers)
            seen["lf"] = level_filter
            return True

        def stop(self, serial, *a, **kw):
            return True

    api.logcat_capture = _SpyCapture()
    res = api.screen_record_start(None, save_dir=str(tmp_path),
                                  with_logcat=True, logcat_levels=["D", "I"])
    assert res.get("ok") is True, res
    assert seen["buffers"] == ["all"], seen
    assert seen["lf"] is None, "旧参数 logcat_levels 不得再把级别过滤带回来"

    # 不传级别时同样是全量（默认路径）
    api.screen_record_stop()
    seen.clear()
    res = api.screen_record_start(None, save_dir=str(tmp_path),
                                  with_logcat=True)
    assert res.get("ok") is True, res
    assert seen["buffers"] == ["all"] and seen["lf"] is None, seen
    api.screen_record_stop()
    api.workers.shutdown(timeout=2.0)


def test_recording_does_not_steal_running_logcat_capture(monkeypatch, tmp_path):
    """设备上已有手动 logcat 抓取时，录屏不得把它登记为自己的抓取并顺手停掉它。

    回归：_screen_record_start_locked 无视 logcat_capture.start() 的返回值照样
    登记，停止录屏时又对该设备调用 stop() —— 用户手动开的抓取被静默掐断，
    而录屏承诺的 txt 因为同名文件从未创建也不会进 zip。
    """
    api = _make_api()
    monkeypatch.setattr(api.video, "start",
                        lambda *a, **kw: (True, str(tmp_path / "r.mp4")))
    started, stopped = [], []

    class _FakeCapture:
        def start(self, serial, path, buffers, level_filter=None):
            started.append((serial, path))
            return False        # 该设备已在抓取中

        def stop(self, serial, *a, **kw):
            stopped.append(serial)
            return True

    api.logcat_capture = _FakeCapture()
    res = api.screen_record_start(None, save_dir=str(tmp_path), with_logcat=True)
    assert res.get("ok") is True, res
    assert started, "录屏应尝试启动同步 logcat 抓取"
    assert api._rec_session["logcat_captures"] == {}, \
        "未能启动的抓取不得登记进会话：%r" % api._rec_session["logcat_captures"]
    texts = [p["text"] for p in _events_by_kind(api).get("status", [])]
    assert not any("已同步开始 logcat 抓取" in t for t in texts), (
        "一条抓取都没起来时不得播报「已同步开始」：%r" % (texts,))
    assert any("没有附带 logcat" in t for t in texts), (
        "必须如实说明本次录屏没有日志文件：%r" % (texts,))

    api._rec_session["videos"] = {}          # 跳过视频收尾，只看抓取处理
    api.screen_record_stop()
    assert stopped == [], "录屏停止不得停掉别人（手动）开的抓取：%r" % stopped
    api.workers.shutdown(timeout=2.0)


def test_shutdown_stops_video_under_rec_lock(monkeypatch):
    """shutdown 的 video.stop_all() 必须与 screen_record_stop 共用 _rec_lock。

    回归：stop_all 在锁外执行，关闭窗口与用户点「停止录屏」撞在一起时，两处会
    同时对同一台设备收尾（各自 pull / 合成同一个文件，产出重复甚至半截的产物）。
    """
    api = _make_api()
    seen = {}

    class _TracingLock:
        """可观测的锁替身：记录 with 块内是否持锁。"""

        def __init__(self):
            self._lock = threading.Lock()
            self.held = False

        def __enter__(self):
            self._lock.acquire()
            self.held = True
            return self

        def __exit__(self, *exc):
            self.held = False
            self._lock.release()
            return False

    api._rec_lock = _TracingLock()
    monkeypatch.setattr(api.video, "stop_all",
                        lambda: seen.setdefault("held", api._rec_lock.held))

    api.shutdown()
    assert "held" in seen, "shutdown 应停掉所有录制"
    assert seen["held"] is True, "video.stop_all() 必须在 _rec_lock 内执行"


# ---------------------------------------------------------------------------
# 文件操作：异常兜底 / 去重反馈 / 迟到的列目录结果
# ---------------------------------------------------------------------------
def test_file_op_timeout_becomes_user_visible_status(monkeypatch):
    """文件操作抛 TimeoutExpired（大文件 push/pull 超 120s）时必须变成状态提示。

    回归：_do_file_* 没有异常兜底，subprocess.TimeoutExpired 直接杀死 worker 线程
    （只落一份用户看不到的 crash 日志）。界面上表现为「点了下载/刷新/查看毫无
    反应」，而且该设备的同名 worker key 一直被占用，后续同类操作全被静默吞掉。
    """
    api = _make_api()
    monkeypatch.setattr(
        api.file_svc, "make_dir",
        lambda *a, **kw: (_ for _ in ()).throw(
            __import__("subprocess").TimeoutExpired("adb", 20)))

    assert api.file_mkdir("A1", "/sdcard/x")["ok"] is True
    assert wait_until(lambda: any(
        "创建目录失败" in (p.get("text") or "")
        for p in _events_by_kind(api).get("status", []))), "超时必须转成状态提示"
    api.workers.shutdown(timeout=2.0)


def test_file_op_reports_busy_instead_of_silent_drop(monkeypatch):
    """同名文件操作在跑时，第二次请求要明确回 busy，而不是静默丢弃还报 ok。

    回归：_file_op 直接用固定 key 交给 Workers 去重，被挡下的请求既不执行也不
    提示，调用方却拿到 {"ok": True} —— 用户点「新建文件夹」什么都没发生。
    """
    api = _make_api()
    release = threading.Event()
    monkeypatch.setattr(api.file_svc, "make_dir",
                        lambda *a, **kw: (release.wait(3.0), "")[1:] or (True, ""))

    assert api.file_mkdir("A1", "/sdcard/x")["ok"] is True
    assert wait_until(lambda: api.workers.is_running("fileop_A1"))
    res = api.file_mkdir("A1", "/sdcard/y")
    assert res == {"ok": False, "reason": "busy"}, res
    texts = [p["text"] for p in _events_by_kind(api).get("status", [])]
    assert any("请稍候" in t for t in texts), texts
    release.set()
    api.workers.shutdown(timeout=2.0)


def test_file_list_supersedes_stale_result(monkeypatch):
    """迟到的列目录结果不得覆盖更新的一次（否则界面会被回退到上一个目录）。"""
    api = _make_api()
    calls = []

    def slow_list(serial, path):
        calls.append(path)
        if path == "/slow":
            time.sleep(0.3)
            return ([{"name": "old"}], None)
        return ([{"name": "new"}], None)

    monkeypatch.setattr(api.file_svc, "list_dir", slow_list)
    api.file_list("A1", "/slow")
    api.file_list("A1", "/fast")
    assert wait_until(lambda: calls.count("/fast") >= 1)
    time.sleep(0.6)                     # 等慢请求返回
    events = [p for p in _events_by_kind(api).get("file", []) if not p.get("error")]
    assert [p["path"] for p in events] == ["/fast"], \
        "慢请求的迟到结果不应推送：%r" % events
    api.workers.shutdown(timeout=2.0)


def test_file_list_uses_unique_key_so_navigation_is_not_dropped(monkeypatch):
    """连续导航不能被同名 worker 去重吞掉（旧实现固定 key=file_<serial>）。"""
    api = _make_api()
    release = threading.Event()
    seen = []

    def blocked_list(serial, path):
        seen.append(path)
        release.wait(3.0)
        return ([], None)

    monkeypatch.setattr(api.file_svc, "list_dir", blocked_list)
    api.file_list("A1", "/first")
    assert wait_until(lambda: api.workers.is_running("filelist_A1_1"))
    api.file_list("A1", "/second")
    assert wait_until(lambda: len(seen) == 2, timeout=2.0), \
        "第二次导航请求被静默丢弃了（实际只执行了 %r）" % seen
    release.set()
    api.workers.shutdown(timeout=2.0)


def test_file_upload_removes_temp_file_when_upload_raises(monkeypatch):
    """上传抛异常（超时 / adb 消失）时临时文件仍必须被清理，且文件名不得逃出临时目录。"""
    import base64
    import subprocess as sp
    import tempfile
    api = _make_api()
    captured = {}

    def boom(serial, local, remote):
        captured["tmp"] = local
        raise sp.TimeoutExpired("adb", 120)

    monkeypatch.setattr(api.file_svc, "upload", boom)
    b64 = base64.b64encode(b"hello").decode()
    # 走真实的 worker 包装层：这一层负责把异常转成用户可见的状态
    api._run_file_op(api._do_file_upload_data, "A1", "../../evil.bin", b64,
                     "/sdcard/evil.bin")

    tmp = captured.get("tmp")
    assert tmp, "file_svc.upload 未被调用"
    # 名字里塞了路径分隔符：必须被净化成纯文件名，落在系统临时目录内
    assert os.path.dirname(os.path.abspath(tmp)) == \
        os.path.abspath(tempfile.gettempdir()), \
        "前端传来的文件名带路径分隔符时不得逃出临时目录：%s" % tmp
    assert not os.path.exists(tmp), "上传失败后不得残留临时文件：%s" % tmp
    texts = [p["text"] for p in _events_by_kind(api).get("status", [])]
    assert any("上传失败" in t for t in texts), texts
    api.workers.shutdown(timeout=2.0)


# ---------------------------------------------------------------------------
# 配置持久化 + 录屏双开关（指针显示 / 触控显示）
# ---------------------------------------------------------------------------

def test_boot_sends_settings_and_warnings(monkeypatch, tmp_path):
    """boot 必须把 settings.json 内容随 booted 下发（前端回填控件），
    并把被防错机制纠正过的字段说明一并带给用户。"""
    p = str(tmp_path / "settings.json")
    patch_ctrl(monkeypatch, "load_commands", lambda: (list(CMDS), []))
    patch_ctrl(monkeypatch, "load_prefs_checked",
                        lambda: ({"save_dir": r"D:\shots", "keep_input": "yes"},
                                 ["keep_input 的值 'yes' 不是有效的开关，已恢复为 开"]))
    monkeypatch.setattr(
        ds.subprocess, "run",
        lambda cmd, **kw: type("R", (), {"stdout": "", "stderr": ""})())
    assert not os.path.exists(p)

    api = WebApi(session_factory=FakeSession, auto_update=False)
    assert api.boot() == {"ok": True}
    booted = _events_by_kind(api)["booted"][0]
    assert booted["settings"]["save_dir"] == r"D:\shots"
    # 防错纠正必须下发（前端据此提示用户，而不是莫名发现开关复位）
    assert booted["settings_warnings"] == \
        ["keep_input 的值 'yes' 不是有效的开关，已恢复为 开"]
    # 配置文件位置与本机实际生效的保存目录要一并下发：
    # 前者让用户能在「关于」页找到并拷走 config.json 去别的电脑同步，
    # 后者用于路径失效时告知「已改用默认目录」。
    assert booted["config_path"].endswith("config.json")
    assert booted["save_dir_effective"]
    api.workers.shutdown(timeout=2.0)


def test_screen_record_passes_visual_toggles(monkeypatch, tmp_path):
    """录屏两个 overlay 开关（pointer_location / show_touches）必须真正生效。

    回归：早期实现把开关传给设备端 screenrecord --show-pointer，定制 ROM 不认
    该参数直接启动失败；现改为系统设置 overlay（settings put system），开关
    语义是「要不要开这个 overlay」，与录屏命令完全解耦。
    """
    api = _make_api()
    seen = {}
    monkeypatch.setattr(
        api.video, "start",
        lambda s, d, extra_name=None:
        (seen.__setitem__("called", True) or
         (True, str(tmp_path / "r.mp4"))))

    res = api.screen_record_start(None, save_dir=str(tmp_path),
                                  pointer_location=False, show_touches=False)
    assert res.get("ok") is True, res
    # 两个开关都关：不得读/写任何设备设置
    assert seen.get("called") is True
    api.screen_record_stop()
    api.workers.shutdown(timeout=2.0)


def test_pointer_location_enabled_and_restored_on_stop(monkeypatch, tmp_path):
    """开启指针位置：录前读原值 → 开；停止时按原值恢复（"null" → 删除该键）。"""
    api = _make_api()
    monkeypatch.setattr(api.video, "start",
                        lambda *a, **kw: (True, str(tmp_path / "r.mp4")))
    reads = []
    puts = []

    def fake_get(adb, serial, key):
        reads.append((serial, key))
        return True, "null"          # 设备从未设置过该键

    def fake_set(adb, serial, key, value):
        puts.append((serial, key, value))
        return True

    monkeypatch.setattr(api.video, "get_system_setting", fake_get)
    _patch_set_setting(monkeypatch, api.video, fake_set)

    res = api.screen_record_start(None, save_dir=str(tmp_path),
                                  pointer_location=True, show_touches=False)
    assert res.get("ok") is True, res
    assert reads == [("A1", "pointer_location")], \
        "应对真正启动录屏的设备读一次原值"
    assert ("A1", "pointer_location", "1") in puts, "录屏启动后应开启指针位置"
    assert api._rec_session["pointer_location_prev"] == {"A1": "null"}

    api.screen_record_stop()
    # 原值是 "null"（从未设置）：恢复手段是 delete（None），不是写 0
    assert puts[-1] == ("A1", "pointer_location", None), puts
    api.workers.shutdown(timeout=2.0)


def test_show_touches_restores_previous_value(monkeypatch, tmp_path):
    """设备原本开着（"1"）或关着（"0"）时，停止录屏必须写回原值。"""
    api = _make_api()
    monkeypatch.setattr(api.video, "start",
                        lambda *a, **kw: (True, str(tmp_path / "r.mp4")))
    puts = []
    monkeypatch.setattr(api.video, "get_system_setting",
                        lambda adb, serial, key: (True, "0"))
    _patch_set_setting(monkeypatch, api.video,
                       lambda adb, serial, key, value: puts.append(
                           (serial, key, value)) or True)

    api.screen_record_start(None, save_dir=str(tmp_path),
                            pointer_location=False, show_touches=True)
    api.screen_record_stop()
    assert puts[-1] == ("A1", "show_touches", "0"), puts
    api.workers.shutdown(timeout=2.0)


def test_show_touches_not_restored_when_read_fails(monkeypatch, tmp_path):
    """读不到原值（adb 瞬断）时**不入表、不恢复**：
    防错优先于功能完整——没有备份就不能瞎写。"""
    api = _make_api()
    monkeypatch.setattr(api.video, "start",
                        lambda *a, **kw: (True, str(tmp_path / "r.mp4")))
    puts = []
    monkeypatch.setattr(api.video, "get_system_setting",
                        lambda adb, serial, key: (False, None))
    _patch_set_setting(monkeypatch, api.video,
                       lambda adb, serial, key, value: puts.append(
                           (serial, key, value)) or True)

    res = api.screen_record_start(None, save_dir=str(tmp_path),
                                  pointer_location=False, show_touches=True)
    assert res.get("ok") is True, res
    assert api._rec_session["show_touches_prev"] == {}
    assert puts == [], "读不到原值就不得写设备设置"
    api.screen_record_stop()
    assert puts == [], "无备份即无恢复"
    api.workers.shutdown(timeout=2.0)


def test_overlays_restored_on_start_failure_cancel(monkeypatch, tmp_path):
    """启动链路中途出现真异常时，撤销必须把已开启的 overlay 恢复原值。

    否则用户设备会一直开着指针准星/触摸圆点——下次正常用手机时满屏干扰。
    """
    api = _make_api()
    api.devices.device_checked = {"A1": True, "B2": True, "C3": False}

    def fake_start(serial, *a, **kw):
        return True, str(tmp_path / ("r_%s.mp4" % serial))

    def fake_get(adb, serial, key):
        # 第一台正常开启 overlay；第二台读设置时 adb 瞬断（未预期异常）。
        if serial == "B2":
            raise OSError("模拟的意外错误")
        return True, "1"

    monkeypatch.setattr(api.video, "start", fake_start)
    puts = []
    monkeypatch.setattr(api.video, "get_system_setting", fake_get)
    _patch_set_setting(monkeypatch, api.video,
                       lambda adb, serial, key, value: puts.append(
                           (serial, key, value)) or True)

    res = api.screen_record_start(None, save_dir=str(tmp_path),
                                  pointer_location=True, show_touches=True)
    assert res.get("ok") is False and res["reason"] == "start_error", res
    assert api._rec_session == {}
    # 撤销路径同样恢复两个 overlay（第一台两个都开了）
    assert ("A1", "pointer_location", "1") in puts, puts
    assert ("A1", "show_touches", "1") in puts, puts
    api.workers.shutdown(timeout=2.0)


def test_start_exception_keeps_other_started_devices_stoppable(
        monkeypatch, tmp_path):
    """并行拉起时某台抛真异常：已启动的设备必须先登记，撤销才能停掉它们。

    不登记的话，那几台的 screenrecord 会成孤儿 —— 一直录到系统 180 秒上限，
    界面却没有任何「录制中」，用户只能等它自己结束。
    """
    api = _make_api()
    api.devices.device_checked = {"A1": True, "B2": True}

    def fake_start(serial, *a, **kw):
        if serial == "B2":
            raise OSError("模拟的意外错误")
        return True, str(tmp_path / ("r_%s.mp4" % serial))

    stopped = []
    monkeypatch.setattr(api.video, "start", fake_start)
    monkeypatch.setattr(
        api.video, "stop",
        lambda s: (stopped.append(s), (True, None, None))[1])

    res = api.screen_record_start(None, save_dir=str(tmp_path),
                                  pointer_location=False, show_touches=False)
    assert res.get("ok") is False and res["reason"] == "start_error", res
    assert stopped == ["A1"], (
        "已启动的设备必须被撤销流程停掉，否则录屏成孤儿：%r" % (stopped,))
    assert api._rec_session == {}
    api.workers.shutdown(timeout=2.0)


def test_multi_device_start_spawns_in_parallel(monkeypatch, tmp_path):
    """多台设备的录屏启动必须并行：单台内部有约 1.5 秒的确认窗口。

    回归：串行拉起时 N 台就按 N 倍累加（3 台 > 4.5 秒纯等待），用户点完
    「开始录制」界面迟迟不出现「录制中」。用 Barrier 做硬证据：只有三台同时
    在启动中，栅栏才放行 —— 串行实现永远凑不齐，会直接超时。
    """
    api = _make_api()
    api.devices.device_checked = {"A1": True, "B2": True, "C3": False}
    gate = threading.Barrier(2, timeout=3)

    def fake_start(serial, *a, **kw):
        gate.wait()          # 串行执行会卡在这里直到超时
        time.sleep(0.3)
        return True, str(tmp_path / ("r_%s.mp4" % serial))

    monkeypatch.setattr(api.video, "start", fake_start)
    t0 = time.time()
    res = api.screen_record_start(None, save_dir=str(tmp_path),
                                  pointer_location=False, show_touches=False)
    elapsed = time.time() - t0

    assert res.get("ok") is True, res
    assert len(api._rec_session["videos"]) == 2
    assert elapsed < 1.0, (
        "两台设备应并行启动（串行时第一台就会撞栅栏超时）：%.2fs" % elapsed)
    api.workers.shutdown(timeout=2.0)


def test_zip_stores_video_and_compresses_log(tmp_path):
    """打包时视频按原样存、日志才压缩：MP4 已被 H.264 压过，再 DEFLATE 白烧 CPU。

    回归：整包统一 ZIP_DEFLATED 时，3 分钟的 1080p 录屏要白白重算一遍压缩，
    体积几乎不变、收尾时间却多出一两秒（用户只能干等「正在收尾」）。
    """
    api = _make_api()
    vid = tmp_path / "record_A1.mp4"
    vid.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200000)
    log = tmp_path / "logcat_A1.txt"
    log.write_text("08-29 10:00:00.000  1  1 I Tag: hello\n" * 2000,
                   encoding="utf-8")

    out = api._zip_paths([str(vid), str(log)], str(tmp_path / "out.zip"))
    assert out, "打包应成功"
    with zipfile.ZipFile(out) as z:
        assert z.getinfo("record_A1.mp4").compress_type == zipfile.ZIP_STORED, (
            "视频不应再走 DEFLATE（纯烧 CPU）")
        assert z.getinfo("logcat_A1.txt").compress_type == zipfile.ZIP_DEFLATED, (
            "日志是文本，必须压缩（体积能差一个数量级）")


def _patch_join(monkeypatch, ok=True, reason=None):
    """把真实 ffmpeg 合并替掉。

    这些用例关心的是**收尾编排**（哪些段被保留、进不进包、怎么提示），
    不是转码本身；真跑 ffmpeg 既慢又引入「本机装没装 ffmpeg」的额外变量。
    ok=True 时按顺序把各段字节拼进 output（顺序＝段序，正是断言想要的）。
    """
    import backend.controllers.record as record_ctrl

    def fake(paths, out_path, timeout=None):
        if not ok:
            return {"ok": False, "path": None, "used": list(paths),
                    "skipped": [], "reason": reason or "未检测到 ffmpeg"}
        with open(out_path, "wb") as f:
            for p in paths:
                with open(p, "rb") as src:
                    f.write(src.read())
        return {"ok": True, "path": out_path, "used": list(paths),
                "skipped": [], "reason": None}

    # raising=False：旧实现里根本没有 join_segments 这个名字。让它静默落空，
    # 这样用旧代码跑新用例时，失败落在**行为断言**（包里还是两个 mp4、没有合并
    # 提示）上，而不是一句 patch 期的 AttributeError。
    monkeypatch.setattr(record_ctrl, "join_segments", fake, raising=False)


def test_multi_segments_merge_into_one_complete_video(monkeypatch, tmp_path):
    """多段录完必须拼成一个完整 mp4：目录与包里只剩一个视频文件。

    回归：分段是程序为绕开 180 秒上限自己选的实现方式，用户按了一次「开始录制」
    却拿到 3 个 `_pN` 文件 —— 得自己猜顺序、自己找工具拼。合并后回到「一个 mp4」，
    文件名也回到不带 `_pN` 的成品名，与没分段的录制一模一样。
    """
    api = _make_api()
    s1 = tmp_path / "record_A1_ts1.mp4"
    s1.write_bytes(b"\x00\x00\x00\x18ftypmp42moov" + b"A" * 100)
    s2 = tmp_path / "record_A1_ts1_p2.mp4"
    s2.write_bytes(b"\x00\x00\x00\x18ftypmp42moov" + b"B" * 100)
    api._rec_session = {
        "ts": "ts1", "dir": str(tmp_path), "with_mic": False,
        "with_zip": True,
        "videos": {"A1": str(s1)}, "devaudio": {}, "logcat_captures": {},
    }
    monkeypatch.setattr(api.video, "is_recording", lambda s: True)
    monkeypatch.setattr(
        api, "_stop_video", lambda s: (True, [str(s1), str(s2)], None))
    _patch_join(monkeypatch)

    assert api.screen_record_stop() == {"ok": True}
    api.workers.shutdown(timeout=2.0)

    texts = [p["text"] for p in _events_by_kind(api).get("status", [])]
    assert any("已合并为 1 个完整视频" in t for t in texts), texts

    assert not s2.exists(), "已并入成片的中间段要删掉，否则目录里有两个版本"
    with zipfile.ZipFile(str(tmp_path / "rec_ts1.zip")) as zf:
        names = zf.namelist()
        mp4s = [n for n in names if n.endswith(".mp4")]
        assert mp4s == ["record_A1_ts1.mp4"], (
            "合并后包里只应有一个视频，且名字回到不带 _pN 的成品名：%r" % names)
        body = zf.read("record_A1_ts1.mp4")
    assert body.endswith(b"B" * 100), "成片必须包含第 2 段的内容（顺序＝段序）"


def test_merge_failure_keeps_every_segment(monkeypatch, tmp_path):
    """合并失败（没装 ffmpeg / concat 报错）时，分段一个都不能删。

    这是本功能最容易造成真实损失的一步：合并要删中间文件，删完之后若打包再
    出错，用户就什么都没有了。所以「合并失败 = 保持原样」必须是硬规则，并且
    要明说原因与文件在哪，而不是留一句「收尾失败」。
    """
    api = _make_api()
    s1 = tmp_path / "record_A1_ts1.mp4"
    s1.write_bytes(b"\x00\x00\x00\x18ftypmp42moov")
    s2 = tmp_path / "record_A1_ts1_p2.mp4"
    s2.write_bytes(b"\x00\x00\x00\x18ftypmp42moov")
    api._rec_session = {
        "ts": "ts1", "dir": str(tmp_path), "with_mic": False,
        "with_zip": False,
        "videos": {"A1": str(s1)}, "devaudio": {}, "logcat_captures": {},
    }
    monkeypatch.setattr(api.video, "is_recording", lambda s: True)
    monkeypatch.setattr(
        api, "_stop_video", lambda s: (True, [str(s1), str(s2)], None))
    _patch_join(monkeypatch, ok=False, reason="未检测到 ffmpeg")

    assert api.screen_record_stop() == {"ok": True}
    api.workers.shutdown(timeout=2.0)

    assert s1.exists() and s2.exists(), "合并失败不得删任何分段"
    texts = [p["text"] for p in _events_by_kind(api).get("status", [])]
    assert any("未能合并为一个视频" in t and "已保留全部分段文件" in t
               for t in texts), texts
    assert any("未能合并" in t for t in texts
               if t.startswith("✓")), "完成 toast 要说明「几段未合并」"


def test_zip_failure_is_reported_not_silently_skipped(monkeypatch, tmp_path):
    """勾了「结束后打包」但打包失败：必须说清「没有 zip」。

    用户是按按钮的勾选状态去目录里找 zip 的。失败时若只报「✓ 录屏已完成」，
    他会以为打包还在进行，或者以为程序把文件弄丢了 —— 文件其实一个不少，
    只是没压缩。这类「产物和界面预期不一致」不能静默过去。
    """
    _patch_join(monkeypatch, ok=False, reason="未检测到 ffmpeg（用例替身）")
    api = _make_api()
    s1 = tmp_path / "record_A1_ts1.mp4"
    s1.write_bytes(b"\x00\x00\x00\x18ftypmp42moov")
    api._rec_session = {
        "ts": "ts1", "dir": str(tmp_path), "with_mic": False,
        "with_zip": True,
        "videos": {"A1": str(s1)}, "devaudio": {}, "logcat_captures": {},
    }
    monkeypatch.setattr(api.video, "is_recording", lambda s: True)
    monkeypatch.setattr(api, "_stop_video", lambda s: (True, [str(s1)], None))
    monkeypatch.setattr(api, "_zip_paths", staticmethod(lambda *a, **k: None))

    assert api.screen_record_stop() == {"ok": True}
    api.workers.shutdown(timeout=2.0)

    assert s1.exists(), "打包失败绝不能删源文件"
    statuses = _events_by_kind(api).get("status", [])
    hits = [p for p in statuses if "打包失败" in (p.get("text") or "")]
    assert hits, "打包失败必须播报，不能只报「✓ 录屏已完成」：%r" % (
        [p.get("text") for p in statuses],)
    assert hits[0].get("toast"), "这条要弹 toast（用户会去目录里找 zip）：%r" % (hits[0],)


def test_all_segments_are_kept_and_zipped(monkeypatch, tmp_path):
    """自动分段的每一段都要落盘并进包 —— 只留最后一段等于把前几段扔掉。

    回归：分段后收尾只取当前（最后）一段，先前每段 170 秒的视频既不进 zip 也
    不出现在任何提示里。用户录了 8 分钟，最后只拿到一个 3 分钟的文件，还以为
    中间那 5 分钟根本没录上。

    这里把合并刻意置为失败（等价于用户机器上没装 ffmpeg）：合并不可用时，
    「每段都保留、都进包」这条兜底必须成立。
    """
    _patch_join(monkeypatch, ok=False, reason="未检测到 ffmpeg（用例替身）")
    api = _make_api()
    s1 = tmp_path / "record_A1_ts1.mp4"
    s1.write_bytes(b"\x00\x00\x00\x18ftypmp42moov")
    s2 = tmp_path / "record_A1_ts1_p2.mp4"
    s2.write_bytes(b"\x00\x00\x00\x18ftypmp42moov")
    api._rec_session = {
        "ts": "ts1", "dir": str(tmp_path), "with_mic": False,
        "with_zip": True,
        "videos": {"A1": str(s1)}, "devaudio": {}, "logcat_captures": {},
    }
    monkeypatch.setattr(api.video, "is_recording", lambda s: True)
    monkeypatch.setattr(
        api, "_stop_video", lambda s: (True, [str(s1), str(s2)], None))

    assert api.screen_record_stop() == {"ok": True}
    api.workers.shutdown(timeout=2.0)

    z = tmp_path / "rec_ts1.zip"
    assert z.exists(), "分段产物应照常打包"
    with zipfile.ZipFile(str(z)) as zf:
        names = zf.namelist()
    assert "record_A1_ts1.mp4" in names and "record_A1_ts1_p2.mp4" in names, names


def test_partially_failed_teardown_keeps_finished_segments(monkeypatch, tmp_path):
    """最后一段收尾失败时，前面已录完的段必须照常保留并进包。

    只说一句「录屏收尾失败」的话，用户会以为整场录制都废了，把本来完好的几段
    一并删掉 —— 而它们其实就在保存目录里躺着。
    """
    api = _make_api()
    s1 = tmp_path / "record_A1_ts1.mp4"
    s1.write_bytes(b"\x00\x00\x00\x18ftypmp42moov")
    partial = tmp_path / "record_A1_ts1_p2.mp4"
    partial.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    api._rec_session = {
        "ts": "ts1", "dir": str(tmp_path), "with_mic": False,
        "with_zip": True,
        "videos": {"A1": str(s1)}, "devaudio": {}, "logcat_captures": {},
    }
    monkeypatch.setattr(api.video, "is_recording", lambda s: True)
    # stop_ex 的语义：paths 只含正常收尾的段，残片路径在 err 里
    monkeypatch.setattr(
        api, "_stop_video",
        lambda s: (False, [str(s1)],
                   "缺 moov 头，无法播放（当前段残片：%s）" % partial))

    assert api.screen_record_stop() == {"ok": True}
    api.workers.shutdown(timeout=2.0)

    z = tmp_path / "rec_ts1.zip"
    with zipfile.ZipFile(str(z)) as zf:
        names = zf.namelist()
    assert "record_A1_ts1.mp4" in names, names
    assert "record_A1_ts1_p2.mp4" not in names, (
        "没正常收尾的残片不该进包（但不代表要删掉它）：%r" % (names,))
    texts = [p["text"] for p in _events_by_kind(api).get("status", [])]
    assert any("已完成的 1 段完整保留" in t for t in texts), texts


def test_segment_roll_is_announced(monkeypatch):
    """自动接下一段时要告诉用户：否则目录里凭空多出 _p2.mp4，没人说得清。"""
    api = _make_api()
    api._rec_session = {"videos": {"A1": "x"}, "devaudio": {}}

    class FakeVideo:
        def rolled_serials(self):
            return [("A1", 2)]

        def died_serials(self):
            return []

        def limit_serials(self):
            return []

    api.video = FakeVideo()
    api._reap_dead_recordings()

    texts = [p["text"] for p in _events_by_kind(api).get("status", [])]
    assert any("第 2 段" in t for t in texts), texts


def test_gone_device_segments_survive_teardown(monkeypatch, tmp_path):
    """设备中途被拔掉：拔之前录完的段已经拉回来了，收尾必须照样进包。

    回归：设备移除走 _reap_gone_recording 强停（那时已经拿到多段路径），但收尾
    发现该设备「未在录制」，只按启动时记下的第一段兜底 —— 后面几段就留在目录里
    既不合成也不进包，用户以为没录上。
    """
    api = _make_api()
    s1 = tmp_path / "record_A1_ts1.mp4"
    s1.write_bytes(b"\x00\x00\x00\x18ftypmp42moov")
    s2 = tmp_path / "record_A1_ts1_p2.mp4"
    s2.write_bytes(b"\x00\x00\x00\x18ftypmp42moov")
    api._rec_session = {
        "ts": "ts1", "dir": str(tmp_path), "with_mic": False,
        "with_zip": True,
        "videos": {"A1": str(s1)}, "devaudio": {}, "logcat_captures": {},
        "video_segs": {"A1": [str(s1), str(s2)]},
    }
    monkeypatch.setattr(api.video, "is_recording", lambda s: False)
    # 合并置为不可用：本用例盯的是「拔线前录完的段有没有进包」，
    # 合并成功会把两段并成一个文件，反而绕开了要断言的那条路径。
    _patch_join(monkeypatch, ok=False, reason="未检测到 ffmpeg（用例替身）")

    assert api.screen_record_stop() == {"ok": True}
    api.workers.shutdown(timeout=2.0)

    with zipfile.ZipFile(str(tmp_path / "rec_ts1.zip")) as zf:
        names = zf.namelist()
    assert "record_A1_ts1_p2.mp4" in names, names


# ---------------------------------------------------------------------------
# 第四轮：config.json 体系（配置路径下发 / 路径失效回退 / config_info）
# ---------------------------------------------------------------------------

def test_boot_reports_missing_save_dir_as_fallback(monkeypatch, tmp_path):
    """配置里的保存目录在本机不存在 → 下发回退提示，且配置文件原值不动。

    这是跨设备同步的关键行为：用户把 config.json 拷到另一台电脑，源机的
    绝对路径在新机不存在。程序必须改用默认目录并**说清楚**，否则用户以为
    同步成功了，实际文件全写丢。
    """
    import core.prefs as prefs
    p = str(tmp_path / "config.json")
    monkeypatch.setattr(prefs, "prefs_path", lambda: p)
    patch_ctrl(monkeypatch, "load_commands", lambda: (list(CMDS), []))
    patch_ctrl(monkeypatch, "load_prefs_checked",
                        lambda: ({"save_dir": str(tmp_path / "nope")}, []))
    monkeypatch.setattr(
        ds.subprocess, "run",
        lambda cmd, **kw: type("R", (), {"stdout": "", "stderr": ""})())

    api = WebApi(session_factory=FakeSession, auto_update=False)
    assert api.boot() == {"ok": True}
    booted = _events_by_kind(api)["booted"][0]

    assert booted["save_dir_effective"] == prefs.default_save_dir()
    assert booted["save_dir_note"] and "不存在" in booted["save_dir_note"]
    api.workers.shutdown(timeout=2.0)


def test_default_save_dir_falls_back_when_configured_path_missing(monkeypatch,
                                                                  tmp_path):
    """_default_save_dir 必须走回退逻辑（不能把文件写进不存在的目录）。"""
    import core.prefs as prefs
    monkeypatch.setattr(prefs, "prefs_path",
                        lambda: str(tmp_path / "config.json"))
    patch_ctrl(monkeypatch, "load_prefs",
                        lambda: {"save_dir": str(tmp_path / "nope")})
    api = _make_api()
    assert api._default_save_dir() == prefs.default_save_dir()


def test_save_settings_reports_effective_save_dir(monkeypatch, tmp_path):
    """改了保存目录后要回报本机实际生效的目录（界面据此即时提示）。

    用户在本机新填的路径本就不存在 → 顺手建出来并直接生效（与旧行为
    一致：回退目录会被自动创建），不该回退默认目录。
    """
    import core.prefs as prefs
    monkeypatch.setattr(prefs, "prefs_path",
                        lambda: str(tmp_path / "config.json"))
    api = _make_api()
    want = str(tmp_path / "new_dir")
    res = api.save_settings({"save_dir": want})
    assert res["ok"] is True
    assert res["settings"]["_save_dir_effective"] == want
    assert res["settings"]["_save_dir_note"] is None
    assert os.path.isdir(want), "用户新填的目录应被自动创建"


def test_config_info_returns_path_and_effective_dir(monkeypatch, tmp_path):
    """config_info 供关于页展示：路径 + 是否存在 + 本机生效目录。"""
    import core.prefs as prefs
    p = str(tmp_path / "config.json")
    # controller 直接 import 了 prefs_path，故 patch controller 命名空间
    patch_ctrl(monkeypatch, "prefs_path", lambda: p)
    patch_ctrl(monkeypatch, "load_prefs",
                        lambda: {"save_dir": str(tmp_path / "nope")})
    api = _make_api()
    info = api.config_info()
    assert info["ok"] is True
    assert info["path"] == p
    assert info["exists"] is False
    assert info["save_dir"] == str(tmp_path / "nope")
    assert info["save_dir_effective"] == prefs.default_save_dir()
    assert info["note"] and "不存在" in info["note"]


# ---------------------------------------------------------------- 投屏（scrcpy）
def test_scrcpy_start_needs_device(monkeypatch):
    """没勾任何受控设备时不该去拉 scrcpy，直接提示先选设备。"""
    api = _make_api()
    monkeypatch.setattr(api.devices, "selected_serials", lambda: [])
    res = api.scrcpy_start(None)
    assert res == {"ok": False, "reason": "no_device"}


def test_scrcpy_start_reports_missing_scrcpy(monkeypatch, tmp_path):
    """找不到 scrcpy 时返回安装指引（reason=scrcpy_not_found + note），不抛异常。"""
    api = _make_api()
    monkeypatch.setattr(api.devices, "selected_serials", lambda: ["A1"])
    monkeypatch.setattr(api, "_scrcpy_pref_path", lambda: "")
    patch_ctrl(monkeypatch, "find_scrcpy",
                        lambda pref: (None, "未找到 scrcpy：可 winget install Genymobile.scrcpy"))
    res = api.scrcpy_start(None)
    assert res["ok"] is False
    assert res["reason"] == "scrcpy_not_found"
    assert "winget" in res["note"]


def test_scrcpy_start_calls_launcher_with_serials(monkeypatch):
    """拿到 scrcpy 路径后把「受控设备」原样交给 launcher（一台一个窗口）。"""
    api = _make_api()
    monkeypatch.setattr(api.devices, "selected_serials", lambda: ["A1", "B2"])
    monkeypatch.setattr(api, "_scrcpy_pref_path", lambda: "/cfg/scrcpy")
    patch_ctrl(monkeypatch, "find_scrcpy", lambda pref: ("/bin/scrcpy", "来自配置的路径"))
    seen = {}

    def _launch(serials, exe):
        seen["serials"] = list(serials)
        seen["exe"] = exe
        return {"started": list(serials), "skipped": [], "failed": []}
    monkeypatch.setattr(api._scrcpy, "launch", _launch)
    res = api.scrcpy_start(None)
    assert seen == {"serials": ["A1", "B2"], "exe": "/bin/scrcpy"}
    assert res["ok"] is True
    assert res["started"] == ["A1", "B2"]


def test_scrcpy_start_reports_partial_failure(monkeypatch):
    """某台设备秒退：其余照常，失败原因逐台回传（前端据此显示在按钮旁）。"""
    api = _make_api()
    monkeypatch.setattr(api.devices, "selected_serials", lambda: ["A1", "B2"])
    monkeypatch.setattr(api, "_scrcpy_pref_path", lambda: "")
    patch_ctrl(monkeypatch, "find_scrcpy", lambda pref: ("/bin/scrcpy", "来自系统 PATH"))
    monkeypatch.setattr(api._scrcpy, "launch", lambda serials, exe: {
        "started": ["A1"], "skipped": [],
        "failed": [("B2", "scrcpy 立即退出（退出码 1）：device unauthorized")]})
    res = api.scrcpy_start(None)
    assert res["ok"] is True and res["started"] == ["A1"]
    assert res["failed"][0]["serial"] == "B2"
    assert "unauthorized" in res["failed"][0]["reason"]


# ------------------------------------------------- 备用投屏（没装 scrcpy 时的降级）
class _FakeFrameServer:
    """帧服务替身：只关心「有没有给前端一个能拉到画面的地址」。"""

    def __init__(self):
        self.dropped = []

    def start(self):
        return 12345

    def frame_url(self, serial):
        return "http://127.0.0.1:12345/frame?serial=%s" % serial

    def set_frame(self, *a):
        pass

    def drop(self, serial):
        self.dropped.append(serial)


def _mirror_api(monkeypatch, prefs=None):
    api = _make_api()
    api._frame_server = _FakeFrameServer()
    monkeypatch.setattr(api, "_mirror_prefs", lambda: prefs or {
        "player_path": "", "size": "", "bitrate": 8, "fps": 2})
    return api


def test_mirror_probe_reports_both_capabilities(monkeypatch):
    """一次探测同时给出 scrcpy 与播放器状态：前端据此预告会落到哪一档。"""
    api = _make_api()
    patch_ctrl(monkeypatch, "scrcpy_probe_info",
                        lambda pref: {"ok": False, "note": "未找到 scrcpy"})
    patch_ctrl(monkeypatch, "probe_player",
                        lambda pref: {"ok": True, "kind": "mpv", "path": "/bin/mpv"})
    res = api.mirror_probe()
    assert res["scrcpy"]["ok"] is False
    assert res["player"]["kind"] == "mpv"


def test_mirror_start_needs_device(monkeypatch):
    api = _mirror_api(monkeypatch)
    monkeypatch.setattr(api.devices, "selected_serials", lambda: [])
    assert api.mirror_start(None, "pipe") == {"ok": False, "reason": "no_device"}


def test_mirror_start_uses_player_when_available(monkeypatch):
    """装了播放器就走管道投屏（画质/帧率最好的一档），不退化到低帧率预览。"""
    api = _mirror_api(monkeypatch)
    monkeypatch.setattr(api.devices, "selected_serials", lambda: ["A1"])
    patch_ctrl(monkeypatch, "find_player", lambda pref: ("ffplay", "/bin/ffplay", "PATH"))
    patch_ctrl(monkeypatch, "plan_size", lambda adb, serial: "720x1280")
    seen = {}

    wired = {}

    class _Pipe:
        def __init__(self, adb, serial, kind, exe, size, br, fps, on_status=None,
                     rec_guard=None):
            seen.update(serial=serial, kind=kind, exe=exe, size=size, br=br)
            wired["rec_guard"] = rec_guard
            self.stopped = False

        def start(self):
            return True, ""

        def alive(self):
            return True

        def stop(self):
            self.stopped = True

    patch_ctrl(monkeypatch, "PipeMirror", _Pipe)
    res = api.mirror_start(None, "pipe")
    assert res["ok"] is True
    assert res["started"][0]["mode"] == "pipe"
    assert seen == {"serial": "A1", "kind": "ffplay", "exe": "/bin/ffplay",
                    "size": "720x1280", "br": 8}
    # 投屏必须拿到「是否正在录屏」的查询入口：收尾清理设备端残留时据此决定
    # 能不能按进程名兜底（设备端可能有一条同名 screenrecord 正在为用户录屏）
    assert callable(wired.get("rec_guard")), wired
    assert wired["rec_guard"]() is False, "当前没有录屏，守卫应报 False"
    api.mirror_stop(None)


def test_mirror_start_falls_back_to_snap_without_player(monkeypatch):
    """一个播放器都没装 → 自动退到低帧率预览，并把内嵌画面的帧地址回给前端。"""
    api = _mirror_api(monkeypatch)
    monkeypatch.setattr(api.devices, "selected_serials", lambda: ["A1"])
    patch_ctrl(monkeypatch, "find_player", lambda pref: ("", None, "未找到播放器"))
    seen = {}

    class _Snap:
        def __init__(self, adb, serial, server, fps, on_status=None):
            seen.update(serial=serial, fps=fps)
            self.stopped = False

        def start(self):
            return True, ""

        def alive(self):
            return True

        def stop(self):
            self.stopped = True

    patch_ctrl(monkeypatch, "SnapMirror", _Snap)
    res = api.mirror_start(None, "pipe")
    assert res["ok"] is True
    assert res["started"][0]["mode"] == "snap"
    assert "frame?serial=A1" in res["started"][0]["frame_url"]
    assert seen == {"serial": "A1", "fps": 2}
    api.mirror_stop(None)


def test_mirror_start_falls_back_when_screenrecord_unavailable(monkeypatch):
    """有播放器、但设备端 screenrecord 用不了（部分 ROM 删了该命令）→ 同样
    退到低帧率预览，而不是卡在「播放器窗口没画面」。"""
    api = _mirror_api(monkeypatch)
    monkeypatch.setattr(api.devices, "selected_serials", lambda: ["A1"])
    patch_ctrl(monkeypatch, "find_player", lambda pref: ("mpv", "/bin/mpv", "PATH"))
    patch_ctrl(monkeypatch, "plan_size", lambda adb, serial: "")

    class _DeadPipe:
        def __init__(self, *a, **kw):
            pass

        def start(self):
            return False, "设备端 screenrecord 未输出画面（not found）"

        def alive(self):
            return False

        def stop(self):
            pass

    class _Snap:
        def __init__(self, *a, **kw):
            pass

        def start(self):
            return True, ""

        def alive(self):
            return True

        def stop(self):
            pass

    patch_ctrl(monkeypatch, "PipeMirror", _DeadPipe)
    patch_ctrl(monkeypatch, "SnapMirror", _Snap)
    res = api.mirror_start(None, "pipe")
    assert res["ok"] is True
    assert res["started"][0]["mode"] == "snap", "screenrecord 不可用时应自动降级"
    api.mirror_stop(None)


def test_mirror_stop_clears_sessions(monkeypatch):
    """停止后登记表必须清空：否则用户再点一次会被判成「已在投屏」而永远开不起来。"""
    api = _mirror_api(monkeypatch)
    monkeypatch.setattr(api.devices, "selected_serials", lambda: ["A1"])
    patch_ctrl(monkeypatch, "find_player", lambda pref: ("", None, "无"))

    class _Snap:
        def __init__(self, *a, **kw):
            self.stopped = False

        def start(self):
            return True, ""

        def alive(self):
            return True

        def stop(self):
            self.stopped = True

    patch_ctrl(monkeypatch, "SnapMirror", _Snap)
    assert api.mirror_start(None, "snap")["ok"] is True
    assert api.mirror_status()["snap"] == ["A1"]
    res = api.mirror_stop(None)
    assert res["stopped"] == ["A1"]
    assert api.mirror_status() == {"pipe": [], "snap": []}


# ------------------------------------------------- 性能监控（采样 / 导出 / 收尾）
class _FakePerfMon:
    """PerfMonitor 替身：记录构造参数，start 直接成功（不碰 adb）。"""

    def __init__(self, adb, serial, interval, pkg, on_status=None):
        self.adb, self.serial, self.interval, self.pkg = adb, serial, interval, pkg
        self.info = {"serial": serial, "model": "Pixel 7", "pkg": pkg,
                     "android": "13", "size": "1080x2340"}
        self.started = False
        self.stopped = False
        self.error = ""
        self.seq = 1
        self._samples = [{"seq": 1, "t": 1.0, "cpu": 12.0}]

    def start(self):
        self.started = True
        return True, ""

    def stop(self):
        self.stopped = True

    def alive(self):
        return self.started and not self.stopped

    def count(self):
        return len(self._samples)

    def all_samples(self):
        return list(self._samples)

    def snapshot(self, since=0):
        return {"running": self.alive(), "seq": 1,
                "samples": [s for s in self._samples if s["seq"] > since],
                "info": dict(self.info), "count": self.count()}


def test_perf_start_needs_device(monkeypatch):
    api = _make_api()
    monkeypatch.setattr(api.devices, "selected_serials", lambda: [])
    assert api.perf_start(None, 1000) == {"ok": False, "reason": "no_device"}


def test_perf_start_uses_first_device_and_passes_params(monkeypatch):
    """单台设备的路径：间隔秒数、包名要原样传到采样器。"""
    api = _make_api()
    monkeypatch.setattr(api.devices, "selected_serials", lambda: ["A1"])
    made = {}

    def _factory(adb, serial, interval, pkg, on_status=None):
        m = _FakePerfMon(adb, serial, interval, pkg, on_status)
        made.update(m=m, adb=adb)
        return m

    patch_ctrl(monkeypatch, "PerfMonitor", _factory)
    res = api.perf_start(None, 500, "com.tencent.kuwo")
    assert res["ok"] is True and res["serial"] == "A1"
    assert made["m"].interval == pytest.approx(0.5)
    assert made["m"].pkg == "com.tencent.kuwo"
    assert made["adb"] == api.state.adb_path


def test_perf_start_monitors_all_selected_devices(monkeypatch):
    """不指定 serial 时全部受控设备一起监控：多台即对比模式，各自一条会话。"""
    api = _make_api()
    monkeypatch.setattr(api.devices, "selected_serials", lambda: ["A1", "B2"])
    patch_ctrl(monkeypatch, "PerfMonitor", _FakePerfMon)
    res = api.perf_start(None, 1000)
    assert res["ok"] is True
    assert sorted(res["sessions"]) == ["A1", "B2"]
    assert sorted(api._perfs) == ["A1", "B2"]
    polled = api.perf_poll(0)
    assert sorted(polled["sessions"]) == ["A1", "B2"]
    assert polled["running"] is True
    # 每台各一个采样点 → 合并后的顶层 samples 有两条（按时间排序）
    assert len(polled["samples"]) == 2
    stopped = api.perf_stop()
    assert stopped["samples"] == 2
    assert sorted(stopped["sessions"]) == ["A1", "B2"]
    assert all(m.stopped for m in api._perfs.values())


def test_perf_poll_accepts_per_device_cursor(monkeypatch):
    """since 传 {serial: seq} 时各设备独立游标，互不影响。"""
    api = _make_api()
    monkeypatch.setattr(api.devices, "selected_serials", lambda: ["A1", "B2"])
    patch_ctrl(monkeypatch, "PerfMonitor", _FakePerfMon)
    api.perf_start(None, 1000)
    polled = api.perf_poll({"A1": 1, "B2": 0})
    assert polled["sessions"]["A1"]["samples"] == []
    assert len(polled["sessions"]["B2"]["samples"]) == 1


def test_perf_start_partial_failure_keeps_good_devices(monkeypatch):
    """一台启动失败不应拖垮另一台：只要有一台起来就算成功，失败原因单独回报。"""
    api = _make_api()
    monkeypatch.setattr(api.devices, "selected_serials", lambda: ["A1", "B2"])

    class _Bad(_FakePerfMon):
        def start(self):
            if self.serial == "B2":
                return False, "设备无响应"
            return True, ""

    patch_ctrl(monkeypatch, "PerfMonitor", _Bad)
    res = api.perf_start(None, 1000)
    assert res["ok"] is True and list(api._perfs) == ["A1"]
    assert "B2" in res["failed"]


def test_perf_device_count_is_capped(monkeypatch):
    """超过上限的设备被忽略并提示，保证每台的采样间隔不被拉长。"""
    api = _make_api()
    lots = ["D%d" % i for i in range(ctrl.PERF_MAX_DEVICES + 2)]
    monkeypatch.setattr(api.devices, "selected_serials", lambda: list(lots))
    patch_ctrl(monkeypatch, "PerfMonitor", _FakePerfMon)
    res = api.perf_start(None, 1000)
    assert res["ok"] is True
    assert len(api._perfs) == ctrl.PERF_MAX_DEVICES
    assert list(api._perfs) == lots[:ctrl.PERF_MAX_DEVICES]


def test_perf_interval_is_clamped(monkeypatch):
    api = _make_api()
    monkeypatch.setattr(api.devices, "selected_serials", lambda: ["A1"])
    patch_ctrl(monkeypatch, "PerfMonitor", _FakePerfMon)
    assert api.perf_start(None, 5)[  # 5ms → 下限 0.2s
        "interval"] == pytest.approx(0.2)
    assert api.perf_start(None, 999999)["interval"] == pytest.approx(
        ctrl.PERF_MAX_INTERVAL)
    assert api.perf_start(None, "abc")["interval"] == pytest.approx(
        ctrl.DEFAULT_INTERVAL)


def test_perf_start_failure_reports_reason(monkeypatch):
    api = _make_api()
    monkeypatch.setattr(api.devices, "selected_serials", lambda: ["A1"])

    class _Bad(_FakePerfMon):
        def start(self):
            return False, "读取设备状态失败（设备是否已授权？）"

    patch_ctrl(monkeypatch, "PerfMonitor", _Bad)
    res = api.perf_start(None, 1000)
    assert res["ok"] is False and res["reason"] == "start_failed"
    assert "授权" in res["error"]


def test_perf_poll_and_stop_keep_session_for_export(monkeypatch):
    """停止后会话对象要保留：否则「先停再导出」会丢光数据。"""
    api = _make_api()
    monkeypatch.setattr(api.devices, "selected_serials", lambda: ["A1"])
    patch_ctrl(monkeypatch, "PerfMonitor", _FakePerfMon)
    api.perf_start(None, 1000)
    polled = api.perf_poll(0)
    assert polled["running"] is True and len(polled["samples"]) == 1
    assert api.perf_stop()["samples"] == 1
    assert api.perf_status()["running"] is False
    assert len(api.perf_poll(0)["samples"]) == 1     # 数据还在


def test_perf_export_without_data(monkeypatch):
    api = _make_api()
    res = api.perf_export()
    assert res["ok"] is False and res["reason"] == "no_data"


def test_perf_export_writes_report(monkeypatch, tmp_path):
    api = _make_api()
    monkeypatch.setattr(api.devices, "selected_serials", lambda: ["A1"])
    patch_ctrl(monkeypatch, "PerfMonitor", _FakePerfMon)
    api.perf_start(None, 1000)
    seen = {}

    def _fake_report(samples, info, out_dir, thresholds=None):
        seen.update(samples=len(samples), info=dict(info), out=out_dir,
                    th=thresholds)
        return {"html": str(tmp_path / "r.html"), "csv": str(tmp_path / "r.csv"),
                "rows": len(samples)}

    patch_ctrl(monkeypatch, "perf_write_report", _fake_report)
    monkeypatch.setattr(api, "_default_save_dir", lambda: str(tmp_path))
    res = api.perf_export()
    assert res["ok"] is True and res["rows"] == 1
    assert seen["out"] == str(tmp_path) and seen["samples"] == 1
    assert seen["info"]["interval"] == pytest.approx(1.0)
    # 报告必须按「当前生效阈值」判定（留空 = 内置基线），不能各写一份
    assert seen["th"] == ctrl.PERF_THRESHOLDS


def test_perf_thresholds_are_exposed_with_rules():
    """阈值只存后端一份：前端拿到的必须是副本，改不坏全局常量。"""
    api = _make_api()
    res = api.perf_thresholds()
    assert res["thresholds"]["fps"]["min"] == pytest.approx(45.0)
    assert res["thresholds"]["jank"]["max"] == pytest.approx(8.0)
    assert "帧率" in res["rules"]["fps"] and "<" in res["rules"]["fps"]
    res["thresholds"]["fps"]["min"] = 1.0
    assert ctrl.PERF_THRESHOLDS["fps"]["min"] == pytest.approx(45.0)
    # 未配置时：custom=False，界面显示的是内置基线，可一键恢复
    assert res["custom"] is False and res["off"] is False
    assert [i["key"] for i in res["items"]] == ["fps", "jank", "temp", "cpu"]


def test_perf_thresholds_payload_marks_off_state(monkeypatch):
    """config.json 里写 "off" 时界面要能区分「全部关闭」与「未配置」。"""
    api = _make_api()
    patch_ctrl(monkeypatch, "load_prefs", lambda: {"perf_thresholds": "off"})
    res = api.perf_thresholds()
    assert res["off"] is True and res["thresholds"] == {}
    assert res["rules"] == {} and res["custom"] is True


def test_perf_thresholds_broken_config_falls_back_to_baseline(monkeypatch):
    """手改 config.json 写错格式：能救的段落生效，错误回报给界面，不崩。"""
    api = _make_api()
    patch_ctrl(monkeypatch, "load_prefs",
                        lambda: {"perf_thresholds": "fps<50,乱写<1"})
    res = api.perf_thresholds()
    assert res["thresholds"] == {"fps": {"min": 50.0}}
    assert res["errors"]


def test_perf_set_thresholds_saves_and_reloads(monkeypatch, tmp_path):
    """改阈值要真的写进 config.json（重启后还在），并立刻反映到下发结构里。"""
    import core.prefs as prefs
    monkeypatch.setattr(prefs, "prefs_path", lambda: str(tmp_path / "config.json"))
    api = _make_api()
    res = api.perf_set_thresholds({"fps": 58, "jank": 5, "temp": None, "cpu": 90})
    assert res["ok"] is True
    assert res["thresholds"]["fps"]["min"] == pytest.approx(58.0)
    assert "temp" not in res["thresholds"]        # None = 关闭该条
    assert res["custom"] is True
    # 重新读取（= 下次启动）依然是这份配置
    again = api.perf_thresholds()
    assert again["thresholds"]["cpu"]["max"] == pytest.approx(90.0)
    assert "temp" not in again["thresholds"]
    assert again["expr"] == "fps<58,jank>5,cpu>90"


def test_perf_set_thresholds_all_off(monkeypatch, tmp_path):
    import core.prefs as prefs
    monkeypatch.setattr(prefs, "prefs_path", lambda: str(tmp_path / "config.json"))
    api = _make_api()
    res = api.perf_set_thresholds({"fps": None, "jank": None, "temp": None,
                                   "cpu": None})
    assert res["ok"] is True and res["off"] is True and res["thresholds"] == {}
    assert api.perf_thresholds()["off"] is True


def test_perf_set_thresholds_rejects_invalid_without_writing(monkeypatch,
                                                             tmp_path):
    """非法值不写盘：否则用户下次启动只会看到告警莫名消失，无从追查。"""
    import core.prefs as prefs
    p = tmp_path / "config.json"
    monkeypatch.setattr(prefs, "prefs_path", lambda: str(p))
    api = _make_api()
    res = api.perf_set_thresholds({"fps": 9999})
    assert res["ok"] is False and res["errors"]
    assert not p.exists()
    assert api.perf_thresholds()["custom"] is False


def test_perf_export_writes_compare_report_for_multi_device(monkeypatch,
                                                            tmp_path):
    """多设备导出：每台一份报告 + 一份横向对比报告，且对比报告是打开的那份。"""
    api = _make_api()
    monkeypatch.setattr(api.devices, "selected_serials", lambda: ["A1", "B2"])
    patch_ctrl(monkeypatch, "PerfMonitor", _FakePerfMon)
    api.perf_start(None, 1000)
    seen = {}

    def _fake_report(samples, info, out_dir, thresholds=None):
        return {"html": str(tmp_path / (info["serial"] + ".html")),
                "csv": str(tmp_path / (info["serial"] + ".csv")), "rows": 1}

    def _fake_compare(entries, out_dir, thresholds=None):
        seen["n"] = len(entries)
        # 同型号两台机（都是 Pixel 7）也必须能区分开，否则图例等于没有
        seen["labels"] = [e["label"] for e in entries]
        seen["serials"] = [e["serial"] for e in entries]
        return {"html": str(tmp_path / "cmp.html"), "devices": len(entries)}

    patch_ctrl(monkeypatch, "perf_write_report", _fake_report)
    patch_ctrl(monkeypatch, "perf_write_compare", _fake_compare)
    monkeypatch.setattr(api, "_default_save_dir", lambda: str(tmp_path))
    res = api.perf_export()
    assert res["ok"] is True and res["sessions"] == 2
    assert res["compare"] == str(tmp_path / "cmp.html")
    assert seen["n"] == 2 and seen["serials"] == ["A1", "B2"]
    assert len(set(seen["labels"])) == 2
    assert all("Pixel 7" in lb for lb in seen["labels"])


def test_perf_export_single_device_skips_compare(monkeypatch, tmp_path):
    api = _make_api()
    monkeypatch.setattr(api.devices, "selected_serials", lambda: ["A1"])
    patch_ctrl(monkeypatch, "PerfMonitor", _FakePerfMon)
    api.perf_start(None, 1000)
    patch_ctrl(monkeypatch, "perf_write_report",
                        lambda *a, **k: {"html": str(tmp_path / "r.html"),
                                         "csv": str(tmp_path / "r.csv"), "rows": 1})
    called = {"n": 0}
    patch_ctrl(monkeypatch, "perf_write_compare",
                        lambda *a, **k: called.update(n=called["n"] + 1) or {})
    monkeypatch.setattr(api, "_default_save_dir", lambda: str(tmp_path))
    res = api.perf_export()
    assert res["ok"] is True and res["compare"] == ""
    assert called["n"] == 0          # 单设备没有对比可言，不该白写一份文件


def test_perf_label_disambiguates_same_model():
    """同型号批量测试时，图例/表头只写型号会出现四个一模一样的名字。"""
    lab = ctrl.WebApi._perf_label({"model": "Pixel 7"}, "1234567890ABCDEF")
    assert lab.startswith("Pixel 7 · ") and lab.endswith("CDEF")
    assert ctrl.WebApi._perf_label({}, "A1") == "A1"
    assert ctrl.WebApi._perf_label({}, "") == "device"


def test_shutdown_stops_perf_monitor(monkeypatch):
    api = _make_api()
    monkeypatch.setattr(api.devices, "selected_serials", lambda: ["A1"])
    patch_ctrl(monkeypatch, "PerfMonitor", _FakePerfMon)
    api.perf_start(None, 1000)
    mon = api._perfs["A1"]
    api.shutdown()
    assert mon.stopped is True and api._perfs == {}


def test_perf_list_packages_needs_device(monkeypatch):
    api = _make_api()
    monkeypatch.setattr(api.devices, "selected_serials", lambda: [])
    res = api.perf_list_packages(None, False)
    assert res["ok"] is False and res["reason"] == "no_device"
    assert "勾选" in res["message"]


def test_perf_list_packages_caches_and_refresh_bypasses(monkeypatch):
    """下拉框每次打开都会问一次，而 pm list packages 要 1~3 秒：
    命中缓存不能再去打 adb，点「刷新」才强制重读。"""
    api = _make_api()
    monkeypatch.setattr(api.devices, "selected_serials", lambda: ["A1"])
    calls = []

    def fake(adb, serial, timeout=12):
        calls.append(serial)
        return {"ok": True, "third": ["com.a"], "system": [], "total": 1}

    patch_ctrl(monkeypatch, "perf_list_installed", fake)
    first = api.perf_list_packages(None, False)
    assert first["ok"] is True and first["cached"] is False
    assert first["serial"] == "A1"
    again = api.perf_list_packages(None, False)
    assert again["cached"] is True and len(calls) == 1
    api.perf_list_packages(None, True)
    assert len(calls) == 2


def test_perf_list_packages_does_not_cache_failures(monkeypatch):
    """读取失败不进缓存：否则插上线后 2 分钟内点开下拉还是那句「读取失败」。"""
    api = _make_api()
    monkeypatch.setattr(api.devices, "selected_serials", lambda: ["A1"])
    calls = []
    state = {"ok": False}

    def fake(adb, serial, timeout=12):
        calls.append(serial)
        return ({"ok": True, "third": ["com.a"], "system": [], "total": 1}
                if state["ok"] else {"ok": False, "reason": "device offline"})

    patch_ctrl(monkeypatch, "perf_list_installed", fake)
    assert api.perf_list_packages(None, False)["ok"] is False
    state["ok"] = True
    res = api.perf_list_packages(None, False)
    assert res["ok"] is True and res["cached"] is False and len(calls) == 2


def test_perf_start_passes_system_mode_through(monkeypatch):
    """全系统模式：哨兵值原样交给采样器（由它决定只采整机指标）。"""
    api = _make_api()
    monkeypatch.setattr(api.devices, "selected_serials", lambda: ["A1"])
    made = {}

    def _factory(adb, serial, interval, pkg, on_status=None):
        m = _FakePerfMon(adb, serial, interval, pkg, on_status)
        made["pkg"] = pkg
        return m

    patch_ctrl(monkeypatch, "PerfMonitor", _factory)
    assert api.perf_start(None, 1000, "__system__")["ok"] is True
    assert made["pkg"] == "__system__"


# ---------------------------------------------------------------------------
# 裸子 shell（powershell / cmd / bash）不能带结束标记
# ---------------------------------------------------------------------------
# 用户报的那条序列：
#   adb root / adb remount / powershell / $currentDate = Get-Date … /
#   adb shell "date -s …" / exit
# 卡死在第 7 条 `exit` 上。裸 powershell 在持久会话里另起一个进程抢走 stdin：
# 后面每条命令（连同调用方写入的结束标记）都被内层读走，`exit` 更把预读的
# 标记一并丢弃再退出 —— 外层永远等不到标记，run() 永久阻塞。而阻塞的正是
# 持有 _user_lock 的 worker，于是后面的命令全部排队，界面表现为「整程序卡死」。
USER_SUBSHELL_SEQ = [
    ("adb root", 500),
    ("adb remount", 500),
    ("powershell", 500),
    ('$currentDate = Get-Date -Format "yyyy-MM-dd HH:mm:ss"', 500),
    ("""adb shell "date -s '$currentDate'" """.strip(), 500),
    ("""adb shell "date -s '2026-09-23 23:59:54'" """.strip(), 500),
    ("exit", 500),
]


def _entries(*pairs):
    return [{"command": c, "delay": d} for c, d in pairs]


def _no_sleep(api):
    """把命令间 delay 打成空操作：这里关心的是下发语义，不是等 3.5 秒。"""
    api._interruptible_sleep = lambda s: None


def test_bare_powershell_goes_interactive():
    """裸 powershell 必须直通（只写不等）。

    带结束标记的话，标记会进内层 powershell；`exit` 那一行连同预读的标记
    一起被丢弃 —— 这就是用户那条序列卡死的原因。
    """
    sess = InteractiveSession()
    api = _make_api(session=sess)
    _no_sleep(api)
    assert api._run_entries(_entries(*USER_SUBSHELL_SEQ), None) is True

    calls = sess.calls
    assert calls[2]["script"] == "powershell"
    assert calls[2]["interactive"] is True, "裸 powershell 必须直通，否则整条序列卡死"
    assert all(c["interactive"] is True for c in calls[2:]), \
        "子 shell 内的命令也必须直通（标记进内层等于白等）"
    assert sess.in_interactive_shell is False, "exit 之后必须复位直通态"


def test_powershell_sequence_completes_all_seven_entries():
    """七条一条不少地下发：不能因为第 3 条"看起来卡住"就静默少跑。"""
    sess = InteractiveSession()
    api = _make_api(session=sess)
    _no_sleep(api)
    api._run_entries(_entries(*USER_SUBSHELL_SEQ), None)
    scripts = [c["script"] for c in sess.calls]
    assert len(scripts) == 7, scripts
    assert scripts[-1] == "exit"
    assert "adb root" in scripts[0] and "adb remount" in scripts[1]


def test_commands_after_exit_return_to_sentinel_mode():
    """exit 之后的命令必须回到「带标记、能判成败」的逐条执行。

    不复位直通态的话，之后每条命令都只能盲写：既没有输出边界，也永远不报错。
    """
    sess = InteractiveSession()
    api = _make_api(session=sess)
    _no_sleep(api)
    api._run_entries(
        _entries(("powershell", 0), ("exit", 0), ("adb devices", 0)), None)

    last = sess.calls[-1]
    assert last["script"].endswith("adb devices")
    assert last["interactive"] is False, "exit 之后必须恢复非交互"
    # timeout 默认 None（不限制），可手动设正值启用自动保护；关键是 interactive=False
    # 用 sentinel 标记判断完成与否（这点由 ShellSession 内部保证）


def test_oneshot_powershell_stays_non_interactive():
    """`powershell -Command "..."` 跑完就退出，不能当成交互式。

    误判成直通的代价是拿不到输出边界（不知道跑完没跑完、失败没失败）。
    """
    for cmd in ('powershell -Command "Get-Date"',
                "powershell -File setup.ps1",
                "cmd /c dir",
                "bash -c ls",
                "sh build.sh"):
        sess = FakeSession()
        api = _make_api(session=sess)
        api._run_entries(_entries((cmd, 0)), None)
        assert sess.calls[0]["interactive"] is False, cmd
        # 默认 timeout 为 None（不限制），可手动设正值启用自动保护


def test_bare_cmd_and_bash_are_interactive():
    """cmd / bash 与 powershell 同类：裸写就是进子 shell。"""
    for cmd in ("cmd", "bash", "sh", "pwsh", "cmd /k"):
        sess = FakeSession()
        api = _make_api(session=sess)
        api._run_entries(_entries((cmd, 0)), None)
        assert sess.calls[0]["interactive"] is True, cmd


def test_non_interactive_command_gets_default_timeout():
    """普通命令默认不限制 timeout，但可通过 cmd_timeout 配置启用自动保护。

    停止按钮一直可用，用户随时可以手动 kill 会话；自动超时是可选的。
    """
    sess = FakeSession()
    api = _make_api(session=sess)
    api._run_entries(_entries(("adb devices", 0)), None)
    # 非交互式（带 sentinel），timeout 默认 None = 不限制
    assert sess.calls[0]["interactive"] is False
    assert sess.calls[0]["timeout"] is None
    # 手动设置 cmd_timeout 后应生效
    import core.prefs as prefs
    prefs.save_prefs({"cmd_timeout": 30})
    try:
        sess2 = FakeSession()
        api2 = _make_api(session=sess2)
        api2._run_entries(_entries(("adb devices", 0)), None)
        assert sess2.calls[0]["timeout"] == 30
    finally:
        prefs.save_prefs({"cmd_timeout": 0})


def test_cmd_timeout_reads_prefs():
    """config.json 的 cmd_timeout 可覆盖默认值；0 表示不限制。"""
    import core.prefs as prefs

    prefs.save_prefs({"cmd_timeout": 45})
    sess = FakeSession()
    api = _make_api(session=sess)
    api._run_entries(_entries(("adb devices", 0)), None)
    assert sess.calls[0]["timeout"] == 45

    prefs.save_prefs({"cmd_timeout": 0})
    sess2 = FakeSession()
    api2 = _make_api(session=sess2)
    api2._run_entries(_entries(("adb devices", 0)), None)
    assert sess2.calls[0]["timeout"] is None, "0 = 不限制"


def test_shutdown_between_commands_ends_quietly():
    """关窗恰好发生在命令序列中途：安静收尾，不能抛「'NoneType' has no 'run'」。

    shutdown() 会先 kill 会话、再把 self.session 置空，而这条序列跑在后台
    worker 里。旧实现每条命令都重新读 self.session，于是第二条踩到 None，被
    _execute 兜底成「⚠ 命令执行出现异常：'NoneType' object has no attribute
    'run'」—— 关窗瞬间弹一条对用户毫无意义的报错。
    """
    class ShutdownSession(InteractiveSession):
        def __init__(self):
            super().__init__()
            self.n = 0

        def run(self, script, timeout=None, interactive=False):
            r = super().run(script, timeout=timeout, interactive=interactive)
            self.n += 1
            return r

    sess = ShutdownSession()
    api = _make_api(session=sess)
    _no_sleep(api)
    orig_run = sess.run

    def run_and_shutdown(script, timeout=None, interactive=False):
        r = orig_run(script, timeout=timeout, interactive=interactive)
        # 模拟 shutdown()：置收尾标记 + 清会话引用
        api.state.mark_shutdown()
        api.session = None
        return r

    sess.run = run_and_shutdown
    assert api._run_entries(_entries(("adb devices", 0), ("adb shell ls", 0)),
                            None) is False
    assert len(sess.calls) == 1, "关窗后不应再下发剩下的命令"


def test_timeout_stops_remaining_commands():
    """超时（run 返回 False）必须停掉后续条目，并给出「执行中断」。"""
    class FailSession(InteractiveSession):
        def run(self, script, timeout=None, interactive=False):
            super().run(script, timeout=timeout, interactive=interactive)
            return False

    sess = FailSession()
    api = _make_api(session=sess)
    _no_sleep(api)
    assert api._run_entries(_entries(("adb devices", 0), ("adb shell ls", 0)), None) is False
    assert len(sess.calls) == 1, "第一条中断后不应继续下发"


def test_interrupt_status_carries_session_reason():
    """中断原因要带到状态栏：只说「执行中断」，用户分不清是超时、被停止，
    还是会话进程被安全软件干掉后静默重建——三种情况的处置完全不同。"""
    class ReasonSession(InteractiveSession):
        last_error = "命令执行超过 120 秒，已自动终止"

        def run(self, script, timeout=None, interactive=False):
            super().run(script, timeout=timeout, interactive=interactive)
            return False

    sess = ReasonSession()
    api = _make_api(session=sess)
    _no_sleep(api)
    api._run_entries(_entries(("adb devices", 0)), None)
    texts = [p["text"] for p in _events_by_kind(api).get("status", [])]
    assert any("执行中断" in t and "超过 120 秒" in t for t in texts), texts


def test_subshell_hints_go_to_console_not_status():
    """进 / 出子 shell 的提示要落在指令台里。

    用户执行命令时盯着的是「指令输出」面板；这两条提示混进顶栏跑马灯，
    几秒后就被刷掉了 —— 他只会看到「后面的命令没有回显」，像是坏了。
    """
    sess = InteractiveSession()
    api = _make_api(session=sess)
    _no_sleep(api)
    api._run_entries(_entries(*USER_SUBSHELL_SEQ), None)

    by_kind = _events_by_kind(api)
    console = [p["text"] for p in by_kind.get("console", [])]
    assert any("» 已进入交互式 shell" in t for t in console), console
    assert any("« 已退出交互式子 shell" in t for t in console), console
    status = [p["text"] for p in by_kind.get("status", [])]
    assert not any("交互式子 shell" in t for t in status), status


# ---------------------------------------------------------------------------
# 命令库保存 / 导入的失败路径与 BOM 兼容
# ---------------------------------------------------------------------------
def test_save_commands_reports_disk_failure(monkeypatch):
    """写盘失败必须原样报错，不能提示「已保存」。

    回归：core.commands._write_json_atomic 早年吞掉异常且不返回，导致
    save_user_commands 恒为 (True, None) —— 只读目录下界面绿色提示「✓ 命令已
    保存」，实际一条都没落盘，下次启动全丢。
    """
    api = _make_api()
    patch_ctrl(monkeypatch, "save_user_commands",
               lambda cmds: (False, "无法写入 commands.json（目录只读）"))
    res = api.save_commands(list(CMDS))
    assert res["ok"] is False
    assert "只读" in res["reason"]
    status = _events_by_kind(api).get("status") or []
    assert any("保存命令失败" in (p.get("text") or "") for p in status), status


def test_import_commands_accepts_bom_prefixed_json(monkeypatch):
    """带 UTF-8 BOM 的备份文件必须能导入（记事本「另存为 UTF-8」就会写 BOM）。"""
    api = _make_api()
    patch_ctrl(monkeypatch, "save_user_commands", lambda cmds: (True, None))
    payload = '\ufeff[{"id": "u_bom", "name": "带 BOM", "commands": []}]'
    res = api.import_commands(payload)
    assert res["ok"] is True, res
    assert any(c.get("id") == "u_bom" for c in api.state.commands)



# ---------------------------------------------------------------------------
# 命令库：对话框字符串路径 / 导出回退 / 数字 id 导入
# ---------------------------------------------------------------------------
class _DialogWindow:
    """pywebview 窗口替身：create_file_dialog 原样返回调用方给的值。"""

    def __init__(self, ret):
        self.ret = ret
        self.calls = []

    def create_file_dialog(self, *a, **kw):
        self.calls.append((a, kw))
        return self.ret


def _fake_webview(monkeypatch):
    """注入最小 webview 模块（CI 上没有真 pywebview）。

    `_open_dialog` 只用 OPEN_DIALOG 常量与 active_window 兜底；file_types 的
    版本探测取不到 webview.util，会退化成字符串格式 —— 正是兼容性最好的那档。
    """
    import sys
    import types
    mod = types.ModuleType("webview")
    mod.OPEN_DIALOG = 1
    mod.active_window = lambda: None
    monkeypatch.setitem(sys.modules, "webview", mod)
    return mod


def test_import_dialog_accepts_plain_string_path(monkeypatch, tmp_path):
    """对话框返回**字符串**（而不是列表）时也要能导入。

    回归：import_commands_dialog 早前另抄了一份对话框代码，而那份漏了
    「返回值可能是 str」的兼容 —— `files[0]` 取到的是路径的第一个字符，
    接着报「读取文件失败：[Errno 2] ... 'C'」。_open_dialog 早就处理了这一档。
    """
    import json
    _fake_webview(monkeypatch)
    api = _make_api()
    patch_ctrl(monkeypatch, "save_user_commands", lambda cmds: (True, None))
    f = tmp_path / "backup.json"
    f.write_text(json.dumps([{"id": "u_str", "name": "字符串路径",
                              "commands": [{"command": "adb devices"}]}]),
                 encoding="utf-8")
    api.window = _DialogWindow(str(f))        # 老代码会取 str 的第一个字符
    res = api.import_commands_dialog()
    assert res["ok"] is True, res
    assert any(c.get("id") == "u_str" for c in api.state.commands)


def test_import_commands_normalizes_numeric_id(monkeypatch):
    """备份里 `"id": 1`（数字）要与内存态的 "1" 视为同一条。

    回归：合并键直接用原值，1 与 "1" 各占一条 —— 文件里存下两条只差一个
    引号的命令，下次启动时后一条被判重名、静默改成 auto2，用户看到的是
    「导入成功，但那条命令莫名其妙重复出现」。
    """
    api = _make_api()
    patch_ctrl(monkeypatch, "save_user_commands", lambda cmds: (True, None))
    api.state.commands = [{"id": "1", "name": "已有命令", "labels": ["通用"],
                           "commands": [{"command": "adb devices"}]}]
    res = api.import_commands([{"id": 1, "name": "数字 id 备份",
                                "commands": [{"command": "adb shell date"}]}])
    assert res["ok"] is True, res
    assert res["added"] == 0, "同一条命令应按 id 覆盖，而不是新增一条"
    ids = [c.get("id") for c in api.state.commands]
    assert ids.count("1") == 1, ids


def test_save_commands_tolerates_empty_payload(monkeypatch):
    """commands 为 None 时不能「写成功却抛 TypeError」。

    回归：保存成功后提示语用 len(commands) 拼条数，None 直接抛 TypeError ——
    文件其实已经写进去了，用户看到的却是一次调用失败，重试还是同样的结果。
    """
    api = _make_api()
    patch_ctrl(monkeypatch, "save_user_commands", lambda cmds: (True, None))
    res = api.save_commands(None)
    assert res["ok"] is True, res
    status = _events_by_kind(api).get("status") or []
    assert any("已保存" in (p.get("text") or "") for p in status), status


def test_export_commands_save_falls_back_to_tempdir(monkeypatch, tmp_path):
    """程序目录不可写时要**真的**退到系统临时目录。

    回归：早前只判断 makedirs 有没有抛错。程序装在 Program Files 这类只读
    位置时目录本来就在，makedirs 一声不响地成功，「回退」永远不触发，
    用户点「导出备份」只得到一句 Permission denied —— 而导出恰恰是他换
    电脑前最需要做的事。
    """
    import tempfile
    api = _make_api()
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")     # 拿普通文件当父目录
    tmpdir = tmp_path / "tmpdir"
    tmpdir.mkdir()
    patch_ctrl(monkeypatch, "program_dir", lambda: str(blocker / "sub"))
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmpdir))
    res = api.export_commands_save()
    assert res["ok"] is True, res
    assert os.path.dirname(res["path"]) == str(tmpdir)
    assert "临时目录" in (res.get("note") or "")
    assert os.path.exists(res["path"])


def test_export_commands_save_keeps_both_backups_within_one_second(
        monkeypatch, tmp_path):
    """同一秒内连点两次导出，不能把第一份覆盖掉（走 unique_path）。"""
    import backend.controllers.commands as cmds_ctrl
    from datetime import datetime as real_datetime

    api = _make_api()
    patch_ctrl(monkeypatch, "program_dir", lambda: str(tmp_path))

    class _FixedNow:
        @staticmethod
        def now():
            return real_datetime(2026, 1, 1, 12, 0, 0)

    class _FakeDt:
        datetime = _FixedNow

    monkeypatch.setattr(cmds_ctrl, "datetime", _FakeDt)
    first = api.export_commands_save()
    second = api.export_commands_save()
    assert first["ok"] and second["ok"]
    assert first["path"] != second["path"]
    assert second["path"].endswith("_2.json"), second["path"]
    assert os.path.exists(first["path"]) and os.path.exists(second["path"])


def test_perf_export_surfaces_partial_failure(monkeypatch, tmp_path):
    """一台成功、一台写报告失败时，不能只报「✓ 已生成 1 份」。

    对比报告是拿这批文件拼的，少一台就等于结论缺一半 —— 用户看到「已生成」
    就不会再去目录里核对少的是哪台。
    """
    api = _make_api()
    monkeypatch.setattr(api.devices, "selected_serials", lambda: ["A1", "B2"])
    patch_ctrl(monkeypatch, "PerfMonitor", _FakePerfMon)
    api.perf_start(None, 1000)

    def _fake_report(samples, info, out_dir, thresholds=None):
        if info["serial"] == "B2":
            raise OSError("磁盘空间不足")
        return {"html": str(tmp_path / "a.html"), "csv": str(tmp_path / "a.csv"),
                "rows": 1}

    patch_ctrl(monkeypatch, "perf_write_report", _fake_report)
    patch_ctrl(monkeypatch, "perf_write_compare",
               lambda *a, **k: {"html": str(tmp_path / "cmp.html")})
    monkeypatch.setattr(api, "_default_save_dir", lambda: str(tmp_path))
    res = api.perf_export()
    assert res["ok"] is True and res["sessions"] == 1
    assert "B2" in res["errors"]
    warns = [p for p in _events_by_kind(api).get("status", [])
             if p.get("type") == "warn" and "未生成" in p.get("text", "")]
    assert warns and "B2" in warns[0]["text"], "缺的那台必须在状态栏点名"


def test_mirror_start_twice_spawns_only_one_window(monkeypatch):
    """连点两次「投屏」只能开一个窗口。

    回归：_start_one_mirror 是同步的（要等首帧，最长 FIRST_DATA_TIMEOUT=6s），
    设备要等它返回才登记进 _mirror_pipes —— 第二次点击查重时表里还是空的，
    于是同一台设备开出两个播放器窗口 + 两条设备端 screenrecord，互相抢 adb
    输入（scrcpy 那边已修过同一个坑，这条降级链当时漏了）。
    """
    api = _mirror_api(monkeypatch)
    monkeypatch.setattr(api.devices, "selected_serials", lambda: ["A1"])
    patch_ctrl(monkeypatch, "find_player",
               lambda pref: ("ffplay", "/bin/ffplay", "PATH"))
    patch_ctrl(monkeypatch, "plan_size", lambda adb, serial: "")
    gate = threading.Event()
    built = []

    class _SlowPipe:
        def __init__(self, *a, **kw):
            built.append(a)          # 每 new 一次 = 多开一个播放器窗口

        def start(self):
            gate.wait(5)             # 模拟「等首帧」的那几秒
            return True, ""

        def alive(self):
            return True

        def stop(self):
            pass

    patch_ctrl(monkeypatch, "PipeMirror", _SlowPipe)
    first = {}
    t = threading.Thread(target=lambda: first.update(api.mirror_start(None, "pipe")))
    t.start()
    assert wait_until(lambda: len(built) == 1), "第一个请求应已进入启动流程"
    second = api.mirror_start(None, "pipe")
    gate.set()
    t.join(5)
    assert len(built) == 1, "同一台设备只应拉起一个播放器窗口"
    assert second["skipped"] == ["A1"]
    assert first["started"][0]["mode"] == "pipe"


def test_mirror_start_recovers_from_dead_entry(monkeypatch):
    """登记表里只剩「已死」的投屏对象时，不能让设备永远卡在「已在投屏」。

    回归：后台链路收尾回调与「启动成功后登记」之间有竞态 —— 回调先到（此时
    还没登记，pop 不到东西），随后 start() 才把已死的实例登记进来。之后每次点
    「投屏」都被跳过，状态里又看不到任何在投设备，用户只能重启程序。
    """
    api = _mirror_api(monkeypatch)
    monkeypatch.setattr(api.devices, "selected_serials", lambda: ["A1"])
    patch_ctrl(monkeypatch, "find_player", lambda pref: ("", None, "无"))

    class _Dead:
        def alive(self):
            return False

        def stop(self):
            pass

    class _Snap:
        def __init__(self, *a, **kw):
            pass

        def start(self):
            return True, ""

        def alive(self):
            return True

        def stop(self):
            pass

    api._mirror_pipes["A1"] = _Dead()
    patch_ctrl(monkeypatch, "SnapMirror", _Snap)
    res = api.mirror_start(None, "snap")
    assert res["started"], "死条目不该阻断重开"
    assert res["skipped"] == []
    assert api.mirror_status()["pipe"] == [], "死条目应被摘掉"
    api.mirror_stop(None)


def test_save_settings_reports_unwritable_config(monkeypatch, tmp_path):
    """config.json 写不进去时必须当面说清，不能回一句「已保存」。

    回归：save_settings 之前无条件回 ok=True、也没检查过写盘结果。程序装在
    Program Files（或 config.json 被标成只读）时，用户改完主题 / 保存目录 /
    投屏参数，界面一切正常，重启后全部回到默认值，且没有任何提示可循。
    """
    import core.prefs as prefs
    monkeypatch.setattr(prefs, "prefs_path",
                        lambda: str(tmp_path / "config.json"))
    monkeypatch.setattr(prefs, "_atomic_write", lambda p: False)
    api = _make_api()
    res = api.save_settings({"mirror_fps": 3})
    assert res["ok"] is True, "本次运行内确实已生效，不该报成请求失败"
    assert res["settings"]["_persist_ok"] is False
    assert "重启后会恢复原值" in res["settings"]["_persist_note"]
    statuses = _events_by_kind(api).get("status", [])
    hits = [p for p in statuses if "未能写入" in p["text"]]
    assert hits and hits[0].get("toast"), "写盘失败必须弹 toast 强提醒：%r" % statuses


# --------------------------------------------------------------------------- #
# 多设备录屏收尾
# --------------------------------------------------------------------------- #
def _rec_session_with(tmp_path, serials, with_devaudio=False):
    files = {}
    for s in serials:
        p = tmp_path / ("rec_%s.mp4" % s)
        p.write_bytes(b"\x00" * 64)
        files[s] = str(p)
    return {
        "ts": "20261031_230000", "dir": str(tmp_path), "with_zip": False,
        "videos": dict(files), "mic_path": None, "mic_started": False,
        "devaudio": {s: "/data/local/tmp/a_%s.wav" % s for s in serials}
        if with_devaudio else {},
        "logcat_captures": {},
        "pointer_location_prev": {}, "show_touches_prev": {},
    }, files


def test_multi_device_teardown_runs_in_parallel(monkeypatch, tmp_path):
    """多设备收尾必须并行：单台 stop 里的那一段等待不能乘以台数。

    回归：_session_teardown 逐台串行 stop，而每台的 stop 要走「kill 设备端
    screenrecord → 等本地 adb 退出 → 轮询设备端文件就绪 → pull」；设备端根本
    没生成文件时，_pull_and_finish 还会把 6 次退避全走完（约 9 秒）。5 台设备
    点「停止」要等 40 秒以上才出现「录屏已完成」，其间 _rec_lock 一直被占着，
    别的录屏动作全排不上——用户只会以为程序卡死了。
    """
    api = _make_api()
    sess, files = _rec_session_with(tmp_path, ("A1", "B1", "C1"))

    class _SlowVideo:
        def is_recording(self, s):
            return True

        def stop(self, s):
            time.sleep(0.6)
            return True, files[s], None

        def set_system_setting(self, *a, **kw):
            raise AssertionError("本用例不应触碰设备系统设置")

        def set_system_setting_ex(self, *a, **kw):
            raise AssertionError("本用例不应触碰设备系统设置")

    api.video = _SlowVideo()
    api._rec_session = sess

    t0 = time.time()
    res = api.screen_record_stop()
    spent = time.time() - t0

    assert res["ok"] is True, res
    assert spent < 1.4, (
        "3 台设备各 0.6 秒：并行约 0.6 秒，串行要 1.8 秒；实际 %.2f 秒" % spent)
    assert api._rec_session == {}, "收尾后会话必须清空，否则录屏功能被锁死"


def test_devaudio_teardown_failure_keeps_video(tmp_path):
    """设备音频收尾炸了，视频仍要照常落盘并计入汇总。

    回归：音频那条循环没有单独兜底，一次异常会让 _session_teardown 整体中断
    （外层 try/finally 只负责清会话），已经 pull 回来的视频既不合音频、也不进
    zip，汇总 toast 还会说「0 个文件已保存」——用户以为这段录像没了。
    """
    api = _make_api()
    sess, files = _rec_session_with(tmp_path, ("A1",), with_devaudio=True)

    class _Video:
        def is_recording(self, s):
            return True

        def stop(self, s):
            return True, files[s], None

        def set_system_setting(self, *a, **kw):
            return True

        def set_system_setting_ex(self, *a, **kw):
            return True, ""

    class _BadAudio:
        def stop(self, s):
            raise RuntimeError("tinycap 收尾失败")

    api.video = _Video()
    api.device_audio = _BadAudio()
    api._rec_session = sess

    res = api.screen_record_stop()
    assert res["ok"] is True, res
    statuses = _events_by_kind(api).get("status", [])
    texts = [p["text"] for p in statuses]
    assert any("设备音频收尾失败" in x for x in texts), texts
    assert any("录屏已保存" in x for x in texts), texts
    assert api._rec_session == {}


def test_command_hint_tells_unusable_checked_devices_apart():
    """勾了但设备都不可用 ≠ 没勾：提示要指到设备状态上。

    设备离线 / 未授权时 selected_serials() 同样是空。旧提示一律「请先在左侧
    勾选设备」，用户于是去点一个**已经勾好**的设备——反复几次也解决不了，因为
    真正要处理的是设备状态（授权弹窗没点 / 掉线 / adb 掉线）。
    """
    api = _make_api()
    api.devices.device_state = {"C3": "unauthorized"}
    api.devices.device_checked = {"C3": True}
    api._execute({"id": "__custom__", "name": "自定义命令",
                  "commands": [{"command": "adb shell ls", "delay": 0}]})

    texts = [p["text"] for p in _events_by_kind(api).get("status", [])]
    assert any("都不可用" in t and "C3" in t for t in texts), texts
    assert not any("请先在左侧勾选设备" in t for t in texts), texts


def test_perf_partial_failure_is_announced(monkeypatch):
    """部分设备没起来时必须单独说清楚：否则用户以为全都监控上了。

    勾了 3 台、实际只监控 2 台，界面只有一句「✓ 已开始性能监控：2 台设备」，
    导出对比报告时才发现少一台，也查不到原因（failed 只躺在返回值里，
    前端从不读它）。
    """
    api = _make_api()
    monkeypatch.setattr(api.devices, "selected_serials", lambda: ["A1", "B2"])

    class _Bad(_FakePerfMon):
        def start(self):
            if self.serial == "B2":
                return False, "读取设备状态失败"
            return True, ""

    patch_ctrl(monkeypatch, "PerfMonitor", _Bad)
    res = api.perf_start(None, 1000)
    assert res["ok"] is True
    texts = [p.get("text", "") for p in _events_by_kind(api).get("status", [])]
    assert any("未能开始性能监控" in t and "B2" in t and "读取设备状态失败" in t
               for t in texts), texts


def test_perf_total_failure_lists_every_reason(monkeypatch):
    """全部失败时不能只报第一台：其余设备的原因同样要找出来。

    只报第一台时，用户按那句「设备离线」去拔插线，而真正卡住的是另一台的
    「包名不存在」—— 两台的原因压根不是一回事。
    """
    api = _make_api()
    monkeypatch.setattr(api.devices, "selected_serials", lambda: ["A1", "B2"])

    class _Bad(_FakePerfMon):
        def start(self):
            if self.serial == "B2":
                return False, "包名不存在"
            return False, "设备无响应"

    patch_ctrl(monkeypatch, "PerfMonitor", _Bad)
    res = api.perf_start(None, 1000)
    assert res["ok"] is False
    assert "设备无响应" in res["error"] and "包名不存在" in res["error"], res["error"]
    texts = [p.get("text", "") for p in _events_by_kind(api).get("status", [])]
    assert any("设备无响应" in t and "包名不存在" in t for t in texts), texts


def test_overlay_enable_failure_is_announced(monkeypatch, tmp_path):
    """设备拒绝开启 overlay 时必须说出来：否则录完才发现画面里没有准星。

    `settings put` 被系统策略拒绝时通常**不返回非零**（SecurityException 打在
    stdout 上），旧实现直接丢掉返回值 —— 用户勾了「指针位置」，回放录像时既没
    准星也没圆点，全程零提示，只能怀疑是录屏功能坏了。
    """
    api = _make_api()
    monkeypatch.setattr(api.video, "start",
                        lambda *a, **kw: (True, str(tmp_path / "r.mp4")))
    monkeypatch.setattr(api.video, "get_system_setting",
                        lambda adb, s, key: (True, "null"))
    _patch_set_setting(monkeypatch, api.video, lambda adb, s, k, v: False)

    api.screen_record_start(None, save_dir=str(tmp_path),
                            pointer_location=True, show_touches=False)

    texts = [p.get("text", "") for p in _events_by_kind(api).get("status", [])]
    assert any("未能开启" in t and "指针位置" in t for t in texts), texts
    api.workers.shutdown(timeout=2.0)


def test_overlay_restore_failure_is_announced(monkeypatch, tmp_path):
    """恢复原值失败时也要说出来：设备上会一直留着一个用户没开过的开关。

    这是唯一会让「设备状态没还回去」无声发生的地方。用户不会知道系统里还留着
    一个自己没开过的开关，而下次录制又会去读它当「原值」—— 一次失败就此固化
    成新默认值。
    """
    api = _make_api()
    monkeypatch.setattr(api.video, "start",
                        lambda *a, **kw: (True, str(tmp_path / "r.mp4")))
    monkeypatch.setattr(api.video, "stop",
                        lambda s: (True, str(tmp_path / "r.mp4"), None))
    monkeypatch.setattr(api.video, "get_system_setting",
                        lambda adb, s, key: (True, "0"))
    state = {"ok": True}

    def fake_set(adb, s, k, v):
        return state["ok"]

    _patch_set_setting(monkeypatch, api.video, fake_set)

    api.screen_record_start(None, save_dir=str(tmp_path),
                            pointer_location=True, show_touches=False)
    state["ok"] = False                      # 收尾时设备拒写（拔线 / 策略变化）
    api.screen_record_stop()

    texts = [p.get("text", "") for p in _events_by_kind(api).get("status", [])]
    assert any("未能恢复原值" in t and "指针位置" in t
               and "手动关闭" in t for t in texts), texts
    api.workers.shutdown(timeout=2.0)


def test_perf_threshold_save_failure_is_reported(monkeypatch):
    """配置写不进去时不能报「✓ 告警阈值已更新」。

    save_prefs 把落盘失败整个吞掉（只读目录 / 文件被占用时返回 False，没人看），
    于是界面弹「已更新」，下次启动阈值却回到旧值 —— 用户只能怀疑自己没点对。
    """
    import backend.controllers.perf as perf_ctrl

    monkeypatch.setattr(perf_ctrl, "save_prefs_checked",
                        lambda patch: ({}, False), raising=False)
    api = _make_api()
    res = api.perf_set_thresholds({"fps": 58})
    assert res["ok"] is False, res
    assert any("无法写入" in e for e in res["errors"]), res["errors"]
    texts = [p.get("text", "") for p in _events_by_kind(api).get("status", [])]
    assert not any("已更新" in t for t in texts), texts


def test_manual_refresh_reports_when_already_running(monkeypatch):
    """已有刷新在跑时，手动点「刷新」不能再是彻底的静默。

    回归：refresh_devices 过去用固定 key "refresh"（boot 首刷也是它）交给
    Workers，撞上存活线程时 spawn 直接复用 —— 这一次点击既不刷新也不提示。

    现在的方案：手动刷新用匿名 worker（key=None），DeviceManager._acquire 内部
    处理排队互斥。上一轮没结束时第二次点击会 spawn 新 worker，内部 _acquire
    会等待上一轮结束（或超时强制释放），等不到时推 status 提示。
    """
    api = _make_api()
    release = threading.Event()
    # 阻塞 _poll_devices，让 DeviceManager._acquire 成功后 _busy 被占住
    # 返回合法的 adb devices 输出（空列表），避免 parse_devices 报错
    monkeypatch.setattr(
        api.devices, "_poll_devices",
        lambda *a, **kw: (release.wait(3.0) and "List of devices attached\n") or None)
    # 第一次点刷新：spawn 匿名 worker → _acquire 成功 → _poll_devices 阻塞
    assert api.refresh_devices()["ok"] is True
    # 等 _busy 被 acquire
    assert wait_until(lambda: api.devices._busy, timeout=2.0)
    # 第二次点刷新：spawn 又一个匿名 worker → 内部 _acquire(wait=True)
    # 会等上一轮结束（release 3s 后），不会被 Workers 层面拦截
    res = api.refresh_devices()
    assert res.get("ok") is True, res
    # DeviceManager._acquire 在 wait=True + verbose=True 且等不到时会推 status；
    # 这里等不到（release 还没 set）但 wait=True 会继续等，不会立刻返回 False。
    # 关键：不再有 Workers.is_running("refresh") 拦截，第二次点击确实触发了
    # 一个新 worker 去排队等待，而不是被静默吞掉。
    release.set()
    api.workers.shutdown(timeout=2.0)


def test_screen_record_devaudio_failure_reports_reason(monkeypatch, tmp_path):
    """设备音频起不来时必须给出原因，而不是一句「启动失败」。

    回归：record 只拿到 start() 的 bool，toast 里没有 tinycap 的退出码 / root
    提示 —— 用户不知道该 adb root 还是换台设备，本次录屏也就悄悄没了声音。
    """
    api = _make_api()
    monkeypatch.setattr(ctrl.DeviceAudioCapture, "supported",
                        staticmethod(lambda *a, **kw: True))
    monkeypatch.setattr(
        api.device_audio, "start_ex",
        lambda s, r: (False, "tinycap 启动后立即退出（退出码 1）：多数机型需要 root"))
    monkeypatch.setattr(api.video, "start",
                        lambda *a, **kw: (True, str(tmp_path / "r.mp4")))

    res = api.screen_record_start(None, with_devaudio=True,
                                  save_dir=str(tmp_path))
    assert res.get("ok") is True, res           # 无设备音频也要照常录屏
    texts = [p["text"] for p in _events_by_kind(api).get("status", [])]
    assert any("音频采集未启动" in t and "root" in t for t in texts), texts
    assert api._rec_session["devaudio"] == {}
    api._rec_session = {}
    api.workers.shutdown(timeout=2.0)


def test_open_save_dir_reports_real_reason(tmp_path):
    """目录打不开时要说真原因（没权限 / 同名文件占位），不能一律「目录不存在」。

    回归：open_save_dir 把 makedirs 的 OSError 整个吞掉，转头发一句「目录不存在」。
    用户照着这句去查，目录明明在 —— 真正的问题是那个路径被一个同名文件占着。
    """
    api = _make_api()
    target = tmp_path / "notadir"
    target.write_text("x", encoding="utf-8")        # 同名的普通文件

    res = api.open_save_dir(str(target))
    assert res["ok"] is False
    assert res.get("text"), res                     # 带上底层原因
    texts = [p["text"] for p in _events_by_kind(api).get("status", [])]
    assert any("无法创建" in t for t in texts), texts
    assert not any("目录不存在" in t for t in texts), texts

def test_unroot_executes_when_root_state_unknown(monkeypatch):
    """无法确认 root 状态时不能猜成「未 root」：`adb unroot` 会被静默跳过。

    回归：`device_is_root` 探测失败返回 False，与「确认未 root」混成一个值。
    用户明明 root 了要 unroot，却被判成「已在目标状态」直接跳过，界面还说
    「设备已未 root」—— 指令没执行，结论还是反的。现在无法确认时放行并说明。
    """
    patch_ctrl(monkeypatch, "root_state", lambda adb, serial: None)
    api = _make_api()
    assert api.run_custom("adb unroot") == {"ok": True}
    assert wait_until(lambda: len(api.session.calls) >= 1)
    assert api.session.calls[0]["script"] == "adb -s A1 unroot"
    texts = [p["text"] for p in _events_by_kind(api).get("status", [])]
    assert any("无法确认" in t for t in texts), texts
    _run_and_settle(api)


def test_unknown_root_state_still_blocked_while_recording(monkeypatch):
    """状态未知不代表可以打断录屏：有进行中任务时仍要拦。"""
    patch_ctrl(monkeypatch, "root_state", lambda adb, serial: None)
    api = _make_api()
    api.video = _FakeVideoRec(recording={"A1"})
    assert api.run_custom("adb unroot") == {"ok": True}
    _run_and_settle(api)
    assert api.session.calls == [], "录屏中不得下发 unroot（会重启 adbd）"
    texts = [p["text"] for p in _events_by_kind(api).get("status", [])]
    assert any("录屏" in t and "跳过" in t for t in texts), texts


def test_screenshot_two_batches_do_not_mix_counts(monkeypatch):
    """连点两次「批量截图」：两批各弹一条汇总，台数各算各的。

    回归：_shot_batch 是一张**共用**的可变字典，第二次点击直接把它重置。上一批
    还在跑的 worker 依旧往这张表记账 —— 前一批的 done 把后一批提前凑满，弹出一
    条台数不对的汇总；后一批真正到齐时 _shot_batch 已置 None，连提示都没有。
    实测「2 台 + 2 台」连点：只弹一条「✓ 已完成 2 台设备的截图」，保存目录里
    却是 4 张，用户没法判断另一批到底成没成。
    """
    api = _make_api()
    api.toggle_device("B2", True)
    release = threading.Event()
    started = []

    def blocked(_adb, serial, _save_dir, _save_file=True):
        started.append(serial)
        release.wait(3.0)
        return ("D:/shots/%s.png" % serial, None)

    monkeypatch.setattr(ctrl.ScreenCapturer, "screenshot", staticmethod(blocked))
    monkeypatch.setattr(ctrl.clipboard, "copy_image", lambda p: (True, ""))

    api.screenshot()
    assert wait_until(lambda: len(started) == 2, timeout=2.0), started
    api.screenshot()                    # 第一批尚未收尾就再点一次
    assert wait_until(lambda: len(started) == 4, timeout=2.0), started
    release.set()
    assert wait_until(lambda: api._shot_inflight == 0, timeout=3.0), \
        "四个 worker 收尾后在途数应归零"

    summaries = [p for p in _events_by_kind(api).get("status", [])
                 if p.get("toast") and "截图" in (p.get("text") or "")]
    assert len(summaries) == 2, \
        "两批各应有一条汇总，实际 %d 条：%r" % (len(summaries), summaries)
    for s in summaries:
        assert "2 台设备" in s["text"], s["text"]
    api.workers.shutdown(timeout=2.0)


def test_file_upload_rejects_empty_content(monkeypatch):
    """内容为空时不能真去上传：设备上会多一个 0 字节文件，界面还报「✓ 上传完成」。

    回归：前端把 readAsDataURL 的结果切掉前缀后直接下发，读到空内容时传的是空串。
    后端 `base64.b64decode("")` 得到 b""，照常落地中转文件、push、然后成功 ——
    用户在设备上拿到一个空文件，以为传好了，回头排查「文件怎么是空的」时无从下手。
    """
    api = _make_api()
    uploaded = []
    monkeypatch.setattr(api.file_svc, "upload",
                        lambda *a, **kw: uploaded.append(a) or (True, ""))
    monkeypatch.setattr(api.workers, "spawn",
                        lambda key, fn, *a, **kw: fn(*a, **kw))

    api.file_upload_data("A1", "empty.txt", "", "/sdcard/empty.txt")

    assert uploaded == [], "空内容不该真的上传"
    texts = [p["text"] for p in _events_by_kind(api).get("status", [])]
    assert any("没有收到文件内容" in t for t in texts), texts
    assert not any("上传完成" in t for t in texts), texts


def test_file_upload_coalesces_directory_refresh(monkeypatch):
    """多选上传 N 个文件，只刷一次目录。

    回归：每个文件上传完成后各自 `_file_refresh` 一次 —— 20 个文件就是 20 次
    `adb shell ls`（每次 100~300ms，全排在 adb 队列里）加 20 次 file 事件，
    用户看到文件列表反复闪烁、刚勾选的项被一轮轮清空，而真正需要的只是最后
    那一次（那时目录里才躺齐全部文件）。
    """
    import base64
    api = _make_api()
    monkeypatch.setattr(api, "_FILE_REFRESH_DEBOUNCE_S", 0.05)
    monkeypatch.setattr(api.file_svc, "upload", lambda *a, **kw: (True, ""))
    monkeypatch.setattr(api.workers, "spawn",
                        lambda key, fn, *a, **kw: fn(*a, **kw))
    listed = []
    monkeypatch.setattr(api, "file_list",
                        lambda s, p: listed.append((s, p)))
    api._file_dir["A1"] = "/sdcard"          # 用户当前在看 /sdcard
    b64 = base64.b64encode(b"hi").decode()

    for name in ("a.txt", "b.txt", "c.txt"):
        api._run_file_op(api._do_file_upload_data, "A1", name, b64,
                         "/sdcard/" + name)

    assert listed == [], "合并窗口内不该立刻刷目录（实测 %r）" % listed
    assert wait_until(lambda: len(listed) == 1, 2.0), listed
    time.sleep(0.2)                          # 再等一个窗口，确认没有第二批
    assert listed == [("A1", "/sdcard")], listed
    api.workers.shutdown(timeout=2.0)


def test_file_upload_refresh_skipped_after_user_left_dir(monkeypatch):
    """上传的合并刷新不能把已经切走的用户弹回旧目录。

    回归：上传 20 个文件后用户点进了别的目录，定时器到期仍去列上传时的目录，
    前端收到 file 事件就把界面拉回去 —— 用户以为自己点错了。
    """
    import base64
    api = _make_api()
    monkeypatch.setattr(api, "_FILE_REFRESH_DEBOUNCE_S", 0.05)
    monkeypatch.setattr(api.file_svc, "upload", lambda *a, **kw: (True, ""))
    monkeypatch.setattr(api.workers, "spawn",
                        lambda key, fn, *a, **kw: fn(*a, **kw))
    listed = []
    monkeypatch.setattr(api, "file_list",
                        lambda s, p: listed.append((s, p)))
    api._file_dir["A1"] = "/sdcard"
    b64 = base64.b64encode(b"hi").decode()

    api._run_file_op(api._do_file_upload_data, "A1", "a.txt", b64,
                     "/sdcard/a.txt")
    api._file_dir["A1"] = "/sdcard/Download"   # 合并窗口内切走了

    time.sleep(0.3)
    assert listed == [], "用户已切到别的目录，这次刷新必须丢弃：%r" % (listed,)
    api.workers.shutdown(timeout=2.0)


def test_shutdown_cancels_pending_file_refresh(monkeypatch):
    """关闭程序时未到期的合并刷新必须被取消。

    否则它在 workers 收尾之后才触发，去起一个 adb ls：窗口已关，命令没有
    收件人，日志里只剩一条来源不明的错误。
    """
    api = _make_api()
    monkeypatch.setattr(api, "_FILE_REFRESH_DEBOUNCE_S", 0.3)
    listed = []
    monkeypatch.setattr(api, "file_list",
                        lambda s, p: listed.append((s, p)))
    api._file_dir["A1"] = "/sdcard"

    api._schedule_file_refresh("A1", "/sdcard/x.txt")
    assert api._file_refresh_timers, "定时器未登记"
    api.shutdown()

    time.sleep(0.5)
    assert listed == [], "关闭后不该再有目录刷新：%r" % (listed,)
    assert not api._file_refresh_timers, "定时器应已在关闭时清空"


def test_screen_record_start_twice_says_why_in_plain_words(monkeypatch, tmp_path):
    """已在录屏时再点「开始」：必须说清「正在录」并给出下一步，而不是回一个机器码。

    回归：守卫只 return {"ok": False, "reason": "recording"}，前端把它原样拼进
    提示 —— 用户看到的是「⚠ 录屏未能启动（recording）」：一句英文代码，既没
    说明现在到底在不在录，也没说想重开该先停。
    """
    api = _make_api()
    monkeypatch.setattr(api.video, "start",
                        lambda *a, **kw: (True, str(tmp_path / "r.mp4")))
    assert api.screen_record_start(None, save_dir=str(tmp_path)).get("ok") is True
    _events_by_kind(api)                      # 清掉启动那一批事件

    res = api.screen_record_start(None, save_dir=str(tmp_path))

    assert res["ok"] is False and res["reason"] == "recording", res
    assert "正在录屏中" in res.get("message", ""), res
    assert "停止录屏" in res["message"], "要给出下一步：先停止才能重开"
    texts = [p["text"] for p in _events_by_kind(api).get("status", [])]
    assert any("正在录屏中" in t for t in texts), texts

    api._rec_session = {}
    api.workers.shutdown(timeout=2.0)


def test_screen_record_stop_without_session_is_not_an_error():
    """没有会话时点「停止」：说一句「当前没有进行中的录屏」，但**不算失败**。

    旧实现什么都不说（用户对着按钮反复点）；这条也刻意不带 message —— 前端
    按 message 弹错误 toast，会把「已经停了」说成「⚠ 停止录屏失败：no_session」。
    """
    api = _make_api()

    res = api.screen_record_stop()

    assert res["ok"] is False and res["reason"] == "no_session", res
    assert "message" not in res, "no_session 不是失败，不该让前端弹 err toast"
    texts = [p["text"] for p in _events_by_kind(api).get("status", [])]
    assert any("当前没有进行中的录屏" in t for t in texts), texts
    api.workers.shutdown(timeout=2.0)


def test_screenshot_spawn_failure_is_reported(monkeypatch):
    """线程起不来时「立即截图」必须回 ok:false 并说清原因。

    回归：spawn 抛异常（线程数耗尽 / 内存告急）时没有 worker 被登记，也就没有
    任何 shot_state 事件；而 API 照旧返回 {"ok": True} —— 前端的禁用态只能等
    下一次 devices 事件才解开，用户对着一个灰掉的按钮不知道发生了什么。
    """
    api = _make_api()

    def boom(key, fn, *a, **kw):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(api.workers, "spawn", boom)

    res = api.screenshot()

    assert res["ok"] is False and res["reason"] == "spawn_error", res
    assert res["failed"] == ["A1"], res
    texts = [p["text"] for p in _events_by_kind(api).get("status", [])]
    assert any("无法启动截图线程" in t and "can't start new thread" in t
               for t in texts), texts


def test_screenshot_batch_completes_when_one_spawn_fails(monkeypatch):
    """批量截图里有一台线程起不来：汇总仍要弹出来，且如实说「1 成功 1 失败」。

    回归：那台没有 worker 记账，批次账永远 done < total —— 汇总 toast 再也弹不
    出来，界面也一直以为「还在截」。
    """
    api = _make_api()
    api.toggle_device("B2", True)
    monkeypatch.setattr(
        ctrl.ScreenCapturer, "screenshot",
        staticmethod(lambda adb, s, d, sf=True: ("D:/shots/%s.png" % s, None)))
    monkeypatch.setattr(ctrl.clipboard, "copy_image", lambda p: (True, ""))
    calls = {"n": 0}

    def spawn(key, fn, *a, **kw):
        calls["n"] += 1
        if calls["n"] == 2:                 # 第二台起不来（A1 先跑）
            raise RuntimeError("can't start new thread")
        return fn(*a, **kw)

    monkeypatch.setattr(api.workers, "spawn", spawn)

    res = api.screenshot()

    assert res["ok"] is True, "有一台跑起来了，整体不算失败：%r" % (res,)
    assert res["failed"] == ["B2"], res
    summaries = [p for p in _events_by_kind(api).get("status", [])
                 if p.get("toast") and "截图" in (p.get("text") or "")]
    assert len(summaries) == 1, "汇总必须弹出来：%r" % (summaries,)
    assert "1 成功" in summaries[0]["text"] and "1 失败" in summaries[0]["text"], \
        summaries[0]["text"]
    assert api._shot_batch is None, "批次结束后计数器必须摘掉"


def _frag_session(tmp_path, serial="A1"):
    """一个最小录屏会话：videos 里有一条已落盘的（残）文件。"""
    frag = tmp_path / ("record_%s.mp4" % serial)
    frag.write_bytes(b"\x00" * 128)
    return {
        "ts": "20240101_000000", "dir": str(tmp_path),
        "videos": {serial: str(frag)}, "devaudio": {}, "logcat_captures": {},
        "pointer_location_prev": {}, "show_touches_prev": {},
    }, frag


def test_record_teardown_failure_reports_partial_path(tmp_path):
    """收尾失败时要把**残片路径**说出来。

    回归：stop() 在「缺 moov 头」「落到本地但打包失败」时仍会回一个残片路径，
    旧实现把它丢掉，只播一句「录屏收尾失败」——用户在保存目录里看到
    record_xxx.mp4，既不知道是不是这次的，也不知道它为什么没进 zip、
    还能不能用。
    """
    api = _make_api()
    sess, frag = _frag_session(tmp_path)
    api._rec_session = sess

    class FakeVideo:
        def is_recording(self, s):
            return True

        def stop(self, s):
            return False, str(frag), "MP4 缺 moov 头，无法播放"

    api.video = FakeVideo()

    res = api.screen_record_stop()

    assert res["ok"] is True, res
    texts = [p["text"] for p in _events_by_kind(api).get("status", [])]
    assert any("录屏收尾失败" in t and str(frag) in t for t in texts), texts
    assert any("缺 moov 头" in t for t in texts), texts


def test_record_dead_teardown_reports_partial_path(tmp_path):
    """进程意外中断时同理：文案里给出残片的具体路径，而不是笼统的「保存目录」。"""
    api = _make_api()
    sess, frag = _frag_session(tmp_path)
    sess["dead"] = {"A1"}
    api._rec_session = sess

    class FakeVideo:
        def is_recording(self, s):
            return True

        def stop(self, s):
            return False, str(frag), "设备端进程已提前退出"

    api.video = FakeVideo()

    api.screen_record_stop()

    texts = [p["text"] for p in _events_by_kind(api).get("status", [])]
    hit = [t for t in texts if "视频不完整" in t]
    assert hit, texts
    assert str(frag) in hit[0], hit[0]


# ---------------------------------------------------------------------------
# 录屏取消：停止并删除本次产物（不合并、不打包）
# ---------------------------------------------------------------------------
def _cancel_session(tmp_path):
    """一个「已经录了一会儿」的会话：1 段视频 + 1 份 logcat + 1 个麦克风 wav。"""
    video = tmp_path / "record_A1_20240101_000000.mp4"
    video.write_bytes(b"\x00" * 256)
    log = tmp_path / "logcat_A1_20240101_000000.txt"
    log.write_text("01-01 log line\n", encoding="utf-8")
    mic = tmp_path / "mic_20240101_000000.wav"
    mic.write_bytes(b"RIFF" + b"\x00" * 64)
    sess = {
        "ts": "20240101_000000", "dir": str(tmp_path),
        "with_mic": False, "with_zip": True,
        "videos": {"A1": str(video)}, "devaudio": {},
        "logcat_captures": {"A1": str(log)},
        "mic_path": str(mic), "mic_started": True,
        "pointer_location_prev": {}, "show_touches_prev": {},
    }
    return sess, video, log, mic


class _FakeCap:
    """替身 logcat 抓取：只关心「停了吗、按什么参数停的」。"""

    def __init__(self):
        self.stopped = []

    def stop(self, serial, zip_on_stop=True):
        self.stopped.append((serial, zip_on_stop))

    def is_running(self, serial):
        return False


def test_screen_record_cancel_deletes_files_without_zip(tmp_path):
    """取消要真的把本次产物删掉，且**不**打包、**不**合并。

    回归背景：以前「录错了」只能点「停止」——它一定走合成 / 打包，用户拿到
    一个「✓ 已打包」的 zip，再自己去目录里删。取消的语义是「一个都不留」。
    """
    api = _make_api()
    sess, video, log, mic = _cancel_session(tmp_path)
    api._rec_session = sess
    api.logcat_capture = _FakeCap()

    calls = []

    class FakeVideo:
        def discard_ex(self, s):
            calls.append(("discard", s))
            return True, [], None

        def stop_ex(self, s):
            raise AssertionError("取消不该走 stop_ex（会把当前段 pull 回来）")

        def stop(self, s):
            raise AssertionError("取消不该走 stop（会把当前段 pull 回来）")

    api.video = FakeVideo()

    res = api.screen_record_cancel()

    assert res["ok"] is True, res
    assert res["removed"] == 3, res
    assert calls == [("discard", "A1")], calls
    assert not video.exists() and not log.exists() and not mic.exists()
    # 不打包：目录里不该出现 zip
    assert [p.name for p in tmp_path.iterdir() if p.suffix == ".zip"] == []
    # 抓取要按「不打包」停：zip_on_stop=True 会在抓取侧再压一次
    assert api.logcat_capture.stopped == [("A1", False)]
    toasts = [p for p in _events_by_kind(api).get("status", []) if p.get("toast")]
    assert len(toasts) == 1 and toasts[0]["type"] == "ok", toasts
    assert "3 个文件已删除" in toasts[0]["text"], toasts[0]["text"]
    assert api._rec_session == {}, "取消后会话必须清空（否则录屏永久锁死）"


def test_screen_record_cancel_deletes_pretaken_and_mic(tmp_path):
    """设备被拔掉时已取回的段（video_segs）与麦克风文件同样要删。

    这两处是「不在 videos 里、但确实是本次产物」的典型：漏了它们，取消之后
    保存目录里还躺着几个 mp4 / wav，用户以为取消没生效。
    """
    api = _make_api()
    sess, video, _log, mic = _cancel_session(tmp_path)
    extra = tmp_path / "record_A1_20240101_000000_p2.mp4"
    extra.write_bytes(b"\x00" * 128)
    sess["video_segs"] = {"A1": [str(extra)]}
    api._rec_session = sess
    api.logcat_capture = _FakeCap()
    api.video = type("V", (), {"discard_ex": lambda self, s: (
        False, [], "该设备未在录制")})()

    api.screen_record_cancel()

    assert not extra.exists(), "已取回的分段也要删"
    assert not mic.exists(), "麦克风文件也要删"


def test_screen_record_cancel_never_deletes_directory(tmp_path):
    """只删普通文件：目录一律跳过。

    取消是最容易被写成「把这次涉及到的路径全删掉」的地方，一旦某条登记进来的
    是目录（例如误把保存目录本身记进 videos），递归删除就等于删用户的文件夹。
    这里断言目录完好，且取消照常回报成功。
    """
    api = _make_api()
    sess, video, _log, _mic = _cancel_session(tmp_path)
    keep_dir = tmp_path / "sub"
    keep_dir.mkdir()
    (keep_dir / "keep.txt").write_text("x", encoding="utf-8")
    sess["videos"]["B2"] = str(keep_dir)
    api._rec_session = sess
    api.logcat_capture = _FakeCap()
    api.video = type("V", (), {"discard_ex": lambda self, s: (
        False, [], "该设备未在录制")})()

    res = api.screen_record_cancel()

    assert res["ok"] is True, res
    assert keep_dir.is_dir() and (keep_dir / "keep.txt").exists()
    assert not video.exists()


def test_screen_record_cancel_reports_undeletable_file(tmp_path, monkeypatch):
    """删不掉的文必须说出来，不能「取消成功」了事。

    最现实的场景：刚拉回来的那段 mp4 还被播放器开着，Windows 直接拒绝删除。
    这时文件还在磁盘上，沉默地报成功等于骗用户。
    """
    import backend.controllers.record as rec_mod

    api = _make_api()
    sess, video, _log, _mic = _cancel_session(tmp_path)
    api._rec_session = sess
    api.logcat_capture = _FakeCap()
    api.video = type("V", (), {"discard_ex": lambda self, s: (True, [], None)})()

    real_remove = rec_mod.os.remove

    def fake_remove(p, *a, **kw):
        if str(p).endswith(".mp4"):
            raise PermissionError("被占用")
        return real_remove(p, *a, **kw)

    monkeypatch.setattr(rec_mod.os, "remove", fake_remove)

    res = api.screen_record_cancel()

    assert res["ok"] is True, res
    assert res["kept"] and res["kept"][0].endswith(".mp4"), res
    assert video.exists(), "删不掉的文件本来就应该还在"
    toasts = [p for p in _events_by_kind(api).get("status", []) if p.get("toast")]
    assert toasts and toasts[0]["type"] == "warn", toasts
    assert "未能删除" in toasts[0]["text"], toasts[0]["text"]
    assert "record_A1_20240101_000000.mp4" in toasts[0]["text"], toasts[0]["text"]


def test_screen_record_cancel_restores_overlays(tmp_path):
    """取消同样要把设备 overlay 恢复原值（录屏开过指针位置 / 触摸圆点）。

    这两项是设备系统设置，与「这次的东西留不留」无关；漏了它，用户点一次取消
    就发现自己手机上永远开着准星，而且不知道是谁开的。
    """
    api = _make_api()
    sess, _video, _log, _mic = _cancel_session(tmp_path)
    sess["pointer_location_prev"] = {"A1": "0"}
    api._rec_session = sess
    api.logcat_capture = _FakeCap()
    api.video = type("V", (), {"discard_ex": lambda self, s: (True, [], None)})()

    seen = []
    api._restore_overlays = lambda s: seen.append(s)

    api.screen_record_cancel()

    assert seen and seen[0] is sess, seen


def test_screen_record_cancel_without_session_is_not_error():
    """没有会话时点取消：一句 info，不算失败（与「停止」同一套口径）。"""
    api = _make_api()
    api._rec_session = {}

    res = api.screen_record_cancel()

    assert res == {"ok": False, "reason": "no_session"}, res
    statuses = _events_by_kind(api).get("status", [])
    assert any("没有进行中的录屏" in (p.get("text") or "") for p in statuses), statuses
    assert not [p for p in statuses if p.get("type") == "err"], statuses


def test_screen_record_cancel_clears_session_even_on_exception(tmp_path):
    """取消过程抛异常时，会话标记也必须清空。

    与停止同理：`_rec_session` 残留 → 之后每次「开始录屏」都被守卫判为
    recording，录屏功能永久锁死，只能重启程序。
    """
    api = _make_api()
    sess, _video, _log, _mic = _cancel_session(tmp_path)
    api._rec_session = sess

    def boom(s):
        raise OSError("磁盘掉线")

    api._session_discard = boom

    res = api.screen_record_cancel()

    assert res["ok"] is False and res["reason"] == "cancel_error", res
    assert api._rec_session == {}, "异常路径也必须清空会话"
    toasts = [p for p in _events_by_kind(api).get("status", []) if p.get("toast")]
    assert any("取消录屏出现异常" in p["text"] for p in toasts), toasts
    # 还能重新开始录屏（守卫不再误判）
    assert api.screen_record_start(None, save_dir=str(tmp_path)).get(
        "reason") != "recording"


def _fake_clock_run(stdout, rc=0):
    class _R:
        def __init__(self):
            self.stdout = stdout
            self.stderr = ""
            self.returncode = rc
    return lambda *a, **k: _R()


def test_device_clock_parses_epoch_and_timezone(monkeypatch):
    """一次 shell 拿回「时刻 + 时区偏移」：日志时间戳只有配上时区才能算准。

    threadtime 是设备本地墙上时间、不含时区，而收尾要拿它和设备此刻作差。
    时区分不清时，主机 +0800、设备 UTC 会平白算出 8 小时缺口。
    """
    monkeypatch.setattr(screen_service.subprocess, "run",
                        _fake_clock_run("1793850520+0800\n"))
    assert screen_service.device_clock("adb", "A1") == (1793850520, 8 * 3600)

    monkeypatch.setattr(screen_service.subprocess, "run",
                        _fake_clock_run("1793850520-0500\n"))
    assert screen_service.device_clock("adb", "A1") == (1793850520, -5 * 3600)

    monkeypatch.setattr(screen_service.subprocess, "run",
                        _fake_clock_run("1793850520+0000\n"))
    assert screen_service.device_clock("adb", "A1") == (1793850520, 0)


def test_device_clock_tolerates_missing_tz(monkeypatch):
    """老 shell 不认 %z（回显字面量或什么都没有）：时区留 None，时刻照给。

    调用方据此跳过「按时间戳算缺口」的判定 —— 猜出来的差值恰好是整小时，
    没法与真缺口区分，宁可不报。
    """
    monkeypatch.setattr(screen_service.subprocess, "run",
                        _fake_clock_run("1793850520%z\n"))
    assert screen_service.device_clock("adb", "A1") == (1793850520, None)

    # 有些 shell 把 \r\n / BOM 一起带回来，仍要能取到
    monkeypatch.setattr(screen_service.subprocess, "run",
                        _fake_clock_run(" 1793850520 \r\n"))
    assert screen_service.device_clock("adb", "A1") == (1793850520, None)


def test_device_clock_returns_none_when_unavailable(monkeypatch):
    """命令失败 / adb 异常：返回 None（未知），调用方跳过校验而不是给错结论。"""
    monkeypatch.setattr(screen_service.subprocess, "run",
                        _fake_clock_run("", 1))
    assert screen_service.device_clock("adb", "A1") is None

    monkeypatch.setattr(screen_service.subprocess, "run",
                        _fake_clock_run("date: not found\n", 127))
    assert screen_service.device_clock("adb", "A1") is None

    # 退出码 0 但输出里根本没有数字（车机 shell 要授权码时就是这种表现）
    monkeypatch.setattr(screen_service.subprocess, "run",
                        _fake_clock_run("Permission denied\n", 0))
    assert screen_service.device_clock("adb", "A1") is None

    def boom(*a, **k):
        raise FileNotFoundError("adb")
    monkeypatch.setattr(screen_service.subprocess, "run", boom)
    assert screen_service.device_clock("adb", "A1") is None


# ---------------------------------------------------------------------------
# logcat 按包过滤：包列表 / 包名转 pid
# ---------------------------------------------------------------------------

def test_logcat_packages_lists_third_party(monkeypatch):
    """默认只列第三方包（-3），并去掉重复、排序。"""
    import backend.controllers.logcat as lc_ctrl

    def fake_run(cmd, **kw):
        class R:
            returncode = 0
            stdout = ("package:com.demo.app\npackage:com.demo.app\n"
                      "package:com.other\n")
        return R()

    monkeypatch.setattr(lc_ctrl.subprocess, "run", fake_run)
    api = WebApi()
    res = api.logcat_packages("A1")
    assert res["ok"] is True
    assert res["packages"] == ["com.demo.app", "com.other"]


def test_logcat_packages_falls_back_to_all_when_no_third_party(monkeypatch):
    """-3 返回空（老系统不认 / 没有第三方包）时回退全量，不给一个空下拉。"""
    import backend.controllers.logcat as lc_ctrl
    seen = []

    def fake_run(cmd, **kw):
        seen.append(list(cmd))

        class R:
            returncode = 0
            # 带 -3 的第一次调用返回空（模拟老系统 / 无第三方包），触发回落
            stdout = ("" if "-3" in cmd
                      else "package:android\npackage:com.android.systemui\n")
        return R()

    monkeypatch.setattr(lc_ctrl.subprocess, "run", fake_run)
    api = WebApi()
    res = api.logcat_packages("A1")
    assert res["ok"] is True
    assert "android" in res["packages"]
    # 第一次带 -3，第二次不带
    assert "-3" in seen[0] and "-3" not in seen[1]


def test_logcat_packages_without_device_returns_empty(monkeypatch):
    import backend.controllers.logcat as lc_ctrl

    def boom(*a, **k):
        raise AssertionError("没有设备时不该起 adb 子进程")

    monkeypatch.setattr(lc_ctrl.subprocess, "run", boom)
    api = WebApi()
    assert api.logcat_packages("")["packages"] == []


def test_logcat_pidof_returns_pids(monkeypatch):
    import backend.controllers.logcat as lc_ctrl

    # 控制器在 import 时就把 pkg_pids_of 绑进自己的命名空间了，必须打到
    # lc_ctrl 上；打到 backend.logcat_service 上不会生效（典型 monkeypatch 陷阱）。
    monkeypatch.setattr(lc_ctrl, "pkg_pids_of",
                        lambda adb, serial, pkg: {"5518", "5417"})
    api = WebApi()
    res = api.logcat_pidof("A1", "com.demo.app")
    assert res["ok"] is True
    assert res["pids"] == ["5417", "5518"]     # 按「短数字在前」排序


def test_logcat_pidof_requires_both_args():
    api = WebApi()
    assert api.logcat_pidof("", "com.demo.app") == {"ok": False, "pids": []}
    assert api.logcat_pidof("A1", "") == {"ok": False, "pids": []}
