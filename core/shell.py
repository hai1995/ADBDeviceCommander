# -*- coding: utf-8 -*-
"""
core.shell —— 持久 PowerShell 会话（ShellSession）。
与 旧 Tk 版（已移除） 中的 ShellSession 同源；不依赖任何 UI。
"""
import os
import sys
import queue
import time
import uuid
import threading
import subprocess


def _kill_tree(proc):
    """终止整个进程树；返回 True 表示已交给系统处理。

    Windows 的 `TerminateProcess`（即 `proc.terminate()`）只杀外层 powershell：
    交互式子 shell 拉起的内层 powershell 会变成孤儿，继续持有 stdout 管道，
    读线程因此永远等不到 EOF，线程与句柄一起泄漏。`taskkill /T` 连子进程收。
    """
    pid = getattr(proc, "pid", None)
    if not pid or not sys.platform.startswith("win"):
        return False
    try:
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(pid)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True
    except Exception:
        return False


class ShellSession:
    """维护一个长期存活的 powershell 进程，向其 stdin 写入命令并捕获输出。
    用 sentinel 标记判断一条命令是否执行完毕；支持终止（停止）当前命令。"""

    # 会话程序的启动参数 / 一次性初始化脚本，提成方法便于单测替换成 sh
    # （Linux 上没有 powershell，但「裸子 shell 抢 stdin」的机制完全一样）。
    @staticmethod
    def _shell_args():
        return ["powershell", "-NoProfile", "-NoLogo", "-Command", "-"]

    @staticmethod
    def _init_script():
        return "$ProgressPreference='SilentlyContinue';"

    @staticmethod
    def _sentinel_stmt(tag):
        """输出结束标记的语句（不含换行）。

        末尾拼上当前路径，供 Python 侧维护 CMD 风格提示符（`<路径>> 命令`）。
        提成方法是为了单测能换成 sh 的写法：Linux 上没有 powershell，但
        「裸子 shell 抢 stdin」的机制完全一样，可以真实复现卡死。
        """
        return 'Write-Output ("%s|" + (Get-Location).Path)' % tag

    def __init__(self, output_callback=None):
        self.proc = None
        self.reader = None
        self.out_queue = queue.Queue()
        self.output_callback = output_callback
        # 每个 run 注册一条 (sentinel, done_event)；reader 命中即 set event
        # 并跳过渲染。run 等自己的 event，sentinel 互不干扰。
        self._pending = []
        self._eof = threading.Event()
        self._abort = threading.Event()
        self._lock = threading.Lock()
        # 是否处于交互式子 shell（如 adb shell）中；kill/_start 后重置
        self.in_interactive_shell = False
        # 当前工作目录（CMD 风格提示符用）。每条非交互命令结束后由 sentinel 行带回。
        self.current_dir = os.getcwd()
        self._start()

    def _start(self):
        args = self._shell_args()
        cf = 0
        if sys.platform.startswith("win"):
            cf = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        # text=True 但不指定 encoding：Python 会按系统默认编码（中文 Windows 为 GBK）
        # 解码 PowerShell 输出，与 PowerShell 实际使用的控制台编码保持一致，
        # 避免我们强制 UTF-8 后两边编码不匹配导致乱码或输出被吞。
        self.proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            bufsize=1,
            creationflags=cf,
            env=os.environ.copy(),
        )
        self._eof.clear()
        self._abort.clear()
        self._pending = []
        self.in_interactive_shell = False
        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.reader.start()
        # 会话级 init（一次性）：只关闭进度条。
        # 必须放在 _start 而不是每次 run 的 payload 前缀，否则 `adb shell` 进入
        # 交互后，PowerShell 会把 init 喂给 adb shell 报 command not found。
        init_script = self._init_script()
        init_tag = "__INIT_DONE_%s__" % uuid.uuid4().hex
        init_ev = threading.Event()
        self._pending.append((init_tag, init_ev))
        try:
            # sentinel 后面拼上当前路径，供 Python 侧维护 CMD 风格提示符
            self.proc.stdin.write(
                init_script + '\n' + self._sentinel_stmt(init_tag) + '\n')
            self.proc.stdin.flush()
        except Exception:
            pass
        # 同步等 init 完成（最多 3s，避免卡住 GUI 启动）
        init_ev.wait(timeout=3.0)
        try:
            self._pending.remove((init_tag, init_ev))
        except ValueError:
            pass

    def _read_loop(self):
        # 固定住本 reader 对应的进程：kill() 会终止进程并让 _start() 重建会话，
        # 而旧 reader 线程要等旧 stdout 真正 EOF 才会退出（有延迟）。若它退出时
        # 无条件置 _eof，就会把**刚重建的新会话**误判成已结束——表现为「点了停止
        # 之后，下一条命令立刻返回 False」。故只有「仍是当前进程」才允许置 EOF。
        proc = self.proc
        try:
            for line in proc.stdout:
                text = line.rstrip("\n")
                t = text.strip()
                # 检查是否匹配任何 pending sentinel（每个 run 独立）
                # sentinel 可能带 "|当前路径" 后缀，用于刷新提示符
                matched_ev = None
                for s, ev in list(self._pending):
                    if t == s:
                        matched_ev = ev
                        break
                    if t.startswith(s + "|"):
                        matched_ev = ev
                        path = t[len(s) + 1:].strip()
                        if path:
                            self.current_dir = path
                        break
                if matched_ev is not None:
                    matched_ev.set()
                    continue   # sentinel 行不渲染
                # 正常输出：有 callback 走 callback，否则入队
                if self.output_callback:
                    try:
                        self.output_callback(text)
                    except Exception:
                        pass
                else:
                    self.out_queue.put(("out", text))
        except Exception:
            pass
        if self.proc is not proc:
            return          # 已被 kill 并重建：旧 reader 不得污染新会话状态
        self.out_queue.put(("eof", ""))
        self._eof.set()

    def run(self, script: str, timeout=None, interactive: bool = False):
        """
        执行一段 powershell 脚本，阻塞直到 sentinel 出现 / 被中止 / 会话结束 / 超时。
        返回 True 表示正常结束，False 表示超时或被中止。
        timeout 为 None 时不主动超时（适用于 while、adb logcat 等长期运行命令）。

        interactive=True：进入交互式子 shell（如 adb shell）后使用，
        不写 sentinel、不等待结束，直接写入 stdin 并立即返回。
        """
        # ---- 交互式直通：不写 sentinel，不等待，直接推给 stdin ----
        if interactive:
            with self._lock:
                if self.proc.poll() is not None:
                    self._start()
                self._eof.clear()
                self._abort.clear()
                self.in_interactive_shell = True
                try:
                    self.proc.stdin.write(script + "\n")
                    self.proc.stdin.flush()
                except Exception as ex:
                    self.out_queue.put(("err", "✗ 写入命令失败: %s" % ex))
                    return False
            return True

        # ---- 非交互式：带 sentinel 结束标记 ----
        sentinel = "__DONE_%s__" % uuid.uuid4().hex
        done = threading.Event()
        # 阶段 1：写命令（持锁，避免 stdin 交错）
        with self._lock:
            if self.proc.poll() is not None:
                self._start()
            self._eof.clear()
            self._abort.clear()
            self._pending.append((sentinel, done))
            # sentinel 后拼上执行完命令后的当前路径，用于刷新提示符
            payload = script + '\n' + self._sentinel_stmt(sentinel) + '\n'
            try:
                self.proc.stdin.write(payload)
                self.proc.stdin.flush()
            except Exception as ex:
                try:
                    self._pending.remove((sentinel, done))
                except ValueError:
                    pass
                self.out_queue.put(("err", "✗ 写入命令失败: %s" % ex))
                return False
        # 阶段 2：等 sentinel（不持锁，允许其他 run 接着写）
        deadline = time.time() + timeout if timeout else None
        while not (done.is_set() or self._abort.is_set() or self._eof.is_set()):
            if deadline and time.time() > deadline:
                self.out_queue.put(("err", "⏱ 命令执行超过 %s 秒，已自动终止。" % timeout))
                self.kill()
                break
            time.sleep(0.05)
        try:
            self._pending.remove((sentinel, done))
        except ValueError:
            pass
        return done.is_set() and not self._abort.is_set()

    @property
    def aborted(self):
        """是否收到过 kill/中止信号。

        供 Python 侧长延时等待（如命令间 delay）轮询：kill() 会把 _abort 置位
        并保持到下一次 run 才清除，从而让等待中的代码及时让出。
        """
        return self._abort.is_set()

    def leave_interactive(self):
        """退出交互式子 shell 后复位直通状态。

        直通模式下 `run()` 只写 stdin、不写结束标记（否则 `adb shell` 会把标记
        当设备端命令执行）。但序列里的 `exit` 只是退出内层子 shell，外层会话
        仍然活着——不复位的话，之后每条命令都按直通发，既拿不到输出边界，也
        无法判断失败，等于把会话永久降级成"盲写"。
        """
        self.in_interactive_shell = False

    def kill(self):
        """中止当前正在执行的命令（终止整个 powershell 会话，下次自动重连）。"""
        self._abort.set()
        self.in_interactive_shell = False
        # 取锁只为「拿到确定的 proc 引用 + 写完中断字节」这一步，避免与 run() 阶段 1
        # （持锁写 stdin）交错：否则用户点「停止」时，\x03 可能插进一条正在写入的
        # 命令中间；同时也能防止 _start() 换掉 self.proc 后，我们终止的是新会话。
        # 注意 wait() 必须在锁外做——run() 超时路径也会调 kill()，持锁等待会拖住
        # 其它 run 的重启。
        with self._lock:
            proc = self.proc
            try:
                proc.stdin.write("\x03\n")
                proc.stdin.flush()
            except Exception:
                pass
        # 先按进程树杀（Windows）：交互式子 shell 的内层进程只 terminate 外层
        # 是收不掉的，它会继续持着 stdout 管道让读线程永远等不到 EOF。
        if not _kill_tree(proc):
            try:
                proc.terminate()
            except Exception:
                pass
        # 同步等待退出，避免下次 run 写命令时进程还在关闭中（消除原 Timer 竞态）
        try:
            proc.wait(timeout=2.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
