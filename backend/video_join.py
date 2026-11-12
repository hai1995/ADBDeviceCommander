"""
backend.video_join —— 把自动分段录出的多段 mp4 合并回一个完整 mp4。

为什么要有这一步
----------------
Android `screenrecord` 单段硬上限 180 秒，超长录制只能分段（见
screen_service 的自动续段）。分段是**实现手段**，不是用户要的结果：用户按
一次「开始录制」，期望拿到的是能从头拖到尾的一个视频。合并就是把实现细节
收回去 —— 保存目录里只留一个 mp4，播放器、剪辑软件、发给同事的压缩包都不必
再关心 `_p2` 该怎么接、顺序对不对。

怎么合
------
`ffmpeg -f concat -c copy`：直接搬 H.264 码流，不解码、不重编码。所以

  * 画质与各段完全一致（没有二次压缩损失）；
  * 耗时是磁盘 IO 量级（几分钟的素材一两秒完成），基本不吃 CPU。

代价只有一个：拼接点不补帧。段与段之间那约 1 秒（设备端重启 screenrecord
的耗时）在成片里表现为**画面跳变**，而不是静帧。这一点必须由界面如实告知，
否则用户会把跳变当成录制中断、以为中间漏录了内容。

产物可信性
----------
`ffmpeg` 退出码 0 **不代表**成片可用：各段的时间基 / 参数不一致时，它会安静
地产出一个只有第一段时长的文件。这里在合并完成后，按「各段时长之和」复核成片
时长，不符即判失败、删掉半成品，让调用方回退到「保留各段」——一个能播的 3 分钟
分段，比一个号称 8 分钟却只能播 3 分钟的成片有用得多。
"""
import os
import subprocess

from backend.audio_service import (
    _have_ffmpeg, _mp4_playable, _silent_remove, _video_duration)
from core.constants import adb_kwargs
from core.longpath import long_path, path_exists, path_getsize

# 单次合并的超时（秒）。`-c copy` 是纯 IO：57 分钟素材（20 段）在机械盘上
# 也就几十秒。给到 1800 是为了留足「磁盘被别的程序抢占」的余量，而不是
# 真的预期会跑这么久 —— 但绝不能不给上限：ffmpeg 卡在坏输入上会一直等，
# 而这段等待发生在收尾里，用户看到的是「点停止后程序没反应」。
MERGE_TIMEOUT_S = 1800


def _has_moov(path, scan=4 * 1024 * 1024):
    """MP4 是否含 moov 头（screenrecord 优雅收尾时写回，缺了就没有时长）。

    判据与 screen_service.VideoRecorder._mp4_has_moov 一致：只扫头/尾各 4MB
    （screenrecord 的 moov 在文件尾部），避免把几十上百 MB 的文件整读一遍。
    这里另写一份而不是跨模块调用，是为了让本模块能独立测试、独立复用。
    """
    try:
        lpath = long_path(path)
        size = os.path.getsize(lpath)
        if size < 64:
            return False
        with open(lpath, "rb") as f:
            if b"moov" in f.read(min(size, scan)):
                return True
            f.seek(max(0, size - scan))
            return b"moov" in f.read()
    except Exception:
        return False


def _concat_quote(path):
    """拼 concat 列表里的路径字面量。

    两处必须处理的细节：
      * 反斜杠统一换成正斜杠 —— Windows 路径 `C:\\a\\b.mp4` 里的 `\\a` 会被
        concat 解析器当成转义序列，路径直接对不上（表现为 ffmpeg 报找不到文件）；
      * 单引号按 concat 语法转义成 `'\\''`（先闭合、转义一个单引号、再打开），
        目录名里带 `'` 时（`D:\\张三's 素材`）不至于把整行截断。
    """
    p = os.path.abspath(path).replace("\\", "/")
    return p.replace("'", "'\\''")


def _total_duration(paths):
    """各段时长之和。返回 (总时长 or None, 第一个取不到时长的路径)。

    任何一段取不到时长就整场放弃这个校验（回 None）：拿残缺的合计值去比对
    成片，只会误判 —— 该报的没报，不该报的报了一堆。
    """
    total = 0.0
    for p in paths:
        try:
            v = float(_video_duration(p))
        except (TypeError, ValueError):
            return None, p
        if v <= 0:
            return None, p
        total += v
    return total, None


def _err_text(proc):
    """ffmpeg 的报错摘要（stderr 优先，取不到再看 stdout）。"""
    for attr in ("stderr", "stdout"):
        try:
            text = (getattr(proc, attr, "") or "").strip()
        except Exception:
            continue
        if text:
            # ffmpeg 的报错可能有很多行，只留最后几行（最后一行通常才是原因）
            return " ".join(text.splitlines()[-3:])[:300]
    return ""


def join_segments(paths, out_path, timeout=None):
    """把同一场录制的多段 mp4 合并为 out_path。

    返回 dict：
      * ok       是否成功（True 时 path 一定可用）
      * path     合并产物路径；只有一段可用时就是那一段本身（未新建文件）
      * used     真正并进成片的段（调用方可据此删除中间文件）
      * skipped  缺 moov 头、未并进成片的残片（**绝不能删**，那是用户仅有的素材）
      * reason   ok=False 时的人话原因

    调用方约定：`used` 里除 `path` 之外的段可以删；`skipped` 一律保留。
    """
    # 存在性与大小都要走长路径安全的版本：Windows 上 os.path.exists 碰到超过
    # 260 字符的路径**返回 False**（不报错），分段会被误判成「不存在」——
    # 于是这里直接判定「没有可合并的完整分段（都缺 moov 头）」，而真实原因
    # 是路径太长，用户完全无从推断。
    segs = [p for p in (paths or [])
            if p and path_exists(p) and path_getsize(p) > 0]
    used, skipped = [], []
    for p in segs:
        (used if _has_moov(p) else skipped).append(p)
    if not used:
        return {"ok": False, "path": None, "used": [], "skipped": skipped,
                "reason": "没有可合并的完整分段（都缺 moov 头，即都没正常收尾）"}
    if len(used) == 1:
        # 只剩一段可用：不启动 ffmpeg（copy 一遍纯属浪费磁盘），直接认它。
        # path 与 used[0] 相同 —— 调用方的「删中间段」逻辑天然不会删成品。
        return {"ok": True, "path": used[0], "used": used,
                "skipped": skipped, "reason": None}
    if not _have_ffmpeg():
        return {"ok": False, "path": None, "used": used, "skipped": skipped,
                "reason": "未检测到 ffmpeg（合并多段视频需要本机安装 ffmpeg 并加入 PATH）"}

    list_path = out_path + ".concat.txt"
    # 先写临时名再改名：ffmpeg 中途被杀 / 磁盘写满时会留下半个文件，
    # 若直接写正式名，那个半成品就会被后续的打包与提示当成成品收走。
    temp = os.path.splitext(out_path)[0] + ".merging.mp4"
    _silent_remove(temp)
    try:
        try:
            with open(long_path(list_path), "w", encoding="utf-8") as f:
                for p in used:
                    f.write("file '%s'\n" % _concat_quote(p))
        except Exception as e:
            return {"ok": False, "path": None, "used": used,
                    "skipped": skipped,
                    "reason": "无法写入合并清单：%s" % e}
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-f", "concat", "-safe", "0", "-i", list_path,
               "-c", "copy", temp]
        try:
            r = subprocess.run(cmd, **adb_kwargs(timeout or MERGE_TIMEOUT_S))
        except Exception as e:
            _silent_remove(temp)
            return {"ok": False, "path": None, "used": used,
                    "skipped": skipped, "reason": "ffmpeg 合并失败：%s" % e}
        if r.returncode != 0 or not path_exists(temp):
            why = _err_text(r)
            _silent_remove(temp)
            return {"ok": False, "path": None, "used": used, "skipped": skipped,
                    "reason": "ffmpeg 合并失败%s"
                              % ("（%s）" % why if why else "")}
        if not _mp4_playable(temp):
            _silent_remove(temp)
            return {"ok": False, "path": None, "used": used, "skipped": skipped,
                    "reason": "合并产物不是可播放的 MP4（缺 moov 头或没有有效时长）"}
        want, bad = _total_duration(used)
        if want:
            try:
                got = float(_video_duration(temp))
            except (TypeError, ValueError):
                got = 0.0
            # 容差取「2 秒」与「合计的 2%」中较大者：拼接点的时间戳取整、
            # 各段首尾帧对齐都会带来零点几秒的差异，卡太死会误判成功为失败。
            tol = max(2.0, want * 0.02)
            if abs(got - want) > tol:
                _silent_remove(temp)
                return {"ok": False, "path": None, "used": used,
                        "skipped": skipped,
                        "reason": "合并产物时长 %.1f 秒，各段合计 %.1f 秒，"
                                  "拼接结果不可信" % (got, want)}
        try:
            os.replace(long_path(temp), long_path(out_path))
        except Exception as e:
            _silent_remove(temp)
            return {"ok": False, "path": None, "used": used,
                    "skipped": skipped,
                    "reason": "合并产物无法写入 %s：%s" % (out_path, e)}
        return {"ok": True, "path": out_path, "used": used,
                "skipped": skipped, "reason": None}
    finally:
        # 清单文件是过程产物，成功失败都不该留在用户的保存目录里。
        _silent_remove(list_path)
