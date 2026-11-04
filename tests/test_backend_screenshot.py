# -*- coding: utf-8 -*-
"""screenshot_data：截图完成后给前端预览图用的 PNG 读取接口。

路径来自后端自己生成的落盘路径（可信），但仍做存在性 + PNG 魔数校验，
避免把非图片 / 不存在的文件当成预览图返回。
"""
import base64

from backend.controllers.screenshot import ScreenshotMixin

# 经典 1x1 黑底 PNG（IHDR 1x1 / 8-bit / RGB）。本接口只校验前 8 字节魔数，
# CRC 不在此范围内，因此照搬这段已知字节即可。
_PNG_1x1 = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90\x77\x53\xde"
    b"\x00\x00\x00\x0cIDAT\x08\xd7\x63\xf8\xcf\xc0\xf0\x1f\x00\x05\x05\x02\x00\x9e\x2d\x68\x6a"
    b"\x00\x00\x00\x00IEND\xae\x42\x60\x82"
)


class _Shot(ScreenshotMixin):
    pass


def test_screenshot_data_ok(tmp_path):
    p = tmp_path / "screenshot_X_1.png"
    p.write_bytes(_PNG_1x1)
    res = _Shot().screenshot_data(str(p))
    assert res["ok"] is True
    assert base64.b64decode(res["data"]) == _PNG_1x1
    assert res["name"] == "screenshot_X_1.png"


def test_screenshot_data_missing(tmp_path):
    res = _Shot().screenshot_data(str(tmp_path / "nope.png"))
    assert res["ok"] is False
    assert res["reason"] == "missing"


def test_screenshot_data_rejects_non_png(tmp_path):
    p = tmp_path / "x.txt"
    p.write_bytes(b"this is not a png")
    res = _Shot().screenshot_data(str(p))
    assert res["ok"] is False
    assert res["reason"] == "not_png"
