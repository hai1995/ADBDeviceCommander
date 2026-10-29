# -*- coding: utf-8 -*-
"""
core.wireless —— 无线调试（Wi-Fi ADB）的纯逻辑
====================================================================
车机 / 手机调试时 USB 线常常不够用（车上走线、USB 口被占用、要做长时间
稳定性测试），无线调试是刚需。本模块只做**纯逻辑**，不碰 adb 进程：

  * normalize_endpoint(text)   用户输入 → `host:port`（校验 + 补默认端口）
  * is_wireless_serial(serial) 判断某个序列号是不是网络设备
  * parse_device_ip(raw)       从 `ip route` / `ip -4 addr` 输出里挑出设备 IP
  * parse_connect_output(text) `adb connect` 输出 → 成败 + 中文说明
  * parse_tcpip_output(text)   `adb tcpip` 输出 → 成败 + 端口
  * add_recent(...)            最近连接地址（config.json 的 wifi_recent）

**为什么地址要严格校验**：校验后的字符串会被拼进 `adb connect <addr>` 的
参数位。虽然 adb 本身不是 shell（不存在 `; rm -rf` 直接执行），但一个带空格
或引号的输入会把整条命令拆成两段参数，行为不可预期；而主机名白名单同时也
挡住了复制粘贴进来的整条命令（`adb connect 1.2.3.4`）——那是最常见的粘贴错误。
"""
import re

DEFAULT_PORT = 5555
# 最近连接地址保留条数。再长就是一条没人翻的流水账，而 config.json 是
# 手编辑的，5 条刚好一行放得下。
MAX_RECENT = 5

# IPv4 四段：每段 0~255，且不允许前导 0（`010.1.1.1` 在部分系统上被当八进制）
_IPV4_RE = re.compile(
    r"^(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)$")
# 主机名：字母数字开头结尾，中间允许点和横线（手机热点常给 `android-abc.local`）
_HOST_RE = re.compile(
    r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")
_IPV6_CHARS_RE = re.compile(r"^[0-9A-Fa-f:.]+$")

# mDNS 无线设备的序列号里没有冒号，形如
# `adb-26151FDF60083B-9tP4nl._adb-tls-connect._tcp`（Android 11+ 无线调试）
_MDNS_MARKERS = ("_adb-tls-connect", "_adb-tls-pairing")


def is_wireless_serial(serial) -> bool:
    """序列号是否代表一台网络设备（`ip:port` 或 mDNS 服务名）。"""
    s = (serial or "")
    if ":" in s:
        return True
    return any(m in s for m in _MDNS_MARKERS)


def _valid_port(text):
    if not text or not text.isdigit():
        return None
    n = int(text)
    return n if 1 <= n <= 65535 else None


def normalize_endpoint(text, default_port=DEFAULT_PORT):
    """把用户输入规范成 `host:port`。返回 `(addr, error)`，出错时 addr 为空。

    接受的写法（都在真实粘贴里见过）：
      `192.168.1.23` / `192.168.1.23:5555` / `adb connect 192.168.1.23:5555`
      / `tcp://192.168.1.23:5555/` / `[fe80::1]:5555`
    """
    raw = (text or "").strip()
    if not raw:
        return "", "请输入设备 IP（或 IP:端口）"

    # 整条命令粘进来：只认 `adb connect` 之后的那一段，其余原样交给校验
    m = re.match(r"^\s*adb(?:\.exe)?\s+connect\s+(.+)$", raw, re.I)
    if m:
        raw = m.group(1).strip()

    low = raw.lower()
    for pre in ("adb://", "tcp://", "http://", "https://"):
        if low.startswith(pre):
            raw = raw[len(pre):]
            low = raw.lower()
    # 去掉粘贴带来的尾部路径 / 查询串
    raw = re.split(r"[/?#]", raw, 1)[0].strip()

    host, port = raw, default_port
    is_v6 = False
    if raw.startswith("["):
        end = raw.find("]")
        if end < 0:
            return "", "IPv6 地址缺少右方括号，应写成 [地址]:端口"
        host = raw[1:end]
        is_v6 = True
        rest = raw[end + 1:]
        if rest.startswith(":"):
            p = _valid_port(rest[1:])
            if p is None:
                return "", "端口号必须是 1~65535 的整数"
            port = p
        elif rest:
            return "", "地址格式不正确（IPv6 请写成 [地址]:端口）"
        if not _IPV6_CHARS_RE.match(host):
            return "", "IPv6 地址含非法字符"
    elif raw.count(":") == 1:
        host, ptext = raw.split(":")
        p = _valid_port(ptext)
        if p is None:
            return "", "端口号必须是 1~65535 的整数"
        port = p
    elif raw.count(":") > 1:
        return "", "IPv6 地址请写成 [地址]:端口"

    host = host.strip()
    if not host:
        return "", "请输入设备 IP（或 IP:端口）"
    if is_v6:
        return "[%s]:%d" % (host, port), ""
    # 只由数字和点组成、且带点的输入必然是「想写 IP」：非法时直接说清哪里不对。
    # 否则它会落进主机名白名单被当成合法主机名，一路走到 adb connect 才失败，
    # 用户看到的是「连接超时 / 无法解析」——与真正的原因（地址写错）无关。
    # 不带点的纯数字（如 `12345`）仍按主机名处理：那不像 IP，拦下来反而误伤。
    if re.match(r"^[0-9]+\.[0-9.]+$", host) and not _IPV4_RE.match(host):
        return "", "IP 地址不合法（四段 0~255，形如 192.168.1.23）"
    if not (_IPV4_RE.match(host) or _HOST_RE.match(host)):
        return "", "IP / 主机名含非法字符（只允许字母、数字、点、横线）"
    return "%s:%d" % (host, port), ""


def split_endpoint(addr):
    """`host:port` → (host, port)；解析不出端口时 port 为 DEFAULT_PORT。"""
    s = (addr or "").strip()
    if s.startswith("["):
        end = s.find("]")
        if end > 0:
            host = s[1:end]
            rest = s[end + 1:]
            p = _valid_port(rest[1:]) if rest.startswith(":") else None
            return host, p or DEFAULT_PORT
    if s.count(":") == 1:
        host, ptext = s.split(":")
        return host, _valid_port(ptext) or DEFAULT_PORT
    return s, DEFAULT_PORT


def parse_device_ip(raw):
    """从设备端 `ip route` + `ip -4 addr` 的输出里挑出可用的 IPv4。

    返回 `(ip, iface)`；挑不出来时返回 `("", "")`。

    取值顺序（车机上常见多网卡：wlan0 连调试网、eth0 连车载以太网）：
      1. 默认路由里的 `src`（`default via 192.168.1.1 dev wlan0 ... src 192.168.1.23`）
         —— 这是设备真正出网用的地址，电脑大概率能连上；
      2. 任一网段的 `src`；
      3. `ip -4 addr` 里 `scope global` 的 `inet`。
    网卡优先级 wlan0 > wlan1 > 其它 wlan* > eth* > 其它，同一优先级取先出现的。
    """
    text = (raw or "")
    route_part, _, addr_part = text.partition("@@ADDR")

    def iface_rank(name):
        n = (name or "").lower()
        if n == "wlan0":
            return 0
        if n == "wlan1":
            return 1
        if n.startswith("wlan"):
            return 2
        if n.startswith("eth"):
            return 3
        if n.startswith("ap") or n.startswith("swlan"):
            return 4
        if n.startswith("lo"):
            return 99
        return 5

    candidates = []          # (rank, order, ip, iface)
    order = 0
    for line in route_part.splitlines():
        line = line.strip()
        if not line:
            continue
        toks = line.split()
        if "src" not in toks or "dev" not in toks:
            continue
        try:
            ip = toks[toks.index("src") + 1]
            iface = toks[toks.index("dev") + 1]
        except IndexError:
            continue
        if _IPV4_RE.match(ip) and not ip.startswith("127."):
            rank = iface_rank(iface)
            if line.startswith("default"):
                rank -= 0.5           # 默认路由优先于同网卡的普通网段
            candidates.append((rank, order, ip, iface))
        order += 1

    cur_iface = ""
    for line in addr_part.splitlines():
        line = line.strip()
        head = re.match(r"^\d+:\s+([^:]+):", line)
        if head:
            cur_iface = head.group(1).split("@")[0]
            continue
        m = re.search(r"\binet\s+(\d+\.\d+\.\d+\.\d+)/", line)
        if not m:
            continue
        ip = m.group(1)
        if ip.startswith("127."):
            continue
        iface = cur_iface
        toks = line.split()
        if toks and re.match(r"^[A-Za-z]", toks[-1]):
            iface = toks[-1]
        candidates.append((iface_rank(iface) + 1, order, ip, iface))
        order += 1

    if not candidates:
        return "", ""
    candidates.sort(key=lambda c: (c[0], c[1]))
    return candidates[0][2], candidates[0][3]


def explain_connect_failure(text):
    """把 adb 的英文报错翻成「下一步该干什么」。"""
    t = (text or "").strip()
    low = t.lower()
    if not t:
        return "adb 没有任何输出（设备可能未响应，可先执行一次 adb kill-server）"
    if "connection refused" in low:
        return "设备拒绝连接：多半还没开启无线调试（先对勾选设备点「开启无线调试 5555」），或端口不是 5555"
    if "no route to host" in low or "unreachable" in low or "network is unreachable" in low:
        return "网络不通：确认电脑与设备连的是同一个 Wi-Fi / 网段，且没有开启 AP 隔离"
    if "timed out" in low or "timeout" in low:
        return "连接超时：设备 IP 可能变了，重新「开启无线调试」获取新地址再试"
    if "authenticate" in low or "authentication" in low or "unauthorized" in low:
        return "需要授权：请解锁设备，在「允许 USB 调试吗」弹窗里点允许"
    if "protocol fault" in low or "cannot connect to daemon" in low:
        return "adb 服务状态异常：先执行 adb kill-server，再重新连接"
    if "unable to resolve host" in low or "unknown host" in low:
        return "地址无法解析：IP / 主机名写错，或设备已离线"
    if "more than one device" in low:
        return "adb 里有重名设备：先在设备栏取消勾选旧的那台再连"
    return t[:200]


def parse_connect_output(text):
    """解析 `adb connect host:port` 的输出。

    adb 的成败信息走 **stderr**（`connected to 1.2.3.4:5555` /
    `failed to connect to '1.2.3.4:5555': Connection refused`），调用方必须把
    stdout + stderr 合并后再传进来。返回 `{ok, address, message}`。
    """
    t = (text or "").strip()
    low = t.lower()
    m = re.search(r"already connected to ([^\s,]+)", low)
    if m:
        return {"ok": True, "address": m.group(1), "message": "已连接（无需重复连接）"}
    if re.search(r"(?<!already )connected to ([^\s,]+)", low):
        m = re.search(r"connected to ([^\s,]+)", low)
        return {"ok": True, "address": m.group(1) if m else "",
                "message": "连接成功"}
    return {"ok": False, "address": "", "message": explain_connect_failure(t)}


def parse_tcpip_output(text):
    """解析 `adb tcpip <port>` 的输出（成功信息同样在 stderr）。

    返回 `{ok, port, message}`。
    """
    t = (text or "").strip()
    low = t.lower()
    m = re.search(r"restarting in tcp mode port:?\s*(\d+)", low)
    if m:
        return {"ok": True, "port": int(m.group(1)),
                "message": "已切换为无线模式（端口 %s）" % m.group(1)}
    if "no devices" in low or "device not found" in low or "not found" in low:
        return {"ok": False, "port": 0,
                "message": "设备已断开：先插好 USB 线（首次开启无线调试必须走 USB）"}
    if "unauthorized" in low:
        return {"ok": False, "port": 0, "message": "设备未授权：请在设备上点「允许 USB 调试」"}
    return {"ok": False, "port": 0,
            "message": explain_connect_failure(t) if t else "设备没有返回结果"}


def add_recent(recent, addr, limit=MAX_RECENT):
    """把 addr 放到最近列表最前面（去重、限量）。返回新列表，不改入参。"""
    a = (addr or "").strip()
    out = [x for x in (recent or []) if x and x != a]
    if a:
        out.insert(0, a)
    return out[:max(1, limit)]


def recent_from_pref(raw):
    """config.json 里的 `wifi_recent`（逗号串）→ 列表。"""
    return [x.strip() for x in (raw or "").split(",") if x.strip()]


def recent_to_pref(items):
    """列表 → config.json 的 `wifi_recent`（逗号串）。"""
    return ",".join([x.strip() for x in (items or []) if x and x.strip()])
