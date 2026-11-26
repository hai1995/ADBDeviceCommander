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
# [收尾慢根治 v20] write_video 的特殊返回：该切段了，请调用 session_rotate。
# 与 native 的 ADC_ROTATE_PENDING 对齐（小正整数，不与 HRESULT 冲突）。
ADC_ROTATE_PENDING = 1

# annex-B 起始码
_SC3 = b"\x00\x00\x01"
_SC4 = b"\x00\x00\x00\x01"

# [修复-收尾慢/僵尸task] 分级调用超时（秒，经 MFWorker.call）：
#   v14 曾把 drain 从 15s 降到 5s，想"卡住尽快失败重试"。但真机 3 分钟长录制
#   实证：高负载下单 worker 被海量 write_video 占满，drain 排队 >5s 是常态，
#   5s 太激进 → 大量 drain 被误判超时。而旧 call() 超时后 task 仍留在 worker
#   队列执行（僵尸），每次重试又堆一个，僵尸占满 worker → finalize 排队 → 收尾
#   超 1 分钟。修复：超时 drain 可在队列中被撤销（见 call(cancelable)），超时值
#   放宽到 10s 减少误报，二者配合从根上消除僵尸堆积。finalize 仍给 60s（含
#   SinkWriter::Finalize 编码器 flush + 文件改名，长录制/多段本就慢）。
#   [v18·write_video 超时] 真机 1min+ 录制仍报"写入 H264 流失败：MF worker 调用超时
#   （15s 未返回）"，但 native 指纹已是 v17——说明新的超时点已从 drain 转移到
#   write_video 本身。根因：native drain_audio_queued 一次 swap 走全部积压音频块
#   (5s≈234 块)逐块同步 AAC 编码，累计可达 15s+，而这段无上限批量编码就嵌在
#   write_video() 内部。根治在 native 分批排空(kAudioDrainBatchMax=48)；这里把
#   write_video 从默认 15s 放宽到 30s 作兜底——宁可多等也别把慢速设备的正常帧
#   误判成致命失败/提前终止录制。30s 仍在 finalize 60s 之内，不影响收尾判定。
#   [v20·切段独立超时] 3min+ 录制跨 170s 分段阈值时，native 旧实现在 write_video
#   内同步做 Finalize+WRITE_THROUGH 刷盘+重建 SinkWriter（重量，可达数十秒），
#   30s write 预算不够 → 误报"写入 H264 流失败"。根治：native 到点只返回
#   ADC_ROTATE_PENDING 请求，Python 显式调 session_rotate 做重量切段，用本独立
#   长超时（120s，覆盖慢盘/EDR 扫描）；write_video 因此恢复轻量、30s 绰绰有余。
DRAIN_CALL_TIMEOUT_S = 10.0
FINALIZE_CALL_TIMEOUT_S = 60.0
VIDEO_WRITE_CALL_TIMEOUT_S = 30.0
ROTATE_CALL_TIMEOUT_S = 120.0


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

    def _drain_pending(self):
        """把队列里尚未处理的调用全部回写错误并唤醒等待方。

        stop() 置位后旧实现直接退出 `_loop`，队列里排着的 call（音频排空定时器
        每 200ms 排一次，停止瞬间常有一两个在途）永远不会被处理，caller 卡在
        `event.wait()` 上不放。这里在退出前逐项报错，保证没有悬挂线程。
        """
        while True:
            try:
                item = self._q.get_nowait()
            except queue.Empty:
                break
            if item is None:
                continue
            _fn, _args, done = item
            done["error"] = MFNativeError("MF worker 已停止，调用未执行")
            done["event"].set()

    def _loop(self):
        lib = self._lib
        try:
            rc = lib.adc_init()
            if rc != ADC_OK:
                self._init_err = self._last_error(lib, rc)
                self._started.set()
                return
            self._started.set()
            # 退出条件以「读到 None 哨兵」为准，而不是 `_stop.is_set()`：
            # 后者一旦置位就让还在队列里的 call 被丢弃，caller 永久等待。
            # stop() 先置位再放哨兵，FIFO 保证哨兵之前的调用都被正常执行。
            while True:
                try:
                    item = self._q.get(timeout=0.2)
                except queue.Empty:
                    if self._stop.is_set():
                        break
                    continue
                if item is None:
                    break
                fn, args, done = item
                try:
                    # [修复-僵尸task] 若调用方已超时放弃且标记可撤销，跳过执行。
                    # 旧实现无条件执行超时 task：drain 每 200ms 投一次、高负载下
                    # 频繁 5s 超时，每次超时都留下一个僵尸 drain 占住 worker，
                    # 堆积后 finalize 排到队尾 → 收尾超 1 分钟。跳过即可根治。
                    if done.get("cancelled"):
                        continue
                    done["value"] = fn(*args)
                except BaseException as ex:  # noqa: BLE001  跨线程传回调用方
                    done["error"] = ex
                finally:
                    # cancelled 分支也 set，避免任何仍在等的路径悬挂（无害）。
                    done["event"].set()
        finally:
            # 无论正常哨兵退出、超时退出还是异常，都唤醒所有仍在等的 caller。
            self._drain_pending()
            with __import__("contextlib").suppress(Exception):
                lib.adc_shutdown()

    def call(self, fn, *args, timeout=15.0, cancelable=False, owner=None):
        """在 worker 线程执行 fn(*args)，同步等结果。

        timeout 兜底：万一 worker 异常死亡（native 崩溃、adc_shutdown 卡死），
        也绝不让调用方无限期挂着——这是界面「停在停止中」的根因之一。

        cancelable=True（仅用于高频 drain 等可丢弃的维护调用）：超时后给 task
        打 cancelled 标记，worker 出队时会跳过、不执行。避免超时 task 变僵尸
        堆积占住 worker，拖垮收尾的 finalize。普通调用（write/finalize）不传，
        语义不变——它们超时是致命错误，也不能被静默丢弃。
        [真失败根治 v29] owner：把会话句柄存进 done，供收尾时按会话精准撤销
        排队中的 write_video 僵尸（多设备共享 worker 时只撤本会话、不误伤他机）。
        """
        if self._thread is None or not self._thread.is_alive():
            raise MFNativeError("MF worker 未启动")
        # [收尾根治 v22] cancelable 标记存进 done，供收尾时主动撤销排队任务。
        # [真失败根治 v29] owner 标记同上：write_video 用会话句柄标记，收尾前
        # 精准撤销该会话残留的排队写入，不让僵尸顶住 finalize。
        done = {"event": threading.Event(), "value": None, "error": None,
                "cancelled": False, "cancelable": cancelable, "owner": owner}
        self._q.put((fn, args, done))
        if not done["event"].wait(timeout):
            if cancelable:
                # 打标即可：worker 若还没取到该 task 会跳过；若已在执行则正常跑完
                # （native 不可中途打断，但只有一个在途，影响有限）。
                done["cancelled"] = True
            raise MFNativeError(f"MF worker 调用超时（{timeout:g}s 未返回）")
        if done["error"] is not None:
            raise done["error"]
        return done["value"]

    def drop_queued_cancelable(self):
        """[收尾根治 v22] 撤销队列中尚未执行的 cancelable 任务（仅 drain）。

        停止收尾的时序痛点：长录制切段（do_rotate，重量 Finalize+MoveFile+
        重建 writer，数十秒）占住单 worker 期间，200ms 定时器持续投递 drain；
        这些 drain 是 cancelable，但"取消"只在各自 call() 超时（10s）后才标记，
        切段结束时队尾仍有一批未超时、会真正执行的 drain 排在 finalize 前面，
        把 finalize 顶过 60s 超时（超时点第 5 次转移）。

        finalize 之前调用本方法，把队列里尚未出队的 cancelable drain 一次性
        标记 cancelled + set event：worker 出队时会跳过（复用既有机制），等待的
        drain 调用方也立即拿到错误而不必空等超时。音频完整性不受影响——finalize
        内部的 drain_audio() 会把 audio_q_ 有界排空写入 writer（v19 保证）。

        正在 worker 中执行的那一个 drain 已经出队、不在队列里，无法也不必撤销；
        它只占一个短任务，不影响 finalize 及时执行。返回撤销的任务数。
        """
        dropped = 0
        # queue.Queue 的内部 deque 有 mutex 保护；遍历期间 worker 可能出队，
        # 用 all_tasks 快照 + set event 是幂等且线程安全的（重复 set 无害）。
        with self._q.mutex:
            pending = list(self._q.queue)
        for _fn, _args, done in pending:
            if done.get("cancelable") and not done.get("cancelled"):
                done["cancelled"] = True
                dropped += 1
                # 唤醒正在 wait 的 drain 调用方，避免它们各自空等到 10s 超时。
                done["event"].set()
        return dropped

    def drop_queued_owner(self, owner):
        """[真失败根治 v29] 撤销队列中尚未执行的、属于指定 owner 的 write_video。

        背景：write_video 是高频非 cancelable 调用（数据帧不能像 drain 那样随手
        丢弃），但一旦 worker 因音频编码/慢盘掉速而排队超时，v21 的降级策略让
        读线程继续投递 → 每次超时留一个僵尸 write_video 在队列里。长录制下僵尸
        不断堆积，收尾时 finalize 投到队尾，被这些僵尸逐个执行顶过 60s 超时，
        屏障再排其后也超时，成片永远来不及改名落盘（真机 10min 收尾 224s、
        "未捞回已发布成片"即此病根）。

        根治时机：stop() 里 `_join_threads()` 之后读线程已彻底结束、不会再投递
        任何 write_video，此时队列里残留的 write_video 全是"迟到且无主"的僵尸。
        在 finalize 之前按本会话 owner 精准撤销（多设备共享 worker，绝不能误伤
        其它会话在途的帧），finalize 得以立即执行、成片及时落盘。尾部最多丢已
        在队列里未执行的几帧，远好过整段成片丢失 + 收尾卡死。

        正在 worker 中执行的那一个已出队、无法撤销，但它只占一个短任务，不挡
        finalize。返回撤销的 task 数；owner=None 时不撤销任何任务（防御误伤）。
        """
        return self._drop_queued_by_owner(owner, match_all=False)

    def drop_queued_all_owners(self):
        """[多设备收尾根治 v31] 撤销队列中尚未执行的**所有**会话的 write_video。

        v29 的 drop_queued_owner 只清指定 owner（本会话），但 stop_all 串行收尾时，
        先 stop 的会话 finalize 会排在**另一台仍在活跃投递**的 write_video 后面被
        顶过 60s（真机 2 台设备、其中一台中途重启，收尾 249s 仍丢成片即此病根）。
        本方法供 stop_all 在**所有 producer 已停止**后一次性清空全队列——此时不会有
        新写入投递，撤销全部迟到僵尸是安全的。owner=None 的调用（fill/诊断）不受影响。
        """
        return self._drop_queued_by_owner(None, match_all=True)

    def _drop_queued_by_owner(self, owner, match_all=False):
        """按 owner 撤销排队 write_video 的共用实现。match_all=True 时不分会话全清。"""
        if owner is None and not match_all:
            return 0
        dropped = 0
        # deque 有 mutex 保护；快照 + set event 幂等线程安全。
        with self._q.mutex:
            pending = list(self._q.queue)
        for _fn, _args, done in pending:
            o = done.get("owner")
            if o is None:
                continue    # 非 write_video（fill / 诊断调用）绝不撤销
            if not match_all and o != owner:
                continue
            if done.get("cancelled"):
                continue
            done["cancelled"] = True
            dropped += 1
            # 给仍在 wait 的调用方一个"调用超时"错误（而非 value=None 被误判
            # 成 native 错误）：读线程的 v21 降级逻辑认这个文本、记为诊断统计。
            if done.get("error") is None:
                done["error"] = MFNativeError("MF worker 调用超时（收尾撤销排队写入）")
            done["event"].set()
        return dropped

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
        i, ll = ctypes.c_int, ctypes.c_longlong
        lib.adc_init.argtypes = []; lib.adc_init.restype = i
        lib.adc_shutdown.argtypes = []; lib.adc_shutdown.restype = None
        lib.adc_last_error.argtypes = [ctypes.c_char_p, i]; lib.adc_last_error.restype = i
        # [构建指纹] 可选符号：老 DLL 没有 adc_build_id， getattr 取不到就跳过，
        # 绝不能像必需符号那样直接取属性（AttributeError 会让整个 DLL 判定不可用）。
        _stamp = getattr(lib, "adc_build_id", None)
        if _stamp is not None:
            _stamp.argtypes = []
            _stamp.restype = ctypes.c_char_p
        lib.adc_mic_start.argtypes = [ctypes.c_wchar_p, i, i, i]; lib.adc_mic_start.restype = i
        lib.adc_mic_stop.argtypes = []; lib.adc_mic_stop.restype = None
        lib.adc_mic_format.argtypes = [ctypes.POINTER(i)] * 3; lib.adc_mic_format.restype = i
        lib.adc_mic_device_events.argtypes = []; lib.adc_mic_device_events.restype = i
        lib.adc_session_create.argtypes = [
            ctypes.c_char_p, ctypes.c_char_p, i, i, i, i, i, i, i,
            ctypes.c_char_p, i]
        lib.adc_session_create.restype = ll
        lib.adc_session_write_video.argtypes = [ll, U8P, i]; lib.adc_session_write_video.restype = i
        # [收尾慢根治 v20] 可选符号：老 DLL 没有 adc_session_rotate。缺它时
        # write_video 沿用"内部同步切段"旧行为（返回 0），Python 不会收到 PENDING、
        # 也不会调用本符号——完美向后兼容，无需因缺符号判定整个 DLL 不可用。
        _rotate = getattr(lib, "adc_session_rotate", None)
        if _rotate is not None:
            _rotate.argtypes = [ll]; _rotate.restype = i
        lib.adc_session_mark_mic_stop.argtypes = [ll]; lib.adc_session_mark_mic_stop.restype = i
        lib.adc_session_drain_audio.argtypes = [ll]; lib.adc_session_drain_audio.restype = i
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

    def drop_queued_drains(self):
        """[收尾根治 v22] 撤销 worker 队列里尚未执行的音频 drain 任务。

        收尾 finalize 之前调用，避免切段期间堆积的 drain 把 finalize 顶过超时。
        返回撤销数；无 worker / 老封装 / 测试替身时降级为 0（向后兼容）。
        """
        w = self.worker
        if w is None:
            return 0
        try:
            return w.drop_queued_cancelable()
        except Exception:  # noqa: BLE001  老 worker 无此方法时静默降级
            return 0

    def drop_queued_video_writes(self, owner):
        """[真失败根治 v29] 撤销 worker 队列里尚未执行的、本会话的 write_video。

        收尾 finalize 之前调用，撤销长录制中因 worker 掉速超时而堆积的僵尸写入，
        让 finalize 立即执行、成片及时落盘。按 owner（会话句柄）精准过滤，多设备
        共享 worker 时不误伤其它会话。老 worker / 测试替身降级为 0（向后兼容）。
        """
        w = self.worker
        if w is None:
            return 0
        try:
            return w.drop_queued_owner(owner)
        except Exception:  # noqa: BLE001  老 worker 无此方法时静默降级
            return 0

    def drop_all_video_writes(self):
        """[多设备收尾根治 v31] 撤销 worker 队列里所有会话未执行的 write_video。

        供 stop_all 在停掉所有 producer 后、逐个 finalize 前一次性调用，避免某台
        设备的迟到写入顶住另一台设备的 finalize。老 worker / 替身降级为 0。
        """
        w = self.worker
        if w is None:
            return 0
        try:
            return w.drop_queued_all_owners()
        except Exception:  # noqa: BLE001  老 worker 无此方法时静默降级
            return 0

    def worker_barrier(self, timeout=30.0):
        """[收尾根治 v22] 投递屏障并等待，确认此前入队的 native 调用已执行完。

        finalize 超时后，其 task 仍非 cancelable 地留在 worker 队列里、最终会
        执行并落盘 .mp4。投递一个空任务到队尾，FIFO 保证它排在该 finalize
        之后；屏障返回即证明 finalize 已跑完，此时再扫描 work_dir 能捞回产物。
        屏障自身也用有界超时，worker 真卡死时不无限等待。
        [真失败根治 v28] 默认 30s，但它必须覆盖 finalize 最坏耗时（60s 含慢盘
        改名）才能等到成片落盘；stop() 超时兜底改为显式传 90s。测试替身请接收
        timeout 参数。
        """
        w = self.worker
        if w is None:
            return False
        try:
            w.call(lambda: True, timeout=timeout)
            return True
        except Exception:  # noqa: BLE001
            return False

    def last_error(self):
        if not self.available:
            return self._error
        buf = ctypes.create_string_buffer(1024)
        with __import__("contextlib").suppress(Exception):
            self._lib.adc_last_error(buf, len(buf))
        return buf.value.decode("utf-8", "replace").strip()

    def build_id(self):
        """返回 native DLL 的构建指纹；老 DLL（无此导出）返回空串。

        不抛异常、不要求 worker：这是纯静态串，可在任意线程读取。调用方在
        启动日志里显示它，用于确认「0xC00D4A45 三根因修复」是否已编译进 DLL。
        """
        if not self.available:
            return ""
        stamp = getattr(self._lib, "adc_build_id", None)
        if stamp is None:
            return ""
        try:
            raw = stamp()
            return (raw or b"").decode("utf-8", "replace").strip() if isinstance(raw, bytes) else ""
        except Exception:  # noqa: BLE001  诊断信息，绝不因它打断录制
            return ""

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
        """写入一条 NAL；返回 True 表示 native 请求分段旋转（须尽快调 session_rotate）。

        [收尾慢根治 v20] 老 DLL 的 write_video 到阈值会在内部同步切段后返回 0，
        新 DLL 则只返回 ADC_ROTATE_PENDING=1、把重量切段交给 session_rotate。
        本方法把该信号透传给调用方（_read_loop），后者据此显式驱动切段。
        """
        buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        # [修复-收尾慢·v18] 用独立的 write_video 超时（30s），不再走默认 15s：
        # 15s 会被 native 内部一次无上限的积压音频排空顶过，误报致命失败。
        # [真失败根治 v29] owner=h：收尾前可按会话精准撤销队列里残留的写入僵尸，
        # 让 finalize 立即执行（多设备共享 worker 不误伤他机会话）。
        rc = self.worker.call(self._lib.adc_session_write_video, h, buf, len(data),
                              timeout=VIDEO_WRITE_CALL_TIMEOUT_S, owner=h)
        if rc == ADC_ROTATE_PENDING:
            return True
        if rc != ADC_OK:
            raise MFNativeError(self.last_error())
        return False

    def session_rotate(self, h):
        """[收尾慢根治 v20] 执行分段旋转（Finalize 当前段+发布+重建 writer）。

        仅在 write_video 返回 ROTATE_PENDING 后调用。重量操作走独立的 120s 超时，
        不再占用高频 write_video 的 30s 预算。老 DLL 无此符号：调用方须先以
        hasattr/native 能力探测，或直接 suppress（老 DLL 不会返回 PENDING，
        因此本方法永远不会被触发）。"""
        rot = getattr(self._lib, "adc_session_rotate", None)
        if rot is None:            # 老 DLL：无独立切段能力，no-op（其 write_video 已内部切段）
            return
        rc = self.worker.call(rot, h, timeout=ROTATE_CALL_TIMEOUT_S)
        if rc != ADC_OK:
            raise MFNativeError(self.last_error())

    def session_drain_audio(self, h):
        """主动排空该会话的音频队列（经 worker 线程，满足 SinkWriter 单线程约束）。

        定时器每 200ms 调用一次，使音频写入与视频帧解耦。视频流稀疏/中断时，
        视频帧驱动不到 drain，靠这个定时器保证音频持续写入、队列不积压。
        """
        # cancelable=True：drain 是每 200ms 的尽力维护调用，超时即弃、不留僵尸
        # 占住 worker（否则堆积拖垮收尾 finalize）。音频完整性由 finalize 内部
        # 的 drain_audio() 兜底保证。
        return self.worker.call(self._lib.adc_session_drain_audio, h,
                                timeout=DRAIN_CALL_TIMEOUT_S, cancelable=True)

    def session_finalize(self, h):
        out = ctypes.create_string_buffer(8192)
        rc = self.worker.call(self._lib.adc_session_finalize, h, out, len(out),
                              timeout=FINALIZE_CALL_TIMEOUT_S)
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
