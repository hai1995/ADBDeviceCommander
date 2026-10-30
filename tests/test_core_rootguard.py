# -*- coding: utf-8 -*-
"""core.rootguard —— root/unroot 命令识别 + 设备 root 状态查询单测。"""
import subprocess

import pytest

import core.rootguard as rg


# ---------------------------------------------------------------------------
# root_intent：命令识别
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("cmd,expect", [
    ("adb root", "root"),
    ("adb.exe root", "root"),
    ("adb -s A1 root", "root"),
    ("adb -s 192.168.1.5:5555 root", "root"),
    ("adb root && adb shell xx", "root"),          # 复合命令同样会重启 adbd
    ("adb root; adb remount", "root"),
    ("adb unroot", "unroot"),
    ("adb -s A1 unroot", "unroot"),
    ("  adb   root  ", "root"),
])
def test_root_intent_detected(cmd, expect):
    assert rg.root_intent(cmd) == expect


@pytest.mark.parametrize("cmd", [
    "adb devices",
    "adb shell id -u",
    "adb shell root",            # root 不是 shell 子命令，不能误判
    "adb roots",                 # 词边界：不匹配 roots
    "adb unrooted",              # 词边界：不匹配 unrooted
    "myadb root",                # 前边界：不是独立 adb
    "adb-shell root",
    'echo "adb root"',           # 引号内：仅回显字符串，不下发
    'git commit -m "adb root 修复"',   # 引号内：提交信息里提到 root
    "$cmd = 'adb root'",         # 变量/字符串赋值里的字样
    "adb remount",
    "adb reboot",
    "git status",
    "",
])
def test_root_intent_not_detected(cmd):
    assert rg.root_intent(cmd) is None


# ---------------------------------------------------------------------------
# device_is_root：状态查询
# ---------------------------------------------------------------------------
def _fake_run(monkeypatch, replies):
    """按命令内容返回预置 replies 的 subprocess.run 替身，并记录调用。"""
    seen = []

    def fake_run(cmd, **kw):
        seen.append(list(cmd))
        for key, (rc, out) in replies.items():
            if key in cmd:
                return type("R", (), {"returncode": rc, "stdout": out,
                                      "stderr": ""})()
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(rg.subprocess, "run", fake_run)
    return seen


def test_device_is_root_true(monkeypatch):
    seen = _fake_run(monkeypatch, {"id": (0, "0\n")})
    assert rg.device_is_root("adb", "A1") is True
    assert seen[0][:4] == ["adb", "-s", "A1", "shell"]


def test_device_is_root_false_for_shell_user(monkeypatch):
    _fake_run(monkeypatch, {"id": (0, "2000\n")})
    assert rg.device_is_root("adb", "A1") is False


def test_device_is_root_falls_back_to_whoami(monkeypatch):
    """个别 ROM 的 toybox 没有 id：退化 whoami 含 root 判定。"""
    def fake_run(cmd, **kw):
        if "id" in cmd:
            return type("R", (), {"returncode": 127, "stdout": "",
                                  "stderr": "id: not found"})()
        return type("R", (), {"returncode": 0, "stdout": "root\n",
                              "stderr": ""})()
    monkeypatch.setattr(rg.subprocess, "run", fake_run)
    assert rg.device_is_root("adb", "A1") is True


def test_device_is_root_false_on_probe_failure(monkeypatch):
    """adb 瞬断 / 设备离线：探测失败按「未 root」（需要切换）处理，不抛异常。"""
    def boom(cmd, **kw):
        raise OSError("adb server 没了")

    monkeypatch.setattr(rg.subprocess, "run", boom)
    assert rg.device_is_root("adb", "A1") is False
