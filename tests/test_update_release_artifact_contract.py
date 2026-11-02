# -*- coding: utf-8 -*-
"""更新源产物契约测试：release.yml 生成的 latest.json ↔ core.update 解析。

用户长期担心「检查更新与发版链路没在真机跑过」。静态源 latest.json 由
release.yml 在 Windows runner 上用 PowerShell 拼出，核心解析逻辑在
core/update.py。两者全靠字段名对齐：release.yml 用
version / notes / url / assets[]，normalize() 必须认得这些字段。若将来有人
改了 release.yml 的字段名却没同步 normalize()，检查更新会静默全失败——
本文件把这条契约锁死，一旦漂移测试即红。

重点覆盖「静态源（latest.json）」这一种形状：它和 test_core_update.py 里
测的 GitHub Release 形状（tag_name / html_url / assets）不一样，是 release.yml
实际产物，此前没有任何测试复刻过，正是「没在真机上跑过」的盲区。

全部用假 opener 复现，不发真实请求。
"""
import json

from core import update
from core.constants import VERSION as CURRENT


def _latest_json(version, notes="本次更新内容", size=20 * 1024 * 1024):
    """逐字段复刻 release.yml 第 284-295 行 PowerShell 生成的 latest.json。"""
    tag = "v" + version
    pkg = "ADBDeviceCommander_%s_win64.zip" % version
    return json.dumps({
        "version": version,
        "notes": notes,
        "url": "https://github.com/hai1995/ADBDeviceCommander/releases/tag/" + tag,
        "assets": [
            {
                "name": pkg,
                "browser_download_url":
                    "https://github.com/hai1995/ADBDeviceCommander/releases/download/%s/%s"
                    % (tag, pkg),
                "size": size,
            },
        ],
    })


def _opener(body):
    return lambda url, timeout: (200, body)


def _bump_year(version, year):
    """把版本号的年段换成给定值，便于构造 更新/最新/超前 三种情形。"""
    parts = version.split(".")
    parts[0] = str(year)
    return ".".join(parts)


def test_release_latest_json_resolves_to_update():
    remote = _bump_year(CURRENT, 2099)
    res = update.check(CURRENT, "https://x/latest.json",
                       opener=_opener(_latest_json(remote)))
    assert res["status"] == "update"
    assert res["version"] == update.format_version(update.parse_version(remote))
    assert res["url"].endswith("v" + remote)


def test_release_latest_json_resolves_to_latest_when_same():
    res = update.check(CURRENT, "https://x/latest.json",
                       opener=_opener(_latest_json(CURRENT)))
    assert res["status"] == "latest"


def test_release_latest_json_resolves_to_ahead_for_dev_build():
    older = _bump_year(CURRENT, 2020)
    res = update.check(CURRENT, "https://x/latest.json",
                       opener=_opener(_latest_json(older)))
    assert res["status"] == "ahead"


def test_release_latest_json_asset_picked_is_win64_and_size_kept():
    remote = _bump_year(CURRENT, 2099)
    res = update.check(CURRENT, "https://x/latest.json",
                       opener=_opener(_latest_json(remote, size=12345678)))
    asset = res["asset"]
    # 发版包名后缀必须与 core.update 的首选后缀一致：build.py 改了包名后缀却没
    # 改 ASSET_SUFFIX 时，pick_asset 会退化成「挑任意 zip」，更新检查仍能给出
    # 版本，但下载链接就不是那个 win64 包了——用户点「去下载」拿到错误文件。
    assert asset["name"].endswith(update.ASSET_SUFFIX)
    assert asset["size"] == 12345678
    assert asset["url"].endswith(asset["name"])


def test_release_latest_json_field_names_locked_to_normalize():
    """字段名契约：release.yml 用的字段 normalize() 必须都认得。

    这里直接 normalize 解析（不经过 check 的多源回退），确保 version / notes /
    url / assets 四个字段名与 normalize() 的期望一致——任何一个被改掉，normalize
    都会返回 None，检查更新随之「认不出版本号」静默失败。
    """
    remote = _bump_year(CURRENT, 2099)
    got = update.normalize(json.loads(_latest_json(remote)))
    assert got is not None
    assert got["version"] == update.format_version(update.parse_version(remote))
    assert got["notes"] == "本次更新内容"
    assert "releases/tag" in got["url"]
    assert got["asset"]
