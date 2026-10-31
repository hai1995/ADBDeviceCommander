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


def _err_text(r, fallback="adb 返回失败（没有给出原因）"):
    """从 CompletedProcess 里取一句**非空**的失败原因。

    `adb shell <cmd>` 的报错几乎都走 **stdout**（远端命令的输出本来就在
    stdout），例如 `mkdir: '/system/x': Read-only file system`；push / pull 的
    部分错误同样落在 stdout。只读 stderr 会拿到空串，界面于是显示
    「⚠ 创建目录失败 /system/x: 」—— 原因那一栏一片空白，用户只能凭猜。
    两路都收，都没有才用兜底文案（至少说明「adb 没给出原因」）。
    成功（returncode == 0）时恒返回空串：调用方约定「err 为空 = 成功」，
    而 push / pull 的正常进度恰恰写在 stdout 上。
    """
    if getattr(r, "returncode", 0) == 0:
        return ""
    text = ((getattr(r, "stderr", "") or "") + "\n"
            + (getattr(r, "stdout", "") or "")).strip()
    return text[:200] or fallback


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
            return None, _err_text(r, "ls 失败")
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
        return r.returncode == 0, _err_text(r)

    def touch(self, serial, path):
        r = self._shell(serial, ["touch", shq(path)], timeout=20)
        return r.returncode == 0, _err_text(r)

    def remove(self, serial, paths):
        r = self._shell(serial, ["rm", "-rf"] + [shq(p) for p in paths],
                        timeout=60)
        return r.returncode == 0, _err_text(r)

    def rename(self, serial, old, new):
        r = self._shell(serial, ["mv", shq(old), shq(new)], timeout=20)
        return r.returncode == 0, _err_text(r)

    def upload(self, serial, local, remote):
        r = subprocess.run(
            [self.adb, "-s", serial, "push", local, remote],
            **adb_kwargs(120))
        return r.returncode == 0, _err_text(r)

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
            return None, _err_text(r, "pull 失败（adb 没有给出原因）")
        base = os.path.basename(remote.rstrip("/")) or safe_name(remote)
        # 落盘名是 **adb 自己**按设备端原名生成的，不是我们净化后的名字：
        # `adb pull` 只认远端文件名，我们无法告诉它「落地时换个名」。所以先按
        # 原名找、找得到再尽力改成净化名（设备端文件名可能含 Windows 非法字符，
        # 如冒号 —— Android 允许、Windows 不允许）。
        # 早前只查净化名：真机上一次「已经下载成功」会被判成失败，且错误文本是
        # None，界面显示成「下载失败 <路径>: None」，用户以为文件丢了。
        raw_local = os.path.join(local_dir, base)
        safe_local = os.path.join(local_dir, safe_name(base))
        if os.path.exists(safe_local):
            return safe_local, None
        if os.path.exists(raw_local):
            if raw_local != safe_local:
                try:
                    os.replace(raw_local, safe_local)
                    return safe_local, None
                except OSError:
                    pass          # 改不了名（占用 / 权限）就把真实路径回给用户
            return raw_local, None
        # pull 返回 0 却找不到文件：目录被外部清掉 / adb 把内容放进了子目录
        return None, "adb 报告成功但本地没有落文件（目标目录：%s）" % local_dir

    def view(self, serial, path, max_inline_bytes=1024 * 1024):
        """小文件直接 cat 内容返回；大文件 pull 到临时目录返回本地路径标记。

        cat 成功但输出**超过 max_inline_bytes** 时同样走 pull 路径：超长文本
        （上百 MB 的日志 / 二进制）经事件总线 + pywebview IPC 直传前端会把界面
        卡死。pull 落地的临时文件名带随机串，避免并行查看不同目录下的同名
        文件时互相覆盖（后拉完的顶掉先拉完的， modal 显示错内容）。
        """
        limit = max_inline_bytes
        # 只取「上限 + 1」字节：早前直接 cat 整个文件，用户点开几百 MB 的日志时
        # 这几百 MB 会先整个进内存（Python str 还要再涨 2~4 倍），随后才被判为
        # 「太大」丢掉 —— 峰值内存与耗时全白付，极端情况下直接 MemoryError
        # 把整个程序带走。head -c 在设备端就裁掉，取回量恒定。
        # 老 ROM（Android 6 之前的 toolbox）head 不认 -c，会返回非零：此时退回
        # 整段 cat，用输出长度判上限 —— 也就是旧版行为，功能不受影响。
        try:
            r = self._shell(serial, ["head", "-c", str(limit + 1), shq(path)],
                            timeout=20)
            if r.returncode != 0:
                r = self._shell(serial, ["cat", shq(path)], timeout=20)
        except Exception as e:
            return None, str(e)
        out = r.stdout or ""
        # 按**字节**算而不是字符数：head 是按字节裁的，中文一个字符占 3 字节，
        # 用 len(str) 比会把「已被截断」误判成「没超限」，于是把半截文件当完整的给用户。
        if r.returncode == 0 and len(out.encode("utf-8", "replace")) <= limit:
            return {"text": out, "local": None}, None
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
        return None, _err_text(r, "查看失败")
