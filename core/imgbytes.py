# -*- coding: utf-8 -*-
"""
core.imgbytes —— 图片字节的「认得出、裁得干净」（零依赖、纯函数）
================================================================
用途只有一个：把**来路不明的字节**变成一段真能被图片库接受的图片数据。

为什么需要它
------------
`screencap -p` 绝大多数设备输出的是干净 PNG，但实测里有一类车机/定制 ROM
会在 PNG 前面先吐几行自己的东西（换行、调试 print、甚至半行 shell 提示），
于是文件变成「前导垃圾 + 完整 PNG」：

* 落盘后看图软件打不开（用户以为是程序坏了）；
* 复制到剪贴板时，`raw.startswith(PNG magic)` 为假 —— ctypes 那条只投
  CF_PNG/CF_DIB 的路径被整段跳过，退到 PowerShell + GDI+ `Image.FromStream`，
  GDI+ 看到开头不是图片签名，报的是一句与真相无关的
  「参数无效。」（用户看到的是「剪贴板被占用」之类的错误提示）。

同一段字节在「判断格式」和「交给别人解码」两处都要用，所以单独立一个
模块：**只做字节层的事，不碰剪贴板、不碰文件、不抛异常**。

对外 API
--------
* `detect(data)`      —— 只看开头，返回 "png" / "jpg" / "gif" / "bmp" / "webp" / None
* `locate(data)`      —— 容忍前导垃圾，返回 (kind, offset)；找不到返回 (None, -1)
* `normalize(data)`   —— 返回 (clean_bytes, kind, note)；认不出时 clean_bytes 为空

`note` 是给状态栏/日志看的短句（含头部十六进制），不面向终端用户堆术语。
"""

from __future__ import annotations

import struct

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# 签名表：顺序即优先级。PNG 必须在前 —— 个别 JPEG 的 EXIF 里会嵌 PNG 缩略图，
# 先认 PNG 会把整张 JPEG 当成「前导垃圾 + PNG」，切出一张缩略图。
_SIGNATURES = (
    ("png", PNG_MAGIC),
    ("jpg", b"\xff\xd8\xff"),
    ("gif", b"GIF87a"),
    ("gif", b"GIF89a"),
    ("bmp", b"BM"),
)

# 只在头部这么多字节里找签名：正常的前导垃圾不会超过几行文本，
# 放太宽反而容易在二进制内容深处误命中。
_HEAD_SCAN = 4096


def detect(data):
    """只看开头判断格式；不做任何搜索。返回 kind 或 None。"""
    if not data:
        return None
    for kind, sig in _SIGNATURES:
        if data.startswith(sig):
            return kind
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _webp_at(data, offset):
    return data[offset:offset + 4] == b"RIFF" and data[offset + 8:offset + 12] == b"WEBP"


# BMP 常见的 DIB 头长度（BITMAPINFOHEADER=40 / V4=108 / V5=124 / OS2=12…）
_BMP_DIB_SIZES = (12, 16, 40, 52, 56, 64, 108, 124)


def _plausible_bmp(data, off):
    """`BM` 只有两个字节，是整张签名表里最弱的一个。

    前导垃圾是设备吐出来的文本，里面出现 `BM` 并不罕见（`MB`、`BMW`、
    甚至一段 base64）。若只看这两个字节，`locate` 会把这段文本当成 BMP 起点，
    切出一段「假图片」——调用方于是从「认不出格式」变成「格式认得出但解不开」，
    又回到那种查不出原因的失败上。所以额外按 BMP 文件头做一次合理性校验：

      * 4 字节保留字段必须为 0（真实文件恒为 0，文本里几乎不可能连出四个 0）；
      * DIB 头长度必须是已知取值之一；
      * 像素数据偏移、文件大小都要落在实际字节范围内。
    """
    if off + 18 > len(data):
        return False
    if data[off + 6:off + 10] != b"\x00\x00\x00\x00":
        return False
    size = struct.unpack("<I", data[off + 2:off + 6])[0]
    offbits = struct.unpack("<I", data[off + 10:off + 14])[0]
    dib = struct.unpack("<I", data[off + 14:off + 18])[0]
    if dib not in _BMP_DIB_SIZES:
        return False
    avail = len(data) - off
    if not 14 <= offbits <= avail:
        return False
    # 部分写入器把文件大小字段留 0，此时只校验数据偏移
    if size and not offbits <= size <= avail:
        return False
    return True


def locate(data):
    """在前 _HEAD_SCAN 字节里找第一个图片签名，返回 (kind, offset)。

    找不到返回 (None, -1)。offset 为 0 表示文件本身干净。

    BMP 候选要额外过 `_plausible_bmp` 的合理性校验：签名太短，纯文本里也能
    命中，误判会让调用方拿到一段根本没被解码过的垃圾。
    """
    if not data:
        return None, -1
    best = (None, -1)
    for kind, sig in _SIGNATURES:
        i = data.find(sig, 0, _HEAD_SCAN)
        while i >= 0:
            if kind != "bmp" or _plausible_bmp(data, i):
                break
            i = data.find(sig, i + 1, _HEAD_SCAN)
        if i >= 0 and (best[1] < 0 or i < best[1]):
            best = (kind, i)
    i = data.find(b"RIFF", 0, _HEAD_SCAN)
    while i >= 0:
        if _webp_at(data, i) and (best[1] < 0 or i < best[1]):
            best = ("webp", i)
            break
        i = data.find(b"RIFF", i + 1, _HEAD_SCAN)
    return best


def _trim_png(data):
    """把 PNG 裁到 IEND 结尾。

    尾部垃圾（多打的换行、下一段输出的残渣）不会让 GDI+ 立刻失败，但会让
    某些严格的解码器报警；顺手裁掉更干净。找不到 IEND 说明图被截断，原样
    返回（截断图仍可能被容错解码器画出上半截，比直接丢弃有用）。
    """
    i = data.rfind(b"IEND")
    if i >= 0 and i + 8 <= len(data):
        return data[:i + 8]
    return data


def _trim_jpg(data):
    """裁到 EOI（FFD9）；没有则原样返回。"""
    i = data.rfind(b"\xff\xd9")
    if i >= 0:
        return data[:i + 2]
    return data


def _head_hex(data, n=8):
    return " ".join("%02x" % b for b in data[:n])


def normalize(data):
    """返回 (clean_bytes, kind, note)。

    * 干净图片：原样返回（PNG/JPG 可能被裁掉尾部垃圾）；
    * 前导有垃圾：从签名处切出有效段，kind 为真实格式；
    * 认不出：返回 (b"", None, 说明)，调用方据此给一条能读懂的原因。
    """
    if not data:
        return b"", None, "字节为空"

    kind, off = locate(data)
    if kind is None:
        return b"", None, ("未识别的图片格式（共 %d 字节，头部 %s）"
                           % (len(data), _head_hex(data)))

    payload = data[off:]
    if kind == "png":
        payload = _trim_png(payload)
    elif kind == "jpg":
        payload = _trim_jpg(payload)

    if off > 0:
        return payload, kind, ("已跳过 %d 字节前导内容后识别为 %s" % (off, kind))
    return payload, kind, ""
