# -*- coding: utf-8 -*-
"""
backend.screen_service —— 截图 + 录屏（视频，不含音频合成）。

  * screenshot(serial, save_dir)              对单台设备 exec-out screencap -p 写 PNG
  * VideoRecorder                              adb screenrecord 起/停 + 拉回本地

音频（设备端 tinycap / 电脑麦克风）与 ffmpeg 合成在 audio_service 中，
由 controller 在录屏会话里按需协同。本模块只负责「视频」这条线。

面向用户的状态文案一律由 controller 统一下发：本模块只**返回**结果
（路径 / 错误原因），不自行 push 事件——否则同一件事会被 controller 与
本模块各报一次，状态栏出现两行一模一样的内容。
"""
import itertools
import os
import signal
import subprocess
import tempfile
import threading
import time

from backend.device_proc import kill_device_process
from core import imgbytes
from core.constants import (
    REC_MAX_SEGMENTS, REC_MAX_TOLERANCE_S, REC_SEGMENT_S,
    adb_kwargs, adb_popen_kwargs, no_window_flags, safe_name)

# adb 明确表示「这台设备已经不在了」的报错片段（用于把「设备掉线」与
# 「文件还没写好」区分开，见 VideoRecorder._remote_probe）。
# 刻意只收与设备可达性有关的措辞：`No such file or directory` 这类**不**在内，
# 它是正常的「还没生成」，需要继续退避等待。
_DEVICE_GONE_HINTS = (
    "device not found",
    "device '",
    "device offline",
    "device unauthorized",
    "no devices/emulators found",
    "no devices found",
    "cannot connect to daemon",
    "error: closed",
    "protocol fault",
)

# `adb pull` 里**不会自愈**的报错：权限 / 磁盘满 / 只读文件系统 / 目标是目录。
# 这类错误再等 6 次、白退避 9 秒，最后报的还是同一句话，而现场看着就像「程序
# 卡住了」。命中即返回，把原因直接给出去（与 _DEVICE_GONE_HINTS 同一思路：
# 能判定不可恢复的，就别耗在重试上）。
_FATAL_PULL_HINTS = (
    "permission denied",
    "operation not permitted",
    "no space left",
    "read-only file system",
    "is a directory",
)


def device_present(adb, serial, timeout=5):
    """探测设备此刻是否仍可连（adb -s <serial> get-state）。

    仅当 get-state 干净返回 ``device`` 才算在；offline / unknown / 超时 /
    异常都视为「不可用 / 已掉线」。用来把「录屏进程死亡」区分为
    「设备真的掉线了（USB 断开）」还是「screenrecord 自己崩了但设备还在」，
    避免把 USB 掉线误判成本工具写死的「录屏期间执行了 adb root」——而录屏路径
    里本工具根本不会重启 adbd（overlay 用 settings put，不碰 adbd）。
    """
    try:
        # 只传 **adb_kwargs(...)：它自带 capture_output=True，再显式写
        # stdout=/stderr= 会被 subprocess.run 判为参数冲突并抛 ValueError。
        # 旧写法正是这么写的 —— 于是每次探测都抛 ValueError 被下面 except 吞掉，
        # 函数**恒定返回 None**：logcat 抓取的掉线判定（`is False`）永远不成立，
        # 设备真掉线也走不成「等重连续写」；重连轮询又把 None 当「没回来」，
        # 只能一路等到窗口耗尽。录屏配套日志丢一大段，根子就在这里。
        r = subprocess.run(
            [adb, "-s", serial, "get-state"], **adb_kwargs(timeout))
    except Exception:
        # adb 本身不可达（缺失 / 超时 / 异常）：无法判定设备状态，返回 None（未知）
        # 而非 False（确认掉线）。这样调用方（logcat 重连等待）才不会把「adb 暂
        # 时查不到」误判成「设备已掉线」而拉起无意义的重连轮询；同时 None 在
        # `not probe(...)` 语境下仍等价于「不在」（设备移除检测据此判为掉线）。
        return None
    if r.returncode != 0:
        return False
    # text=True 已解码（见 adb_kwargs），这里比的是字符串而不是 bytes。
    return (r.stdout or "").strip().lower() == "device"


def device_clock(adb, serial, timeout=5):
    """读设备当前时刻，返回 ``(epoch, tz_offset_seconds)``；读不到返回 None。

    `epoch` 是设备自报的 Unix 秒（`date +%s`），`tz_offset` 是设备本地时区
    相对 UTC 的偏移（`date +%z`，如 +0800 → 28800）。两段一次取回：分两次
    调 adb shell 会让收尾多一次往返，而这两项本来就是同一行输出里的。

    为什么非要时区不可：logcat 的 threadtime 是**设备本地墙上时间**（没有年份、
    也没有时区）。把它解析成 epoch 时必须知道「这台设备的 11:14 是 UTC 的几点」，
    否则会按主机的时区去解释。主机是 +0800、设备是 UTC（车机、部分定制 ROM
    出厂默认）时，日志里的 11:14 会被算成比设备当前时刻早 8 小时 —— 录屏收尾
    就会弹「日志丢了 8 小时」，而实际一条没少。假告警比不告警更糟：它会让用户
    之后连真的那条都不信。

    `%z` 在 toybox（Android 6+）上都支持；个别老 shell 会返回字面量或 %z 原样，
    此时 tz_offset 为 None，调用方据此**跳过**基于日志时间戳的缺口判定（宁可
    不说，也不给一个按主机时区猜出来的结论）。
    """
    try:
        # 一次 shell 取两段：+%s%z 输出形如 "1793850520+0800"，无空格好解析
        r = subprocess.run(
            [adb, "-s", serial, "shell", "date", "+%s%z"],
            **adb_kwargs(timeout))
    except Exception:
        return None
    if r.returncode != 0:
        return None
    for tok in (r.stdout or "").split():
        tok = tok.strip()
        # 手工切「数字 + 时区」两段，不引正则：这里每台设备一次，且要容忍
        # %z 不被支持时冒出来的 "1793850520%z" 这类字面量（切出来 tz 不合法，
        # 就当只有 epoch，offset 留 None）。
        i = 0
        while i < len(tok) and tok[i].isdigit():
            i += 1
        head, tz = tok[:i], tok[i:]
        if len(head) < 9:
            continue
        try:
            epoch = int(head)
        except ValueError:
            continue
        offset = None
        if len(tz) == 5 and tz[0] in "+-" and tz[1:].isdigit():
            hh, mm = int(tz[1:3]), int(tz[3:5])
            if hh <= 14 and mm < 60:      # 现实时区最大 +14:00
                offset = (hh * 3600 + mm * 60) * (-1 if tz[0] == "-" else 1)
        return epoch, offset
    return None


# `settings put` 被系统拒绝时，报错文本里必然出现的片段（见 set_system_setting_ex）。
# 只收明确表示「被拒」的措辞：正常写入时这两路都是空的，不会误报。
_SETTING_REJECT_HINTS = (
    "securityexception",
    "permission denial",
    "permission denied",
    "error:",
    "exception",
)


# 车机 adb shell 需要「授权密码」时，终端会停在 Password: 等处输入。本工具
# 没有终端可输入，子进程要么立刻 EOF、要么一直等到超时 —— 两种都只表现为
# 「没有输出」。下面三组特征词用来把这种情况与「权限被拒」「设备掉线」分开，
# 否则用户只会看到一句「截图失败」，并把它误认成「车机没 root」。
_SHELL_PASSWORD_HINTS = (
    "password", "passwd", "enter password", "login:", "密码", "授权码",
)
_SHELL_DENIED_HINTS = (
    "permission denied", "operation not permitted", "not allowed",
    "securityexception", "security exception", "selinux", "permission denial",
)
_SHELL_UNAUTH_HINTS = (
    "unauthorized", "authentication required", "not authenticated",
)


def _shell_blocked_text(state, detail, serial):
    """把「adb shell 这个通道不可用」翻译成用户能照着做的说明。

    截图失败时用户能看到的只有一句「截图失败」，而真实原因（要输密码 /
    权限被收紧 / 设备掉线）往往只藏在 adb 的一句半截输出里。这里把几种
    最常被混淆的情况分别说清，尤其是「需要密码」—— 它最容易被误读成
    「车机没 root，所以截不了图」，而 screencap 本身并不需要 root。
    """
    # 折叠空白：adb 的报错常带换行，塞进状态栏会把整行撑乱
    detail = " ".join((detail or "").split())
    tail = ("（adb 原话：%s）" % detail[:160]) if detail else ""
    if state == "password":
        return ("车机的 adb shell 需要先输入授权密码才能执行命令 —— 在系统命令行里"
                "手工执行 adb -s %s shell echo hi 会停在 Password: 等待输入，"
                "本工具没有终端可以代为输入，所以任何命令（包括截图）都只会"
                "「没有输出」。请先在车机上完成调试授权（部分车型需在开发者选项里"
                "重新允许 USB 调试并输入授权码 / 密码），再重试截图。%s"
                % (serial, tail))
    if state == "timeout":
        return ("adb shell 8 秒内没有任何响应：最常见的原因是车机要求 adb shell 输入"
                "授权密码（会一直停在 Password:，本工具无法代为输入），其次是该车型"
                "收紧了 shell 执行权限。请用系统命令行执行 adb -s %s shell echo hi "
                "确认：停在 Password: 就是密码校验，回 Permission denied 就是权限被限。"
                % serial)
    if state == "denied":
        return ("车机拒绝了 adb shell 执行命令%s。screencap 不需要 root，这通常是该"
                "车型的定制系统收紧了 shell 权限（SELinux / 调试策略），不是本工具"
                "缺少 root 权限；换成别的 adb 命令同样会被拒。" % tail)
    if state == "unauthorized":
        return ("这台设备的 USB 调试尚未授权：请在车机弹出的「允许 USB 调试吗」"
                "对话框里点允许（建议勾选「一律允许」）后重试。%s" % tail)
    if state == "gone":
        return ("设备当前不可用%s。请检查数据线 / 无线 ADB 连接后重试。" % tail)
    return ("adb shell 无法执行命令，且 adb 没有给出明确原因%s。截图依赖 shell "
            "通道，请先用系统命令行执行 adb -s %s shell echo hi 确认这台车机是否"
            "允许 shell 执行（若停在 Password: 则是需要授权密码）。"
            % (tail, serial))


class ScreenCapturer:
    # 文件名序号：时间戳只精确到秒，同一秒内的两次截图会算出**同一个路径** ——
    # 轻则后来的覆盖先前的（用户少了一张图），重则两个线程同时往同一文件写
    # （PNG 内容交错、文件损坏）。录屏远端文件名早有同样处理（见 VideoRecorder._seq）。
    _seq = itertools.count(1)

    # ---- 取图的三条通路 ---------------------------------------------
    # 1) exec-out：最快，不在设备上留文件，绝大多数设备可用；
    # 2) 设备端落盘 + adb pull：exec-out 的字节被换行转换改坏、或被截断时
    #    的兜底 —— pull 走 sync 协议，二进制原样传输；
    # 3) 都不行：给出**能照着做**的原因，而不是笼统的「截图失败」。
    #
    # 车机上还有一类失败最容易被误读：adb shell 本身要求输入授权密码，
    # adbd 起不了子进程，exec-out 与 shell 都只是「没有输出」。_probe_shell
    # 专门把这一类分辨出来，免得用户把它当成「车机没 root」。

    @staticmethod
    def screenshot(adb, serial, save_dir, save_file=True):
        """对单台设备截图，返回本地 png 路径或 (None, 错误文本)。

        先走 exec-out；坏了自动降级为「设备端落盘 + pull」；两条都不通时
        分别报出原因（能判定是 shell 通道被密码 / 权限拦住时给准确提示）。

        save_file：是否把图写入保存目录。为 False 时（前端「自动保存文件」关掉）
        不往保存目录落盘，而是写到系统临时目录（前缀 adc_shot_，随程序退出/启动
        被清理），仅用于预览与剪贴板 —— 用户只想瞄一眼、不想让保存目录被一堆
        截图占满时，关掉开关即可，且不影响后续的预览与复制。
        """
        if save_file:
            try:
                os.makedirs(save_dir, exist_ok=True)
            except Exception as e:
                return None, "无法创建保存目录 %s: %s" % (save_dir, e)
        ts = time.strftime("%Y%m%d_%H%M%S")
        # safe_name：无线 ADB 序列号形如 192.168.1.5:5555，冒号是 Windows
        # 文件名非法字符，不净化会让 open() 直接失败（截图静默丢失）。
        # 落盘目标按 save_file 分流：保存目录 vs 系统临时目录。
        if save_file:
            out_dir = save_dir
            out_name = "screenshot_%s_%s_%d.png" % (
                safe_name(serial), ts, next(ScreenCapturer._seq))
        else:
            out_dir = tempfile.gettempdir()
            # 临时目录里同样用 safe_name 净化序列号，避免冒号等字符污染文件名
            out_name = "adc_shot_%s_%s_%d.png" % (
                safe_name(serial), ts, next(ScreenCapturer._seq))
        out = os.path.join(out_dir, out_name)

        data, why = ScreenCapturer._exec_out(adb, serial)
        if data:
            clean, kind, err = ScreenCapturer._validate(data)
            if not err:
                return ScreenCapturer._save(out, clean, kind), None
            why = err          # 坏图的原因要留住，最后原样告诉用户

        # 先确认 shell 通道本身可用：车机要密码时，再试任何 adb 命令都只是
        # 「没有输出」，反而把真正的原因（要授权）淹没在一串重试里。
        state, detail = ScreenCapturer._probe_shell(adb, serial)
        if state != "ok":
            return None, _shell_blocked_text(state, detail or why, serial)

        data, pull_why = ScreenCapturer._pull_capture(adb, serial, out)
        if data:
            clean, kind, err = ScreenCapturer._validate(data)
            if not err:
                return ScreenCapturer._save(out, clean, kind), None
            pull_why = err
        return None, ("两条取图通道都没成功：exec-out 报「%s」；"
                      "设备端落盘再 pull 报「%s」" % (why, pull_why))

    @staticmethod
    def _exec_out(adb, serial, timeout=30):
        """exec-out 直取 PNG 字节；返回 (data, 原因)，data 为空即失败。"""
        proc = None
        try:
            # 二进制管道：不能加 text/encoding（会破坏 PNG 字节），只补窗口隐藏
            proc = subprocess.Popen(
                [adb, "-s", serial, "exec-out", "screencap", "-p"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=no_window_flags())
            data, err = proc.communicate(timeout=timeout)
            if proc.returncode == 0 and data:
                return data, ""
            # adb 的报错几乎都落在 **stdout**（`error: device 'xxx' not found`
            # 就是典型），只解 stderr 会得到空串，界面于是显示「截图失败：空
            # 数据」—— 用户完全看不出是设备没连上。两路都收，优先给带内容的
            # 那一句。
            both = ((err or b"") + b"\n" + (data or b"")).strip()
            text = both.decode("utf-8", "ignore").strip()[:200]
            return b"", text or "设备未返回图像（adb 没有给出原因）"
        except Exception as e:
            # 超时（设备无响应 / 被别的 adb 客户端抢锁）时 communicate() 只是抛错、
            # **不会**终止子进程：卡住的 adb exec-out 会变成孤儿进程一直挂着，
            # 且它占着 stdout 管道。这里必须显式回收（kill + 收尾读取）。
            if proc is not None:
                try:
                    proc.kill()
                    proc.communicate(timeout=5)
                except Exception:
                    pass
            return b"", str(e)

    @staticmethod
    def _probe_shell(adb, serial, timeout=8):
        """探测 `adb shell` 能否执行命令：返回 (state, 原始输出)。

        state ∈ ok / password / denied / unauthorized / gone / timeout / error。
        只在 exec-out 已经失败后调用 —— 正常路径不多付这一次往返。

        `echo` 是最小、最不可能被车机策略单独拦下的命令：它能通，说明 shell
        通道没问题，故障只出在 screencap 或字节传输上；它不通，那么任何
        「落盘 + pull」的补救都不会有效，没必要再白试一遍。
        """
        marker = "__ADB_SHELL_OK__"
        try:
            r = subprocess.run(
                [adb, "-s", serial, "shell", "echo", marker],
                stdin=subprocess.DEVNULL, **adb_kwargs(timeout))
        except subprocess.TimeoutExpired:
            # 需要密码时 adbd 会停在 Password: 等输入；本工具没有终端，
            # 子进程就一直等到超时 —— 这正是要分辨出来的那一类。
            return "timeout", ""
        except Exception as e:
            return "error", str(e)
        text = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
        if marker in (r.stdout or ""):
            return "ok", text
        low = text.lower()
        for hint in _SHELL_PASSWORD_HINTS:
            if hint in low:
                return "password", text
        for hint in _SHELL_DENIED_HINTS:
            if hint in low:
                return "denied", text
        for hint in _SHELL_UNAUTH_HINTS:
            if hint in low:
                return "unauthorized", text
        for hint in _DEVICE_GONE_HINTS:
            if hint in low:
                return "gone", text
        return "unknown", text[:200]

    @staticmethod
    def _pull_capture(adb, serial, local_hint, timeout=60):
        """设备端落盘 + `adb pull` 取图；返回 (data, 原因)。

        存在的意义是绕开 exec-out 的文本通道：个别 Windows adb 与车机会在
        那条管道上做换行转换（0x0A → 0x0D 0x0A），把 PNG 内部字节改坏；
        `adb pull` 走 sync 协议，二进制原样传输。
        """
        # 远端文件名带本进程序号：同一台设备连点截图也不会互相覆盖
        remote = "/sdcard/adbdc_shot_%s_%d.png" % (
            safe_name(serial), next(ScreenCapturer._seq))
        try:
            r = subprocess.run(
                [adb, "-s", serial, "shell", "screencap", "-p", remote],
                stdin=subprocess.DEVNULL, **adb_kwargs(30))
        except subprocess.TimeoutExpired:
            return b"", "设备端 screencap 超时（30 秒）"
        except Exception as e:
            return b"", "设备端 screencap 未能执行：%s" % e
        text = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
        if r.returncode != 0:
            return b"", ("设备端 screencap 失败：%s"
                         % (text[:200] or "退出码 %d" % r.returncode))
        part = local_hint + ".part"
        try:
            r2 = subprocess.run(
                [adb, "-s", serial, "pull", remote, part],
                stdin=subprocess.DEVNULL, **adb_kwargs(timeout))
            text2 = ((r2.stdout or "") + "\n" + (r2.stderr or "")).strip()
            if r2.returncode != 0 or not os.path.exists(part):
                return b"", ("adb pull 没有取回截图：%s"
                             % (text2[-200:] or "退出码 %d" % r2.returncode))
            with open(part, "rb") as f:
                return f.read(), ""
        except subprocess.TimeoutExpired:
            return b"", "adb pull 超时（%d 秒）" % timeout
        except Exception as e:
            return b"", "adb pull 失败：%s" % e
        finally:
            # .part 只是中间产物：校验由调用方做，这里负责不留垃圾
            try:
                if os.path.exists(part):
                    os.remove(part)
            except Exception:
                pass
            # 设备端临时文件无论成败都清掉；清不掉（例如传输中途掉线）不该
            # 覆盖本次的真正结果，所以异常一律吞掉。
            try:
                subprocess.run(
                    [adb, "-s", serial, "shell", "rm", "-f", remote],
                    stdin=subprocess.DEVNULL, **adb_kwargs(10))
            except Exception:
                pass

    @staticmethod
    def _validate(data):
        """落盘前校验：返回 (clean_bytes, kind, 错误文本)；错误非空即不许落盘。"""
        # 归一化再落盘：部分车机 / 定制 ROM 的 screencap 会在 PNG 前先吐几行
        # 自己的东西，字节流因此「开头不是图片签名」——写下来是一张打不开的
        # 图，复制到剪贴板也会连累到 GDI+ 报「参数无效」。这里按签名切出有效
        # 段，保证磁盘上的文件就是一张能打开的图（详见 core.imgbytes）。
        clean, kind, note = imgbytes.normalize(data)
        if not clean:
            return b"", None, "设备返回的图像无法识别（%s）" % note
        if kind == "png" and imgbytes.png_size(clean) is None:
            # 头部校验不过的 PNG 就算落盘也打不开 —— 看图软件只会说一句
            # 「分辨率 / 格式有问题」，用户完全不知道是传输环节出了事。
            return b"", None, (
                "设备返回的 PNG 头已损坏（共 %d 字节，头部 %s）——"
                "通常是 adb 传输把换行转换掉了或截图被截断"
                % (len(clean), " ".join("%02x" % b for b in clean[:16])))
        if kind == "png" and not imgbytes.png_complete(clean):
            return b"", None, (
                "设备返回的 PNG 不完整（共 %d 字节，缺少 IEND 块）——"
                "通常是传输超时或中断，截图被截断" % len(clean))
        return clean, kind, ""

    @staticmethod
    def _save(out, data, kind):
        """写盘并返回最终路径；非 PNG 时扩展名跟着改，免得双击打不开。"""
        if kind and kind != "png":
            ext = ".jpg" if kind == "jpg" else "." + kind
            out = os.path.splitext(out)[0] + ext
        # exec-out 输出为原始 PNG 二进制，禁止做任何换行翻译，原样写入
        with open(out, "wb") as f:
            f.write(data)
        return out


# 设备端可视化 overlay 的 Settings.System 键名（录屏「指针位置 / 触摸圆点」用）。
# 二者都是**屏幕 overlay**（系统开发者选项同款），不是 screenrecord 参数：
#   * pointer_location  指针位置：画面常驻准星，跟随最近一次触摸位置；
#   * show_touches      显示触摸操作：触摸时屏幕出现圆点轨迹。
# 用系统设置而非 `screenrecord --show-pointer`（Android 10+ 才有）的原因：
# 后者在定制 ROM / 云手机 / 模拟器上上报的 SDK 与实际二进制常不一致，
# 传错参数会让整场录屏启动即失败；overlay 方案全版本可用、对录屏零风险，
# 且 overlay 画在屏幕上，会被 screenrecord 一并录进视频，目的一致。
KEY_POINTER_LOCATION = "pointer_location"
KEY_SHOW_TOUCHES = "show_touches"


class VideoRecorder:
    """单台设备的 screenrecord 会话：start() 后台录像，stop() 终止并 pull 回本地。

    bus 保留在构造参数里只为签名的稳定性（controller / 测试统一按
    (bus, adb) 构造）；本模块不再自行下发状态文案，由 controller 收口。
    """

    def __init__(self, bus, adb="adb"):
        self.bus = bus
        self.adb = adb
        # RLock：watcher 判定「这一段录满了」后要在**同一个临界区**里切换 session
        # 到下一段（见 _roll_segment_locked），重入比「先放锁再抢锁」安全 ——
        # 中间那一瞬如果 stop() 插进来，它拿到的还是旧 proc，新起的段就没人停了。
        self._lock = threading.RLock()
        self._sessions = {}          # serial -> dict(remote, local, proc, dir, extra)
        self._seq = itertools.count(1)  # 远端文件名序号，保证每次录制唯一

    # ---- 自动分段：命名 / 命令 / 单段错误摘要 ----
    def _seg_remote(self, serial, ts, seg):
        """设备端落地路径（每段唯一）。

        文件名带全局递增序号：既避免上一次崩溃残留的同名文件阻断 screenrecord
        启动（它拒绝覆盖已存在文件），也让「按命令行特征精准结束某一进程」有
        唯一标识可用（见 _stop_device_screenrecord）。
        """
        return "/data/local/tmp/adb_rec_%s_%s_%d.mp4" % (
            safe_name(serial), ts, next(self._seq))

    @staticmethod
    def _seg_local(save_dir, serial, base, seg):
        """本地文件名：第一段沿用 record_<serial>_<ts>.mp4，第二段起加 _pN。

        同一会话的多段在目录里自然排在一起，用户按文件名就知道顺序，不用猜
        哪一段接哪一段；第一段不带后缀，与历史产物、既有脚本保持一致。
        """
        if seg <= 1:
            name = "record_%s_%s.mp4" % (safe_name(serial), base)
        else:
            name = "record_%s_%s_p%d.mp4" % (safe_name(serial), base, seg)
        return os.path.join(save_dir, name)

    @staticmethod
    def _screenrecord_cmd(adb, serial, remote, no_limit=False):
        """构造 screenrecord 命令（每段一份）。

        必须经 `adb shell` 下发：`adb screenrecord ...` 会直接报
        `unknown command screenrecord`（这正是早期「录屏启动即失败」的真因）。

        `--time-limit`：到点由 screenrecord **自己正常收尾**（写回 moov）后退出，
        而不是被 180 秒硬上限掐断 —— 后者在慢设备上可能来不及写完索引，产出
        无时长、播放不了的 mp4。段长取 REC_SEGMENT_S（170 秒，留 10 秒余量）。

        no_limit=True 用于极老的 ROM（不认这个选项时 start() 会去掉它重试一次）：
        退化到 180 秒硬上限也照样自动分段 —— 180 > 170，watcher 的「这一段录满了」
        判据不受影响。宁可段长不可控，也不能让整台设备录不了。
        """
        cmd = [adb, "-s", serial, "shell", "screenrecord"]
        if not no_limit:
            cmd += ["--time-limit", str(REC_SEGMENT_S)]
        cmd.append(remote)
        return cmd

    @staticmethod
    def _timelimit_rejected(err):
        """这次失败是不是「设备端不认 --time-limit」造成的。

        只有报错里**同时**出现该选项名与「不认识 / 无效 / 不支持」才算：光含
        time-limit 的其它报错（比如编码器错误信息里提到它）不该触发重试，
        否则一次真正的失败会被掩盖成「去掉参数再试一次」。
        """
        low = (err or "").lower()
        if "time-limit" not in low and "time_limit" not in low:
            return False
        return any(h in low for h in (
            "unrecognized", "unknown option", "invalid option",
            "not supported", "illegal option"))

    @staticmethod
    def _proc_err(proc):
        """取子进程的错误输出摘要（adb 的报错常落在 stdout，两路都要看）。"""
        for stream in ("stderr", "stdout"):
            f = getattr(proc, stream, None)
            if f is None:
                continue
            try:
                text = (f.read() or "").strip()
            except Exception:
                continue
            if text:
                return text[:300]
        return ""

    def start(self, serial, save_dir, extra_name=None):
        """开始录屏（手动停止）。返回 (ok, 本地最终路径占位)。

        整场录制由用户手动停止（点「停止」/ 关窗口），但**单段不会无限长**：
        Android 的单段硬上限就是 180 秒，所以每段显式带 `--time-limit 170`，到点
        由 screenrecord 自己优雅收尾，watcher 随即在同一台设备上接起下一段（见
        _roll_segment_locked）。用户点一次「开始」就能连着录，产物是同一会话下的
        多个文件（_p2 / _p3 …），stop_ex() 一次取回全部段。
        早年的「固定时长」是另一回事——那时到点会**结束整场录制**，已移除。

        画面内的指针 / 触摸可视化（指针位置 / 触摸圆点）不走本方法：
        它们是设备系统设置的屏幕 overlay，由 controller 在录屏启动后
        另行开启、收尾时恢复（见 get_system_setting / set_system_setting）。
        """
        with self._lock:
            if serial in self._sessions:
                return False, "该设备已在录制"
        try:
            os.makedirs(save_dir, exist_ok=True)
        except Exception as e:
            return False, "无法创建保存目录 %s: %s" % (save_dir, e)
        ts = time.strftime("%Y%m%d_%H%M%S")
        base = extra_name or ts
        # 远端文件名带时间戳 + 序号：避免上一次崩溃残留的同一文件
        # 阻断本次 screenrecord 启动（screenrecord 拒绝覆盖已存在文件）。
        # 远端落到 /data/local/tmp/：该目录为 shell 所有、可写且可被 adb pull 稳定读取。
        # 远端文件名同样过 safe_name：无线序列号含冒号，adb shell 传参时
        # 冒号会被部分 ROM 的 shell 误判为分隔符，净化可保证命令稳定下发。
        remote = self._seg_remote(serial, ts, 1)
        local = self._seg_local(save_dir, serial, base, 1)
        proc, early_err = self._spawn_and_confirm(
            self._screenrecord_cmd(self.adb, serial, remote))
        no_lim = False
        if proc is not None and early_err and self._timelimit_rejected(early_err):
            # 极老的 ROM / 定制机不认 --time-limit，整台设备就完全录不了。去掉它
            # 重试一次：退化到 180 秒硬上限，自动分段照旧（180 > 170，watcher 的
            # 「这一段录满了」判据不受影响）。换一个新的远端文件名重试 —— 报错
            # 前那条进程万一已经建了空文件，同名重试会被 screenrecord 拒绝。
            remote = self._seg_remote(serial, ts, 1)
            proc, early_err = self._spawn_and_confirm(
                self._screenrecord_cmd(self.adb, serial, remote, no_limit=True))
            no_lim = proc is not None and not early_err
        if proc is None:
            return False, early_err
        if early_err is not None:
            # 设备端 screenrecord 在 1~2s 内提前退出：权限 / 目录 / 设备状态
            # 等问题原样上报（重试无意义，还会掩盖真实错误）。
            return False, "录屏启动失败：screenrecord 提前退出%s" % (
                "（%s）" % early_err if early_err.strip() else "")
        with self._lock:
            self._sessions[serial] = {
                "serial": serial,
                "remote": remote, "local": local, "proc": proc,
                "dir": save_dir, "done": threading.Event(),
                # 当前段的启动时刻：退出时据此区分「这一段录满了」与「被外力打断」
                "started": time.time(),
                # 会话名（分段命名要用同一份，不能每段重新取时间戳）
                "ts": ts, "extra": base,
                "seg": 1,        # 当前第几段（1 起）
                # 这台设备的 ROM 不认 --time-limit（已去掉该参数重试成功）：
                # 续段时也必须用同样的命令，否则下一段又会启动失败。
                "no_lim": no_lim,
                # 已结束、正在/已完成 pull 的段：[{n, serial, remote, local, dir,
                #                                  ok, err, done}]
                "segments": [],
            }
        # 进程意外死亡监测：adb root / 设备侧重启 adbd 会在录屏中途杀掉设备端
        # screenrecord，本地 adb 客户端随之退出。不监测的话界面会一直停在
        # 「录制中」，用户点「停止」后才在约 10 秒的 pull 重试后看到一句
        # 「缺 moov 头」。watcher 只负责**标记**（stop() 会先置 stopping，
        # 主动停止不算意外），由 controller 轮询到后自动走收尾 + 复位界面
        # （见 WebApi._reap_dead_recordings 与使用说明「录屏被中断」条）。
        threading.Thread(
            target=self._watch_exit, args=(serial, proc),
            daemon=True, name="rec-watch-%s" % serial).start()
        return True, local

    def _watch_exit(self, serial, proc):
        """等本地 adb 客户端退出，然后判定**这一段**是怎么结束的。

        三种情况，处置完全不同：

          * 用户主动停止（会话已置 stopping）→ 不标记，stop() 自己会收尾；
          * 这一段录满了（--time-limit 到点，screenrecord 已正常写回 moov）
            → **自动接下一段**，用户不需要做任何操作；
          * 远未到点就退出 → 记 died，由 controller 走「被意外中断」收尾。

        会话可能已被收尾弹掉（_pull_and_finish）—— 那种情况下无需标记。
        """
        try:
            proc.wait()
        except Exception:
            pass
        with self._lock:
            sess = self._sessions.get(serial)
            if sess is None or sess.get("proc") is not proc:
                return
            if sess.get("stopping"):
                return
            elapsed = time.time() - float(sess.get("started") or 0)
            full = bool(sess.get("started")) and elapsed >= (
                REC_SEGMENT_S - REC_MAX_TOLERANCE_S)
            if not full:
                sess["died"] = True
                return
            if int(sess.get("seg") or 1) >= REC_MAX_SEGMENTS:
                # 到段数上限：这一段同样是正常收尾（moov 已写回），交给
                # controller 按「录到头了」处理，不能报成意外中断。
                sess["limit_hit"] = True
                return
            self._roll_segment_locked(serial, sess)

    def _roll_segment_locked(self, serial, sess):
        """（须持锁调用）收好刚录满的这一段，并在同一台设备上接起下一段。

        「记录上一段 + 起新段 + 换 session 指针」必须在**同一个临界区**里完成：
        stop() 是靠 sess["proc"] / sess["remote"] 定位「当前正在录的那一段」的。
        中间放过一次锁，stop() 就可能拿到已经退出的旧 proc，于是新起的这一段
        没人停 —— 它会一直录到自己的 --time-limit 才结束，而那时界面早已显示
        「已停止」，用户以为录完了，实际还占着设备在录、在写存储。
        """
        prev = {
            "n": int(sess.get("seg") or 1), "serial": serial,
            "remote": sess.get("remote"), "local": sess.get("local"),
            "dir": sess.get("dir"), "ok": None, "err": None,
            "done": threading.Event(),
        }
        seg_no = prev["n"] + 1
        remote = self._seg_remote(serial, sess.get("ts"), seg_no)
        local = self._seg_local(
            sess.get("dir"), serial, sess.get("extra"), seg_no)
        try:
            proc = subprocess.Popen(
                self._screenrecord_cmd(self.adb, serial, remote,
                                       no_limit=bool(sess.get("no_lim"))),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                **adb_popen_kwargs())
        except Exception as e:
            # 接不上下一段：录制到此为止。但**上一段是完好的**，必须照样收进
            # 产物里 —— 什么都不做的话它既不会被拉回、也不会进包，用户白录。
            sess.setdefault("segments", []).append(prev)
            self._pull_segment_bg(prev)
            sess["seg"] = seg_no
            sess["died"] = True
            sess["seg_err"] = "第 %d 段未能启动（%s）" % (seg_no, e)
            return
        sess.setdefault("segments", []).append(prev)
        # 旧段的 adb proc 通常已退出（它的 --time-limit 到了 / 设备端写完 moov），
        # 但 pipe 句柄还在父进程里。每 roll 一次就留一份，Windows 上累积多段会
        # 触发句柄耗尽。主动关掉立即释放。
        old_proc = sess.get("proc")
        if old_proc is not None:
            for s in ("stdout", "stderr"):
                try:
                    f = getattr(old_proc, s, None)
                    if f is not None: f.close()
                except Exception:
                    pass
        sess["remote"] = remote
        sess["local"] = local
        sess["proc"] = proc
        sess["started"] = time.time()
        sess["seg"] = seg_no
        sess["rolled"] = seg_no
        # 上一段的拉取与下一段的启动**并行**：pull 要几百毫秒到几秒，串行等它
        # 会把段间缝隙从「一次 adb 往返」拉长成好几秒，而那段画面往往正是用户
        # 最想保住的操作过程。
        self._pull_segment_bg(prev)
        threading.Thread(
            target=self._watch_exit, args=(serial, proc), daemon=True,
            name="rec-watch-%s-%d" % (serial, seg_no)).start()
        threading.Thread(
            target=self._confirm_segment, args=(serial, proc, seg_no),
            daemon=True,
            name="rec-confirm-%s-%d" % (serial, seg_no)).start()

    def _confirm_segment(self, serial, proc, seg_no):
        """（后台）确认新起的这一段没有立刻退出。

        新段可能因为编码器还被上一段占着、设备端磁盘满而立刻退出 —— 这同样是
        「意外中断」，但只标一个 died 说不清是哪一段、为什么。而这时**前面几段
        其实是完整可用的**，用户最需要知道的就是这一点（否则会把整场录制扔掉）。
        """
        time.sleep(1.5)
        try:
            if proc.poll() is None:
                return
        except Exception:
            return
        with self._lock:
            sess = self._sessions.get(serial)
            if sess is None or sess.get("proc") is not proc:
                return
            if sess.get("stopping"):
                return
            sess["died"] = True
            if not sess.get("seg_err"):
                why = self._proc_err(proc)
                sess["seg_err"] = "第 %d 段启动后立即退出%s" % (
                    seg_no, "（%s）" % why if why else "")

    def _pull_segment_bg(self, seg):
        """（后台）把一段已录完的视频拉回本地，结果写回 seg。

        seg 自带 done 事件：stop_ex() 收尾时会等它，避免「拉取还在进行、打包
        已经把源文件删掉」这种丢数据的收尾。
        """
        def run():
            try:
                ok, local, err = self._pull_one(seg)
            except Exception as e:
                ok, local, err = False, None, str(e)[:200]
            seg["ok"] = ok
            seg["err"] = err
            if local:
                seg["local"] = local
            seg["done"].set()

        threading.Thread(
            target=run, daemon=True,
            name="rec-pull-%s-%s" % (seg.get("serial"), seg.get("n"))).start()

    def rolled_serials(self):
        """取出并清除「已自动开始下一段」标记（controller 轮询播报用）。

        返回 [(serial, 段号)]。用户点了「开始」就该知道程序在自己续录：不提示的
        话，录到第 3 段时保存目录里突然多出两个 mp4，没人说得清它们从哪来的。
        """
        with self._lock:
            out = []
            for s, sess in self._sessions.items():
                n = sess.pop("rolled", None)
                if n:
                    out.append((s, n))
            return out

    def seg_notes(self):
        """{serial: 分段相关说明}（只读快照，收尾文案用）。

        主要承载「续段失败」的原因：这时前几段是完整的，笼统一句「录屏被意外
        中断」会让用户以为全没了，把已经录好的部分一起扔掉。
        """
        with self._lock:
            return {s: sess["seg_err"] for s, sess in self._sessions.items()
                    if sess.get("seg_err")}

    def died_serials(self):
        """取出并清除「意外退出」标记的序列号（controller 轮询调用）。

        只清 died 标记本身，会话条目保留（收尾时还要靠它拉残片），
        因此同一台设备只会被汇报一次，不会被反复收尾。
        """
        with self._lock:
            out = [s for s, sess in self._sessions.items() if sess.get("died")]
            for s in out:
                self._sessions[s].pop("died", None)
            return out

    def limit_serials(self):
        """取出并清除「跑到单段上限（180s）后自行结束」标记（controller 轮询调用）。

        与 `died_serials()` 分开：两者都走同一条收尾路径，但文案必须不同 ——
        跑到上限是**正常结束**（screenrecord 会先写回 moov 再退出，视频完整），
        报成「被意外中断、请完整重录」是纯误导。
        """
        with self._lock:
            out = [s for s, sess in self._sessions.items()
                   if sess.get("limit_hit")]
            for s in out:
                self._sessions[s].pop("limit_hit", None)
            return out

    def is_recording(self, serial):
        with self._lock:
            return serial in self._sessions

    def any_recording(self):
        """是否有设备正在录屏（会话未收尾都算）。

        供「adb server 自愈」判断：重启 server 会掐断在途的 `adb shell`，把正在
        录的 screenrecord 一起弄死，所以录屏期间必须暂缓自愈。
        """
        with self._lock:
            return bool(self._sessions)

    def _spawn_and_confirm(self, cmd):
        """拉起 screenrecord 并短暂确认它真的活着。

        返回 (proc, early_err)：
        * proc 为 None 表示 Popen 本身失败，early_err 为「启动录屏失败：…」；
        * proc 非 None 但 early_err 非 None 表示进程在 1~2s 内提前退出
          （权限 / 参数错误等），early_err 为其 stderr 摘要，proc 为已退出的
          进程对象（调用方据此识别「起来了但又挂了」并决定是否重试）；
        * 两者都为空（proc 存活、early_err 为 None）才能继续往下走。
        """
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                **adb_popen_kwargs())
        except Exception as e:
            return None, "启动录屏失败：%s" % e
        try:
            if proc.poll() is None:
                time.sleep(1.5)
            if proc.poll() is not None:
                # 设备端 screenrecord 的报错（`Unable to open file` /
                # `Permission denied` / `Codec ... not found`）是**远端命令的
                # 输出**，经 `adb shell` 落在 stdout；stderr 通常只有 adb 客户端
                # 自己的错误。只读 stderr 时这里恒为空，用户能看到的只有一句
                # 「screenrecord 提前退出」——最需要原因的时候偏偏没有原因。
                return proc, self._proc_err(proc)
        except Exception:
            pass
        return proc, None

    # ---- 设备系统设置（可视化 overlay：指针位置 / 触摸圆点）----
    # 录屏的「指针位置 / 触摸圆点」是设备系统设置的屏幕 overlay（系统开发者
    # 选项同款）：录前备份原值并开启，收尾时按原值恢复。它与 screenrecord
    # 命令参数无关——不往录屏命令传任何东西，启动零风险（全 Android 版本
    # 可用），且 overlay 画在屏幕上，会被 screenrecord 一并录进视频。
    @staticmethod
    def get_system_setting(adb, serial, key):
        """读设备 Settings.System 里的键。返回 (ok, 原值字符串)。

        原值可能是 "0" / "1" / "null"（从未设置过）。ok=False 表示读不到
        （adb 不可用等），调用方应按「无法恢复」处理（不恢复优于乱恢复）。
        """
        try:
            r = subprocess.run(
                [adb, "-s", serial, "shell", "settings", "get", "system",
                 key], **adb_kwargs(10))
            if r.returncode != 0:
                return False, None
            val = (r.stdout or "").strip()
            # 老版本 settings 读不存在键时返回空串而非 "null"
            return True, (val or "null")
        except Exception:
            return False, None

    @staticmethod
    def set_system_setting(adb, serial, key, value):
        """写 / 删设备 Settings.System 键。返回是否成功（失败不抛）。

        value 为 "1" / "0" / None（None 或 "null"/空 = 删除该键，
        用于恢复「从未设置过」的设备原状）。

        只回 bool：需要知道**为什么**失败的调用方用 set_system_setting_ex。
        """
        return VideoRecorder.set_system_setting_ex(adb, serial, key, value)[0]

    @staticmethod
    def set_system_setting_ex(adb, serial, key, value):
        """同 set_system_setting，但返回 (是否成功, 失败原因)。

        `settings put` 被系统拒绝时**不一定**返回非零：部分 ROM（尤其是国产
        定制系统的「安全策略」）把 `java.lang.SecurityException` /
        `Permission denial` 打到 stdout 后仍以 rc=0 退出。只看 returncode 会
        把「没改成」当成「改好了」：

          * 录屏开始时 → 用户勾了「指针位置 / 触摸圆点」，录像里却什么都没有；
          * 录屏结束时 → 以为把设备的值恢复了，实际 overlay 一直开着，用户
            下次正常用手机时满屏准星，却不知道是谁开的。

        判据与 adb 的其他调用一致：stdout/stderr 里出现明确的拒绝字样即算失败。
        """
        try:
            if value is None or str(value).strip().lower() in ("null", ""):
                cmd = [adb, "-s", serial, "shell", "settings", "delete",
                       "system", key]
            else:
                cmd = [adb, "-s", serial, "shell", "settings", "put",
                       "system", key, str(value)]
            r = subprocess.run(cmd, **adb_kwargs(10))
        except Exception as e:
            return False, str(e)[:160]
        out = "%s\n%s" % (r.stdout or "", r.stderr or "")
        low = out.lower()
        for hint in _SETTING_REJECT_HINTS:
            if hint in low:
                return False, " ".join(out.split())[:160]
        if r.returncode != 0:
            return False, (" ".join(out.split())[:160]
                           or "settings 返回 %d" % r.returncode)
        return True, ""

    def _stop_device_screenrecord(self, adb, serial, remote=None):
        """精准结束设备端 screenrecord：用 SIGINT 让其优雅收尾（写回 moov 头），这是录出
        可播放 MP4 的关键——screenrecord 只在 SIGINT（Ctrl-C）下收尾，仅 SIGTERM 会直接被杀、
        文件没收尾（无 moov 头、没有时长、播放不了）。

        收尾顺序统一收口到 backend.device_proc.kill_device_process（录屏 / 录音共用）：
        按 PID `kill -INT` → **等它把 moov 写完** → 确认仍存活才补 `-TERM`。早期这里把
        `-INT` 与 `-TERM` 背靠背发出去，进程很可能死在写 moov 的中途——等于白优雅一次，
        产物依旧是坏文件。

        **绝不能按进程名 pkill screenrecord**：投屏（`screenrecord --output-format=h264 -`）
        是同名进程，停止录屏时一刀按名字切下去，会把用户眼前正在看的投屏一起掐断，而设备
        明明好好的。因此只认「命令行里带本次录屏文件名」的那一条（remote 形如
        /data/local/tmp/adb_rec_<serial>_<ts>_<seq>.mp4，每次录制唯一）；精确取不到 PID 时
        退化为 `pkill -f <该文件名>`，仍然只命中自己那条。
        """
        match = os.path.basename(remote) if remote else None
        kill_device_process(adb, serial, "screenrecord", match=match,
                            fallback_name_kill=False)

    def stop(self, serial):
        """停止录屏并拉回本地。返回 (ok, local_path, err)。

        自动分段会把一场录制切成多个文件，本方法只回**第一段**（保留历史签名）；
        需要全部段请用 stop_ex()。controller 走的就是 stop_ex。
        """
        ok, paths, err = self.stop_ex(serial)
        return ok, (paths[0] if paths else None), err

    def stop_ex(self, serial):
        """停止录屏并拉回**全部段**。返回 (ok, [本地路径...], err)。

        路径按段序排列。某一段拉取失败时，只要能拿到残片也一并放进来 —— 半个
        视频总比什么都没有强，而且用户需要知道它躺在哪个文件里。
        """
        with self._lock:
            sess = self._sessions.get(serial)
            segs = list((sess or {}).get("segments") or [])
            if sess is not None:
                # 告知 _watch_exit：这是用户主动停止，别把随后的进程退出当成
                # 「意外死亡」上报给 controller（否则会触发一轮多余的自动收尾）。
                sess["stopping"] = True
        if sess is None:
            return False, [], "该设备未在录制"
        proc = sess.get("proc")
        # 1) POSIX：给本地 adb 客户端发 SIGINT（等价于终端里 Ctrl-C），adb 会把中断转发给
        #    设备端 screenrecord，后者由此优雅收尾（写回 moov 头并关闭文件）。这是标准停止路径，
        #    能确保录出可播放的 MP4。Windows 不支持给子进程 send_signal(SIGINT)，改为靠下方的
        #    设备端按 PID 精准结束。
        if proc is not None and os.name != "nt":
            try:
                proc.send_signal(signal.SIGINT)
            except Exception:
                pass
        # 2) 设备端按 PID 精准结束 screenrecord（比 pkill 更通用）；并给一点时间收尾。
        self._stop_device_screenrecord(self.adb, serial, sess.get("remote"))
        try:
            if proc is not None:
                proc.wait(timeout=10)
        except Exception:
            try:
                if proc is not None:
                    proc.kill()
            except Exception:
                pass
        # 关 pipe：录屏期间 stdout / stderr 可能积累少量 adb 报错；
        # proc 死掉后父进程的 pipe 句柄靠 GC 才被回收，Windows 上累积
        # 多段会短暂触发句柄耗尽。主动关掉立即释放。
        for s in ("stdout", "stderr"):
            try:
                f = getattr(proc, s, None)
                if f is not None: f.close()
            except Exception:
                pass
        ok, local, err = self._pull_and_finish(serial)
        # 3) 已录完的段是**在后台并行拉取**的（见 _roll_segment_bg）：必须等它们
        #    各自落地。不等的话，打包会删掉源文件、而 pull 线程还在往同一个路径
        #    写 —— 尾部落进已删除的 inode，那一段就此消失，且看不出来。
        #
        # paths 里只放**正常收尾**的段：缺 moov 的残片也塞进去的话，它会混在好
        # 文件里一起被打包，用户拿到一个播放不了的 mp4 却不知道是哪一个、为什么。
        # 残片路径改由 err 说明 —— 该有的信息一条不少，但不会被当成成品。
        paths = []
        notes = []
        for seg in sorted(segs, key=lambda x: x.get("n") or 0):
            if not seg["done"].wait(timeout=90):
                notes.append("第 %s 段的拉取未在 90 秒内完成" % seg.get("n"))
            p = seg.get("local")
            if seg.get("ok") and p and os.path.exists(p):
                paths.append(p)
                continue
            if seg.get("err"):
                notes.append("第 %s 段：%s" % (seg.get("n"), seg.get("err")))
            if p and os.path.exists(p):
                notes.append("（第 %s 段残片：%s）" % (seg.get("n"), p))
        # 当前段（段号最大）排在最后，与目录里的 _pN 顺序一致。
        if local and os.path.exists(local):
            if ok:
                paths.append(local)
            else:
                notes.append("（当前段残片：%s）" % local)
        msgs = ([err] if err else []) + notes
        return ok, paths, ("；".join(msgs) if msgs else None)

    def discard_ex(self, serial):
        """取消录制：停掉设备端 screenrecord 并把这一段**丢弃**，返回待删的本地文件。

        返回 (ok, [本地路径...], err)。

        与 stop_ex 的区别只有一条，但很关键：**不拉当前段**。用户点了「取消」，
        这次的内容他明确不要 —— 把几百 MB 从设备 pull 回来再删掉，既慢又白占
        磁盘（弱网下要几十秒，用户只会以为程序卡死）。已经在后台拉回的段（自动
        分段时每录满一段就并行拉一段）不重复下载，但它们的本地路径要交回调用方
        删掉：那些同样是本次录制的产物，取消后不该留在保存目录里。

        设备端临时文件一并 rm：screenrecord 拒绝覆盖同名文件，上一次取消留下的
        残留会让下一次录屏直接启动失败，而用户只会看到「录屏启动失败」，完全联
        想不到是上一次取消留下的。

        与 stop_ex 一样，必须先置 stopping 再收尾，否则 _watch_exit 会把这次退出
        当成「意外中断」上报，触发一轮多余的自动收尾（那时会话已不在，收尾拿不到
        任何东西，只在状态栏留下一条莫名其妙的告警）。
        """
        with self._lock:
            sess = self._sessions.get(serial)
            if sess is None:
                return False, [], "该设备未在录制"
            sess["stopping"] = True
        proc = sess.get("proc")
        # 1) POSIX：SIGINT 让 adb 转发中断，screenrecord 优雅收尾（我们随后删文件，
        #    但进程必须真的退出——否则它会一直占着编码器到 180 秒上限）。
        if proc is not None and os.name != "nt":
            try:
                proc.send_signal(signal.SIGINT)
            except Exception:
                pass
        self._stop_device_screenrecord(self.adb, serial, sess.get("remote"))
        stopped = True
        try:
            if proc is not None:
                proc.wait(timeout=10)
        except Exception:
            stopped = False
            try:
                if proc is not None:
                    proc.kill()
            except Exception:
                pass
        with self._lock:
            self._sessions.pop(serial, None)
        # 2) 已录完的段正在后台并行拉取：等它们各自结束再交路径，否则 pull 线程
        #    还在往同一个路径写，调用方删掉后它继续写进已删除的 inode —— 磁盘上
        #    看不到、也没人报错。
        paths, notes = [], []
        segs = sorted(sess.get("segments") or [], key=lambda x: x.get("n") or 0)
        for seg in segs:
            if not seg["done"].wait(timeout=90):
                notes.append("第 %s 段的拉取未在 90 秒内完成" % seg.get("n"))
            if seg.get("local"):
                paths.append(seg["local"])
        # 3) 设备端残留（当前段 + 各历史段）：无论 pull 成功与否都 rm 一遍，幂等。
        remotes = [sess.get("remote")] + [x.get("remote") for x in segs]
        for r in [x for x in remotes if x]:
            try:
                subprocess.run([self.adb, "-s", serial, "shell", "rm", "-f", r],
                               **adb_kwargs(10))
            except Exception:
                pass
        if not stopped:
            notes.append("设备端 screenrecord 未能确认退出")
        return stopped, paths, ("；".join(notes) if notes else None)

    def stop_all(self):
        """停止全部录制会话。

        每台设备单独兜异常：`stop()` 内部要写盘 / pull / 合成，任一环节抛错
        （最现实的是保存目录所在磁盘被拔掉）都不该让**后面的设备完全不被收尾** ——
        它们的设备端 screenrecord 会继续录到 Android 自带的 3 分钟上限，
        `_sessions` 里也已经 pop 掉无法重试（controller.shutdown 只是吞掉异常）。
        """
        with self._lock:
            serials = list(self._sessions.keys())
        for s in serials:
            try:
                self.stop(s)
            except Exception:
                continue

    @staticmethod
    def _remote_probe(adb, serial, remote):
        """探测设备端文件是否就绪。返回 (就绪, 说明, 设备是否已不可达)。

        收尾/写 moov 有延迟，所以「文件还不存在」值得退避重试；但**设备掉线**
        是另一回事——`adb shell ls` 会一路失败，重试 9 秒后依然失败，最终报的
        却是「设备端未生成录屏文件（screenrecord 可能未启动/提前退出）」，把
        用户引向一个并不存在的问题。两者必须分开：

          * `ls: /path: No such file or directory`（或空输出）→ 文件还没写好，等；
          * `error: device 'A1' not found` / `device offline` / `error: closed`
            → 设备已经不在了，再等也没有结果，应立即报真因。

        adb 的报错既可能落在 stdout 也可能落在 stderr（设备端命令的输出本来就
        在 stdout），两路都要采集，否则这句说明永远是空的。
        """
        try:
            r = subprocess.run(
                [adb, "-s", serial, "shell", "ls", remote], **adb_kwargs(15))
        except Exception as e:
            return False, str(e)[:200], False
        out = "%s\n%s" % (r.stdout or "", r.stderr or "")
        if r.returncode == 0 and (r.stdout or "").strip():
            return True, "", False
        low = out.lower()
        for hint in _DEVICE_GONE_HINTS:
            if hint in low:
                return False, " ".join(out.split())[:200], True
        return False, " ".join(out.split())[:200], False

    @staticmethod
    def _remote_exists(adb, serial, remote):
        """设备端文件是否存在（screenrecord 收尾后才生成，故 stop 时需轮询等待）。"""
        return VideoRecorder._remote_probe(adb, serial, remote)[0]

    @staticmethod
    def _mp4_has_moov(path):
        """MP4 是否含 moov 头（索引在文件尾部，screenrecord 优雅收尾时写回）。
        缺 moov 即未正常收尾，会没有时长、播放不了。仅扫描头/尾各 4MB（moov 在尾部）。"""
        try:
            size = os.path.getsize(path)
            if size < 64:
                return False
            with open(path, "rb") as f:
                head = f.read(min(size, 4 * 1024 * 1024))
                if b"moov" in head:
                    return True
                f.seek(max(0, size - 4 * 1024 * 1024))
                return b"moov" in f.read()
        except Exception:
            return False

    def _wait_device_back(self, serial, max_wait_s=60, interval_s=3):
        """等设备从 offline / reboot 回来。每 interval_s 秒 poll 一次 get-state。

        返回 True 表示设备已回到 state=device；False 表示等了 max_wait_s 仍未回来。
        给设备重启留足窗口（Android 冷启动一般 15~30 秒）。USB 拔线不会回来，
        这时也不会无限等——max_wait_s 到期就放弃。
        """
        deadline = time.time() + max(1, max_wait_s)
        while time.time() < deadline:
            try:
                r = subprocess.run(
                    [self.adb, "-s", serial, "get-state"], **adb_kwargs(5))
                if r.returncode == 0 and (r.stdout or "").strip() == "device":
                    return True
            except Exception:
                pass
            # 用 deadline 减当前时间算出剩余，避免等过了 deadline
            remain = deadline - time.time()
            if remain <= 0:
                break
            time.sleep(min(interval_s, remain))
        return False

    def _pull_and_finish(self, serial):
        with self._lock:
            sess = self._sessions.pop(serial, None)
        if sess is None:
            return False, None, "会话已结束"
        return self._pull_one(sess)

    def _pull_one(self, sess):
        """拉回**一段**录像并校验（不碰 self._sessions）。

        单独抽出来是因为自动分段：一段录完就要立刻拉一段，而拉取必须与下一段的
        启动并行（见 _pull_segment_bg），不能等整场结束再统一拉。sess 既可以是
        整场会话，也可以是里面的一段（两者都带 serial / remote / local / dir）。
        """
        serial = sess.get("serial")
        local = sess["local"]
        remote = sess["remote"]
        # 保存目录可能在录制过程中消失（U 盘/移动硬盘被拔、目录被删）。旧实现在这里
        # 直接抛 OSError：异常一路冒到 controller，跳过本会话的其余收尾，也让
        # stop_all 的循环中断、后面的设备统统不再收尾。转成一条明确的失败返回。
        try:
            os.makedirs(sess["dir"], exist_ok=True)
        except Exception as e:
            return False, local, "无法创建保存目录 %s：%s" % (sess["dir"], e)
        # 收尾/落盘有延迟：device 端 screenrecord 收到 SIGTERM 后需要一点时间写回
        # moov 头并关闭文件。这里先确认远端文件已就绪，再 pull，带退避重试。
        # 注意：adb 的报错信息有时落在 stdout（而非 stderr），两路都要采集，避免
        # 把真实错误吞成一句空泛的「pull 失败」。
        last_err = "pull 失败"
        for attempt in range(6):
            ready, why, gone = self._remote_probe(self.adb, serial, remote)
            if gone:
                # 设备掉线 / 未授权 / adb 连接断了：可能是拔线，也可能是用户在重启设备。
                # 设备重启期间 screenrecord 进程被杀、/data/local/tmp 里的 mp4 还没被
                # 系统清理（多数 ROM 重启后才会清，少数不清）——此时立即放弃会丢掉
                # 已经录好的那一段。给一次等待机会：等设备回来（最多 60 秒），
                # 回来后再 probe + pull。还不行才真正放弃。
                returned = self._wait_device_back(serial, max_wait_s=60)
                if not returned:
                    return False, None, (
                        "设备已断开，录屏文件无法取回（等待设备重启超时 60 秒）%s"
                        % ("（%s）" % why if why else ""))
                # 设备回来了！再 probe + pull 一次
                ready, why, gone = self._remote_probe(self.adb, serial, remote)
                if gone:
                    # 刚回来又掉了？那就真的没办法了
                    return False, None, (
                        "设备重连后再次断开，录屏文件无法取回%s"
                        % ("（%s）" % why if why else ""))
                # ready=False 但 gone=False：文件被系统清了（/data/local/tmp 重启后清空）
                # 或 screenrecord 被杀时根本没来得及 flush 任何东西
                if not ready:
                    return False, None, (
                        "设备已重启，但录屏临时文件已被系统清理或从未写入磁盘，"
                        "本次录制内容丢失"
                        + ("（%s）" % why if why else ""))
                # ready=True：文件还在！走下面的 pull 路径
                break
            if ready:
                try:
                    r = subprocess.run(
                        [self.adb, "-s", serial, "pull", remote, local],
                        **adb_kwargs(120))
                    err = ((r.stderr or "") + "\n" + (r.stdout or "")).strip()
                    if r.returncode == 0 and os.path.exists(local):
                        # 校验 MP4 已收尾（含 moov 头）：否则没有时长、播放不了
                        if not VideoRecorder._mp4_has_moov(local):
                            try:
                                subprocess.run(
                                    [self.adb, "-s", serial, "shell", "rm", "-f", remote],
                                    **adb_kwargs(10))
                            except Exception:
                                pass
                            # 状态文案由 controller 统一下发（这里只回结果）：早期在此
                            # 自行 push 一条 warn，controller 又按返回值推一条，同一次
                            # 失败会在状态栏出现两行内容重叠的提示。
                            return False, local, "录屏文件疑似未正常收尾（MP4 缺 moov 头，无法播放）"
                        # 录像结束，清理设备端临时文件
                        try:
                            subprocess.run(
                                [self.adb, "-s", serial, "shell", "rm", "-f", remote],
                                **adb_kwargs(10))
                        except Exception:
                            pass
                        # 同上：成功文案由 controller 按其上下文（是否合成音频 / 打包）
                        # 统一下发，这里再 push 一次会让状态栏出现两行相同的
                        # 「✓ 录屏已保存: <同一个路径>」。
                        return True, local, None
                    if err:
                        last_err = err[:200]
                        low = err.lower()
                        if any(h in low for h in _FATAL_PULL_HINTS):
                            # 已经拿到 adb 的明确答复，且它不会因为再等一会儿而变好
                            return False, None, "取回录屏文件失败：%s" % last_err
                    else:
                        last_err = "pull 返回非零但无错误输出（可能设备端文件未就绪）"
                except Exception as e:
                    last_err = str(e)[:200]
            else:
                last_err = ("设备端未生成录屏文件 %s（screenrecord 可能未启动/提前退出）"
                            % remote)
                if why:
                    # 带上 adb 原话：`ls` 报的是「文件不存在」还是别的，只有它说得清
                    last_err += "；%s" % why
                # `ls` 报权限不足 / 只读时，文件往往**是存在的**，只是读不到：
                # 再退避 9 秒也还是同一句话，而且最终那句「未生成录屏文件
                # （screenrecord 可能未启动/提前退出）」会把用户引向 screenrecord，
                # 真正该处理的是保存路径的权限。
                if why and any(h in why.lower() for h in _FATAL_PULL_HINTS):
                    return False, None, "无法读取设备端录屏文件：%s" % why
            if attempt < 5:
                time.sleep(0.6 * (attempt + 1))
        return False, None, last_err
