# -*- coding: utf-8 -*-
"""core.update 的单测：版本比较 + 更新源解析 + 各种失败路径。

重点是「线上会变的东西」：
  * tag 可能写成 v2026.1029.1931 / release-2026.1029.1931 / 纯数字；
  * Release 正文可能几千字（要截断），也可能一个字都没有；
  * 接口可能 404（还没发过版）/ 403（限流）/ 返回一页 HTML（被网络中间层拦）；
  * 用户机器在内网，连不上 github.com —— 必须给中文原因，而不是抛异常。
全部用假 opener 复现，不发真实请求。
"""
import json

from core import update

FEED = "https://api.github.com/repos/x/y/releases/latest"


def _gh(tag="v2026.1030.0900", body="修复若干问题", assets=None):
    return json.dumps({
        "tag_name": tag,
        "body": body,
        "html_url": "https://github.com/x/y/releases/tag/" + tag,
        "assets": assets if assets is not None else [
            {"name": "source-v2026.1030.0900.zip",
             "browser_download_url": "https://e/1.zip", "size": 100},
            {"name": "ADBDeviceCommander_v2026.1030.0900_win64.zip",
             "browser_download_url": "https://e/2.zip", "size": 20 * 1024 * 1024},
        ],
    })


def _opener(code, body):
    return lambda url, timeout: (code, body)


# --------------------------------------------------------------------------- #
# 版本号
# --------------------------------------------------------------------------- #
def test_parse_version_accepts_common_tag_forms():
    want = (2026, 1029, 1931)
    for text in ("2026.1029.1931", "v2026.1029.1931", "V2026.1029.1931",
                 "release-2026.1029.1931", " 2026.1029.1931 "):
        assert update.parse_version(text) == want, text


def test_parse_version_missing_part_pads_zero():
    assert update.parse_version("2026.1029") == (2026, 1029, 0)
    assert update.parse_version("2026.1029.0") == (2026, 1029, 0)


def test_parse_version_rejects_unparsable():
    for text in ("", None, "dev", "latest", "v", "abc.def"):
        assert update.parse_version(text) is None, text


def test_parse_version_tolerates_non_string():
    """手改 config.json / 更新源把版本号写成数字时不该抛异常，且必须判为「认不出」。

    断言的是 None 而不是 (2026, 0, 0)：裸数字 / 浮点都不构成版本号。
    放行的后果是「写错类型的版本字段」会变成 (2026,0,0)，任何真版本都比它大，
    于是天天弹「有新版本」且查不出原因 —— 宁可判为无效。
    """
    for value in (2026, 3.14, [], {}, True, False, 0):
        assert update.parse_version(value) is None, value


def test_format_version_pads_month_day():
    assert update.format_version((2026, 1029, 1931)) == "2026.1029.1931"
    assert update.format_version((2026, 12, 5)) == "2026.0012.0005"
    assert update.format_version(None) == ""


def test_is_newer_basic_ordering():
    assert update.is_newer("2026.1030.0900", "2026.1029.1931") is True
    assert update.is_newer("2026.1029.1931", "2026.1030.0900") is False
    assert update.is_newer("2026.1029.1931", "2026.1029.1931") is False


def test_is_newer_false_when_either_side_unparsable():
    """开发态版本号（dev）不能触发「有新版本」——宁可漏报也不误报。"""
    assert update.is_newer("2026.1030.0900", "dev") is False
    assert update.is_newer("dev", "2026.1029.1931") is False
    assert update.is_newer(None, "2026.1029.1931") is False


def test_due_handles_never_checked_and_interval():
    now = 1_000_000.0
    assert update.due(0, now=now) is True
    assert update.due(None, now=now) is True
    assert update.due(now - 10, now=now) is False
    assert update.due(now - update.CHECK_INTERVAL_S - 1, now=now) is True


def test_due_treats_future_timestamp_as_due():
    """系统时间被调回过去时，不能因为 last 在未来就永久不再检查。"""
    now = 1_000_000.0
    assert update.due(now + 99999, now=now) is True


def test_due_survives_garbage_last_value():
    assert update.due("not-a-number", now=1_000_000.0) is True
    assert update.due([], now=1_000_000.0) is True


# --------------------------------------------------------------------------- #
# 资产挑选
# --------------------------------------------------------------------------- #
def test_pick_asset_prefers_win64_package():
    got = update.pick_asset([
        {"name": "ADBDeviceCommander_v1_source.zip", "browser_download_url": "u1"},
        {"name": "ADBDeviceCommander_v1_win64.zip", "browser_download_url": "u2", "size": 5},
    ])
    assert got["url"] == "u2"
    assert got["size"] == 5


def test_pick_asset_falls_back_to_any_zip_then_exe():
    zip_only = update.pick_asset([{"name": "a.zip", "browser_download_url": "u"}])
    assert zip_only["url"] == "u"
    exe_only = update.pick_asset([{"name": "a.exe", "browser_download_url": "u"}])
    assert exe_only["url"] == "u"


def test_pick_asset_ignores_broken_entries():
    assert update.pick_asset([{"name": "a.zip"}, "x", None, 3]) == {}
    assert update.pick_asset(None) == {}
    assert update.pick_asset([]) == {}


# --------------------------------------------------------------------------- #
# 归一化
# --------------------------------------------------------------------------- #
def test_normalize_github_release_shape():
    got = update.normalize(json.loads(_gh()))
    assert got["version"] == "2026.1030.0900"
    assert got["notes"] == "修复若干问题"
    assert got["url"].endswith("v2026.1030.0900")
    assert got["asset"]["name"].endswith("_win64.zip")


def test_normalize_self_hosted_version_json():
    """自建 version.json（只有 version / notes / url）也要认——换内网托管不用改代码。"""
    got = update.normalize({"version": "2026.1101.1000", "notes": "内网版",
                            "url": "https://intra/download"})
    assert got["version"] == "2026.1101.1000"
    assert got["notes"] == "内网版"
    assert got["url"] == "https://intra/download"
    assert got["asset"] == {}


def test_normalize_truncates_long_notes():
    got = update.normalize({"tag_name": "v2026.1030.0900",
                            "body": "x" * (update.NOTES_MAX + 500)})
    assert len(got["notes"]) <= update.NOTES_MAX + 40
    assert "已截断" in got["notes"]


def test_normalize_rejects_payload_without_version():
    assert update.normalize({"tag_name": "nightly", "body": "x"}) is None
    assert update.normalize({}) is None
    assert update.normalize("not a dict") is None
    assert update.normalize(None) is None


def test_normalize_falls_back_to_asset_url_when_no_page_url():
    got = update.normalize({"tag_name": "v2026.1030.0900", "assets": [
        {"name": "x_win64.zip", "browser_download_url": "https://e/f.zip"}]})
    assert got["url"] == "https://e/f.zip"


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def test_check_reports_update_with_notes_and_url():
    res = update.check("2026.1029.1931", FEED, _opener(200, _gh()))
    assert res["status"] == "update"
    assert res["version"] == "2026.1030.0900"
    assert res["notes"] == "修复若干问题"
    assert res["url"].startswith("https://github.com/")
    assert res["checked_at"] > 0


def test_check_reports_latest_when_same_version():
    res = update.check("2026.1030.0900", FEED, _opener(200, _gh()))
    assert res["status"] == "latest"


def test_check_reports_ahead_for_dev_build():
    res = update.check("2026.1105.1200", FEED, _opener(200, _gh()))
    assert res["status"] == "ahead"


def test_check_404_means_no_release_yet():
    res = update.check("2026.1029.1931", FEED, _opener(404, ""))
    assert res["status"] == "error"
    assert "还没有发布过版本" in res["error"]


def test_check_403_mentions_rate_limit():
    res = update.check("2026.1029.1931", FEED, _opener(403, ""))
    assert res["status"] == "error"
    assert "次数用尽" in res["error"]


def test_check_500_and_429_are_translated():
    assert "HTTP 500" in update.check("1.0", FEED, _opener(500, ""))["error"]
    assert "429" in update.check("1.0", FEED, _opener(429, ""))["error"]


def test_check_bad_json_is_translated():
    res = update.check("2026.1029.1931", FEED, _opener(200, "<html>NTLM 认证</html>"))
    assert res["status"] == "error"
    assert "JSON" in res["error"]


def test_check_network_failure_is_translated_not_raised():
    def boom(url, timeout):
        raise TimeoutError("timed out")
    res = update.check("2026.1029.1931", FEED, boom)
    assert res["status"] == "error"
    assert "连不上" in res["error"]
    assert "Timed out" in res["error"] or "timed out" in res["error"]


def test_check_unknown_payload_is_translated():
    res = update.check("2026.1029.1931", FEED, _opener(200, '{"tag_name": "nightly"}'))
    assert res["status"] == "error"
    assert "版本号" in res["error"]


def test_check_passes_timeout_through():
    seen = {}

    def opener(url, timeout):
        seen["url"], seen["timeout"] = url, timeout
        return 200, _gh()
    update.check("2026.1029.1931", FEED, opener, timeout=3)
    assert seen == {"url": FEED, "timeout": 3}


# --------------------------------------------------------------------------- #
# 展示串
# --------------------------------------------------------------------------- #
def test_summary_covers_every_status():
    base = {"current": "2026.1029.1931", "version": "2026.1030.0900"}
    assert "发现新版本" in update.summary(dict(base, status="update"))
    assert "已是最新" in update.summary(dict(base, status="latest"))
    assert "开发版" in update.summary(dict(base, status="ahead"))
    assert "boom" in update.summary({"status": "error", "error": "boom"})
    assert update.summary(None) == ""


def test_download_size_formats_mb():
    assert update.download_size({"asset": {"size": 20 * 1024 * 1024}}) == "20.0 MB"
    assert update.download_size({"asset": {}}) == ""
    assert update.download_size({}) == ""
    assert update.download_size(None) == ""
