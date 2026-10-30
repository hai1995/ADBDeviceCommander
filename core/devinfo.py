# -*- coding: utf-8 -*-
"""
core.devinfo —— 设备信息快照（一次 adb shell 取全，纯解析）
====================================================================
点设备卡片上的 ⓘ 就能看到「这台到底什么机器」：型号 / 厂商 / 系统版本 /
Android 版本 / ABI / 分辨率 / 屏幕密度 / 电量 / 温度 / 存储 / 内存 / 开机时长。
排障时这几项几乎每次都要问（「你那是哪台？什么版本？多大分辨率？」）。

一次 adb 调用取全（分段标记），而不是每项一次：
  * 6 次 `adb shell` 在 USB 上要 1~2 秒，点开弹窗先白屏两秒；
  * 分区读取用 `@@` 标记切开，解析时与命令顺序解耦（多一条少一条都不崩）。

**为什么读 `getprop` 全量而不是逐条 `getprop key`**：全量一次约 8~15KB、
一次 IPC；逐条要十几次进程创建。代价只是解析时按 key 取值。
"""
import re

# 分段标记（与 SCRIPT 里的 echo 一一对应）
MARK_PROP = "@@PROP"
MARK_WM = "@@WM"
MARK_BATT = "@@BATT"
MARK_DF = "@@DF"
MARK_MEM = "@@MEM"
MARK_UP = "@@UP"

# 设备端脚本：全部是系统自带命令，不需要 root。
# `wm size` 在有「强制分辨率」的机器上会打出 Physical / Override 两行，都留着；
# `df /data` 取的是数据分区（截图 / 录屏 / 日志都落在 /data 的 sdcard 链接下）。
SCRIPT = (
    "echo %s; getprop; "
    "echo %s; wm size; wm density; "
    "echo %s; dumpsys battery; "
    "echo %s; df /data; "
    "echo %s; cat /proc/meminfo; "
    "echo %s; cat /proc/uptime"
) % (MARK_PROP, MARK_WM, MARK_BATT, MARK_DF, MARK_MEM, MARK_UP)

# 展示顺序与标签（顺序即弹窗里的行序：先「是哪台」，再「跑得怎么样」）
_PROP_ROWS = (
    ("ro.product.manufacturer", "厂商"),
    ("ro.product.model", "型号"),
    ("ro.product.device", "设备代号"),
    ("ro.build.version.release", "Android 版本"),
    ("ro.build.version.sdk", "SDK"),
    ("ro.build.display.id", "系统版本"),
    ("ro.build.type", "构建类型"),
    ("ro.product.cpu.abi", "CPU 架构"),
    ("ro.serialno", "序列号"),
)

BATTERY_STATUS = {
    "1": "未知", "2": "充电中", "3": "放电中", "4": "未充电", "5": "已充满",
}


def _section(raw, start, ends):
    """取出 `start` 标记到下一个标记之间的内容。"""
    text = raw or ""
    idx = text.find(start)
    if idx < 0:
        return ""
    body = text[idx + len(start):]
    cut = len(body)
    for e in ends:
        j = body.find(e)
        if 0 <= j < cut:
            cut = j
    return body[:cut]


def _parse_props(block):
    """`[key]: [value]` 全量 getprop → dict。"""
    out = {}
    for m in re.finditer(r"^\[([^\]]+)\]:\s*\[(.*)\]\s*$", block or "", re.M):
        out[m.group(1)] = m.group(2)
    return out


def _parse_wm(block):
    """`wm size` / `wm density` → {physical, override, density}。"""
    physical = override = density = ""
    for line in (block or "").splitlines():
        line = line.strip()
        m = re.match(r"Physical size:\s*(\d+x\d+)", line)
        if m:
            physical = m.group(1)
            continue
        m = re.match(r"Override size:\s*(\d+x\d+)", line)
        if m:
            override = m.group(1)
            continue
        m = re.match(r"Physical density:\s*(\d+)", line)
        if m:
            density = density or m.group(1)
            continue
        m = re.match(r"Override density:\s*(\d+)", line)
        if m:
            density = m.group(1)      # 覆盖值才是实际生效值
    return {"physical": physical, "override": override, "density": density}


def _parse_battery(block):
    """`dumpsys battery` → {level, status, temp}（温度单位是 0.1℃）。"""
    out = {"level": "", "status": "", "temp": ""}
    for line in (block or "").splitlines():
        line = line.strip()
        m = re.match(r"level:\s*(\d+)", line)
        if m:
            out["level"] = m.group(1)
            continue
        m = re.match(r"status:\s*(\d+)", line)
        if m:
            out["status"] = m.group(1)
            continue
        m = re.match(r"temperature:\s*(-?\d+)", line)
        if m:
            out["temp"] = "%.1f" % (int(m.group(1)) / 10.0)
    return out


def _to_kb(tok):
    """`df` 的数字列 → KB。兼容 1K-blocks 纯数字与 `-h` 式 `4.0G` 两种写法。"""
    m = re.match(r"^(\d+(?:\.\d+)?)([KMGTP]?)$", (tok or "").strip(), re.I)
    if not m:
        return None
    n = float(m.group(1))
    unit = (m.group(2) or "K").upper()
    mult = {"K": 1, "M": 1024, "G": 1024 ** 2,
            "T": 1024 ** 3, "P": 1024 ** 4}[unit]
    return int(n * mult)


def _parse_df(block):
    """`df /data` → (total_kb, used_kb, avail_kb)；解析不出返回 (0, 0, 0)。

    不同 ROM 的列数不一样（有的多一列 `Mounted on`、有的把文件系统名截断），
    所以按「最后一个百分比列」定位：它右边是挂载点，左边三列就是
    total / used / avail。

    表头行靠「百分比列不存在」自然被跳过，因此这里**逐行都试**而不跳过第一行：
    个别 ROM 会在表头前先打一行警告，跳过首行就把唯一的数据行也跳掉了。
    """
    for line in (block or "").splitlines():
        toks = line.split()
        if len(toks) < 4:
            continue
        pct_idx = None
        for i, t in enumerate(toks):
            if t.endswith("%") and t[:-1].isdigit():
                pct_idx = i
                break
        if pct_idx is None or pct_idx < 3:
            continue
        total = _to_kb(toks[pct_idx - 3])
        used = _to_kb(toks[pct_idx - 2])
        avail = _to_kb(toks[pct_idx - 1])
        if None in (total, used, avail):
            continue
        return total, used, avail
    return 0, 0, 0


def _parse_mem(block):
    """`/proc/meminfo` → (total_kb, avail_kb)。"""
    total = avail = 0
    for line in (block or "").splitlines():
        m = re.match(r"MemTotal:\s*(\d+)\s*kB", line)
        if m:
            total = int(m.group(1))
        m = re.match(r"MemAvailable:\s*(\d+)\s*kB", line)
        if m:
            avail = int(m.group(1))
    return total, avail


def _parse_uptime(block):
    """`/proc/uptime` 第一列（秒）→ 秒数。"""
    m = re.search(r"(\d+(?:\.\d+)?)", block or "")
    return float(m.group(1)) if m else 0.0


def parse_info(raw):
    """把 SCRIPT 的整段输出解析成扁平 dict（缺项为空串 / 0，绝不抛异常）。"""
    props = _parse_props(_section(raw, MARK_PROP, (MARK_WM, MARK_BATT,
                                                   MARK_DF, MARK_MEM, MARK_UP)))
    wm = _parse_wm(_section(raw, MARK_WM, (MARK_BATT, MARK_DF, MARK_MEM, MARK_UP)))
    batt = _parse_battery(_section(raw, MARK_BATT, (MARK_DF, MARK_MEM, MARK_UP)))
    total, used, avail = _parse_df(_section(raw, MARK_DF, (MARK_MEM, MARK_UP)))
    mem_total, mem_avail = _parse_mem(_section(raw, MARK_MEM, (MARK_UP,)))
    uptime = _parse_uptime(_section(raw, MARK_UP, ()))

    info = {key: props.get(key, "") for key, _label in _PROP_ROWS}
    info.update({
        "resolution": wm["physical"],
        "resolution_override": wm["override"],
        "density": wm["density"],
        "battery_level": batt["level"],
        "battery_status": batt["status"],
        "battery_temp": batt["temp"],
        "storage_total_kb": total,
        "storage_used_kb": used,
        "storage_avail_kb": avail,
        "mem_total_kb": mem_total,
        "mem_avail_kb": mem_avail,
        "uptime_s": uptime,
    })
    return info


def _size(kb):
    """KB → 自适应单位的文本。

    单位必须跟着数量级走：车机 `/data` 常常只剩几十 MB，固定按 GB 保留一位
    小数会写成「剩余 0.0 GB」——看着像没空间了，实际还有 50 MB；反过来几十
    GB 的分区写成 MB 也不便读。0 返回 "0 MB"（不是空串），否则「已用 0」那一
    格会变成空白，看起来像没读到。
    """
    n = float(kb or 0)
    if n <= 0:
        return "0 MB"
    if n >= 1024 * 1024:
        return "%.1f GB" % (n / 1024.0 / 1024.0)
    if n >= 1024:
        return "%.0f MB" % (n / 1024.0)
    return "%.0f KB" % n


def fmt_uptime(seconds):
    """秒 → 「3 天 4 小时 12 分」；不足 1 分钟显「不足 1 分钟」。"""
    s = int(seconds or 0)
    if s <= 0:
        return ""
    days, rest = divmod(s, 86400)
    hours, rest = divmod(rest, 3600)
    mins = rest // 60
    if days:
        return "%d 天 %d 小时 %d 分" % (days, hours, mins)
    if hours:
        return "%d 小时 %d 分" % (hours, mins)
    if mins:
        return "%d 分" % mins
    return "不足 1 分钟"


def rows(info):
    """把 parse_info 的结果整理成弹窗要展示的 [(标签, 值)]（空值自动略过）。

    格式化只在这里做一次：前端不再拼字符串，「复制」出去的文本与界面一致。
    """
    info = info or {}
    out = []
    for key, label in _PROP_ROWS:
        val = (info.get(key) or "").strip()
        if val:
            out.append((label, val))

    res = (info.get("resolution") or "").strip()
    over = (info.get("resolution_override") or "").strip()
    if res:
        out.append(("分辨率", res + ("（当前覆盖为 %s）" % over if over and over != res else "")))
    den = (info.get("density") or "").strip()
    if den:
        out.append(("屏幕密度", "%s dpi" % den))

    level = (info.get("battery_level") or "").strip()
    temp = (info.get("battery_temp") or "").strip()
    status = BATTERY_STATUS.get((info.get("battery_status") or "").strip(), "")
    if level:
        line = "%s%%" % level
        if status:
            line += "（%s）" % status
        if temp:
            line += " · %s℃" % temp
        out.append(("电量", line))

    st_total = info.get("storage_total_kb") or 0
    if st_total:
        used = info.get("storage_used_kb") or 0
        avail = info.get("storage_avail_kb") or 0
        pct = int(round(used * 100.0 / st_total)) if st_total else 0
        out.append(("存储 /data",
                    "%s / %s 已用（%d%%），剩余 %s"
                    % (_size(used), _size(st_total), pct, _size(avail))))

    mem_total = info.get("mem_total_kb") or 0
    if mem_total:
        avail = info.get("mem_avail_kb") or 0
        used = max(0, mem_total - avail)
        out.append(("内存", "%s / %s 已用，可用 %s"
                    % (_size(used), _size(mem_total), _size(avail))))

    up = fmt_uptime(info.get("uptime_s"))
    if up:
        out.append(("已开机", up))
    return out


def as_text(info):
    """纯文本版（「复制」按钮用）：`标签: 值` 每行一条。"""
    return "\n".join("%s: %s" % (k, v) for k, v in rows(info))
