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
import random

import pytest

from backend.logcat_service import LogcatMonitor
from core.constants import LOGCAT_EXC_RE
from core.logcat import _TAG_HITS, _is_exception_like, classify_line

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


# --------------------------------------------------------------------------- #
# 异常判定的「廉价预筛」：结果必须与直接跑正则完全一致
# --------------------------------------------------------------------------- #
# 预筛（core.logcat._EXC_HINTS）在正则之前用子串查找做快速否定，把绝大多数
# 普通行（真实日志里 >99%）从「38 μs 的整条正则」降到「几个 μs 的子串查找」。
# 代价是：一旦某个分支的必然子串没被收录，异常行会**静默地不再被标记**——
# 「仅异常」过滤会把真正的崩溃藏起来，而界面上看不出任何异常。故这里逐个
# 分支钉住，并用随机串做等价性对拍。

def _reference(tag, msg):
    """改动前的判定方式，作为对照的「标准答案」。"""
    if not msg:
        return False
    return bool(tag in _TAG_HITS or LOGCAT_EXC_RE.search(msg))


# 正则的每一条分支各给一个样本（左列），加上一批必须判为「非异常」的普通行
EXC_TRUE_MSGS = [
    "FATAL EXCEPTION: main",
    "AndroidRuntime: shutting down",
    "java.lang.NullPointerException: boom",
    "jni. error",                                  # j\\.?ni\\. 的 "jni." 形态
    "j.ni. error",                                 # j\\.?ni\\. 的 "j.ni." 形态
    "Caused by: java.lang.Throwable",
    "at com.example.app.MainActivity.onCreate(MainActivity.java:42)",
    "Native crash at /system/lib64/libc.so",
    "signal 11 (SIGSEGV), code 1",
    "tombstone written to /data/tombstones",
    "Stack trace:",
    "backtrace:",
    "NullPointerException",
    "IllegalStateException",
    "RuntimeException",
    "IndexOutOfBoundsException",
    "SecurityException",
    "ClassNotFoundException",
    "ActivityNotFoundException",
    "ServiceNotFoundException",
    "ANR in com.example.app",
    "app crash detected",
    "\u017ftack trace",                            # 长 s：casefold 后等于 "stack"
    "\u017fTACK TRACE",                            # 长 s + 全大写形态
]

EXC_FALSE_MSGS = [
    "uid=1000 expire 5 lines",
    "just a normal message",
    "format (x) nothing here",                     # 含 "at " 但不构成堆栈帧
    "x" * 400,
    "OutOfMemoryError",                            # 该分支要求以 Exception 结尾
    "",
]


@pytest.mark.parametrize("msg", EXC_TRUE_MSGS)
def test_exception_samples_are_flagged(msg):
    assert _is_exception_like("SomeTag", msg) is True, msg
    assert _is_exception_like("SomeTag", msg) == _reference("SomeTag", msg)


@pytest.mark.parametrize("msg", EXC_FALSE_MSGS)
def test_ordinary_samples_are_not_flagged(msg):
    assert _is_exception_like("SomeTag", msg) is False, msg
    assert _is_exception_like("SomeTag", msg) == _reference("SomeTag", msg)


def test_crash_tag_hits_without_any_keyword():
    """tag 命中时无需看消息内容（libc / DEBUG 打的行常常只有一行地址）。"""
    for tag in _TAG_HITS:
        assert _is_exception_like(tag, "short msg") is True


def test_exception_prefilter_agrees_with_raw_regex_on_random_text():
    """随机拼串对拍：预筛不得把正则能命中的行否掉。

    片段池刻意混入 'ß' / 'ſ' 这类 Unicode 大小写折叠特例 —— 预筛用 casefold
    而正则用 re.IGNORECASE，两者的折叠范围不完全相同，只有在这些字符上才可能
    出现分歧。
    """
    pool = ["at ", "com.a.B(", "java.lang.", "Exception", "FATAL", "crash",
            "anr", "jni.", "j.ni.", "signal ", "tombstone", "Stack trace",
            "backtrace", "Caused by ", "Native", "AndroidRuntime",
            "OutOfMemory", "NullPointer", "x", " ", "(", ":", "中文",
            "\u00df", "\u017f", "K", "0"]
    rnd = random.Random(20261031)
    for _ in range(20000):
        msg = "".join(rnd.choice(pool) for _ in range(rnd.randint(1, 8)))
        assert _is_exception_like("T", msg) == _reference("T", msg), msg
