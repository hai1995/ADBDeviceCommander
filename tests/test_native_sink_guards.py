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


def test_first_writer_not_created_eagerly():
    """create() 不得立即建首段 writer：此刻无 SPS/PPS 会导致 Finalize 0xC00D4A45。"""
    src = _cpp()
    create_body = src[src.index("int create(std::string& first_tmp)"):
                      src.index("/* AudioSink：采集线程回调")]
    assert "ensure_writer(" not in create_body, (
        "首段 writer 必须延迟到收到 SPS/PPS 后创建，create() 只能预算临时名")
    assert "first_tmp = seg_tmp_path(1);" in create_body


def test_video_stream_requires_both_sps_and_pps():
    """视频 sequence header 必须 SPS+PPS 齐备才注入，缺一即失败而非写入坏流。"""
    src = _cpp()
    assert "if (sps_.empty() || pps_.empty())" in src
    # 确认 header 注入在 AddStream(video) 之前
    check_at = src.index("if (sps_.empty() || pps_.empty())")
    add_at = src.index('AddStream(vin, &vstream_)')
    assert check_at < add_at


def test_writer_creation_driven_by_sps_pps_in_write_video():
    """write_video 收到 SPS+PPS 后触发首段 writer 创建（延迟创建核心逻辑）。"""
    src = _cpp()
    wv = src[src.index("int write_video(const unsigned char* data, int len)"):
             src.index("int mark_mic_stop()")]
    assert "have_seq = !sps_.empty() && !pps_.empty();" in wv
    assert "if (have_seq)" in wv
    assert "HRESULT hr = ensure_writer(dummy);" in wv
    # 延迟创建逻辑必须位于写视频 sample 的循环之前
    assert wv.index("have_seq") < wv.index("while (pos < total)")


def test_lazy_create_guards():
    """延迟创建的配套守护：drain/check_rotate 在 writer 未建时不得误处理。"""
    src = _cpp()
    drain = src[src.index("void drain_audio_queued()"):
                src.index("/* 最终排空 + 补静音")]
    assert "if (!writer_) return;" in drain, "writer 未建时不 pop 音频块，避免开头音频丢失"
    rotate = src[src.index("HRESULT check_rotate()"):
                 src.index("HRESULT close_writer(bool publish)")]
    assert "if (!writer_) return S_OK;" in rotate, "writer 未建时 seg_start=0 不得误触发切段"


def test_finalize_reports_no_video_frame():
    """全程无 SPS/PPS（writer 从未创建）必须报错，不能报成功但无产物。"""
    src = _cpp()
    fin = src[src.index("int finalize(std::string& published)"):
              src.index("void discard()")]
    assert "未收到有效 H264 视频帧" in fin
    assert "if (!writer_ && published_.empty())" in fin
