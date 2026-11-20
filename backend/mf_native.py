"""
backend.mf_native —— native MF/WASAPI 扩展（adc_mf_sink.dll）的 ctypes 封装
==========================================================================
只做三件事：

1. **加载与可用性**：找到 dll 并绑定 C ABI；找不到/加载失败时给出明确、
   可显示的中文原因，**绝不抛裸异常**（非 Windows / 未编译 / 杀软拦截都要
   能转成"同源录制不可用"提示，让上层决定是否回退 ffmpeg 兜底）。
2. **线程约束**：`init/shutdown` 只能在同一个 MTA worker 线程调用。本模块
   提供 `MFWorker`——内部起一个常驻线程完成 CoInitializeEx(MTA)+MFStartup，
   所有 native 调用都投递到该线程执行并同步等结果（ctypes 调用在 worker
   线程上跑，UI/业务线程不碰 COM）。
3. **H264 分块缓冲**：adb stdout 按块读，单条 NAL 可能跨两块；这里维护
   块间缓冲，按"下一起始码"切出完整 NAL 才下发，避免跨块 NAL 被截断。

沙箱（Linux）里 dll 不存在，`available()` 返回 False、原因写清；单测用
注入的假 lib 走同一套调用序列，逻辑可在无 Windows 环境下验证。
"""
import ctypes
import os
import queue
import threading

from core.longpath import path_isfile


# ---- 错误码：与 native adc_mf_sink.h 对齐 -------------------------------
RPC_E_CHANGED_MODE = 0x80010106
ADC_OK = 0

# annex-B 起始码
_SC3 = b"\x00\x00\x01"
_SC4 = b"\x00\x00\x00\x01"


class MFNativeError(RuntimeError):
    """native 调用失败（带 HRESULT / 可读原因）。"""


def _hresult_text(hr):
    """把 HRESULT 转成可显示文本（有符号/无符号都归一到 32 位）。"""
    u = hr & 0xFFFFFFFF
    return f"0x{u:08X}"


class MFWorker:
    """常驻 MTA worker：所有 native 调用在该线程执行，结果同步回传。

    生命周期：`start()` → 反复 `call(fn, *args)` → 若干 session 操作 →
    `stop()`（内部 adc_shutdown + 线程退出）。`call` 抛出的异常会在调用
    线程重抛，便于上层 try/finally。
    """

    def __init__(self, lib):
        self._lib = lib
        self._q = queue.Queue()
        self._thread = None
        self._started = threading.Event()
        self._stop = threading.Event()
        self._init_err = None

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name="adc-mf-worker", daemon=True)
        self._thread.start()
        if not self._started.wait(timeout=15):
            # adc_init 未在 15s 内返回（COM/MFStartup 卡死）：不能当成成功，
            # 否则后续 call 会投递到一个永不消费的队列、调用方永久阻塞。
            self._init_err = self._init_err or "MF worker 初始化超时（adc_init 15s 未返回）"
        if self._init_err is not None:
            err = self._init_err
            self.stop()
            raise MFNativeError(err)

    def _loop(self):
        lib = self._lib
        try:
            rc = lib.adc_init()
            if rc != ADC_OK:
                self._init_err = self._last_error(lib, rc)
                self._started.set()
                return
            self._started.set()
            while not self._stop.is_set():
                try:
                    item = self._q.get(timeout=0.2)
                except queue.Empty:
                    continue
                if item is None:
                    break
                fn, args, done = item
                try:
                    done["value"] = fn(*args)
                except BaseException as ex:  # noqa: BLE001  跨线程传回调用方
                    done["error"] = ex
                finally:
                    done["event"].set()
        finally:
            with __import__("contextlib").suppress(Exception):
                lib.adc_shutdown()

    def call(self, fn, *args):
        """在 worker 线程执行 fn(*args)，同步等结果。"""
        if self._thread is None or not self._thread.is_alive():
            raise MFNativeError("MF worker 未启动")
        done = {"event": threading.Event(), "value": None, "error": None}
        self._q.put((fn, args, done))
        done["event"].wait()
        if done["error"] is not None:
            raise done["error"]
        return done["value"]

    def stop(self):
        if self._thread is None:
            return
        self._stop.set()
        try:
            self._q.put(None)
            self._thread.join(timeout=10)
        finally:
            self._thread = None

    @staticmethod
    def _last_error(lib, rc):
        buf = ctypes.create_string_buffer(1024)
        with __import__("contextlib").suppress(Exception):
            lib.adc_last_error(buf, len(buf))
        text = buf.value.decode("utf-8", "replace").strip()
        return text or f"native 初始化失败（{_hresult_text(rc)}）"


class MFNative:
    """ctypes 门面：绑定所有符号，暴露高层方法；不可用时不抛异常。"""

    def __init__(self, dll_path=None):
        self._lib = None
        self._error = ""
        self.worker = None
        self._path = dll_path
        self._bind()

    # ---- 可用性 --------------------------------------------------------
    @property
    def available(self):
        return self._lib is not None

    @property
    def error(self):
        return self._error

    def _bind(self):
        if os.name != "nt":
            self._error = "同源录制仅支持 Windows（当前非 Windows 平台）"
            return
        path = self._path or self._default_dll_path()
        if not path or not path_isfile(path):
            self._error = (
                "未找到 adc_mf_sink.dll：本机未编译同源录制扩展，"
                "或打包时未带上（开发态请在 native/ 下用 cmake 构建后放到 backend/）")
            return
        try:
            lib = ctypes.CDLL(path)
            self._bind_signatures(lib)
            self._lib = lib
        except Exception as ex:  # noqa: BLE001  DLL 损坏/缺系统 DLL 都转可读原因
            self._error = f"加载 adc_mf_sink.dll 失败：{ex}"

    @staticmethod
    def _default_dll_path():
        # PyInstaller onefile：dll 被 --add-binary 放到 _MEIPASS 根。
        meipass = getattr(__import__("sys"), "_MEIPASS", None)
        if meipass:
            return os.path.join(meipass, "adc_mf_sink.dll")
        # 源码态：与 backend 包同目录。
        return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "adc_mf_sink.dll")

    def _bind_signatures(self, lib):
        U8P = ctypes.POINTER(ctypes.c_ubyte)
        i, u, ll = ctypes.c_int, ctypes.c_uint, ctypes.c_longlong
        lib.adc_init.argtypes = []; lib.adc_init.restype = i
        lib.adc_shutdown.argtypes = []; lib.adc_shutdown.restype = None
        lib.adc_last_error.argtypes = [ctypes.c_char_p, i]; lib.adc_last_error.restype = i
        lib.adc_mic_start.argtypes = [ctypes.c_wchar_p, i, i, i]; lib.adc_mic_start.restype = i
        lib.adc_mic_stop.argtypes = []; lib.adc_mic_stop.restype = None
        lib.adc_mic_format.argtypes = [ctypes.POINTER(i)] * 3; lib.adc_mic_format.restype = i
        lib.adc_mic_device_events.argtypes = []; lib.adc_mic_device_events.restype = i
        lib.adc_session_create.argtypes = [
            ctypes.c_char_p, ctypes.c_char_p, i, i, i, i, i, i, i,
            ctypes.c_char_p, i]
        lib.adc_session_create.restype = ll
        lib.adc_session_write_video.argtypes = [ll, U8P, i]; lib.adc_session_write_video.restype = i
        lib.adc_session_mark_mic_stop.argtypes = [ll]; lib.adc_session_mark_mic_stop.restype = i
        lib.adc_session_finalize.argtypes = [ll, ctypes.c_char_p, i]; lib.adc_session_finalize.restype = i
        lib.adc_session_discard.argtypes = [ll]; lib.adc_session_discard.restype = None
        lib.adc_session_destroy.argtypes = [ll]; lib.adc_session_destroy.restype = None
        lib.adc_session_stats.argtypes = [ll, ctypes.POINTER(ll), ctypes.POINTER(ll),
                                          ctypes.POINTER(ll), ctypes.POINTER(i)]
        lib.adc_session_stats.restype = i

    def start_worker(self):
        if not self.available:
            raise MFNativeError(self._error)
        if self.worker is None:
            self.worker = MFWorker(self._lib)
            self.worker.start()
        return self.worker

    def stop_worker(self):
        if self.worker is not None:
            self.worker.stop()
            self.worker = None

    def last_error(self):
        if not self.available:
            return self._error
        buf = ctypes.create_string_buffer(1024)
        with __import__("contextlib").suppress(Exception):
            self._lib.adc_last_error(buf, len(buf))
        return buf.value.decode("utf-8", "replace").strip()

    # ---- 便捷调用（都经 worker 线程；调用方持有 worker）----------------
    def mic_start(self, endpoint_id, rate, bits, channels):
        return self.worker.call(self._lib.adc_mic_start, endpoint_id, rate, bits, channels)

    def mic_stop(self):
        self.worker.call(self._lib.adc_mic_stop)

    def mic_format(self):
        r, b, c = (ctypes.c_int() for _ in range(3))
        rc = self.worker.call(self._lib.adc_mic_format,
                              ctypes.byref(r), ctypes.byref(b), ctypes.byref(c))
        if rc != ADC_OK:
            raise MFNativeError(self.last_error())
        return r.value, b.value, c.value

    def session_create(self, out_dir, stem, width, height, fps_num, fps_den,
                       arate, abits, ach):
        first = ctypes.create_string_buffer(2048)
        h = self.worker.call(
            self._lib.adc_session_create,
            out_dir.encode("utf-8"), stem.encode("utf-8"), width, height,
            fps_num, fps_den, arate, abits, ach, first, len(first))
        if not h:
            raise MFNativeError(self.last_error())
        return h, first.value.decode("utf-8", "replace")

    def session_write_video(self, h, data):
        buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        rc = self.worker.call(self._lib.adc_session_write_video, h, buf, len(data))
        if rc != ADC_OK:
            raise MFNativeError(self.last_error())

    def session_finalize(self, h):
        out = ctypes.create_string_buffer(8192)
        rc = self.worker.call(self._lib.adc_session_finalize, h, out, len(out))
        if rc != ADC_OK:
            raise MFNativeError(self.last_error())
        pub = out.value.decode("utf-8", "replace")
        return [p for p in pub.split(";") if p]

    def session_discard(self, h):
        self.worker.call(self._lib.adc_session_discard, h)

    def session_destroy(self, h):
        self.worker.call(self._lib.adc_session_destroy, h)


class NalBuffer:
    """adb stdout 分块 → 按 NAL 边界切出完整块，避免跨块 NAL 被截断。

    `feed(chunk)` 返回若干"以起始码开头、到下一起始码前"的完整 NAL 段字节串；
    末尾不足一条的残段留在内部，等下一块或 `flush()`。
    """

    def __init__(self):
        self._buf = bytearray()

    def feed(self, chunk):
        if not chunk:
            return []
        self._buf.extend(chunk)
        out = []
        # 只输出「已完整」的 NAL：即后面已出现下一起始码的那几条。
        # 最后一条始终留在缓冲里（它可能跨块未完成），等下一块或 flush()。
        # 旧实现把最后一条也输出、同时又保留，导致它在 feed 和 flush 里各发
        # 一次 —— 同一 NAL 重复喂给 native 会破坏 H264 参考帧/解码。
        starts = self._find_starts(self._buf)
        if not starts:
            # 没有任何起始码：只保留尾部少量，防止 buffer 无限增长。
            if len(self._buf) > 1024 * 1024:
                del self._buf[:-64]
            return []
        for i in range(len(starts) - 1):
            pos = starts[i][0]
            end = starts[i + 1][0]
            out.append(bytes(self._buf[pos:end]))
        # 丢弃第一条起始码之前的噪声，保留从最后一条起始码起的数据
        last_pos = starts[-1][0]
        del self._buf[:last_pos]
        return out

    def flush(self):
        data = bytes(self._buf)
        self._buf.clear()
        return [data] if data else []

    @staticmethod
    def _find_starts(buf):
        res = []
        i = 0
        n = len(buf)
        while i + 3 <= n:
            if buf[i] == 0 and buf[i + 1] == 0 and buf[i + 2] == 1:
                sc = 3
                if i + 4 <= n and buf[i + 3] == 0:
                    sc = 4
                res.append((i, sc))
                i += sc
            else:
                i += 1
        return res
