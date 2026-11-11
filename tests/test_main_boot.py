# -*- coding: utf-8 -*-
"""main 启动提速：PYWEBVIEW_GUI 跳过 backend 探测 + 分段耗时落盘（不创建窗口）。"""
import os

import main


def test_pywebview_gui_pinned_to_edgechromium():
    """import main 时必须显式钉住 PYWEBVIEW_GUI=edgechromium。

    回归：pywebview import 时会逐个探测 cef / gtk / qt / winforms /
    edgechromium，Windows 上通常还要额外加载 pythonnet/clr，白等几百
    ms~1s。本项目只跑 WebView2，显式指定后整段探测被跳过。
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
