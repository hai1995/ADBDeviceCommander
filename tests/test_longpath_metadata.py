# -*- coding: utf-8 -*-
r"""门禁：Windows 长路径（>260 字符）下，本地文件的**元数据查询**也必须可靠。

背景
----
第九十轮给「写」这一侧铺开了 ``core.longpath``（open 写 / os.makedirs /
os.replace / zipfile），但**读**这一侧当时没一起改：

  * ``os.path.exists()`` / ``os.path.getsize()`` / ``os.path.isfile()`` 在
    Windows 上同样受 MAX_PATH 限制 —— 超过 260 字符时它们**不报错，只是返回
    False / 0**；
  * ``open(path, "rb")`` 读超长路径直接抛 OSError。

于是出现了很难查的「半修」状态：文件**写得进去**（写侧有前缀），却**查不到**
（查侧没前缀）。后果是「东西莫名没了 / 打包少了内容」，与「路径太长」毫无关联：

  * ``unique_path()`` 认为位置是空的 → **覆盖用户上一份产物**；
  * ``_zip_paths()`` 认为文件不存在 → **打包出的 zip 少了文件**，界面照样弹
    「✓ 已打包」；
  * ``join_segments()`` 认为分段不存在 → **合并直接失败**，报的是「都缺 moov 头」；
  * ``_wav_ok()`` 认为 wav 不存在 → **刚录好的音频被判为无效并丢弃**。

怎么在 Linux 上验证
-------------------
Windows 的关键行为可以精确建模：**超过 260 字符的路径，只有带 ``\\?\`` 前缀
才够得着**；不带前缀时 ``os.path.exists`` 不抛异常，只是返回 False。

于是本文件用一个「虚拟文件系统」把 CI 变成「小 Windows」：

  * ``core.longpath.long_path`` → 换成 Windows 模拟版：Windows 风格的路径
    （有盘符 / 反斜杠）按 ``win_long_path`` 加前缀；纯 POSIX 路径原样返回
    （否则连 Linux 上的普通文件都访问不到，测试本身就跑不起来）。
  * ``os.path.exists`` / ``isfile`` / ``getsize`` → 换成模拟 Win32 的版本：
    带前缀的路径还原后查**虚拟映射表**（映射到真实的 tmp 文件）；不带前缀
    且超过 260 字符的一律「不存在」。

这样各条链路（unique_path / _zip_paths / _wav_ok）的行为就能在 CI 上真实
复现，不必等到 Windows 机器上才发现。
"""
import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import longpath


_PREFIX = "\\\\?\\"


def _is_windows_style(s: str) -> bool:
    """这个路径像 Windows 路径吗？（有盘符 / 有反斜杠）"""
    return "\\" in s or (len(s) > 1 and s[1] == ":")


class _WinFs:
    """模拟 Win32 的文件可见性：长路径只有带 ``\\?\\`` 前缀才够得着。

    ``vmap`` 把「Windows 风格的路径」映射到真实的本地文件 —— 这样一条超长的
    Windows 路径，在 Linux 上也能真的被 exists / isfile / getsize 命中。
    """

    def __init__(self):
        self.vmap = {}          # windows 路径（无前缀） -> 真实本地文件
        self._real_exists = os.path.exists
        self._real_isfile = os.path.isfile
        self._real_getsize = os.path.getsize

    # -- 内部：把实参解析成 (真实本地路径 或 None, 是否带前缀) --
    def _resolve(self, p):
        s = str(p)
        had_prefix = s.startswith(_PREFIX)
        if had_prefix:
            s = s[len(_PREFIX):]
            if s.startswith("UNC\\"):
                s = "\\\\" + s[4:]
        # 顺序很重要：**先**判「无前缀且超长 → 够不着」，**再**查映射表。
        # 反过来的话，无前缀的超长路径也会在映射表里命中 —— 那就等于没有
        # 模拟 Win32 的限制，回归测试反而会假绿。
        if not had_prefix and len(s) >= 260:
            return None, had_prefix
        if s in self.vmap:
            return self.vmap[s], had_prefix
        return s, had_prefix

    def exists(self, p):
        target, had = self._resolve(p)
        if target is None:
            return False
        return self._real_exists(target)

    def exists_raw(self, p):
        """不带前缀、且超长 → 够不着（Win32 的真实行为）。"""
        s = str(p)
        if not s.startswith(_PREFIX) and len(s) >= 260:
            return False
        return self.exists(p)

    def isfile(self, p):
        target, had = self._resolve(p)
        if target is None:
            return False
        return self._real_isfile(target)

    def getsize(self, p):
        target, had = self._resolve(p)
        if target is None:
            raise OSError(206, "文件名、目录名或卷标语法不正确")
        return self._real_getsize(target)

    def long_path(self, path):
        """Windows 模拟版的 long_path：Windows 风格才加前缀。"""
        if path is None:
            return path
        s = str(path)
        if not s:
            return path
        if not _is_windows_style(s):
            return path
        return longpath.win_long_path(s)


@pytest.fixture
def win_fs(monkeypatch):
    """把当前进程变成「小 Windows」；返回 _WinFs 实例供测试注册虚拟文件。

    注意：`from core.longpath import long_path` 是**按值导入**的 ——
    只改 core.longpath 模块里的那个名字，已经导入各模块的那一份不会跟着变。
    所以这里把所有已导入模块里指向原始 long_path 的地方一并替换掉，
    模拟才是完整的。
    """
    fs = _WinFs()
    original = longpath.long_path

    # 1) core.longpath 模块自身（path_exists 等在模块内部按全局名查找）
    monkeypatch.setattr(longpath, "long_path", fs.long_path)
    # 2) 各消费模块里按值导入的那一份
    for mod in list(sys.modules.values()):
        if mod is None or not hasattr(mod, "__dict__"):
            continue
        try:
            if mod.__dict__.get("long_path") is original:
                monkeypatch.setattr(mod, "long_path", fs.long_path)
        except (TypeError, AttributeError):
            continue

    monkeypatch.setattr(os.path, "exists", fs.exists)
    monkeypatch.setattr(os.path, "isfile", fs.isfile)
    monkeypatch.setattr(os.path, "getsize", fs.getsize)
    # open 也要能打开「带前缀的超长路径」→ 还原成真实文件
    real_open = open

    def fake_open(file, *a, **k):
        if isinstance(file, str):
            target, had = fs._resolve(file)
            if had and target is not None:
                file = target
        return real_open(file, *a, **k)

    monkeypatch.setattr("builtins.open", fake_open)
    return fs


def _long_win_dir() -> str:
    """一个「长度超过 260 字符」的 Windows 目录路径（不要求真的存在）。"""
    return ("D:\\工作\\2026\\客户A\\车机项目\\第二期\\录屏\\"
            + "很深的归档目录\\" * 32)


def _win_join(directory: str, name: str) -> str:
    """按 **Windows** 语义拼路径。

    不能用 os.path.join：它在 Linux 上用 "/" 分隔，拼出来的
    ``D:\\...\\目录/文件.txt`` 里混了两种分隔符，与真实 Windows 路径不一致
    （也会让 ntpath 的规范化产生意料之外的结果）。
    """
    return directory.rstrip("\\") + "\\" + name


# --------------------------------------------------------------------------- #
# 基础设施
# --------------------------------------------------------------------------- #
def test_path_helpers_query_the_prefixed_form(win_fs, tmp_path):
    """path_exists / path_isfile / path_getsize 必须查**带前缀**的那一份。

    这是本轮新加的基础设施：把「加前缀」集中起来，免得每个调用点各写一遍
    long_path(...)，也免得漏。
    """
    real = tmp_path / "a.bin"
    real.write_bytes(b"x" * 100)
    assert longpath.path_exists(str(real)) is True
    assert longpath.path_isfile(str(real)) is True
    assert longpath.path_getsize(str(real)) == 100
    # 不存在的路径 → False / 0，而不是抛异常
    assert longpath.path_exists(str(real) + ".missing") is False
    assert longpath.path_getsize(str(real) + ".missing") == 0


def test_path_remove_reports_failure_instead_of_raising(win_fs, tmp_path):
    """path_remove：删不掉时返回 False，不抛异常（调用点多半静默吞异常）。"""
    missing = tmp_path / "nope.bin"
    assert longpath.path_remove(str(missing)) is False
    real = tmp_path / "yes.bin"
    real.write_bytes(b"x")
    assert longpath.path_remove(str(real)) is True
    assert not real.exists()


# --------------------------------------------------------------------------- #
# 回归：修复前会被这几条抓住
# --------------------------------------------------------------------------- #
def test_unique_path_does_not_overwrite_a_long_existing_file(win_fs, tmp_path):
    """回归：超长路径下 unique_path 仍能看出「位置被占」，不覆盖上一份产物。

    unique_path 存在的唯一目的就是别覆盖用户已经拿到的产物。旧实现用
    os.path.exists 判断，在超长路径上恒为 False → 认为位置是空的 → 返回同一个
    路径 → 下一份产物把上一份**覆盖掉**（用户手上那份悄悄变成新内容）。
    """
    from core import constants

    p = _win_join(_long_win_dir(),
                  "logcat_192.168.1.5:5555_20261112_120000.txt")
    assert len(p) >= 260, "测试样本必须真的超长"

    # 带前缀的够得着（这正是 Windows 上「长路径只有 \?\ 前缀才够得着」的
    # 真实行为），无前缀的够不着 —— 后者正是旧实现会踩到的坑。
    real = tmp_path / "logcat.txt"
    real.write_text("x")
    win_fs.vmap[p] = str(real)
    assert win_fs.exists(longpath.win_long_path(p)) is True
    assert win_fs.exists_raw(p) is False

    # 场景：这份产物已经落盘（vmap 里有它），用户紧接着又抓了一次 ——
    # 新的一份必须换个名字，绝不能覆盖用户手上那份。
    got = constants.unique_path(p)
    assert got != p, (
        "超长路径下 unique_path 认为位置一直是空的 → 会覆盖用户上一份产物")
    assert got.endswith("_2.txt"), got


def test_zip_paths_keeps_long_files(win_fs, tmp_path, monkeypatch):
    """回归：超长路径下的文件仍然会被打进 zip（不被静默跳过）。

    旧实现用 os.path.exists / os.path.isfile 过滤，超长路径上恒为 False →
    文件被跳过 → 压缩包少了内容，而界面照样弹「✓ 已打包」。
    """
    from backend.controllers import record as rec_mod

    # 造一个「超长路径」的文件条目：真实文件放在 tmp 下，但**对外报告的路径**
    # 是超长的那个（模拟用户把保存目录设成多层归档目录）。
    real = tmp_path / "record.mp4"
    real.write_bytes(b"data")
    fake_long = _win_join(_long_win_dir(), "record.mp4")
    assert len(fake_long) >= 260
    win_fs.vmap[fake_long] = str(real)

    # zip 的 write 会拿到 long_path 之后的路径 → 映射回真实文件。
    # 注意：必须**先**把真的 ZipFile 类抓下来 —— 下面 monkeypatch 之后
    # rec_mod.zipfile.ZipFile 就是 _FakeZip 自己了。
    real_zip_cls = rec_mod.zipfile.ZipFile
    zipped = []

    class _FakeZip:
        """包一层真实 ZipFile，只把 write 的入参记录下来。

        __enter__ 必须返回 **自己**（不是内部那个真 ZipFile），否则 with 块里
        拿到的就是真对象，write 根本走不到这里。
        """

        def __init__(self, *a, **k):
            self._z = real_zip_cls(*a, **k)

        def __enter__(self):
            self._z.__enter__()
            return self

        def __exit__(self, *a):
            # 关闭真正的 ZipFile（不 close → 中央目录不写，zip 根本打不开）
            return self._z.__exit__(*a)

        def close(self):
            self._z.close()

        def write(self, src, *a, **k):
            zipped.append(src)
            # src 是 long_path 之后的路径（带前缀）→ 还原成真实文件再交给
            # 真 ZipFile（Linux 上没有长路径支持，真 ZipFile 会直接报
            # ENAMETOOLONG —— 那是模拟环境的限制，不是被测代码的问题）。
            target, _had = win_fs._resolve(src)
            assert target is not None, "写 zip 时拿到的路径够不着：%r" % src
            return self._z.write(target, *a, **k)

    # 只替换 zipfile.ZipFile 这一个属性（模块本身还要提供 ZIP_STORED 等常量）
    monkeypatch.setattr(rec_mod.zipfile, "ZipFile", _FakeZip)
    out = rec_mod.RecordMixin._zip_paths([fake_long], str(tmp_path / "out.zip"))
    assert zipped, "超长路径的文件被静默跳过了（压缩包会缺内容）"
    assert out


def test_wav_ok_accepts_a_long_path_file(win_fs, tmp_path):
    """回归：超长路径下的 wav 仍被认成「可用」（不会被当成空录音丢弃）。

    _wav_ok 返回 False 时，MicRecorder.stop 与 DeviceAudioCapture.stop 会把
    **刚录好的音频**删掉并回 None，用户只看到「未录到声音」。
    """
    from backend import audio_service

    real = tmp_path / "mic.wav"
    data = b"\x00" * 64
    header = (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
              + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 44100, 88200, 2, 16)
              + b"data" + struct.pack("<I", len(data)))
    real.write_bytes(header + data)

    # 用一条**超长路径**指向它（模拟用户把保存目录设成多层归档目录）
    long_wav = _win_join(_long_win_dir(), "mic_20261112_120000.wav")
    assert len(long_wav) >= 260
    win_fs.vmap[long_wav] = str(real)

    assert audio_service._wav_ok(long_wav) is True, \
        "真实可用的 wav 被判成不可用 → 调用方会把它删掉"
