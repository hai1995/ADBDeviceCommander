"""backend.controllers.record —— 录屏 / 投屏 / 麦克风"""

import contextlib
from typing import ClassVar

from backend.controller import (
    KEY_POINTER_LOCATION,
    KEY_SHOW_TOUCHES,
    PipeMirror,
    SnapMirror,
    ThreadPoolExecutor,
    find_player,
    find_scrcpy,
    load_prefs,
    os,
    plan_size,
    probe_player,
    safe_name,
    scrcpy_probe_info,
    shutil,
    time,
    zipfile,
)
from backend.screen_service import device_clock
from core.constants import LOGCAT_COVERAGE_WARN_S, unique_path
from core.logcat import read_time_bounds
from core.longpath import long_path, path_exists, path_isfile


def _fmt_span(sec):
    """把秒数说成人话：「24 分钟」「1 分 30 秒」「45 秒」。

    告警文案里塞一个「1440 秒」用户还得自己换算，而他要判断的恰恰是
    「我录了 34 分钟、日志只跟了 10 分钟」这种量级关系。
    """
    try:
        sec = int(max(0, sec))
    except (TypeError, ValueError):
        return "未知时长"
    if sec >= 3600:
        h, rest = divmod(sec, 3600)
        m = rest // 60
        return (f"{h:d} 小时 {m:d} 分钟") if m else (f"{h:d} 小时")
    if sec >= 60:
        m, s = divmod(sec, 60)
        return (f"{m:d} 分 {s:d} 秒") if s else (f"{m:d} 分钟")
    return f"{sec:d} 秒"


class RecordMixin:
    """录屏、投屏（scrcpy/备用）、麦克风。"""

    # overlay 键 → 界面上的名字（失败提示里点名用，避免把 pointer_location
    # 这种系统键名直接甩给用户）
    _OVERLAY_LABELS: ClassVar[dict[str, str]] = {
        KEY_POINTER_LOCATION: "指针位置",
        KEY_SHOW_TOUCHES: "触摸圆点",
    }

    # ---- 同源录制（方案 B：MF SinkWriter + WASAPI）----------------------

    def _mf_usable(self):
        """本机是否可走同源录制。非 Windows / 未编译 dll 时返回 False，
        controller 明确报错（v36 起录屏全走 MF，不再有其它兜底路径）。

        测试替身没装配 mf_capture 时也返回 False。
        """
        svc = getattr(self, "mf_capture", None)
        if svc is None:
            return False
        try:
            return bool(svc.available)
        except Exception:  # noqa: BLE001  可用性探测失败一律走兜底
            return False

    def _mf_record_start_locked(self, serial=None,
                                with_devaudio=False, with_mic=False,
                                save_dir=None, with_logcat=False,
                                zip_on_stop=False, logcat_levels=None,
                                pointer_location=True, show_touches=True):
        """同源录制启动（须持 _rec_lock）。公开 start 的签名与返回结构不变。"""
        # 守卫：录制中再次 start 会覆盖 _rec_session：第一场的 overlay 原值备份
        # 丢失、mf_capture.start_all 按 serial 顶掉旧 native 会话（旧会话再无引用、
        # 停止时不会 finalize，MP4 缺 moov、设备 overlay 无法恢复）。
        if self._rec_session:
            n = len(self._rec_session.get("videos") or {})
            msg = f"正在录屏中{f'（{n:d} 台设备）' if n > 1 else ''}，如需重新开始请先点「停止录屏」"
            self._push_status("info", "ℹ " + msg)
            return {"ok": False, "reason": "recording", "message": msg}
        serials = self._target_serials(serial)
        if not serials:
            self._push_status("err", "⚠ 录屏前请先勾选至少一个设备。")
            return {"ok": False, "reason": "no_device"}
        save_dir = save_dir or self._default_save_dir()
        sess_ts = time.strftime("%Y%m%d_%H%M%S")
        # 先探一次分辨率：用第一台设备的屏幕尺寸（同源录制 H264 直接写入，
        # 分辨率必须提前定，运行中不支持切换）。取不到用默认值 1080x1920。
        width, height = 1080, 1920
        with contextlib.suppress(Exception):
            w_h = self._mf_probe_size(serials[0])
            if w_h:
                width, height = w_h
        # H264/MP4 要求宽高为偶数，向下取偶后再传给 native 与 screenrecord。
        size = "{}x{}".format(width - width % 2, height - height % 2)
        stems = {s: f"record_{safe_name(s)}_{sess_ts}" for s in serials}
        # sizes 传字典：让所有设备都用探测到的统一分辨率（之前传 {} 导致探测
        # 结果被丢弃、native 用默认 1080x1920，与实际画面不符）。
        ok, reason, firsts = self.mf_capture.start_all(
            serials, save_dir, stems, {s: size for s in serials}, None,
            with_audio=bool(with_mic))
        if not ok:
            self._push_toast(
                "err", f"⚠ 同源录制启动失败：{reason}（本次未产生视频）")
            return {"ok": False, "reason": "mf_start_failed", "error": reason}
        # 会话结构对齐老路径：videos 登记第一段占位路径，收尾统一由 MF 产出。
        self._rec_session = {
            "ts": sess_ts, "dir": save_dir, "mf": True,
            "start_host": time.time(), "video_start_host": time.time(),
            "with_devaudio": bool(with_devaudio), "with_mic": bool(with_mic),
            "with_logcat": bool(with_logcat), "with_zip": bool(zip_on_stop),
            "mic_path": None, "mic_started": bool(with_mic),
            "videos": {s: firsts.get(s) for s in serials},
            "devaudio": {}, "logcat_captures": {},
            "pointer_location_prev": {}, "show_touches_prev": {},
        }
        # overlay 与 logcat 与老路径一致（同源录制只替换视频/音频合成）。
        for s in serials:
            if pointer_location:
                self._enable_overlay(s, KEY_POINTER_LOCATION, "pointer_location_prev")
            if show_touches:
                self._enable_overlay(s, KEY_SHOW_TOUCHES, "show_touches_prev")
        if with_logcat:
            started_caps = 0
            for s in serials:
                lp = os.path.join(save_dir, f"logcat_{safe_name(s)}_{sess_ts}.txt")
                if self.logcat_capture.start(s, lp, ["all"], level_filter=None):
                    self._rec_session["logcat_captures"][s] = lp
                    started_caps += 1
            if started_caps:
                self._push_status("info", "已同步开始 logcat 抓取（全部缓冲区 + 全部级别，随录屏停止）")
            else:
                # 一条都没起来（设备已有手动抓取在跑）：如实说明本次没有日志
                # 文件，否则用户在包里找不到日志会以为程序弄丢了。
                self._push_status(
                    "warn", f"⚠ 本次录屏没有附带 logcat：{len(serials):d} 台设备均已存在进行中的抓取，录制产物里不会有日志文件")
        # 部分设备失败：start_all 只要有一台成功就返回 ok=True，失败设备的
        # 原因被丢弃（firsts 里没有它）。旧实现这里只播「✓ 已开始」，用户以
        # 为全录上了，事后才发现少了设备素材。逐台点名失败的 serial。
        failed = [s for s in serials if s not in firsts]
        if failed:
            self._push_status(
                "err", "⚠ 同源录制：{} 台设备未能开始（{}），这几台本次没有视频；"
                       "其余设备正常录制中".format(
                           len(failed), "、".join(failed)))
        # [诊断] 附上 native DLL 构建指纹：0xC00D4A45 的多轮修复都在 native C++，
        # 必须重新编译 DLL 才生效。老 DLL 无此导出时 build_id 为空，给出明确
        # 提示，避免用户拿旧 DLL 反复测试却以为修复没用。
        with contextlib.suppress(Exception):
            bid = self.mf_capture.build_id or ""
        native_tag = (f"，native 构建 {bid}" if bid else
                      "，native 构建未知(旧DLL? 0xC00D4A45 修复需重新编译 dll)")
        audio_tag = (" + 麦克风语音由系统媒体基础合成带声 MP4" if with_mic
                     else "，纯视频 MP4（未勾选麦克风）")
        self._push_status(
            "ok", f"✓ 已开始同源录制（H264 画面{audio_tag}{native_tag}）")
        return {"ok": True, "mic": None, "ts": sess_ts,
                "started": self._rec_session["video_start_host"]}

    def _mf_probe_size(self, serial):
        """取设备屏幕尺寸 (w, h)；取不到返回 None（用默认值）。

        复用投屏的 plan_size，而不是自己解析 wm size：
          * 它只认 Physical size，忽略用户临时改的 Override；
          * **保持 wm size 的原始横竖顺序**。旧实现 `w <= h` 强行竖屏，
            横屏车机 1920x1080 会被传成 `--size 1080x1920`，编码器声明的
            尺寸与真实帧不符，既可能起不来也会产出旋转/损坏的视频；
          * 长边限制 1920：4K 车机屏直接喂给 screenrecord 编码器可能初始化
            极慢甚至失败（表现为 6s 内不出首帧）。比投屏的 1080 宽松，
            尽量保留录制画质。
        """
        try:
            size = plan_size(self.state.adb_path, serial, max_edge=1920)
            if size:
                w, h = str(size).lower().split("x")
                return int(w), int(h)
        except Exception:  # noqa: BLE001, S110  探测失败用默认值
            pass
        return None

    def _mf_teardown(self, sess):
        """同源录制收尾：停 native 会话 → logcat → 打包，返回 (文件列表, zip)。"""
        self._restore_overlays(sess)
        for s in list(sess.get("logcat_captures", {}).keys()):
            with contextlib.suppress(Exception):
                self.logcat_capture.stop(s, zip_on_stop=False)
        results = self.mf_capture.stop_all()   # {serial: ([路径], 错误)}
        files = []
        # [真失败根治 v28] 视频成片与 logcat 等附带文件分开记：完成提示必须按
        # 「有没有视频」说话，不能因为目录里还有个 logcat txt 就报「1 个文件
        # 已保存」把成片丢失伪装成成功。err 也单独收集，供上层据实上报。
        videos = []
        errors = []
        for s, (paths, err) in results.items():
            if err:
                errors.append(f"{s} {err}")
                self._push_toast("warn", f"⚠ {s} 同源录制收尾提示：{err}")
            for p in paths or []:
                if p and path_exists(p):
                    videos.append(p)
                    files.append(p)
                    self._push_status("ok", f"✓ {s} 带声视频已保存: {p}")
        sess["mf_videos"] = videos
        sess["mf_errors"] = errors
        # logcat 文件一并进产物列表
        for p in (sess.get("logcat_captures") or {}).values():
            if p and path_exists(p):
                files.append(p)
        zpath = None
        if sess.get("with_zip") and files:
            z = os.path.join(sess["dir"], "rec_{}.zip".format(sess["ts"]))
            if self._zip_paths(files, z):
                zpath = z
                self._push_status("ok", f"✓ 录制产物已打包: {zpath}")
            else:
                self._push_toast(
                    "warn", "⚠ 录制产物打包失败（文件已单独保存，可直接使用）：{}".format(
                        sess.get("dir")))
        return files, zpath

    def _mf_discard(self, sess):
        """同源录制取消：停 native 会话（不发布）+ 删 logcat。"""
        self._restore_overlays(sess)
        self.mf_capture.cancel_all()
        candidates = list((sess.get("logcat_captures") or {}).values())
        for s in list((sess.get("logcat_captures") or {}).keys()):
            with contextlib.suppress(Exception):
                self.logcat_capture.stop(s, zip_on_stop=False)
        for _ in range(20):
            if not any(self.logcat_capture.is_running(s) for s in
                       (sess.get("logcat_captures") or {})):
                break
            time.sleep(0.1)
        removed, kept, total = self._delete_files(candidates)
        return removed, kept, total


    def screen_record_start(self, serial=None,
                            with_devaudio=False, with_mic=False, save_dir=None,
                            with_logcat=False, zip_on_stop=False,
                            logcat_levels=None,
                            pointer_location=True, show_touches=True):
        """启动录屏会话（可含设备音频 / 麦 / logcat）。

        整场录制由用户**手动停止**（点「停止」或关窗口），中间不需要任何操作：
        screenrecord 单段硬上限 180 秒，程序按 170 秒自动续流，画面始终写入
        同一个 SinkWriter，收尾产出 1 个完整 MP4（无 _p2/_p3 分段、无需合并）。
        早年的「固定时长」（到点结束整场录制）已移除，与自动续流不是一回事。
        _rec_lock 保护整个会话生命周期，与 screen_record_stop / shutdown
        互斥：连点 start、start 与 stop 撞车，都不会再出现会话引用被覆盖、
        漏停漏收尾的情况。内部实现见 _mf_record_start_locked。

        logcat_levels：历史参数，已不生效 —— 录屏配套的 logcat 现在**一律全量**
        （`-b all` + 不过滤级别），见下方抓取调用的说明。保留形参只为兼容旧调用方
        （以及留一条接回「按级别抓」的口子），界面上的级别勾选已撤掉。

        with_devaudio：保留但界面已撤掉 —— 设备端 tinycap 在多数机型上需要 root，
        无法稳定承诺；开关留着只会让人以为录进去的是设备声音。
        with_mic：界面已恢复「同步录制电脑麦克风」开关（默认关闭）。录的是**本机
        麦克风**（说话声），不是电脑正在播放的声音；仅 Windows 支持。全走同源录制：
        画面（ADB 裸 H264）与麦克风（WASAPI）由系统媒体基础（Media Foundation）直接
        合成带声 MP4；未勾选时 native 走无音轨模式，产出纯视频 MP4（不录音）。
        v36 起不再有 ffmpeg / 老路径兜底，MF 不可用时明确报错。

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
                # [v36 全走 MF] 录屏不再依赖 ffmpeg：无论是否勾选麦克风都走
                # 同源录制。勾麦克风 → 带声 MP4；不勾 → native 无音轨纯视频
                # MP4（arate=0，不订阅 WASAPI、不建 AAC 轨，绝不"偷偷录音"）。
                # 长视频靠 v24 续流 + v25 单文件写成 1 个完整 MP4，无需分段合并。
                # MF 不可用（非 Windows / dll 缺失 / 被拦截）时明确报错，不再
                # 回退到已删除的 ffmpeg 兜底路径。
                if not self._mf_usable():
                    msg = ("录屏不可用：本机系统媒体基础组件（Windows Media "
                           "Foundation）不可用或未编译。请在 Windows 上使用，"
                           "并确认随包的 native 录制组件完整。")
                    self._push_toast("err", "⚠ " + msg)
                    return {"ok": False, "reason": "mf_unavailable", "error": msg}
                return self._mf_record_start_locked(
                    serial, with_devaudio, with_mic, save_dir,
                    with_logcat, zip_on_stop, logcat_levels,
                    pointer_location, show_touches)
            except Exception as ex:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
                # 仅撤销「本次调用自己创建的」会话：异常发生时 _rec_session 必然
                # 是刚建的那份（守卫保证进入前它一定为空），撤销它不会误伤他人。
                self._cancel_half_started_rec()
                self._push_toast(
                    "err", f"⚠ 录屏启动出现异常：{ex}（已自动撤销，可重试）")
                return {"ok": False, "reason": "start_error", "error": str(ex)}


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
        # 同源录制（MF）会话：画面由 native SinkWriter 落盘、麦克风由 WASAPI
        # 采集，self._mic 恒为 None、video.stop 对它无效。过去异常撤销漏了这一
        # 支：native worker（MTA 线程）、设备端 screenrecord、TEMP 裸流全部泄漏，
        # 下次 start 复用仍存活的旧 worker 导致产物错乱。对照正常 stop 的
        # _mf_teardown 与 shutdown 的 cancel_all，这里补上同一收尾。
        if sess.get("mf"):
            with contextlib.suppress(Exception):
                self.mf_capture.cancel_all()
        for s in list(sess.get("videos", {}).keys()):
            with contextlib.suppress(Exception):
                self.video.stop(s)
        for s in list(sess.get("devaudio", {}).keys()):
            with contextlib.suppress(Exception):
                self.device_audio.stop(s)
        if self._mic is not None:
            with contextlib.suppress(Exception):
                self._mic.stop()
            self._mic = None
        for s in list(sess.get("logcat_captures", {}).keys()):
            with contextlib.suppress(Exception):
                self.logcat_capture.stop(s, zip_on_stop=False)
        self._restore_overlays(sess)
        # [EDR A 方案] 半启动撤销不在撤销瞬间删工作目录（其中可能已有拉回的分段），
        # 丢弃引用、留待下次启动 sweep_workdirs 后台清理，收尾零删除。
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
                "warn", "⚠ {} 未能开启「{}」{}，本次录屏不会出现该标记".format(serial, self._OVERLAY_LABELS.get(key, key),
                           f"（{err}）" if err else ""))

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
            except Exception as ex:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
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
                    "warn", "⚠ {} 的「{}」未能恢复原值{}，请在设备系统设置里手动关闭".format(s, self._OVERLAY_LABELS.get(key, key),
                               f"（{err}）" if err else ""))

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
        # 磁盘掉线、native finalize 异常），`self._rec_session = {}` 就永远执行不到，
        # 会话标记残留 → 之后每次点「开始录屏」都被启动守卫判为 recording，录屏功能
        # 永久锁死且只能重启程序；异常还会逃出 js_api 调用，用户看不到任何提示。
        try:
            # [v36 全走 MF] 录屏收尾只有同源录制一条路径（ffmpeg 兜底已删除）。
            files, zpath = self._mf_teardown(sess)
            self._push_status("info", "⏹ 录屏已停止")
            # 完成强提醒：收尾可能要拉文件 / 等设备端写 moov / 合成 / 打包，
            # 耗时以秒计，用户很可能已切去别的页签——一条汇总 toast 说清
            # 「存在哪」，明细（逐台合成/保存/打包）留在状态栏。
            # 自动分段时文件不止一个：说清「几段」，用户才对得上「我录了 8 分钟」
            # 和「目录里到底有几个文件」。段数只数 mp4（包里还有 logcat 的 txt）。
            #
            # 合并成功的场次，目录里只剩 1 个 mp4 —— 只数文件的话这句提示会变成
            # 「1 个文件」，反而掩盖了「3 段拼接」这个事实。所以按收尾时记下的
            # merged_segs（原始段数）说话。
            mp4_n = len([f for f in files
                         if str(f).lower().endswith(".mp4")])
            merged_n = sum(int(n) for n in
                           ((sess or {}).get("merged_segs") or {}).values()
                           if n)
            if merged_n > 1:
                seg_tip = f"（{merged_n:d} 段已合并为 1 个完整视频）"
            elif mp4_n > 1:
                seg_tip = f"（{mp4_n:d} 段视频，未能合并）"
            else:
                seg_tip = ""
            # [真失败根治 v28] 同源录制（MF）一个视频成片都没落盘时，绝不能因为
            # files 里还有 logcat 的 txt 就报「✓ 录屏已完成：1 个文件已保存」——
            # 那 1 个文件是日志不是视频，用户据此以为录到了，去目录一看空的。
            # 真机 12min 长录制 finalize 超时、成片烂在 TEMP 即此症状：收尾提示
            # 只有一条尾帧超时 warn，完成提示却谎报成功。这里据实判失败。
            if sess.get("mf") and mp4_n == 0:
                errs = "; ".join(sess.get("mf_errors") or [])
                reason = errs or "native 未产出视频成片（finalize 超时或合成失败）"
                self._push_toast(
                    "err", f"⚠ 录屏失败：未保存任何视频文件（{reason}）")
                self._push_logcat_notes(sess)
                return {"ok": False, "reason": "no_video", "error": reason}
            if zpath:
                self._push_toast(
                    "ok", f"✓ 录屏已完成{seg_tip}，产物已打包: {zpath}")
            elif files:
                self._push_toast(
                    "ok", f"✓ 录屏已完成{seg_tip}：{len(files):d} 个文件已保存到 {sess.get('dir') or '保存目录'}")
            self._push_logcat_notes(sess)
            return {"ok": True}
        except Exception as ex:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
            self._push_toast("err", f"⚠ 录屏收尾出现异常：{ex}")
            return {"ok": False, "reason": "stop_error", "error": str(ex)}
        finally:
            self._rec_session = {}

    def screen_record_cancel(self):
        """取消录屏：停止并**删除**本次产生的全部文件（不打包）。

        为什么需要单独一条路径：「录错了」是常态 —— 选错设备、场景不对、只是
        想试试。在此之前用户唯一的出口是「停止」，而它会把视频打包、再告诉你
        「已完成」：几百 MB 的垃圾照样落盘，用户还得自己进目录一个个删。取消的
        语义是「这次的东西一个都不留」。

        与停止一样，会话标记必须在 finally 里清掉：任何异常都不能让它残留，
        残留即之后每次「开始录屏」都被守卫判成 recording，功能永久锁死。
        """
        with self._rec_lock:
            try:
                return self._screen_record_cancel_locked()
            except Exception as ex:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
                self._push_toast("err", f"⚠ 取消录屏出现异常：{ex}")
                return {"ok": False, "reason": "cancel_error", "error": str(ex)}
            finally:
                self._rec_session = {}

    def _screen_record_cancel_locked(self):
        """（须在持有 _rec_lock 时调用）取消并删除，返回给前端的结构。"""
        if not self._rec_session:
            # 与「停止」同一套说法：不算错误，故不带 message（前端按 message 弹
            # 错误 toast，会把「本来就没在录」说成「取消失败」）。
            self._push_status("info", "ℹ 当前没有进行中的录屏（无需取消）")
            return {"ok": False, "reason": "no_session"}
        sess = self._rec_session
        # [v36 全走 MF] 取消收尾只有同源录制一条路径（ffmpeg 兜底已删除）。
        removed, kept, total = self._mf_discard(sess)
        self._push_status("info", "🗑 录屏已取消（本次产物未保留）")
        if kept:
            # 删不掉必须说：通常是文件还被别的程序占着（播放器开着刚拉回来的
            # 那一段）。沉默地「取消成功」等于骗人 —— 文件还在磁盘上。
            self._push_toast(
                "warn", f"⚠ 已取消录屏，但有 {len(kept):d} 个文件未能删除（可能仍被其它程序占用），请手动删除：{'、'.join((os.path.basename(p) for p in kept))}")
        elif not total:
            self._push_toast("ok", "✓ 已取消录屏：本次还没有产生任何文件")
        else:
            self._push_toast(
                "ok", f"✓ 已取消录屏：本次产生的 {removed:d} 个文件已删除（未合并、未打包）")
        return {"ok": True, "removed": removed, "kept": kept}


    @staticmethod
    def _delete_files(paths):
        """删掉若干本地文件，返回 (成功删除数, 未能删除的路径列表, 去重后总数)。

        只删**普通文件**：目录一律跳过 —— 取消录屏绝不能变成一次递归删除，
        它删的只能是「本次录制产生的那些文件」。不存在的路径静默忽略（本次
        可能一段都没落盘）；单个失败不影响其余继续删（一个被播放器占着的
        mp4 不该让后面几个 txt 留在磁盘上）。
        """
        removed, kept = 0, []
        seen = set()
        for p in paths or []:
            if not p:
                continue
            try:
                key = os.path.normcase(os.path.abspath(p))
            except Exception:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
                key = p
            if key in seen:
                continue
            seen.add(key)
            try:
                if os.path.isdir(long_path(p)) or not os.path.exists(long_path(p)):
                    continue
                os.remove(long_path(p))
                removed += 1
            except Exception:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
                kept.append(p)
        return removed, kept, len(seen)

    @staticmethod
    def _in_work_dir(path, work_dir):
        """路径是否位于录制工作目录内（跨盘安全）。

        work_dir 为空 / 路径不在其中时返回 False。用它区分「工作目录里的中间
        产物」（收尾不删、留待下次启动）与「用户保存目录里的文件」（照常处理）。
        """
        if not work_dir or not path:
            return False
        try:
            p = os.path.normcase(os.path.abspath(path))
            w = os.path.normcase(os.path.abspath(work_dir))
            return os.path.commonpath([p, w]) == w
        except (ValueError, OSError):
            return False

    @staticmethod
    def _remove_intermediate(path, work_dir):
        """删一个中间产物；位于工作目录内时**跳过**（延迟到下次启动清理）。

        [EDR A 方案] 收尾瞬间对高熵 MP4 的批量 os.remove 是亚信「未授权文件
        加密」勒索检测的直接触发点（用户实测删到第 2 段就被杀）。工作目录在
        系统 TEMP，EDR 天然高容忍；留在那里由下次启动的 sweep_workdirs 后台
        递归删除，那时无活跃录制会话、不与写/改名动作相邻。work_dir 为空
        （mkdtemp 失败 / 测试替身）时退回立即删除，行为与 A 方案前一致。
        """
        if RecordMixin._in_work_dir(path, work_dir):
            return False
        with contextlib.suppress(Exception):
            if path and path_exists(path):
                os.remove(long_path(path))
                return True
        return False

    @staticmethod
    def _publish_product(path, work_dir, save_dir):
        """把工作目录里的成品 copy 回用户保存目录，返回对外路径。

        * 不在工作目录内（测试替身 / 老行为）：原样返回，零副作用；
        * 在工作目录内但未落盘：返回原路径（上层 path_exists 会过滤，不误报成功）；
        * 跨卷安全用 shutil.copy2；与项目其它产物一致走 unique_path 防覆盖；
        * 用后缀 .zip 一并占位，避免成品与后续打包 zip 抢同一 basename。
        """
        if not RecordMixin._in_work_dir(path, work_dir):
            return path
        if not path_isfile(path):
            return path
        try:
            os.makedirs(long_path(save_dir), exist_ok=True)
            dst = unique_path(os.path.join(save_dir, os.path.basename(path)),
                              suffixes=(".zip",))
            if os.path.normcase(os.path.abspath(dst)) != os.path.normcase(
                    os.path.abspath(path)):
                shutil.copy2(long_path(path), long_path(dst))
            return dst
        except Exception:  # noqa: BLE001  回拷失败保留 TEMP 路径，由上层统一上报
            return path


    def _logcat_coverage_notes(self, sess, cap_map):
        """录屏收尾时校验「配套日志有没有覆盖本次录制」，返回 [(级别, 文案)]。

        **纯提示，绝不改动产物**：txt 原样保留、该进包的照常进包，结论只写入
        `sess["logcat_notes"]`，由调用方在「✓ 录屏已完成」之后播报。

        判据只用**进程侧可验证的事实**（`LogcatCapture.capture_facts`）：
          * 抓取线程起点是否晚于录制起点（本机时钟，与设备时钟无关）；
          * 抓取过程中是否真的断过（设备掉线 / adb 意外退出 / 重连耗尽）；
          * 是否因设备不认 `-T` 回落到兼容模式（会先带出历史缓冲）。

        刻意**不再**用「设备当前时刻 − 日志最后一条时间戳」判缺口：车机没校时、
        或录制期间被人手动改过时间，都会让这个差值失真——用户实报的「只录十几秒
        却提示丢了 10 分 49 秒」正是该判据在历史缓冲场景下的假告警。设备时钟只
        用于一条独立提示（与本机差多少，对照时统一按设备时间看），不参与完整性
        判定；读不到设备时间时，上面三条事实仍照常给出结论。
        """
        jobs = [(s, p) for s, p in (cap_map or {}).items() if p]
        if not jobs:
            return []
        host_now = time.time()
        start_host = sess.get("start_host") if isinstance(sess, dict) else None

        def _one(job):
            s, p = job
            out = []
            try:
                # 长路径安全：logcat txt 落在用户的保存目录里。超长路径下
                # os.path.isfile 返回 False → 会被误报成「配套 logcat 文件不存在」。
                if not path_isfile(p):
                    # 文件不在了（保存目录被删 / 同名文件被移走）：说明本次日志
                    # 根本没落盘，别让用户以为包里那份是完整的。
                    return [("warn", "⚠ {} 的配套 logcat 文件不存在（{}），"
                                      "本次录制产物里没有该设备的日志".format(s, p))]
                _first, last = read_time_bounds(p)
                if not last:
                    return [("warn", "⚠ {} 的配套 logcat 文件里没有任何日志行"
                                      "（抓取可能一开始就被中断），"
                                      "本次日志不可用".format(s))]
                try:
                    facts = self.logcat_capture.capture_facts(s) or {}
                except Exception:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
                    facts = {}
                # ① 抓取起点晚于录制起点：录制开头那段确实没有日志。
                cap_started = facts.get("started_host")
                if start_host and cap_started:
                    try:
                        late = float(cap_started) - float(start_host)
                    except (TypeError, ValueError):
                        late = 0.0
                    if late >= LOGCAT_COVERAGE_WARN_S:
                        out.append((
                            "warn",
                            "⚠ {} 的配套 logcat 比录制开始晚约 {} 才启动，"
                            "录制开头这一段没有日志".format(s, _fmt_span(late))))
                # ② 设备不认 -T、走兼容模式：起点可能早于录制，开头可能是历史缓冲。
                # 这只是事实说明，不代表一定缺录制期间的日志（兼容模式也会继续跟流）。
                if facts.get("compat"):
                    out.append((
                        "info",
                        "ℹ {} 的 logcat 不支持从当前时刻起抓（无 -T），已回落兼容"
                        "模式：日志开头可能包含录制前的历史缓冲".format(s)))
                # ③ 真的断过（掉线 / 意外退出 / 重连耗尽）：这是唯一能确证的缺口。
                if facts.get("data_gap"):
                    out.append((
                        "warn",
                        "⚠ {} 的配套 logcat 在录制期间中断过（设备掉线 / logcat "
                        "意外退出），文件里 [logcat] 标记处存在时间缺口"
                        "（中断原因见状态信息）".format(s)))
                # 设备时钟偏差：只影响「视频文件名（本机时间）」与「日志时间戳
                # （设备时间）」的对照，与日志是否完整无关，故只做 info。
                dev = device_clock(self.state.adb_path, s, timeout=3)
                if dev:
                    dev_now, _tz_off = dev
                    skew = dev_now - host_now
                    if abs(skew) >= LOGCAT_COVERAGE_WARN_S:
                        out.append((
                            "info",
                            "ℹ {} 的设备时钟与本机相差 {}（{}），视频与日志对照时"
                            "请统一按设备时间看".format(
                                s, _fmt_span(abs(skew)),
                                "设备偏快" if skew > 0 else "设备偏慢")))
            except Exception:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
                return out
            return out

        if len(jobs) == 1:
            results = [_one(jobs[0])]
        else:
            # 每台一次 adb shell，串行在台数多时会把「已停止」拖出好几秒；
            # 各设备彼此独立，直接并行。
            with ThreadPoolExecutor(max_workers=min(4, len(jobs))) as pool:
                results = list(pool.map(_one, jobs))
        notes = []
        for r in results:
            notes.extend(r or [])
        return notes

    def _push_logcat_notes(self, sess):
        """播报收尾阶段算出的「配套日志覆盖度」结论（见 _logcat_coverage_notes）。

        必须排在「✓ 录屏已完成」之后：用户视线停在最后几条提示上，先报成功、
        再报「日志其实少了 24 分钟」，他才不会把后者漏掉。

        warn 级走 `_push_alert`：状态栏 + toast + **不点就不消失的弹窗**。为什么
        非这样不可 —— 用户实况里这条结论当时是 toast，6 秒后自动消失，而人正
        在录屏之外的事上；等他回来只看得到「✓ 录屏已完成」，日志塌了 24 分钟
        这件事就这么过去了，直到事后对时间轴才发现，那时已经补不回来。数据
        残缺属于「必须让用户亲手确认一次」的结论，不能指望一条会自己消失的提示。
        """
        for level, text in (sess or {}).get("logcat_notes") or []:
            if level == "warn":
                self._push_alert("warn", text,
                                 title="⚠ 本次录制的日志不完整")
            else:
                self._push_status(level, text)



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
            return False, [], "{}（残片：{}）".format(err or "收尾失败", lp)
        return False, [], err


    # 已经压缩过的容器格式：再走 DEFLATE 只烧 CPU，几乎不减小体积。
    _PRECOMPRESSED_EXT: ClassVar[set[str]] = {
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
    def _zip_paths(paths, zip_path, cleanup=True):
        """把若干文件打包为一个 zip（以文件名作条目）。失败返回 None。

        打包**完整写出成功后**清理源文件（仅清理本次实际写入 zip 的普通文件，
        目录 / zip 自身 / 写入失败未进包的文件都不会被删）——与 README 承诺的
        「打包完成后清理刚打包的源文件（仅删打包所覆盖的文件）」保持一致。

        cleanup=False（EDR A 方案）：打包后不删源文件。工作目录模式下成品已
        copy 到用户保存目录，打包源若是那份 copy，删除它又构成"删高熵 MP4"
        的可疑动作；不删、留待下次启动连同工作目录一起清理，收尾零删除。
        """
        written = []
        lzip = long_path(zip_path)
        try:
            if os.path.exists(lzip):
                os.remove(lzip)
            with zipfile.ZipFile(lzip, "w") as z:
                for p in paths:
                    # 长路径安全：Windows 上 os.path.exists / isfile 对超过
                    # 260 字符的路径返回 False —— 文件会被**静默跳过**，打包
                    # 出来的 zip 少了内容，而界面照样弹「✓ 已打包」。用户拿到
                    # 的压缩包缺了录屏，却没有任何提示。
                    if (p and p != zip_path and path_exists(p)
                            and path_isfile(p)):
                        # 视频/音频/图片本来就已经压缩过（H.264/AAC/PNG），
                        # 再走 DEFLATE 只是把整个文件白算一遍：3 分钟的 1080p
                        # 录屏能白白多花一两秒 CPU，体积却几乎不变。体积真正
                        # 能压下来的是 logcat 的 txt，那类仍用 DEFLATE。
                        z.write(long_path(p), os.path.basename(p),
                                compress_type=RecordMixin._zip_method_for(p))
                        written.append(p)
            if not os.path.exists(lzip):
                return None
        except Exception:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
            # 打包中途失败：清掉可能残留的半成品 zip，源文件一律保留
            with contextlib.suppress(Exception):
                if os.path.exists(lzip):
                    os.remove(lzip)
            return None
        if cleanup:
            for p in written:
                with contextlib.suppress(Exception):
                    os.remove(long_path(p))
        return zip_path

    def _scrcpy_pref_path(self):
        """用户配置的 scrcpy 路径（读失败一律当空 = 走自动探测）。"""
        try:
            return str(load_prefs().get("scrcpy_path") or "")
        except Exception:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
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
        except Exception as ex:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
            self._push_toast("err", f"⚠ 投屏启动出现异常：{ex}")
            return {"ok": False, "reason": "start_error", "error": str(ex)}
        started = res["started"]
        skipped = res["skipped"]
        failed = res["failed"]
        if started:
            self._push_status("ok", "✓ 已开启投屏：{}".format("、".join(started)))
        if skipped:
            self._push_status("info", "ℹ 已在投屏中：{}".format("、".join(skipped)))
        for s, reason in failed:
            self._push_status("err", f"⚠ {s} 投屏失败：{reason}")
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
        except Exception:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
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
            self._push_status("err", f"⚠ {serial} 投屏已中断：{error}")
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
            except Exception:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
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
                except Exception as ex:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
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
            except Exception as ex:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
                res = {"error": str(ex)}
            finally:
                # 与 mirror_stop 在同一把锁下「复位启动标记 + 取出被要求停止的实例」：
                # _start_one_mirror 同步等首帧最长 6s，期间 mirror_stop 可能已进来
                # 标记了停请求却摘不到对象（还没登记）。这里登记完成后复查，命中
                # 就把刚起来的对象拿出来，锁外停掉，避免投屏在用户点停止后继续占用
                # 播放器 / adb / screenrecord。
                with self._mirror_lock:
                    self._mirror_starting.discard(s)
                    stop_requested = s in self._mirror_stopreq
                    if stop_requested:
                        self._mirror_stopreq.discard(s)
                        stopped_m = (self._mirror_pipes.pop(s, None)
                                     or self._mirror_snaps.pop(s, None))
                    else:
                        stopped_m = None
                if stop_requested:
                    with contextlib.suppress(Exception):
                        if stopped_m is not None:
                            stopped_m.stop()
            if stop_requested:
                # 用户已明确要求停止：这次启动当作取消，别报「已开启投屏」。
                continue
            if res.get("mode"):
                started.append({"serial": s, "mode": res["mode"],
                                "frame_url": res.get("frame_url") or ""})
            else:
                failed.append({"serial": s, "reason": res.get("error") or "未知原因"})

        label = {"scrcpy": "scrcpy 窗口", "pipe": "播放器窗口（screenrecord 管道）",
                 "snap": "低帧率预览（screencap 轮询）"}
        if started:
            self._push_status("ok", "✓ 已开启投屏：" + "、".join(
                "{}（{}）".format(x["serial"], label.get(x["mode"], x["mode"]))
                for x in started))
        for x in failed:
            self._push_status("err", "⚠ {} 投屏失败：{}".format(x["serial"], x["reason"]))
        if skipped:
            self._push_status("info", "ℹ 已在投屏中：{}".format("、".join(skipped)))
        return {"ok": bool(started or skipped), "started": started,
                "skipped": skipped, "failed": failed}

    def mirror_stop(self, serial=None):
        """停止备用投屏（管道 / 低帧率预览），不含 scrcpy 窗口（由用户自己关）。"""
        targets = self._target_serials(serial)
        stopped = []
        # 启动窗口内（_start_one_mirror 同步等首帧）设备还没进表，mirror_stop
        # 单看表会漏掉它们。持锁把「正在启动」的目标记进 stopreq：start 登记
        # 成功后会复查该标记并立刻停掉刚起来的实例（见 mirror_start 的 finally）。
        with self._mirror_lock:
            for s in self._mirror_starting:
                if not targets or s in targets:
                    self._mirror_stopreq.add(s)
        for s, m in list(self._mirror_pipes.items()):
            if targets and s not in targets:
                continue
            with contextlib.suppress(Exception):
                m.stop()
            self._mirror_pipes.pop(s, None)
            stopped.append(s)
        for s, m in list(self._mirror_snaps.items()):
            if targets and s not in targets:
                continue
            with contextlib.suppress(Exception):
                m.stop()
            self._mirror_snaps.pop(s, None)
            stopped.append(s)
        if stopped:
            self._push_status("info", "ℹ 已停止投屏：{}".format("、".join(stopped)))
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
