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
#include <string>
#include <vector>
#include <deque>
#include <mutex>
#include <atomic>
#include <cstdio>
#include <cstring>
#include <cwchar>

#pragma comment(lib, "mfplat.lib")
#pragma comment(lib, "mfreadwrite.lib")
#pragma comment(lib, "mfuuid.lib")
#pragma comment(lib, "ole32.lib")
#pragma comment(lib, "propsys.lib")
#pragma comment(lib, "uuid.lib")
#pragma comment(lib, "advapi32.lib")

#define IF_FAILED_RETURN(hr, msg) do { HRESULT __hr = (hr); if (FAILED(__hr)) { set_error(__hr, msg); return __hr; } } while (0)

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
        while (end + 3 <= len) {
            if ((p[end] == 0 && p[end+1] == 0 && p[end+2] == 1) ||
                (end + 4 <= len && p[end] == 0 && p[end+1] == 0 &&
                 p[end+2] == 0 && p[end+3] == 1)) break;
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

/* SPS/PPS → AVCC 风格 sequence header：[4B 大端长度][SPS][4B 大端长度][PPS] */
static std::vector<unsigned char> make_seq_header(const std::vector<unsigned char>& sps,
                                                  const std::vector<unsigned char>& pps) {
    std::vector<unsigned char> h;
    auto push = [&](const std::vector<unsigned char>& nal) {
        unsigned int n = (unsigned int)nal.size();
        h.push_back((n>>24)&0xFF); h.push_back((n>>16)&0xFF);
        h.push_back((n>>8)&0xFF);  h.push_back(n&0xFF);
        h.insert(h.end(), nal.begin(), nal.end());
    };
    if (!sps.empty()) push(sps);
    if (!pps.empty()) push(pps);
    return h;
}
static std::vector<unsigned char> to_length_prefixed(const std::vector<std::vector<unsigned char>>& nals) {
    std::vector<unsigned char> out;
    for (const auto& nal : nals) {
        unsigned int n = (unsigned int)nal.size();
        out.push_back((n>>24)&0xFF); out.push_back((n>>16)&0xFF);
        out.push_back((n>>8)&0xFF);  out.push_back(n&0xFF);
        out.insert(out.end(), nal.begin(), nal.end());
    }
    return out;
}

/* ------------------- 音频：WASAPI capture + 广播 ---------------------- */

struct AudioBlock {
    std::vector<unsigned char> pcm;
    LONGLONG ts_hns;
    LONGLONG dur_hns;
};
static const LONGLONG AUDIO_QUEUE_LIMIT_HNS = 5 * 10000000LL;   // 5s 上限

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
                            rate_ = f->nSamplesPerSec; bits_ = f->wBitsPerSample; channels_ = f->nChannels;
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

        // 目标格式必须与 mix format 一致；这是"格式不一致显式转换/上报"的策略：
        // 不引第三方重采样，回读真实格式并要求用它建会话，绝不静默接受不一致。
        {
            std::lock_guard<std::mutex> lk(fmt_mtx_);
            rate_ = fmt->nSamplesPerSec; bits_ = fmt->wBitsPerSample; channels_ = fmt->nChannels;
        }
        fmt_ready_.store(true);   // 唤醒等待中的 format()
        REFERENCE_TIME dur = 10000000; // 1s 缓冲（共享模式）
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

        UINT32 align = (UINT32)(channels_ * bits_ / 8);
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
                size_t nb = (size_t)n * align;
                if (flags & AUDCLNT_BUFFERFLAGS_SILENT) blk.pcm.assign(nb, 0);
                else blk.pcm.assign(data, data + nb);
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
          last_audio_end_(0) {}

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
        LONGLONG queued = 0;
        for (const auto& b : audio_q_) queued += b.dur_hns;
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
        LONGLONG peak = (queued + blk.dur_hns) / 10000;
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
        std::vector<std::vector<unsigned char>> au;
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
            if (type == 9) {           // AUD：新 AU 边界
                if (!au.empty()) { flush_au(au); au.clear(); }
                continue;
            }
            if (type >= 1 && type <= 5 && has_vcl(au)) { flush_au(au); au.clear(); }
            au.push_back(std::move(n));
        }
        if (!au.empty()) flush_au(au);
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
        // [修复-真机 overflow] 删除 `if (overflow_.load()) return;`：overflow_ 现在
        // 只是"曾丢过音频块"的诊断标记，不能再阻断排空，否则队列里已入队的音频会
        // 永远留在内存、收尾也写不进成片。丢弃策略在 on_audio 已完成，这里只管把
        // 队列里剩下的块正常写入。
        std::lock_guard<std::mutex> lk(audio_q_mtx_);
        // [修复-首段延迟创建] 首段 writer 尚未建立（在等 SPS/PPS）时不要 pop 音频块：
        // write_audio_block 会因 !writer_ 静默丢弃，导致录制开头的音频丢失。保留在
        // 有界队列里，writer 一建好（收到 SPS/PPS 后）下一个 drain tick 即写入。
        if (!writer_) return;
        while (!audio_q_.empty()) {
            AudioBlock blk = std::move(audio_q_.front()); audio_q_.pop_front();
            write_audio_block(blk);
            audio_frames_ += (LONGLONG)(blk.pcm.size() / (size_t)(ach_ * abits_ / 8));
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
        // [NEEDS-VERIFY] 补静音：把音轨尾部补到视频 stop 时刻；SinkWriter 不支持
        // 运行中改 sample 时间戳，这里只在尾部追加静音 sample，不改已写入的 ts。
        LONGLONG last_end = last_audio_end_;
        LONGLONG stop_t = qpc_now_hns();
        if (stop_t > last_end && last_end > 0) {
            LONGLONG fill = stop_t - last_end;
            size_t frames = (size_t)(fill * arate_ / 10000000LL);
            size_t nb = frames * (size_t)(ach_ * abits_ / 8);
            if (nb > 0) {
                std::vector<unsigned char> silence(nb, 0);
                AudioBlock b{silence, last_end, fill};
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
    void flush_au(std::vector<std::vector<unsigned char>>& au) {
        if (!writer_ || !writing_ || au.empty()) return;
        std::vector<unsigned char> sample = to_length_prefixed(au);
        LONGLONG ts = qpc_now_hns();
        LONGLONG dur = 10000000LL * fps_den_ / fps_num_;   // 名义帧率估算
        push_sample(vstream_, sample.data(), (UINT32)sample.size(), ts, dur);
    }
    void write_audio_block(const AudioBlock& blk) {
        if (!writer_ || !writing_ || blk.pcm.empty()) return;
        push_sample(astream_, blk.pcm.data(), (UINT32)blk.pcm.size(), blk.ts_hns, blk.dur_hns);
    }
    void push_sample(DWORD stream, const unsigned char* data, UINT32 len, LONGLONG ts, LONGLONG dur) {
        if (!writer_ || !writing_) return;
        IMFSample* sample = nullptr;
        if (FAILED(MFCreateSample(&sample))) { dropped_++; return; }
        IMFMediaBuffer* buf = nullptr;
        if (FAILED(MFCreateMemoryBuffer(len, &buf))) { sample->Release(); dropped_++; return; }
        BYTE* dst = nullptr;
        if (SUCCEEDED(buf->Lock(&dst, nullptr, nullptr)) && dst) { memcpy(dst, data, len); buf->Unlock(); }
        buf->SetCurrentLength(len);
        sample->AddBuffer(buf); buf->Release();
        // [修复] 每段是独立 MP4，sample 时间戳必须相对本段起点（seg_start_hns_），
        // 否则第二段起全局 QPC 已走过 170s+，写进去会让播放器显示 170s 黑屏开头、
        // 时长错乱。上一段残留、采集早于 writer 创建的块可能为负，clamp 到 0。
        LONGLONG rel_ts = ts - seg_start_hns_;
        if (rel_ts < 0) rel_ts = 0;
        sample->SetSampleTime(rel_ts); sample->SetSampleDuration(dur);
        HRESULT hr = writer_->WriteSample(stream, sample);
        sample->Release();
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
        // H264→MP4 remux 必须带 AVCC 风格 sequence header（SPS/PPS），否则
        // Finalize 报 0xC00D4A45 "required headers were not provided to the sink"
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
            IF_FAILED_RETURN(vin->SetBlob(MF_MT_MPEG_SEQUENCE_HEADER,
                                          hdr.data(), (UINT32)hdr.size()),
                             "设置 MF_MT_MPEG_SEQUENCE_HEADER 失败");
        }
        // 目标格式就是 H264 本身（remux 不重编码）：AddStream 的 pTargetMediaType
        // 即写入文件的格式，SinkWriter 对 compressed-in 流直接以它作为输出。
        // 不存在 SetOutputMediaType；原实现调用了幻想 API，MSVC 编译直接失败。
        IF_FAILED_RETURN(writer_->AddStream(vin, &vstream_), "AddStream(video) 失败");
        vin->Release();
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
        aout->SetUINT32(MF_MT_AUDIO_AVG_BYTES_PER_SECOND, 192000 / 8);
        IF_FAILED_RETURN(writer_->AddStream(aout, &astream_), "AddStream(audio/AAC) 失败");

        IMFMediaType* ain = nullptr;    // 输入格式：WASAPI 采集的 PCM
        IF_FAILED_RETURN(MFCreateMediaType(&ain), "MFCreateMediaType(audio PCM) 失败");
        ain->SetGUID(MF_MT_MAJOR_TYPE, MFMediaType_Audio);
        ain->SetGUID(MF_MT_SUBTYPE, MFAudioFormat_PCM);
        ain->SetUINT32(MF_MT_AUDIO_NUM_CHANNELS, ach_);
        ain->SetUINT32(MF_MT_AUDIO_SAMPLES_PER_SECOND, arate_);
        ain->SetUINT32(MF_MT_AUDIO_BITS_PER_SAMPLE, abits_);
        ain->SetUINT32(MF_MT_AUDIO_BLOCK_ALIGNMENT, ach_ * abits_ / 8);
        ain->SetUINT32(MF_MT_AUDIO_AVG_BYTES_PER_SECOND, arate_ * ach_ * abits_ / 8);
        IF_FAILED_RETURN(writer_->SetInputMediaType(astream_, ain, nullptr),
                         "SetInputMediaType(audio/PCM) 失败（系统 AAC 编码器不可用/格式不支持）");
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
        HRESULT hr = S_OK;
        if (writing_) { hr = writer_->Finalize(); writing_ = false; }
        writer_->Release(); writer_ = nullptr;
        if (FAILED(hr)) { set_error(hr, "SinkWriter::Finalize 失败"); return hr; }
        if (publish && !tmp_files_.empty()) {
            std::string tmp = tmp_files_.back();
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
    int queue_peak_ms_;
    std::deque<AudioBlock> audio_q_;
    std::mutex audio_q_mtx_;
    std::atomic<bool> overflow_{false}, mic_stopped_{false};
    LONGLONG last_audio_end_;   // 已写入音频的最后结束时刻（100ns，QPC 时基）
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
