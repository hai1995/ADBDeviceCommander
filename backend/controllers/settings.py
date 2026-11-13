"""backend.controllers.settings —— 设置 / adb 状态 / Wi-Fi 无线调试"""

from backend.controller import (
    adb_kwargs, apply_adb_dir, load_prefs, os,
    prefs_path, resolve_save_dir, save_prefs_checked, subprocess,
    wifi,
)
from core import win_theme
from core.devices import parse_devices
from core.longpath import path_exists

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

    def set_theme(self, mode):
        """切换界面主题时联动原生标题栏（只有 Windows 才绘制标题栏，非 Windows 静默）。

        mode: "dark" / "light" / "system"。前端已负责把主题落盘、给 <html> 套
        data-theme、并解析 system → 实际深浅；这里只管让原生标题栏配色跟上。
        system 在 Windows 上读注册表解析为实际深浅。返回里带上 win_theme 的实际
        结果便于排查，但「非 Windows 不支持」是预期内，不当作失败。
        """
        if mode not in ("dark", "light", "system"):
            self._push_status("err", "⚠ 主题切换失败：未知的取值 %s" % mode)
            return {"ok": False, "reason": "invalid_mode", "mode": mode}
        try:
            res = win_theme.apply_for_mode(mode, pid=os.getpid())
        except Exception as e:  # 标题栏配色是锦上添花，任何异常都不能影响切换
            self._push_status(
                "err", "⚠ 原生标题栏配色未能应用（界面主题已切换）：%s" % e)
            return {"ok": False, "reason": "apply_failed", "mode": mode,
                    "error": str(e)}
        # 非 Windows 上 win_theme 恒返回 unsupported —— 那是预期内，不算失败。
        applied = bool(res.get("ok")) or res.get("reason") == "unsupported"
        return {"ok": applied, "mode": mode, "title_bar": res}

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
            "exists": path_exists(p),
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

    def _adb_found(self):
        """adb 可执行文件是否找得到（纯 PATH 文件查找，不跑子进程，毫秒级）。

        boot 阶段用它代替 _probe_adb：`adb version` 子进程在 adb 异常时会卡满
        8 秒超时，不能把界面就绪押在它身上。真实版本号由 _prewarm_adb_server
        在后台探测后推 adb_info 事件补上。
        """
        import shutil
        path = getattr(self.state, "adb_path", "") or "adb"
        try:
            return bool(shutil.which(path))
        except Exception:
            return False

    def _prewarm_adb_server(self):
        """后台拉起 adb server（幂等）+ 探测真实 adb 版本。失败静默。

        server 冷启一次要数百 ms，由「启动后第一次截图」承担这笔钱会很莫名；
        在 boot 的后台线程里提前拉起来，用户点截图时它一定已在。

        boot 阶段的 adb 状态只是文件级查找（_adb_found），真实版本号在这里
        用 `adb version` 探测（后台线程，即使卡满超时也不挡界面）：探测到就
        写进 prefs 缓存（下次启动的 boot 直接展示），并推 adb_info 事件让
        前端关于页把缓存版本 / 路径替换成真实版本。
        """
        try:
            subprocess.run(
                [getattr(self.state, "adb_path", "") or "adb", "start-server"],
                **adb_kwargs(10))
        except Exception:
            pass
        try:
            info = self._probe_adb()
        except Exception:
            return
        if info["ok"] and info["version"]:
            try:
                if load_prefs().get("adb_version_cache", "") != info["version"]:
                    save_prefs_checked({"adb_version_cache": info["version"]})
            except Exception:
                pass
        try:
            self.bus.push("adb_info", {
                "ok": info["ok"], "path": info["path"],
                "version": info["version"]})
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
        # 配置只读时**不能让连接本身失败**，但也绝不能说没事：这条地址本该出现在
        # 「最近连接」里，下次进来却发现是空的 —— 用户会以为程序没记住，只能重敲。
        try:
            wrote = save_prefs_checked(patch)[1]
        except Exception as e:
            wrote = False
            self._push_status("warn", "⚠ 已连接，但保存「最近连接」时出错：%s" % e)
            return recent
        if not wrote:
            self._push_status(
                "warn", "⚠ 已连接，但「最近连接」没能写入 %s"
                        "（目录只读 / 文件被占用 / 磁盘已满？），"
                        "下次需要重新输入地址。" % prefs_path())
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
            self._push_status(
                "err", "✗ 无线连接失败（%s）：执行 adb connect 失败：%s"
                       % (addr, e), toast=True)
            return {"ok": False, "reason": "执行 adb connect 失败：%s" % e,
                    "address": addr}
        res = wifi.parse_connect_output(
            (r.stdout or "") + "\n" + (r.stderr or ""))
        # 以 adb devices 的实际状态对账（见方法 docstring）。adb connect 报成功但
        # 设备还没上线、报失败但设备其实已注册，都要在这里被纠偏，否则就是「假失败」。
        state = self._wifi_device_state(addr)
        if state == "device":
            return self._wifi_connect_ok(addr)
        if state == "unauthorized":
            self._push_status(
                "err", "✗ 无线连接失败（%s）：设备未授权——请在车机 / 手机端"
                       "「允许 USB 调试吗」弹窗里点「允许」，再重新连接"
                       % addr, toast=True)
            return {"ok": False,
                    "reason": "设备未授权，请在设备上点「允许 USB 调试」后重试",
                    "address": addr}
        if state == "offline":
            self._push_status(
                "err", "✗ 无线连接失败（%s）：设备已注册但连接未就绪（offline）——"
                       "确认电脑与设备在同一网段后，稍等几秒再试" % addr,
                toast=True)
            return {"ok": False,
                    "reason": "设备已注册但连接未就绪（offline），稍后重试",
                    "address": addr}
        if not res["ok"]:
            self._push_status("err", "✗ 无线连接失败（%s）：%s"
                              % (addr, res["message"]), toast=True)
            return {"ok": False, "reason": res["message"], "address": addr}
        # adb connect 成功且设备已在列表（状态非上述三类，理论不会到这）：兜底仍按
        # 成功处理，避免「连上了却报失败」。
        return self._wifi_connect_ok(addr)

    def _wifi_connect_ok(self, addr):
        """连接成功的统一收尾：记最近、推成功、刷设备列表。"""
        recent = self._wifi_remember(addr)
        self._push_status("ok", "✓ 无线调试已连接：%s" % addr, toast=True)
        # 连上不代表 `adb devices` 立刻可见（首次连接要等设备完成认证），但刷新一次
        # 能让已就绪的设备马上出现在左侧列表里。key 独立于常规刷新（refresh）：
        # 那个 key 被自动刷新循环与手动刷新共用，撞上就会「复用存活线程」而这次
        # 刷新被静默吞掉——表现是「提示已连接，但左边列表里没有这台设备」。
        self.workers.spawn("refresh_wifi", self.devices.refresh,
                           self._adb_argv(), True)
        return {"ok": True, "address": addr, "message": "连接成功",
                "recent": recent}

    def _wifi_device_state(self, addr):
        """查 `adb devices`，看 addr 当前在不在列表、是什么状态。

        用于无线连接后对账：`adb connect` 的输出（尤其失败）常常不准。
        返回 'device' / 'unauthorized' / 'offline' / ... 或 ''（不在列表）。
        """
        try:
            r = subprocess.run([self._adb_argv(), "devices"], **adb_kwargs(10))
        except Exception:
            return ""
        text = ((r.stdout or "") + "\n" + (r.stderr or ""))
        for serial, state, _ in parse_devices(text):
            if serial == addr:
                return state
        return ""

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
            # 端口记不住时，下次「开启无线调试」会退回默认端口 —— 而这次明明
            # 是按用户填的端口开的，之后连不上没有任何线索。宁可提示一句。
            try:
                wrote = save_prefs_checked({"wifi_port": p})[1]
            except Exception as e:
                wrote = False
                self._push_status("warn", "⚠ 无线调试已开启，但保存端口失败：%s" % e)
            if not wrote:
                self._push_status(
                    "warn", "⚠ 无线调试已开启（端口 %d），但端口没能写入 %s"
                            "（目录只读 / 文件被占用？），下次会按默认端口处理。"
                            % (p, prefs_path()))
        return {"ok": ok_any, "port": p, "results": results,
                "address": first_addr}
