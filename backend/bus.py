# -*- coding: utf-8 -*-
"""
backend.bus —— 线程安全事件总线。

所有后台线程通过 bus.push(type, payload) 通知前端；
前端通过 WebApi.take_events() 轮询拉取增量（模拟原 Tk 版的 _poll_queue 语义，
避免 pywebview evaluate_js 的线程限制，天然适配 logcat 大流量）。

限流是这里的核心职责之一：**事件条数不等于数据量**。
logcat 的一个 append 事件可携带数百行日志，若只按条数限流（过去的做法），
单次 take 可能返回几十万行，JSON 序列化 + 跨进程传输 + 前端解析会直接把
界面打死 —— 表现为「一开始监控就卡住，滚动完全没反应」。
因此这里同时按「事件条数」与「日志行数」双限流，并对未取走的积压设上限。

实现要点（性能）
----------------
* 内部用 `collections.deque` 存事件：push 是 O(1) 尾插，take 用 `popleft`
  从队首取走、剩余留在 deque 中，不再像旧实现那样每次轮询都做
  `self._events = self._events[i:]` 的整列表切片拷贝（O(n)）。高频 logcat
  场景下这能显著减少每 400ms 一次 take 的拷贝开销。
* 每个事件的「携带日志行数」在 push 时一次性算好并缓存到 `ev["_n"]`，
  take / 积压裁剪不再对同一个事件反复解析 payload。
"""
import threading
from collections import deque


def _payload_lines(ev):
    """事件携带的「数据行数」（用于行级限流与积压裁剪）。

    只有「数据型」事件计数，控制类事件（running/stopped/error、devices、
    console/status 的 clear 等）视作 0——确保它们永不被积压裁剪误删、也永不被
    行预算挤掉。
      * logcat append：其 lines 数组长度；
      * console out/cmd：单行回显（偶有多行块）按文本换行计；
      * status 非 clear：同上。
    命令输出（adb logcat 管道 / cat 大文件 / 飞快构建）原本逐行推送、n=0 不计入
    任何限流，生产速度一旦超过前端轮询消费速度，总线 deque 便无限增长（内存泄漏）；
    让它计入行数后，与 logcat 共享 max_pending_lines 背压与滚动尾缓冲，正常命令不丢行。
    结果缓存到 ev["_n"]，避免 push / take / 裁剪对同一事件反复计算。
    """
    n = ev.get("_n")
    if n is None:
        n = 0
        kind = ev.get("kind")
        p = ev.get("payload") or {}
        if kind == "logcat" and p.get("status") == "append":
            n = len(p.get("lines") or [])
        elif kind == "console":
            if p.get("kind") in ("out", "cmd"):
                n = max(1, (p.get("text") or "").count("\n") + 1)
        elif kind == "status":
            if p.get("type") != "clear":
                n = max(1, (p.get("text") or "").count("\n") + 1)
        ev["_n"] = n
    return n


class BackendBus:
    def __init__(self, max_pending_lines=20000):
        self._lock = threading.Lock()
        self._events = deque()
        self._buf_lines = 0                       # 未取走的日志行数
        self.max_pending_lines = max_pending_lines  # 积压上限，超出丢弃最旧的 append

    def push(self, kind, payload=None):
        ev = {"kind": kind, "payload": payload}
        n = _payload_lines(ev)
        with self._lock:
            self._events.append(ev)
            if n:
                self._buf_lines += n
            self._trim_locked()

    def take(self, max_n=2000, max_lines=2000):
        """取走事件（最多 max_n 条，且其中日志行总计不超过 max_lines）。

        超量的部分保留在队列里，下一轮再取 —— 既保证单次传输体积可控，
        又不会丢数据（除非积压超过 max_pending_lines）。
        非 logcat 事件不计入行限流，始终会被取走，避免控制类事件被日志淹没。
        """
        with self._lock:
            if not self._events:
                return []
            out = []
            lines = 0
            while self._events:
                ev = self._events[0]
                n = ev.get("_n", 0)
                # 至少返回第一条，保证极端情况下也能推进
                if out and (len(out) >= max_n or (n and lines + n > max_lines)):
                    break
                self._events.popleft()
                out.append(ev)
                lines += n
            self._buf_lines -= lines
            return out

    def clear(self):
        with self._lock:
            self._events.clear()
            self._buf_lines = 0

    def pending_lines(self):
        """当前未取走的日志行数（测试/诊断用）。"""
        with self._lock:
            return self._buf_lines

    # ------------------------------------------------------------------
    def _trim_locked(self):
        """积压超过上限时，从最旧的「数据型」事件开始丢弃（最旧的优先）。

        数据型 = `_payload_lines()` 计了行数的事件：logcat append、command/status
        的输出文本。控制类事件（logcat 的 running/stopped/error、devices、
        console/status 的 clear 等）行数为 0，**永不被裁剪**——避免日志洪水把
        「监控已停止」这类关键事件挤掉。

        注意 status 并非一律免疫：带文本的 status 会计入背压（否则逐行刷状态的
        高产命令会让 deque 无限增长，见 _payload_lines），因此它在极端洪泛下
        可能被裁掉，只有 clear 型 status 才是绝对控制事件。

        实现：只从**队首**弹出、直到行预算回到上限以内，遇到控制类事件先暂存、
        裁剪结束后按原顺序放回队首。旧实现每次都把整个 deque 重建一遍（kept
        deque + 全量 popleft），而背压恰恰在「推送速度超过前端轮询」时持续触发
        —— 于是每一次 push 都变成 O(积压条数) 且全程持锁，GIL 被大量占用，
        take_events 被拖慢，界面反而更卡。现在只为「真正丢弃的前缀」付出代价。
        """
        if self._buf_lines <= self.max_pending_lines:
            return
        dropped = 0
        carry = []          # 被跃过的控制类事件，保持原有先后顺序
        while self._events and self._buf_lines - dropped > self.max_pending_lines:
            ev = self._events.popleft()
            n = ev.get("_n", 0)
            if n:
                dropped += n          # 丢弃这条 append（最旧的优先）
            else:
                carry.append(ev)      # 控制类事件必须保留
        if carry:
            self._events.extendleft(reversed(carry))
        self._buf_lines -= dropped
