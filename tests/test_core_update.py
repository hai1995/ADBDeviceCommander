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


def test_next_wait_s_agrees_with_due():
    """next_wait_s 与 due() 必须永远同向（后台循环靠它决定睡多久）。

    这条守住的是一个真实回归：循环曾固定睡 CHECK_INTERVAL_S，「查失败后 1 小时
    重试」的时间戳回拨因此完全失效——断网一次就静默半天。
    """
    now = 1_000_000.0
    iv = update.CHECK_INTERVAL_S
    # 从未查过 / 时间戳在未来：现在就该查
    assert update.next_wait_s(0, now=now) == 0.0
    assert update.next_wait_s(None, now=now) == 0.0
    assert update.next_wait_s(now + 4321, now=now) == 0.0
    # 刚查完：整整一个间隔
    assert update.next_wait_s(now, now=now) == float(iv)
    # 查失败后时间戳被回拨到「1 小时后到点」：返回 3600，而不是 12 小时
    assert update.next_wait_s(now - iv + 3600, now=now) == 3600.0
    # 已到点：0（due() 此时必为 True）
    assert update.next_wait_s(now - iv, now=now) == 0.0
    assert update.due(now - iv, now=now) is True
    # 坏值按「从未查过」处理，与 due() 一致
    assert update.next_wait_s("bad", now=now) == 0.0


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


def test_pick_asset_rejects_non_string_url():
    """browser_download_url 为非字符串（dict/list）时不能入选。

    自建 feed 手写 json 可能把 url 写成对象；旧逻辑只判真值就让它入选并把
    url 赋成 dict，最终 update_open 的 (url).strip() 抛 AttributeError。
    """
    got = update.pick_asset([
        {"name": "a_win64.zip", "browser_download_url": {"href": "https://x/a.zip"}},
        {"name": "b.zip", "browser_download_url": ["https://x/b.zip"]},
    ])
    assert got == {}, "非字符串 url 必须整条跳过"
    # 正常的字符串 url 仍要能选中（确认不是把类型判断写反）
    got = update.pick_asset([
        {"name": "a_win64.zip", "browser_download_url": "https://x/a.zip"},
    ])
    assert got["url"] == "https://x/a.zip"


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


def test_default_feed_prefers_static_latest_json():
    """首选必须是静态 latest.json：REST 接口匿名限流 60 次/小时/IP，
    同事多人共用一个公司出口 IP 时会集体查到「限流」（实测踩过）。"""
    assert update.FEED_URL.endswith("/releases/latest/download/latest.json")
    assert update.FEEDS[0] == update.FEED_URL
    assert update.FEED_API in update.FEEDS


def test_check_falls_back_to_next_feed_on_404():
    calls = []

    def opener(url, timeout):
        calls.append(url)
        return (404, "") if "latest/download" in url else (200, _gh())

    res = update.check("2026.1029.1931", opener=opener)
    assert res["status"] == "update"
    assert len(calls) == 2, calls
    assert res["feed"].startswith("https://api.github.com")


def test_check_stops_at_first_working_feed():
    calls = []

    def opener(url, timeout):
        calls.append(url)
        return 200, _gh()

    res = update.check("2026.1029.1931", opener=opener)
    assert len(calls) == 1, "静态源成功就不该再打 API（省额度）"
    assert res["feed"] == update.FEED_URL


def test_check_reports_attempt_count_when_all_feeds_fail():
    res = update.check("2026.1029.1931", opener=lambda u, t: (403, ""))
    assert res["status"] == "error"
    assert "2 个更新源" in res["error"]


def test_explicit_feed_does_not_fall_back():
    """用户配了内网源就只查它 —— 悄悄又去连 GitHub，用户会以为配置没生效。"""
    calls = []

    def opener(url, timeout):
        calls.append(url)
        return 404, ""

    res = update.check("2026.1029.1931", feed="https://intra.example.com/v.json",
                       opener=opener)
    assert calls == ["https://intra.example.com/v.json"]
    assert "个更新源" not in res["error"]


def test_check_passes_timeout_through():
    seen = {}

    def opener(url, timeout):
        seen["url"], seen["timeout"] = url, timeout
        return 200, _gh()
    update.check("2026.1029.1931", FEED, opener, timeout=3)
    assert seen == {"url": FEED, "timeout": 3}


# --------------------------------------------------------------------------- #
# 更新源 URL 安全（SSRF / 本地文件探测）
# --------------------------------------------------------------------------- #
def test_feed_url_allowed_rules():
    """危险源拒绝、合法源放行；内网自建更新源是明确功能，不能一刀切。"""
    for url in (
        "file:///C:/Users/v/secrets.txt", "ftp://host/x", "gopher://host/x",
        "http://127.0.0.1:8080/admin", "http://127.1.2.3/",
        "http://169.254.169.254/latest/meta-data/", "http://[::1]:80/",
        "http://localhost:8080/", "http://a.localhost/", "http://0.0.0.0/",
        "http://224.0.0.1/", "not a url", "",
        # 回环 / 元数据的 IP 别名：ipaddress.ip_address 不认，但操作系统会
        # 解析成 127.0.0.1 / 169.254.169.254，必须同样拒绝（SSRF 绕过）。
        "http://2130706433/",          # 127.0.0.1 十进制整数
        "http://0x7f000001/",          # 127.0.0.1 十六进制
        "http://0177.0.0.1/",          # 127.0.0.1 八进制段
        "http://127.1/",               # 127.0.0.1 简写（inet_aton）
        "http://2852039166/",          # 169.254.169.254 十进制整数（云元数据）
        "http://[::ffff:127.0.0.1]/",  # IPv4-mapped 回环
    ):
        assert not update.feed_url_allowed(url), url
    for url in (
        "https://github.com/x/y/releases/latest/download/latest.json",
        "https://api.github.com/repos/x/y/releases/latest",
        "http://192.168.1.10/version.json", "http://10.0.0.5/v.json",
        "http://172.16.0.1/v.json", "https://intra.example.com/v.json",
    ):
        assert update.feed_url_allowed(url), url


def test_check_rejects_ssrf_feed_without_request():
    """恶意 feed 绝不发出请求，响应也不回显（带回显 SSRF）。"""
    calls = []

    def opener(url, timeout):
        calls.append(url)
        return 200, '{"version":"2099.0101.0000","notes":"PWNED"}'

    for evil in ("file:///C:/secrets.txt", "http://127.0.0.1:8080/admin",
                 "http://169.254.169.254/latest/meta-data/",
                 # IP 别名形式的回环 / 元数据：必须在 check 层就被拦下，绝不发请求
                 "http://2130706433:8080/admin",
                 "http://0x7f000001:8080/admin",
                 "http://2852039166/latest/meta-data/"):
        calls.clear()
        res = update.check("2026.0101.0000", evil, opener)
        assert calls == [], f"不应请求 {evil}"
        assert res["status"] == "error"
        assert res["notes"] == "" and res["version"] == ""


def test_check_still_allows_intranet_feed():
    """内网私网更新源仍可正常检查（保住自建源功能）。"""
    calls = []

    def opener(url, timeout):
        calls.append(url)
        return 200, _gh()

    res = update.check("2026.0101.0000", "http://192.168.1.10/v.json", opener)
    assert calls == ["http://192.168.1.10/v.json"]
    assert res["status"] == "update"


def test_check_rejects_unsafe_when_mixed_with_safe_feeds():
    """feed 列表里只要混入不安全源就整体拒绝，不偷偷只查安全的那个。"""
    calls = []
    res = update.check("2026.0101.0000",
                       ["https://github.com/x/y", "http://127.0.0.1/x"],
                       lambda u, t: calls.append(u) or (200, _gh()))
    assert calls == []
    assert res["status"] == "error"


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


def test_pick_asset_handles_non_finite_size():
    """更新源 size 是 1e999（json.loads 得 inf）时不能抛 OverflowError。

    自建内网更新源是可配置项；损坏/恶意的 size 不该让「检查更新」整体崩成
    英文内部错误。这类值一律按 0 处理（不影响资产 URL 的选择）。
    """
    payload = json.loads(
        '{"tag_name":"v2026.1120.0912","assets":['
        '{"name":"app_win64.zip","browser_download_url":"http://x/a.zip","size":1e999}]}')
    got = update.normalize(payload)
    assert got is not None
    assert got["asset"]["size"] == 0
    assert got["asset"]["url"] == "http://x/a.zip"
    # nan 同样不能崩
    payload2 = json.loads(
        '{"tag_name":"v2026.1120.0912","assets":['
        '{"name":"app_win64.zip","browser_download_url":"http://x/a.zip","size":NaN}]}')
    assert update.normalize(payload2)["asset"]["size"] == 0
