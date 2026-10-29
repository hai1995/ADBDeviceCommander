# -*- coding: utf-8 -*-
"""
backend.workers —— 后台工作线程管理（去重 / 记档 / 优雅关闭）
================================================================
统一收口所有 `threading.Thread(...).start()` 的调用，避免散落各处的裸线程：
  * 命名任务（key 非空）：同一 key 已有存活线程时不再重复启动（防叠加），
    常用于设备刷新、自动轮询这类“同时只允许一份”的任务；
  * 匿名任务（key 为 None）：每次调用都新建线程，用于用户触发的多条命令
    并发排队执行（stdin 由 ShellSession 内部锁串行化）；
  * shutdown()：窗口关闭时置标记并等待所有线程收尾，幂等可重入。
"""
import threading
import time


class Workers:
    def __init__(self):
        self._lock = threading.Lock()
        self._named = {}    # key -> Thread（去重用）
        self._anon = []     # [Thread]（匿名任务记档，等待关闭用）

    def spawn(self, key, fn, *args, **kwargs):
        """启动一个 daemon 线程。返回实际生效的 Thread。

        key 非空且同名线程存活时直接返回已有线程（不重复启动）；
        key 为 None 时总是新建。args / kwargs 透传给 fn。
        每次 spawn 会顺带回收已结束线程的引用（防长会话内存微增）。
        """
        with self._lock:
            self._gc_locked()
            if key is not None:
                cur = self._named.get(key)
                if cur is not None and cur.is_alive():
                    return cur
            t = threading.Thread(
                target=fn, args=args, kwargs=kwargs,
                daemon=True, name=key or "worker")
            if key is not None:
                self._named[key] = t
            else:
                self._anon.append(t)
            t.start()
            return t

    def _gc_locked(self):
        """回收已结束线程的引用（须在持有 _lock 时调用）。

        匿名任务大量产生（用户一条命令一个线程），长期运行若不回收，
        _anon 会累积成千上万个已结束 Thread 对象的引用。
        """
        self._anon = [t for t in self._anon if t.is_alive()]
        for k in [k for k, t in self._named.items() if not t.is_alive()]:
            del self._named[k]

    def is_running(self, key=None):
        """key 为空时表示“是否存在任意存活工作线程”。"""
        with self._lock:
            if key is not None:
                cur = self._named.get(key)
                return bool(cur and cur.is_alive())
            return self._any_alive_locked()

    def _any_alive_locked(self):
        for t in list(self._named.values()) + list(self._anon):
            if t.is_alive():
                return True
        return False

    def running_keys(self):
        """返回当前存活的命名任务 key 列表（调试 / 对账用）。"""
        with self._lock:
            return [k for k, t in self._named.items() if t.is_alive()]

    def alive_count(self):
        with self._lock:
            return sum(1 for t in list(self._named.values()) + list(self._anon)
                       if t.is_alive())

    def shutdown(self, timeout=3.0):
        """等待所有工作线程在给定时间内自然收尾。

        线程均为 daemon，不会阻止进程退出；此方法用于在关闭前给
        “自动轮询 / 命令执行”一个优雅停止的机会（超时即放弃等待）。
        """
        with self._lock:
            targets = list(self._named.values()) + list(self._anon)
        deadline = time.time() + timeout
        for t in targets:
            if not t.is_alive():
                continue
            remain = deadline - time.time()
            if remain <= 0:
                break
            t.join(min(remain, 0.5))
        return self.alive_count()
