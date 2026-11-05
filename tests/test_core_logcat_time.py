# -*- coding: utf-8 -*-
"""core.logcat 的时间戳解析与抓取文件首末时间（不依赖真实设备）。

为什么值得单独测：录屏配套日志的「到底跟到什么时候」全靠这两个函数，
而 logcat 的 threadtime 里**没有年份** —— 跨年、跨天、设备校时回退这些
边界一旦判错，结果就是「日志被当成重放整段丢掉」或「日志其实少了 24 分钟
却显示一切正常」，两种都只在事后才发现。
"""
import datetime

import pytest

from core.logcat import read_time_bounds, ts_epoch, ts_prefix


def _epoch(y, mo, d, h=0, mi=0, s=0, ms=0):
    return datetime.datetime(y, mo, d, h, mi, s, ms * 1000).timestamp()


def test_ts_prefix_only_accepts_threadtime():
    """只有 threadtime 行首才算时间戳；adb 横幅 / 缺口标记 / 空行都不算。"""
    assert ts_prefix("08-29 10:23:45.123  1234  1234 I Tag: hi\n") == \
        "08-29 10:23:45.123"
    assert ts_prefix("--------- beginning of main\n") == ""
    assert ts_prefix("--------- [logcat] 设备于 2026-01-01 断开 ---------\n") == ""
    assert ts_prefix("") == ""
    assert ts_prefix("08-29 10:23:45.123") == "08-29 10:23:45.123"


def test_ts_epoch_normal():
    ref = _epoch(2026, 2, 6, 12, 0, 0)
    assert ts_epoch("02-06 10:50:00.000", ref=ref) == _epoch(2026, 2, 6, 10, 50)


def test_ts_epoch_rolls_back_one_year_for_future_month():
    """比基准晚半年以上的月日 = 去年的那一天（跨年录制靠这条纠正）。"""
    ref = _epoch(2026, 2, 6, 12, 0, 0)
    # 「12-31」在 2 月看来是去年的事
    assert ts_epoch("12-31 23:59:59.000", ref=ref) == \
        _epoch(2025, 12, 31, 23, 59, 59)


def test_ts_epoch_cross_year_is_monotonic():
    """跨年时「次年 1 月」必须晚于「今年 12 月」，不能被字符串序骗过去。"""
    ref = _epoch(2026, 1, 1, 0, 10, 0)          # 刚过零点
    prev = ts_epoch("12-31 23:59:50.000", ref=ref)
    cur = ts_epoch("01-01 00:00:05.000", ref=ref)
    assert prev is not None and cur is not None
    assert cur > prev, "零点之后的日志被判成「更早」，会整体当成重放丢掉"


@pytest.mark.parametrize("bad", ["", "xx-xx xx:xx:xx.xxx", "08-29 10:23:45.",
                                 "13-45 99:99:99.999"])
def test_ts_epoch_rejects_garbage(bad):
    assert ts_epoch(bad, ref=0) is None


def test_read_time_bounds_small_file(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text(
        "--------- beginning of main\n"
        "08-29 10:00:01.000  1  1 I Tag: a\n"
        "08-29 10:00:02.000  1  1 I Tag: b\n"
        "--------- [logcat] 设备于 2026-01-01 断开连接 ---------\n",
        encoding="utf-8")
    first, last = read_time_bounds(str(p))
    assert first == "08-29 10:00:01.000"
    # 尾部标记行不算：必须是最后一条**真日志**的时间
    assert last == "08-29 10:00:02.000"


def test_read_time_bounds_large_file_reads_tail_only(tmp_path):
    """大文件只读头尾：尾部时间戳必须取到，不能被中间内容拖慢或读错。"""
    p = tmp_path / "big.txt"
    with open(p, "w", encoding="utf-8") as f:
        f.write("08-29 09:00:00.000  1  1 I Tag: start\n")
        for i in range(20000):
            f.write("08-29 09:30:%02d.%03d  1  1 I Tag: filler %d\n"
                    % (i % 60, i % 1000, i))
        f.write("08-29 11:14:00.000  1  1 I Tag: end\n")
    assert p.stat().st_size > 256 * 1024          # 确实超过一次读取的窗口
    first, last = read_time_bounds(str(p))
    assert first == "08-29 09:00:00.000"
    assert last == "08-29 11:14:00.000"


def test_read_time_bounds_missing_or_empty(tmp_path):
    assert read_time_bounds(None) == (None, None)
    assert read_time_bounds(str(tmp_path / "nope.txt")) == (None, None)
    p = tmp_path / "empty.txt"
    p.write_text("", encoding="utf-8")
    assert read_time_bounds(str(p)) == (None, None)
    q = tmp_path / "only_markers.txt"
    q.write_text("--------- beginning of main\n", encoding="utf-8")
    assert read_time_bounds(str(q)) == (None, None)
