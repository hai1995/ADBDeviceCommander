# -*- coding: utf-8 -*-
"""core.prefs —— config.json 配置读写 + adb 目录注入 PATH（纯逻辑单测）。"""
import json
import os
import sys

import pytest

import core.prefs as prefs


def _patch_path(monkeypatch, tmp_path):
    """把配置读写指向 tmp_path/config.json（测试隔离，不碰真实配置）。"""
    p = str(tmp_path / "config.json")
    monkeypatch.setattr(prefs, "prefs_path", lambda: p)
    return p


def _patch_legacy_path(monkeypatch, tmp_path):
    """把「旧版 settings.json」路径也指向 tmp_path（用于迁移测试）。"""
    p = str(tmp_path / "settings.json")
    monkeypatch.setattr(prefs, "legacy_prefs_path", lambda: p)
    return p


def test_load_missing_file_returns_empty(monkeypatch, tmp_path):
    _patch_path(monkeypatch, tmp_path)
    assert prefs.load_prefs() == {}


def test_save_merges_and_persists(monkeypatch, tmp_path):
    p = _patch_path(monkeypatch, tmp_path)
    merged = prefs.save_prefs({"save_dir": r"D:\shots"})
    assert merged["save_dir"] == r"D:\shots"
    # 第二次保存是合并而非整文件覆盖
    merged = prefs.save_prefs({"adb_dir": r"D:\platform-tools"})
    assert merged["save_dir"] == r"D:\shots"
    assert merged["adb_dir"] == r"D:\platform-tools"
    with open(p, encoding="utf-8") as f:
        raw = json.load(f)
    assert raw["save_dir"] == r"D:\shots"


def test_load_corrupt_file_returns_empty(monkeypatch, tmp_path):
    p = _patch_path(monkeypatch, tmp_path)
    with open(p, "w", encoding="utf-8") as f:
        f.write("{ not json !!!")
    assert prefs.load_prefs() == {}


def test_apply_adb_dir_prepends_and_restores(monkeypatch, tmp_path):
    adbdir = tmp_path / "pt"
    adbdir.mkdir()
    (adbdir / "adb.exe").write_text("", encoding="utf-8")
    env = {"PATH": r"C:\base;D:\other"}
    assert prefs.apply_adb_dir(str(adbdir), env) is True
    assert env["PATH"].startswith(str(adbdir) + os.pathsep)
    assert r"C:\base;D:\other" in env["PATH"]
    # 同目录重复注入幂等（不重复前插）
    prefs.apply_adb_dir(str(adbdir), env)
    assert env["PATH"].count(str(adbdir)) == 1
    # 从有到无：摘除前插，恢复原 PATH
    assert prefs.apply_adb_dir("", env) is False
    assert env["PATH"] == r"C:\base;D:\other"


def test_apply_adb_dir_accepts_adb_exe_full_path(monkeypatch, tmp_path):
    adbdir = tmp_path / "pt2"
    adbdir.mkdir()
    exe = str(adbdir / "adb.exe")
    (adbdir / "adb.exe").write_text("", encoding="utf-8")
    env = {"PATH": "C:\\base"}
    assert prefs.apply_adb_dir(exe, env) is True
    assert env["PATH"].startswith(str(adbdir) + os.pathsep)
    # 无效目录直接返回 False 且不改 PATH
    assert prefs.apply_adb_dir(str(tmp_path / "not_exist"), env) is False


def test_get_pref_defaults_when_absent(monkeypatch, tmp_path):
    """没写过的开关走 default（「默认开启」类偏好不能因为键缺失就变成关）。"""
    _patch_path(monkeypatch, tmp_path)
    assert prefs.get_pref("shot_to_clipboard", True) is True
    assert prefs.get_pref("shot_to_clipboard", False) is False


def test_get_pref_respects_explicit_false(monkeypatch, tmp_path):
    """显式关掉（false）必须与「没写过」区分开，否则用户关了也会被默认覆盖。"""
    p = _patch_path(monkeypatch, tmp_path)
    prefs.save_prefs({"shot_to_clipboard": False})
    assert prefs.get_pref("shot_to_clipboard", True) is False
    prefs.save_prefs({"shot_to_clipboard": True})
    assert prefs.get_pref("shot_to_clipboard", True) is True
    with open(p, encoding="utf-8") as f:
        assert json.load(f)["shot_to_clipboard"] is True


def test_save_is_atomic_and_leaves_no_temp_file(monkeypatch, tmp_path):
    """写入必须是「临时文件 + 替换」，不能先截断原文件。

    回归：`open(path, "w")` 先把原文件截断为 0 字节，此间崩溃 / 断电 / 磁盘写满
    都会让 settings.json 变成空文件或半截 JSON —— 下次启动所有偏好悄悄回到默认值。
    """
    p = _patch_path(monkeypatch, tmp_path)
    prefs.save_prefs({"save_dir": r"D:\shots"})
    assert not os.path.exists(p + ".tmp"), "临时文件必须被 os.replace 消化掉"
    # 写失败时也要清掉临时文件，且原文件保持不变
    real_open = open

    def boom(path, *a, **kw):
        if str(path).endswith(".tmp"):
            raise OSError("磁盘写满")
        return real_open(path, *a, **kw)

    monkeypatch.setattr("builtins.open", boom)
    prefs.save_prefs({"save_dir": r"E:\other"})
    monkeypatch.undo()
    assert not os.path.exists(p + ".tmp")
    with open(p, encoding="utf-8") as f:
        assert json.load(f)["save_dir"] == r"D:\shots", "失败不得破坏原文件"


def test_load_tolerates_utf8_bom(monkeypatch, tmp_path):
    """记事本另存为 UTF-8 会写 BOM；带 BOM 的 settings.json 必须照常读出来。"""
    p = _patch_path(monkeypatch, tmp_path)
    with open(p, "w", encoding="utf-8-sig") as f:
        json.dump({"save_dir": r"D:\shots"}, f, ensure_ascii=False)
    assert open(p, "rb").read(3) == b"\xef\xbb\xbf"
    assert prefs.load_prefs()["save_dir"] == r"D:\shots"


# ---------------------------------------------------------------------------
# sanitize_prefs：安全防错（需求 1/3）
# ---------------------------------------------------------------------------

def test_sanitize_corrects_wrong_types():
    """手改 json 最常见的错：布尔写成字符串、路径写成数字、级别拼错。"""
    clean, warnings = prefs.sanitize_prefs({
        "keep_input": "yes",            # 字符串布尔 → 回退默认 True
        "save_dir": 123,                # 非字符串 → ""
        "lc_levels": ["I", "W", "Z"],   # 含非法级别 → 全选
        "rec_show_touches": "true",     # 字符串布尔 → 回退默认 True
        "my_custom_key": "keep-me",     # 未知键原样保留
    })
    assert clean["keep_input"] is True
    assert clean["save_dir"] == ""
    assert clean["lc_levels"] == ["V", "D", "I", "W", "E", "F"]
    assert clean["rec_show_touches"] is True
    assert clean["my_custom_key"] == "keep-me"
    assert len(warnings) == 4
    assert any("keep_input" in w for w in warnings)
    assert any("save_dir" in w for w in warnings)
    assert any("lc_levels" in w for w in warnings)
    assert any("rec_show_touches" in w for w in warnings)


def test_sanitize_string_false_is_not_true():
    """防错核心：手写 "false" 字符串在多数语言里是真值，必须按非法回退默认。"""
    clean, _ = prefs.sanitize_prefs({"rec_logcat": "false"})
    assert clean["rec_logcat"] is True      # 默认就是 True，绝不能被字符串蒙成关
    clean, _ = prefs.sanitize_prefs({"keep_input": "false"})
    assert clean["keep_input"] is True      # 默认 True —— 绝不能被 "false" 字符串蒙成关
    # 真正的 bool 与 0/1 照常生效
    clean, _ = prefs.sanitize_prefs({"keep_input": False})
    assert clean["keep_input"] is False
    clean, _ = prefs.sanitize_prefs({"keep_input": 0})
    assert clean["keep_input"] is False
    clean, _ = prefs.sanitize_prefs({"keep_input": 1})
    assert clean["keep_input"] is True


def test_sanitize_keeps_missing_keys_absent():
    """缺失键不回填（= 界面 HTML 默认勾选驱动），保持既有语义。"""
    clean, warnings = prefs.sanitize_prefs({})
    assert clean == {}
    assert warnings == []
    clean, warnings = prefs.sanitize_prefs({"save_dir": r"D:\x"})
    assert clean == {"save_dir": r"D:\x"}
    assert warnings == []


def test_sanitize_empty_level_list_is_valid():
    """空级别列表 = 「一个都不要」，是合法值，不能回退成全选。"""
    clean, warnings = prefs.sanitize_prefs({"lc_cap_levels": []})
    assert clean["lc_cap_levels"] == []
    assert warnings == []
    clean, _ = prefs.sanitize_prefs({"lc_levels": [], "lc_cap_levels": []})
    assert clean["lc_levels"] == [] and clean["lc_cap_levels"] == []


def test_sanitize_level_list_dedup_and_order():
    """重复项去重、按 V/D/I/W/E/F 固定序返回（落序稳定便于比对）。

    去重 / 重排也算一次「纠正」：写盘的值与用户写的字面不同，应有提示。
    """
    clean, warnings = prefs.sanitize_prefs({"lc_levels": ["E", "I", "E"]})
    assert clean["lc_levels"] == ["I", "E"]
    assert len(warnings) == 1 and "lc_levels" in warnings[0]


def test_sanitize_rejects_non_object():
    clean, warnings = prefs.sanitize_prefs(["not", "a", "dict"])
    assert clean == {}
    assert warnings and "不是对象" in warnings[0]


def test_sanitize_level_list_non_string_elements():
    """列表里混进非字符串（null / 数字）按整项回退，不静默吞掉。"""
    clean, warnings = prefs.sanitize_prefs({"lc_levels": ["I", None, 3]})
    assert clean["lc_levels"] == ["V", "D", "I", "W", "E", "F"]
    assert warnings


def test_save_prefs_sanitizes_patch_before_write(monkeypatch, tmp_path):
    """前端误传非法值也不能把文件写坏：save_prefs 先清洗再合并。"""
    p = _patch_path(monkeypatch, tmp_path)
    merged = prefs.save_prefs({"keep_input": "yes", "save_dir": 42})
    assert merged["keep_input"] is True
    assert merged["save_dir"] == ""
    with open(p, encoding="utf-8") as f:
        raw = json.load(f)
    assert raw["keep_input"] is True
    assert raw["save_dir"] == ""
    assert isinstance(raw["keep_input"], bool)


def test_load_prefs_checked_reports_corrections(monkeypatch, tmp_path):
    """启动时把「被纠正的配置」提示出来（需求 3：纠错要可见）。"""
    p = _patch_path(monkeypatch, tmp_path)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"keep_input": "yes", "lc_buffer": 5}, f)
    prefs_d, warnings = prefs.load_prefs_checked()
    assert prefs_d["keep_input"] is True
    assert prefs_d["lc_buffer"] == ""
    assert len(warnings) == 2


def test_load_prefs_checked_corrupt_has_no_warnings(monkeypatch, tmp_path):
    """文件损坏时无「可纠正内容」，warnings 为空（不是每项都报）。"""
    p = _patch_path(monkeypatch, tmp_path)
    with open(p, "w", encoding="utf-8") as f:
        f.write("{ broken")
    prefs_d, warnings = prefs.load_prefs_checked()
    assert prefs_d == {} and warnings == []


def test_load_prefs_checked_top_level_not_object(monkeypatch, tmp_path):
    p = _patch_path(monkeypatch, tmp_path)
    with open(p, "w", encoding="utf-8") as f:
        json.dump([1, 2, 3], f)
    prefs_d, warnings = prefs.load_prefs_checked()
    assert prefs_d == {}
    assert warnings and "不是对象" in warnings[0]


def test_roundtrip_all_defaults_survive(monkeypatch, tmp_path):
    """全量默认值写盘再读回应保持一致（持久化不漂移）。"""
    _patch_path(monkeypatch, tmp_path)
    prefs.save_prefs(dict(prefs.PREFS_DEFAULTS))
    loaded = prefs.load_prefs()
    for k, v in prefs.PREFS_DEFAULTS.items():
        assert loaded[k] == v, k


def test_rec_toggles_defaults_are_on():
    """需求 2：指针位置 / 触摸圆点默认开启（schema 单一默认值源）。"""
    assert prefs.PREFS_DEFAULTS["rec_pointer_location"] is True
    assert prefs.PREFS_DEFAULTS["rec_show_touches"] is True


def test_legacy_rec_show_pointer_key_migrates(monkeypatch, tmp_path):
    """旧键 rec_show_pointer 自动迁移为 rec_pointer_location。

    录屏「指针显示」从 screenrecord --show-pointer 参数改为系统设置
    pointer_location overlay 后键名变了；老用户显式关掉过指针显示的话，
    升级后不应发现设置悄悄复位。
    """
    p = _patch_path(monkeypatch, tmp_path)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"rec_show_pointer": False, "rec_show_touches": True}, f)
    loaded, warnings = prefs.load_prefs_checked()
    assert loaded["rec_pointer_location"] is False
    assert "rec_show_pointer" not in loaded
    assert warnings == []
    # 迁移后落盘，旧键不再复活
    prefs.save_prefs({"save_dir": "x"})
    with open(p, encoding="utf-8") as f:
        raw = json.load(f)
    assert "rec_show_pointer" not in raw
    assert raw["rec_pointer_location"] is False


def test_new_key_wins_over_legacy_on_migration(monkeypatch, tmp_path):
    """新键已存在（含新默认 true 的歧义）时不被旧键覆盖。"""
    p = _patch_path(monkeypatch, tmp_path)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"rec_show_pointer": False,
                   "rec_pointer_location": True}, f)
    loaded, _ = prefs.load_prefs_checked()
    assert loaded["rec_pointer_location"] is True


# ---------------------------------------------------------------------------
# 跨层一致性：PREFS_DEFAULTS 的布尔默认必须与 index.html 的默认勾选一一对齐
# ---------------------------------------------------------------------------

# schema 键 -> 前端复选框 id（新增开关时两边同步改，这张表就是同步点）
_BOOL_KEY_TO_HTML_ID = {
    "shot_to_clipboard": "shot-clipboard",
    "keep_input": "keep-input",
    "lc_only_exc": "lc-only-exc",
    "lc_autoscroll": "lc-autoscroll",
    "lc_cap_zipstop": "lc-cap-zipstop",
    "rec_logcat": "rec-logcat",
    "rec_zip": "rec-zip",
    "rec_pointer_location": "rec-pointer-location",
    "rec_show_touches": "rec-show-touches",
    "perf_pkg_all": "perf-pkg-all",
    # APK 安装选项（工具页「应用安装」卡的三个复选框）
    "apk_replace": "apk-replace",
    "apk_downgrade": "apk-downgrade",
    "apk_grant": "apk-grant",
    # 诊断包（工具页「诊断包」卡的复选框）
    "diag_with_logcat": "diag-logcat",
    # 版本更新（关于页「更新」行的自动检查复选框）
    "update_check": "about-update-auto",
}

# 没有对应 HTML 复选框的布尔键：设备栏收起是「标题前的 « / » 按钮切换」、
# 四张工具卡（截图 / 录屏 / 安装 / 诊断包 / 投屏）收起是「标题栏整条点击」切换，都不存在
# 「界面默认勾选」可对齐，故不参与下面的逐项比对。
# 显式列出（而非放宽断言）：将来真加了复选框的键必须登记进映射表，
# 不允许被顺手塞进这个豁免名单。
_NO_HTML_CHECKBOX_KEYS = {"sidebar_collapsed",
                          "shot_collapsed", "rec_collapsed", "scrcpy_collapsed",
                          "apk_collapsed", "diag_collapsed"}


def _html_checkbox_checked():
    """解析 frontend/index.html，返回 {复选框 id: 是否默认勾选}。"""
    import re
    p = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
    with open(p, encoding="utf-8") as f:
        html = f.read()
    out = {}
    for m in re.finditer(r'<input type="checkbox" id="([^"]+)"([^>]*)>', html):
        out[m.group(1)] = "checked" in m.group(2)
    return out


def test_bool_defaults_match_frontend_html_checked():
    """防「后端默认 False、界面默认勾选」漂移：新增开关只改一边时，
    用户没写过 settings.json 的行为就取决于哪边被读到，漂移即 bug。

    回归：第二阶段补 schema 时曾把 rec_zip 后端默认写成 True，而 HTML
    一直是未勾选——用户从没被 zip 过的录像会突然开始自动打包。
    """
    checked = _html_checkbox_checked()
    # 表必须覆盖 schema 的全部布尔键（新键忘了登记映射就会在这里失败；
    # 按钮切换类开关走 _NO_HTML_CHECKBOX_KEYS 显式豁免，见其注释）
    expected = set(_BOOL_KEY_TO_HTML_ID) | _NO_HTML_CHECKBOX_KEYS
    assert expected == set(prefs.BOOL_KEYS), \
        "布尔键映射表与 PREFS_DEFAULTS 不同步：%r" % (
            set(prefs.BOOL_KEYS) ^ expected)
    for key, html_id in _BOOL_KEY_TO_HTML_ID.items():
        assert html_id in checked, "index.html 里找不到复选框 %s" % html_id
        assert checked[html_id] is prefs.PREFS_DEFAULTS[key], \
            "默认值漂移：%s（schema=%s）与 #%s（html checked=%s）不一致" % (
                key, prefs.PREFS_DEFAULTS[key], html_id, checked[html_id])


def test_level_keys_have_html_level_rows():
    """级别过滤键在界面上都有对应的级别复选框行（防只加 schema 忘了做 UI）。"""
    import re
    p = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
    with open(p, encoding="utf-8") as f:
        html = f.read()
    # 录屏的级别行已撤掉：随录屏的 logcat 一律全量（见 test_backend_controller
    # 的 test_screen_record_logcat_is_always_full），界面上没有这一行也就没有
    # 「schema 有键、界面没行」的漂移风险。
    for container_id in ("lc-levels", "lc-cap-levels"):
        m = re.search(r'id="%s"[^>]*>(.*?)</span>' % container_id, html, re.S)
        assert m, "index.html 里找不到级别行 #%s" % container_id
        for lv in prefs.VALID_LEVELS:
            assert re.search(r'value="%s"' % lv, m.group(1)), \
                "#%s 缺少级别 %s 的复选框" % (container_id, lv)


# ---------------------------------------------------------------------------
# 第四轮：config.json 体系（改名 / 旧文件自动迁移 / 跨设备路径回退）
# ---------------------------------------------------------------------------

def test_prefs_file_is_config_json():
    """主配置文件名必须是 config.json（用户按此名在设备间拷贝同步）。"""
    assert prefs.PREFS_FILE == "config.json"
    assert prefs.LEGACY_PREFS_FILE == "settings.json"


def test_legacy_settings_json_migrates_to_config_json(monkeypatch, tmp_path):
    """旧版 settings.json 存在而 config.json 不存在时，自动迁移一份过来。

    升级路径：早期版本把配置写在 settings.json。用户升级后应无缝继续用
    原来的设置，而不是「一切归零」再手工重配一遍。
    """
    p_new = _patch_path(monkeypatch, tmp_path)
    p_old = _patch_legacy_path(monkeypatch, tmp_path)
    with open(p_old, "w", encoding="utf-8") as f:
        json.dump({"save_dir": r"D:\shots", "shot_to_clipboard": False}, f)

    loaded, warnings = prefs.load_prefs_checked()

    assert loaded["save_dir"] == r"D:\shots"
    assert loaded["shot_to_clipboard"] is False
    # 新文件已生成，且内容就是旧文件的
    assert os.path.exists(p_new)
    with open(p_new, encoding="utf-8") as f:
        raw = json.load(f)
    assert raw["save_dir"] == r"D:\shots"
    # 旧文件保留不删：它是用户升级前的配置备份，删了就再也回不去了
    assert os.path.exists(p_old)
    # 迁移必须给出提示（用户要知道配置换了个文件名）
    assert warnings and "settings.json" in warnings[0]


def test_migration_does_not_overwrite_existing_config_json(monkeypatch, tmp_path):
    """已有 config.json 时绝不拿旧文件覆盖它（用户的现配置优先）。"""
    p_new = _patch_path(monkeypatch, tmp_path)
    p_old = _patch_legacy_path(monkeypatch, tmp_path)
    with open(p_new, "w", encoding="utf-8") as f:
        json.dump({"save_dir": "NEW"}, f)
    with open(p_old, "w", encoding="utf-8") as f:
        json.dump({"save_dir": "OLD"}, f)

    loaded, _warnings = prefs.load_prefs_checked()

    assert loaded["save_dir"] == "NEW"


def test_migration_ignores_corrupt_legacy_file(monkeypatch, tmp_path):
    """旧文件损坏时不迁移、不报错（静默按无配置启动）。"""
    p_new = _patch_path(monkeypatch, tmp_path)
    p_old = _patch_legacy_path(monkeypatch, tmp_path)
    with open(p_old, "w", encoding="utf-8") as f:
        f.write("{ not json !!!")

    loaded, _warnings = prefs.load_prefs_checked()

    assert loaded == {}
    assert not os.path.exists(p_new)


def test_resolve_save_dir_uses_existing_dir(monkeypatch, tmp_path):
    """配置的目录在本机存在 → 直接采用，无提示。"""
    d = tmp_path / "shots"
    d.mkdir()
    eff, note = prefs.resolve_save_dir({"save_dir": str(d)})
    assert eff == str(d)
    assert note is None


def test_resolve_save_dir_falls_back_when_path_missing(monkeypatch, tmp_path):
    """跨设备同步的核心：配置里的绝对路径在本机不存在 → 改用默认目录。

    背景：用户把 config.json 拷到另一台电脑，源机上的 C:\\Users\\张三\\...
    在新机不存在。照原样用会让截图/录屏写进一个不存在的路径 —— 用户以为
    同步成功了，其实文件全丢。
    """
    missing = str(tmp_path / "not-exist")
    eff, note = prefs.resolve_save_dir({"save_dir": missing})
    assert eff == prefs.default_save_dir()
    assert note and "不存在" in note and "默认目录" in note


def test_resolve_save_dir_fallback_does_not_rewrite_config(monkeypatch, tmp_path):
    """回退只是「本机临时改用默认目录」，绝不能把回退结果写回配置文件。

    文件里的原值在源机器上仍然是正确路径；写回了就等于把用户的配置改坏，
    回拷回去也恢复不了。
    """
    p = _patch_path(monkeypatch, tmp_path)
    missing = str(tmp_path / "not-exist")
    prefs.save_prefs({"save_dir": missing})

    eff, note = prefs.resolve_save_dir(prefs.load_prefs())

    assert eff == prefs.default_save_dir()
    assert note
    with open(p, encoding="utf-8") as f:
        raw = json.load(f)
    assert raw["save_dir"] == missing, "回退结果不应写回配置文件"


def test_resolve_save_dir_empty_uses_default_without_note(monkeypatch, tmp_path):
    """未配置保存目录 → 用默认目录，且不打扰用户（无提示）。"""
    eff, note = prefs.resolve_save_dir({"save_dir": ""})
    assert eff == prefs.default_save_dir()
    assert note is None


def test_resolve_save_dir_falls_back_when_not_writable(monkeypatch, tmp_path):
    """目录存在但不可写 → 同样回退默认目录（否则截图会静默丢文件）。"""
    d = tmp_path / "ro"
    d.mkdir()
    os.chmod(str(d), 0o500)          # 只读：可进入不可写
    try:
        if os.access(str(d), os.W_OK):
            pytest.skip("当前用户可写只读目录（root 环境），跳过该断言")
        eff, note = prefs.resolve_save_dir({"save_dir": str(d)})
        assert eff == prefs.default_save_dir()
        assert note and "不可写" in note
    finally:
        os.chmod(str(d), 0o700)


def test_cmd_filter_persists_and_sanitizes(monkeypatch, tmp_path):
    """指令台搜索关键字：属于「过滤条件」，必须落盘并参与类型校验。"""
    p = _patch_path(monkeypatch, tmp_path)
    assert prefs.PREFS_DEFAULTS["cmd_filter"] == ""

    prefs.save_prefs({"cmd_filter": "install"})
    with open(p, encoding="utf-8") as f:
        raw = json.load(f)
    assert raw["cmd_filter"] == "install"
    assert prefs.load_prefs()["cmd_filter"] == "install"

    # 非法类型（数字）应回退默认空串，而不是被当成真值
    clean, warnings = prefs.sanitize_prefs({"cmd_filter": 123})
    assert clean["cmd_filter"] == ""
    assert warnings and "cmd_filter" in warnings[0]


def test_sidebar_collapsed_persists_and_sanitizes(monkeypatch, tmp_path):
    """设备栏收起状态：布局偏好，必须落盘并参与类型校验。"""
    p = _patch_path(monkeypatch, tmp_path)
    assert prefs.PREFS_DEFAULTS["sidebar_collapsed"] is False

    prefs.save_prefs({"sidebar_collapsed": True})
    assert prefs.load_prefs()["sidebar_collapsed"] is True
    with open(p, encoding="utf-8") as f:
        assert json.load(f)["sidebar_collapsed"] is True

    # 非法类型（字符串 "false"）按布尔键规则回退默认 False，不被当成真值
    clean, warnings = prefs.sanitize_prefs({"sidebar_collapsed": "false"})
    assert clean["sidebar_collapsed"] is False
    assert warnings and "sidebar_collapsed" in warnings[0]


def test_config_path_points_to_config_json(monkeypatch, tmp_path):
    """prefs_path 指向 config.json（运行目录 / exe 同目录）。"""
    p = _patch_path(monkeypatch, tmp_path)
    assert p.endswith("config.json")
    assert prefs.prefs_path() == p


def test_prefs_path_never_points_into_meipass(monkeypatch, tmp_path):
    """打包态下 config.json 必须落在 exe 同目录，而不是 _MEIPASS 临时目录。

    回归陷阱：若 config.json 被打进 exe 内部（BUNDLED_DATA），同目录那份缺失时
    resource_path() 会回退到 _MEIPASS 里的内置副本——save_prefs 写进去
    「重启即丢」：设置看起来保存成功、下次启动全部复位，且毫无报错。
    prefs_path 因此刻意不走 resource_path 的回退分支。
    """
    exe = tmp_path / "dist" / "ADB设备指令台.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "meipass"), raising=False)
    monkeypatch.setattr(sys, "executable", str(exe), raising=False)
    p = prefs.prefs_path()
    assert p == str(exe.parent / "config.json")
    assert "meipass" not in p.lower()


# ---------------------------------------------------------------------------
# 默认配置生成 + 启动补建（build.py 分发的模板与运行时补建共用同一来源）
# ---------------------------------------------------------------------------

def test_default_prefs_is_detached_copy_of_schema():
    """default_prefs 与 schema 等值但是独立副本（列表值必须深拷贝）。"""
    d = prefs.default_prefs()
    assert d == prefs.PREFS_DEFAULTS
    d["lc_levels"].append("X")
    d["save_dir"] = "mutated"
    assert prefs.PREFS_DEFAULTS["lc_levels"] == list(prefs.VALID_LEVELS)
    assert prefs.PREFS_DEFAULTS["save_dir"] == ""


def test_default_prefs_json_roundtrips_to_schema():
    """默认配置 JSON 读回来必须与 schema 完全一致（分发的模板不能缺项）。"""
    data = json.loads(prefs.default_prefs_json())
    assert data == prefs.PREFS_DEFAULTS


def test_ensure_prefs_file_creates_defaults_when_missing(monkeypatch, tmp_path):
    """文件缺失 → 按默认值补建（用户打开程序目录就能看到全部可配置项）。"""
    p = _patch_path(monkeypatch, tmp_path)
    assert prefs.ensure_prefs_file() == p
    with open(p, encoding="utf-8") as f:
        assert json.load(f) == prefs.PREFS_DEFAULTS


def test_ensure_prefs_file_keeps_existing_content(monkeypatch, tmp_path):
    """已有配置文件 → 原样不动（启动补建绝不能覆盖用户的设置）。"""
    p = _patch_path(monkeypatch, tmp_path)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"save_dir": r"D:\mine"}, f)
    prefs.ensure_prefs_file()
    with open(p, encoding="utf-8") as f:
        assert json.load(f) == {"save_dir": r"D:\mine"}


def test_ensure_prefs_file_leaves_no_temp_file(monkeypatch, tmp_path):
    """补建同样走「临时文件 + 原子替换」：不留下 .tmp 残骸。"""
    p = _patch_path(monkeypatch, tmp_path)
    prefs.ensure_prefs_file()
    assert os.path.exists(p)
    assert not os.path.exists(p + ".tmp")


def test_ensure_prefs_file_is_silent_when_dir_not_writable(monkeypatch, tmp_path):
    """exe 装在只读目录（Program Files 无权限）时不抛异常、不留临时文件。"""
    p = _patch_path(monkeypatch, tmp_path)
    real_open = open

    def boom(path, *a, **kw):
        if str(path).endswith(".tmp"):
            raise OSError("拒绝访问")
        return real_open(path, *a, **kw)

    monkeypatch.setattr("builtins.open", boom)
    assert prefs.ensure_prefs_file() == p      # 静默失败，不抛异常
    monkeypatch.undo()
    assert not os.path.exists(p)
    assert not os.path.exists(p + ".tmp")

def test_mirror_view_size_persists_and_clamps(monkeypatch, tmp_path):
    """备用投屏预览区大小：0 = 自适应，非 0 按像素记住，且夹在 0~2400。"""
    p = _patch_path(monkeypatch, tmp_path)
    assert prefs.PREFS_DEFAULTS["mirror_view_w"] == 0
    assert prefs.PREFS_DEFAULTS["mirror_view_h"] == 0

    prefs.save_prefs({"mirror_view_w": 520, "mirror_view_h": 640})
    assert prefs.load_prefs()["mirror_view_w"] == 520
    with open(p, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["mirror_view_h"] == 640

    # 拖成 0 是合法值（= 回到自适应），不能当成「非法」退回默认
    clean, warns = prefs.sanitize_prefs({"mirror_view_w": 0, "mirror_view_h": 0})
    assert clean["mirror_view_w"] == 0 and clean["mirror_view_h"] == 0
    assert warns == []

    # 手改成字符串 / 超出上限：回退默认 0（不让它写出一个比屏幕还大的窗口）
    clean, warns = prefs.sanitize_prefs({"mirror_view_w": "big", "mirror_view_h": 5000})
    assert clean["mirror_view_w"] == 0 and clean["mirror_view_h"] == 0
    assert len(warns) == 2


def test_cmd_timeout_defaults_and_clamps(monkeypatch, tmp_path):
    """命令兜底超时：默认 120 秒，0 = 不限制（合法值），越界/手写成字符串回退默认。

    这个键是「卡死」的唯一兜底：命令序列里任何一条读 stdin 的工具（裸
    powershell、`adb logcat` 之类）都会永久占住执行锁，后续命令全部排队。
    """
    p = _patch_path(monkeypatch, tmp_path)
    assert prefs.PREFS_DEFAULTS["cmd_timeout"] == 120

    prefs.save_prefs({"cmd_timeout": 45})
    assert prefs.load_prefs()["cmd_timeout"] == 45
    with open(p, encoding="utf-8") as f:
        assert json.load(f)["cmd_timeout"] == 45

    # 0 = 不限制：是用户显式选择，不能被当成「非法」退回 120
    clean, warns = prefs.sanitize_prefs({"cmd_timeout": 0})
    assert clean["cmd_timeout"] == 0
    assert warns == []

    # 负数 / 超过 1 小时 / 字符串：回退默认
    clean, warns = prefs.sanitize_prefs({"cmd_timeout": -5})
    assert clean["cmd_timeout"] == 120
    clean, warns = prefs.sanitize_prefs({"cmd_timeout": 99999})
    assert clean["cmd_timeout"] == 120
    clean, warns = prefs.sanitize_prefs({"cmd_timeout": "soon"})
    assert clean["cmd_timeout"] == 120


# ---------------------------------------------------------------------------
# 并发写入：读-改-写必须整体互斥
# ---------------------------------------------------------------------------
def _slow_atomic_write(monkeypatch, delay=0.05):
    """把落盘人为放慢，把「读-合并-写」之间的竞态窗口撑大到必现。"""
    import time as _t
    real = prefs._atomic_write

    def slow(p):
        _t.sleep(delay)
        return real(p)

    monkeypatch.setattr(prefs, "_atomic_write", slow)


def test_concurrent_saves_do_not_lose_updates(monkeypatch, tmp_path):
    """两个线程同时改不同键：谁都不能把对方的改动覆盖掉。

    没有 _SAVE_LOCK 时，两边各自读到同一份旧内容、各自合并、后写的整份盖掉
    先写的 —— 表现是「刚改的开关过一会儿自己弹回去了」，且极难复现。
    """
    import threading
    p = _patch_path(monkeypatch, tmp_path)
    _slow_atomic_write(monkeypatch)
    prefs.save_prefs({"save_dir": "seed"})

    def worker(key, val):
        prefs.save_prefs({key: val})

    t1 = threading.Thread(target=worker, args=("adb_dir", r"D:\pt"))
    t2 = threading.Thread(target=worker, args=("wifi_port", 6000))
    t1.start(); t2.start(); t1.join(); t2.join()

    with open(p, encoding="utf-8") as f:
        raw = json.load(f)
    assert raw.get("save_dir") == "seed"
    assert raw.get("adb_dir") == r"D:\pt"
    assert raw.get("wifi_port") == 6000


def test_atomic_write_uses_unique_temp_name(monkeypatch, tmp_path):
    """临时文件名必须唯一：固定名会让并发写入互相截断成半份 JSON。"""
    p = _patch_path(monkeypatch, tmp_path)
    seen = []
    real_open = open

    def spy(path, *a, **kw):
        if isinstance(path, str) and path != p:
            seen.append(path)
        return real_open(path, *a, **kw)

    monkeypatch.setattr("builtins.open", spy)
    prefs.save_prefs({"save_dir": "a"})
    prefs.save_prefs({"save_dir": "b"})
    # 至少两次写入（首次保存还会顺带触发一次「录屏默认值迁移」落盘），
    # 关键是每个临时文件名都不同且都紧跟配置路径
    assert len(seen) >= 2
    assert len(set(seen)) == len(seen)
    assert all(s.startswith(p) and s.endswith(".tmp") for s in seen)
