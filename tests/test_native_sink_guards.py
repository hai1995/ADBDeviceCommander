"""native SinkWriter 源码守卫测试（Linux 沙箱无法编译 native，故静态锁定关键行为）。

真机曾出现「开启录音后收尾稳定报 SinkWriter::Finalize 失败（0x80070005 /
拒绝访问）」：根因是 moov 前置属性要求 sink 在 Finalize 阶段对同一输出文件
做二次 seek/remux，把 moov 从尾部搬到头部，这一步在真机被拒。本地录屏用本机
播放器播放，moov 在尾部完全可播，无需 faststart。这些用例防止该属性被重新
引入、并锁定已修复的 Finalize 错误上报与临时文件发布链。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

CPP = os.path.join(ROOT, "native", "adc_mf_sink.cpp")


def _cpp():
    with open(CPP, "r", encoding="utf-8") as fh:
        return fh.read()


def test_no_moov_before_mdat_attribute():
    """禁止重新引入 moov 前置：真机 Finalize 二次 remux 会报 0x80070005。"""
    src = _cpp()
    assert "MF_MPEG4SINK_MOOV_BEFORE_MDAT" not in src, (
        "moov 前置属性已移除：真机 Finalize 二次 seek/remux 触发拒绝访问")


def test_sinkwriter_created_with_null_attributes():
    """MFCreateSinkWriterFromURL 的 pAttributes 传 nullptr，走默认 moov 布局。"""
    src = _cpp()
    assert "MFCreateSinkWriterFromURL(wtmp, nullptr, nullptr, &writer_)" in src


def test_finalize_error_is_reported():
    """Finalize 失败必须转成可读 reason（set_error），不能被静默吞掉。"""
    src = _cpp()
    assert 'set_error(hr, "SinkWriter::Finalize 失败")' in src


def test_publish_happens_only_after_finalize():
    """原子发布在 Finalize 成功后进行：Finalize 失败时 .tmp 不冒充成功产物。"""
    src = _cpp()
    finalize_at = src.index("writer_->Finalize()")
    publish_at = src.index("MOVEFILE_REPLACE_EXISTING")
    assert finalize_at < publish_at
