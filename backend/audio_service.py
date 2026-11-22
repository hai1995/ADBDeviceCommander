"""
backend.audio_service —— 音频采集（电脑麦克风 / 设备端）+ ffmpeg 合成。

  * MicRecorder        Windows 下用 WinMM waveIn 录电脑麦克风到本地 WAV
  * DeviceAudioCapture 设备端用 tinycap 录设备声音（需固件带 tinycap）
  * ffmpeg_mux(...)    把视频 + 若干 WAV 混流为一个带音视频的 MP4（尽力而为）

所有函数不依赖 UI；通过 controller 的 bus 推送 tool 状态。非 Windows 平台 MicRecorder
会在 start() 抛出可读错误，由调用方提示「仅 Windows 支持电脑麦克风」。
"""
import contextlib
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
from core.ffmpeg_bin import ffmpeg_exe
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
#
# 不同声卡在 WinMM 共享模式下支持的组合并不统一：笔记本内置阵列麦常常只有
# 单声道，部分 USB 麦只认 48kHz。旧实现写死 44.1kHz 立体声，waveInOpen 直接
# 返回 32（WAVERR_BADFORMAT）—— 用户明明已在系统里允许了麦克风权限，却只看到
# 「电脑麦克风启动失败」，以为是自己哪里没开。这里按「立体声优先、再降为单
# 声道」的顺序逐个试，**只有 32 才换下一种**：设备被占用（4）、无驱动（6）
# 这类错误换格式也不会好，必须原样报出来，否则用户永远查不到真正原因。
_MIC_FORMATS = ((2, 44100), (2, 48000), (1, 48000), (1, 44100), (1, 16000))

# waveInOpen 的 uDeviceID 必须传 WAVE_MAPPER（= (UINT)-1），让系统按用户在
# 「声音设置 → 输入」里选定的**默认麦克风**去映射，而不是写死 0。
#
# 写死 0 = 永远打开系统里的第 0 号输入设备，这在多声卡机器上几乎必然出错：
# 钉钉 / EV录屏 / 腾讯会议 / 各类声卡驱动都会往输入设备列表里插**虚拟麦克风**
# （往往排在最前，正好占住 0 号位），这些虚拟设备平时没有真实信号源，录出来
# 就是一条纯静音 wav —— 表现正是「勾了麦克风、权限也给了，视频却没声音」。
# 用户再去翻「隐私 → 麦克风」会发现程序根本不在列表里、也没弹过权限申请，
# 于是误以为是权限没开；其实 Win32 桌面程序从不弹权限窗（那是 Store 应用的
# 机制），只受「让桌面应用访问麦克风」这个总开关控制，真正的问题是选错了设备。
WAVE_MAPPER = 0xFFFFFFFF


def _check_mmresult(mr, what):
    """WinMM 调用返回非 0 就抛可读异常（0 / None 视为成功）。

    这些接口**返回错误码而不抛异常**，不校验就等于「什么都没发生」：
    waveInStart 失败时 start() 照样返回成功，界面显示「录音中」，停止后却
    一句「未录到声音」—— 用户以为是自己没说话。校验之后错误当场就有名字。
    """
    if not mr:
        return
    raise RuntimeError("{} 失败，错误码 {}（{}）".format(what, mr, _MM_ERROR_TEXT.get(mr, "未知错误")))


def _have_ffmpeg():
    try:
        r = subprocess.run([ffmpeg_exe(), "-version"], **adb_kwargs(10))  # noqa: PLW1510  失败不致命，调用方自行核对 returncode
        return r.returncode == 0
    except Exception:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
        return False


def _wav_duration(path):
    """读出 WAV 的 data 段字节数（不是秒数）；解析不出返回 None。

    只认「标准 44 字节 RIFF/WAVE 头 + fmt + data」的 PCM WAV —— 也就是本模块自己
    写出的那种。tinycap 写出的头有时字段顺序不同，宁可判为不可用也不要喂给 ffmpeg。
    """
    try:
        # 长路径安全：读侧也必须加前缀，否则超过 260 字符时 getsize 直接抛
        # OSError、open 抛 FileNotFoundError，函数返回 None → 上层把**刚录好
        # 的音频**判成无效并丢弃。
        total = path_getsize(path)
        with open(long_path(path), "rb") as f:
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
    except Exception:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
        return None


def _wav_ok(path):
    """WAV 是否**真正可用**：头合法 **且** 含实际音频数据。

    早期实现只查「头是 RIFF/WAVE 且体积 >= 44 字节」，于是「录了 0 字节」的空音频
    （正好 44 字节）会被判为可用并喂给 ffmpeg —— ffmpeg 对纯静音/零长度输入会输出一个
    258 字节、`duration=N/A` 的空壳 mp4，用户表现为「合成出来的视频打不开」。
    这里额外要求 data 段有真实字节数。
    """
    try:
        # 长路径安全：Windows 上 os.path.exists 对超长路径返回 False（不报错），
        # 于是「文件不存在」被误判 → _wav_ok 返回 False → 调用方把**录好的
        # 音频当成空录音删掉**（见 MicRecorder.stop 与 DeviceAudioCapture.stop）。
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
    except Exception:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
        return False


def _mp4_playable(path):
    """合成产物是否是一个真能播的 mp4（含视频流、时长 > 0、体积合理）。

    ffmpeg 退出码为 0 **不代表**产物可用：音频为空/过短时它会成功输出一个几百字节、
    没有有效时长的空壳文件。这里用 ffprobe（或退化为扫 moov + 体积兜底）复核，
    避免把坏文件当成功结果交给用户。
    """
    try:
        # 长路径安全：同 _wav_ok —— 超长路径下 exists 返回 False，会把正常的
        # mp4 判成「不可播放」，合成结果被白白丢掉。
        if not path_exists(path):
            return False
        size = path_getsize(path)
        # 正常 1 帧视频都远大于 4KB；低于此值基本可判定为空壳
        if size < 4096:
            return False
        with contextlib.suppress(Exception):
            r = subprocess.run(  # noqa: PLW1510  失败不致命，调用方自行核对 returncode
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
                **adb_kwargs(20))
            if r.returncode == 0:
                return "video" in (r.stdout or "")
        # 没有 ffprobe 时退化为「体积 + moov 头」兜底判断
        with open(long_path(path), "rb") as f:
            return b"moov" in f.read(min(size, 4 * 1024 * 1024))
    except Exception:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
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
                        return f"{duration / float(timescale):.3f}"
                    return None
                pos += bsize
        return None
    except Exception:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
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
    # 长路径安全：视频落在用户的保存目录里，路径可以超长。
    if not (video_path and path_exists(video_path)):
        return None
    audios = [a for a in (audio_paths or []) if a and _wav_ok(a)]
    if not audios:
        return None
    duration = _video_duration(video_path)
    if not duration:
        return None
    cmd = [ffmpeg_exe(), "-y", "-i", video_path]
    for a in audios:
        cmd += ["-i", a]
    # 视频流直接复制（不重编码，保留 screenrecord 的原始画质与速度）；
    # 音频把所有输入混为单条立体声。
    # 两处容易踩的坑（实测报错）：
    #   a) 视频**不能**进 filter_complex（写成 [0:v]copy 会报 "Streamcopy requested for
    #      output stream fed from a complex filtergraph"），用 -map 0:v:0 直接引用原流。
    #   b) apad 也**不能**用独立的 -af（与复杂滤镜图同时作用于同一流会报
    #      "Simple and complex filtering cannot be used together"），必须写进滤镜图里。
    mix = f"amix=inputs={len(audios):d}:duration=longest:dropout_transition=0,apad[a]"
    cmd += ["-filter_complex", mix,
            "-map", "0:v:0", "-map", "[a]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
            "-t", duration,
            out_path]
    try:
        r = subprocess.run(cmd, **adb_kwargs(300))  # noqa: PLW1510  失败不致命，调用方自行核对 returncode
        if r.returncode == 0 and path_exists(out_path):
            # 复核：ffmpeg 成功也可能产出空壳（音频为空/过短时）
            if _mp4_playable(out_path):
                return out_path
            _silent_remove(out_path)
        else:
            _silent_remove(out_path)
    except Exception:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
        _silent_remove(out_path)
    return None


def _media_duration(path):
    """用 ffprobe 取媒体时长（秒，字符串）；取不到返回 None。"""
    with contextlib.suppress(Exception):
        r = subprocess.run(  # noqa: PLW1510  失败不致命，调用方自行核对 returncode
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path], **adb_kwargs(20))
        if r.returncode == 0:
            v = (r.stdout or "").strip().rstrip(",")
            return v if v and v != "N/A" else None
    return None


def _silent_remove(path):
    with contextlib.suppress(Exception):
        if path and os.path.exists(long_path(path)):
            os.remove(long_path(path))


class DeviceAudioCapture:
    """设备端 tinycap 录音（写入 /data/local/tmp 下 wav，停止后 pull 回本地）。"""

    @staticmethod
    def supported(adb, serial):
        try:
            r = subprocess.run(  # noqa: PLW1510  失败不致命，调用方自行核对 returncode
                [adb, "-s", serial, "shell", "command", "-v", "tinycap"],
                **adb_kwargs(10))
            return r.returncode == 0 and "tinycap" in (r.stdout or "")
        except Exception:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
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
        """启动设备端 tinycap，返回 `(ok, 原因)`。

        为什么要带原因：tinycap 在多数 ROM 上需要 root，会**立刻退出**。只回
        False 时调用方只能播一句「音频采集启动失败」，用户手上是什么线索都没有
        —— 而真正的原因（需要 root / 没有音频输入）恰好决定了下一步该做什么。
        """
        with self._lock:
            if serial in self._procs:
                return False, "该设备已在采集设备音频"
        try:
            proc = subprocess.Popen(
                [self.adb, "-s", serial, "shell", "tinycap", remote_wav],
                # 输出丢弃而不挂管道：录制期间没有任何代码读它，若设备端/本地 adb
                # 往这条管道写满 64KB，写入方会阻塞，把整个采集链路拖死。
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                **adb_popen_kwargs())
        except Exception as e:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
            return False, f"无法启动 tinycap：{e}"
        # 探测 tinycap 是否真的跑起来了：很多 ROM 上 tinycap 需要 root，会立刻退出，
        # 而 supported() 只查了 `command -v tinycap`。不做这一步，start() 会对一个
        # 已经死掉进程返回 True —— 状态栏照样显示「（含设备音频）」，停止时 pull
        # 必然失败，用户最终拿到一段没有声音的视频且不知道原因。
        rc = None
        with contextlib.suppress(Exception):
            if proc.poll() is None:
                time.sleep(1.0)
            rc = proc.poll()
        if rc is not None:
            # 进程已退出，但 poll() 不等于回收：不 wait() 会留下僵尸 Popen，
            # 反复失败（每次录制都探一次）会累积句柄直到 fd 耗尽。
            with contextlib.suppress(Exception):
                proc.wait(timeout=2)
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
        with contextlib.suppress(Exception):
            proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
            with contextlib.suppress(Exception):
                proc.kill()
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
            "adb_devaudio_{}_{}.wav".format(safe_name(serial), time.strftime("%H%M%S")))
        # pull 带重试（容忍收尾/落盘延迟）；并校验 wav 头，损坏则丢弃，避免污染合成视频
        for attempt in range(5):
            with contextlib.suppress(Exception):
                r = subprocess.run(  # noqa: PLW1510  失败不致命，调用方自行核对 returncode
                    [self.adb, "-s", serial, "pull", remote_wav, tmp],
                    **adb_kwargs(60))
                if r.returncode == 0 and _wav_ok(tmp):
                    local = tmp
                    break
            time.sleep(0.5 * (attempt + 1))
        if local is None:
            # 五轮都没拿到可用的 wav（pull 失败 / 文件头不完整 / 设备端还没写完）：
            # 把已经落盘的残片删掉。它不会被合成，留在 TEMP 里既白占空间，
            # 又让人看到 adb_devaudio_*.wav 误以为这次录音是好的。
            with contextlib.suppress(Exception):
                if os.path.exists(long_path(tmp)):
                    os.remove(long_path(tmp))
        with contextlib.suppress(Exception):
            subprocess.run([self.adb, "-s", serial, "shell", "rm", "-f", remote_wav],  # noqa: PLW1510  失败不致命，调用方自行核对 returncode
                           **adb_kwargs(10))
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
        # _chunks 只在「不经 start() 的构造」（单测）里作为兜底使用；正常录音
        # 路径由 _wav_fp 流式写盘，PCM 不堆在内存里（见 _append_audio_locked）。
        self._chunks = []
        self._wav_fp = None          # 已打开的 WAV 落盘句柄（流式写入）
        self._data_bytes = 0         # 已写入的 data 段字节数（回填 WAV 头用）
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

        self._winmm = winmm
        self._WAVEFORMATEX = WAVEFORMATEX
        # ---- WinMM 原型必须显式声明 --------------------------------------
        # 不声明 argtypes 时 ctypes 走「默认转换」：byref 对象被当成一个整数
        # （它指向的地址）传下去，而 C int 只有 32 位 —— 64 位下指针就此被截断，
        # waveInOpen / waveInPrepareHeader 拿到的是野指针，**电脑麦克风录音在
        # Windows 上根本起不来**（报出来的是「设备被占用 / 无驱动」，与真实
        # 原因毫无关系）。实测（本机 Python 3.11 / x86-64）：不声明时 byref
        # 被转成截断后的 32 位地址 —— 这不是「也许」，是必然。
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
            # 替身不是 ctypes 函数对象（单测里的假 WinMM 是普通 Python 方法，
            # 没有 argtypes 属性）—— 真实环境里 winmm.waveInOpen 一定是
            # _FuncPtr，不会走到这里。
            pass
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
                    self._append_audio_locked(ctypes.string_at(hdr.lpData, n))
                    # 标记这块已收集：stop() 排空缓冲区时据此跳过，避免重复叠加（重影）
                    self._collected.add(int(hdr.lpData or 0))
            if not self._stop.is_set():
                with contextlib.suppress(Exception):
                    winmm.waveInAddBuffer(
                        hwi, ctypes.cast(dwParam1, ctypes.POINTER(_WAVEHDR)),
                        ctypes.sizeof(_WAVEHDR))

        self._callback = WAVE_CALLBACK(_cb)
        # 逐个格式尝试打开（见 _MIC_FORMATS）：只有 32（格式不支持）才换下一种；
        # 其它错误（设备占用 / 无驱动 / 无权限）原地报出来，换格式也救不了。
        self._wavein = None
        last_err = None
        for channels, rate in _MIC_FORMATS:
            block_align = channels * (self.sample_bits // 8)
            fmt = WAVEFORMATEX(
                WAVE_FORMAT_PCM, channels, rate,
                rate * block_align, block_align, self.sample_bits, 0)
            phwi = ctypes.c_void_p()
            mr = winmm.waveInOpen(
                # uDeviceID 用 WAVE_MAPPER，交给系统按默认输入设备映射；写死 0
                # 会打开第 0 号设备，在装有虚拟声卡（钉钉 / EV录屏等）的机器上
                # 往往落到没有信号的虚拟设备上，录出全程静音。见 WAVE_MAPPER 注释。
                ctypes.byref(phwi), WAVE_MAPPER, ctypes.byref(fmt),
                # dwCallback 是 DWORD_PTR（回调函数地址）：声明了 c_void_p 之后
                # 必须显式 cast，直接传 CFUNCTYPE 实例会被拒。
                ctypes.cast(self._callback, ctypes.c_void_p),
                0, CALLBACK_FUNCTION)
            if not mr:
                # 用实际打开成功的格式写 WAV 头：降级到单声道后若仍按立体声写头，
                # 播放器会把音高/时长全算错。
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
            os.makedirs(long_path(save_dir), exist_ok=True)
        except Exception as e:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
            return False, f"无法创建目录：{e}"
        ts = time.strftime("%Y%m%d_%H%M%S")
        # 同一秒内「停止 → 再录」不能把上一段录音覆盖掉（时间戳只到秒）
        self._path = unique_path(os.path.join(save_dir, f"mic_{ts}.wav"))
        self._chunks = []
        self._collected = set()
        self._wav_fp = None
        self._data_bytes = 0
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
        # 必须在 _open() 成功后建头：_open() 会按实际打开的格式降级
        # self.channels / self.rate（见那里），头部参数以实际值为准。
        # 若建头失败（只读盘 / 路径被占用），同样要释放已开的麦克风句柄。
        try:
            self._open_wav_stream()
        except Exception:
            self._release_device()
            self._close_wav_stream(remove=True)
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
        with contextlib.suppress(Exception):
            winmm.waveInStop(self._wavein)
        self._drain_buffers()
        with contextlib.suppress(Exception):
            winmm.waveInReset(self._wavein)
        self._running = False
        self._release_device()
        self._write_wav()
        # 空录音（麦克风被占用 / 全程静音 / 权限不足）会写出只有 44 字节头的 wav，
        # 这种文件任何播放器都打不开。删掉并回 None，让调用方明确提示「未录到声音」。
        if self._path and path_exists(self._path) and not _wav_ok(self._path):
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
        with contextlib.suppress(Exception):
            for hdr, _buf in getattr(self, "_hdrs", []):
                winmm.waveInUnprepareHeader(
                    hwi, ctypes.byref(hdr), ctypes.sizeof(_WAVEHDR))
        with contextlib.suppress(Exception):
            winmm.waveInClose(hwi)
        self._wavein = None

    # ---- 流式落盘（根治 _chunks 无界累积）--------------------------------
    # 背景：44100Hz / 2ch / 16bit ≈ 172 KB/s，录 10 分钟就往 _chunks 堆 ~100MB，
    # 1 小时 >600MB；stop() 的 b"".join 还要再复制一份，峰值翻倍 → 长录屏 + 麦克风
    # 直接把内存吃满。改为边录边写文件：内存里只留极小的文件写缓冲，与录制时长无关。
    def _open_wav_stream(self):
        """打开目标 WAV 并写入 44 字节占位头（RIFF/data 长度先填 0，收尾回填）。

        必须在 _open() 之后调用：_open() 会按实际打开的格式降级 channels/rate，
        头部只能用实际的格式写，否则播放器按错误参数解码（音高/时长全错）。
        """
        import struct
        block_align = self.channels * (self.sample_bits // 8)
        f = open(long_path(self._path), "wb")
        try:
            f.write(b"RIFF")
            f.write(struct.pack("<I", 0))        # 占位：36 + data size
            f.write(b"WAVEfmt ")
            f.write(struct.pack("<IHHIIHH", 16, 1, self.channels, self.rate,
                                self.rate * block_align, block_align,
                                self.sample_bits))
            f.write(b"data")
            f.write(struct.pack("<I", 0))        # 占位：data size
            f.flush()
        except Exception:
            with contextlib.suppress(Exception):
                f.close()
            raise
        self._wav_fp = f
        self._data_bytes = 0

    def _append_audio_locked(self, data):
        """写入一段 PCM（调用方须持 self._lock）。

        有流式句柄就直接写文件并累加字节数；没有（绕过 start() 的构造 / 单测）
        则维持老的 _chunks 行为，保证既有测试与调用方式不变。
        """
        if not data:
            return
        fp = getattr(self, "_wav_fp", None)
        if fp is not None:
            fp.write(data)
            self._data_bytes += len(data)
        else:
            self._chunks.append(data)

    def _close_wav_stream(self, remove=False):
        """关闭流式句柄；remove=True 时连占位文件一起删（启动失败清理用）。"""
        fp = getattr(self, "_wav_fp", None)
        self._wav_fp = None
        if fp is not None:
            with contextlib.suppress(Exception):
                fp.close()
        if remove and self._path:
            _silent_remove(self._path)

    def _drain_buffers(self):
        """停止后把各缓冲区里已录到的残余数据（dwBytesRecorded）写入落盘流。

        waveInReset 会让未回调完的缓冲区直接失效，reset 之前必须先把残余数据取走。
        已由 WIM_DATA 回调收集过的缓冲区（记在 _collected）跳过，否则同一段音频会被
        叠加两次，听感上是「重影 + 音量翻倍」。
        """
        collected = getattr(self, "_collected", None)
        if collected is None:
            collected = self._collected = set()
        for hdr, _buf in getattr(self, "_hdrs", []):
            try:
                # 判重与写入必须同锁：waveInStop 前已排队的 WIM_DATA 回调可能
                # 晚于本次 drain 执行。旧实现在锁外查 collected，若回调恰在
                # 「查完→拿锁」之间 append+add 同一 buffer，drain 会再写一次，
                # 成片音频重影/音量翻倍。把判重挪进同一把锁，与回调的
                # _append_audio_locked+add 形成原子序列。
                n = hdr.dwBytesRecorded
                if n and hdr.lpData:
                    with self._lock:
                        key = int(hdr.lpData or 0)
                        if key in collected:
                            continue
                        self._append_audio_locked(ctypes.string_at(hdr.lpData, n))
                        collected.add(key)
            except Exception:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
                continue

    def _write_wav(self):
        """收尾：把 data 长度回填到 WAV 头并关闭文件；无流式句柄时回退老逻辑。

        流式路径下 PCM 已经在录制过程中逐块写进文件，这里绝不再 b"".join 整段数据
        —— 那正是无界累积的根源。只需按 block_align 对齐截断尾部、回填两个长度字段。
        """
        import struct
        # WAV 头两个长度字段都是 32 位无符号（最大 0xFFFFFFFF）。单场录音
        # 超过约 4GB（≈6.8 小时的 44.1k/16bit/双声道）时，struct.pack("<I")
        # 会抛 struct.error：旧实现没兜住，被上层吞掉后误报「没录到声音」，
        # 还留下一个头没回填的坏 wav。clamp 到上限保证头始终合法可解析——
        # 超出部分播放器读不到，但至少不是损坏文件（超长录音本就该分段）。
        size_cap = 0xFFFFFFFF
        block_align = self.channels * (self.sample_bits // 8)
        fp = getattr(self, "_wav_fp", None)
        if fp is not None:
            with self._lock:
                # 按 block_align 对齐：尾部不足一帧的字节会让部分播放器判损坏
                size = self._data_bytes
                if block_align > 1 and size % block_align:
                    size -= size % block_align
                # RIFF size = 36 + data size，同样不能溢出 32 位。
                riff_size = min(size_cap, 36 + size)
                size = min(size_cap, size)
                try:
                    fp.flush()
                    fp.seek(4)
                    fp.write(struct.pack("<I", riff_size))   # RIFF size @ 偏移 4
                    # WAV 44 字节头布局：RIFF(4)+size(4)+WAVEfmt (8)
                    # + fmt body pack<IHHIIHH>(20) + data(4) → data size @ 偏移 40
                    fp.seek(40)
                    fp.write(struct.pack("<I", size))
                    fp.flush()
                finally:
                    with contextlib.suppress(Exception):
                        fp.close()
                    self._wav_fp = None
            # 截断掉未对齐的尾部字节，保证文件实际长度与头部声明一致
            if size < self._data_bytes:
                with contextlib.suppress(Exception):
                    with open(long_path(self._path), "r+b") as tf:
                        tf.truncate(44 + size)
            return

        # 回退路径：无流式句柄（绕过 start() 的构造 / 单测）时维持老的整块写。
        with self._lock:
            data = b"".join(self._chunks)
        self._chunks = []
        if block_align > 1 and len(data) % block_align:
            data = data[:-(len(data) % block_align)]
        size = len(data)
        riff_size = min(size_cap, 36 + size)
        size = min(size_cap, size)
        with open(long_path(self._path), "wb") as f:
            f.write(b"RIFF")
            f.write(struct.pack("<I", riff_size))
            f.write(b"WAVEfmt ")
            f.write(struct.pack("<IHHIIHH", 16, 1, self.channels, self.rate,
                                self.rate * block_align, block_align,
                                self.sample_bits))
            f.write(b"data")
            f.write(struct.pack("<I", size))
            f.write(data)
