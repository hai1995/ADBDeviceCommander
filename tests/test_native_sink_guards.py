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
    """延迟创建的配套守护：drain/should_rotate 在 writer 未建时不得误处理。"""
    src = _cpp()
    drain = src[src.index("size_t drain_audio_queued()"):
                src.index("/* 最终排空 + 补静音")]
    assert "if (!writer_) return 0;" in drain, "writer 未建时不 pop 音频块，避免开头音频丢失"
    rotate = src[src.index("bool should_rotate()"):
                 src.index("HRESULT close_writer(bool publish)")]
    assert "if (!writer_ || rotate_pending_) return false;" in rotate, (
        "writer 未建时 seg_start=0 不得误触发切段")


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
              src.index("bool should_rotate()")]
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
                "arate_", "ach_", "diag_sps_", "diag_pps_", "diag_seqh_",
                "video_frame_count_", "diag_vsim_"):
        assert tok in call, f"诊断调用缺少 {tok}"
    # append_error_stats 本身要把分路字段写进错误文本
    ae = src[src.index("static void append_error_stats"):
             src.index("extern \"C\" int adc_last_error")]
    for key in ("a=%lldF", "v=%lldB", "vws=%lld", "aws=%lld",
                "vlhr=0x%08X", "alhr=0x%08X", "aac=%dHz/%dch/%dbit",
                "sps=%dB", "seqh=%dB", "vfc=%lld", "vsim=0x%08X"):
        assert key in ae, f"诊断文本缺少字段 {key}"


def test_video_stream_sets_input_media_type():
    """[0xC00D4A45 视频根因·v11] 视频流必须调用 SetInputMediaType。

    物证(半成品 mp4)：只有 ftyp/uuid/mdat，无 moov/avcC/esds → sink 在 Finalize
    前就拿不到生成 codec-private header 所需的信息。诊断：音频 aws=292/awf=0
    全成功(音频流有 SetInputMediaType)，视频 vws=1/vwf=69 首帧后 sticky 全失败
    (视频流此前只有 AddStream、从未设输入类型)。0xC00D4A45 =
    MF_E_SINK_HEADERS_NOT_FOUND，SinkWriter 的 sequence header 从输入媒体类型读取。
    修复：config_video_stream 在 AddStream 后对视频流调用 SetInputMediaType，
    remux 输入输出同为 H264，复用带 sequence header 的 vin。
    """
    src = _cpp()
    cv = src[src.index("HRESULT config_video_stream()"):
             src.index("HRESULT config_audio_stream()")]
    # 必须有 AddStream 之后的 SetInputMediaType(video)
    assert "AddStream(vin, &vstream_)" in cv
    assert "SetInputMediaType(vstream_, vin, nullptr)" in cv
    # 顺序：AddStream 必须在 SetInputMediaType 之前（MSDN 标准序列）
    assert cv.index("AddStream(vin, &vstream_)") < cv.index("SetInputMediaType(vstream_, vin, nullptr)")
    # 结果必须落到诊断字段，便于真机确认是否被接受
    assert "diag_vsim_ = writer_->SetInputMediaType(vstream_, vin, nullptr)" in cv
    # 成员必须声明且构造初始化
    assert "HRESULT diag_vsim_;" in src
    assert "diag_vsim_(S_OK)" in src


def test_video_uses_frame_index_clock():
    """[视频时间戳回归] 视频 ts 绝不用 QPC 到达时刻；保留 v8/v9 历史约束。

    v8/v9 真机诊断(vws=4→49, vwf=339→298, vtc=45, 音频 awf=0 全成功)证明：
    视频 ts 用 QPC 到达时刻会被 adb 突发/卡顿污染——后帧重叠或向前 gap 都会让
    MP4 sink 以 E_UNEXPECTED(0x8000FFFF) 拒帧并进入 sticky 错误态。v10 的帧号
    主钟解决了单调性，v15 在其上叠加音频时长校准解决音画不同步（见另两个守卫）。
    本守卫锁定：视频仍走独立分支、不用 QPC 到达时刻、无 v9 钳制残留、切段归零。
    """
    src = _cpp()
    ps = src[src.index("void push_sample(DWORD stream, bool audio"):
             src.index("// 段临时文件名")]
    # 视频流(!audio)有独立分支，时间戳不用传入的 QPC 到达时刻 ts
    assert "if (!audio) {" in ps
    vc = ps[ps.index("if (!audio) {"):
            ps.index("sample->SetSampleTime(rel_ts)")]
    assert "rel_ts = video_ts_hns_;" in vc, "视频 ts 来自累加器，不用 QPC 到达时刻"
    assert "++video_frame_count_;" in vc
    # v9 的钳制方案必须彻底移除（无 last_video_end_/vtc_ 残留）
    assert "last_video_end_" not in src, "钳制方案已弃用：修不了向前 gap，不能留残留"
    assert "vtc_" not in src
    # 音频路不得被视频校准影响：仍用传入的 ts（含 seg_start 换算）
    assert "sample->SetSampleTime(rel_ts);" in ps
    # 切段必须归零：新 MP4 时间轴从 0 开始
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


def test_write_sample_is_called_and_hr_declared():
    """[编译回归] push_sample 必须声明 hr 且真正调用 WriteSample。

    v10 首次提交曾误删 `HRESULT hr = writer_->WriteSample(...)` 整行：导致
    CI 编译报 error C2065 'hr' undeclared identifier(C2065@827-842)，且 sample
    从未写入 sink。静态文本守卫锁定 hr 声明→WriteSample→使用的完整链路。
    """
    src = _cpp()
    ps = src[src.index("void push_sample(DWORD stream, bool audio"):
             src.index("// 段临时文件名")]
    # hr 必须声明且由 WriteSample 赋值
    assert "HRESULT hr = writer_->WriteSample(stream, sample);" in ps
    decl = ps.index("HRESULT hr = writer_->WriteSample(stream, sample);")
    # 声明必须在使用它的分路统计之前
    use = ps.index("if (SUCCEEDED(hr)) { ++aws_")
    assert decl < use, "hr 声明必须早于分路统计使用"
    # WriteSample 调用必须存在（sample 真正写进 sink）
    assert ps.count("WriteSample(stream, sample)") == 1


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


# --- 根因修复 v12：AnnexB 格式 + 完整 AU（0xC00D4A45 真因）-----------------

def test_sequence_header_uses_annexb_start_codes():
    """[0xC00D4A45 真因·v12] 序列头必须 AnnexB 起始码，不是 AVCC 长度前缀。

    微软 MPEG-4 File Sink / MF_MT_MPEG_SEQUENCE_HEADER 文档明确要求：
    h264 的 sequence header blob 是 'concatenated NAL units in Annex B format,
    along with their start codes'。失败 mp4 的 mdat 中 0 个 AnnexB 起始码、
    全是 AVCC 4 字节长度前缀，证明旧实现写的格式 sink 根本不认识。
    """
    src = _cpp()
    assert "static const unsigned char kAnnexBStartCode[4] = {0x00, 0x00, 0x00, 0x01};" in src
    helpers = src[src.index("static void append_annexb_nal"):
                  src.index("/* ------------------- 音频：WASAPI")]
    # SPS/PPS 都通过 AnnexB 追加，绝不能再出现 4 字节大端长度前缀
    assert "append_annexb_nal(h, sps);" in helpers
    assert "append_annexb_nal(h, pps);" in helpers
    assert "(n>>24)&0xFF" not in helpers, "禁止回退到 AVCC 长度前缀"
    # 序列头仍必须注入媒体类型
    cv = src[src.index("HRESULT config_video_stream()"):
             src.index("HRESULT config_audio_stream()")]
    assert "SetBlob(MF_MT_MPEG_SEQUENCE_HEADER" in cv
    assert "make_seq_header(sps_, pps_)" in cv


def test_video_samples_are_annexb_not_length_prefixed():
    """[0xC00D4A45 真因·v12] 喂给 sink 的样本必须是 AnnexB，不能 AVCC 化。

    MPEG-4 File Sink 要求位流符合 H.264 Annex B（NALU 以 3/4 字节起始码分隔）。
    旧实现 to_length_prefixed() 把每个 NAL 前加 4 字节长度，sink 原样写入 mdat
    且无法解析 → WriteSample 首帧后 sticky E_UNEXPECTED、Finalize 出不了 header。
    """
    src = _cpp()
    assert "to_annexb" in src
    assert "to_length_prefixed" not in src, "AVCC 转换函数必须彻底移除"
    fp = src[src.index("/* 冲刷跨 native 调用累积的当前 AU"):
             src.index("void write_audio_block(")]
    assert "to_annexb(pending_au_)" in fp
    assert "(n>>24)&0xFF" not in fp


def test_access_unit_assembled_across_native_calls():
    """[0xC00D4A45 真因·v12] AU 必须跨 native 调用累积，收尾/切段冲刷。

    Python 每次 session_write_video 只送一条 AnnexB NAL（见 mf_native.NalBuffer），
    一帧的 SEI/VCL 常跨多次调用。旧实现在 write_video 末尾把每条 NAL 单独写成
    sample，纯非 VCL(NAL type 6/9) 也成 sample，违反微软'样本须包含单帧全部
    切片与数据 NALU'要求，sink 收到无效 AU 后进入 sticky 错误态。
    """
    src = _cpp()
    # 成员：跨调用累积的 AU
    assert "std::vector<std::vector<unsigned char>> pending_au_;" in src
    # write_video 内不能有函数级局部 au，也不能在末尾 flush
    wv = src[src.index("int write_video(const unsigned char* data, int len)"):
             src.index("int mark_mic_stop()")]
    assert "std::vector<std::vector<unsigned char>> au;" not in wv
    assert "flush_au(au)" not in wv and "if (!au.empty())" not in wv
    assert "pending_au_.push_back" in wv
    # AU 边界：AUD 冲刷 + 新 VCL 到来时冲刷上一帧
    assert "if (type == 9)" in wv and "flush_pending_au();" in wv
    assert "if (type >= 1 && type <= 5 && has_vcl(pending_au_)) flush_pending_au();" in wv
    # flush_pending_au 必须只写含 VCL 的完整 AU，纯非 VCL 残片丢弃
    fp = src[src.index("/* 冲刷跨 native 调用累积的当前 AU"):
             src.index("void write_audio_block(")]
    assert "if (has_vcl(pending_au_))" in fp
    assert "pending_au_.clear();" in fp
    # 收尾/切段：close_writer 在 Finalize 前冲刷未到边界的最后一帧
    cw = src[src.index("HRESULT close_writer(bool publish)"):
             src.index("std::string out_dir_, stem_;")]
    flush_at = cw.index("flush_pending_au();")
    finalize_at = cw.index("writer_->Finalize()")
    assert flush_at < finalize_at, "最后一帧必须在 Finalize 之前冲刷进 sink"


def test_annexb_nal_scan_does_not_truncate_tail_bytes():
    """[花屏回归·v13] NAL 扫描必须覆盖到 buffer 末尾，不能截掉尾部载荷。

    本地 ffmpeg 实证：旧实现内层 `while (end + 3 <= len)` 在 buffer 末尾提前
    2 字节退出，17/17 条 NAL 的尾部被截 1~2 字节，切片数据损坏 → 整屏马赛克。
    修正为 `while (end < len)` 并对每个起始码判断逐项加 `end + k <= len` 守卫：
    0/17 截断、15 帧全部正常解码。此守卫锁定该扫描边界不被回退。
    """
    src = _cpp()
    fn = src[src.index("static int next_annexb_nal"):
             src.index("/* [根因修复 v12] Annex B 格式")]
    # 只看代码行（剔除注释中引用的旧循环），避免注释误触发
    code_lines = [ln.split("//")[0] for ln in fn.splitlines()]
    code = "\n".join(code_lines)
    # 内层扫描必须走到 len（不能用 end+3<=len 当循环条件）
    assert "while (end < len) {" in code, "NAL 扫描必须覆盖 buffer 最后一字节"
    assert "while (end + 3 <= len)" not in code, "禁止回退到会截断尾部的扫描边界"
    # 3/4 字节起始码判断都要有独立的长度守卫，避免越界读
    assert "end + 3 <= len && p[end] == 0 && p[end+1] == 0 && p[end+2] == 1" in code
    assert "end + 4 <= len && p[end] == 0 && p[end+1] == 0 &&" in code


def test_audio_write_sample_outside_queue_lock():
    """[收尾慢/排空超时回归·v14] WriteSample 必须在音频队列锁外执行。

    旧实现持 audio_q_mtx_ 逐块 write_audio_block（内含同步的 SinkWriter::WriteSample
    → AAC 编码）。高负载下单次 WriteSample 慢 → 持锁期间 WASAPI 采集线程 on_audio
    入队被堵 → worker 队列 drain 堆积 → 某次排空卡满 15s → Python 报"MF worker 调用
    超时"并永久停止排空，同时 finalize 排队 → 收尾变慢。修复：持锁只做有界的取块
    (v14 swap 整批 → v18 批上限取块)，锁外逐块编码。此守卫锁定"锁内无 WriteSample、
    写入在锁外"。
    """
    src = _cpp()
    fn = src[src.index("size_t drain_audio_queued()"):
             src.index("/* 最终排空 + 补静音")]
    code = "\n".join(ln.split("//")[0] for ln in fn.splitlines())
    # 锁的生命周期：必须用独立作用域把 lock_guard 夹起来，取块后立即出作用域
    assert "std::deque<AudioBlock> batch;" in fn, "须用与 audio_q_ 同类型的 batch 承接"
    assert "kAudioDrainBatchMax" in code, "取块须受批上限约束（v18）"
    # 关键顺序：锁内取块（pop_front）在前，写入循环在后；锁作用域 } 夹在两者之间
    take_at = code.index("audio_q_.pop_front()")
    write_at = code.index("write_audio_block(blk)")
    scope_end = code.index("\n        }", take_at)   # 取块所在 lock_guard 作用域的结束
    assert take_at < scope_end < write_at, (
        "必须先在锁内取块、再出锁作用域、最后在锁外 WriteSample")
    # write_audio_block 调用必须只有一处（在锁外循环里），不能残留在锁内
    assert code.count("write_audio_block(blk)") == 1


def test_audio_queue_queued_hns_is_o1():
    """[收尾慢回归·v14] audio_q_ 累计时长必须 O(1) 维护，禁止每次遍历整个队列。

    旧实现 on_audio 每次入队都 `for (auto& b : audio_q_) queued += b.dur_hns`，
    长录制队列积压时采集线程被 O(n) 遍历拖慢。修复为成员 queued_hns_：入队 +=、
    drain 归零。此守卫锁定该累计值存在且无残留遍历。
    """
    src = _cpp()
    fn = src[src.index("void on_audio(const AudioBlock& blk) override"):
             src.index("int write_video(")]
    code_lines = [ln.split("//")[0] for ln in fn.splitlines()]
    code = "\n".join(code_lines)
    assert "queued_hns_" in code, "须用累计时长成员，避免 O(n) 遍历"
    assert "for (const auto& b : audio_q_)" not in code, "禁止回退到 O(n) 遍历队列"
    # 成员声明与构造函数初始化都要有
    assert "LONGLONG queued_hns_;" in src
    assert "queued_hns_(0)" in src


def test_video_timestamp_is_cumulative_not_framecount_times_fixed():
    """[音画不同步回归·v15] 视频 ts 必须累加式，不能用帧号×固定帧长。

    根因物证：成品 mp4 视频 459 帧=15.300s(硬编码30fps)、音频 735×1024/48000
    =15.680s，真实帧率 29.27fps，视频时间轴短 2.4% 且随录制累积 → 声音快画面慢。
    修复：video_ts_hns_ 累加式 + video_frame_dur_hns_ 校准。此守卫禁止回退到旧式。
    """
    src = _cpp()
    # 旧式「帧号×固定帧长」必须彻底消失
    assert "video_frame_count_ * dur" not in src, "禁止回退到帧号×固定帧长"
    # 累加式时间戳与校准帧长成员必须存在并初始化
    assert "LONGLONG video_ts_hns_;" in src
    assert "LONGLONG video_frame_dur_hns_;" in src
    assert "video_ts_hns_(0)" in src
    # 累加动作：video_ts_hns_ += video_frame_dur_hns_
    assert "video_ts_hns_ += video_frame_dur_hns_;" in src
    # rel_ts 取自累加器，而非帧号乘算
    assert "rel_ts = video_ts_hns_;" in src
    # sample duration 用校准帧长（与时间戳步进一致）
    assert "dur = video_frame_dur_hns_;" in src


def test_video_frame_dur_calibrated_from_synced_audio_only():
    """[音画不同步回归·v16] 帧长观测源必须是「与视频同时段」的音频时长。

    v15 用全局 audio_frames_(含麦克风先于 screenrecord 启动的前置音频)，真机
    实证前置约1.3s 使观测帧长虚高4%→视频被拉长、声音反而变晚。v16 改用
    sync_audio_hns_(只累加采集时刻>=seg_start 的音频)作观测源，彻底排除前置音频。
    钳制 [名义×0.7,名义×1.4] + 步长≤名义/50 保证 sink 单调性。
    """
    src = _cpp()
    fn = src[src.index("void push_sample("):src.index("void push_sample(") + 3500]
    code = "\n".join(ln.split("//")[0] for ln in fn.splitlines())
    # 观测源 = 已排除前置音频的 sync_audio_hns_（禁止用全局 audio_frames_ 换算）
    assert "sync_audio_hns_" in code, "须以同步段音频时长为观测源"
    assert "audio_frames_" not in code, "禁止用全局 audio_frames_(含前置音频)"
    assert "audio_real" not in code
    assert "observed = sync_audio_hns_ / video_frame_count_" in code
    # 钳制上下界 + 步长限制（sink 单调性保证）
    assert "nominal * 7 / 10" in code, "帧长下限钳制"
    assert "nominal * 14 / 10" in code, "帧长上限钳制"
    assert "LONGLONG step = nominal / 50;" in code, "每帧步长限制"
    assert "video_frame_dur_hns_ += delta;" in code, "渐进校准而非跳变"
    # 冷启动保护：前几帧音频未写入时不校准
    assert "video_frame_count_ >= 5" in code


def test_sync_audio_excludes_pre_roll_before_segment_start():
    """[音画不同步回归·v16] sync_audio_hns_ 必须按采集时刻过滤，排除前置音频。

    麦克风常早于 screenrecord 启动，ts<seg_start 的音频块不属于任何视频帧。
    若计入会使观测帧长虚高、视频被拉长。守卫锁定 ts 过滤条件存在。
    """
    src = _cpp()
    # drain 中按 ts 过滤累加
    drain = src[src.index("size_t drain_audio_queued()"):src.index("int drain_audio()")]
    code = "\n".join(ln.split("//")[0] for ln in drain.splitlines())
    assert "blk.ts_hns >= seg_start_hns_" in code, "必须按采集时刻过滤前置音频"
    assert "sync_audio_hns_ += blk.dur_hns" in code, "只累加同步段音频时长"
    # 成员声明 + 构造初始化 + 切段重置
    assert "LONGLONG sync_audio_hns_;" in src
    assert "sync_audio_hns_(0)" in src
    ew = src[src.index("HRESULT ensure_writer(std::string& first_tmp_out)"):
             src.index("HRESULT config_video_stream()")]
    assert "sync_audio_hns_ = 0;" in ew, "切段须重置同步音频观测"


def test_video_clock_reset_on_segment_rotation():
    """[音画不同步回归·v15] 切段时累加时钟/帧长必须重置，否则新段首帧时间戳错乱。"""
    src = _cpp()
    # 找到 ensure_writer 里 seg_start_hns_ 赋值附近的重置块
    assert "video_ts_hns_ = 0;" in src, "切段重置累加时间戳"
    assert "video_frame_dur_hns_ = 10000000LL * fps_den_ / fps_num_;" in src, "切段重置帧长为名义值"



def test_audio_drain_has_batch_cap():
    """[收尾慢根因回归·v18] 单次音频排空必须有批上限，杜绝 write_video 超时。

    v17 只把超时 drain 变可取消，但被 cancel 的 drain 不再执行 → 队列积压到 5s
    上限(~234 块)；native 一次 swap 走全部逐块同步 AAC 编码累计 15s+，嵌在
    write_video 内部顶过 15s 超时 → 误报"写入 H264 流失败"。修复必须：
    1) drain_audio_queued 每批封顶(批上限常量)；2) 剩余留在队列而非一次清空；
    3) 返回本批块数供 finalize 判断残留。
    """
    src = _cpp()
    fn = src[src.index("size_t drain_audio_queued()"):src.index("int drain_audio()")]
    code = "\n".join(ln.split("//")[0] for ln in fn.splitlines())
    # 签名返回块数（供 finalize 循环判定）
    assert "size_t drain_audio_queued()" in src, "排空函数须返回本批块数"
    assert "return batch.size()" in code, "须返回本批处理数"
    # 批上限常量 + 按上限截断取块
    assert "kAudioDrainBatchMax" in code, "须有单次排空批上限常量"
    assert "kAudioDrainBatchMax = 48" in code, "批上限须为有界值(48)"
    assert "audio_q_.size() < kAudioDrainBatchMax" in code, "取块数须受批上限约束"
    # 不得再一次性 swap 全队列（那样批上限形同虚设）
    assert "batch.swap(audio_q_)" not in code, "禁止一次 swap 全部积压块"
    # 剩余时长仍计入队列水位（不能清零）
    assert "queued_hns_ -= batch_hns" in code, "只减去本批移出的时长"


def test_finalize_stops_producer_then_drains_bounded():
    """[收尾慢根因回归·v19] finalize 排空必须先停生产者、且有界，杜绝忙等死循环。

    v18 用 `while(drain_audio_queued()>0){}` 无界循环，但 stop_all 顺序是
    「先 finalize→后 _stop_mic」，finalize 期间采集线程仍在入队 → 队列永不空
    → 忙等卡死 worker 60s+。v19：先 unsubscribe_() 停生产者，再用有界 for
    循环排空（队列 5s 上限≈234 块，64 批绰绰有余）。
    """
    src = _cpp()
    fn = src[src.index("int drain_audio()"):src.index("int finalize(")]
    code = "\n".join(ln.split("//")[0] for ln in fn.splitlines())
    # ① 必须先退订停止音频入队，否则生产者不停、循环永不结束
    assert "unsubscribe_()" in code, "drain 前须 unsubscribe 停止音频生产者"
    # ② 必须是有界循环，绝不能是 while(>0) 忙等
    assert "while (drain_audio_queued() > 0)" not in code, "禁止无界 while 忙等"
    assert "kMaxDrainBatches" in code, "排空循环须有硬上限"
    assert "for (int i = 0; i < kMaxDrainBatches" in code, "须用有界 for 循环"
    assert "drain_audio_queued() == 0" in code, "队列见底即提前退出"


def test_build_id_v34():
    """native 指纹升到 v34，真机据此确认整包含 v24~v34 全部录制/收尾修复。

    v34 native 增加带外 phase 探针（adc_diag_phase，纯原子读不经 worker）：worker
    被 native 同步调用占死时，stats/最后错误都因走 worker 或加锁拿不到，只有 phase
    能带外读出卡死点；配合 Python 侧 moov 成片抢救（已 Finalize 的 .tmp.mp4 直接
    改名捞回）。v33 屏障不再当唯一落盘判据 + native stats 落地；v32 adb 自愈守卫；
    v31 stop_all 两阶段收尾；v30 IDR 打 CleanPoint 根治快进花屏。
    """
    src = _cpp()
    assert 'kBuildId = "mf-20261124-drain-v34"' in src, "native 指纹须为 v34"


def test_diag_phase_probe_is_out_of_band():
    """[诊断 phase v34·守卫] 卡死点探针必须是纯原子读、不经 worker、不碰锁/COM。

    worker 被 native 同步调用占死时，任何 worker.call（stats/barrier/finalize）都
    超时，诊断通道若也走 worker 就永远拿不到卡死点。本守卫确保 adc_diag_phase 是
    直接 atomic load，且在 write_video/drain/flush/push_sample/ensure_writer/
    sink_finalize/movefile/finalize_done 各阶段都有 diag_phase 埋点。
    """
    src = _cpp()
    assert "std::atomic<int> g_diag_phase" in src, "phase 必须用原子变量"
    fn = src[src.index("extern \"C\" int adc_diag_phase"):]
    fn = fn[:fn.index("\n}") + 2]
    assert "load(std::memory_order_relaxed)" in fn, "探针须为无锁原子读"
    assert "worker" not in fn and "call" not in fn, "探针不得走 worker 队列"
    # 头文件必须有 ADC_API 导出声明，否则 MSVC 不导出符号、ctypes 找不到
    hdr = open(os.path.join(ROOT, "native", "adc_mf_sink.h"),
               "r", encoding="utf-8").read()
    assert "ADC_API int adc_diag_phase(void);" in hdr, "头文件须声明探针导出"
    # 关键阶段都要有埋点码（1~9）；视频/音频样本WriteSample(4/5)用三元写法
    for code in (1, 2, 3, 6, 7, 8, 9):
        assert f"diag_phase({code}" in src, f"缺少阶段 {code} 的埋点"
    assert "diag_phase(audio ? 5 : 4)" in src, "缺少 WriteSample 视频/音频分路埋点"


def test_rotate_is_pulled_out_of_write_video():
    """[收尾慢根治回归·v20] 重量切段不得再在 write_video 内同步执行。

    3min+ 录制跨 170s 阈值，旧 check_rotate 在 write_video 的 30s worker 调用内
    同步做 Finalize+WRITE_THROUGH 刷盘+重建 SinkWriter → 超时"写入 H264 流失败"。
    v20：write_video 只返回 ADC_ROTATE_PENDING 请求，Python 显式调 adc_session_rotate。
    """
    src = _cpp()
    # write_video 末尾只返回轻量信号，不再直接调重量切段
    wv = src[src.index("int write_video("):src.index("int mark_mic_stop()")]
    wv_code = "\n".join(ln.split("//")[0] for ln in wv.splitlines())
    assert "return should_rotate() ? ADC_ROTATE_PENDING : ADC_OK;" in wv_code, (
        "write_video 只返回切段请求信号")
    assert "check_rotate" not in wv_code, "write_video 不得再同步执行重量切段"
    # 存在独立的请求/执行两段 + C ABI 导出
    assert "bool should_rotate()" in src, "须有轻量的切段请求判定"
    assert "rotate_pending_" in src, "须有 pending 标志防重复请求"
    assert "HRESULT do_rotate()" in src, "须有独立的重量切段执行函数"
    assert "extern \"C\" int adc_session_rotate(long long h)" in src, "须导出切段 ABI"
    assert "ADC_ROTATE_PENDING = 1" in src, "须定义切段请求返回码"


def test_move_file_write_through_removed():
    """[收尾慢根治回归·v20] 原子发布不得用 MOVEFILE_WRITE_THROUGH 强制刷盘。

    同卷改名是元数据操作、天然原子；WRITE_THROUGH 却强制把几十~上百 MB tmp
    刷到物理盘，慢盘/EDR 扫描下可达数十秒，是切段与收尾卡顿元凶。
    """
    src = _cpp()
    cw = src[src.index("HRESULT close_writer(bool publish)"):
             src.index("std::string out_dir_, stem_;")]
    code = "\n".join(ln.split("//")[0] for ln in cw.splitlines())
    assert "MoveFileExW(wt, wf, MOVEFILE_REPLACE_EXISTING)" in code, (
        "原子发布只需 MOVEFILE_REPLACE_EXISTING")
    assert "MOVEFILE_WRITE_THROUGH" not in code, "禁止 WRITE_THROUGH 强制刷盘"



def test_both_return_codes_defined_in_cpp():
    """[编译回归·v20-hotfix] write_video 用的两个返回码都必须在 C++ 侧定义。

    CI release #58 (commit 0fd3a7b) 因 667 行 `? ADC_ROTATE_PENDING : ADC_OK`
    里的 `ADC_OK` 只在 Python 定义、C++ 未定义而报 C2065 编译失败。
    ADC_OK / ADC_ROTATE_PENDING 必须与 backend/mf_native.py 严格对齐定义。
    """
    src = _cpp()
    assert "static const int ADC_OK = 0;" in src, (
        "C++ 必须定义 ADC_OK=0（否则 write_video 三元返回 C2065 编译失败）")
    assert "static const int ADC_ROTATE_PENDING = 1;" in src, (
        "C++ 必须定义 ADC_ROTATE_PENDING=1")
    # Python 侧须有对应定义，两边严格对齐
    import backend.mf_native as mn
    assert mn.ADC_OK == 0 and mn.ADC_ROTATE_PENDING == 1, (
        "Python 返回码须与 C++ 对齐：ADC_OK=0, ADC_ROTATE_PENDING=1")


def test_idr_sample_marked_clean_point_for_seek():
    """[快进花屏根治·v30] IDR sample 须打 CleanPoint，让 MP4 stss 含 seek 锚点。

    真机长录制成品：顺序播放正常、快进/拖进度条满屏马赛克条带。根因是从未
    给视频 sample 设 MFSampleExtension_CleanPoint，MP4 sink 生成的 stss 关键帧表
    缺随机访问点；seek 落到非 IDR 的 P 帧、缺参考帧解不出 → 花屏。历史
    FIX_NOTES v13 早已把"IDR 未设 CleanPoint"列为下一嫌疑。
    """
    src = _cpp()
    # ① push_sample 对 is_keyframe 的视频 sample 设 CleanPoint + Discontinuity
    ps = src[src.index("void push_sample("):src.index("// 段临时文件名")]
    code = "\n".join(ln.split("//")[0] for ln in ps.splitlines())
    assert "bool is_keyframe = false" in code, (
        "push_sample 须有 is_keyframe 参数（默认 false 向后兼容音频调用）")
    assert "if (!audio && is_keyframe)" in code, (
        "只对视频 IDR 设关键帧标记，避免误伤音频 sample")
    assert "MFSampleExtension_CleanPoint" in code, (
        "IDR sample 须设 CleanPoint，MP4 sink 才把它写进 stss 关键帧表")
    assert "MFSampleExtension_Discontinuity" in code, (
        "IDR sample 须设 Discontinuity，提示解码器参考链在此重置")


def test_flush_pending_au_detects_idr_nal_type5():
    """[快进花屏根治·v30] flush_pending_au 须检测 AU 内 IDR(NAL type=5) 并透传。

    只有正确识别 IDR 才能给对应 sample 打关键帧标记；若漏判则 stss 仍缺锚点。
    type=5 判断天然覆盖续流后新进程首帧 IDR，无需额外状态。
    """
    src = _cpp()
    fp = src[src.index("void flush_pending_au()"):src.index("void write_audio_block(")]
    code = "\n".join(ln.split("//")[0] for ln in fp.splitlines())
    assert "(nal[0] & 0x1F) == 5" in code, (
        "须按 H264 NAL type=5 识别 IDR（随机访问点）")
    assert "is_keyframe" in code, "flush_pending_au 须计算 is_keyframe 并传给 push_sample"
    # 确认 push_sample 调用确实把 is_keyframe 传下去（而非仅算未用）；
    # 调用跨多行，取 push_sample(...) 起到段落末尾的整体片段再判断。
    call_start = code.index("push_sample(vstream_")
    call_block = code[call_start:]
    assert "is_keyframe" in call_block, (
        "is_keyframe 必须透传给 push_sample，不能算了不用")
