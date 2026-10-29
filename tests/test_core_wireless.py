# -*- coding: utf-8 -*-
"""core.wireless —— 无线调试纯逻辑（地址校验 / IP 提取 / 输出解析）。"""
import pytest

from core import wireless as w


# ---------------------------------------------------------------- 地址规范化
def test_normalize_accepts_plain_ip_and_adds_default_port():
    assert w.normalize_endpoint("192.168.1.23") == ("192.168.1.23:5555", "")


def test_normalize_keeps_explicit_port():
    assert w.normalize_endpoint("10.0.0.8:6666") == ("10.0.0.8:6666", "")


def test_normalize_strips_whitespace_and_scheme():
    assert w.normalize_endpoint("  tcp://192.168.1.23:5555/  ") == (
        "192.168.1.23:5555", "")


def test_normalize_accepts_pasted_env_connect_command():
    """整条 `adb connect x:5555` 粘进来是最常见的误操作，必须能认。"""
    assert w.normalize_endpoint("adb connect 192.168.1.23:5555") == (
        "192.168.1.23:5555", "")
    assert w.normalize_endpoint("adb.exe connect 192.168.1.23") == (
        "192.168.1.23:5555", "")


def test_normalize_accepts_ipv6_bracket_form():
    assert w.normalize_endpoint("[fe80::1]:5555") == ("[fe80::1]:5555", "")
    assert w.normalize_endpoint("[fe80::1]") == ("[fe80::1]:5555", "")


def test_normalize_accepts_hostname():
    assert w.normalize_endpoint("android-abc.local") == (
        "android-abc.local:5555", "")


@pytest.mark.parametrize("bad, hint", [
    ("", "请输入"),
    ("   ", "请输入"),
    ("192.168.1.23:0", "端口号"),
    ("192.168.1.23:70000", "端口号"),
    ("192.168.1.23:abc", "端口号"),
    ("192.168.1.23:5555:1", "IPv6"),
    ("192.168.1.23; reboot", "非法字符"),
    ("my phone", "非法字符"),
    ("1.2.3.4/24", None),          # 带掩码：截掉 /24 后仍合法
])
def test_normalize_rejects_or_recovers(bad, hint):
    addr, err = w.normalize_endpoint(bad)
    if hint is None:
        assert err == "" and addr == "1.2.3.4:5555"
    else:
        assert addr == ""
        assert hint in err


def test_split_endpoint():
    assert w.split_endpoint("1.2.3.4:6666") == ("1.2.3.4", 6666)
    assert w.split_endpoint("1.2.3.4") == ("1.2.3.4", w.DEFAULT_PORT)
    assert w.split_endpoint("[fe80::1]:5555") == ("fe80::1", 5555)


# ---------------------------------------------------------------- 序列号判定
def test_is_wireless_serial():
    assert w.is_wireless_serial("192.168.1.23:5555") is True
    assert w.is_wireless_serial(
        "adb-26151FDF60083B-9tP4nl._adb-tls-connect._tcp") is True
    assert w.is_wireless_serial("QKX7N18A25001234") is False
    assert w.is_wireless_serial("") is False


# ---------------------------------------------------------------- 设备 IP
_ROUTE_DEFAULT = (
    "default via 192.168.1.1 dev wlan0 proto dhcp src 192.168.1.23 metric 600\n"
    "192.168.1.0/24 dev wlan0 proto kernel scope link src 192.168.1.23\n"
)


def test_parse_device_ip_prefers_default_route_src():
    raw = _ROUTE_DEFAULT + "@@ADDR\n2: wlan0: <BROADCAST>\n" \
        "    inet 192.168.1.23/24 brd 192.168.1.255 scope global wlan0\n"
    assert w.parse_device_ip(raw) == ("192.168.1.23", "wlan0")


def test_parse_device_ip_without_route_uses_addr_section():
    raw = ("@@ADDR\n2: wlan0: <BROADCAST,MULTICAST,UP>\n"
           "    inet 172.20.10.5/28 brd 172.20.10.15 scope global wlan0\n")
    assert w.parse_device_ip(raw) == ("172.20.10.5", "wlan0")


def test_parse_device_ip_skips_loopback():
    raw = ("@@ADDR\n1: lo: <LOOPBACK,UP>\n"
           "    inet 127.0.0.1/8 scope host lo\n"
           "3: eth0: <UP>\n"
           "    inet 10.1.2.3/24 brd 10.1.2.255 scope global eth0\n")
    assert w.parse_device_ip(raw) == ("10.1.2.3", "eth0")


def test_parse_device_ip_prefers_wlan_over_eth():
    """车机常见双网卡：调试网在 wlan0、车载以太网在 eth0，优先 wlan。"""
    raw = ("10.0.0.2 dev eth0 scope link src 10.0.0.9\n"
           "192.168.1.0/24 dev wlan0 scope link src 192.168.1.23\n")
    assert w.parse_device_ip(raw) == ("192.168.1.23", "wlan0")


def test_parse_device_ip_empty_output():
    assert w.parse_device_ip("") == ("", "")
    assert w.parse_device_ip("%%no such tool") == ("", "")


def test_device_ip_ignores_ipv6_only_output():
    raw = "@@ADDR\n2: wlan0: <UP>\n    inet6 fe80::1/64 scope link wlan0\n"
    assert w.parse_device_ip(raw) == ("", "")


# ---------------------------------------------------------------- 输出解析
def test_parse_connect_success():
    res = w.parse_connect_output("connected to 192.168.1.23:5555")
    assert res["ok"] is True and res["address"] == "192.168.1.23:5555"


def test_parse_connect_already_connected_is_success():
    res = w.parse_connect_output("already connected to 192.168.1.23:5555")
    assert res["ok"] is True
    assert "already" not in res["message"]


def test_parse_connect_refused_explains_next_step():
    res = w.parse_connect_output(
        "failed to connect to '192.168.1.23:5555': Connection refused")
    assert res["ok"] is False
    assert "无线调试" in res["message"]


def test_parse_connect_empty_output_is_failure():
    res = w.parse_connect_output("")
    assert res["ok"] is False and "没有" in res["message"]


def test_parse_tcpip_success_uses_stderr_text():
    """`adb tcpip` 的成功信息走 stderr，调用方把两路合并后传进来。"""
    res = w.parse_tcpip_output("restarting in TCP mode port: 5555\n")
    assert res == {"ok": True, "port": 5555,
                   "message": "已切换为无线模式（端口 5555）"}


def test_parse_tcpip_no_device():
    res = w.parse_tcpip_output("error: no devices/emulators found")
    assert res["ok"] is False
    assert "USB" in res["message"]


# ---------------------------------------------------------------- 最近连接
def test_add_recent_puts_newest_first_and_dedupes():
    out = w.add_recent(["1.1.1.1:5555", "2.2.2.2:5555"], "2.2.2.2:5555")
    assert out == ["2.2.2.2:5555", "1.1.1.1:5555"]


def test_add_recent_caps_length():
    items = ["%d.%d.%d.%d:5555" % (i, i, i, i) for i in range(1, 8)]
    out = w.add_recent(items, "9.9.9.9:5555")
    assert len(out) == w.MAX_RECENT
    assert out[0] == "9.9.9.9:5555"


def test_add_recent_ignores_empty():
    assert w.add_recent(["1.1.1.1:5555"], "  ") == ["1.1.1.1:5555"]


def test_recent_pref_roundtrip():
    raw = "1.1.1.1:5555, 2.2.2.2:6666"
    assert w.recent_from_pref(raw) == ["1.1.1.1:5555", "2.2.2.2:6666"]
    assert w.recent_to_pref(["1.1.1.1:5555", "2.2.2.2:6666"]) == \
        "1.1.1.1:5555,2.2.2.2:6666"
    assert w.recent_from_pref("") == []


@pytest.mark.parametrize("bad", [
    "999.1.1.1",          # 每段必须在 0~255
    "1.2.3",             # 只有三段
    "192.168.1.23.",     # 多一个点
    "1.2.3.4.5",
])
def test_normalize_reports_bad_ip_as_ip_not_hostname(bad):
    """像 IP 但写错的输入，报「IP 不合法」而不是含糊的「连接超时」。

    回归：`999.1.1.1` 完全符合主机名白名单（字母数字+点），旧实现会把它
    当合法主机名放行，一路走到 `adb connect` 才失败，界面显示「无法解析 /
    连接超时」——用户会去查网络、查防火墙，而真正的原因只是地址打错了。
    """
    addr, err = w.normalize_endpoint(bad)
    assert addr == ""
    assert "IP 地址不合法" in err
    assert "0~255" in err, "要说清正确写法，不能只说「不合法」"


def test_normalize_still_accepts_numeric_hostname_free_of_dots():
    """纯数字的主机名（热点偶尔这样发）不该被 IP 校验拦下。"""
    assert w.normalize_endpoint("12345") == ("12345:5555", "")
