"""
core.logcat —— logcat 行分类 / 异常识别 / 时间戳解析（纯逻辑，与 UI 无关）。
供 Logcat 监控实时渲染与抓取共用。

逻辑与 旧 Tk 版（已移除） 中的 _logcat_classify 同源（见 tests/test_logcat_capture.py）。
"""
import datetime

from core.constants import LOGCAT_EXC_RE, LOGCAT_RE
from core.longpath import long_path, path_getsize

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
    pid, tid, level, tag, msg = (
        m.group(1), m.group(2), m.group(3), m.group(4), m.group(5))
    return {
        "raw": text,
        "pid": pid,
        "tid": tid,
        "level": level,
        "tag": tag,
        "msg": msg,
        "exc": _is_exception_like(tag, msg),
    }


# ---------------------------------------------------------------------------
# 过滤表达式（关键字）解析与匹配 —— 与前端 app.js 的 lcSplitTerms/lcMatchTerm
# 保持同一套语义。两边各有一份实现是**有意**的：后端用它做落盘侧的兜底过滤，
# 前端用它做「改关键字即时生效」的本地过滤（不必重启 logcat 子进程）。规则
# 一旦改动，两处必须同步，且 tests 与 tests/frontend 各有对应用例锁定。
#
# 语法：
#   空格分隔      多个词 = AND（每个词都要命中）
#   -前缀         排除（如 -tag:Noise 表示「不要含 Noise 这个 tag 的行」）
#   tag:x         tag 字段包含 x
#   msg:x         消息正文包含 x
#   pid:x         pid 精确等于 x（右键菜单填入的就是精确值）
#   tid:x         tid 精确等于 x
#   level:x       级别属于 x 中的字母（"level:EWF" = 只看 W/E/F）
#   pkg:包名      该包名下所有进程的 pid（需调用方预先解析出 pkg_pids）
#   无前缀        在整行原文里包含（兼容旧行为，也覆盖进程名等其它字段）
FILTER_FIELDS = ("tag:", "msg:", "pid:", "tid:", "level:", "pkg:")


def split_filter_terms(keyword):
    """把过滤表达式切成 ``[(negate, term), ...]``；空表达式返回 ``[]``。

    单独抽出供前端/后端/测试共用同一份切词结果，避免「空格切分」这种
    看似简单、实际容易在连续空格、首尾空格、孤立 '-' 上各写各的。
    """
    out = []
    for token in str(keyword or "").split():
        # 只有一个 '-' 时不当作排除符：用户可能真的想搜连字符
        negate = len(token) > 1 and token.startswith("-")
        term = (token[1:] if negate else token).strip()
        if term:
            out.append((negate, term))
    return out


def match_one_term(rec, term, pkg_pids=None):
    """单个过滤词是否命中一行（rec 为 classify_line 的返回值）。

    pkg_pids：``{包名小写: {"pid", ...}}``。pkg: 无法在纯文本里判断，必须由
    调用方先用 ``adb shell pidof`` 解析成 pid 集合再传进来；没有映射就当作
    不命中（宁可少匹配，也不要把「过滤条件没生效」伪装成全量放行）。
    """
    low = str(term).lower()
    for prefix in FILTER_FIELDS:
        if not low.startswith(prefix):
            continue
        pat = low[len(prefix):]
        if not pat:
            return True                 # 只写了 "tag:"：视为无效词，忽略
        if prefix == "tag:":
            return pat in (rec.get("tag") or "").lower()
        if prefix == "msg:":
            return pat in (rec.get("msg") or "").lower()
        # pid/tid 用精确比较：子串会让 "pid:41" 命中 4170，做排除时误伤一片
        if prefix == "pid:":
            return (rec.get("pid") or "") == pat
        if prefix == "tid:":
            return (rec.get("tid") or "") == pat
        if prefix == "level:":
            return (rec.get("level") or "").lower() in pat
        if prefix == "pkg:":
            pids = (pkg_pids or {}).get(pat) or ()
            return bool(pids) and (rec.get("pid") or "") in pids
    # 无前缀：整行原文匹配。既兼容旧行为，也覆盖 tag/msg 之外的字段
    # （进程名、被截断消息的前半段等），用户「搜得到才是硬道理」。
    return low in (rec.get("raw") or "").lower()


def match_filter(rec, keyword, pkg_pids=None):
    """整条表达式是否命中（AND 语义；任一排除词命中即整行不通过）。"""
    for negate, term in split_filter_terms(keyword):
        ok = match_one_term(rec, term, pkg_pids)
        if negate:
            if ok:
                return False
        elif not ok:
            return False
    return True


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


def ts_epoch(ts: str, ref=None, tz_offset=None):
    """把「MM-DD HH:MM:SS.mmm」解析为 epoch 秒；失败返回 None。

    logcat 的 threadtime 里**没有年份**，只能推断：以 ref（默认现在）的年份为
    基准，若算出来的时刻比 ref 晚了半年以上，说明那一行发生在上一年。

    时区（`tz_offset`，秒）默认 None = 按**本机**本地时区解释，这对
    logcat_service 是够用的：那里比的是同一台设备的两条日志，两边的时区误差
    完全抵消。但跨机器对照就不能这么算了 —— 录屏收尾要拿「日志最后一条」和
    「设备此刻」作差，两个时刻都来自设备，必须都按**设备**的时区解释。传
    `tz_offset` 即为设备偏移（见 backend.screen_service.device_clock），
    否则主机 +0800、设备 UTC 时会被算成平白少了 8 小时。

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
    if tz_offset is None:
        # 本机时区（logcat_service 的去重走这条：同设备两条日志，误差自相抵消）
        tz = None
        year = datetime.datetime.fromtimestamp(ref).year
    else:
        tz = datetime.timezone(datetime.timedelta(seconds=tz_offset))
        # 年份也要按设备时区推：跨年那一夜，主机与设备的「今年」可能差一年
        year = datetime.datetime.fromtimestamp(ref, tz).year
    for y in (year, year - 1):
        try:
            dt = datetime.datetime(y, mon, day, hh, mm, ss, ms * 1000, tzinfo=tz)
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
        # 长路径安全：录屏收尾时校验「配套日志跟到什么时候」用的就是这里。
        # 超过 260 字符时 getsize 抛 OSError → 返回 (None, None) → 界面报
        # 「配套日志没覆盖到录屏区间」，而日志其实好好的，只是路径太长。
        size = path_getsize(path)
    except OSError:
        return None, None
    if size <= 0:
        return None, None
    try:
        with open(long_path(path), "rb") as f:
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
            with open(long_path(path), "rb") as f:
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
