# -*- coding: utf-8 -*-
"""backend.controllers.file —— 文件浏览 / 增删改 / 上传下载"""

from backend.controller import (
    os, safe_name, subprocess, sys
)

class FileMixin:
    """设备文件浏览/增删改/上传下载/预览。"""

    _FILE_OP_LABELS = {
            "_do_file_list": "列出目录", "_do_file_mkdir": "创建目录",
            "_do_file_touch": "创建文件", "_do_file_remove": "删除",
            "_do_file_rename": "重命名", "_do_file_upload_data": "上传",
            "_do_file_download": "下载", "_do_file_view": "查看",
        }

    def open_save_dir(self, dir_path=None):
        """在系统文件管理器打开保存目录（Windows 用 explorer / startfile）。"""
        d = (dir_path or "").strip() or self._default_save_dir()
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass
        if not os.path.isdir(d):
            self._push_status("err", "⚠ 目录不存在：%s" % d)
            return {"ok": False}
        try:
            if sys.platform.startswith("win"):
                os.startfile(d)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", d])
            else:
                subprocess.Popen(["xdg-open", d])
            self._push_status("info", "📂 已打开目录：%s" % d)
            return {"ok": True}
        except Exception as e:
            self._push_status("err", "⚠ 无法打开目录 %s: %s" % (d, e))
            return {"ok": False, "text": str(e)}

    @staticmethod
    def _parent_dir(path):
        p = (path or "/").rstrip("/")
        if "/" not in p:
            return "/"
        return p.rsplit("/", 1)[0] or "/"

    def file_list(self, serial, path):
        if not serial:
            return {"ok": False, "reason": "no_device"}
        # 每次列目录用**唯一** worker key + 记录「该设备最新一次请求」：
        #  · 唯一 key：旧实现固定用 "file_<serial>"，上一次 `ls -la` 还没结束时
        #    （大目录 / 慢设备）用户再点进另一个目录，Workers 会按同名去重直接
        #    丢弃新请求且不报错 —— 界面停在旧目录，看起来「点了没反应」；
        #  · 最新序号：新请求发起后，先前那次迟到的响应会被丢弃，避免旧目录的
        #    内容覆盖刚打开的目录。
        seq = next(self._file_seq)
        self._file_req[serial] = seq
        self.workers.spawn("filelist_%s_%d" % (serial, seq),
                           self._run_file_op, self._do_file_list,
                           serial, path, seq)
        return {"ok": True}

    def _do_file_list(self, serial, path, seq=None):
        entries, err = self.file_svc.list_dir(serial, path)
        if seq is not None and self._file_req.get(serial) != seq:
            return          # 已有更新的一次列目录请求，丢弃这次迟到的结果
        if err:
            self._push_status("err", "⚠ 列出目录失败 %s: %s" % (path, err))
            self.bus.push("file", {"serial": serial, "path": path,
                                   "error": err})
        else:
            self.bus.push("file", {"serial": serial, "path": path,
                                   "entries": entries})

    def _file_refresh(self, serial, path):
        self.file_list(serial, self._parent_dir(path))

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
        k = key or ("fileop_%s" % serial)
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
        except Exception as ex:
            label = self._FILE_OP_LABELS.get(
                getattr(do_fn, "__name__", ""), "文件操作")
            self._push_status("err", "⚠ %s失败 %s：%s" % (label, serial, ex))

    def file_mkdir(self, serial, path):
        return self._file_op(serial, self._do_file_mkdir, path)

    def _do_file_mkdir(self, serial, path):
        ok, err = self.file_svc.make_dir(serial, path)
        if ok:
            self._push_status("ok", "✓ 已创建目录: %s" % path)
        else:
            self._push_status("err", "⚠ 创建目录失败 %s: %s" % (path, err))
        self._file_refresh(serial, path)

    def file_touch(self, serial, path):
        return self._file_op(serial, self._do_file_touch, path)

    def _do_file_touch(self, serial, path):
        ok, err = self.file_svc.touch(serial, path)
        if ok:
            self._push_status("ok", "✓ 已创建文件: %s" % path)
        else:
            self._push_status("err", "⚠ 创建文件失败 %s: %s" % (path, err))
        self._file_refresh(serial, path)

    def file_remove(self, serial, paths):
        paths = paths if isinstance(paths, list) else [paths]
        if not paths:
            return {"ok": False, "reason": "empty"}
        return self._file_op(serial, self._do_file_remove, list(paths))

    def _do_file_remove(self, serial, paths):
        ok, err = self.file_svc.remove(serial, paths)
        if ok:
            self._push_status("ok", "✓ 已删除 %d 个项" % len(paths))
        else:
            self._push_status("err", "⚠ 删除失败: %s" % err)
        if paths:
            self._file_refresh(serial, paths[0])

    def file_rename(self, serial, old, new):
        return self._file_op(serial, self._do_file_rename, old, new)

    def _do_file_rename(self, serial, old, new):
        ok, err = self.file_svc.rename(serial, old, new)
        if ok:
            self._push_status("ok", "✓ 重命名: %s -> %s" % (old, new))
        else:
            self._push_status("err", "⚠ 重命名失败: %s" % err)
        self._file_refresh(serial, old)

    def file_upload_data(self, serial, name, b64, remote):
        """前端以 base64 传文件内容（浏览器不暴露本地路径），后端落地后 push。

        与下载同理：每个文件一个独立 worker key，否则「一次选多个文件上传」会
        被 "fileop_<serial>" 去重吞掉 —— 只有第一个真正传到设备。
        """
        return self._file_op(serial, self._do_file_upload_data, name, b64, remote,
                             key="fileup_%s_%d" % (serial, next(self._file_seq)))

    def _do_file_upload_data(self, serial, name, b64, remote):
        import base64
        import tempfile
        import uuid
        # 临时文件名带随机串：多设备/多文件并行上传同名文件时，固定名会互相覆盖，
        # 导致其中一个线程上传的是别人的内容（或中途被删而上传失败）。
        # 前端传来的 name 一律先取 basename 并净化：它若含路径分隔符，会把临时文件
        # 写到 %TEMP% 之外（甚至覆盖任意可写文件）。
        tmp = os.path.join(
            tempfile.gettempdir(),
            "adb_up_%s_%s" % (uuid.uuid4().hex[:8],
                              safe_name(os.path.basename(name or ""))))
        try:
            with open(tmp, "wb") as f:
                f.write(base64.b64decode(b64 or ""))
        except Exception as e:
            self._push_status("err", "⚠ 解码上传文件失败：%s" % e)
            return
        # try/finally：upload 抛异常（大文件 push 超过 120s 超时、adb 中途消失）时
        # 旧实现会跳过 os.remove，每次失败都在 %TEMP% 留下一个多 MB 的孤儿文件。
        try:
            ok, err = self.file_svc.upload(serial, tmp, remote)
        finally:
            try:
                os.remove(tmp)
            except Exception:
                pass
        if ok:
            self._push_status("ok", "✓ 上传完成: %s" % remote)
        else:
            self._push_status("err", "⚠ 上传失败 %s: %s" % (remote, err))
        self._file_refresh(serial, remote)

    def file_download(self, serial, remote, local_dir):
        # 每个文件一个独立 worker key（含序列号），保证同一设备批量「下载选中」
        # 时所有文件各自成线程并行 pull，不会被 "fileop_<serial>" 去重吞掉。
        return self._file_op(
            serial, self._do_file_download, remote,
            local_dir or self._default_save_dir(),
            key="filedl_%s_%d" % (serial, next(self._file_seq)))

    def _do_file_download(self, serial, remote, local_dir):
        path, err = self.file_svc.download(serial, remote, local_dir)
        if path:
            self._push_status("ok", "✓ 已下载: %s" % path)
        else:
            self._push_status("err", "⚠ 下载失败 %s: %s" % (remote, err))

    def file_view(self, serial, path):
        # 查看同样用唯一 key：连续点开两个文件的「查看」时，固定 key 会让第二个
        # 请求被去重静默丢弃（用户看到的是上一个文件的内容 / 什么都没发生）。
        return self._file_op(serial, self._do_file_view, path,
                             key="fileview_%s_%d" % (serial,
                                                     next(self._file_seq)))

    def open_local_file(self, path):
        """用系统默认程序打开本地文件（大文件查看弹窗的「查看」按钮）。

        路径来自本程序 pull 落地的临时文件；仍做存在性校验，
        避免把明显非法的输入透传给系统打开机制。
        """
        try:
            if not path or not os.path.isfile(path):
                return {"ok": False, "reason": "文件不存在或已被清理"}
            if os.name == "nt":
                os.startfile(path)                    # Windows：文件关联程序
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "reason": str(e)}

    def _do_file_view(self, serial, path):
        res, err = self.file_svc.view(serial, path)
        if err:
            self._push_status("err", "⚠ 查看失败 %s: %s" % (path, err))
            return
        self.bus.push("file_view", {
            "serial": serial, "path": path,
            "text": res.get("text"), "local": res.get("local"),
            "note": res.get("note"),
        })
