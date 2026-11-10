# -*- coding: utf-8 -*-
"""backend.controllers.logcat —— logcat 监控与抓取"""

from backend.controller import (
    adb_kwargs, load_prefs, os, resolve_save_dir, safe_name,
    subprocess, time, unique_path
)
from backend.logcat_service import pkg_pids_of

class LogcatMixin:
    """logcat 实时监控与抓取。"""

    def logcat_start(self, serial, buffers, level_filter=None,
                     keyword="", only_exc=False):
        """对单台设备启动实时 logcat 监控。buffers 为缓冲区名列表。"""
        if not serial:
            return {"ok": False, "reason": "no_device"}
        ok = self.logcat_monitor.start(
            serial, buffers, level_filter=level_filter,
            keyword=keyword or "", only_exc=bool(only_exc))
        if not ok:
            # 前端是事件驱动、不看返回值的（callApi 结果只作兜底）：这里不播报，
            # 用户点「开始监控」看到的就是彻底的静默 —— 分不清是设备在忙、
            # 还是按钮没点上。
            self._push_status(
                "warn", "⚠ 设备 %s 已在 logcat 监控中，不用重复开始" % serial)
            return {"ok": False, "reason": "already_running"}
        self._push_status("info", "开始监控 logcat: %s" % serial)
        return {"ok": True}

    def logcat_stop(self, serial):
        if not serial:
            return {"ok": False, "reason": "no_device"}
        self.logcat_monitor.stop(serial)
        return {"ok": True}

    def logcat_clear(self, serial):
        self.bus.push("logcat", {"serial": serial, "status": "clear"})
        return {"ok": True}

    def logcat_packages(self, serial, third_party_only=True):
        """列出设备上可过滤的包名，供前端「按包过滤」下拉选用。

        默认只列第三方包（`pm list packages -3`）：车机调试时用户的关注点几乎
        总是自己装的应用，把几百个系统包一起列出来反而淹没目标。找不到第三方
        包（或老系统不认 -3）时回退全量列表，宁可多列也不给一个空下拉。
        """
        if not serial:
            return {"ok": False, "reason": "no_device", "packages": []}
        adb = self.state.adb_path

        def _list(extra):
            try:
                r = subprocess.run(
                    [adb, "-s", serial, "shell", "pm", "list", "packages"] + extra,
                    **adb_kwargs(12))
            except Exception:
                return []
            if r.returncode != 0:
                return []
            out = []
            for line in (r.stdout or "").splitlines():
                line = line.strip()
                if line.startswith("package:"):
                    name = line[len("package:"):].strip()
                    if name:
                        out.append(name)
            return sorted(set(out))

        pkgs = _list(["-3"]) if third_party_only else []
        if not pkgs:
            pkgs = _list([])
        return {"ok": True, "packages": pkgs}

    def logcat_pidof(self, serial, package):
        """把包名解析成当前 pid 列表（前端 pkg: 过滤的即时解析）。

        与监控 worker 内部用的是同一个函数（backend.logcat_service.pkg_pids_of），
        保证「下拉选中包时算出来的 pid」和「后端过滤时用的 pid」不会两套口径。
        """
        if not serial or not package:
            return {"ok": False, "pids": []}
        pids = pkg_pids_of(self.state.adb_path, serial, package)
        return {"ok": True, "pids": sorted(pids, key=lambda x: (len(x), x))}

    def logcat_capture_start(self, serial, save_dir, buffers, level_filter=None):
        if not serial:
            return {"ok": False, "reason": "no_device"}
        # 与截图/录屏/录音保持一致：未指定目录时回退到默认保存目录，
        # 避免 save_dir 为 None 时 os.makedirs(None) 抛 TypeError 直接失败。
        save_dir = save_dir or self._default_save_dir()
        try:
            os.makedirs(save_dir, exist_ok=True)
        except Exception as e:
            # 同上：返回前端也不看。保存目录不可写（只读盘 / 盘符不存在 /
            # 路径被同名文件占位）时，用户点「开始抓取」后什么都不发生。
            self._push_status(
                "err", "⚠ 无法创建保存目录 %s：%s" % (save_dir, e))
            return {"ok": False, "reason": "mkdir", "text": str(e)}
        ts = time.strftime("%Y%m%d_%H%M%S")
        # safe_name：无线 ADB 序列号（IP:端口）含冒号，Windows 下文件名非法
        path = unique_path(
            os.path.join(save_dir, "logcat_%s_%s.txt" % (safe_name(serial), ts)),
            suffixes=(".zip",))
        ok = self.logcat_capture.start(serial, path, buffers,
                                       level_filter=level_filter)
        if not ok:
            self._push_status(
                "warn", "⚠ 设备 %s 已有 logcat 抓取在进行，请先停止再开始"
                        % serial)
            return {"ok": False, "reason": "already_running"}
        self._push_status("info", "开始抓取 logcat: %s -> %s%s"
                          % (serial, path, self._level_filter_desc(level_filter)))
        return {"ok": True, "path": path}

    @staticmethod
    def _level_filter_desc(level_filter):
        """级别过滤的人类可读后缀（全级别 / 未过滤时返回空串，不刷屏）。"""
        if level_filter is None:
            return ""
        picked = [x for x in ("V", "D", "I", "W", "E", "F")
                  if x in set(level_filter)]
        if len(picked) == 6:
            return ""
        if not picked:
            return "（级别: 无 — 不会写入任何日志行）"
        return "（级别: %s）" % "/".join(picked)

    def logcat_capture_stop(self, serial, zip_on_stop=True):
        if not serial:
            return {"ok": False, "reason": "no_device"}
        if not self.logcat_capture.stop(serial, zip_on_stop=zip_on_stop):
            # 没在抓取（设备刚被移除 / 上一轮已经停了）：说一句，而不是让用户
            # 对着一个"点了没反应"的按钮反复点。
            self._push_status(
                "info", "ℹ 设备 %s 当前没有进行中的 logcat 抓取" % serial)
            return {"ok": False, "reason": "not_running"}
        return {"ok": True}

    def _default_save_dir(self):
        """本机实际生效的保存目录。

        优先用 config.json 的 save_dir（用户偏好，跨会话记住）；但该路径是
        绝对路径，配置被拷到另一台电脑后通常在本机并不存在——此时改用默认
        目录（见 core.prefs.resolve_save_dir），绝不让程序往一个不存在的
        路径里写文件。**不回写配置文件**：文件里的原值在源机器上仍然正确。
        """
        # 不建目录：这里读的是「配置里带来的路径」，若它在本机不存在，
        # 多半是从别的电脑同步过来的失效路径（父目录都不在了），
        # 建不出来也不该建 —— 交由 resolve_save_dir 回退默认目录。
        eff, _note = resolve_save_dir(load_prefs())
        return eff

    def default_save_dir(self):
        """把默认保存目录透出给前端（截图/录屏/下载共用同一份定义）。

        浏览器里没有环境变量，前端无法自行推导用户目录，也不该复制一份公式
        （两份必然漂移）。故由后端作为单一数据源提供，前端仅负责回填输入框。
        """
        return {"ok": True, "dir": self._default_save_dir()}
