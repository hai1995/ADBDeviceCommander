# -*- coding: utf-8 -*-
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
    _WAVEHDR, adb_kwargs, adb_popen_kwargs, safe_name, unique_path)


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


def _check_mmresult(mr, what):
    """WinMM 调用返回非 0 就抛可读异常（0 / None 视为成功）。

    这些接口**返回错误码而不抛异常**，不校验就等于「什么都没发生」：
    waveInStart 失败时 start() 照样返回成功，界面显示「录音中」，停止后却
    一句「未录到声音」—— 用户以为是自己没说话。校验之后错误当场就有名字。
    """
    if not mr:
        return
    raise RuntimeError("%s 失败，错误码 %s（%s）"
                       % (what, mr, _MM_ERROR_TEXT.get(mr, "未知错误")))


def _have_ffmpeg():
    try:
        r = subprocess.run(["ffmpeg", "-version"], **adb_kwargs(10))
        return r.returncode == 0
    except Exception:
        return False


def _wav_duration(path):
    """读出 WAV 的 data 段字节数（不是秒数）；解析不出返回 None。

    只认「标准 44 字节 RIFF/WAVE 头 + fmt + data」的 PCM WAV —— 也就是本模块自己
    写出的那种。tinycap 写出的头有时字段顺序不同，宁可判为不可用也不要喂给 ffmpeg。
    """
    try:
        total = os.path.getsize(path)
        with open(path, "rb") as f:
            head = f.read(12)
            if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
                return None
            fmt_seen = False
            # fmt 块之后紧跟 data 块；逐块跳过，遇到 data 立即返回长度
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
                    # 必须先见过 fmt 块：只有 RIFF/WAVE + data 而没有 fmt 的文件
                    # 不是可解码的 PCM（可能是个坏文件或别的容器），喂给 ffmpeg
                    # 只会得到一个 0 秒的空壳视频。
                    if not fmt_seen:
                        return None
                    # 文件实际长度才是权威：有的写头时把长度写大，有的干脆
                    # 写 0xFFFFFFFF（流式 WAV）。早前用**头里的** riff_size 反算
                    # 「剩余字节」，等于用头校验头 —— 一段被截断的残录音仍会被
                    # 认为「有几十 KB 音频」，通过 _wav_ok 后直接喂给 ffmpeg。
                    actual = max(0, total - f.tell())
                    if actual <= 0:
                        return None          # data 段一个字节都没有
                    return min(csize, actual)
                else:
                    f.seek(csize + (csize & 1), os.SEEK_CUR)
            return None
    except Exception:
        return None


def _wav_ok(path):
    """WAV 是否**真正可用**：头合法 **且** 含实际音频数据。

    早期实现只查「头是 RIFF/WAVE 且体积 >= 44 字节」，于是「录了 0 字节」的空音频
    （正好 44 字节）会被判为可用并喂给 ffmpeg —— ffmpeg 对纯静音/零长度输入会输出一个
    258 字节、`duration=N/A` 的空壳 mp4，用户表现为「合成出来的视频打不开」。
    这里额外要求 data 段有真实字节数。
    """
    try:
        if not os.path.exists(path):
            return False
        if os.path.getsize(path) < 44:
            return False
        with open(path, "rb") as f:
            head = f.read(12)
        if head[:4] != b"RIFF" or head[8:12] != b"WAVE":
            return False
        n = _wav_duration(path)
        return n is not None and n > 0
    except Exception:
        return False


def _mp4_playable(path):
    """合成产物是否是一个真能播的 mp4（含视频流、时长 > 0、体积合理）。

    ffmpeg 退出码为 0 **不代表**产物可用：音频为空/过短时它会成功输出一个几百字节、
    没有有效时长的空壳文件。这里用 ffprobe（或退化为扫 moov + 体积兜底）复核，
    避免把坏文件当成功结果交给用户。
    """
    try:
        if not os.path.exists(path):
            return False
        size = os.path.getsize(path)
        # 正常 1 帧视频都远大于 4KB；低于此值基本可判定为空壳
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
        # 没有 ffprobe 时退化为「体积 + moov 头」兜底判断
        with open(path, "rb") as f:
            return b"moov" in f.read(min(size, 4 * 1024 * 1024))
    except Exception:
        return False


def _mp4_duration(path):
    """从 MP4 的 moov/mvhd 盒子里解析时长（秒，字符串）；解析不出返回 None。

    不依赖 ffprobe：个别环境只装了 ffmpeg 却没装 ffprobe（或不在 PATH），
    `_media_duration` 会取不到值。旧实现在此时给 ffmpeg 传 `-t 0`——按 0 秒
    截断，产出空壳 mp4（随后被 `_mp4_playable` 拒掉并回退，音频整体丢失）。
    这里按盒子结构顺序 seek 扫描（screenrecord 的 moov 在文件**尾部**，
    不能只读文件头），拿到 mvhd 的 timescale/duration 后换算。
    """
    try:
        total = os.path.getsize(path)
        if total < 16:
            return None
        with open(path, "rb") as f:
            moov = None
            pos = 0
            while pos + 8 <= total:
                f.seek(pos)
                hdr = f.read(8)
                if len(hdr) < 8:
                    break
                bsize = int.from_bytes(hdr[:4], "big")
                btype = hdr[4:8]
                if bsize == 1:                       # 64 位扩展大小
                    ext = f.read(8)
                    if len(ext) < 8:
                        break
                    bsize = int.from_bytes(ext, "big")
                    body = pos + 16
                elif bsize == 0:                     # 延伸到文件尾
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
                    f.read(3)                         # flags
                    if ver == b"\x01":                # version 1：64 位时间戳
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
       视频一起砍掉（实测 6s 视频 + 2s 音频 → 成片只剩 2s）。改为只让**音频**收尾在
       视频时长内（`-shortest` 仅作用于 filter_complex 的音频输出），视频完整保留。
    2. **音频不足则补静音**：音频比视频短时用 `apad` 补齐，长了则 `atrim` 截断，
       保证音轨与画面等长—— 否则末尾会有一段无声冻帧。
    3. **复核产物**：`returncode == 0` 不代表产物可播（零长度音频会产出 258 字节的
       空壳 mp4，duration=N/A）。产出后用 `_mp4_playable` 复核，不通过则删除并返回
       None，让调用方回退到「保留无音轨视频」。
    4. **时长取不到就不合成**：`apad` 会无限补静音，没有 `-t` ffmpeg 永远不会收尾；
       而传 `-t 0` 会截出空壳文件。故时长（ffprobe / 本地解析 MP4 头都取不到）未知
       时直接返回 None，调用方保留无音轨的原始视频，绝不产出坏文件。
    """
    if not _have_ffmpeg():
        return None
    if not (video_path and os.path.exists(video_path)):
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
    # 视频流直接复制（不重编码，保留 screenrecord 的原始画质与速度）；
    # 音频把所有输入混为单条立体声。
    # 两处容易踩的坑（实测报错）：
    #   a) 视频**不能**进 filter_complex（写成 [0:v]copy 会报 "Streamcopy requested for
    #      output stream fed from a complex filtergraph"），用 -map 0:v:0 直接引用原流。
    #   b) apad 也**不能**用独立的 -af（与复杂滤镜图同时作用于同一流会报
    #      "Simple and complex filtering cannot be used together"），必须写进滤镜图里。
    mix = "amix=inputs=%d:duration=longest:dropout_transition=0,apad[a]" % len(audios)
    cmd += ["-filter_complex", mix,
            "-map", "0:v:0", "-map", "[a]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
            "-t", duration,
            out_path]
    try:
        r = subprocess.run(cmd, **adb_kwargs(300))
        if r.returncode == 0 and os.path.exists(out_path):
            # 复核：ffmpeg 成功也可能产出空壳（音频为空/过短时）
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
        if path and os.path.exists(path):
            os.remove(path)
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
        with self._lock:
            if serial in self._procs:
                return False
        try:
            proc = subprocess.Popen(
                [self.adb, "-s", serial, "shell", "tinycap", remote_wav],
                # 输出丢弃而不挂管道：录制期间没有任何代码读它，若设备端/本地 adb
                # 往这条管道写满 64KB，写入方会阻塞，把整个采集链路拖死。
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                **adb_popen_kwargs())
        except Exception:
            return False
        # 探测 tinycap 是否真的跑起来了：很多 ROM 上 tinycap 需要 root，会立刻退出，
        # 而 supported() 只查了 `command -v tinycap`。不做这一步，start() 会对一个
        # 已经死掉进程返回 True —— 状态栏照样显示「（含设备音频）」，停止时 pull
        # 必然失败，用户最终拿到一段没有声音的视频且不知道原因。
        try:
            if proc.poll() is None:
                time.sleep(1.0)
            if proc.poll() is not None:
                return False
        except Exception:
            pass
        with self._lock:
            self._procs[serial] = (proc, remote_wav)
        return True

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
        # 与录屏同理：tinycap 只在 SIGINT（Ctrl-C）下优雅收尾并写回 wav 头。
        # 本地 adb 退出不代表设备端 tinycap 也退了，故显式收尾，避免孤儿进程占用音频输入。
        # 收尾顺序统一走 backend.device_proc（按 PID `kill -INT` → **等它写完 RIFF 头**
        # → 仍存活才补 `-TERM`）：早期把 -INT 与 -TERM 背靠背发出去，tinycap 很可能死
        # 在补写 wav 头的中途，拉回来的就是一个播不了的残文件。
        kill_device_process(self.adb, serial, "tinycap")
        local = None
        # 必须用 tempfile.gettempdir() 而不是 os.environ["TEMP"]：Windows 上
        # 后者通常存在，但非 Windows（开发态 / 调试脚本）或环境被裁剪（服务、
        # 精简启动器）时它是空的，早前的 `os.environ.get("TEMP", ".")` 就把
        # 录音直接写进了**当前工作目录**——项目根下那一堆 adb_devaudio_*.wav
        # 就是这么来的。gettempdir() 走 TEMP/TMPDIR 再兜底 /tmp，永远有值。
        tmp = os.path.join(
            tempfile.gettempdir(),
            # safe_name：无线序列号含冒号，Windows 临时文件名会非法
            "adb_devaudio_%s_%s.wav" % (safe_name(serial), time.strftime("%H%M%S")))
        # pull 带重试（容忍收尾/落盘延迟）；并校验 wav 头，损坏则丢弃，避免污染合成视频
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
            # 五轮都没拿到可用的 wav（pull 失败 / 文件头不完整 / 设备端还没写完）：
            # 把已经落盘的残片删掉。它不会被合成，留在 TEMP 里既白占空间，
            # 又让人看到 adb_devaudio_*.wav 误以为这次录音是好的。
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
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

    # ---- WinMM 封装 ----
    def _open(self):
        # ctypes 在模块级导入：stop() 也要用它（waveInUnprepareHeader / byref / sizeof）。
        # 早期版本把它放在本函数内局部导入，stop() 里便成了未定义名，抛出的
        # NameError 又被下面的 try/except 吞掉 —— 结果缓冲区从未 unprepare。
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

        block_align = self.channels * (self.sample_bits // 8)
        fmt = WAVEFORMATEX(
            WAVE_FORMAT_PCM, self.channels, self.rate,
            self.rate * block_align, block_align, self.sample_bits, 0)

        self._winmm = winmm
        self._WAVEFORMATEX = WAVEFORMATEX
        phwi = ctypes.c_void_p()
        WAVE_CALLBACK = ctypes.CFUNCTYPE(
            None, ctypes.c_void_p, ctypes.c_uint,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)

        def _cb(hwi, uMsg, dwInstance, dwParam1, dwParam2):
            if uMsg != 0x3C0:   # WIM_DATA
                return
            hdr = ctypes.cast(dwParam1, ctypes.POINTER(_WAVEHDR)).contents
            n = hdr.dwBytesRecorded
            if n and hdr.lpData:
                with self._lock:
                    self._chunks.append(ctypes.string_at(hdr.lpData, n))
                    # 标记这块已收集：stop() 排空缓冲区时据此跳过，避免重复叠加（重影）
                    self._collected.add(int(hdr.lpData or 0))
            if not self._stop.is_set():
                try:
                    winmm.waveInAddBuffer(
                        hwi, ctypes.cast(dwParam1, ctypes.c_void_p),
                        ctypes.sizeof(_WAVEHDR))
                except Exception:
                    pass

        self._callback = WAVE_CALLBACK(_cb)
        mr = winmm.waveInOpen(
            ctypes.byref(phwi), 0, ctypes.byref(fmt),
            self._callback, 0, CALLBACK_FUNCTION)
        _check_mmresult(mr, "waveInOpen")
        self._wavein = phwi
        self._fmt = fmt

        # 准备缓冲区
        self._hdrs = []
        self._collected = set()   # 已由 WIM_DATA 回调收集过数据的缓冲区地址（避免 stop 时重复收集）
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
            os.makedirs(save_dir, exist_ok=True)
        except Exception as e:
            return False, "无法创建目录：%s" % e
        ts = time.strftime("%Y%m%d_%H%M%S")
        # 同一秒内「停止 → 再录」不能把上一段录音覆盖掉（时间戳只到秒）
        self._path = unique_path(os.path.join(save_dir, "mic_%s.wav" % ts))
        self._chunks = []
        self._collected = set()
        self._stop.clear()
        try:
            self._open()
        except Exception:
            # _open 里 waveInOpen 可能已经成功，只是准备缓冲区 / 启动采集失败。
            # 此时必须把句柄关掉：否则麦克风被本进程一直占着，用户打开任何别的
            # 录音软件都拿不到设备 —— 而界面上只有一句「无法开始录音」，
            # 重启程序才恢复。_running 仍为 False，stop() 不会代劳。
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
        # 先 waveInStop 停止采集，**再把各缓冲区里已录到的残余数据取走**。
        # 早前直接 waveInReset 会丢弃「正填充中、尚未触发 WIM_DATA 回调」的那块数据
        # —— 录屏刚开始就停止时，整段录音可能全丢，写出 44 字节的空 WAV，播放不了。
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
        # 空录音（麦克风被占用 / 全程静音 / 权限不足）会写出只有 44 字节头的 wav，
        # 这种文件任何播放器都打不开。删掉并回 None，让调用方明确提示「未录到声音」。
        if self._path and os.path.exists(self._path) and not _wav_ok(self._path):
            _silent_remove(self._path)
            self._path = None
            return None
        return self._path

    def _release_device(self):
        """尽力释放 WinMM 句柄（unprepare → close），任一步失败都不影响下一步。

        单独抽出来是因为它有两个调用点：正常 stop()，以及 start() 中 _open()
        半途失败 —— 后者早前根本没做收尾（异常直接往上传，句柄留在进程里）。
        方法自身幂等：句柄关掉后置空，重复调用直接返回。
        """
        winmm = getattr(self, "_winmm", None)
        hwi = getattr(self, "_wavein", None)
        if winmm is None or hwi is None:
            return
        # 这两步各自兜底：unprepare 失败也绝不能跳过 close，否则麦克风设备会一直
        # 被本进程占用（其它录音程序随之失效）。
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
        """停止后把各缓冲区里已录到的残余数据（dwBytesRecorded）并入 _chunks。

        waveInReset 会让未回调完的缓冲区直接失效，reset 之前必须先把残余数据取走。
        已由 WIM_DATA 回调收集过的缓冲区（记在 _collected）跳过，否则同一段音频会被
        叠加两次，听感上是「重影 + 音量翻倍」。
        """
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
        # 按 block_align 对齐：奇数长度字节会让部分播放器判为损坏文件
        block_align = self.channels * (self.sample_bits // 8)
        if block_align > 1 and len(data) % block_align:
            data = data[:-(len(data) % block_align)]
        import struct
        size = len(data)
        with open(self._path, "wb") as f:
            f.write(b"RIFF")
            f.write(struct.pack("<I", 36 + size))
            f.write(b"WAVEfmt ")
            f.write(struct.pack("<IHHIIHH", 16, 1, self.channels, self.rate,
                                self.rate * block_align, block_align,
                                self.sample_bits))
            f.write(b"data")
            f.write(struct.pack("<I", size))
            f.write(data)
