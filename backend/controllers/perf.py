# -*- coding: utf-8 -*-
"""backend.controllers.perf —— 性能监控"""

from backend.controller import (
    DEFAULT_INTERVAL, PERF_CRIT_RATIO, PERF_MAX_DEVICES, PERF_MAX_INTERVAL,
    PERF_MIN_INTERVAL, PERF_PKG_CACHE_S, PerfMonitor, load_prefs,
    os, perf_build_thresholds, perf_default_threshold_expr, perf_format_thresholds,
    perf_list_installed, perf_parse_thresholds, perf_pkg_display, perf_rule_text,
    perf_stop_monitors, perf_threshold_items, perf_write_compare,
    perf_write_report, save_prefs,
    time
)

class PerfMixin:
    """性能监控（采样/阈值/报告/对比）。"""

    @staticmethod
    def _perf_label(info, serial):
        """报告里用的设备短名：型号 + 序列号尾部。

        同型号批量测试（一次 4 台 Pixel）时，只写型号会让对比报告的图例与表头
        出现四个一模一样的名字 —— 那就等于没有图例。
        """
        serial = str(serial or "")
        model = (info or {}).get("model") or ""
        tail = serial[-4:] if len(serial) > 10 else serial
        return ("%s · %s" % (model, tail)) if model else (tail or "device")

    def _perf_interval(self, interval_ms):
        """采样间隔：前端可能传空 / 字符串 / 越界值，一律夹到安全区间。

        下限 0.2s 是防止手抖填 0 把 adb 打满（一次采样本就要 200~400ms，
        再快只是在排队，采到的还是同一时刻的数据）；上限 10s 避免「点完
        开始，半分钟没反应」。
        """
        try:
            ms = int(interval_ms)
        except (TypeError, ValueError):
            ms = int(DEFAULT_INTERVAL * 1000)
        sec = ms / 1000.0
        return min(PERF_MAX_INTERVAL, max(PERF_MIN_INTERVAL, sec))

    def perf_list_packages(self, serial=None, refresh=False):
        """读设备上已安装的应用包名，供「应用包名」下拉框使用。

        serial 为空时取第一台受控设备（与 perf-start 的默认目标一致）：应用
        列表在几台设备之间通常一致，没必要每台都拉一遍再拼起来。

        结果缓存 PERF_PKG_CACHE_S 秒：下拉框每次打开都会问一次，而 `pm list
        packages` 在应用多的机器上要 1~3 秒 —— 不缓存的话「点开下拉框」这件
        事会稳定地卡两秒。点「刷新」或换设备时 refresh=True 绕过缓存。
        """
        if serial:
            target = serial
        else:
            controlled = self._target_serials(None)
            target = controlled[0] if controlled else ""
        if not target:
            return {"ok": False, "reason": "no_device",
                    "message": "请先在左侧勾选一台设备"}
        now = time.time()
        with self._perf_pkg_lock:
            cached = self._perf_pkg_cache.get(target)
            if (not refresh) and cached and (now - cached.get("at", 0) < PERF_PKG_CACHE_S):
                out = dict(cached["data"])
                out["cached"] = True
                return out
        res = perf_list_installed(self.state.adb_path, target)
        res["serial"] = target
        res["cached"] = False
        if res.get("ok"):
            with self._perf_pkg_lock:
                self._perf_pkg_cache[target] = {"at": now, "data": dict(res)}
        return res

    def perf_start(self, serial=None, interval_ms=None, pkg=None):
        """开始性能监控。

        不传 serial 时监控**全部受控设备**（多台即进入对比模式），上限
        PERF_MAX_DEVICES 台：每台一条采样线程、每 1s 一次 `adb shell`，
        再多就只是在 adb 的调用队列里排队，换不来更多信息。
        """
        serials = self._target_serials(serial)
        if not serials:
            self._push_status("err", "⚠ 性能监控前请先勾选至少一台设备。")
            return {"ok": False, "reason": "no_device"}
        if len(serials) > PERF_MAX_DEVICES:
            skipped = serials[PERF_MAX_DEVICES:]
            serials = serials[:PERF_MAX_DEVICES]
            self._push_status(
                "warn", "⚠ 性能监控最多同时监控 %d 台设备，已忽略：%s"
                % (PERF_MAX_DEVICES, "、".join(skipped)))
        interval = self._perf_interval(interval_ms)
        pkg = (pkg or "").strip()
        started, infos, failed = {}, {}, {}
        for s in serials:
            mon = PerfMonitor(self.state.adb_path, s, interval, pkg,
                              on_status=self._push_status)
            ok, err = mon.start()
            if not ok:
                try:
                    mon.stop()
                except Exception:
                    pass
                failed[s] = err
                continue
            started[s] = mon
            infos[s] = dict(mon.info)
        if not started:
            err = next(iter(failed.values()), "启动失败")
            self._push_status("err", "⚠ 性能监控启动失败：%s" % err)
            return {"ok": False, "reason": "start_failed", "error": err,
                    "failed": failed}
        # 新会话就位后再关旧会话：启动失败时旧数据还在，用户不会白丢一段曲线。
        with self._perf_lock:
            old, self._perfs = dict(self._perfs), started
        perf_stop_monitors(old.values())
        primary = serials[0] if serials[0] in started else next(iter(started))
        info = infos[primary]
        if len(started) == 1:
            self._push_status(
                "ok", "✓ 已开始性能监控：%s（%s · 每 %.1f 秒采样一次）"
                % (info.get("model") or primary, perf_pkg_display(info), interval))
        else:
            self._push_status(
                "ok", "✓ 已开始性能监控：%d 台设备（%s · 每 %.1f 秒采样一次）"
                % (len(started), perf_pkg_display(info), interval))
        return {"ok": True, "serial": primary, "info": info,
                "interval": interval, "sessions": infos, "failed": failed}

    def perf_stop(self, serial=None):
        """停止采样。会话对象**保留**：停完还能导出刚才那段报告。

        serial 为空 = 全部停止；指定则只停那一台（对比时想先收掉一台的情况）。
        """
        with self._perf_lock:
            if serial:
                targets = ({serial: self._perfs[serial]}
                           if serial in self._perfs else {})
            else:
                targets = dict(self._perfs)
        if not targets:
            return {"ok": True, "samples": 0, "sessions": {}}
        perf_stop_monitors(targets.values())
        per, total = {}, 0
        for s, mon in targets.items():
            per[s] = mon.count()
            total += per[s]
        if len(per) == 1:
            self._push_status("info", "⏹ 已停止性能监控（本次共 %d 个采样点）" % total)
        else:
            self._push_status("info", "⏹ 已停止 %d 台设备的性能监控（共 %d 个采样点）"
                              % (len(per), total))
        return {"ok": True, "samples": total, "sessions": per}

    def perf_poll(self, since=0):
        """增量拉取采样点。前端按 0.6s 轮询，不用事件总线。

        since 可以是 {serial: seq}（多设备各自维护游标），也可以是单个 int
        （首次调用 / 旧前端：所有会话都从该 seq 之后取）。顶层 samples 是各
        会话合并后按时间排序的结果，仅为兼容旧前端；新前端读 sessions。
        """
        with self._perf_lock:
            sessions = dict(self._perfs)
        if not sessions:
            return {"running": False, "seq": 0, "samples": [], "info": {},
                    "sessions": {}}
        out, seqs, merged = {}, {}, []
        running = False
        for s, mon in sessions.items():
            try:
                cursor = since.get(s, 0) if isinstance(since, dict) else int(since or 0)
            except (TypeError, ValueError, AttributeError):
                cursor = 0
            snap = mon.snapshot(cursor)
            running = running or bool(snap.get("running"))
            seqs[s] = snap.get("seq", 0)
            merged.extend(snap.get("samples") or [])
            out[s] = snap
        merged.sort(key=lambda x: x.get("t") or 0)
        first = next(iter(sessions))
        return {"running": running, "seq": seqs, "samples": merged,
                "info": dict(sessions[first].info), "sessions": out,
                "count": sum(len(v.get("samples") or []) for v in out.values())}

    def _perf_thresholds(self):
        """当前生效的告警阈值（读 config.json，留空 = 内置基线）。

        每次现读而不是缓存到 self：用户可以边监控边在界面上改阈值，也可以
        直接编辑 config.json 后重启监控 —— 缓存一份就得处理失效，而这里读
        文件的开销（几 KB JSON）在「点一次按钮」「导一次报告」的量级上无所谓。
        返回 (阈值 dict, 解析错误列表, 原始表达式)。
        """
        try:
            expr = (load_prefs() or {}).get("perf_thresholds")
        except Exception:
            expr = ""
        th, errs = perf_parse_thresholds(expr)
        return th, errs, (expr or "").strip() if isinstance(expr, str) else ""

    def _perf_threshold_payload(self):
        th, errs, expr = self._perf_thresholds()
        return {
            "thresholds": dict((k, dict(v)) for k, v in th.items()),
            "rules": dict((k, perf_rule_text(k, v)) for k, v in th.items()),
            "items": perf_threshold_items(th),
            "crit_ratio": PERF_CRIT_RATIO,
            "expr": perf_format_thresholds(th) if th else "",
            "default_expr": perf_default_threshold_expr(),
            "custom": bool(expr),
            "off": not th,
            "errors": errs,
        }

    def perf_thresholds(self):
        """下发告警阈值：界面实时标红与报告里的告警卡片共用同一份定义。

        阈值只有一份来源（config.json 的 perf_thresholds，缺省回落
        backend/perf_service.DEFAULT_THRESHOLDS）：前端不再抄一份 ——
        两份常量一定会漂移，最后报告说「没超标」而界面标红。
        """
        return self._perf_threshold_payload()

    def perf_set_thresholds(self, values=None):
        """保存界面提交的阈值（{key: 数值或 None}，None = 关闭该条）。

        提交值先过与手改 config.json 相同的校验，非法时**不写盘**并把原因
        返回给界面：静默存下一份非法配置，用户下次启动只会看到告警莫名消失。
        """
        if not isinstance(values, dict):
            return {"ok": False, "reason": "bad_args",
                    "errors": ["阈值参数格式不正确"]}
        th, errs = perf_build_thresholds(values)
        if errs:
            return {"ok": False, "reason": "invalid", "errors": errs}
        expr = perf_format_thresholds(th) if th else "off"
        try:
            save_prefs({"perf_thresholds": expr})
        except Exception as ex:
            return {"ok": False, "reason": "save_failed", "errors": [str(ex)]}
        payload = self._perf_threshold_payload()
        payload["ok"] = True
        if th:
            self._push_status("ok", "✓ 告警阈值已更新：%s" % " · ".join(
                perf_rule_text(k, v) for k, v in th.items()), toast=True)
        else:
            self._push_status("info", "告警阈值已全部关闭（不再标红 / 不再告警）",
                              toast=True)
        return payload

    def perf_status(self):
        with self._perf_lock:
            sessions = dict(self._perfs)
        if not sessions:
            return {"running": False, "serial": "", "info": {}, "seq": 0,
                    "count": 0, "sessions": {}}
        first = next(iter(sessions))
        detail = {}
        running = False
        total = 0
        for s, mon in sessions.items():
            n = mon.count()
            alive = mon.alive()
            running = running or alive
            total += n
            detail[s] = {"running": alive, "seq": mon.seq, "count": n,
                         "info": dict(mon.info), "error": mon.error}
        return {"running": running, "serial": first, "info": dict(sessions[first].info),
                "seq": {s: d["seq"] for s, d in detail.items()}, "count": total,
                "error": sessions[first].error, "sessions": detail}

    def perf_export(self):
        """把本次采到的全部样本导出为 HTML 报告 + CSV（每台设备一份）。"""
        with self._perf_lock:
            sessions = dict(self._perfs)
        if not sessions:
            self._push_status("err", "⚠ 还没有采样数据，先开始监控再导出报告。")
            return {"ok": False, "reason": "no_data"}
        saved, errors, total_rows, total_samples = [], {}, 0, 0
        th, _th_errs, _expr = self._perf_thresholds()
        compare_entries = []
        for s, mon in sessions.items():
            samples = mon.all_samples()
            if not samples:
                continue
            info = dict(mon.info)
            info["interval"] = mon.interval
            compare_entries.append({
                "serial": s, "label": self._perf_label(info, s),
                "samples": samples, "info": info, "interval": mon.interval,
            })
            try:
                res = perf_write_report(samples, info, self._default_save_dir(), th)
            except Exception as ex:
                errors[s] = str(ex)
                continue
            res["serial"] = s
            res["samples"] = len(samples)
            saved.append(res)
            total_rows += res.get("rows", 0)
            total_samples += len(samples)
        if not saved:
            why = next(iter(errors.values()), "没有采样数据")
            self._push_status("err", "⚠ 报告生成失败：%s" % why)
            return {"ok": False, "reason": why, "errors": errors}
        # 多设备时再出一份「横向对比」报告：三份独立报告摊在桌上自己对照，
        # 是导出这件事里最费劲的一步，合并成一份能省掉全部来回翻页。
        compare = ""
        if len(compare_entries) > 1:
            try:
                res = perf_write_compare(compare_entries, self._default_save_dir(), th)
                compare = res.get("html") or ""
            except Exception as ex:
                errors["compare"] = str(ex)
        if len(saved) == 1:
            msg = "✓ 性能报告已生成：%s（%d 个采样点）" % (
                saved[0]["html"], total_rows)
        elif compare:
            msg = "✓ 已生成 %d 份设备报告 + 1 份对比报告（共 %d 个采样点）：%s" % (
                len(saved), total_rows, os.path.dirname(compare) or ".")
        else:
            msg = "✓ 已生成 %d 份性能报告（共 %d 个采样点）：%s" % (
                len(saved), total_rows, os.path.dirname(saved[0]["html"]) or ".")
        self._push_status("ok", msg, toast=True)
        if errors:
            # 只报「✓ 已生成 N 份」会让用户以为全都导出了：对比报告正是拿这批
            # 文件拼的，少一台等于结论缺一半。失败的设备单独说清楚。
            self._push_status(
                "warn", "⚠ 有 %d 份报告未生成：%s" % (
                    len(errors),
                    "；".join("%s（%s）" % (k, v) for k, v in errors.items())))
        return {"ok": True, "files": saved, "html": saved[0]["html"],
                "csv": saved[0]["csv"], "rows": total_rows,
                "samples": total_samples, "sessions": len(saved),
                "compare": compare, "errors": errors}
