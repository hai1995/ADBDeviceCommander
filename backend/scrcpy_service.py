# -*- coding: utf-8 -*-
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

# 可执行文件名（Windows 带 .exe，其它平台不带）
SCRCPY_EXE_NAMES = ("scrcpy.exe", "scrcpy")

# 启动后观察窗口：scrcpy 在「设备未授权 / 版本不兼容 / adb 报错」时会**秒退**，
# 此时窗口一闪而过、用户只看到"点了没反应"。等这么久再确认它是否还活着，
# 才有机会把 stderr 里的原因回显到状态栏。
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
            # winget（Genymobile.scrcpy）与手动解压两派布局都覆盖
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
    # 目录 → 在里面找可执行文件
    if os.path.isdir(p):
        for name in SCRCPY_EXE_NAMES:
            cand = os.path.join(p, name)
            if os.path.isfile(cand):
                return cand
        return None
    if os.path.isfile(p):
        return p
    return None


def find_scrcpy(pref_path=""):
    """按「配置 → PATH → 常见目录」的顺序找 scrcpy。

    返回 (可执行文件路径 or None, 说明文字)。说明文字用于前端展示探测过程，
    找不到时它同时也是可执行的处理建议（而不是一句"未找到"了事）。
    """
    # 1) 用户显式配置（目录或全路径都认）
    if pref_path:
        exe = _as_exe(pref_path)
        if exe:
            return exe, "来自配置的路径"
        # 配置了但无效：继续往下探测，但把这件事说清楚（否则用户会以为配置生效了）
        note_prefix = "配置的路径无效（%s），已改用自动探测；" % pref_path
    else:
        note_prefix = ""

    # 2) 系统 PATH
    for name in SCRCPY_EXE_NAMES:
        exe = shutil.which(name)
        if exe:
            return exe, note_prefix + "来自系统 PATH"

    # 3) 常见安装目录
    for d in _extra_dirs():
        if not os.path.isdir(d):
            continue
        if d.rstrip("\\/").lower().endswith("packages"):
            # winget 布局是 Packages/<包名>/<版本>/scrcpy.exe，往下扫两层
            try:
                pkgs = sorted(os.listdir(d), reverse=True)
            except OSError:
                continue
            for pkg in pkgs[:40]:
                pkg_dir = os.path.join(d, pkg)
                if not os.path.isdir(pkg_dir):
                    continue
                exe = _as_exe(pkg_dir)          # 有的包直接铺在包目录下
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
            return exe, note_prefix + "来自常见安装目录 %s" % d

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
        version = ""      # 取不到版本不影响可用性（老版本 scrcpy 也支持 -s）
    return {"ok": True, "path": exe, "version": version, "note": note}


def _tail(path, limit=400):
    """读日志文件末尾（秒退时用它给出 scrcpy 自己的报错）。"""
    try:
        with open(path, "rb") as f:
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
        self._procs = {}            # serial -> Popen
        self._logs = {}             # serial -> 日志临时文件路径
        self._lock = threading.Lock()

    # ---- 查询 ----
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
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    # ---- 启动 ----
    def launch(self, serials, exe):
        """对每台设备拉一个 scrcpy 窗口。

        返回 {started, skipped, failed: [(serial, 原因)]}：
          started  本次真正开起来的
          skipped  已经在投屏、不重复开的
          failed   启动即失败（含秒退原因）
        """
        started, skipped, failed = [], [], []
        for serial in serials:
            with self._lock:
                old = self._procs.get(serial)
                if old is not None and old.poll() is None:
                    skipped.append(serial)
                    continue
                self._procs.pop(serial, None)

            ok, reason = self._spawn(serial, exe)
            if ok:
                started.append(serial)
            else:
                failed.append((serial, reason))
        return {"started": started, "skipped": skipped, "failed": failed}

    def _spawn(self, serial, exe):
        log_path = os.path.join(tempfile.gettempdir(),
                                "adc_scrcpy_%s.log" % safe_name(serial))
        try:
            f = open(log_path, "wb")
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
                # 刚建的日志文件是空的，Popen 都没起来就没人会用：顺手删掉，
                # 免得每失败一次就在 TEMP 里留一个 0 字节文件。
                try:
                    os.remove(log_path)
                except Exception:
                    pass
            return False, "启动失败：%s" % e
        else:
            if f is not None:
                f.close()      # 子进程持有自己的句柄，父进程关掉不影响它写

        # 观察 START_SETTLE_S：秒退说明 scrcpy 自己报错（未授权 / 版本不兼容 / adb 不可用）
        time.sleep(START_SETTLE_S)
        rc = p.poll()
        if rc is not None:
            msg = _tail(log_path)
            try:
                os.remove(log_path)
            except Exception:
                pass
            return False, ("scrcpy 立即退出（退出码 %s）%s"
                           % (rc, ("：" + msg) if msg else ""))
        with self._lock:
            self._procs[serial] = p
            self._logs[serial] = log_path
        return True, ""

    # ---- 收尾 ----
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
        # 日志文件可能还被刚刚 terminate 的进程短暂占用，留给系统临时目录清理
        for path in logs:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass
