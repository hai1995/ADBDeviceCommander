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

from core.constants import no_window_flags, safe_name
from core.longpath import long_path, path_isfile

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
        self._error = ""
        # stderr 只作诊断信息，单独存放。它绝不能写进 _error：_error 是主流程
        # 错误通道，正常 stop 时 terminate 进程会让 stderr 读到 EOF/退出日志，
        # 若写进 _error 会（a）覆盖读线程记录的首个真实错误（overflow/WriteSample
        # 失败），（b）即使录制完全成功也可能在收尾时报一句无关的"警告"。
        self._stderr_tail = ""
        self._lock = threading.Lock()
        self._stats = {"bytes": 0, "first_ok": False}
        self._tmp_first = ""

    # ---- 启动 ----------------------------------------------------------
    def start(self):
        """返回 (ok, 错误原因)。同步等首字节，秒退立即报错。"""
        arate, abits, ach = self.mic_fmt
        # [EDR 误报缓解] native 只在 work_dir 里写 .tmp.mp4 / 改名 / 删除，
        # 用户保存目录不再出现"高熵半成品写入 → 改名 → 批量删"的勒索特征信号。
        native_dir = self.work_dir or self.save_dir
        with self._lock:
            self._handle, self._tmp_first = self.native.session_create(
                native_dir, self.stem, self.width, self.height,
                FPS_NUM, FPS_DEN, arate, abits, ach)
        try:
            # H264 是**二进制流**：绝不能用 adb_popen_kwargs()（它带 text=True/
            # encoding=utf-8，会把码流按 UTF-8 解码并损坏数据）。这里 stdout 保持
            # bytes 模式，只借用 no_window_flags 隐藏黑窗。stderr 是文本，由
            # _drain_stderr 自行按 utf-8/replace 解码。
            proc = subprocess.Popen(
                h264_cmd(self.adb, self.serial, self.size),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL, creationflags=no_window_flags())
        except Exception as ex:  # noqa: BLE001  启动失败转成可读原因
            self._teardown_native(discard=True)
            return False, f"无法启动 screenrecord H264 流：{ex}"
        self._proc = proc
        # stderr 必须有消费者，否则 64KB 写满会把设备端阻塞。
        self._err_thread = threading.Thread(
            target=self._drain_stderr, daemon=True,
            name=f"mf-h264-err-{safe_name(self.serial)}")
        self._err_thread.start()
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
        """周期性排空音频队列（经 worker 线程）。任何异常不致命，记首错后续上报。"""
        while not self._drain_stop.wait(AUDIO_DRAIN_INTERVAL_S):
            h = self._handle
            if not h:
                continue
            try:
                self.native.session_drain_audio(h)
            except Exception as ex:  # noqa: BLE001  定时排空失败记首错，不打断录制
                self._error = self._error or f"音频排空失败：{ex}"
                break

    def _read_loop(self):
        nal_buf = __import__("backend.mf_native", fromlist=["NalBuffer"]).NalBuffer()
        stream = self._proc.stdout if self._proc is not None else None
        if stream is None:
            return
        try:
            while not self._stop.is_set():
                # [修复-首帧超时] 必须用 read1，绝不能退回 read：
                #   BufferedReader.read(64KB) 在管道上会阻塞到「凑满 64KB 或 EOF」。
                #   车机静止/低码率画面下 H264 输出可能只有几 KB/s，6s 都攒不满，
                #   _first_data 因此永不置位，start() 卡满超时后误报「screenrecord
                #   未在 6s 内输出 H264 数据（退出码 None）」——其实进程还活着、
                #   数据也在慢慢到达，只是被 read 憋在管道缓冲里。
                #   read1 有多少读多少，首字节到达即置位首帧事件，慢速流也能秒过
                #   判定。投屏路径 mirror_service._feed_loop 同样用 read1，对齐。
                chunk = stream.read1(READ_CHUNK)
                if not chunk:
                    break
                if not self._first_data.is_set():
                    self._first_data.set()
                # 按 NAL 边界切块，避免跨块 NAL 被 native 截断。
                for nal in nal_buf.feed(chunk):
                    if self._stop.is_set():
                        break
                    # [修复] native 写入失败（overflow / WriteSample 失败）必须
                    # 记录，不能被 suppress 吞成"假成功"——否则 finalize 出一个
                    # 缺帧/无音视频还向用户报成功。首错为准，并置停止标志。
                    try:
                        self.native.session_write_video(self._handle, nal)
                        self._stats["bytes"] += len(nal)
                    except Exception as ex:  # noqa: BLE001
                        self._error = self._error or f"写入 H264 流失败：{ex}"
                        self._stop.set()
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
                        self._error = self._error or f"写入 H264 尾帧失败：{ex}"
                        break
            self._first_data.set()   # 即使失败也唤醒 wait，避免等满超时

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
        self._close_proc()
        self._join_threads()
        if not self._handle:
            return [], self._error or "会话未创建"
        with self._lock:
            with contextlib.suppress(Exception):
                self.native.session_mark_mic_stop(self._handle)
        paths = []
        err = self._error
        # [修复] finalize 失败（overflow / SinkWriter::Finalize 报错）必须转成
        # 可读原因上抛，否则 paths=[] + err="" 会被 controller 当成"正常停止但
        # 无产物"，用户看不到任何失败提示。
        try:
            paths = self.native.session_finalize(self._handle)
        except Exception as ex:  # noqa: BLE001
            err = err or f"同源合成失败：{ex}"
        # [EDR 误报缓解] native 产物在 TEMP 工作目录里：只在 finalize 成功后
        # 把成品 copy 回用户保存目录。copy 失败或未落盘的产物不入列表并明确
        # 上报（work_dir 随后被删，返回悬空 TEMP 路径没有意义），绝不误报成功。
        published, pub_err = self._publish_to_save_dir(paths)
        err = err or pub_err
        self._teardown_native(discard=False)
        return published, err

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
                        # finalize 报了产物却没落盘：work_dir 随后被删，绝不能
                        # 把悬空 TEMP 路径当成功产物，过滤并明确上报。
                        errs.append(f"同源产物未落盘：{os.path.basename(p)}")
                    else:
                        out.append(p)   # 占位/替身路径，原样保留（上层 path_exists 过滤）
                    continue
                dst = os.path.join(self.save_dir, os.path.basename(p))
                if p_abs != os.path.abspath(dst):
                    shutil.copy2(long_path(p), long_path(dst))
                out.append(dst)
            except Exception as ex:  # noqa: BLE001
                # 不加入产物列表：work_dir 随后会被清理，返回 TEMP 原路径没有
                # 意义且可能让上层误报成功；改为明确上报搬运失败。
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
        for t in (self._read_thread, self._err_thread, self._drain_thread):
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
        # 各设备 stem 不同天然隔离）。stop/cancel 收尾后统一删除。
        self._work_dir = None

    @property
    def available(self):
        return self.native.available

    @property
    def error(self):
        return self.native.error

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
        # [EDR 误报缓解] 建系统 TEMP 工作目录：native 的所有 .tmp.mp4 写入、
        # 改名、取消删除都落这里，用户保存目录不再出现勒索特征文件操作。
        # 所有设备会话共享一个目录（stem 不同天然隔离），收尾统一清理。
        self._work_dir = tempfile.mkdtemp(prefix="adc_mf_")
        started, first_err = {}, None
        for s in serials:
            stem = self._value(stems, s, f"record_{safe_name(s)}")
            size = self._value(sizes, s, None)
            width, height = self._parse_size(size, 1080, 1920)
            session = MFCaptureSession(
                self.native, s, save_dir, stem, width, height,
                mic_fmt=mic_fmt, adb=self.adb, size=size,
                work_dir=self._work_dir)
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
        """删除本次录制的工作目录（含所有 .tmp.mp4 中间态），幂等。

        在 stop_all（成品已 copy 回保存目录）/ cancel_all（丢弃半成品）/ 启动
        全失败三种收尾调用。删除失败只吞异常——TEMP 残留由系统清理，不影响用户。
        """
        wd = self._work_dir
        self._work_dir = None
        if wd:
            with contextlib.suppress(Exception):
                shutil.rmtree(long_path(wd), ignore_errors=True)

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
