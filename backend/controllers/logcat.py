# -*- coding: utf-8 -*-
"""backend.controllers.logcat —— logcat 监控与抓取"""

from backend.controller import (
    load_prefs, os, resolve_save_dir, safe_name,
    time
)

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

    def logcat_capture_start(self, serial, save_dir, buffers, level_filter=None):
        if not serial:
            return {"ok": False, "reason": "no_device"}
        # 与截图/录屏/录音保持一致：未指定目录时回退到默认保存目录，
        # 避免 save_dir 为 None 时 os.makedirs(None) 抛 TypeError 直接失败。
        save_dir = save_dir or self._default_save_dir()
        try:
            os.makedirs(save_dir, exist_ok=True)
        except Exception as e:
            return {"ok": False, "reason": "mkdir", "text": str(e)}
        ts = time.strftime("%Y%m%d_%H%M%S")
        # safe_name：无线 ADB 序列号（IP:端口）含冒号，Windows 下文件名非法
        path = os.path.join(
            save_dir, "logcat_%s_%s.txt" % (safe_name(serial), ts))
        ok = self.logcat_capture.start(serial, path, buffers,
                                       level_filter=level_filter)
        if not ok:
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
        self.logcat_capture.stop(serial, zip_on_stop=zip_on_stop)
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
