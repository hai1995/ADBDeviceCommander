# -*- coding: utf-8 -*-
r"""门禁：性能统计的**前后端两套实现必须给出完全相同的数字**。

背景
----
同一个「P95」在本项目里被算了两遍：

  * 前端 `frontend/js/app.js` 的 `perfPct()` —— 性能面板上拖选区间后弹出的
    「区间统计」卡（均值 / 最低 / P95 / 最高）；
  * 后端 `backend/perf_service.py` 的 `summarize()` —— 导出的 HTML 报告里
    每个指标的统计表（最低 / 均值 / 最高 / P95），以及多设备对比报告。

两边**消费的不是同一批数据**（前端是用户拖选的那一段，后端是整场会话），
所以「数值不同」本身不一定是 bug。但**算法**必须一致：同一个指标用两套公式
算，用户在「区间统计」卡里看到 P95 = 60、在报告里看到 P95 = 55，
没有任何办法判断哪个是真的 —— 报告是要拿去跟客户对账的东西。

这跟第九轮修的 logcat 过滤是同一类问题：**同一份规则写了两遍**。上一轮的
差分门禁已经把「规则漂移」从「靠人记住要同步」变成了「改漏就红」。

这次的实际分歧
--------------
后端原实现是 ``int(round(0.95 * (n - 1)))``，前端是 ``ceil(0.95 * n) - 1``：

  * 前者是「线性插值的位置再取整」，后者才是真正的 **nearest-rank**
    （第 ceil(p·n) 个，1 起算）；
  * 二者在 **85/200** 的样本量上给出不同结果，且旧的后端公式因为 Python 的
    **银行家舍入**（``round(28.5) == 28``）还会系统性地偏低一格；
  * 差异最刺眼的地方：n=12 时前端给的是**最大值**，后端给的是次大值。

本测试从 app.js 里**提取**前端的 `perfPct()`（不是抄一份 —— 抄的会跟着前端
一起漂移，等于没测），与后端真实实现跑同一批样本，结果必须逐条一致。

node 不在环境里时整条跳过（CI 的前端测试 job 本来就需要 node）。
"""
import json
import math
import pathlib
import random
import re
import shutil
import subprocess

import pytest

from backend import perf_service as svc

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = ROOT / "frontend" / "js" / "app.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="没有 node，跳过前后端差分测试")


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


def _run_frontend(sorted_lists, tmp_path):
    """把 app.js 的 perfPct 原样送进 node 跑一遍，返回逐条 P95。"""
    js = "\n".join([
        _extract_js_function("perfPct"),
        'const fs = require("fs");',
        'const data = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));',
        'const out = data.lists.map((xs) => {',
        '  const v = perfPct(xs, 0.95);',
        '  return v === null ? null : v;',
        '});',
        'fs.writeFileSync(process.argv[3], JSON.stringify(out));',
    ])
    data_path = tmp_path / "lists.json"
    out_path = tmp_path / "out.json"
    data_path.write_text(json.dumps({"lists": sorted_lists}), encoding="utf-8")
    script = tmp_path / "front.js"
    script.write_text(js, encoding="utf-8")
    subprocess.run(["node", str(script), str(data_path), str(out_path)],
                   check=True, capture_output=True, timeout=120)
    return json.loads(out_path.read_text())


def _sample_lists():
    """一批**已排序**的数值列表。

    前端 perfPct() 收的已经是排好序的数组（perfRangeModel 里先 sort 再传），
    后端 summarize() 内部自己 sort —— 两边喂的必须是同一份数据。
    """
    rnd = random.Random(20261112)
    lists = []
    # 1) 连续整数：覆盖 n = 1..200 的每一个样本量，把公式分歧全踩一遍
    for n in range(1, 201):
        lists.append([float(v) for v in range(1, n + 1)])
    # 2) 随机浮点：带小数、含负数、含重复值
    for _ in range(120):
        n = rnd.randint(1, 80)
        vals = [round(rnd.uniform(-50.0, 120.0), 3) for _ in range(n)]
        lists.append(sorted(vals))
    # 3) 边界值：全相同、含 0、含极值
    lists.extend([
        [0.0],
        [5.0, 5.0, 5.0],
        [-1.0, 0.0, 1.0],
        [0.0, 100.0],
        [round(v * 0.1, 2) for v in range(1, 51)],
    ])
    return lists


def test_frontend_and_backend_p95_agree(tmp_path):
    """前后端两套 P95 实现，对同一批样本必须逐条一致。"""
    lists = _sample_lists()
    front = _run_frontend(lists, tmp_path)

    diffs = []
    for i, xs in enumerate(lists):
        back = svc.summarize(xs)["p95"]
        f = front[i]
        if f is None or back is None:
            diffs.append((i, xs, f, back))
            continue
        # 后端 summarize 对结果做了 round(..., 1)，前端 perfPct 返回原值；
        # 比的是「显示出来的那个数」，所以两边都按后端的口径对齐。
        if abs(float(f) - float(back)) > 0.05:
            diffs.append((i, xs, f, back))
    assert not diffs, (
        "前后端 P95 不一致 %d 处（共 %d 组样本）：\n%s"
        % (len(diffs), len(lists),
           "\n".join("  #%d n=%d 前端=%r 后端=%r" % (i, len(xs), f, b)
                     for i, xs, f, b in diffs[:10])))


def test_backend_p95_is_true_nearest_rank():
    """后端必须是**真正的 nearest-rank**：第 ceil(0.95·n) 个（1 起算）。

    这条不是重复上面的差分门禁，而是把「公式本身」钉死：即使有人把前端的
    perfPct 一起改成别的算法，差分门禁仍然绿（两边一起错），但这条会红。
    """
    for n in range(1, 201):
        vals = [float(v) for v in range(1, n + 1)]
        got = svc.summarize(vals)["p95"]
        want = vals[min(n - 1, max(0, math.ceil(0.95 * n) - 1))]
        assert got == want, (
            "n=%d 时后端 P95=%r，应为 nearest-rank 的 %r" % (n, got, want))


def test_p95_differs_from_the_old_broken_formula():
    """旧公式（round(0.95·(n-1))）必须已经被换掉。

    旧公式在 85/200 的样本量上与 nearest-rank 不同，且因为 Python 的银行家
    舍入（round(28.5)==28）系统性地偏低一格。这里挑几个「差异最刺眼」的
    样本量钉住：

      * n=12 / 13 / 19：nearest-rank 落在**最大值**上，旧公式给的是次大值；
      * n=31：旧公式因银行家舍入 round(28.5)==28 再偏低一格；
      * n=52：旧公式同样偏低一格。
    """
    for n in (12, 13, 19, 31, 52):
        vals = [float(v) for v in range(1, n + 1)]
        old = vals[min(n - 1, max(0, int(round(0.95 * (n - 1)))))]
        new = svc.summarize(vals)["p95"]
        want = vals[min(n - 1, max(0, math.ceil(0.95 * n) - 1))]
        assert new == want, (
            "n=%d 时后端 P95=%r，应为 nearest-rank 的 %r" % (n, new, want))
        assert new != old, (
            "n=%d 时后端 P95 仍是旧公式的 %r（应为 nearest-rank 的 %r）"
            % (n, old, want))
    # n<=19 时 nearest-rank 恰好落在最大值上（旧公式给的是次大值）
    for n in (12, 13, 19):
        vals = [float(v) for v in range(1, n + 1)]
        assert svc.summarize(vals)["p95"] == vals[-1], (
            "n=%d 时 nearest-rank 的 P95 应为最大值" % n)
