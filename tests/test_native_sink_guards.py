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


# --- 0xC00D4A45 音频流 header 缺失（float32→PCM16 + AAC 流配置）----------

def test_wasapi_float_converted_to_pcm16():
    """WASAPI 的 float32 mix 必须转成 PCM16 再喂 AAC（否则 WriteSample 全失败）。"""
    src = _cpp()
    assert "static bool is_ieee_float_format" in src
    assert "static void float32_to_pcm16" in src
    # 采集循环里必须同时具备 float32 转换分支和 16-bit PCM 原样分支
    loop = src[src.index("HRESULT capture_until_change"):
               src.index("std::atomic<bool> running_, stop_;")]
    assert "src_float && src_bits == 32" in loop
    assert "float32_to_pcm16(data, n, src_channels, blk.pcm)" in loop
    assert "src_bits == 16" in loop


def test_mic_format_reports_pcm16():
    """回读给 Python 的麦克风格式必须报告 16-bit（与采集写入、AAC 输入一致）。"""
    src = _cpp()
    assert "rate_ = f->nSamplesPerSec; bits_ = 16; channels_ = f->nChannels;" in src
    assert "rate_ = fmt->nSamplesPerSec; bits_ = 16; channels_ = src_channels;" in src


def test_aac_stream_declares_payload_type_and_pcm16_input():
    """AAC 输出流声明 raw payload + 16-bit，输入流固定 PCM16（AAC MFT 硬性要求）。"""
    src = _cpp()
    cfg = src[src.index("HRESULT config_audio_stream()"):
              src.index("HRESULT check_rotate()")]
    assert "MF_MT_AUDIO_BITS_PER_SAMPLE, 16" in cfg
    assert "MF_MT_AAC_PAYLOAD_TYPE, 0" in cfg
    assert "MFAudioFormat_PCM" in cfg
    assert "const int pcm_bits = 16" in cfg


def test_drain_audio_fills_silence_even_without_any_audio_sample():
    """全程无音频块时也必须补保底静音，确保 AAC 产出 esds header。"""
    src = _cpp()
    fin = src[src.index("int drain_audio()"):
              src.index("int finalize(std::string& published)")]
    assert "no_audio_at_all" in fin
    # 旧的 last_end > 0 致命门控必须移除
    assert "last_end > 0" not in fin
    assert "SILENCE_CAP_HNS" in fin          # 防长录制静音 OOM
    assert "MIN_FRAMES" in fin               # 保底 >=2 个 AAC 帧


# --- 本轮：构建指纹 + Finalize 诊断 + 补静音封顶/duration ----------------

def test_native_exposes_build_fingerprint():
    """native 必须导出构建指纹，供日志/真机确认 DLL 是否重新编译。"""
    src = _cpp()
    assert "const char* const kBuildId" in src
    assert 'extern "C" const char* adc_build_id(void)' in src
    # 导出必须在头文件声明（ctypes 侧才知道有这个符号）
    hdr = open(os.path.join(ROOT, "native", "adc_mf_sink.h"),
               "r", encoding="utf-8").read()
    assert "ADC_API const char* adc_build_id(void);" in hdr


def test_finalize_failure_carries_stream_stats():
    """Finalize 失败必须带 v/a/d 统计，区分视频缺 header 还是音频缺 esds。"""
    src = _cpp()
    cw = src[src.index("HRESULT close_writer(bool publish)"):
             src.index("std::string out_dir_, stem_;")]
    assert 'set_error(hr, "SinkWriter::Finalize 失败")' in cw
    assert "append_error_stats(video_bytes_, audio_frames_, dropped_)" in cw
    # append_error_stats 本身要把 a= 帧数写进错误文本
    ae = src[src.index("static void append_error_stats"):
             src.index("extern \"C\" int adc_last_error")]
    assert "a=%lldF" in ae and "v=%lldB" in ae


def test_silence_fill_capped_unconditionally_and_duration_matches_frames():
    """补静音必须无条件封顶（防中途停麦 OOM），且 duration 与帧数一致。"""
    src = _cpp()
    fin = src[src.index("int drain_audio()"):
              src.index("int finalize(std::string& published)")]
    # 封顶不能只在 no_audio_at_all 分支——中途有音频后停掉同样会 OOM
    assert "if (fill > SILENCE_CAP_HNS) fill = SILENCE_CAP_HNS;" in fin
    assert "if (no_audio_at_all && fill > SILENCE_CAP_HNS)" not in fin
    # duration 按实际帧数算，不能再塞墙钟差 fill
    assert "LONGLONG dur = (LONGLONG)frames * 10000000LL / arate_;" in fin
    assert "AudioBlock b{silence, anchor, dur};" in fin
    assert "AudioBlock b{silence, anchor, fill};" not in fin
