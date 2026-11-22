"""backend.controllers.file —— 文件浏览 / 增删改 / 上传下载"""

import contextlib
import uuid
from typing import ClassVar

from backend.controller import (
    os,
    push_timeout_for,
    safe_name,
    subprocess,
    sys,
    threading,
)
from core.longpath import long_path, path_getsize, path_isdir, path_isfile


def _build_browse_info(title):
    """构造 SHBrowseForFolder 用的 BROWSEINFO，返回 ``(bi, display_buf)``。

    单独抽出来是为了能在**非 Windows** 上回归这段 ctypes —— 它曾经这样写：

        bi.pszDisplayName = ctypes.create_unicode_buffer(2048)

    `pszDisplayName` 的字段类型是 `c_wchar_p`，而 `create_unicode_buffer` 返回的
    是 `c_wchar_Array_2048`，ctypes 直接拒绝赋值：

        TypeError: incompatible types, c_wchar_Array_2048 instance instead of
        c_wchar_p instance

    这行抛出的异常被 `_win_select_folder` 外层的 `except Exception: return None`
    吞成「用户取消」。于是后端回 `{"ok": false, "reason": "cancelled"}`，前端按
    取消静默处理 —— 用户看到的就是「保存目录的『选择』按钮点了没反应」，而且
    在 Windows 上**每次**都这样。必须 cast 成指针后再赋。
    """
    import ctypes
    from ctypes import wintypes

    BIF_RETURNONLYFSDIRS = 0x0001
    BIF_USENEWUI = 0x0040          # 新版 UI：带可粘贴路径的输入框
    BIF_NONEWFOLDERBUTTON = 0x0200  # 不显示「新建文件夹」

    class BROWSEINFO(ctypes.Structure):
        _fields_ = [
            ("hwndOwner", wintypes.HWND),
            ("pidlRoot", ctypes.c_void_p),
            ("pszDisplayName", ctypes.c_wchar_p),
            ("lpszTitle", ctypes.c_wchar_p),
            ("ulFlags", wintypes.UINT),
            ("lpfn", ctypes.c_void_p),
            ("lParam", ctypes.c_void_p),
            ("iImage", wintypes.INT),
        ]

    display = ctypes.create_unicode_buffer(wintypes.MAX_PATH + 1)
    bi = BROWSEINFO()
    bi.pidlRoot = None
    # 关键：cast 成 wchar 指针，不能直接赋 buffer（见上方说明）
    bi.pszDisplayName = ctypes.cast(display, ctypes.c_wchar_p)
    bi.lpszTitle = title or "选择文件夹"
    bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_USENEWUI | BIF_NONEWFOLDERBUTTON
    bi.lpfn = None
    bi.lParam = None
    bi.iImage = 0
    return bi, display


def _win_select_folder(title):
    """Windows 原生「选择文件夹」对话框（SHBrowseForFolder + BIF_USENEWUI）。

    返回选中的绝对路径；用户取消或当前平台不支持（非 Windows）时返回 None。

    这是 pywebview 拿不到窗口时的兜底（正常路径见 `_pick_folder`）。对话框必须
    设 owner 为当前前台窗口：`hwndOwner = None` 时它不受本窗口约束，会跑到
    其它窗口后面去 —— 表现同样是「点了没反应」。
    """
    if not sys.platform.startswith("win"):
        return None
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
        return None
    try:
        bi, _display = _build_browse_info(title)
        shell32 = ctypes.windll.shell32
        ole32 = ctypes.windll.ole32
        user32 = ctypes.windll.user32
        # ---- Win32 原型必须显式声明 --------------------------------------
        # 不声明 argtypes 时 PIDL 这种指针参数按 C int（32 位）传，64 位下直接
        # 被截断 —— SHBrowseForFolder 拿不到有效的 PIDL，这段兜底路径必然失败
        # （用户看到的是「选择目录」按钮点了没反应）。
        ole32.CoInitialize.argtypes = [ctypes.c_void_p]
        ole32.CoInitialize.restype = wintypes.HRESULT
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        ole32.CoTaskMemFree.restype = None
        ole32.CoUninitialize.argtypes = []
        ole32.CoUninitialize.restype = None
        shell32.SHBrowseForFolder.argtypes = [ctypes.c_void_p]
        shell32.SHBrowseForFolder.restype = ctypes.c_void_p
        shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p,
                                                 ctypes.c_wchar_p]
        shell32.SHGetPathFromIDListW.restype = ctypes.c_int
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wintypes.HWND
        try:
            bi.hwndOwner = user32.GetForegroundWindow()
        except Exception:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
            bi.hwndOwner = None

        ole32.CoInitialize(None)
        pidl = None
        try:
            pidl = shell32.SHBrowseForFolder(
                ctypes.cast(ctypes.byref(bi), ctypes.c_void_p))
            if not pidl:
                return None
            # 缓冲区给足：MAX_PATH(260) 在多层归档目录下不够用，
            # SHGetPathFromIDListW 缓冲区不足时直接失败 —— 用户看到的是
            # 「明明选中了目录，却说没选」。先按 4096 试，失败再按它要的
            # 尺寸（它会把所需长度写回来）重试一次。
            buf = ctypes.create_unicode_buffer(4096)
            if not shell32.SHGetPathFromIDListW(
                    pidl, ctypes.cast(buf, ctypes.c_wchar_p)):
                try:
                    need = int(shell32.SHGetPathFromIDListW(pidl, None) or 0)
                except Exception:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
                    need = 0
                if need <= 0:
                    return None
                buf = ctypes.create_unicode_buffer(need + 1)
                if not shell32.SHGetPathFromIDListW(
                        pidl, ctypes.cast(buf, ctypes.c_wchar_p)):
                    return None
            return buf.value or None
        finally:
            # SHBrowseForFolder 返回的 PIDL 由调用方用 CoTaskMemFree 释放：
            # 不释放就是每点一次「选择目录」漏一次 COM 内存。
            with contextlib.suppress(Exception):
                if pidl:
                    ole32.CoTaskMemFree(pidl)
            ole32.CoUninitialize()
    except Exception:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
        return None


def _pick_folder(initial=None):
    """弹出「选择文件夹」对话框，返回 ``(路径, 失败原因)``。

    优先走 pywebview 的原生对话框（Windows 下是 WinForms 的 FolderBrowserDialog，
    自带 owner 窗口与置前行为，也可定位到初始目录）。路径非空即成功；否则
    reason ∈ {"cancelled", "unsupported", "error:<详情>"}。

    区分这三档不是为了好看：把「用户点了取消」和「对话框根本没打开」都揉成
    一个 None，前台就只能一律静默 —— 那正是「按钮点了没反应」的成因。
    """
    try:
        import webview
    except Exception:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
        return None, "unsupported"
    win = None
    try:
        if hasattr(webview, "active_window"):
            win = webview.active_window()
    except Exception:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
        win = None
    if win is None or not hasattr(win, "create_file_dialog"):
        return None, "unsupported"
    directory = initial if (initial and path_isdir(initial)) else ""
    try:
        res = win.create_file_dialog(webview.FOLDER_DIALOG, directory=directory)
    except TypeError:
        # 各版本签名略有差异（与 _open_dialog 同一套位置参数兜底）
        try:
            res = win.create_file_dialog(webview.FOLDER_DIALOG, directory)
        except TypeError:
            try:
                res = win.create_file_dialog(webview.FOLDER_DIALOG)
            except Exception as e:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
                return None, f"error:{e}"
        except Exception as e:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
            return None, f"error:{e}"
    except Exception as e:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
        return None, f"error:{e}"
    if not res:
        return None, "cancelled"
    path = res[0] if isinstance(res, (list, tuple)) else str(res)
    path = (path or "").strip()
    return (path, "") if path else (None, "cancelled")


class FileMixin:
    """设备文件浏览/增删改/上传下载/预览。"""

    # 目录刷新合并窗口（秒）。一次多选上传 N 个文件会在几秒内连续完成 N 次
    # 上传，每次都刷一次目录的话就是 N 次 `adb shell ls` + N 次列表重建。
    _FILE_REFRESH_DEBOUNCE_S = 0.4

    _FILE_OP_LABELS: ClassVar[dict[str, str]] = {
            "_do_file_list": "列出目录", "_do_file_mkdir": "创建目录",
            "_do_file_touch": "创建文件", "_do_file_remove": "删除",
            "_do_file_rename": "重命名", "_do_file_upload_data": "上传",
            "_do_file_upload_path": "上传",
            "_do_file_download": "下载", "_do_file_view": "查看",
        }

    def open_save_dir(self, dir_path=None):
        """在系统文件管理器打开保存目录（Windows 用 explorer / startfile）。"""
        d = (dir_path or "").strip() or self._default_save_dir()
        # 保留建目录的真实原因：路径落在只读位置 / 父目录不存在时，旧实现把
        # OSError 整个吞掉，转头发一句「目录不存在」——用户照着这句话去查，
        # 目录明明在，真正的问题是没权限。
        mkdir_err = ""
        try:
            os.makedirs(long_path(d), exist_ok=True)
        except OSError as e:
            mkdir_err = str(e)
        if not os.path.isdir(long_path(d)):
            why = mkdir_err or "路径不存在"
            self._push_status("err", f"⚠ 无法创建 / 打开目录 {d}：{why}")
            return {"ok": False, "text": why}
        try:
            if sys.platform.startswith("win"):
                os.startfile(d)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", d])
            else:
                subprocess.Popen(["xdg-open", d])
            self._push_status("info", f"📂 已打开目录：{d}")
            return {"ok": True}
        except Exception as e:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
            self._push_status("err", f"⚠ 无法打开目录 {d}: {e}")
            return {"ok": False, "text": str(e)}

    def select_save_dir(self, current=None):
        """弹出「选择文件夹」对话框，返回用户选中的目录。

        优先 pywebview 原生对话框，Windows 上窗口拿不到时退到 SHBrowseForFolder。
        三种结果要分清（前端据此决定说还是不说）：
          · 选中 → {"ok": True, "path": ...}
          · 取消 → {"ok": False, "reason": "cancelled"}（静默，谁都不想被取消烦到）
          · 打不开 → {"ok": False, "reason": "unsupported"/"error"} + 状态栏播报
        旧实现把后两者都揉成 cancelled，前端一律不吭声 —— 按钮点下去就像没接线。
        """
        path, why = _pick_folder(current)
        if not path and why == "unsupported" and sys.platform.startswith("win"):
            # pywebview 拿不到活动窗口（极少见）：退到系统原生对话框
            path = _win_select_folder("选择保存目录")
            why = "" if path else "cancelled"
        if path:
            return {"ok": True, "path": path}
        if why.startswith("error:"):
            msg = why[len("error:"):]
            self._push_status(
                "err", f"⚠ 打开「选择文件夹」失败：{msg}（可直接手动输入路径）")
            return {"ok": False, "reason": "error", "text": msg}
        return {"ok": False, "reason": why or "unsupported"}

    @staticmethod
    def _parent_dir(path):
        p = (path or "/").rstrip("/")
        if "/" not in p:
            return "/"
        return p.rsplit("/", 1)[0] or "/"

    def file_list(self, serial, path):
        if not serial:
            self._push_status("warn", "⚠ 请先在左侧勾选一台设备，再浏览它的文件")
            return {"ok": False, "reason": "no_device"}
        # 每次列目录用**唯一** worker key + 记录「该设备最新一次请求」：
        #  · 唯一 key：旧实现固定用 "file_<serial>"，上一次 `ls -la` 还没结束时
        #    （大目录 / 慢设备）用户再点进另一个目录，Workers 会按同名去重直接
        #    丢弃新请求且不报错 —— 界面停在旧目录，看起来「点了没反应」；
        #  · 最新序号：新请求发起后，先前那次迟到的响应会被丢弃，避免旧目录的
        #    内容覆盖刚打开的目录。
        seq = next(self._file_seq)
        self._file_req[serial] = seq
        # 记住「这台设备当前看的是哪个目录」：批量上传的合并刷新据此判断
        # 用户是否已经切走（切走了就别再把他弹回旧目录）。
        self._file_dir[serial] = path
        self.workers.spawn(f"filelist_{serial}_{seq:d}",
                           self._run_file_op, self._do_file_list,
                           serial, path, seq)
        return {"ok": True}

    def _do_file_list(self, serial, path, seq=None):
        entries, err = self.file_svc.list_dir(serial, path)
        if seq is not None and self._file_req.get(serial) != seq:
            return          # 已有更新的一次列目录请求，丢弃这次迟到的结果
        if err:
            self._push_status("err", f"⚠ 列出目录失败 {path}: {err}")
            self.bus.push("file", {"serial": serial, "path": path,
                                   "error": err})
        else:
            self.bus.push("file", {"serial": serial, "path": path,
                                   "entries": entries})

    def _file_refresh(self, serial, path):
        self.file_list(serial, self._parent_dir(path))

    def _schedule_file_refresh(self, serial, path):
        """把「稍后刷一次目录」合并成一个尾部请求（批量上传用）。

        一次勾选 20 个文件上传，前端会为每个文件单独调一次 file_upload_data，
        后端也就为每个文件各刷一次目录：20 次 `adb shell ls`（每次 100~300ms，
        全挤在同一条 adb 队列里）+ 20 次 file 事件让列表重建。用户看到的是
        文件列表反复闪烁、刚勾上的项被一轮轮清空，而真正需要的只是**最后
        一次**——那一刻目录里已经躺齐了全部文件。

        合并窗口取 _FILE_REFRESH_DEBOUNCE_S：比单个文件的上传间隔长，又短到
        用户不会觉得「传完了列表没更新」。同一设备只保留一个待触发定时器
        （后来的顶掉先前的），不同设备各算各的。
        """
        key = serial or ""
        target = self._parent_dir(path)
        with self._file_refresh_lock:
            old = self._file_refresh_timers.pop(key, None)
            if old is not None:
                old.cancel()
            timer = threading.Timer(
                self._FILE_REFRESH_DEBOUNCE_S, self._fire_file_refresh,
                args=(key, target))
            timer.daemon = True
            self._file_refresh_timers[key] = timer
            timer.start()

    def _fire_file_refresh(self, serial, target):
        """合并窗口到期：真正发起一次列目录请求。"""
        with self._file_refresh_lock:
            self._file_refresh_timers.pop(serial, None)
        if self.state.shutting_down:
            return
        # 用户在这 0.4 秒里点进了别的目录：这次刷新只会把界面弹回上传时的
        # 目录（而文件其实已经传好了）。直接丢弃，别打断他的浏览。
        cur = self._file_dir.get(serial)
        if cur and cur != target:
            return
        try:
            self.file_list(serial, target)
        except Exception as ex:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
            self._push_status("err", f"⚠ 刷新目录失败 {target}：{ex}")

    def _file_op(self, serial, do_fn, *args, key=None):
        """文件操作公共入口：无设备兜底 + 后台线程派发 + 立即返回。

        key 为空时退化为 "fileop_<serial>"（同名存活任务不重复启动，用于
        mkdir/touch/remove/rename 等互斥场景）；key 非空时作为后台线程去重键。
        批量下载必须用唯一 key（见 file_download），否则同一设备的多个文件会被
        Workers 去重掉、只剩第一个真正下载。

        被去重挡下时**不再谎报成功**：返回 busy 并给出提示，否则用户点了「新建
        文件夹」却什么都没发生、也没有任何解释。
        """
        if not serial:
            return {"ok": False, "reason": "no_device"}
        k = key or (f"fileop_{serial}")
        if self.workers.is_running(k):
            self._push_status("warn", "⚠ 上一项文件操作尚未完成，请稍候再试。")
            return {"ok": False, "reason": "busy"}
        self.workers.spawn(k, self._run_file_op, do_fn, serial, *args)
        return {"ok": True}

    def _run_file_op(self, do_fn, serial, *args):
        """后台执行文件操作，并把未预期异常转成用户可见的状态。

        没有这层兜底时，`subprocess.TimeoutExpired`（adb push/pull 大文件超过
        120s 超时）会直接杀死 worker 线程，只落一份用户看不到的 crash 日志：
        界面上表现为「点了下载/刷新/查看毫无反应」，且该设备的同名任务一直占着
        去重键，后续同类操作全被静默吞掉。
        """
        try:
            do_fn(serial, *args)
        except Exception as ex:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
            label = self._FILE_OP_LABELS.get(
                getattr(do_fn, "__name__", ""), "文件操作")
            self._push_status("err", f"⚠ {label}失败 {serial}：{ex}")

    def file_mkdir(self, serial, path):
        return self._file_op(serial, self._do_file_mkdir, path)

    def _do_file_mkdir(self, serial, path):
        ok, err = self.file_svc.make_dir(serial, path)
        if ok:
            self._push_status("ok", f"✓ 已创建目录: {path}")
        else:
            self._push_status("err", f"⚠ 创建目录失败 {path}: {err}")
        self._file_refresh(serial, path)

    def file_touch(self, serial, path):
        return self._file_op(serial, self._do_file_touch, path)

    def _do_file_touch(self, serial, path):
        ok, err = self.file_svc.touch(serial, path)
        if ok:
            self._push_status("ok", f"✓ 已创建文件: {path}")
        else:
            self._push_status("err", f"⚠ 创建文件失败 {path}: {err}")
        self._file_refresh(serial, path)

    def file_remove(self, serial, paths):
        paths = paths if isinstance(paths, list) else [paths]
        if not paths:
            self._push_status("warn", "⚠ 没有选中要删除的项目")
            return {"ok": False, "reason": "empty"}
        return self._file_op(serial, self._do_file_remove, list(paths))

    def _do_file_remove(self, serial, paths):
        ok, err = self.file_svc.remove(serial, paths)
        if ok:
            self._push_status("ok", f"✓ 已删除 {len(paths):d} 个项")
        else:
            self._push_status("err", f"⚠ 删除失败: {err}")
        if paths:
            self._file_refresh(serial, paths[0])

    def file_rename(self, serial, old, new):
        return self._file_op(serial, self._do_file_rename, old, new)

    def _do_file_rename(self, serial, old, new):
        ok, err = self.file_svc.rename(serial, old, new)
        if ok:
            self._push_status("ok", f"✓ 重命名: {old} -> {new}")
        else:
            self._push_status("err", f"⚠ 重命名失败: {err}")
        self._file_refresh(serial, old)

    def _push_upload_event(self, task_id, serial, name, remote, status,
                           percent=None, error=""):
        """推一条 file_upload 进度事件（前端上传队列据此更新对应项）。

        task_id 由前端生成并贯穿重试：一次「上传 → 失败 → 重试」用同一个 id，
        前端才能把新进度更新到原来那一格，而不是另起一行。事件载荷尽量自描述，
        前端不必回头查本地缓存就知道是哪台设备、哪个文件。
        """
        payload = {"task_id": task_id, "serial": serial, "name": name,
                   "remote": remote, "status": status}
        if percent is not None:
            payload["percent"] = percent
        if error:
            payload["error"] = error
        self.bus.push("file_upload", payload)

    def file_upload_data(self, serial, name, b64, remote, task_id=None,
                         progress=False):
        """前端以 base64 传文件内容（浏览器不暴露本地路径），后端落地后 push。

        与下载同理：每个文件一个独立 worker key，否则「一次选多个文件上传」会
        被 "fileop_<serial>" 去重吞掉 —— 只有第一个真正传到设备。

        task_id / progress 是「上传队列 + 进度条」的新通道（前端显式开启）；
        老调用方（自动化脚本 / 历史单测）不传这两个参数时行为完全不变。
        """
        return self._file_op(serial, self._do_file_upload_data, name, b64, remote,
                             task_id, progress,
                             key=f"fileup_{serial}_{next(self._file_seq):d}")

    def _do_file_upload_data(self, serial, name, b64, remote, task_id=None,
                             progress=False):
        import base64
        import tempfile
        # 进度通道开启才推事件：老路径（progress=False）一行事件都不发，状态栏与
        # 既有单测的观察点保持不变。
        use_progress = bool(progress and task_id)
        display = os.path.basename(name or "") or remote
        # 临时文件名带随机串：多设备/多文件并行上传同名文件时，固定名会互相覆盖，
        # 导致其中一个线程上传的是别人的内容（或中途被删而上传失败）。
        # 前端传来的 name 一律先取 basename 并净化：它若含路径分隔符，会把临时文件
        # 写到 %TEMP% 之外（甚至覆盖任意可写文件）。
        # 内容为空就直接失败：以前会照常写出一个 0 字节中转文件、push 上去，
        # 然后报「✓ 上传完成」—— 设备上多出一个空文件，用户以为传成功了。
        # 前端那一侧也已拦住，这里再兜一层（桥接直调 / 自动化脚本同样受保护）。
        if not (b64 or "").strip():
            why = "没有收到文件内容（读取结果为空）"
            self._push_status("err", f"⚠ 上传失败 {display}：{why}")
            if use_progress:
                self._push_upload_event(task_id, serial, name, remote,
                                        "failed", error=why)
            return
        tmp = os.path.join(
            tempfile.gettempdir(),
            "adb_up_{}_{}".format(uuid.uuid4().hex[:8],
                              safe_name(os.path.basename(name or ""))))
        try:
            with open(long_path(tmp), "wb") as f:
                # validate=True：默认会静默丢弃非法字符，桥接直调/自动化脚本
                # 传入带脏字符的 b64 时落盘内容被悄悄改变却报「上传成功」。
                # 前端取的是 dataURL 逗号后的纯 base64（无空白/换行），不受影响。
                f.write(base64.b64decode(b64 or "", validate=True))
        except Exception as e:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
            self._push_status("err", f"⚠ 解码上传文件失败：{e}")
            if use_progress:
                self._push_upload_event(task_id, serial, name, remote,
                                        "failed", error=str(e))
            return
        if use_progress:
            self._push_upload_event(task_id, serial, name, remote,
                                    "uploading", percent=0)
        # try/finally：upload 抛异常（大文件 push 超过 120s 超时、adb 中途消失）时
        # 旧实现会跳过 os.remove，每次失败都在 %TEMP% 留下一个多 MB 的孤儿文件。
        cancelled = False
        try:
            if use_progress:
                def on_pct(pct):
                    self._push_upload_event(task_id, serial, name, remote,
                                            "uploading", percent=pct)
                ok, err = self.file_svc.upload_stream(
                    serial, tmp, remote, progress=on_pct,
                    task_id=task_id, cleanup=(tmp,))
            else:
                ok, err = self.file_svc.upload(serial, tmp, remote)
        except Exception as e:  # noqa: BLE001  有意把异常转成用户可见的失败事件
            ok, err = False, str(e)
        finally:
            with contextlib.suppress(Exception):
                os.remove(tmp)
        cancelled = bool(task_id) and self.file_svc.is_cancelled(task_id)
        if cancelled:
            # 用户主动取消：不算失败，不弹红条；只在队列里标记已取消。
            self._push_upload_event(task_id, serial, name, remote, "cancelled")
        elif ok:
            self._push_status("ok", f"✓ 上传完成: {remote}")
            if use_progress:
                self._push_upload_event(task_id, serial, name, remote, "done", percent=100)
        else:
            self._push_status("err", f"⚠ 上传失败 {remote}: {err}")
            if use_progress:
                self._push_upload_event(task_id, serial, name, remote, "failed",
                                        error=err or "上传失败")
        # 合并刷新：多选上传时 N 个文件只刷一次目录（见 _schedule_file_refresh）
        # 取消的文件没写完整，仍刷一次以反映设备真实状态（半成本地文件已被清理）。
        self._schedule_file_refresh(serial, remote)

    def file_upload_pick(self, serial, remote_dir):
        """弹原生「选择文件」框，按**本地路径**直接 push —— 字节不过 js_api 桥。

        为什么不用 `<input type=file>`（拖拽那条路仍保留它）：浏览器控件只暴露
        File 对象、拿不到本地路径，只能把整个文件编码成 base64 交给后端。几百 MB
        的文件光「JSON 序列化 + 过桥 + 反序列化」就要几十秒，而这期间桥是独占的：

          * 前端 callApi 有 15s 超时 → 状态栏报「请求超时（15s）」，上传直接算失败；
          * take_events 轮询排在同一个桥后面 → 后端 push 期间推的进度事件全堆在
            队列里，等桥腾出来时 push 早已结束，进度条于是从 0% 一步跳到 100%。

        原生对话框只回路径，后端自己读文件，两个问题一起消失；大文件也不再需要
        在浏览器内存里先翻 1.33 倍的 base64。
        """
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        if not serial:
            self._push_status("warn", "⚠ 请先在左侧勾选一台设备（文件上传需要目标设备）")
            return {"ok": False, "reason": "no_device"}
        paths = self._open_dialog((("所有文件", "*.*"),), "选择要上传的文件",
                                  multiple=True)
        # 取消是正常操作，静默返回 —— 用户自己按的「取消」，不该再弹一条红字。
        if not paths:
            return {"ok": False, "reason": "cancelled"}
        directory = (remote_dir or "/sdcard").rstrip("/") or "/"
        items = []
        for local in paths:
            name = os.path.basename(local) or "未命名"
            # 取不到大小（路径过长 / 文件刚被删）不算失败：push 的成败由 adb 说了算，
            # 这里读大小只是为了给 push 估一个够宽的超时上界。
            items.append({"task_id": "p" + uuid.uuid4().hex[:10],
                          "path": local, "name": name,
                          "size": path_getsize(local),
                          "remote": directory + "/" + name})
        # 这里**不启动** worker：前端要先按这些条目把队列项画出来，再由它逐项调
        # file_upload_path 启动。反过来的话，几 KB 的小文件可能在队列项还没建好
        # 之前就 push 完并推了 done —— 那条事件因为没有对应项被前端丢掉，界面就
        # 永远停在 0%。
        return {"ok": True, "items": items}

    def file_upload_path(self, serial, local, remote, task_id=None):
        """按本地路径重传一个文件（上传队列里「重试」走这里）。

        与 file_upload_pick 同一条通道：路径由后端持有，用户不必回到文件夹重挑，
        内容也不必再经 js_api 桥搬一次。
        """
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        if not serial:
            return {"ok": False, "reason": "no_device"}
        if not path_isfile(local):
            display = os.path.basename(local or "") or remote
            self._push_status(
                "err", f"⚠ 上传失败 {display}：本地文件已不存在（可能被移动或删除）")
            return {"ok": False, "reason": "本地文件已不存在（可能被移动或删除）"}
        tid = task_id or ("p" + uuid.uuid4().hex[:10])
        self._file_op(serial, self._do_file_upload_path, local, remote, tid,
                      key=f"fileup_{serial}_{next(self._file_seq):d}")
        return {"ok": True, "task_id": tid}

    def _do_file_upload_path(self, serial, local, remote, task_id):
        """把本地文件 push 到设备（路径直传版）：带 adb push 的真实百分比进度。

        task_id 贯穿进度事件与取消：注册到 FileService 的传输表，前端点取消时
        cancel_transfer 据此找到 adb 进程并终止。
        """
        display = os.path.basename(local) or remote
        self._push_upload_event(task_id, serial, display, remote,
                                "uploading", percent=0)

        def on_pct(pct):
            self._push_upload_event(task_id, serial, display, remote,
                                    "uploading", percent=pct)

        try:
            ok, err = self.file_svc.upload_stream(
                serial, local, remote, progress=on_pct,
                timeout=push_timeout_for(path_getsize(local)),
                task_id=task_id)
        except Exception as e:  # noqa: BLE001  有意把异常转成用户可见的失败事件
            ok, err = False, str(e)
        if self.file_svc.is_cancelled(task_id):
            self._push_upload_event(task_id, serial, display, remote, "cancelled")
        elif ok:
            self._push_status("ok", f"✓ 上传完成: {remote}")
            self._push_upload_event(task_id, serial, display, remote, "done", percent=100)
        else:
            self._push_status("err", f"⚠ 上传失败 {remote}: {err}")
            self._push_upload_event(task_id, serial, display, remote, "failed",
                                    error=err or "上传失败")
        self._schedule_file_refresh(serial, remote)

    def file_download(self, serial, remote, local_dir, task_id=None):
        """下载一个文件到保存目录。task_id 可选：给了就走带进度/可取消的新通道。

        老调用（自动化 / 旧测试）不传 task_id，行为与从前完全一致（同步 pull +
        状态栏提示），零回归。前端队列传 task_id 后改走 file_download 事件。
        """
        if task_id:
            return self._file_op(
                serial, self._do_file_download_path, remote,
                local_dir or self._default_save_dir(), task_id,
                key=f"filedl_{serial}_{next(self._file_seq):d}")
        # 每个文件一个独立 worker key（含序列号），保证同一设备批量「下载选中」
        # 时所有文件各自成线程并行 pull，不会被 "fileop_<serial>" 去重吞掉。
        return self._file_op(
            serial, self._do_file_download, remote,
            local_dir or self._default_save_dir(),
            key=f"filedl_{serial}_{next(self._file_seq):d}")

    def _do_file_download(self, serial, remote, local_dir):
        path, err = self.file_svc.download(serial, remote, local_dir)
        if path:
            self._push_status("ok", f"✓ 已下载: {path}")
        else:
            self._push_status("err", f"⚠ 下载失败 {remote}: {err}")

    def _do_file_download_path(self, serial, remote, local_dir, task_id):
        """带进度、可取消的下载：走 download_stream，推 file_download 事件。"""
        name = os.path.basename(remote.rstrip("/")) or remote
        self._push_download_event(task_id, serial, name, remote, local_dir,
                                  "downloading", percent=0)

        def on_pct(pct):
            self._push_download_event(task_id, serial, name, remote, local_dir,
                                      "downloading", percent=pct)

        try:
            path, err = self.file_svc.download_stream(
                serial, remote, local_dir, progress=on_pct, task_id=task_id)
        except Exception as e:  # noqa: BLE001  有意把异常转成用户可见的失败事件
            path, err = None, str(e)
        if self.file_svc.is_cancelled(task_id):
            self._push_download_event(task_id, serial, name, remote, local_dir,
                                      "cancelled")
        elif path:
            self._push_status("ok", f"✓ 已下载: {path}")
            self._push_download_event(task_id, serial, name, remote, local_dir,
                                      "done", percent=100, local=path)
        else:
            self._push_status("err", f"⚠ 下载失败 {remote}: {err}")
            self._push_download_event(task_id, serial, name, remote, local_dir,
                                      "failed", error=err or "下载失败")

    def _push_download_event(self, task_id, serial, name, remote, local_dir,
                             status, percent=None, error="", local=""):
        """推一条 file_download 进度事件（前端下载队列据此更新对应项）。"""
        payload = {"task_id": task_id, "serial": serial, "name": name,
                   "remote": remote, "local_dir": local_dir, "status": status}
        if percent is not None:
            payload["percent"] = percent
        if error:
            payload["error"] = error
        if local:
            payload["local"] = local
        self.bus.push("file_download", payload)

    def file_transfer_cancel(self, task_id):
        """取消一个正在进行的上传/下载：终止 adb 进程并清理半成本地文件。

        由前端传输队列的「取消」按钮调用。找不到任务（已自然结束 / 从未登记）
        也返回 ok，避免竞态下用户点了取消却看到报错。
        """
        found = self.file_svc.cancel_transfer(task_id)
        return {"ok": True, "found": found, "task_id": task_id}

    def file_view(self, serial, path):
        # 查看同样用唯一 key：连续点开两个文件的「查看」时，固定 key 会让第二个
        # 请求被去重静默丢弃（用户看到的是上一个文件的内容 / 什么都没发生）。
        return self._file_op(serial, self._do_file_view, path,
                             key=f"fileview_{serial}_{next(self._file_seq):d}")

    def open_local_file(self, path):
        """用系统默认程序打开本地文件（大文件查看弹窗的「查看」按钮）。

        路径来自本程序 pull 落地的临时文件；仍做存在性校验，
        避免把明显非法的输入透传给系统打开机制。
        """
        try:
            # 长路径安全：这里只做「存在性校验」，真正的打开交给系统
            # （os.startfile 不认 \\?\ 前缀，所以路径原样传）。
            if not path or not path_isfile(path):
                why = "文件不存在或已被清理"
                self._push_status("err", f"⚠ 无法打开文件：{why}")
                return {"ok": False, "reason": why}
            if os.name == "nt":
                os.startfile(path)                    # Windows：文件关联程序
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
            return {"ok": True}
        except Exception as e:  # noqa: BLE001  有意捕获一切异常并回落到安全默认值
            why = str(e)
            self._push_status("err", f"⚠ 打开文件失败：{why}")
            return {"ok": False, "reason": why}

    def _do_file_view(self, serial, path):
        res, err = self.file_svc.view(serial, path)
        if err:
            self._push_status("err", f"⚠ 查看失败 {path}: {err}")
            return
        self.bus.push("file_view", {
            "serial": serial, "path": path,
            "text": res.get("text"), "local": res.get("local"),
            "note": res.get("note"),
        })
