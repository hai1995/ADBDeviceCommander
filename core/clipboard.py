"""
core.clipboard —— 把图片写进**系统**剪贴板（零第三方依赖）
============================================================
给「工具 ▸ 设备截图 ▸ 同步至粘贴板」使用。

为什么不用 Pillow / pywin32：
  * 二者都不在运行时依赖里。

各平台实现：
  * Windows  ctypes 同时投放两种格式：CF_DIB / CF_PNG。
  * macOS    osascript。
  * Linux    Wayland → wl-copy，X11 → xclip。

性能说明：纯 python 解 PNG 的 filter 还原是 CPU 密集活。

设计约定（与 core/* 其它模块一致）：
  * **绝不抛异常**：任何平台 / 任何异常都被兜住，返回 (ok, reason)。
"""
import base64
import os
import struct
import subprocess
import sys
import time
import zlib

from core.longpath import long_path, path_isfile

try:
    from core import imgbytes
except ImportError:
    import imgbytes

_NP_UNSET = object()
_np = _NP_UNSET


def _numpy():
    """按需导入 numpy；不可用返回 None（失败结果会被缓存，不反复重试）。"""
    global _np
    if _np is _NP_UNSET:
        try:
            import numpy as _mod
        except Exception:
            _mod = None
        _np = _mod
    return _np

CF_DIB = 8
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_MAX_DIB_BYTES = 128 * 1024 * 1024
_WIN_ATTEMPTS = 3
_WIN_RETRY_SLEEP = (0.1, 0.2, 0.4)
_WIN_OPEN_TRIES = 10
_WIN_OPEN_SLEEP = 0.05
_WIN_PS_ATTEMPTS = 2
_WIN_PS_RETRY_SLEEP = 0.3


def supported():
    """当前平台是否能把图片写进剪贴板。返回 (bool, 说明)。"""
    impl = PLATFORM_IMPL.get(sys.platform)
    if impl is None:
        return False, "当前平台（{}）暂不支持自动写入剪贴板".format(sys.platform)
    return True, ""


def copy_image(path):
    """把本地图片文件（PNG / JPG 等）写进系统剪贴板。返回 (ok, reason)。"""
    try:
        if not path or not path_isfile(path):
            return False, "图片不存在: %s" % (path or "<空>")
        with open(long_path(path), "rb") as f:
            raw = f.read()
        if not raw:
            return False, "图片为空: {}".format(path)
    except Exception as e:
        return False, "读取图片失败: {}".format(e)

    impl = PLATFORM_IMPL.get(sys.platform)
    if impl is None:
        return False, "当前平台（{}）暂不支持自动写入剪贴板".format(sys.platform)

    data, kind, note = imgbytes.normalize(raw)
    if not data:
        return False, "图片格式无法识别（{}）".format(note)

    png = data if kind == "png" else b""
    pix = decode_png(data) if png else None
    try:
        ok, reason = impl(data, png, pix, path)
    except Exception as e:
        return False, "写入剪贴板异常: {}".format(e)
    return bool(ok), reason


def decode_png(data):
    """把 PNG 字节解码成 (w, h, bgra)。失败返回 None。"""
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
            pos += 12 + length
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
        want = h * (stride + 1)
        raw = zlib.decompressobj().decompress(b"".join(idat), want)
        if len(raw) < want:
            return None
        topdown = None
        if ct == 6:
            try:
                topdown = _pillow_rgba(data)
            except Exception:
                topdown = None
        if topdown is not None:
            np = _numpy()
            if np is not None:
                topdown = np.frombuffer(
                    topdown, dtype=np.uint8).reshape(h, stride)
        else:
            topdown = _unfilter(raw, h, stride, bpp)
        return _bgra_bottom_up(topdown, w, h, bpp, stride)
    except Exception:
        return None


def _pillow_rgba(data):
    """可选加速：Pillow 可用时返回自上而下的 RGBA 字节流，否则 None。"""
    import io

    from PIL import Image

    img = Image.open(io.BytesIO(data))
    return img.convert("RGBA").tobytes()


def _unfilter(raw, h, stride, bpp):
    """按行还原 PNG 的 5 种 filter，返回自上而下的像素缓冲。"""
    if _numpy() is not None:
        try:
            return _unfilter_np(raw, h, stride, bpp)
        except Exception:
            pass
    return _unfilter_py(raw, h, stride, bpp)


def _unfilter_np(raw, h, stride, bpp):
    """numpy 向量化版 filter 还原（语义与 _unfilter_py 逐字节一致）。"""
    np = _numpy()
    buf = np.frombuffer(raw, dtype=np.uint8)
    out = np.empty((h, stride), dtype=np.uint8)
    prev = np.zeros(stride, dtype=np.uint8)
    row_len = stride + 1
    for y in range(h):
        base = y * row_len
        filt = int(buf[base])
        line = buf[base + 1: base + 1 + stride]
        if filt == 0:
            out[y] = line
        elif filt == 1:
            m = line.reshape(-1, bpp).astype(np.uint16)
            m = np.cumsum(m, axis=0, dtype=np.uint16)
            np.bitwise_and(m, 0xFF, out=m)
            out[y] = m.astype(np.uint8).reshape(stride)
        elif filt == 2:
            np.add(line, prev, out=out[y])
        elif filt in (3, 4):
            out[y] = np.frombuffer(
                _filter_row_avg_paeth(line.tobytes(), prev.tobytes(), bpp, filt),
                dtype=np.uint8)
        else:
            raise ValueError("未知 PNG filter %d" % filt)
        prev = out[y]
    return out


def _filter_row_avg_paeth(line, prev, bpp, filt):
    """单行 Average / Paeth 的逐字节还原（返回 bytearray）。"""
    out = bytearray(len(line))
    if filt == 3:
        for i in range(len(line)):
            a = out[i - bpp] if i >= bpp else 0
            out[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
    else:
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
    """按行还原 PNG 的 5 种 filter，返回自上而下的像素缓冲（bytearray）。"""
    out = bytearray(stride * h)
    prev = bytes(stride)
    off = 0
    for _y in range(h):
        filt = raw[_y * (stride + 1)]
        begin = _y * (stride + 1) + 1
        line = bytearray(raw[begin:begin + stride])
        if len(line) != stride:
            raise ValueError("PNG 行数据不完整")
        if filt == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif filt == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif filt == 3:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif filt == 4:
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
    """RGB/RGBA → 32bpp BGRA，并翻转成 CF_DIB 要求的**自下而上**行序。"""
    np = _numpy()
    if np is not None and isinstance(topdown, np.ndarray):
        try:
            return _bgra_bottom_up_np(topdown, w, h, bpp, stride)
        except Exception:
            pass
    return _bgra_bottom_up_py(topdown, w, h, bpp, stride)


def _bgra_bottom_up_np(topdown, w, h, bpp, stride):
    """numpy 版通道换位 + 行翻转：整图一步完成（C 层 memcpy）。"""
    np = _numpy()
    dstride = w * 4
    if dstride * h > _MAX_DIB_BYTES:
        raise ValueError("位图过大 %dx%d" % (w, h))
    arr = topdown.reshape(h, w, bpp)[::-1]
    d = np.empty((h, w, 4), dtype=np.uint8)
    d[..., 0] = arr[..., 2]
    d[..., 1] = arr[..., 1]
    d[..., 2] = arr[..., 0]
    if bpp == 4:
        d[..., 3] = arr[..., 3]
    else:
        d[..., 3] = 255
    return w, h, d.tobytes()


def _bgra_bottom_up_py(topdown, w, h, bpp, stride):
    """RGB/RGBA → 32bpp BGRA，并翻转成 CF_DIB 要求的**自下而上**行序。"""
    dstride = w * 4
    if dstride * h > _MAX_DIB_BYTES:
        raise ValueError("位图过大 %dx%d" % (w, h))
    dib = bytearray(dstride * h)
    for y in range(h):
        s0 = (h - 1 - y) * stride
        src = bytes(topdown[s0:s0 + stride])
        d0 = y * dstride
        if bpp == 4:
            dib[d0:d0 + dstride] = src
            dib[d0 + 0:d0 + dstride:4] = src[2::4]
            dib[d0 + 2:d0 + dstride:4] = src[0::4]
        else:
            dib[d0 + 0:d0 + dstride:4] = src[2::3]
            dib[d0 + 1:d0 + dstride:4] = src[1::3]
            dib[d0 + 2:d0 + dstride:4] = src[0::3]
            dib[d0 + 3:d0 + dstride:4] = b"\xff" * w
    return w, h, bytes(dib)


def copy_windows(raw, png, pix, path):
    """Windows：ctypes 投放 CF_DIB + CF_PNG，任一成功即算成功。"""
    import ctypes

    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except Exception as e:
        return False, "无法访问 Windows 剪贴板 API: {}".format(e)

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
    ok, ps_reason = _win_write_powershell(path, raw)
    if ok:
        return True, ""
    parts = []
    if last_reason:
        parts.append("直接写入：{}".format(last_reason))
    if ps_reason:
        parts.append(ps_reason)
    detail = "；".join(parts) or "没有可写入剪贴板的图片数据"
    return False, ("Windows 剪贴板写入失败（{}）。常见于远程桌面会话、"
                   "安全软件或剪贴板工具正占用剪贴板——可重试截图，"
                   "或先手动复制一次其它内容再试".format(detail))


def _win_write_once(user32, kernel32, png, pix):
    """一轮完整序列：开（短暂重试）→ 清空 → 投 PNG/DIB → 关。返回 (ok, reason)。"""
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
    """把 PowerShell 子进程的输出字节解成可读文本。"""
    if not b:
        return ""
    for enc in ("utf-8", "gbk"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", "replace")


def _win_write_powershell(path, raw=None):
    """兜底：powershell -STA 调 .NET `Clipboard.SetImage` 写剪贴板。"""
    import subprocess as sp

    b64 = base64.b64encode(raw).decode("ascii") if raw else ""
    quoted = str(path).replace("'", "''")
    script = (
        "try {{ [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 }} catch {{}};"
        "Add-Type -AssemblyName System.Windows.Forms;"
        "Add-Type -AssemblyName System.Drawing;"
        "try {{"
        "  $b64 = [Console]::In.ReadToEnd();"
        "  if ($b64) {{"
        "    $bytes = [Convert]::FromBase64String($b64.Trim());"
        "    $ms = [System.IO.MemoryStream]::new($bytes);"
        "    $img = [System.Drawing.Image]::FromStream($ms);"
        "  }} else {{"
        "    $img = [System.Drawing.Image]::FromFile('{}');"
        "    $ms = $null;"
        "  }}"
        "  [System.Windows.Forms.Clipboard]::SetImage($img);"
        "  $img.Dispose();"
        "  if ($ms) {{ $ms.Dispose() }}"
        "}} catch {{"
        "  [Console]::Error.WriteLine('clipboard fallback failed: ' + $_.Exception.Message);"
        "  exit 1;"
        "}}".format(quoted))
    flags = 0x08000000 if os.name == "nt" else 0
    last_reason = ""
    for attempt in range(_WIN_PS_ATTEMPTS):
        try:
            r = sp.run(["powershell", "-NoProfile", "-STA", "-Command", script],
                       input=b64.encode("ascii"), timeout=25,
                       capture_output=True, creationflags=flags)
        except FileNotFoundError:
            return False, "未找到 powershell（.NET 兜底不可用）"
        except sp.TimeoutExpired:
            last_reason = "PowerShell 兜底超时"
        else:
            if r.returncode == 0:
                return True, ""
            err = _ps_text(r.stderr).strip()[:200]
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
        kernel32.GlobalFree(hmem)
        return False
    return True


def copy_macos(raw, png, pix, path):
    """macOS：交给 AppleScript 读文件进剪贴板（连 PNG 都不必自己解）。"""
    klass = "PNGf" if str(path).lower().endswith(".png") else "JPEG"
    quoted = str(path).replace("\\", "\\\\").replace('"', '\\"')
    script = ('set the clipboard to (read (POSIX file "{}") as «class {}»)'.format(quoted, klass))
    try:
        r = subprocess.run(["osascript", "-e", script], timeout=20,
                           capture_output=True)
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
            with open(long_path(path), "rb") as f:
                r = subprocess.run(cmd, stdin=f, timeout=20,
                                   capture_output=True)
        except FileNotFoundError:
            continue
        except subprocess.TimeoutExpired:
            tried.append("{} 超时".format(tool))
            continue
        if r.returncode == 0:
            return True, ""
        err = (r.stderr or b"").decode(errors="ignore")[:120].strip()
        tried.append("{}：{}".format(tool, err or "返回非零"))
    return False, ("Linux 下需要 wl-copy（Wayland）或 xclip（X11）才能写图片剪贴板"
                   + ("（{}）".format("；".join(tried)) if tried else ""))


PLATFORM_IMPL = {
    "win32": copy_windows,
    "darwin": copy_macos,
    "linux": copy_linux,
}
