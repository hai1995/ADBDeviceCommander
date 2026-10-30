# -*- coding: utf-8 -*-
"""core.apk —— APK 安装参数拼装与输出解析。"""
from core import apk


def test_install_args_default_is_replace_only():
    assert apk.install_args() == ["install", "-r"]


def test_install_args_full_order_is_stable():
    """顺序固定，日志与断言才可读（参数本身与位置无关）。"""
    assert apk.install_args(replace=True, downgrade=True, grant=True) == \
        ["install", "-r", "-d", "-g"]
    assert apk.install_args(replace=False, downgrade=True, grant=True,
                            test_only=True) == ["install", "-d", "-g", "-t"]


def test_parse_success():
    assert apk.parse_install_output("Performing Streamed Install\nSuccess\n") == {
        "ok": True, "code": "", "message": "安装成功"}


def test_parse_success_without_streamed_line():
    """老 adb 只打一行 Success。"""
    assert apk.parse_install_output("Success")["ok"] is True


def test_parse_already_exists_maps_to_actionable_hint():
    res = apk.parse_install_output(
        "Failure [INSTALL_FAILED_ALREADY_EXISTS: Attempt to re-install "
        "com.x without first uninstalling.]")
    assert res["ok"] is False
    assert res["code"] == "INSTALL_FAILED_ALREADY_EXISTS"
    assert "覆盖安装" in res["message"]


def test_parse_version_downgrade():
    res = apk.parse_install_output("Failure [INSTALL_FAILED_VERSION_DOWNGRADE]")
    assert res["code"] == "INSTALL_FAILED_VERSION_DOWNGRADE"
    assert "允许降级" in res["message"]


def test_parse_signature_mismatch():
    res = apk.parse_install_output(
        "adb: failed to install app.apk: Failure "
        "[INSTALL_FAILED_UPDATE_INCOMPATIBLE: Package com.x signatures do not "
        "match previously installed version; ignoring!]")
    assert res["ok"] is False
    assert "签名" in res["message"]


def test_parse_test_only_keeps_code_for_auto_retry():
    """controller 要凭这个 code 自动加 -t 重试一次。"""
    res = apk.parse_install_output("Failure [INSTALL_FAILED_TEST_ONLY]")
    assert res["code"] == "INSTALL_FAILED_TEST_ONLY"
    assert "-t" in res["message"]


def test_parse_unknown_code_falls_back_to_detail():
    res = apk.parse_install_output(
        "Failure [INSTALL_FAILED_SOMETHING_NEW: device said no]")
    assert res["ok"] is False
    assert res["code"] == "INSTALL_FAILED_SOMETHING_NEW"
    assert "device said no" in res["message"]


def test_parse_parse_failed_family():
    res = apk.parse_install_output(
        "Failure [INSTALL_PARSE_FAILED_UNEXPECTED_EXCEPTION]")
    assert res["ok"] is False
    assert "解析失败" in res["message"]


def test_parse_device_offline():
    res = apk.parse_install_output("adb: device offline")
    assert res["ok"] is False
    assert "离线" in res["message"]


def test_parse_no_devices():
    res = apk.parse_install_output("error: no devices/emulators found")
    assert res["ok"] is False
    assert "勾选" in res["message"]


def test_parse_truncated_streamed_install_is_failure():
    """只有 `Performing Streamed Install` 没有 Success：输出被截断，不能当成功。"""
    res = apk.parse_install_output("Performing Streamed Install\n")
    assert res["ok"] is False
    assert "重试" in res["message"]


def test_parse_empty_output_is_failure():
    res = apk.parse_install_output("")
    assert res["ok"] is False
    assert res["message"].startswith("安装失败")


def test_parse_keeps_tail_detail():
    res = apk.parse_install_output("some noise\nreal reason here\n")
    assert "real reason here" in res["message"]


def test_format_size():
    assert apk.format_size(0) == "0 B"
    assert apk.format_size(900) == "900 B"
    assert apk.format_size(1024) == "1.0 KB"
    assert apk.format_size(3 * 1024 * 1024) == "3.0 MB"
    assert apk.format_size(2.5 * 1024 ** 3) == "2.5 GB"
    assert apk.format_size(None) == ""
    assert apk.format_size(-1) == ""
