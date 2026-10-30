# -*- coding: utf-8 -*-
"""
backend.file_service —— 设备文件系统管理（基于 adb shell + pull/push）。

  * list_dir(serial, path)    执行 `ls -la`（兼容 GNU/Toybox），解析为条目
  * make_dir / touch / remove / rename / view / upload / download

调用方负责把结果经 bus 推送为 file 事件。本模块只做命令执行与解析。
"""
import os
import subprocess
import tempfile
import uuid

from core.constants import adb_kwargs, parse_ls_output, posix_join, safe_name
from core import tmpfiles


def shq(text) -> str:
    """把设备端路径安全包装成「单个」POSIX shell 参数。

    `adb shell` 会把剩余 argv 用空格拼成一条远端命令再交给设备端 sh 解析——
    路径若含空格 / 引号 / shell 元字符而不加包裹，就会被拆成多个参数
    （rm -rf / mv 时甚至可能误删相邻文件）。单引号包裹后远端 sh 视为一个
    整体参数；路径内含单引号时用 `'\\''` 转义（POSIX 标准做法）。
    """
    return "'" + str(text).replace("'", "'\\''") + "'"


class FileService:
    def __init__(self, adb="adb"):
        self.adb = adb

    def _shell(self, serial, args, timeout=30):
        # adb 输出固定 UTF-8（中文文件名/内容），必须显式指定 encoding：
        # 中文 Windows 的默认编码是 cp936，不指定就会把 UTF-8 字节解成乱码。
        return subprocess.run(
            [self.adb, "-s", serial, "shell"] + args, **adb_kwargs(timeout))

    def list_dir(self, serial, path):
        """列出目录条目（已排序：目录在前，文件在后；隐藏项保留末尾）。
        返回 (entries, err)。entries 中每项含 name/perm/size/date/is_dir/is_link/target。
        """
        path = path or "/"
        # 不加 --time-style=long-iso 等 GNU 扩展，兼容 Android Toybox / BusyBox / BSD
        r = self._shell(serial, ["ls", "-la", shq(posix_join(path, "."))], timeout=20)
        if r.returncode != 0:
            return None, (r.stderr or r.stdout or "ls 失败").strip()[:200]
        items = parse_ls_output(r.stdout or "")
        # 极少数设备 ls -la 输出被截断或异常导致解析为空：兜底 ls -l 再试一次
        if not items:
            r2 = self._shell(serial, ["ls", "-l", shq(posix_join(path, "."))], timeout=20)
            if r2.returncode == 0:
                items = parse_ls_output(r2.stdout or "")
        # 排掉 . 和 ..
        items = [i for i in items if i["name"] not in (".", "..")]
        items.sort(key=lambda i: (not i["is_dir"], i["name"].lower()))
        return items, None

    def make_dir(self, serial, path):
        r = self._shell(serial, ["mkdir", "-p", shq(path)], timeout=20)
        return r.returncode == 0, (r.stderr or "").strip()[:200]

    def touch(self, serial, path):
        r = self._shell(serial, ["touch", shq(path)], timeout=20)
        return r.returncode == 0, (r.stderr or "").strip()[:200]

    def remove(self, serial, paths):
        r = self._shell(serial, ["rm", "-rf"] + [shq(p) for p in paths],
                        timeout=60)
        return r.returncode == 0, (r.stderr or "").strip()[:200]

    def rename(self, serial, old, new):
        r = self._shell(serial, ["mv", shq(old), shq(new)], timeout=20)
        return r.returncode == 0, (r.stderr or "").strip()[:200]

    def upload(self, serial, local, remote):
        r = subprocess.run(
            [self.adb, "-s", serial, "push", local, remote],
            **adb_kwargs(120))
        return r.returncode == 0, (r.stderr or "").strip()[:200]

    def download(self, serial, remote, local_dir):
        # 目录建不出来（无权限 / 非法盘符）要回一句人话，否则 worker 线程里
        # 静默抛异常，前端只会看到「没有任何反应」。
        try:
            os.makedirs(local_dir, exist_ok=True)
        except Exception as e:
            return None, "无法创建保存目录 %s：%s" % (local_dir, e)
        r = subprocess.run(
            [self.adb, "-s", serial, "pull", remote, local_dir],
            **adb_kwargs(120))
        if r.returncode != 0:
            return None, (r.stderr or "").strip()[:200]
        base = os.path.basename(remote.rstrip("/"))
        # 设备端文件名可能含 Windows 非法字符（如冒号；Android 允许但 Windows
        # 不允许），直接拼路径会让 pull 落盘失败——净化后再拼。
        local = os.path.join(local_dir, safe_name(base))
        return (local if os.path.exists(local) else None), None

    def view(self, serial, path, max_inline_bytes=1024 * 1024):
        """小文件直接 cat 内容返回；大文件 pull 到临时目录返回本地路径标记。

        cat 成功但输出**超过 max_inline_bytes** 时同样走 pull 路径：超长文本
        （上百 MB 的日志 / 二进制）经事件总线 + pywebview IPC 直传前端会把界面
        卡死。pull 落地的临时文件名带随机串，避免并行查看不同目录下的同名
        文件时互相覆盖（后拉完的顶掉先拉完的， modal 显示错内容）。
        """
        try:
            r = self._shell(serial, ["cat", shq(path)], timeout=20)
        except Exception as e:
            return None, str(e)
        if r.returncode == 0 and len(r.stdout or "") <= max_inline_bytes:
            return {"text": r.stdout, "local": None}, None
        # 失败（可能大文件/二进制）或输出超限：尝试 pull
        try:
            # 先清理上一轮遗留的临时副本：这类文件每次「查看」都会新增一份，
            # 没人删就会在 %TEMP% 里一直堆积（几百 MB 的日志看几次就吃掉几个 GB）。
            # 保留最新 8 个 + 10 分钟宽限，保证正在看的这一份不会被删掉。
            tmpfiles.sweep_view_files(keep_newest=8, min_age_s=600.0)
            tmp = os.path.join(
                tempfile.gettempdir(),
                "adb_view_%s_%s" % (uuid.uuid4().hex[:8],
                                    safe_name(os.path.basename(path))))
            pr = subprocess.run(
                [self.adb, "-s", serial, "pull", path, tmp], **adb_kwargs(120))
            # 用 isfile 而非 exists：对目录执行查看时 cat 会失败、pull 会把整个
            # 目录拉下来，exists 命中后 getsize 直接抛 IsADirectoryError，用户看到
            # 一句 "[Errno 21] Is a directory" 的 Python 内部错误；isfile 不命中时
            # 落到下面的 cat stderr（"Is a directory"），是人能看懂的原因。
            if pr.returncode == 0 and os.path.isfile(tmp):
                sz = os.path.getsize(tmp)
                if sz <= max_inline_bytes:
                    with open(tmp, "r", encoding="utf-8",
                              errors="replace") as f:
                        txt = f.read()
                    try:
                        os.remove(tmp)
                    except Exception:
                        pass
                    return {"text": txt, "local": None}, None
                return {"text": None, "local": tmp,
                        "note": "文件较大(%d 字节)，已拉取到本地临时文件" % sz}, None
        except Exception as e:
            return None, str(e)
        return None, (r.stderr or "查看失败").strip()[:200]
