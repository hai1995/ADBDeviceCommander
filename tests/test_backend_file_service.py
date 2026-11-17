# -*- coding: utf-8 -*-
"""backend.file_service.FileService —— 设备文件系统管理单测。

回归保护：list_dir 必须使用最广泛兼容的 `ls -la`（不带 GNU 扩展），
否则在 Android Toybox / BusyBox 设备上会因 --time-style 不支持而整列失败。
"""
import sys
import os
import tempfile

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


def _R(stdout="", stderr="", returncode=0):
    return type("R", (), {"stdout": stdout, "stderr": stderr,
                          "returncode": returncode})()


ROOT_LS_WITH_LINKS = (
    "total 40\n"
    "drwxr-xr-x 2 root root 3483 2024-01-01 02:02 vendor_dlkm\n"
    "lrw-r--r-- 1 root root   21 2009-01-01 08:00 "
    "sdcard -> /storage/self/primary\n"
    "lrwxrwxrwx 1 root root    7 2009-01-01 08:00 hw -> /system/hw\n"
)


def test_list_dir_marks_symlink_to_directory_as_dir(monkeypatch):
    """`/sdcard` 这类「链到目录」的符号链接必须标成目录。

    回归：`ls -la` 只能看到链接本身（权限位 l 开头），旧实现统一按文件渲染，
    于是 `/sdcard` 点不进去，还给出「下载 / 查看」。list_dir 会用**一次**批量
    探测（[ -d ]）确认链接目标类型，而不是每个链接各跑一次 adb。
    """
    calls = []

    def fake_run(cmd, **kw):
        calls.append(list(cmd))
        if len(calls) == 1:
            return _R(stdout=ROOT_LS_WITH_LINKS)
        return _R(stdout="D\nF\n")      # sdcard -> 目录；hw -> 文件

    monkeypatch.setattr(fs_mod.subprocess, "run", fake_run)
    items, err = FileService().list_dir("SERIAL", "/")
    assert err is None
    by = {i["name"]: i for i in items}
    assert by["sdcard"]["is_dir"] is True, "指向目录的链接应可进入"
    assert by["sdcard"]["is_link"] is True, "仍然保留「这是符号链接」的信息"
    assert by["sdcard"]["target"] == "/storage/self/primary"
    assert by["hw"]["is_dir"] is False, "指向文件的链接不能被当成目录"
    names = [i["name"] for i in items]
    assert names.index("hw") > names.index("sdcard"), "现在应排到目录组"
    assert len(calls) == 2, "链接探测必须合成一次调用，实际 %d 次" % len(calls)
    assert "for f in" in calls[1][-1] and "'sdcard'" in calls[1][-1]


def test_list_dir_keeps_entries_when_link_probe_fails(monkeypatch):
    """链接探测失败时保持原判断（按文件），列表本身不能失败。"""
    calls = []

    def fake_run(cmd, **kw):
        calls.append(list(cmd))
        if len(calls) == 1:
            return _R(stdout=ROOT_LS_WITH_LINKS)
        return _R(stdout="", returncode=1)

    monkeypatch.setattr(fs_mod.subprocess, "run", fake_run)
    items, err = FileService().list_dir("SERIAL", "/")
    assert err is None and items
    by = {i["name"]: i for i in items}
    assert by["sdcard"]["is_dir"] is False


def test_list_dir_link_probe_quotes_dir_path(monkeypatch):
    """探测命令里的目录要整体加引号，含空格的目录才不会 cd 失败。"""
    calls = []

    def fake_run(cmd, **kw):
        calls.append(list(cmd))
        if len(calls) == 1:
            return _R(stdout="lrwxrwxrwx 1 root root 7 2009-01-01 08:00 "
                              "link -> /data\n")
        return _R(stdout="D\n")

    monkeypatch.setattr(fs_mod.subprocess, "run", fake_run)
    items, err = FileService().list_dir("SERIAL", "/sdcard/My Folder")
    assert err is None and items[0]["is_dir"] is True
    assert "cd '/sdcard/My Folder'" in calls[1][-1]


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
    # 前两次：-la 解析为空，随后用 -l 兜底；之后可能还有一次「符号链接是否指向
    # 目录」的探测（本次替身只有两份输出，探测会因取不到响应而被忽略）。
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
        if "head" in cmd:
            # 设备端按 head -c 裁出「上限 + 1」字节：超过上限 → 不许内联
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
        if "head" in cmd or "cat" in cmd:
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



# ---------------------------------------------------------------------------
# 失败原因：adb 的报错大多在 stdout 上，别让界面显示空原因
# ---------------------------------------------------------------------------
def _fail_run(stdout="", stderr=""):
    """构造一个 rc=1 的 adb 结果（模拟设备端命令失败）。"""
    return type("R", (), {"stdout": stdout, "stderr": stderr,
                          "returncode": 1})()


def test_make_dir_reports_error_printed_on_stdout(monkeypatch):
    """`adb shell mkdir` 的报错走 **stdout**，不能因此给出空原因。

    回归：所有文件操作都只读 `r.stderr`；而 adb shell 把远端命令的输出
    （包括 `mkdir: '/system/x': Read-only file system`）原样转在 stdout，
    stderr 是空的 —— 界面于是显示「⚠ 创建目录失败 /system/x: 」，
    原因那一栏一片空白，用户只能靠猜。
    """
    monkeypatch.setattr(fs_mod.subprocess, "run",
                        lambda cmd, **kw: _fail_run(
                            stdout="mkdir: '/system/x': Read-only file system"))
    ok, err = FileService().make_dir("S", "/system/x")
    assert ok is False
    assert "Read-only file system" in err


def test_failure_without_any_output_has_readable_reason(monkeypatch):
    """rc 非 0 且两路都空：至少要说清「adb 没给出原因」，不能是空串。"""
    monkeypatch.setattr(fs_mod.subprocess, "run", lambda cmd, **kw: _fail_run())
    for ok, err in (FileService().remove("S", ["/sdcard/x"]),
                    FileService().make_dir("S", "/sdcard/x"),
                    FileService().touch("S", "/sdcard/x"),
                    FileService().rename("S", "/a", "/b"),
                    FileService().upload("S", "/tmp/a", "/sdcard/a")):
        assert ok is False
        assert err and "没有给出原因" in err, err


def test_download_failure_text_comes_from_stdout(monkeypatch, tmp_path):
    """pull 失败时 adb 把错误写在 stdout，界面不能只显示一个空原因。"""
    monkeypatch.setattr(
        fs_mod.subprocess, "run",
        lambda cmd, **kw: _fail_run(
            stdout="adb: error: failed to copy '/sdcard/a' to "
                   "'%s/a': remote No such file or directory" % tmp_path))
    local, err = FileService().download("S", "/sdcard/a", str(tmp_path))
    assert local is None
    assert "failed to copy" in err

def test_view_caps_remote_read_instead_of_catting_whole_file(monkeypatch, tmp_path):
    """查看文件只从设备取「上限 + 1」字节，不再整段 cat 进内存。

    回归：用户点开一个几百 MB 的日志时，旧实现先把整份内容读进 Python 字符串
    （str 还要再涨 2~4 倍），再判「太大」丢掉 —— 峰值内存与耗时全白付，极端
    情况直接 MemoryError 把程序带走。
    """
    records = []

    def fake_run(cmd, **kw):
        records.append(list(cmd))
        if "head" in cmd:
            return type("R", (), {"stdout": "x" * 11, "stderr": "",
                                  "returncode": 0})()
        if "pull" in cmd:
            return type("R", (), {"stdout": "", "stderr": "",
                                  "returncode": 1})()
        return type("R", (), {"stdout": "x" * 999, "stderr": "",
                              "returncode": 0})()

    monkeypatch.setattr(fs_mod.subprocess, "run", fake_run)
    svc = FileService()
    svc.view("SERIAL", "/sdcard/huge.log", max_inline_bytes=10)
    head = [c for c in records if "head" in c]
    assert head, "应优先用 head -c 有界读取"
    at = head[0].index("head")
    assert head[0][at:at + 3] == ["head", "-c", "11"], (
        "要让设备端只给「上限 + 1」字节：%r" % (head[0],))
    assert not [c for c in records if "cat" in c], "head 成功时不该再 cat 全量"


def test_view_falls_back_to_cat_when_head_unsupported(monkeypatch):
    """老 ROM 的 head 不认 -c 时退回整段 cat（旧行为），功能不能丢。"""
    records = []

    def fake_run(cmd, **kw):
        records.append(list(cmd))
        if "head" in cmd:
            return type("R", (), {"stdout": "", "stderr": "head: invalid option -- c",
                                  "returncode": 255})()
        if "cat" in cmd:
            return type("R", (), {"stdout": "hello", "stderr": "",
                                  "returncode": 0})()
        return type("R", (), {"stdout": "", "stderr": "", "returncode": 1})()

    monkeypatch.setattr(fs_mod.subprocess, "run", fake_run)
    svc = FileService()
    res, err = svc.view("SERIAL", "/sdcard/a.txt", max_inline_bytes=1024)
    assert err is None and res["text"] == "hello"
    assert [c for c in records if "cat" in c], "head 失败应退回 cat"


def test_view_returns_non_empty_reason_when_pull_fails(monkeypatch):
    """head 成功取回内容但超限、随后的 pull 失败：原因不能是空串。

    旧实现 `return None, _err_text(r, "查看失败")`，而 r 是**成功**的 head
    （rc=0），_err_text 的契约是「成功恒返回空串」—— 于是 view 返回
    (None, "")。上层 _do_file_view 用「err 是否为空」判断成败，空串让它把
    res=None 当成成功去 .get()，用户看到的是：

        查看失败 /sdcard/big.log: 'NoneType' object has no attribute 'get'

    与真正的原因（pull 失败 / 没有权限）毫无关系。
    """
    def fake_run(cmd, **kw):
        if "head" in cmd:
            return type("R", (), {"stdout": "x" * 64, "stderr": "",
                                  "returncode": 0})()
        if "pull" in cmd:
            return type("R", (), {"stdout": "adb: error: failed to stat remote "
                                            "object /sdcard/big.log: No such file",
                                  "stderr": "", "returncode": 1})()
        return type("R", (), {"stdout": "", "stderr": "", "returncode": 1})()

    monkeypatch.setattr(fs_mod.subprocess, "run", fake_run)
    svc = FileService()
    res, err = svc.view("SERIAL", "/sdcard/big.log", max_inline_bytes=8)
    assert res is None
    assert err, "失败必须带原因，空串会被上层当成成功"
    assert "No such file" in err, err


def test_view_explains_directory_target_instead_of_returning_empty_reason(monkeypatch):
    """点开一个目录：pull「成功」但落地的是目录，原因同样不能为空。

    adb pull 对目录会整棵拉下来，落地不是文件。旧实现在这种分支给出空串，
    上层同样会去解包 None。
    """
    import os as _os

    def fake_run(cmd, **kw):
        if "head" in cmd:
            return type("R", (), {"stdout": "x" * 64, "stderr": "",
                                  "returncode": 0})()
        if "pull" in cmd:
            _os.makedirs(cmd[-1], exist_ok=True)     # 落地成目录
            return type("R", (), {"stdout": "", "stderr": "", "returncode": 0})()
        return type("R", (), {"stdout": "", "stderr": "", "returncode": 1})()

    monkeypatch.setattr(fs_mod.subprocess, "run", fake_run)
    svc = FileService()
    res, err = svc.view("SERIAL", "/sdcard/somedir", max_inline_bytes=8)
    assert res is None
    assert err and "目录" in err, err

def test_list_dir_empty_dir_does_not_retry(monkeypatch):
    """空目录不该再跑一次 ls -l：那是每次进入空目录都白等一个 adb 往返。

    只有 `total 0` 一行时，结果必然是空，兜底没有信息增量（100~300ms 的
    可感延迟换一个空列表）。旧实现无条件兜底。
    """
    records = []
    monkeypatch.setattr(fs_mod.subprocess, "run",
                        _make_fake_run(records, "total 0\n"))
    svc = FileService()
    items, err = svc.list_dir("SERIAL", "/empty")
    assert err is None
    assert items == []
    assert len(records) == 1, "空目录不该重试，实际调用了 %d 次" % len(records)


def test_parse_push_progress_picks_last_percentage():
    """adb push 进度用 [ NN%] 表示，且以 \\r 覆盖刷新：一段输出里会有多个，
    取最后一个才是当前进度；必须忽略不带方括号的百分比（错误文案里的 100%）。"""
    parse = fs_mod._parse_push_progress
    assert parse("[ 45%] /sdcard/a\r[ 67%] /sdcard/a\r") == 67
    assert parse("[100%] /sdcard/a") == 100
    assert parse("  [  1%] x\n[ 10%] x") == 10
    assert parse("CPU 100% memory 50%") is None
    assert parse("") is None
    assert parse("adb: error: failed") is None
    # 部分 adb 版本/平台输出圆括号百分比（实测 Transferring: x/y (NN%)）
    assert parse("Transferring: 11468800/38632644 (29%)\r") == 29
    assert parse("[ 10%] a\rTransferring: x/y (67%)\r") == 67
    assert parse("Transferring: x/y (45%)\r[ 88%] a\r") == 88


def test_upload_stream_reports_progress_and_succeeds(monkeypatch):
    """upload_stream 把 adb push 的每个进度百分比回调出来，完成后回调 100。

    返回契约与 upload 一致：(ok, err)。用假 Popen 喂一段典型进度输出，
    不启动真 adb / 真线程也能验证顺序。"""
    import io

    class FakeProc:
        def __init__(self):
            self.stdout = io.StringIO(
                "[ 10%] /sdcard/a\r[ 50%] /sdcard/a\r[100%] /sdcard/a\r"
                "/sdcard/a: 1 file pushed, 0 skipped. 2.0 MB/s (10 bytes in 0.005s)\n")
            self.returncode = 0

        def wait(self, timeout=None):
            return self.returncode

    monkeypatch.setattr(fs_mod.subprocess, "Popen", lambda *a, **kw: FakeProc())
    seen = []
    ok, err = fs_mod.FileService().upload_stream(
        "S", "/tmp/a", "/sdcard/a", progress=seen.append)
    assert (ok, err) == (True, "")
    assert 10 in seen and 50 in seen, seen
    assert seen[-1] == 100, seen


def test_upload_stream_failure_returns_reason(monkeypatch):
    """进度流失败时仍给出非空原因，不能只回调进度然后静默失败。"""
    import io

    class FakeProc:
        def __init__(self):
            self.stdout = io.StringIO(
                "[ 10%] /sdcard/a\radb: error: failed to copy: remote offline\n")
            self.returncode = 1

        def wait(self, timeout=None):
            return self.returncode

    monkeypatch.setattr(fs_mod.subprocess, "Popen", lambda *a, **kw: FakeProc())
    seen = []
    ok, err = fs_mod.FileService().upload_stream(
        "S", "/tmp/a", "/sdcard/a", progress=seen.append)
    assert ok is False
    assert "remote offline" in err, err
    assert seen and seen[-1] != 100, "失败不该回调 100% 完成"


def test_list_dir_reports_unparsable_output_instead_of_empty(monkeypatch):
    """有内容却解析不出来时必须报原因，不能画成「空目录」。

    回归：两次 ls 都解析为空时直接返回 ([], None)，前端据此渲染「此目录为空」——
    而目录里其实有文件（该 ROM 的列布局不同 / 输出被截断）。用户以为文件没了。
    """
    weird = ("drwxr-xr-x 2 root root 4096 data\n"
             "-rw-r--r-- 1 root root 12 f\n")   # 缺日期列 -> 逐行都解析失败
    records = []
    monkeypatch.setattr(fs_mod.subprocess, "run",
                        _make_fake_run(records, weird))
    svc = FileService()
    items, err = svc.list_dir("SERIAL", "/weird")
    assert items is None, "解析失败不能当作空目录返回"
    assert err and "无法解析" in err, err


def test_push_timeout_scales_with_file_size():
    """push 的总超时上界要随文件大小放大：固定 120s 会把大文件传到一半就杀掉。

    回归：1 GB 走无线 adb（约 2 MB/s）需要 8 分钟，旧实现到点就 kill，界面报
    「上传超时」，用户以为文件传不动，其实只是被自己设的上界误杀。
    """
    assert fs_mod.push_timeout_for(0) == 120, "取不到大小要退回 120s 下限"
    assert fs_mod.push_timeout_for(None) == 120
    assert fs_mod.push_timeout_for("oops") == 120, "脏值不能崩"
    assert fs_mod.push_timeout_for(1024) == 120, "小文件保持 120s"
    big = fs_mod.push_timeout_for(1024 ** 3)          # 1 GB
    assert big >= 8 * 60, big                          # 至少容得下 1 MB/s 的 1 GB
    assert fs_mod.push_timeout_for(10 ** 12) > big, "更大的文件上界要更大"


def test_upload_stream_gives_up_when_output_goes_silent(monkeypatch):
    """管道彻底安静（设备掉线）时要按「空闲」判定卡住，而不是等满总超时。

    回归：read(1) 卡在管道上不会自己返回，旧的固定 join(timeout) 只有总超时
    到点才收尾；大文件的上界被放宽到十几分钟后，一次掉线就让队列项转十几分钟。
    """
    import threading
    import time as _time

    released = threading.Event()

    class _SilentStream:
        """永远不吐字节的管道：read 一直阻塞，直到进程被 kill。"""
        def read(self, n=1):
            released.wait(5)
            return ""

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class SilentProc:
        def __init__(self):
            self.stdout = _SilentStream()
            self.returncode = -9
            self.killed = False

        def kill(self):
            self.killed = True
            released.set()

        def wait(self, timeout=None):
            return self.returncode

    monkeypatch.setattr(fs_mod.subprocess, "Popen", lambda *a, **kw: SilentProc())
    started = _time.monotonic()
    ok, err = FileService().upload_stream(
        "S", "/tmp/a", "/sdcard/a", timeout=30, idle_timeout=0.1)
    cost = _time.monotonic() - started
    assert ok is False
    assert "卡住" in err, err
    assert cost < 5, f"空闲超时应当很快判定，实际用了 {cost:.1f}s"


def test_upload_stream_slow_but_alive_is_not_killed(monkeypatch):
    """传输慢但一直有输出（大文件正常情形）绝不能被空闲超时误杀。

    这是「上传到 60% 突然报失败」的防线：判据必须是「多久没动静」，
    而不是「总共花了多久」。
    """
    class SlowProc:
        """每读一个字符都要 20ms 的管道 —— 比 idle_timeout 慢，但一直有进展。"""
        def __init__(self):
            self._src = "[ 30%] /sdcard/a\r[100%] /sdcard/a\r"
            self._pos = 0
            self.returncode = 0
            self.stdout = self

        def read(self, n=1):
            import time as _time
            if self._pos >= len(self._src):
                return ""
            _time.sleep(0.02)      # 远大于 idle_timeout=0.05 的单次间隔累积
            ch = self._src[self._pos]
            self._pos += 1
            return ch

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(fs_mod.subprocess, "Popen", lambda *a, **kw: SlowProc())
    seen = []
    ok, err = FileService().upload_stream(
        "S", "/tmp/a", "/sdcard/a", progress=seen.append,
        timeout=60, idle_timeout=0.05)
    assert (ok, err) == (True, ""), err
    assert seen[-1] == 100, seen



def test_upload_stream_forces_progress_flag(monkeypatch):
    """upload_stream 必须给 adb push 加 -p，否则较新版 adb 在输出被管道捕获时
    不打印 [ NN%]，真机全程跑马灯、结束才补一个 100%（测试里的假 adb 手工拼了
    百分比，所以旧实现下这条会失败）。"""
    import io

    captured = {}

    class FakeProc:
        def __init__(self, argv, **kw):
            captured["argv"] = list(argv)
            self.stdout = io.StringIO("[ 50%] /sdcard/a\r[100%] /sdcard/a\r")
            self.returncode = 0

        def wait(self, timeout=None):
            return self.returncode

    monkeypatch.setattr(fs_mod.subprocess, "Popen", lambda *a, **kw: FakeProc(*a, **kw))
    ok, err = fs_mod.FileService().upload_stream("S", "/tmp/a", "/sdcard/a")
    assert (ok, err) == (True, ""), err
    argv = captured["argv"]
    assert "-p" in argv, f"adb push 未带 -p，真机不会输出百分比：{argv}"
    i_p, i_push = argv.index("-p"), argv.index("push")
    assert i_push < i_p < len(argv) - 2, f"-p 须在 push 之后、本地路径之前：{argv}"


def test_upload_stream_falls_back_without_p_on_old_adb(monkeypatch):
    """老版本 adb（<1.0.32）不认 -p 会立即报 unknown option；此时应自动去掉
    -p 重试一次——宁可没有百分比，也不能让本来能传成的大文件直接失败。"""
    import io

    calls = []

    class FakeProc:
        def __init__(self, argv, **kw):
            calls.append(list(argv))
            old_adb = "-p" in argv
            self.stdout = io.StringIO(
                "error: unknown option 'p'\n" if old_adb
                else "[100%] /sdcard/a\r")
            self.returncode = 1 if old_adb else 0

        def wait(self, timeout=None):
            return self.returncode

    monkeypatch.setattr(fs_mod.subprocess, "Popen", lambda *a, **kw: FakeProc(*a, **kw))
    seen = []
    ok, err = fs_mod.FileService().upload_stream(
        "S", "/tmp/a", "/sdcard/a", progress=seen.append)
    assert (ok, err) == (True, ""), err
    assert len(calls) == 2, f"应带 -p 试一次、失败后去掉 -p 再试一次：{calls}"
    assert "-p" in calls[0] and "-p" not in calls[1], calls
    assert seen and seen[-1] == 100, seen


def test_upload_stream_no_fallback_on_real_failure(monkeypatch):
    """真正的传输失败（设备掉线）不能误判成「老 adb 不认 -p」而去重试——
    那会把一次失败变成两次、还可能造成设备上重复落盘。"""
    import io

    calls = []

    class FakeProc:
        def __init__(self, argv, **kw):
            calls.append(list(argv))
            self.stdout = io.StringIO("adb: error: failed to copy: remote offline\n")
            self.returncode = 1

        def wait(self, timeout=None):
            return self.returncode

    monkeypatch.setattr(fs_mod.subprocess, "Popen", lambda *a, **kw: FakeProc(*a, **kw))
    ok, err = fs_mod.FileService().upload_stream("S", "/tmp/a", "/sdcard/a")
    assert ok is False
    assert "remote offline" in err, err
    assert len(calls) == 1, f"真实失败不该重试：{calls}"




# ---------------------------------------------------------------- 传输取消 / 下载进度

def test_cancel_transfer_kills_proc_and_removes_partial_file():
    """取消传输：杀掉登记的 adb 进程 + 删除半成品落地文件，且幂等。"""
    import io

    class FakeProc:
        def __init__(self):
            self.killed = False
            self.stdout = io.StringIO("")

        def poll(self):
            return None if not self.killed else -9

        def kill(self):
            self.killed = True

    svc = FileService()
    proc = FakeProc()
    partial = os.path.join(tempfile.gettempdir(), "adc_cancel_test_partial.bin")
    with open(partial, "wb") as f:
        f.write(b"half")

    svc.register_transfer("t1", proc, (partial,))
    assert svc.is_cancelled("t1") is False
    assert svc.cancel_transfer("t1") is True
    assert proc.killed is True, "必须杀掉 adb 进程"
    assert not os.path.exists(partial), "必须删掉半成品文件"
    assert svc.is_cancelled("t1") is True, "取消标记要留住，供 worker 据此推 cancelled"
    assert svc.cancel_transfer("t1") is False, "重复取消不该报错（返回未找到）"


def test_register_transfer_clears_stale_cancel_on_retry():
    """同一 task_id 重试（「重试」按钮）：注册时清掉上次的取消标记。"""
    svc = FileService()
    svc._cancelled.add("t2")
    svc.register_transfer("t2", object(), ())
    assert svc.is_cancelled("t2") is False


def test_upload_stream_stops_promptly_when_cancelled(monkeypatch):
    """上传中取消：循环检测到 cancelled 立刻退出，不误报「卡住/超时」。"""
    class P:
        """持续输出的 adb 进程；被 kill 后 stdout 立刻给 EOF。

        真实 adb 被 kill 时 stdout 管道关闭、read 返回空。mock 必须照做 ——
        否则 daemon 读线程永远读下去，即便本用例通过也会拖垮整个 pytest
        session（表现为全量跑到一半突然卡死）。
        """
        def __init__(self):
            self.returncode = 0
            self.killed = False
            self.stdout = self

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n):
            return "" if self.killed else "x"

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            self.killed = True

        def poll(self):
            return None

    made = []

    def make_proc(*a, **kw):
        p = P()
        made.append(p)
        return p

    monkeypatch.setattr(fs_mod.subprocess, "Popen", make_proc)
    svc = FileService()
    # 调用前先放好取消标记，再让 register 不清标记（模拟「传输已开始后才取消」）。
    svc._cancelled.add("t3")

    def register_no_clear(tid, proc, cleanup=()):
        with svc._transfer_lock:
            svc._transfers[tid] = {"proc": proc, "cleanup": tuple(cleanup)}
    svc.register_transfer = register_no_clear

    ok, err = svc.upload_stream("S", "/tmp/a", "/sdcard/a", task_id="t3",
                                timeout=60, idle_timeout=60)
    assert ok is False
    assert "取消" in err, err
    # 进程确实被 kill；其 read 从此返回 EOF，读线程会自然收尾，不再空转。
    assert made and made[0].killed is True

def test_download_stream_reports_progress(monkeypatch, tmp_path):
    """download_stream 用 -p 输出解析百分比并回调，成功后落地文件。"""
    import io

    landed = str(tmp_path / "a.bin")

    class FakeProc:
        def __init__(self, argv, **kw):
            assert "-p" in argv, "下载也要带 -p 才有百分比"
            self.stdout = io.StringIO("[ 30%] a.bin\r[100%] a.bin\r")
            self.returncode = 0
            # 假装在 pull 过程中落地了文件
            with open(landed, "wb") as f:
                f.write(b"data")

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            pass

        def poll(self):
            return 0

    monkeypatch.setattr(fs_mod.subprocess, "Popen", lambda *a, **kw: FakeProc(*a, **kw))
    svc = FileService()
    seen = []
    path, err = svc.download_stream(
        "S", "/sdcard/a.bin", str(tmp_path), progress=seen.append, task_id="d1")
    assert err is None and path, (path, err)
    assert 30 in seen and seen[-1] == 100, seen


def test_upload_stream_progress_from_file_size_when_adb_buffers(monkeypatch):
    """adb 把进度缓冲住/不吐百分比时，靠目标文件大小给出真实进度。

    回归：真机上「等半天直接跳 100%」——文本进度回调一次都不触发，只剩收尾
    补的 100。这里让 stdout 只读到一个不带百分比的字符就一直阻塞（模拟 adb
    缓冲），主线程靠文件大小探测给出 30%，验证中间百分比确实被回调出来。

    用「隔离的假时钟」而不是真实等待，才能让这个 1 秒探测门槛的用例在慢速 CI
    上也稳定：
      * 只把 fs_mod 命名空间里的 time 名字换成假对象——file_service 用假时钟，
        而 threading / pytest 仍用真 time 模块，互不污染。绝不 setattr 到 time
        模块本身（那是进程级单例，会改掉全局计时导致 CI flaky）。
      * 假进程的「放行」事件按实例隔离，且只放行 upload_stream 真正登记的那个
        进程。全量跑时别的用例残留的后台线程会经被 patch 的全局 subprocess.Popen
        拿到本用例的假进程类实例；若放行事件在实例间共享，残留线程 kill 掉它拿
        到的实例就会误放行本用例的读线程，读线程提前 EOF 后主循环在 poll_size
        之前就 break，表现为偶发的「大小探测从未触发」。实例隔离后，残留线程
        只能放掉它自己那个无关实例，碰不到本用例的上传进程。
      * probed 只在「大小探测真的执行」时置位，不会被收尾补的 100 误触发。
    """
    import threading

    class FakeClock:
        def __init__(self):
            self.now = 1000.0

        def monotonic(self):
            return self.now

    clock = FakeClock()
    monkeypatch.setattr(fs_mod, "time", clock)   # 仅替换被测模块的 time 名字
    probed = threading.Event()

    class StuckProc:
        def __init__(self):
            self.stdout = self
            self.returncode = 0
            self._n = 0
            # 放行事件按实例隔离：残留线程拿到的同款实例 kill 掉的只是它自己，
            # 不会影响本用例上传进程读线程的阻塞/放行。
            self.release = threading.Event()

        def read(self, n=1):
            self._n += 1
            if self._n == 1:
                return "pushing"      # 没有 [ NN%] 也没有 (NN%)
            clock.now += 2.0          # 模拟「2 秒没有任何输出」→ 跨过探测门槛
            self.release.wait(20)     # 用真 Event 等待，不受假时钟影响
            return ""

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            self.release.set()        # 只放行本实例，不碰别的假进程

        def poll(self):
            return None

    made = []

    def make_proc(*a, **kw):
        p = StuckProc()
        made.append(p)
        return p

    monkeypatch.setattr(fs_mod.subprocess, "Popen", make_proc)
    svc = FileService()

    def fake_size(serial, p):
        probed.set()                  # 标记：大小探测真的执行了
        # 只放行 upload_stream 登记的那个进程（made[0] 是本用例自己创建的）。
        # 即便残留线程又造了同款实例，它们各自的 release 互不相干。
        if made:
            made[0].release.set()
        return 300

    monkeypatch.setattr(svc, "_remote_file_size", fake_size)
    monkeypatch.setattr(fs_mod, "path_getsize", lambda p: 1000)

    seen = []
    ok, err = svc.upload_stream(
        "S", "/tmp/a.bin", "/sdcard/a.bin", progress=seen.append,
        timeout=60, idle_timeout=30, task_id="sz1")
    assert (ok, err) == (True, ""), err
    # probed 只由 fake_size 置位，收尾补的 100 不会碰到它——断言稳定不 flaky。
    assert probed.is_set(), "大小探测从未触发"
    assert 30 in seen, seen           # 文件大小 300/1000 -> 30%
    assert seen[-1] == 100, seen      # 收尾补 100
