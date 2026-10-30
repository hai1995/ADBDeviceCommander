# -*- coding: utf-8 -*-
"""backend.controllers.record —— 录屏 / 投屏 / 麦克风"""

from backend.controller import (
    DeviceAudioCapture, KEY_POINTER_LOCATION, KEY_SHOW_TOUCHES, MicRecorder,
    PipeMirror, SnapMirror, _have_ffmpeg, ffmpeg_mux,
    find_player, find_scrcpy, load_prefs, os,
    plan_size, probe_player, safe_name, scrcpy_probe_info,
    time, zipfile
)

class RecordMixin:
    """录屏、投屏（scrcpy/备用）、麦克风。"""

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

        录屏一律**手动停止**（点「停止」或关窗口）：早期支持过「固定时长」，
        但实际使用中手动停止更直观，该选项已移除。
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
            return {"ok": False, "reason": "recording"}
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
        for s in serials:
            da = False
            if with_devaudio and DeviceAudioCapture.supported(
                    self.state.adb_path, s):
                # safe_name：无线序列号含冒号，设备端路径同样需要净化，
                # 保证 adb shell 命令与后续 pull 的路径完全一致。
                remote = "/data/local/tmp/adb_rec_%s_%s_audio.wav" % (
                    safe_name(s), sess_ts)
                if self.device_audio.start(s, remote):
                    self._rec_session["devaudio"][s] = remote
                    da = True
                else:
                    self._push_toast("warn", "⚠ 设备 %s 音频采集启动失败" % s)
            ok, local = self.video.start(s, save_dir, extra_name=sess_ts)
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
                else:
                    self._push_status(
                        "warn", "⚠ %s 已有 logcat 抓取在进行，本次录屏未重复抓取" % s)
            self._push_status(
                "info", "已同步开始 logcat 抓取（全部缓冲区 + 全部级别，随录屏停止）")
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
        """
        ok, old = self.video.get_system_setting(self.state.adb_path, serial, key)
        if not ok:
            return
        self._rec_session.setdefault(prev_field, {})[serial] = old
        self.video.set_system_setting(self.state.adb_path, serial, key, "1")

    def _restore_overlays(self, sess):
        """把会话里备份的 pointer_location / show_touches 原值写回各设备
        （"null" → 删除该键）。

        所有收尾路径（停止 / 启动失败撤销 / 异常撤销）都必须经过这里，
        否则用户设备会一直开着 overlay——下次正常用手机时满屏准星/圆点。
        单台失败不影响其余设备（各自独立 try）。
        """
        for field, key in (("pointer_location_prev", KEY_POINTER_LOCATION),
                           ("show_touches_prev", KEY_SHOW_TOUCHES)):
            for s, old in ((sess or {}).get(field) or {}).items():
                try:
                    # "null"/空 = 设备原本没设过这个键：恢复手段是删除而不是写 0，
                    # 否则会在系统设置里留下一个用户从未创建过的条目。
                    val = None if (old is None or str(old).strip().lower()
                                   in ("null", "")) else str(old).strip()
                    self.video.set_system_setting(self.state.adb_path, s, key, val)
                except Exception:
                    pass

    def screen_record_stop(self):
        """停止录屏：收尾合成 / 打包 / 清理会话（与 start / shutdown 串行）。"""
        with self._rec_lock:
            return self._screen_record_stop_locked()

    def _screen_record_stop_locked(self):
        if not self._rec_session:
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
            if zpath:
                self._push_toast("ok", "✓ 录屏已完成，产物已打包: %s" % zpath)
            elif files:
                self._push_toast(
                    "ok", "✓ 录屏已完成：%d 个文件已保存到 %s"
                    % (len(files), sess.get("dir") or "保存目录"))
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
        local_videos = {}
        dead = sess.get("dead") or set()
        for s in list(sess.get("videos", {}).keys()):
            local = None
            if self.video.is_recording(s):
                ok, lp, err = self.video.stop(s)
                if ok:
                    local = lp
                elif s in dead:
                    # 进程意外死亡（adb root 等）：文案说清「视频不完整」，
                    # 与普通收尾失败区分开（用户据此知道该重录，而不是怀疑程序坏了）。
                    self._push_toast(
                        "warn",
                        "⚠ %s 录屏被意外中断，视频不完整（%s）。残片已保留在保存目录，"
                        "音频未合成；请完整重录。" % (s, err or "设备端进程已提前退出"))
                else:
                    self._push_toast(
                        "warn", "⚠ 录屏收尾失败 %s：%s" % (s, err or "未知原因"))
            else:
                # 会话已被其他路径收尾弹出（stop_all / 异常清理等）时，
                # 这里再用 stop() 只会得到「该设备未在录制」。必须用启动时记录的
                # 本地路径兜底，否则这段视频既不合成音频、也不进 zip、界面也无提示。
                local = sess.get("videos", {}).get(s)
            if local and os.path.exists(local):
                local_videos[s] = local
        local_devaudio = {}
        for s in list(sess.get("devaudio", {}).keys()):
            lp = self.device_audio.stop(s)
            if lp:
                local_devaudio[s] = lp
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
        for s, vlocal in local_videos.items():
            audios = []
            if local_devaudio.get(s):
                audios.append(local_devaudio[s])
            if mic_path:
                audios.append(mic_path)
            if audios:
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
        # 同步停止 logcat 抓取，等待写盘后收集 txt
        for s, p in sess.get("logcat_captures", {}).items():
            try:
                self.logcat_capture.stop(s, zip_on_stop=False)
            except Exception:
                pass
            for _ in range(20):
                if not self.logcat_capture.is_running(s):
                    break
                time.sleep(0.1)
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
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
                for p in paths:
                    if (p and p != zip_path and os.path.exists(p)
                            and os.path.isfile(p)):
                        z.write(p, os.path.basename(p))
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
                               on_status=self._on_mirror_error)
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
            if s in self._mirror_pipes or s in self._mirror_snaps:
                skipped.append(s)
                continue
            try:
                res = self._start_one_mirror(s, pref, mode)
            except Exception as ex:
                res = {"error": str(ex)}
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
        return {
            "pipe": [s for s, m in self._mirror_pipes.items() if m.alive()],
            "snap": [s for s, m in self._mirror_snaps.items() if m.alive()],
        }
