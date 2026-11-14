"""
backend.audio_service —— 音频采集（电脑麦克风 / 设备端）+ ffmpeg 合成。

  * MicRecorder        Windows 下用 WinMM waveIn 录电脑麦克风到本地 WAV
  * DeviceAudioCapture 设备端用 tinycap 录设备声音（需固件带 tinycap）
  * ffmpeg_mux(...)    把视频 + 若干 WAV 混流为一个带音视频的 MP4（尽力而为）

所有函数不依赖 UI；通过 controller 的 bus 推送 tool 状态。非 Windows 平台 MicRecorder
会在 start() 抛出可读错误，由调用方提示「仅 Windows 支持电脑麦克风」。
"""
import ctypes
import os
import subprocess
import tempfile
import threading
import time

from backend.device_proc import kill_device_process
from core.constants import (
    _WAVEHDR,
    adb_kwargs,
    adb_popen_kwargs,
    safe_name,
    unique_path,
)
from core.longpath import long_path, path_exists, path_getsize

# MMSYSERR / WAVERR 里最常见的几个：报错时直接翻成人话，用户才知道该动哪里。
_MM_ERROR_TEXT = {
    1: "未指明的错误",
    2: "设备号越界（这台机器上没有这个录音设备）",
    4: "设备已被占用（别的程序正在录音？）",
    5: "句柄无效",
    6: "没有可用的音频驱动",
    7: "内存不足",
    8: "设备不支持该操作",
    11: "参数无效",
    12: "句柄正被占用",
    32: "设备不支持该音频格式（声道 / 采样率 / 位深）",
}

# 电脑麦克风按顺序尝试的采集格式：(声道, 采样率)。
_MIC_FORMATS = ((2, 44100), (2, 48000), (1, 48000), (1, 44100), (1, 16000))


def _check_mmresult(mr, what):
    """WinMM 调用返回非 0 就抛可读异常（0 / None 视为成功）。"""
    if not mr:
        return
    raise RuntimeError("{} 失败，错误码 {}（{}）".format(what, mr, _MM_ERROR_TEXT.get(mr, "未知错误")))


def _have_ffmpeg():
    try:
        r = subprocess.run(["ffmpeg", "-version"], **adb_kwargs(10))
        return r.returncode == 0
    except Exception:
        return False


def _wav_duration(path):
    """读出 WAV 的 data 段字节数（不是秒数）；解析不出返回 None。"""
    try:
        total = path_getsize(path)
        with open(long_path(path), "rb") as f:
            head = f.read(12)
            if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
                return None
            fmt_seen = False
            for _ in range(8):
                ch = f.read(8)
                if len(ch) < 8:
                    return None
                cid = ch[:4]
                csize = int.from_bytes(ch[4:8], "little")
                if cid == b"fmt ":
                    fmt_seen = True
                    f.seek(csize + (csize & 1), os.SEEK_CUR)
                elif cid == b"data":
                    if not fmt_seen:
                        return None
                    actual = max(0, total - f.tell())
                    if actual <= 0:
                        return None
                    return min(csize, actual)
                else:
                    f.seek(csize + (csize & 1), os.SEEK_CUR)
            return None
    except Exception:
        return None


def _wav_ok(path):
    """WAV 是否**真正可用**：头合法 **且** 含实际音频数据。"""
    try:
        if not path_exists(path):
            return False
        if path_getsize(path) < 44:
            return False
        with open(long_path(path), "rb") as f:
            head = f.read(12)
        if head[:4] != b"RIFF" or head[8:12] != b"WAVE":
            return False
        n = _wav_duration(path)
        return n is not None and n > 0
    except Exception:
        return False


def _mp4_playable(path):
    """合成产物是否是一个真能播的 mp4（含视频流、时长 > 0、体积合理）。"""
    try:
        if not path_exists(path):
            return False
        size = path_getsize(path)
        if size < 4096:
            return False
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
                **adb_kwargs(20))
            if r.returncode == 0:
                return "video" in (r.stdout or "")
        except Exception:
            pass
        with open(long_path(path), "rb") as f:
            return b"moov" in f.read(min(size, 4 * 1024 * 1024))
    except Exception:
        return False


def _mp4_duration(path):
    """从 MP4 的 moov/mvhd 盒子里解析时长（秒，字符串）；解析不出返回 None。"""
    try:
        total = path_getsize(path)
        if total < 16:
            return None
        with open(long_path(path), "rb") as f:
            moov = None
            pos = 0
            while pos + 8 <= total:
                f.seek(pos)
                hdr = f.read(8)
                if len(hdr) < 8:
                    break
                bsize = int.from_bytes(hdr[:4], "big")
                btype = hdr[4:8]
                if bsize == 1:
                    ext = f.read(8)
                    if len(ext) < 8:
                        break
                    bsize = int.from_bytes(ext, "big")
                    body = pos + 16
                elif bsize == 0:
                    bsize = total - pos
                    body = pos + 8
                else:
                    body = pos + 8
                if bsize < 8 or pos + bsize > total:
                    break
                if btype == b"moov":
                    moov = (body, bsize - 8)
                    break
                pos += bsize
            if moov is None:
                return None
            pos, end = moov[0], moov[0] + moov[1]
            while pos + 8 <= end:
                f.seek(pos)
                hdr = f.read(8)
                if len(hdr) < 8:
                    break
                bsize = int.from_bytes(hdr[:4], "big")
                btype = hdr[4:8]
                if bsize == 1:
                    ext = f.read(8)
                    bsize = int.from_bytes(ext, "big")
                    sub_body = pos + 16
                elif bsize == 0:
                    bsize = end - pos
                    sub_body = pos + 8
                else:
                    sub_body = pos + 8
                if bsize < 8 or pos + bsize > end:
                    break
                if btype == b"mvhd":
                    f.seek(sub_body)
                    ver = f.read(1)
                    f.read(3)
                    if ver == b"\x01":
                        f.read(16)
                    else:
                        f.read(8)
                    timescale = int.from_bytes(f.read(4), "big")
                    if ver == b"\x01":
                        duration = int.from_bytes(f.read(8), "big")
                    else:
                        duration = int.from_bytes(f.read(4), "big")
                    if timescale > 0 and duration > 0:
                        return "%.3f" % (duration / float(timescale))
                    return None
                pos += bsize
        return None
    except Exception:
        return None


def _video_duration(path):
    """视频时长（秒，字符串）：ffprobe 优先，取不到再本地解析 MP4 头兜底。"""
    d = _media_duration(path)
    if d:
        return d
    return _mp4_duration(path)


def ffmpeg_mux(video_path, audio_paths, out_path):
    """把 video + 若干 wav 合成为带音视频的 mp4；成功返回路径，否则 None。

    关键修正（均为「合成结果播放不了」的根因）：

    1. **不全局用 -shortest**：它按「最短的流」截断整段输出，音频只录到一半时会连
       视频一起砍掉。改为只让**音频**收尾在视频时长内。
    2. **音频不足则补静音**：音频比视频短时用 `apad` 补齐，长了则 `atrim` 截断。
    3. **复核产物**：`returncode == 0` 不代表产物可播。产出后用 `_mp4_playable` 复核。
    4. **时长取不到就不合成**：`apad` 会无限补静音，没有 `-t` ffmpeg 永远不会收尾。
    """
    if not _have_ffmpeg():
        return None
    if not (video_path and path_exists(video_path)):
        return None
    audios = [a for a in (audio_paths or []) if a and _wav_ok(a)]
    if not audios:
        return None
    duration = _video_duration(video_path)
    if not duration:
        return None
    cmd = ["ffmpeg", "-y", "-i", video_path]
    for a in audios:
        cmd += ["-i", a]
    mix = "amix=inputs=%d:duration=longest:dropout_transition=0,apad[a]" % len(audios)
    cmd += ["-filter_complex", mix,
            "-map", "0:v:0", "-map", "[a]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
            "-t", duration,
            out_path]
    try:
        r = subprocess.run(cmd, **adb_kwargs(300))
        if r.returncode == 0 and path_exists(out_path):
            if _mp4_playable(out_path):
                return out_path
            _silent_remove(out_path)
        else:
            _silent_remove(out_path)
    except Exception:
        _silent_remove(out_path)
    return None


def _media_duration(path):
    """用 ffprobe 取媒体时长（秒，字符串）；取不到返回 None。"""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path], **adb_kwargs(20))
        if r.returncode == 0:
            v = (r.stdout or "").strip().rstrip(",")
            return v if v and v != "N/A" else None
    except Exception:
        pass
    return None


def _silent_remove(path):
    try:
        if path and os.path.exists(long_path(path)):
            os.remove(long_path(path))
    except Exception:
        pass


class DeviceAudioCapture:
    """设备端 tinycap 录音（写入 /data/local/tmp 下 wav，停止后 pull 回本地）。"""

    @staticmethod
    def supported(adb, serial):
        try:
            r = subprocess.run(
                [adb, "-s", serial, "shell", "command", "-v", "tinycap"],
                **adb_kwargs(10))
            return r.returncode == 0 and "tinycap" in (r.stdout or "")
        except Exception:
            return False

    def __init__(self, adb="adb"):
        self.adb = adb
        self._procs = {}
        self._lock = threading.Lock()

    def is_recording(self, serial):
        """该设备是否正在进行 tinycap 采集（供 root 切换保护等场景探测）。"""
        with self._lock:
            return serial in self._procs

    def start(self, serial, remote_wav):
        """启动设备端 tinycap，返回是否成功（需要原因请用 start_ex）。"""
        return self.start_ex(serial, remote_wav)[0]

    def start_ex(self, serial, remote_wav):
        """启动设备端 tinycap，返回 `(ok, 原因)`。"""
        with self._lock:
            if serial in self._procs:
                return False, "该设备已在采集设备音频"
        try:
            proc = subprocess.Popen(
                [self.adb, "-s", serial, "shell", "tinycap", remote_wav],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                **adb_popen_kwargs())
        except Exception as e:
            return False, "无法启动 tinycap：{}".format(e)
        rc = None
        try:
            if proc.poll() is None:
                time.sleep(1.0)
            rc = proc.poll()
        except Exception:
            pass
        if rc is not None:
            return False, ("tinycap 启动后立即退出（退出码 {}）："
                           "多数机型需要 root 才能录设备端声音，可先执行 adb root 再试".format(rc))
        with self._lock:
            self._procs[serial] = (proc, remote_wav)
        return True, ""

    def stop(self, serial):
        """停止并 pull 回本地临时文件，返回本地 wav 路径或 None。"""
        with self._lock:
            item = self._procs.pop(serial, None)
        if item is None:
            return None
        proc, remote_wav = item
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        kill_device_process(self.adb, serial, "tinycap")
        local = None
        tmp = os.path.join(
            tempfile.gettempdir(),
            "adb_devaudio_{}_{}.wav".format(safe_name(serial), time.strftime("%H%M%S")))
        for attempt in range(5):
            try:
                r = subprocess.run(
                    [self.adb, "-s", serial, "pull", remote_wav, tmp],
                    **adb_kwargs(60))
                if r.returncode == 0 and _wav_ok(tmp):
                    local = tmp
                    break
            except Exception:
                pass
            time.sleep(0.5 * (attempt + 1))
        if local is None:
            try:
                if os.path.exists(long_path(tmp)):
                    os.remove(long_path(tmp))
            except Exception:
                pass
        try:
            subprocess.run([self.adb, "-s", serial, "shell", "rm", "-f", remote_wav],
                           **adb_kwargs(10))
        except Exception:
            pass
        return local


class MicRecorder:
    """Windows 下用 WinMM waveIn 录制电脑麦克风到 WAV。

    使用回调方式持续捕获；stop() 后写标准 WAV 头。非 Windows 抛 RuntimeError。
    """

    def __init__(self, channels=2, rate=44100, sample_bits=16):
        if os.name != "nt":
            raise RuntimeError("电脑麦克风录音仅支持 Windows（依赖 WinMM waveIn）")
        self.channels = channels
        self.rate = rate
        self.sample_bits = sample_bits
        self._chunks = []
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._running = False
        self._path = None
        self._callback = None
        self._wavein = None

    def _open(self):
        winmm = ctypes.windll.winmm

        WAVE_FORMAT_PCM = 1
        CALLBACK_FUNCTION = 0x30000

        class WAVEFORMATEX(ctypes.Structure):
            _fields_ = [
                ("wFormatTag", ctypes.c_ushort),
                ("nChannels", ctypes.c_ushort),
                ("nSamplesPerSec", ctypes.c_uint),
                ("nAvgBytesPerSec", ctypes.c_uint),
                ("nBlockAlign", ctypes.c_ushort),
                ("wBitsPerSample", ctypes.c_ushort),
                ("cbSize", ctypes.c_ushort),
            ]

        self._winmm = winmm
        self._WAVEFORMATEX = WAVEFORMATEX
        try:
            winmm.waveInOpen.argtypes = [
                ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint,
                ctypes.POINTER(WAVEFORMATEX), ctypes.c_void_p,
                ctypes.c_void_p, ctypes.c_uint]
            winmm.waveInOpen.restype = ctypes.c_int
            winmm.waveInPrepareHeader.argtypes = [
                ctypes.c_void_p, ctypes.POINTER(_WAVEHDR), ctypes.c_uint]
            winmm.waveInPrepareHeader.restype = ctypes.c_int
            winmm.waveInAddBuffer.argtypes = [
                ctypes.c_void_p, ctypes.POINTER(_WAVEHDR), ctypes.c_uint]
            winmm.waveInAddBuffer.restype = ctypes.c_int
            winmm.waveInStart.argtypes = [ctypes.c_void_p]
            winmm.waveInStart.restype = ctypes.c_int
            winmm.waveInStop.argtypes = [ctypes.c_void_p]
            winmm.waveInStop.restype = ctypes.c_int
            winmm.waveInReset.argtypes = [ctypes.c_void_p]
            winmm.waveInReset.restype = ctypes.c_int
            winmm.waveInUnprepareHeader.argtypes = [
                ctypes.c_void_p, ctypes.POINTER(_WAVEHDR), ctypes.c_uint]
            winmm.waveInUnprepareHeader.restype = ctypes.c_int
            winmm.waveInClose.argtypes = [ctypes.c_void_p]
            winmm.waveInClose.restype = ctypes.c_int
        except AttributeError:
            pass
        WAVE_CALLBACK = ctypes.CFUNCTYPE(
            None, ctypes.c_void_p, ctypes.c_uint,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)

        def _cb(hwi, uMsg, dwInstance, dwParam1, dwParam2):
            if uMsg != 0x3C0:
                return
            hdr = ctypes.cast(dwParam1, ctypes.POINTER(_WAVEHDR)).contents
            n = hdr.dwBytesRecorded
            if n and hdr.lpData:
                with self._lock:
                    self._chunks.append(ctypes.string_at(hdr.lpData, n))
                    self._collected.add(int(hdr.lpData or 0))
            if not self._stop.is_set():
                try:
                    winmm.waveInAddBuffer(
                        hwi, ctypes.cast(dwParam1, ctypes.POINTER(_WAVEHDR)),
                        ctypes.sizeof(_WAVEHDR))
                except Exception:
                    pass

        self._callback = WAVE_CALLBACK(_cb)
        self._wavein = None
        last_err = None
        for channels, rate in _MIC_FORMATS:
            block_align = channels * (self.sample_bits // 8)
            fmt = WAVEFORMATEX(
                WAVE_FORMAT_PCM, channels, rate,
                rate * block_align, block_align, self.sample_bits, 0)
            phwi = ctypes.c_void_p()
            mr = winmm.waveInOpen(
                ctypes.byref(phwi), 0, ctypes.byref(fmt),
                ctypes.cast(self._callback, ctypes.c_void_p),
                0, CALLBACK_FUNCTION)
            if not mr:
                self.channels, self.rate = channels, rate
                self._fmt = fmt
                self._wavein = phwi
                break
            last_err = mr
            if mr != 32:
                break
        if self._wavein is None:
            _check_mmresult(last_err, "waveInOpen")
            raise RuntimeError("waveInOpen 失败（未返回错误码）")
        phwi = self._wavein

        self._hdrs = []
        self._collected = set()
        buf_size = 4096
        for _ in range(4):
            buf = ctypes.create_string_buffer(buf_size)
            hdr = _WAVEHDR()
            hdr.lpData = ctypes.cast(buf, ctypes.c_void_p)
            hdr.dwBufferLength = buf_size
            hdr.dwFlags = 0
            _check_mmresult(
                winmm.waveInPrepareHeader(phwi, ctypes.byref(hdr),
                                          ctypes.sizeof(_WAVEHDR)),
                "waveInPrepareHeader")
            _check_mmresult(
                winmm.waveInAddBuffer(phwi, ctypes.byref(hdr),
                                      ctypes.sizeof(_WAVEHDR)),
                "waveInAddBuffer")
            self._hdrs.append((hdr, buf))
        _check_mmresult(winmm.waveInStart(phwi), "waveInStart")

    def start(self, save_dir):
        if self._running:
            return False, "已在录音"
        try:
            os.makedirs(long_path(save_dir), exist_ok=True)
        except Exception as e:
            return False, "无法创建目录：{}".format(e)
        ts = time.strftime("%Y%m%d_%H%M%S")
        self._path = unique_path(os.path.join(save_dir, "mic_{}.wav".format(ts)))
        self._chunks = []
        self._collected = set()
        self._stop.clear()
        try:
            self._open()
        except Exception:
            self._release_device()
            raise
        self._running = True
        return True, self._path

    def stop(self):
        """停止并返回本地 WAV 路径；**没录到任何音频时返回 None**（不产出空文件）。"""
        if not self._running:
            return None
        self._stop.set()
        winmm = self._winmm
        try:
            winmm.waveInStop(self._wavein)
        except Exception:
            pass
        self._drain_buffers()
        try:
            winmm.waveInReset(self._wavein)
        except Exception:
            pass
        self._running = False
        self._release_device()
        self._write_wav()
        if self._path and path_exists(self._path) and not _wav_ok(self._path):
            _silent_remove(self._path)
            self._path = None
            return None
        return self._path

    def _release_device(self):
        winmm = getattr(self, "_winmm", None)
        hwi = getattr(self, "_wavein", None)
        if winmm is None or hwi is None:
            return
        try:
            for hdr, _buf in getattr(self, "_hdrs", []):
                winmm.waveInUnprepareHeader(
                    hwi, ctypes.byref(hdr), ctypes.sizeof(_WAVEHDR))
        except Exception:
            pass
        try:
            winmm.waveInClose(hwi)
        except Exception:
            pass
        self._wavein = None

    def _drain_buffers(self):
        collected = getattr(self, "_collected", None)
        if collected is None:
            collected = self._collected = set()
        for hdr, _buf in getattr(self, "_hdrs", []):
            try:
                if int(hdr.lpData or 0) in collected:
                    continue
                n = hdr.dwBytesRecorded
                if n and hdr.lpData:
                    with self._lock:
                        self._chunks.append(ctypes.string_at(hdr.lpData, n))
                        collected.add(int(hdr.lpData or 0))
            except Exception:
                continue

    def _write_wav(self):
        with self._lock:
            data = b"".join(self._chunks)
        self._chunks = []
        block_align = self.channels * (self.sample_bits // 8)
        if block_align > 1 and len(data) % block_align:
            data = data[:-(len(data) % block_align)]
        import struct
        size = len(data)
        with open(long_path(self._path), "wb") as f:
            f.write(b"RIFF")
            f.write(struct.pack("<I", 36 + size))
            f.write(b"WAVEfmt ")
            f.write(struct.pack("<IHHIIHH", 16, 1, self.channels, self.rate,
                                self.rate * block_align, block_align,
                                self.sample_bits))
            f.write(b"data")
            f.write(struct.pack("<I", size))
            f.write(data)
