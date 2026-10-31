# -*- coding: utf-8 -*-
"""backend.controller.WebApi —— pywebview js_api 桥单测（注入 FakeSession，不跑真命令）。"""
import os
import threading
import time
import zipfile

import pytest

import backend.controller as ctrl
import backend.device_service as ds
from backend.controller import WebApi

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

    def __init__(self, output_callback=None):
        self.output_callback = output_callback
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

    def __init__(self, output_callback=None):
        super().__init__(output_callback)
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
    patch_ctrl(monkeypatch, "device_is_root", lambda adb, serial: False)
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
    patch_ctrl(monkeypatch, "device_is_root", lambda adb, serial: True)
    api = _make_api()
    assert api.run_custom("adb root") == {"ok": True}
    _run_and_settle(api)
    assert api.session.calls == [], "已 root 时不应再下发 adb root"
    by_kind = _events_by_kind(api)
    assert any("已处于 root" in p["text"] and "跳过" in p["text"]
               for p in by_kind.get("status", [])), by_kind.get("status")


def test_unroot_skipped_when_not_root(monkeypatch):
    """设备未 root：`adb unroot` 同样是无谓重启，跳过（方向对称）。"""
    patch_ctrl(monkeypatch, "device_is_root", lambda adb, serial: False)
    api = _make_api()
    assert api.run_custom("adb unroot") == {"ok": True}
    _run_and_settle(api)
    assert api.session.calls == []
    by_kind = _events_by_kind(api)
    assert any("未 root" in p["text"] and "跳过" in p["text"]
               for p in by_kind.get("status", [])), by_kind.get("status")


def test_root_executes_when_needed_and_idle(monkeypatch):
    """未 root、无进行中任务：正常下发（保护不能把正常需求挡死）。"""
    patch_ctrl(monkeypatch, "device_is_root", lambda adb, serial: False)
    api = _make_api()
    assert api.run_custom("adb root") == {"ok": True}
    assert wait_until(lambda: len(api.session.calls) >= 1)
    assert api.session.calls[0]["script"] == "adb -s A1 root"


def test_root_skipped_while_recording(monkeypatch):
    """未 root 但正在录屏：跳过并说明——执行会重启 adbd 杀掉 screenrecord，
    视频缺 moov 头、不完整（使用说明「录屏被中断」条就是这个坑）。"""
    patch_ctrl(monkeypatch, "device_is_root", lambda adb, serial: False)
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
    patch_ctrl(monkeypatch, "device_is_root", lambda adb, serial: False)
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
    patch_ctrl(monkeypatch, "device_is_root", lambda adb, serial: False)
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
    patch_ctrl(monkeypatch, "device_is_root", lambda adb, serial: False)
    api = _make_api()
    api.video = _FakeVideoRec(recording={"A1"})
    assert api.run_custom("adb root && adb shell id") == {"ok": True}
    _run_and_settle(api)
    assert api.session.calls == [], "复合命令里的 root 切换也要整条拦下"


def test_root_mention_in_quotes_is_not_guarded(monkeypatch):
    """引号内仅「提到」adb root（提交信息 / 回显）不下发，不应被拦。"""
    patch_ctrl(monkeypatch, "device_is_root", lambda adb, serial: True)
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
    """设备被移除（gone）后，_reap_gone_tools 应强停其遗留的 logcat 监控 / 抓取，
    但不误杀仍在设备列表里（含宽限期内短暂失联）的设备。

    回归点：无线 / 网络 ADB 或 adb 卡顿时 `adb logcat` 可能迟迟不退，光靠 worker 的
    stdout-EOF 自收尾不可靠，会留下孤儿 adb 进程且界面卡在「监控中」。以设备快照为
    权威可补这一缺口。
    """
    api = _make_api()
    # 当前设备快照只剩 A1、B2（C3 已彻底移除，D4 处于宽限仍保留）
    api.devices.device_state = {"A1": "device", "B2": "device", "D4": "offline"}
    api.devices.device_checked = {"A1": True, "B2": True, "D4": True}

    stopped_mon, stopped_cap = [], []

    class FakeMon:
        def __init__(self, running): self._r = list(running)
        def running_serials(self): return list(self._r)
        def stop(self, s): stopped_mon.append(s)

    class FakeCap:
        def __init__(self, running): self._r = list(running)
        def running_serials(self): return list(self._r)
        def stop(self, s, zip_on_stop=False): stopped_cap.append(s)

    # 监控 / 抓取正在 A1、B2、C3、D4 上进行；C3 已从快照移除应被杀，其余不应
    api.logcat_monitor = FakeMon(["A1", "B2", "C3", "D4"])
    api.logcat_capture = FakeCap(["A1", "C3"])
    api._reap_gone_tools()

    assert stopped_mon == ["C3"], stopped_mon
    assert stopped_cap == ["C3"], stopped_cap


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


# ---------------------------------------------------------------------------
# 截图 → 同步至粘贴板
# ---------------------------------------------------------------------------
class _FakeCapturer:
    """替身 ScreenCapturer：固定返回一条路径（或一条失败信息）。"""

    def __init__(self, path=None, err=None):
        self.path = path or r"D:\shots\screenshot_A1_20260928_120000.png"
        self.err = err
        self.calls = []

    def screenshot(self, adb, serial, save_dir):
        self.calls.append((adb, serial, save_dir))
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

    def blocked(_adb, serial, _save_dir):
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
    def flaky(adb, serial, save_dir):
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

    def blocked(_adb, serial, _save_dir):
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

    def gated(_adb, serial, _save_dir):
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

    def boom(_adb, _serial, _save_dir):
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

    def half_boom(adb, serial, save_dir):
        if serial == "B2":
            raise RuntimeError("adb 崩了")
        return (r"D:\shots\s.png", None)

    monkeypatch.setattr(ctrl.ScreenCapturer, "screenshot",
                        staticmethod(half_boom))

    with pytest.raises(RuntimeError):
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
    monkeypatch.setattr(api.video, "stop", boom)

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
    monkeypatch.setattr(api.video, "set_system_setting", fake_set)

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
    monkeypatch.setattr(api.video, "set_system_setting",
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
    monkeypatch.setattr(api.video, "set_system_setting",
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
    """启动失败撤销半启动会话时，已开启 overlay 的设备也必须恢复。

    否则用户设备会一直开着指针准星/触摸圆点——下次正常用手机时满屏干扰。
    """
    api = _make_api()
    api.devices.device_checked = {"A1": True, "B2": True, "C3": False}
    started = {"n": 0}

    def fake_start(*a, **kw):
        started["n"] += 1
        if started["n"] == 1:
            return True, str(tmp_path / "r1.mp4")   # 第一台成功
        raise OSError("模拟的意外错误")

    monkeypatch.setattr(api.video, "start", fake_start)
    puts = []
    monkeypatch.setattr(api.video, "get_system_setting",
                        lambda adb, serial, key: (True, "1"))
    monkeypatch.setattr(api.video, "set_system_setting",
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

    class _Pipe:
        def __init__(self, adb, serial, kind, exe, size, br, fps, on_status=None):
            seen.update(serial=serial, kind=kind, exe=exe, size=size, br=br)
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
    assert last["timeout"] is not None, "恢复后也要带兜底超时"


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
        assert sess.calls[0]["timeout"] is not None, cmd


def test_bare_cmd_and_bash_are_interactive():
    """cmd / bash 与 powershell 同类：裸写就是进子 shell。"""
    for cmd in ("cmd", "bash", "sh", "pwsh", "cmd /k"):
        sess = FakeSession()
        api = _make_api(session=sess)
        api._run_entries(_entries((cmd, 0)), None)
        assert sess.calls[0]["interactive"] is True, cmd


def test_non_interactive_command_gets_default_timeout():
    """普通命令必须带兜底超时。

    没有它，任何一条"哑"命令（读 stdin 的工具、卡住的 adb）都会永久占用
    _user_lock，后续命令全部排队 —— 界面就是卡死、点不动。
    """
    sess = FakeSession()
    api = _make_api(session=sess)
    api._run_entries(_entries(("adb devices", 0)), None)
    assert sess.calls[0]["timeout"] == api.DEFAULT_CMD_TIMEOUT == 120


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
