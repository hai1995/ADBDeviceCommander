# -*- coding: utf-8 -*-
"""core.diag 的单测：解析 + 打包 + 单段失败不影响整包。

重点是「真实 ROM 的怪异输出」：
  * ps 表头列序不同 / 干脆没表头 / 老设备不支持 ps -A；
  * 老设备 logcat 不支持 -t（必须回退全量 dump 再截尾部）；
  * /data/anr 无权限（只在该文件里写一行说明，整包照常产出）。
这些分支在产品里都是「用户机器上才会遇到」的路径，靠假 runner 复现。
"""
import json
import os
import zipfile

import pytest

from core import diag, devinfo

PS_NEW = (
    "USER           PID  PPID     VSZ    RSS WCHAN            ADDR S NAME\n"
    "root             1     0 1234567   9000 0                   0 S init\n"
    "u0_a123        1234   567 2345678 222222 0                   0 S com.big.app\n"
    "u0_a45         4321   567 3456789  45000 0                   0 S com.small.app\n"
)
PS_OLD = (
    "  PID USER     TIME     RSS NAME\n"
    "  100 root     0:01:02  8000 system_server\n"
)

MEMINFO_SAMPLE = (
    "Applications Memory Usage (in Kilobytes):\n"
    "Uptime: 123456789 Realtime: 123456789\n"
    "\n"
    "Total PSS by process:\n"
    "   234567 kB: com.big.app (pid 1234) (foreground)\n"
    "    65432 kB: com.small.app (pid 4321)\n"
    "    12345 kB: system (pid 567)\n"
    "Total PSS by OOM adjustment:\n"
    "   234567 kB: Foreground\n"
    "    65432 kB: Visible\n"
    "Total PSS by category:\n"
    "   120000 kB: Native\n"
    "    80000 kB: Dalvik\n"
    "Total RAM: 8000000 kB\n"
    " Free RAM: 2000000 kB\n"
    " Used RAM: 5000000 kB\n"
    " Lost RAM: 100000 kB\n"
)

NET_IP_SAMPLE = (
    "1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN\n"
    "    inet 127.0.0.1/8 scope host lo\n"
    "2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 state UP\n"
    "    inet 192.168.1.5/24 brd 192.168.1.255 scope global eth0\n"
    "3: wlan0: <BROADCAST,MULTICAST> mtu 1500 state DOWN\n"
)

NETCFG_SAMPLE = (
    "lo       UP      127.0.0.1/8       0x00000049 00:00:00:00:00:00\n"
    "eth0     UP      192.168.1.5/24    0x00001043 00:11:22:33:44:55\n"
    "wlan0    DOWN    0.0.0.0/0         0x00001002 aa:bb:cc:dd:ee:ff\n"
)


def test_parse_net_from_ip_addr():
    rows = diag.parse_net(NET_IP_SAMPLE)
    d = {n: (up, ip) for n, up, ip in rows}
    assert d["lo"] == (True, "127.0.0.1")
    assert d["eth0"] == (True, "192.168.1.5")
    # wlan0 接口存在但 DOWN 且没有 inet 行，仍要登记（无 IP 记为空）
    assert d["wlan0"] == (False, "")


def test_parse_net_falls_back_to_netcfg():
    """只有 netcfg 输出（老 ROM 无 ip addr）时也能解析。"""
    rows = diag.parse_net("__NETCFG__\n" + NETCFG_SAMPLE)
    d = {n: (up, ip) for n, up, ip in rows}
    assert d["eth0"] == (True, "192.168.1.5")
    assert d["wlan0"] == (False, "")          # 0.0.0.0 当作无 IP


def test_parse_net_empty():
    assert diag.parse_net("") == []
    assert diag.parse_net("no interfaces here") == []


def test_net_report_lists_up_down_and_ip():
    txt = diag.net_report(NET_IP_SAMPLE)
    assert "== 网络接口（状态 / IPv4）==" in txt
    assert "eth0" in txt and "192.168.1.5" in txt
    assert "wlan0" in txt
    assert "DOWN" in txt                       # wlan0 状态要体现
    assert "（无 IP）" in txt                  # wlan0 无 IP
    assert "== 原始输出 ==" in txt


def test_net_report_fallback_when_nothing_parsed():
    txt = diag.net_report("garbage")
    assert "未能解析出网络接口" in txt


def test_parse_meminfo_extracts_by_process_only():
    """只解析 by process 段：by OOM / by category 的 Native/Dalvik/Foreground
    不能被错当成进程。"""
    rows = diag.parse_meminfo(MEMINFO_SAMPLE)
    names = [r[1] for r in rows]
    assert "com.big.app" in names
    assert "com.small.app" in names
    assert "system" in names
    assert "Native" not in names
    assert "Dalvik" not in names
    assert "Foreground" not in names
    # 按 PSS 降序
    assert [r[0] for r in rows] == [234567, 65432, 12345]


def test_parse_meminfo_pulls_pid_and_strips_suffix():
    rows = diag.parse_meminfo(MEMINFO_SAMPLE)
    big = [r for r in rows if r[1] == "com.big.app"][0]
    assert big[2] == 1234
    small = [r for r in rows if r[1] == "com.small.app"][0]
    assert small[2] == 4321


def test_parse_meminfo_empty_and_no_marker():
    assert diag.parse_meminfo("") == []
    assert diag.parse_meminfo("no meminfo markers here") == []


def test_meminfo_report_has_top_n_and_summary():
    txt = diag.meminfo_report(MEMINFO_SAMPLE, limit=2)
    assert "内存分页明细 TOP 2" in txt
    assert "com.big.app" in txt and "com.small.app" in txt
    head, _, tail = txt.partition("== dumpsys meminfo 内存汇总 ==")
    assert "system" not in head          # TOP 2 明细不含第三名
    assert "system" in tail              # 但汇总段保留完整 by process
    assert "== dumpsys meminfo 内存汇总 ==" in txt
    assert "Total RAM: 8000000 kB" in txt   # 汇总段保留全局画像
    assert "Native" in txt                  # by category 也进了汇总段


def test_meminfo_report_falls_back_when_no_block():
    txt = diag.meminfo_report("nothing useful")
    assert "未能从 meminfo" in txt or "无汇总段" in txt


def _props_block():
    return (
        "@@PROP\n"
        "[ro.product.manufacturer]: [Google]\n"
        "[ro.product.model]: [Pixel 7]\n"
        "[ro.build.version.release]: [14]\n"
        "[ro.build.version.sdk]: [34]\n"
        "[ro.product.cpu.abi]: [arm64-v8a]\n"
        "@@WM\nPhysical size: 1080x2400\nPhysical density: 420\n"
        "@@BATT\n  level: 88\n  status: 2\n  temperature: 305\n"
        "@@DF\n/dev/block/dm-0 1000000 500000 500000 50% /data\n"
        "@@MEM\nMemTotal: 8000000 kB\nMemAvailable: 2000000 kB\n"
        "@@UP\n12345.67 890.12\n"
    )


def make_runner(ps=PS_NEW, logcat_supports_t=True, anr_ok=True,
                apps3="package:a.b\npackage:c.d\n",
                apps_all="package:a.b\npackage:c.d\npackage:android\n"):
    """造一个假 adb runner：按参数返回各种真实设备的输出。"""
    calls = []

    def runner(args, timeout):
        calls.append(list(args))
        a = " ".join(args)
        if "getprop" in a:
            return 0, _props_block(), ""
        if a.startswith("shell ps"):
            return (0, ps, "") if ps else (1, "", "unknown option -A")
        if a.startswith("shell pm list packages -3"):
            return 0, apps3, ""
        if a.startswith("shell pm list packages"):
            return 0, apps_all, ""
        if a.startswith("shell dumpsys meminfo"):
            return 0, MEMINFO_SAMPLE, ""
        if "ip addr" in a or "__NETCFG__" in a:
            return 0, NET_IP_SAMPLE, ""
        if a.startswith("shell dumpsys"):
            if not anr_ok:
                return 0, "", "Permission denied"
            return 0, "mCurrentFocus=Window{1 u0 com.big.app/.Main}\n", ""
        if a.startswith("logcat"):
            if "-t" in a:
                if not logcat_supports_t:
                    return 1, "", "logcat: unknown option -t"
                return 0, "".join(
                    "08-29 10:00:%02d.000  1 1 I tag: line%d\n" % (i, i)
                    for i in range(5)), ""
            return 0, "".join(
                "08-29 09:00:%02d.000  1 1 I old: old%d\n" % (i, i)
                for i in range(5)), ""
        return 0, "-- lastanr --\n(null)\n", ""

    runner.calls = calls
    return runner


# ---------------------------------------------------------------------------
# 纯解析
# ---------------------------------------------------------------------------
def test_clamp_lines():
    assert diag.clamp_lines(None) == diag.DEFAULT_LOGCAT_LINES
    assert diag.clamp_lines("abc") == diag.DEFAULT_LOGCAT_LINES
    assert diag.clamp_lines(0) == diag.DEFAULT_LOGCAT_LINES
    assert diag.clamp_lines(-5) == diag.DEFAULT_LOGCAT_LINES
    assert diag.clamp_lines("3000") == 3000
    assert diag.clamp_lines(10 ** 9) == diag.MAX_LOGCAT_LINES


def test_parse_ps_new_header():
    rows, cols = diag.parse_ps(PS_NEW)
    assert cols.get("pid") == 1 and cols.get("rss") == 4
    assert (1234, 222222, "com.big.app") in rows
    assert len(rows) == 3


def test_parse_ps_old_header():
    """老 ROM 的表头是 PID USER TIME RSS NAME：RSS 在第 4 列而不是第 5 列。"""
    rows, _cols = diag.parse_ps(PS_OLD)
    assert rows and rows[0][0] == 100
    assert rows[0][1] == 8000
    assert rows[0][2] == "system_server"


def test_parse_ps_no_header():
    """无表头的裁剪输出也不能整段丢掉。"""
    rows, _cols = diag.parse_ps("  555  0.5  120000  com.x\n")
    assert rows and rows[0][0] == 555


def test_parse_ps_empty_and_garbage():
    assert diag.parse_ps("") == ([], {})
    rows, _ = diag.parse_ps("not a ps output at all\n")
    assert rows == []


def test_top_memory_sorts_desc_and_limits():
    top = diag.top_memory(PS_NEW, limit=2)
    assert [r[2] for r in top] == ["com.big.app", "com.small.app"]
    assert len(diag.top_memory(PS_NEW, limit=99)) == 3


def test_process_report_keeps_raw():
    txt = diag.process_report(PS_NEW)
    assert "内存占用 TOP 3" in txt
    assert "com.big.app" in txt
    # 原始表必须完整保留（开发常要自己 grep 某个进程）
    assert "WCHAN" in txt


def test_summarize_packages_counts():
    txt = diag.summarize_packages("package:a.b\n", "package:a.b\npackage:sys\n")
    assert "第三方应用：1 个" in txt
    assert "系统应用：1 个" in txt
    assert "全部应用：2 个" in txt
    assert "a.b" in txt


def test_summarize_packages_lists_system_apps():
    """系统应用包名也要列出来：车机问题常出在预置应用，只给第三方查不到。"""
    txt = diag.summarize_packages(
        "package:a.b\n",
        "package:a.b\npackage:sys.one\npackage:sys.two\n")
    assert "== 系统应用包名 ==" in txt
    assert "sys.one" in txt and "sys.two" in txt
    # 系统清单是「全量 − 第三方」，第三方不重复出现
    sys_sec = txt.split("== 系统应用包名 ==", 1)[1]
    assert "a.b" not in sys_sec


def test_summarize_packages_without_all_output():
    """只拿到 -3 输出（全量那条失败）时不算失败，也不凭空编系统清单。"""
    txt = diag.summarize_packages("package:a.b\n", "")
    assert "第三方应用：1 个" in txt
    assert "系统应用" not in txt
    assert "全部应用" not in txt
    assert "a.b" in txt


# ---------------------------------------------------------------------------
# 端到端打包
# ---------------------------------------------------------------------------
def test_collect_produces_zip_with_all_parts(tmp_path):
    z, man, err = diag.collect("adb", "SERIAL1", str(tmp_path),
                               runner=make_runner())
    assert err is None and z and os.path.exists(z)
    with zipfile.ZipFile(z) as zf:
        names = zf.namelist()
        assert names == [diag.F_DEVICE, diag.F_PROPS, diag.F_LOGCAT,
                         diag.F_PROCESS, diag.F_APPS, diag.F_ANR, diag.F_NET,
                         diag.F_MEMINFO, diag.F_META]
        meta = json.loads(zf.read(diag.F_META).decode("utf-8"))
        assert meta["serial"] == "SERIAL1"
        assert meta["device"]["model"] == "Pixel 7"
        assert meta["device"]["android"] == "14"
        assert all(p["ok"] for p in meta["parts"])
        assert "Pixel 7" in zf.read(diag.F_DEVICE).decode("utf-8")
        assert "ro.product.model" in zf.read(diag.F_PROPS).decode("utf-8")
        assert "com.big.app" in zf.read(diag.F_PROCESS).decode("utf-8")
        assert "a.b" in zf.read(diag.F_APPS).decode("utf-8")
        assert "com.big.app" in zf.read(diag.F_MEMINFO).decode("utf-8")
        assert "Total RAM" in zf.read(diag.F_MEMINFO).decode("utf-8")
        assert "eth0" in zf.read(diag.F_NET).decode("utf-8")
        assert "192.168.1.5" in zf.read(diag.F_NET).decode("utf-8")


def test_collect_without_logcat_omits_file(tmp_path):
    z, man, err = diag.collect("adb", "S1", str(tmp_path),
                               with_logcat=False, runner=make_runner())
    assert err is None
    with zipfile.ZipFile(z) as zf:
        assert diag.F_LOGCAT not in zf.namelist()
    assert man["logcat_lines"] == 0


def test_collect_logcat_t_fallback(tmp_path):
    """老设备不支持 `logcat -t`：回退全量 dump 并在本地截尾部。"""
    runner = make_runner(logcat_supports_t=False)
    z, _man, err = diag.collect("adb", "S1", str(tmp_path),
                                logcat_lines=3, runner=runner)
    assert err is None
    with zipfile.ZipFile(z) as zf:
        text = zf.read(diag.F_LOGCAT).decode("utf-8")
    assert "不支持 -t" in text
    # 只保留最后 3 行：old0 / old1 必须被截掉
    assert "old2" in text and "old3" in text and "old4" in text
    assert "old0" not in text and "old1" not in text


def test_collect_ps_fallback_when_dash_a_unsupported(tmp_path):
    """`ps -A` 失败（老设备）后必须退到 `ps`，不能直接判定读取失败。"""
    calls = {"n": 0}

    def runner(args, timeout):
        a = " ".join(args)
        if a == "shell ps -A":
            calls["n"] += 1
            return 1, "", "ps: unknown option -A"
        if a == "shell ps":
            return 0, PS_NEW, ""
        return make_runner()(args, timeout)

    z, man, err = diag.collect("adb", "S1", str(tmp_path), with_logcat=False,
                               runner=runner)
    assert err is None and calls["n"] == 1
    with zipfile.ZipFile(z) as zf:
        assert "com.big.app" in zf.read(diag.F_PROCESS).decode("utf-8")
    assert [p for p in man["parts"] if p["name"] == diag.F_PROCESS][0]["ok"]


def test_collect_section_failure_still_produces_zip(tmp_path):
    """某一项读不到（无权限）不能让整包失败，缺口要写进清单。"""
    z, man, err = diag.collect("adb", "S1", str(tmp_path), with_logcat=False,
                               runner=make_runner(anr_ok=False, apps3="",
                                                  apps_all=""))
    assert err is None and z
    flags = {p["name"]: p["ok"] for p in man["parts"]}
    assert flags[diag.F_APPS] is False
    assert flags[diag.F_DEVICE] is True
    assert "诊断包" in diag.summary_line(z, man) or "已保存" in diag.summary_line(z, man)


def test_collect_meminfo_failure_still_produces_zip(tmp_path):
    """meminfo 段读不到（dumpsys 无权限 / 精简 ROM）时只记失败，整包照常产出。"""
    def runner(args, timeout):
        if " ".join(args).startswith("shell dumpsys meminfo"):
            return 1, "", "Permission denied"
        return make_runner()(args, timeout)

    z, man, err = diag.collect("adb", "S1", str(tmp_path), with_logcat=False,
                               runner=runner)
    assert err is None and z
    flags = {p["name"]: p["ok"] for p in man["parts"]}
    assert flags[diag.F_MEMINFO] is False
    assert flags[diag.F_DEVICE] is True          # 其它段不受牵连
    with zipfile.ZipFile(z) as zf:
        assert diag.F_MEMINFO in zf.namelist()
        assert "失败" in zf.read(diag.F_MEMINFO).decode("utf-8")


def test_collect_netcfg_fallback(tmp_path):
    """老 ROM 没有 ip addr（ip addr 段为空）时退回 netcfg 仍产出 net.txt。"""
    def runner(args, timeout):
        if "ip addr" in " ".join(args):
            return 0, "__NETCFG__\n" + NETCFG_SAMPLE, ""
        return make_runner()(args, timeout)

    z, man, err = diag.collect("adb", "S1", str(tmp_path), with_logcat=False,
                               runner=runner)
    assert err is None and z
    with zipfile.ZipFile(z) as zf:
        assert diag.F_NET in zf.namelist()
        txt = zf.read(diag.F_NET).decode("utf-8")
        assert "eth0" in txt and "192.168.1.5" in txt


def test_collect_net_failure_still_produces_zip(tmp_path):
    """网络段读不到（无 ip addr 也无 netcfg）时只记失败，整包照常产出。"""
    def runner(args, timeout):
        if "ip addr" in " ".join(args):
            return 1, "", "not found"
        return make_runner()(args, timeout)

    z, man, err = diag.collect("adb", "S1", str(tmp_path), with_logcat=False,
                               runner=runner)
    assert err is None and z
    flags = {p["name"]: p["ok"] for p in man["parts"]}
    assert flags[diag.F_NET] is False
    assert flags[diag.F_DEVICE] is True          # 其它段不受牵连
    with zipfile.ZipFile(z) as zf:
        assert diag.F_NET in zf.namelist()
        assert "失败" in zf.read(diag.F_NET).decode("utf-8")


def test_collect_runner_raises_is_contained(tmp_path):
    """adb 不存在 / 超时（runner 抛异常）时只把该段记成失败。"""
    def runner(args, timeout):
        raise OSError("adb not found")

    z, man, err = diag.collect("adb", "S1", str(tmp_path), with_logcat=False,
                               runner=runner)
    assert err is None and z            # 仍然产包（每段都写失败原因）
    assert all(not p["ok"] for p in man["parts"])
    assert man["notes"]                     # 至少记了原因


def test_collect_bad_out_dir(tmp_path):
    """保存目录建不出来时返回中文原因，而不是抛异常。"""
    bad = str(tmp_path / "a.txt")
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    z, man, err = diag.collect("adb", "S1", bad, runner=make_runner())
    assert z is None and err and "保存目录" in err


def test_collect_zip_name_is_safe_for_wireless_serial(tmp_path):
    """无线设备序列号带冒号：Windows 文件名不允许，必须净化。"""
    z, _man, err = diag.collect("adb", "192.168.1.5:5555", str(tmp_path),
                                with_logcat=False, runner=make_runner())
    assert err is None
    name = os.path.basename(z)
    assert ":" not in name
    assert name.startswith("diag_192.168.1.5_5555_")


def test_collect_cleans_temp_dir(tmp_path, monkeypatch):
    """收集过程中的中间目录必须清理掉（不能每收一次就在 TEMP 留一堆）。"""
    import tempfile as _tf
    made = []
    real = _tf.mkdtemp

    def spy(*a, **kw):
        d = real(*a, **kw)
        made.append(d)
        return d

    monkeypatch.setattr(diag.tempfile, "mkdtemp", spy)
    diag.collect("adb", "S1", str(tmp_path), with_logcat=False,
                 runner=make_runner())
    assert made and all(not os.path.exists(d) for d in made)


@pytest.mark.parametrize("app_version", [None, "v-test-1"])
def test_collect_records_version(tmp_path, app_version):
    z, man, _err = diag.collect("adb", "S1", str(tmp_path), with_logcat=False,
                                runner=make_runner(), app_version=app_version)
    with zipfile.ZipFile(z) as zf:
        meta = json.loads(zf.read(diag.F_META).decode("utf-8"))
    assert meta["app_version"] == (app_version or diag.VERSION)


def test_script_sections_are_all_consumed():
    """devinfo.SCRIPT 的每个分段标记都要能被 diag 的 props 提取逻辑认出来。"""
    block = devinfo._section(_props_block(), devinfo.MARK_PROP,
                             (devinfo.MARK_WM, devinfo.MARK_BATT,
                              devinfo.MARK_DF, devinfo.MARK_MEM,
                              devinfo.MARK_UP))
    assert "ro.product.model" in block
    assert "@@WM" not in block
