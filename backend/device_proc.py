# -*- coding: utf-8 -*-
"""
backend.device_proc —— 设备端后台进程的收尾（录屏 screenrecord / 录音 tinycap 共用）。

为什么不能简单地 kill：
  `screenrecord` 与 `tinycap` 都只在收到 **SIGINT**（终端里的 Ctrl-C）时才「优雅收尾」
  并写回收尾信息——MP4 要在文件尾部写 `moov` 索引，WAV 要把 `RIFF` 头的数据长度补齐。
  直接发 SIGTERM 会立刻终止进程，留下没有时长、播放不了的残文件。

为什么发完 SIGINT 不能马上补 SIGTERM：
  收尾是「收到信号后」才开始做的动作。若 -INT 与 -TERM 背靠背发出去，进程很可能在
  写 `moov` / 补 WAV 头的中途被 -TERM 打死——等于白优雅了一次，产物依旧是坏的。
  因此统一为：**-INT → 等一会儿（让收尾跑完）→ 确认还活着才补 -TERM**。

另外：本地 adb 客户端退出不代表设备端进程也退了，必须显式收尾，否则孤儿进程会继续
录写 /sdcard、占用音频输入（麦克风）并耗电。
"""
import subprocess
import time

from core.constants import adb_kwargs


def _run(cmd, timeout=10):
    """执行一条 adb 命令，失败静默——收尾动作要尽力而为，不能反过来打断主流程。"""
    try:
        subprocess.run(cmd, **adb_kwargs(timeout))
    except Exception:
        pass


def _pick_pid(line):
    """从 `ps` 的一行里挑出 PID（挑不到返回 None）。

    设备端 `ps -A` 的列布局不唯一：
      * POSIX / toybox：`USER PID PPID ... NAME`（用户名列通常是 u0_a123 / root
        这样的名字，**但部分 ROM 会直接打印数字 UID**）；
      * busybox：`PID USER TIME COMMAND`（PID 在第一列）。
    只取「第一个数字列」的话，numeric-UID 的 ROM 会把 UID 当成 PID 交给 kill ——
    那是另一个进程，可能误伤系统进程。这里按布局判定：第一列是数字且第二列不是
    数字 -> busybox（PID 在第一列）；其余情况一律从第二列起找，绝不把第一列当 PID。
    """
    toks = line.split()
    if len(toks) >= 2 and toks[0].isdigit() and not toks[1].isdigit():
        return toks[0]
    return next((t for t in toks[1:] if t.isdigit()), None)


def device_pid(adb, serial, name):
    """取设备端同名进程的 PID：`pidof` 优先，退化 `ps -A` 逐行找。

    取不到（进程已退出 / 老 ROM 无 pidof 且 ps 输出异常）返回 None。
    """
    try:
        r = subprocess.run([adb, "-s", serial, "shell", "pidof", name],
                           **adb_kwargs(10))
        # 只认纯数字：adb shell 会把设备端的报错并进 **stdout**
        # （`/system/bin/sh: pidof: not found`），按空白切分后第一个 token 是
        # "pidof:"。拿它去 kill 杀不掉任何东西，更糟的是 kill_device_process
        # 会据此认为「已按 PID 精准结束」，连 pkill 兜底都不走 —— 设备端
        # screenrecord / tinycap 就成了孤儿，继续写卡、继续占着麦克风。
        pids = [t for t in (r.stdout or "").split() if t.isdigit()]
        if pids:
            return pids[0]
    except Exception:
        pass
    try:
        r = subprocess.run([adb, "-s", serial, "shell", "ps", "-A"],
                           **adb_kwargs(10))
        for line in (r.stdout or "").splitlines():
            if name in line:
                pid = _pick_pid(line)
                if pid:
                    return pid
    except Exception:
        pass
    return None


def kill_device_process(adb, serial, name, wait=0.6):
    """尽力让设备端进程优雅退出（写回 moov / RIFF 收尾信息）。

    策略：按 PID `kill -INT`（比 pkill 通用，部分 ROM 无 pkill）→ 等 `wait` 秒收尾 →
    仍活着才补 `kill -TERM`；拿不到 PID 时同序退化为 `pkill`。

    返回 True 表示走的是「按 PID 精准结束」分支（便于调用方/测试区分）。
    """
    pid = device_pid(adb, serial, name)
    if pid:
        _run([adb, "-s", serial, "shell", "kill", "-INT", pid])
        if wait:
            time.sleep(wait)          # 等它把收尾信息写完并自行退出
        # 只在确实还活着时补 -TERM；已退出就别再补刀（补了反而可能砍在收尾中途）
        if device_pid(adb, serial, name):
            _run([adb, "-s", serial, "shell", "kill", "-TERM", pid])
        return True
    # 拿不到 PID（老 ROM 无 pidof / ps 输出异常）：退化为 pkill，顺序同上
    _run([adb, "-s", serial, "shell", "pkill", "-INT", name])
    if wait:
        time.sleep(wait)
    _run([adb, "-s", serial, "shell", "pkill", "-TERM", name])
    return False
