# -*- coding: utf-8 -*-
"""backend.controllers.apk —— APK 选择 / 安装"""

from backend.controller import (
    adb_kwargs, apkinfo, load_prefs, os,
    subprocess
)

class ApkMixin:
    """APK 选择/安装。"""

    def apk_pick(self):
        """弹原生文件对话框选一个 APK，只记路径（不读字节）。"""
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        path = self._open_dialog((("APK 安装包", "*.apk"),
                                  ("所有文件", "*.*")), "安装包 (*.apk)")
        if not path:
            return {"ok": False, "reason": "cancelled"}
        try:
            size = os.path.getsize(path)
        except OSError as e:
            return {"ok": False, "reason": "读取安装包失败：%s" % e}
        self._apk_path = path
        return {"ok": True, "path": path, "name": os.path.basename(path),
                "size": size, "size_text": apkinfo.format_size(size)}

    def apk_install(self, serial=None, replace=None, downgrade=None,
                    grant=None):
        """把选好的 APK 装到受控设备（每台一个后台 worker）。

        选项为 None 时取 config.json 里的默认值（界面上的勾选也会即时落盘，
        所以两条来源一致；显式传入则以传入为准）。
        """
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        path = self._apk_path
        if not path or not os.path.isfile(path):
            return {"ok": False, "reason": "请先选择 APK 安装包"}
        prefs = load_prefs()
        if replace is None:
            replace = bool(prefs.get("apk_replace", True))
        if downgrade is None:
            downgrade = bool(prefs.get("apk_downgrade", False))
        if grant is None:
            grant = bool(prefs.get("apk_grant", False))
        targets = self._target_serials(serial)
        if not targets:
            return {"ok": False, "reason": "请先在左侧勾选设备"}
        with self._apk_batch_lock:
            # 同一时刻只允许一批。worker 的 key 是 `apk_install_<serial>`，
            # 同一台设备上一批还没跑完时 spawn 会**复用存活线程**（不会真的
            # 再装一遍），可批次账已经被后一次点击重置——于是前一批的结果
            # 记进后一批的账里，界面提前收到 running=False，实际还在装。
            # 直接从源头拒绝第二次点击，比事后修补账面可靠。
            if self._apk_batch is not None:
                return {"ok": False,
                        "reason": "上一批安装还没结束，请等它完成后再装"}
            self._apk_batch = {
                "total": len(targets), "done": 0, "ok": 0,
                "failed": [], "seen": set(),
                "name": os.path.basename(path),
            }
        self.bus.push("apk_state", {"running": True})
        for s in targets:
            # key 带序列号：同一台设备连点两次不会叠加，不同设备互不阻塞
            try:
                self.workers.spawn("apk_install_" + s, self._do_apk_install, s,
                                   path, bool(replace), bool(downgrade),
                                   bool(grant))
            except Exception as e:
                # 线程起不来（进程线程数耗尽 / 内存告急）时把这台直接记成失败，
                # 让批次账能走到 done == total。否则 _apk_batch 永远挂着：之后
                # 每次「安装」都被上面那句「上一批安装还没结束」挡回去，
                # apk_state 也停在 running —— 安装功能彻底锁死，只能重启程序。
                self._apk_batch_done(
                    s, {"ok": False, "message": "无法启动安装线程：%s" % e}, path)
        self._push_status(
            "info", "开始安装 %s → %d 台设备（%s）"
            % (os.path.basename(path), len(targets),
               "、".join(["覆盖" if replace else "全新",
                          "允许降级" if downgrade else "",
                          "授予权限" if grant else ""]).replace("、、", "、").strip("、")),
            toast=False)
        return {"ok": True, "count": len(targets)}

    def _do_apk_install(self, serial, path, replace, downgrade, grant):
        """单台设备的安装（后台线程）：失败不抛，结果进状态栏 + 批次账。"""
        res = {"ok": False, "code": "", "message": "安装未完成"}
        # 记账必须无条件发生（finally）：这个线程的任何一次「没记上账」都会让
        # _apk_batch 永远差一台，而 _apk_batch 非空时后续每次安装都被「上一批
        # 安装还没结束」挡回去 —— 安装功能就此锁死，只能重启程序。
        try:
            args = apkinfo.install_args(replace=replace, downgrade=downgrade,
                                        grant=grant)
            r = subprocess.run(
                [self._adb_argv(), "-s", serial] + args + [path],
                **adb_kwargs(300))
            out, err = r.stdout or "", r.stderr or ""
            res = apkinfo.parse_install_output(out + "\n" + err)
            # testOnly 调试包很常见（CI 出的包默认带 testOnly），遇上了自动
            # 加 -t 重试一次——比让用户自己看错误码再去查参数强得多。
            if (not res["ok"] and res.get("code") == "INSTALL_FAILED_TEST_ONLY"):
                self._push_status(
                    "warn", "… %s 是 testOnly 包，改用 -t 重试" % serial)
                args2 = args + ["-t"]
                r2 = subprocess.run(
                    [self._adb_argv(), "-s", serial] + args2 + [path],
                    **adb_kwargs(300))
                res = apkinfo.parse_install_output(
                    (r2.stdout or "") + "\n" + (r2.stderr or ""))
            if res["ok"]:
                self._push_status("ok", "✓ 安装成功：%s ← %s"
                                  % (serial, os.path.basename(path)))
            else:
                self._push_status("err", "✗ 安装失败：%s — %s"
                                  % (serial, res["message"]), toast=True)
        except subprocess.TimeoutExpired:
            res = {"ok": False, "code": "",
                   "message": "安装超时（5 分钟）：包太大或设备 IO 卡住，可重试"}
            self._push_status("err", "✗ 安装失败：%s — %s"
                              % (serial, res["message"]), toast=True)
        except Exception as e:
            res = {"ok": False, "code": "", "message": "安装异常：%s" % e}
            self._push_status("err", "✗ 安装失败：%s — %s"
                              % (serial, res["message"]), toast=True)
        finally:
            self._apk_batch_done(serial, res, path)

    def _apk_batch_done(self, serial, res, path):
        """批次汇总：全部设备到齐后弹一条 toast（不逐台刷屏）。"""
        with self._apk_batch_lock:
            b = self._apk_batch
            if not b:
                return
            seen = b.setdefault("seen", set())
            if serial in seen:
                return                          # 同一台被重复记账（防御）
            seen.add(serial)
            b["done"] += 1
            if res["ok"]:
                b["ok"] += 1
            else:
                b["failed"].append((serial, res["message"]))
            done, total = b["done"], b["total"]
            ok_count = b["ok"]
            failed = list(b["failed"])
            name = b["name"]
            if done < total:
                return
            self._apk_batch = None
        # 批次结束（成功 / 失败都算）：前端据此恢复「安装」按钮的可用态。
        # 不靠「状态文案里含『完成』」来判断——文案随时会改，事件才是契约。
        self.bus.push("apk_state", {"running": False})
        if failed:
            self._push_status(
                "warn", "%s 安装完成：%d 成功 / %d 失败（%s）"
                % (name, ok_count, len(failed),
                   "；".join("%s：%s" % (s, m) for s, m in failed[:3])),
                toast=True)
        else:
            self._push_status("ok", "✓ %s 已安装到 %d 台设备" % (name, ok_count),
                              toast=True)
