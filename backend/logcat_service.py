"""
backend.logcat_service —— Logcat 实时监控 + 抓取服务（与 UI 无关）。

两套能力，共用 `adb logcat -v threadtime`，差异在「去向」：
  * LogcatMonitor   实时推给前端渲染（按级别/关键字/仅异常过滤，批量事件推送）；
  * LogcatCapture   落盘为本地 txt（单文件一路写到底，可按级别过滤写盘，
                    停止时可选打包 zip）。设备掉线、或设备仍在线而 `adb logcat`
                    被外力打断，都会**自动重连/重启并续写同一文件**，断点与缺失
                    时段以 `[logcat]` 标记行写入文件 —— 录屏配套的日志是事后按
                    时间轴复现问题的唯一物证，绝不能悄悄停在半路。

事件协议（经 BackendBus 推送，前端 take_events 消费）：
  logcat        {serial, status, lines?, total?, exc?, text?}
                status ∈ append | clear | running | stopped | error
  logcat_capture {serial, status, path?, src?, lines?, size?, text?, packaged?}
                status ∈ running | stopped | zipped | error
                zipped = 用户勾选「结束后打包 zip」，停止时把整份 txt 打包
                packaged（仅 stopped）= 本次已打包，前端不再重复弹完成 toast
"""
import os
import queue
import threading
import subprocess
import time
import zipfile

from core.constants import (LOGCAT_DISPLAY_MAX_LPS,
                            LOGCAT_DROP_NOTICE_MIN, LOGCAT_DROP_NOTICE_SEC,
                            LOGCAT_CAP_RECONNECT_MAX_S, LOGCAT_CAP_RECONNECT_POLL_S,
                            LOGCAT_CAP_RESTART_MAX, LOGCAT_CAP_RESTART_NO_PROGRESS,
                            LOGCAT_CAP_RESTART_BACKOFF_S,
                            LOGCAT_CAP_RESTART_BACKOFF_MAX_S,
                            LOGCAT_CAP_HOLE_WARN_S, LOGCAT_CAP_REPLAY_SKIP_MAX,
                            LOGCAT_CAP_REBOOT_UPTIME_SLACK_S, adb_kwargs,
                            adb_popen_kwargs)
from core.logcat import (classify_line, match_filter, split_filter_terms,
                         ts_epoch, ts_prefix as _ts_prefix)
from backend.screen_service import device_present


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
# 读线程与消费线程之间的行队列上限。必须**有界**：无界队列会让读线程把 adb
# 管道抽干（旧实现里消费与读在同一线程，管道满了自然反压到 adb 与设备端，
# 日志洪流不会在本进程堆内存）。有界队列 + 阻塞 put 把这份背压原样保留，
# 同时仍能让消费循环按 _FLUSH_MS 限时等待、按时刷新残批。5000 行 ≈ 数百 KB
# 到 1MB，足够吸收启动爆发期的抖动。
_QUEUE_MAX = 5000

# 读线程队列的结束哨兵：看到它说明 adb 的输出已到 EOF（或读线程异常退出），
# 消费循环据此收尾，而不是继续等下去。
_LOGCAT_EOF = object()


def _write_marker(f, text):
    """往抓取文件里写一条 「--------- [logcat] xxx ---------」分隔标记。

    写不进去也不外抛：标记只是给人看的，它失败不该把整场抓取带崩。
    返回是否写成功（调用方据此决定要不要把 gap 标记算数）。
    """
    try:
        f.write("\n--------- [logcat] %s ---------\n" % text)
        f.flush()
        return True
    except Exception:
        return False


def _device_uptime(adb, serial):
    """设备开机时长（秒），取不到返回 None。

    `/proc/uptime` 是**开机时长**，与系统墙上时钟无关 —— 车机重启后时间没校时
    也照样准。抓取据此判断「设备在本次录制期间有没有重启过」：重启过就说明
    logcat 缓冲区已清空，重连时不存在「缓冲区重放」，时间戳倒退只能是时钟问题。
    """
    try:
        r = subprocess.run(
            [adb, "-s", serial, "shell", "cat", "/proc/uptime"],
            **adb_kwargs(5))
    except Exception:
        return None
    if r.returncode != 0:
        return None
    try:
        return float((r.stdout or "").split()[0])
    except Exception:
        return None


def _now_mono():
    """抓取流程里的单调时钟（单独抽出来，方便单测把「录制已进行时长」打桩）。"""
    return time.monotonic()


# pkg: 过滤的 pid 刷新间隔（秒）。应用被杀掉重开 pid 就变了，但用户要的
# 语义是「一直只看这个包」，所以按固定间隔静默重解析。5s 足够灵敏，
# 又不至于为每条日志起 adb 子进程。
PKG_PID_REFRESH_S = 5.0


def pkg_pids_of(adb, serial, package, timeout=6):
    """把包名解析成当前进程 pid 集合（字符串集合）；解析不到返回 set()。

    两条路径：
      * `pidof <包名>`：Android 6+ 的 toybox 有；一次就能拿到多进程。
      * `ps -A` / `ps`：老车机常没有 pidof，逐行找末列的进程名等于包名的行。
    宁可返回空集也**不要**返回 None：调用方据此判定「pkg: 不命中任何行」，
    与「没有过滤条件」是两种截然不同的语义，混用会让过滤静默失效。
    """
    pkg = (package or "").strip()
    if not pkg:
        return set()
    try:
        r = subprocess.run(
            [adb, "-s", serial, "shell", "pidof", pkg],
            **adb_kwargs(timeout))
        out = (r.stdout or "").strip()
        if r.returncode == 0 and out:
            return set(out.split())
    except Exception:
        pass
    # 回落 ps：老系统 / pidof 被裁剪。ps 的输出格式随版本差异极大（toybox
    # 是 `USER PID PPID ... NAME`，busybox 可能首列就是 PID），所以不假设
    # 固定列位——取「最后一个字段 == 包名」的行，再取该行里第一个纯数字字段
    # 当 PID（跳过用户名/状态列，pid 一定是数字）。
    try:
        r = subprocess.run(
            [adb, "-s", serial, "shell", "ps"],
            **adb_kwargs(timeout))
        if r.returncode != 0:
            return set()
        pids = set()
        for line in (r.stdout or "").splitlines():
            parts = line.split()
            if len(parts) < 2 or parts[-1] != pkg:
                continue
            for tok in parts:
                if tok.isdigit():
                    pids.add(tok)
                    break
        return pids
    except Exception:
        return set()


def _logcat_cmd(adb, serial, buffers, from_now_lines=None):
    """构造 `adb -s <serial> logcat -v threadtime [-T <n>] [-b <buf>]...` 命令。

    监控（实时渲染）与抓取（落盘）共用同一份构造：两边曾各自抄了一份，
    改格式（如换 -v 参数）时只改一处就会漏掉另一处，且两份行为悄然漂移。

    from_now_lines：仅**抓取**（落盘）用。传正整数时加 `-T <n>`——logcat 只让
    最近 n 行作为起点，随后实时追加。这是「短录制抓不到日志」的根治点：

    不带 -T 时，每个 adb logcat 进程都会先把设备环形缓冲区**从头**灌一遍。
    车机 `-b all` 的历史缓冲动辄几十 MB，经 ADB 传输要十几秒到几十秒。用户
    只录十几秒就点停止时，缓冲区还没灌到「现在」——文件里全是录制开始**之前**
    的历史日志，录制期间一条都没有；收尾校验再拿「设备当前时刻 - 最后一条
    日志」算缺口，就报出「距录屏结束还有 10 分 49 秒没有日志」这种与录制
    时长完全不成比例的假缺口（用户实报）。

    加 -T 后处于「实时跟流」状态，第一行就落在录制起点附近，录制期间逐行
    追加，既不存在追赶窗口，也不再白写几十 MB 历史。重启 / 重连后的新会话
    同样从当时刻开始，正是「断点之后续写」要的语义。
    """
    cmd = [adb, "-s", serial, "logcat", "-v", "threadtime"]
    if from_now_lines is not None and int(from_now_lines) > 0:
        cmd += ["-T", str(int(from_now_lines))]
    for b in buffers:
        cmd += ["-b", b]
    return cmd


# 抓取起点：`-T 1` = 只取「最近 1 行」当起点，随后实时追加。
# 不用 -T 0（部分 logcat 版本对 0 的解释不一致），1 行也不会多写什么。
LOGCAT_CAP_FROM_NOW_LINES = 1
# -T 是 Android 5.0+ 的 logcat 选项；老车机 / 被裁剪的 logcat 可能不认。
# 不做事前探测（探测要真起进程，反而干扰测试替身与忙碌设备），改为：
# 带上 -T 后若一行日志都没拿到就 EOF，且报错原文指向「选项不认识」，
# 就地回落兼容命令重试一次，并把这台设备记进 _no_T（见 _worker）。

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
            # 注册期间就被点了停止：消费循环还没开始，stop() 当时拿不到 proc，
            # 这里补一次终止，让下面的提前退出检查立即生效。
            stop_now = serial in self._stopreq
        if stop_now:
            stop_ev.set()
            _terminate(proc)
        else:
            # 用户已经点了停止：不要再广播 running。前端收到它会把状态切成
            # 「采集中…」、把「开始监控」锁上，紧接着又被 stopped 拨回来 ——
            # 一次从未成立的状态，白闪一下还多一轮无意义的置位/复位。
            self.bus.push("logcat",
                          {"serial": serial, "status": "running",
                           "buffers": buffers})
        batch, last = [], time.time()
        # 未产出任何日志行时收集到的「非日志行」（adb 的报错正是这个形态：
        # `error: device 'xxx' not found` / `adb: device offline`）。平时它们只是
        # 被原样丢给前端当纯文本；设备掉线时，这是唯一能说清原因的东西。
        err_lines = []
        # 收到的**真日志行数**（不受级别/关键字过滤影响）。判「有没有收到日志」
        # 必须用它：用户把级别全取消勾选、或关键字一个都没命中时，过滤后的行数
        # 天然是 0，拿它当判据就会把正常监控误报成「设备离线」。
        stats = {"seen": 0}
        # pkg: 过滤需要把包名解析成 pid 集合。pid 会随应用重启变化，所以在
        # 消费循环的空闲分支里定期重解析（见下方 pkg_refresh_at）。
        pkg_pids = self._resolve_pkg_pids(serial, keyword)
        pkg_refresh_at = time.time() + (PKG_PID_REFRESH_S if pkg_pids else 0)
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
        q = None                  # 读线程 → 消费线程的行队列（见下方说明）
        try:
            # 读线程 + 限时等待的消费循环。
            #
            # 不能在 worker 线程里直接 `for raw in proc.stdout`：设备安静下来后
            # 这个循环会一直阻塞，而批量推送的「攒够 _BATCH_MAX 行 / 距上次推送
            # 超过 _FLUSH_MS」只在**收到下一行**时才会被检查。于是最后那几条
            # 日志（以及启动爆发期尾部）会一直压在 batch / boot_buf 里，直到
            # 设备再吐一行、或用户点停止才冒出来 —— 用户看到的是「日志停在
            # 半路，一按停止就全出现了」，还会误以为监控挂了。
            # 读线程只负责把 stdout 搬进队列，消费循环用 get(timeout) 等待：
            # 超时即代表「这段时间没有新行」，正好用来按时刷新与收尾爆发期。
            # 单线程消费保证推送顺序与原来完全一致。
            q = queue.Queue(maxsize=_QUEUE_MAX)
            threading.Thread(
                target=self._pump, args=(proc, q),
                daemon=True, name="logcat-pump-%s" % serial).start()

            def _flush_batch(now):
                nonlocal batch, last
                if batch:
                    self.bus.push("logcat",
                                  {"serial": serial, "status": "append",
                                   "lines": batch, "total": total, "exc": exc})
                batch, last = [], now

            def _end_boot(now):
                nonlocal in_boot, boot_buf, batch, last
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
                batch, last = [], now

            while True:
                if stop_ev.is_set():
                    break
                now = time.time()
                # pkg: 的 pid 会随应用重启变化，按墙钟每 PKG_PID_REFRESH_S 重解析。
                # 必须放在循环顶部：早前放在「队列超时（这段没有新日志）」分支里，
                # 日志持续不断时那个分支永远进不去，pid 就一直停在启动时那一份 ——
                # 应用重启后按包过滤突然「一行都没有」，而界面看不出任何原因。
                if pkg_refresh_at and now >= pkg_refresh_at:
                    pkg_pids = self._resolve_pkg_pids(serial, keyword)
                    pkg_refresh_at = time.time() + PKG_PID_REFRESH_S
                try:
                    raw = q.get(timeout=_FLUSH_MS)
                except queue.Empty:
                    # 这段时间没有新日志：把攒下的行按时推出去（爆发期则按时
                    # 结束，避免尾部历史行等不到「下一行」而滞留）。
                    now = time.time()
                    if in_boot:
                        if now - t0 >= BOOT_WINDOW_SEC:
                            _end_boot(now)
                    elif batch:
                        _flush_batch(now)
                    continue
                if raw is _LOGCAT_EOF:
                    break
                item = self._classify_and_filter(raw, levels, keyword, only_exc,
                                                 stats, pkg_pids)
                if item is None:
                    continue
                if "raw" in item:
                    # 只在「还没收到任何日志」时留几条，正常跑起来后零额外开销
                    if not stats["seen"] and len(err_lines) < 5:
                        err_lines.append(item["raw"])
                if item.get("exc"):
                    exc += 1
                total += 1

                if in_boot:
                    boot_buf.append(item)
                    if len(boot_buf) > BOOT_KEEP_LINES:
                        boot_buf.pop(0)
                        boot_dropped += 1
                    if time.time() - t0 >= BOOT_WINDOW_SEC:
                        # 爆发期结束：把攒下的最近若干行作为第一批推给前端
                        # （设备安静时由上面的超时分支负责收尾）
                        _end_boot(time.time())
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
                    _flush_batch(now)
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
            # 把队列里没消费完的行丢掉，解开可能阻塞在满队列 put 上的读线程，
            # 让它读到 EOF 自行退出（否则每次停止都可能遗留一个卡住的 pump 线程）。
            if q is not None:
                try:
                    while True:
                        q.get_nowait()
                except queue.Empty:
                    pass
            with self._lock:
                self._running.pop(serial, None)
                self._procs.pop(serial, None)
                self._stops.pop(serial, None)
                self._stopreq.discard(serial)
            if not stop_ev.is_set() and not stats["seen"]:
                # 没点停止、却一条日志都没解析到就退出了：设备离线 / 序列号失效 /
                # logd 没跑时，adb 只往 stdout 打一行原因然后退出。此前那行被当成
                # 普通文本推给前端，紧接着又推 stopped —— 界面显示「空闲，0 行」，
                # 看起来像「点了一下就自动停了」，完全看不出设备根本没连上。
                detail = "；".join(x.strip() for x in err_lines if x.strip())[:300]
                self.bus.push("logcat",
                              {"serial": serial, "status": "error",
                               "total": total, "exc": exc,
                               "text": "logcat 没有输出任何日志就退出了%s。"
                                       "设备可能已断开 / 离线，或 logd 未运行"
                                       % ("：" + detail if detail else "")})
            else:
                self.bus.push("logcat",
                              {"serial": serial, "status": "stopped",
                               "total": total, "exc": exc})

    @staticmethod
    def _pump(proc, q):
        """读线程：把 adb stdout 的每一行搬进队列，结束时投递 EOF 哨兵。

        只做搬运、不做解析：解析与推送全部留在 worker 线程，保证事件顺序与
        原先的单线程读循环完全一致。异常（终止瞬间的管道错误）不外抛 —— 收尾
        由 worker 的 finally 统一负责。

        队列有界，put 满了就阻塞（限时重试）：这就是旧「同线程阻塞读」天然
        具备的背压 —— 队列满 → 不再读 stdout → 管道满 → adb 停写 → 设备端
        logcat 缓冲自己顶住，本进程内存不会随日志洪流无上限增长。
        adb 进程已退出（消费者也走了）时直接返回，避免线程永远卡在 put 上。
        """
        try:
            for raw in proc.stdout:
                while True:
                    try:
                        q.put(raw, timeout=0.5)
                        break
                    except queue.Full:
                        if proc.poll() is not None:
                            return
        except Exception:
            pass
        finally:
            # 收尾哨兵也可能撞上满队列：限时投递，投不进去说明消费者已经不在了。
            try:
                q.put(_LOGCAT_EOF, timeout=0.5)
            except Exception:
                pass

    def _resolve_pkg_pids(self, serial, keyword):
        """把过滤表达式里的 pkg:xxx 解析成 {包名小写: {pid,...}}。

        只解析**非排除**的 pkg 词：`-pkg:x`（排除某包）同样需要 pid 映射才能
        判断，所以一并解析，避免「排除条件静默变成不排除」。
        没有 pkg: 词时返回 {}，调用方据此关闭定期刷新。
        """
        out = {}
        for _negate, term in split_filter_terms(keyword):
            low = term.lower()
            if not low.startswith("pkg:"):
                continue
            name = term[4:].strip().lower()
            if not name or name in out:
                continue
            out[name] = pkg_pids_of(self.adb_path, serial, name)
        return out

    @staticmethod
    def _classify_and_filter(raw, levels, keyword, only_exc, stats=None,
                             pkg_pids=None):
        rec = classify_line(raw)
        if rec is None:
            # 非 threadtime 行（标题/分隔/空行）原样保留给前端做纯文本渲染
            return {"raw": (raw or "").rstrip("\n")}
        if stats is not None:
            stats["seen"] = stats.get("seen", 0) + 1
        if rec["level"] not in levels:
            return None
        if only_exc and not rec["exc"]:
            return None
        # 过滤表达式（tag:/msg:/pid:/level:/pkg:、- 排除、空格 AND）统一走
        # core.logcat，避免它与前端各写一套规则后悄然漂移。
        if keyword and not match_filter(rec, keyword, pkg_pids):
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
        # 正处于「设备掉线、等待重连」的 serial：供孤儿回收（_reap_gone_tools）
        # 豁免——这类抓取是有意存活的，不能被当成「设备已移除」而强停。
        self._reconnecting = set()
        # 已被孤儿回收线程告知「设备已从设备列表消失」的 serial。用于在
        # device_present 查不出结论（adb 不可达 / 返回 None）时仍能判定这是一次
        # 掉线：否则会把被截断的文件当成「✓ 抓取完毕」报给用户。
        self._gone = set()
        # 等重连期间供 stop() 立刻唤醒（serial -> Event）。没有它，停抓取最多要
        # 等一个轮询间隔（3s）才生效——「录屏停、日志同步停」就会被拖成两条对不齐
        # 的时间线，正是日志与视频要按时间轴对照时最忌讳的。
        self._reconn_wake = {}
        # 已实测「不认 -T」的设备序列号（老车机 / 裁剪版 logcat）。
        # 一旦某台设备带 -T 一行日志都拿不到就 EOF，就把它记进来，本次进程内
        # 后续抓取直接走兼容命令——不再每次都先撞一次墙。
        self._no_T = set()
        # 最近一次抓取的「会话事实」，供录屏收尾判断日志有没有覆盖录制时段。
        # 只记录**进程侧可验证**的信号（起点、是否回落兼容模式、是否真的断过），
        # 一律不依赖设备时钟 —— 车机没校时、或被手动改过时间，都不会让这些
        # 信号失真。设备时钟只影响日志时间戳的展示，不影响完整性判定。
        self._facts = {}

    def is_running(self, serial):
        with self._lock:
            return serial in self._procs or serial in self._starting

    def running_serials(self):
        """当前正在抓取的设备序列号（供「设备移除后强停孤儿抓取」使用）。"""
        with self._lock:
            return list(set(self._procs.keys()) | self._starting)

    def is_reconnecting(self, serial):
        """抓取是否正处于「设备掉线、等待重连」状态。

        供 autorefresh._reap_gone_tools 豁免：这种抓取是**有意存活**的（在等
        设备重连并续写同一文件），绝不能因为它此刻不在设备列表里就被当成
        「已移除的孤儿」强停——否则设备一掉线，刚建立的续写保护立刻被回收逻辑掐断。
        """
        with self._lock:
            return serial in self._reconnecting

    def notice_device_gone(self, serial):
        """告知抓取：这台设备已从设备列表里消失（孤儿回收线程调用）。

        与 stop() 的区别是**不设停止请求**：抓取不该就此结束，而应转入「掉线、
        等重连」状态（写缺口标记 → 推 reconnecting → 窗口内续写同一文件）。

        旧行为是回收线程直接 stop()：worker 把 `_stopreq` 当作「用户主动停止」，
        收尾时报 `stopped` 且没有 gap —— 设备拔线、文件在掉线处截断，界面却弹
        「✓ 抓取完毕：N 行」。分析时拿视频流对日志才发现中间少了一段，属于最
        典型的「假成功 + 结果错」。而 Windows 上 `adb logcat` 在设备拔掉后常常
        迟迟不退出，回收线程反而是这条路的**主干道**，必须走同一个掉线通道。

        这里只做两件事：
          * 记下「设备确实没了」这一事实（device_present 查不出结论时据此仍能
            判定掉线，不至于把截断报成成功）；
          * 终止当前 adb 进程，让读循环立刻解开阻塞并进入判定分支。

        返回 True 表示确有进行中的抓取被通知到。
        """
        with self._lock:
            if serial not in self._procs and serial not in self._starting:
                return False
            self._gone.add(serial)
            proc = self._procs.get(serial)
        if proc is not None:
            _terminate(proc)
        return True

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
            self._facts[serial] = {
                "started_host": time.time(),
                "compat": False,
                "data_gap": False,
                "lines": 0,
                "error": "",
            }
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
            # 正在等设备重连时，立刻叫醒等待循环：停抓取必须马上生效，
            # 否则最多拖一个轮询间隔（3s），日志就比视频多出这几秒。
            wake = self._reconn_wake.get(serial)
        if proc is not None:
            _terminate(proc)
        if wake is not None:
            wake.set()
        # 收尾由 _worker finally 统一处理（决定是否打包末段）
        return True

    def stop_all(self, zip_on_stop=True):
        with self._lock:
            serials = list(self._procs.keys()) + list(self._starting)
        for s in serials:
            self.stop(s, zip_on_stop=zip_on_stop)

    # ------------------------------------------------------------------
    def capture_facts(self, serial):
        """最近一次抓取的「会话事实」，未知设备返回空 dict。

        字段全部是进程侧可验证的：
          * started_host —— 抓取线程启动的本机时刻；
          * compat       —— 是否因设备不认 -T 回落到兼容模式（会先带出历史
                            缓冲，起点可能早于录制开始）；
          * data_gap     —— 是否真的断过（设备掉线 / logcat 意外退出 / 重连
                            耗尽），文件里必有 [logcat] 缺口标记；
          * lines        —— 实际写盘行数；
          * error        —— 收尾错误原文（写盘失败 / 重连耗尽）。
        刻意不含「设备时钟推算的缺口」：设备没校时或被人手动改时间时那个值
        不可信，拿它做完整性判定只会产生假告警。
        """
        with self._lock:
            f = self._facts.get(serial)
            return dict(f) if f else {}

    def _fact(self, serial, **kw):
        """更新会话事实（抓取线程内部用；serial 已收尾时静静忽略）。"""
        with self._lock:
            f = self._facts.get(serial)
            if f is not None:
                f.update(kw)

    # ------------------------------------------------------------------
    # 重连等待：设备掉线后轮询直到重连 / 用户停止 / 超时。
    # 返回 "ok"（设备回来了）/ "stopped"（用户中途点了停止）/ "timeout"（窗口耗尽）。
    def _wait_reconnect(self, serial):
        deadline = time.time() + LOGCAT_CAP_RECONNECT_MAX_S
        with self._lock:
            wake = self._reconn_wake.setdefault(serial, threading.Event())
        while True:
            with self._lock:
                if serial in self._stopreq:
                    return "stopped"
            # device_present 异常（adb 缺失/无响应）一律视为「还没回来」，继续等；
            # 它只做 get-state 探测，不会外抛。
            try:
                if device_present(self.adb_path, serial):
                    return "ok"
            except Exception:
                pass
            if time.time() >= deadline:
                return "timeout"
            # 用 Event 而不是 sleep：stop() 会立刻 set，停抓取不必等满一个轮询间隔。
            wake.clear()
            wake.wait(LOGCAT_CAP_RECONNECT_POLL_S)

    def _worker(self, serial, path, buffers, levels=None):
        adb = self.adb_path
        # 从「现在」开始抓，而不是先把设备整个历史缓冲区灌一遍：否则录屏一短，
        # 缓冲区还没灌到当下就停止了，文件里全是录制前的历史日志（见 _logcat_cmd）。
        with self._lock:
            from_now = serial not in self._no_T
        cmd = _logcat_cmd(
            adb, serial, buffers,
            LOGCAT_CAP_FROM_NOW_LINES if from_now else None)
        # 是否已经为「不认 -T」回落过一次（每台设备每次抓取最多回落一次，
        # 避免老设备上无限重试）。
        fallback_tried = False
        lines = 0
        # 一行都没写进去时留下的前几行原文（多为 adb 的报错：device not found 等），
        # 供末段判断「设备没连上」时把原因带出来。
        err_lines = []
        # 是否解析到过**真日志行**（threadtime 形态）。不能拿「读到的行数」判断：
        # 设备离线时 adb 恰好会吐一行 `error: device ... not found`，那一行也是
        # 「读到了」。只在前几行判断一次，拿到日志行后不再产生开销。
        logish = 0
        err_reported = False      # 已在 except 里报过错，末段不要再报一次
        # 写盘中途失败的原因（磁盘满 / 目录被删 / 权限）。末段的 stopped 必须
        # 把它带上：只推一条 error 紧接着又推 stopped「抓取完毕」，前端后到的
        # 成功 toast 会把前一条错误盖掉 —— 用户看到的是「✓ 抓取完毕」，而文件
        # 只有半截，甚至一行都没写进去。
        write_error = ""
        gap_written = False        # 文件里是否写过「设备掉线」缺口标记
        # 是否发生过**真实的数据缺口**（设备掉线 / logcat 意外退出 / 重连后
        # 的日志空洞）。与 gap_written 分开：后者还包含「设备时钟回退」这类
        # 只影响排序、并不丢数据的标记，不能拿来判完整性。
        data_gap = False
        # 设备仍在线、adb logcat 却自己退出了：文件在此处截断。收尾时必须
        # 说明，否则就是一次「✓ 抓取完毕」的假成功（见 finally）。
        eof_unexpected = False
        eof_ts = ""
        # 已写盘的最后一条 threadtime 时间戳：重连时新起的 adb 会把缓冲区从头
        # 重放一遍，据此跳过断点之前的部分（否则整段日志会重复出现）。
        # 注意别用 resume_ts 这个名字：下面写「恢复连接」标记时它装的是墙上
        # 时间字符串，撞在一起会把续写会话的每一行都误判成重放而全部跳过。
        last_log_ts = ""
        # last_log_ts 对应的精确时刻（epoch 秒）。字符串比较只在「同一天内」
        # 成立，跨年 / 设备校时回退时会判错，凡是走到「时间像是倒流」的分支才
        # 落到 ts_epoch() 精确比较，正常路径（时间向前）完全不付这份开销。
        last_log_epoch = None
        # 本次续写是否已检查过「断点与续写起点之间的空洞」。只在新会话的第一条
        # 新日志上检查一次：缺口只会出现在续写开头。
        hole_checked = False
        skipped = 0                # 本次会话跳过的重放行数（仅用于提示）
        # 「设备仍在线、logcat 自己退了」的自动重启计数（见 LOGCAT_CAP_RESTART_*）
        restarts = 0
        no_progress = 0            # 连续多少次重启没有任何新日志
        lines_at_restart = 0       # 上一次重启时的累计行数（判断有没有进展）
        restart_ts = ""            # 最近一次意外中断的墙上时间（写标记用）
        f = None
        # 重启判定：首次会话开始时记下单调时钟起点。之后遇到「时间戳倒退」再
        # 惰性探一次开机时长 —— 录制期间重启过的话，uptime 必然小于录制已进行
        # 的时长（因为它是从重启那一刻重新计数）。惰性探避免给正常启动路径
        # 增加一次 adb 往返，也不影响没有时间回退的会话。
        cap_started = None

        session = 0
        outcome_error = ""         # 重连窗口耗尽等原因导致的最终报错（区别于写盘异常）
        try:
            while True:
                session += 1
                # 每进入一轮新会话就重置「续写空洞」检查位：缺口只会出现在
                # 续写的最前面一条新日志上（见读循环里的 hole_checked）。
                hole_checked = False
                # 时间戳倒退时才惰性探一次「设备是否在录制期间重启过」：
                # 每轮会话最多探一次，避免逐行调用 adb。
                boot_probed = False
                reboot_seen = False
                rollback_marked = False
                if cap_started is None:
                    cap_started = _now_mono()
                try:
                    proc = subprocess.Popen(
                        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        **adb_popen_kwargs())
                except Exception as e:
                    err_reported = True
                    write_error = "启动抓取失败：%s" % e
                    self.bus.push("logcat_capture",
                                  {"serial": serial, "status": "error",
                                   "text": write_error})
                    break
                with self._lock:
                    self._starting.discard(serial)
                    self._procs[serial] = proc
                    # 启动期间就被告知「设备已从设备列表消失」（拔线 / USB 复位恰好
                    # 撞上拉起 adb 的瞬间）：必须主动终止，让读循环立刻结束并走
                    # 「掉线」通道。不终止的话，设备端没有日志可读时
                    # `for raw in proc.stdout` 会一直阻塞 —— 抓取既停不下来、
                    # 也永远走不到掉线判定，界面就一直停在「采集中」。
                    gone_now = serial in self._gone
                if session == 1:
                    # 「启动瞬间点停止」必须在 open 文件之前判定：stop() 在 Popen 返回前
                    # （_starting 窗口内）调用时，此处已能看到 _stopreq，从而跳过建文件、
                    # 不留 0 字节 txt（否则前端弹「✓ 抓取完毕：0 行」误导用户）。检查点
                    # 放在 Popen 之后——抢在 Popen 返回前点停止的场景，此刻 _stopreq
                    # 才刚刚被写入，前置到 Popen 之前会落入竞态、仍建出空文件。
                    with self._lock:
                        stop_during_start = serial in self._stopreq
                    if stop_during_start:
                        _terminate(proc)
                        with self._lock:
                            self._procs.pop(serial, None)
                            self._stopreq.discard(serial)
                            self._flags.pop(serial, None)
                            self._reconnecting.discard(serial)
                            self._gone.discard(serial)
                        self.bus.push("logcat_capture",
                                      {"serial": serial, "status": "stopped",
                                       "path": path, "lines": 0, "size": 0,
                                       "packaged": False, "no_file": True,
                                       "text": "已停止：还没写入任何日志就结束了，"
                                               "本次没有生成日志文件"})
                        return
                    # 首会话：开文件 + 播 running（重连的后续会话复用同一文件句柄）
                    try:
                        # buffering=1：文本模式行缓冲，**每写一行就落盘**。
                        # 满缓冲全级别 logcat 一秒能吐上万行，攒在用户态缓冲里
                        # 等「满 1000 行 / 满 0.5s」再 flush 时，程序被强杀或崩溃
                        # 就会丢掉最后那一小段 —— 而「照视频时间戳回查日志」最
                        # 需要的往往正是断点前那几十行。每行 flush 的代价只是一次
                        # write 系统调用（本机写盘速率远高于 adb 输出速率，不会
                        # 反压到设备端 logcat 缓冲）。
                        f = open(path, "w", encoding="utf-8", errors="replace",
                                 buffering=1)
                    except Exception as e:
                        err_reported = True
                        write_error = "抓取异常：%s" % e
                        self.bus.push("logcat_capture",
                                      {"serial": serial, "status": "error",
                                       "text": write_error})
                        _terminate(proc)
                        with self._lock:
                            self._procs.pop(serial, None)
                            self._stopreq.discard(serial)
                            self._flags.pop(serial, None)
                            self._reconnecting.discard(serial)
                            self._gone.discard(serial)
                        break
                    self.bus.push("logcat_capture",
                                  {"serial": serial, "status": "running",
                                   "path": path})
                if gone_now:
                    # 见上方 gone_now 的取值处：终止进程，把阻塞的读循环放出来，
                    # 让它走掉线判定而不是无限挂着。
                    _terminate(proc)
                # ---- 读循环：把日志写入同一文件（重连后继续追加）----
                try:
                    for raw in proc.stdout:
                        with self._lock:
                            if serial in self._stopreq:
                                break
                        if not logish:
                            if classify_line(raw) is not None:
                                logish = 1
                            elif len(err_lines) < 5:
                                err_lines.append(raw.rstrip("\n"))
                        # 级别过滤（与实时监控同语义）：能识别出级别的行按用户勾选
                        # 的集合过滤；识别不出的行（标题/分隔线）原样写盘。
                        if levels is not None:
                            rec = classify_line(raw)
                            if rec is not None and rec["level"] not in levels:
                                continue
                        ts = _ts_prefix(raw)
                        if session > 1 and last_log_ts and ts and ts < last_log_ts:
                            # 重连后新起的 `adb logcat` 会**从缓冲区开头重放**：这些
                            # 行早就写进文件了，再写一遍会让时间线上出现整段重复
                            # （对照视频找日志时以为同一段发生了两次），文件也白白
                            # 翻倍。按行首 threadtime 时间戳跳过断点之前的部分。
                            #
                            # 这里先做字符串比较是因为它零成本：同一天内字符串序
                            # 就是时间序。但跨年（12-31 → 01-01）和设备校时回退会
                            # 让它判错方向 —— 一律落到 ts_epoch() 比精确时刻，否则
                            # 跨年录制一夜之后，零点起的日志会被整体当成「重放」
                            # 全部丢掉，文件就那么停在 23:59。
                            if last_log_epoch is None:
                                last_log_epoch = ts_epoch(last_log_ts)
                            cur_epoch = ts_epoch(ts)
                            older = (cur_epoch is not None
                                     and last_log_epoch is not None
                                     and cur_epoch < last_log_epoch)
                            if older and not boot_probed:
                                # 第一次遇到倒退才探 uptime（每轮会话最多一次）。
                                # 录制期间重启过 → uptime 从重启那刻重新计数，
                                # 必然小于「录制已进行的时长」；没重启则 uptime
                                # 一定大于这个时长。由此把「缓冲区重放」与
                                # 「车机时钟没校时」彻底分开。
                                boot_probed = True
                                up = _device_uptime(adb, serial)
                                reboot_seen = (
                                    up is not None
                                    and up + LOGCAT_CAP_REBOOT_UPTIME_SLACK_S
                                    < _now_mono() - cap_started)
                            if older and reboot_seen:
                                # 设备在本次抓取期间重启过：缓冲区随重启清空，
                                # 不可能出现「缓冲区重放」。此时的时间戳倒退只能
                                # 是车机时钟没校时 / 校时回退，而这些日志都是**新
                                # 产生**的 —— 原样接收并重置基准，一行都不丢。
                                if not rollback_marked:
                                    _write_marker(
                                        f, "设备重启后时间回退（%s → %s），已停止"
                                           "按时间戳去重、按实际顺序继续记录"
                                        % (last_log_ts, ts))
                                    rollback_marked = True
                                    gap_written = True
                                skipped = 0
                                last_log_ts = ""
                                last_log_epoch = None
                            elif older and skipped < LOGCAT_CAP_REPLAY_SKIP_MAX:
                                skipped += 1
                                continue
                            elif older:
                                # 跳过量已远超「缓冲区重放」的量级：这不是重放，
                                # 是设备时钟整体回退（校时 / 换电池 / 时区）。
                                # 继续跳过等于把之后的日志全扔掉，故接受并标记。
                                _write_marker(
                                    f, "设备时间发生回退（%s → %s），已停止按"
                                       "时间戳去重、按实际顺序继续记录"
                                       % (last_log_ts, ts))
                                gap_written = True
                                skipped = 0
                                last_log_ts = ""
                                last_log_epoch = None
                        if session > 1 and not hole_checked and ts and last_log_ts:
                            # 续写的第一条新日志：若它离断点太远，说明断连期间产生的
                            # 日志已经滚出设备环形缓冲区、永远取不回来了。必须写下
                            # 缺失区间 —— 否则文件看着是连续的，只有事后按视频对
                            # 时间轴才会发现「这里少了一大段」，而那时已无从补救。
                            hole_checked = True
                            prev = (last_log_epoch if last_log_epoch is not None
                                    else ts_epoch(last_log_ts))
                            cur = ts_epoch(ts)
                            if (prev is not None and cur is not None
                                    and cur - prev > LOGCAT_CAP_HOLE_WARN_S):
                                _write_marker(
                                    f, "日志缺失：%s ~ %s 之间（约 %d 秒）的日志"
                                       "未能取回（中断期间产生的日志已滚出设备"
                                       "缓冲区）" % (last_log_ts, ts, cur - prev))
                                gap_written = True
                                data_gap = True
                        f.write(raw)
                        lines += 1
                        if ts:
                            last_log_ts = ts
                            # 基准变了，下次走慢路径时重新算精确时刻
                            last_log_epoch = None
                        # 落盘由文件对象的行缓冲负责（见上面的 buffering=1）：
                        # 这里不再做「攒够多少行再 flush」，否则尾部落盘不及时。
                except Exception as e:
                    err_reported = True
                    write_error = "抓取异常：%s" % e
                    self.bus.push("logcat_capture",
                                  {"serial": serial, "status": "error",
                                   "text": write_error})
                    break
                finally:
                    # 终止 adb 子进程（无论正常 EOF / 用户停止 / 写盘异常）。
                    # 注意：此处**不**从 _procs 移除进程——重连等待期间保留它，
                    # 使 is_running() / stop() 仍认得这次抓取在进行，用户点「停止」
                    # 不会被当成「当前没有进行中的抓取」而静默忽略。下一轮会话会
                    # 用新进程覆盖它。
                    _terminate(proc)
                # ---- 读循环结束（EOF / 用户停止 / 写盘异常）----
                with self._lock:
                    if serial in self._stopreq:
                        break
                if not logish:
                    # 一行真日志都没解析到就 EOF：设备离线 / 序列号失效 / logd 未运行，
                    # 也可能是**老 logcat 不认 -T**（打印用法后立刻退出）。
                    # 后者必须能自愈：回落一次兼容命令继续抓，否则老车机上日志
                    # 一条都抓不到。判定依据不只看「0 行」——设备抖动也会 0 行 EOF，
                    # 所以优先看 adb/logcat 的报错原文里有没有「选项不认识」。
                    if from_now and not fallback_tried:
                        fallback_tried = True
                        blob = "".join(err_lines).lower()
                        bad_opt = any(k in blob for k in (
                            "invalid option", "unknown option", "unrecognized option",
                            "unrecognised option", "usage:"))
                        if bad_opt:
                            with self._lock:
                                self._no_T.add(serial)
                        from_now = False
                        cmd = _logcat_cmd(adb, serial, buffers, None)
                        # 兼容模式会先把历史缓冲区灌出来：起点可能早于录制开始。
                        # 这是收尾判断「日志有没有覆盖录制时段」的真实依据之一。
                        self._fact(serial, compat=True)
                        if bad_opt:
                            text = ("logcat 抓取：设备 %s 不支持 -T（从当前时刻起抓），"
                                    "已改用兼容命令重新开始（本次会先带出缓冲区里的历史日志）"
                                    % serial)
                        else:
                            text = ("logcat 抓取：设备 %s 本会话未产出日志（%s），"
                                    "已用兼容命令重试一次"
                                    % (serial, (err_lines[0] if err_lines else "无输出")))
                        self.bus.push("status", {"type": "info", "text": text})
                        continue
                    # 此前这行被原样写进 txt，紧接着推 stopped —— 前端弹「✓ 抓取完毕：
                    # 0 行」，一个完美的假成功。这里不再尝试重连（从来没连上过的设备
                    # 重连也没意义），留待 finally 按「设备离线」报错。
                    break
                # 已经抓到过日志、却在这里 EOF：多半是设备掉线（adb logcat 在连接
                # 存活时会一直跑，不会自己退出）。判定依据两条：
                #   * device_present 明确返回 False（确认设备已不在）；
                #   * 孤儿回收线程已告知「这台设备从设备列表消失了」（_gone）——
                #     设备拔掉后 adb 可能查不出结论（返回 None），此时不能因为
                #     「查不到」就当成功收尾，那样文件在掉线处截断却报「✓ 抓取完毕」。
                # 返回 True（设备还在）才按正常收尾——否则会把「设备其实没掉线」
                # 误判成掉线、反复拉起空转。
                with self._lock:
                    gone_hint = serial in self._gone
                if gone_hint or device_present(adb, serial) is False:
                    # 确认设备掉了：写入缺口标记，等待重连后往同一文件续写（绝不丢已抓到的）。
                    gap_written = True
                    data_gap = True
                    drop_ts = time.strftime("%Y-%m-%d %H:%M:%S")
                    try:
                        f.write("\n--------- [logcat] 设备于 %s 断开连接，等待重连 ---------\n"
                                % drop_ts)
                        f.flush()
                    except Exception:
                        pass
                    self.bus.push("logcat_capture",
                                  {"serial": serial, "status": "reconnecting",
                                   "path": path,
                                   "text": "设备 %s 掉线，logcat 抓取等待重连"
                                           "（最长 %d 秒，期间已抓到的日志不会丢）"
                                           % (serial, LOGCAT_CAP_RECONNECT_MAX_S)})
                    with self._lock:
                        self._reconnecting.add(serial)
                    verdict = self._wait_reconnect(serial)
                    with self._lock:
                        self._reconnecting.discard(serial)
                        # 重连成功 / 超时都清掉「已消失」提示：它只用于这次判定，
                        # 留着会让下次「设备其实还在、logcat 自己退了」被误判成掉线。
                        self._gone.discard(serial)
                    if verdict == "stopped":
                        break
                    if verdict == "timeout":
                        # 重连窗口耗尽：抓取就此结束，但文件里留有缺口标记，绝不把缺口
                        # 藏成一次「成功抓取」。不另推 error 事件——下面的 stopped(gap)
                        # 已携带缺口说明，避免界面叠出两条告警。
                        outcome_error = ("设备在重连窗口（%d 秒）内未恢复，logcat 抓取已结束。"
                                         "文件存在时间缺口：从 %s 起的日志缺失"
                                         "（设备断连期间产生的日志已无法从该缓冲区取回）。"
                                         % (LOGCAT_CAP_RECONNECT_MAX_S, drop_ts))
                        break
                    # 重连成功：写恢复标记，继续外层循环往同一文件续写。
                    resume_ts = time.strftime("%Y-%m-%d %H:%M:%S")
                    try:
                        f.write("--------- [logcat] 设备于 %s 恢复连接，继续抓取 ---------\n"
                                % resume_ts)
                        f.flush()
                    except Exception:
                        pass
                    self.bus.push("status",
                                  {"type": "info",
                                   "text": "logcat 抓取：设备 %s 已重连，继续写入 %s"
                                           % (serial, path)
                                           + ("（已跳过重放的 %d 行）" % skipped
                                              if skipped else "")})
                    skipped = 0
                    continue
                # device_present 为 True / None：设备还在，或 adb 查不出结论。
                # 但连接存活时 `adb logcat` 不会自己退出 —— 它在这里 EOF，
                # 说明这次抓取是被外力打断的（logd 重启 / adb 内部错误 /
                # 别的工具 kill-server / 满缓冲全级别日志 + 录屏把 USB 带宽拉满）。
                #
                # **必须自动拉起**：旧实现只报一句「意外退出」就收尾，于是录屏
                # 还在继续、日志却从此刻停住 —— 用户实况正是视频录到 11:14、
                # 配套日志的最后一条停在 10:50，后 24 分钟一条不剩，而且直到事后
                # 拿时间轴比对才发现。这里与「设备掉线」同等对待：写缺口标记、
                # 退避、重启，继续往同一文件续写。
                if not lines:
                    # 一行都没写进去（用户取消了全部级别 / 从未收到日志行）：
                    # 重启也换不来内容，按正常收尾处理，不制造无谓的重启循环。
                    break
                if restarts >= LOGCAT_CAP_RESTART_MAX:
                    outcome_error = (
                        "logcat 抓取累计 %d 次被意外中断（设备仍在线），已停止"
                        "自动重启。文件存在时间缺口：最后一次日志停在 %s。"
                        "常见诱因是 USB 带宽被占满（录屏 + 满缓冲全级别日志同时"
                        "运行）、设备 logd 重启或其它工具重启了 adb server。"
                        % (restarts, last_log_ts or "未知"))
                    break
                if lines <= lines_at_restart:
                    no_progress += 1
                else:
                    no_progress = 0
                lines_at_restart = lines
                if no_progress >= LOGCAT_CAP_RESTART_NO_PROGRESS:
                    # 连着重启都不产出任何新日志：不是「偶发中断」，重启只会
                    # 无限空转（每次都要新起一个 adb 进程）。明确收尾并说清原因。
                    eof_unexpected = True
                    eof_ts = time.strftime("%H:%M:%S")
                    break
                restarts += 1
                restart_ts = time.strftime("%Y-%m-%d %H:%M:%S")
                _write_marker(
                    f, "抓取进程于 %s 意外中断（设备仍在线），第 %d 次自动重连…"
                       % (restart_ts, restarts))
                gap_written = True
                data_gap = True
                self.bus.push("logcat_capture",
                              {"serial": serial, "status": "reconnecting",
                               "path": path,
                               "text": "设备 %s 的 logcat 抓取被意外中断"
                                       "（设备仍在线），正在第 %d 次自动重连，"
                                       "已抓到的日志不会丢"
                                       % (serial, restarts)})
                self.bus.push("status",
                              {"type": "warn",
                               "text": "⚠ %s 的 logcat 抓取被意外中断（设备仍在"
                                       "线），正在自动重连（第 %d/%d 次）"
                                       % (serial, restarts,
                                          LOGCAT_CAP_RESTART_MAX)})
                # 退避：立刻重连往往撞上同一个诱因（USB 带宽尖峰），退一步再拉起。
                # 等待必须能被打断 —— 用 Event + 200ms 小步轮询，而不是一次
                # sleep 满整个退避：用户点「停止」要立刻生效，不能让录屏收尾干等
                # 一个退避间隔（「录屏停、日志同步停」靠的就是这一点）。单次 wait
                # 也不能太长：stop() 在 set 之后才被 clear 掉的情况会丢掉那次唤醒。
                with self._lock:
                    wake = self._reconn_wake.setdefault(serial, threading.Event())
                deadline = time.time() + min(
                    LOGCAT_CAP_RESTART_BACKOFF_S * (2 ** (restarts - 1)),
                    LOGCAT_CAP_RESTART_BACKOFF_MAX_S)
                while True:
                    with self._lock:
                        if serial in self._stopreq:
                            break
                    left = deadline - time.time()
                    if left <= 0:
                        break
                    wake.wait(min(0.2, left))
                with self._lock:
                    if serial in self._stopreq:
                        break
                continue
        finally:
            # 关文件句柄（之后才打包/量大小）：Windows 上开着的句柄会让 zip 失败。
            if f is not None:
                try:
                    f.close()
                except Exception:
                    pass
            with self._lock:
                self._procs.pop(serial, None)
                self._starting.discard(serial)
                # 在 discard 之前取：区分「用户点了停止」与「adb 自己退出了」。
                stopped_by_user = serial in self._stopreq
                self._stopreq.discard(serial)
                self._reconnecting.discard(serial)
                self._gone.discard(serial)
                self._reconn_wake.pop(serial, None)
                flags = self._flags.pop(serial, {"zip_on_stop": False})
                # 把本轮会话的可验证事实留档，供录屏收尾判断覆盖度（只读快照）。
                fact = self._facts.get(serial)
                if fact is not None:
                    fact["lines"] = lines
                    fact["data_gap"] = bool(fact.get("data_gap") or data_gap)
                    fact["error"] = write_error or outcome_error
            # 打包条件：仅「结束后打包 zip」——抓取过程不做任何按大小的自动
            # 打包（旧「超 15M 自动打包」已整体移除），停止时是否打包
            # 完全由用户在界面上勾选的这一个开关决定。
            do_zip = bool(flags.get("zip_on_stop"))
            zpath = None
            # 勾了「结束后打包」却没打成时，必须留一句原因：用户按开关的承诺
            # 去保存目录找 zip，只看到 txt（或什么都没有），而界面只报「抓取
            # 完毕」—— 分不清是没勾上、还是打包失败了。
            zip_err = ""
            if do_zip:
                # 先确认是**普通文件**：open(path, "w") 失败时（保存目录被删、
                # 路径被同名目录占位），path 可能仍 exists —— 对目录打包会产出
                # 一个只有空目录条目的 zip，看起来「打包成功」却什么都没有。
                try:
                    is_file = os.path.isfile(path)
                    size_now = os.path.getsize(path) if is_file else 0
                except OSError:
                    is_file, size_now = False, 0
                if not is_file:
                    zip_err = ("抓取文件不存在或不是普通文件（保存目录被删 / "
                               "被同名目录占位？）")
                elif size_now <= 0:
                    zip_err = "抓取文件为空，没有可打包的内容"
                else:
                    zpath = self._zip_one(path)
                    if not zpath:
                        zip_err = ("打包失败（文件被占用 / 磁盘空间不足？），"
                                   "已保留 txt 文件")
            if zpath:
                self.bus.push("logcat_capture",
                              {"serial": serial, "status": "zipped",
                               "path": zpath, "src": path,
                               "text": "已打包：%s" % zpath})
            # size 语义：打了包就报 zip 的大小（源 txt 已清理），否则报 txt 大小
            if zpath and os.path.exists(zpath):
                size_out = os.path.getsize(zpath)
            elif os.path.isfile(path):
                size_out = os.path.getsize(path)
            else:
                size_out = 0
            if not stopped_by_user and not logish and not err_reported and not gap_written:
                # 用户没点停止、却一行都没写进去就退出了：设备离线 / 序列号失效时
                # adb 只往 stdout 打一行原因然后退出。此前这行被原样写进 txt，
                # 紧接着推 stopped —— 前端弹的是「✓ 抓取完毕：0 行」，一个完美的
                # 假成功：用户以为抓到了空日志，实际是设备根本没连上。
                detail = "；".join(err_lines)[:300]
                self.bus.push("logcat_capture",
                              {"serial": serial, "status": "error",
                               "path": path, "lines": 0, "size": size_out,
                               "text": "抓取没有收到任何日志就结束了%s。"
                                       "设备可能已断开 / 离线，或 logd 未运行"
                                       % ("：" + detail if detail else "")})
            else:
                payload = {"serial": serial, "status": "stopped",
                           "path": path, "lines": lines, "size": size_out,
                           # 打了包：zipped 事件已另行通知「已打包」，
                           # stopped 不再重复弹完成 toast（前端据此二选一）。
                           "packaged": bool(zpath)}
                if write_error:
                    # 有它时前端必须以「中断 / 文件不完整」呈现，不能再报 ✓。
                    payload["error"] = write_error
                if outcome_error:
                    payload["error"] = outcome_error
                if (eof_unexpected and not payload.get("error")
                        and not write_error and not outcome_error):
                    # 比「设备掉线」更隐蔽的一档：设备明明还在，抓取却停了。
                    # 前端见到 error 就不再弹「✓ 抓取完毕」，改为告警呈现。
                    payload["error"] = (
                        "adb logcat 在设备仍在线时意外退出（%s），文件在此处截断，" 
                        "之后的日志没有抓到" % eof_ts)
                if gap_written:
                    # 文件里有缺口标记：即便用户主动停止，也要把「期间掉过线 /
                    # 中断过」说清楚，否则分析师对照视频流找日志时会误以为
                    # 时间线是连续的。
                    payload["gap"] = True
                    note = "（注意：抓取期间曾掉线或中断，文件含时间缺口标记，"
                    payload["text"] = (note + "缺失时段见文件内 [logcat] 标记）")
                if zip_err:
                    payload["zip_error"] = zip_err
                self.bus.push("logcat_capture", payload)

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
