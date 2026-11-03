# -*- coding: utf-8 -*-
"""backend.controllers.record —— 录屏 / 投屏 / 麦克风"""

from backend.controller import (
    DeviceAudioCapture, KEY_POINTER_LOCATION, KEY_SHOW_TOUCHES, MicRecorder,
    PipeMirror, SnapMirror, _have_ffmpeg, ffmpeg_mux,
    find_player, find_scrcpy, load_prefs, os,
    plan_size, probe_player, safe_name, scrcpy_probe_info,
    ThreadPoolExecutor, time, zipfile
)

class RecordMixin:
    """录屏、投屏（scrcpy/备用）、麦克风。"""

    # overlay 键 → 界面上的名字（失败提示里点名用，避免把 pointer_location
    # 这种系统键名直接甩给用户）
    _OVERLAY_LABELS = {
        KEY_POINTER_LOCATION: "指针位置",
        KEY_SHOW_TOUCHES: "触摸圆点",
    }

    def _mic_start(self, save_dir):
        """启动电脑麦克风录音；任何一步失败都返回 (False, 人话原因)，**绝不外抛**。

        早前这里只 try 了构造函数，`MicRecorder.start()` 裸调 —— 而 start() 内部的
        `_open()` 在 `waveInOpen` 失败（无麦克风设备 / 被隐私策略禁用 / 设备被占用）
        时会抛 RuntimeError。异常一路逃出 js_api 调用，且此时 `_screen_record_start_locked`
        已把 `_rec_session` 置为非空：异常跳过 `_cancel_half_started_rec()`，会话残留
        导致之后每次「开始录屏」都被守卫判为 recording 返回 —— 录屏功能永久锁死，
        用户只能重启程序。故这里对 start() 同样兜住，并顺手清掉半初始化的实例
        （否则 `_mic` 非 None 会让下次 `_mic_start` 误报「已在录音」）。
        """
        if self._mic is not None:
            return False, "已在录音"
        try:
            self._mic = MicRecorder()
        except Exception as e:
            self._mic = None
            return False, str(e)
        try:
            ok, p = self._mic.start(save_dir)
        except Exception as e:
            try:
                self._mic.stop()
            except Exception:
                pass
            self._mic = None
            return False, str(e)
        if not ok:
            self._mic = None
            return False, p
        return True, p

    def screen_record_start(self, serial=None,
                            with_devaudio=False, with_mic=False, save_dir=None,
                            with_logcat=False, zip_on_stop=False,
                            logcat_levels=None,
                            pointer_location=True, show_touches=True):
        """启动录屏会话（可含设备音频 / 麦 / logcat）。

        整场录制由用户**手动停止**（点「停止」或关窗口），中间不需要任何操作：
        单段到 170 秒会自动接下一段（Android screenrecord 单段硬上限 180 秒），
        产物落在同一目录、按 _p2 / _p3 顺序命名，收尾时一并打包。早年的
        「固定时长」（到点结束整场录制）已移除，与自动分段不是一回事。
        _rec_lock 保护整个会话生命周期，与 screen_record_stop / shutdown
        互斥：连点 start、start 与 stop 撞车，都不会再出现会话引用被覆盖、
        漏停漏合成的情况。内部实现见 _screen_record_start_locked。

        logcat_levels：历史参数，已不生效 —— 录屏配套的 logcat 现在**一律全量**
        （`-b all` + 不过滤级别），见下方抓取调用的说明。保留形参只为兼容旧调用方
        （以及留一条接回「按级别抓」的口子），界面上的级别勾选已撤掉。

        with_devaudio / with_mic：同理保留但界面已撤掉 —— 设备端 tinycap 探测与
        ffmpeg 合成两条链路都没做完，开关留着只会让人以为录出来的是有声视频。

        pointer_location：录屏画面常驻指针准星（设备系统设置
        `settings put system pointer_location 1`，画面 overlay，全版本可用；
        停止录屏时自动恢复设备原值）。
        show_touches：开启系统「显示触摸操作」（`settings put system
        show_touches 1`）——触摸时屏幕出现圆点轨迹，回顾录像时能直观看到
        操作轨迹；停止录屏时恢复设备原值。

        整体兜底：启动链路上任何**未预期异常**（不是各服务返回的 ok=False，
        而是真正的抛出）都必须转化为 ok=False + 撤销半启动会话。否则
        `_rec_session` 已置非空、异常又跳过撤销逻辑，之后每次「开始录屏」
        都会被守卫判为「已在录制」而永远无法开始（只能重启程序），前端也只
        看到一次调用失败、没有任何解释。
        """
        with self._rec_lock:
            try:
                return self._screen_record_start_locked(
                    serial, with_devaudio, with_mic, save_dir,
                    with_logcat, zip_on_stop, logcat_levels,
                    pointer_location, show_touches)
            except Exception as ex:
                # 仅撤销「本次调用自己创建的」会话：异常发生时 _rec_session 必然
                # 是刚建的那份（守卫保证进入前它一定为空），撤销它不会误伤他人。
                self._cancel_half_started_rec()
                self._push_toast(
                    "err", "⚠ 录屏启动出现异常：%s（已自动撤销，可重试）" % ex)
                return {"ok": False, "reason": "start_error", "error": str(ex)}

    def _screen_record_start_locked(self, serial=None,
                                    with_devaudio=False, with_mic=False,
                                    save_dir=None, with_logcat=False,
                                    zip_on_stop=False, logcat_levels=None,
                                    pointer_location=True, show_touches=True):
        # 守卫：已有录制会话进行中，避免重复点击覆盖会话引用导致漏停/漏合成
        if self._rec_session:
            # 已经在录、用户又点了一次「开始」：旧实现只回一个 reason 就返回，
            # 前端把它原样拼进提示，用户看到的是「⚠ 录屏未能启动（recording）」
            # —— 一句英文机器码，既没说清现在到底在不在录，也没给出下一步。
            # 这里给一句人话：正在录几台、想重开该先停。
            n = len(self._rec_session.get("videos") or {})
            msg = "正在录屏中%s，如需重新开始请先点「停止录屏」" % (
                "（%d 台设备）" % n if n > 1 else "")
            self._push_status("info", "ℹ " + msg)
            return {"ok": False, "reason": "recording", "message": msg}
        serials = self._target_serials(serial)
        if not serials:
            self._push_status("err", "⚠ 录屏前请先勾选至少一个设备。")
            return {"ok": False, "reason": "no_device"}
        save_dir = save_dir or self._default_save_dir()
        sess_ts = time.strftime("%Y%m%d_%H%M%S")
        self._rec_session = {
            "ts": sess_ts, "dir": save_dir,
            "with_devaudio": with_devaudio, "with_mic": with_mic,
            "with_logcat": bool(with_logcat), "with_zip": bool(zip_on_stop),
            "mic_path": None, "mic_started": False,
            "videos": {}, "devaudio": {},
            "logcat_captures": {},
            # 可视化 overlay 原值备份：serial -> "0"/"1"/"null"（None = delete 恢复）。
            # 只登记「本次真的要恢复」的设备；读不到原值的设备不入表（不动它）。
            "pointer_location_prev": {},
            "show_touches_prev": {},
        }
        if with_mic:
            ok, p = self._mic_start(save_dir)
            if ok:
                self._rec_session["mic_path"] = p
                self._rec_session["mic_started"] = True
            else:
                self._rec_session["mic_started"] = False
                self._push_toast("warn", "⚠ 电脑麦克风启动失败：%s" % p)
        ok_any = False

        def _spawn(s):
            """拉起单台设备：设备音频（可选）+ screenrecord。

            放进线程池是因为 `VideoRecorder.start` 内部有约 1.5 秒的「确认设备端
            screenrecord 真的活着」窗口 —— 串行时 3 台设备就是 4.5 秒以上的纯
            等待，用户点完「开始录制」界面迟迟没有「录制中」。各设备的 adb 调用
            彼此独立（服务对象内部各自加锁），并行拉起即可。会话登记 / overlay
            备份 / 状态播报仍回到主线程串行做：那些是共享状态，不能同时改。
            """
            da_tried = False
            da, da_err, remote = False, "", ""
            if with_devaudio and DeviceAudioCapture.supported(
                    self.state.adb_path, s):
                da_tried = True
                # safe_name：无线序列号含冒号，设备端路径同样需要净化，
                # 保证 adb shell 命令与后续 pull 的路径完全一致。
                remote = "/data/local/tmp/adb_rec_%s_%s_audio.wav" % (
                    safe_name(s), sess_ts)
                # 带原因版本：tinycap 在多数机型上需要 root，会立刻退出。只说
                # 「启动失败」用户不知道该 adb root 还是换台设备，最后只能放弃。
                start_ex = getattr(self.device_audio, "start_ex", None)
                if start_ex is not None:
                    da_ok, da_err = start_ex(s, remote)
                else:                       # 兼容只有 start() 的旧实现 / 替身
                    da_ok, da_err = bool(self.device_audio.start(s, remote)), ""
                da = bool(da_ok)
            # 这里**不吞异常**：真正的抛出（不是各服务返回的 ok=False）会一路
            # 冒到 screen_record_start 的兜底，把整场半启动会话撤销掉。并行化
            # 只改「等多久」，不改这条失败语义。
            ok, local = self.video.start(s, save_dir, extra_name=sess_ts)
            return s, {"da_tried": da_tried, "da": da, "da_err": da_err,
                       "remote": remote, "ok": ok, "local": local}

        spawned = {}
        errors = []
        if len(serials) <= 1:
            for s in serials:
                try:
                    rs, r = _spawn(s)
                    spawned[rs] = r
                except Exception as ex:
                    errors.append(ex)
        else:
            # 上限 4：再多设备同时拉起也挤在同一条 adb server 通道上。
            with ThreadPoolExecutor(max_workers=min(4, len(serials))) as pool:
                futures = [pool.submit(_spawn, s) for s in serials]
            # 出了 with 所有任务都已结束，这里逐个取结果：先攒异常、不急着抛，
            # 否则已启动的那几台还没来得及登记就被撤销流程漏掉（见下）。
            for f in futures:
                try:
                    rs, r = f.result()
                    spawned[rs] = r
                except Exception as ex:
                    errors.append(ex)

        if errors:
            # 有设备抛了真异常 → 整场会话撤销（与串行时代一致）。但异常可能发生在
            # 「另外几台已经启动成功」之后，撤销流程只停**会话里登记过**的设备；
            # 不先把它们登进去，那几台的 screenrecord 就成了孤儿，一直录到系统
            # 180 秒上限，界面还看不到任何「录制中」。
            for s in serials:
                r = spawned.get(s) or {}
                if r.get("da"):
                    self._rec_session["devaudio"][s] = r["remote"]
                if r.get("ok"):
                    self._rec_session["videos"][s] = r["local"]
            raise errors[0]

        for s in serials:
            r = spawned[s]
            da = r["da"]
            if da:
                self._rec_session["devaudio"][s] = r["remote"]
            elif r["da_tried"]:
                self._push_toast(
                    "warn", "⚠ 设备 %s 音频采集未启动：%s"
                            "（本次录屏不含设备声音）"
                            % (s, r["da_err"] or "未知原因"))
            ok, local = r["ok"], r["local"]
            if ok:
                ok_any = True
                self._rec_session["videos"][s] = local
                # 可视化 overlay：录屏真的起来了才开（并在收尾时恢复原值）。
                # 开失败不阻断录屏——可视化是增强，不是必需品。
                if pointer_location:
                    self._enable_overlay(
                        s, KEY_POINTER_LOCATION, "pointer_location_prev")
                if show_touches:
                    self._enable_overlay(s, KEY_SHOW_TOUCHES, "show_touches_prev")
                self._push_status(
                    "info", "录屏: %s%s" % (s, "（含设备音频）" if da else ""))
            else:
                self._push_status("err", "⚠ 录屏启动失败 %s: %s" % (s, local))
        # 同步抓取 logcat（走落盘抓取路径，避免占用实时监控渲染管线）
        if with_logcat:
            started_caps = 0
            for s in serials:
                # safe_name：无线序列号含冒号，Windows 下文件名非法
                lp = os.path.join(
                    save_dir, "logcat_%s_%s.txt" % (safe_name(s), sess_ts))
                # 只有「本次录屏真的启动了这条抓取」才登记进会话。
                # 用户若已手动开着同一台设备的 Logcat 抓取，start() 会返回 False
                # （落在另一个文件上）；旧实现无视返回值照样登记，停止录屏时又把
                # 那条手动抓取一并 stop 掉 —— 用户的抓取被静默掐断，而录屏承诺的
                # txt 还因文件从未创建而不进 zip。
                #
                # 缓冲区用 `-b all`、级别不过滤（level_filter=None）：录屏配套的
                # logcat 是「事后复现问题」的唯一物证，缺一条就可能正好缺在案发现
                # 场上。曾按 main/system/events/crash 四缓冲 + 界面级别勾选抓，
                # 结果是 radio 日志整段不见、用户少勾一级就丢掉整类线索，且事后
                # 无法补救（录屏已经停了）。这里的取舍是「宁可文件大一点」。
                if self.logcat_capture.start(
                        s, lp, ["all"], level_filter=None):
                    self._rec_session["logcat_captures"][s] = lp
                    started_caps += 1
                else:
                    self._push_status(
                        "warn", "⚠ %s 已有 logcat 抓取在进行，本次录屏未重复抓取" % s)
            # 只在**真的**起来了至少一条时才播报。原来无条件推「已同步开始
            # logcat 抓取」：设备上已有抓取在跑时一条都没起，用户却被告知
            # 日志已在抓，直到停止录屏、打开产物包才发现里面没有 txt ——
            # 事后复现问题唯一的物证就这么无声地缺了。
            if started_caps:
                self._push_status(
                    "info", "已同步开始 logcat 抓取（全部缓冲区 + 全部级别，随录屏停止）")
            elif ok_any:
                self._push_status(
                    "warn", "⚠ 本次录屏没有附带 logcat：%d 台设备均已存在进行中的抓取，"
                            "录制产物里不会有日志文件" % len(serials))
        if not ok_any:
            # 全部设备启动失败：撤销本会话残留（麦 / 设备音频 / 同步 logcat
            # 可能已启动）。若不清理，前端看不到「录制中」也就点不到停止，残留
            # 的麦克风/设备端 tinycap 会一直录到程序关闭。
            self._cancel_half_started_rec()
            self._push_status(
                "err", "⚠ 录屏未能启动：已自动撤销本会话，请检查设备与目录权限后重试。")
            return {"ok": False, "reason": "start_failed"}

        return {"ok": ok_any, "mic": self._rec_session.get("mic_path"),
                "ts": sess_ts}

    def _cancel_half_started_rec(self):
        """撤销「启动失败 / 启动异常」的录屏会话残留（须在持有 _rec_lock 时调用）。

        语义是「把本次会话已启动的一切全部收掉」：设备音频、电脑麦克风、同步
        logcat 抓取，以及**已启动的录屏**。早前只管前三项，那是因为唯一的调用
        路径（`if not ok_any`）按定义不可能有视频启动成功；现在启动异常兜底
        （screen_record_start 的 except）也可能在「部分设备的 video.start 已
        成功之后」才炸，不补收视频就会留下设备端 screenrecord 一直录到 Android
        自带的 3 分钟上限、界面却没有任何「录制中」提示的孤儿会话。
        """
        sess = self._rec_session or {}
        for s in list(sess.get("videos", {}).keys()):
            try:
                self.video.stop(s)
            except Exception:
                pass
        for s in list(sess.get("devaudio", {}).keys()):
            try:
                self.device_audio.stop(s)
            except Exception:
                pass
        if self._mic is not None:
            try:
                self._mic.stop()
            except Exception:
                pass
            self._mic = None
        for s in list(sess.get("logcat_captures", {}).keys()):
            try:
                self.logcat_capture.stop(s, zip_on_stop=False)
            except Exception:
                pass
        self._restore_overlays(sess)
        self._rec_session = {}

    def _enable_overlay(self, serial, key, prev_field):
        """打开设备端 overlay（指针位置 / 触摸圆点），原值备份进会话（须持 _rec_lock）。

        读不到原值（adb 瞬断）时**不入表**：没有备份就不恢复，
        胜过把用户原来的 "0" 误删成默认——防错优先于功能完整。

        写失败要说出来：`settings put` 被系统策略拒绝时通常**不返回非零**
        （SecurityException 打在 stdout 上），旧实现直接丢掉返回值 —— 用户勾了
        「指针位置」，录完回放才发现画面里既没准星也没圆点，而全程零提示。
        """
        ok, old = self.video.get_system_setting(self.state.adb_path, serial, key)
        if not ok:
            return
        self._rec_session.setdefault(prev_field, {})[serial] = old
        ok, err = self._set_device_setting(serial, key, "1")
        if not ok:
            self._push_status(
                "warn", "⚠ %s 未能开启「%s」%s，本次录屏不会出现该标记"
                        % (serial, self._OVERLAY_LABELS.get(key, key),
                           "（%s）" % err if err else ""))

    def _set_device_setting(self, serial, key, value):
        """写设备 Settings.System，返回 (是否成功, 失败原因)。

        优先走带原因的 `set_system_setting_ex`；只提供旧接口
        （`set_system_setting`，回 bool）的对象照样能用，只是拿不到具体原因。
        """
        fn = getattr(self.video, "set_system_setting_ex", None)
        if fn is not None:
            return fn(self.state.adb_path, serial, key, value)
        ok = self.video.set_system_setting(
            self.state.adb_path, serial, key, value)
        return bool(ok), ""

    def _restore_overlays(self, sess):
        """把会话里备份的 pointer_location / show_touches 原值写回各设备
        （"null" → 删除该键）。

        所有收尾路径（停止 / 启动失败撤销 / 异常撤销）都必须经过这里，
        否则用户设备会一直开着 overlay——下次正常用手机时满屏准星/圆点。
        单台失败不影响其余设备（各自独立 try）。

        恢复失败**必须报**：这是唯一会让「设备状态没还回去」无声发生的地方。
        用户不会知道系统里还留着一个自己没开过的开关，而下次录制又会去读它当
        「原值」——一次失败就此固化成新默认值。
        """
        jobs = []
        for field, key in (("pointer_location_prev", KEY_POINTER_LOCATION),
                           ("show_touches_prev", KEY_SHOW_TOUCHES)):
            for s, old in ((sess or {}).get(field) or {}).items():
                jobs.append((s, key, old))
        if not jobs:
            return

        def _one(job):
            s, key, old = job
            try:
                # "null"/空 = 设备原本没设过这个键：恢复手段是删除而不是写 0，
                # 否则会在系统设置里留下一个用户从未创建过的条目。
                val = None if (old is None or str(old).strip().lower()
                               in ("null", "")) else str(old).strip()
                ok, err = self._set_device_setting(s, key, val)
            except Exception as ex:
                ok, err = False, str(ex)[:160]
            return s, key, ok, err

        # 每台设备 2 个键 = 2 次 `adb shell settings`，串行时台数一多就是成倍的
        # 等待，而这里每一条都是彼此独立的设备写操作，直接并行。播报仍回主线程。
        if len(jobs) == 1:
            results = [_one(jobs[0])]
        else:
            with ThreadPoolExecutor(max_workers=min(4, len(jobs))) as pool:
                results = list(pool.map(_one, jobs))
        for s, key, ok, err in results:
            if not ok:
                self._push_status(
                    "warn", "⚠ %s 的「%s」未能恢复原值%s，请在设备系统设置里手动关闭"
                            % (s, self._OVERLAY_LABELS.get(key, key),
                               "（%s）" % err if err else ""))

    def screen_record_stop(self):
        """停止录屏：收尾合成 / 打包 / 清理会话（与 start / shutdown 串行）。"""
        with self._rec_lock:
            return self._screen_record_stop_locked()

    def _screen_record_stop_locked(self):
        if not self._rec_session:
            # 会话已经不在了（自动收尾已跑过 / 上一轮停止还没回前端）：说一句，
            # 而不是让用户对着一个「点了没反应」的按钮反复点。这条**不算错误**，
            # 故不放进 message —— 前端按 message 弹错误 toast，会把它变成
            # 「⚠ 停止录屏失败：当前没有进行中的录屏」，明明已经停了却说失败。
            self._push_status("info", "ℹ 当前没有进行中的录屏（可能已经停止过了）")
            return {"ok": False, "reason": "no_session"}
        sess = self._rec_session
        # 整个收尾过程必须包在 try/finally 里：只要中途抛一次（例如保存目录所在
        # 磁盘掉线 → screen_service._pull_and_finish 里的 os.makedirs 抛错），
        # `self._rec_session = {}` 就永远执行不到，会话标记残留 → 之后每次点「开始
        # 录屏」都被 `_screen_record_start_locked` 的守卫判为 recording，录屏功能
        # 永久锁死且只能重启程序；异常还会逃出 js_api 调用，用户看不到任何提示。
        try:
            files, zpath = self._session_teardown(sess)
            self._push_status("info", "⏹ 录屏已停止")
            # 完成强提醒：收尾可能要拉文件 / 等设备端写 moov / 合成 / 打包，
            # 耗时以秒计，用户很可能已切去别的页签——一条汇总 toast 说清
            # 「存在哪」，明细（逐台合成/保存/打包）留在状态栏。
            # 自动分段时文件不止一个：说清「几段」，用户才对得上「我录了 8 分钟」
            # 和「目录里为什么有 3 个 mp4」。段数只数 mp4（包里还有 logcat 的 txt）。
            seg_n = len([f for f in files
                         if str(f).lower().endswith(".mp4")])
            seg_tip = "（%d 段视频）" % seg_n if seg_n > 1 else ""
            if zpath:
                self._push_toast(
                    "ok", "✓ 录屏已完成%s，产物已打包: %s" % (seg_tip, zpath))
            elif files:
                self._push_toast(
                    "ok", "✓ 录屏已完成%s：%d 个文件已保存到 %s"
                    % (seg_tip, len(files), sess.get("dir") or "保存目录"))
            return {"ok": True}
        except Exception as ex:
            self._push_toast("err", "⚠ 录屏收尾出现异常：%s" % ex)
            return {"ok": False, "reason": "stop_error", "error": str(ex)}
        finally:
            self._rec_session = {}

    def _session_teardown(self, sess):
        """录屏会话收尾主体（须在持有 _rec_lock 时调用；异常由调用方兜底）。

        返回 (产出文件列表, zip 路径或 None)，供调用方弹「已完成」汇总 toast；
        全失败的场景文件列表为空，此时明细 warn 已由内部逐条 toast。
        """
        # 可视化 overlay 必须**先于**视频收尾恢复：它们是设备系统设置，
        # 早一点恢复，用户设备就少一瞬处于「开着准星/圆点」的意外状态。
        self._restore_overlays(sess)
        # 同步 logcat 必须**先于视频收尾**下发停止（stop 本身是异步的：置停止
        # 标记 + 终止 adb，立刻返回）。视频 stop 要走「kill 设备端 → 等本地 adb
        # 退出 → 轮询设备端文件就绪 → pull」，几台设备并行也要数秒；日志若等
        # 它拉完再停，就会比视频多跑这几秒 —— 事后按时间轴对照视频找日志时，
        # 两边差出的正是案发现场那一段。
        for s in list(sess.get("logcat_captures", {}).keys()):
            try:
                self.logcat_capture.stop(s, zip_on_stop=False)
            except Exception:
                pass
        videos_map = sess.get("videos", {}) or {}
        devaudio_map = sess.get("devaudio", {}) or {}
        dead = sess.get("dead") or set()
        serials = list(videos_map.keys()) + [
            s for s in devaudio_map if s not in videos_map]
        teardown = self._teardown_devices(
            serials, dead, videos_map, devaudio_map,
            pretaken=sess.get("video_segs") or {})
        local_videos = {}
        for s, (vs, _a) in teardown.items():
            keep = [p for p in (vs or []) if p and os.path.exists(p)]
            if keep:
                local_videos[s] = keep
        local_devaudio = {s: a for s, (_v, a) in teardown.items() if a}
        mic_path = None
        if self._mic is not None:
            try:
                mic_path = self._mic.stop()
            except Exception:
                mic_path = None
            self._mic = None
        rec_files = []   # 最终要打包的产出文件
        # 「勾了麦却没声」只在麦克风**确实启动过**时才提示：启动就失败的场景
        # 上面已经 toast 过「电脑麦克风启动失败」，不再重复归因为「全程静音」。
        mic_lost = bool(sess.get("with_mic") and sess.get("mic_started")
                        and not mic_path)
        for s, vlist in local_videos.items():
            audios = []
            if local_devaudio.get(s):
                audios.append(local_devaudio[s])
            if mic_path:
                audios.append(mic_path)
            if audios and len(vlist) > 1:
                # 音频是**整场连续**的一条，视频却被切成了多段。按段切音频需要
                # 每一段的起始偏移，任何一处算错都会让后几段音画错位 —— 那比
                # 干脆没有声音更难排查。这里只把音频并进第 1 段，其余段保留为
                # 无音轨视频，并明确说出来（不说的话用户会以为是合成失败）。
                self._push_status(
                    "warn", "⚠ %s 共 %d 段：音频只并入第 1 段，其余段为无音轨视频"
                            % (s, len(vlist)))
            for idx, vlocal in enumerate(vlist):
                if audios and idx == 0:
                    final = (vlocal[:-4] + "_final.mp4") if vlocal.endswith(
                        ".mp4") else (vlocal + ".final.mp4")
                    merged = ffmpeg_mux(vlocal, audios, final)
                    if merged:
                        self._push_status("ok", "✓ 已合成音视频: %s" % merged)
                        rec_files.append(merged)
                    else:
                        # 合成失败/产出不可播放时**保留原视频**，并说清原因：
                        # 「未安装 ffmpeg」只是其中一种，音频为空、ffmpeg 过旧同样会走到这里。
                        why = "" if _have_ffmpeg() else "（未检测到 ffmpeg）"
                        self._push_toast(
                            "warn", "⚠ 合成音视频失败%s，原始视频已保存（无音轨）: %s"
                            % (why, vlocal))
                        if os.path.exists(vlocal):
                            rec_files.append(vlocal)
                else:
                    self._push_status("ok", "✓ 录屏已保存: %s" % vlocal)
                    if os.path.exists(vlocal):
                        rec_files.append(vlocal)
        if mic_lost:
            # 空录音（麦克风被占用 / 全程静音 / 无录音权限）现在会返回 None 并删除坏文件，
            # 这里明确告诉用户「为什么没有声音」，否则用户只看到成片没音轨。
            self._push_toast(
                "warn", "⚠ 未录到电脑麦克风声音（麦克风可能被占用、无权限或全程静音），"
                        "已按无音轨保存视频。")
        # 设备端音频被 pull 到 %TEMP% 的临时 wav（adb_devaudio_*.wav），唯一用途就是
        # 喂给 ffmpeg 合成；合成结束后这些文件已无用，必须清理，否则每次录屏都会在
        # TEMP 留下孤儿文件，长期累积会悄悄占满系统盘。
        for lp in local_devaudio.values():
            try:
                if lp and os.path.exists(lp):
                    os.remove(lp)
            except Exception:
                pass
        # 同步 logcat 抓取收尾：**录屏结束，日志必须同时结束**。
        # 日志的用途是事后按时间轴对照视频找问题，录像停了日志还在往下写、
        # 或者日志比视频多跑一大截，两边就对不齐了。所以这里不做任何例外：
        # 无论是用户点停止、还是录屏被意外中断，配套抓取都随会话一起停、并
        # 一并打包（视频 + 日志一体包）。意外中断的断点由抓取侧写入的
        # 「设备断开连接」缺口标记标明，分析时一眼能看出哪里缺了。
        for s, p in list(sess.get("logcat_captures", {}).items()):
            # 停止已在收尾开头下发（与视频同步），这里只等它把缓冲区写完再取
            # 文件（最多 2 秒）。抓取正在等设备重连时，stop 会立刻打断等待，
            # 不会把这段时间拖进收尾流程。
            for _ in range(20):
                if not self.logcat_capture.is_running(s):
                    break
                time.sleep(0.1)
            if self.logcat_capture.is_running(s):
                # 2 秒还没收尾（磁盘很慢 / 写盘阻塞）：绝不能把它塞进包里。
                # 打包完会删源文件，而抓取还在往这个路径写 —— 尾部会落进已删除的
                # inode：zip 里少一段、磁盘上也没有，日志就此彻底消失，且看不出来。
                # 宁可不打包，保留原 txt 并说清位置。
                self._push_toast(
                    "warn",
                    "⚠ %s 的 logcat 日志仍在收尾，未放入本次压缩包，"
                    "原文件已保留：%s" % (s, p))
                continue
            if os.path.exists(p):
                rec_files.append(p)
        # 结束录制后自动压缩为 zip（录屏 mp4 + 同步 logcat 一并打包）
        zpath = None
        if sess.get("with_zip") and rec_files:
            z = os.path.join(sess["dir"], "rec_%s.zip" % sess["ts"])
            if self._zip_paths(rec_files, z):
                zpath = z
                self._push_status("ok", "✓ 录制产物已打包: %s" % zpath)
        return rec_files, zpath

    def _stop_video(self, serial):
        """停止单台设备并取回**全部段**。返回 (ok, [本地路径...], err)。

        优先用 stop_ex（自动分段下会有多段）。只有旧实现 / 测试替身才退化为
        stop()，那时只可能有一段。
        """
        fn = getattr(self.video, "stop_ex", None)
        if fn is not None:
            return fn(serial)
        # 旧 stop() 只有「路径」一个出口，失败时它可能带回来的是**残片**（缺 moov
        # 的半截 mp4）。这里不能把它当成「已正常收尾的段」放进列表：那会让残片
        # 混进压缩包，用户拿到一个播放不了的文件却分不出是哪个、为什么。路径改
        # 由 err 带出去，信息不少一条，但不会被当成成品。
        ok, lp, err = self.video.stop(serial)
        if ok:
            return True, ([lp] if lp else []), err
        if lp:
            return False, [], "%s（残片：%s）" % (err or "收尾失败", lp)
        return False, [], err

    def _teardown_devices(self, serials, dead, videos_map, devaudio_map,
                          pretaken=None):
        """逐设备收尾（拉视频 + 拉设备端音频），**多台设备并行**。

        单台设备的 stop 要走「kill 设备端进程 → 等本地 adb 退出 → 轮询设备端
        文件就绪 → pull」，而 _pull_and_finish 在设备端根本没生成文件时会把
        6 次退避全部走完（约 9 秒）；设备端音频那条链同理（tinycap 的 wav 也
        要等落盘）。串行时这些等待会被乘以台数：5 台设备点「停止」，要 40 秒
        以上才见到「录屏已完成」，其间 _rec_lock 一直被占着，别的录屏动作全
        排不上。各设备之间是彼此独立的 adb 调用、没有共享状态，直接并行。

        返回 {serial: (本地视频路径列表, 本地音频路径或 None)}。列表是因为自动
        分段：一台设备的一场录制会有多段（每段约 170 秒），每一段都要落盘、合成
        与打包，只留最后一段等于把前几段直接扔掉。逐台兜住异常：一台收尾炸了
        不该让其余设备连文件都拉不回来。
        """
        def one(s):
            local_vs = []
            if s in videos_map:
                if self.video.is_recording(s):
                    ok, paths, err = self._stop_video(s)
                    paths = [p for p in (paths or []) if p]
                    if ok:
                        local_vs = paths
                        if err:
                            # 有段没取回来、当前段却是好的：不能静默。用户以为
                            # 录了 8 分钟，包里只有 5 分钟，缺的那 3 分钟他会以为
                            # 是「本来就没发生」。
                            self._push_toast(
                                "warn", "⚠ %s 部分分段未取回：%s" % (s, err))
                    else:
                        # paths 里全是**已正常收尾**的段（残片只在 err 里说明），
                        # 必须整体保留：只报一句「收尾失败」会让用户把前面几段
                        # 本来完好的视频一并扔掉。
                        local_vs = paths
                        where = ""
                        kept = ("已完成的 %d 段完整保留：%s。"
                                % (len(local_vs),
                                   "、".join(os.path.basename(x)
                                             for x in local_vs))
                                if local_vs else "")
                        if s in dead:
                            # 进程意外死亡（续段失败 / adb root 等）：文案说清
                            # 「视频不完整」，与普通收尾失败区分开。
                            self._push_toast(
                                "warn",
                                "⚠ %s 录屏被意外中断，这一段视频不完整（%s）。"
                                "%s%s未合成音频。"
                                % (s, err or "设备端进程已提前退出",
                                   where or "残片已保留在保存目录，", kept))
                        else:
                            self._push_toast(
                                "warn", "⚠ 录屏收尾失败 %s：%s%s%s"
                                        % (s, err or "未知原因", where, kept))
                else:
                    # 会话已被其他路径收尾弹出（stop_all / 异常清理 / 设备被移除后
                    # 强停）时，这里再用 stop() 只会得到「该设备未在录制」。必须用
                    # 之前记录的路径兜底，否则这段视频既不合成音频、也不进 zip、
                    # 界面也无提示。pretaken 是「设备被移除时已经取回的那几段」，
                    # 没有它就只能拿到第一段。
                    local_vs = list((pretaken or {}).get(s) or [])
                    if not local_vs:
                        first = videos_map.get(s)
                        local_vs = [first] if first else []
            local_a = None
            if s in devaudio_map:
                try:
                    local_a = self.device_audio.stop(s)
                except Exception as e:
                    # 音频收尾失败不能连累视频落盘，也不能让整轮收尾中断
                    self._push_status(
                        "warn", "⚠ %s 设备音频收尾失败：%s" % (s, e))
                    local_a = None
            return s, (local_vs, local_a)

        if len(serials) <= 1:
            return dict(one(s) for s in serials)
        # 上限 4：再多的设备同时 pull 也挤在同一条 adb server 通道上，
        # 并发度拉满只会让每条都变慢，还平白多占内存。
        with ThreadPoolExecutor(max_workers=min(4, len(serials))) as pool:
            return dict(pool.map(one, serials))

    # 已经压缩过的容器格式：再走 DEFLATE 只烧 CPU，几乎不减小体积。
    _PRECOMPRESSED_EXT = {
        ".mp4", ".m4a", ".m4v", ".mov", ".mkv", ".webm",
        ".mp3", ".aac", ".wav", ".ogg",
        ".jpg", ".jpeg", ".png", ".webp", ".gif",
        ".zip", ".gz", ".xz", ".7z",
    }

    @staticmethod
    def _zip_method_for(path):
        """按文件类型选 zip 压缩方式：已压缩的存（STORED），文本类才压。"""
        ext = os.path.splitext(path or "")[1].lower()
        if ext in RecordMixin._PRECOMPRESSED_EXT:
            return zipfile.ZIP_STORED
        return zipfile.ZIP_DEFLATED

    @staticmethod
    def _zip_paths(paths, zip_path):
        """把若干文件打包为一个 zip（以文件名作条目）。失败返回 None。

        打包**完整写出成功后**清理源文件（仅清理本次实际写入 zip 的普通文件，
        目录 / zip 自身 / 写入失败未进包的文件都不会被删）——与 README 承诺的
        「打包完成后清理刚打包的源文件（仅删打包所覆盖的文件）」保持一致。
        """
        written = []
        try:
            if os.path.exists(zip_path):
                os.remove(zip_path)
            with zipfile.ZipFile(zip_path, "w") as z:
                for p in paths:
                    if (p and p != zip_path and os.path.exists(p)
                            and os.path.isfile(p)):
                        # 视频/音频/图片本来就已经压缩过（H.264/AAC/PNG），
                        # 再走 DEFLATE 只是把整个文件白算一遍：3 分钟的 1080p
                        # 录屏能白白多花一两秒 CPU，体积却几乎不变。体积真正
                        # 能压下来的是 logcat 的 txt，那类仍用 DEFLATE。
                        z.write(p, os.path.basename(p),
                                compress_type=RecordMixin._zip_method_for(p))
                        written.append(p)
            if not os.path.exists(zip_path):
                return None
        except Exception:
            # 打包中途失败：清掉可能残留的半成品 zip，源文件一律保留
            try:
                if os.path.exists(zip_path):
                    os.remove(zip_path)
            except Exception:
                pass
            return None
        for p in written:
            try:
                os.remove(p)
            except Exception:
                pass
        return zip_path

    def _scrcpy_pref_path(self):
        """用户配置的 scrcpy 路径（读失败一律当空 = 走自动探测）。"""
        try:
            return str(load_prefs().get("scrcpy_path") or "")
        except Exception:
            return ""

    def scrcpy_probe(self):
        """探测本机 scrcpy（工具页初始化 / 「重新检测」按钮）。

        返回 {ok, path, version, note}：
          * ok=False 时 note 是可执行的安装建议（不是一句"未找到"）；
          * ok=True 时 path/version 直接显示在界面上，用户能确认用的是哪一份。
        """
        return scrcpy_probe_info(self._scrcpy_pref_path())

    def scrcpy_start(self, serial=None):
        """对勾选（或指定）设备各开一个 scrcpy 投屏窗口。

        一台设备一个窗口（scrcpy 的限制：一个实例只能投一台设备）。
        已在投屏的设备不重复开窗；秒退的（未授权 / 版本不兼容 / adb 报错）
        把 scrcpy 自己的报错回显到状态栏，而不是让窗口一闪而过、用户以为没反应。
        """
        serials = self._target_serials(serial)
        if not serials:
            self._push_status("err", "⚠ 投屏前请先勾选至少一台设备。")
            return {"ok": False, "reason": "no_device"}
        exe, note = find_scrcpy(self._scrcpy_pref_path())
        if not exe:
            self._push_status("warn", "⚠ " + note)
            return {"ok": False, "reason": "scrcpy_not_found", "note": note}
        try:
            res = self._scrcpy.launch(serials, exe)
        except Exception as ex:
            self._push_toast("err", "⚠ 投屏启动出现异常：%s" % ex)
            return {"ok": False, "reason": "start_error", "error": str(ex)}
        started = res["started"]
        skipped = res["skipped"]
        failed = res["failed"]
        if started:
            self._push_status("ok", "✓ 已开启投屏：%s" % "、".join(started))
        if skipped:
            self._push_status("info", "ℹ 已在投屏中：%s" % "、".join(skipped))
        for s, reason in failed:
            self._push_status("err", "⚠ %s 投屏失败：%s" % (s, reason))
        return {
            "ok": bool(started or skipped),
            "path": exe,
            "started": started,
            "skipped": skipped,
            "failed": [{"serial": s, "reason": r} for s, r in failed],
        }

    def _mirror_prefs(self):
        """备用投屏相关配置（读失败一律回退默认值，不让界面卡在异常上）。"""
        try:
            p = load_prefs()
        except Exception:
            p = {}
        return {
            "player_path": str(p.get("mirror_player_path") or ""),
            "size": str(p.get("mirror_size") or ""),
            "bitrate": int(p.get("mirror_bitrate") or 8),
            "fps": int(p.get("mirror_fps") or 2),
        }

    def mirror_probe(self):
        """探测本机投屏能力：scrcpy 与播放器各自的可用状态。

        前端据此决定「备用投屏」按钮的提示文案——有 scrcpy 就主推 scrcpy，
        没有但有播放器就说明会用播放器窗口，两者都没有则预告会退化成低帧率预览。
        """
        return {
            "scrcpy": scrcpy_probe_info(self._scrcpy_pref_path()),
            "player": probe_player(self._mirror_prefs()["player_path"]),
        }

    def _on_mirror_error(self, serial, error):
        """后台转发/抓帧线程结束回调：只报真错误，并把设备从登记表摘掉。

        摘掉是必要的：不摘的话这台设备会一直显示「投屏中」，用户再点一次
        按钮会因为「已在投屏」被跳过，永远开不起来。
        """
        if error:
            self._push_status("err", "⚠ %s 投屏已中断：%s" % (serial, error))
        self._mirror_pipes.pop(serial, None)
        self._mirror_snaps.pop(serial, None)

    def _mirror_live(self, serial):
        """取该设备仍存活的投屏对象；登记表里只剩「已死」的条目时顺手摘掉。

        为什么要摘：后台链路收尾回调（_on_mirror_error）与「启动成功后登记」
        之间有竞态 —— 回调可能先到（此时还没登记，pop 不到任何东西），随后
        start() 才把已死的实例登记进来。之后每次点「投屏」都被判成「已在投屏中」
        跳过，而状态里又看不到任何在投设备，用户只能重启程序。
        调用方需持有 _mirror_lock（本方法只读表 + 摘死条目，不自己加锁）。
        """
        for table in (self._mirror_pipes, self._mirror_snaps):
            m = table.get(serial)
            if m is None:
                continue
            try:
                alive = bool(m.alive())
            except Exception:
                alive = False          # 探活本身抛错 = 当作已死，让用户能重开
            if alive:
                return m
            table.pop(serial, None)    # 死条目摘掉，腾出「可重开」的位置
        return None

    def _start_one_mirror(self, serial, pref, mode):
        """对单台设备按 mode 逐级降级地开投屏，返回 {mode, frame_url} 或 {error}。

        降级顺序（只走到第一个能用为止）：
          scrcpy（仅 auto） → screenrecord 管道给播放器 → screencap 低帧率预览
        """
        if mode == "auto":
            exe, _note = find_scrcpy(self._scrcpy_pref_path())
            if exe:
                try:
                    res = self._scrcpy.launch([serial], exe)
                except Exception as ex:
                    res = {"started": [], "skipped": [], "failed": [(serial, str(ex))]}
                if res["started"] or res["skipped"]:
                    return {"mode": "scrcpy", "frame_url": ""}
                # 起不来（未授权 / 版本不兼容）→ 继续往下降级，别轻易放弃

        if mode in ("auto", "pipe"):
            kind, exe, note = find_player(pref["player_path"])
            if exe:
                size = pref["size"] or plan_size(self.state.adb_path, serial)
                m = PipeMirror(self.state.adb_path, serial, kind, exe, size,
                               pref["bitrate"], 60,
                               on_status=self._on_mirror_error,
                               rec_guard=self.video.any_recording)
                ok, err = m.start()
                if ok:
                    self._mirror_pipes[serial] = m
                    return {"mode": "pipe", "frame_url": "", "player": exe,
                            "size": size}
                pipe_err = err
            else:
                pipe_err = note
        else:
            pipe_err = ""

        # 兜底：只要 adb 能截图就一定有画面（帧率很低，但不会「点了没反应」）
        if not self._frame_server.start():
            return {"error": pipe_err or "帧服务启动失败（本地回环端口不可用）"}
        m = SnapMirror(self.state.adb_path, serial, self._frame_server,
                       pref["fps"], on_status=self._on_mirror_error)
        ok, err = m.start()
        if ok:
            self._mirror_snaps[serial] = m
            return {"mode": "snap", "frame_url": self._frame_server.frame_url(serial),
                    "note": pipe_err}
        return {"error": err or "低帧率预览也启动失败"}

    def mirror_start(self, serial=None, mode="pipe"):
        """开启备用投屏（一台设备一个画面源）。

        mode：
          * "auto" —— scrcpy → 管道 → 低帧率预览，逐级降级；
          * "pipe" —— 管道 → 低帧率预览（主按钮已单独负责 scrcpy，故默认不含它）；
          * "snap" —— 只用低帧率预览。
        """
        serials = self._target_serials(serial)
        if not serials:
            self._push_status("err", "⚠ 投屏前请先勾选至少一台设备。")
            return {"ok": False, "reason": "no_device"}
        pref = self._mirror_prefs()
        started, skipped, failed = [], [], []
        for s in serials:
            # 查重与占位必须在同一把锁里完成：_start_one_mirror 是**同步**的
            # （等首帧最长 6s），期间登记表里还没有这台设备。连点两次的间隙
            # 足以让两条 js_api 调用都通过查重，各自拉起一个播放器窗口 + 一条
            # 设备端 screenrecord，互相抢 adb 输入。
            with self._mirror_lock:
                busy = (self._mirror_live(s) is not None
                        or s in self._mirror_starting)
                if not busy:
                    self._mirror_starting.add(s)
            if busy:
                skipped.append(s)
                continue
            try:
                res = self._start_one_mirror(s, pref, mode)
            except Exception as ex:
                res = {"error": str(ex)}
            finally:
                with self._mirror_lock:
                    self._mirror_starting.discard(s)
            if res.get("mode"):
                started.append({"serial": s, "mode": res["mode"],
                                "frame_url": res.get("frame_url") or ""})
            else:
                failed.append({"serial": s, "reason": res.get("error") or "未知原因"})

        label = {"scrcpy": "scrcpy 窗口", "pipe": "播放器窗口（screenrecord 管道）",
                 "snap": "低帧率预览（screencap 轮询）"}
        if started:
            self._push_status("ok", "✓ 已开启投屏：" + "、".join(
                "%s（%s）" % (x["serial"], label.get(x["mode"], x["mode"]))
                for x in started))
        for x in failed:
            self._push_status("err", "⚠ %s 投屏失败：%s" % (x["serial"], x["reason"]))
        if skipped:
            self._push_status("info", "ℹ 已在投屏中：%s" % "、".join(skipped))
        return {"ok": bool(started or skipped), "started": started,
                "skipped": skipped, "failed": failed}

    def mirror_stop(self, serial=None):
        """停止备用投屏（管道 / 低帧率预览），不含 scrcpy 窗口（由用户自己关）。"""
        targets = self._target_serials(serial)
        stopped = []
        for s, m in list(self._mirror_pipes.items()):
            if targets and s not in targets:
                continue
            try:
                m.stop()
            except Exception:
                pass
            self._mirror_pipes.pop(s, None)
            stopped.append(s)
        for s, m in list(self._mirror_snaps.items()):
            if targets and s not in targets:
                continue
            try:
                m.stop()
            except Exception:
                pass
            self._mirror_snaps.pop(s, None)
            stopped.append(s)
        if stopped:
            self._push_status("info", "ℹ 已停止投屏：%s" % "、".join(stopped))
        return {"ok": True, "stopped": stopped}

    def mirror_status(self):
        """当前备用投屏状态（前端用来刷新按钮与预览区可见性）。"""
        with self._mirror_lock:
            # 顺便剪掉已死的条目：前端每次都调这个接口，下一次就不会再显示
            # 「投屏中」而按钮却被跳过（见 _mirror_live 的说明）。
            return {
                "pipe": [s for s in list(self._mirror_pipes)
                         if self._mirror_live(s) is not None],
                "snap": [s for s in list(self._mirror_snaps)
                         if self._mirror_live(s) is not None],
            }
