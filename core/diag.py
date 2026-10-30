# -*- coding: utf-8 -*-
"""
core.diag —— 「一键诊断包」：把一次问题的现场证据收齐，打成一个 zip。
====================================================================
为什么需要它：车机上复现一个 bug 之后，要发回给开发的东西每次都一样 ——

  设备是什么机器 / 什么系统版本、当时的 logcat 尾部、谁在吃内存、
  装了哪些应用、有没有 ANR / tombstone。

这些以前要点 4~5 次不同功能、分别存文件、再自己打包命名；忙起来就漏，事后
补不回来。本模块把「收集 + 命名 + 打包 + 写清单」一次做完，产出**一个 zip**，
直接发给同事即可。

设计要点
--------
* **尽量少的 adb 调用**：设备信息（getprop / wm / battery / df / meminfo /
  uptime）复用 core.devinfo 的单次 shell 脚本；整个诊断包共 7 次调用
  （另含一次 `dumpsys meminfo` 与一次网络接口快照），USB 上约 4~10 秒。
  meminfo 只抽取头部的汇总段（Total PSS by process / by category / Total RAM），
  **丢弃几 MB 的进程详情**，既精准回答「谁在吃内存」（PSS 比 ps 的 RSS 更准）
  又不撑爆包体；网络快照用 `ip addr` / `netcfg` 双格式兜底，回答「接口通不通、
  有没有拿到 IP」（车机联网问题最常见）。
* **每段独立失败**：logcat 拉不到、/data/anr 无权限，都只在该文件里写一行
  中文说明并记进清单，绝不让整包失败 —— 收集现场时「有 4 份、缺 1 份」远好过
  「什么都没有」。
* **清单可读**：meta.json 记录收集时间、程序版本、每份文件的来源命令与字节数、
  失败原因，方便判断这份包是不是完整。
* **纯函数 + runner 注入**：本模块不直接依赖 subprocess，单测可用假 runner
  复现各种 ROM 的怪异输出（无 ps -o、logcat 不支持 -t、无 /data/anr 权限）。
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile

from core.constants import VERSION, adb_kwargs, safe_name
from core import devinfo

# 默认 / 上限 logcat 行数。上限不是「随便定一个」：单条 threadtime 约 150 字节，
# 5 万行 ≈ 7 MB，压缩后 1~2 MB，是能随手发出去的体积；再多就该用「logcat 抓取」
# 那种落盘模式了。
DEFAULT_LOGCAT_LINES = 2000
MAX_LOGCAT_LINES = 50000
# 单次 adb 调用的超时。logcat 尾部 5 万行在慢设备上要十几秒，故给宽一些。
TIMEOUT = 40
# 进程表只展示内存 TOP N（全量仍原样写进文件，只是把摘要放最上面）。
PROC_TOP_N = 15

# 诊断包内的文件名（顺序即 zip 内的展示顺序）
F_DEVICE = "device.txt"      # 设备信息（人读摘要）
F_PROPS = "props.txt"        # getprop 全量（机器可读的原始值）
F_LOGCAT = "logcat.txt"      # 日志尾部
F_PROCESS = "process.txt"    # 进程 + 内存 TOP
F_APPS = "apps.txt"          # 已安装应用（第三方 + 系统包名清单）
F_ANR = "anr.txt"            # 前台 Activity / ANR / tombstone 线索
F_MEMINFO = "meminfo.txt"    # 内存分页明细（PSS by process TOP N + 汇总）
F_NET = "net.txt"            # 网络接口状态 / IP（ip addr 与 netcfg 兜底）
F_META = "meta.json"         # 清单


# ---------------------------------------------------------------------------
# 入参归一化
# ---------------------------------------------------------------------------
def clamp_lines(n, default=DEFAULT_LOGCAT_LINES):
    """把用户给的行数夹到合法区间；非数字 / None 用默认值。"""
    try:
        v = int(n)
    except (TypeError, ValueError):
        return default
    if v <= 0:
        return default
    return min(MAX_LOGCAT_LINES, v)


# ---------------------------------------------------------------------------
# 解析：ps 内存 TOP
# ---------------------------------------------------------------------------
def parse_ps(text):
    """解析 `ps` / `ps -A` / `ps -A -o PID,RSS,NAME` 输出。

    返回 (rows, cols)：rows 为 [(pid, rss_kb, name)]，cols 为表头里认出来的
    列名映射（认不出时为空 dict）。不同 ROM 的列顺序差别很大（老 Toybox 是
    `USER PID PPID VSZ RSS WCHAN PC NAME`，新的是 `PID TTY TIME CMD`），
    所以优先按表头定位 RSS 列，表头认不出时退回「第 5 列」这一历史惯例。
    """
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
    else:                       # 无表头的裁剪输出
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


# ---------------------------------------------------------------------------
# 解析：dumpsys meminfo 内存分页明细
# ---------------------------------------------------------------------------
def _meminfo_summary_block(text):
    """从 `dumpsys meminfo` 输出里抽取头部汇总段（丢弃几 MB 的进程详情）。

    返回从「Total PSS by process:」到「Total RAM:」之间的文本——这一段同时
    覆盖 by process / by OOM adjustment / by category 三个汇总表与全局 Total RAM
    画像，是诊断「谁在吃内存」最有价值、体积又最小的部分。老 ROM 没有这些标记
    时返回空串（调用方据此写失败原因，绝不抛异常）。
    """
    if not text:
        return ""
    start = text.find("Total PSS by process:")
    if start < 0:
        return ""
    end = text.find("Total RAM:", start)
    if end < 0:
        return text[start:]
    # 含 Total RAM 那一行（其后的 Free/Used/Lost RAM 也一并保留，画像更完整）
    nl = text.find("\n", end)
    return text[start:(nl if nl > 0 else len(text))]


def parse_meminfo(text):
    """解析 `dumpsys meminfo` 的「Total PSS by process」段。

    返回 [(pss_kb, name, pid_or_none)]，按 PSS 降序。每行形如
    `  123456 kB: com.abc (pid 1234) (foreground)`，不同 ROM 还可能带
    `(uid NNN)` 或没有 pid；name 会剔除这些括号后缀。认不出 PSS 数字的行
    （如总计行）会被忽略。
    """
    block = _meminfo_summary_block(text)
    # 只解析 by process 段：by OOM / by category 段也有「NNN kB: 名字」格式，
    # 会把 Native/Dalvik/Foreground 之类错当成进程，必须限定在 process 段内。
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


# ---------------------------------------------------------------------------
# 解析：网络接口（ip addr 与 netcfg 双格式兜底）
# ---------------------------------------------------------------------------
_NETCFG_SEP = "__NETCFG__"


def _parse_ip_addr(block):
    """解析 `ip addr` 输出，返回 [(name, up, ipv4)]。

    `ip addr` 是 Android 5.0+ 的标准命令；接口行形如
    `2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> ... state UP ...`，IP 在后续
    `inet 192.168.1.5/24 ...` 行。只取第一个 IPv4（inet6 行不匹配），一个接口
    没有 inet（无 IP）也照样登记——「接口 UP 但没 IP」正是车机最常踩的坑。
    """
    out = []
    cur = None                      # [name, up, ip]
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
    """解析 `netcfg` 输出，返回 [(name, up, ipv4)]。

    老 ROM（Android 4.x）没有 `ip addr`，用 `netcfg` 兜底，格式是
    `lo  UP  127.0.0.1/8  0x...  MAC`。IP 为 `0.0.0.0` 表示未分配到地址，记为空。
    """
    out = []
    for ln in (block or "").splitlines():
        toks = ln.split()
        if len(toks) < 3:
            continue
        if toks[1] not in ("UP", "DOWN"):
            continue
        ip = toks[2].split("/")[0]
        # 0.0.0.0 表示接口未分配到地址，等同于「无 IP」（车机常见：网线插了却没拿到地址）
        if not re.match(r"^\d+\.\d+\.\d+\.\d+$", ip) or ip == "0.0.0.0":
            ip = ""
        out.append((toks[0], toks[1] == "UP", ip))
    return out


def parse_net(text):
    """从 `ip addr ; netcfg` 的组合输出里提取网络接口列表。

    优先 `ip addr`（现代 ROM），完全解析不到时退回 `netcfg`（老 ROM）。
    返回 [(name, up, ipv4)]，解析不出任何接口时返回空 list（绝不抛异常）。
    """
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


# ---------------------------------------------------------------------------
# 解析：应用清单摘要
# ---------------------------------------------------------------------------
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
    # 系统应用 = 全量 − 第三方。排查「这个弹窗是哪来的 / 这个服务谁在拉起」
    # 时只给第三方清单经常查不到 —— 车机上的问题十有八九出在预置应用里。
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


# ---------------------------------------------------------------------------
# 执行
# ---------------------------------------------------------------------------
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
        self.parts = []          # [{name, ok, bytes, source, error}]

    def run(self, args, timeout=TIMEOUT):
        try:
            return self.runner(list(args), timeout)
        except Exception as e:      # 超时 / adb 不存在 / 设备拔掉
            return 1, "", str(e)

    def record(self, name, ok, size=0, source="", error=""):
        self.parts.append({"name": name, "ok": bool(ok), "bytes": int(size),
                           "source": source, "error": error or ""})


def _write(path, text):
    """写一份诊断文件（UTF-8 + 宽松换行），返回字节数。"""
    with open(path, "w", encoding="utf-8", errors="replace", newline="\n") as f:
        f.write(text if text is not None else "")
    return os.path.getsize(path)


def _logcat_text(ctx, lines):
    """取 logcat 尾部 N 行。返回 (text, error)。

    老设备（Android 4.x 部分定制 ROM）不支持 `-t`，会直接报 unknown option：
    此时退回 `-d` 全量 dump 再在本地截尾部 —— 全量可能几十万行，但这是在
    「拿不到」和「拿一大坨再截」之间唯一可行的折中，且截断后就地释放。
    """
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
    """收集一台设备的诊断包。

    参数
    ----
    adb          adb 可执行文件
    serial       设备序列号
    out_dir      输出目录（不存在会自动创建）
    with_logcat  是否包含 logcat 尾部（抓大日志要十几秒，用户可关掉）
    logcat_lines logcat 尾部行数（会被夹到 1~MAX_LOGCAT_LINES）
    runner       `(args, timeout) -> (rc, out, err)`，默认走真实 adb（测试注入）
    now          当前时间（注入用）
    app_version  写进清章的程序版本，默认取 core.constants.VERSION

    返回 `(zip_path, manifest, error)`：
      * 成功：zip_path 为产出的 zip 绝对路径，error 为 None；
      * 失败（目录不可写 / 打包异常）：zip_path 为 None，error 为中文原因。
    单段失败不算整包失败（该文件里会写明原因，清单里也标出来）。
    """
    dt = now or datetime.datetime.now()
    ts = dt.strftime("%Y%m%d_%H%M%S")
    serial_s = str(serial or "")
    try:
        os.makedirs(out_dir, exist_ok=True)
    except Exception as e:
        return None, None, "无法创建保存目录 %s：%s" % (out_dir, e)

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
        # ---- 1) 设备信息 + getprop 全量（一次 shell 取全）----
        rc, out, err = ctx.run(["shell", devinfo.SCRIPT], timeout=TIMEOUT)
        info = devinfo.parse_info(out) if rc == 0 else {}
        device_text = ""
        if rc == 0 and out.strip():
            rows = devinfo.rows(info)
            device_text = "\n".join("%s: %s" % (k, v) for k, v in rows)
            if not device_text:
                device_text = "（未能解析出设备信息，见 props.txt 原始输出）"
        else:
            device_text = "（读取设备信息失败：%s）" % (
                (err or "adb shell 无输出").strip()[:200])
            manifest["notes"].append("设备信息读取失败")
        size = _write(os.path.join(work, F_DEVICE), device_text + "\n")
        ctx.record(F_DEVICE, bool(device_text and rc == 0), size,
                   "adb shell <devinfo.SCRIPT>",
                   "" if rc == 0 else (err or "")[:200])
        # getprop 原样落地：型号 / 版本这类信息出问题时，开发常要自己 grep
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

        # ---- 2) 进程 / 内存 ----
        rc, out, err = ctx.run(["shell", "ps", "-A"], timeout=TIMEOUT)
        if rc != 0 or not out.strip():
            # 老设备没有 -A（用 ps 全量）；再不行就写失败原因
            rc, out, err = ctx.run(["shell", "ps"], timeout=TIMEOUT)
        proc_text = (process_report(out) if (rc == 0 and out.strip())
                     else "（读取进程列表失败：%s）\n"
                          % (err or "ps 无输出").strip()[:200])
        size = _write(os.path.join(work, F_PROCESS), proc_text)
        ctx.record(F_PROCESS, bool(rc == 0 and out.strip()),
                   size, "adb shell ps -A",
                   "" if rc == 0 else (err or "")[:200])
        if rc != 0:
            manifest["notes"].append("进程列表读取失败")

        # ---- 2.5) 内存分页明细（dumpsys meminfo 的 PSS 汇总段）----
        rc, out, err = ctx.run(["shell", "dumpsys", "meminfo"], timeout=TIMEOUT)
        mem_text = (meminfo_report(out) if (rc == 0 and out.strip())
                    else "（读取内存分页明细失败：%s）\n"
                         % (err or "dumpsys meminfo 无输出").strip()[:200])
        size = _write(os.path.join(work, F_MEMINFO), mem_text)
        ctx.record(F_MEMINFO, bool(rc == 0 and out.strip()),
                   size, "adb shell dumpsys meminfo",
                   "" if rc == 0 else (err or "")[:200])
        if rc != 0:
            manifest["notes"].append("内存分页明细读取失败")

        # ---- 3) 应用清单 ----
        rc3, out3, _e3 = ctx.run(["shell", "pm", "list", "packages", "-3"],
                                 timeout=TIMEOUT)
        rca, outa, _ea = ctx.run(["shell", "pm", "list", "packages"],
                                 timeout=TIMEOUT)
        apps_text = (summarize_packages(out3, outa)
                     if (out3 or outa) else "（读取应用列表失败）\n")
        size = _write(os.path.join(work, F_APPS), apps_text)
        ctx.record(F_APPS, bool(out3 or outa), size,
                   "adb shell pm list packages [-3]",
                   "" if (out3 or outa) else "pm list packages 无输出")

        # ---- 4) 前台 Activity / ANR / tombstone 线索 ----
        anr_cmd = ("dumpsys window 2>/dev/null | grep -E "
                   "'mCurrentFocus|mFocusedApp' | head -8; "
                   "echo '-- lastanr --'; "
                   "dumpsys activity lastanr 2>/dev/null | head -30; "
                   "echo '-- /data/anr --'; ls -l /data/anr 2>&1 | head -20; "
                   "echo '-- /data/tombstones --'; "
                   "ls -l /data/tombstones 2>&1 | head -20")
        rc, out, err = ctx.run(["shell", anr_cmd], timeout=TIMEOUT)
        anr_text = (out if (rc == 0 and out.strip())
                    else "（读取 ANR / tombstone 线索失败：%s）\n"
                         % (err or "dumpsys 无输出").strip()[:200])
        size = _write(os.path.join(work, F_ANR), anr_text)
        ctx.record(F_ANR, bool(rc == 0 and out.strip()), size,
                   "adb shell dumpsys window/activity + ls /data/anr")
        if rc != 0:
            manifest["notes"].append("ANR 线索读取失败（部分机型需 root）")

        # ---- 4.5) 网络接口快照（ip addr / netcfg 双格式兜底）----
        rc, out, err = ctx.run(
            ["shell", "ip addr 2>/dev/null; echo %s; netcfg 2>/dev/null"
             % _NETCFG_SEP],
            timeout=TIMEOUT)
        net_text = (net_report(out) if (rc == 0 and out.strip())
                    else "（读取网络接口失败：%s）\n"
                         % (err or "无输出").strip()[:200])
        size = _write(os.path.join(work, F_NET), net_text)
        ctx.record(F_NET, bool(rc == 0 and out.strip()),
                   size, "adb shell ip addr / netcfg",
                   "" if rc == 0 else (err or "")[:200])
        if rc != 0:
            manifest["notes"].append("网络接口读取失败")

        # ---- 5) logcat 尾部（可选：抓大日志要十几秒）----
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

        # ---- 打包 ----
        name = "diag_%s_%s.zip" % (safe_name(serial_s, "device"), ts)
        zip_path = os.path.join(out_dir, name)
        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
                for fn in (F_DEVICE, F_PROPS, F_LOGCAT, F_PROCESS, F_APPS,
                           F_ANR, F_NET, F_MEMINFO, F_META):
                    p = os.path.join(work, fn)
                    if os.path.exists(p):
                        z.write(p, fn)
        except Exception as e:
            try:
                if os.path.exists(zip_path):
                    os.remove(zip_path)
            except Exception:
                pass
            return None, manifest, "打包失败：%s" % e
        return zip_path, manifest, None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def summary_line(zip_path, manifest):
    """一行中文结果说明（状态栏 / toast 用）。"""
    m = manifest or {}
    dev = m.get("device") or {}
    who = dev.get("model") or (m.get("serial") or "设备")
    bad = [p.get("name") for p in (m.get("parts") or []) if not p.get("ok")]
    tail = ("，缺：%s" % "、".join(bad)) if bad else ""
    return "✓ 诊断包已保存: %s（%s%s）" % (zip_path, who, tail)
