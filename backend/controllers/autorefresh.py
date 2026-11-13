"""backend.controllers.autorefresh —— 自动轮询与孤儿回收"""

from backend.controller import (
    AUTO_REFRESH_MS, REC_DEATH_CHECK_S, time,
)
from backend.screen_service import device_present
from core.constants import (
    REC_MAX_SEGMENTS, REC_REBOOT_WAIT_S, REC_SEGMENT_S)

class AutoRefreshMixin:
    """自动轮询与孤儿回收（录屏/工具/录制）。"""

    def _start_auto_refresh(self):
        if self._auto_started or self.state.shutting_down:
            return
        self._auto_started = True
        self.workers.spawn("auto_refresh", self._auto_loop)

    def _auto_loop(self):
        """每 AUTO_REFRESH_MS 静默刷一次；无变化不广播。

        采用 0.2s 小步 tick 而不是整段 sleep，保证 shutdown() 后能及时退出。
        另外按 REC_DEATH_CHECK_S 的步长检测「录屏进程意外死亡」（与设备刷新
        解耦：死亡时要尽快自动收尾，不能等下一个 5s 刷新周期）。
        """
        interval = AUTO_REFRESH_MS / 1000.0
        next_run = time.time() + interval
        next_death_check = time.time() + REC_DEATH_CHECK_S
        while not self.state.shutting_down:
            time.sleep(0.2)
            if self.state.shutting_down:
                break
            now = time.time()
            if now >= next_death_check:
                next_death_check = now + REC_DEATH_CHECK_S
                try:
                    self._reap_dead_recordings()
                except Exception:
                    pass
            if now < next_run:
                continue
            next_run = now + interval
            try:
                self.devices.refresh(self.state.adb_path, verbose=False)
            except Exception:
                pass
            # 设备被移除后，停掉它遗留的 logcat 监控 / 抓取（详见 _reap_gone_tools）
            try:
                self._reap_gone_tools()
            except Exception:
                pass

    def _reap_dead_recordings(self):
        """发现「无人停止却退出」的录屏进程即派后台 worker 自动收尾。

        两种退出都走这条链路，但结论相反：被外力打断（died）要报「视频不完整」，
        跑到 180 秒单段上限（limit_hit）则是正常收尾、视频完整。

        不处理的后果：界面永远停在「录制中」，用户以为还在录；点「停止」后
        还要经历最多约 10 秒的 pull 重试才看到「缺 moov 头」——而那一刻用户
        早就切到别的页签做别的事了。检测本身极轻（VideoRecorder 内的 watcher
        线程已标记，这里只是取标记），故可放在自动轮询线程里直接跑。
        """
        # 自动分段：录满一段后程序自己接上下一段，用户什么都没做。这件事必须
        # 说出来 —— 否则保存目录里凭空多出一个 _p2.mp4，没人说得清它是哪来的，
        # 更没人敢相信「停止的时候不会漏掉它」。
        roll_fn = getattr(self.video, "rolled_serials", None)
        for s, n in (roll_fn() if roll_fn else []) or []:
            self._push_status(
                "info", "⏱ %s 已录满一段，已自动接着录第 %d 段（无需操作）"
                        % (s, n))
        # 设备掉线（典型是车机重启）→ 等待窗口内自动续录。进入等待和恢复
        # 各有一次性标记，只在翻转的当口播报，不重复刷状态栏。
        wait_fn = getattr(self.video, "reboot_wait_notes", None)
        for s in (wait_fn() if wait_fn else []) or []:
            self._push_status(
                "warn",
                "⏸ %s 连接中断（可能是设备重启），正在等待恢复（最长 %d 秒）："
                "设备回来后会自动继续录制，重启前已录的片段不会丢失；"
                "不想等可直接点「停止」，已录内容照样保存"
                % (s, REC_REBOOT_WAIT_S))
        resume_fn = getattr(self.video, "resumed_serials", None)
        for s in (resume_fn() if resume_fn else []) or []:
            self._push_status(
                "info",
                "▶ %s 已恢复连接，已自动继续录制（重启前那一段已保留，"
                "停止时会一并合并）" % s)
        # 上一轮「死亡收尾」还在跑（停止设备端 / 拉段 / 合并 / 打包，秒级）时
        # 先不取标记：died_serials() / limit_serials() 取完即清，而 Workers.spawn
        # 对同名存活线程会直接丢弃新参数 —— 标记被消耗、收尾却没收到，那台
        # 设备的「被意外中断 / 视频不完整」就永久丢失（多设备先后掉线时会撞上）。
        # 下一轮轮询再取（标记不会被下一个人抢走，仍是本次会话自己的）。
        if self.workers.is_running("rec-reap-dead"):
            return
        died = self.video.died_serials()
        # 「跑到分段上限后自己结束」与「被外力打断」在本地表现完全一样（adb 客户端
        # 自己退出），但结论相反：前者视频完整、只是录到头了，后者才需要重录。
        # 分开取标记，才能给用户不同的话。替身没有该方法时按「没有」处理。
        fn = getattr(self.video, "limit_serials", None)
        hit_limit = fn() if fn else []
        if not died and not hit_limit:
            return
        self.workers.spawn(
            "rec-reap-dead", self._teardown_dead_recordings, died, hit_limit)

    def _teardown_dead_recordings(self, serials, hit_limit=()):
        """（后台 worker）收尾自行退出的录屏：与手动停止同一条完整路径。

        serials 是「被外力打断」的设备（文案强调视频不完整）；hit_limit 是
        「跑到 180 秒上限」的设备（正常收尾，只说明为什么停了）。

        只收尾「仍在当前会话里」的设备；会话已被其他路径（用户点停止 /
        设备移除强停）结束掉时直接返回。残片视频不合成音频、源文件保留在
        保存目录；其余仍在录的设备会被优雅停掉并一并合成/打包。
        """
        with self._rec_lock:
            sess = self._rec_session
            if not sess:
                return
            videos = sess.get("videos") or {}
            dead = {s for s in serials if s in videos}
            limited = {s for s in hit_limit if s in videos}
            if not dead and not limited:
                return
            # 记下死亡设备，供 _session_teardown 把失败文案从「收尾失败」
            # 换成更准确的「被意外中断（视频不完整）」。
            sess["dead"] = set(sess.get("dead") or set()) | dead
        # 以下播报放在锁外：_rec_lock 保护的是会话状态，往界面推事件不需要它，
        # 占着锁推只会让并发的「开始/停止」多等一会儿。
        if limited:
            # 到分段上限是**正常结束**（screenrecord 先写回 moov 再退出）。
            # 不单独说明的话，用户会看到和「进程崩了」一模一样的收尾流程，
            # 以为视频坏了白录一场；而实际上它完整可用，只是录到头了。
            self._push_status(
                "info",
                "⏱ %s 已达到自动分段上限（共 %d 段，约 %d 分钟），录屏已正常"
                "收尾、视频完整（收尾时合并为一个完整 mp4，无需手动拼接）；"
                "需要更长时间请停止后重新开始录制"
                % ("、".join(sorted(limited)), REC_MAX_SEGMENTS,
                   REC_MAX_SEGMENTS * REC_SEGMENT_S // 60))
        if dead:
            # 续段失败的原因（第 N 段起不来 / 起来就退）只有录屏服务知道，
            # 不带出来就只剩一句笼统的「被意外中断」，用户会把已经录好的
            # 前几段也一起扔掉。
            note_fn = getattr(self.video, "seg_notes", None)
            notes = {}
            if note_fn is not None:
                try:
                    notes = note_fn() or {}
                except Exception:
                    notes = {}
            self._push_toast(
                "warn", self._build_death_message(sorted(dead), notes=notes))
        # 完整收尾：停掉其余设备 / 麦 / 设备音频、恢复指针位置/触摸圆点、合成与打包
        # 照常进行（异常由 _screen_record_stop_locked 兜底并清会话）。
        self.screen_record_stop()
        # 前端复位：会话已结束，把「停止」按钮切回「开始录制」。没有这条广播，
        # 界面会一直显示「录制中」（后端停了、前端不知道）。
        self.bus.push("rec_state", {"running": False, "reason": "died"})

    def _build_death_message(self, dead, probe=None, notes=None):
        """根据设备是否真的掉线，给出准确的录屏中断原因。

        不再写死「常见原因是 adb root」——录屏路径里本工具不会重启 adbd
        （指针位置 / 触摸圆点用的是 settings put，不碰 adbd），那句猜测在多数
        掉线场景里是错的，会把用户引去查一个不存在的原因。真正该做的是区分：
          * 设备确实掉了（USB 断开 / adb 失去连接）→ 提示连接问题，点出硬件 /
            USB 诱因，以及「录屏同时叠加满缓冲全级别 logcat 拉满 USB 带宽」这一
            最常见的放大器；
          * 设备还在但 screenrecord 自己退出 → 才是进程异常，此时才提 adb root /
            切无线调试（重启 adbd）作为其中一种可能。
        probe 可注入，便于测试（默认走真实的 device_present 探测）。
        """
        probe = probe or device_present
        names = "、".join(dead)
        gone = [s for s in dead if not probe(self.state.adb_path, s)]
        # 自动分段中途断掉时，用户最需要知道的是「前面几段还在」—— 不说的话，
        # 「视频不完整」四个字足以让他把整场录制当成废品删掉。
        seg_txt = ""
        for s in dead:
            why = (notes or {}).get(s)
            if why:
                seg_txt += ("；%s 的分段续录中断：%s（此前已录好的部分完整保留，"
                            "收尾时会合并成一个视频，见保存目录）" % (s, why))
        if gone:
            return ("⚠ 检测到录屏中断（%s）：设备连接已断开（USB 掉线 / adb 失去连接），"
                    "已保留已录片段。常见诱因是 USB 接触不良、系统 USB 省电"
                    "（选择性暂停），或在录屏同时叠加满缓冲全级别 logcat 拉满 USB 带宽"
                    "——可换后置 USB 口 / 短线缆 / 关闭 USB 选择性暂停，"
                    "或只抓需要的 logcat 缓冲区。%s" % (names, seg_txt))
        return ("⚠ 检测到录屏进程意外结束（%s）：设备仍在连接，screenrecord 自身异常终止，"
                "已保留已录片段。若你曾在录屏时执行 adb root / 切无线调试，"
                "adbd 重启也会触发此情况。%s" % (names, seg_txt))

    def _reap_gone_tools(self):
        """设备被移除（gone）后，收拾它正在进行的 logcat 监控 / 抓取，以及录屏会话里
        该设备的视频 / 设备音频。

        设备突然断开时 `adb logcat` 通常会退出（stdout EOF，worker 自行收尾推送
        stopped），但无线 / 网络 ADB 或 adb 卡顿时它可能迟迟不退出，留下孤儿 adb
        进程且界面卡在「监控中」。录屏同理：设备端 `screenrecord` / `tinycap` 在 adb
        断开后未必随退出，会残留进程、占用音频输入，且界面停留「录制中」直到用户手动
        点停止（那时 pull 必然失败）。这里以设备快照为权威处理「正在跑、却已不在设备
        列表里」的 serial。处于宽限（短暂失联、仍保留勾选）的设备不会被误处理——它们
        仍留在 device_state 中。

        但**抓取与监控处理方式不同**：监控直接 stop（实时画面断了就是断了，没有可挽回
        的东西）；抓取必须走 notice_device_gone —— stop 会被 worker 当成「用户主动
        停止」，收尾时报 stopped 且没有 gap，于是拔线导致的截断被报成「✓ 抓取完毕」。
        抓取应当转入掉线通道（缺口标记 + 等重连续写），因为落盘日志是用来事后分析的。
        """
        try:
            known = {d["serial"] for d in self.devices.get_items()}
        except Exception:
            return
        for s in self.logcat_monitor.running_serials():
            if s not in known:
                self.logcat_monitor.stop(s)
        for s in self.logcat_capture.running_serials():
            if s not in known:
                # 正在等重连的抓取是「有意存活」：设备掉线后它会在重连窗口内
                # 续写同一文件，不能因为它此刻不在设备列表里就被当成孤儿强停——
                # 那会把刚建立的掉线保护立刻掐断，logcat 照样丢数据。
                if self.logcat_capture.is_reconnecting(s):
                    continue
                # 不能 stop()：stop 会被 worker 当成「用户主动停止」，收尾时报
                # stopped 且没有 gap —— 设备拔线、文件在掉线处截断，界面却弹
                # 「✓ 抓取完毕」。改走 notice_device_gone：终止遗留的 adb 进程
                # （不留孤儿、界面不卡「采集中」），同时让抓取转入掉线通道
                # （写缺口标记 + 等重连续写），保住已抓到的日志。
                self.logcat_capture.notice_device_gone(s)
        # 录屏会话（多设备聚合）：只强停「已移除」的那几台，绝不替用户结束整个会话
        # （其余设备可能仍在正常录制）。停止涉及 adb 调用，设备离线时可能短暂阻塞，
        # 故放到后台 worker，不堵自动轮询线程。
        with self._rec_lock:
            sess = self._rec_session or {}
            candidates = [s for s in list(sess.get("videos", {}).keys())
                          + list(sess.get("devaudio", {}).keys())
                          if s not in known]
        # 正在「等待设备重启后自动续录」的设备绝不能在这里强停：它只是暂时
        # 掉线（screenrecord 随重启被杀），录屏侧有专门的等待线程——窗口内
        # 设备回来会先拉回重启前那一段、再自动接续下一段。这里强停会把整场
        # 录制提前结束，正是「重启后视频和日志都丢」的老毛病。
        try:
            waiting = set(self.video.reboot_wait_serials())
        except Exception:
            waiting = set()
        rec_gone = [s for s in candidates if s not in waiting]
        if rec_gone:
            self.workers.spawn(
                "rec-reap", self._reap_gone_recording, set(rec_gone))

    def _reap_gone_recording(self, gone_set):
        """后台强停已移除设备的视频 / 设备音频（务必在 rec-reap worker 内调用）。

        被移除设备的录屏 / tinycap 在设备端未必自动退出：强停可释放其占用的音频输入，
        并避免界面一直停留「录制中」。不改动会话其余部分——其余设备照常录，用户对
        仍在录的设备点「停止」时，本处已停止的设备会被判定为「未录制」而安全跳过。

        两处 stop 在未录制时都直接返回（不发 adb、幂等），故无需先 is_recording 判断；
        DeviceAudioCapture 本就没有 is_recording 方法。
        """
        for s in gone_set:
            try:
                # 用 stop_ex 取回**全部段**并记进会话：设备虽然掉了，掉之前录完的
                # 那几段已经拉回本地，收尾时必须一并进包。只调 stop() 的话它们
                # 就留在目录里、既不合成也不打包，用户以为没录上。
                ok, paths, err = self._stop_video(s)
                if paths:
                    with self._rec_lock:
                        sess = self._rec_session
                        if sess:
                            sess.setdefault("video_segs", {})[s] = paths
            except Exception:
                pass
            try:
                self.device_audio.stop(s)
            except Exception:
                pass

    def clear_output(self, ws=None):
        """清空**指定工作区**的指令输出。

        多工作区下「清空」必须带上 ws：不带的话，用户在工作区 2 点清空会把
        工作区 1 里正要回看的输出一起抹掉 —— 而那块面板此刻可能根本没显示在
        屏幕上，他连「被清了」都不知道。
        """
        payload = {"kind": "clear"}
        wid = self._ws_id(ws)
        if wid != self.WS_DEFAULT:
            payload["ws"] = wid
        self.bus.push("console", payload)
        return {"ok": True}

    def clear_status(self):
        self.bus.push("status", {"type": "clear"})
        return {"ok": True}