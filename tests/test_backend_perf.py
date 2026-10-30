# -*- coding: utf-8 -*-
"""backend.perf_service —— 性能采样解析 / 采样器 / 报告生成单测（全部离线）。"""
import os

import pytest

import backend.perf_service as svc


# --------------------------------------------------------------------------- #
# /proc 与 dumpsys 解析
# --------------------------------------------------------------------------- #
def test_parse_proc_stat_and_cpu_percent():
    a = svc.parse_proc_stat("cpu  1000 100 300 6000 200 0 50 0 0 0")
    b = svc.parse_proc_stat("cpu  1100 100 400 6400 200 0 50 0 0 0")
    assert a == {"total": 7650, "idle": 6200}
    assert b["total"] == 8250
    # Δtotal=600，Δidle=400 → 33.3%
    assert svc.cpu_percent(a, b) == pytest.approx(33.3, abs=0.05)


def test_parse_proc_stat_ignores_guest_fields():
    """guest/guest_nice 已含在 user/nice 里，再加一遍会让 CPU% 系统性偏低。"""
    with_guest = svc.parse_proc_stat("cpu  100 0 100 800 0 0 0 0 500 500")
    without = svc.parse_proc_stat("cpu  100 0 100 800 0 0 0 0 0 0")
    assert with_guest == without


def test_cpu_percent_clamps_and_handles_bad_input():
    a = svc.parse_proc_stat("cpu  0 0 0 100 0 0 0 0")
    assert svc.cpu_percent(a, a) is None          # Δtotal=0：除零，返回 None
    assert svc.cpu_percent(None, a) is None
    assert svc.parse_proc_stat("") is None
    assert svc.parse_proc_stat("cpu  x y z w") is None


def test_parse_pid_stat_with_spaces_in_comm():
    """comm 可能带空格/括号（如 `(Web Content)`），必须从最后一个 ')' 开始切。"""
    line = ("1234 (Web Content) S 1 1234 1234 0 -1 4194624 100 0 0 0 "
            "120 30 0 0 20 0 10 0 500 1000000 3000 18446744073709551615")
    assert svc.parse_pid_stat(line) == 150
    assert svc.parse_pid_stat("") is None
    assert svc.parse_pid_stat("1234 (broken") is None


def test_parse_meminfo_prefers_mem_available():
    text = ("MemTotal:        7900000 kB\nMemFree:          300000 kB\n"
            "MemAvailable:    3100000 kB\nBuffers:           20000 kB\n")
    r = svc.parse_meminfo(text)
    assert r["total_mb"] == pytest.approx(7714.8, abs=0.1)
    assert r["used_mb"] == pytest.approx(4687.5, abs=0.1)


def test_parse_meminfo_falls_back_to_free_buffers_cached():
    """老内核没有 MemAvailable：用 Free+Buffers+Cached 近似，不能直接当作 0。"""
    text = ("MemTotal:  8000000 kB\nMemFree:  500000 kB\n"
            "Buffers:  100000 kB\nCached:  2400000 kB\n")
    r = svc.parse_meminfo(text)
    assert r["used_mb"] == pytest.approx((8000000 - 3000000) / 1024.0, abs=0.1)


def test_parse_meminfo_rejects_garbage():
    assert svc.parse_meminfo("") is None
    assert svc.parse_meminfo("nothing here") is None


def test_parse_dumpsys_meminfo_total_row():
    text = ("** MEMINFO in pid 1234 [com.foo] **\n"
            "                   Pss  Private  Private  SwapPss      Rss\n"
            "  Native Heap    12345    12000        0        0    20000\n"
            "         TOTAL    78901    60000      500        0   120000\n")
    assert svc.parse_dumpsys_meminfo(text) == pytest.approx(77.1, abs=0.05)


def test_parse_dumpsys_meminfo_legacy_total_pss():
    assert svc.parse_dumpsys_meminfo("TOTAL PSS:   40960\n") == pytest.approx(40.0)


def test_parse_dumpsys_meminfo_missing_returns_none():
    assert svc.parse_dumpsys_meminfo("no total line") is None
    assert svc.parse_dumpsys_meminfo("") is None


def test_parse_gfxinfo():
    text = ("** Graphics info **\n\nTotal frames rendered: 5432\n"
            "Janky frames: 123 (2.26%)\n")
    assert svc.parse_gfxinfo(text) == (5432, pytest.approx(2.26))
    assert svc.parse_gfxinfo("") == (None, None)


def test_parse_battery_scales_temperature():
    """temperature 是**十分之一摄氏度**：310 必须变成 31.0，否则报告里是「310 度」。"""
    r = svc.parse_battery("  level: 78\n  temperature: 310\n  status: 2\n")
    assert r["batt"] == 78 and r["temp"] == pytest.approx(31.0) and r["status"] == 2
    assert svc.parse_battery("garbage") is None


def test_parse_focus_pkg_prefers_current_focus():
    text = ("  mFocusedApp=ActivityRecord{9a u0 com.other/.Main t1}\n"
            "  mCurrentFocus=Window{8f u0 com.tencent.kuwo/music.MainActivity}\n")
    assert svc.parse_focus_pkg(text) == "com.tencent.kuwo"


def test_parse_focus_pkg_falls_back_to_focused_app():
    text = "  mFocusedApp=ActivityRecord{9a u0 com.other/.Main t1}\n"
    assert svc.parse_focus_pkg(text) == "com.other"
    assert svc.parse_focus_pkg("") == ""


def test_parse_wm_size_prefers_override():
    assert svc.parse_wm_size("Physical size: 1080x2340") == "1080x2340"
    assert svc.parse_wm_size(
        "Physical size: 1080x2340\nOverride size: 720x1560") == "720x1560"
    assert svc.parse_wm_size("") == ""


def test_fps_from_frames_and_reset():
    assert svc.fps_from_frames(1000, 1060, 1.0) == pytest.approx(60.0)
    # 应用重启 → 计数归零：必须返回 None（断线），不能算出负帧率
    assert svc.fps_from_frames(5000, 10, 1.0) is None
    assert svc.fps_from_frames(None, 10, 1.0) is None
    assert svc.fps_from_frames(1, 2, 0) is None


def test_app_cpu_percent():
    assert svc.app_cpu_percent(100, 160, 10000, 14000) == pytest.approx(1.5)
    # 进程重启：jiffies 变小 → None
    assert svc.app_cpu_percent(1000, 10, 10000, 14000) is None
    assert svc.app_cpu_percent(None, 10, 10000, 14000) is None


# --------------------------------------------------------------------------- #
# 采样器
# --------------------------------------------------------------------------- #
class _Proc:
    def __init__(self, out="", code=0, err=""):
        self.stdout = out
        self.stderr = err
        self.returncode = code


_RAW = """@@STAT
cpu  1000 100 300 6000 200 0 50 0 0 0
@@MEM
MemTotal:        7900000 kB
MemFree:          300000 kB
MemAvailable:    3100000 kB
@@PID
4321
@@PSTAT
4321 (com.foo) S 1 4321 4321 0 -1 4194624 100 0 0 0 120 30 0 0 20 0 10 0 500 1000000 3000 0
@@GFX
Total frames rendered: 1000
Janky frames: 10 (1.00%)
@@PSS
         TOTAL    78901    60000      500        0   120000
@@BATT
  level: 78
  temperature: 310
  status: 2
"""


def _monitor(pkg="com.foo"):
    return svc.PerfMonitor("adb", "S1", 1.0, pkg)


def test_collect_builds_full_sample(monkeypatch):
    mon = _monitor()
    raws = [_RAW, _RAW.replace("cpu  1000 100 300 6000",
                               "cpu  1100 100 400 6400") \
                     .replace("1000\nJanky", "1060\nJanky") \
                     .replace("120 30", "160 30")]
    # 第一份只当基线（_collect 只消费第二份），迭代器直接从 raws[1] 起
    it = iter(raws[1:])
    monkeypatch.setattr(mon, "_run", lambda *a, **k: _Proc(next(it)))
    mon._prev = mon._diff_state(svc._split_sections(raws[0]))
    s = mon._collect()
    assert s["cpu"] == pytest.approx(33.3, abs=0.1)
    assert s["mem_used"] == pytest.approx(4687.5, abs=0.1)
    assert s["mem_total"] == pytest.approx(7714.8, abs=0.1)
    assert s["pss"] == pytest.approx(77.1, abs=0.05)
    assert s["batt"] == 78 and s["temp"] == pytest.approx(31.0)
    assert s["fps"] is not None and s["fps"] > 0
    assert s["app_cpu"] is not None


def test_collect_reports_adb_failure(monkeypatch):
    mon = _monitor()
    monkeypatch.setattr(mon, "_run",
                        lambda *a, **k: _Proc("", code=1, err="device offline"))
    assert mon._collect() is None
    assert "offline" in mon.error


def test_script_never_interpolates_unsafe_package():
    """包名会拼进设备端 shell：非法字符必须被整体丢弃，绝不能漏进去。"""
    bad = svc.PerfMonitor("adb", "S1", 1.0, "com.foo; rm -rf /sdcard")
    assert bad.pkg == "" and bad.auto_pkg is True
    assert "rm -rf" not in bad._script()
    good = svc.PerfMonitor("adb", "S1", 1.0, "com.tencent.kuwo")
    assert "dumpsys gfxinfo com.tencent.kuwo" in good._script()


def test_script_without_package_skips_gfxinfo():
    mon = svc.PerfMonitor("adb", "S1", 1.0, "")
    script = mon._script()
    assert "gfxinfo" not in script and "dumpsys battery" in script
    assert "pidof" not in script


def test_interval_is_clamped():
    assert svc.PerfMonitor("adb", "S1", 0, "").interval == pytest.approx(
        svc.MIN_INTERVAL)
    assert svc.PerfMonitor("adb", "S1", 999, "").interval == pytest.approx(
        svc.MAX_INTERVAL)


def test_snapshot_is_incremental_and_seq_monotonic(monkeypatch):
    mon = _monitor()
    monkeypatch.setattr(mon, "alive", lambda: True)
    for i in range(3):
        with mon._lock:
            mon._seq += 1
            mon._samples.append({"seq": mon._seq, "t": 1.0 + i, "cpu": 10.0 + i})
    full = mon.snapshot(0)
    assert [s["cpu"] for s in full["samples"]] == [10.0, 11.0, 12.0]
    tail = mon.snapshot(2)
    assert len(tail["samples"]) == 1 and tail["samples"][0]["cpu"] == 12.0
    assert tail["seq"] == 3
    # 乱传 since 不能抛
    assert mon.snapshot("oops")["seq"] == 3


def test_ring_buffer_drops_oldest(monkeypatch):
    monkeypatch.setattr(svc, "MAX_SAMPLES", 3)
    mon = _monitor()
    for i in range(6):
        with mon._lock:
            mon._seq += 1
            mon._samples.append({"seq": mon._seq, "cpu": i})
    got = mon.all_samples()
    assert len(got) == 3 and [s["cpu"] for s in got] == [3, 4, 5]
    assert mon.count() == 3


def test_start_fails_when_device_unreadable(monkeypatch):
    mon = _monitor()
    monkeypatch.setattr(mon, "_read_device_info", lambda: None)
    monkeypatch.setattr(mon, "_run", lambda *a, **k: _Proc("", code=1))
    ok, err = mon.start()
    assert ok is False and "设备" in err


# --------------------------------------------------------------------------- #
# 统计与报告
# --------------------------------------------------------------------------- #
def test_summarize():
    assert svc.summarize([]) is None
    s = svc.summarize([1, 2, 3, 4, 100])
    assert s["min"] == 1 and s["max"] == 100 and s["avg"] == 22.0
    assert s["n"] == 5 and s["p95"] == 100


def test_metric_summary_ignores_none():
    samples = [{"cpu": 10.0, "fps": None}, {"cpu": 20.0, "fps": 60.0}]
    ms = svc.metric_summary(samples)
    assert ms["cpu"]["avg"] == 15.0
    assert ms["fps"]["n"] == 1
    assert ms["pss"] is None


def _demo_samples(n=30):
    out = []
    for i in range(n):
        out.append({
            "seq": i + 1, "t": 1793200000.0 + i,
            "cpu": 20.0 + (i % 5), "app_cpu": 6.0, "mem_used": 4000.0 + i,
            "mem_total": 7714.8, "pss": None if i in (3, 4) else 300.0 + i,
            "fps": 59.0 if i % 7 else None, "jank": 2.0,
            "batt": 78, "temp": 31.0 + i * 0.1,
        })
    return out


def test_build_report_html_has_charts_and_summary():
    html = svc.build_report_html(_demo_samples(), {
        "serial": "A1", "model": "Pixel 7", "android": "13", "size": "1080x2340",
        "pkg": "com.foo", "started_at": "2026-10-29 07:00:00", "interval": 1.0})
    assert html.startswith("<!DOCTYPE html>")
    assert html.count("<svg") == len(svc.METRICS)      # 每个指标一张曲线
    assert "Pixel 7" in html and "com.foo" in html
    assert "P95" in html and "采样明细" in html
    assert "nan" not in html.lower()


def test_build_report_html_handles_empty_and_single():
    """空数据 / 单点都要能出报告（用户可能刚点开始就导出）。"""
    info = {"serial": "A1"}
    assert "<html" in svc.build_report_html([], info)
    assert "<html" in svc.build_report_html(_demo_samples(1), info)


def test_write_report_creates_html_and_csv(tmp_path):
    res = svc.write_report(_demo_samples(), {"serial": "A1:5555", "model": "M"},
                           str(tmp_path))
    assert os.path.isfile(res["html"]) and os.path.isfile(res["csv"])
    assert res["rows"] == 30
    # 无线序列号的冒号不能进文件名（Windows 非法），必须被净化
    assert ":" not in os.path.basename(res["html"])
    head = open(res["csv"], encoding="utf-8-sig").read().splitlines()
    assert head[0].startswith("time,cpu_percent")
    assert len(head) == 31


def test_write_csv_uses_bom_for_excel(tmp_path):
    p = str(tmp_path / "x.csv")
    svc.write_csv(_demo_samples(2), p)
    assert open(p, "rb").read(3) == b"\xef\xbb\xbf"


# --------------------------------------------------------------------------- #
# 卡顿率（区间值）
# --------------------------------------------------------------------------- #
def test_parse_gfxinfo_detail_extracts_janky_frames():
    text = ("Total frames rendered: 5432\n"
            "Janky frames: 123 (2.26%)\n"
            "50th percentile: 6ms\n")
    frames, janky, pct = svc.parse_gfxinfo_detail(text)
    assert frames == 5432 and janky == 123
    assert pct == pytest.approx(2.26)


def test_parse_gfxinfo_detail_partial_rom_output():
    """部分 ROM 只有累计帧数、没有 Janky 行：卡顿率必须是 None（断线）而不是 0。"""
    frames, janky, pct = svc.parse_gfxinfo_detail("Total frames rendered: 900\n")
    assert frames == 900 and janky is None and pct is None
    assert svc.parse_gfxinfo_detail("") == (None, None, None)


def test_jank_window_is_interval_based():
    """区间率只看**新增帧**：300 帧里新增 15 个卡顿帧 → 5%，与累计 1.2% 无关。"""
    assert svc.jank_window(100, 115, 300, 1.2) == pytest.approx(5.0)


def test_jank_window_falls_back_to_cumulative():
    # 没有新帧（界面静止）：累计值才是唯一有意义的口径
    assert svc.jank_window(10, 10, 2, 3.4) == pytest.approx(3.4)
    # 应用重启：janky 计数回退
    assert svc.jank_window(500, 3, 60, 0.5) == pytest.approx(0.5)
    # 缺卡顿帧数：原样返回累计百分比
    assert svc.jank_window(None, 3, 60, 0.5) == pytest.approx(0.5)
    assert svc.jank_window(None, None, None, None) is None
    # 极端：整段都在卡（防止算出 >100%）
    assert svc.jank_window(0, 50, 10, 0.0) == pytest.approx(100.0)


def test_collect_computes_window_jank(monkeypatch):
    """gfxinfo 帧 1000->1060、卡顿 10->13：区间卡顿率 3/60 = 5%，累计 1.00%。"""
    mon = _monitor()
    cur = (_RAW.replace("cpu  1000 100 300 6000", "cpu  1100 100 400 6400")
               .replace("Total frames rendered: 1000", "Total frames rendered: 1060")
               .replace("Janky frames: 10 (1.00%)", "Janky frames: 13 (1.23%)"))
    monkeypatch.setattr(mon, "_run", lambda *a, **k: _Proc(cur))
    mon._prev = mon._diff_state(svc._split_sections(_RAW))
    s = mon._collect()
    assert s["jank"] == pytest.approx(5.0)
    assert s["jank_cum"] == pytest.approx(1.23)


def test_metrics_expose_jank_with_percent_unit():
    keys = [k for k, _t, _u, _m in svc.METRICS]
    assert "jank" in keys
    meta = dict((k, (u, m)) for k, _t, u, m in svc.METRICS)["jank"]
    # 单位是百分比，但**不做 0~100 固定量程**：真实值常年 1~15%，
    # 按 100 画会全压在底部一条线，看不出波动（曲线自适应 + 纳入阈值线）
    assert meta == ("%", None)


def test_report_and_csv_carry_jank(tmp_path):
    samples = _demo_samples()
    html = svc.build_report_html(samples, {"serial": "A1"})
    assert "卡顿率" in html
    p = str(tmp_path / "j.csv")
    svc.write_csv(samples, p)
    head = open(p, encoding="utf-8-sig").read().splitlines()[0]
    assert "jank_percent" in head and "jank_cumulative_percent" in head


# --------------------------------------------------------------------------- #
# 阈值告警
# --------------------------------------------------------------------------- #
def _alert_samples():
    out = []
    for i in range(20):
        out.append({
            "t": 1793200000.0 + i,
            "cpu": 90.0 if i < 5 else 30.0,
            "fps": 30.0 if i < 6 else 58.0,
            "jank": 20.0 if i < 3 else 1.0,
            "temp": 44.0 if i < 2 else 33.0,
        })
    return out


def test_evaluate_alerts_counts_and_ranks_by_ratio():
    alerts = svc.evaluate_alerts(_alert_samples())
    assert [a["key"] for a in alerts] == ["fps", "cpu", "jank", "temp"]
    fps = alerts[0]
    assert fps["count"] == 6 and fps["total"] == 20
    assert fps["ratio"] == pytest.approx(30.0)
    assert fps["worst"] == pytest.approx(30.0)
    assert fps["level"] == "crit"          # 30% ≥ 25% 阈值 → 严重
    assert fps["longest_s"] == pytest.approx(5.0)
    assert "帧率" in fps["rule"] and "<" in fps["rule"]
    # 只有 10% 的温度属于 warn
    assert alerts[-1]["key"] == "temp" and alerts[-1]["level"] == "warn"


def test_evaluate_alerts_clean_and_empty():
    clean = [{"t": i, "fps": 60.0, "jank": 1.0, "cpu": 20.0, "temp": 33.0}
             for i in range(5)]
    assert svc.evaluate_alerts(clean) == []
    assert svc.evaluate_alerts([]) == []
    # 完全没有该指标的数据 → 不误报
    assert svc.evaluate_alerts([{"t": 1.0, "cpu": 10.0}]) == []


def test_evaluate_alerts_single_point_gets_duration():
    """单点超标时长不能显示 0 秒：用平均采样间隔兜底。"""
    samples = [{"t": 100.0, "fps": 60.0}, {"t": 101.0, "fps": 30.0},
               {"t": 102.0, "fps": 60.0}]
    a = svc.evaluate_alerts(samples)
    assert a[0]["count"] == 1
    assert a[0]["longest_s"] == pytest.approx(1.0)


def test_evaluate_alerts_accepts_custom_thresholds():
    samples = [{"t": 1.0, "fps": 50.0}, {"t": 2.0, "fps": 50.0}]
    assert svc.evaluate_alerts(samples) == []
    custom = {"fps": {"min": 55.0}}
    got = svc.evaluate_alerts(samples, custom)
    assert len(got) == 1 and got[0]["ratio"] == pytest.approx(100.0)


def test_report_alert_card_escapes_rule_and_marks_level():
    html = svc.build_report_html(_alert_samples(), {"serial": "A1"})
    assert "阈值告警" in html
    assert "帧率 FPS &lt; 45" in html        # 尖括号必须转义，否则被当标签
    assert '<tr class="crit">' in html
    assert "判定标准" in html


def test_report_without_alerts_still_shows_conclusion():
    html = svc.build_report_html(_demo_samples(), {"serial": "A1"})
    assert "阈值告警" in html
    assert "未触发任何阈值告警" in html


# --------------------------------------------------------------------------- #
# 可配置阈值（表达式解析 / 回写 / 界面元数据）
# --------------------------------------------------------------------------- #
def test_default_threshold_expr_roundtrips():
    """内置基线 -> 表达式 -> 解析回来必须完全一致（否则「恢复默认」会悄悄改值）。"""
    expr = svc.default_threshold_expr()
    assert expr == "fps<45,jank>8,temp>42,cpu>85"
    th, errs = svc.parse_thresholds(expr)
    assert errs == []
    assert th == svc.DEFAULT_THRESHOLDS
    assert svc.format_thresholds(th) == expr


def test_parse_thresholds_empty_means_builtin():
    th, errs = svc.parse_thresholds("")
    assert th == svc.DEFAULT_THRESHOLDS and errs == []
    th, errs = svc.parse_thresholds(None)
    assert th == svc.DEFAULT_THRESHOLDS and errs == []


def test_parse_thresholds_off_disables_all():
    """「off」= 一条都不要。空串不能表达这个语义（空串 = 用内置基线）。"""
    assert svc.parse_thresholds("off") == ({}, [])
    assert svc.parse_thresholds(" OFF ") == ({}, [])
    assert svc.parse_thresholds("none") == ({}, [])


def test_parse_thresholds_is_overriding_not_merging():
    """表达式里没提到的指标就不告警：删掉一段 = 关掉这条，与取消勾选一一对应。"""
    th, errs = svc.parse_thresholds("fps<50")
    assert th == {"fps": {"min": 50.0}} and errs == []
    assert svc.format_thresholds(th) == "fps<50"


def test_parse_thresholds_rejects_wrong_direction():
    """FPS 只能「低于即告警」：写成 fps>50 是笔误，不能当合法阈值静默接受。"""
    th, errs = svc.parse_thresholds("fps>50,jank>8")
    assert "fps" not in th and th.get("jank") == {"max": 8.0}
    assert errs and "只能" in errs[0]


def test_parse_thresholds_rejects_unknown_and_out_of_range():
    th, errs = svc.parse_thresholds("bogus<1")
    assert th == {} and errs and "未知指标" in errs[0]
    _th, errs = svc.parse_thresholds("jank>250")
    assert errs and "合理范围" in errs[0]


def test_parse_thresholds_strict_falls_back_to_builtin():
    """用户刚提交的表达式含非法段 -> 整条作废并回落内置，不能「删一半生效一半」。"""
    th, errs = svc.parse_thresholds("fps<50,wat<1", strict=True)
    assert th == svc.DEFAULT_THRESHOLDS
    assert errs and "未知指标" in errs[0]


def test_parse_thresholds_reports_garbled_segment():
    """连 `key<数字` 形状都不对时必须有错误：errors 为空界面就会当成功保存。"""
    th, errs = svc.parse_thresholds("fps<50,乱写<1")
    assert th == {"fps": {"min": 50.0}}     # 有效段落保留（读历史配置时的抢救）
    assert errs and "无法识别" in errs[0]


def test_parse_thresholds_non_strict_keeps_valid_parts():
    """读历史配置（strict=False）时能救则救：有效段落保留，错误照报。"""
    th, errs = svc.parse_thresholds("fps<50,wat<1")
    assert th == {"fps": {"min": 50.0}} and errs


def test_threshold_items_expose_ui_metadata():
    """界面四行的方向 / 单位 / 理由 / 范围都由后端给出，前端不另抄一份。"""
    items = svc.threshold_items()
    assert [i["key"] for i in items] == ["fps", "jank", "temp", "cpu"]
    fps = items[0]
    assert fps["dir"] == "min" and fps["unit"] == "FPS"
    assert fps["value"] == 45.0 and fps["default"] == 45.0
    assert fps["min"] <= fps["value"] <= fps["max"]
    assert fps["hint"]
    # 关掉某项后 value 为 None，界面靠它显示成未启用
    off = svc.threshold_items({"fps": {"min": 50.0}})
    assert off[0]["value"] == 50.0 and off[1]["value"] is None


# --------------------------------------------------------------------------- #
# 报告：超标色带 + 自定义阈值
# --------------------------------------------------------------------------- #
def _band_samples():
    """FPS：60,60,30,30,60 —— 中间两点跌破 45，应画出一条色带。"""
    t = 1793200000
    out = []
    for i, fps in enumerate([60, 60, 30, 30, 60]):
        out.append({"t": t + i, "cpu": 20.0, "mem_used": 3000.0, "pss": 300.0,
                    "fps": float(fps), "jank": 2.0, "batt": 70.0, "temp": 33.0})
    return out


def test_report_chart_draws_band_for_bad_range():
    html = svc.build_report_html(_band_samples(), {"serial": "A1"})
    assert 'fill="#ff5f6b" opacity=".12"' in html      # 色带
    assert "stroke-dasharray" in html                  # 阈值虚线
    assert "≥ 45 FPS" in html                          # 行尾标签（min 方向用 ≥）


def test_report_chart_band_only_when_below_threshold():
    """全程 60 FPS 的报告不应该出现任何色带 —— 全都达标却满屏红是最坏的误报。"""
    t = 1793200000
    samples = [{"t": t + i, "fps": 60.0} for i in range(5)]
    html = svc.build_report_html(samples, {"serial": "A1"})
    assert 'opacity=".12"' not in html


def test_report_accepts_custom_thresholds():
    """用户把 FPS 卡到 58：同一份 60 FPS 数据就变成「不达标」，报告口径必须跟着变。"""
    t = 1793200000
    samples = [{"t": t + i, "fps": 56.0} for i in range(5)]
    assert 'opacity=".12"' not in svc.build_report_html(samples, {})
    html = svc.build_report_html(samples, {}, {"fps": {"min": 58.0}})
    assert 'opacity=".12"' in html
    assert "帧率 FPS &lt; 58" in html


def test_report_thresholds_off_shows_disabled_state():
    html = svc.build_report_html(_band_samples(), {}, {})
    assert "本次采样未启用阈值告警" in html
    assert 'opacity=".12"' not in html


def test_write_report_forwards_thresholds(tmp_path):
    p = svc.write_report(_band_samples(), {"serial": "A1", "interval": 1.0},
                         str(tmp_path), {"fps": {"min": 58.0}})
    body = open(p["html"], encoding="utf-8").read()
    assert "帧率 FPS &lt; 58" in body


# --------------------------------------------------------------------------- #
# 多设备对比报告
# --------------------------------------------------------------------------- #
def _dev_samples(fps, jank=2.0, temp=33.0, cpu=20.0, n=5, t0=1793200000):
    return [{"t": t0 + i, "cpu": cpu, "mem_used": 3000.0, "pss": 300.0,
             "fps": float(fps), "jank": jank, "batt": 70.0, "temp": temp}
            for i in range(n)]


def _entries():
    return [
        {"serial": "S1", "label": "Pixel 7 · 0001",
         "info": {"serial": "S1", "model": "Pixel 7", "android": "13",
                  "size": "1080x2400", "pkg": "com.demo"},
         "samples": _dev_samples(58, jank=2.0, temp=33.0), "interval": 1.0},
        {"serial": "S2", "label": "Pixel 7 · 0002",
         "info": {"serial": "S2", "model": "Pixel 7", "android": "13",
                  "size": "1080x2400", "pkg": "com.demo"},
         "samples": _dev_samples(30, jank=20.0, temp=45.0), "interval": 1.0},
    ]


def test_compare_report_needs_two_devices():
    assert svc.build_compare_html([]) == ""
    assert svc.build_compare_html(_entries()[:1]) == ""


def test_compare_report_has_devices_matrix_and_charts():
    html = svc.build_compare_html(_entries())
    assert "多设备对比性能报告" in html
    assert "Pixel 7 · 0001" in html and "Pixel 7 · 0002" in html
    assert "指标对比" in html and "对比设备" in html
    # 七项指标各一张多线图 + 七条图例（两台设备 → 每图两个图例项）
    assert html.count('class="legend"') == len(svc.METRICS)
    assert html.count('class="lg"') == 2 * len(svc.METRICS)


def test_compare_matrix_marks_worst_device():
    """帧率越低越差：S2（30 FPS）应被标红；两台相同的指标（CPU 都是 20）不标。"""
    html = svc.build_compare_html(_entries())
    rows = [r for r in html.split("<tr>") if "帧率 (FPS)</td>" in r]
    assert len(rows) == 1
    assert '<td class="worst">30' in rows[0]
    cpu_row = [r for r in html.split("<tr>") if ">CPU (" in r][0]
    assert "worst" not in cpu_row          # 并列最差不标红（避免假结论）


def test_compare_alert_table_flags_bad_device():
    html = svc.build_compare_html(_entries())
    assert "阈值告警" in html
    assert "帧率 FPS &lt; 45" in html        # 表头写清判定规则
    assert 'class="crit"' in html or 'class="warn"' in html
    assert "达标" in html                    # S1 的帧率/温度/卡顿都达标


def test_compare_report_escapes_device_label():
    """设备型号来自设备端，可能带尖括号；拼进 HTML 必须转义。"""
    e = _entries()
    e[1]["label"] = '<img src=x onerror=alert(1)>'
    html = svc.build_compare_html(e)
    assert "<img src=x" not in html and "&lt;img" in html


def test_compare_report_without_thresholds():
    html = svc.build_compare_html(_entries(), {})
    assert "本次采样未启用阈值告警" in html
    assert "stroke-dasharray" not in html.split("阈值告警")[0]


def test_write_compare_report_creates_file(tmp_path):
    res = svc.write_compare_report(_entries(), str(tmp_path))
    assert res["devices"] == 2 and os.path.exists(res["html"])
    assert "perf_compare_2_dev_" in os.path.basename(res["html"])
    assert svc.write_compare_report(_entries()[:1], str(tmp_path)) == {}


# --------------------------------------------------------------------------- #
# 目标应用模式：跟随前台 / 锁定包名 / 全系统
# --------------------------------------------------------------------------- #
_SYS_RAW = """@@STAT
cpu  1100 100 400 6400 200 0 50 0 0 0
@@MEM
MemTotal:        7900000 kB
MemFree:          300000 kB
MemAvailable:    3100000 kB
@@BATT
  level: 78
  temperature: 310
  status: 2
"""


def test_system_mode_is_not_a_package():
    """`__system__` 是模式哨兵，不是包名：不能留着当 self.pkg 拼进设备端命令。"""
    mon = svc.PerfMonitor("adb", "S1", 1.0, svc.SYSTEM_PKG)
    assert mon.system_only is True
    assert mon.pkg == "" and mon.auto_pkg is False
    assert mon.mode == "system" and mon.info["pkg_mode"] == "system"
    script = mon._script()
    assert svc.SYSTEM_PKG not in script
    # 全系统不绑进程：脚本里不该出现按包名取数的 dumpsys / pidof
    # （/proc/meminfo 是整机内存，不在此列）
    for bad in ("dumpsys gfxinfo", "dumpsys meminfo", "pidof"):
        assert bad not in script


def test_auto_and_manual_modes():
    auto = svc.PerfMonitor("adb", "S1", 1.0, "")
    assert auto.mode == "auto" and auto.auto_pkg is True and auto.pkg == ""
    manual = svc.PerfMonitor("adb", "S1", 1.0, "com.foo")
    assert manual.mode == "manual" and manual.auto_pkg is False


def test_diff_state_exposes_jank_cum_and_focus():
    """_diff_state 现在一次性把 GFX 的累计卡顿率(jank_cum) 与（跟随前台时的）
    前台包名(focus) 一并返回，_collect 直接复用，不再重复解析 @@GFX 段。"""
    mon = _monitor()
    cur = mon._diff_state(svc._split_sections(_RAW))
    assert cur["jank_cum"] == pytest.approx(1.00)
    # manual 模式不解析 focus（脚本里压根没有 @@FOCUS 段）
    assert cur["focus"] == ""

    auto = svc.PerfMonitor("adb", "S1", 1.0, "")
    raw = _RAW + "@@FOCUS\n  mCurrentFocus=Window{8f u0 com.spotify.music/Player}\n"
    cur2 = auto._diff_state(svc._split_sections(raw))
    assert cur2["focus"] == "com.spotify.music"


def test_auto_mode_script_includes_focus_section():
    """跟随前台模式把前台包名探测并到同一段脚本（@@FOCUS），不再单独起 adb。"""
    auto = svc.PerfMonitor("adb", "S1", 1.0, "")
    script = auto._script()
    assert "FOCUS" in script and "dumpsys window" in script
    # 但脚本里没有按包名取数的命令（此时还没拿到前台包名）
    for bad in ("dumpsys gfxinfo", "dumpsys meminfo", "pidof"):
        assert bad not in script


def test_auto_mode_collect_applies_focus_pkg(monkeypatch):
    """_collect 解析 @@FOCUS 后把前台包名写回 self.pkg / info.pkg，
    后续采样才会带上 GFX / PSS / PID 段。"""
    auto = svc.PerfMonitor("adb", "S1", 1.0, "")
    raw = (_RAW
           + "@@FOCUS\n  mCurrentFocus=Window{8f u0 com.spotify.music/Player}\n")
    monkeypatch.setattr(auto, "_run", lambda *a, **k: _Proc(raw))
    assert auto.pkg == ""
    auto._collect()
    assert auto.pkg == "com.spotify.music"
    assert auto.info["pkg"] == "com.spotify.music"
    # 下一帧脚本已经带上该包名 -> 会采应用级指标
    assert "dumpsys gfxinfo com.spotify.music" in auto._script()


def test_collect_reuses_gfx_parse_no_double_work(monkeypatch):
    """_collect 直接复用 _diff_state 解析出的 frames/janky/jank_cum，
    不得再调用 parse_gfxinfo_detail（用计数器确认只解析一次）。"""
    import backend.perf_service as svc2
    calls = {"n": 0}
    orig = svc2.parse_gfxinfo_detail

    def spy(text):
        calls["n"] += 1
        return orig(text)

    monkeypatch.setattr(svc2, "parse_gfxinfo_detail", spy)
    mon = _monitor()
    raws = [_RAW, _RAW.replace("cpu  1000 100 300 6000",
                               "cpu  1100 100 400 6400") \
                     .replace("1000\nJanky", "1060\nJanky") \
                     .replace("120 30", "160 30")]
    it = iter(raws[1:])
    monkeypatch.setattr(mon, "_run", lambda *a, **k: _Proc(next(it)))
    mon._prev = mon._diff_state(svc._split_sections(raws[0]))
    mon._collect()
    # 基线 1 次 + 采样 1 次 = 2 次；若 _collect 再解析一次就会变成 3 次
    assert calls["n"] == 2


def test_system_mode_skips_focus_probe(monkeypatch):
    """全系统模式不探前台应用：脚本里不带 @@FOCUS，_collect 也不会改写 pkg。"""
    mon = svc.PerfMonitor("adb", "S1", 1.0, svc.SYSTEM_PKG)
    monkeypatch.setattr(mon, "_run", lambda *a, **k: _Proc(_SYS_RAW))
    script = mon._script()
    assert "FOCUS" not in script and "dumpsys window" not in script
    mon._collect()
    assert mon.pkg == "" and mon.info["pkg"] == ""


def test_system_mode_collect_leaves_app_metrics_empty(monkeypatch):
    """应用级指标（PSS / 帧率 / 卡顿）在全系统模式下必须是 None，
    不能拿整机数字冒充，否则报告里会出现一条语义错误的曲线。"""
    mon = svc.PerfMonitor("adb", "S1", 1.0, svc.SYSTEM_PKG)
    base = _SYS_RAW.replace("cpu  1100 100 400 6400", "cpu  1000 100 300 6000")
    mon._prev = mon._diff_state(svc._split_sections(base))
    monkeypatch.setattr(mon, "_run", lambda *a, **k: _Proc(_SYS_RAW))
    s = mon._collect()
    assert s["cpu"] == pytest.approx(33.3, abs=0.3)
    assert s["mem_used"] is not None
    assert s["pss"] is None and s["fps"] is None and s["jank"] is None
    assert s["batt"] == 78


def test_pkg_display_covers_all_modes():
    assert svc.pkg_display({"pkg": "", "pkg_mode": "system"}) == "全系统（仅整机指标）"
    assert svc.pkg_display({"pkg": "com.foo", "pkg_mode": "auto"}) == "com.foo（跟随前台）"
    assert svc.pkg_display({"pkg": "com.foo", "pkg_mode": "manual"}) == "com.foo"
    assert "跟随前台" in svc.pkg_display({"pkg": "", "pkg_mode": "auto"})
    # 老数据（升级前采的样本）没有 pkg_mode：有包名就显示包名，没有就说整机
    assert svc.pkg_display({"pkg": "com.old"}) == "com.old"
    assert svc.pkg_display({}) == "（整机）"


def test_report_shows_system_mode_label():
    """报告正文「监控应用」一行要能看出这份数据是全系统采的。"""
    entries = _entries()
    for e in entries:
        e["info"] = dict(e["info"], pkg="", pkg_mode="system")
    html = svc.build_compare_html(entries)
    assert "全系统（仅整机指标）" in html


# --------------------------------------------------------------------------- #
# 已安装应用列表（下拉框数据源）
# --------------------------------------------------------------------------- #
def test_parse_package_list_dedupes_and_sorts():
    text = ("package:com.b.app\npackage:com.a.app\npackage:com.a.app\n\n"
            "GCONSOLE: 1 package\n")
    assert svc.parse_package_list(text) == ["com.a.app", "com.b.app"]


def test_parse_package_list_rejects_unsafe_names():
    """包名最终会拼进设备端 shell，带 ; / 空格 的行必须整条丢掉。"""
    text = "package:com.foo;reboot\npackage:com.ok.app\npackage:com a\n"
    assert svc.parse_package_list(text) == ["com.ok.app"]


def test_list_packages_splits_third_party_and_system(monkeypatch):
    out = ("@@TP\npackage:com.tencent.kuwo\npackage:com.android.chrome\n"
           "@@ALL\npackage:com.tencent.kuwo\npackage:com.android.chrome\n"
           "package:com.android.settings\n")
    seen = {}

    def fake_run(args, **kw):
        seen["args"] = args
        return _Proc(out)

    monkeypatch.setattr(svc.subprocess, "run", fake_run)
    r = svc.list_packages("adb", "S1")
    assert r["ok"] is True
    assert r["third"] == ["com.android.chrome", "com.tencent.kuwo"]
    assert r["system"] == ["com.android.settings"]
    assert r["total"] == 3
    assert seen["args"][:3] == ["adb", "-s", "S1"]
    # 一次 adb 调用同时取两份清单：切「含系统应用」时不用再走一次设备
    assert seen["args"].count("shell") == 1


def test_list_packages_reports_adb_failure(monkeypatch):
    monkeypatch.setattr(svc.subprocess, "run",
                        lambda a, **k: _Proc("", code=1, err="device offline"))
    r = svc.list_packages("adb", "S1")
    assert r["ok"] is False and "offline" in r["reason"]


def test_list_packages_empty_device_is_failure(monkeypatch):
    """空列表 ≠ 成功：设备没授权时 pm 也会「正常返回空」，必须当成失败报出来。"""
    monkeypatch.setattr(svc.subprocess, "run", lambda a, **k: _Proc(""))
    r = svc.list_packages("adb", "S1")
    assert r["ok"] is False and "应用" in r["reason"]
