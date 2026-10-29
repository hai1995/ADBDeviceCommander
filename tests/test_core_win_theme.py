"""core.win_theme 的单测（Linux 上可跑：模块对非 Windows 全程 no-op）。

标题栏配色这条链路的特点是「在 Linux CI 上完全摸不到真窗口」，所以设计上把
「算什么值」与「怎么调系统」拆开了：colorref / title_attributes 是纯函数，
apply_to_hwnd 接受可注入的 setter。这里锁的就是这层纯逻辑：

  * COLORREF 是 **BGR** 顺序，写错就是红蓝互换（深蓝黑变暗红）；
  * 深色模式属性有两个编号（19 / 20），新编号被拒时必须补旧编号；
  * 老 Windows 上没有 34/35/36，写不进去只降级、不报错；
  * 非 Windows / 拿不到句柄时安静返回，绝不影响启动。
"""
import sys

import pytest

import core.win_theme as wt


# --------------------------------------------------------------------------- #
# 颜色换算
# --------------------------------------------------------------------------- #
def test_colorref_is_bgr_not_rgb():
    """COLORREF = 0x00BBGGRR：#0b0f14 → 0x00140f0b（红蓝反过来）。"""
    assert wt.colorref("#0b0f14") == 0x00140F0B
    assert wt.colorref("#e9f0f8") == 0x00F8F0E9


def test_colorref_accepts_shorthand_and_bare_hex():
    assert wt.colorref("#abc") == wt.colorref("#aabbcc")
    assert wt.colorref("112233") == 0x00332211


@pytest.mark.parametrize("bad", ["", "#12", "#12345", "zzzzzz", None, 123, "#1234567"])
def test_colorref_rejects_garbage(bad):
    """非法颜色返回 None —— 由调用方跳过该属性，而不是抛异常打断启动。"""
    assert wt.colorref(bad) is None


# --------------------------------------------------------------------------- #
# 属性表
# --------------------------------------------------------------------------- #
def test_title_attributes_puts_dark_mode_first():
    attrs = wt.title_attributes()
    assert attrs[0] == (wt.DWMWA_USE_IMMERSIVE_DARK_MODE, 1)
    codes = [a for a, _ in attrs]
    assert wt.DWMWA_CAPTION_COLOR in codes
    assert wt.DWMWA_TEXT_COLOR in codes
    assert wt.DWMWA_BORDER_COLOR in codes


def test_title_attributes_skips_bad_colors():
    """颜色写错时只少一条属性：深色模式仍要生效（否则标题栏直接是浅色）。"""
    attrs = wt.title_attributes(bg="oops", text="#ffffff", border="#000000")
    codes = [a for a, _ in attrs]
    assert wt.DWMWA_USE_IMMERSIVE_DARK_MODE in codes
    assert wt.DWMWA_CAPTION_COLOR not in codes
    assert wt.DWMWA_TEXT_COLOR in codes


# --------------------------------------------------------------------------- #
# 写入（注入 setter）
# --------------------------------------------------------------------------- #
class _Recorder:
    def __init__(self, reject=()):
        self.calls = []
        self.reject = set(reject)

    def __call__(self, hwnd, attr, value):
        if attr in self.reject:
            raise OSError("unsupported")
        self.calls.append((hwnd, attr, value))


def test_apply_to_hwnd_writes_all_attributes():
    rec = _Recorder()
    res = wt.apply_to_hwnd(0x1234, setter=rec)
    assert res["ok"] is True and res["reason"] == ""
    assert [a for _h, a, _v in rec.calls] == [20, 35, 36, 34]
    assert all(h == 0x1234 for h, _a, _v in rec.calls)


def test_apply_to_hwnd_falls_back_to_old_dark_mode_id():
    """Win10 1809~1903 只认 19：新编号被拒后必须补一次旧编号。"""
    rec = _Recorder(reject={20})
    res = wt.apply_to_hwnd(1, setter=rec)
    assert wt.DWMWA_USE_IMMERSIVE_DARK_MODE_OLD in res["applied"]
    assert res["ok"] is True
    assert 19 in [a for _h, a, _v in rec.calls]


def test_apply_to_hwnd_tolerates_win10_without_color_attributes():
    """老 Windows 没有 34/35/36：降级成「只有深色模式」，仍算成功。"""
    rec = _Recorder(reject={34, 35, 36})
    res = wt.apply_to_hwnd(1, setter=rec)
    assert res["ok"] is True
    assert res["applied"] == [20]
    assert sorted(res["failed"]) == [34, 35, 36]


def test_apply_to_hwnd_all_rejected_is_not_ok():
    res = wt.apply_to_hwnd(1, setter=_Recorder(reject={20, 19, 34, 35, 36}))
    assert res["ok"] is False and res["reason"] == "dwm_rejected"


def test_apply_to_hwnd_without_hwnd():
    res = wt.apply_to_hwnd(0, setter=_Recorder())
    assert res["ok"] is False and res["reason"] == "no_window"


@pytest.mark.skipif(sys.platform.startswith("win"), reason="仅在非 Windows 上验证降级")
def test_apply_to_hwnd_without_setter_is_unsupported_on_non_windows():
    """不注入 setter 时走真实的 _dwm_setter()：非 Windows 必须返回 unsupported。"""
    res = wt.apply_to_hwnd(1)
    assert res["ok"] is False and res["reason"] == "unsupported"


# --------------------------------------------------------------------------- #
# 句柄查找与 attach
# --------------------------------------------------------------------------- #
class _FakeNative:
    def __init__(self, value):
        self.Handle = value


class _IntPtrLike:
    """模拟 pythonnet 的 IntPtr：只能 ToInt64()，不能 int()。"""

    def __init__(self, v):
        self._v = v

    def ToInt64(self):
        return self._v


def test_hwnd_of_accepts_plain_int_and_intptr():
    assert wt._hwnd_of(_FakeNative(42)) == 42
    assert wt._hwnd_of(_FakeNative(_IntPtrLike(7))) == 7


def test_hwnd_of_returns_zero_for_missing_native():
    assert wt._hwnd_of(None) == 0

    class _Boom:
        @property
        def Handle(self):
            raise RuntimeError("no window yet")

    assert wt._hwnd_of(_Boom()) == 0


@pytest.mark.skipif(sys.platform.startswith("win"), reason="非 Windows 才有 no-op 语义")
def test_find_window_and_attach_are_noop_off_windows():
    assert wt.find_window(1234) == 0
    res = wt.attach(None, timeout=0.2)
    assert res["ok"] is False and res["reason"] == "unsupported"


def test_attach_retries_until_hwnd_appears(monkeypatch):
    """窗口对象比 start(func=...) 的线程晚出现：attach 必须轮询而不是一锤子放弃。"""
    seq = {"n": 0}

    def fake_hwnd(_native):
        seq["n"] += 1
        return 0 if seq["n"] < 3 else 555

    rec = _Recorder()
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(wt, "_hwnd_of", fake_hwnd)
    monkeypatch.setattr(wt, "_dwm_setter", lambda: rec)
    res = wt.attach(object(), timeout=2.0, interval=0.01)
    assert res["ok"] is True
    assert seq["n"] == 3
    assert all(h == 555 for h, _a, _v in rec.calls)


def test_attach_gives_up_quietly_after_timeout(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(wt, "_hwnd_of", lambda _n: 0)
    monkeypatch.setattr(wt, "find_window", lambda *a, **k: 0)
    res = wt.attach(None, timeout=0.05, interval=0.01)
    assert res["ok"] is False and res["reason"] == "no_window"
