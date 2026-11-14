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
            bstate = {"total": len(serials), "ok": 0, "fail": 0,
                      "dir": save_dir, "errs": [], "saved": save_file}
            with self._shot_batch_lock:
                self._shot_batch = bstate
        failed = []
        for s in serials:
            try:
                self.workers.spawn(
                    "screenshot_%s_%d" % (s, next(self._shot_seq)),
                    self._do_screenshot, s, save_dir, to_clipboard and not batch,
                    batch, bstate, save_file)
            except Exception as e:
                failed.append(s)
                if batch:
                    self._shot_batch_done(
                        ok=False, serial=s, err="无法启动截图线程：{}".format(e),
                        bstate=bstate)
                else:
                    self._push_status(
                        "err", "⚠ 无法启动截图线程 {}：{}".format(s, e))
        if failed and len(failed) == len(serials):
            return {"ok": False, "reason": "spawn_error", "failed": failed}
        if failed:
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
        if b is None:
            return
        with self._shot_batch_lock:
            if b.get("closed"):
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
                self._shot_batch = None
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
        self._shot_state_change(1)
        try:
            self._do_screenshot_locked(serial, save_dir, to_clipboard, batch,
                                       bstate, save_file)
        except Exception:
            if batch:
                self._shot_batch_done(ok=False, serial=serial, err="内部错误",
                                      bstate=bstate)
            raise
        finally:
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
            self.bus.push("tool", payload)

    def screenshot_data(self, path):
        """读取已保存的截图文件，返回 base64（供前端在截图卡片下方预览）。

        路径来自后端自己生成的落盘路径，可信；仍做存在性 + PNG 魔数校验，
        避免把非图片 / 不存在的文件当成预览图返回。
        """
        import base64
        p = (path or "").strip()
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