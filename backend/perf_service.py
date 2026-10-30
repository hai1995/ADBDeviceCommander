# -*- coding: utf-8 -*-
"""
backend.perf_service —— 设备性能实时采样（CPU / 内存 / FPS / 电量 / 温度）
================================================================================
定位与 PerfDog 同类：**只读、不注入、不改设备**，全部指标都用系统自带的
`/proc` 与 `dumpsys` 采集，因此任何一台开了 USB 调试的 Android 都能用。

一、指标怎么来的（每条都有坑，写在对应函数里）
  * CPU（整机）      /proc/stat 两次采样的 jiffies 差分，1 - Δidle/Δtotal。
                     不用 `top`：`top -n 1` 在部分 ROM 上首帧恒为 0，且它自己
                     就要吃几十毫秒 CPU，测出来的数字是被自己污染过的。
  * 应用 CPU         /proc/<pid>/stat 的 utime+stime 差分 ÷ 整机 Δtotal。
                     与 `dumpsys cpuinfo` 的口径一致（占整机能力的百分之几）。
  * 系统内存         /proc/meminfo 的 MemTotal - MemAvailable。用 MemAvailable
                     而不是 MemFree：Linux 会把空闲页拿去做缓存，MemFree 常年
                     只有几百 MB，按它算「内存占用 95%」是假警报。
  * 应用内存（PSS）  `dumpsys meminfo <pkg>` 的 TOTAL 行。PSS 把共享库按比例
                     摊到各进程，是 Android 上唯一不会重复计算的口径。
  * 帧率             `dumpsys gfxinfo <pkg>` 的 `Total frames rendered` 计数差分
                     ÷ 采样间隔。**必须用差分**：gfxinfo 给的是自进程启动以来的
                     累计值，直接读会得到「开了一小时 = 3600 帧」这种没法看的数。
  * 卡顿率           `Janky frames: N (x%)`，同一份 gfxinfo 里就有。曲线画的是
                     **区间值**（Δ卡顿帧 ÷ Δ总帧），不是那个累计百分比：累计值
                     挂机久了几乎不动，看不出「刚才那一下卡」。累计值另存
                     `jank_cum` 一并进 CSV，两种口径都留档。
  * 电量 / 温度      `dumpsys battery`，温度单位是**0.1℃**（310 = 31.0℃）。

二、为什么一次采样只调一次 adb
  1Hz 采样下如果每个指标各起一个 adb 进程，光进程创建就要几百毫秒，采样间隔
  会被拖成 2~3 秒，曲线全是台阶。这里把各项命令拼成一个 shell 脚本，用
  `echo @@XXX` 做分段标记，一次 `adb shell` 全部取回（约 150~400ms）。跟随前台
  时前台包名探测也并到同一条脚本里（@@FOCUS），不再为它额外起一个 adb 进程。
  代价是**指标之间最多差 300ms**——对趋势图完全够用，对逐帧归因不够（那本来
  也不是本功能的定位）。

三、进程模型
  PerfMonitor 一条后台线程 + 环形缓冲（MAX_SAMPLES）。前端按 seq 增量拉取
  （perf_poll），不把样本塞进事件总线：1Hz × 多指标走 JSON 事件桥会白白占用
  日志/状态的队列预算，而监控数据本来就是「拉」比「推」更合适的形态。
"""
import csv
import datetime
import os
import re
import subprocess
import threading
import time
from collections import deque

from core.constants import adb_kwargs

# 环形缓冲上限：1Hz 约 5.5 小时。够长（够挂机跑一夜），又不会把内存吃穿
# （单样本 ~200B，20000 条约 4MB）。
MAX_SAMPLES = 20000
DEFAULT_INTERVAL = 1.0
MIN_INTERVAL = 0.2
MAX_INTERVAL = 10.0
# 「监控全系统」的哨兵包名：故意不绑任何进程，只采整机指标（CPU / 系统内存 /
# 电量 / 温度）。应用级指标（PSS / 帧率 / 卡顿）在这一模式下没有意义（一个
# 「整机帧率」既不是某一帧率、也没法差分），故一律留空而不是拿别的数据顶上。
SYSTEM_PKG = "__system__"
# 连续失败多少次判定设备掉了（一次抖动不打断监控）
MAX_FAILS = 3

# 包名白名单：它会直接拼进设备端 shell 脚本，绝不能让 `;`、`$()`、反引号
# 之类的东西漏进去（那等于给设备执行任意命令的口子）。
_PKG_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.]*$")

# 指标元数据：key -> (标题, 单位, 固定上限或 None)
METRICS = (
    ("cpu", "CPU", "%", 100.0),
    ("mem_used", "系统内存", "MB", None),
    ("pss", "应用内存", "MB", None),
    ("fps", "帧率", "FPS", None),
    ("jank", "卡顿率", "%", None),
    ("batt", "电量", "%", 100.0),
    ("temp", "电池温度", "℃", None),
)
METRIC_LABEL = {k: t for k, t, _u, _m in METRICS}

# 内置告警阈值。取值不是「教科书标准」，而是「拿这份报告去验收时会被问的那几条」：
#   * 帧率 < 45：60Hz 屏掉到 45 以下，滑动已经能被肉眼看出不跟手；
#                120Hz 屏同理，卡到 45 就是掉帧掉一半。
#   * 卡顿率 > 8%：gfxinfo 的 janky 口径偏宽松，8% 已经意味着每 12 帧卡 1 帧。
#   * 温度 > 42℃：电池 42℃ 以上开始降频，性能数据会自己变差（噪声来源）。
#   * CPU > 85%：留 15% 余量，超过后系统调度开始互相抢占，帧率会连锁下跌。
# 键与 METRICS 对齐；min 表示「低于即告警」，max 表示「高于即告警」。
DEFAULT_THRESHOLDS = {
    "fps": {"min": 45.0},
    "jank": {"max": 8.0},
    "temp": {"max": 42.0},
    "cpu": {"max": 85.0},
}
# 可配置阈值的 4 项：方向（min = 低于即告警 / max = 高于即告警）、说明、合法范围。
# 顺序即界面上的展示顺序（也是「最常被问到的」顺序：先看帧率，再看卡顿）。
# 说明文案写在这里而不是前端：用户改阈值时看到的理由与报告里的口径必须是同一份。
THRESHOLD_META = (
    ("fps", "min", (1.0, 240.0), "60Hz 屏掉到 45 以下，滑动已经能被肉眼看出不跟手"),
    ("jank", "max", (0.0, 100.0), "gfxinfo 口径偏宽松，8% 已意味着每 12 帧卡 1 帧"),
    ("temp", "max", (0.0, 90.0), "电池 42℃ 以上开始降频，性能数据会自己变差"),
    ("cpu", "max", (1.0, 100.0), "留 15% 余量，超过后系统调度互相抢占、帧率连锁下跌"),
)
_THRESHOLD_META = dict((k, (d, r, h)) for k, d, r, h in THRESHOLD_META)

# 超标点数占比达到该值升级为严重（crit）：零星几点抖动是常态，
# 占比超过 1/4 说明是持续性问题，不是偶发。
ALERT_CRIT_RATIO = 25.0

# 「全部关闭」的显式写法。空字符串表示「用内置基线」，因此不能用空串表达
# 「一条都不要」——两者语义相反，混用会让用户清空输入框后告警奇迹般复活。
THRESHOLDS_OFF = "off"
_TH_EXPR_RE = re.compile(r"^([a-z_]+)\s*([<>])\s*(-?\d+(?:\.\d+)?)$")

# 纯解析函数跑在采样热路径上，下面这些正则只编译一次，避免每次调用都 re.compile。
_NUM_RE = re.compile(r"\d+")
_GFX_NUM_RE = re.compile(r"(\d+)")
_GFX_PCT_RE = re.compile(r"\(([\d.]+)%\)")
_FOCUS_RE = re.compile(r"u\d+\s+([A-Za-z0-9_.]+)/")
_WM_SIZE_RE = re.compile(r"(\d+x\d+)")


# --------------------------------------------------------------------------- #
# 纯解析（全部无副作用，单测直接喂字符串）
# --------------------------------------------------------------------------- #
def parse_proc_stat(text):
    """/proc/stat 首行 -> {"total": jiffies, "idle": jiffies}；失败返回 None。

    字段序（内核固定）：user nice system idle iowait irq softirq steal guest
    guest_nice。total 取前 8 项：guest/guest_nice 已经包含在 user/nice 里，
    再加一遍会让总时间虚高、CPU% 偏低（`top` 也是这么处理的）。
    """
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("cpu "):
            continue
        parts = line.split()[1:]
        try:
            nums = [int(x) for x in parts[:8]]
        except ValueError:
            return None
        if len(nums) < 4:
            return None
        total = sum(nums)
        idle = nums[3] + (nums[4] if len(nums) > 4 else 0)   # idle + iowait
        return {"total": total, "idle": idle}
    return None


def parse_pid_stat(text):
    """/proc/<pid>/stat -> 进程累计 jiffies（utime + stime）；失败返回 None。

    comm 字段里可能有空格和括号（例如 `(Web Content)`），所以不能整行 split，
    必须从**最后一个 ')'** 之后开始切：那时的第 1 个字段是 state，utime 是
    第 12 个（内核字段号 14）。
    """
    if not text:
        return None
    close = text.rfind(")")
    if close < 0:
        return None
    parts = text[close + 1:].split()
    if len(parts) < 13:
        return None
    try:
        return int(parts[11]) + int(parts[12])
    except ValueError:
        return None


def parse_meminfo(text):
    """/proc/meminfo -> {"total_mb", "used_mb"}；缺字段返回 None。"""
    kv = {}
    for line in (text or "").splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        num = v.strip().split()
        if not num:
            continue
        try:
            kv[k.strip()] = int(num[0])          # kB
        except ValueError:
            continue
    total = kv.get("MemTotal")
    avail = kv.get("MemAvailable")
    if total is None and avail is None:
        return None
    if total is None:
        return None
    if avail is None:
        # 老内核没有 MemAvailable：用 Free + Buffers + Cached 近似（与内核对
        # MemAvailable 的估算思路一致，比单看 MemFree 准得多）。
        avail = (kv.get("MemFree", 0) + kv.get("Buffers", 0)
                 + kv.get("Cached", 0))
    return {"total_mb": round(total / 1024.0, 1),
            "used_mb": round(max(0, total - avail) / 1024.0, 1)}


def parse_dumpsys_meminfo(text):
    """`dumpsys meminfo <pkg>` -> 总 PSS（MB）；解析不到返回 None。

    两种输出形态都要认：
      * App Summary 的 `TOTAL    45678    40000 ...`（数值在行首列）
      * 老版本 / 完整输出的 `TOTAL PSS:   45678`
    """
    for line in (text or "").splitlines():
        s = line.strip()
        if not s.upper().startswith("TOTAL"):
            continue
        nums = _NUM_RE.findall(s)
        if not nums:
            continue
        try:
            return round(int(nums[0]) / 1024.0, 1)
        except ValueError:
            continue
    return None


def parse_gfxinfo_detail(text):
    """`dumpsys gfxinfo <pkg>` -> (累计帧数, 累计卡顿帧数, 累计卡顿率%)。

    三个值分别可能为 None：`Janky frames` 行在部分 ROM / 部分版本上不存在，
    此时卡顿率整条曲线只能断在那里。累计卡顿帧数是算**区间卡顿率**的关键：
    只有百分比是没法差分的（百分比的差分没有物理意义）。
    """
    frames = None
    janky = None
    pct = None
    for line in (text or "").splitlines():
        s = line.strip()
        low = s.lower()
        if low.startswith("total frames rendered"):
            m = _GFX_NUM_RE.search(s)
            if m:
                frames = int(m.group(1))
        elif low.startswith("janky frames"):
            m = _GFX_NUM_RE.search(s)
            if m:
                janky = int(m.group(1))
            m2 = _GFX_PCT_RE.search(s)
            if m2:
                try:
                    pct = float(m2.group(1))
                except ValueError:
                    pct = None
    return frames, janky, pct


def parse_gfxinfo(text):
    """`dumpsys gfxinfo <pkg>` -> (累计帧数, 卡顿率%)；解析不到返回 (None, None)。"""
    frames, _janky, pct = parse_gfxinfo_detail(text)
    return frames, pct


def jank_window(prev_janky, cur_janky, dframes, cum_pct, min_frames=5):
    """区间卡顿率：**新增的那些帧**里卡顿帧占百分之几。

    为什么不用 gfxinfo 直接给的百分比：那是「自应用启动以来」的累计水位，
    挂机监控两小时后，哪怕最近十分钟一直卡到掉帧，那条线也几乎不动——
    它反映的是历史平均，不是「现在卡不卡」。

    三种退回累计值的情形（都返回 cum_pct，而不是 None 断线）：
      * 没有卡顿帧数（老 ROM 只给百分比）；
      * 新增帧太少（界面静止，音乐播放页常见）——此时区间率没有统计意义；
      * 计数回退（应用重启，gfxinfo 归零）。
    """
    if prev_janky is None or cur_janky is None or dframes is None:
        return cum_pct
    dj = cur_janky - prev_janky
    if dframes < min_frames or dj < 0:
        return cum_pct
    return round(min(100.0, dj * 100.0 / float(dframes)), 1)


def parse_battery(text):
    """`dumpsys battery` -> {"batt": %, "temp": ℃, "status": int}；无电量返回 None。

    温度字段是**十分之一摄氏度**（310 = 31.0℃）。很多文档只写 "temperature"，
    不写单位，直接拿来画图会得到「310 度」的离谱曲线。
    """
    level = None
    temp = None
    status = None
    for line in (text or "").splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip().lower()
        v = v.strip()
        try:
            if k == "level":
                level = int(v)
            elif k == "temperature":
                temp = round(int(v) / 10.0, 1)
            elif k == "status":
                status = int(v)
        except ValueError:
            continue
    if level is None and temp is None:
        return None
    return {"batt": level, "temp": temp, "status": status}


def parse_focus_pkg(text):
    """`dumpsys window` 里取前台应用包名；解析不到返回 ""。

    Android 10+ 是 `mCurrentFocus=Window{... u0 com.foo/com.foo.MainActivity}`，
    更老的版本用 `mFocusedApp=ActivityRecord{... u0 com.foo/.Main}`。两种都认，
    优先 mCurrentFocus（它才是真正有输入焦点的窗口）。
    """
    cur = ""
    for line in (text or "").splitlines():
        for key in ("mCurrentFocus", "mFocusedApp"):
            idx = line.find(key)
            if idx < 0:
                continue
            seg = line[idx:]
            m = _FOCUS_RE.search(seg)
            if m:
                if key == "mCurrentFocus":
                    return m.group(1)
                cur = cur or m.group(1)
    return cur


def parse_wm_size(text):
    """`wm size` -> "1080x2340"（优先 Override size）；解析不到返回 ""。"""
    override = ""
    physical = ""
    for line in (text or "").splitlines():
        m = _WM_SIZE_RE.search(line)
        if not m:
            continue
        if "override" in line.lower():
            override = m.group(1)
        elif "physical" in line.lower():
            physical = m.group(1)
    return override or physical


def pkg_display(info):
    """「监控应用」一行怎么显示（报告正文 + 状态栏共用）。

    三种模式必须一眼分得清，否则报告里只写一个包名，读者无法判断这份数据是
    「锁定某个应用」采的、还是「跟随前台」中途换过应用采的：
      * system  —— 全系统，不绑进程，只有整机指标；
      * auto    —— 跟随前台（包名是启动时探测到的那个，可能随操作切换）；
      * manual  —— 手选包名，全程锁定；
    老数据（升级前采的、没有 pkg_mode 字段）按「有包名就显示包名」处理。
    """
    info = info or {}
    mode = info.get("pkg_mode") or ""
    pkg = (info.get("pkg") or "").strip()
    if mode == "system":
        return "全系统（仅整机指标）"
    if pkg:
        return ("%s（跟随前台）" % pkg) if mode == "auto" else pkg
    if mode == "auto":
        return "跟随前台（未探测到）"
    return "（整机）"


_PM_LINE_RE = re.compile(r"^package:\s*(\S+)\s*$")


def parse_package_list(text):
    """`pm list packages` 输出 -> 包名列表（去重 + 排序 + 白名单校验）。

    行格式是 `package:com.foo.bar`；个别 ROM 会多带一段 `uid:`。解析不出来的
    行直接丢，绝不让它混进下拉框（包名最终要拼进设备端 shell 脚本）。
    """
    seen = set()
    for line in (text or "").splitlines():
        m = _PM_LINE_RE.match(line.strip())
        if not m:
            continue
        pkg = m.group(1)
        if _PKG_RE.match(pkg):
            seen.add(pkg)
    return sorted(seen)


def list_packages(adb="adb", serial="", timeout=12):
    """读设备上已安装的应用包名：一次 adb 调用同时取「第三方」与「全部」。

    为什么要两个清单：性能测试盯的基本都是被测 App（第三方），把几百个系统
    应用一起堆进下拉框只会稀释搜索结果；但偶尔也要监控系统应用（比如对比
    系统相机 / 桌面），所以全量清单一并取回，由前端用「含系统应用」开关切换，
    切的时候不再走一次 adb。

    返回 {ok, third, system, total}；失败返回 {ok: False, reason}（人话原因），
    绝不外抛 —— 调用方是界面按钮，抛出去只会变成一个没人看得懂的报错框。
    """
    script = ("echo @@TP; pm list packages -3 2>/dev/null; "
              "echo @@ALL; pm list packages 2>/dev/null")
    args = [adb or "adb"]
    if serial:
        args += ["-s", serial]
    args += ["shell", script]
    try:
        r = subprocess.run(args, **adb_kwargs(timeout))
    except Exception as ex:
        return {"ok": False, "reason": "adb 调用失败：%s" % ex}
    if getattr(r, "returncode", 0) != 0:
        err = (r.stderr or "").strip() or (r.stdout or "").strip()
        return {"ok": False,
                "reason": "读取应用列表失败：%s" % (err[:120] or "adb 返回非零")}
    sec = _split_sections(r.stdout or "")
    third = parse_package_list(sec.get("TP", ""))
    every = parse_package_list(sec.get("ALL", ""))
    tset = set(third)
    system = [p for p in every if p not in tset]
    if not every and not third:
        return {"ok": False, "reason": "设备上没有读到任何应用（是否已授权？）"}
    return {"ok": True, "third": third, "system": system,
            "total": len(set(every) | tset)}


def cpu_percent(prev, cur):
    """两次 /proc/stat 采样 -> 整机 CPU 使用率（0~100）。数据不足返回 None。"""
    if not prev or not cur:
        return None
    dt = cur["total"] - prev["total"]
    di = cur["idle"] - prev["idle"]
    if dt <= 0:
        return None
    pct = (1.0 - float(di) / float(dt)) * 100.0
    if pct < 0:
        return 0.0
    if pct > 100:
        return 100.0
    return round(pct, 1)


def app_cpu_percent(prev_proc, cur_proc, prev_total, cur_total):
    """进程 jiffies 差分 ÷ 整机差分 -> 应用 CPU 占整机的百分比。

    与 `dumpsys cpuinfo` 同口径（所有进程加起来约等于整机 CPU）。进程刚重启
    （计数归零）时差分为负，返回 None 让前端断点，而不是画一个 -30% 的坑。
    """
    if None in (prev_proc, cur_proc, prev_total, cur_total):
        return None
    dp = cur_proc - prev_proc
    dt = cur_total - prev_total
    if dt <= 0 or dp < 0:
        return None
    pct = float(dp) / float(dt) * 100.0
    if pct < 0:
        return None
    return round(min(pct, 100.0), 1)


def fps_from_frames(prev_frames, cur_frames, dt_s):
    """累计帧数差分 ÷ 时间 -> FPS。计数回退（应用重启）返回 None。"""
    if prev_frames is None or cur_frames is None:
        return None
    if dt_s <= 0:
        return None
    df = cur_frames - prev_frames
    if df < 0:
        return None
    return round(df / float(dt_s), 1)


# --------------------------------------------------------------------------- #
# 采样器
# --------------------------------------------------------------------------- #
def _split_sections(raw):
    """把 `echo @@XXX` 分段输出拆成 {XXX: 文本}。"""
    out = {}
    name = None
    buf = []
    for line in (raw or "").splitlines():
        s = line.strip()
        if s.startswith("@@"):
            if name:
                out[name] = "\n".join(buf)
            name = s[2:].strip()
            buf = []
        elif name:
            buf.append(line)
    if name:
        out[name] = "\n".join(buf)
    return out


class PerfMonitor:
    """单台设备的性能采样会话（一台设备一条线程）。

    生命周期：start() -> 后台线程持续采样 -> stop()。数据留在内存里供
    snapshot() 增量拉取、导出报告时按全量使用。
    """

    def __init__(self, adb="adb", serial="", interval=DEFAULT_INTERVAL,
                 pkg="", on_status=None):
        self.adb = adb or "adb"
        self.serial = serial
        self.interval = min(MAX_INTERVAL, max(MIN_INTERVAL, float(interval)))
        user_pkg = (pkg or "").strip()
        # 全系统模式：既不是「跟随前台」也不是「锁定某应用」，单独一种状态。
        # （哨兵值不能落到 self.pkg 上 —— 那会被拼进 gfxinfo/meminfo 命令。）
        self.system_only = (user_pkg == SYSTEM_PKG)
        self.pkg = "" if self.system_only else (
            user_pkg if _PKG_RE.match(user_pkg or "") else "")
        self.auto_pkg = not self.pkg and not self.system_only
        self.mode = ("system" if self.system_only
                     else ("auto" if self.auto_pkg else "manual"))
        self.on_status = on_status
        self.info = {"serial": serial, "model": "", "android": "", "size": "",
                     "pkg": self.pkg, "pkg_mode": self.mode, "started_at": ""}
        self.error = ""
        self._samples = deque(maxlen=MAX_SAMPLES)
        self._seq = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._prev = {}            # 上一次采样的差分基线
        self._fails = 0

    # ---------------- 采集 ----------------
    def _run(self, args, timeout=8):
        return subprocess.run([self.adb, "-s", self.serial] + args,
                              **adb_kwargs(timeout))

    def _script(self):
        """拼设备端的采样脚本。pkg 已过白名单，可安全内插。

        跟随前台（auto_pkg）时每次都顺带探一次前台包名（@@FOCUS 段），与各项
        指标走同一条 adb 取回，不必为它单独再起一个 adb 进程（老实现每 10 次采样
        就多一次进程创建，纯属浪费）。前台包名只用于刷新后续采样的 pkg，本身不
        参与差分，因此拿不到（设备忙）时留空即可，不影响整机指标。

        GFX / PSS / PID 这些「按包名取数」的段，只在 pkg 已知时才拼进脚本——
        跟随前台但还没探到前台包名时，自然先只采整机指标。
        """
        # 仅跟随前台模式下带 @@FOCUS；其余模式（全系统 / 锁定包名）不需要。
        focus = ("echo @@FOCUS; dumpsys window 2>/dev/null | grep -E 'mCurrentFocus|mFocusedApp' | head -4; "
                 if self.auto_pkg else "")
        pkg = self.pkg
        if not pkg:
            return ("echo @@STAT; head -1 /proc/stat; "
                    "echo @@MEM; head -8 /proc/meminfo; "
                    + focus +
                    "echo @@BATT; dumpsys battery 2>/dev/null")
        return (
            "echo @@STAT; head -1 /proc/stat; "
            "echo @@MEM; head -8 /proc/meminfo; "
            "echo @@PID; P=$(pidof " + pkg + " 2>/dev/null | tr ' ' '\\n' | head -1); echo \"$P\"; "
            "echo @@PSTAT; [ -n \"$P\" ] && cat /proc/$P/stat 2>/dev/null; "
            "echo @@GFX; dumpsys gfxinfo " + pkg + " 2>/dev/null | head -80; "
            "echo @@PSS; dumpsys meminfo " + pkg + " 2>/dev/null | grep -E '^[[:space:]]*TOTAL' "
            "| head -3; "
            + focus +
            "echo @@BATT; dumpsys battery 2>/dev/null")

    def _read_device_info(self):
        try:
            r = self._run(["shell",
                           "getprop ro.product.model; getprop ro.build.version.release; "
                           "wm size 2>/dev/null"], timeout=8)
            lines = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
        except Exception:
            return
        if len(lines) >= 1:
            self.info["model"] = lines[0]
        if len(lines) >= 2:
            self.info["android"] = lines[1]
        for ln in lines[2:]:
            size = parse_wm_size(ln)
            if size:
                self.info["size"] = size
                break

    def _baseline(self):
        """先取一次差分基线，让第一帧就有真实 CPU% 而不是空白。

        跟随前台时顺手把前台包名也记下来（@@FOCUS 段就在同一条脚本里），免得
        _collect 第一帧还拿不到 pkg、采不到应用级指标。
        """
        try:
            raw = self._run(["shell", self._script()]).stdout
        except Exception:
            return
        sec = _split_sections(raw)
        self._prev = self._diff_state(sec)
        if self.auto_pkg:
            self._apply_focus(self._prev)

    def _diff_state(self, sec):
        stat = parse_proc_stat(sec.get("STAT", ""))
        proc = parse_pid_stat(sec.get("PSTAT", ""))
        frames, janky, jank_cum = parse_gfxinfo_detail(sec.get("GFX", ""))
        # 前台包名只在跟随前台模式下解析（system / manual 模式根本不含 @@FOCUS 段，
        # 解析了也没人用）；它不参与差分，纯属给下一帧刷新 pkg 用。
        focus = parse_focus_pkg(sec.get("FOCUS", "")) if self.auto_pkg else ""
        return {"t": time.time(), "stat": stat, "proc": proc,
                "frames": frames, "janky": janky, "jank_cum": jank_cum,
                "focus": focus}

    def _apply_focus(self, cur):
        """用本次采样探到的前台包名刷新 pkg（仅跟随前台模式、且确实探到时）。"""
        focus = cur.get("focus") or ""
        if focus and _PKG_RE.match(focus):
            self.pkg = focus
            self.info["pkg"] = focus

    def _collect(self):
        """采一次样，返回 sample dict（失败返回 None）。"""
        try:
            r = self._run(["shell", self._script()])
        except Exception as ex:
            self.error = "adb 调用失败：%s" % ex
            return None
        if getattr(r, "returncode", 0) != 0:
            err = (r.stderr or "").strip() or (r.stdout or "").strip()
            self.error = "设备无响应：%s" % (err[:120] or "adb 返回非零")
            return None
        sec = _split_sections(r.stdout or "")
        now = time.time()
        prev = self._prev or {}
        cur = self._diff_state(sec)
        if self.auto_pkg:
            self._apply_focus(cur)
        dt = (cur["t"] - prev.get("t", now)) if prev else self.interval
        mem = parse_meminfo(sec.get("MEM", ""))
        batt = parse_battery(sec.get("BATT", "")) or {}
        pss = parse_dumpsys_meminfo(sec.get("PSS", ""))
        # 直接复用 _diff_state 里已经解析好的 GFX 结果，不必再解析一次 @@GFX 段
        # （老实现这里重复调用了 parse_gfxinfo_detail，等于白干一遍字符串解析）。
        frames = cur["frames"]
        janky = cur["janky"]
        jank_cum = cur["jank_cum"]
        prev_frames = prev.get("frames")
        dframes = (frames - prev_frames
                   if frames is not None and prev_frames is not None else None)
        sample = {
            "t": round(now, 3),
            "cpu": cpu_percent(prev.get("stat"), cur["stat"]),
            "app_cpu": app_cpu_percent(
                prev.get("proc"), cur["proc"],
                (prev.get("stat") or {}).get("total"),
                (cur["stat"] or {}).get("total")),
            "mem_used": mem["used_mb"] if mem else None,
            "mem_total": mem["total_mb"] if mem else None,
            "pss": pss,
            "fps": fps_from_frames(prev_frames, frames, dt),
            "jank": jank_window(prev.get("janky"), janky, dframes, jank_cum),
            "jank_cum": jank_cum,
            "batt": batt.get("batt"),
            "temp": batt.get("temp"),
        }
        self._prev = cur
        self.error = ""
        return sample

    # ---------------- 线程 ----------------
    def start(self):
        """探测设备信息 + 取基线 + 起线程。返回 (ok, 错误说明）。"""
        self._read_device_info()
        self.info["started_at"] = datetime.datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S")
        self._baseline()
        if not self._prev.get("stat"):
            # 连 /proc/stat 都读不到：设备没授权 / 掉线 / adb 坏了。
            # 立刻报错，而不是留一条空线程让用户盯着空图表等。
            return False, self.error or "读取设备状态失败（设备是否已授权？）"
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="perf-%s" % self.serial)
        self._thread.start()
        return True, ""

    def _loop(self):
        while not self._stop.is_set():
            t0 = time.time()
            sample = self._collect()
            if sample is None:
                self._fails += 1
                if self._fails >= MAX_FAILS:
                    break
            else:
                self._fails = 0
                with self._lock:
                    self._seq += 1
                    sample["seq"] = self._seq
                    self._samples.append(sample)
            wait = self.interval - (time.time() - t0)
            if wait > 0:
                self._stop.wait(wait)
        # 线程退出 = 会话结束（主动 stop 或连续失败）
        if self.on_status and not self._stop.is_set():
            self.on_status("err", "性能监控已中断：%s" % (self.error or "设备无响应"))

    def stop(self):
        """停止采样并等线程退出（最多 3 秒，绝不死等）。"""
        self._stop.set()
        th = self._thread
        if th is not None and th.is_alive():
            th.join(timeout=3)

    def alive(self):
        th = self._thread
        return bool(th is not None and th.is_alive() and not self._stop.is_set())

    # ---------------- 取数 ----------------
    @property
    def seq(self):
        with self._lock:
            return self._seq

    def count(self):
        with self._lock:
            return len(self._samples)

    def snapshot(self, since=0):
        """返回 seq > since 的增量样本 + 会话信息。"""
        try:
            since = int(since or 0)
        except (TypeError, ValueError):
            since = 0
        with self._lock:
            out = [dict(s) for s in self._samples if s.get("seq", 0) > since]
            seq = self._seq
        return {"running": self.alive(), "seq": seq, "samples": out,
                "info": dict(self.info), "error": self.error,
                "interval": self.interval, "count": self.count()}

    def all_samples(self):
        with self._lock:
            return [dict(s) for s in self._samples]


# --------------------------------------------------------------------------- #
# 统计与报告
# --------------------------------------------------------------------------- #
def _values(samples, key):
    out = []
    for s in samples:
        v = s.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out.append(float(v))
    return out


def summarize(values):
    """-> {"min","avg","max","p95","n"}；空数据返回 None。

    P95 用「最近秩」法（不进位到两端），比线性插值简单且样本少时也不会
    被插出一个数据里根本不存在的极值。
    """
    if not values:
        return None
    vals = sorted(values)
    n = len(vals)
    idx = min(n - 1, max(0, int(round(0.95 * (n - 1)))))
    return {"min": round(vals[0], 1), "max": round(vals[-1], 1),
            "avg": round(sum(vals) / n, 1), "p95": round(vals[idx], 1), "n": n}


def metric_summary(samples):
    """六个指标各自的统计（无数据的指标为 None）。"""
    return {k: summarize(_values(samples, k)) for k, _t, _u, _m in METRICS}


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def threshold_rule_text(key, rule):
    """-> "FPS < 45" / "卡顿率 > 8%"（给报告与前端 tooltip 共用同一份措辞）。"""
    unit = {k: u for k, _t, u, _m in METRICS}.get(key, "")
    label = METRIC_LABEL.get(key, key)
    if isinstance(rule.get("min"), (int, float)):
        return "%s %s < %s" % (label, unit, _fmt(rule["min"]))
    if isinstance(rule.get("max"), (int, float)):
        return "%s %s > %s" % (label, unit, _fmt(rule["max"]))
    return label


def format_thresholds(thresholds):
    """阈值 dict -> 单行表达式（写进 config.json 的那一份）。

    用 `fps<45,jank>8` 这种写法而不是 JSON 对象，是为了让用户在 config.json
    里一眼看懂、直接手改：嵌套对象既不好读，也要靠缩进去猜结构。
    """
    def num(v):
        # "%g" 而不是 _fmt：_fmt 的 int 分支会写成 "50.0"（报表里要一位小数），
        # 而配置文本里 `fps<50.0` 看着像有意保留小数，其实是格式噪声。
        return "%g" % float(v)

    parts = []
    for key, _dir, _rng, _hint in THRESHOLD_META:
        rule = (thresholds or {}).get(key) or {}
        if _is_num(rule.get("min")):
            parts.append("%s<%s" % (key, num(rule["min"])))
        elif _is_num(rule.get("max")):
            parts.append("%s>%s" % (key, num(rule["max"])))
    return ",".join(parts) if parts else THRESHOLDS_OFF


def default_threshold_expr():
    """内置基线的表达式文本（前端「恢复默认」与配置模板共用）。"""
    return format_thresholds(DEFAULT_THRESHOLDS)


def parse_thresholds(expr, strict=False):
    """表达式 -> (阈值 dict, 错误列表)。

    * 空串 / None：用内置基线（= 用户没配过，与其它配置项的语义一致）；
    * "off" / "none"：全部关闭，返回空 dict；
    * 其余：**覆盖式**解析 —— 表达式里没提到的指标就不告警。这样「删掉一段」
      等于「关掉这条」，与界面上取消勾选完全对应，不会出现「删了却还在告警」。
    * strict=True 时，任何一段无法解析都把整条表达式判为非法（返回内置基线 +
      错误），用于「用户刚提交的设置」；strict=False 用于读历史配置，能救则救
      （部分段落无效时保留其余有效段落，并把错误抛给调用方去提示）。
    """
    raw = (expr or "").strip() if isinstance(expr, str) else ""
    errors = []
    if not raw:
        return dict((k, dict(v)) for k, v in DEFAULT_THRESHOLDS.items()), errors
    if raw.lower() in (THRESHOLDS_OFF, "none", "false", "0"):
        return {}, errors

    out, unparsed = {}, []
    for seg in re.split(r"[,;\s]+", raw):
        if not seg:
            continue
        m = _TH_EXPR_RE.match(seg.strip())
        if not m:
            # 连 `key<数字` 的形状都不是（拼错、中文、多余字符）：单独记，
            # 否则用户改错一个字符时界面拿到的 errors 是空数组 —— 界面会把
            # 它当成功，用户以为改好了，实际仍按基线判。
            unparsed.append(seg)
            continue
        key, op, num = m.group(1), m.group(2), float(m.group(3))
        meta = _THRESHOLD_META.get(key)
        if meta is None:
            errors.append("未知指标 %s（可选：%s）"
                          % (key, "、".join(k for k, _d, _r, _h in THRESHOLD_META)))
            continue
        want_dir, (lo, hi), _hint = meta
        if (op == "<") != (want_dir == "min"):
            errors.append("%s 只能用「%s」（%s）"
                          % (METRIC_LABEL.get(key, key),
                             "<" if want_dir == "min" else ">",
                             "低于即告警" if want_dir == "min" else "高于即告警"))
            continue
        if not (lo <= num <= hi):
            errors.append("%s 的阈值 %s 超出合理范围 %s~%s"
                          % (METRIC_LABEL.get(key, key), _fmt(num),
                             _fmt(lo), _fmt(hi)))
            continue
        out[key] = {"min" if op == "<" else "max": num}

    if unparsed:
        errors.append("无法识别的写法：%s（应形如 fps<45 或 jank>8）"
                      % "、".join(unparsed))
    if errors and strict:
        return dict((k, dict(v)) for k, v in DEFAULT_THRESHOLDS.items()), errors
    return out, errors


def build_thresholds(values):
    """界面提交的 {key: 数值或 None} -> (阈值 dict, 错误列表)。

    与 parse_thresholds 的分工：界面给的是结构化数字（不必拼表达式再解析回来），
    但仍要走同一套校验，否则「界面能存、手改 config.json 却被拒」两套标准。
    未提供 / None / 空串 = 关闭该条。
    """
    th, errors = {}, []
    if not isinstance(values, dict):
        return {}, ["阈值格式不正确"]
    for key, direction, (lo, hi), _hint in THRESHOLD_META:
        if key not in values:
            continue
        v = values[key]
        if v is None or (isinstance(v, str) and not v.strip()):
            continue
        if isinstance(v, str):
            try:
                v = float(v.strip())
            except ValueError:
                errors.append("%s 的阈值不是数字：%r" % (METRIC_LABEL.get(key, key), v))
                continue
        if isinstance(v, bool) or not _is_num(v):
            errors.append("%s 的阈值不是数字：%r" % (METRIC_LABEL.get(key, key), v))
            continue
        if not (lo <= float(v) <= hi):
            errors.append("%s 的阈值 %s 超出合理范围 %s~%s"
                          % (METRIC_LABEL.get(key, key), _fmt(float(v)),
                             _fmt(lo), _fmt(hi)))
            continue
        th[key] = {direction: float(v)}
    return th, errors


def threshold_items(thresholds=None):
    """给界面的可编辑项清单（4 条，含当前值 / 方向 / 说明 / 合法范围）。

    前端不硬编码这四行：方向（< 还是 >）、单位、取值范围与理由都在后端，
    两边各抄一份必然漂移 —— 最后会出现「界面写 45、报告按 50 判定」。
    """
    th = DEFAULT_THRESHOLDS if thresholds is None else thresholds
    items = []
    for key, direction, (lo, hi), hint in THRESHOLD_META:
        rule = (th or {}).get(key) or {}
        value = rule.get("min") if direction == "min" else rule.get("max")
        items.append({
            "key": key,
            "title": METRIC_LABEL.get(key, key),
            "unit": {k: u for k, _t, u, _m in METRICS}.get(key, ""),
            "dir": direction,
            "value": value if _is_num(value) else None,
            "default": (DEFAULT_THRESHOLDS.get(key) or {}).get(direction),
            "min": lo,
            "max": hi,
            "hint": hint,
        })
    return items


def evaluate_alerts(samples, thresholds=None):
    """按阈值挑出超标项，返回告警列表（按超标占比降序）。

    每项：key / title / rule / count / total / ratio / worst / level /
          longest_s / first_t。
    「最长持续」按样本时间差算：把连续超标的样本串起来，用该段首尾时间差
    计量；末尾仍在超标的那一段，用最后一个样本时刻收尾（至少计一个采样间隔
    的一半，否则单点告警会显示 0 秒）。
    """
    th = DEFAULT_THRESHOLDS if thresholds is None else thresholds
    out = []
    if not samples:
        return out
    for key, rule in th.items():
        if not rule:
            continue
        lo, hi = rule.get("min"), rule.get("max")
        if lo is None and hi is None:
            continue
        pts = [(s.get("t") or 0.0, s.get(key)) for s in samples if _is_num(s.get(key))]
        if not pts:
            continue

        def is_bad(v):
            return ((lo is not None and v < lo) or (hi is not None and v > hi))

        bad = [(t, v) for t, v in pts if is_bad(v)]
        if not bad:
            continue
        worst = min(v for _t, v in bad) if lo is not None else max(
            v for _t, v in bad)

        # 最长连续超标时长
        longest = 0.0
        run_start = None
        prev_t = None
        for t, v in pts:
            if is_bad(v):
                if run_start is None:
                    run_start = t
                prev_t = t
            elif run_start is not None:
                longest = max(longest, max(0.0, prev_t - run_start))
                run_start = None
        if run_start is not None:
            longest = max(longest, max(0.0, prev_t - run_start))
        if longest <= 0 and len(pts) > 1:
            # 只有单点超标：用平均采样间隔兜个底，别显示「持续 0 秒」
            span = pts[-1][0] - pts[0][0]
            longest = span / float(max(1, len(pts) - 1))

        ratio = round(len(bad) * 100.0 / len(pts), 1)
        out.append({
            "key": key,
            "title": METRIC_LABEL.get(key, key),
            "rule": threshold_rule_text(key, rule),
            "count": len(bad),
            "total": len(pts),
            "ratio": ratio,
            "worst": round(worst, 1),
            "level": "crit" if ratio >= ALERT_CRIT_RATIO else "warn",
            "longest_s": round(longest, 1),
            "first_t": bad[0][0],
        })
    out.sort(key=lambda a: (-a["ratio"], a["key"]))
    return out


def _fmt(v, unit=""):
    if v is None:
        return "--"
    if isinstance(v, float) and abs(v - round(v)) < 1e-9:
        return "%d%s" % (int(round(v)), unit)
    return "%.1f%s" % (v, unit)


def _fmt_tick(v, span):
    """纵轴刻度：按量程决定小数位。

    内存动辄 4000~5000 MB，固定一位小数的刻度会写成一列 `5020.6 / 4909.7 /
    4798.0`——满屏噪音，反而看不出趋势。量程大用整数，量程小（FPS 52~60）
    才保留小数。
    """
    try:
        span = float(span)
    except (TypeError, ValueError):
        span = 0.0
    if span >= 20:
        return "%d" % int(round(v))
    if span >= 2:
        return ("%.1f" % v).rstrip("0").rstrip(".")
    return ("%.2f" % v).rstrip("0").rstrip(".")


def _ts(sec, fmt="%H:%M:%S"):
    return datetime.datetime.fromtimestamp(sec, datetime.timezone.utc).astimezone().strftime(fmt)


def _hover_strips(cells, y, ih, title_fn):
    """把「像素列 → (时间, 数据)」画成一排透明热区，浏览器原生 <title> 出提示。

    不逐点放热区 —— 两万个采样点就是两万个 rect，报告体积与渲染都吃不消；
    按**像素列**合并后热区数量恒定不超过图表宽度，且相邻列首尾相接铺满整张
    绘图区，鼠标停在曲线上任意位置都有提示。不写一行脚本：报告是双击打开的
    离线文件，靠 SVG 内置的 <title> 就能出 tooltip，「双击即可看」仍然成立。
    cells: {像素列x: (时间戳秒, 数据)}；title_fn(t, data) → 提示文本；
    y/ih 热区纵向范围。
    """
    if not cells:
        return []
    xs = sorted(cells)
    out = []
    for k, cx in enumerate(xs):
        left = cx if k == 0 else (xs[k - 1] + 1 + cx) // 2
        right = cx if k == len(xs) - 1 else max(cx, (cx + xs[k + 1]) // 2)
        t, data = cells[cx]
        out.append(
            '<rect x="%d" y="%d" width="%d" height="%d" fill="transparent">'
            '<title>%s</title></rect>'
            % (left, y, max(1, right - left + 1), ih, esc_html(title_fn(t, data))))
    return out


def _svg_chart(samples, key, color, unit, cap=None, w=760, h=170, rule=None):
    """把一条指标画成内联 SVG（面积 + 折线 + 网格 + 首尾时间 + 超标色带 +
    悬停提示）。鼠标停在图上任意位置会浮出该时刻的时间与读数（SVG 原生
    <title>，不需要脚本）。

    None 值（设备断连 / 应用重启）会**断开**折线而不是连成一条假的直线——
    报告里最忌讳把「没数据」画成「数据很好」。
    """
    pts = []
    for i, s in enumerate(samples):
        v = s.get(key)
        pts.append((i, float(v) if isinstance(v, (int, float))
                    and not isinstance(v, bool) else None))
    vals = [v for _i, v in pts if v is not None]
    if len(vals) < 2:
        return ('<div class="nochart">采样点不足，无法绘制曲线</div>')

    # 阈值：既画成虚线，也**纳入纵轴量程** —— 只画线不扩量程的话，读数远离
    # 阈值时（FPS 稳定 58，阈值 45）自动缩放会把线挤出画布，恰恰在最该看见
    # 它「合格」的时候消失。
    th_val, th_dir = None, None
    if rule:
        for k in ("min", "max"):
            if _is_num(rule.get(k)):
                th_val, th_dir = float(rule[k]), k

    lo, hi = min(vals), max(vals)
    if cap is not None:
        lo, hi = 0.0, float(cap)
    elif hi - lo < 1e-9:
        lo, hi = lo - 1, hi + 1
    else:
        pad = (hi - lo) * 0.12
        lo, hi = max(0.0, lo - pad), hi + pad
    if th_val is not None and cap is None:
        span = max(1.0, hi - lo)
        if th_val < lo:
            lo = max(0.0, th_val - span * 0.08)
        elif th_val > hi:
            hi = th_val + span * 0.08

    def is_bad(v):
        if th_val is None or v is None:
            return False
        return v < th_val if th_dir == "min" else v > th_val

    pad_l, pad_r, pad_t, pad_b = 44, 10, 12, 20
    iw, ih = w - pad_l - pad_r, h - pad_t - pad_b
    n = max(1, len(pts) - 1)

    def x_of(i):
        return pad_l + iw * (i / n)

    def y_of(v):
        return pad_t + ih * (1 - (v - lo) / (hi - lo))

    # 网格 + 纵轴刻度（4 段）
    grid = []
    for k in range(5):
        val = lo + (hi - lo) * k / 4.0
        y = y_of(val)
        grid.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#1d2836" '
                    'stroke-width="1"/>' % (pad_l, y, w - pad_r, y))
        grid.append('<text x="%d" y="%.1f" fill="#6e8299" font-size="9" '
                    'text-anchor="end" font-family="monospace">%s</text>'
                    % (pad_l - 6, y + 3, _fmt_tick(val, hi - lo)))

    # 超标色带：把「哪一段不达标」画成红色竖条，比让读者自己去和虚线比高低
    # 直观得多。同一段连续超标的点合并成一条色带（逐点画会在密集处叠出发黑的
    # 矩形，反而看不出边界）；单点超标的宽度兜底为一个采样间隔，否则宽度为 0
    # 什么都看不见 —— 「偶发掉一帧」恰恰是最需要被看见的。
    bands = []
    if th_val is not None:
        step = iw / float(max(1, len(pts) - 1))
        i = 0
        while i < len(pts):
            if not is_bad(pts[i][1]):
                i += 1
                continue
            j = i
            while j + 1 < len(pts) and is_bad(pts[j + 1][1]):
                j += 1
            x1, x2 = x_of(i), x_of(j)
            if x2 - x1 < 2.0:
                x2 = x1 + max(2.0, step)
            bands.append('<rect x="%.1f" y="%d" width="%.1f" height="%d" '
                         'fill="#ff5f6b" opacity=".12"/>'
                         % (x1, pad_t, x2 - x1, ih))
            i = j + 1

    # 折线（按 None 切段）
    segs, cur = [], []
    for i, v in pts:
        if v is None:
            if cur:
                segs.append(cur)
                cur = []
        else:
            cur.append((x_of(i), y_of(v)))
    if cur:
        segs.append(cur)
    lines, areas = [], []
    for seg in segs:
        if len(seg) == 1:
            lines.append('<circle cx="%.1f" cy="%.1f" r="1.6" fill="%s"/>'
                         % (seg[0][0], seg[0][1], color))
            continue
        d = "M" + " L".join("%.1f %.1f" % p for p in seg)
        lines.append('<path d="%s" fill="none" stroke="%s" stroke-width="1.8" '
                     'vector-effect="non-scaling-stroke" '
                     'stroke-linejoin="round"/>' % (d, color))
        base = pad_t + ih
        areas.append('<path d="M%.1f %.1f L%s L%.1f %.1f Z" fill="%s" opacity=".14"/>'
                     % (seg[0][0], base,
                        " L".join("%.1f %.1f" % p for p in seg),
                        seg[-1][0], base, color))

    # 阈值虚线 + 行尾标签（画在折线之下：线本身才是主体，参考线不该抢眼）
    thline, thlabel = [], []
    if th_val is not None:
        ty = y_of(th_val)
        thline.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#ff5f6b" '
                      'stroke-width="1" stroke-dasharray="4 4" opacity=".6"/>'
                      % (pad_l, ty, w - pad_r, ty))
        thlabel.append('<text x="%d" y="%.1f" fill="#ff5f6b" font-size="9" '
                       'text-anchor="end" font-family="monospace" opacity=".85">'
                       '%s %s %s</text>'
                       % (w - pad_r - 2, ty - 4,
                          "≥" if th_dir == "min" else "≤",
                          _fmt_tick(th_val, hi - lo), unit))

    t0 = samples[0].get("t") or 0
    t1 = samples[-1].get("t") or 0
    # 悬停热区：同列多笔采样取最后一笔（与曲线最右端的最新读数一致）。
    cols = {}
    for i, v in pts:
        if v is not None:
            cols[int(x_of(i))] = (samples[i].get("t") or 0, v)
    hots = _hover_strips(
        cols, pad_t, ih,
        lambda t, v: "%s  %s%s" % (_ts(t), _fmt(v), unit))
    return (
        '<svg viewBox="0 0 %d %d" preserveAspectRatio="none" class="chart" '
        'width="100%%" height="%d">%s%s%s%s%s%s%s'
        '<text x="%d" y="%d" fill="#6e8299" font-size="9" font-family="monospace">%s</text>'
        '<text x="%d" y="%d" fill="#6e8299" font-size="9" text-anchor="end" '
        'font-family="monospace">%s</text>'
        '</svg>'
        % (w, h, h, "".join(grid), "".join(bands), "".join(areas),
           "".join(thline), "".join(lines), "".join(hots), "".join(thlabel),
           pad_l, h - 6, _ts(t0), w - pad_r, h - 6, _ts(t1)))


_REPORT_CSS = """
* { box-sizing: border-box; }
body { margin: 0; padding: 28px 32px 48px; background: #0b0f14; color: #e9f0f8;
  font-family: "Chakra Petch", "Microsoft YaHei UI", "PingFang SC", sans-serif;
  background-image:
    radial-gradient(90rem 34rem at 6% -8%, rgba(52,224,234,.07), transparent 62%),
    linear-gradient(rgba(126,166,204,.045) 1px, transparent 1px),
    linear-gradient(90deg, rgba(126,166,204,.045) 1px, transparent 1px);
  background-size: auto, 26px 26px, 26px 26px;
}
h1 { font-size: 20px; letter-spacing: .12em; margin: 0 0 4px; font-weight: 600; }
h1::before { content: ""; display: inline-block; width: 8px; height: 8px;
  background: #34e0ea; transform: rotate(45deg); margin-right: 10px;
  box-shadow: 0 0 10px rgba(52,224,234,.5); vertical-align: 2px; }
.sub { color: #6e8299; font-size: 11px; font-family: monospace; letter-spacing: .16em; }
.meta { display: flex; flex-wrap: wrap; gap: 8px 22px; margin: 18px 0 22px;
  padding: 12px 16px; border: 1px solid rgba(126,166,204,.14);
  border-radius: 10px; background: #10161f; font-size: 12px; }
.meta b { color: #8ba1b8; font-weight: 500; }
.meta span { font-family: monospace; color: #e9f0f8; }
table { width: 100%; border-collapse: collapse; font-size: 12px; }
th, td { padding: 7px 10px; text-align: right; border-bottom: 1px solid rgba(126,166,204,.10); }
th:first-child, td:first-child { text-align: left; }
th { color: #6e8299; font-weight: 500; font-family: monospace; font-size: 10px;
  letter-spacing: .14em; text-transform: uppercase; }
td { font-family: "JetBrains Mono", monospace; color: #b9c8d8; }
.card { border: 1px solid rgba(126,166,204,.14); border-radius: 12px; background: #10161f;
  padding: 14px 16px; margin: 16px 0 0; box-shadow: 0 2px 8px rgba(3,8,14,.5); }
.card h2 { font-size: 13px; font-weight: 600; letter-spacing: .1em; margin: 0 0 2px;
  color: #e9f0f8; display: flex; align-items: center; gap: 10px; }
.card h2 em { font-style: normal; font-family: monospace; font-size: 10px; color: #6e8299;
  letter-spacing: .16em; }
.card h2 .thmark { margin-left: auto; font-family: monospace; font-size: 10px;
  color: #ff8f9a; letter-spacing: .04em; opacity: .85; }
.chart { display: block; }
.nochart { color: #6e8299; font-size: 12px; padding: 26px 0; text-align: center; }
.noalert { color: #3ddc84; font-size: 12px; padding: 16px 0 2px; }
.note { color: #6e8299; font-size: 11px; margin: 10px 0 0; font-family: monospace; }
tr.crit td { color: #ff8f9a; }
tr.crit td:first-child::before {
  content: ""; display: inline-block; width: 5px; height: 5px; margin-right: 7px;
  background: #ff5f6b; border-radius: 50%; vertical-align: 2px;
}
tr.warn td { color: #ffb454; }
tr.warn td:first-child::before {
  content: ""; display: inline-block; width: 5px; height: 5px; margin-right: 7px;
  background: #ffb454; border-radius: 50%; vertical-align: 2px;
}
details { margin-top: 22px; }
summary { cursor: pointer; color: #8ba1b8; font-size: 12px; letter-spacing: .06em; }
.foot { margin-top: 26px; color: #6e8299; font-size: 11px; }
"""


def esc_html(s):
    """HTML 文本转义（指标名 / 规则文本 / 设备型号都来自设备与用户输入）。"""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _alert_card_html(alerts, thresholds=None):
    """报告里的「阈值告警」卡片。没有告警也要出现——「没超标」本身就是结论。"""
    esc = esc_html

    th = DEFAULT_THRESHOLDS if thresholds is None else thresholds
    if not th:
        return ('<div class="card"><h2>阈值告警 <em>ALERTS</em></h2>'
                '<div class="noalert">本次采样未启用阈值告警</div>'
                '<div class="note">在性能监控页点「阈值」可开启并自定义判定标准。</div>'
                '</div>')
    th_line = "判定标准：" + " · ".join(
        threshold_rule_text(k, v) for k, v in th.items())
    if not alerts:
        return ('<div class="card"><h2>阈值告警 <em>ALERTS</em></h2>'
                '<div class="noalert">本次采样未触发任何阈值告警</div>'
                '<div class="note">%s</div></div>' % esc(th_line))
    rows = []
    for a in alerts:
        rows.append(
            '<tr class="%s"><td>%s</td><td>%s</td><td>%d / %d</td><td>%s%%</td>'
            '<td>%s</td><td>%s 秒</td><td>%s</td></tr>'
            % (a["level"], a["title"], esc(a["rule"]), a["count"], a["total"],
               _fmt(a["ratio"]), _fmt(a["worst"]), _fmt(a["longest_s"]),
               _ts(a["first_t"])))
    return (
        '<div class="card"><h2>阈值告警 <em>ALERTS</em></h2>'
        '<table><thead><tr><th>指标</th><th>规则</th><th>超标点</th><th>占比</th>'
        '<th>最差值</th><th>最长持续</th><th>首次出现</th></tr></thead>'
        '<tbody>%s</tbody></table><div class="note">%s</div></div>'
        % ("".join(rows), esc(th_line)))


def build_report_html(samples, info, thresholds=None, generated_at=None):
    """生成自包含的 HTML 报告（无外链、无脚本，双击即可看）。

    图表带悬停提示：鼠标停在曲线上浮出该时刻的时间与读数（SVG 原生
    <title>，无需脚本，离线双击可用）。
    thresholds 由调用方（controller）从用户配置解析后传入：None = 内置基线，
    {} = 用户关掉了全部告警。报告、界面、CSV 必须按同一份阈值判，缺一不可。
    """
    info = info or {}
    th = DEFAULT_THRESHOLDS if thresholds is None else thresholds
    generated_at = generated_at or datetime.datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S")
    sums = metric_summary(samples)
    n = len(samples)
    t0 = samples[0].get("t") if samples else None
    t1 = samples[-1].get("t") if samples else None
    dur = (t1 - t0) if (t0 and t1) else 0
    dur_txt = "%.1f 分钟" % (dur / 60.0) if dur >= 60 else "%.0f 秒" % dur

    rows = []
    for key, title, unit, _cap in METRICS:
        s = sums.get(key)
        if not s:
            rows.append("<tr><td>%s</td><td>--</td><td>--</td><td>--</td>"
                        "<td>--</td></tr>" % title)
            continue
        rows.append("<tr><td>%s (%s)</td><td>%s</td><td>%s</td><td>%s</td>"
                    "<td>%s</td></tr>"
                    % (title, unit, _fmt(s["min"]), _fmt(s["avg"]),
                       _fmt(s["max"]), _fmt(s["p95"])))

    colors = {"cpu": "#34e0ea", "mem_used": "#4cc3ff", "pss": "#a78bfa",
              "fps": "#3ddc84", "jank": "#f472b6", "batt": "#ffb454",
              "temp": "#ff5f6b"}
    charts = []
    for key, title, unit, cap in METRICS:
        rule = th.get(key)
        svg = _svg_chart(samples, key, colors[key], unit, cap, rule=rule)
        note = ""
        if rule:
            # 标题旁标一行判定标准：色带与虚线都在图里，但「≥ 45」这个数字
            # 得能直接读到，不能指望每个人都会去图上找虚线标签。
            note = ('<span class="thmark">%s</span>'
                    % esc_html(threshold_rule_text(key, rule)))
        charts.append('<div class="card"><h2>%s <em>%s</em>%s</h2>%s</div>'
                      % (title, unit.upper(), note, svg))

    # 明细表：样本多时只放前 2000 行，避免报告变成几十 MB
    body_rows = []
    for s in samples[:2000]:
        body_rows.append(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
            "<td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (_ts(s.get("t") or 0), _fmt(s.get("cpu")), _fmt(s.get("app_cpu")),
               _fmt(s.get("mem_used")), _fmt(s.get("pss")), _fmt(s.get("fps")),
               _fmt(s.get("jank")), _fmt(s.get("batt")), _fmt(s.get("temp"))))

    meta = [
        ("设备", info.get("model") or info.get("serial") or "未知"),
        ("序列号", info.get("serial") or "--"),
        ("Android", info.get("android") or "--"),
        ("分辨率", info.get("size") or "--"),
        ("监控应用", pkg_display(info)),
        ("开始时间", info.get("started_at") or "--"),
        ("时长", dur_txt),
        ("样本数", str(n)),
    ]
    meta_html = "".join("<div><b>%s</b> <span>%s</span></div>" % (k, v)
                        for k, v in meta)

    alert_html = _alert_card_html(evaluate_alerts(samples, th), th)

    return (
        '<!DOCTYPE html>\n<html lang="zh-CN"><head><meta charset="utf-8">'
        '<title>性能监控报告 %s</title><style>%s</style></head><body>'
        '<h1>性能监控报告</h1><div class="sub">PERFORMANCE MONITOR REPORT</div>'
        '<div class="meta">%s</div>'
        '<div class="card"><h2>指标统计 <em>SUMMARY</em></h2>'
        '<table><thead><tr><th>指标</th><th>最小</th><th>平均</th><th>最大</th>'
        '<th>P95</th></tr></thead><tbody>%s</tbody></table></div>'
        '%s'
        '%s'
        '<details><summary>采样明细（前 %d 条）</summary><div class="card">'
        '<table><thead><tr><th>时间</th><th>CPU%%</th><th>应用CPU%%</th>'
        '<th>内存MB</th><th>PSS MB</th><th>FPS</th><th>卡顿%%</th><th>电量%%</th>'
        '<th>温度℃</th>'
        '</tr></thead><tbody>%s</tbody></table></div></details>'
        '<div class="foot">由「ADB 设备指令台 · 性能监控」生成于 %s。'
        '指标采集自 /proc 与 dumpsys，采样间隔 %s 秒。</div>'
        '</body></html>'
        % (generated_at, _REPORT_CSS, meta_html, "".join(rows), alert_html,
           "".join(charts), min(n, 2000), "".join(body_rows), generated_at,
           info.get("interval") or DEFAULT_INTERVAL))


CSV_HEADER = ["time", "cpu_percent", "app_cpu_percent", "mem_used_mb",
              "mem_total_mb", "pss_mb", "fps", "jank_percent",
              "jank_cumulative_percent", "battery_percent", "battery_temp_c"]


def write_csv(samples, path):
    """写 CSV（utf-8-sig：Excel 直接双击不乱码）。返回写入行数。

    jank_percent 是**区间**卡顿率（本采样窗口内新增帧的卡顿占比），
    jank_cumulative_percent 是 gfxinfo 报的「自应用启动以来」的累计值——
    两列都留，分析时想看长期水位还是瞬时抖动都有据可查。
    """
    rows = 0
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        for s in samples:
            w.writerow([
                _ts(s.get("t") or 0, "%Y-%m-%d %H:%M:%S"), s.get("cpu") or "",
                s.get("app_cpu") or "", s.get("mem_used") or "",
                s.get("mem_total") or "", s.get("pss") or "",
                s.get("fps") or "", s.get("jank") or "",
                s.get("jank_cum") or "",
                s.get("batt") or "", s.get("temp") or ""])
            rows += 1
    return rows


def write_report(samples, info, out_dir, thresholds=None):
    """把 HTML + CSV 写到 out_dir，返回 {"html","csv","rows"}。"""
    os.makedirs(out_dir, exist_ok=True)
    serial = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(info.get("serial") or "device"))
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    base = "perf_%s_%s" % (serial, stamp)
    html_path = os.path.join(out_dir, base + ".html")
    csv_path = os.path.join(out_dir, base + ".csv")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(build_report_html(samples, info, thresholds))
    rows = write_csv(samples, csv_path)
    return {"html": html_path, "csv": csv_path, "rows": rows}


# --------------------------------------------------------------------------- #
# 多设备对比报告（同一份文档里横向比较，而不是让用户开 N 个标签页自己对照）
# --------------------------------------------------------------------------- #
# 设备配色：与前端曲线同一组色（青 / 紫 / 绿 / 橙 / 蓝 / 粉…）。报告与界面
# 颜色对不上的话，用户拿着报告回看界面时得重新认一遍哪条线是哪台。
COMPARE_COLORS = ("#34e0ea", "#a78bfa", "#3ddc84", "#ffb454",
                  "#4cc3ff", "#f472b6", "#ffd166", "#5eead4")

# 「最差」的判定方向：帧率越低越差，其余越高越差。
_WORSE_LOW = frozenset(("fps",))


def _svg_compare(series, key, unit, cap=None, rule=None, w=760, h=190):
    """多设备同指标画在一张图里（横轴按**时间**对齐，不是按样本序号）。

    不画超标色带：三条线叠在一起时，色带属于哪台设备无从分辨。改用「超标点
    打红点」—— 红点落在哪条线上，就是哪台设备在那一刻不达标，指认明确。
    图上带悬停提示（SVG 原生 <title>）：停在任意时刻会列出每台设备的读数。
    """
    prepared, ts, vals = [], [], []
    for label, color, samples in series:
        pts = []
        for s in samples or []:
            v = s.get(key)
            pts.append((s.get("t") or 0.0,
                        float(v) if _is_num(v) else None))
        good = [v for _t, v in pts if v is not None]
        if not good:
            continue
        prepared.append((label, color, pts))
        ts.append(pts[0][0])
        ts.append(pts[-1][0])
        vals.extend(good)
    if not prepared or len(vals) < 2:
        return '<div class="nochart">采样点不足，无法绘制曲线</div>'

    th_val, th_dir = None, None
    if rule:
        for k in ("min", "max"):
            if _is_num(rule.get(k)):
                th_val, th_dir = float(rule[k]), k

    lo, hi = min(vals), max(vals)
    if cap is not None:
        lo, hi = 0.0, float(cap)
    elif hi - lo < 1e-9:
        lo, hi = lo - 1, hi + 1
    else:
        pad = (hi - lo) * 0.12
        lo, hi = max(0.0, lo - pad), hi + pad
    if th_val is not None and cap is None:
        span = max(1.0, hi - lo)
        if th_val < lo:
            lo = max(0.0, th_val - span * 0.08)
        elif th_val > hi:
            hi = th_val + span * 0.08

    pad_l, pad_r, pad_t, pad_b = 44, 10, 12, 20
    iw, ih = w - pad_l - pad_r, h - pad_t - pad_b
    t0, t1 = min(ts), max(ts)
    span = t1 - t0
    if span < 1e-9:          # 只有一条采样：给 1 秒兜底，避免除零
        span = 1.0

    def x_of(t):
        return pad_l + iw * ((t - t0) / span)

    def y_of(v):
        return pad_t + ih * (1 - (v - lo) / (hi - lo))

    grid = []
    for k in range(5):
        val = lo + (hi - lo) * k / 4.0
        y = y_of(val)
        grid.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#1d2836" '
                    'stroke-width="1"/>' % (pad_l, y, w - pad_r, y))
        grid.append('<text x="%d" y="%.1f" fill="#6e8299" font-size="9" '
                    'text-anchor="end" font-family="monospace">%s</text>'
                    % (pad_l - 6, y + 3, _fmt_tick(val, hi - lo)))

    lines, dots = [], []
    shown_dots = 0
    for _label, color, pts in prepared:
        segs, cur = [], []
        for t, v in pts:
            if v is None:
                if cur:
                    segs.append(cur)
                    cur = []
                continue
            cur.append((x_of(t), y_of(v)))
            bad = (th_val is not None
                   and (v < th_val if th_dir == "min" else v > th_val))
            # 红点上限 400：整段全超标时逐点画会让报告膨胀几 MB，而那时候
            # 「满屏都是红的」本身就是结论，不需要每个点都留证。
            if bad and shown_dots < 400:
                dots.append('<circle cx="%.1f" cy="%.1f" r="1.7" fill="#ff5f6b"/>'
                            % (x_of(t), y_of(v)))
                shown_dots += 1
        if cur:
            segs.append(cur)
        for seg in segs:
            if len(seg) == 1:
                lines.append('<circle cx="%.1f" cy="%.1f" r="1.6" fill="%s"/>'
                             % (seg[0][0], seg[0][1], color))
                continue
            lines.append('<path d="M%s" fill="none" stroke="%s" stroke-width="1.7" '
                         'vector-effect="non-scaling-stroke" '
                         'stroke-linejoin="round"/>'
                         % (" L".join("%.1f %.1f" % p for p in seg), color))

    thline, thlabel = [], []
    if th_val is not None:
        ty = y_of(th_val)
        thline.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#ff5f6b" '
                      'stroke-width="1" stroke-dasharray="4 4" opacity=".6"/>'
                      % (pad_l, ty, w - pad_r, ty))
        thlabel.append('<text x="%d" y="%.1f" fill="#ff5f6b" font-size="9" '
                       'text-anchor="end" font-family="monospace" opacity=".85">'
                       '%s %s %s</text>'
                       % (w - pad_r - 2, ty - 4,
                          "≥" if th_dir == "min" else "≤",
                          _fmt_tick(th_val, hi - lo), unit))

    # 悬停热区（与单设备报告同一套路）：按像素列合并，一列一条提示，
    # 列出该时刻**每台设备**的读数 —— 对比图的提示必须一次看全各家，不然
    # 用户得在几条线之间来回找。
    cols = {}
    for label, _color, pts in prepared:
        for t, v in pts:
            if v is None:
                continue
            ent = cols.setdefault(int(x_of(t)), (t, {}))
            ent[1][label] = v

    def _cmp_title(t, per):
        lines = [_ts(t)]
        for label, v in per.items():
            lines.append("%s  %s%s" % (label, _fmt(v), unit))
        return "\n".join(lines)

    hots = _hover_strips(cols, pad_t, ih, _cmp_title)

    return (
        '<svg viewBox="0 0 %d %d" preserveAspectRatio="none" class="chart" '
        'width="100%%" height="%d">%s%s%s%s%s%s'
        '<text x="%d" y="%d" fill="#6e8299" font-size="9" font-family="monospace">%s</text>'
        '<text x="%d" y="%d" fill="#6e8299" font-size="9" text-anchor="end" '
        'font-family="monospace">%s</text>'
        '</svg>'
        % (w, h, h, "".join(grid), "".join(thline), "".join(lines),
           "".join(dots), "".join(hots), "".join(thlabel),
           pad_l, h - 6, _ts(t0), w - pad_r, h - 6, _ts(t1)))


def _compare_legend(entries):
    """图例：一色一台，写在卡片标题行（SVG 内留白不够，长型号会被截断）。"""
    parts = []
    for i, e in enumerate(entries):
        color = COMPARE_COLORS[i % len(COMPARE_COLORS)]
        parts.append('<span class="lg"><i style="background:%s"></i>%s</span>'
                     % (color, esc_html(e.get("label") or e.get("serial") or "?")))
    return '<div class="legend">%s</div>' % "".join(parts)


def _cell_num(v):
    """对比表格里的数字：≥1000 取整。

    内存 3120.0 MB 与 3181.2 MB 并排时，一位小数只是噪声 —— 同一单元格里
    「3120 / 3181.2」两种精度还会让人以为后者更准。小数值（FPS / 温度 / %）
    仍保留一位，够用且不埋掉趋势。
    """
    if v is None:
        return "--"
    if abs(v) >= 1000:
        return "%d" % int(round(v))
    return _fmt(v)


def _compare_matrix(entries, sums):
    """指标 × 设备的统计矩阵；每行把最不理想的那台标红。

    「最差」按方向判：帧率越低越差，卡顿 / 温度 / CPU / 内存越高越差。
    不做归一化打分（那会把「温度高 2℃」和「FPS 掉 20」算成同一件事），
    只标出每行的极值，剩下的交给看图的人判断。
    """
    head = ['<th>指标</th>']
    for e in entries:
        head.append('<th>%s</th>' % esc_html(e.get("label") or e.get("serial")))
    rows = []
    for key, title, unit, _cap in METRICS:
        cells, avgs = [], []
        for i, e in enumerate(entries):
            s = sums[i].get(key)
            if not s:
                cells.append('<td class="null">--</td>')
                continue
            avgs.append((i, s["avg"]))
            cells.append('<td>%s<span class="dim"> / %s</span></td>'
                         % (_cell_num(s["avg"]), _cell_num(s["max"])))
        # 只在**唯一**最差时标红：两台数值相同（同一份包、同一台机型的正常
        # 表现）时随便挑一台标红，等于给读者一个假的结论。
        if len(avgs) > 1:
            target = (min if key in _WORSE_LOW else max)(v for _i, v in avgs)
            hits = [i for i, v in avgs if v == target]
            if len(hits) == 1:
                cells[hits[0]] = cells[hits[0]].replace(
                    "<td>", '<td class="worst">', 1)
        rows.append("<tr><td>%s (%s)</td>%s</tr>"
                    % (title, esc_html(unit), "".join(cells)))
    return ('<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>'
            % ("".join(head), "".join(rows)))


def _compare_alert_table(entries, th, alerts_per):
    """告警汇总：行 = 设备，列 = 各可配阈值项，格 = 超标占比（及最长持续）。"""
    keys = [k for k, _d, _r, _h in THRESHOLD_META if k in (th or {})]
    if not keys:
        return ('<div class="card"><h2>阈值告警 <em>ALERTS</em></h2>'
                '<div class="noalert">本次采样未启用阈值告警</div></div>')
    head = ["<th>设备</th>"] + [
        "<th>%s</th>" % esc_html(threshold_rule_text(k, th[k])) for k in keys]
    rows = []
    for i, e in enumerate(entries):
        got = dict((a["key"], a) for a in alerts_per[i])
        cells = []
        for k in keys:
            a = got.get(k)
            if not a:
                cells.append('<td class="ok">达标</td>')
            else:
                cells.append('<td class="%s">%s%%<span class="dim"> · %s / %s 点'
                             '</span></td>'
                             % (a["level"], _fmt(a["ratio"]), a["count"],
                                a["total"]))
        rows.append('<tr><td>%s</td>%s</tr>'
                    % (esc_html(e.get("label") or e.get("serial")),
                       "".join(cells)))
    return ('<div class="card"><h2>阈值告警 <em>ALERTS</em></h2>'
            '<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>'
            '<div class="note">占比 = 超标采样点 / 有效采样点；≥%s%% 记为严重。</div>'
            '</div>'
            % ("".join(head), "".join(rows), _fmt(ALERT_CRIT_RATIO)))


def build_compare_html(entries, thresholds=None, generated_at=None):
    """多设备横向对比报告（单文件、无外链）。

    entries: [{"serial","label","samples","info","interval"}, ...]
    单设备时没有对比意义，返回空串由调用方决定是否落盘。
    """
    entries = [e for e in (entries or []) if e and e.get("samples")]
    if len(entries) < 2:
        return ""
    th = DEFAULT_THRESHOLDS if thresholds is None else thresholds
    generated_at = generated_at or datetime.datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S")

    sums = [metric_summary(e["samples"]) for e in entries]
    alerts_per = [evaluate_alerts(e["samples"], th) for e in entries]

    # 设备信息表：横向对比最怕「拿两台不同版本 / 不同分辨率的机器比」，先把
    # 这些前提摆出来，读者自己就能判断这组数据能不能比。
    head = ["<th>设备</th>", "<th>序列号</th>", "<th>Android</th>",
            "<th>分辨率</th>", "<th>监控应用</th>", "<th>时长</th>",
            "<th>样本数</th>"]
    rows = []
    for i, e in enumerate(entries):
        info = e.get("info") or {}
        samples = e["samples"]
        t0 = samples[0].get("t") or 0
        t1 = samples[-1].get("t") or 0
        dur = max(0.0, t1 - t0)
        dur_txt = "%.1f 分钟" % (dur / 60.0) if dur >= 60 else "%.0f 秒" % dur
        color = COMPARE_COLORS[i % len(COMPARE_COLORS)]
        rows.append(
            '<tr><td><i class="dot" style="background:%s"></i>%s</td>'
            '<td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>'
            '<td>%s</td></tr>'
            % (color, esc_html(e.get("label") or e.get("serial")),
               esc_html(info.get("serial") or "--"),
               esc_html(info.get("android") or "--"),
               esc_html(info.get("size") or "--"),
               esc_html(pkg_display(info)),
               dur_txt, len(samples)))
    meta_table = ('<div class="card"><h2>对比设备 <em>DEVICES</em></h2>'
                  '<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>'
                  '</div>' % ("".join(head), "".join(rows)))

    matrix = ('<div class="card"><h2>指标对比 <em>COMPARE</em></h2>%s'
              '<div class="note">每格为「均值 / 峰值」；<span class="worst-inline">'
              '红字</span> = 该指标最不理想的一台（FPS 取最低，其余取最高）。'
              '</div></div>'
              % _compare_matrix(entries, sums))

    series_all = [(e.get("label") or e.get("serial"),
                   COMPARE_COLORS[i % len(COMPARE_COLORS)], e["samples"])
                  for i, e in enumerate(entries)]
    charts = []
    for key, title, unit, cap in METRICS:
        svg = _svg_compare(series_all, key, unit, cap, rule=(th or {}).get(key))
        charts.append('<div class="card"><h2>%s <em>%s</em>%s</h2>%s%s</div>'
                      % (title, unit.upper(),
                         ('<span class="thmark">%s</span>'
                          % esc_html(threshold_rule_text(key, th[key])))
                         if (th or {}).get(key) else "",
                         _compare_legend(entries), svg))

    alert_html = _compare_alert_table(entries, th, alerts_per)

    foot_meta = " · ".join(
        "%s 采样间隔 %s 秒" % (esc_html(e.get("label") or e.get("serial")),
                               e.get("interval") or DEFAULT_INTERVAL)
        for e in entries)

    total_pts = sum(len(e["samples"]) for e in entries)
    t_first = min(e["samples"][0].get("t") or 0 for e in entries)
    t_last = max(e["samples"][-1].get("t") or 0 for e in entries)

    return (
        '<!DOCTYPE html>\n<html lang="zh-CN"><head><meta charset="utf-8">'
        '<title>多设备对比性能报告 %s</title><style>%s</style></head><body>'
        '<h1>多设备对比性能报告</h1>'
        '<div class="sub">MULTI-DEVICE PERFORMANCE COMPARISON</div>'
        '<div class="meta"><div><b>设备数</b> <span>%d</span></div>'
        '<div><b>监控应用</b> <span>%s</span></div>'
        '<div><b>时间范围</b> <span>%s</span></div>'
        '<div><b>总采样点</b> <span>%d</span></div>'
        '<div><b>生成时间</b> <span>%s</span></div></div>'
        '%s%s%s%s'
        '<div class="foot">由「ADB 设备指令台 · 性能监控」生成于 %s。%s。'
        '指标采集自 /proc 与 dumpsys。每台设备的逐条原始数据见各自的 CSV。</div>'
        '</body></html>'
        % (generated_at, _REPORT_CSS + _COMPARE_CSS, len(entries),
           esc_html(pkg_display(entries[0].get("info") or {})),
           esc_html("%s ~ %s" % (_ts(t_first), _ts(t_last))),
           total_pts, generated_at,
           meta_table, matrix, alert_html, "".join(charts), generated_at,
           foot_meta))


_COMPARE_CSS = """
.dot { display: inline-block; width: 7px; height: 7px; border-radius: 2px;
  margin-right: 7px; vertical-align: 1px; }
.legend { display: flex; flex-wrap: wrap; gap: 6px 16px; margin: 8px 0 2px;
  font-family: monospace; font-size: 10px; color: #8ba1b8; }
.legend .lg { display: inline-flex; align-items: center; gap: 6px; }
.legend i { display: block; width: 10px; height: 2px; border-radius: 1px; }
td.worst { color: #ff8f9a; font-weight: 600; }
td.crit { color: #ff8f9a; font-weight: 600; }
td.warn { color: #ffb454; }
td.ok { color: #3ddc84; }
td.null { color: #4d5c6d; }
td .dim, .dim { color: #6e8299; font-weight: 400; }
.worst-inline { color: #ff8f9a; }
"""


def write_compare_report(entries, out_dir, thresholds=None):
    """把多设备对比报告写到 out_dir；单设备返回 {}（没有对比可做）。"""
    html = build_compare_html(entries, thresholds)
    if not html:
        return {}
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(out_dir, "perf_compare_%d_dev_%s.html"
                        % (len(entries), stamp))
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return {"html": path, "devices": len(entries)}
