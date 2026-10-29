# -*- coding: utf-8 -*-
"""
adb_inject.py
=============
纯逻辑模块：负责把命令里的 `adb` / `adb.exe` / `scrcpy` 自动拼接上
`-s <设备序列号>`，以及判断某条快捷指令「是否需要指定设备（会被注入 -s）」。

该模块不依赖任何 GUI / 外部进程，可独立单元测试，方便后续优化。
"""

import re

# 这些 adb 子命令是「全局」的，不能（也不需要）指定 -s：
#   adb devices / kill-server / start-server / connect / disconnect / ...
NO_SERIAL_SUBCOMMANDS = {
    "devices", "kill-server", "start-server", "connect", "disconnect",
    "version", "help", "pair", "keygen", "reconnect",
}

# 匹配 adb 或 adb.exe，且可附带已存在的 -s <serial>
#   (?<![A-Za-z0-9_\"\'$])  前不能是单词字符，也不能是引号/$（避免误匹配字符串内或变量内的 adb）
#   adb(?:\.exe)?             adb 或 adb.exe
#   (?![A-Za-z0-9_])          后不能有单词字符
#   (?:\s+-s\s+\S+)?          可选的已存在 -s <serial>
ADB_RE = re.compile(
    r"(?<![A-Za-z0-9_\"\'$])adb(?:\.exe)?(?![A-Za-z0-9_])(?:\s+-s\s+\S+)?"
)
SCRCPY_RE = re.compile(r"(?<![A-Za-z0-9_])scrcpy(?![A-Za-z0-9_])")

# 用于抽取 adb 后的第一个子命令词（忽略末尾的常见分隔符 / 括号 / 花括号）
_SUB_RE = re.compile(r"[A-Za-z0-9_-]+")


def _adb_subcommand(cmd: str, match: re.Match) -> str:
    """根据 match 后面的第一个有效词，判断 adb 子命令是什么。"""
    after = cmd[match.end():].lstrip()
    if not after:
        return ""
    # 如果 adb 紧跟在引号后面，大概率位于字符串字面量内部，不按子命令处理
    if after[0] in ('"', "'"):
        return ""
    m = _SUB_RE.match(after)
    return m.group(0) if m else ""


def transform(cmd: str, serial: str) -> str:
    """
    把一条命令里的 **所有** adb / adb.exe / scrcpy 自动拼上 `-s <serial>`。

    - serial 为空 -> 原样返回（不需要指定设备）。
    - 全局子命令（devices / kill-server ...）-> 不注入 -s。
    - 已带 -s 的（如 adb -s 0612333…）-> 替换为所选设备序列号。
    - 非 adb / 非 scrcpy 命令 -> 原样返回，逻辑零改动。
    """
    if not serial:
        return cmd

    def _replace_adb(m: re.Match) -> str:
        token = m.group(0).split()[0]  # 'adb' 或 'adb.exe'
        sub = _adb_subcommand(cmd, m)
        if sub in NO_SERIAL_SUBCOMMANDS:
            return m.group(0)
        return f"{token} -s {serial}"

    new_cmd = ADB_RE.sub(_replace_adb, cmd)

    # scrcpy（投屏也支持按设备下发）
    if SCRCPY_RE.search(new_cmd) and not re.search(r"(?<![A-Za-z0-9_])scrcpy(?![A-Za-z0-9_]).*?-s\s+\S+", new_cmd):
        new_cmd = SCRCPY_RE.sub("scrcpy -s " + serial, new_cmd, count=1)

    return new_cmd


def needs_device(cmd_obj) -> bool:
    """
    该快捷指令是否包含「需要指定设备」的命令（adb/scrcpy 且会被注入 -s）。
    用于决定：点击时是按所选设备循环下发，还是只执行一次（PC 侧脚本）。
    """
    for e in cmd_obj.get("commands", []):
        if transform(e.get("command", ""), "__DUMMY__") != e.get("command", ""):
            return True
    return False


# ---------------------------------------------------------------------------
# 交互式 adb shell 自动合并
# ---------------------------------------------------------------------------
SHELL_INTERACTIVE_RE = re.compile(
    r"^adb(?:\.exe)?(?:\s+-s\s+\S+)?\s+shell\s*$",
    re.IGNORECASE,
)

# 遇到这些命令就结束 shell 命令合并（它们是 PC 侧命令或退出 shell）
# powershell / cmd / bash 也必须在内：它们会另起一个子 shell 抢走会话 stdin，
# 被合并进 `adb shell '...'` 之后既进不去也退不出（见 is_subshell_command）。
_PC_CMD_RE = re.compile(
    r"^(?:adb(?:\.exe)?|scrcpy|python|py|git|appium|code|exit"
    r"|powershell(?:\.exe)?|pwsh(?:\.exe)?|cmd(?:\.exe)?|bash|sh)\b",
    re.IGNORECASE,
)


def merge_adb_shell_commands(commands):
    """见 merge_adb_shell_commands_detailed，只返回合并后的命令列表。"""
    return [cmd for cmd, _ in merge_adb_shell_commands_detailed(commands)]


def merge_adb_shell_commands_detailed(commands):
    """
    把 `adb shell` / `adb -s xxx shell` 后面紧跟着的 shell 内部命令
    合并成一条非交互式命令，避免进入交互 shell 后卡住。

    例：
        ["adb shell", "cd /log/logcat", "ls"]
      -> [("adb shell 'cd /log/logcat; ls'", 2)]

    返回值与 merge_adb_shell_commands 相同，但每一项是
    (merged_cmd, end_index)：end_index 表示该条（合并后的）命令
    在原始 commands 列表中的结束下标（含），供调用方把命令间 delay
    挂到正确的原始命令上（合并块取最后一条的 delay）。

    如果后续遇到另一个 adb/scrcpy/python/git/appium/exit 命令，则结束合并。
    """
    out, buf = [], []

    def flush():
        if not buf:
            return
        if len(buf) == 1:
            out.append((buf[0][0], buf[0][1]))
        else:
            out.append((_build_shell(buf[0][0], [c[0] for c in buf[1:]]), buf[-1][1]))
        buf.clear()

    for idx, raw in enumerate(commands):
        c = raw.strip()
        if buf:
            if _PC_CMD_RE.match(c):
                flush()
                if SHELL_INTERACTIVE_RE.match(c):
                    buf.append((c, idx))
                else:
                    out.append((raw, idx))
            else:
                buf.append((c, idx))
        else:
            if SHELL_INTERACTIVE_RE.match(c):
                buf.append((c, idx))
            else:
                out.append((raw, idx))

    flush()
    return out


def _build_shell(shell_cmd: str, inner: list) -> str:
    """把 shell 入口命令 + 内部命令拼接成非交互式 adb shell 命令。"""
    if not inner:
        return shell_cmd
    # 用单引号包裹，避免 PowerShell 解析内部 ';'
    return shell_cmd + " '" + "; ".join(inner) + "'"


# ---------------------------------------------------------------------------
# 交互式子 shell 识别（powershell / cmd / bash / sh）
# ---------------------------------------------------------------------------
# `adb shell` 有 merge_adb_shell_commands 把紧跟着的几条合并成一条非交互命令，
# 但 powershell / cmd / bash / sh 没有这层保护。它们在持久会话里执行时会另起
# 一个进程**抢走同一个 stdin**：
#
#   1. 后面每条命令（连同调用方写入的结束标记）都被内层读走，外层收不到；
#   2. `exit` 那一行内层读走后直接退出，stdio 缓冲里预读的结束标记一并丢弃
#      ——外层从阻塞返回后再也等不到标记，`run()` 只能永远挂着；
#   3. 卡住的正是持有执行锁的 worker，于是界面表现为「整程序卡死、后续命令
#      全部排队点不动」。
#
# 因此这几类命令要和 `adb shell` 一样走「直通」：只写入、不写结束标记、不等。
_SUBSHELL_BASE = {"powershell", "pwsh", "cmd", "bash", "sh", "zsh"}

# 一次性执行开关：带这些参数就是「跑完即退」，不是交互式会话。
# `powershell -Command "..."` / `cmd /c dir` / `bash -c "ls"` 都属于此类。
_ONESHOT_FLAGS = {
    "powershell": ("-command", "-c", "-file", "-f", "-encodedcommand", "-e", "-ec"),
    "pwsh": ("-command", "-c", "-file", "-f", "-encodedcommand", "-e", "-ec"),
    "cmd": ("/c",),
    "bash": ("-c",),
    "sh": ("-c",),
    "zsh": ("-c",),
}


def _base_name(token: str) -> str:
    """从可执行文件路径里取小写程序名：`C:\\Windows\\powershell.exe` -> powershell。"""
    name = token.strip().strip('"\'')
    name = name.rsplit("\\", 1)[-1].rsplit("/", 1)[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


def _split_head(text: str):
    """拆出「程序名 + 其余参数」，支持带引号且含空格的路径。

    `"C:\\Program Files\\PowerShell\\7\\pwsh.exe" -NoProfile` 直接 split 会把
    路径切成两半，程序名认不出来 —— 用户从快捷方式属性里复制路径时很常见。
    """
    t = text.lstrip()
    if t[:1] in ('"', "'"):
        quote = t[0]
        end = t.find(quote, 1)
        if end > 0:
            return t[1:end], t[end + 1:].strip()
    head, _, tail = t.partition(" ")
    return head, tail.strip()


def is_subshell_command(cmd: str) -> bool:
    """该命令是否会「进入一个交互式子 shell」并抢走会话 stdin。

    只认「整条命令就是这一个程序」的形式：`cd /x && powershell` 这类复合命令
    不在此列（前半段是普通命令，后半段进子 shell 的概率也低，交给超时兜底）。

    >>> is_subshell_command("powershell")
    True
    >>> is_subshell_command("powershell -NoProfile -NoLogo")
    True
    >>> is_subshell_command('powershell -Command "Get-Date"')
    False
    >>> is_subshell_command("cmd /c dir")
    False
    >>> is_subshell_command("bash build.sh")
    False
    >>> is_subshell_command("adb root")
    False
    """
    text = (cmd or "").strip()
    if not text:
        return False
    # 复合命令 / 管道 / 重定向：不当交互式子 shell（见 docstring）
    if re.search(r"[;&|<>]", text):
        return False
    head, tail = _split_head(text)
    base = _base_name(head)
    if base not in _SUBSHELL_BASE:
        return False
    rest = [p.strip('"\'') for p in tail.split()]
    # 一次性执行开关 -> 跑完就退，不是交互会话
    for flag in _ONESHOT_FLAGS.get(base, ()):
        for arg in rest:
            low = arg.lower()
            if low == flag or low.startswith(flag + ":"):
                return False
    # 后面跟的是脚本文件（`sh build.sh`、`powershell setup.ps1`）：同样跑完就退
    if rest and not rest[0].startswith(("-", "/")):
        return False
    return True
