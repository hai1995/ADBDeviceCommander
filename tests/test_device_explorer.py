"""测试 core.constants 中的纯函数（路径拼接 / 大小格式化 / ls 解析）。

这些逻辑原属 legacy Tk 版的 posix_join / fmt_size / parse_ls_output，
现已统一收敛到 core.constants，供 Web 版与任意前端复用。"""


from core.constants import parse_ls_output, fmt_size, posix_join


LS_SAMPLE = (
    "drwxr-xr-x 2 root root  4096 2024-01-01 12:00 data\n"
    "drwxr-xr-x 3 root root  4096 2024-01-01 12:00 system\n"
    "-rw-r--r-- 1 root root   123 2024-01-01 12:01 build.prop\n"
    "lrwxrwxrwx 1 root root     7 2024-01-01 12:00 hw -> /system/hw\n"
    "total 1234\n"
    "drwxr-xr-x 2 root root  4096 Jan  1 12:00 sdcard\n"
)


def test_posix_join():
    assert posix_join("/", "data") == "/data"
    assert posix_join("/data", "local") == "/data/local"
    assert posix_join("/data/", "/local") == "/data/local"
    assert posix_join("/", "/") == "/"


def test_fmt_size():
    assert fmt_size(0) == "0 B"
    assert fmt_size(512) == "512 B"
    assert fmt_size(1024) == "1 KB"
    assert fmt_size(1536) == "1.5 KB"
    assert fmt_size(1024 * 1024) == "1 MB"
    assert fmt_size(-1) == ""


def test_parse_ls_output_long_iso():
    ents = parse_ls_output(LS_SAMPLE)
    names = [e["name"] for e in ents]
    assert "data" in names
    assert "system" in names
    assert "build.prop" in names
    assert "hw" in names
    assert "sdcard" in names
    d = next(e for e in ents if e["name"] == "data")
    assert d["is_dir"] and d["perm"] == "drwxr-xr-x" and d["size"] == 4096
    f = next(e for e in ents if e["name"] == "build.prop")
    assert not f["is_dir"] and f["size"] == 123
    ln = next(e for e in ents if e["name"] == "hw")
    assert ln["is_link"] and ln["target"] == "/system/hw"


# Android Toybox / BusyBox 的 ls -la 默认输出（无 --time-style），格式为 "Mon D HH:MM"
TOYBOX_SAMPLE = (
    "drwxr-xr-x 2 root root     4096 Sep  4 10:12 data\n"
    "drwxr-xr-x 3 root root     4096 Sep  4 10:12 system\n"
    "-rw-r--r-- 1 root root      123 Sep  4 10:13 build.prop\n"
    "lrwxrwxrwx 1 root root       7 Sep  4 10:12 hw -> /system/hw\n"
    "drwxrwx--- 4 root sdcard_rw 4096 Sep  4 11:00 Android\n"
    "total 80\n"
)


def test_parse_ls_output_toybox_default():
    """修复回归：原 --time-style=long-iso 在 Toybox 不支持导致 list_dir 失败。
    改用原生 ls -la 后，解析器必须正确处理默认的 "Mon D HH:MM" 格式。"""
    ents = parse_ls_output(TOYBOX_SAMPLE)
    names = [e["name"] for e in ents]
    assert "data" in names and "system" in names and "build.prop" in names
    assert "hw" in names
    d = next(e for e in ents if e["name"] == "data")
    assert d["is_dir"] and d["perm"] == "drwxr-xr-x" and d["size"] == 4096
    f = next(e for e in ents if e["name"] == "build.prop")
    assert not f["is_dir"] and f["size"] == 123
    ln = next(e for e in ents if e["name"] == "hw")
    assert ln["is_link"] and ln["target"] == "/system/hw"
