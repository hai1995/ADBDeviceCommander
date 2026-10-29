"""backend.bus 的限流测试：事件条数 ≠ 数据量（logcat 一行 append 可带数百行）。"""
import threading

from backend.bus import BackendBus


def _append(lines):
    return {"kind": "logcat", "payload": {"status": "append", "lines": [1] * lines}}


def _status():
    return {"kind": "status", "payload": {"type": "info", "text": "x"}}


def test_take_limited_by_lines_not_just_count():
    """单次 take 的日志行合计受 max_lines 约束，避免一次返回几十万行卡死前端。"""
    bus = BackendBus()
    for _ in range(10):                 # 10 个 append 事件，每个 400 行 = 4000 行
        bus.push("logcat", {"status": "append", "lines": [1] * 400})
    out = bus.take(max_n=2000, max_lines=2000)
    n = sum(len(e["payload"]["lines"]) for e in out)
    assert n <= 2000, f"单次返回 {n} 行，超过 max_lines 上限"
    # 多出来的事件应留在队列里，下一轮再取
    assert len(bus.take()) <= 2000


def test_control_events_always_taken_even_when_lines_over_limit():
    """非 logcat 事件不计入行限流，必须被取走，否则控制事件会被日志淹没。"""
    bus = BackendBus()
    bus.push("status", {"type": "info", "text": "keep me"})
    for _ in range(10):
        bus.push("logcat", {"status": "append", "lines": [1] * 400})
    out = bus.take(max_n=2000, max_lines=2000)
    kinds = [e["kind"] for e in out]
    assert "status" in kinds, "status 事件被日志挤掉了"


def test_pending_cap_drops_oldest_append_not_control():
    """积压超过上限时只丢最旧的 logcat append，运行/停止/错误等关键事件保留。"""
    bus = BackendBus(max_pending_lines=1000)
    bus.push("logcat", {"status": "running"})          # 关键控制事件
    for _ in range(10):                                # 4000 行，远超 1000 上限
        bus.push("logcat", {"status": "append", "lines": [1] * 400})
    bus.push("logcat", {"status": "stopped"})          # 关键控制事件
    # pending_lines 被压到上限内
    assert bus.pending_lines() <= 1000, f"pending_lines={bus.pending_lines()}"
    # 关键事件仍在（未被裁剪逻辑误删）
    kinds = [e["kind"] for e in bus._events]
    assert "logcat" in kinds
    # running / stopped 作为非 append 事件，永远不丢
    payloads = [e["payload"].get("status") for e in bus._events]
    assert "running" in payloads and "stopped" in payloads


def test_take_thread_safe_under_concurrent_push():
    """并发 push 下 take 不丢事件也不崩溃（模拟多 worker 场景）。"""
    bus = BackendBus()
    errs = []

    def producer():
        try:
            for _ in range(300):
                bus.push("status", {"type": "info", "text": "x"})
        except Exception as e:            # noqa: BLE001
            errs.append(e)

    threads = [threading.Thread(target=producer) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    taken = 0
    while True:
        evs = bus.take()
        if not evs:
            break
        taken += len(evs)
    assert taken == 1200, f"并发下事件丢失：{taken}/1200"
    assert not errs, f"push 抛错：{errs}"


def test_console_output_counts_toward_backpressure():
    """命令输出（console out）按行计入积压：正常命令不丢行，且能正常取走。"""
    bus = BackendBus()
    for _ in range(100):                      # 100 个 console 事件，每行 1 行
        bus.push("console", {"kind": "out", "text": "line"})
    assert bus.pending_lines() == 100
    out = bus.take(max_n=2000, max_lines=2000)
    assert len(out) == 100
    assert all(e["kind"] == "console" for e in out)


def test_console_flood_bounded_by_pending_cap():
    """持续高产出命令（cat 大文件 / adb logcat 管道）：超出积压上限后丢弃最旧输出，
    总线 deque 不再无限增长（堵住内存泄漏），并保留滚动尾缓冲。"""
    bus = BackendBus(max_pending_lines=2000)
    N = 20000                                 # 远超 2000 上限
    for i in range(N):
        bus.push("console", {"kind": "out", "text": "L%d" % i})
    # 积压被压到上限内（不再是无限增长）
    assert bus.pending_lines() <= 2000, f"pending_lines={bus.pending_lines()}"
    assert len(bus._events) <= 2000
    # 最旧的 L0 已丢弃，最新的 L(N-1) 仍在（尾缓冲）
    texts = [e["payload"]["text"] for e in bus._events]
    assert "L0" not in texts
    assert "L%d" % (N - 1) in texts
    # 仍能正常取走最近的一批
    out = bus.take(max_n=2000, max_lines=2000)
    assert len(out) > 0


def test_console_clear_is_control_not_counted():
    """console clear 是控制事件，不计入行数、永不被积压裁剪误删。"""
    bus = BackendBus(max_pending_lines=10)
    bus.push("console", {"kind": "clear"})
    assert bus.pending_lines() == 0
    assert any(e["payload"].get("kind") == "clear" for e in bus._events)


def test_take_consumes_from_deque_leaving_rest():
    """take 应从队首消费事件（而非拷贝），剩余事件保留在队列中。

    这是 deque 重构后的关键契约：旧实现的 self._events = self._events[i:]
    等价于消费语义，重构后改用 deque.popleft 必须保持同一行为，否则会重复投递
    或漏投事件。
    """
    from collections import deque

    bus = BackendBus()
    assert isinstance(bus._events, deque), "内部存储应为 deque（O(1) 取走）"
    for i in range(5):
        bus.push("status", {"type": "info", "text": "x%d" % i})

    first = bus.take(max_n=2, max_lines=2000)
    assert [e["payload"]["text"] for e in first] == ["x0", "x1"]
    # 剩余 3 条仍留在队列，下一轮取走
    rest = bus.take()
    assert [e["payload"]["text"] for e in rest] == ["x2", "x3", "x4"]
    assert bus.take() == []


def test_trim_keeps_order_and_only_scans_dropped_prefix():
    """背压裁剪只从队首弹出、并保持剩余事件的原有先后顺序。

    回归：旧实现每次都把整个 deque 重建一遍（kept = deque() + 全量 popleft），
    而背压恰恰在「推送速度超过前端轮询消费」时持续触发 —— 于是洪水期间**每一次
    push** 都变成 O(积压条数) 且全程持锁，GIL 被大量占用，take_events 被拖慢，
    界面反而更卡（正是限流想解决的那个场景）。

    修复后只为「真正被丢弃的前缀」付出代价，因此这里额外断言：裁剪完成后，
    未被丢弃的事件顺序与内容完全不变，且队列长度等于上限内的合理值。
    """
    bus = BackendBus(max_pending_lines=1000)
    for i in range(10):                       # 每 400 行，共 4000 行
        bus.push("logcat", {"status": "append", "lines": [i] * 400})
        # 真正的控制事件（非 append 的 logcat 状态）：行数为 0，永不被裁剪
        bus.push("logcat", {"status": "running", "seq": i})

    assert bus.pending_lines() <= 1000
    left = list(bus._events)
    # 控制事件一个都不能丢，且保持原有先后顺序
    markers = [e["payload"]["seq"] for e in left
               if e["payload"].get("status") == "running"]
    assert markers == list(range(10)), markers
    # 保留下来的 append 必须是「最近的若干个」，且顺序不乱
    kept_vals = [e["payload"]["lines"][0] for e in left
                 if e["payload"].get("status") == "append"]
    assert kept_vals == sorted(kept_vals), kept_vals
    assert kept_vals and kept_vals[-1] == 9, kept_vals
    assert 0 not in kept_vals, "最旧的 append 应被丢弃"
    # 相对顺序：把 left 投影回原推送序列的 token 序列后，必须仍是原序列的子序列
    tokens = []
    for i in range(10):
        tokens.append("append%d" % i)
        tokens.append("ctl%d" % i)
    got = [("append%d" % e["payload"]["lines"][0])
           if e["payload"].get("status") == "append"
           else ("ctl%d" % e["payload"]["seq"]) for e in left]
    it = iter(tokens)
    assert all(t in it for t in got), "裁剪后的事件顺序被打乱：%r" % got


def test_trim_does_not_scan_tail_events():
    """裁剪的工作量应与「被丢弃的前缀」成正比，而不是与整条队列长度成正比。

    用一个大 payload 事件把配额一次性打满：修复后只需弹出队首这一条即可回到
    上限内；旧实现则会把剩余的上万个事件全部重新 append 一遍（kept deque）。
    """
    bus = BackendBus(max_pending_lines=100)
    for i in range(5000):                     # 大量小事件（各自 1 行）撑起长队列
        bus.push("console", {"kind": "out", "text": "L%d" % i})
    assert bus.pending_lines() <= 100
    # 剩下的都应是最近的尾巴（L4999 必须还在）
    texts = [e["payload"]["text"] for e in bus._events]
    assert "L4999" in texts
    assert "L0" not in texts
    assert len(bus._events) == bus.pending_lines() == 100
