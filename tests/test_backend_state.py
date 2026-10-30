# -*- coding: utf-8 -*-
"""backend.state.AppState —— 集中状态管理单测（纯逻辑，无 UI 依赖）。"""
import threading

from backend.state import AppState


def test_initial_state():
    st = AppState(adb_path="adb.exe")
    assert st.booted is False
    assert st.shutting_down is False
    assert st.adb_path == "adb.exe"
    assert st.is_busy() is False
    assert st.running_count() == 0


def test_begin_end_run_changes_busy_once():
    st = AppState()
    # 第一条命令：busy 从 False -> True，changed=True
    assert st.begin_run() == (True, True)
    # 并发第二条：仍 busy，无翻转
    assert st.begin_run() == (True, False)
    # 结束一条：仍 busy（还有一条在跑），无翻转
    assert st.end_run() == (True, False)
    # 结束最后一条：busy 翻回 False
    assert st.end_run() == (False, True)
    # 空跑 end_run 不会变负数
    assert st.end_run() == (False, False)
    assert st.running_count() == 0


def test_interactive_keeps_busy_even_with_zero_running():
    st = AppState()
    assert st.sync_stop(False) == (False, False)
    # 进入 adb shell 交互：即使没有计数中的命令也 busy
    assert st.sync_stop(True) == (True, True)
    # 交互中再来一次不重复广播
    assert st.sync_stop(True) == (True, False)
    # 退出交互
    assert st.sync_stop(False) == (False, True)


def test_mark_booted_writes_content_and_flags():
    st = AppState()
    cmds = [
        {"id": "a", "name": "命令A", "labels": ["通用"],
         "commands": [{"command": "git status", "delay": 0}]},
        {"id": "b", "name": "命令B", "labels": ["设备"],
         "commands": [{"command": "adb shell date", "delay": 0}]},
    ]
    payload = st.mark_booted(
        cmds, ["第 3 条命令无法解析"], adb_path="adb", version="web-test")
    assert st.booted is True
    assert st.cmd_warnings == ["第 3 条命令无法解析"]
    assert payload["version"] == "web-test"
    # payload 含精简字段 + 命令文本（供前端指令台按内容检索）；不改动原对象
    assert [c["id"] for c in payload["commands"]] == ["a", "b"]
    assert payload["commands"][0]["labels"] == ["通用"]
    # 命令文本随 payload 下发，applyCmdFilter 才能按「命令内容」检索
    assert payload["commands"][0]["commands"] == [
        {"command": "git status", "delay": 0}]
    assert payload["commands"][1]["commands"] == [
        {"command": "adb shell date", "delay": 0}]
    assert "commands" in cmds[0]  # 原对象不动


def test_mark_booted_keeps_builtin_flag():
    """内置命令的 builtin 标记必须随命令一起下发给前端。

    回归：mark_booted 重建命令字典时只挑了 id/name/labels/commands/clickCount，
    把 builtin 丢了 —— 前端 `if (c.builtin)` 恒为假，内置命令的角标样式
    （.cmd-chip--builtin）与「程序内置默认…」提示永远不会出现，界面上一眼看不出
    哪些命令是程序自带的。
    """
    st = AppState()
    payload = st.mark_booted([
        {"id": "bi.reboot", "name": "[内置] 重启设备", "labels": ["通用"],
         "commands": [{"command": "adb reboot", "delay": 0}],
         "clickCount": 0, "builtin": True},
        {"id": "u1", "name": "[通用] 我的命令", "labels": ["通用"],
         "commands": [{"command": "git status", "delay": 0}]},
    ], [])
    by_id = {c["id"]: c for c in payload["commands"]}
    assert by_id["bi.reboot"]["builtin"] is True
    # 用户命令没有该字段 -> 下发 False（前端只需判断真假，不必处理 undefined）
    assert by_id["u1"]["builtin"] is False


def test_mark_booted_keeps_input_only_flag():
    """inputOnly（electerm 仅输入模式）必须随命令下发给前端。

    回归：mark_booted 以白名单逐字段重建命令字典，normalize_commands 新解析出的
    inputOnly 若不加进来就永远到不了前端 —— 用户标了 "inputOnly": true 的命令
    点击后照样直接执行，填输入框确认的机会被静默吞掉。
    """
    st = AppState()
    payload = st.mark_booted([
        {"id": "a", "name": "仅输入", "labels": ["x"], "inputOnly": True,
         "commands": [{"command": "adb shell settings put global http_proxy 1.2.3.4:8080",
                       "delay": 0}]},
        {"id": "b", "name": "直接执行", "labels": ["x"], "inputOnly": False,
         "commands": [{"command": "adb devices", "delay": 0}]},
    ], [])
    by_id = {c["id"]: c for c in payload["commands"]}
    assert by_id["a"]["inputOnly"] is True
    assert by_id["b"]["inputOnly"] is False


def test_mark_shutdown_and_snapshot():
    st = AppState()
    st.begin_run()
    st.mark_shutdown()
    snap = st.snapshot()
    assert snap["shutting_down"] is True
    assert snap["busy"] is True
    assert snap["running"] == 1
    assert snap["booted"] is False


def test_thread_safety_smoke():
    """多线程并发 begin/end 不把计数弄负 / 忙翻转不乱。"""
    st = AppState()
    errs = []

    def worker():
        try:
            for _ in range(200):
                st.begin_run()
                st.end_run()
            # 同一线程内保证 begin 先于 end 的配对
            st.begin_run()
        except Exception as ex:  # pragma: no cover
            errs.append(ex)

    ts = [threading.Thread(target=worker) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errs
    # 每个 worker 末尾各留了一次 begin_run，共 8 个未配对
    assert st.running_count() == 8
    assert st.is_busy() is True
