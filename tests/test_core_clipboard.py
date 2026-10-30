# -*- coding: utf-8 -*-
"""core.clipboard —— 图片写系统剪贴板单测（纯逻辑，不依赖真实设备 / 真实剪贴板）。

覆盖三件事：
  1. PNG → CF_DIB 像素的解码（对照独立参考实现，覆盖全部 5 种 filter）；
  2. 平台分派与**绝不抛异常**的契约（替身实现、异常实现、不支持的平台）；
  3. Windows ctypes 实现的资源语义（OpenClipboard 独占重试、SetClipboardData
     成功后的内存归属、任何路径都要 CloseClipboard）。
"""
import base64
import os
import shutil
import struct
import sys
import zlib

import pytest

import core.clipboard as cb

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------------------
# 测试用 PNG 生成（自己编码，避免依赖 Pillow / 固定素材）
# ---------------------------------------------------------------------------
def _chunk(tag, body):
    c = tag + body
    return struct.pack(">I", len(body)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)


def make_png(width, height, color_type=6, filters=(0,), bit_depth=8,
             interlace=0, seed=7):
    """构造一张 PNG，同时返回**解码前的原始像素行**（自上而下）作为对照基准。"""
    import random
    rnd = random.Random(seed)
    bpp = 4 if color_type == 6 else 3
    stride = width * bpp
    rows, truth = [], []
    prev = bytes(stride)
    for y in range(height):
        line = bytearray()
        for _x in range(width):
            line += bytes(rnd.randrange(256) for _ in range(bpp))
        truth.append(bytes(line))
        f = filters[y % len(filters)]
        if f == 1:  # Sub
            for i in range(stride - 1, bpp - 1, -1):
                line[i] = (line[i] - line[i - bpp]) & 0xFF
        elif f == 2:  # Up
            line = bytearray(((line[i] - prev[i]) & 0xFF) for i in range(stride))
        elif f == 3:  # Average
            for i in range(stride - 1, -1, -1):
                a = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] - ((a + prev[i]) >> 1)) & 0xFF
        elif f == 4:  # Paeth
            for i in range(stride - 1, -1, -1):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] - pr) & 0xFF
        rows.append(bytes([f]) + bytes(line))
        prev = truth[-1]
    ihdr = struct.pack(">IIBBBBB", width, height, bit_depth, color_type,
                       0, 0, interlace)
    data = (PNG_MAGIC + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(b"".join(rows), 6))
            + _chunk(b"IEND", b""))
    return data, truth


def expected_bgra(truth, width, height, bpp):
    """独立算一遍「自下而上 BGRA」，用逐像素写法（不复用被测代码）。"""
    out = bytearray(width * 4 * height)
    for y in range(height):
        row = truth[height - 1 - y]
        d0 = y * width * 4
        for x in range(width):
            s = x * bpp
            if bpp == 4:
                r, g, b, a = row[s], row[s + 1], row[s + 2], row[s + 3]
            else:
                r, g, b, a = row[s], row[s + 1], row[s + 2], 255
            out[d0 + x * 4:d0 + x * 4 + 4] = bytes((b, g, r, a))
    return bytes(out)


def assert_decodes(data, truth, width, height, color_type):
    got = cb.decode_png(data)
    assert got is not None, "该 PNG 应被解码"
    w, h, bgra = got
    assert (w, h) == (width, height)
    assert bgra == expected_bgra(truth, width, height,
                                 4 if color_type == 6 else 3)


# ---------------------------------------------------------------------------
# 1. PNG 解码
# ---------------------------------------------------------------------------
def test_decode_png_every_filter_matches_reference():
    """五种 filter（None/Sub/Up/Average/Paeth）与混排都要和独立参考实现一致。

    这是 CF_DIB 的关键：一旦还原错一个字节，粘贴出来的图就是花屏。
    """
    for color_type in (6, 2):
        for filters in ((0,), (1,), (2,), (3,), (4,), (0, 1, 2, 3, 4)):
            data, truth = make_png(23, 17, color_type, filters)
            assert_decodes(data, truth, 23, 17, color_type)


def test_decode_png_rgb_image_gets_opaque_alpha():
    """RGB（无 alpha 通道）要补成不透明，否则粘贴出的图会是全透明。"""
    data, truth = make_png(8, 4, color_type=2, filters=(1,))
    w, h, bgra = cb.decode_png(data)
    assert (w, h) == (8, 4)
    alpha = bytes(bgra[3::4])
    assert set(alpha) == {0xFF}, "RGB 图的 alpha 必须全为 255"


def test_decode_png_rejects_unsupported_variants():
    """隔行 / 16bit / 调色板形态直接放弃解码（调用方会退化为只投 CF_PNG）。"""
    interlaced, _ = make_png(9, 9, interlace=1)
    assert cb.decode_png(interlaced) is None
    depth16, _ = make_png(9, 9, bit_depth=16)
    assert cb.decode_png(depth16) is None
    palette, _ = make_png(9, 9, color_type=3)
    assert cb.decode_png(palette) is None


def test_decode_png_rejects_garbage_and_truncated():
    assert cb.decode_png(b"") is None
    assert cb.decode_png(b"not a png at all") is None
    good, _ = make_png(4, 4)
    assert cb.decode_png(good[:len(good) // 2]) is None   # IDAT 被截断


def test_decode_png_never_raises_on_corrupt_idat():
    """IDAT 是坏数据（zlib 解不开）时也不能炸，返回 None 让上层降级。"""
    ihdr = struct.pack(">IIBBBBB", 4, 4, 8, 6, 0, 0, 0)
    broken = (PNG_MAGIC + _chunk(b"IHDR", ihdr)
              + _chunk(b"IDAT", b"\x00\x01\x02bogus")
              + _chunk(b"IEND", b""))
    assert cb.decode_png(broken) is None


def test_pillow_fast_path_only_used_for_rgba(monkeypatch):
    """Pillow 输出固定是 RGBA：RGB 图若走它会 stride 错位，必须跳过。"""
    calls = []

    def fake_pillow(data):
        calls.append(len(data))
        return None

    monkeypatch.setattr(cb, "_pillow_rgba", fake_pillow)
    data_rgba, truth_rgba = make_png(6, 5, color_type=6)
    assert cb.decode_png(data_rgba) is not None
    assert len(calls) == 1, "RGBA 应尝试 Pillow 加速"

    calls.clear()
    data_rgb, truth_rgb = make_png(6, 5, color_type=2)
    assert cb.decode_png(data_rgb) is not None
    assert calls == [], "RGB 图不能走 Pillow（行距不一致）"


def test_pillow_failure_falls_back_to_stdlib(monkeypatch):
    """Pillow 抛异常 / 缺失时回落手撸解码，结果依旧正确（有 Pillow 与否同解）。"""

    def boom(data):
        raise ImportError("no pillow")

    monkeypatch.setattr(cb, "_pillow_rgba", boom)
    data, truth = make_png(7, 7, filters=(4, 2))
    assert_decodes(data, truth, 7, 7, 6)


# ---------------------------------------------------------------------------
# 1b. numpy 加速路径与纯 Python 路径对拍（输出必须逐字节一致）
# ---------------------------------------------------------------------------
def _encode_scanlines(rows, filters, bpp):
    """把原始行（自上而下）按指定 filter 编码成 PNG 规范的 raw 数据。

    编码逻辑与 make_png 一致（逆运算），供直接喂给 _unfilter_np / _unfilter_py。
    """
    out = bytearray()
    prev = bytes(len(rows[0]))
    for y, line in enumerate(rows):
        f = filters[y % len(filters)]
        enc = bytearray(line)
        if f == 1:                                          # Sub
            for i in range(len(enc) - 1, bpp - 1, -1):
                enc[i] = (enc[i] - enc[i - bpp]) & 0xFF
        elif f == 2:                                        # Up
            enc = bytearray(((enc[i] - prev[i]) & 0xFF)
                            for i in range(len(enc)))
        elif f == 3:                                        # Average
            for i in range(len(enc) - 1, -1, -1):
                a = enc[i - bpp] if i >= bpp else 0
                enc[i] = (enc[i] - ((a + prev[i]) >> 1)) & 0xFF
        elif f == 4:                                        # Paeth
            for i in range(len(enc) - 1, -1, -1):
                a = enc[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                enc[i] = (enc[i] - pr) & 0xFF
        out.append(f)
        out += enc
        prev = line
    return bytes(out)


def test_numpy_path_matches_pure_python(monkeypatch):
    """有/无 numpy 两条解码路径必须逐字节一致。

    numpy 路径把 filter 0/1/2 做了向量化（cumsum / 整行加），与纯 Python
    逐字节实现只要差一个字节，粘贴出来的图就是花屏——对拍锁死 correctness。
    """
    numpy = pytest.importorskip("numpy")
    # 关掉 Pillow 快路：本用例要逼数据走 filter 还原（_unfilter）
    monkeypatch.setattr(cb, "_pillow_rgba", lambda data: None)
    for color_type in (6, 2):
        for filters in ((0,), (1,), (2,), (3,), (4,), (0, 1, 2, 3, 4)):
            data, truth = make_png(23, 17, color_type, filters)
            monkeypatch.setattr(cb, "_np", None)           # 强制纯 Python
            r_py = cb.decode_png(data)
            monkeypatch.setattr(cb, "_np", numpy)          # 强制 numpy
            r_np = cb.decode_png(data)
            assert r_py == r_np, \
                "numpy 路径与纯 Python 不一致（ct=%s, filters=%s）" % (
                    color_type, filters)
            # 顺带验证两条路径都解对了（对照独立参考实现）
            w, h, bgra = r_np
            assert bgra == expected_bgra(truth, w, h, bpp=3 if color_type == 2 else 4)


def test_unfilter_np_matches_py_per_filter(monkeypatch):
    """_unfilter_np 与 _unfilter_py 对同一 raw 数据输出逐字节一致。"""
    numpy = pytest.importorskip("numpy")
    monkeypatch.setattr(cb, "_np", numpy)
    import random
    rnd = random.Random(11)
    for bpp in (3, 4):
        stride = 7 * bpp
        rows = [bytes(rnd.randrange(256) for _ in range(stride))
                for _ in range(9)]
        for filters in ((0,), (1,), (2,), (3,), (4,), (0, 1, 2, 3, 4)):
            raw = _encode_scanlines(rows, filters, bpp)
            got_np = bytes(cb._unfilter_np(raw, 9, stride, bpp))
            got_py = bytes(cb._unfilter_py(raw, 9, stride, bpp))
            assert got_np == got_py == b"".join(rows), \
                "filter %s 还原不一致" % (filters,)


def test_bgra_bottom_up_np_matches_py(monkeypatch):
    """BGR 换位 + 行翻转：numpy 整图版与纯 Python 逐行版输出一致。"""
    numpy = pytest.importorskip("numpy")
    monkeypatch.setattr(cb, "_np", numpy)
    import random
    rnd = random.Random(23)
    for bpp in (3, 4):
        w, h = 9, 6
        stride = w * bpp
        pix = bytes(rnd.randrange(256) for _ in range(stride * h))
        arr = numpy.frombuffer(pix, dtype=numpy.uint8).reshape(h, stride)
        r_np = cb._bgra_bottom_up_np(arr, w, h, bpp, stride)
        r_py = cb._bgra_bottom_up_py(pix, w, h, bpp, stride)
        assert r_np == r_py, "bgra 两条路径不一致（bpp=%d）" % bpp


def test_numpy_missing_still_decodes(monkeypatch):
    """没有 numpy 的环境（_np=None）解码照常且结果正确——加速是可选的。"""
    monkeypatch.setattr(cb, "_np", None)
    monkeypatch.setattr(cb, "_pillow_rgba", lambda data: None)
    data, truth = make_png(13, 9, color_type=6, filters=(1, 2, 4))
    assert_decodes(data, truth, 13, 9, 6)


# ---------------------------------------------------------------------------
# 2. copy_image 的分派与「绝不抛异常」
# ---------------------------------------------------------------------------
class _Capture:
    """替身平台实现：记录入参并返回预设结果（或抛异常）。"""

    def __init__(self, result=(True, ""), raise_it=False):
        self.result = result
        self.raise_it = raise_it
        self.calls = []

    def __call__(self, raw, png, pix, path):
        self.calls.append({"raw": raw, "png": png, "pix": pix, "path": path})
        if self.raise_it:
            raise RuntimeError("boom")
        return self.result


def _install_impl(monkeypatch, capture):
    monkeypatch.setitem(cb.PLATFORM_IMPL, sys.platform, capture)


def _write_tmp(tmp_path, data, name="shot.png"):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def test_copy_image_passes_png_bytes_and_decoded_pixels(tmp_path, monkeypatch):
    cap = _Capture()
    _install_impl(monkeypatch, cap)
    data, _truth = make_png(6, 5)
    path = _write_tmp(tmp_path, data)

    ok, reason = cb.copy_image(path)

    assert ok is True and reason == ""
    call = cap.calls[0]
    assert call["path"] == path
    assert call["raw"] == data
    assert call["png"] == data, "PNG 应原样透传（CF_PNG 用它）"
    w, h, _bgra = call["pix"]
    assert (w, h) == (6, 5)


def test_copy_image_non_png_skips_decoding(tmp_path, monkeypatch):
    """JPG 之类不必解码：平台侧可用系统 API 直接读文件，pix 传 None。"""
    cap = _Capture()
    _install_impl(monkeypatch, cap)
    path = _write_tmp(tmp_path, b"\xff\xd8\xff\xe0" + b"x" * 40, "shot.jpg")

    assert cb.copy_image(path) == (True, "")
    call = cap.calls[0]
    assert call["png"] == b""
    assert call["pix"] is None


def test_copy_image_missing_or_empty_file_is_reported(tmp_path, monkeypatch):
    cap = _Capture()
    _install_impl(monkeypatch, cap)
    ok, reason = cb.copy_image(str(tmp_path / "nope.png"))
    assert ok is False and "不存在" in reason

    empty = _write_tmp(tmp_path, b"", "empty.png")
    ok, reason = cb.copy_image(empty)
    assert ok is False and "空" in reason
    assert cap.calls == [], "读不到 / 空文件不应打扰平台实现"


def test_copy_image_unsupported_platform(tmp_path, monkeypatch):
    monkeypatch.setattr(cb, "PLATFORM_IMPL", {})
    data, _ = make_png(4, 4)
    ok, reason = cb.copy_image(_write_tmp(tmp_path, data))
    assert ok is False and "不支持" in reason


def test_copy_image_impl_exception_is_swallowed(tmp_path, monkeypatch):
    """平台实现炸了也只是「这次没复制成功」，绝不冒泡到截图流程。"""
    _install_impl(monkeypatch, _Capture(raise_it=True))
    data, _ = make_png(4, 4)
    ok, reason = cb.copy_image(_write_tmp(tmp_path, data))
    assert ok is False and "boom" in reason


def test_supported_reflects_platform(monkeypatch):
    monkeypatch.setattr(cb, "PLATFORM_IMPL", {"plan9": lambda *a: (True, "")})
    monkeypatch.setattr(sys, "platform", "plan9")
    assert cb.supported() == (True, "")
    monkeypatch.setattr(sys, "platform", "amiga")
    ok, reason = cb.supported()
    assert ok is False and "amiga" in reason


# ---------------------------------------------------------------------------
# 3. Windows ctypes 实现的资源语义
# ---------------------------------------------------------------------------
class _FakeFn:
    """ctypes 的 `dll.FuncName` 是个可赋值 argtypes/restype 的对象；用同款替身，
    这样 _bind_win 的原型声明（含 64 位句柄）能被真正走到。"""

    def __init__(self, dll, name):
        self._dll, self._name = dll, name

    def __call__(self, *args):
        return self._dll._dispatch(self._name, args)


class _FakeWinDll:
    """替身 user32 / kernel32：把调用记成日志，可编程返回失败。"""

    def __init__(self, open_ok=True, empty_ok=True, set_ok=True,
                 register_ok=True):
        self.log = []
        self.freed = []
        self.handles = []
        self.open_ok = open_ok
        self.empty_ok = empty_ok
        self.set_ok = set_ok
        self.register_ok = register_ok
        self._seq = [0]

    def __getattr__(self, name):
        if name.startswith("_"):                 # 走 __getattribute__ 的私有成员
            raise AttributeError(name)
        return _FakeFn(self, name)

    def _dispatch(self, name, args):
        self.log.append((name,) + tuple(args))
        if name == "GlobalAlloc":
            handle = 1000 + self._seq[0]
            self.handles.append((handle, args[1]))
            self._seq[0] += 1
            return handle
        if name == "GlobalFree":
            self.freed.append(args[0])
            return 0
        return {
            "OpenClipboard": lambda: 1 if self.open_ok else 0,
            "EmptyClipboard": lambda: 1 if self.empty_ok else 0,
            "CloseClipboard": lambda: 1,
            "RegisterClipboardFormatW": lambda: 0xC0DE if self.register_ok else 0,
            "SetClipboardData": lambda: args[1] if self.set_ok else 0,
            "GlobalLock": lambda: args[0] + 5000,   # 假地址（memmove 已打桩）
            "GlobalUnlock": lambda: 1,
        }[name]()


def _install_fake_win(monkeypatch, **kw):
    """把 ctypes.WinDLL / ctypes.memmove 换成假件。

    copy_windows 里是函数内 `import ctypes`，运行时才查属性，所以直接改 ctypes
    模块属性即可生效。**必须**把 memmove 也打桩：替身 GlobalLock 返回的是编造的
    「地址」，真 memmove 会往那个地址写（段错误）。
    """
    fake = _FakeWinDll(**kw)
    ctypes_mod = sys.modules["ctypes"]
    monkeypatch.setattr(ctypes_mod, "WinDLL", lambda name, **k: fake,
                        raising=False)
    monkeypatch.setattr(ctypes_mod, "memmove", lambda dst, src, n: None,
                        raising=False)
    return fake


def test_windows_sets_both_dib_and_png(tmp_path, monkeypatch):
    """Windows 要同时投放 CF_DIB（通用兼容）与 CF_PNG（体积小 / 带 alpha）。"""
    fake = _install_fake_win(monkeypatch)
    data, _ = make_png(6, 5)
    ok, reason = cb.copy_windows(data, data, cb.decode_png(data), str(tmp_path))

    assert ok is True, reason
    formats = [c[1] for c in fake.log if c[0] == "SetClipboardData"]
    assert cb.CF_DIB in formats, "必须投放 CF_DIB（最通用的位图格式）"
    assert 0xC0DE in formats, "必须投放 CF_PNG"
    # 成功交接后内存归系统所有，我们不能再 GlobalFree，否则粘贴方读到的是废数据
    assert fake.freed == [], "SetClipboardData 成功后不应再释放内存"
    assert ("CloseClipboard",) in fake.log, "剪贴板必须关闭"


def test_windows_dib_header_describes_bottom_up_32bpp(tmp_path, monkeypatch):
    """CF_DIB 的头必须是 40 字节 BITMAPINFOHEADER + 32bpp + 自下而上正高。"""
    import struct as _struct

    fake = _install_fake_win(monkeypatch)
    # 记录真正被搬进全局内存的内容
    moved = []

    def fake_memmove(dst, src, n):
        moved.append(bytes(src)[:n] if not isinstance(src, bytes) else src[:n])

    monkeypatch.setattr(sys.modules["ctypes"], "memmove", fake_memmove,
                        raising=False)
    data, _x = make_png(5, 3)
    cb.copy_windows(data, data, cb.decode_png(data), str(tmp_path))

    # 找到 BITMAPINFOHEADER 那一笔（首 4 字节 = biSize 40）
    dib = next(m for m in moved if len(m) > 40
               and _struct.unpack("<I", m[:4])[0] == 40)
    size, w, h, planes, bits, comp, img_sz = _struct.unpack("<IiiHHII", dib[:24])
    assert size == 40 and (w, h) == (5, 3)
    assert (planes, bits) == (1, 32)
    assert comp == 0 and img_sz == 5 * 4 * 3
    assert h > 0, "自下而上 DIB 用正高度标识"


def test_windows_png_only_counts_as_success(tmp_path, monkeypatch):
    """CF_DIB 投不进去（例如超大图没解码出来）但 PNG 成功时，也算复制成功。"""
    fake = _install_fake_win(monkeypatch)
    ok, reason = cb.copy_windows(b"\x89PNG\r\n\x1a\ndata",
                                 b"\x89PNG\r\n\x1a\ndata", None, str(tmp_path))
    assert ok is True, reason
    formats = [c[1] for c in fake.log if c[0] == "SetClipboardData"]
    assert formats == [0xC0DE], "只有 PNG 时不应尝试 CF_DIB"


def _no_powershell(cmd, **kw):
    """模拟「这台电脑没有 powershell」：让 .NET 兜底走 FileNotFoundError 分支。"""
    raise FileNotFoundError(cmd[0])


def test_windows_busy_clipboard_is_reported(tmp_path, monkeypatch):
    """剪贴板被别的程序锁住：短暂重试后给明确原因，而不是卡死或抛异常。"""
    monkeypatch.setattr(cb.time, "sleep", lambda s: None)
    monkeypatch.setattr(cb.subprocess, "run", _no_powershell)
    fake = _install_fake_win(monkeypatch, open_ok=False)
    data, _ = make_png(4, 4)
    ok, reason = cb.copy_windows(data, data, None, str(tmp_path))
    assert ok is False and "占用" in reason
    assert len([c for c in fake.log if c[0] == "OpenClipboard"]) == \
        cb._WIN_OPEN_TRIES * cb._WIN_ATTEMPTS, "每轮都要重试开剪贴板"
    assert [c for c in fake.log if c[0] == "CloseClipboard"] == [], \
        "没抢到剪贴板就不该去关它"


def test_windows_empty_clipboard_failure_closes_it(tmp_path, monkeypatch):
    """EmptyClipboard 失败（如 ACL / 会话限制）：必须关门后再报错。"""
    monkeypatch.setattr(cb.time, "sleep", lambda s: None)
    monkeypatch.setattr(cb.subprocess, "run", _no_powershell)
    fake = _install_fake_win(monkeypatch, empty_ok=False)
    ok, reason = cb.copy_windows(b"\x89PNG\r\n\x1a\nx", b"\x89PNG\r\n\x1a\nx",
                                 None, str(tmp_path))
    assert ok is False and "清空" in reason
    assert ("CloseClipboard",) in fake.log


def test_windows_all_formats_fail_frees_memory(tmp_path, monkeypatch):
    """SetClipboardData 全失败：自己申请的内存要释放，不能泄漏。"""
    monkeypatch.setattr(cb.time, "sleep", lambda s: None)
    monkeypatch.setattr(cb.subprocess, "run", _no_powershell)
    fake = _install_fake_win(monkeypatch, set_ok=False)
    data, _ = make_png(4, 4)
    ok, reason = cb.copy_windows(data, data, cb.decode_png(data), str(tmp_path))
    assert ok is False and "写入失败" in reason
    # 每轮投两种格式、两种都被拒收：两笔都要 GlobalFree，一轮都不能少
    assert len(fake.freed) == 2 * cb._WIN_ATTEMPTS, "每轮两笔失败数据都要释放"
    assert ("CloseClipboard",) in fake.log


def test_windows_retries_whole_sequence_when_set_fails(tmp_path, monkeypatch):
    """SetClipboardData 首轮全败、第二轮放行：必须整段重试并最终报成功。

    回归：用户电脑上报「SetClipboardData 未接受该数据」——部分机器上
    剪贴板被第三方短暂持有，Open/Empty 都过、唯独 Set 返回 NULL，
    旧实现一轮就放弃。现在整段重试，第二轮撞上窗口即成功。
    """
    monkeypatch.setattr(cb.time, "sleep", lambda s: None)
    monkeypatch.setattr(cb.subprocess, "run", _no_powershell)
    fake = _install_fake_win(monkeypatch, set_ok=False)
    data, _ = make_png(4, 4)
    real_dispatch = fake._dispatch
    calls = {"n": 0}

    def flaky_dispatch(name, args):
        if name == "SetClipboardData":
            calls["n"] += 1
            # 第一轮的 PNG + DIB 都被拒收（返回 0），第二轮起放行
            return 0 if calls["n"] <= 2 else args[1]
        return real_dispatch(name, args)

    monkeypatch.setattr(fake, "_dispatch", flaky_dispatch)
    ok, reason = cb.copy_windows(data, data, cb.decode_png(data), str(tmp_path))
    assert ok is True, reason
    opens = [c for c in fake.log if c[0] == "OpenClipboard"]
    assert len(opens) == 2, "第一轮失败后应整段重开一轮"
    assert len(fake.freed) == 2, "只有失败的第一轮需要释放内存"


def test_windows_powershell_fallback_after_ctypes_fails(tmp_path, monkeypatch):
    """ctypes 三轮全败后用 powershell -STA + .NET SetImage 兜底成功。

    图片字节走 stdin（base64）：子进程不打开截图文件——用户机器上的真实
    故障就是 FromFile 被 AV 独占锁后抛 GDI+「内存不足」，整个兜底在走到
    剪贴板之前就失败了。这里锁定「字节来自内存、不来自文件」的新契约。
    """
    monkeypatch.setattr(cb.time, "sleep", lambda s: None)
    _install_fake_win(monkeypatch, set_ok=False)
    data, _ = make_png(4, 4)
    captured = {}

    class R:
        returncode = 0
        stdout = b""
        stderr = b""

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["kw"] = kw
        return R()

    monkeypatch.setattr(cb.subprocess, "run", fake_run)
    shot = str(tmp_path / "shot.png")
    ok, reason = cb.copy_windows(data, data, cb.decode_png(data), shot)
    assert ok is True, reason
    assert captured["cmd"][0] == "powershell"
    assert "-STA" in captured["cmd"], ".NET 剪贴板 API 要求单线程套户"
    assert "-Command" in captured["cmd"]
    script = captured["cmd"][-1]
    # 主路径：stdin 字节 -> FromStream（不碰文件）
    assert "FromStream" in script and "FromBase64String" in script
    assert "[Console]::In.ReadToEnd()" in script
    assert "SetImage" in script and "System.Windows.Forms.Clipboard" in script
    # 错误输出强制 UTF8（中文 Windows 默认 GBK，按 UTF-8 解会出乱码）
    assert "OutputEncoding" in script and "UTF8" in script
    # stdin 里送的就是整张图的字节（base64），不是文件路径
    assert captured["kw"].get("input") == \
        base64.b64encode(data), "图片字节应经 stdin 送进子进程"
    # 文件路径仍嵌在脚本里：raw 为空时的 FromFile 遗留分支用
    assert shot.replace("'", "''") in script


def test_windows_powershell_stdin_bytes_not_path(tmp_path, monkeypatch):
    """stdin 传图契约：input = base64(原始字节)，且子进程命令里不含图片路径读取。"""
    monkeypatch.setattr(cb.time, "sleep", lambda s: None)
    captured = {}

    class R:
        returncode = 0
        stdout = b""
        stderr = b""

    def fake_run(cmd, **kw):
        captured.update(cmd=cmd, kw=kw)
        return R()

    monkeypatch.setattr(cb.subprocess, "run", fake_run)
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"fake-png-bytes" * 8
    ok, reason = cb._win_write_powershell("/d/shot.png", png_bytes)
    assert ok is True, reason
    assert captured["kw"]["input"] == base64.b64encode(png_bytes)
    script = captured["cmd"][-1]
    assert "FromStream" in script
    # FromFile 只应出现在 raw 为空的遗留分支里（有字节时不该去读文件）
    assert script.count("FromFile") == 1, "FromFile 仅留作遗留分支"


def test_windows_powershell_legacy_fromfile_without_raw(tmp_path, monkeypatch):
    """raw 为空（非常规入口直接调 copy_windows）：回落 FromFile(path)。"""
    monkeypatch.setattr(cb.time, "sleep", lambda s: None)
    captured = {}

    class R:
        returncode = 0
        stdout = b""
        stderr = b""

    def fake_run(cmd, **kw):
        captured.update(cmd=cmd, kw=kw)
        return R()

    monkeypatch.setattr(cb.subprocess, "run", fake_run)
    shot = str(tmp_path / "shot.png")
    ok, reason = cb._win_write_powershell(shot)
    assert ok is True, reason
    assert captured["kw"]["input"] == b"", "无字节时 stdin 送空串（立即 EOF）"
    assert shot.replace("'", "''") in captured["cmd"][-1]
    assert "FromFile" in captured["cmd"][-1]


def test_windows_powershell_retries_then_succeeds(monkeypatch):
    """剪贴板被第三方短暂持有：兜底第一轮失败、第二轮成功（整段重试）。"""
    monkeypatch.setattr(cb.time, "sleep", lambda s: None)
    n = {"i": 0}

    class FailThenOk:
        returncode = 1
        stdout = b""
        stderr = "".encode()

    class Ok:
        returncode = 0
        stdout = b""
        stderr = b""

    def flaky_run(cmd, **kw):
        n["i"] += 1
        return FailThenOk() if n["i"] == 1 else Ok()

    monkeypatch.setattr(cb.subprocess, "run", flaky_run)
    ok, reason = cb._win_write_powershell("/d/shot.png", b"\x89PNG\r\n\x1a\nx")
    assert ok is True, reason
    assert n["i"] == 2, "第一轮失败后应整段重试一轮"


def test_windows_powershell_error_is_readable_gbk(monkeypatch):
    """GBK stderr 必须解成可读中文，不再是「ʱ쳣ڴ治㡣」式乱码。"""
    monkeypatch.setattr(cb.time, "sleep", lambda s: None)

    class R:
        returncode = 1
        stdout = b""
        # 中文 Windows 上 PowerShell 的默认输出编码：GBK
        stderr = "clipboard fallback failed: 异常: 内存不足".encode("gbk")

    monkeypatch.setattr(cb.subprocess, "run", lambda cmd, **kw: R())
    ok, reason = cb._win_write_powershell("/d/shot.png", b"\x89PNG\r\n\x1a\nx")
    assert ok is False
    assert "内存不足" in reason, "GBK 输出应解成可读中文，实际 %r" % reason


def test_ps_text_decodes_gbk_without_mojibake():
    """_ps_text：GBK 字节 -> 可读中文；UTF-8 优先；坏字节不抛异常。"""
    gbk = "异常: 内存不足".encode("gbk")
    assert cb._ps_text(gbk) == "异常: 内存不足"
    utf8 = "异常: 内存不足".encode("utf-8")
    assert cb._ps_text(utf8) == "异常: 内存不足"
    assert cb._ps_text(b"") == ""
    assert isinstance(cb._ps_text(b"\xff\xfe\x80"), str)   # 坏字节也不抛


def test_windows_final_failure_mentions_common_causes(tmp_path, monkeypatch):
    """全部手段失败时，原因要写成人话（远程桌面 / 安全软件 / 剪贴板工具），
    且两阶段明细都要带上（直接写入 + PowerShell 兜底），便于报障定位。"""
    monkeypatch.setattr(cb.time, "sleep", lambda s: None)
    monkeypatch.setattr(cb.subprocess, "run", _no_powershell)
    _install_fake_win(monkeypatch, set_ok=False)
    data, _ = make_png(4, 4)
    ok, reason = cb.copy_windows(data, data, cb.decode_png(data),
                                 str(tmp_path / "s.png"))
    assert ok is False
    assert "写入失败" in reason and "SetClipboardData" in reason
    assert "直接写入" in reason, "两阶段明细：%r" % reason
    assert "远程桌面" in reason and "安全软件" in reason


# ---------------------------------------------------------------------------
# 4. macOS / Linux 实现（命令行为 + 缺命令的提示）
# ---------------------------------------------------------------------------
def test_macos_uses_osascript_png_class(monkeypatch):
    captured = {}

    class R:
        returncode = 0
        stdout = b""
        stderr = b""

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["kw"] = kw
        return R()

    monkeypatch.setattr(cb.subprocess, "run", fake_run)
    ok, reason = cb.copy_macos(b"", b"", None, "/tmp/shot.png")
    assert ok is True and reason == ""
    assert captured["cmd"][0] == "osascript"
    script = captured["cmd"][2]
    assert "PNGf" in script and "/tmp/shot.png" in script


def test_macos_osascript_failure_is_explained(monkeypatch):
    class R:
        returncode = 1
        stdout = b""
        stderr = b"execution error: boom"

    monkeypatch.setattr(cb.subprocess, "run", lambda cmd, **kw: R())
    ok, reason = cb.copy_macos(b"", b"", None, "/tmp/shot.png")
    assert ok is False and "boom" in reason


def test_linux_reports_missing_tools(tmp_path, monkeypatch):
    """两个命令都不存在时要给出「装什么」的明确提示，而不是裸 False。"""
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(shutil, "which", lambda tool: None)
    ok, reason = cb.copy_linux(b"", b"", None, str(tmp_path / "x.png"))
    assert ok is False and "xclip" in reason and "wl-copy" in reason


def test_linux_prefers_xclip_without_wayland(tmp_path, monkeypatch):
    """非 Wayland 会话优先用 xclip（带 image/png 类型）。"""
    path = _write_tmp(tmp_path, PNG_MAGIC + b"\x00" * 8, "shot.png")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(shutil, "which", lambda tool: "/usr/bin/" + tool)
    calls = []

    class R:
        returncode = 0
        stdout = stderr = b""

    def fake_run(cmd, **kw):
        calls.append((cmd, kw))
        return R()

    monkeypatch.setattr(cb.subprocess, "run", fake_run)
    ok, reason = cb.copy_linux(b"", b"", None, path)
    assert ok is True, reason
    assert calls[0][0][0] == "xclip" and "image/png" in calls[0][0]


# ---------------------------------------------------------------------------
# 前导垃圾容错（车机 screencap 实测：PNG 前多吐了几行文本）
# ---------------------------------------------------------------------------
def test_copy_image_strips_leading_junk_so_png_path_is_used(tmp_path, monkeypatch):
    """PNG 前面多出几行垃圾时，仍要按 PNG 走（并透传干净的 PNG 字节）。

    回归：真实车机上截图落盘的文件「开头不是 PNG 签名」，于是 `png` 被判成空，
    ctypes 那条只投 CF_PNG/CF_DIB 的分支被整段跳过，退到 PowerShell + GDI+
    `Image.FromStream`，报的是一句与真相无关的「参数无效。」——用户看到的是
    「剪贴板被占用，请重试」，重试多少次都一样。
    """
    cap = _Capture()
    _install_impl(monkeypatch, cap)
    good, _truth = make_png(4, 3)
    junk = b"\r\nshell@android:/ $ screencap\r\n"
    path = _write_tmp(tmp_path, junk + good, "junk.png")

    ok, reason = cb.copy_image(path)

    assert ok is True, reason
    call = cap.calls[0]
    assert call["png"].startswith(PNG_MAGIC), "必须识别成 PNG，否则 ctypes 路径被跳过"
    assert call["png"] == good, "交给平台的应是剥离前导垃圾后的干净 PNG"
    assert call["raw"] == good, "PowerShell 兜底拿到的也必须是干净字节"
    assert call["pix"] is not None, "像素解码同样要成功（CF_DIB 依赖它）"


def test_copy_image_reports_unrecognized_bytes(tmp_path, monkeypatch):
    """认不出格式时给一条能读懂的原因，而不是编一个「剪贴板被占用」。"""
    cap = _Capture()
    _install_impl(monkeypatch, cap)
    path = _write_tmp(tmp_path, b"\x01\x02\x03\x04not-an-image", "bad.png")

    ok, reason = cb.copy_image(path)

    assert ok is False
    assert "无法识别" in reason
    assert "01 02 03 04" in reason, "带上头部字节，报障时才能判断到底是什么"
    assert cap.calls == [], "格式都不认，就不该再往平台实现里送"


def test_copy_image_keeps_non_png_untouched(tmp_path, monkeypatch):
    """JPEG 不做像素解码，但仍要原样交给平台实现（走系统图片 API）。"""
    cap = _Capture()
    _install_impl(monkeypatch, cap)
    jpg = b"\xff\xd8\xff\xe0" + b"\x00" * 32 + b"\xff\xd9"
    path = _write_tmp(tmp_path, jpg, "shot.jpg")

    ok, _reason = cb.copy_image(path)

    assert ok is True
    call = cap.calls[0]
    assert call["png"] == b"", "非 PNG 不投 CF_PNG"
    assert call["pix"] is None
    assert call["raw"] == jpg
