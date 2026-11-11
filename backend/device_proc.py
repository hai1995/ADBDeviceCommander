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


def device_pid(adb, serial, name, match=None):
    """取设备端同名进程的 PID：`pidof` 优先，退化 `ps -A` 逐行找。

    取不到（进程已退出 / 老 ROM 无 pidof 且 ps 输出异常）返回 None。

    match：命令行特征（如管道投屏独有的 `--output-format`）。**设备上可能同时
    有两条同名 screenrecord**（用户正在录屏的那条 + 投屏用的那条），`pidof` 只认
    进程名、取到的可能是别人的 PID；给了 match 就只认整行同时包含 name 与 match
    的那一条，绝不按名字取第一个。
    """
    if match is None:
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
    # 给了命令行特征时，先要「带完整命令行」的 ps：默认的 `ps -A` 只打印
    # 进程名（comm），两条 screenrecord（录屏那条 + 投屏那条）在 NAME 列里
    # 长得一模一样，据此区分不了谁是谁 —— 按它挑 PID 等于随机杀一个。
    # 老 ROM 的 ps 不支持 -o 时会把 usage 打到 stdout，解析不出东西就退回
    # 普通 `ps -A`（至少别把流程断在这里）。
    variants = (["-A", "-o", "PID,ARGS"], ["-A"]) if match is not None \
        else (["-A"],)
    for extra in variants:
        try:
            r = subprocess.run([adb, "-s", serial, "shell", "ps"] + extra,
                               **adb_kwargs(10))
        except Exception:
            continue
        for line in (r.stdout or "").splitlines():
            if name not in line:
                continue
            if match is not None and match not in line:
                continue
            pid = _pick_pid(line)
            if pid:
                return pid
    return None


def kill_device_process(adb, serial, name, wait=0.6, match=None,
                        fallback_name_kill=True):
    """尽力让设备端进程优雅退出（写回 moov / RIFF 收尾信息）。

    策略：按 PID `kill -INT`（比 pkill 通用，部分 ROM 无 pkill）→ 等 `wait` 秒收尾 →
    仍活着才补 `kill -TERM`；拿不到 PID 时同序退化为 `pkill`。

    match：按命令行特征精确定位（见 device_pid）。
    fallback_name_kill：精确匹配不到时，是否允许退回「按进程名 pkill」。按名字
    杀会连**同名的其它进程**一起杀掉 —— 用户正在录屏的那条 screenrecord 就是
    同名进程，一次投屏收尾就能把正常录屏弄断。因此调用方在「可能有别人的同名
    进程」时必须传 False：宁可不清理，也绝不误杀。传 False 且给了 match 时，
    仍会退化为 `pkill -f <match>`（按命令行特征，不是按名字），既清得掉自己的
    残留，也不会误伤同名进程。

    返回 True 表示走的是「按 PID 精准结束」分支（便于调用方/测试区分）。
    """
    pid = device_pid(adb, serial, name, match)
    if pid:
        _run([adb, "-s", serial, "shell", "kill", "-INT", pid])
        if wait:
            time.sleep(wait)          # 等它把收尾信息写完并自行退出
        # 只在确实还活着时补 -TERM；已退出就别再补刀（补了反而可能砍在收尾中途）
        if device_pid(adb, serial, name, match):
            _run([adb, "-s", serial, "shell", "kill", "-TERM", pid])
        return True
    if not fallback_name_kill:
        # 精确没找到、也不允许按名字兜底：设备上可能有另一条同名进程正被用户
        # 使用着，按名字一刀下去就是误杀。但若给了命令行特征，还能用
        # `pkill -f <特征>` 清理 —— 它同样只匹配「命令行含该特征」的那一条，
        # 不会波及同名的别的进程。没有特征就真的什么都不做：宁可留一个最多
        # 活到系统时长上限（默认 180s）的孤儿，也不误杀用户正在用的那条。
        if match:
            _run([adb, "-s", serial, "shell", "pkill", "-INT", "-f", match])
            if wait:
                time.sleep(wait)
            _run([adb, "-s", serial, "shell", "pkill", "-TERM", "-f", match])
        return False
    # 拿不到 PID（老 ROM 无 pidof / ps 输出异常）：退化为 pkill，顺序同上
    _run([adb, "-s", serial, "shell", "pkill", "-INT", name])
    if wait:
        time.sleep(wait)
    _run([adb, "-s", serial, "shell", "pkill", "-TERM", name])
    return False
