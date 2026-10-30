# -*- coding: utf-8 -*-
"""backend.controllers.autorefresh —— 自动轮询与孤儿回收"""

from backend.controller import (
    AUTO_REFRESH_MS, REC_DEATH_CHECK_S, time
)

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
        self._push_toast(
            "warn",
            "⚠ 检测到录屏进程意外结束（%s）——常见原因是录屏期间执行了 adb root "
            "或设备重启了 adbd。正在自动收尾并复位界面…" % "、".join(sorted(dead)))
        # 完整收尾：停掉其余设备 / 麦 / 设备音频、恢复指针位置/触摸圆点、合成与打包
        # 照常进行（异常由 _screen_record_stop_locked 兜底并清会话）。
        self.screen_record_stop()
        # 前端复位：会话已结束，把「停止」按钮切回「开始录制」。没有这条广播，
        # 界面会一直显示「录制中」（后端停了、前端不知道）。
        self.bus.push("rec_state", {"running": False, "reason": "died"})

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
                self.logcat_capture.stop(s, zip_on_stop=False)
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
