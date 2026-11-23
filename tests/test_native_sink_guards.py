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


def test_half_writer_tmp_not_published():
    """[产物完整性回归] writer 已建但未 BeginWriting 时不得发布无 moov 的半成品。

    ensure_writer 在 BeginWriting 之前失败(AAC 编码器不可用等)会留下 writer_+
    tmp_files_ 条目但 writing_=false。旧 close_writer 跳过 Finalize 却仍发布 tmp
    并让 finalize 报假成功。修复:捕获 was_writing,未就绪则删 tmp + 报错 return。
    """
    src = _cpp()
    cw = src[src.index("HRESULT close_writer(bool publish)"):
             src.index("std::string out_dir_, stem_;")]
    # 必须在 Finalize 把 writing_ 置回 false 之前捕获原始状态
    capture = cw.index("const bool was_writing = writing_;")
    finalize = cw.index("if (writing_) { hr = writer_->Finalize(); writing_ = false; }")
    assert capture < finalize
    # 发布前必须用 was_writing 守卫；未就绪时删磁盘 tmp + 报错 + return
    guard = cw.index("if (!was_writing) {")
    release = cw.index("published_.push_back(final);")
    assert guard < release, "was_writing 守卫必须位于发布动作之前"
    block = cw[guard:cw.index("std::string final = tmp;", guard)]
    assert "DeleteFileW(wt)" in block, "半成品 tmp 必须从磁盘删除"
    assert "tmp_files_.pop_back()" in block
    assert "return E_FAIL;" in block, "半成品不得走成功发布路径"


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


def test_push_sample_discards_on_lock_failure():
    """[数据完整性回归] IMFMediaBuffer Lock 失败必须丢弃本块，禁止写未初始化内存。

    旧实现 `if (SUCCEEDED(Lock) && dst) {memcpy...}` 在 Lock 失败时跳过 memcpy，
    却仍 SetCurrentLength(len)+AddBuffer+WriteSample —— 把未初始化的堆内存写进
    音视频流。改为 Lock 失败即释放并 dropped_++ return。
    """
    src = _cpp()
    fn = src[src.index("void push_sample("):
             src.index("// 段临时文件名")]
    # 必须显式判断 Lock 失败，且失败分支里 Release 后直接 return
    assert "FAILED(buf->Lock(&dst, nullptr, nullptr)) || !dst" in fn
    fail_pos = fn.index("FAILED(buf->Lock(&dst, nullptr, nullptr)) || !dst")
    ret_pos = fn.index("buf->Release(); sample->Release(); dropped_++; return;")
    assert fail_pos < ret_pos, "Lock 失败分支必须 Release 后立即 return"
    # memcpy/Unlock/SetCurrentLength 只能在成功分支（return 之后）执行
    memcpy_pos = fn.index("memcpy(dst, data, len);")
    assert ret_pos < memcpy_pos, "拷贝必须发生在失败分支 return 之后"


def test_wasapi_float_guid_offset_is_correct():
    """[静音回归] EXTENSIBLE 的 SubFormat 必须用 offsetof 定位，cbSize 下限 22。

    真机/现代 Windows 共享模式默认返回 WAVE_FORMAT_EXTENSIBLE + 32-bit float。
    旧实现把 GUID 从 `f + sizeof(WAVEFORMATEX)`(=18) 读，实际落在 Samples/mask
    上，memcmp 永不命中 → float32 被误判为不支持 → 全程静音，上一轮的
    float32→PCM16 修复从未生效。此处静态锁定正确偏移，防止回退。
    """
    src = _cpp()
    fn = src[src.index("static bool is_ieee_float_format"):
             src.index("/* float32 [-1,1]")]
    # 用权威 offsetof 定位 SubFormat，而不是 sizeof(WAVEFORMATEX)
    assert "offsetof(WAVEFORMATEXTENSIBLE, SubFormat)" in fn
    assert "sizeof(WAVEFORMATEX)" not in fn, (
        "不能用 WAVEFORMATEX 的大小当 SubFormat 偏移：它前面还有 Samples+mask")
    # cbSize 下限按 SDK 文档 >=22，不是 sizeof(GUID)=16
    assert "f->cbSize >= 22" in fn
    # 需要 mmreg.h / cstddef 提供类型与 offsetof
    assert "#include <mmreg.h>" in src and "#include <cstddef>" in src


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
    """Finalize 失败必须带分路诊断，定位 0xC00D4A45 到底缺哪路的 header。"""
    src = _cpp()
    cw = src[src.index("HRESULT close_writer(bool publish)"):
             src.index("std::string out_dir_, stem_;")]
    assert 'set_error(hr, "SinkWriter::Finalize 失败")' in cw
    # [诊断 v8] 调用必须传入每路 WriteSample 成功/失败计数、HRESULT、AAC 配置、seq header 长度
    call = cw[cw.index("append_error_stats("):]
    call = call[:call.index(");") + 2]
    for tok in ("vws_", "aws_", "vwf_", "awf_", "vlhr_", "alhr_",
                "arate_", "ach_", "diag_sps_", "diag_pps_", "diag_seqh_", "video_frame_count_"):
        assert tok in call, f"诊断调用缺少 {tok}"
    # append_error_stats 本身要把分路字段写进错误文本
    ae = src[src.index("static void append_error_stats"):
             src.index("extern \"C\" int adc_last_error")]
    for key in ("a=%lldF", "v=%lldB", "vws=%lld", "aws=%lld",
                "vlhr=0x%08X", "alhr=0x%08X", "aac=%dHz/%dch/%dbit",
                "sps=%dB", "seqh=%dB", "vfc=%lld"):
        assert key in ae, f"诊断文本缺少字段 {key}"


def test_video_uses_frame_index_clock():
    """[0xC00D4A45 视频根因·v10 根治回归] 视频时间戳必须用帧序号合成时钟。

    v8/v9 真机诊断(vws=4→49, vwf=339→298, vtc=45, 音频 awf=0 全成功)证明：
    视频 ts 用 QPC 到达时刻会被 adb 突发/卡顿污染——后帧重叠或向前 gap 都会让
    MP4 sink 以 E_UNEXPECTED(0x8000FFFF) 拒帧并进入 sticky 错误态。钳制只修重叠
    修不了向前跳跃(v9 仍失败 298)。视频 347 帧÷30fps=11.57s 与音频 11.58s 吻合，
    证明源帧数正常、问题纯在时间戳。根治：第 N 帧 ts=N×名义帧长，绝对均匀单调。
    """
    src = _cpp()
    ps = src[src.index("void push_sample(DWORD stream, bool audio"):
             src.index("// 段临时文件名")]
    # 视频流(!audio)时间戳必须由帧序号 × dur 合成，而非 QPC 到达时刻
    assert "if (!audio) {" in ps
    vc = ps[ps.index("if (!audio) {"):
            ps.index("sample->SetSampleTime(rel_ts)")]
    assert "rel_ts = (LONGLONG)video_frame_count_ * dur;" in vc
    assert "++video_frame_count_;" in vc
    # v9 的钳制方案必须彻底移除（无 last_video_end_/vtc_ 残留）
    assert "last_video_end_" not in src, "钳制方案已弃用：修不了向前 gap，不能留残留"
    assert "vtc_" not in src
    # 音频路不得被帧号时钟影响：仍用传入的 ts（含 seg_start 换算）
    assert "sample->SetSampleTime(rel_ts);" in ps
    # 切段必须归零：新 MP4 帧号从 0 开始
    ew = src[src.index("HRESULT ensure_writer(std::string& first_tmp_out)"):
             src.index("HRESULT config_video_stream()")]
    assert "video_frame_count_ = 0;" in ew


def test_write_sample_stats_are_per_stream():
    """[诊断回归] 每路 WriteSample 成功/失败必须分开计数，且不依赖 stream id 数值。"""
    src = _cpp()
    ps = src[src.index("void push_sample(DWORD stream, bool audio"):
             src.index("// 段临时文件名")]
    # 新签名带 audio 标志
    assert "void push_sample(DWORD stream, bool audio," in ps
    # 按 audio 标志分别记成功/失败与最后 HRESULT
    assert "if (audio) {" in ps
    assert "++aws_; alhr_ = hr" in ps and "++vws_; vlhr_ = hr" in ps
    assert "++awf_; alhr_ = hr" in ps and "++vwf_; vlhr_ = hr" in ps
    # 两个调用点都传了 audio 标志
    assert "push_sample(vstream_, false," in src
    assert "push_sample(astream_, true," in src


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
