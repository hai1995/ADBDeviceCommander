# -*- coding: utf-8 -*-
"""select_save_dir：保存目录「选择」按钮的后端。

只做「弹系统文件夹对话框、回传选中路径」这一件小事，不碰任何设备 / 会话状态，
所以用一个最小子类直接构造即可（mixin 不要求 bus / state 等依赖）。

这组用例的起因是一个真实故障：用户点「选择」毫无反应。根因是 ctypes 结构体
字段赋值抛 TypeError（c_wchar_Array 塞给 c_wchar_p），异常被外层
`except Exception: return None` 吞成「用户取消」，前端按取消静默 —— 于是
按钮像没接线。三档结果（选中 / 取消 / 打不开）必须分得开。
"""
import sys
import types

import backend.controllers.file as file_mod
from backend.controllers.file import FileMixin, _build_browse_info, _win_select_folder


class _File(FileMixin):
    pass


class _FileWithBus(FileMixin):
    """带状态播报桩的版本：验证「打不开」时确实说了话。"""

    def __init__(self):
        self.pushed = []

    def _push_status(self, type_, text, toast=False):
        self.pushed.append((type_, text))


def test_win_select_folder_returns_none_off_windows():
    # 非 Windows 平台没有原生文件夹对话框，必须显式返回 None（而非抛异常）
    assert _win_select_folder("x") is None


def test_build_browse_info_sets_display_buffer_without_typeerror():
    """核心回归：pszDisplayName 必须能赋值。

    旧写法 `bi.pszDisplayName = ctypes.create_unicode_buffer(2048)` 每次调用都抛
    `TypeError: incompatible types, c_wchar_Array_2048 instance instead of
    c_wchar_p instance`，异常被吞成 None —— 在 Windows 上「选择」按钮**永远**
    没有下文。现在先 cast 成 wchar 指针再赋。
    """
    bi, _buf = _build_browse_info("选择保存目录")
    # 未赋值时 c_wchar_p 读回 None；空缓冲区读回 ""。这里要的是「指针已设」
    assert bi.pszDisplayName is not None
    assert bi.lpszTitle == "选择保存目录"
    assert bi.ulFlags & 0x0040, "BIF_USENEWUI：带可粘贴路径的新版界面"


def test_pick_folder_uses_webview_folder_dialog(monkeypatch):
    """pywebview 可用时走原生文件夹对话框（有 owner 窗口，不会被主窗口盖住）。"""
    seen = {}

    class _Win:
        def create_file_dialog(self, kind, directory=""):
            seen["kind"] = kind
            seen["directory"] = directory
            return (r"D:\shots",)

    fake = types.SimpleNamespace(FOLDER_DIALOG="FOLDER",
                                 active_window=lambda: _Win())
    monkeypatch.setitem(sys.modules, "webview", fake)
    monkeypatch.setattr(file_mod.os.path, "isdir", lambda p: True)

    assert file_mod._pick_folder(r"D:\shots") == (r"D:\shots", "")
    assert seen["kind"] == "FOLDER"
    assert seen["directory"] == r"D:\shots", "应定位到当前目录，省得用户从头找"


def test_pick_folder_distinguishes_cancel_from_error(monkeypatch):
    """取消与「打不开」必须分开：前者静默，后者要播报。"""

    class _Cancel:
        def create_file_dialog(self, *a, **k):
            return ()

    class _Boom:
        def create_file_dialog(self, *a, **k):
            raise RuntimeError("no display")

    monkeypatch.setitem(sys.modules, "webview",
                        types.SimpleNamespace(FOLDER_DIALOG="FOLDER",
                                              active_window=lambda: _Cancel()))
    assert file_mod._pick_folder() == (None, "cancelled")

    monkeypatch.setitem(sys.modules, "webview",
                        types.SimpleNamespace(FOLDER_DIALOG="FOLDER",
                                              active_window=lambda: _Boom()))
    path, why = file_mod._pick_folder()
    assert path is None and why.startswith("error:") and "no display" in why


def test_pick_folder_unsupported_without_window(monkeypatch):
    """拿不到窗口 / 没有 pywebview：报 unsupported，由调用方决定退路。"""
    monkeypatch.setitem(sys.modules, "webview",
                        types.SimpleNamespace(FOLDER_DIALOG="FOLDER",
                                              active_window=lambda: None))
    assert file_mod._pick_folder() == (None, "unsupported")

    monkeypatch.setitem(sys.modules, "webview", None)   # 模拟 import 失败
    assert file_mod._pick_folder() == (None, "unsupported")


def test_select_save_dir_unsupported_off_windows():
    # 开发 / CI 跑在 Linux：选目录功能不可用，应当给出明确 reason 而非崩溃
    res = _File().select_save_dir()
    assert res == {"ok": False, "reason": "unsupported"}


def test_select_save_dir_returns_chosen_path(monkeypatch):
    # 对话框选中路径 -> 原样回传，前端据此写输入框 + 落盘
    monkeypatch.setattr(file_mod, "_pick_folder", lambda cur=None: (r"D:\shots", ""))
    assert _File().select_save_dir() == {"ok": True, "path": r"D:\shots"}


def test_select_save_dir_cancelled_is_silent(monkeypatch):
    # 用户主动取消：前端静默忽略，不该弹任何提示
    monkeypatch.setattr(file_mod, "_pick_folder", lambda cur=None: (None, "cancelled"))
    assert _File().select_save_dir() == {"ok": False, "reason": "cancelled"}


def test_select_save_dir_falls_back_to_win32(monkeypatch):
    """pywebview 拿不到窗口时，Windows 上退到 SHBrowseForFolder（而不是直接放弃）。"""
    monkeypatch.setattr(file_mod, "_pick_folder", lambda cur=None: (None, "unsupported"))
    monkeypatch.setattr(file_mod.sys, "platform", "win32")
    monkeypatch.setattr(file_mod, "_win_select_folder", lambda title: r"D:\shots")
    assert _File().select_save_dir() == {"ok": True, "path": r"D:\shots"}


def test_select_save_dir_error_is_broadcast(monkeypatch):
    """打不开对话框要播报一句：否则用户面对的就是「点了没反应」。"""
    monkeypatch.setattr(file_mod, "_pick_folder",
                        lambda cur=None: (None, "error:no display"))
    f = _FileWithBus()
    res = f.select_save_dir()
    assert res == {"ok": False, "reason": "error", "text": "no display"}
    assert f.pushed and f.pushed[0][0] == "err", f.pushed
    assert "no display" in f.pushed[0][1]
    # 要给出可执行的退路，不能只说「失败了」
    assert "手动输入" in f.pushed[0][1], f.pushed[0][1]
