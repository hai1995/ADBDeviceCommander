# -*- coding: utf-8 -*-
"""backend.controllers.deviceinfo —— 设备信息 / 诊断包"""

from backend.controller import (
    adb_kwargs, devinfo, diag, get_pref,
    subprocess
)

class DeviceInfoMixin:
    """设备信息、诊断包收集。"""

    def device_info(self, serial):
        """一次 adb shell 取回型号 / 版本 / 分辨率 / 电量 / 存储 / 内存。"""
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        s = (serial or "").strip()
        if not s:
            return {"ok": False, "reason": "请先选择设备"}
        try:
            r = subprocess.run(
                [self._adb_argv(), "-s", s, "shell", devinfo.SCRIPT],
                **adb_kwargs(20))
        except subprocess.TimeoutExpired:
            return {"ok": False, "reason": "读取设备信息超时（设备可能无响应）"}
        except Exception as e:
            return {"ok": False, "reason": "读取设备信息失败：%s" % e}
        if r.returncode != 0 and not (r.stdout or "").strip():
            detail = ((r.stderr or "").strip() or "设备未返回内容")[:160]
            return {"ok": False, "reason": "读取设备信息失败：%s" % detail}
        info = devinfo.parse_info(r.stdout or "")
        rows = devinfo.rows(info)
        return {"ok": True, "serial": s, "info": info,
                "rows": [[k, v] for k, v in rows],
                "text": devinfo.as_text(info)}

    def diag_options(self):
        """诊断包卡的默认值（来自 config.json，单一数据源）。"""
        try:
            lines = get_pref("diag_logcat_lines", diag.DEFAULT_LOGCAT_LINES)
            with_log = bool(get_pref("diag_with_logcat", True))
        except Exception:
            lines, with_log = diag.DEFAULT_LOGCAT_LINES, True
        return {"ok": True,
                "with_logcat": with_log,
                "logcat_lines": diag.clamp_lines(lines),
                "max_lines": diag.MAX_LOGCAT_LINES,
                "running": self._diag_running}

    def diag_collect(self, serial=None, with_logcat=None, logcat_lines=None):
        """对勾选（或指定）设备各收集一个诊断包。

        单设备 3~6 秒（logcat 尾部 2000 行占大头），故整批丢进一条后台线程顺序
        执行，主线程立刻返回；完成/失败经 status + diag_state 事件回报。

        与截图不同，这里**不做多线程并行**：诊断包是 adb 密集操作，多台设备并行
        只会在 adb 的调用队列里互相排队，还会让 logcat 尾部的时间点对不齐。
        """
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        serials = self._target_serials(serial)
        if not serials:
            self._push_status("err", "⚠ 收集诊断包前请先勾选至少一个设备。")
            return {"ok": False, "reason": "no_device"}
        with self._diag_lock:
            if self._diag_running:
                # 已经在收集：直接拒绝并说明，不要排队 —— 排队会让用户以为
                # 「点了两下，出了两个包」，而第二个包的时间点是几分钟后的。
                self._push_status("info", "ℹ 诊断包正在收集中，请等当前这一批完成。")
                return {"ok": False, "reason": "busy"}
            self._diag_running = True
        if with_logcat is None:
            with_logcat = bool(get_pref("diag_with_logcat", True))
        lines = diag.clamp_lines(
            logcat_lines if logcat_lines is not None
            else get_pref("diag_logcat_lines", diag.DEFAULT_LOGCAT_LINES))
        save_dir = self._default_save_dir()
        self.bus.push("diag_state", {"running": True})
        self._push_status(
            "info", "开始收集诊断包：%d 台设备（%s）"
                    % (len(serials),
                       "含 logcat 尾部 %d 行" % lines if with_logcat else "不含 logcat"))
        self.workers.spawn("diag", self._do_diag, serials, save_dir,
                           bool(with_logcat), lines)
        return {"ok": True, "devices": serials}

    def _do_diag(self, serials, save_dir, with_logcat, lines):
        """逐台收集诊断包（后台线程）；每台一条结果，收尾复位按钮态。"""
        ok_count, failed, paths = 0, [], []
        try:
            for s in serials:
                if self.state.shutting_down:
                    return
                try:
                    path, manifest, err = diag.collect(
                        self._adb_argv(), s, save_dir,
                        with_logcat=with_logcat, logcat_lines=lines)
                except Exception as e:      # 兜底：诊断包异常不能拖垮整批
                    path, manifest, err = None, None, "内部错误：%s" % e
                if err or not path:
                    failed.append("%s：%s" % (s, err or "未知原因"))
                    self._push_status("err", "⚠ 诊断包失败 %s：%s"
                                      % (s, err or "未知原因"))
                    continue
                ok_count += 1
                paths.append(path)
                self.bus.push("tool", {"type": "diag", "serial": s,
                                       "path": path})
                self._push_status("ok", diag.summary_line(path, manifest))
        finally:
            with self._diag_lock:
                self._diag_running = False
            self.bus.push("diag_state", {"running": False})
        if ok_count and not failed:
            self._push_toast("ok", "✓ 诊断包已生成 %d 个，保存目录 %s"
                             % (ok_count, save_dir))
        elif ok_count and failed:
            self._push_toast(
                "warn", "⚠ 诊断包：%d 成功 / %d 失败（%s）"
                        % (ok_count, len(failed), "；".join(failed)[:120]))
        elif failed:
            self._push_toast("err", "⚠ 诊断包收集失败：%s" % "；".join(failed)[:160])
