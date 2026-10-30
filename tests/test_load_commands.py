"""验证 core.commands.load_commands / normalize_commands 对小伙伴不同格式的兼容性，
以及内置默认命令的合并（用户自定义优先）。

（原 legacy_main_tk 版测试已迁移到 core 包：加载逻辑现位于 core.commands。）
"""
import json
import os

import core.commands as cmds_mod
from core.commands import load_commands, normalize_commands, merge_builtins
from core.builtin_commands import BUILTIN_COMMANDS


def _load_via_file(raw):
    """把 raw 写到临时目录的 quick_commands.json，走真实 load_commands（扫描目录）。"""
    import tempfile
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "quick_commands.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False)
    orig = cmds_mod.command_scan_dir
    cmds_mod.command_scan_dir = lambda: tmp
    try:
        return load_commands()
    finally:
        cmds_mod.command_scan_dir = orig


def test_current_format_still_works():
    """用户自己的格式：list + commands 数组，保持原样（内置默认会一并并入）。"""
    raw = [{
        "id": "a", "name": "查看时间", "labels": ["通用"],
        "commands": [{"delay": 100, "command": "adb shell date"}],
    }]
    cmds, warns = _load_via_file(raw)
    by_name = {c["name"]: c for c in cmds}
    assert "查看时间" in by_name
    assert by_name["查看时间"]["labels"] == ["通用"]
    assert by_name["查看时间"]["commands"][0]["command"] == "adb shell date"
    assert by_name["查看时间"]["commands"][0]["delay"] == 100
    assert warns == []


def test_commands_as_string_old_electerm():
    """旧版 electerm 把 commands 写成字符串，应被包装成单条命令。"""
    raw = [{"name": "投屏", "labels": ["通用"], "commands": "scrcpy"}]
    cmds, warns = _load_via_file(raw)
    by_name = {c["name"]: c for c in cmds}
    assert by_name["投屏"]["commands"] == [{"command": "scrcpy", "delay": 0}]
    assert warns == []


def test_cmd_field_instead_of_command():
    """命令字段叫 cmd 而非 command，应被正确识别。"""
    raw = [{"name": "c", "labels": ["x"], "commands": [{"cmd": "adb devices"}]}]
    cmds, warns = _load_via_file(raw)
    assert cmds[0]["commands"][0]["command"] == "adb devices"
    assert warns == []


def test_tags_instead_of_labels():
    """分组字段叫 tags 而非 labels，应被当作分组。"""
    raw = [{"name": "c", "tags": ["设备"], "commands": [{"command": "ls"}]}]
    cmds, warns = _load_via_file(raw)
    assert cmds[0]["labels"] == ["设备"]
    assert warns == []


def test_top_level_is_object():
    """顶层是对象（dict）而非数组，应取 values（内置默认会一并并入）。"""
    raw = {
        "id1": {"name": "c1", "labels": ["通用"], "commands": [{"command": "ls"}]},
        "id2": {"name": "c2", "labels": ["通用"], "commands": [{"command": "pwd"}]},
    }
    cmds, warns = _load_via_file(raw)
    by_name = {c["name"]: c for c in cmds}
    assert "c1" in by_name and "c2" in by_name
    assert warns == []


def test_mixed_string_and_dict_in_commands():
    """commands 数组里混了纯字符串，应都能解析。"""
    raw = [{
        "name": "c", "labels": ["x"],
        "commands": ["adb shell date", {"command": "ls", "delay": 50}],
    }]
    cmds, warns = _load_via_file(raw)
    by_name = {c["name"]: c for c in cmds}
    assert len(by_name["c"]["commands"]) == 2
    assert by_name["c"]["commands"][0] == {"command": "adb shell date", "delay": 0}
    assert by_name["c"]["commands"][1] == {"command": "ls", "delay": 50}
    assert warns == []


def test_no_name_falls_back_to_id():
    raw = [{"id": "xyz", "commands": [{"command": "ls"}]}]
    cmds, warns = _load_via_file(raw)
    assert cmds[0]["name"] == "xyz"
    assert cmds[0]["labels"] == ["其他"]   # 无标签归到「其他」
    assert warns == []


def test_unparseable_entry_is_skipped_with_warning():
    """整条命令解析不出任何可执行命令，应跳过并告警，但不影响其它。"""
    raw = [
        {"name": "坏命令", "labels": ["x"], "commands": []},   # 空命令
        {"name": "好命令", "labels": ["x"], "commands": [{"command": "ls"}]},
    ]
    cmds, warns = _load_via_file(raw)
    by_name = {c["name"]: c for c in cmds}
    assert "好命令" in by_name          # 好命令保留（内置默认另算，不在此断言）
    assert any("坏命令" in w for w in warns)


def test_empty_file_falls_back_to_builtins():
    """完全解析不出命令时，回退到内置默认命令（程序自带通用集）。"""
    cmds, warns = _load_via_file([])
    assert len(cmds) >= len(BUILTIN_COMMANDS)
    ids = {c["id"] for c in cmds}
    assert all(b["id"] in ids for b in BUILTIN_COMMANDS)
    assert any("回退" in w for w in warns)


def test_builtins_supplement_when_user_has_no_equivalent():
    """用户 quick_commands.json 为空时，内置默认命令全部补齐。"""
    cmds, _ = _load_via_file([])
    ids = {c["id"] for c in cmds}
    assert ids == {b["id"] for b in BUILTIN_COMMANDS}


def test_user_same_name_suppresses_builtin():
    """用户已有一条同名（去掉 [标签] 前缀）命令时，内置被压制，避免重复。"""
    raw = [{"id": "u1", "name": "[通用] 设备序列号", "labels": ["通用"],
            "commands": [{"command": "adb get-serialno --custom"}]}]
    cmds, _ = _load_via_file(raw)
    by_id = {c["id"]: c for c in cmds}
    assert "u1" in by_id                       # 用户的保留
    assert by_id["u1"]["commands"][0]["command"] == "adb get-serialno --custom"
    assert "bi.serial" not in by_id            # 同名内置被压制


def test_user_same_id_overrides_builtin():
    """用户用与内置相同的 id 定义命令时，用户的精确覆盖内置。"""
    raw = [{"id": "bi.serial", "name": "[内置] 设备序列号", "labels": ["通用"],
            "commands": [{"command": "adb get-serialno --override"}]}]
    cmds, _ = _load_via_file(raw)
    by_id = {c["id"]: c for c in cmds}
    assert by_id["bi.serial"]["commands"][0]["command"] == "adb get-serialno --override"


def test_whitespace_only_difference_suppresses_builtin():
    """用户命令与内置仅空格差异（如「获取当前 Activity」vs「获取当前Activity」）
    应视为同名而被压制，避免重复出现。"""
    raw = [{"id": "u1", "name": "[通用] 获取当前 Activity", "labels": ["通用"],
            "commands": [{"command": "adb shell dumpsys window"}]}]
    cmds, _ = _load_via_file(raw)
    by_id = {c["id"]: c for c in cmds}
    assert "u1" in by_id
    assert "bi.current-activity" not in by_id


def test_builtin_flag_present():
    """并入的内置命令带 builtin=True 标记，便于前端区分/禁止误删。"""
    cmds, _ = _load_via_file([])
    builtins = [c for c in cmds if c.get("builtin")]
    assert len(builtins) == len(BUILTIN_COMMANDS)
    assert all(c["builtin"] is True for c in builtins)


def test_merge_builtins_pure_function():
    """merge_builtins 不修改入参。"""
    user = [{"id": "x", "name": "[通用] 截图", "labels": ["通用"],
             "commands": [{"command": "x"}]}]
    snapshot = [dict(c) for c in user]
    merge_builtins(user)
    assert user == snapshot


# ---------------------------------------------------------------------------
# 内置命令独立为「内置」标签：与用户的「通用」等分组解耦，前端把它钉在
# 标签条/分组列表最底，避免 20 条程序默认命令冲掉用户自己的命令。
# ---------------------------------------------------------------------------
def test_builtins_all_carry_builtin_label():
    """每条内置命令的 labels 都必须恰为 ["内置"]（不再混进用户的「通用」）。"""
    for b in BUILTIN_COMMANDS:
        assert b["labels"] == ["内置"], (b["id"], b["labels"])
    assert BUILTIN_COMMANDS, "内置命令集不应为空"


def test_builtins_not_polluting_user_tag_generic():
    """load_commands 并入内置后，「通用」标签下不得出现内置命令。"""
    raw = [{"id": "u", "name": "我的命令", "labels": ["通用"],
            "commands": [{"command": "adb devices"}]}]
    cmds, _ = _load_via_file(raw)
    generic = [c for c in cmds if "通用" in (c.get("labels") or [])]
    assert generic, "用户命令应仍在通用标签下"
    assert all(not c.get("builtin") for c in generic), \
        "内置命令混进了「通用」：%r" % [c["id"] for c in generic if c.get("builtin")]
    builtins = [c for c in cmds if c.get("builtin")]
    assert builtins and all(c["labels"] == ["内置"] for c in builtins)


# ---------------------------------------------------------------------------
# clickCount：使用频次必须透传到前端（「常用命令靠前」排序的数据源）
# ---------------------------------------------------------------------------
def test_click_count_preserved_through_normalize():
    raw = [
        {"id": "a", "name": "常用", "labels": ["x"], "clickCount": 12,
         "commands": [{"command": "ls"}]},
        {"id": "b", "name": "冷门", "labels": ["x"], "clickCount": 1,
         "commands": [{"command": "pwd"}]},
    ]
    cmds, warns = _load_via_file(raw)
    assert warns == []
    by_id = {c["id"]: c for c in cmds}
    assert by_id["a"]["clickCount"] == 12
    assert by_id["b"]["clickCount"] == 1


def test_save_click_deltas_updates_json_in_place():
    """回写只累加 clickCount，其余字段（含用户手改的自定义键）原样保留。"""
    raw = [{"id": "a", "name": "x", "labels": ["g"], "comment": "keep-me",
            "clickCount": 3, "commands": [{"command": "ls"}]}]
    tmp = os.path.join(__import__("tempfile").mkdtemp(), "quick_commands.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False)
    orig = cmds_mod.command_scan_dir
    cmds_mod.command_scan_dir = lambda: os.path.dirname(tmp)
    try:
        cmds_mod.save_click_deltas({"a": 2, "missing": 9})
    finally:
        cmds_mod.command_scan_dir = orig
    with open(tmp, encoding="utf-8") as f:
        data = json.load(f)
    assert data[0]["clickCount"] == 5       # 3 + 2
    assert data[0]["name"] == "x"
    assert data[0]["comment"] == "keep-me"  # 未识别的自定义字段不得被抹掉
    assert data[0]["commands"] == [{"command": "ls"}]


def test_save_click_deltas_handles_dict_top_level():
    """顶层为 dict 时同样按 id 更新（与 normalize 兼容的输入形态）。"""
    raw = {"a": {"id": "a", "name": "x", "clickCount": 0,
                 "commands": [{"command": "ls"}]}}
    tmp = os.path.join(__import__("tempfile").mkdtemp(), "quick_commands.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False)
    orig = cmds_mod.command_scan_dir
    cmds_mod.command_scan_dir = lambda: os.path.dirname(tmp)
    try:
        cmds_mod.save_click_deltas({"a": 1})
    finally:
        cmds_mod.command_scan_dir = orig
    with open(tmp, encoding="utf-8") as f:
        data = json.load(f)
    assert data["a"]["clickCount"] == 1


def test_save_click_deltas_matches_numeric_id():
    """json 里 id 写成数字（"id": 1）时，点击计数也必须能写回。

    回归：normalize_commands 会把数字 id 归一化成字符串 "1"（内存态命令的 id），
    而回写时旧实现直接拿文件里的原始值 1 去比字典键 "1" —— 永远比不中，
    这类命令的点击计数静默丢失，「常用命令靠前」排序对它们从不生效。
    """
    raw = [{"id": 1, "name": "数字id", "clickCount": 0,
            "commands": [{"command": "ls"}]}]
    tmp = os.path.join(__import__("tempfile").mkdtemp(), "quick_commands.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False)
    orig = cmds_mod.command_scan_dir
    cmds_mod.command_scan_dir = lambda: os.path.dirname(tmp)
    try:
        # 前端下发的 cmd_id 是归一化后的字符串（见 normalize_commands）
        cmds_mod.save_click_deltas({"1": 2})
    finally:
        cmds_mod.command_scan_dir = orig
    with open(tmp, encoding="utf-8") as f:
        data = json.load(f)
    assert data[0]["clickCount"] == 2
    # 文件里的原始数字 id 形态不被改写（只动 clickCount）
    assert data[0]["id"] == 1


# ---------------------------------------------------------------------------
# 源码卫生：内置命令含 PowerShell 正则（如 '(\S+)/'），写在普通字符串里会触发
# 无效转义序列警告（DeprecationWarning，未来 Python 版本将升为语法错误）。
# 这里直接编译源码文本（不受 import 缓存影响），把该类回归一次拦住。
# ---------------------------------------------------------------------------
def test_core_sources_have_no_invalid_escape_sequences():
    import warnings
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    sources = [root / "core" / "builtin_commands.py", root / "core" / "commands.py"]
    for src in sources:
        text = src.read_text(encoding="utf-8")
        with warnings.catch_warnings():
            warnings.simplefilter("error")     # 任何 SyntaxWarning/DeprecationWarning 都算失败
            compile(text, str(src), "exec")


def test_builtin_regex_command_text_unchanged():
    r"""回归：把含正则的命令改为 raw 字符串时，命令文本必须逐字节不变
    （ PowerShell 的 -match '(\S+)/' 少一个反斜杠就匹配不到包名/Activity ）。"""
    cmd = next(
        e["command"] for b in BUILTIN_COMMANDS if b["id"] == "bi.kill-activity"
        for e in b["commands"])
    assert cmd == (
        r"adb shell dumpsys window | sls mCurrentFocus | %{ if ($_ -match '(\S+)/') "
        r"{ adb shell am force-stop $Matches[1] } }")


def test_builtin_wake_unlock_uses_wakeup_not_power():
    """「亮屏并上滑解锁」必须用 KEYCODE_WAKEUP(224)，不能用 POWER(26)。

    回归：26 是电源**开关**，屏幕亮着时按下去等于熄屏，后面的上滑自然毫无效果 ——
    命令名说「亮屏」，实际做的是把屏幕关掉。
    """
    cmds = [e["command"] for b in BUILTIN_COMMANDS
            if b["id"] == "bi.wake-unlock" for e in b["commands"]]
    assert "adb shell input keyevent 224" in cmds, cmds
    assert not any("keyevent 26" in c for c in cmds), cmds


def test_builtin_commands_avoid_non_gbK_chars():
    """内置命令里不能出现 GBK 编码不下的字符。

    会话管道用的是系统区域默认编码（中文 Windows 为 cp936），✅/❌ 这类字符编码不进
    GBK，会被 errors="replace" 换成 "?"，状态行变成「[时间] ? ADB设备已连接」，
    一眼看不出是成功还是失败。
    """
    for b in BUILTIN_COMMANDS:
        for e in b["commands"]:
            cmd = e["command"]
            try:
                cmd.encode("gbk")
            except UnicodeEncodeError as ex:
                raise AssertionError(
                    "内置命令 %s 含 GBK 无法编码的字符（会显示成 ?）：%s"
                    % (b["id"], ex))


def test_load_commands_tolerates_utf8_bom():
    """带 UTF-8 BOM 的 quick_commands.json 必须照常加载。

    回归：使用说明让同事「用记事本编辑」，而记事本保存 UTF-8 会写入 BOM，
    `json.load(encoding="utf-8")` 遇 BOM 直接抛 JSONDecodeError —— 用户改完命令
    却「一条都没生效」，全部回退内置默认。
    """
    import tempfile
    raw = [{"id": "a", "name": "带BOM", "labels": ["通用"],
            "commands": [{"command": "adb shell date"}]}]
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "quick_commands.json")
    with open(path, "w", encoding="utf-8-sig") as f:      # utf-8-sig 会写 BOM
        json.dump(raw, f, ensure_ascii=False)
    assert open(path, "rb").read(3) == b"\xef\xbb\xbf", "样本文件应带 BOM"

    orig = cmds_mod.command_scan_dir
    cmds_mod.command_scan_dir = lambda: tmp
    try:
        cmds, warns = cmds_mod.load_commands()
    finally:
        cmds_mod.command_scan_dir = orig
    assert any(c["name"] == "带BOM" for c in cmds), \
        "带 BOM 的文件被当成损坏而整体回退：%r" % warns
    assert warns == [], warns


def test_non_string_fields_do_not_break_loading():
    """文件里出现类型不对的字段时，只跳过那一条，不能让整次加载抛异常。

    回归：`"id": 1`（数字）会走到 `core_name(name)` 的 re.sub 上抛 TypeError，
    `"command": ["adb","devices"]` 会抛 AttributeError。而 `load_commands` 的调用方
    controller.boot() 没有兜底 —— 程序启动后一条命令都没有，界面只显示「未就绪」。
    """
    raw = [
        {"id": 1, "commands": [{"command": "adb devices"}]},          # 数字 id
        {"name": "坏命令", "commands": [{"command": ["adb", "x"]}]},   # 命令不是字符串
        {"name": "好命令", "labels": ["x"], "commands": [{"command": "ls"}]},
        "这不是对象",
    ]
    cmds, warns = _load_via_file(raw)
    names = [c["name"] for c in cmds]
    assert "好命令" in names, names
    assert all(isinstance(c["id"], str) and c["id"] for c in cmds), \
        "每条命令都必须有非空的字符串 id：%r" % [c["id"] for c in cmds]
    assert any("不是字符串" in w for w in warns), warns
    assert any("不是对象" in w for w in warns), warns


def test_missing_or_duplicate_ids_become_unique():
    """缺失 / 重复的 id 必须各自补成唯一值。

    回归：旧实现把缺失的 id 都留成 ""，重复的原样保留 —— run_command 按 id 查表时
    全都命中第一条，点哪张卡片都执行同一条命令，点击计数也会同时加到多条上。
    """
    raw = [
        {"name": "无id甲", "labels": ["x"], "commands": [{"command": "ls"}]},
        {"name": "无id乙", "labels": ["x"], "commands": [{"command": "pwd"}]},
        {"id": "dup", "name": "重复甲", "labels": ["x"], "commands": [{"command": "a"}]},
        {"id": "dup", "name": "重复乙", "labels": ["x"], "commands": [{"command": "b"}]},
    ]
    cmds, _ = _load_via_file(raw)
    ids = [c["id"] for c in cmds if not c.get("builtin")]
    assert len(ids) == len(set(ids)), "id 必须互不相同：%r" % ids
    assert all(ids), ids
    # 原有 id 不受影响（重复条目里保留第一条）
    assert "dup" in ids


def test_click_delta_applies_to_first_duplicate_only():
    """同一 id 出现多次时，点击增量只累加到第一条（否则点一次等于点 N 次）。"""
    raw = [{"id": "d", "name": "甲", "clickCount": 0, "commands": [{"command": "a"}]},
           {"id": "d", "name": "乙", "clickCount": 0, "commands": [{"command": "b"}]}]
    tmp = os.path.join(__import__("tempfile").mkdtemp(), "quick_commands.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False)
    orig = cmds_mod.command_scan_dir
    cmds_mod.command_scan_dir = lambda: os.path.dirname(tmp)
    try:
        cmds_mod.save_click_deltas({"d": 1})
    finally:
        cmds_mod.command_scan_dir = orig
    with open(tmp, encoding="utf-8") as f:
        data = json.load(f)
    assert data[0]["clickCount"] == 1
    assert data[1]["clickCount"] == 0, "重复 id 的第二条不该被一起累加"


# ---------------------------------------------------------------------------
# inputOnly：electerm 的「仅输入模式」——点击只把命令填进输入框、不直接执行，
# 给用户一个确认/改参数的机会。标记为顶层 "inputOnly": true。
# ---------------------------------------------------------------------------
def test_input_only_true_fills_input_not_runs():
    """inputOnly=true 的命令必须原样带出标记（前端据此只填输入框）。"""
    raw = [{"id": "a", "name": "仅输入", "labels": ["x"], "inputOnly": True,
            "commands": [{"command": "adb shell setprop persist.sys.locale zh-CN"}]}]
    cmds, warns = _load_via_file(raw)
    by_id = {c["id"]: c for c in cmds}
    assert warns == []
    assert by_id["a"]["inputOnly"] is True


def test_input_only_absent_defaults_false():
    """没有 inputOnly 字段（绝大多数命令）默认 False，语义不变。"""
    raw = [{"id": "a", "name": "普通", "labels": ["x"],
            "commands": [{"command": "ls"}]}]
    cmds, warns = _load_via_file(raw)
    assert warns == []
    assert cmds[0]["inputOnly"] is False


def test_input_only_false_is_false():
    """显式 inputOnly=false 不得被误判为真。"""
    raw = [{"id": "a", "name": "显式假", "labels": ["x"], "inputOnly": False,
            "commands": [{"command": "ls"}]}]
    cmds, _ = _load_via_file(raw)
    assert cmds[0]["inputOnly"] is False


def test_input_only_string_and_number_variants():
    """手写 json 常见把 true 写成 "true" / 1 / "yes" / "on"：都要认出来。"""
    variants = [("true", True), ("1", True), ("yes", True), ("on", True),
                ("false", False), ("0", False), ("no", False),
                (1, True), (0, False), (None, False), ([], False)]
    for i, (val, expect) in enumerate(variants):
        raw = [{"id": "a%d" % i, "name": "变体%d" % i, "labels": ["x"],
                "inputOnly": val, "commands": [{"command": "ls"}]}]
        cmds, warns = _load_via_file(raw)
        assert warns == [], (val, warns)
        assert cmds[0]["inputOnly"] is expect, (val, cmds[0]["inputOnly"])


def test_input_only_survives_merge_builtins():
    """merge_builtins 并入内置命令时也必须补齐 inputOnly 键（前端统一读）。"""
    user = [{"id": "u", "name": "用户", "labels": ["x"], "inputOnly": True,
             "commands": [{"command": "ls"}]}]
    merged = merge_builtins(user)
    by_id = {c["id"]: c for c in merged}
    assert by_id["u"]["inputOnly"] is True, "用户命令的标记不得在合并时丢失"
    for b in merged:
        if b.get("builtin"):
            assert b["inputOnly"] is False, "内置命令一律直接执行"


# ---------------------------------------------------------------------------
# 运行目录多文件扫描 / 合并去重 / 无文件时生成 commands.json
# ---------------------------------------------------------------------------
def _load_dir(files):
    """在临时目录写入若干 json，令 command_scan_dir 指向它后走真实 load_commands。

    返回 (目录, (commands, warnings))。
    """
    import tempfile
    tmp = tempfile.mkdtemp()
    for name, data in files.items():
        with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    orig = cmds_mod.command_scan_dir
    cmds_mod.command_scan_dir = lambda: tmp
    try:
        res = cmds_mod.load_commands()
    finally:
        cmds_mod.command_scan_dir = orig
    return tmp, res


def _user_names(cmds):
    return [c["name"] for c in cmds if not c.get("builtin")]


def test_loads_commands_json_in_run_dir():
    """运行目录里的 commands.json 会被自动发现并加载。"""
    _, (cmds, warns) = _load_dir({
        "commands.json": [{"id": "a", "name": "[通用] 查看时间", "labels": ["通用"],
                           "commands": [{"command": "adb shell date"}]}],
    })
    assert "[通用] 查看时间" in _user_names(cmds)
    assert warns == []


def test_merges_multiple_command_files_and_dedupes():
    """目录里多份命令合集：合并，并按 id / 核心名去重（保留先出现者）。"""
    _, (cmds, warns) = _load_dir({
        "commands.json": [
            {"id": "x", "name": "[通用] 重启", "labels": ["通用"],
             "commands": [{"command": "adb reboot"}]},
        ],
        "team.json": [
            # 核心名同为「重启」→ 应与上面合并为一条（不同 id，靠同名去重）
            {"id": "z", "name": "重启", "labels": ["设备"],
             "commands": [{"command": "adb reboot"}]},
            {"id": "w", "name": "[设备] 序列号", "labels": ["设备"],
             "commands": [{"command": "adb get-serialno"}]},
        ],
    })
    names = _user_names(cmds)
    assert "[通用] 重启" in names and "[设备] 序列号" in names, names
    assert names.count("重启") == 0, "同名重复项应被去重：%r" % names
    assert sum(1 for n in names if n in ("[通用] 重启", "重启")) == 1, names
    assert any("合并" in w for w in warns), warns


def test_dedupe_by_same_id_across_files():
    """不同文件里 id 相同且命令内容相同的命令视为同一条，只保留先出现的。"""
    _, (cmds, _) = _load_dir({
        "commands.json": [{"id": "dup", "name": "[通用] 甲", "labels": ["通用"],
                           "commands": [{"command": "adb devices"}]}],
        "other.json": [{"id": "dup", "name": "[通用] 乙", "labels": ["通用"],
                        "commands": [{"command": "adb devices"}]}],
    })
    names = _user_names(cmds)
    assert "[通用] 甲" in names and "[通用] 乙" not in names, names


def test_same_name_different_command_is_not_deduped():
    """同名但命令内容不同（同一功能在不同项目各一份）必须都保留，不能误删。"""
    _, (cmds, _) = _load_dir({
        "commands.json": [
            {"id": "j", "name": "[J01] 清缓存", "labels": ["J01"],
             "commands": [{"command": "adb shell pm clear com.j01.app"}]},
            {"id": "c", "name": "[CEI] 清缓存", "labels": ["CEI"],
             "commands": [{"command": "adb shell pm clear com.cei.app"}]},
        ],
    })
    names = _user_names(cmds)
    assert "[J01] 清缓存" in names and "[CEI] 清缓存" in names, names


def test_generates_commands_json_when_no_file():
    """目录里没有任何有效命令合集文件时，自动生成 commands.json。"""
    tmp, (cmds, warns) = _load_dir({})
    generated = os.path.join(tmp, "commands.json")
    assert os.path.exists(generated), "应生成 commands.json"
    with open(generated, encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, list) and data, "生成的 commands.json 应是含示例命令的数组"
    assert any("生成" in w and "commands.json" in w for w in warns), warns
    # 生成的示例命令应被加载（用户命令里能看到）
    assert any(not c.get("builtin") for c in cmds)


def test_config_json_is_not_treated_as_command_file():
    """config.json（配置）不能被当作命令合集；只剩它时应触发生成 commands.json。"""
    tmp, (_cmds, warns) = _load_dir({
        "config.json": {"keep_input": True, "save_dir": "", "rec_zip": True},
    })
    assert os.path.exists(os.path.join(tmp, "commands.json")), \
        "只有 config.json 时应生成 commands.json"
    assert any("生成" in w for w in warns), warns


def test_primary_path_prefers_commands_json():
    """写回目标优先 commands.json；只有历史 quick_commands.json 时才写它。"""
    import tempfile
    d = tempfile.mkdtemp()
    # 只有 legacy 时写 legacy
    with open(os.path.join(d, "quick_commands.json"), "w", encoding="utf-8") as f:
        json.dump([], f)
    assert os.path.basename(cmds_mod.primary_command_path(d)) == "quick_commands.json"
    # 两个都在时优先 commands.json
    with open(os.path.join(d, "commands.json"), "w", encoding="utf-8") as f:
        json.dump([], f)
    assert os.path.basename(cmds_mod.primary_command_path(d)) == "commands.json"
    # 都没有时返回 commands.json（写入时创建）
    d2 = tempfile.mkdtemp()
    assert os.path.basename(cmds_mod.primary_command_path(d2)) == "commands.json"


def test_generated_file_is_valid_command_collection():
    """生成的 commands.json 必须能被再次解析出命令（模板可用，不是空壳）。"""
    tmp, _ = _load_dir({})
    with open(os.path.join(tmp, "commands.json"), encoding="utf-8") as f:
        raw = json.load(f)
    cmds, _w = normalize_commands(raw)
    assert cmds, "生成的模板应至少含一条可解析的示例命令"
    assert all(c["commands"] for c in cmds)


def test_export_backup_files_are_ignored():
    """commands_export_*.json 是导出备份，不进入扫描（否则删除的命令会被加回来）。"""
    _, (cmds, _w) = _load_dir({
        "commands.json": [{"id": "a", "name": "[通用] 保留", "labels": ["通用"],
                           "commands": [{"command": "ls"}]}],
        "commands_export_20260101_000000.json": [
            {"id": "b", "name": "[通用] 备份里的", "labels": ["通用"],
             "commands": [{"command": "pwd"}]}],
    })
    names = _user_names(cmds)
    assert "[通用] 保留" in names, names
    assert "[通用] 备份里的" not in names, names

# --------------------------------------------------------------------------- #
# 内置命令集（v2026.1029.1500 起大幅扩充：按键 / 屏幕状态 / 网络 / 性能调试）
# --------------------------------------------------------------------------- #
def test_builtin_ids_unique_and_namespaced():
    """id 必须唯一且带 bi. 前缀：命令行按 id 落 clickCount，重 id 会让
    「常用靠前」的排序同时加到所有同 id 条目上（见 normalize_commands 的说明）。"""
    ids = [c["id"] for c in BUILTIN_COMMANDS]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("bi.") for i in ids)


def test_builtin_entries_are_well_formed():
    """每条内置命令都要能直接被前端渲染 + 被 run_command 执行。"""
    for c in BUILTIN_COMMANDS:
        assert c["labels"] == ["内置"], c["id"]
        assert c.get("builtin") is True
        assert c["name"].startswith("[内置] "), c["id"]
        assert c["commands"], c["id"]
        for item in c["commands"]:
            cmd = item["command"]
            assert cmd.strip() == cmd and cmd, c["id"]
            # 会话是一行一条喂给 PowerShell 的：命令里出现换行会被拆成两条，
            # 后半截变成一条独立命令直接执行（最坏情况是执行了半句 rm/reboot）
            assert "\n" not in cmd and "\r" not in cmd, c["id"]


# 这一轮明确要「更多点」的几组：ids 是契约，改名可以，删掉必须显式改这里
_EXPECTED_IDS = {
    # 指针位置 / 触摸圆点（用户点名要的四条）
    "bi.pointer-on", "bi.pointer-off", "bi.touch-on", "bi.touch-off",
    # 屏幕与按键
    "bi.screen-off", "bi.screen-on", "bi.key-back", "bi.key-home",
    "bi.key-recents", "bi.vol-up", "bi.vol-down", "bi.vol-mute",
    "bi.home-desktop", "bi.stayon-on", "bi.stayon-off",
    # 旋转
    "bi.rot-portrait", "bi.rot-landscape", "bi.rot-auto",
    # 网络
    "bi.airplane-on", "bi.airplane-off", "bi.wifi-on", "bi.wifi-off",
    "bi.data-on", "bi.data-off", "bi.wlan-ip",
    # 性能与调试
    "bi.anim-off", "bi.anim-on", "bi.kill-all", "bi.logcat-clear",
    "bi.battery", "bi.storage", "bi.meminfo", "bi.third-party",
}


def test_builtin_covers_device_operations():
    have = {c["id"] for c in BUILTIN_COMMANDS}
    missing = sorted(_EXPECTED_IDS - have)
    assert not missing, "内置命令缺少：%s" % missing


def test_builtin_group_is_reasonably_rich():
    """「内置」组要真能当兜底用：太少就等于没有（本轮从 21 条扩到 45+）。"""
    assert len(BUILTIN_COMMANDS) >= 40


def _cmd_of(cid):
    for c in BUILTIN_COMMANDS:
        if c["id"] == cid:
            return c["commands"][0]["command"]
    raise AssertionError("没有这条内置命令: %s" % cid)


def test_on_off_pairs_touch_the_same_setting():
    """成对的开关必须改同一个键、且值互补：写成两个不同的键时，
    「开启」能开、「关闭」关不掉，用户会以为设备坏了。"""
    pairs = [
        ("bi.pointer-on", "bi.pointer-off", "pointer_location"),
        ("bi.touch-on", "bi.touch-off", "show_touches"),
        ("bi.wifi-on", "bi.wifi-off", "svc wifi"),
        ("bi.data-on", "bi.data-off", "svc data"),
        ("bi.stayon-on", "bi.stayon-off", "stayon"),
    ]
    for on_id, off_id, key in pairs:
        on_cmd, off_cmd = _cmd_of(on_id), _cmd_of(off_id)
        assert key in on_cmd, (on_id, key)
        assert key in off_cmd, (off_id, key)
    # 值互补：一个 1 / 一个 0（或 enable / disable）
    for on_id, off_id in (("bi.pointer-on", "bi.pointer-off"),
                          ("bi.touch-on", "bi.touch-off")):
        assert _cmd_of(on_id).endswith(" 1")
        assert _cmd_of(off_id).endswith(" 0")
    for on_id, off_id in (("bi.wifi-on", "bi.wifi-off"),
                          ("bi.data-on", "bi.data-off")):
        assert _cmd_of(on_id).endswith("enable")
        assert _cmd_of(off_id).endswith("disable")


def test_power_key_is_not_used_for_screen_on():
    """亮屏必须用 224（WAKEUP）而不是 26（POWER）：26 是电源**开关**，
    屏幕本来就亮时按下去等于熄屏 —— 名字说「亮屏」，效果却是把屏关掉。"""
    assert "224" in _cmd_of("bi.screen-on")
    assert "keyevent 26" not in _cmd_of("bi.screen-on")
    assert "223" in _cmd_of("bi.screen-off")


def test_builtin_merge_without_user_commands_keeps_everything():
    merged = merge_builtins([])
    assert len(merged) == len(BUILTIN_COMMANDS)
    assert all("inputOnly" in c for c in merged)
    assert all(c["inputOnly"] is False for c in merged)


def test_same_name_user_command_suppresses_builtin():
    """用户自带同名命令时不重复显示（内置只是兜底）——「开启指针位置」就是典型：
    老用户的 commands.json 里已有这条，界面上不该出现第二个同名卡片。"""
    user = [{"id": "u1", "name": "[通用] 开启指针位置", "labels": ["通用"],
             "commands": [{"command": "adb shell settings put system pointer_location 1"}]}]
    merged = merge_builtins(user)
    names = [c["name"] for c in merged]
    assert "[通用] 开启指针位置" in names
    assert "[内置] 开启指针位置" not in names
    # 其余内置照常补齐
    assert "[内置] 息屏" in names


# ---------------------------------------------------------------------------
# 内置命令的二级分组（section）
# ---------------------------------------------------------------------------
# 49 条平铺在界面上要横跨两三屏，前端按 section 分成六段并可折叠。分组名是
# 「前后端共享的枚举」：后端写归属、前端定顺序（BUILTIN_SECTIONS）。写歪一个
# 字（「网络」写成「网络 」）不会报错，只会让那条命令悄悄掉进「其他」——
# 故这里把六个名字钉死成契约。
BUILTIN_SECTIONS = ["连接与投屏", "显示辅助", "按键", "屏幕状态", "网络", "应用与信息"]


def test_every_builtin_has_known_section():
    missing = [c["id"] for c in BUILTIN_COMMANDS if not c.get("section")]
    assert not missing, "这些内置命令没写 section：%s" % missing
    bad = [(c["id"], c["section"]) for c in BUILTIN_COMMANDS
           if c["section"] not in BUILTIN_SECTIONS]
    assert not bad, "section 不在白名单（前端会归到「其他」）：%s" % bad


def test_sections_are_all_used_and_not_tiny():
    from collections import Counter
    cnt = Counter(c["section"] for c in BUILTIN_COMMANDS)
    assert set(cnt) == set(BUILTIN_SECTIONS), cnt
    # 少于 3 条的分组没有单独折叠的意义，反而多一次点击
    assert all(n >= 3 for n in cnt.values()), cnt
    assert sum(cnt.values()) == len(BUILTIN_COMMANDS)


def test_section_does_not_leak_into_labels():
    """section 是二级分组，不能混进 labels：labels 决定一级分组和顶部标签条，
    六个细分塞进标签条会把「通用 / 常用」挤出视野。"""
    for c in BUILTIN_COMMANDS:
        assert c["labels"] == ["内置"], (c["id"], c["labels"])


def test_section_survives_merge_for_frontend():
    """前端靠 booted 载荷里的 section 分组，merge_builtins 若把字段丢了，
    界面上就只剩一个 49 条的平铺组（不报错，只是难用）。"""
    merged = merge_builtins([])
    assert all("section" in c for c in merged)
    assert {c["section"] for c in merged} == set(BUILTIN_SECTIONS)
