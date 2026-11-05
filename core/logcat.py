# -*- coding: utf-8 -*-
"""
core.logcat —— logcat 行分类 / 异常识别 / 时间戳解析（纯逻辑，与 UI 无关）。
供 Logcat 监控实时渲染与抓取共用。

逻辑与 旧 Tk 版（已移除） 中的 _logcat_classify 同源（见 tests/test_logcat_capture.py）。
"""
import datetime
import os

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


# ---------------------------------------------------------------------------
# threadtime 行首时间戳：「MM-DD HH:MM:SS.mmm」（18 字符，不含年份）
# ---------------------------------------------------------------------------
TS_LEN = 18


def ts_prefix(raw: str) -> str:
    """取 threadtime 行首的「MM-DD HH:MM:SS.mmm」，不像日志行则返回 ""。

    只做切片 + 两个字符位判断，不跑正则：抓取是全量落盘的，满缓冲场景每秒
    可上万行，每行再匹配一次正则没有意义。
    """
    if not raw or len(raw) < TS_LEN or raw[2] != "-" or raw[5] != " ":
        return ""
    return raw[:TS_LEN]


def ts_epoch(ts: str, ref=None):
    """把「MM-DD HH:MM:SS.mmm」解析为 epoch 秒（本地时区）；失败返回 None。

    logcat 的 threadtime 里**没有年份**，只能推断：以 ref（默认现在）的年份为
    基准，若算出来的时刻比 ref 晚了半年以上，说明那一行发生在上一年。

    为什么不能用字符串比较代替（旧实现在重连去重时就是直接比字符串）：
    「12-31 23:59」在字符串上大于「01-01 00:00」，跨年录制一夜之后，新日志会
    被整体判成「比断点更早的重放」而全部丢弃 —— 日志从零点起彻底停住。设备
    校时回退同理。故凡是「看起来时间在倒流」的地方都必须落到这里算精确时间。
    """
    if not ts or len(ts) < TS_LEN:
        return None
    try:
        mon = int(ts[0:2])
        day = int(ts[3:5])
        hh = int(ts[6:8])
        mm = int(ts[9:11])
        ss = int(ts[12:14])
        ms = int(ts[15:18])
    except (ValueError, TypeError):
        return None
    ref = ref if isinstance(ref, (int, float)) else None
    if ref is None:
        import time
        ref = time.time()
    year = datetime.datetime.fromtimestamp(ref).year
    for y in (year, year - 1):
        try:
            dt = datetime.datetime(y, mon, day, hh, mm, ss, ms * 1000)
        except ValueError:
            return None
        v = dt.timestamp()
        # 比 ref 晚半年以上 => 那一行其实是去年的（跨年续写靠这一条纠正）
        if v - ref <= 183 * 86400:
            return v
    return None


def _ts_of_bytes(raw: bytes) -> str:
    """从一行原始字节里取时间戳（容错：非法字节替换，不抛异常）。"""
    try:
        text = raw.decode("utf-8", "replace")
    except Exception:
        return ""
    return ts_prefix(text)


def read_time_bounds(path, head_bytes=128 * 1024, tail_bytes=128 * 1024):
    """读抓取文件的 (首条, 末条) threadtime 时间戳；取不到则对应位置为 None。

    只读文件头尾各若干字节：日志文件动辄上百 MB，为了两个时间戳整份读一遍
    既慢又占内存；而首末两条必然落在头/尾附近（缺口标记行、adb 横幅不算
    时间戳，会被跳过）。

    用途是录屏收尾时校验「配套日志到底跟到什么时候」——见
    backend.controllers.record.RecordMixin._logcat_coverage_notes。
    """
    if not path:
        return None, None
    try:
        size = os.path.getsize(path)
    except OSError:
        return None, None
    if size <= 0:
        return None, None
    try:
        with open(path, "rb") as f:
            head = f.read(min(head_bytes, size))
    except OSError:
        return None, None
    first = ""
    for raw in head.split(b"\n"):
        first = _ts_of_bytes(raw)
        if first:
            break
    else:
        first = ""
    parts = None
    if size <= len(head):
        parts = head.split(b"\n")
    else:
        try:
            with open(path, "rb") as f:
                f.seek(max(0, size - tail_bytes))
                tail = f.read()
        except OSError:
            return (first or None), None
        parts = tail.split(b"\n")
        # seek 可能落在一行中间：丢掉第一段残行（它不是完整行，时间戳不可信）
        if len(parts) > 1:
            parts = parts[1:]
    last = ""
    for raw in reversed(parts or []):
        last = _ts_of_bytes(raw)
        if last:
            break
    else:
        last = ""
    return (first or None), (last or None)
