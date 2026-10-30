# -*- coding: utf-8 -*-
"""core.update —— 版本检查（发现新版本 → 提示用户去下载）。

为什么是「检查 + 提示」，而不是「自动替换」
------------------------------------------
程序目录里的 exe 正在运行时，Windows 不允许覆盖自身。要自动替换只有两条路：
写一个 .bat 等进程退出后再拷（杀毒软件对「脚本延迟改可执行文件」高度敏感，
十有八九被拦）、或要求管理员权限（同事机器上等于让程序弹 UAC）。两条都不划算，
所以这里只负责「判断有没有新版 + 把差异说清楚」，下载与覆盖交给浏览器和用户。

设计边界
--------
* **纯逻辑**：不发真实网络请求（`opener` 注入）、不碰 UI、不读配置文件，
  可以在 headless 下完整单测；网络、配置、事件广播都留给 backend 层。
* **更新源可换**：默认读 GitHub Releases（仓库已 public，匿名可访问）。
  同一个地址若返回的是自建 version.json（只含 version / notes / url），
  也照样认——换内网托管时不用改代码，只改 `config.json` 里的 `update_feed`。
* **失败不打扰**：网络不通、限流、返回格式变了，都只返回一句中文原因，
  由调用方决定「自动检查时静默、手动检查时才显示」。
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

# 默认更新源：GitHub Releases 的「最新正式版」接口。
# 用 latest 而不是列表接口：列表接口要把全部 release 拉下来再自己挑，随版本
# 累积会越来越慢，且分页容易漏掉最新那条。
FEED_URL = "https://api.github.com/repos/hai1995/ADBDeviceCommander/releases/latest"

# 单次检查超时（秒）。这个值同时是「自动检查」的最坏阻塞时长——检查在后台线程里
# 跑，用户不会看到转圈，但线程池名额有限，不宜等到 30s 让后续任务排队。
TIMEOUT = 10

# 自动检查间隔（秒）：12 小时。程序是常驻工具（开着就是半天），
# 比「每次启动检查」更贴合实际使用，又不会频繁打接口（匿名限流 60 次/小时）。
CHECK_INTERVAL_S = 12 * 3600

# 更新说明在弹窗里的最大长度。Release 正文可以很长（一整轮改动清单），
# 弹窗里只需要让人判断「值不值得现在更新」，完整说明在下载页看。
NOTES_MAX = 3000

# 首选资产名后缀：CI 打出来的 Windows 分发包（ADBDeviceCommander_v<版本>_win64.zip）。
# 与 build.py --package 产出的名字必须一致，否则会退化成「挑任意 zip」。
ASSET_SUFFIX = "_win64.zip"

# GitHub 接口强制要求带 User-Agent（缺了直接 403），并且明确拒绝空 UA。
UA = "ADBDeviceCommander-Updater/1.0"

# 版本号形如 2026.1029.1931（年.月日.时分）。取「数字.数字[.数字]」的前缀，
# 这样 tag 写成 v2026.1029.1931 / release-2026.1029.1931 都能认出来。
_VER_RE = re.compile(r"(\d{1,4})\.(\d{1,4})(?:\.(\d{1,4}))?")


# --------------------------------------------------------------------------- #
# 版本号
# --------------------------------------------------------------------------- #
def parse_version(text):
    """把版本字符串解析成可比较的元组；认不出返回 None。

    返回 3 元组（缺的段补 0），因此 "2026.1029" 与 "2026.1029.0" 等价。
    刻意不用 `packaging.version`：本项目版本号不是 PEP 440 语义（"2026.1029.1931"
    在 PEP 440 眼里是非法或怪异的），而且那是第三方依赖，为比较三个整数不值当。

    只接受**字符串**：数字 / 浮点 / 布尔一律认不出。理由是不能让「写错类型的
    版本字段」蒙混过关 —— 若把 2026 当成版本号，它会变成 (2026, 0, 0)，
    任何真版本都比它大，于是天天弹「有新版本」，而且找不到原因。
    """
    if not isinstance(text, str):
        return None
    m = _VER_RE.search(text)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def format_version(v) -> str:
    """把 parse_version 的元组还原成 YYYY.MMDD.HHMM 展示串。"""
    if not v:
        return ""
    return "%d.%04d.%04d" % tuple(v)


def is_newer(remote, local) -> bool:
    """remote 是否比 local 新。任一方认不出（如开发态的 "dev"）一律不算新——
    宁可漏报一次更新，也不能因为解析失败就天天弹「有新版本」。
    """
    a, b = parse_version(remote), parse_version(local)
    if a is None or b is None:
        return False
    return a > b


def due(last_ts, now=None, interval=CHECK_INTERVAL_S) -> bool:
    """是否已到下一次自动检查的时间。last_ts 为 0 / None 视为「从未检查」。"""
    import time
    now = time.time() if now is None else now
    try:
        last = float(last_ts or 0)
    except (TypeError, ValueError):
        last = 0.0
    if last <= 0:
        return True
    # last 在未来（改过系统时间 / 手改了 config.json）：当作「刚到点」，
    # 否则要把系统时间调回来才会再检查，等于永久不再提示更新。
    if last > now:
        return True
    return (now - last) >= max(0, int(interval))


# --------------------------------------------------------------------------- #
# 解析更新源返回的内容
# --------------------------------------------------------------------------- #
def pick_asset(assets, prefer: str = ASSET_SUFFIX) -> dict:
    """从 Release 资产列表里挑出要下载的那个。

    优先级：`_win64.zip` > 任意 .zip > 任意 .exe。返回
    {"name", "url", "size"}；挑不出返回 {}（此时只用 release 页面地址）。
    """
    if not isinstance(assets, list):
        return {}
    cands = [a for a in assets
             if isinstance(a, dict) and a.get("browser_download_url")]
    picks = (
        lambda n: n.endswith(prefer.lower()),
        lambda n: n.endswith(".zip"),
        lambda n: n.endswith(".exe"),
    )
    for hit in picks:
        for a in cands:
            if hit(str(a.get("name") or "").lower()):
                try:
                    size = int(a.get("size") or 0)
                except (TypeError, ValueError):
                    size = 0
                return {"name": a.get("name") or "",
                        "url": a.get("browser_download_url"),
                        "size": size}
    return {}


def normalize(payload) -> dict:
    """把更新源返回的 JSON 归一化成统一结构；认不出返回 None。

    同时兼容两种格式：
      * GitHub `releases/latest`：tag_name / body / html_url / assets[]
      * 自建 version.json：       version  / notes / url
    两条路径都归到 {version, notes, url, asset}，后面的判断逻辑不必分叉。
    """
    if not isinstance(payload, dict):
        return None
    ver = (payload.get("tag_name") or payload.get("version")
           or payload.get("latest") or payload.get("name"))
    parsed = parse_version(ver)
    if parsed is None:
        return None
    notes = payload.get("body") or payload.get("notes") or payload.get("changelog") or ""
    if not isinstance(notes, str):
        notes = str(notes)
    notes = notes.strip()
    truncated = len(notes) > NOTES_MAX
    if truncated:
        notes = notes[:NOTES_MAX].rstrip() + "\n…（说明过长已截断，完整内容见下载页）"
    url = (payload.get("html_url") or payload.get("page")
           or payload.get("download_url") or payload.get("url") or "")
    if not isinstance(url, str):
        url = ""
    asset = pick_asset(payload.get("assets") or payload.get("files") or payload.get("asset"))
    if not url and asset.get("url"):
        url = asset["url"]
    return {
        "version": format_version(parsed),
        "notes": notes,
        "url": url,
        "asset": asset,
    }


def _host(url: str) -> str:
    """从 URL 里取主机名（错误提示里只提域名，不甩整条链接）。"""
    m = re.match(r"^[a-zA-Z][\w+.-]*://([^/?#]+)", url or "")
    return m.group(1) if m else (url or "更新源")


def _http_get(url: str, timeout: int):
    """默认取数实现：返回 (HTTP 状态码, 响应正文)。

    只用标准库（打包体积不增加，也不需要为一次 GET 引入 requests）。
    4xx/5xx 不当异常抛——状态码本身就是要做分支判断的信息；
    网络层失败（DNS / 连接 / 超时）才抛，由 check() 统一翻译。
    """
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/vnd.github+json, application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            # 6MB 上限：正常 Release 正文远小于此，挡住「返回了整页 HTML」的情况
            return r.getcode(), r.read(6 * 1024 * 1024).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read(64 * 1024).decode("utf-8", "replace")
        except Exception:
            pass
        return e.code, body


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def check(current: str, feed: str = None, opener=None, timeout: int = TIMEOUT) -> dict:
    """检查更新，返回统一结果字典（**不抛异常**）。

    status 取值：
      update  —— 有比当前新的版本（version / notes / url 可用）
      latest  —— 已是最新
      ahead   —— 本机版本比发布版还新（开发态，自己比线上超前）
      error   —— 没查成（error 里是中文原因）

    无论哪种结果都带上 current / feed，便于状态栏与「关于」页直接展示。
    """
    feed = feed or FEED_URL
    out = {"status": "error", "current": current or "", "feed": feed,
           "version": "", "notes": "", "url": "", "asset": {},
           "error": "", "checked_at": 0}
    import time
    out["checked_at"] = int(time.time())

    try:
        code, body = (opener or _http_get)(feed, timeout)
    except Exception as e:                      # noqa: BLE001 —— 任何网络异常都要翻译成人话
        out["error"] = ("检查更新失败：连不上 %s（%s）。若这台机器在内网，"
                        "可在 config.json 里把 update_feed 改成内网可访问的版本地址。"
                        % (_host(feed), e))
        return out

    if code == 404:
        out["error"] = ("更新源里还没有发布过版本（HTTP 404）。"
                        "首次发版后这里就能查到版本了。")
        return out
    if code in (403, 429):
        out["error"] = ("更新源暂时拒绝访问（HTTP %s，通常是接口调用次数用尽）。"
                        "稍后再试，或把 update_feed 换成内网自建地址。" % code)
        return out
    if code != 200:
        out["error"] = "更新源返回异常状态 HTTP %s。" % code
        return out

    try:
        payload = json.loads(body or "null")
    except ValueError:
        out["error"] = ("更新源返回的不是有效 JSON（可能被网络中间层改写成了网页）。"
                        "若公司网络有拦截页，请把 update_feed 指向内网地址。")
        return out

    norm = normalize(payload)
    if norm is None:
        out["error"] = ("更新源返回的内容里没有可识别的版本号"
                        "（期望形如 tag_name=v2026.1029.1931）。")
        return out

    out.update(version=norm["version"], notes=norm["notes"],
               url=norm["url"], asset=norm["asset"])
    if is_newer(norm["version"], current):
        out["status"] = "update"
    elif parse_version(norm["version"]) == parse_version(current):
        out["status"] = "latest"
    else:
        out["status"] = "ahead"
    return out


def summary(res: dict) -> str:
    """把结果压成一行中文，供状态栏 / toast 使用。"""
    if not isinstance(res, dict):
        return ""
    st = res.get("status")
    if st == "update":
        return "发现新版本 %s（当前 %s）" % (res.get("version"), res.get("current"))
    if st == "latest":
        return "已是最新版本（%s）" % res.get("current")
    if st == "ahead":
        return "本机版本 %s 比发布版 %s 更新（开发版）" % (res.get("current"),
                                                          res.get("version"))
    return res.get("error") or "检查更新未完成"


def download_size(res: dict) -> str:
    """把资产体积格式化成 MB 文本（无资产信息时返回空串）。"""
    try:
        n = int((res or {}).get("asset", {}).get("size") or 0)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return ""
    return "%.1f MB" % (n / 1024.0 / 1024.0)
