# -*- coding: utf-8 -*-
"""core.devinfo —— 设备信息快照解析（一次 adb shell 取全后的纯解析）。"""
from core import devinfo


_RAW = """@@PROP
[ro.product.manufacturer]: [Xiaomi]
[ro.product.model]: [MI 11]
[ro.product.device]: [venus]
[ro.build.version.release]: [13]
[ro.build.version.sdk]: [33]
[ro.build.display.id]: [TKQ1.221013.002]
[ro.build.type]: [user]
[ro.product.cpu.abi]: [arm64-v8a]
[ro.serialno]: [abc123]
@@WM
Physical size: 1440x3200
Override size: 1080x2400
Physical density: 560
Override density: 440
@@BATT
Current Battery Service state:
  AC powered: false
  level: 87
  status: 2
  temperature: 315
@@DF
Filesystem      1K-blocks     Used Available Use% Mounted on
/dev/block/dm-4 115343360 43567890  71775470  38% /data
@@MEM
MemTotal:        7628000 kB
MemFree:          400000 kB
MemAvailable:    2314000 kB
@@UP
123456.78 456789.01
"""


def test_parse_props_and_wm():
    info = devinfo.parse_info(_RAW)
    assert info["ro.product.model"] == "MI 11"
    assert info["ro.product.manufacturer"] == "Xiaomi"
    assert info["ro.build.version.release"] == "13"
    assert info["ro.product.cpu.abi"] == "arm64-v8a"
    assert info["resolution"] == "1440x3200"
    assert info["resolution_override"] == "1080x2400"
    # 覆盖密度才是实际生效值
    assert info["density"] == "440"


def test_parse_battery_temp_is_tenths_of_degree():
    info = devinfo.parse_info(_RAW)
    assert info["battery_level"] == "87"
    assert info["battery_status"] == "2"
    assert info["battery_temp"] == "31.5"


def test_parse_storage_and_mem():
    info = devinfo.parse_info(_RAW)
    assert info["storage_total_kb"] == 115343360
    assert info["storage_used_kb"] == 43567890
    assert info["storage_avail_kb"] == 71775470
    assert info["mem_total_kb"] == 7628000
    assert info["mem_avail_kb"] == 2314000


def test_parse_uptime_seconds():
    assert devinfo.parse_info(_RAW)["uptime_s"] == 123456.78


def test_rows_are_ordered_and_formatted():
    rows = devinfo.rows(devinfo.parse_info(_RAW))
    labels = [k for k, _v in rows]
    assert labels[0] == "厂商"
    assert "分辨率" in labels and "电量" in labels
    assert "存储 /data" in labels and "内存" in labels
    res = dict(rows)["分辨率"]
    assert "1440x3200" in res and "1080x2400" in res
    assert dict(rows)["电量"].startswith("87%")
    assert "31.5℃" in dict(rows)["电量"]


def test_rows_skip_missing_values():
    rows = devinfo.rows(devinfo.parse_info("@@PROP\n[ro.product.model]: [X]\n"))
    assert rows == [("型号", "X")]


def test_parse_tolerates_garbage_and_empty():
    assert devinfo.parse_info("")["ro.product.model"] == ""
    assert devinfo.parse_info("%%weird%%")["storage_total_kb"] == 0
    assert devinfo.parse_info(None)["mem_total_kb"] == 0


def test_df_with_extra_columns_still_parses():
    """不同 ROM 的 df 列数不一样，按「最后一个百分比列」定位。"""
    raw = ("@@DF\nFilesystem  Size  Used  Avail  Use%  Mounted on\n"
           "/dev/root  10G  4.0G  5.5G  42%  /data\n")
    info = devinfo.parse_info(raw)
    assert (info["storage_total_kb"], info["storage_used_kb"]) != (0, 0)


def test_override_resolution_equal_to_physical_not_repeated():
    raw = "@@WM\nPhysical size: 1080x2400\nOverride size: 1080x2400\n"
    rows = dict(devinfo.rows(devinfo.parse_info(raw)))
    assert rows["分辨率"] == "1080x2400"


def test_fmt_uptime():
    assert devinfo.fmt_uptime(0) == ""
    assert devinfo.fmt_uptime(59) == "不足 1 分钟"
    assert devinfo.fmt_uptime(120) == "2 分"
    assert devinfo.fmt_uptime(3 * 3600 + 5 * 60) == "3 小时 5 分"
    assert devinfo.fmt_uptime(2 * 86400 + 3600 + 60) == "2 天 1 小时 1 分"


def test_as_text_lines_match_rows():
    info = devinfo.parse_info(_RAW)
    text = devinfo.as_text(info)
    assert text.splitlines()[0] == "厂商: Xiaomi"
    assert len(text.splitlines()) == len(devinfo.rows(info))


def test_script_contains_all_sections():
    """脚本与解析标记必须一一对应（改一处忘另一处就会静默丢整段信息）。"""
    for mark in (devinfo.MARK_PROP, devinfo.MARK_WM, devinfo.MARK_BATT,
                 devinfo.MARK_DF, devinfo.MARK_MEM, devinfo.MARK_UP):
        assert mark in devinfo.SCRIPT


# ---------------------------------------------------------------------------
# 容量单位自适应（剩余空间小时不能写成 0.0 GB）
# ---------------------------------------------------------------------------
def test_rows_use_mb_when_free_space_is_small():
    """剩余 50 MB 必须显示「50 MB」，不能是「0.0 GB」。

    回归：`_size` 原来固定按 GB 保留一位小数，车机 /data 只剩几十 MB 时
    渲染成「剩余 0.0 GB」——看着像已经满了，实际还能装一个包；反过来这类
    误读会让人去清缓存、删应用，白折腾。
    """
    info = devinfo.parse_info("")           # 空输出先拿一份全空的骨架
    info.update({
        "storage_total_kb": 32 * 1024 * 1024,   # 32 GB
        "storage_used_kb": 32 * 1024 * 1024 - 50 * 1024,
        "storage_avail_kb": 50 * 1024,          # 只剩 50 MB
    })
    line = dict(devinfo.rows(info))["存储 /data"]
    assert "剩余 50 MB" in line, line
    assert "0.0 GB" not in line, line


def test_rows_show_zero_used_instead_of_blank():
    """刚好清空的分区要显示「0 MB 已用」，不能留一格空白。"""
    info = devinfo.parse_info("")
    info.update({"storage_total_kb": 1024 * 1024,
                 "storage_used_kb": 0,
                 "storage_avail_kb": 1024 * 1024})
    line = dict(devinfo.rows(info))["存储 /data"]
    assert line.startswith("0 MB / "), line
    assert "已用（0%）" in line, line


def test_rows_memory_uses_sensible_units():
    """内存常用 MB 量级，别一律折成 GB。"""
    info = devinfo.parse_info("")
    info.update({"mem_total_kb": 3 * 1024 * 1024,      # 3 GB
                 "mem_avail_kb": 800 * 1024})          # 800 MB
    line = dict(devinfo.rows(info))["内存"]
    assert "800 MB" in line, line


def test_df_parses_even_when_warning_precedes_header():
    """表头前多一行警告时，仍要读出容量（不能把唯一的数据行跳过）。"""
    raw = ("@@DF\n"
           "df: /data: No such file or directory\n"      # 警告占掉首行
           "Filesystem     1K-blocks     Used Available Use% Mounted on\n"
           "/dev/block/dm-3 26000000 12000000 14000000  47% /data\n")
    info = devinfo.parse_info(raw)
    assert info["storage_total_kb"] == 26000000
    assert info["storage_used_kb"] == 12000000
    assert info["storage_avail_kb"] == 14000000


def test_df_parses_output_without_header_at_all():
    """个别精简 ROM 直接给数据行（无表头），也要读得出来。"""
    raw = ("@@DF\n"
           "/dev/block/dm-3 26000000 12000000 14000000  47% /data\n")
    info = devinfo.parse_info(raw)
    assert info["storage_total_kb"] == 26000000
