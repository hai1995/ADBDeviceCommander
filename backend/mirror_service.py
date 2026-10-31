# -*- coding: utf-8 -*-
"""
backend.mirror_service —— 没有 scrcpy 时的备用投屏（两条降级链路）
================================================================
工具页的投屏首选 scrcpy（见 scrcpy_service）：它延迟最低、还能反向控制设备。
但它**不随本程序打包**，用户机器上没装就整块功能不可用。这里补上两条只依赖
adb 的退路，让「投屏」在任何机器上都有个能出画面的答案：

  ① 管道投屏（PipeMirror）—— 流畅档
     `adb exec-out screenrecord --output-format=h264 -` 把屏幕打成**裸 H.264 流**
     吐到 stdout，Python 原样转发给本机的 ffplay / mpv / mplayer / vlc 播放。
     延迟约 0.2~1s、30~60fps，画面投在播放器窗口里（和 scrcpy 一样是独立窗口）。
     两个必须自己处理的坑：
       * screenrecord 有 **180 秒硬上限**，到点会自己退出 —— 检测退出后立刻重开
         续流（画面卡一下就恢复），否则用户投 3 分钟就黑屏；
       * 部分 ROM（华为等）直接**删掉了 screenrecord** —— 秒退时要把 stderr
         原样报出来，而不是让窗口一闪而过。

  ② 低帧率预览（SnapMirror + FrameServer）—— 兜底档
     循环 `adb exec-out screencap -p` 抓帧，画面**内嵌在程序界面里**。
     零第三方依赖、任何设备都能用，代价是只有 1~3fps（只能"看个画面"）。

为什么帧不走 bus / JSON 桥
--------------------------
一帧 1080p 截图是几百 KB，base64 后更大。走 `take_events()` 的 JSON 桥会让
每次轮询都背上序列化 + 跨进程传输的开销，界面跟着卡；更要命的是 bus 对未知
kind 不计行数限流，帧推得比前端消费快时 deque 会无限增长。
因此 ② 改为**本机回环 HTTP 帧服务**：后端只保留"最新一帧"，前端 `<img src>`
直接拉，浏览器自己负责解码与丢弃——不占 JSON 通道，也没有积压问题。
服务只绑 127.0.0.1 且拒绝非回环来源，不外泄画面。
"""
import os
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote

from backend.device_proc import kill_device_process
from core.constants import no_window_flags

# ---- 播放器：按「延迟表现」排序，越靠前越优先 ----
PLAYER_ORDER = ("ffplay", "mpv", "mplayer", "vlc")

PLAYER_EXE_NAMES = {
    "ffplay": ("ffplay.exe", "ffplay"),
    "mpv": ("mpv.exe", "mpv"),
    "mplayer": ("mplayer.exe", "mplayer"),
    "vlc": ("vlc.exe", "vlc"),
}

# screenrecord 一次最长 180s（Android 硬限制），到点必须重开才能继续投。
# 留 2s 余量：设备端先退出、本地 adb 客户端随后退出，别把正常收尾误判成续流。
SCREENRECORD_MAX_S = 180
# 续流次数上限（防「设备端一直秒退」时空转刷屏；正常投 1 小时约 20 次）
MAX_RESTARTS = 500
# 转发块大小：够大以减少 syscall，又不至于让一块数据拖出可见延迟
CHUNK = 65536
# 低帧率预览的抓帧超时（设备卡顿 / adb 被抢锁时不能把线程永久挂住）
SNAP_TIMEOUT_S = 15
# 等「第一帧画面」的时限。screenrecord 若不可用（ROM 删了该命令 / 参数不支持）
# 会在 1~2s 内秒退；而编码器初始化慢的设备可能要 3~4s 才吐首帧。取 6s 兼顾
# 两者——这段等待是**同步**的，正是「管道投屏失败 → 自动降级到低帧率预览」
# 能成立的判断依据。
FIRST_DATA_TIMEOUT = 6.0


def _player_args(kind, fps=60):
    """各播放器「从 stdin 读裸 H.264 并低延迟播放」的参数。

    `-` 表示 stdin。参数都是为此场景挑过的：
      * ffplay：`-probesize 32` 快速起播、`-fflags nobuffer` + `-framedrop`
        砍掉缓冲（默认缓冲会带来好几秒延迟）；
      * mpv：`--no-cache --untimed --no-correct-pts` 关闭一切时序重排，
        `--framedrop=always` 宁可丢帧也要追上实时；
      * mplayer：`-demuxer h264es` 明确告诉它这是裸流，`-cache 512` 给个小窗；
      * vlc：`--demux=h264`（vlc 对裸流的 stdin 支持最别扭，故排最后）。
    """
    if kind == "ffplay":
        return ["-f", "h264", "-framerate", str(fps), "-framedrop",
                "-fflags", "nobuffer", "-flags", "low_delay",
                "-probesize", "32", "-sync", "video", "-"]
    if kind == "mpv":
        return ["--no-cache", "--untimed", "--no-correct-pts",
                "--fps=%d" % fps, "--framedrop=always", "-"]
    if kind == "mplayer":
        return ["-framedrop", "-fps", "6000", "-cache", "512",
                "-demuxer", "h264es", "-nosound", "-"]
    if kind == "vlc":
        return ["--demux=h264", "--no-video-title-show", "-"]
    return []


def _guess_kind(path):
    """从用户填的路径猜播放器类型（猜不出就按 ffplay 的参数走，反正会用错报错）。"""
    low = os.path.basename(str(path or "")).lower()
    for kind in PLAYER_ORDER:
        if kind in low:
            return kind
    return ""


def _player_extra_dirs():
    """PATH 之外的常见安装目录（ffmpeg / mpv / vlc 三家的默认落地位置）。"""
    home = os.path.expanduser("~")
    dirs = []
    if sys.platform.startswith("win"):
        dirs += [r"C:\ffmpeg\bin", os.path.join(home, "ffmpeg", "bin"),
                 os.path.join(home, "scoop", "shims"),
                 os.path.join(home, "scoop", "apps", "ffmpeg", "current", "bin")]
        for env in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(env)
            if not base:
                continue
            dirs += [os.path.join(base, "Programs", "ffmpeg", "bin"),
                     os.path.join(base, "ffmpeg", "bin"),
                     os.path.join(base, "mpv"),
                     os.path.join(base, "VideoLAN", "VLC")]
    elif sys.platform == "darwin":
        dirs += ["/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin",
                 "/Applications/VLC.app/Contents/MacOS"]
    else:
        dirs += ["/usr/local/bin", "/usr/bin", "/snap/bin"]
    return [d for d in dirs if os.path.isdir(d)]


def _as_exe(path, names):
    """把「目录 / exe 全路径」解析成可执行文件路径。"""
    if not path:
        return None
    p = str(path).strip().strip('"')
    if not p:
        return None
    if os.path.isdir(p):
        for name in names:
            cand = os.path.join(p, name)
            if os.path.isfile(cand):
                return cand
        return None
    if os.path.isfile(p):
        return p
    return None


def find_player(pref_path=""):
    """按「配置 → PATH → 常见目录」找可用的播放器。

    返回 (kind, exe, note)：kind 为 ffplay/mpv/mplayer/vlc 之一，找不到时
    kind 与 exe 均为空、note 给出可执行的处理建议。
    """
    if pref_path:
        kind = _guess_kind(pref_path)
        names = PLAYER_EXE_NAMES.get(kind) or \
            tuple(n for names_ in PLAYER_EXE_NAMES.values() for n in names_)
        exe = _as_exe(pref_path, names)
        if exe:
            return (kind or "ffplay"), exe, "来自配置的路径"
        note_prefix = "配置的播放器路径无效（%s），已改用自动探测；" % pref_path
    else:
        note_prefix = ""

    for kind in PLAYER_ORDER:
        for name in PLAYER_EXE_NAMES[kind]:
            exe = shutil.which(name)
            if exe:
                return kind, exe, note_prefix + "来自系统 PATH"

    for d in _player_extra_dirs():
        for kind in PLAYER_ORDER:
            exe = _as_exe(d, PLAYER_EXE_NAMES[kind])
            if exe:
                return kind, exe, note_prefix + "来自常见安装目录 %s" % d

    # 找不到时 exe 返回 None（与 find_scrcpy 一致），调用方一律用 `if exe:` 判断
    return "", None, (note_prefix +
                      "未找到播放器：装任意一个即可（Windows 推荐 winget install "
                      "Gyan.FFmpeg 拿 ffplay；macOS brew install ffmpeg / mpv；"
                      "Linux apt install ffmpeg）。装好后填路径或加到 PATH")


def probe_player(pref_path=""):
    """探测本机播放器并取版本串（失败不抛异常）。"""
    kind, exe, note = find_player(pref_path)
    if not exe:
        return {"ok": False, "kind": "", "path": "", "version": "", "note": note}
    version = ""
    try:
        r = subprocess.run([exe, "--version"], timeout=6, capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           creationflags=no_window_flags())
        out = (r.stdout or "").strip() or (r.stderr or "").strip()
        version = out.splitlines()[0].strip()[:60] if out else ""
    except Exception:
        version = ""
    return {"ok": True, "kind": kind, "path": exe, "version": version,
            "note": note}


def device_size(adb, serial):
    """读设备物理分辨率 `wm size` → (w, h)；读不到返回 (0, 0)（调用方走默认值）。

    只认 Physical size（Override size 是用户/开发者改过的临时值，用它算缩放
    会在投屏结束后把用户的覆盖设置固化进命令参数里）。
    """
    try:
        r = subprocess.run([adb, "-s", serial, "shell", "wm", "size"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=10,
                           creationflags=no_window_flags())
        text = r.stdout or ""
        # 两轮扫描：先只认 `Physical size`（真实分辨率），整份输出里都没有它
        # 时才退而接受其它带 "size" 的行（个别 ROM 只打一行 `Override size`）。
        # 原来写的是 `if "Physical size" in line or "size" in line.lower():` ——
        # 后半个条件让前半个形同虚设，谁先出现就用谁，与上面「只认 Physical」
        # 的承诺并不一致：`wm size` 先打 Override 的 ROM 上会拿到临时分辨率。
        for want in ("physical size", "size"):
            for line in text.splitlines():
                if want not in line.lower():
                    continue
                part = line.split(":")[-1].strip()
                if "x" not in part:
                    continue
                w, _, h = part.partition("x")
                if w.strip().isdigit() and h.strip().isdigit():
                    return int(w), int(h)
    except Exception:
        pass
    return 0, 0


def plan_size(adb, serial, max_edge=1080):
    """按设备分辨率等比缩放，长边不超过 max_edge。

    1080p 以上的原始分辨率既吃码率又吃编码器算力，投屏反而更卡；等比缩小
    长边能显著降低延迟。screenrecord 只接受设备**支持**的尺寸，保守起见只在
    需要缩小时才传 --size（读不到分辨率就干脆不传，让它用默认值）。
    返回 "WxH" 字符串或 ""（= 不指定）。
    """
    w, h = device_size(adb, serial)
    if not w or not h:
        return ""
    edge = max(w, h)
    if edge <= max_edge:
        return "%dx%d" % (w, h)
    scale = max_edge / float(edge)
    # 偶数对齐：H.264 编码器对奇数宽高支持不一，取整到偶数最稳
    nw = int(w * scale) // 2 * 2
    nh = int(h * scale) // 2 * 2
    return "%dx%d" % (max(nw, 2), max(nh, 2))


def _tail_text(stream, limit=400):
    """取子进程 stderr 末尾若干字符（秒退时用它给出设备端的真实报错）。"""
    try:
        data = stream.read() or ""
    except Exception:
        return ""
    text = data.decode("utf-8", "replace") if isinstance(data, bytes) else data
    return " ".join(text.split())[-limit:]


class PipeMirror:
    """单台设备的管道投屏：adb screenrecord → 本机播放器窗口（含 180s 续流）。

    数据不走 shell 管道而由 Python 中转，原因有二：Windows 没有可靠的 shell
    管道拼接（`cmd /c` 与 PowerShell 语法还不一样），且中转线程能自己感知
    「adb 退出了」——这正是续流的触发点，用 shell 管道拿不到。
    """

    def __init__(self, adb, serial, player_kind, player_exe,
                 size="", bitrate_mbps=8, fps=60, on_status=None):
        self.adb = adb
        self.serial = serial
        self.player_kind = player_kind
        self.player_exe = player_exe
        self.size = size or ""
        self.bitrate_mbps = bitrate_mbps
        self.fps = fps
        self.on_status = on_status
        self._stop = threading.Event()
        self._first_data = threading.Event()   # 已收到首帧 = 链路可用
        self._done = threading.Event()         # 结论就绪（收到首帧 或 已判定失败）
        self._player = None
        self._player_err = ""                  # 播放器 stderr 末尾（失败时给原因）
        self._adb_proc = None
        self._thread = None
        self.restarts = 0
        self.error = ""
        # 「已经给用户开出画面」才允许回调 on_status。start() 判定失败时，
        # controller 会立刻降级到低帧率预览并提示「已开启投屏」；若失败路径
        # 也回调，用户会先看到一条红字「投屏已中断」，紧接着又看到绿字
        # 「已开启投屏」—— 同一台设备同时「中断」和「开启」，只能让人以为
        # 程序在乱报（实际上那一档根本没起来）。
        self._started_ok = False

    # ---- 命令 ----
    def _adb_cmd(self):
        cmd = [self.adb, "-s", self.serial, "exec-out", "screenrecord",
               "--output-format=h264"]
        if self.size:
            cmd += ["--size", self.size]
        # screenrecord 的 --bit-rate 单位是 bps（不是 Mbps）
        cmd += ["--bit-rate", str(int(self.bitrate_mbps) * 1000000)]
        cmd += ["-"]
        return cmd

    # ---- 生命周期 ----
    def start(self):
        """拉起播放器与首轮 screenrecord，同步等到「出画面或确认失败」。

        返回 (ok, 错误信息)。这里刻意**同步等首帧**：只有同步判定出
        「设备端 screenrecord 用不了」，controller 才能在同一次点击里自动
        降级到低帧率预览；若异步报错，用户只会看到一个没画面的播放器窗口。
        """
        try:
            self._player = subprocess.Popen(
                [self.player_exe] + _player_args(self.player_kind, self.fps),
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, creationflags=no_window_flags())
        except Exception as e:
            return False, "播放器启动失败：%s" % e
        # 必须有人把 stderr 读走：管道容量只有 64KB，mpv / vlc 这类会持续
        # 打日志的播放器写满之后就会**阻塞在写日志上**，随之不再消费 stdin，
        # 画面卡死而原因完全看不出来。读走的同时留末尾一段，秒退时能报真因。
        threading.Thread(target=self._drain_player_err,
                         args=(self._player.stderr,), daemon=True,
                         name="mirror-player-%s" % self.serial).start()
        ok, err = self._spawn_adb()
        if not ok:
            self._kill_player()
            return False, err
        self._thread = threading.Thread(
            target=self._feed_loop, daemon=True,
            name="mirror-pipe-%s" % self.serial)
        self._thread.start()
        self._done.wait(FIRST_DATA_TIMEOUT)
        if self._first_data.is_set():
            return True, ""
        # 超时 / 秒退：收掉这一轮，把设备端原因交给调用方
        reason = self.error or "设备端 screenrecord 未在 %.0fs 内输出画面" % FIRST_DATA_TIMEOUT
        self.stop()
        return False, reason

    def _spawn_adb(self):
        try:
            self._adb_proc = subprocess.Popen(
                self._adb_cmd(), stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, creationflags=no_window_flags())
        except Exception as e:
            return False, "screenrecord 启动失败：%s" % e
        return True, ""

    def _drain_player_err(self, stream):
        """把播放器的 stderr 持续读走，只留末尾 400 字符（供秒退时报原因）。

        不读的后果不是「少一条日志」：管道写满 64KB 后播放器会阻塞在写日志上，
        于是不再消费 stdin —— 表现为画面突然卡死，而我们这边仍在一路 write，
        看起来像「设备不吐数据」。异常一律吞掉，这条线程不能影响转发。
        """
        try:
            for raw in iter(stream.readline, b""):
                if self._stop.is_set():
                    break
                line = raw.decode("utf-8", "replace").strip()
                if line:
                    self._player_err = (self._player_err + " " + line)[-400:]
        except Exception:
            pass

    def _player_alive(self):
        """播放器窗口是否还开着（用户直接关窗口 = poll() 非 None）。"""
        p = self._player
        if p is None:
            return False
        try:
            return p.poll() is None
        except Exception:
            return False

    def _close_player(self, wait=2.0):
        """收掉播放器进程：terminate → 短暂等待 → 仍活着才 kill。"""
        player = self._player
        if player is None:
            return
        try:
            if player.poll() is not None:
                return
            player.terminate()
        except Exception:
            return
        try:
            player.wait(timeout=wait)
        except Exception:
            try:
                player.kill()
            except Exception:
                pass

    def _feed_loop(self):
        """转发循环：adb stdout → 播放器 stdin；adb 退出即续流（直到被 stop）。"""
        while not self._stop.is_set():
            proc = self._adb_proc
            got = False
            if proc is not None:
                try:
                    while not self._stop.is_set():
                        # read1 而非 read：read(n) 会死等到凑满 n 字节，
                        # 低码率画面下这几秒等待会直接变成可见延迟
                        chunk = proc.stdout.read1(CHUNK)
                        if not chunk:
                            break
                        self._player.stdin.write(chunk)
                        self._player.stdin.flush()
                        if not got:
                            # 只有**真的写进播放器**才算「出画面」：写失败时提前
                            # 置位会让 start() 误报成功，用户拿到一个黑窗口。
                            got = True
                            self._started_ok = True   # 此后中断才值得回调整
                            self._first_data.set()
                            self._done.set()     # 放行 start() 的同步等待
                except Exception as e:
                    self.error = "转发中断：%s" % e
                try:
                    proc.stdout.close()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=5)
                except Exception:
                    # 读循环已退出但 adb 还活着：必须主动收掉。否则每次中断都留
                    # 一个挂着设备端 screenrecord 的 adb 进程，而续流又会再起
                    # 一个新的 —— 几轮下来设备端编码器被抢光。
                    try:
                        proc.kill()
                    except Exception:
                        pass
            if self._stop.is_set():
                break
            if not self._player_alive():
                # 用户把播放器窗口关了：继续「续流」是纯粹的空转 —— 每轮都是
                # 立刻写失败、立刻重开 screenrecord，能一路刷到 MAX_RESTARTS，
                # 设备端编码器被反复占用，报出来的却只有一句「转发中断」。
                tail = (self._player_err or "").strip()
                self.error = ("播放器窗口已关闭，投屏停止"
                              + ("（%s）" % tail[-200:] if tail else ""))
                break
            if not got:
                # 一个字节都没收到就退出 = 设备端命令不可用（ROM 移除 /
                # 参数不支持 / 未授权），重试无意义
                tail = _tail_text(proc.stderr) if proc is not None else ""
                self.error = self.error or (
                    "设备端 screenrecord 未输出画面%s"
                    % ("（%s）" % tail if tail else ""))
                self._done.set()
                self._emit()
                return
            # 正常跑满 180s 上限 → 续流
            self.restarts += 1
            if self.restarts > MAX_RESTARTS:
                # 设备端 screenrecord 反复退出（编码器被别的应用占着 / 该 ROM
                # 限制了单次时长）：停止重连，并把原因留下来。原来是静默
                # break —— 画面停住，状态栏一个字都没有。
                self.error = ("已连续重连 %d 次仍未恢复，投屏停止"
                              "（设备端 screenrecord 反复退出）" % MAX_RESTARTS)
                break
            ok, err = self._spawn_adb()
            if not ok:
                self.error = err
                break
        self._done.set()
        self._emit()

    def _emit(self):
        # 没投起来就没什么可「中断」的：这条回调的语义是「已经在投的链路断了」，
        # 由 controller 转成红字状态。启动失败的那一档由 start() 的返回值负责，
        # 调用方会降级并给出正常提示。
        if not self._started_ok:
            return
        if self.on_status:
            try:
                self.on_status(self.serial, self.error)
            except Exception:
                pass

    def _kill_player(self):
        """只收播放器（screenrecord 起不来的失败路径用：播放器窗口不该留着）。"""
        self._close_player()

    def stop(self):
        """停止投屏：先断 adb（停止喂数据），再收播放器，最后清设备端残留。"""
        self._stop.set()
        self._done.set()          # 放行可能还在同步等待的 start()
        proc = self._adb_proc
        if proc is not None:
            try:
                if proc.poll() is None:
                    proc.kill()
            except Exception:
                pass
        # 设备端 screenrecord 可能还活着（adb 客户端被杀不会带走它），
        # 不清理会一直占着编码器、下次录屏也起不来
        try:
            kill_device_process(self.adb, self.serial, "screenrecord")
        except Exception:
            pass
        self._close_player()

    def alive(self):
        return (not self._stop.is_set()
                and self._player is not None
                and self._player.poll() is None)


class FrameServer:
    """本机回环 HTTP 帧服务：只保留「最新一帧」，供前端 <img> 直接拉。

    绑 127.0.0.1 的随机空闲端口（port=0 由内核分配），避免固定端口冲突；
    非回环来源一律 403，画面不外泄。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._frames = {}          # serial -> bytes（PNG）
        self._httpd = None
        self._port = 0
        self._thread = None

    def start(self):
        """启动服务并返回端口号（重复调用幂等）。"""
        if self._httpd is not None:
            return self._port
        try:
            self._httpd = _ThreadingFrameServer(("127.0.0.1", 0), _make_handler(self))
            self._port = self._httpd.server_address[1]
        except Exception:
            self._httpd = None
            return 0
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, daemon=True, name="mirror-frame-http")
        self._thread.start()
        return self._port

    @property
    def port(self):
        return self._port

    def set_frame(self, serial, data):
        with self._lock:
            self._frames[serial] = data

    def get_frame(self, serial):
        with self._lock:
            return self._frames.get(serial)

    def drop(self, serial):
        with self._lock:
            self._frames.pop(serial, None)

    def frame_url(self, serial):
        """前端 <img> 用的地址（带 serial 查询参数，多设备各取各的）。"""
        if not self._port:
            return ""
        return "http://127.0.0.1:%d/frame?serial=%s" % (
            self._port, quote(str(serial), safe=""))

    def stop(self):
        httpd, self._httpd, self._port = self._httpd, None, 0
        if httpd is None:
            return
        try:
            httpd.shutdown()
        except Exception:
            pass
        try:
            httpd.server_close()
        except Exception:
            pass
        with self._lock:
            self._frames.clear()


class _ThreadingFrameServer(ThreadingHTTPServer):
    """关闭监听 socket 的等待：默认 allow_reuse_address 在 Windows 上会让端口
    处于 TIME_WAIT，重启程序时偶发绑定失败。"""
    allow_reuse_address = True
    daemon_threads = True


def _make_handler(server):
    class _Handler(BaseHTTPRequestHandler):
        server_version = "ADCMirror/1.0"

        def _deny(self):
            try:
                self.send_error(403, "local only")
            except Exception:
                pass

        def do_GET(self):
            if not str(self.client_address[0]).startswith("127."):
                return self._deny()
            if not self.path.startswith("/frame"):
                try:
                    self.send_error(404, "not found")
                except Exception:
                    pass
                return
            serial = ""
            if "?" in self.path:
                serial = (parse_qs(self.path.split("?", 1)[1]).get("serial")
                          or [""])[0]
            data = server.get_frame(serial)
            if not data:
                try:
                    self.send_error(404, "no frame")
                except Exception:
                    pass
                return
            try:
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(data)))
                # 每次都要拿最新一帧，禁止任何缓存
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                self.send_header("Pragma", "no-cache")
                self.end_headers()
                self.wfile.write(data)
            except Exception:
                pass

        def log_message(self, fmt, *args):
            """静默：默认会把每次拉帧打到 stderr，.pack 后污染控制台。"""
            return

    return _Handler


class SnapMirror:
    """单台设备的低帧率预览：循环 screencap，最新一帧交给 FrameServer。

    适合「没装 scrcpy 也没装播放器」的机器 —— 只要 adb 能用就一定有画面，
    代价是 1~3fps，只能看个状态，不适合演示操作。
    """

    def __init__(self, adb, serial, server, fps=2, on_status=None):
        self.adb = adb
        self.serial = serial
        self.server = server
        self.fps = fps
        self.on_status = on_status
        self._stop = threading.Event()
        self._thread = None
        self.error = ""
        self.frames = 0

    @property
    def interval(self):
        return 1.0 / max(1, min(int(self.fps or 2), 10))

    def start(self):
        """先抓一帧确认链路可用，再起后台循环。返回 (ok, 错误信息)。"""
        data, err = self._grab()
        if not data:
            return False, err or "截图失败（设备未授权 / adb 不可用）"
        self.server.set_frame(self.serial, data)
        self.frames += 1
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="mirror-snap-%s" % self.serial)
        self._thread.start()
        return True, ""

    def _grab(self):
        """抓一帧 PNG。返回 (bytes or None, 错误文本)。"""
        proc = None
        try:
            # 二进制管道：不能加 text/encoding（会破坏 PNG 字节）
            proc = subprocess.Popen(
                [self.adb, "-s", self.serial, "exec-out", "screencap", "-p"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=no_window_flags())
            data, err = proc.communicate(timeout=SNAP_TIMEOUT_S)
            if proc.returncode != 0 or not data:
                return None, (err or b"").decode("utf-8", "replace")[:200] or "空数据"
            return data, None
        except Exception as e:
            # 超时时 communicate 只抛错、不终止子进程：卡住的 adb 会变孤儿
            if proc is not None:
                try:
                    proc.kill()
                    proc.communicate(timeout=5)
                except Exception:
                    pass
            return None, str(e)[:200]

    def _loop(self):
        while not self._stop.is_set():
            # 按「距上一帧的间隔」补睡眠，抓帧本身耗的时间也算进去，
            # 避免慢设备上sleep + 抓帧叠加成远超预期的帧间隔
            t0 = time.time()
            data, err = self._grab()
            if data:
                self.server.set_frame(self.serial, data)
                self.frames += 1
            elif err and not self.error:
                self.error = err
            wait = self.interval - (time.time() - t0)
            if wait > 0:
                self._stop.wait(wait)      # stop() 会提前唤醒
            if self._stop.is_set():
                break
        if self.on_status:
            try:
                self.on_status(self.serial, self.error)
            except Exception:
                pass

    def stop(self):
        self._stop.set()
        try:
            self.server.drop(self.serial)
        except Exception:
            pass

    def alive(self):
        return not self._stop.is_set()
