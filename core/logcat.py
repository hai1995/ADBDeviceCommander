# -*- coding: utf-8 -*-
"""
core.logcat —— logcat 行分类 / 异常识别（纯逻辑，与 UI 无关）。
供 Logcat 监控实时渲染与抓取共用。

逻辑与 旧 Tk 版（已移除） 中的 _logcat_classify 同源（见 tests/test_logcat_capture.py）。
"""
from core.constants import LOGCAT_EXC_RE, LOGCAT_RE

# 直接判为异常的 tag（AndroidRuntime 打 Java 崩溃、libc 打 native crash）。
# 用 frozenset：这行判定在日志洪流下每秒要跑上万次，集合查找比元组线性扫描省事。
_TAG_HITS = frozenset(("AndroidRuntime", "FATAL EXCEPTION", "libc", "DEBUG"))

# ---- 快速否定的「必含子串」 ----------------------------------------------
# LOGCAT_EXC_RE 是一张十几条分支的大交替（还带 IGNORECASE），在**不命中**时
# 要逐条扫过整个消息才能确认 —— 400 字符的消息实测 38 μs/行。而 logcat 洪流下
# 每行都要过一次这个判定（监控分类 + 抓取落盘的级别过滤），一秒几千行就是
# 上百毫秒的纯 CPU，全压在 logcat 读取线程上，读得慢 -> 丢行/延迟。
#
# 这里先用一组极廉价的子串查找做否定：表中每一项都是正则某个分支的**必然
# 子串**（见下方逐条对照），不含任何一项就绝不可能命中正则 —— 于是绝大多数
# 普通日志只需要 15 次 C 层 str.__contains__（实测 3.5 μs）就被否掉，只有疑似
# 行才付出整条正则的代价。
#
#   分支                              必然子串
#   FATAL EXCEPTION / \bFATAL\b       "fatal"
#   AndroidRuntime                     "androidruntime"
#   java\.lang\.                       "java.lang."
#   j\.?ni\.                           "jni" 或 "j.ni."
#   Caused by\s                       "caused by"
#   at [a-zA-Z][\w.$]*\(              "at "
#   Native crash                       "native crash"
#   signal \d+ \(                      "signal "
#   tombstone                          "tombstone"
#   Stack trace                        "stack trace"
#   backtrace                          "backtrace"
#   \b(...)[A-Za-z]*Exception\b        "exception"
#   \bANR\b                            "anr"
#   \bcrash\b                          "crash"
#
# 顺序按「疑似行的命中概率」粗排：常见形态（堆栈的 "at "、抛异常的 "exception"）
# 靠前，命中即止。对**不命中**的行顺序没有影响（都要走完）。
_EXC_HINTS = (
    "exception", "fatal", "crash", "androidruntime", "java.lang.",
    "caused by", "stack trace", "backtrace", "tombstone", "native crash",
    "signal ", "jni", "j.ni.", "anr", "at ",
)


def _may_be_exception(msg: str) -> bool:
    """廉价预筛：消息里是否含任一「异常特征必然子串」。

    用 casefold() 而不是 lower()：正则带 re.IGNORECASE，走的是 Unicode
    simple case folding，而 casefold 是更宽的 full folding —— 只会**多**放行
    （多跑一次正则），不会漏判（'ß' -> 'ss'、'ſ' -> 's' 都被覆盖）。
    """
    low = msg.casefold()
    for hint in _EXC_HINTS:
        if hint in low:
            return True
    return False


def _is_exception_like(tag: str, msg: str) -> bool:
    """判定一行是否为异常/崩溃特征。

    与 legacy 一致：tag 命中 TAG_HIT（AndroidRuntime / FATAL EXCEPTION /
    libc / DEBUG）或 msg 命中 LOGCAT_EXC_RE 都视为异常行。判定只看
    tag + msg，**不按级别**（部分设备会把 crash 打到 I/W 级，
    LOGCAT_EXC_RE 的特征匹配已覆盖这类情况）。

    判定结果与「直接跑 LOGCAT_EXC_RE」完全一致，中间那层 `_may_be_exception`
    只是把绝大多数普通行用更便宜的代价否掉（见 _EXC_HINTS 的说明）；
    tests/test_core_logcat_classify.py 里有逐分支样本 + 随机串的等价性回归。
    """
    if not msg:
        return False
    if tag in _TAG_HITS:
        return True
    if not _may_be_exception(msg):
        return False
    return bool(LOGCAT_EXC_RE.search(msg))


def classify_line(line: str):
    """对单行 logcat 文本做分类（纯函数，供测试/监控/抓取共用）。

    返回 dict 或 None：
      {
        "raw":       原始行（未去掉换行）
        "level":     V/D/I/W/E/F（无则 None）
        "tag":       标签（无则 None）
        "msg":       消息内容
        "exc":       bool，是否异常特征行
      }
    None 表示该行不是 threadtime 日志格式（可能是标题/分隔线/空行），
    交由上层决定是否保留为“原始行”。
    """
    text = (line or "").rstrip("\n")
    if not text:
        return None
    # 复用 core.constants 模块级已编译的 LOGCAT_RE，避免每行都重新编译正则
    # （logcat 高频场景每秒可达数万行，重复编译开销可观）。
    m = LOGCAT_RE.match(text)
    if not m:
        return None
    level, tag, msg = m.group(1), m.group(2), m.group(3)
    return {
        "raw": text,
        "level": level,
        "tag": tag,
        "msg": msg,
        "exc": _is_exception_like(tag, msg),
    }
