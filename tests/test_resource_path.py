"""测试 core.constants.resource_path（开发态 / 打包态优先级）。

（原 legacy_main_tk 版测试已迁移到 core 包。）
"""
import os
import sys

import core.constants as cconst


def test_resource_path_dev_uses_project_root(monkeypatch, tmp_path):
    # 开发态：frozen 不存在，按 PROJECT_ROOT 解析
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(cconst, "PROJECT_ROOT", str(tmp_path))
    (tmp_path / "foo.txt").write_text("x")
    got = cconst.resource_path("foo.txt")
    assert got == str(tmp_path / "foo.txt")


def test_resource_path_frozen_prefers_exe_dir(monkeypatch, tmp_path):
    # 打包态：exe 同目录存在资源 -> 优先返回 exe 同目录这份（可编辑）
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    exe = tmp_path / "dist" / "ADB设备指令台.exe"
    exe.parent.mkdir(parents=True)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    (tmp_path / "dist" / "quick_commands.json").write_text("{}")
    got = cconst.resource_path("quick_commands.json")
    assert got == str(tmp_path / "dist" / "quick_commands.json")


def test_resource_path_frozen_falls_back_to_meipass(monkeypatch, tmp_path):
    # 打包态：exe 同目录没有该资源 -> 回退到 _MEIPASS 内置只读副本
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    exe = tmp_path / "dist" / "app.exe"
    exe.parent.mkdir(parents=True)
    monkeypatch.setattr(sys, "executable", str(exe))

    meipass = tmp_path / "_MEI1234"
    meipass.mkdir()
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)

    (meipass / "assets").mkdir()
    (meipass / "assets" / "app.ico").write_bytes(b"x")
    # 入参用 os.path.join 拼，别写死 "assets/app.ico"：Windows 上 os.path.join
    # 会产出 "…\assets/app.ico"（分隔符混用），与 pathlib 的 "…\assets\app.ico"
    # 字符串不相等 —— 两条路径对系统等价，但断言只在 POSIX 上成立。
    got = cconst.resource_path(os.path.join("assets", "app.ico"))
    assert os.path.normpath(got) == os.path.normpath(str(meipass / "assets" / "app.ico"))


def test_resource_path_frozen_missing_returns_exe_path(monkeypatch, tmp_path):
    # 打包态：都不存在 -> 返回 exe 同目录的推导路径（让 open 报明确错误）
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    exe = tmp_path / "dist" / "app.exe"
    exe.parent.mkdir(parents=True)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    got = cconst.resource_path("nope.json")
    assert got == str(tmp_path / "dist" / "nope.json")
