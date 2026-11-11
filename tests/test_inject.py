# -*- coding: utf-8 -*-
"""adb_inject 的单元测试：验证 -s 自动拼接逻辑，方便后续优化时回归。

运行：  python -m pytest tests/test_inject.py -q
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adb_inject import (
    transform,
    needs_device,
    merge_adb_shell_commands,
    merge_adb_shell_commands_detailed,
    is_subshell_command,
)


def test_basic_adb_shell():
    assert transform("adb shell date", "AE86EE") == "adb -s AE86EE shell date"


def test_adb_reboot():
    assert transform("adb reboot", "AE86EE") == "adb -s AE86EE reboot"


def test_adb_pull():
    assert transform("adb pull /log/logcat/", "AE86EE") == "adb -s AE86EE pull /log/logcat/"


def test_adb_exe_global_subcommand_not_injected():
    # kill-server 是全局子命令，不注入 -s
    assert transform("adb.exe kill-server", "AE86EE") == "adb.exe kill-server"


def test_adb_devices_not_injected():
    assert transform('adb devices | Select-String "device$"', "AE86EE") == \
        'adb devices | Select-String "device$"'


def test_existing_serial_replaced():
    cmd = "adb -s 0612333158554305 shell input tap 1411 443"
    assert transform(cmd, "AE86EE") == "adb -s AE86EE shell input tap 1411 443"


def test_powershell_variable_preserved():
    cmd = 'adb shell "date $currentDate"'
    assert transform(cmd, "AE86EE") == 'adb -s AE86EE shell "date $currentDate"'


def test_scrcpy_injected():
    assert transform("scrcpy", "AE86EE") == "scrcpy -s AE86EE"


def test_non_adb_untouched():
    assert transform("python -m pytest x.py -s", "AE86EE") == "python -m pytest x.py -s"
    assert transform("cd D:\\BUG", "AE86EE") == "cd D:\\BUG"


def test_empty_serial_returns_original():
    assert transform("adb shell date", "") == "adb shell date"


def test_no_false_positive_on_adbdevices():
    # 不能把 adbdevices 当成 adb 命令
    assert transform("adbdevices foo", "AE86EE") == "adbdevices foo"


def test_needs_device():
    assert needs_device({"commands": [{"command": "adb shell date"}]}) is True
    assert needs_device({"commands": [{"command": "python -m pytest x.py"}]}) is False
    assert needs_device({"commands": [{"command": "adb devices"}]}) is False


def test_merge_interactive_adb_shell():
    # 基本合并：adb shell + cd + ls
    assert merge_adb_shell_commands(
        ["adb shell", "cd /log/logcat", "ls"]
    ) == ["adb shell 'cd /log/logcat; ls'"]

    # 已有 -s 也要合并
    assert merge_adb_shell_commands(
        ["adb -s 0612333158554305 shell", "cd /sdcard", "ls -l"]
    ) == ["adb -s 0612333158554305 shell 'cd /sdcard; ls -l'"]

    # 遇到下一条 adb 命令时结束合并
    assert merge_adb_shell_commands(
        ["adb shell", "cd /sdcard", "adb devices"]
    ) == ["adb shell 'cd /sdcard'", "adb devices"]

    # 非 adb shell 不受影响
    assert merge_adb_shell_commands(
        ["adb shell date", "python -m pytest"]
    ) == ["adb shell date", "python -m pytest"]

    # 空列表安全
    assert merge_adb_shell_commands([]) == []


def test_multiple_adb_in_complex_pipeline():
    # PowerShell 管道 + 脚本块内部再次出现 adb，也需要注入 -s
    cmd = (
        r"adb shell dumpsys window | sls mCurrentFocus | "
        r"%{ if ($_ -match '(\S+)/') { adb shell am force-stop $Matches[1] } }"
    )
    expected = (
        r"adb -s AE86EE shell dumpsys window | sls mCurrentFocus | "
        r"%{ if ($_ -match '(\S+)/') { adb -s AE86EE shell am force-stop $Matches[1] } }"
    )
    assert transform(cmd, "AE86EE") == expected


def test_global_adb_left_others_injected():
    # 同一条复杂命令里既有全局子命令，又有普通 adb 命令
    assert transform("adb devices; adb shell date", "AE86EE") == \
        "adb devices; adb -s AE86EE shell date"
    assert transform("adb shell date && adb kill-server", "AE86EE") == \
        "adb -s AE86EE shell date && adb kill-server"


def test_adb_inside_string_literal_preserved():
    # 位于引号字面量里的 adb 不再被注入，避免破坏 PowerShell 字符串
    assert transform('echo "adb shell date"', "AE86EE") == 'echo "adb shell date"'
    assert transform("echo 'adb devices'", "AE86EE") == "echo 'adb devices'"


def test_merge_detailed_mapping():
    # 合并块的 end_index 指向原始列表最后一条（delay 挂接依据）
    assert merge_adb_shell_commands_detailed(
        ["adb shell", "cd /log/logcat", "ls"]
    ) == [("adb shell 'cd /log/logcat; ls'", 2)]

    # 合并块 + 后续独立命令，各自带正确下标
    assert merge_adb_shell_commands_detailed(
        ["adb shell", "cd /sdcard", "adb devices"]
    ) == [("adb shell 'cd /sdcard'", 1), ("adb devices", 2)]

    # 单条命令原样返回，下标不变
    assert merge_adb_shell_commands_detailed(
        ["adb shell date", "python -m pytest"]
    ) == [("adb shell date", 0), ("python -m pytest", 1)]

    # 空列表安全
    assert merge_adb_shell_commands_detailed([]) == []

    # 与 merge_adb_shell_commands 结果一致
    cmds = ["adb shell", "cd /x", "ls", "adb devices", "echo ok"]
    assert merge_adb_shell_commands(cmds) == \
        [c for c, _ in merge_adb_shell_commands_detailed(cmds)]


# ---------------------------------------------------------------------------
# 裸子 shell 识别：powershell / cmd / bash 会抢走持久会话的 stdin
# ---------------------------------------------------------------------------
# 这几条命令一旦被当成普通命令（带结束标记下发），标记就会进内层 shell；
# `exit` 那一行连同预读的标记一起被丢弃，外层永远等不到 → 卡死。
def test_bare_shells_are_subshell():
    for cmd in ("powershell", "powershell.exe", "pwsh", "cmd", "cmd /k",
                "bash", "sh", "zsh",
                "powershell -NoProfile -NoLogo -ExecutionPolicy Bypass"):
        assert is_subshell_command(cmd) is True, cmd


def test_oneshot_forms_are_not_subshell():
    """带一次性执行开关 / 直接跟脚本文件的，跑完就退，不是交互会话。"""
    for cmd in ('powershell -Command "Get-Date"',
                'powershell -c "Get-Date"',
                "powershell -File setup.ps1",
                "powershell setup.ps1",
                "cmd /c dir",
                "bash -c ls",
                "sh build.sh",
                "bash ./run.sh"):
        assert is_subshell_command(cmd) is False, cmd


def test_non_shell_commands_are_not_subshell():
    for cmd in ("adb root", "adb shell", "echo hi", "python a.py",
                "git status", "", "   "):
        assert is_subshell_command(cmd) is False, cmd


def test_full_path_shell_is_subshell():
    """用户在输入框里贴了完整路径时也要认出来。"""
    assert is_subshell_command(
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe") is True
    assert is_subshell_command("/usr/local/bin/bash") is True
    assert is_subshell_command('"C:\\Program Files\\PowerShell\\7\\pwsh.exe"') is True


def test_compound_command_is_not_treated_as_subshell():
    """复合命令（`cd x && powershell`）不按子 shell 处理。

    前半段是普通命令，整条走直通会让前半段的成败也失去反馈；这类情况交给
    兜底超时收尾即可。
    """
    for cmd in ("cd /x && powershell", "echo hi; powershell", "dir | powershell"):
        assert is_subshell_command(cmd) is False, cmd


def test_shell_names_followed_by_flags_only():
    """只带开关（没有脚本文件）仍是交互式：`cmd /k`、`powershell -NoExit`。"""
    assert is_subshell_command("cmd /k") is True
    assert is_subshell_command("powershell -NoExit") is True
    # 但 `cmd /c` 是一次性
    assert is_subshell_command("cmd /c") is False

# ---------------------------------------------------------------------------
# 序列号拼接：加引号（安全 + 含空格序列号不丢）
# ---------------------------------------------------------------------------
def test_plain_serial_stays_unquoted():
    """普通序列号保持原样：指令台里显示的还是用户熟悉的样子。"""
    assert transform("adb shell date", "AE86EE") == "adb -s AE86EE shell date"
    assert transform("adb shell date", "192.168.1.5:5555") == \
        "adb -s 192.168.1.5:5555 shell date"
    assert transform("adb shell date", "emulator-5554") == \
        "adb -s emulator-5554 shell date"


def test_serial_with_space_is_quoted():
    """mDNS 冲突时 adb 打印的序列号本身含空格 —— 必须**整体**交给 adb。

    不引起来的话 adb 只收到 `adb-XXXX`，命令就下到了错误的设备（或者干脆
    报 device not found），用户完全看不出发生了什么。
    """
    serial = "adb-XXXX (2)._adb-tls-connect._tcp"
    got = transform("adb shell date", serial)
    assert got == "adb -s '%s' shell date" % serial


def test_serial_with_shell_metacharacters_is_quoted():
    r"""序列号来自设备端描述符，不能让它把命令拼成别的意思。

    序列号自称 `x"; Remove-Item C:\; "` 时，未加引号的拼法就是一条
    PowerShell 注入命令。
    """
    serial = 'x"; Remove-Item C:\\; "'
    got = transform("adb shell date", serial)
    assert got.startswith("adb -s '")
    assert got.endswith("' shell date")
    # 整段序列号原样落在引号里
    assert serial in got


def test_serial_with_single_quote_is_doubled():
    """PowerShell 单引号串里，单引号写成两个（'' 表示一个 '）。"""
    assert transform("adb shell date", "a'b") == "adb -s 'a''b' shell date"


def test_scrcpy_serial_with_backslash_is_not_mangled():
    r"""re.sub 的字符串替换会处理 `\` 转义 —— 序列号含反斜杠时不能被改写。

    旧实现把序列号直接拼进替换串：`a\b` 里的 `\b` 被当成退格符，序列号直接
    变成乱码；`a\d` 则让 re.sub 抛 `bad escape`，整条命令执行失败。
    """
    got = transform("scrcpy", "a\\b")
    assert got == "scrcpy -s 'a\\b'"
    # 不含反斜杠的普通序列号仍然不加引号
    assert transform("scrcpy", "AE86EE") == "scrcpy -s AE86EE"


def test_transform_replaces_existing_quoted_serial():
    """命令里已经写了带引号的 -s 时，整段都要被换掉（不能只换前半截）。"""
    got = transform("adb -s 'old one' shell date", "AE86EE")
    assert got == "adb -s AE86EE shell date"


def test_merge_detects_interactive_shell_with_quoted_serial():
    """带引号的序列号也要能被认成「交互式 adb shell」，否则合并与直通都失效。"""
    cmds = ["adb -s 'x y' shell", "cd /log", "ls"]
    merged = merge_adb_shell_commands_detailed(cmds)
    assert len(merged) == 1
    assert merged[0][0] == "adb -s 'x y' shell 'cd /log; ls'"
