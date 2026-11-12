# -*- coding: utf-8 -*-
"""backend.controllers.settings.SettingsMixin.set_theme —— 主题切换联动原生标题栏。

set_theme 只做三件事：校验模式 ∈ {dark,light,system} → 调 win_theme.apply_for_mode
（按 pid 回退找窗口句柄、system 读注册表解析）→ 把「非 Windows 不支持」当作预期，
不当作失败。本测试用假件替换 win_theme.apply_for_mode，只验证这层编排与容错。
"""
import core.win_theme as win_theme
from backend.controllers.settings import SettingsMixin


def _mixin():
    """造一个可独立测试的 SettingsMixin。

    set_theme 失败时会播报状态（原生标题栏配色失败不该一声不吭），而播报通道
    在真实的 WebApi 上才有 —— 纯 mixin 单测里补一个记录用的替身。
    """
    m = SettingsMixin()
    m.notes = []
    m._push_status = lambda kind, text, **kw: m.notes.append((kind, text))
    return m


def test_set_theme_valid_modes_call_apply_for_mode(monkeypatch):
    cap = {}

    def fake(mode, pid=None, native=None, title_hint=None, setter=None):
        cap["mode"] = mode
        return {"ok": True, "reason": ""}

    monkeypatch.setattr(win_theme, "apply_for_mode", fake)
    m = _mixin()
    for mode in ("dark", "light", "system"):
        r = m.set_theme(mode)
        assert r["ok"] is True
        assert r["mode"] == mode
        assert r["title_bar"]["ok"] is True
        assert cap["mode"] == mode


def test_set_theme_invalid_mode_rejected():
    m = _mixin()
    r = m.set_theme("neon")
    assert r["ok"] is False
    assert r["reason"] == "invalid_mode"
    assert r["mode"] == "neon"


def test_set_theme_unsupported_is_treated_as_ok(monkeypatch):
    """非 Windows 上 apply_for_mode 返回 unsupported：那是预期内，不算失败。"""
    def fake(mode, **kw):
        return {"ok": False, "reason": "unsupported"}

    monkeypatch.setattr(win_theme, "apply_for_mode", fake)
    m = _mixin()
    r = m.set_theme("light")
    assert r["ok"] is True
    assert r["title_bar"]["reason"] == "unsupported"


def test_set_theme_apply_exception_is_caught(monkeypatch):
    """标题栏配色是锦上添花，任何异常都不能把切换本身搞失败。"""
    def fake(mode, **kw):
        raise RuntimeError("dwmapi exploded")

    monkeypatch.setattr(win_theme, "apply_for_mode", fake)
    m = _mixin()
    r = m.set_theme("dark")
    assert r["ok"] is False
    assert r["reason"] == "apply_failed"
    assert "dwmapi exploded" in r["error"]
