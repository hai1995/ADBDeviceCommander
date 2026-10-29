# -*- coding: utf-8 -*-
"""
core.clipboard —— 把图片写进**系统**剪贴板（零第三方依赖）
============================================================
给「工具 ▸ 设备截图 ▸ 同步至粘贴板」使用：截图落盘后要能直接 Ctrl+V 粘贴到
微信 / QQ / Word / 画图 / 浏览器等任意目标，所以必须操作**原生**剪贴板，
不能走浏览器里的 clipboard——WebView2 的 Async Clipboard API 对 image/png
支持不一致，且常因「文档未获得焦点 / 非安全上下文」静默失败。

为什么不用 Pillow / pywin32：
  * 二者都不在运行时依赖里（build.py 的 EXCLUDE_MODULES 明确把 PIL 排除出包，
    requirements.txt 也把 pillow 标为「仅用于生成图标」），引入会抬高 exe 体积与
    打包风险。故 Windows 侧直接 ctypes 调 user32/kernel32，PNG 解码用 zlib 手写
    （screencap 产出的 PNG 形态固定，见 decode_png 的注释）。Pillow 若**恰好**
    可导入（源码运行时常见）则作为加速路径用一下，用不上也不影响正确性。

各平台实现：
  * Windows  ctypes 同时投放两种格式：
             - CF_DIB ：BITMAPINFOHEADER + 32bpp BGRA（自下而上）。兼容性最好，
                        几乎所有 Windows 应用都能粘贴；
             - CF_PNG ：RegisterClipboardFormatW("PNG") + 原始 PNG 字节。体积更
                        小、带 alpha，Chrome / Edge / Office / 多数现代应用会优先
                        读它。
             两者任一成功即算成功（粘贴目标挑它认得的格式）。
             部分电脑（远程桌面 / 安全软件 / 剪贴板历史工具 / Win10+ 云剪贴板）
             会短暂持有剪贴板：Open/Empty 都正常，唯独 SetClipboardData 返回
             NULL——整段序列重试几轮（见 _WIN_ATTEMPTS）多数能撞上窗口，仍败则
             用 powershell -STA + .NET `Clipboard.SetImage` 兜底（独立进程、
             另一条 API 路径；图片字节经 stdin 送过去、子进程不碰截图文件，
             错误输出强制 UTF8，详见 _win_write_powershell）。
  * macOS    osascript：`set the clipboard to (read … as «class PNGf»)`。
  * Linux    Wayland → wl-copy，X11 → xclip（`-t image/png`）；都没装则给明确原因。

性能说明：纯 python 解 PNG 的 filter 还原是 CPU 密集活（1080x2400 约 1~2 秒），
这一段跑在截图的后台线程里，不卡界面。可选加速路径（按优先级）：
  * Pillow 若**恰好**可导入（源码运行时常见）整张图 C 层解码，快一个量级；
  * numpy 若可导入，filter 0/1/2 与 BGR 换位整行/整图向量化（见 _unfilter_np /
    _bgra_bottom_up_np），混合 filter 的图也能快数倍；
  * 两者都没有时回退逐字节纯 Python（本模块的既有实现，任何平台/环境可用）。
Average / Paeth 是行内逐字节递推，没有 C 层原语可向量化，仍走逐字节循环。

设计约定（与 core/* 其它模块一致）：
  * **绝不抛异常**：任何平台 / 任何异常都被兜住，返回 (ok, reason)；调用方据此
    写状态栏即可，剪贴板失败绝不影响「截图已保存到磁盘」这个主结果；
  * 纯逻辑 + headless：平台实现集中在可替换的 PLATFORM_IMPL 字典里，单测在 Linux
    上换成替身即可验证分派 / PNG 解码 / 失败语义（见 tests/test_core_clipboard.py）。
"""
import base64
import os
import struct
import subprocess
import sys
import time
import zlib

try:
    from core import imgbytes
except ImportError:                  # 以 core/ 为 sys.path[0] 直接跑时
    import imgbytes

# 可选加速：numpy 不在运行时依赖里（requirements 标「可选」），导入失败
# （没装 / 装坏）一律回退下面的纯 Python 实现，功能与结果完全一致。
try:
    import numpy as _np
except Exception:
    _np = None

CF_DIB = 8                      # BITMAPINFO + 像素（Windows 剪贴板「通用位图」格式）
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
# DIB 上限（1080x2400 约 8MB，这里留足余量；超出的多半是畸形宽高，直接放弃 DIB）
_MAX_DIB_BYTES = 128 * 1024 * 1024
# Windows：完整「开→清→投→关」序列的重试参数。SetClipboardData 返回 NULL 在
# 部分电脑上是短暂现象（第三方正握着剪贴板），换一轮重来多半就撞上窗口。
_WIN_ATTEMPTS = 3
_WIN_RETRY_SLEEP = (0.1, 0.2, 0.4)      # 轮与轮之间的退避（秒）
_WIN_OPEN_TRIES = 10                    # 每轮里 OpenClipboard 的重试次数
_WIN_OPEN_SLEEP = 0.05
# PowerShell 兜底：起一次独立进程就要 1~2 秒（.NET 装配 + STA），但剪贴板被
# 第三方短暂持有时多撞一次窗口往往就撞上了——重试 2 轮、轮间 0.3 秒。
_WIN_PS_ATTEMPTS = 2
_WIN_PS_RETRY_SLEEP = 0.3


# --------------------------------------------------------------------------
# 对外 API
# --------------------------------------------------------------------------
def supported():
    """当前平台是否能把图片写进剪贴板。返回 (bool, 说明)。"""
    impl = PLATFORM_IMPL.get(sys.platform)
    if impl is None:
        return False, "当前平台（%s）暂不支持自动写入剪贴板" % sys.platform
    return True, ""


def copy_image(path):
    """把本地图片文件（PNG / JPG 等）写进系统剪贴板。返回 (ok, reason)。

    失败原因写成人话（直接供状态栏展示），且本函数在任何情况下都不抛异常。
    """
    try:
        if not path or not os.path.isfile(path):
            return False, "图片不存在: %s" % (path or "<空>")
        with open(path, "rb") as f:
            raw = f.read()
        if not raw:
            return False, "图片为空: %s" % path
    except Exception as e:                                  # 连读盘也永不冒泡
        return False, "读取图片失败: %s" % e

    impl = PLATFORM_IMPL.get(sys.platform)
    if impl is None:
        return False, "当前平台（%s）暂不支持自动写入剪贴板" % sys.platform

    # 先归一化字节：某些车机 / 定制 ROM 的 screencap 会在 PNG 前吐几行自己的
    # 东西，文件因此「开头不是 PNG」——ctypes 那条只投 CF_PNG/CF_DIB 的分支会被
    # 整段跳过，退到 GDI+ 时报一句与真相无关的「参数无效」。
    data, kind, note = imgbytes.normalize(raw)
    if not data:
        return False, "图片格式无法识别（%s）" % note

    # 只有 PNG 才需要解码成像素（其它格式交给平台自身的图片 API）
    png = data if kind == "png" else b""
    pix = decode_png(data) if png else None
    try:
        ok, reason = impl(data, png, pix, path)
    except Exception as e:
        return False, "写入剪贴板异常: %s" % e
    return bool(ok), reason


# --------------------------------------------------------------------------
# PNG → (宽, 高, 自下而上 BGRA 像素)，可直接塞进 CF_DIB
# --------------------------------------------------------------------------
def decode_png(data):
    """把 PNG 字节解码成 (w, h, bgra)。失败返回 None。

    支持范围（足以覆盖 adb screencap 的产出）：8bit / 非隔行 / 颜色类型
    2(RGB) 与 6(RGBA)。其它形态（隔行、16bit、调色板、灰度）返回 None，
    调用方会退化为「只投 CF_PNG」，不至于整张图都丢掉。
    """
    try:
        if not data or data[:8] != _PNG_MAGIC:
            return None
        w = h = bd = ct = None
        interlace = None
        idat = []
        pos, total = 8, len(data)
        while pos + 8 <= total:
            length = int.from_bytes(data[pos:pos + 4], "big")
            tag = data[pos + 4:pos + 8]
            body = data[pos + 8:pos + 8 + length]
            pos += 12 + length                              # 数据内容 + CRC
            if tag == b"IHDR" and length >= 13:
                w = int.from_bytes(body[0:4], "big")
                h = int.from_bytes(body[4:8], "big")
                bd, ct = body[8], body[9]
                interlace = body[12]
            elif tag == b"IDAT":
                idat.append(body)
            elif tag == b"IEND":
                break
        if not (w and h) or bd != 8 or ct not in (2, 6) or interlace != 0:
            return None
        bpp = 4 if ct == 6 else 3
        stride = w * bpp
        if stride * h > _MAX_DIB_BYTES:
            return None
        raw = zlib.decompress(b"".join(idat))
        if len(raw) < h * (stride + 1):
            return None
        # 注意它固定输出 RGBA，故只在 PNG 本身就是 RGBA（ct=6，stride 一致）时才用，
        # 否则行距对不上会把图切坏。加速器的任何异常都必须导向回落，绝不能连累主路径。
        topdown = None
        if ct == 6:
            try:
                topdown = _pillow_rgba(data)
            except Exception:
                topdown = None
        if topdown is not None:
            # Pillow 已还原为自上而下 RGBA 字节流；包成 ndarray，让 BGR 换位
            # 也走向量化（无 numpy 时保持 bytes，_bgra_bottom_up 自行分派）。
            if _np is not None:
                topdown = _np.frombuffer(
                    topdown, dtype=_np.uint8).reshape(h, stride)
        else:
            # 无 Pillow：filter 还原按「有无关 numpy」分派向量化 / 纯 Python，
            # 两条路径输出逐字节一致（tests/test_core_clipboard.py 有对拍）。
            topdown = _unfilter(raw, h, stride, bpp)
        return _bgra_bottom_up(topdown, w, h, bpp, stride)
    except Exception:
        return None


def _pillow_rgba(data):
    """可选加速：Pillow 可用时返回自上而下的 RGBA 字节流，否则 None。

    延迟导入 + 只在 decode_png 里被调用（外层已兜异常），这里就不再重复 try 了。
    """
    import io
    from PIL import Image                                   # 装了才用，没装是常态

    img = Image.open(io.BytesIO(data))
    return img.convert("RGBA").tobytes()


def _unfilter(raw, h, stride, bpp):
    """按行还原 PNG 的 5 种 filter，返回自上而下的像素缓冲。

    numpy 可用时返回 (h, stride) 的 uint8 ndarray，否则 bytearray；
    两者内容逐字节一致（见 _unfilter_np / _unfilter_py 与对拍测试）。
    """
    if _np is not None:
        try:
            return _unfilter_np(raw, h, stride, bpp)
        except Exception:
            pass                       # 任何意外都回落纯 Python，绝不中断解码
    return _unfilter_py(raw, h, stride, bpp)


def _unfilter_np(raw, h, stride, bpp):
    """numpy 向量化版 filter 还原（语义与 _unfilter_py 逐字节一致）。

    * filter 0 (None)  整行拷贝（C 层 memmove）；
    * filter 1 (Sub)   按 bpp 通道分组做前缀累加：PNG 规范的 Sub 递推
                       `recon[x] = raw[x] + recon[x-bpp]` 正是「每通道
                       独立的前缀和」，cumsum 一步算完整行；
    * filter 2 (Up)    整行加一行（uint8 加法天然按 256 回绕）；
    * filter 3/4 (Average/Paeth) 行内逐字节递推，没有 C 层原语可向量化，
                       回落逐字节循环（_filter_row_avg_paeth）。一张图里
                       0/1/2 通常占多数，整体仍比纯 Python 快一个量级。
    """
    buf = _np.frombuffer(raw, dtype=_np.uint8)
    out = _np.empty((h, stride), dtype=_np.uint8)
    prev = _np.zeros(stride, dtype=_np.uint8)
    row_len = stride + 1                                   # 每行 = 1 字节 filter + stride 数据
    for y in range(h):
        base = y * row_len
        filt = int(buf[base])
        line = buf[base + 1: base + 1 + stride]
        if filt == 0:
            out[y] = line
        elif filt == 1:
            m = line.reshape(-1, bpp).astype(_np.uint16)   # (w, bpp)，按列=按通道
            m = _np.cumsum(m, axis=0, dtype=_np.uint16)
            _np.bitwise_and(m, 0xFF, out=m)
            out[y] = m.astype(_np.uint8).reshape(stride)
        elif filt == 2:
            _np.add(line, prev, out=out[y])                # uint8 溢出回绕即 & 0xFF
        elif filt in (3, 4):
            out[y] = _np.frombuffer(
                _filter_row_avg_paeth(line.tobytes(), prev.tobytes(), bpp, filt),
                dtype=_np.uint8)
        else:
            raise ValueError("未知 PNG filter %d" % filt)
        prev = out[y]
    return out


def _filter_row_avg_paeth(line, prev, bpp, filt):
    """单行 Average / Paeth 的逐字节还原（返回 bytearray）。

    line / prev 为 bytes；filt ∈ {3, 4}。这两种 filter 的每个字节都依赖
    「本行已还原的左字节」，是行内串行递推，无法用 cumsum 之类一次算完——
    numpy 路径对它们也只能逐字节（与纯 Python 同速），故单独抽出复用。
    """
    out = bytearray(len(line))
    if filt == 3:                                        # Average
        for i in range(len(line)):
            a = out[i - bpp] if i >= bpp else 0
            out[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
    else:                                                # Paeth
        for i in range(len(line)):
            a = out[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            p = a + b - c
            pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
            pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
            out[i] = (line[i] + pr) & 0xFF
    return out


def _unfilter_py(raw, h, stride, bpp):
    """按行还原 PNG 的 5 种 filter，返回自上而下的像素缓冲（bytearray）。

    这是整个模块唯一的 CPU 热点：逐字节 Python 循环，1080x2400 约 1~2 秒，
    跑在后台线程里。刻意不去位运算黑化（SWAR）——为了几秒钟牺牲可读性不划算。
    （numpy 路径见 _unfilter_np：0/1/2 向量化，3/4 仍逐字节。）
    """
    out = bytearray(stride * h)
    prev = bytes(stride)                                     # 上一行（首行视为全 0）
    off = 0
    for _y in range(h):
        filt = raw[_y * (stride + 1)]
        begin = _y * (stride + 1) + 1
        line = bytearray(raw[begin:begin + stride])
        if len(line) != stride:
            raise ValueError("PNG 行数据不完整")
        if filt == 1:                                        # Sub：加左边同通道像素
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif filt == 2:                                      # Up：加正上方像素
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif filt == 3:                                      # Average
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif filt == 4:                                      # Paeth
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        elif filt != 0:
            raise ValueError("未知 PNG filter %d" % filt)
        out[off:off + stride] = line
        off += stride
        prev = bytes(line)
    return out


def _bgra_bottom_up(topdown, w, h, bpp, stride):
    """RGB/RGBA → 32bpp BGRA，并翻转成 CF_DIB 要求的**自下而上**行序。

    topdown 为 (h, stride) 的 uint8 ndarray（numpy 路径）或 bytes/bytearray
    （纯 Python 路径）；两条路径输出逐字节一致（有对拍测试）。
    """
    if _np is not None and isinstance(topdown, _np.ndarray):
        try:
            return _bgra_bottom_up_np(topdown, w, h, bpp, stride)
        except Exception:
            pass                       # 任何意外回落纯 Python，绝不中断解码
    return _bgra_bottom_up_py(topdown, w, h, bpp, stride)


def _bgra_bottom_up_np(topdown, w, h, bpp, stride):
    """numpy 版通道换位 + 行翻转：整图一步完成（C 层 memcpy，无逐行 Python 循环）。

    通道换位与行翻转都用扩展切片完成，避免逐像素 Python 循环 ——
    这是解码里唯一还能抠出来的性能，<_unfilter 则无能为力。
    """
    dstride = w * 4
    if dstride * h > _MAX_DIB_BYTES:
        raise ValueError("位图过大 %dx%d" % (w, h))
    arr = topdown.reshape(h, w, bpp)[::-1]          # 自下而上行序
    d = _np.empty((h, w, 4), dtype=_np.uint8)
    d[..., 0] = arr[..., 2]                          # B
    d[..., 1] = arr[..., 1]                          # G
    d[..., 2] = arr[..., 0]                          # R
    if bpp == 4:
        d[..., 3] = arr[..., 3]                      # A
    else:                                            # RGB：补满不透明 alpha
        d[..., 3] = 255
    return w, h, d.tobytes()


def _bgra_bottom_up_py(topdown, w, h, bpp, stride):
    """RGB/RGBA → 32bpp BGRA，并翻转成 CF_DIB 要求的**自下而上**行序。

    通道换位与行翻转都用扩展切片（C 层 memcpy）完成，避免逐像素 Python 循环 ——
    这是解码里唯一还能抠出来的性能，<_unfilter 则无能为力。
    """
    dstride = w * 4
    if dstride * h > _MAX_DIB_BYTES:
        raise ValueError("位图过大 %dx%d" % (w, h))
    dib = bytearray(dstride * h)
    for y in range(h):
        s0 = (h - 1 - y) * stride                            # 自下而上取源行
        src = bytes(topdown[s0:s0 + stride])
        d0 = y * dstride
        if bpp == 4:
            dib[d0:d0 + dstride] = src
            dib[d0 + 0:d0 + dstride:4] = src[2::4]           # B
            dib[d0 + 2:d0 + dstride:4] = src[0::4]           # R
        else:                                                # RGB：补满不透明 alpha
            dib[d0 + 0:d0 + dstride:4] = src[2::3]
            dib[d0 + 1:d0 + dstride:4] = src[1::3]
            dib[d0 + 2:d0 + dstride:4] = src[0::3]
            dib[d0 + 3:d0 + dstride:4] = b"\xff" * w
    return w, h, bytes(dib)


# --------------------------------------------------------------------------
# 平台实现：统一签名 (raw, png, pix, path) -> (ok, reason)
# --------------------------------------------------------------------------
def copy_windows(raw, png, pix, path):
    """Windows：ctypes 投放 CF_DIB + CF_PNG，任一成功即算成功。

    部分电脑上 OpenClipboard / EmptyClipboard 都正常，唯独 SetClipboardData
    返回 NULL——常见元凶：远程桌面会话（rdpclip 卡住）、安全软件 / 剪贴板
    历史工具（Ditto、360、电脑管家）正握着剪贴板、Win10+ 云剪贴板同步。
    这些持有都是**短暂**的，所以对策是两层：
      1. 整段序列重试 _WIN_ATTEMPTS 轮，轮间退避 0.1/0.2 秒（全程 < 1 秒）；
      2. 仍败则调 powershell -STA 用 .NET `Clipboard.SetImage` 兜底——独立
         进程、另一条 API 路径；图片字节经 stdin 送过去（子进程不碰文件，
         详见 _win_write_powershell）。兜底也重试 _WIN_PS_ATTEMPTS 轮。
    """
    import ctypes

    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except Exception as e:
        return False, "无法访问 Windows 剪贴板 API: %s" % e

    _bind_win(user32, kernel32)
    last_reason = ""
    if png or pix:
        for attempt in range(_WIN_ATTEMPTS):
            ok, reason = _win_write_once(user32, kernel32, png, pix)
            if ok:
                return True, ""
            last_reason = reason or last_reason
            if attempt + 1 < _WIN_ATTEMPTS:
                time.sleep(_WIN_RETRY_SLEEP[min(attempt,
                                                len(_WIN_RETRY_SLEEP) - 1)])
    # ctypes 全败（或压根没有可投的格式，如 JPG）：换 PowerShell + .NET 走几轮
    ok, ps_reason = _win_write_powershell(path, raw)
    if ok:
        return True, ""
    parts = []
    if last_reason:
        parts.append("直接写入：%s" % last_reason)
    if ps_reason:
        parts.append(ps_reason)
    detail = "；".join(parts) or "没有可写入剪贴板的图片数据"
    return False, ("Windows 剪贴板写入失败（%s）。常见于远程桌面会话、"
                   "安全软件或剪贴板工具正占用剪贴板——可重试截图，"
                   "或先手动复制一次其它内容再试" % detail)


def _win_write_once(user32, kernel32, png, pix):
    """一轮完整序列：开（短暂重试）→ 清空 → 投 PNG/DIB → 关。返回 (ok, reason)。

    剪贴板是全局独占资源：别的程序（或刚才那次粘贴）可能正占着，
    OpenClipboard 要短暂重试。SetClipboardData 失败多为剪贴板被第三方
    短暂持有，由外层 copy_windows 整段重试。
    """
    for _attempt in range(_WIN_OPEN_TRIES):
        if user32.OpenClipboard(None):
            break
        time.sleep(_WIN_OPEN_SLEEP)
    else:
        return False, "剪贴板被其它程序占用，请稍后再试"
    try:
        if not user32.EmptyClipboard():
            return False, "无法清空剪贴板（可能被其它程序锁定）"
        ok_dib = ok_png = False
        if png:
            fmt = user32.RegisterClipboardFormatW("PNG")
            if fmt:
                ok_png = _win_set(user32, kernel32, fmt, png)
        if pix:
            w, h, bgra = pix
            header = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 32, 0,
                                 len(bgra), 0, 0, 0, 0)
            ok_dib = _win_set(user32, kernel32, CF_DIB, header + bgra)
        if ok_dib or ok_png:
            return True, ""
        return False, "SetClipboardData 未接受该数据"
    finally:
        user32.CloseClipboard()


def _ps_text(b):
    """把 PowerShell 子进程的输出字节解成可读文本。

    中文 Windows 上 PowerShell 的 stderr 默认按系统 ANSI 代码页（GBK）输出，
    Python 按 UTF-8 硬解会得到「ʱ쳣ڴ治㡣」式乱码——用户报障时最难读的就是它。
    脚本里已把 [Console]::OutputEncoding 设为 UTF8（正常走 utf-8 分支），
    这里再兜底 gbk，都失败才 replace，保证任何输入都有东西可看。
    """
    if not b:
        return ""
    for enc in ("utf-8", "gbk"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", "replace")


def _win_write_powershell(path, raw=None):
    """兜底：powershell -STA 调 .NET `Clipboard.SetImage` 写剪贴板。

    与 ctypes 完全不同的路径（独立进程 + .NET 的剪贴板封装）：我们进程的
    剪贴板调用被安全软件拦、或线程状态异常时，它往往还能写进去。

    图片字节走 **stdin（base64）**，不让 PowerShell 去读文件：用户机器上的
    真实故障是 `Image.FromFile` 抛 GDI+「内存不足」——那通常是刚落盘的 PNG
    被反病毒 / 同步工具（备份、网盘扫描刚落盘文件）瞬时独占锁住，GDI+ 打不开
    文件时把所有错误都归成这一句，还会在走到剪贴板之前就整个失败。我们在
    Python 侧早已把整图读进内存（copy_image 的 raw），直接管带过去，子进程
    完全不碰文件，这一类失败从此不存在；GDI+ 的 FromStream 也认 JPG/BMP/GIF，
    补上 ctypes 路径只认 PNG 的短板。raw 为空（直接调 copy_windows 的非常规
    入口）时才回落 FromFile(path)。

    脚本内把 [Console]::OutputEncoding 设为 UTF8，错误信息不再有乱码
    （配合 Python 侧 _ps_text 的多编码兜底）。剪贴板持有是短暂的，整段重试
    _WIN_PS_ATTEMPTS 轮。返回 (ok, reason)。
    """
    import subprocess as sp

    b64 = base64.b64encode(raw).decode("ascii") if raw else ""
    quoted = str(path).replace("'", "''")       # PowerShell 单引号串转义
    script = (
        # 错误输出按 UTF8：中文 Windows 默认 GBK，Python 侧按 UTF-8 解会出乱码
        "try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {};"
        "Add-Type -AssemblyName System.Windows.Forms;"
        "Add-Type -AssemblyName System.Drawing;"
        "try {"
        "  $b64 = [Console]::In.ReadToEnd();"
        "  if ($b64) {"
        # 字节来自 stdin：子进程不打开截图文件，绕开「文件被 AV 独占锁」
        "    $bytes = [Convert]::FromBase64String($b64.Trim());"
        "    $ms = [System.IO.MemoryStream]::new($bytes);"
        "    $img = [System.Drawing.Image]::FromStream($ms);"
        "  } else {"
        "    $img = [System.Drawing.Image]::FromFile('%s');"
        "    $ms = $null;"
        "  }"
        "  [System.Windows.Forms.Clipboard]::SetImage($img);"
        "  $img.Dispose();"
        "  if ($ms) { $ms.Dispose() }"
        "} catch {"
        # 明确到「哪一步」失败的可读一行（不带 ErrorRecord 噪音）
        "  [Console]::Error.WriteLine('clipboard fallback failed: ' + $_.Exception.Message);"
        "  exit 1;"
        "}" % quoted)
    # CREATE_NO_WINDOW：别让控制台窗口闪一下（非 Windows 下该标志被忽略）
    flags = 0x08000000 if os.name == "nt" else 0
    last_reason = ""
    for attempt in range(_WIN_PS_ATTEMPTS):
        try:
            r = sp.run(["powershell", "-NoProfile", "-STA", "-Command", script],
                       input=b64.encode("ascii"), timeout=25,
                       stdout=sp.PIPE, stderr=sp.PIPE,
                       creationflags=flags)
        except FileNotFoundError:
            return False, "未找到 powershell（.NET 兜底不可用）"
        except sp.TimeoutExpired:
            last_reason = "PowerShell 兜底超时"
        else:
            if r.returncode == 0:
                return True, ""
            err = _ps_text(r.stderr).strip()[:200]
            # 带上字节数：GDI+ 的「参数无效」既可能是数据被截断，也可能是格式
            # 根本不认，有长度才分得清（下次报障时不用再猜）。
            last_reason = "PowerShell 兜底失败（%d 字节）：%s" % (
                len(raw or b""), err or "返回非零")
        if attempt + 1 < _WIN_PS_ATTEMPTS:
            time.sleep(_WIN_PS_RETRY_SLEEP)
    return False, last_reason


def _bind_win(user32, kernel32):
    """显式声明 ctypes 原型：64 位下句柄 / SIZE_T 的默认 int 转换会截断指针。"""
    import ctypes

    if getattr(user32, "_clipboard_bound", False):
        return
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_int
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = ctypes.c_int
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = ctypes.c_int
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.RegisterClipboardFormatW.argtypes = [ctypes.c_wchar_p]
    user32.RegisterClipboardFormatW.restype = ctypes.c_uint
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = ctypes.c_int
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.restype = ctypes.c_void_p
    user32._clipboard_bound = True


def _win_set(user32, kernel32, fmt, buf):
    """把 buf 拷进可移动全局内存并挂到剪贴板。成功后内存归系统所有，不可再释放。"""
    import ctypes

    GMEM_MOVEABLE = 0x0002
    hmem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(buf))
    if not hmem:
        return False
    ptr = kernel32.GlobalLock(hmem)
    if not ptr:
        kernel32.GlobalFree(hmem)
        return False
    try:
        ctypes.memmove(ptr, buf, len(buf))
    finally:
        kernel32.GlobalUnlock(hmem)
    if not user32.SetClipboardData(fmt, hmem):
        kernel32.GlobalFree(hmem)                            # 系统没收，自己擦屁股
        return False
    return True


def copy_macos(raw, png, pix, path):
    """macOS：交给 AppleScript 读文件进剪贴板（连 PNG 都不必自己解）。"""
    klass = "PNGf" if str(path).lower().endswith(".png") else "JPEG"
    quoted = str(path).replace("\\", "\\\\").replace('"', '\\"')
    script = ('set the clipboard to (read (POSIX file "%s") as «class %s»)'
              % (quoted, klass))
    try:
        r = subprocess.run(["osascript", "-e", script], timeout=20,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        return False, "未找到 osascript（非 macOS 环境）"
    except subprocess.TimeoutExpired:
        return False, "写入剪贴板超时"
    if r.returncode != 0:
        err = (r.stderr or b"").decode(errors="ignore")[:150]
        return False, "写入剪贴板失败：%s" % (err.strip() or "osascript 返回非零")
    return True, ""


def copy_linux(raw, png, pix, path):
    """Linux：Wayland 优先 wl-copy，X11 用 xclip（原生 PNG 类型，无需解码）。"""
    import shutil

    wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
    order = ["wl-copy", "xclip"] if wayland else ["xclip", "wl-copy"]
    tried = []
    for tool in order:
        if not shutil.which(tool):
            continue
        cmd = (["xclip", "-selection", "clipboard", "-t", "image/png"]
               if tool == "xclip" else ["wl-copy", "-t", "image/png"])
        try:
            with open(path, "rb") as f:
                r = subprocess.run(cmd, stdin=f, timeout=20,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        except FileNotFoundError:
            continue
        except subprocess.TimeoutExpired:
            tried.append("%s 超时" % tool)
            continue
        if r.returncode == 0:
            return True, ""
        err = (r.stderr or b"").decode(errors="ignore")[:120].strip()
        tried.append("%s：%s" % (tool, err or "返回非零"))
    return False, ("Linux 下需要 wl-copy（Wayland）或 xclip（X11）才能写图片剪贴板"
                   + ("（%s）" % "；".join(tried) if tried else ""))


PLATFORM_IMPL = {
    "win32": copy_windows,
    "darwin": copy_macos,
    "linux": copy_linux,
}
