"""
backend.mf_capture_service —— 同源录屏编排（adb 裸 H264 流 + native SinkWriter）
================================================================================
把两台设备各自的一条 adb `exec-out screenrecord --output-format=h264 -` 流，
接到 native 的一个 `adc_session`（SinkWriter，H264+AAC 同源写入）里；麦克风
由 native 内部 WASAPI 采集并广播给所有会话。直接产出带声 MP4，无 ffmpeg
后处理。

职责边界：
  * 本模块只管"视频流 → native session"这条数据通路与会话生命周期；
  * 设备选择 / overlay / logcat / 打包 / 状态文案仍由 controller 负责；
  * ffmpeg 合成代码原样保留作兜底，本模块不修改、不优化它。

沙箱/单测（Linux、无 dll）：`MFCaptureService(available=False)` 走纯 Python
替身，记录调用序列供断言；真机由 backend.mf_native.MFNative 驱动。
"""
import contextlib
import os
import shutil
import subprocess
import tempfile
import threading

from core.constants import no_window_flags, safe_name, unique_path
from core.longpath import long_path, path_isfile
from core.tmpfiles import MF_WORKDIR_PREFIX

# 首帧等待：screenrecord 秒退（ROM 不支持 --output-format=h264）要能快速报错。
FIRST_DATA_TIMEOUT_S = 6.0
# stdout 单次读上限（64KB）：H264 ES 无内建时间戳，native 按 sample 到达时刻打
# QPC 时间戳。用 read1 只按当前可用量返回（稀疏流常常只有几 KB），此值只是上限；
# 若上限取得过大（如 1MB），突发大块会让多帧挤到同一时刻、时间轴压缩。
# 64KB 兼顾系统调用次数与时间精度。
READ_CHUNK = 64 * 1024
# 音频队列排空周期（秒）：远小于 native 的 5s 队列上限，留出充足余量。
# 音频写入因此不依赖 video sample 到达——视频流稀疏/中断时音频仍能持续写盘。
AUDIO_DRAIN_INTERVAL_S = 0.2
# [收尾慢根治 v21] stop() 等读线程退出的预算：须覆盖一次最坏 session_rotate
# （native 切段 120s 独立超时）+ 尾部几帧 write_video 的排队，留 ~10s 余量。
# 正常切段只需几秒，这个上界仅在 worker 真挂死的病态场景才会用满，避免界面
# 无限期卡住；届时读线程是 daemon，进程退出不受阻。
READ_DONE_BUDGET_S = 130.0
# [真失败根治 v28] finalize 超时后，投递屏障等 finalize task 真正跑完并落盘的
# 预算。必须 >= finalize 自身最坏耗时（mf_native.FINALIZE_CALL_TIMEOUT_S=60s，
# 含 SinkWriter::Finalize 编码器 flush + 慢盘/EDR 下 MoveFile 改名），否则屏障
# 先于 finalize 超时 → 捞回时成片还是 .tmp.mp4（被排除）→ 随后 worker.stop()
# 把队列里未跑完的 finalize task 丢弃 → 成片永远烂在 TEMP。真机 12min 录制
# 收尾 162s 却无文件即此病根。留 30s 余量取 90s。
BARRIER_RECOVER_TIMEOUT_S = 90.0
# [长录制续流根治] screenrecord 有 180s 硬上限（core.constants.REC_MAX_S），
# 到点自行退出、视频流断。投屏路径 mirror_service 早已实现续流，但同源录制
# 的 _read_loop 读到空就 break —— 于是 3min+ 录制后面全部丢画面、切段由
# write_video 驱动也随之中止（只剩 p1）。这里给续流次数设上限（约 20×170s
# ≈ 57min，与 REC_MAX_SEGMENTS 对齐），防设备端反复秒退时无限空转。
MF_RESTART_MAX = 20
# [v25 单文件完整录制] native 每 170s 的墙钟切段（ADC_ROTATE_PENDING）初衷是
# 配合旧架构「screenrecord 180s 退出即断流」——每段对应一次进程生命周期。v24
# 续流后视频流全程连续、同一个 SinkWriter 可持续写，切段反而把一条连续流切成
# p1/p2 多文件；而 MF 路径从不合并（ffmpeg 已不随包发布），完成提示只能显示
# 「N 段视频，未能合并」。默认忽略切段请求、整场写单个 writer，finalize 自然
# 产出 1 个从头到尾的带声 MP4。置 False 可恢复分段（诊断/回退用）。
MF_SINGLE_FILE = True
# [修复-长录制收尾·v17] 排空连续失败次数只作诊断统计（写入 stats），不再是
# 停止排空的阈值。旧实现达阈值就 break + 记 _error，长录制下把 worker 繁忙
# 造成的偶发 drain 超时误判成 worker 死亡，永久关闭排空并误报收尾失败。
# 现在超时只丢本轮、下个 tick 继续；连续失败数仅用于真机观测 worker 健康度。
# 名义帧率（H264 ES 无时间戳，native 用它估 duration；真机核对）。
FPS_NUM, FPS_DEN = 30, 1
# 默认麦克风目标格式 (rate, bits, channels)，与 native adc_mic_start /
# adc_mic_format / adc_session_create 的参数顺序一致。native 回读实际 mix
# format 后以实际值为准。
DEFAULT_MIC = (48000, 16, 2)


def h264_cmd(adb, serial, size=None, bitrate_mbps=8):
    """构造裸 H264 流命令（与 mirror_service 的投屏命令同源，只去掉播放器）。"""
    cmd = [adb, "-s", serial, "exec-out", "screenrecord", "--output-format=h264"]
    if size:
        cmd += ["--size", size]
    cmd += ["--bit-rate", str(int(bitrate_mbps) * 1000000), "-"]
    return cmd


class MFCaptureSession:
    """单设备的同源录制会话：一个 adb 进程 + 一个 native session。"""

    def __init__(self, native, serial, save_dir, stem, width, height,
                 mic_fmt=DEFAULT_MIC, adb="adb", size=None, work_dir=None):
        self.native = native
        self.serial = serial
        self.save_dir = save_dir
        # [EDR 误报缓解] native 的工作目录：.tmp.mp4 的写入、Finalize 改名、
        # 取消删除都发生在这里。默认落系统 TEMP（EDR 对安装器/进程在 TEMP 的
        # 批量读写天然高容忍），只在 stop 成功后把成品 copy 回 save_dir。
        # work_dir=None 时退回 save_dir（保留旧行为，便于兼容/调试）。
        self.work_dir = work_dir
        self.stem = stem
        # [串味根治 v26] 仅多设备共享 work_dir 时才按 stem 严格过滤兜底捞回。
        # 单设备（含测试替身）work_dir 里只有本会话产物，保持原行为不过滤。
        self._strict_recover = False
        self.width = int(width)
        self.height = int(height)
        self.mic_fmt = mic_fmt
        self.adb = adb
        self.size = size
        self._proc = None
        self._handle = 0
        self._stop = threading.Event()
        self._read_thread = None
        self._err_thread = None
        # [修复-真机 overflow] 音频排空定时器：独立于视频帧，周期把 native 音频
        # 队列写入 SinkWriter，避免视频流稀疏时队列积压 5s 而 overflow。
        self._drain_thread = None
        self._drain_stop = threading.Event()
        self._first_data = threading.Event()
        # [收尾慢根治 v21] 读线程"真正跑完"的信号：_read_loop 的 finally 末尾置位。
        # stop() 据此等待，而不是盲 join 固定秒数——读线程可能正阻塞在 120s 的
        # session_rotate 里，等它退出才能保证它投递的所有 write_video/rotate 都已
        # 排进 worker 队列、位于 finalize 之前，杜绝 write_video 被 finalize 顶超时。
        self._read_done = threading.Event()
        self._error = ""
        # stderr 只作诊断信息，单独存放。它绝不能写进 _error：_error 是主流程
        # 错误通道，正常 stop 时 terminate 进程会让 stderr 读到 EOF/退出日志，
        # 若写进 _error 会（a）覆盖读线程记录的首个真实错误（overflow/WriteSample
        # 失败），（b）即使录制完全成功也可能在收尾时报一句无关的"警告"。
        self._stderr_tail = ""
        self._lock = threading.Lock()
        self._stats = {"bytes": 0, "first_ok": False}
        self._tmp_first = ""

    def _spawn_proc(self):
        """拉起一条 adb exec-out screenrecord H264 进程 + stderr 消费者。

        [长录制续流根治] 抽成独立方法，供 start() 首次启动与 _read_loop 续流
        复用。H264 是二进制流，stdout 必须保持 bytes 模式（不能用 adb_popen_
        kwargs 的 text=True，会按 UTF-8 解码损坏码流）；stderr 是文本，由
        _drain_stderr 按 utf-8/replace 解码，且必须有消费者，否则 64KB 写满
        会把设备端阻塞。每次调用都新建 stderr 线程，绑定新进程的 stderr。
        """
        proc = subprocess.Popen(
            h264_cmd(self.adb, self.serial, self.size),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL, creationflags=no_window_flags())
        self._proc = proc
        self._err_thread = threading.Thread(
            target=self._drain_stderr, daemon=True,
            name=f"mf-h264-err-{safe_name(self.serial)}")
        self._err_thread.start()
        return proc

    # ---- 启动 ----------------------------------------------------------
    def start(self):
        """返回 (ok, 错误原因)。同步等首字节，秒退立即报错。"""
        self._read_done.clear()   # 防御会话复用：每次 start 重置读线程完成信号
        arate, abits, ach = self.mic_fmt
        # [EDR 误报缓解] native 只在 work_dir 里写 .tmp.mp4 / 改名 / 删除，
        # 用户保存目录不再出现"高熵半成品写入 → 改名 → 批量删"的勒索特征信号。
        native_dir = self.work_dir or self.save_dir
        with self._lock:
            self._handle, self._tmp_first = self.native.session_create(
                native_dir, self.stem, self.width, self.height,
                FPS_NUM, FPS_DEN, arate, abits, ach)
        try:
            proc = self._spawn_proc()
        except Exception as ex:  # noqa: BLE001  启动失败转成可读原因
            self._teardown_native(discard=True)
            return False, f"无法启动 screenrecord H264 流：{ex}"
        self._read_thread = threading.Thread(
            target=self._read_loop, daemon=True,
            name=f"mf-h264-read-{safe_name(self.serial)}")
        self._read_thread.start()
        if not self._first_data.wait(timeout=FIRST_DATA_TIMEOUT_S):
            ok = proc.poll() is None
            self._error = self._error or (
                f"screenrecord 未在 {FIRST_DATA_TIMEOUT_S:.0f}s 内输出 H264 数据"
                f"（退出码 {proc.poll()}；请确认设备屏幕已点亮且未锁屏，"
                "部分车机 ROM 不支持 --output-format=h264）")
            # stderr 只在启动失败诊断时拼进原因；正常路径绝不把它当错误。
            if self._stderr_tail and self._stderr_tail not in self._error:
                self._error = f"{self._error}（{self._stderr_tail}）"
            if not ok:
                self._stop.set()
            return False, self._error
        if self._error:
            return False, self._error
        # [修复-真机 overflow] 启动音频排空定时器：每 200ms 经 worker 线程主动
        # 排空 native 音频队列。这样即使 screenrecord 的 H264 流稀疏/中断、
        # write_video 几乎不被调用，音频也持续写入 SinkWriter，不会积压溢出。
        self._drain_stop.clear()
        self._drain_thread = threading.Thread(
            target=self._drain_loop, daemon=True,
            name=f"mf-audio-drain-{safe_name(self.serial)}")
        self._drain_thread.start()
        return True, ""

    def _drain_loop(self):
        """周期性排空音频队列（经 worker 线程）。尽力而为，超时绝不致命。

        [修复-长录制收尾慢/排空失败·v17] 三处缺陷一并根治：
          1) 旧实现一次超时就 break，把高负载下 write_video 挤占 worker 造成的
             drain 排队误判为 worker 死亡，永久关闭排空 → 剩余录制音频无人写 →
             native 队列 overflow 丢音频；
          2) v14 改成"连续 3 次超时才 break 并记 _error"，3 分钟长录制仍会触发，
             收尾把这条误报当失败展示给用户（文件其实已成功发布）；
          3) 超时 task 在 worker 队列里变僵尸、堆积拖慢收尾 finalize。

        现策略：drain 是尽力维护调用——超时只丢本轮（超时 task 已由
        MFWorker.call(cancelable=True) 标记跳过、不留僵尸），下一个 tick 继续重试，
        成功即清零；绝不写 _error、绝不永久停排空。真正能判定失败的是 finalize：
        worker 若真挂死，finalize 调用自身会超时并上报可读错误，无需这里抢判。
        这样既保证整段音频持续排空（不 overflow），又消除收尾的假失败提示。
        """
        while not self._drain_stop.wait(AUDIO_DRAIN_INTERVAL_S):
            h = self._handle
            if not h:
                continue
            try:
                self.native.session_drain_audio(h)
                self._stats["drain_fail_streak"] = 0   # 成功即清零
            except Exception:  # noqa: BLE001  尽力调用：超时只丢本轮，继续重试
                self._stats["drain_fail_streak"] = self._stats.get("drain_fail_streak", 0) + 1

    def _read_loop(self):
        nal_buf = __import__("backend.mf_native", fromlist=["NalBuffer"]).NalBuffer()
        restarts = 0
        try:
            # [长录制续流根治] 外层循环：screenrecord 有 180s 硬上限，到点进程
            # 自行退出、stdout EOF。旧实现读到空就 break，视频流断后再无
            # write_video → 切段停止 → 只留下第一段（真机录 5min/8min 只剩 p1，
            # 收尾还拖满 _join_threads 的 130s 预算）。与投屏 mirror_service.
            # _feed_loop 对齐：检测到进程确实退出且未 stop，就重拉一条
            # screenrecord 继续喂**同一个** native session（handle 不变、
            # SinkWriter 不重建），画面短暂卡一下即恢复，切段/音频都不受影响。
            while not self._stop.is_set():
                proc = self._proc
                stream = proc.stdout if proc is not None else None
                if stream is None:
                    break
                try:
                    while not self._stop.is_set():
                        # [修复-首帧超时] 必须用 read1，绝不能退回 read：
                        #   BufferedReader.read(64KB) 在管道上会阻塞到「凑满 64KB
                        #   或 EOF」。车机静止/低码率画面下 H264 可能只有几 KB/s，
                        #   read 会憋住首帧导致 start 误报超时；read1 有多少读多少。
                        #   投屏 mirror_service._feed_loop 同样用 read1，对齐。
                        chunk = stream.read1(READ_CHUNK)
                        if not chunk:
                            break
                        if not self._first_data.is_set():
                            self._first_data.set()
                        # 按 NAL 边界切块，避免跨块 NAL 被 native 截断。
                        for nal in nal_buf.feed(chunk):
                            if self._stop.is_set():
                                break
                            # [修复] native 写入失败（overflow / WriteSample 失败）
                            # 必须记录，不能被 suppress 吞成"假成功"。首错为准。
                            try:
                                need_rotate = self.native.session_write_video(
                                    self._handle, nal)
                                self._stats["bytes"] += len(nal)
                                # [收尾慢根治 v20] native 到 170s 只回"请求"信号，
                                # 重量切段用独立 120s 超时显式执行。老 DLL 不返回
                                # True（内部同步切段），此分支自动跳过，向后兼容。
                                #
                                # [v25 单文件完整录制] 默认忽略该请求：native 的
                                # should_rotate() 在 rotate_pending_ 置位后恒返回
                                # false，所以忽略这一次后整场不再请求切段，后续帧
                                # 继续写同一个 SinkWriter。时间戳基准（视频从 0
                                # 累加、音频相对 seg_start_hns_）在单段下天然对齐，
                                # finalize 直接产出 1 个完整带声 MP4，无需 ffmpeg。
                                # 只有显式关闭 MF_SINGLE_FILE（诊断/回退）才切段。
                                if need_rotate:
                                    if MF_SINGLE_FILE:
                                        self._stats["rotate_skipped"] = \
                                            self._stats.get("rotate_skipped", 0) + 1
                                    else:
                                        self.native.session_rotate(self._handle)
                                        self._stats["rotations"] = \
                                            self._stats.get("rotations", 0) + 1
                            except Exception as ex:  # noqa: BLE001
                                # [收尾慢根治 v21] 真 native 错误才上报；"MF worker
                                # 调用超时"是单 worker 被重量操作挤占的排队等待，
                                # task 非 cancelable、最终仍执行、数据不丢，只记统计。
                                if "MF worker 调用超时" in str(ex):
                                    self._stats["write_timeout_streak"] = \
                                        self._stats.get("write_timeout_streak", 0) + 1
                                else:
                                    self._error = self._error or f"写入 H264 流失败：{ex}"
                                    self._stop.set()
                                    break
                finally:
                    with contextlib.suppress(Exception):
                        stream.close()

                if self._stop.is_set():
                    break

                # 流读到 EOF。先 wait 给本地 adb 客户端一点时间退出（设备端
                # screenrecord 先退、adb exec-out 后退，mirror 留 2s 余量同理）；
                # 之后 poll() 非 None 才判定"进程确实退出→续流"。测试替身
                # FakeProc.poll() 恒 None、wait 立即返回，故不续流，保持既有
                # 测试"读空即静默结束"的行为不变。
                with contextlib.suppress(Exception):
                    proc.wait(timeout=2)
                if proc.poll() is None:
                    # 进程仍活着却 EOF：非正常到期的异常中断，按旧行为退出。
                    break

                restarts += 1
                if restarts > MF_RESTART_MAX:
                    self._error = self._error or (
                        f"screenrecord 已续流 {MF_RESTART_MAX} 次后仍中断，停止录制")
                    break
                # [竞态根治 v26] stop 可能恰在上面 proc.wait(timeout=2) 期间置位：
                # 285 行的 stop 检查在 wait 之前，wait 返回后到 spawn 之间没有检查。
                # 若此时继续续流，新进程会在 stop 的 _close_proc 之后才拉起，成为
                # 无人 terminate 的孤儿——设备屏幕被占、下次录制起不来。spawn 前
                # 先检查一次，spawn 后再复查（见下）。
                if self._stop.is_set():
                    break
                # 清理旧进程残留句柄（进程已退出，只 close 流 + 回收 wait）。
                for name in ("stdout", "stderr"):
                    with contextlib.suppress(Exception):
                        s = getattr(proc, name, None)
                        if s is not None:
                            s.close()
                with contextlib.suppress(Exception):
                    proc.wait(timeout=2)
                # 重拉新进程，继续喂同一个 native session（handle 不变）。
                try:
                    new_proc = self._spawn_proc()
                    self._stats["restarts"] = restarts
                    # [竞态根治 v26] spawn 期间 stop 若恰好置位，_close_proc 可能
                    # 已先于 new_proc 赋值执行（terminate 旧进程并把 _proc 置空），
                    # 那新进程就无人关闭。这里复查：若 _proc 仍指向刚拉起的进程，
                    # 说明 _close_proc 没覆盖到它，主动关闭；若已被置空/替换，说明
                    # stop 已处理，不重复。两种情况都不留孤儿进程。
                    if self._stop.is_set():
                        with self._lock:
                            current = self._proc
                        if current is new_proc:
                            self._close_proc()
                        break
                    # [续流残段根治 v26] nal_buf 只吐"遇到下一起始码"的完整 NAL，
                    # 上一段进程 EOF 时末尾那条仍留在缓冲里。若直接让新进程的
                    # 数据续写进去，旧残段会与新进程首个 NAL 粘成畸形帧（实测
                    # 残段 65aabbcc 粘到新 SPS 前）。正确做法：先把旧残段作为本段
                    # 尾帧 flush 写入 native（不丢帧），再重建缓冲让新进程从关键帧
                    # 干净开始。仅在没有错误时才写尾帧，与正常收尾语义一致。
                    if not self._error:
                        for tail in nal_buf.flush():
                            with contextlib.suppress(Exception):
                                self.native.session_write_video(self._handle, tail)
                                self._stats["bytes"] += len(tail)
                    nal_buf = __import__(
                        "backend.mf_native", fromlist=["NalBuffer"]).NalBuffer()
                except Exception as ex:  # noqa: BLE001
                    self._error = self._error or f"screenrecord 续流失败：{ex}"
                    break
        except Exception as ex:  # noqa: BLE001  读线程异常记录原因，不吞
            self._error = self._error or f"读取 H264 流失败：{ex}"
        finally:
            # 正常 stop 时也要把缓冲里的最后一帧写入（[修复]：原实现用
            # `if not self._stop.is_set()` 挡住，而 stop() 会先置该标志，导致
            # 末帧永久丢失）。仅在记录过错误时才跳过尾部写入。
            if not self._error:
                for tail in nal_buf.flush():
                    try:
                        self.native.session_write_video(self._handle, tail)
                        self._stats["bytes"] += len(tail)
                    except Exception as ex:  # noqa: BLE001
                        # [收尾根治 v27] 与主循环(v21)口径一致："MF worker 调用超时"
                        # 是单 worker 被残留 drain / 重量操作挤占的排队等待；该
                        # write_video task 非 cancelable、仍在队列里最终执行，尾帧
                        # 数据不丢，finalize（FIFO 排在其后）能拿到完整数据。
                        # [结论更正 v28] 上一轮曾据此断言"成片已保存、只是假警告"——
                        # 这是误判：真机 12min 录制 finalize 同样超时且屏障(30s)先于
                        # finalize(60s)放弃，成片烂在 TEMP 真的丢了。尾帧超时本身仍
                        # 不应写成致命（否则掩盖真正失败），但"成片丢失"由 stop() 的
                        # 未捞回成片错误据实上报，绝不静默成功。真 native 错误仍上报。
                        if "MF worker 调用超时" in str(ex):
                            self._stats["write_timeout_streak"] = \
                                self._stats.get("write_timeout_streak", 0) + 1
                        else:
                            self._error = self._error or f"写入 H264 尾帧失败：{ex}"
                            break
            self._first_data.set()   # 即使失败也唤醒 wait，避免等满超时
            # [收尾慢根治 v21] 通知 stop()：本读线程的所有 native 调用（含切段
            # rotate 与上面的尾刷 write_video）都已投递完毕。stop() 等此信号后再
            # finalize，保证 worker 队列顺序为 [...write_video, rotate, finalize]，
            # 而非 [...finalize, 迟到的 write_video]（后者会顶过 30s 超时）。
            self._read_done.set()

    def _drain_stderr(self):
        stream = self._proc.stderr if self._proc is not None else None
        if stream is None:
            return
        try:
            tail = b""
            while not self._stop.is_set():
                line = stream.readline()
                if not line:
                    break
                tail = (tail + line)[-2048:]
            if tail:
                self._stderr_tail = tail.decode("utf-8", "replace").strip()[-300:]
        except Exception:  # noqa: BLE001, S110  后台读 stderr，失败不影响主流程
            pass

    # ---- 停止 / 取消 ---------------------------------------------------
    def stop(self):
        """正常收尾：停 adb → 等读线程 → native finalize → 返回发布路径列表。"""
        self._stop.set()
        self._stop_drain()          # 先停音频排空定时器，再 finalize
        # [收尾根治 v27] 停定时器后立刻撤销 worker 队列里尚未执行的 drain。
        # 读线程 finally 的尾帧 write_video 在 _join_threads() 期间投递；旧实现
        # 把撤销 drain 放在 _join_threads() 之后、finalize 之前，尾帧 write_video
        # 会先排在残留 drain 后面被顶过 30s → 超时误报 + 收尾拖慢。此处提前撤销，
        # 让尾帧与 finalize 都不被挤占。定时器已停、不会再投新 drain；音频完整性
        # 仍由 finalize 内部的 drain_audio() 有界排空保证，撤销不丢音频。
        drop = getattr(self.native, "drop_queued_drains", None)
        if drop is not None:
            with contextlib.suppress(Exception):
                drop()
        self._close_proc()
        self._join_threads()
        if not self._handle:
            return [], self._error or "会话未创建"
        with self._lock:
            with contextlib.suppress(Exception):
                self.native.session_mark_mic_stop(self._handle)
        paths = []
        err = self._error
        # [收尾根治 v22] finalize 之前，撤销 worker 队列里尚未执行的音频 drain。
        # 长录制切段（do_rotate，重量 Finalize+MoveFile+重建 writer，数十秒）占住
        # 单 worker 期间，200ms 定时器持续投递 drain；它们只在各自 call() 超时
        # （10s）后才被标 cancelled，切段结束时队尾仍有一批会真正执行的 drain
        # 排在 finalize 前面，把 finalize 顶过 60s 超时——这是超时点第 5 次转移
        # （drain→write15s→finalize60s→write30s→finalize60s）的真正病根：重量操作
        # 与高频 drain 共用单 FIFO 队列。drain 是尽力维护调用，音频完整性由
        # finalize 内部的 drain_audio() 有界排空保证，撤销排队 drain 不丢音频。
        drop = getattr(self.native, "drop_queued_drains", None)
        if drop is not None:
            with contextlib.suppress(Exception):
                drop()
        # [真失败根治 v29] 撤销本会话残留的 write_video 僵尸，让 finalize 立即
        # 排到队首执行。root cause：write_video 是非 cancelable 的高频调用，超时
        # 后 v21 降级策略让读线程继续投递，每次超时留一个僵尸 task 在队列里；
        # 长录制（真机 10min）worker 掉速 → 僵尸堆积 → finalize 投队尾被逐个执行
        # 顶过 60s → 屏障 90s 也排不上 → 成片来不及改名落盘 → "未捞回成片"、
        # 收尾 224s。此时读线程已退出（_join_threads 保证）、不会再生新帧，队列
        # 里残留的全是迟到僵尸；按本会话句柄精准撤销（多设备共享 worker 不误伤
        # 他机在途帧），finalize 随即执行。尾部最多丢已在队列未执行的几帧，远好
        # 过整段成片丢失 + 收尾卡死。老 native/替身无此接口时静默降级。
        drop_video = getattr(self.native, "drop_queued_video_writes", None)
        if drop_video is not None:
            with contextlib.suppress(Exception):
                drop_video(self._handle)
        # [修复] finalize 失败（overflow / SinkWriter::Finalize 报错）必须转成
        # 可读原因上抛，否则 paths=[] + err="" 会被 controller 当成"正常停止但
        # 无产物"，用户看不到任何失败提示。
        timed_out = False
        try:
            paths = self.native.session_finalize(self._handle)
        except Exception as ex:  # noqa: BLE001
            # [收尾根治 v22] 区分"worker 调用超时"与真 native 错误。超时时 finalize
            # task 仍非 cancelable 地留在 worker 队列里、随后会执行并落盘 .mp4；
            # 只是调用方已放弃、拿不到 out buffer 里的路径。此时不能马上 teardown：
            # 先投递屏障等该 finalize 真正跑完，再从 work_dir 捞出已发布产物，
            # 避免"明明成片了却报失败、产物还丢在 TEMP"的老问题。真 native 错误
            # （overflow / Finalize 报错）task 已执行且失败，无需屏障兜底。
            if "MF worker 调用超时" in str(ex):
                timed_out = True
            else:
                err = err or f"同源合成失败：{ex}"
        if timed_out:
            # 投递屏障等 finalize task 真正执行完（它非 cancelable、仍在队列里，
            # Finalize+MoveFile 会把 .tmp.mp4 改名为正式 .mp4 落盘）。
            # [真失败根治 v28] 屏障预算必须覆盖 finalize 最坏耗时（含慢盘改名），
            # 旧实现用 worker_barrier 默认 30s，比 finalize 的 60s 预算还短：
            # 屏障先超时→捞回时成片仍是 .tmp.mp4（被排除）→报"未捞回成片"，
            # 而队列里的 finalize task 随后被 worker.stop() 丢弃→成片真丢失。
            # 这里显式传 90s，让 finalize 有时间改名落盘后再捞回。
            barrier = getattr(self.native, "worker_barrier", None)
            if barrier is not None:
                with contextlib.suppress(Exception):
                    barrier(timeout=BARRIER_RECOVER_TIMEOUT_S)
            recovered = self._recover_published_from_workdir()
            if recovered:
                # 成片确实已落盘：超时只是"等不及回传路径"的假失败，按正常产物搬运。
                # err 在超时分支未写，保持为 self._error；捞回成功不新增错误。
                paths = list(paths) + recovered
            else:
                # [真失败根治 v28] 既没拿到回传路径也没捞到成片：如实上报，绝不
                # 静默报成功。用直接赋值覆盖作为主错误上抛——旧实现 `err or ...`
                # 会被前面记下的尾帧超时等诊断错误短路，把"没成片"这一致命结果
                # 掩盖成一条无害警告，controller 再据 files 里的 logcat 谎报成功。
                err = "同源合成失败：MF worker 调用超时，未捞回已发布成片"
        # [EDR 误报缓解] native 产物在 TEMP 工作目录里：只在 finalize 成功后
        # 把成品 copy 回用户保存目录。copy 失败或未落盘的产物不入列表并明确
        # 上报（work_dir 留待下次启动清理，返回 TEMP 路径没有意义），绝不误报成功。
        published, pub_err = self._publish_to_save_dir(paths)
        err = err or pub_err
        # session_destroy 同样经 worker.call 投递，FIFO 保证它排在 finalize 之后，
        # finalize 执行时 handle 仍有效，无 use-after-free；worker 真挂死时 destroy
        # 自身也会超时，被 _teardown_native 的 suppress 吞掉，不冒崩溃风险。
        self._teardown_native(discard=False)
        return published, err

    def _recover_published_from_workdir(self):
        """[收尾根治 v22] 扫描工作目录里已原子发布的 .mp4（排除 .tmp.mp4）。

        finalize 超时兜底：native 已把 .tmp.mp4 改名为 .mp4 并记入 published_，
        但 Python 侧因超时丢失了回传路径。这里直接扫描工作目录把成片捞回。
        只认正式 .mp4、不认 .tmp.mp4 半成品，避免把损坏文件当用户产物。
        """
        if not self.work_dir:
            return []
        try:
            import glob
            # [串味根治 v26] 所有设备会话共享一个 work_dir（start_all 里共建），
            # 各设备靠 stem 前缀隔离。若按 *.mp4 全捞，设备 A finalize 超时时会把
            # 设备 B 的成片也当自己的产物发布（重复/错配给用户）。只捞本会话 stem
            # 开头的正式 .mp4——native 命名规则是 {stem}_pN.mp4。
            pat = os.path.join(long_path(self.work_dir), "*.mp4")
            all_published = [p for p in glob.glob(pat)
                             if not p.lower().endswith(".tmp.mp4")]
            if not getattr(self, "_strict_recover", False):
                return sorted(all_published)
            # 多设备共享 work_dir：native 文件名是 {stem}_pN.mp4，stem 用原生值
            # （controller 传入时已净化），必须与之一致、不可二次净化，否则前缀
            # 失配反而捞不到成片。只保留本会话 stem 的成片，杜绝串味。
            prefix = self.stem + "_p"
            return sorted(p for p in all_published
                          if os.path.basename(p).startswith(prefix))
        except Exception:  # noqa: BLE001  扫描失败不影响主流程
            return []

    def _publish_to_save_dir(self, paths):
        """把工作目录里的成品 copy 回用户保存目录。

        返回 (路径列表, 错误串)。设计要点：
          * work_dir=None（未启用 A 方案 / 老行为）：原样返回，零副作用；
          * 源文件是工作目录内的占位但不存在：过滤 + 上报，绝不误报成功；
          * 源文件不在工作目录（测试替身）：原样返回，由上层 path_exists 过滤；
          * 跨卷安全：用 shutil.copy2 而非 os.replace（TEMP 与保存目录常不同盘）；
          * copy 失败：不入产物列表并汇总错误上抛（work_dir 随后被删）。
        """
        if not paths or not self.work_dir:
            return list(paths or []), ""
        try:
            os.makedirs(long_path(self.save_dir), exist_ok=True)
        except Exception as ex:  # noqa: BLE001
            return list(paths), f"创建保存目录失败：{ex}"
        work_abs = os.path.abspath(self.work_dir)
        out, errs = [], []
        for p in paths:
            if not p:
                continue
            try:
                p_abs = os.path.abspath(p)
                # 是否位于工作目录内：真机产物在这里，测试替身的占位路径不在。
                try:
                    in_work = os.path.commonpath([p_abs, work_abs]) == work_abs
                except ValueError:  # 不同盘符（Windows）
                    in_work = False
                if not path_isfile(p):
                    if in_work:
                        # finalize 报了产物却没落盘：work_dir 留待下次启动清理，
                        # 绝不能把悬空 TEMP 路径当成功产物，过滤并明确上报。
                        errs.append(f"同源产物未落盘：{os.path.basename(p)}")
                    else:
                        out.append(p)   # 占位/替身路径，原样保留（上层 path_exists 过滤）
                    continue
                # [修复-防覆盖] 与项目其它产物链路（截图/logcat/perf/命令导出/wav）
                # 一致走 unique_path：保存目录已有同名文件时补 _2/_3...，绝不静默
                # 覆盖上一场用户已拿到的视频（"停止→立刻再开始"落在同一秒、stem
                # 时间戳相同即可触发）。suffixes 把后续打包的 .zip 一并视为占用。
                dst = unique_path(
                    os.path.join(self.save_dir, os.path.basename(p)),
                    suffixes=(".zip",))
                if p_abs != os.path.abspath(dst):
                    shutil.copy2(long_path(p), long_path(dst))
                out.append(dst)
            except Exception as ex:  # noqa: BLE001
                # 不加入产物列表：work_dir 留待下次启动清理，返回 TEMP 原路径
                # 没有意义且可能让上层误报成功；改为明确上报搬运失败。
                errs.append(f"搬运 {os.path.basename(str(p))} 失败：{ex}")
        return out, "; ".join(errs)

    def cancel(self):
        """取消：停 adb → native discard（不发布）→ 删临时文件。"""
        self._stop.set()
        self._stop_drain()          # 先停音频排空定时器，再 discard
        self._close_proc()
        self._join_threads()
        if self._handle:
            with contextlib.suppress(Exception):
                self.native.session_discard(self._handle)
        self._teardown_native(discard=False)
        return []

    def _close_proc(self):
        proc = self._proc
        if proc is None:
            return
        with contextlib.suppress(Exception):
            if proc.poll() is None:
                proc.terminate()
        with contextlib.suppress(Exception):
            proc.wait(timeout=5)
        with contextlib.suppress(Exception):
            if proc.poll() is None:
                proc.kill()
        for name in ("stdout", "stderr"):
            with contextlib.suppress(Exception):
                stream = getattr(proc, name, None)
                if stream is not None:
                    stream.close()
        with self._lock:
            self._proc = None

    def _join_threads(self):
        # [收尾慢根治 v21] 读线程必须"真正跑完"才能往下走 finalize。旧实现对所有
        # 线程一律 join 6s：长录制切段时读线程正阻塞在 120s 的 session_rotate 里，
        # 6s 超时后 stop() 就把 finalize 投递到 worker；读线程从 rotate 返回后迟到
        # 的尾刷 write_video 排在重量 finalize 后面被顶过 30s → 误报"写入 H264 流
        # 失败"、收尾拖 106s（真机 v20 症状，短录制无切段故正常）。
        # 修复：等 _read_done 信号（读线程在 finally 末尾置位），预算覆盖一次最坏
        # rotate(120s)+尾刷余量；stderr/drain 线程不投递 native 写调用，仍短 join。
        read = self._read_thread
        if read is not None and read.is_alive():
            # 预算需覆盖 session_rotate 的 120s 超时 + 尾刷几次 write_video。
            if not self._read_done.wait(timeout=READ_DONE_BUDGET_S):
                # 病态兜底：worker 真挂死时不能无限等界面；此时读线程仍活着，但
                # 再用一个短 join 收尾，避免留下非 daemon 线程（本线程均 daemon）。
                with contextlib.suppress(Exception):
                    read.join(timeout=2)
        for t in (self._err_thread, self._drain_thread):
            if t is not None and t.is_alive():
                with contextlib.suppress(Exception):
                    t.join(timeout=6)

    def _stop_drain(self):
        """通知并等待音频排空定时器退出（幂等）。"""
        self._drain_stop.set()
        t = self._drain_thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            with contextlib.suppress(Exception):
                t.join(timeout=6)
        self._drain_thread = None

    def _teardown_native(self, discard):
        if not self._handle:
            return
        with contextlib.suppress(Exception):
            if discard:
                self.native.session_discard(self._handle)
            self.native.session_destroy(self._handle)
        self._handle = 0

    def stats(self):
        return dict(self._stats)


class MFCaptureService:
    """多设备会话集合 + 进程级 native worker 生命周期。"""

    def __init__(self, native=None, adb="adb"):
        from backend.mf_native import MFNative  # 局部导入避免循环
        self.native = native if native is not None else MFNative()
        self.adb = adb
        self._sessions = {}          # serial -> MFCaptureSession
        self._lock = threading.Lock()
        self._mic_started = False
        # [EDR 误报缓解] 本次录制共用的系统 TEMP 工作目录（所有设备会话共享，
        # 各设备 stem 不同天然隔离）。收尾不删，留待下次启动 sweep_workdirs 清理。
        self._work_dir = None

    @property
    def available(self):
        return self.native.available

    @property
    def error(self):
        return self.native.error

    @property
    def build_id(self):
        """native DLL 构建指纹（老 DLL 返回空串），供启动日志自证版本。"""
        try:
            return self.native.build_id()
        except Exception:  # noqa: BLE001  测试替身/老封装无此接口时降级为空
            return ""

    def start_all(self, serials, save_dir, stems, sizes, mic_endpoint=None):
        """启动全部设备会话；任一失败撤销全部，返回 (ok, 原因, 首路径映射)。

        `stems`/`sizes` 是与 serials 等长的序列或 serial->值 的字典。
        """
        if not self.available:
            return False, self.error or "同源录制不可用", {}
        worker = self.native.start_worker()
        # 麦克风：native 内部采集；先启动并用其回读的真实格式建会话。
        # [修复] 失败路径必须与下方 mic_format 失败分支一样停掉 worker：
        # worker 是常驻 MTA 线程（已 MFStartup）。这里若直接 return，controller
        # 侧因会话尚未登记不会调 stop_all/cancel_all，worker 会一直挂到进程退出。
        try:
            rc = self.native.mic_start(mic_endpoint, *DEFAULT_MIC)
            if rc != 0:
                reason = self.native.last_error()   # 先取，stop 可能覆盖 native 末次错误
                worker.stop()
                self.native.worker = None
                return False, reason, {}
            self._mic_started = True
        except Exception as ex:  # noqa: BLE001
            self._stop_mic()
            worker.stop()
            self.native.worker = None
            return False, f"启动麦克风采集失败：{ex}", {}
        # native 回读真实 mix format，顺序 (rate, bits, channels) 原样传给会话，
        # 保证音频流媒体类型与实际采集一致（否则 Finalize 0xC00D4A45）。
        # [修复] native 在无设备/未就绪时会报错误码，MFNative.mic_format 抛
        # MFNativeError；这里必须接住并转成可读 reason，否则异常冒泡到
        # controller 的 start_all 调用点（无 try）会变成 API 500。0 值同样
        # 是非法的（会让 AddStream 失败），一并拦截。
        try:
            mic_fmt = self.native.mic_format()
        except Exception as ex:  # noqa: BLE001
            self._stop_mic()
            worker.stop()
            self.native.worker = None
            return False, f"读取麦克风格式失败：{ex}", {}
        if not mic_fmt or any(not isinstance(x, int) or x <= 0 for x in mic_fmt):
            self._stop_mic()
            worker.stop()
            self.native.worker = None
            return False, f"麦克风格式非法（{mic_fmt}），无法建音频流", {}
        # [修复-0xC00D4A45 第三根因] 系统 AAC 编码器只接受 44100/48000 Hz、
        # 1/2/6 声道。WASAPI mix format 若为 96000/192000 等或非常规声道数，
        # SetInputMediaType/WriteSample 会失败 → 音频流 0 sample → Finalize
        # 生成不了 esds box 报 0xC00D4A45。与其静默录出无声坏片，不如启动前
        # 明确拒绝并给出可读原因（native 已把位深统一为 16，这里只校验 rate/ch）。
        mic_rate, _mic_bits, mic_ch = mic_fmt
        if mic_rate not in (44100, 48000) or mic_ch not in (1, 2, 6):
            self._stop_mic()
            worker.stop()
            self.native.worker = None
            return False, (
                f"麦克风格式 {mic_rate}Hz/{mic_ch}声道 超出系统 AAC 编码器支持范围"
                "（44.1/48kHz、1/2/6 声道），请在系统声音设置里把输入设备改为 48kHz 后重试"), {}
        # [EDR 误报缓解] 建系统 TEMP 工作目录：native 的所有 .tmp.mp4 写入、
        # 改名、取消删除都落这里，用户保存目录不再出现勒索特征文件操作。
        # 所有设备会话共享一个目录（stem 不同天然隔离）；收尾不删，留待下次
        # 启动由 tmpfiles.sweep_workdirs 后台清理，让"点停止"瞬间零批量删除。
        self._work_dir = tempfile.mkdtemp(prefix=MF_WORKDIR_PREFIX)
        # [串味根治 v26] 多设备共享同一 work_dir 时，兜底捞回必须按 stem 隔离，
        # 否则 A 超时捞回会把 B 的成片当 A 的产物发布。
        multi_device = len(serials) > 1
        started, first_err = {}, None
        for s in serials:
            stem = self._value(stems, s, f"record_{safe_name(s)}")
            size = self._value(sizes, s, None)
            width, height = self._parse_size(size, 1080, 1920)
            session = MFCaptureSession(
                self.native, s, save_dir, stem, width, height,
                mic_fmt=mic_fmt, adb=self.adb, size=size,
                work_dir=self._work_dir)
            session._strict_recover = multi_device
            ok, err = session.start()
            if ok:
                started[s] = session
            else:
                first_err = first_err or f"{s}：{err}"
                session.cancel()
        if not started:
            self._stop_mic()
            worker.stop()
            self.native.worker = None
            self._drop_work_dir()
            return False, first_err or "所有设备 H264 流启动失败", {}
        with self._lock:
            self._sessions.update(started)
        firsts = {s: sess._tmp_first for s, sess in started.items()}
        return True, "", firsts

    def stop_all(self):
        """停止全部并 finalize，返回 {serial: ([路径], 错误)}。finally 清理 worker。"""
        out = {}
        with self._lock:
            sessions = list(self._sessions.items())
            self._sessions.clear()
        try:
            for s, sess in sessions:
                paths, err = sess.stop()
                out[s] = (paths, err)
        finally:
            self._stop_mic()
            if self.native.worker is not None:
                self.native.worker.stop()
                self.native.worker = None
            self._drop_work_dir()
        return out

    def cancel_all(self):
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        try:
            for sess in sessions:
                sess.cancel()
        finally:
            self._stop_mic()
            if self.native.worker is not None:
                self.native.worker.stop()
                self.native.worker = None
            self._drop_work_dir()

    def _drop_work_dir(self):
        """放弃本次工作目录的引用，**不在收尾瞬间删除**（幂等）。

        [EDR 误报缓解] 旧实现在此处对 TEMP 工作目录做一次集中 rmtree。亚信
        「未授权文件加密」盯的正是"写高熵 MP4 → 改名 → 批量删"的行为序列；
        即使前两步已搬进 TEMP，"点停止"这一刻仍紧跟一次目录级批量删除，仍是
        可疑信号。现在收尾只清引用、不碰磁盘：TEMP 里的中间态留给下次启动
        由 core.tmpfiles.sweep_workdirs 后台清理 —— 那时没有活跃录制会话，
        删除不会与写入/改名挤在同一瞬间。

        在 stop_all（成品已 copy 回保存目录）/ cancel_all（丢弃半成品）/ 启动
        全失败三种收尾调用。目录残留由下次启动兜底清理，绝不影响本次结果。
        """
        self._work_dir = None

    def _stop_mic(self):
        if self._mic_started:
            with contextlib.suppress(Exception):
                self.native.mic_stop()
            self._mic_started = False

    @staticmethod
    def _value(src, key, default):
        if src is None:
            return default
        if isinstance(src, dict):
            return src.get(key, default)
        return default

    @staticmethod
    def _even(v):
        """H264/MP4 编码要求宽高为偶数：向下取偶。"""
        v = int(v)
        return v if v % 2 == 0 else v - 1

    @classmethod
    def _parse_size(cls, size, dw, dh):
        if not size:
            return cls._even(dw), cls._even(dh)
        try:
            w, h = str(size).lower().split("x")
            return cls._even(w), cls._even(h)
        except Exception:  # noqa: BLE001  非法尺寸退回默认
            return cls._even(dw), cls._even(dh)

    def stats(self):
        with self._lock:
            return {s: sess.stats() for s, sess in self._sessions.items()}
