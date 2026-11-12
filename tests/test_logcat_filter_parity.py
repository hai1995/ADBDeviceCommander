# -*- coding: utf-8 -*-
"""门禁：logcat 过滤的**前后端两套实现必须给出完全相同的判定**。

背景
----
过滤规则在项目里有两份实现，且是**有意**各写一份的：

  * 前端 `frontend/js/app.js` 的 `lcSplitTerms` / `lcMatchTerm` / `linePassesFilter`
    —— 改关键字即时生效，不必重启 logcat 子进程；
  * 后端 `core/logcat.py` 的 `split_filter_terms` / `match_filter`，以及
    `backend/logcat_service.py` 的 `_classify_and_filter`（落盘抓取的级别过滤）。

`core/logcat.py` 的注释写着「规则一旦改动，两处必须同步」。但「必须同步」目前
只是一句口头约定：两边的单测各自锁定自己的实现，**没有交叉锁定** —— 有人改了前端
却忘了改后端（反之亦然），两边测试照样全绿，用户看到的却是「界面上过滤不生效 /
抓取下来的日志和界面对不上」。

本测试用**差分**把这条约定变成可执行的：从 app.js 里**提取**前端的三个函数
（不是抄一份），与后端真实实现跑同一批样本，判定必须逐条一致。

node 不在环境里时整条跳过（CI 的前端测试 job 本来就需要 node）。
"""
import json
import pathlib
import random
import re
import shutil
import subprocess

import pytest

from core import logcat

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = ROOT / "frontend" / "js" / "app.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="没有 node，跳过前后端差分测试")

_LEVELS = ["V", "D", "I", "W", "E", "F"]
_TAGS = ["ActivityManager", "AndroidRuntime", "PowerManagerService", "chatty",
         "lowmemorykiller", "System.err"]
_MSGS = ["hello world", "ANR in com.demo", "FATAL EXCEPTION: main",
         "connect timeout", "Process com.demo has died", "utf8 中文消息",
         "0x1234 abort", "sqlite error", ""]
_PIDS = ["1234", "4170", "56789"]
_TIDS = ["1234", "1300"]


def _extract_js_function(name):
    """从 app.js 里原样抠出某个函数（含完整花括号配平）。"""
    src = APP.read_text(encoding="utf-8")
    m = re.search(r"function %s\([^)]*\)\s*\{" % re.escape(name), src)
    assert m, "app.js 里找不到 %s" % name
    depth, j = 0, m.end() - 1
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    return src[m.start():j + 1]


def _samples():
    """一批日志行。

    前端拿到的行**就是后端解析后推过来的那条**（含 level / tag / msg / pid /
    tid / exc 字段），所以这里用 `classify_line` 解析 raw 来构造前端样本 —— 两边
    喂的必须是同一份数据，否则比出来的差异全是测试自己造的。
    """
    rnd = random.Random(20261112)
    out = []
    for _ in range(120):
        lvl, tag = rnd.choice(_LEVELS), rnd.choice(_TAGS)
        msg, pid, tid = rnd.choice(_MSGS), rnd.choice(_PIDS), rnd.choice(_TIDS)
        raw = "01-02 03:04:05.678  %s %s %s %s: %s" % (pid, tid, lvl, tag, msg)
        rec = logcat.classify_line(raw)
        assert rec is not None, "样本构造有误：%r 解析失败" % raw
        out.append({"raw": rec["raw"], "level": rec["level"], "tag": rec["tag"],
                    "msg": rec["msg"], "pid": rec["pid"], "tid": rec["tid"],
                    "exc": rec["exc"]})
    # 再加几行「非 threadtime 格式」的纯文本（两端都要原样保留）
    for extra in ("--------- beginning of main", "", "  随机一行文本"):
        out.append({"raw": extra, "level": "", "tag": "", "msg": "",
                    "pid": "", "tid": "", "exc": False})
    return out


def _exprs():
    exprs = ["abc", "ANR", "-ANR", "tag:Activity", "tag:activity", "msg:anr",
             "msg:ANR", "pid:1234", "pid:41", "tid:1300", "level:EWF",
             "level:W", "level:E", "tag:", "pid:", "level:", "ActivityManager hello",
             "-tag:chatty ANR", "utf8", "0x1234", "com.demo", "level:EF",
             "tag:ActivityManager", "  ", "-", "--x", "a  b", "msg:中文"]
    rnd = random.Random(7)
    words = ["abc", "anr", "ANR", "tag:x", "msg:y", "pid:1", "tid:2", "level:W",
             "-abc", "1234", "chatty", "com.demo", "utf8", "-"]
    for _ in range(60):
        exprs.append(" ".join(rnd.choice(words)
                               for _ in range(rnd.randint(1, 3))))
    return exprs


def _run_frontend(samples, exprs, level_sets, only_exc_flags, tmp_path):
    """把 app.js 的三个函数原样送进 node 跑一遍，返回逐条判定。"""
    js = "\n".join([
        _extract_js_function("lcSplitTerms"),
        _extract_js_function("lcMatchTerm"),
        _extract_js_function("linePassesFilter"),
        'const LC_FILTER_FIELDS = ["tag:", "msg:", "pid:", "tid:", "level:", "pkg:"];',
        'const fs = require("fs");',
        'const data = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));',
        'const out = [];',
        'for (const s of data.samples) {',
        '  for (const kw of data.exprs) {',
        '    for (const lv of data.levelSets) {',
        '      for (const oe of data.onlyExc) {',
        '        const f = {levels: lv, onlyExc: oe, terms: lcSplitTerms(kw)};',
        '        out.push(linePassesFilter(s, f) ? 1 : 0);',
        '      }',
        '    }',
        '  }',
        '}',
        'fs.writeFileSync(process.argv[3], JSON.stringify(out));',
    ])
    data_path = tmp_path / "samples.json"
    out_path = tmp_path / "out.json"
    data_path.write_text(json.dumps(
        {"samples": samples, "exprs": exprs, "levelSets": level_sets,
         "onlyExc": only_exc_flags}, ensure_ascii=False), encoding="utf-8")
    script = tmp_path / "front.js"
    script.write_text(js, encoding="utf-8")
    subprocess.run(["node", str(script), str(data_path), str(out_path)],
                   check=True, capture_output=True, timeout=120)
    return json.loads(out_path.read_text())


def _run_backend(samples, exprs, level_sets, only_exc_flags):
    """后端真实实现的逐条判定（行级过滤直接用服务里的那个方法）。"""
    from backend.logcat_service import LogcatMonitor
    out = []
    for s in samples:
        for kw in exprs:
            for levels in level_sets:
                for only_exc in only_exc_flags:
                    rec = LogcatMonitor._classify_and_filter(
                        s["raw"], list(levels), kw, only_exc)
                    # 非 threadtime 行两端都「保留」（前端 linePassesFilter 对
                    # 无 level 的行直接返回 true）
                    kept = rec is not None
                    if rec is not None and not rec.get("level"):
                        kept = True
                    out.append(1 if kept else 0)
    return out


def test_frontend_and_backend_filter_agree(tmp_path):
    """前后端两套过滤实现，对同一批样本必须逐条一致。"""
    samples = _samples()
    exprs = _exprs()
    level_sets = [["V", "D", "I", "W", "E", "F"], ["W", "E", "F"], ["E"]]
    only_exc_flags = [False, True]

    front = _run_frontend(samples, exprs, level_sets, only_exc_flags, tmp_path)
    back = _run_backend(samples, exprs, level_sets, only_exc_flags)
    assert len(front) == len(back)
    diffs = [i for i, (a, b) in enumerate(zip(front, back)) if a != b]
    assert not diffs, (
        "前后端过滤判定不一致 %d 处（样本 %d × 表达式 %d × 级别组 %d × 仅异常 %d）：\n%s"
        % (len(diffs), len(samples), len(exprs), len(level_sets),
           len(only_exc_flags),
           "\n".join("  #%d 样本=%r 表达式=%r"
                     % (i, samples[i // (len(exprs) * len(level_sets) * 2)],
                        exprs[(i // (len(level_sets) * 2)) % len(exprs)])
                     for i in diffs[:10])))


def test_split_terms_agree(tmp_path):
    """切词结果也要一致（切法不同 → 整条表达式的判定就会不同）。"""
    exprs = _exprs()
    js = "\n".join([
        _extract_js_function("lcSplitTerms"),
        'const fs = require("fs");',
        'const data = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));',
        'fs.writeFileSync(process.argv[3],'
        ' JSON.stringify(data.exprs.map((k) => lcSplitTerms(k))));',
    ])
    data_path = tmp_path / "exprs.json"
    out_path = tmp_path / "terms.json"
    data_path.write_text(json.dumps({"exprs": exprs}, ensure_ascii=False),
                         encoding="utf-8")
    script = tmp_path / "terms.js"
    script.write_text(js, encoding="utf-8")
    subprocess.run(["node", str(script), str(data_path), str(out_path)],
                   check=True, capture_output=True, timeout=120)
    front = json.loads(out_path.read_text())
    back = [[{"neg": neg, "term": term} for neg, term in
             logcat.split_filter_terms(kw)] for kw in exprs]
    assert front == back, "前后端切词结果不一致"
