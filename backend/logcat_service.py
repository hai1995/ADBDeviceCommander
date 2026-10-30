# -*- coding: utf-8 -*-
"""
backend.logcat_service —— Logcat 实时监控 + 抓取服务（与 UI 无关）。

两套能力，共用 `adb logcat -v threadtime`，差异在「去向」：
  * LogcatMonitor   实时推给前端渲染（按级别/关键字/仅异常过滤，批量事件推送）；
  * LogcatCapture   落盘为本地 txt（单文件一路写到底，可按级别过滤写盘，
                    停止时可选打包 zip）。

事件协议（经 BackendBus 推送，前端 take_events 消费）：
  logcat        {serial, status, lines?, total?, exc?, text?}
                status ∈ append | clear | running | stopped | error
  logcat_capture {serial, status, path?, src?, lines?, size?, text?, packaged?}
                status ∈ running | stopped | zipped | error
                zipped = 用户勾选「结束后打包 zip」，停止时把整份 txt 打包
                packaged（仅 stopped）= 本次已打包，前端不再重复弹完成 toast
"""
import os
import threading
import subprocess
import time
import zipfile

from core.constants import (LOGCAT_DISPLAY_MAX_LPS,
                            LOGCAT_DROP_NOTICE_MIN, LOGCAT_DROP_NOTICE_SEC,
                            adb_popen_kwargs)
from core.logcat import classify_line


def _terminate(proc):
    """尽力终止子进程并回收（terminate + wait），任何异常都不外抛。

    terminate 只发信号，不 wait 会留下僵尸进程句柄；这里的 wait 有超时，
    超时再 kill，保证收尾路径（停止 / 关闭窗口）不会被卡住。
    """
    try:
        proc.terminate()
    except Exception:
        pass
    try:
        proc.wait(timeout=2)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


_BATCH_MAX = 400          # 单次 append 事件最多携带行数
_FLUSH_MS = 0.05          # 批量刷新间隔（秒）


def _logcat_cmd(adb, serial, buffers):
    """构造 `adb -s <serial> logcat -v threadtime [-b <buf>]...` 命令。

    监控（实时渲染）与抓取（落盘）共用同一份构造：两边曾各自抄了一份，
    改格式（如换 -v 参数）时只改一处就会漏掉另一处，且两份行为悄然漂移。
    """
    cmd = [adb, "-s", serial, "logcat", "-v", "threadtime"]
    for b in buffers:
        cmd += ["-b", b]
    return cmd

# 启动爆发期保护：`adb logcat` 不带 -t，启动瞬间会把设备缓冲区里的历史日志
# （动辄上万行）一次性吐出来，前端即便增量渲染也会被这次尖峰打满而卡死。
# 这里在启动后的一小段时间内只保留「最近 N 行」，其余直接丢弃：
# 实时监控场景下那些历史日志用户根本看不过来，却足以摧毁交互体验。
BOOT_WINDOW_SEC = 1.0     # 启动后多久视为历史 dump 爆发期
BOOT_KEEP_LINES = 500     # 爆发期内最多保留（推送）的行数，超出的丢弃


class LogcatMonitor:
    """实时 logcat 监控：按设备启动/停止，过滤后批量推送分类行。"""

    def __init__(self, bus, adb_path="adb"):
        self.bus = bus
        self.adb_path = adb_path
        self._lock = threading.Lock()
        self._running = {}        # serial -> bool
        self._procs = {}          # serial -> Popen
        self._stops = {}          # serial -> Event
        # 已收到 stop() 但 worker 还没把 Popen 登记进 _procs 的 serial（启动瞬间）。
        # 缺了它就存在一个「点停止没反应」的窗口：start() 先公开 _stops，worker 要等
        # Popen 返回后才公开 _procs，这段窗口内 stop() 只置 Event、拿不到 proc，
        # 而 worker 随后注册进程、推 running，并阻塞在 `for raw in proc.stdout` 上
        # —— 只有读到下一行才会检查 stop_ev，设备安静时永远读不到，监控既停不掉
        # 又拒绝再次 start（already_running）。LogcatCapture 早有同等机制。
        self._stopreq = set()

    # ------------------------------------------------------------------
    def is_running(self, serial):
        with self._lock:
            return bool(self._running.get(serial))

    def running_serials(self):
        """当前正在监控的设备序列号（供「设备移除后强停孤儿监控」使用）。"""
        with self._lock:
            return [s for s, v in self._running.items() if v]

    def start(self, serial, buffers, level_filter=None, keyword="",
              only_exc=False):
        """启动监控。level_filter 为允许级别集合（默认 VDIWEF 全开）。
        返回 True 表示新启动；已在跑返回 False。

        注意用 `is None` 而不是 `or`：前端在用户取消勾选**全部**级别时传的是
        空列表 `[]`，而 `[] or "VDIWEF"` 会回退成「全开」——用户明明关掉了所有
        级别，后端却仍把每一行都收进来（白跑一趟，且与前端空视图 + 计数对不上）。
        """
        with self._lock:
            if self._running.get(serial):
                return False
            self._running[serial] = True
            stop_ev = threading.Event()
            self._stops[serial] = stop_ev
            self._stopreq.discard(serial)
        levels = set("VDIWEF") if level_filter is None else set(level_filter)
        threading.Thread(
            target=self._worker,
            args=(serial, list(buffers or ["main"]),
                  levels, (keyword or "").lower(),
                  bool(only_exc), stop_ev),
            daemon=True, name="logcat-mon-%s" % serial).start()
        return True

    def stop(self, serial):
        with self._lock:
            ev = self._stops.get(serial)
            proc = self._procs.get(serial)
            # 记下「已请求停止」：worker 若还没注册进程，注册后据此立刻收尾，
            # 不会出现「stop 找不到 proc → 监控停不下来」的窗口。
            if ev is not None or proc is not None:
                self._stopreq.add(serial)
        if ev is not None:
            ev.set()
        # 只置 Event 不够：worker 卡在 `for raw in proc.stdout` 上（adb 无输出时
        # 一直阻塞），读不到下一行就永远检查不到 stop_ev —— 表现为「点了停止
        # 没反应」、`adb logcat` 子进程残留、再次 start 被判 already_running。
        # 故这里主动终止子进程，把阻塞的读循环放出来。
        if proc is not None:
            _terminate(proc)
        return bool(ev is not None or proc is not None)

    def stop_all(self):
        with self._lock:
            evs = list(self._stops.values())
            procs = list(self._procs.values())
            self._stopreq.update(self._stops.keys())
            self._stopreq.update(self._procs.keys())
        for ev in evs:
            ev.set()
        for proc in procs:
            _terminate(proc)

    # ------------------------------------------------------------------
    def _worker(self, serial, buffers, levels, keyword, only_exc, stop_ev):
        adb = self.adb_path
        cmd = _logcat_cmd(adb, serial, buffers)
        total = exc = 0
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                **adb_popen_kwargs())
        except Exception as e:
            with self._lock:
                self._running.pop(serial, None)
                self._stops.pop(serial, None)
                self._stopreq.discard(serial)
            self.bus.push("logcat",
                          {"serial": serial, "status": "error",
                           "text": "启动 logcat 失败：%s" % e})
            return
        with self._lock:
            self._procs[serial] = proc
            # 注册期间就被点了停止：读循环还没开始，stop() 当时拿不到 proc，
            # 这里补一次终止，让下面的 `for raw in proc.stdout` 立即结束。
            stop_now = serial in self._stopreq
        if stop_now:
            stop_ev.set()
            _terminate(proc)
        self.bus.push("logcat",
                      {"serial": serial, "status": "running",
                       "buffers": buffers})
        batch, last = [], time.time()
        # 启动爆发期：先用定长窗口接住历史 dump，只留最近的若干行
        t0 = time.time()
        boot_buf = []
        boot_dropped = 0
        in_boot = True
        # 展示行数软上限（滑动 1s 窗口）：设备日志洪流下从源头节流。没有它时，
        # 总线背压只保证「不丢控制事件」，主线程仍会被持续的高速 JSON 传输 +
        # 分帧渲染占满 —— 一开始监控整个程序就卡顿（用户实报）。
        win_start, win_pushed = t0, 0
        dropped, noticed, last_notice = 0, 0, 0.0
        try:
            for raw in proc.stdout:
                if stop_ev.is_set():
                    break
                item = self._classify_and_filter(raw, levels, keyword, only_exc)
                if item is None:
                    continue
                if item.get("exc"):
                    exc += 1
                total += 1

                if in_boot:
                    boot_buf.append(item)
                    if len(boot_buf) > BOOT_KEEP_LINES:
                        boot_buf.pop(0)
                        boot_dropped += 1
                    if time.time() - t0 < BOOT_WINDOW_SEC:
                        continue
                    # 爆发期结束：把攒下的最近若干行作为第一批推给前端
                    in_boot = False
                    if boot_buf:
                        self.bus.push("logcat",
                                      {"serial": serial, "status": "append",
                                       "lines": boot_buf, "total": total, "exc": exc})
                        boot_buf = []
                    if boot_dropped:
                        self.bus.push(
                            "status",
                            {"type": "info",
                             "text": "已跳过 %d 行历史日志（仅保留最近 %d 行）"
                                     % (boot_dropped, BOOT_KEEP_LINES)})
                    batch, last = [], time.time()
                    continue

                # ---- 展示行数软上限（滑动 1s 窗口）----
                # total/exc 仍按「收到的全部过滤行」计数（与启动爆发期丢弃历史
                # 日志的语义一致：计数反映设备侧活动量，视图是节流后的样本，
                # 丢弃量由状态栏提示补偿）。
                now = time.time()
                if now - win_start >= 1.0:
                    win_start, win_pushed = now, 0
                if win_pushed >= LOGCAT_DISPLAY_MAX_LPS:
                    dropped += 1
                    # 提示本身也要节流：每 LOGCAT_DROP_NOTICE_SEC 秒最多一条，
                    # 且两次提示间至少又攒了 LOGCAT_DROP_NOTICE_MIN 行丢弃
                    if (dropped - noticed >= LOGCAT_DROP_NOTICE_MIN
                            and now - last_notice >= LOGCAT_DROP_NOTICE_SEC):
                        noticed, last_notice = dropped, now
                        self.bus.push(
                            "status",
                            {"type": "warn",
                             "text": "日志流量过高：已丢弃约 %d 行"
                                     "（实时监控限速 %d 行/秒，保证界面流畅；"
                                     "需要全量请用「抓取」落盘）"
                                     % (dropped, LOGCAT_DISPLAY_MAX_LPS)})
                    continue
                win_pushed += 1

                batch.append(item)
                if len(batch) >= _BATCH_MAX or now - last >= _FLUSH_MS:
                    self.bus.push("logcat",
                                  {"serial": serial, "status": "append",
                                   "lines": batch, "total": total, "exc": exc})
                    batch, last = [], now
        finally:
            if in_boot and boot_buf:
                # 爆发期内就结束了：仍然把攒下的行推给前端，不吞数据
                batch = boot_buf
            if batch:
                self.bus.push("logcat",
                              {"serial": serial, "status": "append",
                               "lines": batch, "total": total, "exc": exc})
            # 收尾补报「还没提示过」的丢弃量：行数计数含被限速丢弃的部分，
            # 视图里看不到它们，这里给个可解释的闭环（每次停止最多一条）。
            if dropped > noticed:
                self.bus.push(
                    "status",
                    {"type": "warn",
                     "text": "监控结束：本次限速丢弃约 %d 行"
                             "（实时监控限速 %d 行/秒）"
                             % (dropped - noticed, LOGCAT_DISPLAY_MAX_LPS)})
            _terminate(proc)
            with self._lock:
                self._running.pop(serial, None)
                self._procs.pop(serial, None)
                self._stops.pop(serial, None)
                self._stopreq.discard(serial)
            self.bus.push("logcat",
                          {"serial": serial, "status": "stopped",
                           "total": total, "exc": exc})

    @staticmethod
    def _classify_and_filter(raw, levels, keyword, only_exc):
        rec = classify_line(raw)
        if rec is None:
            # 非 threadtime 行（标题/分隔/空行）原样保留给前端做纯文本渲染
            return {"raw": (raw or "").rstrip("\n")}
        if rec["level"] not in levels:
            return None
        if only_exc and not rec["exc"]:
            return None
        if keyword:
            # 关键字与内容都统一小写后再比对：用户随手输入 "FATAL" / "Fatal"
            # 也要能命中（此前只有全小写才命中，等于过滤「时灵时不灵」）。
            kw = str(keyword).lower()
            hay = ((rec["msg"] or "") + " " + (rec["tag"] or "")).lower()
            if kw not in hay:
                return None
        return rec


class LogcatCapture:
    """Logcat 抓取：落盘为本地 txt（单文件一路写到底），停止时可按需打包 zip。

    唯一打包开关是 zip_on_stop（stop()，前端「结束后打包 zip」，默认开）：
    用户点「停止抓取」时把整份 txt 打包成 zip（源 txt 清理）。抓取过程中
    没有任何按大小触发的自动动作——旧实现的「超 15M 自动打包」已按用户
    要求整体移除，长抓取不再被任何阈值打断。
    """

    def __init__(self, bus, adb_path="adb"):
        self.bus = bus
        self.adb_path = adb_path
        self._lock = threading.Lock()
        self._procs = {}          # serial -> Popen
        self._files = {}          # serial -> path
        # serial -> {"zip_on_stop": bool}
        self._flags = {}
        # 已 start() 但 worker 还没把 Popen 登记进 _procs 的 serial（启动瞬间）
        self._starting = set()
        # 已收到 stop() 的 serial：worker 启动完成时据此立刻收尾，避免「启动后
        # 马上点停止」时 stop 找不到 proc 而返回 False、抓取线程再也停不掉。
        self._stopreq = set()

    def is_running(self, serial):
        with self._lock:
            return serial in self._procs or serial in self._starting

    def running_serials(self):
        """当前正在抓取的设备序列号（供「设备移除后强停孤儿抓取」使用）。"""
        with self._lock:
            return list(set(self._procs.keys()) | self._starting)

    def start(self, serial, path, buffers, level_filter=None):
        """启动抓取，写入 path（txt，单文件）。返回 True 表示新启动。

        level_filter：允许写盘的日志级别集合（"VDIWEF" 的子集）。
          * None   —— 全级别写入（默认，与旧行为一致）；
          * 空列表 —— 一个级别都不写（用户可在界面上取消全部勾选，
            语义与实时监控一致：`[]` 不是「不过滤」而是「全不要」）；
          * 非 threadtime 行（adb 横幅 / 分隔线 / 空行）不过滤，原样写盘
            （与 LogcatMonitor 对非日志行的处理保持同语义）。
        """
        with self._lock:
            if serial in self._procs or serial in self._starting:
                return False
            self._files[serial] = path
            self._flags[serial] = {"zip_on_stop": False}
            self._stopreq.discard(serial)
            self._starting.add(serial)
        # 用 `is None` 而非 `or`：前端取消勾选全部级别时传的是空列表 []，
        # `[] or set("VDIWEF")` 会回退成全开 —— 用户明明关掉了所有级别，
        # 文件里却照样写了一切（与实时监控的既有语义相悖）。
        levels = None if level_filter is None else set(level_filter)
        threading.Thread(
            target=self._worker,
            args=(serial, path, list(buffers or ["main"]), levels),
            daemon=True, name="logcat-cap-%s" % serial).start()
        return True

    def stop(self, serial, zip_on_stop=True):
        """停止抓取。zip_on_stop 置位后，worker 收尾时会据此打包末段。"""
        with self._lock:
            proc = self._procs.get(serial)
            if proc is None and serial not in self._starting:
                return False
            self._stopreq.add(serial)
            if serial in self._flags:
                # 关键：把「停止时是否打包」写进 flags，让 worker 的 finally 据此决策。
                # 旧实现把该参数读到 local 变量后丢弃，导致「结束后打包 zip」完全失效。
                self._flags[serial]["zip_on_stop"] = bool(zip_on_stop)
        if proc is not None:
            _terminate(proc)
        # 收尾由 _worker finally 统一处理（决定是否打包末段）
        return True

    def stop_all(self, zip_on_stop=True):
        with self._lock:
            serials = list(self._procs.keys()) + list(self._starting)
        for s in serials:
            self.stop(s, zip_on_stop=zip_on_stop)

    # ------------------------------------------------------------------
    def _worker(self, serial, path, buffers, levels=None):
        adb = self.adb_path
        cmd = _logcat_cmd(adb, serial, buffers)
        lines = 0
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                **adb_popen_kwargs())
        except Exception as e:
            self.bus.push("logcat_capture",
                          {"serial": serial, "status": "error",
                           "text": "启动抓取失败：%s" % e})
            with self._lock:
                self._starting.discard(serial)
                self._stopreq.discard(serial)
            return
        with self._lock:
            self._starting.discard(serial)
            stop_now = serial in self._stopreq
            self._procs[serial] = proc
        # 启动期间就被点停止：立刻收尾，不要开始写文件
        if stop_now:
            _terminate(proc)
        self.bus.push("logcat_capture",
                      {"serial": serial, "status": "running", "path": path})
        # f 必须先初始化再进 try：open() 失败（保存目录被删 / 磁盘掉线 / 只读）时
        # 旧实现让 finally 里去读未绑定的 f，直接抛 UnboundLocalError —— finally 随之
        # 中断，_procs/_starting/_stopreq/_flags 全部没清理、子进程也没 terminate：
        # 抓取永远卡在「运行中」（is_running 恒 True、再 start 判 already_running、
        # 用户点停止也停不掉），并泄漏一个 adb logcat 进程。
        f = None
        try:
            f = open(path, "w", encoding="utf-8", errors="replace")
            for raw in proc.stdout:
                # 级别过滤（与实时监控同语义）：能识别出级别的行按用户勾选
                # 的集合过滤；识别不出的行（标题/分隔线）原样写盘。
                if levels is not None:
                    rec = classify_line(raw)
                    if rec is not None and rec["level"] not in levels:
                        continue
                f.write(raw)
                lines += 1
        except Exception as e:
            self.bus.push("logcat_capture",
                          {"serial": serial, "status": "error",
                           "text": "抓取异常：%s" % e})
        finally:
            # 子进程收尾放在最前面：读循环正常结束（EOF）/ 写盘异常中断 / 文件根本
            # 没打开成功，三条路径都必须确保 adb logcat 被终止——旧实现只在正常
            # EOF 后 terminate，另两条路径都会留下一个一直挂着的 adb 进程。
            # terminate+wait 幂等：对已退出的进程是空操作，重复调用无副作用。
            _terminate(proc)
            # 再关文件句柄（之后才打包/量大小）：Windows 上开着的句柄会让 zip 失败
            if f is not None:
                try:
                    f.close()
                except Exception:
                    pass
            with self._lock:
                self._procs.pop(serial, None)
                self._starting.discard(serial)
                self._stopreq.discard(serial)
                flags = self._flags.pop(serial, {"zip_on_stop": False})
            # 打包条件：仅「结束后打包 zip」——抓取过程不做任何按大小的自动
            # 打包（旧「超 15M 自动打包」已整体移除），因此停止时是否打包
            # 完全由用户在界面上勾选的这一个开关决定。
            do_zip = bool(flags.get("zip_on_stop"))
            zpath = None
            if do_zip and os.path.exists(path) and os.path.getsize(path) > 0:
                zpath = self._zip_one(path)
                if zpath:
                    self.bus.push("logcat_capture",
                                  {"serial": serial, "status": "zipped",
                                   "path": zpath, "src": path,
                                   "text": "已打包：%s" % zpath})
            # size 语义：打了包就报 zip 的大小（源 txt 已清理），否则报 txt 大小
            if zpath and os.path.exists(zpath):
                size_out = os.path.getsize(zpath)
            elif os.path.exists(path):
                size_out = os.path.getsize(path)
            else:
                size_out = 0
            self.bus.push("logcat_capture",
                          {"serial": serial, "status": "stopped",
                           "path": path, "lines": lines, "size": size_out,
                           # 打了包：zipped 事件已另行通知「已打包」，
                           # stopped 不再重复弹完成 toast（前端据此二选一）。
                           "packaged": bool(zpath)})

    @staticmethod
    def _zip_one(path):
        """把单个 txt 打包为同名 .zip，成功后清理源 txt（避免重复占磁盘）。

        只在 zip 完整写出后才删除源文件；删除失败不阻断（zip 已可用，下轮
        或手工清理即可），且 zip 失败时绝不删源。
        """
        zpath = path + ".zip"
        try:
            if os.path.exists(zpath):
                os.remove(zpath)
            with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
                z.write(path, os.path.basename(path))
        except Exception:
            try:
                if os.path.exists(zpath):
                    os.remove(zpath)
            except Exception:
                pass
            return None
        try:
            os.remove(path)
        except Exception:
            pass
        return zpath
