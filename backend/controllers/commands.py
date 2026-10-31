# -*- coding: utf-8 -*-
"""backend.controllers.commands —— 指令执行 / 保存 / 导入导出 / 自定义"""

from backend.controller import (
    SHELL_INTERACTIVE_RE, _EXIT_RE, datetime, device_is_root,
    get_pref, is_subshell_command, json, merge_adb_shell_commands_detailed,
    merge_builtins, needs_device, os, program_dir,
    root_intent, save_user_commands, tempfile, time,
    transform, uuid
)

class CommandMixin:
    """快捷指令：执行、保存、导入导出、自定义、停止。"""

    DEFAULT_CMD_TIMEOUT = 120

    def run_command(self, cmd_id):
        """下发一条快捷指令（可多设备循环，线程内执行）。"""
        if self.state.shutting_down:
            return {"ok": False}
        cmd_obj = next(
            (c for c in self.state.commands if c.get("id") == cmd_id), None)
        if cmd_obj is None:
            self._push_status("err", "⚠ 未找到命令：%s" % cmd_id)
            return {"ok": False}
        if self.session is None:
            self._push_status("err", "⚠ 会话尚未初始化，请稍后重试。")
            return {"ok": False}
        # 命中一次计一次使用频次（驱动「常用命令靠前」排序）
        self._bump_click(cmd_id)
        self.workers.spawn(None, self._execute, cmd_obj)
        return {"ok": True}

    def save_commands(self, commands):
        """前端维护的命令（界面增删改后）整体回写 commands.json。

        commands 已是归一化结构（仅用户自定义命令；前端已过滤掉内置默认）。
        后端只负责原子写回与内存态同步（state.commands），不重新归一化——
        前端持有的就是界面真实展示的命令，直接写回能完整保留 clickCount，
        避免下次启动「常用命令靠前」排序被重置。失败回 err 状态并 ok=False。
        """
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        ok, err = save_user_commands(commands)
        if not ok:
            self._push_status("err", "⚠ 保存命令失败：%s" % err)
            return {"ok": False, "reason": err}
        # 同步内存态：用户命令并入内置默认，保持与 boot 后一致，使后续
        # run_command / 点击计数基于最新列表（state.commands 是 run_command 的来源）。
        user_cmds = []
        for c in (commands or []):
            if isinstance(c, dict):
                c = dict(c)
                c.pop("builtin", None)
                user_cmds.append(c)
        self.state.commands = merge_builtins(user_cmds)
        self._push_status("ok", "✓ 命令已保存（%d 条）" % len(commands))
        return {"ok": True}

    def export_commands(self):
        """导出用户自定义命令（界面维护的命令，已过滤内置默认），供备份 / 分享。

        返回归一化结构（与 import_commands 互为逆操作）：仅用户命令，
        含 id / name / labels / commands / clickCount / inputOnly。
        """
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
            })
        return {"ok": True, "commands": user_cmds, "count": len(user_cmds)}

    def export_commands_save(self):
        """把导出的命令写入「程序运行处」目录并返回本地路径（前端可 open_local_file）。

        默认落在程序所在目录（exe 旁 / 开发态项目根），用户不指定路径时
        即可在程序同目录找到备份文件；该目录不可写时回退系统临时目录。
        """
        data = self.export_commands()
        if not data.get("ok"):
            return data
        text = json.dumps(data["commands"], ensure_ascii=False, indent=2)
        out_dir = program_dir()
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception:
            out_dir = tempfile.gettempdir()
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(out_dir, "commands_export_%s.json" % ts)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception as e:
            return {"ok": False, "reason": "写入失败：%s" % e}
        return {"ok": True, "path": path}

    def _dialog_types(self, pairs):
        """把 ((描述, 通配符), ...) 转成当前 pywebview 版本接受的 file_types。

        pywebview 在 5.x 之前 / 之后改了 file_types 格式：

        * 旧版(<5)：期望 ``(('描述', '*.ext'), ...)`` 这样的元组；
        * 新版(>=5)：期望 ``('描述 (*.ext)', ...)`` 这样的字符串，内部用
          ``re.search`` 解析。

        若按旧版元组传给新版，``parse_file_type`` 会对「元组」做正则匹配，
        抛出 ``TypeError: expected string or bytes-like object`` —— 正是
        Windows 下导入报错的根因。这里运行时探测一次，生成正确格式。
        """
        pairs = tuple(pairs)
        try:
            from webview.util import parse_file_type
        except Exception:
            # 拿不到探测函数时，回退到兼容性最好的「字符串格式」
            return tuple("%s (%s)" % (desc, ext) for desc, ext in pairs)
        # 探测新版字符串格式是否可用：能解析字符串就说明是新版
        try:
            parse_file_type("探测 (*.json)")
        except Exception:
            # 解析失败 -> 旧版，用元组格式
            return pairs
        # 新版：拼成 '描述 (*.ext)' 字符串
        return tuple("%s (%s)" % (desc, ext) for desc, ext in pairs)

    def _make_file_types(self):
        """命令导入用的 file_types（JSON / 所有文件）。"""
        return self._dialog_types((("JSON 命令备份", "*.json"),
                                  ("所有文件", "*.*")))

    def _open_dialog(self, pairs, label=""):
        """弹原生「打开文件」对话框，返回选中文件路径；取消 / 不可用返回空串。

        统一收口各版本的 create_file_dialog 签名差异与取消语义，调用方只需
        判断返回是否为空。
        """
        try:
            import webview
        except Exception as e:
            self._push_status("warn", "⚠ 当前环境不支持原生文件对话框：%s" % e)
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
            # 不同版本签名略有差异，做一次位置参数兜底
            try:
                files = win.create_file_dialog(
                    webview.OPEN_DIALOG, directory, False, None, ft)
            except TypeError:
                files = win.create_file_dialog(
                    webview.OPEN_DIALOG, directory, False)
        except Exception as e:
            self._push_status("warn", "⚠ 打开文件对话框失败：%s" % e)
            return ""
        if not files:
            return ""
        return files[0] if isinstance(files, (list, tuple)) else str(files)

    def import_commands_dialog(self):
        """弹出原生文件选择框（默认定位到程序目录），读取 JSON 并导入合并。

        与 import_commands 互为顺操作：对话框返回选中文件 -> 读取内容 ->
        交给 import_commands 按 id 合并（已存在覆盖、不存在新增）。取消选择
        时返回 reason="cancelled"，调用方可据此静默忽略。
        """
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        try:
            import webview
            # 新版 pywebview 已移除模块级 create_file_dialog，必须走窗口实例。
            # pywebview 会在创建窗口时把 api.window 注入到本对象；此处优先用
            # self.window，再回退到 active_window()，保证跨版本可用。
            win = getattr(self, "window", None)
            if win is None and hasattr(webview, "active_window"):
                win = webview.active_window()
            if win is None or not hasattr(win, "create_file_dialog"):
                return {"ok": False, "reason": "当前环境不支持原生文件对话框"}
            ft = self._make_file_types()
            directory = str(program_dir())  # WinForms 后端要求字符串，确保非 Path
            try:
                files = win.create_file_dialog(
                    webview.OPEN_DIALOG,
                    directory=directory,
                    allow_multiple=False,
                    file_types=ft,
                )
            except TypeError:
                # 不同版本 create_file_dialog 签名略有差异，做一次位置参数兜底：
                # 先带过滤器用 5 参数签名，再退化为不带过滤器的 3 参数签名。
                try:
                    files = win.create_file_dialog(
                        webview.OPEN_DIALOG, directory, False, None, ft
                    )
                except TypeError:
                    files = win.create_file_dialog(
                        webview.OPEN_DIALOG, directory, False
                    )
        except Exception as e:
            return {"ok": False, "reason": "打开文件对话框失败：%s" % e}
        if not files:
            return {"ok": False, "reason": "cancelled"}
        path = files[0]
        try:
            # utf-8-sig：用户在记事本里「另存为 UTF-8」会写入 BOM，而
            # json.loads 遇 \ufeff 直接报 "Unexpected UTF-8 BOM" —— 一个看不见的
            # 字符就让导入失败，且错误信息完全指不到真正原因。utf-8-sig 同时
            # 兼容无 BOM 的普通 UTF-8（与 config.json / 命令库的读法一致）。
            with open(path, "r", encoding="utf-8-sig") as f:
                text = f.read()
        except Exception as e:
            return {"ok": False, "reason": "读取文件失败：%s" % e}
        return self.import_commands(text)

    def import_commands(self, payload):
        """导入命令（备份 / 分享文件）。payload 可为：
          * 列表：[{id,name,labels,commands,...}, ...]
          * 字典：{"commands": [...]}
          * 上述结构的 JSON 字符串
        按 id 合并：已存在则覆盖，不存在则新增（缺失 id 自动生成）。
        导入后整体回写 commands.json 并同步内存态。
        """
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        if isinstance(payload, str):
            try:
                # 前端 / 第三方工具传进来的字符串可能带 BOM（记事本另存为 UTF-8），
                # json.loads 对 \ufeff 直接报 "Unexpected UTF-8 BOM"。
                payload = json.loads(payload.lstrip("\ufeff"))
            except Exception as e:
                return {"ok": False, "reason": "JSON 解析失败：%s" % e}
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
            cid = c.get("id")
            if not cid or cid not in existing:
                if not cid:
                    c = dict(c); c["id"] = "u_" + uuid.uuid4().hex[:10]
                added += 1
            existing[c.get("id")] = c
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

    def load_commands(self):
        """返回当前完整命令列表（用户命令 + 内置默认，已 merge_builtins 归一化）。

        前端用于导入 / 外部改动后刷新界面（避免重启应用）。
        """
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        out = []
        for c in (self.state.commands or []):
            d = c if isinstance(c, dict) else vars(c)
            out.append(dict(d))
        return {"ok": True, "commands": out}

    def run_custom(self, text):
        """执行自定义命令：与快捷指令同源——按受控设备逐台循环并通过
        adb_inject.transform 自动注入 `-s <serial>`，彻底告别
        "more than one device/emulator"。纯 PC 脚本（不含 adb/scrcpy）
        走单次执行旁路。"""
        text = (text or "").strip()
        if not text:
            return {"ok": False}
        if self.session is None:
            self._push_status("err", "⚠ 会话尚未初始化，请稍后重试。")
            return {"ok": False}
        # 复用 _execute 的「按设备展开 + transform + shell 合并」完整链路
        self.workers.spawn(None, self._execute, {
            "id": "__custom__", "name": "自定义命令", "commands": [{"command": text}],
        })
        return {"ok": True}

    def stop_run(self):
        """终止当前命令（等价 Tk 版 ctrl+c / 停止）。"""
        if self.session is not None:
            self._push_status("err", "⏹ 已发送停止信号，正在终止当前命令…")
            try:
                self.session.kill()
            except Exception:
                pass
        else:
            self._push_status("warn", "当前没有正在运行的命令。")
        self._sync_stop_state(interactive=False)
        return {"ok": True}

    def _execute(self, cmd_obj):
        """执行一条快捷指令：按需逐设备循环 + 每条命令带 delay。

        用户命令「单飞」：同一时刻只允许一条命令真正执行（_user_lock 排队），
        后续命令等上一条结束后再跑——避免连点多条时输出在指令台交错混淆；
        也保证 stop_run 的语义是「停掉当前这一条」。shutdown 后排队任务直接
        放弃，不再往已终止的会话里写命令。

        整体兜异常：命令下发链路（transform / 会话 / 设备快照）任何未预期错误
        都只转化为一条错误状态，绝不让 worker 线程裸抛到 threading.excepthook
        （那只会落一份崩溃日志，用户在界面上看不到任何反馈）。
        """
        with self._user_lock:
            if self.state.shutting_down:
                return
            busy, changed = self.state.begin_run()
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
                            self._push_status(
                                "err", "⚠ 命令「%s」需要指定设备，请先在左侧勾选设备。" % name)
                            return
                        for serial in serials:
                            self._push_status("info", "──── 设备: %s ────" % serial)
                            if not self._run_entries(entries, serial):
                                break
                    else:
                        self._push_status(
                            "info", "──── 执行「%s」（无需指定设备）────" % name)
                        self._run_entries(entries, None)
                except Exception as ex:
                    self._push_status(
                        "err", "⚠ 命令执行出现异常：%s" % ex)
            finally:
                # 交互式 adb shell（`adb shell` 直通）结束后会话仍是交互态：此时
                # 「停止」按钮必须继续亮着，用户才能把这条交互会话 kill 掉。
                # AppState 的 busy 本就包含交互态，但没人通知它——这里在 end_run
                # 之前按会话实际状态同步一次（交互态下 busy 不变，不会重复广播；
                # 非交互命令照常由 end_run 熄灭按钮）。
                self._sync_stop_state()
                busy, changed = self.state.end_run()
                if changed:
                    self.bus.push("stop_state", {"running": busy})

    def _run_entries(self, entries, serial):
        """逐条下发命令；adb shell 交互 / 合并 / delay 与 legacy 语义一致。
        返回 False 表示执行被中断（超时/停止），上层据此停止后续设备。"""
        # shutdown() 会把 self.session 置空（杀完再清引用），而本方法跑在后台
        # worker 里：不检查就会踩 None 抛 AttributeError，被 _execute 的兜底
        # 翻译成一条「命令执行出现异常：'NoneType' object has no attribute …」——
        # 关窗瞬间用户看到一条毫无意义的报错。这里静默放弃即可。
        if self.session is None:
            return False
        raw_cmds = [e.get("command", "") for e in entries]
        if serial:
            raw_cmds = [transform(c, serial) for c in raw_cmds]
        merged = merge_adb_shell_commands_detailed(raw_cmds)
        timeout = self._cmd_timeout()
        for cmd, end_idx in merged:
            if not cmd.strip():
                continue
            # root / unroot 切换保护（见 _skip_root_switch）：已在目标状态、
            # 或该设备有进行中的录屏 / 抓取时，本条命令不下发。
            if self._skip_root_switch(cmd, serial):
                continue
            stripped = cmd.strip()
            was_interactive = bool(self.session.in_interactive_shell)
            # 交互式（直通）判定的三个来源：
            #   1. 已经在子 shell 里（上一轮 adb shell / powershell 的直通）；
            #   2. 裸 `adb shell`：后面几条已被 merge 合并，只剩单独一条时才直通；
            #   3. 裸 powershell / cmd / bash —— 这类命令没人合并，它在持久会话
            #      里另起一个进程抢走 stdin，后面每条的结束标记都被内层读走；
            #      `exit` 更是连标记一起丢掉再退出，外层永远等不到 → 死锁。
            interactive = (was_interactive
                           or bool(SHELL_INTERACTIVE_RE.match(stripped))
                           or is_subshell_command(stripped))
            self._push_cmd(cmd)
            if interactive and not was_interactive:
                # 推在指令台而不是顶栏：用户此刻盯着就是这块面板，而且「后续命令
                # 去哪了」本身就是命令流的一部分，混进全局跑马灯很容易错过。
                self._push_console(
                    "info",
                    "» 已进入交互式 shell：后续命令直接送入该子 shell，"
                    "输入 exit 可退出并恢复逐条执行")
            if interactive:
                ok = self.session.run(cmd, interactive=True)
                if ok and _EXIT_RE.match(stripped):
                    # `exit` 退出的是内层子 shell，外层会话仍然活着。不复位
                    # 直通态的话，之后每条命令都只能"盲写"（不写结束标记、
                    # 无法判断成败），等于把会话永久降级。
                    self.session.leave_interactive()
                    # 子进程退出是异步生效的：紧接着写的命令有概率仍被投递给
                    # 正在退出的那个 shell，留一点间隔再继续。
                    self._interruptible_sleep(0.15)
                    self._push_console("info", "« 已退出交互式子 shell，恢复逐条执行")
            else:
                # 兜底超时：没有它，任何一条"哑"命令（读 stdin 的工具、卡住的
                # adb）都会永久占用 _user_lock，后续命令全部排队 —— 界面表现
                # 就是「整程序卡死、点不动」。超时由 run() 内部杀会话并返回 False。
                ok = self.session.run(cmd, timeout=timeout)
            if not ok:
                self._push_status("info", "✗ 执行中断")
                return False
            delay = 0
            if not interactive and 0 <= end_idx < len(entries):
                delay = int(entries[end_idx].get("delay", 0) or 0)
            if delay:
                # 旧实现把 Start-Sleep 塞进 powershell 会话：命令间 delay 超过
                # run(timeout=10) 会被误判超时杀掉整个会话，且占用 shell 影响
                # 并发命令。改为 Python 侧可打断 sleep（不占会话、可被停止）。
                self._interruptible_sleep(delay / 1000.0)
        self._push_status("info", "✓ 完成")
        return True

    def _cmd_timeout(self):
        """本条序列里非交互命令的超时秒数；None 表示不限制。"""
        try:
            v = int(get_pref("cmd_timeout", self.DEFAULT_CMD_TIMEOUT))
        except (TypeError, ValueError):
            v = self.DEFAULT_CMD_TIMEOUT
        return v if v > 0 else None

    def _skip_root_switch(self, cmd, serial):
        """本条命令是否应跳过（不下发）：root 状态切换的两种「跳过」情形。

        `adb root` / `adb unroot` 会重启设备端 adbd，杀掉经它拉起的
        screenrecord / tinycap（录屏视频缺 moov、不完整），并断开 logcat
        监控 / 抓取与文件操作。而重复切换（已在目标状态）除了重启没有任何
        效果——这是最常见的误伤：用户随手再点一次「root」，在录的屏就断了。
        因此下发前逐设备判断：

          1. 已在目标状态（要 root 的已 root / 要 unroot 的未 root）→ 跳过；
          2. 状态确实要变、但该设备有进行中的任务 → 跳过并说明，避免静默
             数据丢失（想切换请先停止录屏 / 抓取）。

        复合命令（`adb root && adb shell xx`）无法只跳过其中一段，整条跳过。
        返回 True 表示调用方应 `continue`（本条不下发，其 delay 一并跳过）。
        """
        intent = root_intent(cmd)
        if not intent:
            return False
        # 无序列号（纯 PC 旁路）不可能是设备 root 切换，直接放行
        if not serial:
            return False
        adb = self.state.adb_path or "adb"
        try:
            rooted = device_is_root(adb, serial)
        except Exception:
            rooted = False   # 探测失败按「需要切换」：交给下面的任务检查兜底
        # 已在目标状态：切换是零收益的无谓重启
        if (intent == "root") == bool(rooted):
            self._push_status(
                "info",
                "ℹ 设备 %s 已%s，跳过 `%s`（重复切换只会重启 adbd，"
                "可能中断进行中的录屏 / 抓取）"
                % (serial, "处于 root" if rooted else "未 root", cmd.strip()))
            return True
        # 状态确实要变：该设备有进行中的任务则跳过（任务会随 adbd 重启全断）
        busy = self._device_busy_tasks(serial)
        if busy:
            self._push_toast(
                "warn",
                "⚠ 设备 %s 正在%s：`%s` 会重启 adbd 并中断这些任务"
                "（录屏视频将不完整、日志抓取会断）。已跳过执行——"
                "请先停止录屏 / 抓取，再执行 root 状态切换。"
                % (serial, "、".join(busy), cmd.strip()))
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
        """Python 侧延时等待，stop_run / 窗口关闭时提前返回。

        以 50ms 步长轮询而非一次性 sleep：kill 会让 ShellSession.aborted 置位，
        延时中的批处理能及时感知停止，关闭时也无需等满整个 delay。
        """
        sess = self.session
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self.state.shutting_down:
                return
            if sess is not None and getattr(sess, "aborted", False):
                return
            time.sleep(0.05)
