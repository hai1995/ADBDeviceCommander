"""core.envcheck 启动前环境预检的单元测试（headless 可跑，无平台副作用）。

纯逻辑模块，所有平台取值都经参数注入桩，因此 CI / 无头 Linux 下也能完整验证
各分支：parse_version、WebView2 未安装 / 过旧 / 达标、pywebview 缺失 / 过旧 / 达标、
adb 缺失 / 存在，以及 run_all 的汇总与文案结构。
"""
import core.envcheck as ec


def _npv(*versions):
    """构造一个 get_pv 桩：返回给定 pv 版本串列表。"""
    return lambda: list(versions)


def test_parse_version_normal():
    assert ec.parse_version("100.0.1185.36") == (100, 0, 1185, 36)
    assert ec.parse_version("150.0.4078.48") == (150, 0, 4078, 48)


def test_parse_version_loose_and_invalid():
    # 前后脏字符 / 空格可容忍，取数字点分前缀
    assert ec.parse_version("  121.0.2277.1  ") == (121, 0, 2277, 1)
    assert ec.parse_version("v140.1.0") == (140, 1, 0)
    assert ec.parse_version("1.2.x") == (1, 2)      # 尾部脏字符截断取前缀
    # 完全没有数字开头 / 非法 / None -> None
    assert ec.parse_version(None) is None
    assert ec.parse_version("") is None
    assert ec.parse_version("abc") is None
    assert ec.parse_version("v") is None


def test_parse_version_non_decimal_digits_return_none():
    """非十进制「数字」（如 Unicode 上标 ²）必须返回 None，不能抛 ValueError。

    回归：旧实现用 `p.isdigit()` 判断后直接 `int(p)`，而 `'²'.isdigit()` 为真、
    `int('²')` 抛 ValueError。该异常会一路冒到 main._preflight —— 用户看到的是一份
    崩溃日志，而不是「WebView2 缺失 / 过旧」的中文引导弹窗。
    """
    assert ec.parse_version("\u00b2") is None
    assert ec.parse_version("12\u00b2x") is None
    # 非法取值也不能让整轮预检炸掉
    assert ec.run_all(get_pv=_npv("\u00b2"), pywebview_version="6.2",
                      adb_path="adb")[0].name == "WebView2 Runtime"


def test_check_webview2_not_installed():
    p = ec.check_webview2(_npv())          # 没有任何 pv
    assert p is not None
    assert p.name == "WebView2 Runtime"
    assert "WebView2" in p.fix and "https" in p.fix
    # get_pv 为 None（非 Windows 场景）同样视为未安装
    assert ec.check_webview2(None) is not None


def test_check_webview2_too_old():
    p = ec.check_webview2(_npv("100.0.1185.36"))   # 用户实机场景
    assert p is not None
    assert "过旧" in p.name
    assert "100.0.1185.36" in p.detail
    assert str(ec.MIN_WEBVIEW2_MAJOR) in p.fix


def test_check_webview2_ok():
    assert ec.check_webview2(_npv("121.0.2277.1")) is None
    assert ec.check_webview2(_npv("150.0.4078.48")) is None


def test_check_webview2_takes_max_when_multiple():
    # 多个安装位置版本不同时取较大者；最大已达标则通过
    assert ec.check_webview2(_npv("100.0.0.0", "150.0.0.0")) is None
    # 两个都 <121 时报出其中较大的版本
    p = ec.check_webview2(_npv("100.0.0.0", "118.0.0.0"))
    assert p is not None and "118.0.0.0" in p.detail


def test_check_pywebview_missing():
    p = ec.check_pywebview(None)
    assert p is not None and "缺失" in p.name
    assert "pip install -r requirements.txt" in p.fix


def test_check_pywebview_ok_and_old():
    assert ec.check_pywebview("7.0.0") is None
    p = ec.check_pywebview("5.0")          # requirements 要求 >=6
    assert p is not None and "过旧" in p.name
    assert "pip install -U pywebview" in p.fix


def test_check_adb():
    assert ec.check_adb("C:/tools/adb.exe") is None
    p = ec.check_adb(None)
    assert p is not None and p.name == "adb 未找到"
    assert "PATH" in p.fix


def test_blocking_semantics():
    """blocking 标记：只有 adb 缺失不阻断启动（「可启动 + 界面内引导配置」）。

    回归点：main._preflight 过去用 `p.name != "adb 未找到"` 字符串过滤非阻断项，
    一旦 envcheck 改了文案，过滤器就静默失效——没装 adb 的同事连界面都打不开。
    现在过滤依据是结构化字段，与文案解耦。
    """
    assert ec.check_adb(None).blocking is False
    assert ec.check_webview2(_npv()).blocking is True
    assert ec.check_webview2(_npv("100.0.0.0")).blocking is True
    assert ec.check_pywebview(None).blocking is True
    assert ec.check_pywebview("5.0").blocking is True


def test_run_all_summary():
    # 全部失败：应返回 3 条且顺序固定 WebView2 -> pywebview -> adb
    probs = ec.run_all(get_pv=_npv("100.0.0.0"), pywebview_version=None, adb_path=None)
    assert [x.name for x in probs] == [
        "WebView2 Runtime 版本过旧", "pywebview 依赖缺失", "adb 未找到"]
    for pr in probs:                       # 每条都含可展示的三段文案
        msg = pr.message()
        assert pr.name in msg and "处理：" in msg and "现状：" in msg


def test_run_all_empty_when_healthy():
    probs = ec.run_all(get_pv=_npv("150.0.0.0"), pywebview_version="7.0",
                       adb_path="/usr/bin/adb")
    assert probs == []
