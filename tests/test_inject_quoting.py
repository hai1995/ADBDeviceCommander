# -*- coding: utf-8 -*-
r"""门禁：合并后的 `adb shell '...'` 在 **PowerShell 参数模式**下必须只切出
「一个」命令参数。

背景
----
`adb_inject._build_shell()` 把连续几条设备端命令合并成
``adb shell '<cmd1>; <cmd2>'``，靠外层单引号把整串交给 adb —— adb 收到**一个**
参数后才会把它原样丢给设备端 shell，里面的 `;` 由**设备端**去切分。

但包裹用的单引号是在**本机 PowerShell** 里解析的。PowerShell 的参数模式里，
单引号串内部的单引号会**提前闭合**外层引号：

    adb shell 'grep 'a;b' /proc/x'

在 PowerShell 里被切成::

    ['adb', 'shell', 'grep a', ';', 'b /proc/x']

`;` 于是提前变成了 **PowerShell 的语句分隔符** —— 后半截 `b /proc/x` 会被当成
**本机命令**执行，而不是设备端命令的一部分。用户在指令台里写
``grep 'FATAL' /proc/x`` 这种带引号的设备端命令时，就会看到「设备上什么都没发生，
本机却蹦出一堆输出」。

修复
----
包裹时把内部命令自带的单引号按 PowerShell 规则写成两个（``''``）::

    adb shell 'grep ''a;b'' /proc/x'

PowerShell 还原出的仍是**一个**参数 `grep 'a;b' /proc/x`，adb 原样交给设备端。

为什么用模拟的分词器而不是真的 PowerShell
------------------------------------------
本项目的 CI 跑在 Linux 上，没有 PowerShell 可用；而这条规则的**要害**恰恰是
PowerShell 的参数模式与 POSIX shell 不同（POSIX 的单引号里没有转义，
`''` 会被解析成「空串 + 空串」）。因此这里用一个**按 PowerShell 规则写的
分词器**做模型：

  * 单引号串：``''`` 表示一个字面单引号（唯一的转义规则）；
  * 双引号串：反斜杠转义 + ``$`` 变量展开（本用例不涉及，只保留结构）；
  * 裸字（bareword）：遇到空白 / 引号 / ``;`` / 结束为止；
  * ``;`` 是语句分隔符：切断当前参数并结束本条命令；
  * 相邻的裸字与引号串之间**没有空白** → 拼成同一个参数。

模型与真实 PowerShell 的差异只可能让本门禁**更严**（宁可误报不可漏报），
且它明确覆盖了真实缺陷 —— 见 test_merge_quote_is_not_early_closed。
"""
import pytest

from adb_inject import merge_adb_shell_commands_detailed


def _ps_split_statements(line):
    """把一行 PowerShell 按参数模式切成「若干条语句，每条是参数列表」。

    返回 [[arg, ...], [arg, ...], ...]。语句之间由 `;` 分隔。
    """
    statements, args = [], []
    cur = ""
    i, n = 0, len(line)
    while i < n:
        ch = line[i]
        if ch == "'":
            i += 1
            while i < n:
                if line[i] == "'":
                    # '' → 字面单引号；单独一个 ' → 闭合
                    if i + 1 < n and line[i + 1] == "'":
                        cur += "'"
                        i += 2
                        continue
                    i += 1
                    break
                cur += line[i]
                i += 1
            continue
        if ch == '"':
            i += 1
            while i < n and line[i] != '"':
                if line[i] == "\\" and i + 1 < n:
                    cur += line[i + 1]
                    i += 2
                    continue
                cur += line[i]
                i += 1
            i += 1
            continue
        if ch == ";":
            if cur:
                args.append(cur)
                cur = ""
            statements.append(args)
            args = []
            i += 1
            continue
        if ch.isspace():
            if cur:
                args.append(cur)
                cur = ""
            i += 1
            continue
        cur += ch
        i += 1
    if cur:
        args.append(cur)
    if args:
        statements.append(args)
    return statements


def _merged(commands):
    out = merge_adb_shell_commands_detailed(commands)
    assert len(out) == 1, "期望合并成一条，实际 %d 条：%r" % (len(out), out)
    return out[0][0]


# --------------------------------------------------------------------------- #
# 用例
# --------------------------------------------------------------------------- #
_CASES = [
    # (设备端命令序列, 期望 adb 收到的设备端命令)
    (["adb shell", "cd /log/logcat", "ls"], "cd /log/logcat; ls"),
    (["adb shell", "grep 'FATAL' /proc/x"], "grep 'FATAL' /proc/x"),
    (["adb shell", "grep 'a;b' /proc/x"], "grep 'a;b' /proc/x"),
    (["adb shell", "ls -l '/data/local/tmp/my file.txt'"],
     "ls -l '/data/local/tmp/my file.txt'"),
    (["adb shell", "echo 'it''s here'"], "echo 'it''s here'"),
    (["adb shell", "cat '/sdcard/中文 目录/a.txt'"], "cat '/sdcard/中文 目录/a.txt'"),
    (["adb shell", "echo '$PATH'"], "echo '$PATH'"),
]


@pytest.mark.parametrize("cmds,want", _CASES)
def test_merged_shell_is_one_argument_in_powershell(cmds, want):
    """合并后的命令在 PowerShell 里必须只切出「一条语句、一个 adb 参数」。"""
    merged = _merged(cmds)
    stmts = _ps_split_statements(merged)
    assert len(stmts) == 1, (
        "合并后的命令在 PowerShell 里被切成了 %d 条语句（`;` 提前变成了"
        "PowerShell 的语句分隔符）：%r\n  原命令序列：%r"
        % (len(stmts), stmts, cmds))
    args = stmts[0]
    assert args[0] == "adb" and args[1] == "shell", (
        "参数头不对：%r" % (args,))
    assert len(args) == 3, (
        "adb 之后应当只有**一个**命令参数，实际切出 %d 个：%r"
        % (len(args) - 2, args[2:]))
    # PowerShell 还原出的那个参数，必须与设备端命令逐字相同
    assert args[2] == want, (
        "交给 adb 的设备端命令不对：\n  实际=%r\n  期望=%r" % (args[2], want))


def test_merge_quote_is_not_early_closed():
    """回归：内层单引号不得提前闭合外层引号。

    旧实现直接拼 `'...'`（不转义），遇到设备端命令自带单引号时，
    PowerShell 会提前闭合外层引号，把一条命令切成几条语句 ——
    后半截会被当成本机命令执行。
    """
    merged = _merged(["adb shell", "grep 'a;b' /proc/x"])
    # 转义后的形态：'...' 内部不含未转义的单引号
    body = merged[len("adb shell "):]
    assert body.startswith("'") and body.endswith("'"), (
        "外层引号位置不对：%r" % merged)
    inner = body[1:-1]
    # 内部每个单引号都必须是成对出现的 ''（PowerShell 的唯一转义规则）
    i = 0
    while i < len(inner):
        if inner[i] == "'":
            assert i + 1 < len(inner) and inner[i + 1] == "'", (
                "内层出现未转义的单引号（位置 %d）：%r" % (i, inner))
            i += 2
            continue
        i += 1
    # 还原后应与设备端命令一致
    assert inner.replace("''", "'") == "grep 'a;b' /proc/x"


def test_merge_without_inner_quotes_is_unchanged():
    """不含单引号的常见场景，输出形态保持原样（不引入多余转义）。"""
    assert _merged(["adb shell", "cd /log", "ls"]) == "adb shell 'cd /log; ls'"


def test_merged_serial_keeps_its_own_quoting():
    """带序列号的入口命令：序列号自己的引号不受影响。"""
    merged = _merged(["adb -s 'x y' shell", "ls"])
    assert merged == "adb -s 'x y' shell 'ls'", merged
    stmts = _ps_split_statements(merged)
    assert len(stmts) == 1
    assert stmts[0] == ["adb", "-s", "x y", "shell", "ls"], stmts[0]


def test_ps_splitter_model_itself():
    """分词器模型的自检：确认它确实会把「提前闭合」切成多条语句。

    没有这一条，上面那些用例可能因为模型写错而「假绿」。
    """
    bad = "adb shell 'grep 'a;b' /proc/x'"
    stmts = _ps_split_statements(bad)
    assert len(stmts) == 2, (
        "模型没认出提前闭合的特征（应切出 2 条语句）：%r" % (stmts,))
    assert stmts[1] == ["b /proc/x"], stmts[1]
    # 对照：转义后只有一条语句、一个命令参数
    good = "adb shell 'grep ''a;b'' /proc/x'"
    stmts = _ps_split_statements(good)
    assert len(stmts) == 1, stmts
    assert stmts[0] == ["adb", "shell", "grep 'a;b' /proc/x"], stmts[0]


def test_adb_receives_whole_sequence_as_one_arg():
    """多条设备端命令合并后，adb 收到的是**一条**命令（`;` 由设备端切分）。"""
    merged = _merged(["adb shell", "cd /sdcard", "ls -l", "cat a.txt"])
    args = _ps_split_statements(merged)[0]
    assert args == ["adb", "shell", "cd /sdcard; ls -l; cat a.txt"], args
