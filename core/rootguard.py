"""core.rootguard —— `adb root` / `adb unroot` 的执行保护（判定 + 状态查询）。

为什么需要专门保护这一条命令
--------------------------
`adb root` / `adb unroot` 会**重启设备端 adbd**：所有经它的连接全部断开，
由它拉起的设备端进程（screenrecord / tinycap）会被杀掉——录屏视频因此缺
moov 头、播不了，logcat 监控 / 抓取、文件操作一并中断。而使用上它极其
「无害」：用户只是想切个 root 状态，很难联想到会断掉正在进行的录屏
（使用说明「录屏被中断」条记的就是这个坑）。

更常见的负收益场景是**重复切换**：设备已经 root，再执行一次 `adb root`
除了重启 adbd 没有任何效果——纯粹白断一次连接。

因此下发 root 切换前先问两个问题（见 backend.controller._skip_root_switch）：
  1. 设备是否已在目标状态？是 → 跳过（无谓重启，零收益）；
  2. 状态确实要变、但该设备有进行中的任务（录屏 / 设备音频 / logcat）？
     是 → 跳过并说明（避免静默数据丢失；先停止任务再切换）。

判定与查询都集中在本模块（无 UI 依赖），便于单测覆盖各种命令写法。
"""
import re
import subprocess

from core.constants import adb_kwargs

# root 状态切换命令：adb / adb.exe，可选已注入的 -s <serial>，后跟 root|unroot。
# 用 search 而非 match：复合命令（`adb root && adb shell xx`、`adb root; adb remount`）
# 同样会随 adbd 重启受影响，且无法只跳过其中一段，故一并按「root 切换」处理。
# 前边界排除单词字符与引号 / $：`adb roots`、`myadb root` 不匹配（词边界），
# 引号内的字样（`git commit -m "adb root 修复"`、`echo "adb root"`）也不算——与
# adb_inject.ADB_RE 的防护保持一致，避免把「提到 root 的命令」当成「切换 root」。
_ROOT_SWITCH_RE = re.compile(
    r"(?<![A-Za-z0-9_\"'$])adb(?:\.exe)?(?:\s+-s\s+\S+)?\s+(root|unroot)\b",
    re.IGNORECASE,
)


def root_intent(cmd):
    """命令是否包含 root 状态切换：返回 'root' / 'unroot' / None。"""
    m = _ROOT_SWITCH_RE.search(cmd or "")
    return m.group(1).lower() if m else None


def root_state(adb, serial, timeout=8):
    """设备当前 root 状态：True / False / **None（无法确认）**。

    判定：`adb shell id -u` 输出 0 即 root（shell 用户是 2000 之类）；
    个别 ROM 的 toybox 没有 id 时退化为 `whoami` 含 root。

    None 与 False 必须分开：探测失败（adb 瞬断 / 设备忙 / 两个命令都没有）
    **不等于**「设备没有 root」。调用方把 None 当 False 时，`adb unroot` 会被
    判成「已在目标状态」而跳过 —— 用户明明 root 了却 unroot 不掉，界面还给
    一句「设备已未 root」，方向完全相反。无法确认时应放行指令（并说明），
    由用户自己决定要不要切换。
    """
    for args in (["id", "-u"], ["whoami"]):
        try:
            r = subprocess.run([adb, "-s", serial, "shell"] + args,
                               **adb_kwargs(timeout))
        except Exception:
            return None
        out = (r.stdout or "").strip()
        if r.returncode != 0 or not out:
            continue
        first = out.splitlines()[0].strip().lower()
        if args[0] == "id":
            # 输出非空但没有数字段（个别 ROM 的 id 被替换成别名）也算认不出
            return first.split()[0] == "0" if first else False
        return "root" in first
    return None


def device_is_root(adb, serial, timeout=8):
    """设备当前是否已处于 root 状态（布尔版，保留给旧调用方）。

    探测失败按 False 处理。**需要区分「确认未 root」与「无法确认」的调用方
    请直接用 `root_state`** —— 布尔版会把两者混成一个 False。
    """
    return bool(root_state(adb, serial, timeout))
