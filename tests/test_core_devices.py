"""测试 core.devices（设备解析与增量 diff 决策）。

这是「设备指令/工具广播目标」「自动勾选唯一可用设备」「不可操作设备取消勾选」
等核心行为的纯逻辑保障，独立于任何前端。
"""
from core.devices import parse_devices, plan_devices
from core.constants import is_usable, state_label


def test_parse_devices_basic():
    raw = (
        "List of devices attached\n"
        "abc123\tdevice\tmodel:Pixel\n"
        "def456\toffline\n"
    )
    devs = parse_devices(raw)
    assert ("abc123", "device", "Pixel") in devs
    assert ("def456", "offline", "") in devs


def test_parse_devices_serial_containing_space():
    """序列号里含空格的设备必须整条解析出来。

    回归：解析用 `parts = line.split(); serial, state = parts[0], parts[1]`。
    但 adb 在 mDNS 服务名冲突时会打印带空格后缀的序列号
    （`adb-XXXX (2)._adb-tls-connect._tcp`），按空白切分后序列号被截断、
    state 变成 `(2)` —— 设备既显示成乱码状态，又永远无法勾选下发。
    """
    raw = (
        "List of devices attached\n"
        "adb-26151FDF60083B-9tP4nl (2)._adb-tls-connect._tcp device "
        "product:pixel transport_id:2\n"
    )
    assert parse_devices(raw) == [
        ("adb-26151FDF60083B-9tP4nl (2)._adb-tls-connect._tcp", "device", ""),
    ]


def test_parse_devices_multiword_state_no_permissions():
    """两词状态 `no permissions` 不能被截成 `no`（否则中文说明表里那条永远用不上）。"""
    raw = ("List of devices attached\n"
           "????????????\tno permissions (user in plugdev group; "
           "are your udev rules wrong?)\n")
    assert parse_devices(raw) == [("????????????", "no permissions", "")]
    assert state_label("no permissions") == "无权限（注意 udev / 驱动）"


def test_parse_devices_keeps_unknown_state_via_fallback():
    """未来 adb 新增的状态词不在已知表里时，仍按旧的空白切分保留设备。"""
    raw = "List of devices attached\nA1\tbrand-new-state\n"
    assert parse_devices(raw) == [("A1", "brand-new-state", "")]


def test_plan_preserves_checked_on_refresh():
    # 已勾选的在线设备刷新后应保留勾选
    prev_checked = {"abc123": True}
    prev_state = {"abc123": "device"}
    prev_model = {"abc123": "Pixel"}
    devices = [("abc123", "device", "Pixel")]
    plan = plan_devices(prev_checked, prev_state, prev_model, devices)
    item = next(i for i in plan["items"] if i["serial"] == "abc123")
    assert item["checked"] is True
    assert plan["changed"] is False


def test_plan_auto_selects_single_usable_first_load():
    # 首次加载、仅一台可用设备时自动勾选
    plan = plan_devices({}, {}, {}, [("abc123", "device", "Pixel")])
    item = plan["items"][0]
    assert item["checked"] is True
    assert plan["first_load"] is True


def test_plan_keeps_checked_on_unusable_flicker():
    # 设备原先勾选，本次变为 offline，但仍在列表中：勾选记忆保留（不强制取消），
    # 计入 stat_changed；dropped 恒为空（新版不再因不可用而取消勾选）。
    prev_checked = {"abc123": True}
    prev_state = {"abc123": "device"}
    devices = [("abc123", "offline", "Pixel")]
    plan = plan_devices(prev_checked, prev_state, {}, devices)
    item = plan["items"][0]
    assert item["checked"] is True
    assert item["ok"] is False
    assert plan["dropped"] == []
    assert "abc123" in plan["stat_changed"]


def test_plan_reports_added_and_gone():
    prev_checked = {"abc123": True}
    prev_state = {"abc123": "device"}
    # abc123 消失，新增 xyz789；单轮消失仍在宽限内（不视为 gone）
    devices = [("xyz789", "device", "Pixel2")]
    plan = plan_devices(prev_checked, prev_state, {}, devices)
    assert plan["gone"] == []
    assert plan["added"] == ["xyz789"]
    assert plan["changed"] is True
    # 携带上一次完整快照（勾选 + 状态 + absent 计数）继续刷新，超过宽限才真正 gone
    ck, st, pa = plan["checked"], plan["states"], plan["absent_streak"]
    plan2 = plan_devices(ck, st, {}, devices, prev_absent=pa)
    plan3 = plan_devices(plan2["checked"], plan2["states"], {}, devices,
                         prev_absent=plan2["absent_streak"])
    assert "abc123" in plan3["gone"]
    assert plan3["checked"].get("abc123") is not True


def test_usable_and_label_helpers():
    assert is_usable("device") is True
    assert is_usable("offline") is False
    assert state_label("unauthorized") == "未授权（请在设备屏幕上确认调试授权）"
    assert state_label("weird") == "weird"
