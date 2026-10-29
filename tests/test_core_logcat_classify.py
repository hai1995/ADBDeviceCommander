"""threadtime 行解析 + 日志过滤的分类回归测试。

aosp 的 threadtime 输出里 tag 按 "%-8s: " 打印（**左对齐补空格到 8 列**），所以短 tag
的冒号前会带若干空格：

    08-29 10:23:45.123  1234  1234 I chatty  : uid=1000 expire 5 lines
    08-29 10:23:45.123  1234  1234 E libc    : Fatal signal 11 (SIGSEGV)

早前的正则不允许 tag 与冒号之间有空白，这类行会被整行判成「非 threadtime」而走
原样透传分支，后果是：
  * 级别过滤 / 仅异常 / 关键字过滤对它们**全部失效**（透传行不受任何过滤约束）；
  * `libc` 的 native crash 不再被识别为异常，异常高亮也一并丢失。
"""
import pytest

from backend.logcat_service import LogcatMonitor
from core.logcat import classify_line

# (原始行, 级别, tag, 消息正文(已 strip), 是否异常)
PADDED_CASES = [
    ("08-29 10:23:45.123  1234  1234 I chatty  : uid=1000 expire 5 lines",
     "I", "chatty", "uid=1000 expire 5 lines", False),
    ("08-29 10:23:45.123  1234  1234 E libc    : Fatal signal 11 (SIGSEGV), code 1",
     "E", "libc", "Fatal signal 11 (SIGSEGV), code 1", True),
    ("08-29 10:23:45.123  1234  1234 D Zygote  : Process 1234 created",
     "D", "Zygote", "Process 1234 created", False),
    ("08-29 10:23:45.123  1234  1234 I TagName : the message",
     "I", "TagName", "the message", False),
    # 恰好 8 列：不补空格，冒号紧跟 tag
    ("08-29 10:23:45.123  1234  1234 W EightCol: no padding at all",
     "W", "EightCol", "no padding at all", False),
    # 7 个线程号位数 / 多位数 PID 也不能影响解析
    ("08-29 10:23:45.123  123456  123456 E libc    : Fatal signal 6",
     "E", "libc", "Fatal signal 6", True),
]

UNPADDED_CASES = [
    ("08-29 10:23:45.123  1234  1234 E AndroidRuntime: FATAL EXCEPTION: main",
     "E", "AndroidRuntime", "FATAL EXCEPTION: main", True),
    ("08-29 10:23:45.123  1234  1234 I ActivityManager: Start proc 1234",
     "I", "ActivityManager", "Start proc 1234", False),
]


@pytest.mark.parametrize("raw,level,tag,msg,exc", PADDED_CASES)
def test_padded_tag_is_parsed(raw, level, tag, msg, exc):
    rec = classify_line(raw)
    assert rec is not None, "补齐对齐的 threadtime 行必须能被识别：%r" % raw
    assert (rec["level"], rec["tag"]) == (level, tag)
    assert rec["msg"].strip() == msg
    assert rec["exc"] is exc


@pytest.mark.parametrize("raw,level,tag,msg,exc", UNPADDED_CASES)
def test_unpadded_long_tag_still_parsed(raw, level, tag, msg, exc):
    rec = classify_line(raw)
    assert rec is not None
    assert (rec["level"], rec["tag"]) == (level, tag)
    assert rec["msg"].strip() == msg
    assert rec["exc"] is exc


@pytest.mark.parametrize("raw", [
    "--------- beginning of main",
    "--------- beginning of system",
    "",
    "random plain text without threadtime prefix",
])
def test_non_threadtime_line_returns_none(raw):
    assert classify_line(raw) is None


def test_libc_native_crash_is_flagged_as_exception():
    # 只有修好 tag 与冒号之间的空白容忍度，libc 行才会被分类 → 才谈得上异常识别
    rec = classify_line("08-29 10:23:45.123  1234  1234 E libc    : Fatal signal 11 (SIGSEGV)")
    assert rec is not None and rec["exc"] is True


def test_level_filter_applies_to_padded_short_tags():
    libc = "08-29 10:23:45.123  1234  1234 E libc    : Fatal signal 11"
    chatty = "08-29 10:23:45.123  1234  1234 I chatty  : uid=1000 expire 5 lines"
    # 只保留 I 级：短 tag 的 E 行必须被过滤掉（修复前会原样透传）
    assert LogcatMonitor._classify_and_filter(libc, {"I"}, "", False) is None
    kept = LogcatMonitor._classify_and_filter(chatty, {"I"}, "", False)
    assert kept is not None and kept["tag"] == "chatty"


def test_only_exc_filter_applies_to_padded_short_tags():
    libc = "08-29 10:23:45.123  1234  1234 E libc    : Fatal signal 11"
    chatty = "08-29 10:23:45.123  1234  1234 I chatty  : uid=1000 expire 5 lines"
    assert LogcatMonitor._classify_and_filter(chatty, {"V", "D", "I", "W", "E", "F"}, "", True) is None
    kept = LogcatMonitor._classify_and_filter(libc, {"V", "D", "I", "W", "E", "F"}, "", True)
    assert kept is not None and kept["exc"] is True


def test_keyword_filter_applies_to_padded_short_tags():
    libc = "08-29 10:23:45.123  1234  1234 E libc    : Fatal signal 11"
    chatty = "08-29 10:23:45.123  1234  1234 I chatty  : uid=1000 expire 5 lines"
    assert LogcatMonitor._classify_and_filter(chatty, {"V", "D", "I", "W", "E", "F"}, "fatal", False) is None
    kept = LogcatMonitor._classify_and_filter(libc, {"V", "D", "I", "W", "E", "F"}, "fatal", False)
    assert kept is not None


def test_banner_line_bypasses_filters():
    # 非 threadtime 行（分隔/标题）保持原样透传，不受级别/关键字/仅异常影响
    rec = LogcatMonitor._classify_and_filter("--------- beginning of main", {"I"}, "fatal", True)
    assert rec == {"raw": "--------- beginning of main"}
