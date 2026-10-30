"""测试 backend.device_proc 的 PID 解析。

核心回归点：`_pick_pid` 必须能在不同 ROM 的 `ps -A` 输出里挑对 PID，
绝不能把「数字 UID」当成 PID 交给 kill（否则误杀别的系统进程）。
"""
import subprocess

import backend.device_proc as dp


def test_pick_pid_busybox_first_column():
    # busybox 布局：PID 在第一列
    line = "1234 root      0:00 /system/bin/screenrecord"
    assert dp._pick_pid(line) == "1234"


def test_pick_pid_toybox_name_uid():
    # 标准 toybox：USER(PID 在第二列)，用户名是文字
    line = "u0_a123 5678 123 0:00 screenrecord"
    assert dp._pick_pid(line) == "5678"


def test_pick_pid_numeric_uid_not_confused_with_pid():
    # 部分 ROM 第一列直接打印数字 UID：绝不能把 UID 当 PID
    # 第一列 10123(数字) 且第二列 5678(数字) -> 不是 busybox -> 取第二列起的 PID
    line = "10123 5678 4321 0:00 screenrecord"
    assert dp._pick_pid(line) == "5678"


def test_pick_pid_no_digit_returns_none():
    assert dp._pick_pid("root abc def screenrecord") is None


def test_device_pid_uses_ps_path_and_skips_numeric_uid(monkeypatch):
    # pidof 失败（空输出）时退化到 ps -A；ps 行里第一列是数字 UID，
    # 必须挑第二列的数字作为 PID，不能返回 UID。
    calls = []

    class _R:
        def __init__(self, out):
            self.stdout = out
            self.returncode = 0

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if "pidof" in cmd:
            return _R("")  # pidof 没找到
        return _R("10123 5678 4321 0:00 screenrecord\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    pid = dp.device_pid("adb", "serial123", "screenrecord")
    assert pid == "5678"
    # 确认走的是 ps -A 退化路径
    assert any("ps" in c for c in calls)


# ---------------------------------------------------------------------------
# 收尾顺序：-INT → 等收尾 → 仍存活才 -TERM
# ---------------------------------------------------------------------------
def _alive_run(calls):
    """fake subprocess.run：pidof 始终报同一个 PID（即「进程一直活着」）。"""

    class _R:
        def __init__(self, out=""):
            self.stdout = out
            self.returncode = 0

    def fake_run(cmd, **kw):
        calls.append(list(cmd))
        return _R("4321\n" if "pidof" in cmd else "")

    return fake_run


def test_graceful_kill_waits_before_term_and_skips_term_if_dead(monkeypatch):
    """`-INT` 之后必须**先等它写完收尾信息**，确认仍存活才补 `-TERM`。

    回归：早期实现把 -INT 与 -TERM 背靠背发出去，进程很可能死在写 moov / 补
    RIFF 头的中途 —— 白优雅一次，产出的 MP4 / WAV 依旧是坏的。
    """
    import time as _time
    calls, slept = [], []

    def fake_run(cmd, **kw):
        calls.append(list(cmd))
        if "pidof" in cmd:
            # 第一次问：活着；第二次问（-INT 之后）：已自行退出
            alive = not any("kill" in c for c in calls)
            return type("R", (), {"returncode": 0,
                                  "stdout": "4321\n" if alive else ""})()
        if "ps" in cmd:
            return type("R", (), {"returncode": 0, "stdout": ""})()
        return type("R", (), {"returncode": 0, "stdout": ""})()

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(dp.time, "sleep", lambda s: slept.append(s))

    assert dp.kill_device_process("adb", "A1", "screenrecord", wait=0.6) is True
    kills = [c for c in calls if "kill" in c]
    assert kills and kills[0][-3:] == ["kill", "-INT", "4321"], kills
    assert slept == [0.6], "发完 -INT 必须先等收尾（实际 %r）" % slept
    assert not any(c[-2:] == ["-TERM", "4321"] for c in kills), \
        "进程已退出时不应再补 -TERM（会砍在收尾中途）：%r" % kills


def test_graceful_kill_sends_term_only_when_still_alive(monkeypatch):
    """进程在 -INT 后仍存活（僵死 / 不响应）时才补 -TERM。"""
    calls = []
    monkeypatch.setattr(subprocess, "run", _alive_run(calls))
    monkeypatch.setattr(dp.time, "sleep", lambda s: None)

    assert dp.kill_device_process("adb", "A1", "tinycap", wait=0.6) is True
    sigs = [c[5] for c in calls if "kill" in c]
    assert sigs == ["-INT", "-TERM"], sigs
