"""backend.controllers.screenshot —— 截图"""

from backend.controller import (
    ScreenCapturer,
    clipboard,
    get_pref,
    os,
)
from core.longpath import long_path, path_isfile


class ScreenshotMixin:
    """截图（单设备/批量/剪贴板）。"""

    def screenshot(self, serial=None, to_clipboard=None, save_file=None):
        """对勾选（或指定）设备各截一张 PNG。

        to_clipboard：是否同步写入系统剪贴板。前端在开关变化时同时下发这个值
        （即时、不依赖 config.json 是否可写）；未传则读用户偏好
        （shot_to_clipboard，缺省 = 开启）。
        save_file：是否把图写入保存目录（缺省 = 开启，对应前端「自动保存文件」
        开关）。关闭时不往保存目录落盘，只写到系统临时目录用于预览/剪贴板，
        避免不想要存档时保存目录被一堆截图占满。

        多设备批量时**不自动复制**：剪贴板一次只能放一张，几台设备的后台线程
        互相覆盖后最终是哪一张完全不确定，还不如明确告知（文件照常各存一份）。

        完成通知（toast）分两种形态：单设备——每台完成即弹一条；
        批量——各 worker 只记数，全部到齐后由 _shot_batch_done 弹一条汇总，
        避免 N 台设备弹 N 条 toast 刷屏。

        按钮态：每个截图 worker 入口在途 +1（广播 shot_state
        running=true，前端禁用「立即截图」防连点），收尾时 -1，
        全部结束才恢复——用户点完就看清"在跑了"，不会反复点。
        spawn 本身失败（连线程都起不来的极端情况）不会有 worker 登记，
        由前端按调用失败恢复按钮（见 app.js 点击处理）。
        """
        serials = self._target_serials(serial)
        if not serials:
            self._push_status("err", "⚠ 截图前请先勾选至少一个设备。")
            return {"ok": False, "reason": "no_device"}
        if to_clipboard is None:
            to_clipboard = self._shot_to_clipboard_pref()
        to_clipboard = bool(to_clipboard)
        if save_file is None:
            save_file = self._shot_save_file_pref()
        save_file = bool(save_file)
        batch = len(serials) > 1
        save_dir = self._default_save_dir()
        if to_clipboard and batch:
            self._push_status(
                "warn", "⚠ 多设备批量截图不自动写入剪贴板（一次只能放一张），"
                        "图片已分别保存到保存目录。")
        bstate = None
        if batch:
            # 批量汇总计数器：_do_screenshot 完成一台记一笔，到齐后弹一条 toast。
            # 计数器**随 worker 走**（bstate 引用作为参数传下去），不是共用一张表：
            # 上一批还没跑完就再点一次时，它的 worker 仍在记账 —— 旧实现两批共用
            # 同一个字典，前一批的 done 把后一批提前凑满，弹出一条台数不对的汇总；
            # 而后一批真正到齐时 _shot_batch 已置 None，连提示都没有。实测「2 台 +
            # 2 台」连点：只弹一条「✓ 已完成 2 台设备的截图」，保存目录里却是 4 张。
            bstate = {"total": len(serials), "ok": 0, "fail": 0,
                      "dir": save_dir, "errs": [], "saved": save_file}
            with self._shot_batch_lock:
                self._shot_batch = bstate      # 仅供外部查询「当前批次」
        failed = []
        for s in serials:
            # 每次截图一个独立 worker key：固定用 "screenshot_<serial>" 时，上一张
            # 还没截完就再点一次，Workers 会按同名把这次请求**静默丢弃**，而 API
            # 照旧返回 {"ok": True} —— 用户以为连截了两张，实际只有一张。
            # 文件名带序号（ScreenCapturer._seq），并行两次也不会互相覆盖。
            # 在途登记放在 worker 入口（_do_screenshot），这里不碰计数器：
            # +1/-1 同源同宿，任何执行时序（同步/异步 spawn）都自然平衡。
            try:
                self.workers.spawn(
                    "screenshot_%s_%d" % (s, next(self._shot_seq)),
                    self._do_screenshot, s, save_dir, to_clipboard and not batch,
                    batch, bstate, save_file)
            except Exception as e:
                # 线程起不来（线程数耗尽 / 内存告急）：这台没有 worker，也就不会
                # 有任何人来记账 —— 批量汇总永远凑不齐（那条 toast 再也弹不出来），
                # 而 API 仍回 ok=True，前端的禁用态只能等下一次 devices 事件才解。
                # 与安装 / 诊断包同样处理：当场记一笔失败。
                failed.append(s)
                if batch:
                    self._shot_batch_done(
                        ok=False, serial=s, err="无法启动截图线程：{}".format(e),
                        bstate=bstate)
                else:
                    self._push_status(
                        "err", "⚠ 无法启动截图线程 {}：{}".format(s, e))
        if failed and len(failed) == len(serials):
            # 一台都没跑起来：明确告诉调用方失败，前端据此立刻恢复按钮
            # （没有 worker 就没有 shot_state 事件，等不到那次「已完成」）。
            return {"ok": False, "reason": "spawn_error", "failed": failed}
        if failed:
            # 部分失败：把名单带上，调用方/日志据此知道哪几台没截到。
            return {"ok": True, "failed": failed}
        return {"ok": True}

    def _shot_state_change(self, delta):
        """截图在途任务数 +/-1，越过 0 边界时向前端广播 shot_state。

        前端「立即截图」禁用态的唯一事实来源：点击时乐观禁用只是即时反馈，
        完成 / 异常收尾后的恢复由本事件驱动（与 rec_state 同一套路）。
        计数而非布尔：两次截图请求叠上时（API 直调、禁用生效前的竞态），
        先结束的那个不会把另一个的禁用态提前解开；0<->1 翻转才推事件，
        批量 N 台设备也只推一对 true/false，不刷事件队列。
        """
        with self._shot_state_lock:
            self._shot_inflight += delta
            running = self._shot_inflight > 0
            if running == self._shot_running:
                return
            self._shot_running = running
        self.bus.push("shot_state", {"running": running})

    def _shot_batch_done(self, ok, serial, err=None, bstate=None):
        """批量截图的一台完成：记数，全部到齐时弹一条汇总 toast。

        汇总而非逐台弹：多设备（本工具的主场景）一次点击会给每台设备各起一个
        worker，逐台弹 toast 会瞬间刷屏；成功/失败计数 + 保存目录一条说清。

        bstate 是本 worker 所属那一批的计数器（由 screenshot() 创建并传下来）。
        必须按批记：两批叠在一起时，若共用一张表，前一批的完成会把后一批提前
        凑满，弹出台数不对的汇总，而真正完成的那批反倒一声不响。
        """
        b = bstate if bstate is not None else self._shot_batch
        if b is None:                           # 从未开启批量（单设备）
            return
        with self._shot_batch_lock:
            if b.get("closed"):
                # 这一批已经结算过了：同一台被重复记账（worker 内部异常由
                # _do_screenshot 记了一笔，spawn 那一层又兜了一次）时，若这里
                # 再记，就会在 summarize 之后又弹一条台数不对的汇总。
                return
            if ok:
                b["ok"] += 1
            else:
                b["fail"] += 1
                b["errs"].append("{}：{}".format(serial, err or "未知原因"))
            done = b["ok"] + b["fail"]
            if done < b["total"]:
                return
            b["closed"] = True
            if self._shot_batch is b:
                self._shot_batch = None         # 先摘计数器，避免与下一批交叉
        saved = b.get("saved", True)
        if b["fail"]:
            where = ("保存目录 {}".format(b["dir"])) if saved else "（未保存到目录）"
            self._push_toast(
                "warn",
                "⚠ 批量截图完成：%d 成功，%d 失败（%s）——%s"
                % (b["ok"], b["fail"], "；".join(b["errs"])[:120], where))
        else:
            where = ("保存目录 {}".format(b["dir"])) if saved else "（未保存到目录）"
            self._push_toast(
                "ok", "✓ 已完成 %d 台设备的截图，%s"
                % (b["ok"], where))

    def _shot_to_clipboard_pref(self):
        """用户偏好：截图后同步到粘贴板与否（缺省开启）。"""
        try:
            return bool(get_pref("shot_to_clipboard", True))
        except Exception:
            return True

    def _shot_save_file_pref(self):
        """用户偏好：截图是否写入保存目录（缺省开启）。

        关掉（前端「自动保存文件」取消勾选）后不往保存目录落盘，只写到系统
        临时目录供预览/剪贴板用，避免不想要的存档占用保存目录。
        """
        try:
            return bool(get_pref("shot_save_file", True))
        except Exception:
            return True

    def _do_screenshot(self, serial, save_dir, to_clipboard=False, batch=False,
                       bstate=None, save_file=True):
        # 在途登记放在 worker 入口：与 finally 的 -1 严格同源，成败甚至抛
        # 异常都平衡；批量 N 台也只在 0<->1 翻转时推事件（见 _shot_state_change）
        self._shot_state_change(1)
        try:
            self._do_screenshot_locked(serial, save_dir, to_clipboard, batch,
                                       bstate, save_file)
        except Exception:
            if batch:
                # 未预期的异常也要记进批次账：否则汇总 toast 永远等不齐，
                # 下一批之前 _shot_batch 一直挂着（按钮态由 finally 保证恢复）
                self._shot_batch_done(ok=False, serial=serial, err="内部错误",
                                      bstate=bstate)
            raise
        finally:
            # 成败甚至抛异常，在途计数都必须回落：漏一次 -1，「立即截图」
            # 会被 shot_state 永远锁在禁用态（按钮假死，只能重启程序）
            self._shot_state_change(-1)

    def _do_screenshot_locked(self, serial, save_dir, to_clipboard=False,
                             batch=False, bstate=None, save_file=True):
        path, err = ScreenCapturer.screenshot(
            self.state.adb_path, serial, save_dir, save_file)
        if err:
            self._push_status("err", "⚠ 截图失败 {}: {}".format(serial, err))
            if batch:
                self._shot_batch_done(ok=False, serial=serial, err=err,
                                      bstate=bstate)
            return
        # 主反馈立刻给：图已落盘这个事实不再等剪贴板。写系统剪贴板要解 PNG
        # （1080x2400 纯 Python 约 1~2 秒），让它排在「已保存」提示之后，
        # 用户点击截图后第一时间就看到结果，而不是干等剪贴板。
        # 批量模式例外：N 台设备各弹一条会刷屏，toast 收口到 _shot_batch_done
        # 的一条汇总，这里只写状态栏明细。
        # save_file=False 时不落盘到保存目录（只到临时目录供预览/剪贴板用），
        # 措辞改「截图完成（未保存到目录）」避免用户去保存目录找一份不存在的图。
        if save_file:
            saved_msg = "✓ 已保存截图: {}".format(path)
        else:
            saved_msg = "✓ 截图完成（未保存到目录）"
        if batch:
            self._push_status("ok", saved_msg)
        else:
            self._push_toast("ok", saved_msg)
        payload = {"type": "screenshot", "serial": serial, "path": path}
        clip_ok = None
        if to_clipboard:
            # 剪贴板是不可靠的外部资源（被别的程序锁住、远程桌面会话、权限…），
            # 失败只影响「能否直接粘贴」，绝不影响已经落盘的那张图。
            clip_ok, clip_err = clipboard.copy_image(path)
            if clip_ok:
                self._push_status("ok", "✓ 已复制到粘贴板")
                payload["clipboard"] = True
            else:
                self._push_status(
                    "warn", "⚠ 已保存截图: {}（复制到粘贴板失败：{}）".format(path, clip_err or "未知原因"))
                payload["clipboard"] = False
        if batch:
            self._shot_batch_done(ok=True, serial=serial, bstate=bstate)
        else:
            # 单设备：tool 事件即时推（前端可据此刷新缩略图等）
            self.bus.push("tool", payload)

    def screenshot_data(self, path):
        """读取已保存的截图文件，返回 base64（供前端在截图卡片下方预览）。

        路径来自后端自己生成的落盘路径，可信；仍做存在性 + PNG 魔数校验，
        避免把非图片 / 不存在的文件当成预览图返回。
        """
        import base64
        p = (path or "").strip()
        # 长路径安全：截图落在用户的保存目录里，路径可以超长。Windows 上
        # os.path.isfile 对超长路径返回 False → 预览图读不出来（界面空白）。
        if not p or not path_isfile(p):
            return {"ok": False, "reason": "missing"}
        try:
            with open(long_path(p), "rb") as f:
                data = f.read()
        except Exception as e:
            return {"ok": False, "reason": str(e)}
        if len(data) < 8 or data[:8] != b"\x89PNG\r\n\x1a\n":
            return {"ok": False, "reason": "not_png"}
        return {"ok": True, "data": base64.b64encode(data).decode("ascii"),
                "name": os.path.basename(p)}
