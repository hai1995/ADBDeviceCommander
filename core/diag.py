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
  uptime）复用 core.devinfo 的单次 shell 脚本；整个诊断包共 5 次调用，
  USB 上约 3~6 秒。
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
F_APPS = "apps.txt"          # 已安装应用（第三方优先）
F_ANR = "anr.txt"            # 前台 Activity / ANR / tombstone 线索
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
    lines = ["第三方应用：%d 个" % len(third)]
    if total:
        lines.append("全部应用：%d 个" % len(total))
    lines.append("")
    lines.append("== 第三方应用包名 ==")
    lines.extend(["  " + n for n in sorted(third)] or ["  （无）"])
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
                           F_ANR, F_META):
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
