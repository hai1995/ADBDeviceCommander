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

    def __init__(self, output_callback=None, on_dir_change=None):
        self.proc = None
        self.reader = None
        self.out_queue = queue.Queue()
        self.output_callback = output_callback
        # 工作目录变化回调：shell 通过 sentinel|path 机制上报当前 cwd 时触发，
        # 用于 UI 上 cmd 风格 prompt 实时更新。交互式 shell 里 cd 不会经过
        # sentinel，所以只在非交互 run 结束时更新。
        self.on_dir_change = on_dir_change
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
        # 最近一次 run() 失败的原因（人话，供调用方拼进提示）。成功时清空。
        self.last_error = ""
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

    def _emit(self, text, kind="out"):
        """把一行面向用户的文本交给上层：**优先走回调**，没有回调才入队。

        生产环境（backend/controllers/base.py）构造会话时一定传 output_callback，
        out_queue 因此根本没人消费。早前「⏱ 命令执行超过 N 秒」「✗ 写入命令失败」
        这两条关键原因只 push 进队列，等于丢进黑洞：指令台输出戛然而止，界面上
        没有任何解释，用户只能反复重试。凡是要给人看的文本都必须走这里。
        """
        if self.output_callback:
            try:
                self.output_callback(text)
                return
            except Exception:
                pass                          # 回调自身出错则退回队列，不丢消息
        self.out_queue.put((kind, text))

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
                        if path and path != self.current_dir:
                            self.current_dir = path
                            if self.on_dir_change:
                                try:
                                    self.on_dir_change(path)
                                except Exception:
                                    pass
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
                self.last_error = ""
                self.in_interactive_shell = True
                try:
                    self.proc.stdin.write(script + "\n")
                    self.proc.stdin.flush()
                except Exception as ex:
                    self.last_error = "写入命令失败: %s" % ex
                    self._emit("✗ " + self.last_error, "err")
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
            self.last_error = ""
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
                self.last_error = "写入命令失败: %s" % ex
                self._emit("✗ " + self.last_error, "err")
                return False
        # 阶段 2：等 sentinel（不持锁，允许其他 run 接着写）
        deadline = time.time() + timeout if timeout else None
        while not (done.is_set() or self._abort.is_set() or self._eof.is_set()):
            if deadline and time.time() > deadline:
                self.last_error = "命令执行超过 %s 秒，已自动终止" % timeout
                self._emit("⏱ %s。" % self.last_error, "err")
                # timeout 到了：温和中止当前命令，不 kill 整个会话。
                # 发 Ctrl-C 尝试终止 PowerShell 里的当前脚本，会话本身继续存活——
                # 后续命令不需要重新拉起 PowerShell。
                self._abort.set()
                try:
                    self.proc.stdin.write("\x03\n")
                    self.proc.stdin.flush()
                except Exception:
                    pass
                break
            time.sleep(0.05)
        try:
            self._pending.remove((sentinel, done))
        except ValueError:
            pass
        if done.is_set() and not self._abort.is_set():
            return True
        # 失败原因按「最能解释现象的那个」定：超时已在上面记好，别再被覆盖成
        # 笼统的「已停止」——kill() 超时路径同样会置 _abort，顺序敏感。
        if not self.last_error:
            if self._abort.is_set():
                self.last_error = "已被停止"
            elif self._eof.is_set():
                # 会话进程自己没了（powershell 被安全软件杀 / 崩溃 / 内存不足）：
                # 界面上表现为「输出突然结束」，不给原因就完全无从排查。
                self.last_error = "命令会话进程意外结束（已自动重建，可重试）"
            else:
                self.last_error = "未等到命令结束标记"
        return False

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
