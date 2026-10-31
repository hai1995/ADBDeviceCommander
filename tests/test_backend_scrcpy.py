# -*- coding: utf-8 -*-
"""backend.scrcpy_service —— 投屏（调用本机 scrcpy）的探测与进程管理单测。

本文件刻意**不要求本机装 scrcpy、也不连真机**：
  * 探测（find_scrcpy / probe）用临时目录造「假 scrcpy」来验证查找顺序与说明文案；
  * 启动（ScrcpyLauncher）用 Popen 替身拦截，只验证「不重复开窗 / 秒退能拿到原因 /
    收尾能关掉」这些进程语义。

真实调用 scrcpy 的行为（窗口有没有出来）只能在用户机器上看，这里不假装能测。
"""
import os

import pytest

import backend.scrcpy_service as svc


def _fake_exe(dir_path):
    """在目录里造一个「假 scrcpy」可执行文件（名字必须能被探测逻辑认出来）。"""
    name = "scrcpy.exe" if os.name == "nt" else "scrcpy"
    p = dir_path / name
    p.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    return p


# ---------------------------------------------------------------- 探测


def test_find_prefers_configured_dir(tmp_path):
    exe = _fake_exe(tmp_path)
    found, note = svc.find_scrcpy(str(tmp_path))
    assert found == str(exe)
    assert "配置" in note


def test_find_accepts_exe_path_and_name(tmp_path):
    """配置项既能填目录，也能填 exe 全路径（与 adb_dir 的宽容度一致）。"""
    exe = _fake_exe(tmp_path)
    assert svc.find_scrcpy(str(exe))[0] == str(exe)


def test_find_invalid_config_falls_back_and_explains(monkeypatch, tmp_path):
    """配置了不存在的路径：继续自动探测，但必须说明「配置的路径无效」，
    否则用户会以为填了却没生效。"""
    monkeypatch.setattr(svc, "_extra_dirs", lambda: [])
    monkeypatch.setattr(svc.shutil, "which", lambda name: None)
    found, note = svc.find_scrcpy(str(tmp_path / "not-here"))
    assert found is None
    assert "配置的路径无效" in note
    assert "winget" in note          # 找不到时给的是可执行的安装指引


def test_find_scans_extra_dirs(monkeypatch, tmp_path):
    d = tmp_path / "scrcpy-win64"
    d.mkdir()
    exe = _fake_exe(d)
    monkeypatch.setattr(svc.shutil, "which", lambda name: None)
    monkeypatch.setattr(svc, "_extra_dirs", lambda: [str(d)])
    found, note = svc.find_scrcpy("")
    assert found == str(exe)
    assert "常见安装目录" in note


def test_find_scans_winget_package_layout(monkeypatch, tmp_path):
    """winget 布局是 Packages/<包名>/<版本>/scrcpy.exe，要能往下扫两层。"""
    pkgs = tmp_path / "Microsoft" / "WinGet" / "Packages"
    ver_dir = pkgs / "Genymobile.scrcpy_Microsoft.Winget.Source_8wekyb3d8bbwe" / "2.4"
    ver_dir.mkdir(parents=True)
    exe = _fake_exe(ver_dir)
    monkeypatch.setattr(svc.shutil, "which", lambda name: None)
    monkeypatch.setattr(svc, "_extra_dirs", lambda: [str(pkgs)])
    found, note = svc.find_scrcpy("")
    assert found == str(exe)
    assert "winget" in note


def test_probe_reports_version_and_handles_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(svc, "_extra_dirs", lambda: [])
    monkeypatch.setattr(svc.shutil, "which", lambda name: None)
    miss = svc.probe("")
    assert miss["ok"] is False and miss["path"] == "" and miss["note"]

    # 假 exe 用当前解释器代替：`<exe> --version` 能跑通并输出一行版本
    import sys
    ok = svc.probe(sys.executable)
    assert ok["ok"] is True
    assert ok["path"] == sys.executable
    assert ok["version"]


# ---------------------------------------------------------------- 启动 / 收尾


class _FakeProc:
    """Popen 替身：poll() 决定「还活着」还是「秒退」。"""

    def __init__(self, args, alive=True, code=0, stdout=None, **kw):
        self.args = args
        self._alive = alive
        self._code = code
        self.terminated = False
        if stdout is not None and not alive:
            # 模拟 scrcpy 自己把报错写进 stderr（_spawn 把两者合并到同一文件）
            stdout.write(b"ERROR: Could not find any ADB device\n")
            stdout.flush()

    def poll(self):
        return None if self._alive else self._code

    def terminate(self):
        self.terminated = True


@pytest.fixture()
def fast(monkeypatch):
    """免等 START_SETTLE_S，并把 Popen 换成可配置的替身。"""
    monkeypatch.setattr(svc, "START_SETTLE_S", 0)
    procs = []

    def _install(**kw):
        def _popen(args, **kwargs):
            p = _FakeProc(args, stdout=kwargs.get("stdout"), **kw)
            procs.append(p)
            return p
        monkeypatch.setattr(svc.subprocess, "Popen", _popen)
        return procs
    return _install


def test_launch_starts_one_window_per_device(fast):
    fast()
    L = svc.ScrcpyLauncher()
    res = L.launch(["A1", "B2"], "/fake/scrcpy")
    assert res["started"] == ["A1", "B2"]
    assert res["skipped"] == [] and res["failed"] == []
    assert L.alive() == ["A1", "B2"]


def test_launch_skips_device_already_casting(fast):
    """连点两次按钮不能开出两个窗口（同设备重复投屏会抢 adb 输入）。"""
    fast()
    L = svc.ScrcpyLauncher()
    L.launch(["A1"], "/fake/scrcpy")
    res = L.launch(["A1"], "/fake/scrcpy")
    assert res == {"started": [], "skipped": ["A1"], "failed": []}


def test_launch_reports_fast_exit_reason(fast):
    """scrcpy 秒退（未授权 / 版本不兼容）时要把它的报错带回来，
    否则用户只看到窗口一闪而过、以为"点了没反应"。"""
    fast(alive=False, code=1)
    L = svc.ScrcpyLauncher()
    res = L.launch(["A1"], "/fake/scrcpy")
    assert res["started"] == []
    serial, reason = res["failed"][0]
    assert serial == "A1"
    assert "立即退出" in reason and "退出码 1" in reason
    assert "Could not find any ADB device" in reason


def test_launch_passes_serial(fast):
    procs = fast()
    svc.ScrcpyLauncher().launch(["R58M123"], "/fake/scrcpy")
    assert procs[0].args == ["/fake/scrcpy", "-s", "R58M123"]


def test_close_all_terminates_only_own_windows(fast):
    procs = fast()
    L = svc.ScrcpyLauncher()
    L.launch(["A1"], "/fake/scrcpy")
    L.close_all()
    assert procs[0].terminated is True
    assert L.alive() == []


def test_alive_drops_exited_process(fast):
    """进程被用户关掉后，再次查询应把它从表里摘掉（否则永远显示"已在投屏"）。"""
    procs = fast()
    L = svc.ScrcpyLauncher()
    L.launch(["A1"], "/fake/scrcpy")
    assert L.alive() == ["A1"]
    procs[0]._alive = False          # 用户手动关掉投屏窗口
    assert L.alive() == []


def test_alive_removes_log_of_closed_window(fast):
    """用户关掉投屏窗口后，日志文件也要跟着删掉。

    回归：alive() 只把进程从表里摘掉，日志留在 _logs 里 —— 每台设备在 TEMP
    里各留一份 adc_scrcpy_*.log，直到下次程序启动被 tmpfiles 扫掉才消失。
    """
    procs = fast()
    L = svc.ScrcpyLauncher()
    L.launch(["A1"], "/fake/scrcpy")
    log = L._logs["A1"]
    assert os.path.exists(log)
    procs[0]._alive = False           # 用户手动关掉窗口
    assert L.alive() == []
    assert not os.path.exists(log), "窗口关掉后日志应一并删除"


def test_launch_failure_leaves_no_empty_log(monkeypatch, tmp_path):
    """Popen 直接失败时，别在 TEMP 留下一个 0 字节日志文件。"""
    monkeypatch.setattr(svc, "START_SETTLE_S", 0)
    monkeypatch.setattr(svc.tempfile, "gettempdir", lambda: str(tmp_path))

    def _boom(*a, **k):
        raise OSError("cannot start")

    monkeypatch.setattr(svc.subprocess, "Popen", _boom)
    res = svc.ScrcpyLauncher().launch(["A1"], "/fake/scrcpy")
    assert res["started"] == [] and res["failed"]
    assert os.listdir(str(tmp_path)) == []
