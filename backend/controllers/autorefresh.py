# -*- coding: utf-8 -*-
"""backend.controllers.autorefresh —— 自动轮询与孤儿回收"""

from backend.controller import (
    AUTO_REFRESH_MS, REC_DEATH_CHECK_S, time
)
from backend.screen_service import device_present

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

        不处理的后果：界面永远停在「录制中」，用户以为还在录；点「停止」后
        还要经历最多约 10 秒的 pull 重试才看到「缺 moov 头」——而那一刻用户
        早就切到别的页签做别的事了。检测本身极轻（VideoRecorder 内的 watcher
        线程已标记，这里只是取标记），故可放在自动轮询线程里直接跑。
        """
        died = self.video.died_serials()
        if not died:
            return
        self.workers.spawn(
            "rec-reap-dead", self._teardown_dead_recordings, died)

    def _teardown_dead_recordings(self, serials):
        """（后台 worker）收尾意外死亡的录屏：与手动停止同一条完整路径。

        只收尾「仍在当前会话里」的设备；会话已被其他路径（用户点停止 /
        设备移除强停）结束掉时直接返回。残片视频不合成音频、源文件保留在
        保存目录；其余仍在录的设备会被优雅停掉并一并合成/打包。
        """
        with self._rec_lock:
            sess = self._rec_session
            if not sess:
                return
            dead = {s for s in serials if s in (sess.get("videos") or {})}
            if not dead:
                return
            # 记下死亡设备，供 _session_teardown 把失败文案从「收尾失败」
            # 换成更准确的「被意外中断（视频不完整）」。
            sess["dead"] = set(sess.get("dead") or set()) | set(dead)
        self._push_toast("warn", self._build_death_message(sorted(dead)))
        # 完整收尾：停掉其余设备 / 麦 / 设备音频、恢复指针位置/触摸圆点、合成与打包
        # 照常进行（异常由 _screen_record_stop_locked 兜底并清会话）。
        self.screen_record_stop()
        # 前端复位：会话已结束，把「停止」按钮切回「开始录制」。没有这条广播，
        # 界面会一直显示「录制中」（后端停了、前端不知道）。
        self.bus.push("rec_state", {"running": False, "reason": "died"})

    def _build_death_message(self, dead, probe=None):
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
        if gone:
            return ("⚠ 检测到录屏中断（%s）：设备连接已断开（USB 掉线 / adb 失去连接），"
                    "已保留已录片段。常见诱因是 USB 接触不良、系统 USB 省电"
                    "（选择性暂停），或在录屏同时叠加满缓冲全级别 logcat 拉满 USB 带宽"
                    "——可换后置 USB 口 / 短线缆 / 关闭 USB 选择性暂停，"
                    "或只抓需要的 logcat 缓冲区。" % names)
        return ("⚠ 检测到录屏进程意外结束（%s）：设备仍在连接，screenrecord 自身异常终止，"
                "已保留已录片段。若你曾在录屏时执行 adb root / 切无线调试，"
                "adbd 重启也会触发此情况。" % names)

    def _reap_gone_tools(self):
        """设备被移除（gone）后，停掉它正在进行的 logcat 监控 / 抓取，以及录屏会话里
        该设备的视频 / 设备音频。

        设备突然断开时 `adb logcat` 通常会退出（stdout EOF，worker 自行收尾推送
        stopped），但无线 / 网络 ADB 或 adb 卡顿时它可能迟迟不退出，留下孤儿 adb
        进程且界面卡在「监控中」。录屏同理：设备端 `screenrecord` / `tinycap` 在 adb
        断开后未必随退出，会残留进程、占用音频输入，且界面停留「录制中」直到用户手动
        点停止（那时 pull 必然失败）。这里以设备快照为权威：凡正在监控 / 抓取 / 录制、
        却已不在设备列表里的 serial 一律强停。处于宽限（短暂失联、仍保留勾选）的设备
        不会被误杀——它们仍留在 device_state 中。
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
            rec_gone = [s for s in list(sess.get("videos", {}).keys())
                        + list(sess.get("devaudio", {}).keys())
                        if s not in known]
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
                self.video.stop(s)
            except Exception:
                pass
            try:
                self.device_audio.stop(s)
            except Exception:
                pass

    def clear_output(self):
        self.bus.push("console", {"kind": "clear"})
        return {"ok": True}

    def clear_status(self):
        self.bus.push("status", {"type": "clear"})
        return {"ok": True}
