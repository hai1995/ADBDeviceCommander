"""backend.controllers.commands —— 指令执行 / 保存 / 导入导出 / 自定义"""

from backend.controller import (
    _EXIT_RE,
    SHELL_INTERACTIVE_RE,
    datetime,
    get_pref,
    is_subshell_command,
    json,
    merge_adb_shell_commands_detailed,
    merge_builtins,
    needs_device,
    os,
    program_dir,
    root_intent,
    root_state,
    save_user_commands,
    tempfile,
    time,
    transform,
    unique_path,
    uuid,
)
from core.longpath import long_path


class CommandMixin:
    """快捷指令：执行、保存、导入导出、自定义、停止。"""

    DEFAULT_CMD_TIMEOUT = 0   # 不限制；由 config.json 的 cmd_timeout 覆盖

    def run_command(self, cmd_id, ws=None):
        """下发一条快捷指令（可多设备循环，线程内执行）。

        ws：指令台工作区（子 tab）id。不同工作区各自一条会话、各自一把执行锁，
        因此两个工作区可以真的同时在跑；省略即默认工作区（历史行为不变）。
        """
        if self.state.shutting_down:
            return {"ok": False}
        cmd_obj = next(
            (c for c in self.state.commands if c.get("id") == cmd_id), None)
        if cmd_obj is None:
            self._push_status("err", "⚠ 未找到命令：{}".format(cmd_id))
            return {"ok": False}
        if self._ws_id(ws) == self.WS_DEFAULT and self.session is None:
            self._push_status("err", "⚠ 会话尚未初始化，请稍后重试。")
            return {"ok": False}
        self._bump_click(cmd_id)
        self.workers.spawn(None, self._execute, cmd_obj, self._ws_id(ws))
        return {"ok": True}

    def save_commands(self, commands):
        """前端维护的命令（界面增删改后）整体回写 commands.json。

        后端只负责原子写回与内存态同步（state.commands），不重新归一化——
        前端持有的就是界面真实展示的命令，直接写回能完整保留 clickCount，
        避免下次启动「常用命令靠前」排序被重置。失败回 err 状态并 ok=False。
        """
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        ok, err = save_user_commands(commands)
        if not ok:
            self._push_status("err", "⚠ 保存命令失败：{}".format(err))
            return {"ok": False, "reason": err}
        user_cmds = []
        for c in (commands or []):
            if isinstance(c, dict):
                c = dict(c)
                c.pop("builtin", None)
                user_cmds.append(c)
        self.state.commands = merge_builtins(user_cmds)
        self._push_status("ok", "✓ 命令已保存（%d 条）" % len(user_cmds))
        return {"ok": True}

    def export_commands(self):
        """导出用户自定义命令（界面维护的命令，已过滤内置默认），供备份 / 分享。"""
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        user_cmds = []
        for c in (self.state.commands or []):
            d = c if isinstance(c, dict) else vars(c)
            if d.get("builtin"):
                continue
            user_cmds.append({
                "id": d.get("id"),
                "name": d.get("name"),
                "labels": d.get("labels") or ["其他"],
                "commands": d.get("commands") or [],
                "clickCount": d.get("clickCount") or 0,
                "inputOnly": bool(d.get("inputOnly")),
                **({"note": d["note"]} if isinstance(d.get("note"), str)
                                        and d["note"].strip() else {}),
                **({"bg": d["bg"]} if d.get("bg") else {}),
                **({"fg": d["fg"]} if d.get("fg") else {}),
            })
        return {"ok": True, "commands": user_cmds, "count": len(user_cmds)}

    def export_commands_save(self):
        """把导出的命令写入「程序运行处」目录并返回本地路径（前端可 open_local_file）。"""
        data = self.export_commands()
        if not data.get("ok"):
            return data
        text = json.dumps(data["commands"], ensure_ascii=False, indent=2)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        name = "commands_export_{}.json".format(ts)
        primary = program_dir()
        last_err = ""
        for out_dir in (primary, tempfile.gettempdir()):
            try:
                os.makedirs(long_path(out_dir), exist_ok=True)
                path = unique_path(os.path.join(out_dir, name))
                with open(long_path(path), "w", encoding="utf-8") as f:
                    f.write(text)
            except OSError as e:
                last_err = str(e)
                continue
            return {"ok": True, "path": path,
                    "note": ("程序目录不可写，已改存到临时目录"
                             if os.path.normcase(out_dir)
                             != os.path.normcase(primary) else "")}
        return {"ok": False, "reason": "写入失败：{}".format(last_err)}

    def _dialog_types(self, pairs):
        """把 ((描述, 通配符), ...) 转成当前 pywebview 版本接受的 file_types。"""
        pairs = tuple(pairs)
        try:
            from webview.util import parse_file_type
        except Exception:
            return tuple("{} ({})".format(desc, ext) for desc, ext in pairs)
        try:
            parse_file_type("探测 (*.json)")
        except Exception:
            return pairs
        return tuple("{} ({})".format(desc, ext) for desc, ext in pairs)

    def _open_dialog(self, pairs, label=""):
        """弹原生「打开文件」对话框，返回选中文件路径；取消 / 不可用返回空串。"""
        try:
            import webview
        except Exception as e:
            self._push_status("warn", "⚠ 当前环境不支持原生文件对话框：{}".format(e))
            return ""
        win = getattr(self, "window", None)
        try:
            if win is None and hasattr(webview, "active_window"):
                win = webview.active_window()
        except Exception:
            win = None
        if win is None or not hasattr(win, "create_file_dialog"):
            self._push_status("warn", "⚠ 当前环境不支持原生文件对话框")
            return ""
        ft = self._dialog_types(pairs)
        directory = str(program_dir())
        try:
            files = win.create_file_dialog(
                webview.OPEN_DIALOG, directory=directory,
                allow_multiple=False, file_types=ft)
        except TypeError:
            try:
                files = win.create_file_dialog(
                    webview.OPEN_DIALOG, directory, False, None, ft)
            except TypeError:
                try:
                    files = win.create_file_dialog(
                        webview.OPEN_DIALOG, directory, False)
                except Exception as e:
                    self._push_status("warn", "⚠ 打开文件对话框失败：{}".format(e))
                    return ""
        except Exception as e:
            self._push_status("warn", "⚠ 打开文件对话框失败：{}".format(e))
            return ""
        if not files:
            return ""
        return files[0] if isinstance(files, (list, tuple)) else str(files)

    def import_commands_dialog(self):
        """弹出原生文件选择框（默认定位到程序目录），读取 JSON 并导入合并。"""
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        path = self._open_dialog((("JSON 命令备份", "*.json"),
                                  ("所有文件", "*.*")))
        if not path:
            return {"ok": False, "reason": "cancelled"}
        try:
            with open(long_path(path), encoding="utf-8-sig") as f:
                text = f.read()
        except Exception as e:
            return {"ok": False, "reason": "读取文件失败：{}".format(e)}
        return self.import_commands(text)

    def import_commands(self, payload):
        """导入命令（备份 / 分享文件）。payload 可为：列表 / 字典 / JSON 字符串。
        按 id 合并：已存在则覆盖，不存在则新增（缺失 id 自动生成）。"""
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload.lstrip("\ufeff"))
            except Exception as e:
                return {"ok": False, "reason": "JSON 解析失败：{}".format(e)}
        if isinstance(payload, dict) and "commands" in payload:
            incoming = payload.get("commands") or []
        elif isinstance(payload, list):
            incoming = payload
        else:
            incoming = []
        incoming = [c for c in (incoming or []) if isinstance(c, dict)]
        if not incoming:
            return {"ok": False, "reason": "没有可导入的命令"}
        existing = {}
        for c in (self.state.commands or []):
            d = c if isinstance(c, dict) else vars(c)
            if d.get("builtin"):
                continue
            existing[d.get("id")] = d
        added = 0
        for c in incoming:
            cid = self._norm_cmd_id(c.get("id"))
            if not cid:
                cid = "u_" + uuid.uuid4().hex[:10]
            c = dict(c)
            c["id"] = cid
            if cid not in existing:
                added += 1
            existing[cid] = c
        merged = list(existing.values())
        ok, err = save_user_commands(merged)
        if not ok:
            return {"ok": False, "reason": err}
        user_cmds = []
        for c in merged:
            cc = c if isinstance(c, dict) else vars(c)
            cc = dict(cc); cc.pop("builtin", None)
            user_cmds.append(cc)
        self.state.commands = merge_builtins(user_cmds)
        self._push_status("ok", "✓ 已导入命令（新增 %d 条，共 %d 条用户命令）"
                          % (added, len(merged)))
        return {"ok": True, "added": added, "total": len(merged)}

    @staticmethod
    def _norm_cmd_id(raw_id):
        """命令 id 归一化（与 core.commands.normalize_commands 同一规则）。"""
        if isinstance(raw_id, str):
            return raw_id.strip()
        if isinstance(raw_id, (int, float)) and not isinstance(raw_id, bool):
            return str(raw_id)
        return ""

    def load_commands(self):
        """返回当前完整命令列表（用户命令 + 内置默认，已 merge_builtins 归一化）。"""
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        out = []
        for c in (self.state.commands or []):
            d = c if isinstance(c, dict) else vars(c)
            out.append(dict(d))
        return {"ok": True, "commands": out}

    def run_custom(self, text, ws=None):
        """执行自定义命令：与快捷指令同源——按受控设备逐台循环并通过
        adb_inject.transform 自动注入 `-s <serial>`，彻底告别
        "more than one device/emulator"。纯 PC 脚本走单次执行旁路。

        ws：指令台工作区（子 tab）id，省略即默认工作区。
        """
        text = (text or "").strip()
        if not text:
            return {"ok": False}
        if self.state.shutting_down:
            return {"ok": False}
        if self._ws_id(ws) == self.WS_DEFAULT and self.session is None:
            self._push_status("err", "⚠ 会话尚未初始化，请稍后重试。")
            return {"ok": False}
        self.workers.spawn(None, self._execute, {
            "id": "__custom__", "name": "自定义命令", "commands": [{"command": text}],
        }, self._ws_id(ws))
        return {"ok": True}

    def stop_run(self, ws=None):
        """终止**指定工作区**的当前命令。"""
        wid = self._ws_id(ws)
        sess = self._ws_session(wid, create=False)
        if sess is not None:
            self._ws_status("err", "⏹ 已发送停止信号，正在终止当前命令…")
            try:
                sess.kill()
            except Exception:
                pass
        else:
            self._ws_status("warn", "当前没有正在运行的命令。")
        self._sync_stop_state(interactive=False, ws=wid)
        return {"ok": True}

    def _execute(self, cmd_obj, ws=None):
        """执行一条快捷指令：按需逐设备循环 + 每条命令带 delay。"""
        wid = self._ws_set_cur(ws)
        sess = self._ws_session(wid)
        try:
            with self._ws_lock(wid):
                if self.state.shutting_down or sess is None:
                    return
                busy, changed = self._ws_begin(wid)
                if changed:
                    self.bus.push("stop_state", {"running": busy})
                try:
                    try:
                        entries = cmd_obj.get("commands", [])
                        loop = needs_device(cmd_obj)
                        name = cmd_obj.get("name", "命令")
                        if loop:
                            serials = self.devices.selected_serials()
                            if not serials:
                                self._ws_status("err", self._no_device_hint(name))
                                return
                            for serial in serials:
                                self._ws_status("info", "──── 设备: {} ────".format(serial))
                                if not self._run_entries(entries, serial):
                                    break
                        else:
                            self._ws_status(
                                "info", "──── 执行「{}」（无需指定设备）────".format(name))
                            self._run_entries(entries, None)
                    except Exception as ex:
                        self._ws_status(
                            "err", "⚠ 命令执行出现异常：{}".format(ex))
                finally:
                    self._sync_stop_state(ws=wid)
                    busy, changed = self._ws_end(wid)
                    if changed:
                        self.bus.push("stop_state", {"running": busy})
        finally:
            self._ws_clear_cur()

    def _no_device_hint(self, name):
        """「命令需要设备，却一台都不可下发」时的提示。"""
        try:
            checked = [s for s, on in (self.devices.device_checked or {}).items()
                       if on]
        except Exception:
            checked = []
        if checked:
            return ("⚠ 命令「%s」需要设备，但已勾选的 %d 台当前都不可用"
                    "（离线 / 未授权 / 正在重连）：%s"
                    % (name, len(checked), "、".join(sorted(checked))))
        return "⚠ 命令「{}」需要指定设备，请先在左侧勾选设备。".format(name)

    def _run_entries(self, entries, serial):
        """逐条下发命令；返回 False 表示执行被中断（超时/停止）。"""
        sess = self._ws_session(self._ws_cur(), create=False)
        if sess is None:
            return False
        raw_cmds = [e.get("command", "") for e in entries]
        if serial:
            raw_cmds = [transform(c, serial) for c in raw_cmds]
        merged = merge_adb_shell_commands_detailed(raw_cmds)
        timeout = self._cmd_timeout()
        for cmd, end_idx in merged:
            if not cmd.strip():
                continue
            if self.state.shutting_down:
                return False
            if self._skip_root_switch(cmd, serial):
                continue
            stripped = cmd.strip()
            was_interactive = bool(sess.in_interactive_shell)
            interactive = (was_interactive
                           or bool(SHELL_INTERACTIVE_RE.match(stripped))
                           or is_subshell_command(stripped))
            self._push_cmd(cmd)
            if interactive and not was_interactive:
                self._push_console(
                    "info",
                    "» 已进入交互式 shell：后续命令直接送入该子 shell，"
                    "输入 exit 可退出并恢复逐条执行")
            if interactive:
                ok = sess.run(cmd, interactive=True)
                if ok and _EXIT_RE.match(stripped):
                    sess.leave_interactive()
                    self._interruptible_sleep(0.15)
                    self._push_console("info", "« 已退出交互式子 shell，恢复逐条执行")
            else:
                ok = sess.run(cmd, timeout=timeout)
            if not ok:
                reason = (getattr(sess, "last_error", "") or "").strip()
                self._ws_status("info", "✗ 执行中断" + ("：{}".format(reason) if reason else ""))
                return False
            delay = 0
            if not interactive and 0 <= end_idx < len(entries):
                delay = int(entries[end_idx].get("delay", 0) or 0)
            if delay:
                self._interruptible_sleep(delay / 1000.0)
        self._ws_status("info", "✓ 完成")
        return True

    def _cmd_timeout(self):
        """本条序列里非交互命令的超时秒数；None 表示不限制。"""
        try:
            v = int(get_pref("cmd_timeout", self.DEFAULT_CMD_TIMEOUT))
        except (TypeError, ValueError):
            v = self.DEFAULT_CMD_TIMEOUT
        return v if v > 0 else None

    def _skip_root_switch(self, cmd, serial):
        """本条命令是否应跳过（不下发）：root 状态切换的两种「跳过」情形。"""
        intent = root_intent(cmd)
        if not intent:
            return False
        if not serial:
            return False
        adb = self.state.adb_path or "adb"
        try:
            rooted = root_state(adb, serial)
        except Exception:
            rooted = None
        if rooted is None:
            self._ws_status(
                "warn",
                "⚠ 无法确认设备 {} 当前是否 root（adb 未返回 id/whoami 输出），"
                "已按指令下发 `{}`；若它已在目标状态，这次切换只会重启 adbd。".format(serial, cmd.strip()))
        elif (intent == "root") == bool(rooted):
            self._ws_status(
                "info",
                "ℹ 设备 {} 已{}，跳过 `{}`（重复切换只会重启 adbd，"
                "可能中断进行中的录屏 / 抓取）".format(serial, "处于 root" if rooted else "未 root", cmd.strip()))
            return True
        busy = self._device_busy_tasks(serial)
        if busy:
            self._ws_toast(
                "warn",
                "⚠ 设备 {} 正在{}：`{}` 会重启 adbd 并中断这些任务"
                "（录屏视频将不完整、日志抓取会断）。已跳过执行——"
                "请先停止录屏 / 抓取，再执行 root 状态切换。".format(serial, "、".join(busy), cmd.strip()))
            return True
        return False

    def _device_busy_tasks(self, serial):
        """该设备当前进行中、且会随 adbd 重启而中断的任务（中文名列表）。"""
        tasks = []
        try:
            if self.video.is_recording(serial):
                tasks.append("录屏")
            if self.device_audio.is_recording(serial):
                tasks.append("录制设备音频")
            if self.logcat_monitor.is_running(serial):
                tasks.append("logcat 监控")
            if self.logcat_capture.is_running(serial):
                tasks.append("logcat 抓取")
        except Exception:
            pass
        return tasks

    def _interruptible_sleep(self, seconds):
        """Python 侧延时等待，stop_run / 窗口关闭时提前返回。"""
        sess = self._ws_session(self._ws_cur(), create=False)
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self.state.shutting_down:
                return
            if sess is not None and getattr(sess, "aborted", False):
                return
            time.sleep(0.05)
