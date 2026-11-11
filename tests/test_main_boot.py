# -*- coding: utf-8 -*-
"""main 启动链路：后端固定、分段耗时落盘、MOTW 清理与 GUI 失败兜底（不创建窗口）。"""
import os

import main


def test_pywebview_gui_pinned_to_edgechromium():
    """import main 时必须显式钉住 PYWEBVIEW_GUI=edgechromium。

    注意这不是「跳过后端探测」的提速：pywebview 6.x 的 Windows 分支无论该值
    如何都只调 import_winforms，本来就没有多后端探测。这一行只是固定后端，
    避免将来 pywebview 改默认行为时窗口表现漂移（见 main.py 顶部注释）。
    """
    assert os.environ.get("PYWEBVIEW_GUI") == "edgechromium"


def test_boot_mark_writes_stderr_and_log_file(tmp_path, monkeypatch, capsys):
    """分段耗时既写 stderr 也写日志文件。

    --windowed 打包的 exe 没有控制台，stderr 看不到；只有落盘的分段日志，
    用户才能把「这次启动慢在哪一段」反馈回来。
    """
    log = tmp_path / "boot_timing.log"
    monkeypatch.setattr(main, "_boot_timing_path", lambda: str(log))
    mark = main._make_boot_mark(0.0)
    mark("hello_tag")
    body = log.read_text(encoding="utf-8")
    assert "hello_tag" in body and "[boot" in body
    assert "hello_tag" in capsys.readouterr().err


def test_reset_boot_timing_log_truncates(tmp_path, monkeypatch):
    """每次启动重起一份：旧分段不能留在文件里误导下次排查。"""
    log = tmp_path / "boot_timing.log"
    log.write_text("旧的记录\n", encoding="utf-8")
    monkeypatch.setattr(main, "_boot_timing_path", lambda: str(log))
    main._reset_boot_timing_log()
    body = log.read_text(encoding="utf-8")
    assert "旧的记录" not in body and "启动" in body


def test_boot_mark_never_raises_on_unwritable_log(tmp_path, monkeypatch):
    """日志路径不可写（目录被删 / 只读）时打点本身绝不能把启动弄崩。"""
    monkeypatch.setattr(main, "_boot_timing_path",
                        lambda: str(tmp_path / "no_such_dir" / "x.log"))
    main._make_boot_mark(0.0)("silent_tag")   # 不抛即通过


def test_process_age_is_none_off_windows(monkeypatch):
    """非 Windows 拿不到进程创建时间：返回 None（日志里就不打这一行）。

    这段耗时专为量化 onefile 解压而加，取不到时只能静默跳过，绝不能抛异常
    或返回负数影响分段日志。
    """
    monkeypatch.setattr(main.sys, "platform", "linux")
    assert main._process_age_seconds() is None


def test_module_t0_precedes_backend_imports():
    """计时起点在业务模块 import 之前：否则 import backend/core 的耗时被漏算。"""
    assert isinstance(main._MODULE_T0, float)
    assert main._MODULE_T0 > 0


# ---------------------------------------------------------------------------
# onedir 崩溃修复：清除「来自网络」标记（Zone.Identifier）
# ---------------------------------------------------------------------------
def test_strip_motw_is_noop_when_not_frozen(monkeypatch):
    """源码运行 / 非 Windows：绝不能去碰 ctypes.windll，直接返回 0。"""
    monkeypatch.setattr(main, "_motw_needed", lambda: False)

    def _must_not_run(path):
        raise AssertionError("不该在非打包态调用 DeleteFileW")

    monkeypatch.setattr(main, "_delete_zone_identifier", _must_not_run)
    assert main._strip_mark_of_the_web() == 0


def test_strip_motw_only_touches_binary_suffixes(tmp_path, monkeypatch):
    """只清二进制、不递归整个包：用户已反馈启动慢，清理不能变成新瓶颈。"""
    (tmp_path / "Python.Runtime.dll").write_bytes(b"MZ")
    (tmp_path / "ClrLoader.pyd").write_bytes(b"MZ")
    (tmp_path / "helper.exe").write_bytes(b"MZ")
    (tmp_path / "app.manifest").write_text("<xml/>", encoding="utf-8")
    (tmp_path / "module.pyc").write_bytes(b"\x00")
    (tmp_path / "notes.txt").write_text("keep", encoding="utf-8")
    (tmp_path / "nested.dll").mkdir()          # 同名目录不能被当文件处理

    monkeypatch.setattr(main, "_motw_needed", lambda: True)
    monkeypatch.setattr(main, "_motw_cleanup_dirs", lambda: [str(tmp_path)])
    seen = []
    monkeypatch.setattr(main, "_delete_zone_identifier",
                        lambda p: seen.append(p) or True)

    count = main._strip_mark_of_the_web()

    assert count == 4
    assert len(seen) == 4
    assert all(p.endswith(":Zone.Identifier") for p in seen)
    names = {os.path.basename(p).split(":")[0] for p in seen}
    assert names == {"Python.Runtime.dll", "ClrLoader.pyd",
                     "helper.exe", "app.manifest"}
    assert not any("module.pyc" in p or "notes.txt" in p or "nested.dll" in p
                   for p in seen)


def test_strip_motw_never_raises_on_bad_dir(monkeypatch):
    """目录不可列举 / 删除失败时清理本身绝不把启动弄崩。"""
    monkeypatch.setattr(main, "_motw_needed", lambda: True)
    monkeypatch.setattr(main, "_motw_cleanup_dirs",
                        lambda: ["/definitely/not/a/real/dir"])
    assert main._strip_mark_of_the_web() == 0


def test_delete_zone_identifier_is_noop_off_windows():
    """非 Windows 没有 kernel32：返回 False 且不抛（Linux 跑单测时走这条）。"""
    ads = "C:\\app\\_internal\\pythonnet\\runtime\\Python.Runtime.dll:Zone.Identifier"
    assert main._delete_zone_identifier(ads) is False


# ---------------------------------------------------------------------------
# GUI 初始化失败：给用户可自救的中文指引
# ---------------------------------------------------------------------------
def test_gui_failure_lines_gives_unblock_guide():
    """pythonnet / MOTW 错误必须给出「解除锁定 + 重新解压」的可操作步骤。"""
    exc = RuntimeError(
        "Failed to resolve Python.Runtime.Loader.Initialize from "
        "C:\\app\\_internal\\pythonnet\\runtime\\Python.Runtime.dll")
    lines = "\n".join(main._gui_failure_lines(exc))
    assert "解除锁定" in lines
    assert "Unblock-File" in lines
    assert "Python.Runtime" in lines


def test_gui_failure_lines_generic_error():
    """非 pythonnet 错误不该误导用户去解除锁定。"""
    lines = "\n".join(main._gui_failure_lines(ValueError("WebView2 missing")))
    assert "解除锁定" not in lines
    assert "崩溃日志" in lines


def test_report_gui_init_failure_logs_and_shows_guide(tmp_path, monkeypatch):
    """失败时写一行启动打点、留崩溃日志并弹中文指引（不弹重复窗口）。"""
    log = tmp_path / "boot_timing.log"
    monkeypatch.setattr(main, "_boot_timing_path", lambda: str(log))
    monkeypatch.setattr(main, "_write_crash_log",
                        lambda *a, **k: str(tmp_path / "crash.log"))
    shown = {}
    monkeypatch.setattr(main, "_show_native_error",
                        lambda title, lines, url=None: shown.update(
                            title=title, lines=lines))

    exc = RuntimeError("Failed to resolve Python.Runtime.Loader.Initialize")
    main._report_gui_init_failure(exc)

    assert "[启动失败]" in log.read_text(encoding="utf-8")
    assert shown and "启动失败" in shown["title"]
    assert any("解除锁定" in line for line in shown["lines"])
    assert any("crash.log" in line for line in shown["lines"])
