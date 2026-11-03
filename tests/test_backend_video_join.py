# -*- coding: utf-8 -*-
"""backend.video_join 的分段合并测试。

覆盖的失败模式都是「不崩溃但结果错」那一类：
  * 合并产物只有第一段时长（ffmpeg 退出码照样 0）→ 用户以为录了 8 分钟；
  * 缺 moov 的残段被塞进 concat → 整片时长算错；
  * 没有 ffmpeg 却悄悄返回「成功」→ 目录里还是 3 个分段，但界面说已合并；
  * 合并半途失败留下半个文件 → 被打包成成品。
"""
import os
import shutil
import subprocess

import pytest

import backend.video_join as vj


def _have_real_ffmpeg():
    try:
        return subprocess.run(["ffmpeg", "-version"],
                              capture_output=True).returncode == 0
    except Exception:
        return False


ffmpeg_required = pytest.mark.skipif(
    not _have_real_ffmpeg(), reason="本机没有 ffmpeg，跳过真实合并验证")


def _fake_mp4(path, with_moov=True, size=8192):
    """写一个够大的假 mp4（只带 moov 标记，不求真能播）。"""
    with open(path, "wb") as f:
        f.write(b"\x00\x00\x00\x18ftypmp42")
        f.write(b"\x00" * max(0, size - 20))
        if with_moov:
            f.write(b"moov")


class _R:
    def __init__(self, out="", rc=0, err=""):
        self.stdout, self.returncode, self.stderr = out, rc, err


def _make_real_segment(path, seconds=2.5):
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i",
         "testsrc=size=320x240:rate=10:duration=%s" % seconds,
         "-pix_fmt", "yuv420p", "-c:v", "mpeg4", "-q:v", "5", str(path)],
        check=True)
    return str(path)


# ---------------------------------------------------------------------------
# 单段 / 残段
# ---------------------------------------------------------------------------
def test_single_segment_is_returned_as_is(tmp_path, monkeypatch):
    """只有一段可合并时不该启动 ffmpeg（copy 一遍纯属浪费磁盘）。

    更重要的是返回的 path 就是**那一段自己**：调用方依据 used 删中间文件，
    若这里另建一个文件再返回，丢掉的那一段就是用户唯一的素材。
    """
    s1 = tmp_path / "record_A1_ts.mp4"
    _fake_mp4(s1)

    def boom(*a, **kw):
        raise AssertionError("单段不应调用 ffmpeg")

    monkeypatch.setattr(vj.subprocess, "run", boom)
    res = vj.join_segments([str(s1)], str(tmp_path / "out.mp4"))

    assert res["ok"] is True, res
    assert res["path"] == str(s1), res
    assert res["used"] == [str(s1)], res


def test_broken_segment_is_skipped_not_merged(tmp_path):
    """缺 moov 的残段必须被剔除：塞进 concat 会让整片时长算错、还可能播不了。

    但它**不能**被静默丢掉 —— 放在 skipped 里交回调用方，由业务层提示
    「残片保留在保存目录」，这是用户仅有的那部分画面。
    """
    good = tmp_path / "record_A1_ts.mp4"
    _fake_mp4(good)
    bad = tmp_path / "record_A1_ts_p2.mp4"
    _fake_mp4(bad, with_moov=False)

    res = vj.join_segments([str(good), str(bad)], str(tmp_path / "out.mp4"))

    assert res["ok"] is True, res
    assert res["path"] == str(good), res
    assert res["skipped"] == [str(bad)], res
    assert str(bad) not in res["used"], res


def test_all_broken_segments_report_reason(tmp_path):
    """一段完整的都没有时要说清原因，而不是回一个空成功。"""
    a = tmp_path / "a.mp4"
    _fake_mp4(a, with_moov=False)
    b = tmp_path / "b.mp4"
    _fake_mp4(b, with_moov=False)

    res = vj.join_segments([str(a), str(b)], str(tmp_path / "out.mp4"))

    assert res["ok"] is False and res["path"] is None, res
    assert "moov" in res["reason"], res


def test_missing_ffmpeg_says_why(tmp_path, monkeypatch):
    """没有 ffmpeg 时必须明说，绝不能返回「成功」让界面以为已合并成一个文件。"""
    a = tmp_path / "a.mp4"
    _fake_mp4(a)
    b = tmp_path / "b.mp4"
    _fake_mp4(b)
    monkeypatch.setattr(vj, "_have_ffmpeg", lambda: False)

    res = vj.join_segments([str(a), str(b)], str(tmp_path / "out.mp4"))

    assert res["ok"] is False, res
    assert "ffmpeg" in res["reason"], res
    assert res["used"] == [str(a), str(b)], "失败时也要回报哪些段可用，供调用方保留"


# ---------------------------------------------------------------------------
# ffmpeg 失败 / 假成功
# ---------------------------------------------------------------------------
def test_ffmpeg_failure_reports_stderr_and_leaves_no_output(tmp_path, monkeypatch):
    """ffmpeg 报错要把它的原话带出来，且不留下半个文件。

    只回一句「合并失败」的话，用户既不知道该装什么、也不知道目录里那个
    `_full.mp4` 是不是能用。
    """
    a = tmp_path / "a.mp4"
    _fake_mp4(a)
    b = tmp_path / "b.mp4"
    _fake_mp4(b)
    monkeypatch.setattr(vj, "_have_ffmpeg", lambda: True)
    monkeypatch.setattr(
        vj.subprocess, "run",
        lambda cmd, **kw: _R(rc=1, err="DTS out of order; failed to open input"))

    out = tmp_path / "out.mp4"
    res = vj.join_segments([str(a), str(b)], str(out))

    assert res["ok"] is False, res
    assert "failed to open input" in res["reason"], res
    assert not out.exists(), "合并失败不得留下成品文件"


def test_wrong_duration_output_is_rejected(tmp_path, monkeypatch):
    """成片时长明显短于各段之和 → 判定失败，不能把「只拼了第一段」当成功。

    回归：concat + `-c copy` 在时间基不一致时会安静地只输出第一段，退出码仍是
    0、文件也能播。用户录了 6 分钟，拿到一个 3 分钟的文件，还以为后半段没录上。
    """
    a = tmp_path / "a.mp4"
    _fake_mp4(a)
    b = tmp_path / "b.mp4"
    _fake_mp4(b)
    monkeypatch.setattr(vj, "_have_ffmpeg", lambda: True)
    monkeypatch.setattr(vj, "_mp4_playable", lambda p: True)
    monkeypatch.setattr(vj, "_video_duration", lambda p: "2.500")

    def fake_run(cmd, **kw):
        with open(cmd[-1], "wb") as f:
            f.write(b"\x00" * 8192)
        return _R(rc=0)

    monkeypatch.setattr(vj.subprocess, "run", fake_run)

    out = tmp_path / "out.mp4"
    res = vj.join_segments([str(a), str(b)], str(out))

    assert res["ok"] is False, res
    assert "不可信" in res["reason"], res
    assert not out.exists(), "时长不符的成片必须删掉，否则会被当成成品打包"


def test_concat_list_is_cleaned_up(tmp_path, monkeypatch):
    """合并清单是过程产物，成功失败都不该留在用户的保存目录里。"""
    a = tmp_path / "a.mp4"
    _fake_mp4(a)
    b = tmp_path / "b.mp4"
    _fake_mp4(b)
    monkeypatch.setattr(vj, "_have_ffmpeg", lambda: True)
    monkeypatch.setattr(
        vj.subprocess, "run", lambda cmd, **kw: _R(rc=1, err="boom"))

    out = tmp_path / "out.mp4"
    vj.join_segments([str(a), str(b)], str(out))

    assert not (tmp_path / "out.mp4.concat.txt").exists()


def test_concat_list_quotes_and_slashes(tmp_path, monkeypatch):
    """路径里的单引号 / 反斜杠必须按 concat 语法处理，否则 ffmpeg 找不到文件。

    目录名带 `'`（`D:\\张三's 素材`）在 Windows 上很常见，拼接列表又不转义的话
    整行会被截断，表现为「ffmpeg 合并失败」而原因指向一个不存在的路径；
    反斜杠则会被 concat 解析器当成转义序列（`\\a`、`\\x`）。
    """
    p = os.path.join(str(tmp_path), "a'b.mp4")
    quoted = vj._concat_quote(p)
    assert quoted.endswith("/a'\\''b.mp4"), quoted
    assert "\r" not in quoted and "\n" not in quoted, quoted

    monkeypatch.setattr(vj.os.path, "abspath", lambda p: r"D:\素材\x.mp4")
    assert vj._concat_quote("x") == "D:/素材/x.mp4"


# ---------------------------------------------------------------------------
# 真实 ffmpeg：两段拼成一段，时长等于两段之和
# ---------------------------------------------------------------------------
@ffmpeg_required
def test_two_segments_merge_into_one_playable_file(tmp_path):
    """真实合并：产出一个能播的文件，时长 = 各段之和，源段保持不动。

    源段不被本函数删除（删除是业务层按 used 做的决策）—— 这样调用方一旦在
    合并后、打包前出错，素材还在磁盘上。
    """
    a = _make_real_segment(tmp_path / "record_A1_ts.mp4", 2.5)
    b = _make_real_segment(tmp_path / "record_A1_ts_p2.mp4", 2.5)
    out = tmp_path / "record_A1_ts_full.mp4"

    res = vj.join_segments([a, b], str(out))

    assert res["ok"] is True, res
    assert res["path"] == str(out) and out.exists()
    assert res["used"] == [a, b] and res["skipped"] == []
    dur = float(vj._video_duration(str(out)))
    assert 4.5 <= dur <= 5.5, "合并后时长应约为 5 秒，实际 %.2f" % dur
    assert os.path.exists(a) and os.path.exists(b), "源段不应被合并函数删除"
    assert not (tmp_path / "record_A1_ts_full.mp4.concat.txt").exists()


@ffmpeg_required
def test_real_merge_keeps_single_segment_untouched(tmp_path):
    """单段真实文件也走同一条路径（不复制、不改名），内容与原件一致。"""
    a = _make_real_segment(tmp_path / "a.mp4", 1.0)
    before = open(a, "rb").read()

    res = vj.join_segments([a], str(tmp_path / "out.mp4"))

    assert res["ok"] is True and res["path"] == a
    assert open(a, "rb").read() == before
    assert shutil.os.path.getsize(a) == len(before)
