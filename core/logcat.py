# -*- coding: utf-8 -*-
"""
core.logcat —— logcat 行分类 / 异常识别（纯逻辑，与 UI 无关）。
供 Logcat 监控实时渲染与抓取共用。

逻辑与 旧 Tk 版（已移除） 中的 _logcat_classify 同源（见 tests/test_logcat_capture.py）。
"""
from core.constants import LOGCAT_EXC_RE, LOGCAT_RE


def _is_exception_like(tag: str, msg: str) -> bool:
    """判定一行是否为异常/崩溃特征。

    与 legacy 一致：tag 命中 TAG_HIT（AndroidRuntime / FATAL EXCEPTION /
    libc / DEBUG）或 msg 命中 LOGCAT_EXC_RE 都视为异常行。判定只看
    tag + msg，**不按级别**（部分设备会把 crash 打到 I/W 级，
    LOGCAT_EXC_RE 的特征匹配已覆盖这类情况）。
    """
    if not msg:
        return False
    tag_hit = tag in ("AndroidRuntime", "FATAL EXCEPTION", "libc", "DEBUG")
    return bool(
        tag_hit
        or (msg and LOGCAT_EXC_RE.search(msg))
    )


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
