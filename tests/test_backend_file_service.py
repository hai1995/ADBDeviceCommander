# -*- coding: utf-8 -*-
"""backend.file_service.FileService —— 设备文件系统管理单测。

回归保护：list_dir 必须使用最广泛兼容的 `ls -la`（不带 GNU 扩展），
否则在 Android Toybox / BusyBox 设备上会因 --time-style 不支持而整列失败。
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import backend.file_service as fs_mod
from backend.file_service import FileService


TOYBOX_LS_OUTPUT = (
    "total 80\n"
    "drwxr-xr-x 2 root root     4096 Sep  4 10:12 data\n"
    "drwxr-xr-x 3 root root     4096 Sep  4 10:12 system\n"
    "-rw-r--r-- 1 root root      123 Sep  4 10:13 build.prop\n"
    "lrwxrwxrwx 1 root root        7 Sep  4 10:12 hw -> /system/hw\n"
)


def _make_fake_run(records, stdout_text=TOYBOX_LS_OUTPUT, returncode=0):
    """构造 subprocess.run 替身：记录所有调用命令，返回指定 stdout。"""
    def fake_run(cmd, **kw):
        records.append(list(cmd))
        return type("R", (), {
            "stdout": stdout_text, "stderr": "", "returncode": returncode,
        })()
    return fake_run


def test_list_dir_does_not_pass_gnu_time_style(monkeypatch):
    """回归保护：原 --time-style=long-iso 在 Toybox 不支持导致整列失败。
    list_dir 必须仅传 ls -la，不带任何 GNU 扩展。"""
    records = []
    monkeypatch.setattr(fs_mod.subprocess, "run", _make_fake_run(records))
    svc = FileService()
    items, err = svc.list_dir("SERIAL", "/sdcard")
    assert err is None, err
    assert items is not None
    # 校验命令：必须包含 ls -la 但绝不包含 --time-style
    cmd = records[0]
    assert "ls" in cmd and "-la" in cmd
    assert all("--time-style" not in str(x) for x in cmd)
    # 至少成功解析出 data / system / build.prop
    names = [i["name"] for i in items]
    assert "data" in names and "system" in names and "build.prop" in names


def test_list_dir_parses_toybox_default_format(monkeypatch):
    """Toybox 默认输出格式为 "Mon D HH:MM"，解析器必须能正确处理。"""
    records = []
    monkeypatch.setattr(fs_mod.subprocess, "run", _make_fake_run(records))
    svc = FileService()
    items, err = svc.list_dir("SERIAL", "/sdcard")
    assert err is None and items
    d = next(i for i in items if i["name"] == "data")
    assert d["is_dir"] and d["perm"] == "drwxr-xr-x" and d["size"] == 4096
    f = next(i for i in items if i["name"] == "build.prop")
    assert not f["is_dir"] and f["size"] == 123
    ln = next(i for i in items if i["name"] == "hw")
    assert ln["is_link"] and ln["target"] == "/system/hw"


def test_list_dir_falls_back_when_first_parse_empty(monkeypatch):
    """若首次 ls -la 解析为空，list_dir 应自动重试 ls -l。"""
    records = []
    # 第一次返回空 ls 输出（设备异常 / 输出被截断），第二次返回正常 Toybox 输出
    responses = iter([
        TOYBOX_LS_OUTPUT[:0],     # 空字符串 -> 解析为空
        TOYBOX_LS_OUTPUT,
    ])
    def fake_run(cmd, **kw):
        records.append(list(cmd))
        stdout = next(responses)
        return type("R", (), {
            "stdout": stdout, "stderr": "", "returncode": 0,
        })()
    monkeypatch.setattr(fs_mod.subprocess, "run", fake_run)
    svc = FileService()
    items, err = svc.list_dir("SERIAL", "/sdcard")
    assert err is None
    # 两次调用：第一次 -la，第二次 -l
    assert len(records) == 2
    assert "-la" in records[0]
    assert "-l" in records[1] and "-la" not in records[1]
    # 第二次成功解析
    assert any(i["name"] == "data" for i in items)


def test_list_dir_returns_error_on_failure(monkeypatch):
    """adb shell 失败时必须返回错误信息，不抛异常。"""
    def fake_run(cmd, **kw):
        return type("R", (), {
            "stdout": "", "stderr": "ls: permission denied", "returncode": 1,
        })()
    monkeypatch.setattr(fs_mod.subprocess, "run", fake_run)
    svc = FileService()
    items, err = svc.list_dir("SERIAL", "/root")
    assert items is None
    assert err and "permission" in err.lower()


# ---------------------------------------------------------------------------
# shq：设备端路径必须整体包裹为单引号 shell 参数
# （回归：adb shell 会把空格路径拆成多个参数，rm -rf 可能误删相邻文件）
# ---------------------------------------------------------------------------
def test_shq_wraps_path_in_single_quotes():
    assert fs_mod.shq("/sdcard/My Folder/a.txt") == "'/sdcard/My Folder/a.txt'"


def test_shq_escapes_inner_single_quote():
    assert fs_mod.shq("it's") == "'it'\\''s'"


def test_list_dir_path_is_shell_quoted(monkeypatch):
    """list_dir 的路径参数必须带单引号，空格目录才不会被拆开。"""
    records = []
    monkeypatch.setattr(fs_mod.subprocess, "run", _make_fake_run(records))
    svc = FileService()
    items, err = svc.list_dir("SERIAL", "/sdcard/My Folder")
    assert err is None and items is not None
    assert "'/sdcard/My Folder/.'" in records[0]


def test_remove_quotes_every_path(monkeypatch):
    """remove 的每个路径都必须单独包裹（含空格时绝不拆参数）。"""
    records = []
    monkeypatch.setattr(fs_mod.subprocess, "run", _make_fake_run(records))
    svc = FileService()
    ok, err = svc.remove("SERIAL", ["/a b", "/plain", "we'ird"])
    assert ok and err == ""
    assert "'/a b'" in records[0]
    assert "'/plain'" in records[0]
    assert "'we'\\''ird'" in records[0]


# ---------------------------------------------------------------------------
# view：大文件不得经 IPC 直传；临时文件名防并行碰撞
# ---------------------------------------------------------------------------
def test_view_small_file_returns_text_without_pull(monkeypatch):
    """小文件 cat 成功时应直接返回文本，不触发 pull。"""
    records = []
    monkeypatch.setattr(fs_mod.subprocess, "run",
                        _make_fake_run(records, stdout_text="hello world"))
    svc = FileService()
    res, err = svc.view("SERIAL", "/sdcard/small.txt")
    assert err is None
    assert res == {"text": "hello world", "local": None}
    assert not any("pull" in c for c in records), "小文件不应 pull"


def test_view_large_cat_output_falls_back_to_pull(monkeypatch, tmp_path):
    """cat 输出超过上限时必须走 pull 路径：超长文本直传前端会卡死界面。

    回归：cat 一个上百 MB 的日志/二进制文件时，旧实现把整段文本经事件总线 +
    pywebview IPC 直送前端，主线程被序列化/解析独占。
    """
    records = []

    def fake_run(cmd, **kw):
        records.append(list(cmd))
        if "cat" in cmd:
            return type("R", (), {"stdout": "x" * 100, "stderr": "",
                                  "returncode": 0})()
        if "pull" in cmd:
            with open(cmd[-1], "w", encoding="utf-8") as f:
                f.write("y" * 5)     # pull 回来后仍在限额内 -> 直接给文本
            return type("R", (), {"stdout": "", "stderr": "",
                                  "returncode": 0})()
        return type("R", (), {"stdout": "", "stderr": "", "returncode": 0})()

    monkeypatch.setattr(fs_mod.subprocess, "run", fake_run)
    svc = FileService()
    res, err = svc.view("SERIAL", "/sdcard/big.log", max_inline_bytes=10)
    assert err is None
    assert any("pull" in c for c in records), "超过上限应回退到 pull"
    assert res["text"] == "y" * 5, "pull 回来后（仍在限额内）应直接给文本"


def test_view_temp_name_is_unique_per_call(monkeypatch, tmp_path):
    """并行查看不同目录下的同名文件时，pull 的临时文件名不得互相覆盖。"""
    pulls = []

    def fake_run(cmd, **kw):
        if "cat" in cmd:
            return type("R", (), {"stdout": "", "stderr": "",
                                  "returncode": 1})()
        pulls.append(cmd[-1])
        with open(cmd[-1], "wb") as f:
            f.write(b"\x00" * 8192)     # 超过 max_inline_bytes -> 保留本地路径
        return type("R", (), {"stdout": "", "stderr": "", "returncode": 0})()

    monkeypatch.setattr(fs_mod.subprocess, "run", fake_run)
    svc = FileService()
    r1, _ = svc.view("SERIAL", "/a/data.bin", max_inline_bytes=1024)
    r2, _ = svc.view("SERIAL", "/b/data.bin", max_inline_bytes=1024)
    assert len(pulls) == 2
    assert pulls[0] != pulls[1], "两次 pull 的临时文件名必须不同（否则互相覆盖）"
    assert r1["local"] and r2["local"] and r1["local"] != r2["local"]


# ---------------------------------------------------------------------------
# download：设备端文件名含 Windows 非法字符（如冒号）时必须净化
# ---------------------------------------------------------------------------
def test_download_sanitizes_illegal_remote_name(monkeypatch, tmp_path):
    """设备端文件名含冒号（Android 合法、Windows 非法）时，本地路径必须净化，
    否则 pull 落盘直接失败，用户看到「下载失败」却不知为何。"""

    def fake_run(cmd, **kw):
        if "pull" in cmd:
            # adb pull <remote> <local_dir>：在净化后的本地路径上造出文件
            with open(os.path.join(cmd[-1], "a_b.txt"), "wb") as f:
                f.write(b"data")
            return type("R", (), {"stdout": "", "stderr": "",
                                  "returncode": 0})()
        return type("R", (), {"stdout": "", "stderr": "", "returncode": 0})()

    monkeypatch.setattr(fs_mod.subprocess, "run", fake_run)
    svc = FileService()
    local, err = svc.download("SERIAL", "/sdcard/a:b.txt", str(tmp_path))
    assert err is None
    assert local and os.path.exists(local)
    assert ":" not in os.path.basename(local), "本地文件名不得含冒号：%s" % local


def test_download_finds_file_pulled_under_original_name(monkeypatch, tmp_path):
    """adb 只按**设备端原名**落盘，它不认识我们的净化规则。

    回归：早前 pull 成功后只查净化后的路径，于是真机上「文件其实已经下载好了」
    被判成失败，而且错误文本是 None —— 界面显示「下载失败 /sdcard/a:b.txt: None」。
    这里复现「落盘用的是原名」，断言仍能拿到路径、并尽量改成净化名。
    """
    import pytest
    if os.name == "nt":
        pytest.skip("Windows 不允许创建含冒号的文件名，无法复现该场景")

    def fake_run(cmd, **kw):
        if "pull" in cmd:
            with open(os.path.join(cmd[-1], "a:b.txt"), "wb") as f:
                f.write(b"data")
        return type("R", (), {"stdout": "", "stderr": "", "returncode": 0})()

    monkeypatch.setattr(fs_mod.subprocess, "run", fake_run)
    local, err = FileService().download("SERIAL", "/sdcard/a:b.txt",
                                        str(tmp_path))
    assert err is None, "文件确实下载成功了，不能报错：%r" % (err,)
    assert local and os.path.exists(local)
    assert ":" not in os.path.basename(local), "应已改名为净化后的名字"
    assert os.path.exists(os.path.join(str(tmp_path), "a_b.txt"))


def test_download_reports_clear_error_when_no_file_landed(monkeypatch, tmp_path):
    """pull 返回 0 但本地没有文件：必须给出可读原因，而不是 (None, None)。"""
    monkeypatch.setattr(
        fs_mod.subprocess, "run",
        lambda cmd, **kw: type("R", (), {"stdout": "", "stderr": "",
                                         "returncode": 0})())
    local, err = FileService().download("SERIAL", "/sdcard/x.txt", str(tmp_path))
    assert local is None
    assert err and "落文件" in err
