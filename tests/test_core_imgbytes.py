# -*- coding: utf-8 -*-
"""core.imgbytes —— 图片字节识别 / 归一化单测。

这个模块存在的唯一理由：某些车机 / 定制 ROM 的 `screencap -p` 会在 PNG 前
先吐几行自己的东西，字节流于是「开头不是图片签名」。后果有两层——落盘的文件
打不开，复制到剪贴板时还会被误判成「不是 PNG」而跳过 ctypes 路径、退到 GDI+
报一句与真相无关的「参数无效」。这里把两层的判定都钉住。
"""
import struct
import zlib

import core.imgbytes as ib

PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _png_bytes(w=1, h=1, rgba=(255, 0, 0, 255)):
    """造一张最小合法 PNG（8bit / RGBA / 非隔行），带完整 IEND。"""
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    row = b"\x00" + bytes(rgba) * w          # filter 0 + 像素
    return (PNG_SIG + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(row * h)) + chunk(b"IEND", b""))


# ---------------------------------------------------------------------------
# detect / locate
# ---------------------------------------------------------------------------
def test_detect_recognizes_common_formats():
    assert ib.detect(_png_bytes()) == "png"
    assert ib.detect(b"\xff\xd8\xff\xe0" + b"\x00" * 32) == "jpg"
    assert ib.detect(b"GIF89a" + b"\x00" * 16) == "gif"
    assert ib.detect(b"GIF87a" + b"\x00" * 16) == "gif"
    assert ib.detect(b"BM" + b"\x00" * 32) == "bmp"
    assert ib.detect(b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 8) == "webp"


def test_detect_returns_none_for_junk():
    assert ib.detect(b"") is None
    assert ib.detect(b"not an image at all") is None
    # 签名不在开头就不算「干净」——detect 只看开头，定位交给 locate
    assert ib.detect(b"\r\n" + _png_bytes()) is None


def test_locate_finds_signature_after_leading_junk():
    junk = b"\r\nadb: warning: something\r\n"
    data = junk + _png_bytes()
    kind, off = ib.locate(data)
    assert kind == "png"
    assert off == len(junk)
    assert ib.locate(_png_bytes()) == ("png", 0)


def test_locate_returns_minus_one_when_nothing_found():
    assert ib.locate(b"") == (None, -1)
    assert ib.locate(b"plain text, no image here") == (None, -1)


def test_locate_ignores_signature_far_into_the_file():
    """头部 4KB 之外的签名不认：那是二进制内容里巧合出现的字节，
    认了反而会把正常文件切坏。"""
    data = b"\x00" * 5000 + _png_bytes()
    assert ib.locate(data) == (None, -1)


# ---------------------------------------------------------------------------
# normalize
# ---------------------------------------------------------------------------
def test_normalize_keeps_clean_png_as_is():
    png = _png_bytes()
    out, kind, note = ib.normalize(png)
    assert kind == "png"
    assert out == png
    assert note == ""


def test_normalize_strips_leading_junk():
    junk = b"\r\nshell@android:/ $\r\n"
    png = _png_bytes()
    out, kind, note = ib.normalize(junk + png)
    assert kind == "png"
    assert out.startswith(PNG_SIG), "必须从签名处开始，否则 GDI+ 仍报参数无效"
    assert out == png
    assert "跳过" in note and str(len(junk)) in note


def test_normalize_trims_trailing_junk_after_iend():
    png = _png_bytes()
    out, kind, _ = ib.normalize(png + b"\r\n\r\ngarbage after png")
    assert kind == "png"
    assert out == png, "IEND 之后的残渣应当裁掉"


def test_normalize_keeps_truncated_png_because_half_an_image_beats_none():
    png = _png_bytes()
    truncated = png[:-10]                 # 砍掉 IEND 尾部
    out, kind, _ = ib.normalize(truncated)
    assert kind == "png"
    assert out == truncated, "找不到 IEND 说明被截断，原样返回交给上层决定"


def test_normalize_recognizes_jpeg_and_trims_eoi():
    jpg = b"\xff\xd8\xff\xe0" + b"\x00" * 40 + b"\xff\xd9"
    out, kind, _ = ib.normalize(jpg + b"tail")
    assert kind == "jpg"
    assert out == jpg


def test_normalize_reports_head_bytes_for_unknown_data():
    out, kind, note = ib.normalize(b"\x01\x02\x03\x04\x05\x06\x07\x08\x09")
    assert out == b"" and kind is None
    assert "未识别" in note
    assert "01 02 03 04" in note, "头部十六进制要写进说明，报障时才有据可查"


def test_normalize_handles_empty_bytes():
    out, kind, note = ib.normalize(b"")
    assert out == b"" and kind is None
    assert "空" in note


def test_normalize_accepts_webp():
    webp = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBPVP8 " + b"\x00" * 16
    out, kind, _ = ib.normalize(webp)
    assert kind == "webp"
    assert out == webp


# ---------------------------------------------------------------------------
# BMP 的弱签名（两字节）不能把文本当中招
# ---------------------------------------------------------------------------
def _bmp_bytes(w=1, h=1, bpp=24):
    """造一张最小合法 BMP（BITMAPINFOHEADER = 40 字节）。"""
    row = (w * bpp // 8 + 3) // 4 * 4          # 4 字节对齐
    pixels = b"\x00" * (row * h)
    dib = struct.pack("<IiiHHIIiiII", 40, w, h, 1, bpp, 0,
                      len(pixels), 2835, 2835, 0, 0)
    offbits = 14 + len(dib)
    size = offbits + len(pixels)
    head = b"BM" + struct.pack("<IHHI", size, 0, 0, offbits)
    return head + dib + pixels


def test_locate_accepts_real_bmp():
    data = b"\r\n" + _bmp_bytes(2, 2)
    kind, off = ib.locate(data)
    assert (kind, off) == ("bmp", 2), "真实 BMP 仍要认得出来"


def test_locate_ignores_bm_inside_leading_text():
    """前导文本里出现 `BM` 时不能切出一段假图片。

    回归：`locate` 原来只比「谁先出现」，而 BMP 的签名只有两个字节。设备吐的
    调试文本里 `MBM` / `BMW` / 一段 base64 都能命中，于是格式判成 bmp、起始位置
    落在文本中间 —— 调用方拿到一段既不是文本也不是图片的字节，报「写入剪贴板
    失败」却查不到原因（字节本身就没被当成图片解码过）。
    """
    junk = b"\r\nshell@android:/ $ dumpsys window | grep BMW\r\n"
    data = junk + _png_bytes()
    kind, off = ib.locate(data)
    assert (kind, off) == ("png", len(junk)), \
        "文本里的 BM 应被跳过，最终定位到真正的 PNG"


def test_locate_skips_bmp_signature_with_bogus_header():
    """`BM` 后面跟的不是合理 BMP 头时，不认这个候选。"""
    junk = b"BM" + b"\x01\x02\x03\x04" + b"text" + b"\x00" * 8
    kind, off = ib.locate(junk + _png_bytes())
    assert kind == "png", (kind, off)


def test_normalize_still_handles_bmp_after_junk():
    data = b"\n" + _bmp_bytes(4, 4)
    clean, kind, note = ib.normalize(data)
    assert kind == "bmp"
    assert clean.startswith(b"BM")
    assert "bmp" in note
