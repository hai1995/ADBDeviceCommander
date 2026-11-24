/*
 * adc_mf_sink.cpp —— 同源录屏 native 实现（Windows only, x64）
 * =============================================================
 * 视频（设备端 screenrecord 输出的裸 H264 ES）与麦克风（本机 WASAPI capture）
 * 在**同一个 Media Foundation SinkWriter** 里按统一 QPC(100ns) 时基写入，
 * 直接产出 H264+AAC 的 MP4，去掉 ffmpeg 后处理。多设备并发时每设备一个
 * SinkWriter，麦克风采集一次后**广播**给所有会话（全场共用一条）。
 *
 * 依赖：仅 Windows 系统 DLL（mfplat/mfreadwrite/mf / ole32 / propsys /
 *       mmdevapi / avrt）。MSVC 编译。**无第三方二进制、无 GPL。**
 * 链接库：mfplat.lib mfreadwrite.lib mfuuid.lib ole32.lib propsys.lib
 *         uuid.lib advapi32.lib
 *
 * ┌─────────────────────────────────────────────────────────────────────┐
 * │ [NEEDS-VERIFY] 本文件在 Linux 沙箱内编写，无法用 MSVC 编译验证。     │
 * │ 必须在 Win11 x64 真机上按 Microsoft Learn 逐条核对：                 │
 * │  1. [已移除] 原用 moov 前置属性让 moov 写在 mdat 前，真机 Finalize   │
 * │     二次 seek/remux 时稳定报 E_ACCESSDENIED(0x80070005)。本地播放    │
 * │     无需 faststart，已改回 sink 默认的 moov-after-mdat 布局。         │
 * │  2. [已修复] H264 的 SPS/PPS（MF_MT_MPEG_SEQUENCE_HEADER）必须在      │
 * │     AddStream 前注入；旧实现在 create() 提前建首段 writer 致 header 空，│
 * │     真机首段收尾报 0xC00D4A45。已改为收到 SPS+PPS 后才创建首段 writer。│
 * │  3. 系统 AAC MFT 的 PCM 输入位深/采样率矩阵（音频已用 AAC 目标规避    │
 * │     裸 PCM 喂 MP4 sink 的 0xC00D4A45）。                              │
 * │  4. WASAPI 共享模式 + IAudioClient/IMMDeviceEnumerator 线程模型；    │
 * │     默认设备热切换（GetId 变化）重建 client 的时序。                 │
 * │  5. H264 ES 无内建时间戳：native 按 AU 顺序补 QPC 时间戳，60min 漂移 │
 * │     须实测；AAC 编码器是否要求 sample 严格等距。                     │
 * └─────────────────────────────────────────────────────────────────────┘
 */

#include "adc_mf_sink.h"

#include <windows.h>
#include <mfapi.h>
#include <mfidl.h>
#include <mfreadwrite.h>
#include <mferror.h>
#include <propsys.h>
#include <mmdeviceapi.h>
#include <audioclient.h>
#include <objbase.h>
#include <mmreg.h>       // WAVEFORMATEXTENSIBLE（SubFormat GUID 的权威偏移来源）
#include <string>
#include <vector>
#include <deque>
#include <mutex>
#include <atomic>
#include <cstdio>
#include <cstring>
#include <cwchar>
#include <cstddef>       // offsetof

#pragma comment(lib, "mfplat.lib")
#pragma comment(lib, "mfreadwrite.lib")
#pragma comment(lib, "mfuuid.lib")
#pragma comment(lib, "ole32.lib")
#pragma comment(lib, "propsys.lib")
#pragma comment(lib, "uuid.lib")
#pragma comment(lib, "advapi32.lib")

#define IF_FAILED_RETURN(hr, msg) do { HRESULT __hr = (hr); if (FAILED(__hr)) { set_error(__hr, msg); return __hr; } } while (0)

/* [构建指纹] 每次改动本文件语义时必须更新本串。Python 在启动提示里显示，
 * 真机日志据此判断运行的是不是重新编译过的 DLL —— 本文件所有修复都必须
 * 重新 cmake --build + cmake --install 才会生效。 */
static const char* const kBuildId = "mf-20261124-drain-v14";

extern "C" const char* adc_build_id(void) { return kBuildId; }

static std::mutex g_err_mtx;
static std::string g_last_error;

static void set_error(HRESULT hr, const char* what) {
    char buf[64];
    _snprintf_s(buf, sizeof(buf), "HRESULT 0x%08X", (unsigned int)hr);
    std::lock_guard<std::mutex> lk(g_err_mtx);
    g_last_error = std::string(what ? what : "MF 错误") + "（" + buf + "）";
}
static void set_error_text(const char* what) {
    std::lock_guard<std::mutex> lk(g_err_mtx);
    g_last_error = what ? what : "未知错误";
}
/* [诊断 v8] 0xC00D4A45 分路定位：把每路 WriteSample 实际成功数、各自最后一次
 * HRESULT、AAC 真实配置、SPS/PPS/seq-header 长度、float32 转换状态全写进错误文本。
 * 关键区别：a=是"尝试写入的 PCM 采样帧"，而 aws=是 AAC 流真正 WriteSample 成功的
 * 次数 —— 若 aws=0 说明 AAC 编码链一个样本都没被 sink 接受（esds 根因在音频）；
 * vws=0 则是视频流（avcC 根因）。两者区分后即可一锤定音，不再盲修。 */
static void append_error_stats(long long vb, long long af, long long dr,
                               long long vws, long long aws, long long vwf, long long awf,
                               HRESULT vlhr, HRESULT alhr, int ar, int ac, int ab,
                               int sps, int pps, int seqh, int flt, int ovf, int uns,
                               long long vfc, HRESULT vsim) {
    char buf[768];
    _snprintf_s(buf, sizeof(buf),
        " [诊断 v=%lldB a=%lldF d=%lld | vws=%lld vwf=%lld vlhr=0x%08X | "
        "aws=%lld awf=%lld alhr=0x%08X | aac=%dHz/%dch/%dbit | sps=%dB pps=%dB seqh=%dB | "
        "f32=%d ovf=%d uns=%d vfc=%lld vsim=0x%08X]",
        vb, af, dr,
        vws, vwf, (unsigned int)vlhr,
        aws, awf, (unsigned int)alhr,
        ar, ac, ab,
        sps, pps, seqh,
        flt, ovf, uns, vfc, (unsigned int)vsim);
    std::lock_guard<std::mutex> lk(g_err_mtx);
    g_last_error += buf;
}

extern "C" int adc_last_error(char* out, int out_cap) {
    if (!out || out_cap <= 0) return 0;
    std::lock_guard<std::mutex> lk(g_err_mtx);
    size_t n = g_last_error.size();
    if ((int)n > out_cap - 1) n = (size_t)(out_cap - 1);
    memcpy(out, g_last_error.c_str(), n);
    out[n] = '\0';
    return (int)n;
}

/* ------------------------- 全局 MF 生命周期 --------------------------- */

static void qpc_init();   // 前向声明（定义在"QPC 时基"小节）

static std::atomic<bool> g_mf_ready{false};
static DWORD g_owner_tid = 0;

extern "C" int adc_init(void) {
    // COM 单元：MTA 专用 worker 线程。若调用线程已 STA，返回 RPC_E_CHANGED_MODE，
    // 交给 Python 转中文提示——这就是"GUI 线程直接初始化立刻失败"的根因处理。
    HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (hr == RPC_E_CHANGED_MODE) {
        set_error_text("媒体基础必须在多线程单元(MTA)初始化：当前线程已是 STA。"
                       "请在专用后台 worker 线程初始化，不要在 UI 线程调用。");
        return (int)(HRESULT)RPC_E_CHANGED_MODE;
    }
    if (FAILED(hr) && hr != S_FALSE) { set_error(hr, "CoInitializeEx(MTA) 失败"); return (int)hr; }
    hr = MFStartup(MF_VERSION, MFSTARTUP_NOSOCKET);
    if (FAILED(hr)) { set_error(hr, "MFStartup 失败"); CoUninitialize(); return (int)hr; }
    qpc_init();   // 无论有没有麦克风都要初始化时基
    g_mf_ready.store(true);
    g_owner_tid = GetCurrentThreadId();
    return 0;
}

extern "C" void adc_shutdown(void) {
    if (!g_mf_ready.load()) return;
    if (g_owner_tid && GetCurrentThreadId() != g_owner_tid) {
        set_error_text("adc_shutdown 必须在 adc_init 的同一线程调用（线程关联错误，已跳过）");
        return;
    }
    MFShutdown();
    CoUninitialize();
    g_mf_ready.store(false);
    g_owner_tid = 0;
}

/* ------------------- QPC 时基 / annex-B 工具 -------------------------- */

static LARGE_INTEGER g_qpc_freq = {0};
static LARGE_INTEGER g_qpc_origin = {0};
static std::mutex g_qpc_mtx;

void qpc_init() {
    std::lock_guard<std::mutex> lk(g_qpc_mtx);
    if (g_qpc_freq.QuadPart == 0) {
        QueryPerformanceFrequency(&g_qpc_freq);
        QueryPerformanceCounter(&g_qpc_origin);
    }
}
static LONGLONG qpc_now_hns() {
    LARGE_INTEGER now; QueryPerformanceCounter(&now);
    std::lock_guard<std::mutex> lk(g_qpc_mtx);
    if (g_qpc_freq.QuadPart == 0) return 0;
    return (now.QuadPart - g_qpc_origin.QuadPart) * 10000000LL / g_qpc_freq.QuadPart;
}

/* annex-B → 单个 NAL（去起始码，保留 NAL header）。返回 NAL type 或 -1。 */
static int next_annexb_nal(const unsigned char* p, size_t len, size_t& pos,
                           const unsigned char** nal, size_t& nal_len) {
    while (pos + 3 <= len) {
        size_t sc = 0;
        if (p[pos] == 0 && p[pos+1] == 0 && p[pos+2] == 1) sc = 3;
        else if (pos + 4 <= len && p[pos] == 0 && p[pos+1] == 0 &&
                 p[pos+2] == 0 && p[pos+3] == 1) sc = 4;
        if (!sc) { ++pos; continue; }
        size_t start = pos + sc, end = start;
        // [根因修复 v13·花屏] 原循环 `while (end + 3 <= len)` 在 buffer 末尾会
        // 提前 2 字节退出：end 最多停在 len-3，导致每条 NAL 尾部被截掉 1~2 个
        // 真实载荷字节。切片(slice)尾部被截 → 解码出现马赛克/花屏。本地 ffmpeg
        // 实证：17/17 条 NAL 被截、帧解码报 non-existing PPS；改为扫到 len 并对
        // 起始码判断逐项加长度守卫后 0/17 截断、15 帧全部正常解码。
        while (end < len) {
            if (end + 3 <= len && p[end] == 0 && p[end+1] == 0 && p[end+2] == 1) break;
            if (end + 4 <= len && p[end] == 0 && p[end+1] == 0 &&
                p[end+2] == 0 && p[end+3] == 1) break;
            ++end;
        }
        // end 已指向本 NAL 结束处（下一个起始码前，或数据块末尾）
        while (end > start && p[end-1] == 0) --end;   // trailing zero
        pos = end;
        *nal = p + start;
        nal_len = end - start;
        if (nal_len == 0) return -1;
        return (*nal)[0] & 0x1F;
    }
    return -1;
}

/* [根因修复 v12] Annex B 格式：微软 MPEG-4 文件接收器文档明确要求
 * "For h264/h265, MF_MT_MPEG_SEQUENCE_HEADER blob contains concatenated NAL
 *  units in Annex B format, along with their start codes"、以及
 * "bitstream must conform to H.264 Annex B: NALUs separated by 3/4-byte start
 *  codes"。此前实现把序列头和样本都改成 AVCC(4 字节长度前缀)，与文档相反：
 * sink 在 mdat 里原样写入了 AVCC 字节、找不到任何 AnnexB 起始码，视频流始终
 * 无法被解析 → WriteSample 从首帧后全报 E_UNEXPECTED(0x8000FFFF)、Finalize
 * 生成不了 avcC/stsd → 0xC00D4A45。改为统一输出 4 字节起始码的 AnnexB。 */
static const unsigned char kAnnexBStartCode[4] = {0x00, 0x00, 0x00, 0x01};

static void append_annexb_nal(std::vector<unsigned char>& out,
                              const std::vector<unsigned char>& nal) {
    if (nal.empty()) return;
    out.insert(out.end(), kAnnexBStartCode, kAnnexBStartCode + 4);
    out.insert(out.end(), nal.begin(), nal.end());
}

/* SPS/PPS → AnnexB 序列头：[00 00 00 01][SPS][00 00 00 01][PPS] */
static std::vector<unsigned char> make_seq_header(const std::vector<unsigned char>& sps,
                                                  const std::vector<unsigned char>& pps) {
    std::vector<unsigned char> h;
    append_annexb_nal(h, sps);
    append_annexb_nal(h, pps);
    return h;
}

/* 一个完整 AU 的所有 NAL → AnnexB 样本：[SC][NAL]... */
static std::vector<unsigned char> to_annexb(const std::vector<std::vector<unsigned char>>& nals) {
    std::vector<unsigned char> out;
    for (const auto& nal : nals) append_annexb_nal(out, nal);
    return out;
}

/* ------------------- 音频：WASAPI capture + 广播 ---------------------- */

struct AudioBlock {
    std::vector<unsigned char> pcm;
    LONGLONG ts_hns;
    LONGLONG dur_hns;
};
static const LONGLONG AUDIO_QUEUE_LIMIT_HNS = 5 * 10000000LL;   // 5s 上限

/* [修复-0xC00D4A45] 判断 WASAPI mix format 是否为 IEEE float。
 * Windows AAC 编码器的输入只接受 MFAudioFormat_PCM / 16-bit；但 WASAPI 共享
 * 模式 GetMixFormat 默认返回 32-bit float。旧实现把 float32 原始字节当成
 * PCM/32bit 喂给 AAC 编码器，WriteSample 失败被静默计 dropped_，音频流全程
 * 0 sample → sink 生成不了 esds(AudioSpecificConfig) box → Finalize 报
 * 0xC00D4A45。这里用数值常量判断源格式，避免新增 ksmedia 头文件依赖。
 *
 * [二次修复-静音] WAVE_FORMAT_EXTENSIBLE 的 SubFormat(GUID) 并非紧跟在
 * WAVEFORMATEX 之后，中间还隔着 Samples(WORD) + dwChannelMask(DWORD) 共 6 字节：
 *   offsetof(WAVEFORMATEXTENSIBLE, SubFormat) == 24（packed）/ 28（默认对齐）
 * 旧代码用 `f + sizeof(WAVEFORMATEX)`(=18) 读 GUID，实际读到的是 Samples 和
 * dwChannelMask 的字节，memcmp 永不命中。后果：现代 Windows 共享模式最常见的
 * "EXTENSIBLE + 32-bit IEEE float" 被误判成「不支持的位深」→ 全程静音，上一轮
 * 的 float32→PCM16 转换形同虚设。改用 offsetof 精确定位，并把 cbSize 下限按
 * SDK 文档规定的 22 字节校验（旧值 sizeof(GUID)=16 过宽，可能越过缓冲区读）。 */
static bool is_ieee_float_format(const WAVEFORMATEX* f) {
    if (!f) return false;
    if (f->wFormatTag == 0x0003 /* WAVE_FORMAT_IEEE_FLOAT */) return true;
    if (f->wFormatTag == 0xFFFE /* WAVE_FORMAT_EXTENSIBLE */ &&
        f->cbSize >= 22 /* SDK: WAVE_FORMAT_EXTENSIBLE 的 cbSize 至少 22 */) {
        // KSDATAFORMAT_SUBTYPE_IEEE_FLOAT = {00000003-0000-0010-8000-00AA00389B71}
        static const GUID k_float_sub = {
            0x00000003, 0x0000, 0x0010,
            {0x80, 0x00, 0x00, 0xAA, 0x00, 0x38, 0x9B, 0x71}};
        // SubFormat 相对结构起点有 Samples(2B)+dwChannelMask(4B) 的前缀，绝不能拿
        // WAVEFORMATEX 结构本身的大小当偏移：那会读在 Samples/mask 上，永远匹配不到 GUID。
        const GUID* sub = reinterpret_cast<const GUID*>(
            reinterpret_cast<const BYTE*>(f)
            + offsetof(WAVEFORMATEXTENSIBLE, SubFormat));
        if (memcmp(sub, &k_float_sub, sizeof(GUID)) == 0) return true;
    }
    return false;
}

/* float32 [-1,1] → 16-bit PCM，clamp 防溢出并兼治 NaN。
 * 输出写进 out（交错声道，小端），样本数 = frames * channels。 */
static void float32_to_pcm16(const BYTE* src, size_t frames, int channels,
                             std::vector<unsigned char>& out) {
    size_t count = frames * (size_t)channels;
    out.resize(count * 2);
    const float* s = reinterpret_cast<const float*>(src);
    for (size_t i = 0; i < count; ++i) {
        float v = s[i];
        // NaN 时 (v > -1.0f) 为 false → 落入 -1.0f 分支；顺带 clamp 下界。
        short iv;
        if (!(v > -1.0f)) iv = -32768;
        else if (v > 1.0f) iv = 32767;
        else iv = (short)(v < 0 ? v * 32768.0f : v * 32767.0f);
        memcpy(out.data() + i * 2, &iv, 2);
    }
}

/* 订阅者：每个 RecordSession 一个，采集到的 PCM 广播给所有订阅者。 */
class AudioSink {
public:
    virtual ~AudioSink() {}
    virtual void on_audio(const AudioBlock& blk) = 0;
};

class AudioCapture {
public:
    AudioCapture() : running_(false), stop_(false), thread_(nullptr),
                     device_events_(0), rate_(0), bits_(0), channels_(0) {}
    ~AudioCapture() { stop(); }

    int start(const wchar_t* endpoint_id, int rate, int bits, int channels) {
        if (running_.load()) return 0;
        HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
        if (FAILED(hr) && hr != RPC_E_CHANGED_MODE && hr != S_FALSE) {
            set_error(hr, "WASAPI 线程 CoInitializeEx 失败"); return (int)hr;
        }
        stop_.store(false);
        fmt_ready_.store(false);   // 新一轮录制：格式需重新回读，避免拿到上一次的陈旧值
        endpoint_id_ = endpoint_id ? endpoint_id : L"";
        want_rate_ = rate; want_bits_ = bits; want_ch_ = channels;
        thread_ = CreateThread(nullptr, 0, &AudioCapture::thread_proc, this, 0, nullptr);
        if (!thread_) { set_error_text("创建音频采集线程失败"); return (int)HRESULT_FROM_WIN32(GetLastError()); }
        running_.store(true);
        return 0;
    }
    void stop() {
        if (!running_.exchange(false)) return;
        stop_.store(true);
        if (thread_) { WaitForSingleObject(thread_, 5000); CloseHandle(thread_); thread_ = nullptr; }
    }
    int format(int* r, int* b, int* c) {
        // [修复] mic_start() 只负责 CreateThread 就立即返回；真实 mix format 要等
        // 采集线程跑 GetMixFormat 才有。若此刻直接回读，rate_/bits_/channels_ 仍
        // 是初始的 0 —— 会话用它建音频流时 MF_MT_AUDIO_SAMPLES_PER_SECOND=0，
        // AddStream 失败，导致整场同源录制根本无法启动（启动竞态）。
        // 这里等格式就绪（有界 ~3s），拿不到就明确报错让 Python 回退，绝不返回 0。
        for (int i = 0; i < 300 && !fmt_ready_.load(); ++i) Sleep(10);
        if (!fmt_ready_.load()) {
            set_error_text("麦克风采集线程未在 3s 内回读到 PCM 格式"
                           "（无输入设备 / 设备被占用 / 权限未授予？）");
            return MF_E_UNEXPECTED;
        }
        std::lock_guard<std::mutex> lk(fmt_mtx_);
        *r = rate_; *b = bits_; *c = channels_; return 0;
    }
    int device_events() const { return device_events_.load(); }
    // 诊断：采集到 AAC 编码器不支持的源位深（已静音降级，不会让 Finalize 失败）
    bool unsupported_src() const { return unsupported_src_.load(); }

    void subscribe(AudioSink* s) { std::lock_guard<std::mutex> lk(subs_mtx_); subs_.push_back(s); }
    void unsubscribe(AudioSink* s) {
        std::lock_guard<std::mutex> lk(subs_mtx_);
        subs_.erase(std::remove(subs_.begin(), subs_.end(), s), subs_.end());
    }

private:
    static DWORD WINAPI thread_proc(LPVOID self) {
        ((AudioCapture*)self)->capture_loop();
        return 0;
    }

    void publish(const AudioBlock& blk) {
        std::lock_guard<std::mutex> lk(subs_mtx_);
        for (AudioSink* s : subs_) s->on_audio(blk);   // 广播，所有设备各持副本
    }

    void capture_loop() {
        // [修复] 本方法运行在 CreateThread 新建的采集线程上，COM 单元不继承
        // 调用线程的状态 —— 必须在本线程自行初始化 MTA，否则下面的
        // CoCreateInstance(MMDeviceEnumerator) 直接返回 CO_E_NOTINITIALIZED，
        // 音频全程静音。退出时配对 CoUninitialize。
        HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
        if (FAILED(hr) && hr != RPC_E_CHANGED_MODE && hr != S_FALSE) {
            set_error(hr, "WASAPI 采集线程 CoInitializeEx(MTA) 失败"); return;
        }
        bool com_inited = SUCCEEDED(hr);   // S_FALSE/RPC_E_CHANGED_MODE 不需本线程反初始化
        // [NEEDS-VERIFY] 显式 capture endpoint / 禁用 loopback / 热切换重建。
        // 共享模式只采麦克风（不设 AUDCLNT_STREAMFLAGS_LOOPBACK，绝不混入回放声）。
        // 每 200ms 检查默认设备 GetId 是否变化，变化则重建 IAudioClient，
        // 期间持续 publish，不静音、不崩。
        IMMDeviceEnumerator* enumerator = nullptr;
        hr = CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL,
                              __uuidof(IMMDeviceEnumerator), (void**)&enumerator);
        if (FAILED(hr)) {
            set_error(hr, "创建 IMMDeviceEnumerator 失败");
            if (com_inited) CoUninitialize();
            return;
        }

        std::wstring current_id;
        while (!stop_.load()) {
            IMMDevice* dev = nullptr;
            hr = endpoint_id_.empty()
                ? enumerator->GetDefaultAudioEndpoint(eCapture, eMultimedia, &dev)
                : enumerator->GetDevice(endpoint_id_.c_str(), &dev);
            if (FAILED(hr) || !dev) { device_events_.fetch_add(1); Sleep(300); continue; }

            LPWSTR id = nullptr; dev->GetId(&id);
            bool changed = id && (current_id != id);
            if (changed) {
                current_id = id;
                device_events_.fetch_add(1);
                // 回读真实 PCM 格式给 Python（Python 用 adc_mic_format 建会话音频流）。
                IAudioClient* tmpc = nullptr;
                if (SUCCEEDED(dev->Activate(__uuidof(IAudioClient), CLSCTX_ALL, nullptr, (void**)&tmpc))) {
                    WAVEFORMATEX* f = nullptr;
                    if (SUCCEEDED(tmpc->GetMixFormat(&f)) && f) {
                        {
                            std::lock_guard<std::mutex> lk(fmt_mtx_);
                            // [修复-0xC00D4A45] 对外统一报告 16-bit PCM：采集线程
                            // 会把 float32 mix 转成 PCM16 再写入 AAC 编码器，Python
                            // 用这里回读的格式建会话音频流，必须与写入样本一致。
                            rate_ = f->nSamplesPerSec; bits_ = 16; channels_ = f->nChannels;
                        }
                        fmt_ready_.store(true);   // 唤醒等待中的 format()
                        CoTaskMemFree(f);
                    }
                    tmpc->Release();
                }
            }
            if (id) CoTaskMemFree(id);

            hr = capture_until_change(dev);
            dev->Release();
            if (FAILED(hr) && !stop_.load()) Sleep(200);
        }
        enumerator->Release();
        if (com_inited) CoUninitialize();
    }

    /* 对一个设备持续采集，直到：stop / 默认设备变化 / 错误。 */
    HRESULT capture_until_change(IMMDevice* dev) {
        IAudioClient* client = nullptr;
        HRESULT hr = dev->Activate(__uuidof(IAudioClient), CLSCTX_ALL, nullptr, (void**)&client);
        if (FAILED(hr)) return hr;
        WAVEFORMATEX* fmt = nullptr;
        hr = client->GetMixFormat(&fmt);
        if (FAILED(hr)) { client->Release(); return hr; }

        // [修复-0xC00D4A45] 记住 WASAPI mix format 的真实位深/类型，采集时把
        // float32 转成 PCM16 再写入 AAC 编码器；对外只报告 16-bit PCM。
        // 原实现把 float32 原始字节按 bits_(=32) 打包，声明 subtype=PCM，
        // AAC MFT 拒绝 32-bit 整型 PCM → WriteSample 全失败被吞成 dropped_ →
        // 音频流 0 sample → sink 生成不了 esds box → Finalize 报 0xC00D4A45。
        const bool src_float = is_ieee_float_format(fmt);
        const int src_bits = (int)fmt->wBitsPerSample;
        const int src_channels = (int)fmt->nChannels;
        const UINT32 src_align = (UINT32)(src_channels * src_bits / 8);
        {
            std::lock_guard<std::mutex> lk(fmt_mtx_);
            rate_ = fmt->nSamplesPerSec; bits_ = 16; channels_ = src_channels;
        }
        fmt_ready_.store(true);   // 唤醒等待中的 format()
        REFERENCE_TIME dur = 10000000; // 1s 缓冲（共享模式）
        // IAudioClient::Initialize 仍必须用设备原始 mix format（float32 等），
        // 转换只发生在 publish 前，不影响 WASAPI 采集本身。
        hr = client->Initialize(AUDCLNT_SHAREMODE_SHARED, AUDCLNT_STREAMFLAGS_EVENTCALLBACK,
                                dur, 0, fmt, nullptr);
        CoTaskMemFree(fmt);
        if (FAILED(hr)) { client->Release(); return hr; }
        IAudioCaptureClient* cap = nullptr;
        hr = client->GetService(__uuidof(IAudioCaptureClient), (void**)&cap);
        if (FAILED(hr)) { client->Release(); return hr; }
        HANDLE evt = CreateEvent(nullptr, FALSE, FALSE, nullptr);
        client->SetEventHandle(evt);
        client->Start();

        while (!stop_.load()) {
            DWORD wait = WaitForSingleObject(evt, 200);
            if (wait == WAIT_TIMEOUT) continue;   // 每 200ms 回到循环，外层可重查设备
            if (wait != WAIT_OBJECT_0) break;
            UINT32 n = 0; DWORD flags = 0; BYTE* data = nullptr; UINT64 devpos = 0, ts = 0;
            while (SUCCEEDED(cap->GetBuffer(&data, &n, &flags, &devpos, &ts))) {
                if (!n) { cap->ReleaseBuffer(n); break; }
                AudioBlock blk;
                blk.ts_hns = qpc_now_hns();
                blk.dur_hns = (LONGLONG)n * 10000000LL / rate_;
                if (flags & AUDCLNT_BUFFERFLAGS_SILENT) {
                    // 静音帧：直接产出 PCM16 全零（2 字节/样本）
                    blk.pcm.assign((size_t)n * (size_t)src_channels * 2, 0);
                } else if (src_float && src_bits == 32) {
                    float32_to_pcm16(data, n, src_channels, blk.pcm);
                } else if (src_bits == 16) {
                    // 设备本来就是 16-bit PCM：原样拷贝
                    blk.pcm.assign(data, data + (size_t)n * src_align);
                } else {
                    // 其它位深（24/32-bit 整型等）：本编码器不支持的源，
                    // 静音代替并计数，绝不把错位深的字节喂给 AAC 触发 Finalize 失败。
                    unsupported_src_.store(true);
                    blk.pcm.assign((size_t)n * (size_t)src_channels * 2, 0);
                }
                cap->ReleaseBuffer(n);
                publish(blk);   // 广播：每个订阅会话自行判 5s 上限
            }
        }
        client->Stop();
        CloseHandle(evt);
        cap->Release(); client->Release();
        return S_OK;
    }

    std::atomic<bool> running_, stop_;
    HANDLE thread_;
    std::wstring endpoint_id_;
    int want_rate_, want_bits_, want_ch_;
    int rate_, bits_, channels_;
    std::atomic<bool> fmt_ready_{false};   // 采集线程是否已回读到真实 mix format
    std::atomic<bool> unsupported_src_{false};  // 出现 AAC 不支持的源位深（诊断）
    std::mutex fmt_mtx_;
    std::atomic<int> device_events_;
    std::vector<AudioSink*> subs_;
    std::mutex subs_mtx_;
};

static AudioCapture g_audio;

extern "C" int adc_mic_start(const wchar_t* endpoint_id, int rate, int bits, int channels) {
    qpc_init();
    return g_audio.start(endpoint_id, rate, bits, channels);
}
extern "C" void adc_mic_stop(void) { g_audio.stop(); }
extern "C" int adc_mic_format(int* r, int* b, int* c) { return g_audio.format(r, b, c); }
extern "C" int adc_mic_device_events(void) { return g_audio.device_events(); }

/* ------------------- 录制会话：SinkWriter + 分段 ---------------------- */

class RecordSession : public AudioSink {
public:
    RecordSession(const std::string& out_dir, const std::string& stem,
                  int width, int height, int fps_num, int fps_den,
                  int arate, int abits, int ach)
        : out_dir_(out_dir), stem_(stem), width_(width), height_(height),
          fps_num_(fps_num > 0 ? fps_num : 30), fps_den_(fps_den > 0 ? fps_den : 1),
          arate_(arate), abits_(abits), ach_(ach),
          writer_(nullptr), vstream_(0), astream_(0), writing_(false),
          seg_no_(0), seg_start_hns_(0),
          video_bytes_(0), audio_frames_(0), dropped_(0), queue_peak_ms_(0),
          queued_hns_(0), last_audio_end_(0), video_frame_count_(0),
          vws_(0), aws_(0), vwf_(0), awf_(0), vlhr_(S_OK), alhr_(S_OK),
          diag_vsim_(S_OK),
          diag_sps_(0), diag_pps_(0), diag_seqh_(0) {}

    ~RecordSession() { unsubscribe_(); close_writer(false); }

    int create(std::string& first_tmp) {
        // [修复] 必须同步置位 subscribed_，否则 unsubscribe_() 里的
        // `if (!subscribed_) return` 永远跳过真正的退订，session 销毁后
        // 采集线程仍持有本对象指针并回调 on_audio → use-after-free 崩溃。
        g_audio.subscribe(this);
        subscribed_.store(true);
        // [修复-首段 0xC00D4A45] 首段 writer 不再在此提前创建。此刻还没有视频帧，
        // SPS/PPS 为空；若此时 AddStream 视频流，config_video_stream 无法注入
        // MF_MT_MPEG_SEQUENCE_HEADER，MP4 sink 在 Finalize 时生成不了 stsd box →
        // 报 0xC00D4A45（"required headers were not provided to the sink"）。
        // 改为只预算首段临时名返回上层（纯字符串，前端展示用），writer 延迟到
        // write_video 收到 SPS+PPS 后在其中内联创建。第 2 段起 check_rotate
        // 正常切段、缓存已有 SPS/PPS，不受影响。
        first_tmp = seg_tmp_path(1);
        return 0;
    }

    /* AudioSink：采集线程回调，把 PCM 放进本会话的有界队列。 */
    void on_audio(const AudioBlock& blk) override {
        std::lock_guard<std::mutex> lk(audio_q_mtx_);
        if (finalized_ || discarded_) return;
        // [修复-收尾慢] 队列累计时长用原子计数维护，O(1)；原实现每次回调遍历
        // 整个 audio_q_ 求和，长录制队列积压时采集线程被 O(n) 遍历拖慢，入队
        // 竞争 audio_q_mtx_ 的时间变长，间接放大 drain 锁竞争。语义完全等价：
        // 入队 +=，drain 移出 -=，overflow 判定用同一个累计值。
        LONGLONG queued = queued_hns_;
        if (queued + blk.dur_hns > AUDIO_QUEUE_LIMIT_HNS) {
            // [修复-真机 overflow] 原实现置 overflow_=true 并让 finalize 直接失败，
            // 结果是整段视频报废（.tmp 不发布、无 moov、无法播放）——为了几秒钟
            // 的音频积压毁掉用户一分多钟的录制，代价完全不可接受。改为**丢弃当前
            // 音频块并计数**：队列恒有界（≤5s），不再有致命 overflow；视频/已入队
            // 音频照常 finalize 成可播放的 MP4。dropped_ 会在 stats 里暴露，便于
            // 事后诊断音频是否曾经积压。定时器每 200ms 排空，正常情况永不触发此处。
            overflow_.store(true);   // 保留为诊断标记，不再让 finalize 失败
            dropped_++;
            return;
        }
        audio_q_.push_back(blk);
        queued_hns_ = queued + blk.dur_hns;
        LONGLONG peak = queued_hns_ / 10000;
        if (peak > queue_peak_ms_) queue_peak_ms_ = (int)peak;
    }

    int write_video(const unsigned char* data, int len) {
        if (finalized_ || discarded_) return E_FAIL;
        video_bytes_ += len;
        // [修复] 每个视频 sample 到来时顺带把音频队列排空写入 writer。
        // 原实现只在 finalize 才 drain，但采集线程一直在入队、又有 5s 上限，
        // 于是任何超过 5s 的录制都会 overflow 失败 —— 等于录不了长视频。
        // 视频帧由 screenrecord 持续产出（~30fps），借此周期性 drain 音频，
        // 队列正常只积压一帧时间（~33ms），5s 上限退化为真正的"卡死保护"。
        // 注意：write_video 由 MTA worker 线程调用，与 finalize 同一线程，
        // 满足 SinkWriter 单线程写入约束。
        drain_audio_queued();
        // [修复-首段 0xC00D4A45] SPS/PPS 到达后、写首个视频 sample 之前，
        // 若 writer 尚未创建（首段被延迟），此刻创建：config_video_stream 能
        // 从缓存注入 sequence header，从根上消除 Finalize 缺 header 的错误。
        // video_bytes_ 已累加首字节，音频可能已入队，但都只是内存缓冲，writer
        // 一建好即可正常写入（音频块在 writer 创建前 drain 会被跳过，下个 tick
        // 继续，不丢）。SPS/PPS 可能分帧到达，故每帧都检查，两者齐备才建。
        if (!writer_) {
            bool have_seq = false;
            {
                std::lock_guard<std::mutex> lk(seq_mtx_);
                have_seq = !sps_.empty() && !pps_.empty();
            }
            if (have_seq) {
                std::string dummy;
                HRESULT hr = ensure_writer(dummy);
                if (FAILED(hr)) return (int)hr;
            }
        }
        size_t pos = 0;
        const unsigned char* p = data;
        size_t total = (size_t)len;
        while (pos < total) {
            const unsigned char* nal = nullptr; size_t nal_len = 0;
            int type = next_annexb_nal(p, total, pos, &nal, nal_len);
            if (type < 0 || !nal) break;
            std::vector<unsigned char> n(nal, nal + nal_len);
            if (type == 7) {           // SPS：缓存，供首段 writer 注入 sequence header
                std::lock_guard<std::mutex> lk(seq_mtx_);
                sps_ = n;
                continue;
            }
            if (type == 8) {           // PPS
                std::lock_guard<std::mutex> lk(seq_mtx_);
                pps_ = n;
                continue;
            }
            if (type == 9) {           // AUD：显式 AU 边界，冲刷上一帧
                flush_pending_au();
                continue;
            }
            // 新的 VCL NAL 到来且当前 AU 已有 VCL，说明上一帧结束。
            if (type >= 1 && type <= 5 && has_vcl(pending_au_)) flush_pending_au();
            // SEI/SPS-ext/PPS-ext 等非 VCL 与随后的 VCL 必须留在同一个样本里，
            // 微软要求样本包含"单个呈现时间对应的全部切片与数据 NALU"。
            pending_au_.push_back(std::move(n));
        }
        // [根因修复 v12] 不在每个 native 调用末尾 flush：Python 侧每次只送一条
        // NAL，一帧的 AUD/SEI/VCL 常跨多次调用，旧实现把 SEI 等纯非 VCL 单独
        // 写成样本，sink 收到无效 AU 后进入 sticky 错误态。改为跨调用累积，
        // 只在 AU 边界 / 切段 / 收尾冲刷（见 flush_pending_au 调用点）。
        return check_rotate();
    }

    int mark_mic_stop() { mic_stopped_.store(true); return 0; }

    // [修复-真机 overflow] 音频队列的排空不能再只靠 write_video 驱动：
    // 真机上 screenrecord 的 H264 流可能长时间稀疏甚至中断（录制 1min+ 只写出
    // 几十 KB），此时 write_video 极少被调用，音频采集线程持续入队 → 队列 5s
    // 积压 → overflow → finalize 失败 → .tmp.mp4 不发布/无 moov → 视频报废。
    // 改为由 Python 层定时器经 worker 线程（满足 SinkWriter 单线程约束）周期性
    // 调用本方法主动排空，音频写入与视频帧解耦。定时器在 worker 线程执行，
    // 与 write_video/finalize 串行，无数据竞争。
    int drain_audio_tick() { drain_audio_queued(); return 0; }

    /* 只把队列里已有的音频块写入 writer（不补静音）。由 write_video 高频
     * 调用，也由 finalize 在补静音前调用一次。写完后 last_audio_end_ 记录
     * 最后一块的结束时刻，供补静音使用。 */
    void drain_audio_queued() {
        // [修复-收尾慢/排空超时] 关键：绝不能持 audio_q_mtx_ 做 WriteSample。
        // 旧实现在锁内逐块 write_audio_block（内含同步的 MF SinkWriter::WriteSample
        // → AAC 编码），高负载下单次可达数十毫秒；持锁期间 WASAPI 采集线程 on_audio
        // 被堵在锁外 → 入队延迟 → worker 队列里的 drain 调用堆积 → 某次排空卡满 15s
        // → Python 报"MF worker 调用超时"并停止排空，同时 finalize 排队 → 收尾变慢。
        // 修复：持锁只做 O(1) 的 buffer swap（拿走全部待写块），立即释放锁，再在锁外
        // 逐块 WriteSample。采集线程入队与编码解耦，锁竞争降到最低。块顺序/时间戳不变。
        std::deque<AudioBlock> batch;   // 类型须与 audio_q_ 一致，swap 才能编译
        {
            std::lock_guard<std::mutex> lk(audio_q_mtx_);
            // [修复-真机 overflow] 删除 `if (overflow_.load()) return;`：overflow_ 现在
            // 只是"曾丢过音频块"的诊断标记，不能再阻断排空，否则队列里已入队的音频会
            // 永远留在内存、收尾也写不进成片。丢弃策略在 on_audio 已完成，这里只管把
            // 队列里剩下的块正常写入。
            // [修复-首段延迟创建] writer 未建（等 SPS/PPS）时不取块：write_audio_block
            // 会因 !writer_ 静默丢弃导致开头音频丢失；留在有界队列，下个 tick 再写。
            if (!writer_) return;
            batch.swap(audio_q_);      // 一次性拿走全部待写块，锁内只做指针交换
            queued_hns_ = 0;           // 队列已空，累计时长归零（与 on_audio 同锁维护）
        }
        // 锁外执行同步编码；audio_frames_ / last_audio_end_ 只由 worker 线程访问，无竞态。
        for (const AudioBlock& blk : batch) {
            write_audio_block(blk);
            // 采集端已统一转 PCM16，帧数按 16-bit block align 统计（与写入格式一致）
            audio_frames_ += (LONGLONG)(blk.pcm.size() / (size_t)(ach_ * 16 / 8));
            LONGLONG this_end = blk.ts_hns + blk.dur_hns;
            if (this_end > last_audio_end_) last_audio_end_ = this_end;
        }
    }

    /* 最终排空 + 补静音到 stop 时刻（不改已有时间戳）。 */
    int drain_audio() {
        // [修复-真机 overflow] 移除 overflow 致命分支：即使中途丢过音频块，也要
        // 把队列里剩的正常写入并 close_writer 发布成可播放 MP4。丢块数由 dropped_
        // 统计暴露（stats），用户保住视频远比"因几秒音频积压整段报废"重要。
        drain_audio_queued();
        // [修复-0xC00D4A45 第二根因] 旧实现对 last_audio_end_ 正值门控，导致
        // "全程没有任何音频块写入"(麦克风设备无声/被占用)时该值恒为 0，
        // 补静音被整体跳过 → AAC 流一个 sample 都没有 → sink 生成不了 esds
        // → Finalize 报 0xC00D4A45。改为：从未写入音频时从段起点补一段保底
        // 静音，确保 AAC 编码器至少编码出 1 帧、产出 header。
        // 上限 2s：长录制全程无声时若一路补到 stop 会分配数百 MB 静音而 OOM；
        // 保底 2s 足以让音轨可播放、拿到 esds，音轨内容本就是静音，无损体验。
        LONGLONG last_end = last_audio_end_;
        LONGLONG stop_t = qpc_now_hns();
        const bool no_audio_at_all = (last_end <= 0);
        LONGLONG anchor = no_audio_at_all ? seg_start_hns_ : last_end;
        if (anchor <= 0) anchor = stop_t - 2000000LL;   // 异常兜底，约 0.2s
        LONGLONG fill = stop_t - anchor;
        const LONGLONG SILENCE_CAP_HNS = 2 * 10000000LL;
        // [修复-本轮] 上限判断不再限于 no_audio_at_all：中途曾有音频但音频在
        // 结束前很早就停了（设备热切换/被占用）时，last_end 停在很早，fill 可达
        // 整段录制时长 → frames*nb 巨大 → 一次性分配上百 MB 静音 → OOM。统一封顶。
        if (fill > SILENCE_CAP_HNS) fill = SILENCE_CAP_HNS;
        if (fill > 0) {
            const int pcm_bits = 16;   // 与采集转换、SetInputMediaType 一致
            size_t frames = (size_t)(fill * arate_ / 10000000LL);
            // AAC 一帧 1024 samples：保底 2 帧，确保 MFT 输出音频样本与 header。
            const size_t MIN_FRAMES = 2048;
            if (frames < MIN_FRAMES) frames = MIN_FRAMES;
            size_t nb = frames * (size_t)(ach_ * pcm_bits / 8);
            if (nb > 0) {
                std::vector<unsigned char> silence(nb, 0);
                // [修复-本轮] duration 必须与实际帧数一致：原实现塞入 fill（墙钟
                // 差），而 fill 已被封顶/帧数被 MIN_FRAMES 抬高，二者不再相等。
                // duration 与实际样本数不符会让 AAC MFT / sink 时间轴错乱。
                LONGLONG dur = (LONGLONG)frames * 10000000LL / arate_;
                AudioBlock b{silence, anchor, dur};
                write_audio_block(b);
                audio_frames_ += (LONGLONG)frames;
            }
        }
        return 0;
    }

    int finalize(std::string& published) {
        if (finalized_) return 0;
        if (!mic_stopped_.load()) mark_mic_stop();
        int rc = drain_audio();               // 麦克风先停、先排空，替代 -shortest
        if (FAILED(rc)) return rc;
        // [修复-首段延迟创建] 若全程未收到 SPS/PPS，writer 从未创建、published_
        // 为空；close_writer(true) 会因 !writer_ 直接返回 S_OK，造成"报成功但无
        // 产物"的假成功。这里显式转成可读错误，让上层如实提示用户。
        if (!writer_ && published_.empty()) {
            set_error(E_FAIL, "未收到有效 H264 视频帧（缺 SPS/PPS），无可发布录制");
            finalized_ = true;
            unsubscribe_();
            return E_FAIL;
        }
        HRESULT hr = close_writer(true);
        if (FAILED(hr)) return (int)hr;
        finalized_ = true;
        unsubscribe_();
        for (size_t i = 0; i < published_.size(); ++i) {
            if (i) published += ';';
            published += published_[i];
        }
        return 0;
    }

    void discard() {
        if (finalized_ || discarded_) return;
        discarded_ = true;
        unsubscribe_();
        close_writer(false);
        // [修复] 段切换（170s）已原子发布的 .mp4 在 published_ 里，取消时也必须
        // 删除，否则用户点"取消"后目录里仍残留前面已发布的段（语义矛盾）。
        auto delete_utf8 = [](const std::string& path) {
            wchar_t w[2048];
            MultiByteToWideChar(CP_UTF8, 0, path.c_str(), -1, w, 2048);
            DeleteFileW(w);
        };
        for (const auto& t : tmp_files_) delete_utf8(t);
        tmp_files_.clear();
        for (const auto& p : published_) delete_utf8(p);
        published_.clear();
    }

    void stats(long long* vb, long long* af, long long* dr, int* qp) {
        *vb = video_bytes_; *af = audio_frames_; *dr = dropped_; *qp = queue_peak_ms_;
    }

private:
    void unsubscribe_() {
        if (!subscribed_) return;
        g_audio.unsubscribe(this); subscribed_ = false;
    }
    static bool has_vcl(const std::vector<std::vector<unsigned char>>& au) {
        for (const auto& n : au)
            if (!n.empty() && ((n[0] & 0x1F) >= 1 && (n[0] & 0x1F) <= 5)) return true;
        return false;
    }
    /* 冲刷跨 native 调用累积的当前 AU。只有至少含一个 VCL NAL 才是有效帧，
     * 纯非 VCL（如只有 SEI/AUD）残片直接丢弃，绝不作为独立 sample 写入 sink。 */
    void flush_pending_au() {
        if (pending_au_.empty()) return;
        if (has_vcl(pending_au_)) {
            std::vector<unsigned char> sample = to_annexb(pending_au_);
            LONGLONG ts = qpc_now_hns();
            LONGLONG dur = 10000000LL * fps_den_ / fps_num_;   // 名义帧率估算
            push_sample(vstream_, false, sample.data(), (UINT32)sample.size(), ts, dur);
        }
        pending_au_.clear();
    }
    void write_audio_block(const AudioBlock& blk) {
        if (!writer_ || !writing_ || blk.pcm.empty()) return;
        push_sample(astream_, true, blk.pcm.data(), (UINT32)blk.pcm.size(), blk.ts_hns, blk.dur_hns);
    }
    void push_sample(DWORD stream, bool audio, const unsigned char* data, UINT32 len, LONGLONG ts, LONGLONG dur) {
        if (!writer_ || !writing_) return;
        IMFSample* sample = nullptr;
        if (FAILED(MFCreateSample(&sample))) { dropped_++; return; }
        IMFMediaBuffer* buf = nullptr;
        if (FAILED(MFCreateMemoryBuffer(len, &buf))) { sample->Release(); dropped_++; return; }
        BYTE* dst = nullptr;
        // [修复-未初始化内存] Lock 失败或拿不到写指针时,绝不能把未初始化的 buffer
        // 当有效 sample 写进 MP4(否则向音视频流写入随机字节、污染产物)。丢弃本块。
        if (FAILED(buf->Lock(&dst, nullptr, nullptr)) || !dst) {
            buf->Release(); sample->Release(); dropped_++; return;
        }
        memcpy(dst, data, len);
        buf->Unlock();
        buf->SetCurrentLength(len);
        sample->AddBuffer(buf); buf->Release();
        // [修复] 每段是独立 MP4，sample 时间戳必须相对本段起点（seg_start_hns_），
        // 否则第二段起全局 QPC 已走过 170s+，写进去会让播放器显示 170s 黑屏开头、
        // 时长错乱。上一段残留、采集早于 writer 创建的块可能为负，clamp 到 0。
        LONGLONG rel_ts = ts - seg_start_hns_;
        if (rel_ts < 0) rel_ts = 0;
        // [修复-真机 0xC00D4A45 视频根因·v10 根治] H264 裸流本身无时间戳，v8/v9 曾
        // 用 sample 到达的 QPC 时刻打 ts：adb/64KB chunk 传输会突发到达(多帧挤同一
        // 时刻→重叠)，卡顿后又留下巨大向前 gap(discontinuity)。MP4 sink 要求视频流
        // 时间戳严格单调、等间隔、无 gap，两类异常都会触发 E_UNEXPECTED(0x8000FFFF)
        // 并使 sink 进入 sticky 错误态(首错后全失败)。
        // v9 实证：钳制(vtc=45)虽把 vws 从 4 救到 49，但只能修"向后重叠"、修不了
        // "向前跳跃"，仍有 vwf=298 连续失败；而音频 aws=1158/awf=0 全程成功(其 dur
        // 按实际样本数算、时间轴自洽)。视频 347 帧÷30fps=11.57s 与音频 11.58s 仅差
        // 0.013s，证明 screenrecord 是稳定 30fps、帧数完全正常，问题纯粹在时间戳。
        // 根治：视频改用「帧序号 × 名义帧长」合成时钟——第 N 帧 ts = N*(1e7/fps)，
        // 绝对均匀单调、无重叠无 gap，彻底不依赖不可靠的 QPC 到达时刻。
        // 音频路保持原样(真实 QPC + 按样本数的 dur，已验证自洽，不能扰乱)。
        if (!audio) {
            rel_ts = (LONGLONG)video_frame_count_ * dur;
            ++video_frame_count_;
        }
        sample->SetSampleTime(rel_ts); sample->SetSampleDuration(dur);
        // 必须真正把 sample 写进 sink；hr 供下方分路统计与错误上报使用。
        HRESULT hr = writer_->WriteSample(stream, sample);
        sample->Release();
        // [诊断 v8] 按流分别统计：哪一路 WriteSample 真正被 sink 接受。
        // 用调用方传入的 audio 标志判断，不依赖 stream id 数值（可能为 0）。
        // 只记计数，不改变原有 Failed 时的 set_error + dropped_ 行为。
        if (audio) {
            if (SUCCEEDED(hr)) { ++aws_; alhr_ = hr; } else { ++awf_; alhr_ = hr; }
        } else {
            if (SUCCEEDED(hr)) { ++vws_; vlhr_ = hr; } else { ++vwf_; vlhr_ = hr; }
        }
        if (FAILED(hr)) { set_error(hr, "WriteSample 失败"); dropped_++; }
    }

    // 段临时文件名：create() 预算首段名与 ensure_writer() 实际写入名共用，
    // 保证两者一致（首段延迟创建后，上层拿到的 first_tmp 仍指向正确路径）。
    std::string seg_tmp_path(int n) {
        char name[1024];
        _snprintf_s(name, sizeof(name), "%s_p%d.tmp.mp4", stem_.c_str(), n);
        return std::string(out_dir_) + "\\" + name;
    }

    HRESULT ensure_writer(std::string& first_tmp_out) {
        ++seg_no_;
        std::string tmp = seg_tmp_path(seg_no_);
        wchar_t wtmp[2048];
        MultiByteToWideChar(CP_UTF8, 0, tmp.c_str(), -1, wtmp, 2048);

        // [修复-真机 E_ACCESSDENIED] 不再设置 moov 前置（faststart）属性。
        // 真机现象：开启录音走同源路径时，收尾稳定报
        // "SinkWriter::Finalize 失败（HRESULT 0x80070005）"，.tmp 不发布、无 moov。
        // 根因：moov 前置要求 sink 在 Finalize 阶段对同一输出文件做二次 seek/remux，
        // 把 moov 从尾部搬到头部；这一步在真机被拒（拒绝访问）。此前几轮的音频
        // overflow 修复让 finalize 第一次真正走到 Finalize()，才暴露出这个一直
        // 被 overflow 提前 return 掩盖的问题。
        // 本项目录屏保存在本地、由本机播放器双击播放，moov 在尾部完全可播，
        // 不需要 faststart；用 sink 默认布局即可从根上消除该二次文件访问。
        // pAttributes 传 nullptr 合法（SDK 文档允许），无需再创建 attrs。
        HRESULT hr = MFCreateSinkWriterFromURL(wtmp, nullptr, nullptr, &writer_);
        if (FAILED(hr)) { set_error(hr, "MFCreateSinkWriterFromURL 失败"); return hr; }
        tmp_files_.push_back(tmp);
        if (seg_no_ == 1) first_tmp_out = tmp;

        IF_FAILED_RETURN(config_video_stream(), "配置视频流失败");
        IF_FAILED_RETURN(config_audio_stream(), "配置音频流失败");
        IF_FAILED_RETURN(writer_->BeginWriting(), "BeginWriting 失败");
        writing_ = true;
        seg_start_hns_ = qpc_now_hns();
        // 新段是独立 MP4，视频帧序号时钟从 0 重新起算，
        // 否则上段的帧序号会让新段首帧时间戳从很大的值开始。
        video_frame_count_ = 0;
        return S_OK;
    }

    HRESULT config_video_stream() {
        // 压缩输入 + 相同压缩输出（remux，不解码重编码）。
        IMFMediaType* vin = nullptr;
        IF_FAILED_RETURN(MFCreateMediaType(&vin), "MFCreateMediaType(video in) 失败");
        vin->SetGUID(MF_MT_MAJOR_TYPE, MFMediaType_Video);
        vin->SetGUID(MF_MT_SUBTYPE, MFVideoFormat_H264);
        vin->SetUINT32(MF_MT_AVG_BITRATE, 8000000);
        MFSetAttributeSize(vin, MF_MT_FRAME_SIZE, width_, height_);
        MFSetAttributeRatio(vin, MF_MT_FRAME_RATE, fps_num_, fps_den_);
        MFSetAttributeRatio(vin, MF_MT_PIXEL_ASPECT_RATIO, 1, 1);
        // H264→MP4 remux 必须带 AnnexB 起始码风格的 sequence header（SPS/PPS），
        // 否则 Finalize 报 0xC00D4A45 "required headers were not provided to the sink"
        // 或产出无法解码的文件。真机曾现首段 _p1.tmp.mp4 收尾稳定报此错：根因是
        // 旧实现在 create() 里提前建 writer，那时 SPS/PPS 尚未到达、header 为空。
        // [修复] 首段 writer 已延迟到 write_video 收到 SPS+PPS 后才创建，故走到
        // 这里缓存必然齐备；缺任一项说明调用路径异常，返回明确错误而非写入一个
        // 注定 Finalize 失败的流。
        {
            std::lock_guard<std::mutex> lk(seq_mtx_);
            if (sps_.empty() || pps_.empty()) {
                vin->Release();
                set_error(E_FAIL, "创建视频流时缺少 SPS/PPS（无法注入 sequence header）");
                return E_FAIL;
            }
            std::vector<unsigned char> hdr = make_seq_header(sps_, pps_);
            diag_sps_ = (int)sps_.size();
            diag_pps_ = (int)pps_.size();
            diag_seqh_ = (int)hdr.size();
            IF_FAILED_RETURN(vin->SetBlob(MF_MT_MPEG_SEQUENCE_HEADER,
                                          hdr.data(), (UINT32)hdr.size()),
                             "设置 MF_MT_MPEG_SEQUENCE_HEADER 失败");
        }
        // 目标格式就是 H264 本身（remux 不重编码）：AddStream 的 pTargetMediaType
        // 即写入文件的格式，SinkWriter 对 compressed-in 流直接以它作为输出。
        // 不存在 SetOutputMediaType；原实现调用了幻想 API，MSVC 编译直接失败。
        IF_FAILED_RETURN(writer_->AddStream(vin, &vstream_), "AddStream(video) 失败");
        // [根因修复 v11] 视频流必须 SetInputMediaType —— MSDN 标准序列
        // AddStream → SetInputMediaType → BeginWriting，此前视频流只调了 AddStream，
        // 从未设输入类型（音频流 945 行有 → aws 全成功，视频缺 → vws=1 后 sticky 全败）。
        // SinkWriter 生成 avcC/stsd 依赖输入媒体类型上的 sequence header；输入类型缺失
        // 时 sink 在写 sample 阶段报 E_UNEXPECTED(0x8000FFFF)、Finalize 报
        // 0xC00D4A45(MF_E_SINK_HEADERS_NOT_FOUND)，半成品 mp4 无 moov/avcC。
        // remux 的输入/输出同为 H264，复用带 sequence header 的 vin 作为输入类型。
        // 用显式 hr 记录而非 IF_FAILED_RETURN：即使此机型 sink 拒绝该调用，也不让
        // 录制直接起不来，同时把 HRESULT 写进诊断供真机判断。
        diag_vsim_ = writer_->SetInputMediaType(vstream_, vin, nullptr);
        vin->Release();
        if (FAILED(diag_vsim_)) {
            set_error(diag_vsim_, "SetInputMediaType(video/H264) 失败");
            return diag_vsim_;
        }
        return S_OK;
    }

    HRESULT config_audio_stream() {
        // PCM 输入 + MFAudioFormat_AAC 目标：让系统 AAC MFT 编码，
        // 避免裸 PCM 直接喂 MP4 sink 在 Finalize 报 0xC00D4A45。
        //
        // IMFSinkWriter 正确用法（无 SetOutputMediaType 这个方法）：
        //   1) AddStream(目标类型=AAC) 建流；pTargetMediaType 描述"写进文件"的格式；
        //   2) SetInputMediaType(输入类型=PCM) 告诉 SinkWriter 喂进来的样本格式。
        // 原实现把 PCM 当目标、AAC 当输出并调用幻想的 SetOutputMediaType，
        // MSVC 编译直接失败（C2039）。
        IMFMediaType* aout = nullptr;   // 目标/编码格式：AAC
        IF_FAILED_RETURN(MFCreateMediaType(&aout), "MFCreateMediaType(audio AAC) 失败");
        aout->SetGUID(MF_MT_MAJOR_TYPE, MFMediaType_Audio);
        aout->SetGUID(MF_MT_SUBTYPE, MFAudioFormat_AAC);
        aout->SetUINT32(MF_MT_AUDIO_NUM_CHANNELS, ach_);
        aout->SetUINT32(MF_MT_AUDIO_SAMPLES_PER_SECOND, arate_);
        aout->SetUINT32(MF_MT_AUDIO_BITS_PER_SAMPLE, 16);
        aout->SetUINT32(MF_MT_AUDIO_AVG_BYTES_PER_SECOND, 128000 / 8);
        // [修复-0xC00D4A45] 显式声明 raw AAC payload（值必须为 0）。MP4 sink
        // 据此生成 esds(AudioSpecificConfig) box；缺省虽默认 0，但真机部分
        // sink 实现下缺失该属性导致 Finalize 拿不到 header 报错，明确设置消除歧义。
        aout->SetUINT32(MF_MT_AAC_PAYLOAD_TYPE, 0);
        IF_FAILED_RETURN(writer_->AddStream(aout, &astream_), "AddStream(audio/AAC) 失败");

        IMFMediaType* ain = nullptr;    // 输入格式：采集线程已统一转成 16-bit PCM
        IF_FAILED_RETURN(MFCreateMediaType(&ain), "MFCreateMediaType(audio PCM) 失败");
        const int pcm_bits = 16;   // AAC MFT 输入硬性要求 16-bit PCM，与采集转换一致
        ain->SetGUID(MF_MT_MAJOR_TYPE, MFMediaType_Audio);
        ain->SetGUID(MF_MT_SUBTYPE, MFAudioFormat_PCM);
        ain->SetUINT32(MF_MT_AUDIO_NUM_CHANNELS, ach_);
        ain->SetUINT32(MF_MT_AUDIO_SAMPLES_PER_SECOND, arate_);
        ain->SetUINT32(MF_MT_AUDIO_BITS_PER_SAMPLE, pcm_bits);
        ain->SetUINT32(MF_MT_AUDIO_BLOCK_ALIGNMENT, ach_ * pcm_bits / 8);
        ain->SetUINT32(MF_MT_AUDIO_AVG_BYTES_PER_SECOND, arate_ * ach_ * pcm_bits / 8);
        IF_FAILED_RETURN(writer_->SetInputMediaType(astream_, ain, nullptr),
                         "SetInputMediaType(audio/PCM16) 失败（系统 AAC 编码器不可用/格式不支持）");
        ain->Release(); aout->Release();
        return S_OK;
    }

    HRESULT check_rotate() {
        // [修复-首段延迟创建] writer 未建立（仍在等 SPS/PPS）时 seg_start_hns_
        // 尚为 0，此刻做差会得到巨大的伪经过时间而误触发切段。首段还没开始写，
        // 无需切段，直接返回。
        if (!writer_) return S_OK;
        LONGLONG seg_limit = (LONGLONG)SEGMENT_SECONDS_ * 10000000LL;
        if (qpc_now_hns() - seg_start_hns_ < seg_limit) return S_OK;
        // 段切换：先停音频并入队静止（音频由订阅广播继续，我不在此 drain），
        // Finalize 当前段并原子发布，再开新段。
        HRESULT hr = close_writer(true);
        if (FAILED(hr)) return hr;
        std::string dummy;
        return ensure_writer(dummy);
    }

    HRESULT close_writer(bool publish) {
        if (!writer_) return S_OK;
        // [根因修复 v12] 把尚未写到 AU 边界的最后一帧冲刷进当前段再 Finalize，
        // 否则录屏末尾这帧永远丢失；切段路径同样走这里，新段从空 AU 开始。
        if (writing_) flush_pending_au();
        HRESULT hr = S_OK;
        // [修复-半成品发布] Finalize 会把 writing_ 置回 false，先捕获"本段是否
        // 真正进入过 writing"。ensure_writer 在 BeginWriting 之前失败(AAC 编码器
        // 不可用/流配置失败)时 writer 已建、tmp 已入列、磁盘 tmp 已生成，但从未
        // BeginWriting —— 该 tmp 无 moov、不可播放，绝不能当成功产物发布。
        const bool was_writing = writing_;
        if (writing_) { hr = writer_->Finalize(); writing_ = false; }
        writer_->Release(); writer_ = nullptr;
        if (FAILED(hr)) {
            set_error(hr, "SinkWriter::Finalize 失败");
            // [诊断 v8] 分路定位 0xC00D4A45：看 aws/vws 谁没被 sink 接受。
            const int uns = g_audio.unsupported_src() ? 1 : 0;
            append_error_stats(video_bytes_, audio_frames_, dropped_,
                               vws_, aws_, vwf_, awf_, vlhr_, alhr_,
                               arate_, ach_, abits_,
                               diag_sps_, diag_pps_, diag_seqh_,
                               uns ? 0 : 1, overflow_.load() ? 1 : 0, uns,
                               video_frame_count_, diag_vsim_);
            return hr;
        }
        if (publish && !tmp_files_.empty()) {
            std::string tmp = tmp_files_.back();
            if (!was_writing) {
                // 半成品：删磁盘 tmp、出列并报错，避免发布损坏 MP4 且 finalize 假成功。
                wchar_t wt[2048];
                MultiByteToWideChar(CP_UTF8, 0, tmp.c_str(), -1, wt, 2048);
                DeleteFileW(wt);
                tmp_files_.pop_back();
                set_error(E_FAIL, "录制段未完成初始化（未能进入 writing 状态），已丢弃半成品");
                return E_FAIL;
            }
            std::string final = tmp;
            size_t p = final.find(".tmp.mp4");
            if (p != std::string::npos) final.replace(p, std::string(".tmp.mp4").size(), ".mp4");
            wchar_t wt[2048], wf[2048];
            MultiByteToWideChar(CP_UTF8, 0, tmp.c_str(), -1, wt, 2048);
            MultiByteToWideChar(CP_UTF8, 0, final.c_str(), -1, wf, 2048);
            if (!MoveFileExW(wt, wf, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
                HRESULT eh = HRESULT_FROM_WIN32(GetLastError());
                set_error(eh, "原子发布临时文件失败");
                return eh;
            }
            published_.push_back(final);
        }
        return S_OK;
    }

    std::string out_dir_, stem_;
    int width_, height_, fps_num_, fps_den_;
    int arate_, abits_, ach_;
    IMFSinkWriter* writer_;
    DWORD vstream_, astream_;
    bool writing_;
    std::atomic<bool> subscribed_{false};
    int seg_no_;
    // 跨线程读写：on_audio 在采集线程检查，write_video/finalize 在 worker
    // 线程写入 —— 必须是原子，否则数据竞争（未定义行为）。
    std::atomic<bool> finalized_{false}, discarded_{false};
    LONGLONG seg_start_hns_;
    static const int SEGMENT_SECONDS_ = 170;   // 与 core.constants.REC_SEGMENT_S 一致
    std::vector<std::string> tmp_files_, published_;
    long long video_bytes_, audio_frames_, dropped_;
    // [诊断 v8] 分路写入统计：vws/aws=各路 WriteSample 成功数；vwf/awf=失败数；
    // vlhr/alhr=各路最后一次 HRESULT。0xC00D4A45 据此判断是哪一路没喂进 sink。
    long long vws_, aws_, vwf_, awf_;
    HRESULT vlhr_, alhr_;
    HRESULT diag_vsim_;   // 诊断：SetInputMediaType(video) 的 HRESULT，S_OK=输入类型被接受
    int diag_sps_, diag_pps_, diag_seqh_;   // 诊断：注入 sink 的 sequence header 长度
    int queue_peak_ms_;
    std::deque<AudioBlock> audio_q_;
    std::mutex audio_q_mtx_;
    // [修复-收尾慢] 与 audio_q_ 同锁维护的累计时长(100ns)：on_audio 入队时 +=，
    // drain 移出时归零。用于把 overflow 判定从 O(n) 遍历降为 O(1)。
    LONGLONG queued_hns_;
    // [根因修复 v12] 跨 native 调用累积的当前 AU 的 NAL。Python 每次只送一条
    // AnnexB NAL，一帧的 SEI/VCL 常跨多次调用，必须攒齐再写成一个完整 sample。
    std::vector<std::vector<unsigned char>> pending_au_;
    std::atomic<bool> overflow_{false}, mic_stopped_{false};
    LONGLONG last_audio_end_;   // 已写入音频的最后结束时刻（100ns，QPC 时基）
    // [修复-视频时间戳 v10] 视频帧序号：ts = 帧序号 × 名义帧长。H264 裸流无时间戳，
    // 用帧序号合成恒定帧率时钟，彻底避免 QPC 到达时刻的突发重叠/向前 gap 触发
    // MP4 sink 的 E_UNEXPECTED → Finalize 0xC00D4A45。切段时归零（新 MP4 时间轴）。
    long long video_frame_count_;
    // 视频 SPS/PPS 缓存：采集线程(write_video)写，worker 线程(config_video_stream)读。
    std::vector<unsigned char> sps_, pps_;
    std::mutex seq_mtx_;
};

/* --------------------------- 句柄表 & C ABI --------------------------- */

static std::mutex g_sessions_mtx;
static std::vector<RecordSession*> g_sessions;
static RecordSession* find_session(long long h) {
    std::lock_guard<std::mutex> lk(g_sessions_mtx);
    for (auto* s : g_sessions) if ((long long)s == h) return s;
    return nullptr;
}

extern "C" long long adc_session_create(const char* out_dir, const char* stem,
        int width, int height, int fps_num, int fps_den,
        int arate, int abits, int ach, char* first_tmp, int first_tmp_cap) {
    if (!g_mf_ready.load()) { set_error_text("MF 未初始化：请先调用 adc_init（MTA worker 线程）"); return 0; }
    auto* s = new RecordSession(out_dir, stem, width, height, fps_num, fps_den, arate, abits, ach);
    std::string first;
    if (FAILED(s->create(first))) { delete s; return 0; }
    { std::lock_guard<std::mutex> lk(g_sessions_mtx); g_sessions.push_back(s); }
    if (first_tmp && first_tmp_cap > 0) {
        size_t n = first.size(); if ((int)n > first_tmp_cap - 1) n = (size_t)(first_tmp_cap - 1);
        memcpy(first_tmp, first.c_str(), n); first_tmp[n] = '\0';
    }
    return (long long)s;
}
extern "C" int adc_session_write_video(long long h, const unsigned char* data, int len) {
    RecordSession* s = find_session(h);
    if (!s) { set_error_text("会话句柄无效"); return E_INVALIDARG; }
    return s->write_video(data, len);
}
extern "C" int adc_session_mark_mic_stop(long long h) {
    RecordSession* s = find_session(h);
    return s ? s->mark_mic_stop() : E_INVALIDARG;
}
// [修复-真机 overflow] 供 Python 定时器经 worker 线程周期调用，主动排空音频队列，
// 使音频写入与 video sample 解耦；视频流稀疏/中断时音频仍能持续写入 SinkWriter。
extern "C" int adc_session_drain_audio(long long h) {
    RecordSession* s = find_session(h);
    return s ? s->drain_audio_tick() : E_INVALIDARG;
}
extern "C" int adc_session_finalize(long long h, char* published, int cap) {
    RecordSession* s = find_session(h);
    if (!s) return E_INVALIDARG;
    std::string pub;
    int rc = s->finalize(pub);
    if (rc == 0 && published && cap > 0) {
        size_t n = pub.size(); if ((int)n > cap - 1) n = (size_t)(cap - 1);
        memcpy(published, pub.c_str(), n); published[n] = '\0';
    }
    return rc;
}
extern "C" void adc_session_discard(long long h) {
    RecordSession* s = find_session(h);
    if (s) s->discard();
}
extern "C" void adc_session_destroy(long long h) {
    std::lock_guard<std::mutex> lk(g_sessions_mtx);
    for (auto it = g_sessions.begin(); it != g_sessions.end(); ++it) {
        if ((long long)*it == h) { delete *it; g_sessions.erase(it); break; }
    }
}
extern "C" int adc_session_stats(long long h, long long* vb, long long* af, long long* dr, int* qp) {
    RecordSession* s = find_session(h);
    if (!s) return E_INVALIDARG;
    s->stats(vb, af, dr, qp); return 0;
}
