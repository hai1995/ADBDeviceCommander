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


class _TickTime:
    """每次 strftime 自增 1 秒：生成互不覆盖的崩溃日志名。"""

    def __init__(self):
        self.n = 0

    def strftime(self, _fmt):
        self.n += 1
        return "20261122_10%02d%02d" % (self.n // 60, self.n % 60)


def test_crash_logs_are_rotated_to_keep_limit(tmp_path, monkeypatch):
    """反复崩溃时 crash_*.log 不能无上限堆积，只保留最近 CRASH_LOG_KEEP 份。

    回归：threading.excepthook 对后台线程的每个未捕获异常都写一份日志，一个
    反复重连的坏循环能在短时间内写出成百上千份，填满程序目录/临时目录磁盘。
    """
    monkeypatch.setattr(main, "PROJECT_ROOT", str(tmp_path))
    tick = _TickTime()
    monkeypatch.setattr(main, "time", tick)
    monkeypatch.setattr(main, "CRASH_LOG_KEEP", 5)
    for i in range(12):
        et, ev, tb = _crash("boom-%d" % i)
        main._write_crash_log("测试", et, ev, tb)
    logs = [p for p in tmp_path.iterdir()
            if p.name.startswith("crash_") and p.name.endswith(".log")]
    assert len(logs) == 5, "应只保留最近 5 份，实际 %d" % len(logs)
    # 最新的几份（含最后的 boom-11）必须还在
    bodies = [p.read_text(encoding="utf-8") for p in logs]
    assert any("boom-11" in b for b in bodies)


def test_crash_log_survives_lone_surrogate(tmp_path, monkeypatch):
    """异常消息含 lone surrogate 时日志不能因为编码错误而整份丢失。

    Windows 文件名走 surrogateescape，traceback 里常见 \\udcxx；默认
    errors=strict 会让 f.write 抛 UnicodeEncodeError，两个候选目录都失败后
    返回 None —— 最需要日志的崩溃场景反而日志全丢。
    """
    monkeypatch.setattr(main, "PROJECT_ROOT", str(tmp_path))
    et, ev, tb = _crash("bad-name-\udcff-suffix")
    path = main._write_crash_log("测试", et, ev, tb)
    assert path is not None, "含 surrogate 的异常也必须写出日志"
    with open(path, encoding="utf-8") as f:
        assert "bad-name-" in f.read()
