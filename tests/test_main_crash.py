# -*- coding: utf-8 -*-
"""main._write_crash_log —— 崩溃日志落盘（不创建窗口 / 不依赖 webview）。"""
import os

import main


class _FrozenTime:
    """固定时间戳：让多次崩溃必然落在「同一秒」，才验证得了覆盖问题。"""

    @staticmethod
    def strftime(_fmt):
        return "20261031_120000"


def _crash(msg):
    try:
        raise ValueError(msg)
    except ValueError:
        import sys
        return sys.exc_info()


def test_crash_logs_in_same_second_do_not_overwrite(tmp_path, monkeypatch):
    """同一秒内多个线程相继崩溃时，先写的那份（带根因）不能被后一份冲掉。

    回归：文件名只到秒（crash_<YYYYmmdd_HHMMSS>.log），一个坏循环连着炸时，
    最后一份把前面全部覆盖 —— 而最先炸的那一份才带着根因。
    """
    monkeypatch.setattr(main, "PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(main, "time", _FrozenTime)
    paths = []
    for i in range(3):
        et, ev, tb = _crash("boom-%d" % i)
        paths.append(main._write_crash_log("测试", et, ev, tb))
    assert all(paths) and len(set(paths)) == 3, "三份日志不能互相覆盖"
    bodies = []
    for p in paths:
        assert p.startswith(str(tmp_path))
        assert os.path.exists(p)
        with open(p, encoding="utf-8") as f:
            bodies.append(f.read())
    assert any("boom-0" in b for b in bodies), "第一份（根因）必须保留"
    assert any("原因  : 测试" in b for b in bodies)
