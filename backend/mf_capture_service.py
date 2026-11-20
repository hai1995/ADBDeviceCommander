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
import subprocess
import threading

from core.constants import no_window_flags, safe_name

# 首帧等待：screenrecord 秒退（ROM 不支持 --output-format=h264）要能快速报错。
FIRST_DATA_TIMEOUT_S = 6.0
# stdout 读块大小（64KB）：H264 ES 无内建时间戳，native 按 sample 到达时刻打
# QPC 时间戳。1MB 在 8Mbps 下要约 8s 才攒满，会让整批帧挤到同一时刻、时间轴
# 严重压缩；64KB 约 0.5s，兼顾系统调用次数与时间精度。
READ_CHUNK = 64 * 1024
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
                 mic_fmt=DEFAULT_MIC, adb="adb", size=None):
        self.native = native
        self.serial = serial
        self.save_dir = save_dir
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
        with self._lock:
            self._handle, self._tmp_first = self.native.session_create(
                self.save_dir, self.stem, self.width, self.height,
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
                f"（退出码 {proc.poll()}）")
            # stderr 只在启动失败诊断时拼进原因；正常路径绝不把它当错误。
            if self._stderr_tail and self._stderr_tail not in self._error:
                self._error = f"{self._error}（{self._stderr_tail}）"
            if not ok:
                self._stop.set()
            return False, self._error
        if self._error:
            return False, self._error
        return True, ""

    def _read_loop(self):
        nal_buf = __import__("backend.mf_native", fromlist=["NalBuffer"]).NalBuffer()
        stream = self._proc.stdout if self._proc is not None else None
        if stream is None:
            return
        try:
            while not self._stop.is_set():
                chunk = stream.read(READ_CHUNK)
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
        except Exception:  # noqa: BLE001  后台读 stderr，失败不影响主流程
            pass

    # ---- 停止 / 取消 ---------------------------------------------------
    def stop(self):
        """正常收尾：停 adb → 等读线程 → native finalize → 返回发布路径列表。"""
        self._stop.set()
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
        self._teardown_native(discard=False)
        return paths, err

    def cancel(self):
        """取消：停 adb → native discard（不发布）→ 删临时文件。"""
        self._stop.set()
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
        for t in (self._read_thread, self._err_thread):
            if t is not None and t.is_alive():
                with contextlib.suppress(Exception):
                    t.join(timeout=6)

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
        started, first_err = {}, None
        for s in serials:
            stem = self._value(stems, s, f"record_{safe_name(s)}")
            size = self._value(sizes, s, None)
            width, height = self._parse_size(size, 1080, 1920)
            session = MFCaptureSession(
                self.native, s, save_dir, stem, width, height,
                mic_fmt=mic_fmt, adb=self.adb, size=size)
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
