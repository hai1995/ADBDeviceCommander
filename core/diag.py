"""
core.diag —— 「一键诊断包」：把一次问题的现场证据收齐，打成一个 zip。
====================================================================
为什么需要它：车机上复现一个 bug 之后，要发回给开发的东西每次都一样。

设计要点
--------
* **尽量少的 adb 调用**。
* **每段独立失败**。
* **清单可读**。
* **纯函数 + runner 注入**。
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile

from core import devinfo
from core.constants import VERSION, adb_kwargs, safe_name, unique_path
from core.longpath import long_path, path_exists

DEFAULT_LOGCAT_LINES = 2000
MAX_LOGCAT_LINES = 50000
TIMEOUT = 40
PROC_TOP_N = 15

F_DEVICE = "device.txt"
F_PROPS = "props.txt"
F_LOGCAT = "logcat.txt"
F_PROCESS = "process.txt"
F_APPS = "apps.txt"
F_ANR = "anr.txt"
F_MEMINFO = "meminfo.txt"
F_NET = "net.txt"
F_CPU = "cpu.txt"
F_META = "meta.json"


def clamp_lines(n, default=DEFAULT_LOGCAT_LINES):
    """把用户给的行数夹到合法区间；非数字 / None 用默认值。"""
    try:
        v = int(n)
    except (TypeError, ValueError):
        return default
    if v <= 0:
        return default
    return min(MAX_LOGCAT_LINES, v)


def parse_ps(text):
    """解析 `ps` / `ps -A` / `ps -A -o PID,RSS,NAME` 输出。"""
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return [], {}
    idx = {"pid": None, "rss": None, "name": None}
    header = lines[0].split()
    up = [c.upper() for c in header]
    if "PID" in up:
        idx["pid"] = up.index("PID")
        idx["rss"] = up.index("RSS") if "RSS" in up else None
        if "NAME" in up:
            idx["name"] = up.index("NAME")
        elif "CMD" in up:
            idx["name"] = up.index("CMD")
        body = lines[1:]
    else:
        body = lines
    out = []
    for ln in body:
        toks = ln.split()
        if len(toks) < 3:
            continue
        try:
            pid = int(toks[idx["pid"] if idx["pid"] is not None else 0])
        except (TypeError, ValueError):
            continue
        rss = 0
        ri = idx["rss"] if idx["rss"] is not None else (4 if len(toks) > 4 else None)
        if ri is not None and ri < len(toks):
            try:
                rss = int(toks[ri])
            except ValueError:
                rss = 0
        ni = idx["name"]
        name = toks[ni] if (ni is not None and ni < len(toks)) else toks[-1]
        out.append((pid, max(0, rss), name))
    return out, {k: v for k, v in idx.items() if v is not None}


def _mb(kb):
    """KB → MB 文本（进程 RSS 用）。"""
    try:
        n = float(kb or 0)
    except (TypeError, ValueError):
        return "-"
    if n <= 0:
        return "-"
    if n >= 1024:
        return "%.1f MB" % (n / 1024.0)
    return "%d KB" % int(n)


def top_memory(text, limit=PROC_TOP_N):
    """从 ps 输出里取内存占用 TOP N（按 RSS 降序）。"""
    rows, _cols = parse_ps(text)
    rows = [r for r in rows if r[1] > 0]
    rows.sort(key=lambda r: r[1], reverse=True)
    return rows[:max(1, int(limit or 1))]


def process_report(text, limit=PROC_TOP_N):
    """把 ps 输出整理成「摘要 + 原始表」的文本。"""
    rows = top_memory(text, limit)
    head = ["== 内存占用 TOP %d（RSS，来自 ps）==" % len(rows)]
    if rows:
        for pid, rss, name in rows:
            head.append("  %-7d %10s  %s" % (pid, _mb(rss), name))
    else:
        head.append("  （未能从 ps 输出里解析出 RSS 列，见下方原始输出）")
    head.append("")
    head.append("== ps 原始输出 ==")
    return "\n".join(head) + "\n" + (text or "")


def _meminfo_summary_block(text):
    """从 `dumpsys meminfo` 输出里抽取头部汇总段（丢弃几 MB 的进程详情）。"""
    if not text:
        return ""
    start = text.find("Total PSS by process:")
    if start < 0:
        return ""
    end = text.find("Total RAM:", start)
    if end < 0:
        return text[start:]
    nl = text.find("\n", end)
    return text[start:(nl if nl > 0 else len(text))]


def parse_meminfo(text):
    """解析 `dumpsys meminfo` 的「Total PSS by process」段。"""
    block = _meminfo_summary_block(text)
    m = re.search(r"Total PSS by process:\s*(.*?)(?=Total PSS by |\Z)",
                  block, re.S)
    if m:
        block = m.group(1)
    rows = []
    for ln in block.splitlines():
        m = re.match(r"^\s*(\d+)\s*kB:\s*(.+?)\s*$", ln)
        if not m:
            continue
        try:
            pss = int(m.group(1))
        except ValueError:
            continue
        name = m.group(2)
        pid = None
        pm = re.search(r"\(pid\s+(\d+)\)", name)
        if pm:
            pid = int(pm.group(1))
            name = name[:pm.start()].strip()
        rows.append((pss, name, pid))
    rows.sort(key=lambda r: r[0], reverse=True)
    return rows


def meminfo_report(text, limit=PROC_TOP_N):
    """把 `dumpsys meminfo` 整理成「分页明细 TOP N + 内存汇总段」的文本。"""
    rows = parse_meminfo(text)[:max(1, int(limit or 1))]
    head = ["== 内存分页明细 TOP %d（PSS，来自 dumpsys meminfo）==" % len(rows)]
    if rows:
        for pss, name, _pid in rows:
            head.append("  %-40s %12s" % (name, _mb(pss)))
    else:
        head.append("  （未能从 meminfo 输出里解析出 PSS 分段，见下方原始汇总）")
    head.append("")
    block = _meminfo_summary_block(text)
    head.append("== dumpsys meminfo 内存汇总 ==")
    if block.strip():
        head.append(block.strip())
    else:
        head.append("（无汇总段：部分精简 ROM 不输出 Total PSS by process）")
    return "\n".join(head) + "\n"


_NETCFG_SEP = "__NETCFG__"


def _parse_ip_addr(block):
    """解析 `ip addr` 输出，返回 [(name, up, ipv4)]。"""
    out = []
    cur = None
    for ln in (block or "").splitlines():
        m = re.match(r"^\d+:\s*([\w.@-]+):\s*<([^>]*)>", ln)
        if m:
            if cur is not None:
                out.append(tuple(cur))
            flags = m.group(2).split(",")
            cur = [m.group(1), ("UP" in flags), ""]
            continue
        if cur is not None:
            im = re.match(r"\s*inet\s+(\d+\.\d+\.\d+\.\d+)/\d+", ln)
            if im:
                cur[2] = im.group(1)
                out.append(tuple(cur))
                cur = None
    if cur is not None:
        out.append(tuple(cur))
    return out


def _parse_netcfg(block):
    """解析 `netcfg` 输出，返回 [(name, up, ipv4)]。"""
    out = []
    for ln in (block or "").splitlines():
        toks = ln.split()
        if len(toks) < 3:
            continue
        if toks[1] not in ("UP", "DOWN"):
            continue
        ip = toks[2].split("/")[0]
        if not re.match(r"^\d+\.\d+\.\d+\.\d+$", ip) or ip == "0.0.0.0":
            ip = ""
        out.append((toks[0], toks[1] == "UP", ip))
    return out


def parse_net(text):
    """从 `ip addr ; netcfg` 的组合输出里提取网络接口列表。"""
    if not text:
        return []
    if _NETCFG_SEP in text:
        ip_part, _, nc_part = text.partition(_NETCFG_SEP)
    else:
        ip_part, nc_part = text, ""
    rows = _parse_ip_addr(ip_part)
    if not rows:
        rows = _parse_netcfg(nc_part or text)
    return rows


def net_report(text):
    """把网络接口整理成「接口列表 + 原始输出」的文本。"""
    rows = parse_net(text)
    head = ["== 网络接口（状态 / IPv4）=="]
    if rows:
        for name, up, ip in rows:
            head.append("  %-12s %s  %s" % (name, "UP  " if up else "DOWN",
                                            ip or "（无 IP）"))
    else:
        head.append("  （未能解析出网络接口，见下方原始输出）")
    head.append("")
    head.append("== 原始输出 ==")
    head.append((text or "").strip())
    return "\n".join(head) + "\n"


_CPUINFO_SEP = "__CPUINFO__"


def parse_cpu(text):
    """从 `cat /proc/loadavg ; dumpsys cpuinfo` 的组合输出里提取 CPU 现场。"""
    load = {}
    procs = []
    if not text:
        return load, procs
    if _CPUINFO_SEP in text:
        la_part, _, ci_part = text.partition(_CPUINFO_SEP)
    else:
        la_part, ci_part = text, ""
    toks = (la_part or "").split()
    if len(toks) >= 5:
        try:
            load["one"] = float(toks[0])
            load["five"] = float(toks[1])
            load["fifteen"] = float(toks[2])
        except ValueError:
            pass
        rt = toks[3].split("/")
        if len(rt) == 2:
            try:
                load["runnable"] = int(rt[0])
                load["total_threads"] = int(rt[1])
            except ValueError:
                pass
        try:
            load["last_pid"] = int(toks[4])
        except ValueError:
            pass
    rows = []
    if ci_part:
        for ln in ci_part.splitlines():
            s = ln.strip()
            if not s:
                continue
            if s.startswith("TOTAL"):
                break
            if s.startswith(("Load:", "CPU usage")):
                continue
            pm = re.search(r"([\w.\-/]+):\s*(\d+(?:\.\d+)?)\s*%", s)
            if not pm or pm.group(1).upper() == "TOTAL":
                continue
            name = pm.group(1)
            if "/" in name:
                name = name.rsplit("/", 1)[-1]
            try:
                pct = float(pm.group(2))
            except ValueError:
                continue
            rows.append((pct, name))
    rows.sort(key=lambda r: r[0], reverse=True)
    procs = rows
    return load, procs


def cpu_report(text):
    """把 CPU 现场整理成「整体负载 + 进程 CPU 占比 TOP N + 原始输出」的文本。"""
    load, procs = parse_cpu(text)
    head = ["== 整体负载（来自 /proc/loadavg）=="]
    if load:
        head.append("  1 分钟: {}   5 分钟: {}   15 分钟: {}".format(load.get("one", "-"), load.get("five", "-"),
                       load.get("fifteen", "-")))
        if "runnable" in load:
            head.append("  运行队列: %d / 线程总数 %d"
                        % (load["runnable"], load.get("total_threads", 0)))
    else:
        head.append("  （未能读取 /proc/loadavg）")
    head.append("")
    head.append("== 进程 CPU 占比 TOP %d（来自 dumpsys cpuinfo）==" % len(procs))
    if procs:
        for pct, name in procs:
            head.append("  {:6.1f}%  {}".format(pct, name))
    else:
        head.append("  （cpuinfo 受限或无进程占比，仅看整体负载即可）")
    head.append("")
    head.append("== 原始输出 ==")
    head.append((text or "").strip())
    return "\n".join(head) + "\n"


def summarize_packages(text3, text_all=""):
    """`pm list packages -3` / `pm list packages` → 一段中文摘要。"""
    def names(t):
        out = []
        for ln in (t or "").splitlines():
            ln = ln.strip()
            if ln.startswith("package:"):
                out.append(ln[len("package:"):].strip())
        return out
    third = names(text3)
    total = names(text_all)
    third_set = set(third)
    system = [n for n in total if n not in third_set]
    lines = ["第三方应用：%d 个" % len(third)]
    if system:
        lines.append("系统应用：%d 个" % len(system))
    if total:
        lines.append("全部应用：%d 个" % len(total))
    lines.append("")
    lines.append("== 第三方应用包名 ==")
    lines.extend(["  " + n for n in sorted(third)] or ["  （无）"])
    if system:
        lines.append("")
        lines.append("== 系统应用包名 ==")
        lines.extend(["  " + n for n in sorted(system)])
    return "\n".join(lines) + "\n"


def _default_runner(adb, serial, args, timeout):
    """真实执行 `adb -s <serial> <args>`，返回 (rc, stdout, stderr)。"""
    r = subprocess.run([adb, "-s", serial] + list(args), **adb_kwargs(timeout))
    return r.returncode, (r.stdout or ""), (r.stderr or "")


class _Ctx:
    """收集过程的小工具：统一调 runner、统一记录每段的成败。"""

    def __init__(self, adb, serial, runner):
        self.adb = adb
        self.serial = serial
        self.runner = runner or (
            lambda args, timeout: _default_runner(adb, serial, args, timeout))
        self.parts = []

    def run(self, args, timeout=TIMEOUT):
        try:
            return self.runner(list(args), timeout)
        except Exception as e:
            return 1, "", str(e)

    def record(self, name, ok, size=0, source="", error=""):
        self.parts.append({"name": name, "ok": bool(ok), "bytes": int(size),
                           "source": source, "error": error or ""})


def _write(path, text):
    """写一份诊断文件（UTF-8 + 宽松换行），返回字节数。"""
    lp = long_path(path)
    with open(lp, "w", encoding="utf-8", errors="replace", newline="\n") as f:
        f.write(text if text is not None else "")
    return os.path.getsize(lp)


def _logcat_text(ctx, lines):
    """取 logcat 尾部 N 行。返回 (text, error)。"""
    n = clamp_lines(lines)
    rc, out, err = ctx.run(["logcat", "-d", "-v", "threadtime",
                            "-t", str(n)], timeout=TIMEOUT)
    if rc == 0 and out.strip():
        return out, ""
    rc2, out2, err2 = ctx.run(["logcat", "-d", "-v", "threadtime"], timeout=TIMEOUT)
    if rc2 == 0 and out2:
        tail = out2.splitlines()[-n:]
        note = ("（本机 logcat 不支持 -t，已改为全量 dump 后截取尾部 %d 行）\n" % n)
        return note + "\n".join(tail) + "\n", ""
    return "", (err or err2 or "logcat 无输出").strip()[:300]


def collect(adb, serial, out_dir, with_logcat=True,
            logcat_lines=DEFAULT_LOGCAT_LINES, runner=None, now=None,
            app_version=None):
    """收集一台设备的诊断包。"""
    dt = now or datetime.datetime.now()
    ts = dt.strftime("%Y%m%d_%H%M%S")
    serial_s = str(serial or "")
    try:
        os.makedirs(long_path(out_dir), exist_ok=True)
    except Exception as e:
        return None, None, "无法创建保存目录 {}：{}".format(out_dir, e)

    ctx = _Ctx(adb, serial_s, runner)
    work = tempfile.mkdtemp(prefix="adb_diag_")
    manifest = {
        "tool": "ADB 设备指令台",
        "app_version": app_version or VERSION,
        "collected_at": dt.strftime("%Y-%m-%d %H:%M:%S"),
        "serial": serial_s,
        "adb": adb,
        "with_logcat": bool(with_logcat),
        "logcat_lines": clamp_lines(logcat_lines) if with_logcat else 0,
        "device": {},
        "parts": [],
        "notes": [],
    }
    try:
        rc, out, err = ctx.run(["shell", devinfo.SCRIPT], timeout=TIMEOUT)
        info = devinfo.parse_info(out) if rc == 0 else {}
        device_text = ""
        if rc == 0 and out.strip():
            rows = devinfo.rows(info)
            device_text = "\n".join("{}: {}".format(k, v) for k, v in rows)
            if not device_text:
                device_text = "（未能解析出设备信息，见 props.txt 原始输出）"
        else:
            device_text = "（读取设备信息失败：{}）".format((err or "adb shell 无输出").strip()[:200])
            manifest["notes"].append("设备信息读取失败")
        size = _write(os.path.join(work, F_DEVICE), device_text + "\n")
        ctx.record(F_DEVICE, bool(device_text and rc == 0), size,
                   "adb shell <devinfo.SCRIPT>",
                   "" if rc == 0 else (err or "")[:200])
        props = devinfo._section(out, devinfo.MARK_PROP,
                                 (devinfo.MARK_WM, devinfo.MARK_BATT,
                                  devinfo.MARK_DF, devinfo.MARK_MEM,
                                  devinfo.MARK_UP)) if out else ""
        size = _write(os.path.join(work, F_PROPS), props)
        ctx.record(F_PROPS, bool(props), size, "adb shell getprop",
                   "" if props else "getprop 无输出")
        manifest["device"] = {
            "model": info.get("ro.product.model", ""),
            "manufacturer": info.get("ro.product.manufacturer", ""),
            "android": info.get("ro.build.version.release", ""),
            "sdk": info.get("ro.build.version.sdk", ""),
            "abi": info.get("ro.product.cpu.abi", ""),
            "resolution": info.get("resolution", ""),
            "battery_level": info.get("battery_level", ""),
            "uptime_s": info.get("uptime_s", 0),
        }

        rc, out, err = ctx.run(["shell", "ps", "-A"], timeout=TIMEOUT)
        if rc != 0 or not out.strip():
            rc, out, err = ctx.run(["shell", "ps"], timeout=TIMEOUT)
        proc_text = (process_report(out) if (rc == 0 and out.strip())
                     else "（读取进程列表失败：{}）\n".format((err or "ps 无输出").strip()[:200]))
        size = _write(os.path.join(work, F_PROCESS), proc_text)
        ctx.record(F_PROCESS, bool(rc == 0 and out.strip()),
                   size, "adb shell ps -A",
                   "" if rc == 0 else (err or "")[:200])
        if rc != 0:
            manifest["notes"].append("进程列表读取失败")

        rc, out, err = ctx.run(["shell", "dumpsys", "meminfo"], timeout=TIMEOUT)
        mem_text = (meminfo_report(out) if (rc == 0 and out.strip())
                    else "（读取内存分页明细失败：{}）\n".format((err or "dumpsys meminfo 无输出").strip()[:200]))
        size = _write(os.path.join(work, F_MEMINFO), mem_text)
        ctx.record(F_MEMINFO, bool(rc == 0 and out.strip()),
                   size, "adb shell dumpsys meminfo",
                   "" if rc == 0 else (err or "")[:200])
        if rc != 0:
            manifest["notes"].append("内存分页明细读取失败")

        _, out3, _e3 = ctx.run(["shell", "pm", "list", "packages", "-3"],
                                 timeout=TIMEOUT)
        _, outa, _ea = ctx.run(["shell", "pm", "list", "packages"],
                                 timeout=TIMEOUT)
        apps_text = (summarize_packages(out3, outa)
                     if (out3 or outa) else "（读取应用列表失败）\n")
        size = _write(os.path.join(work, F_APPS), apps_text)
        ctx.record(F_APPS, bool(out3 or outa), size,
                   "adb shell pm list packages [-3]",
                   "" if (out3 or outa) else "pm list packages 无输出")

        anr_cmd = ("dumpsys window 2>/dev/null | grep -E "
                   "'mCurrentFocus|mFocusedApp' | head -8; "
                   "echo '-- lastanr --'; "
                   "dumpsys activity lastanr 2>/dev/null | head -30; "
                   "echo '-- /data/anr --'; ls -l /data/anr 2>&1 | head -20; "
                   "echo '-- /data/tombstones --'; "
                   "ls -l /data/tombstones 2>&1 | head -20")
        rc, out, err = ctx.run(["shell", anr_cmd], timeout=TIMEOUT)
        anr_text = (out if (rc == 0 and out.strip())
                    else "（读取 ANR / tombstone 线索失败：{}）\n".format((err or "dumpsys 无输出").strip()[:200]))
        size = _write(os.path.join(work, F_ANR), anr_text)
        ctx.record(F_ANR, bool(rc == 0 and out.strip()), size,
                   "adb shell dumpsys window/activity + ls /data/anr")
        if rc != 0:
            manifest["notes"].append("ANR 线索读取失败（部分机型需 root）")

        rc, out, err = ctx.run(
            ["shell", "ip addr 2>/dev/null; echo {}; netcfg 2>/dev/null".format(_NETCFG_SEP)],
            timeout=TIMEOUT)
        net_text = (net_report(out) if (rc == 0 and out.strip())
                    else "（读取网络接口失败：{}）\n".format((err or "无输出").strip()[:200]))
        size = _write(os.path.join(work, F_NET), net_text)
        ctx.record(F_NET, bool(rc == 0 and out.strip()),
                   size, "adb shell ip addr / netcfg",
                   "" if rc == 0 else (err or "")[:200])
        if rc != 0:
            manifest["notes"].append("网络接口读取失败")

        rc, out, err = ctx.run(
            ["shell", "cat /proc/loadavg 2>/dev/null; echo {}; "
             "dumpsys cpuinfo 2>/dev/null".format(_CPUINFO_SEP)],
            timeout=TIMEOUT)
        cpu_text = (cpu_report(out) if (rc == 0 and out.strip())
                    else "（读取 CPU 负载失败：{}）\n".format((err or "无输出").strip()[:200]))
        size = _write(os.path.join(work, F_CPU), cpu_text)
        ctx.record(F_CPU, bool(rc == 0 and out.strip()),
                   size, "adb shell cat /proc/loadavg ; dumpsys cpuinfo",
                   "" if rc == 0 else (err or "")[:200])
        if rc != 0:
            manifest["notes"].append("CPU 负载读取失败")

        if with_logcat:
            text, lerr = _logcat_text(ctx, logcat_lines)
            if not text:
                text = "（读取 logcat 失败：%s）\n" % (lerr or "无输出")
                manifest["notes"].append("logcat 读取失败")
            size = _write(os.path.join(work, F_LOGCAT), text)
            ctx.record(F_LOGCAT, not lerr, size,
                       "adb logcat -d -t %d" % clamp_lines(logcat_lines), lerr)

        manifest["parts"] = ctx.parts
        _write(os.path.join(work, F_META),
               json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

        name = "diag_{}_{}.zip".format(safe_name(serial_s, "device"), ts)
        zip_path = unique_path(os.path.join(out_dir, name))
        lzip = long_path(zip_path)
        try:
            with zipfile.ZipFile(lzip, "w", zipfile.ZIP_DEFLATED) as z:
                for fn in (F_DEVICE, F_PROPS, F_LOGCAT, F_PROCESS, F_APPS,
                           F_ANR, F_NET, F_MEMINFO, F_CPU, F_META):
                    p = os.path.join(work, fn)
                    if path_exists(p):
                        z.write(long_path(p), fn)
        except Exception as e:
            try:
                if os.path.exists(lzip):
                    os.remove(lzip)
            except Exception:
                pass
            return None, manifest, "打包失败：{}".format(e)
        return zip_path, manifest, None
    finally:
        shutil.rmtree(long_path(work), ignore_errors=True)


def summary_line(zip_path, manifest):
    """一行中文结果说明（状态栏 / toast 用）。"""
    m = manifest or {}
    dev = m.get("device") or {}
    who = dev.get("model") or (m.get("serial") or "设备")
    parts = m.get("parts") or []
    bad = [p.get("name") for p in parts if not p.get("ok")]
    if parts and len(bad) == len(parts):
        first = next((p.get("error") for p in parts if p.get("error")), "")
        why = "，首个原因：{}".format(first.strip()[:80]) if first else ""
        return ("⚠ 诊断包已保存，但 %d 项内容全部收集失败%s：%s"
                "（设备可能已断开或未授权，建议重新连接后再收集）"
                % (len(parts), why, zip_path))
    tail = ""
    if bad:
        shown = "、".join(bad[:6])
        more = "" if len(bad) <= 6 else " 等 %d 项" % len(bad)
        tail = "，缺 {}{}".format(shown, more)
    return "✓ 诊断包已保存: {}（{}{}）".format(zip_path, who, tail)
