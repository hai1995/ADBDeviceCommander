"""
backend.scrcpy_service —— 调用「用户机器上已安装的」scrcpy 做设备投屏
=====================================================================
设计前提：**不内置 scrcpy、不重新打包它**。

scrcpy 是 Genymobile 的独立开源投屏工具（Windows/macOS/Linux 各自发布），
体积 ~50MB 且随平台/版本更新频繁，塞进本程序既臃肿又会过期。所以这里的
职责只有两件事：

  1. **找到它**：配置项 `scrcpy_path` → 系统 PATH → 各平台常见安装目录；
  2. **拉起它**：`scrcpy -s <serial>`，一台受控设备一个投屏窗口。

找到的路径会被回传给前端显示（用户能一眼看出用的是哪一份 scrcpy，
而不是"到底有没有调起来"全靠猜），找不到时给可执行的安装指引。

进程管理刻意做得很轻：不接管 scrcpy 的生命周期（用户直接关窗口即可），
只保留 Popen 句柄用于「同一台设备不要重复开窗」与关闭程序时的兜底清理。
"""
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

from core.constants import no_window_flags, safe_name
from core.longpath import long_path, path_isdir, path_isfile

SCRCPY_EXE_NAMES = ("scrcpy.exe", "scrcpy")

START_SETTLE_S = 0.7


def _extra_dirs():
    """PATH 之外的常见安装目录（按平台）。"""
    home = os.path.expanduser("~")
    if sys.platform.startswith("win"):
        dirs = [os.path.join(home, "scrcpy"), r"C:\scrcpy", r"C:\tools\scrcpy",
                os.path.join(home, "scoop", "apps", "scrcpy", "current"),
                os.path.join(home, "scoop", "shims")]
        for env in ("LOCALAPPDATA", "APPDATA", "ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(env)
            if not base:
                continue
            dirs += [
                os.path.join(base, "scrcpy"),
                os.path.join(base, "Programs", "scrcpy"),
                os.path.join(base, "Microsoft", "WinGet", "Packages"),
                os.path.join(base, "Programs", "scrcpy-win64"),
            ]
        return dirs
    if sys.platform == "darwin":
        return ["/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin",
                os.path.join(home, "scrcpy")]
    return ["/usr/local/bin", "/usr/bin", "/snap/bin", "/opt/scrcpy",
            os.path.join(home, "scrcpy"), os.path.join(home, ".local", "bin")]


def _as_exe(path):
    """把「目录 / exe 全路径 / 可执行名」统一解析成 scrcpy 可执行文件路径。"""
    if not path:
        return None
    p = str(path).strip().strip('"')
    if not p:
        return None
    if path_isdir(p):
        for name in SCRCPY_EXE_NAMES:
            cand = os.path.join(p, name)
            if path_isfile(cand):
                return cand
        return None
    if path_isfile(p):
        return p
    return None


def find_scrcpy(pref_path=""):
    """按「配置 → PATH → 常见目录」的顺序找 scrcpy。

    返回 (可执行文件路径 or None, 说明文字)。说明文字用于前端展示探测过程，
    找不到时它同时也是可执行的处理建议（而不是一句"未找到"了事）。
    """
    if pref_path:
        exe = _as_exe(pref_path)
        if exe:
            return exe, "来自配置的路径"
        note_prefix = "配置的路径无效（{}），已改用自动探测；".format(pref_path)
    else:
        note_prefix = ""

    for name in SCRCPY_EXE_NAMES:
        exe = shutil.which(name)
        if exe:
            return exe, note_prefix + "来自系统 PATH"

    for d in _extra_dirs():
        if not path_isdir(d):
            continue
        if d.rstrip("\\/").lower().endswith("packages"):
            try:
                pkgs = sorted(os.listdir(d), reverse=True)
            except OSError:
                continue
            for pkg in pkgs[:40]:
                pkg_dir = os.path.join(d, pkg)
                if not path_isdir(pkg_dir):
                    continue
                exe = _as_exe(pkg_dir)
                if exe:
                    return exe, note_prefix + "来自 winget 安装目录"
                try:
                    vers = sorted(os.listdir(pkg_dir), reverse=True)
                except OSError:
                    continue
                for v in vers[:10]:
                    exe = _as_exe(os.path.join(pkg_dir, v))
                    if exe:
                        return exe, note_prefix + "来自 winget 安装目录"
            continue
        exe = _as_exe(d)
        if exe:
            return exe, note_prefix + "来自常见安装目录 {}".format(d)

    return None, (note_prefix +
                  "未找到 scrcpy：可 winget install Genymobile.scrcpy / "
                  "brew install scrcpy，或下载解压后把目录填到「scrcpy 路径」")


def probe(pref_path=""):
    """探测本机 scrcpy 并取版本号（失败不抛异常）。"""
    exe, note = find_scrcpy(pref_path)
    if not exe:
        return {"ok": False, "path": "", "version": "", "note": note}
    version = ""
    try:
        r = subprocess.run([exe, "--version"], timeout=6, capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           creationflags=no_window_flags())
        out = (r.stdout or "").strip() or (r.stderr or "").strip()
        version = out.splitlines()[0].strip() if out else ""
    except Exception:
        version = ""
    return {"ok": True, "path": exe, "version": version, "note": note}


def _tail(path, limit=400):
    """读日志文件末尾（秒退时用它给出 scrcpy 自己的报错）。"""
    try:
        with open(long_path(path), "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - limit))
            text = f.read().decode("utf-8", "replace").strip()
        lines = [ln for ln in text.splitlines() if ln.strip()]
        return lines[-1].strip() if lines else ""
    except Exception:
        return ""


class ScrcpyLauncher:
    """把「勾选的设备」映射成若干个 scrcpy 窗口。

    线程安全：pywebview 的 js_api 调用可能并发进来（连点两次按钮），
    去重与登记都在锁内完成，避免同一条命令开出多个窗口。
    """

    def __init__(self):
        self._procs = {}
        self._logs = {}
        self._pending = set()
        self._lock = threading.Lock()

    def alive(self):
        """当前仍在投屏的序列号列表（顺带清理已退出的句柄与日志）。"""
        with self._lock:
            out = []
            for serial, p in list(self._procs.items()):
                if p.poll() is None:
                    out.append(serial)
                else:
                    self._procs.pop(serial, None)
                    self._drop_log(serial)
            return out

    def _drop_log(self, serial):
        """删掉该设备的 scrcpy 日志（须持锁调用）。

        秒退路径已在 _spawn 里删过；用户自己关窗口时这里补删 —— 否则 TEMP 里
        会按设备数各留一份日志，直到下次程序启动被 core.tmpfiles 扫掉才消失。
        """
        path = self._logs.pop(serial, None)
        if not path:
            return
        try:
            if os.path.exists(long_path(path)):
                os.remove(long_path(path))
        except Exception:
            pass

    def launch(self, serials, exe):
        """对每台设备拉一个 scrcpy 窗口。

        返回 {started, skipped, failed: [(serial, 原因)]}：
          started  本次真正开起来的
          skipped  已经在投屏（含**正在启动中**）、不重复开的
          failed   启动即失败（含秒退原因）
        """
        started, skipped, failed = [], [], []
        for serial in serials:
            with self._lock:
                old = self._procs.get(serial)
                if old is not None and old.poll() is None:
                    skipped.append(serial)
                    continue
                if serial in self._pending:
                    skipped.append(serial)
                    continue
                self._pending.add(serial)
                self._procs.pop(serial, None)

            try:
                ok, reason = self._spawn(serial, exe)
            finally:
                with self._lock:
                    self._pending.discard(serial)
            if ok:
                started.append(serial)
            else:
                failed.append((serial, reason))
        return {"started": started, "skipped": skipped, "failed": failed}

    def _spawn(self, serial, exe):
        log_path = os.path.join(tempfile.gettempdir(),
                                "adc_scrcpy_{}.log".format(safe_name(serial)))
        try:
            f = open(long_path(log_path), "wb")
        except Exception:
            f = None
        try:
            if f is not None:
                p = subprocess.Popen([exe, "-s", serial],
                                     stdout=f, stderr=subprocess.STDOUT,
                                     creationflags=no_window_flags())
            else:
                p = subprocess.Popen([exe, "-s", serial],
                                     creationflags=no_window_flags())
        except Exception as e:
            if f is not None:
                f.close()
                try:
                    os.remove(long_path(log_path))
                except Exception:
                    pass
            return False, "启动失败：{}".format(e)
        else:
            if f is not None:
                f.close()

        time.sleep(START_SETTLE_S)
        rc = p.poll()
        if rc is not None:
            msg = _tail(log_path)
            try:
                os.remove(long_path(log_path))
            except Exception:
                pass
            return False, ("scrcpy 立即退出（退出码 {}）{}".format(rc, ("：" + msg) if msg else ""))
        with self._lock:
            self._procs[serial] = p
            self._logs[serial] = log_path
        return True, ""

    def close_all(self):
        """关闭程序时收掉本程序开出的投屏窗口（用户自己关的不会受影响）。"""
        with self._lock:
            procs = list(self._procs.values())
            logs = list(self._logs.values())
            self._procs.clear()
            self._logs.clear()
        for p in procs:
            try:
                if p.poll() is None:
                    p.terminate()
            except Exception:
                pass
        for path in logs:
            try:
                if os.path.exists(long_path(path)):
                    os.remove(long_path(path))
            except Exception:
                pass