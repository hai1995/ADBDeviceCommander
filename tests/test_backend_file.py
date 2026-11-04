# -*- coding: utf-8 -*-
"""select_save_dir：保存目录「选择」按钮的后端。

只做「弹系统文件夹对话框、回传选中路径」这一件小事，不碰任何设备 / 会话状态，
所以用一个最小子类直接构造即可（mixin 不要求 bus / state 等依赖）。
"""
import backend.controllers.file as file_mod
from backend.controllers.file import FileMixin, _win_select_folder


class _File(FileMixin):
    pass


def test_win_select_folder_returns_none_off_windows():
    # 非 Windows 平台没有原生文件夹对话框，必须显式返回 None（而非抛异常）
    assert _win_select_folder("x") is None


def test_select_save_dir_unsupported_off_windows():
    # 开发 / CI 跑在 Linux：选目录功能不可用，应当给出明确 reason 而非崩溃
    res = _File().select_save_dir()
    assert res == {"ok": False, "reason": "unsupported"}


def test_select_save_dir_returns_chosen_path(monkeypatch):
    # 对话框选中路径 -> 原样回传，前端据此写输入框 + 落盘
    monkeypatch.setattr(file_mod, "_win_select_folder", lambda title: r"D:\shots")
    assert _File().select_save_dir() == {"ok": True, "path": r"D:\shots"}


def test_select_save_dir_cancelled_on_windows(monkeypatch):
    # 仅在 Windows 上用户点取消才报 cancelled：用假平台 + 假对话框验证分支
    monkeypatch.setattr(file_mod, "_win_select_folder", lambda title: None)
    monkeypatch.setattr(file_mod.sys, "platform", "win32")
    assert _File().select_save_dir() == {"ok": False, "reason": "cancelled"}
