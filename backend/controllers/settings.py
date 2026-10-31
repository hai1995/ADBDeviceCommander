# -*- coding: utf-8 -*-
"""backend.controllers.settings —— 设置 / adb 状态 / Wi-Fi 无线调试"""

from backend.controller import (
    adb_kwargs, apply_adb_dir, load_prefs, os,
    prefs_path, resolve_save_dir, save_prefs, save_prefs_checked, subprocess,
    wifi
)

class SettingsMixin:
    """设置、adb 状态、Wi-Fi 无线调试。"""

    def save_settings(self, patch):
        """合并保存用户偏好；adb_dir 变更即时生效（前插到进程 PATH）。

        由前端在各偏好控件的 change / 保存时调用；返回合并后的完整设置。
        保存目录改这里后，default_save_dir / 各录制下载默认目录立即生效。
        """
        if not isinstance(patch, dict) or not patch:
            return {"ok": False, "reason": "empty_patch"}
        merged, wrote = save_prefs_checked(patch)
        if "adb_dir" in patch:
            apply_adb_dir(merged.get("adb_dir"))
            # 配置变更后立即回测一次，供前端即时更新关于页 / 引导文案
            merged["_adb_ok"] = self._probe_adb()["ok"]
        # 保存目录改动后立刻回报「本机实际生效的目录」：用户填了一个本机
        # 不存在的路径时，界面要马上说清已改用默认目录，而不是等下一次
        # 截图失败才发现（配置文件里的原值保持不动）。
        if "save_dir" in patch:
            # ensure_dir=True：用户在本机新填的路径本就不存在，这是正常
            # 流程 —— 顺手建出来（与旧行为一致：回退目录会被自动创建）。
            eff, note = resolve_save_dir(merged, ensure_dir=True)
            merged["_save_dir_effective"] = eff
            merged["_save_dir_note"] = note
        if not wrote:
            # 内存里已经生效（本次运行可用），但文件没写进去——重启就没了。
            # 早前这里无条件回 ok=True，用户改完主题 / 保存目录 / 投屏参数，
            # 界面一切正常，第二天打开又是旧设置，且没有任何线索可查。
            # 典型场景：程序放在 Program Files，或 config.json 被标成只读。
            note = ("设置未能写入 %s（目录只读 / 文件被占用 / 磁盘已满？），"
                    "本次改动只在当前运行生效，重启后会恢复原值。"
                    "可把程序放到可写目录，或去掉 config.json 的只读属性后重试。"
                    % prefs_path())
            merged["_persist_ok"] = False
            merged["_persist_note"] = note
            self._push_toast("err", "⚠ " + note)
        return {"ok": True, "settings": merged}

    def config_info(self):
        """配置文件信息（关于页展示用）。

        返回 {path, exists, save_dir, save_dir_effective, note}：
          * path —— config.json 的绝对路径，用户拷走它即可在别的电脑同步；
          * exists —— 文件是否已存在（首次运行时尚未生成）；
          * save_dir —— 配置文件里记录的原值（可能是别的电脑的路径）；
          * save_dir_effective —— 本机实际生效的目录（原值不可用时的回退结果）；
          * note —— 回退提示文案（一切正常时为 None）。
        """
        settings = load_prefs()
        eff, note = resolve_save_dir(settings)
        p = prefs_path()
        return {
            "ok": True,
            "path": p,
            "exists": os.path.exists(p),
            "save_dir": settings.get("save_dir", ""),
            "save_dir_effective": eff,
            "note": note,
        }

    def adb_status(self):
        """adb 可用性（路径 / 版本），about 页配置后即时刷新用。"""
        info = self._probe_adb()
        return {"ok": info["ok"], "path": info["path"],
                "version": info["version"]}

    def _probe_adb(self):
        """探测当前 adb 是否可用，返回 {ok, path, version}。"""
        path = getattr(self.state, "adb_path", "") or "adb"
        try:
            r = subprocess.run([path, "version"], **adb_kwargs(8))
            if r.returncode == 0:
                lines = [ln.strip() for ln in (r.stdout or "").splitlines()
                         if ln.strip()]
                ver = next(
                    (ln for ln in lines if ln.lower().startswith("version")),
                    lines[0] if lines else "adb version")
                return {"ok": True, "path": path, "version": ver}
        except Exception:
            pass
        return {"ok": False, "path": path, "version": ""}

    def _prewarm_adb_server(self):
        """启动后台拉起 adb server（幂等）。失败静默——它不是关键路径。

        server 冷启一次要数百 ms，由「启动后第一次截图」承担这笔钱会很莫名；
        在 boot 的后台线程里提前拉起来，用户点截图时它一定已在。
        """
        try:
            subprocess.run(
                [getattr(self.state, "adb_path", "") or "adb", "start-server"],
                **adb_kwargs(10))
        except Exception:
            pass

    def _target_serials(self, serial):
        if serial:
            return [serial]
        return self.devices.selected_serials()

    def _adb_argv(self):
        """当前 adb 可执行文件（-s 之外的所有 adb 调用都走这里）。"""
        return getattr(self.state, "adb_path", "") or "adb"

    def _wifi_default_port(self):
        try:
            return int(load_prefs().get("wifi_port", wifi.DEFAULT_PORT))
        except Exception:
            return wifi.DEFAULT_PORT

    def _wifi_recent(self):
        try:
            raw = load_prefs().get("wifi_recent", "")
        except Exception:
            raw = ""
        return wifi.recent_from_pref(raw)

    def _wifi_remember(self, addr):
        """把地址写进「最近连接」（config.json），并记住端口。"""
        recent = wifi.add_recent(self._wifi_recent(), addr)
        patch = {"wifi_recent": wifi.recent_to_pref(recent)}
        # 只有地址里真的写了端口才更新 wifi_port。mDNS 服务名（Android 11+ 的
        # 无线调试）不带端口，split_endpoint 会回落到默认 5555 —— 照抄就会把
        # 用户自定义过的端口悄悄改回 5555。
        if wifi.has_explicit_port(addr):
            patch["wifi_port"] = wifi.split_endpoint(addr)[1]
        try:
            save_prefs(patch)
        except Exception:
            pass                       # 配置只读时不该让连接本身失败
        return recent

    def wifi_state(self):
        """无线调试弹窗的初始数据：已连的无线设备 + 最近地址 + 目标设备。"""
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        items = self.devices.get_items()
        wireless = [{
            "serial": it.get("serial", ""),
            "model": it.get("model", ""),
            "ok": bool(it.get("ok")),
            "state": it.get("state", ""),
        } for it in items if wifi.is_wireless_serial(it.get("serial", ""))]
        return {
            "ok": True,
            "wireless": wireless,
            "usb": [it.get("serial", "") for it in items
                    if not wifi.is_wireless_serial(it.get("serial", ""))],
            "recent": self._wifi_recent(),
            "port": self._wifi_default_port(),
            "selected": self.devices.selected_serials(),
        }

    def wifi_connect(self, address):
        """`adb connect <ip:port>`：连上后立刻刷新设备列表。

        地址由 core.wireless.normalize_endpoint 校验后才拼进参数位——把
        「adb connect 1.2.3.4」整条命令粘进来也能被正确解析。
        """
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        addr, err = wifi.normalize_endpoint(address, self._wifi_default_port())
        if err:
            self._push_status("warn", "⚠ 无线调试地址无效：" + err)
            return {"ok": False, "reason": err}
        try:
            r = subprocess.run([self._adb_argv(), "connect", addr],
                               **adb_kwargs(25))
        except Exception as e:
            return {"ok": False, "reason": "执行 adb connect 失败：%s" % e}
        res = wifi.parse_connect_output(
            (r.stdout or "") + "\n" + (r.stderr or ""))
        if not res["ok"]:
            self._push_status("err", "✗ 无线连接失败（%s）：%s"
                              % (addr, res["message"]), toast=True)
            return {"ok": False, "reason": res["message"], "address": addr}
        recent = self._wifi_remember(addr)
        self._push_status("ok", "✓ 无线调试已连接：%s" % addr, toast=True)
        # 连上不代表 `adb devices` 立刻可见（首次连接要等设备完成认证），
        # 但刷新一次能让已就绪的设备马上出现在左侧列表里。
        # key 独立于常规刷新（refresh）：那个 key 被自动刷新循环与手动刷新
        # 共用，撞上就会「复用存活线程」而这次刷新被静默吞掉——表现是
        # 「提示已连接，但左边列表里没有这台设备」。
        self.workers.spawn("refresh_wifi", self.devices.refresh,
                           self._adb_argv(), True)
        return {"ok": True, "address": addr, "message": res["message"],
                "recent": recent}

    def wifi_disconnect(self, address):
        """`adb disconnect <ip:port>`；也接受 mDNS 序列号原样传入。"""
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        raw = (address or "").strip()
        if not raw:
            return {"ok": False, "reason": "请先选择要断开的无线设备"}
        if wifi.is_wireless_serial(raw) and ":" in raw:
            addr, err = wifi.normalize_endpoint(raw, self._wifi_default_port())
            if err:
                return {"ok": False, "reason": err}
        else:
            addr = raw                      # mDNS 服务名：adb 原样接受
        try:
            r = subprocess.run([self._adb_argv(), "disconnect", addr],
                               **adb_kwargs(20))
        except Exception as e:
            return {"ok": False, "reason": "执行 adb disconnect 失败：%s" % e}
        text = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
        low = text.lower()
        if "error" in low or "no such device" in low:
            self._push_status("err", "✗ 断开失败（%s）：%s"
                              % (addr, text[:160]), toast=True)
            return {"ok": False, "reason": text[:160] or "adb 拒绝断开"}
        self._push_status("ok", "✓ 已断开无线设备：%s" % addr, toast=True)
        self.workers.spawn("refresh_wifi", self.devices.refresh,
                           self._adb_argv(), True)
        return {"ok": True, "address": addr}

    def _device_ip(self, serial):
        """读设备自身 IP（`ip route` + `ip -4 addr`）。返回 (ip, iface)。"""
        script = "ip route 2>/dev/null; echo @@ADDR; ip -4 addr 2>/dev/null"
        try:
            r = subprocess.run(
                [self._adb_argv(), "-s", serial, "shell", script],
                **adb_kwargs(15))
        except Exception:
            return "", ""
        return wifi.parse_device_ip(r.stdout or "")

    def wifi_enable(self, serial=None, port=None):
        """对目标设备执行 `adb tcpip <port>`，顺便把设备 IP 一起取回来。

        车机调试的典型流程是「插一次线 → 开无线 → 拔线」，而手动查 IP
        （设置里翻 WLAN 详情）是最容易被卡住的一步，所以这里一并读出来，
        前端直接填进地址框、点一下就连接。
        """
        if self.state.shutting_down:
            return {"ok": False, "reason": "shutting_down"}
        try:
            p = int(port) if port not in (None, "") else self._wifi_default_port()
        except (TypeError, ValueError):
            p = self._wifi_default_port()
        if not 1024 <= p <= 65535:
            return {"ok": False, "reason": "端口号必须是 1024~65535 的整数"}
        targets = self._target_serials(serial)
        if not targets:
            return {"ok": False, "reason": "请先在左侧勾选设备（首次开启必须走 USB）"}
        results = []
        for s in targets:
            ip, iface = self._device_ip(s)
            try:
                r = subprocess.run(
                    [self._adb_argv(), "-s", s, "tcpip", str(p)],
                    **adb_kwargs(20))
                out = ((r.stdout or "") + "\n" + (r.stderr or ""))
            except Exception as e:
                out = str(e)
            res = wifi.parse_tcpip_output(out)
            addr = "%s:%d" % (ip, p) if ip else ""
            results.append({
                "serial": s, "ip": ip, "iface": iface,
                "address": addr, "ok": res["ok"], "message": res["message"],
            })
            if res["ok"]:
                self._push_status(
                    "ok", "✓ %s 已开启无线调试%s（端口 %d）"
                    % (s, "：" + addr if addr else "，但没读到设备 IP，请手动填入",
                       res["port"] or p))
            else:
                self._push_status("err", "✗ %s 开启无线调试失败：%s"
                                  % (s, res["message"]), toast=True)
        ok_any = any(x["ok"] for x in results)
        first_addr = next((x["address"] for x in results if x["address"]), "")
        if ok_any:
            try:
                save_prefs({"wifi_port": p})
            except Exception:
                pass
        return {"ok": ok_any, "port": p, "results": results,
                "address": first_addr}
