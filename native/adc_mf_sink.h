/*
 * adc_mf_sink.h —— ADBDeviceCommander 同源录屏 native 扩展的 C ABI
 * ================================================================
 * 仅导出 extern "C" 函数，供 Python ctypes 直接调用；不导出任何 C++ 类型。
 *
 * 线程模型（调用方必须遵守，否则 COM 单元会直接失败）：
 *   - adc_init / adc_shutdown 只能在同一个**专用 worker 线程**调用，且该线程
 *     必须先处于 MTA（adc_init 内部做 CoInitializeEx(MTA)，见实现）。
 *   - 禁止在 pywebview/WinForms 的 UI 线程（STA）调用 adc_init：
 *     CoInitializeEx(MTA) 在已 STA 的线程上返回 RPC_E_CHANGED_MODE，
 *     adc_init 会返回该 HRESULT，调用方须转成中文错误提示。
 *   - 各 session 的 WriteVideo/WriteAudio/MarkMicStop/Finalize 从该 worker
 *     线程调用；WASAPI 采集在 native 内部自有线程，通过有界队列交给 worker。
 *
 * 数据流：
 *   Python 读 adb `exec-out screenrecord --output-format=h264 -` 的 stdout，
 *   分块调用 adc_session_write_video；麦克风由 native 内部 WASAPI 显式
 *   capture endpoint 采集，PCM 直接（经队列）写入**同一个** SinkWriter 的
 *   音频流。音视频共用 QPC→100ns 时基，由 native 统一打时间戳。
 *
 * 所有返回 int 的 API：0 表示成功，非 0 为 HRESULT（失败）或本模块自定义
 * 错误码（见 adc_last_error 的文本）。cdecl 调用约定。
 */
#ifndef ADC_MF_SINK_H
#define ADC_MF_SINK_H

#ifdef ADC_MF_SINK_EXPORTS
#define ADC_API __declspec(dllexport)
#else
#define ADC_API __declspec(dllimport)
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* ---- 进程级生命周期（只在专用 MTA worker 线程调用）------------------- */

/* CoInitializeEx(COINIT_MULTITHREADED) + MFStartup(MF_VERSION, MFSTARTUP_NO_SOCKETS)。
 * 返回 0 成功；RPC_E_CHANGED_MODE(0x80010106) 表示调用线程已是 STA。 */
ADC_API int adc_init(void);
ADC_API void adc_shutdown(void);

/* 把上一次失败的可读描述写入 out（UTF-8），返回实际写入字节数。线程安全。 */
ADC_API int adc_last_error(char* out, int out_cap);

/* ---- 麦克风（全局单例，native 内部 WASAPI 线程）---------------------- */

/* 启动采集。
 *   endpoint_id: WASAPI 设备 ID（UTF-16）；传 NULL 时用默认 capture endpoint。
 *   rate/bits/channels: 期望的 PCM 格式；实际协商结果由 adc_mic_format 回读。
 * 返回 0 成功。显式禁止 loopback（不设置 AUDCLNT_STREAMFLAGS_LOOPBACK）。 */
ADC_API int adc_mic_start(const wchar_t* endpoint_id, int rate, int bits, int channels);
ADC_API void adc_mic_stop(void);
/* 返回实际 PCM 格式：*rate/*bits/*channels；0 成功。 */
ADC_API int adc_mic_format(int* rate, int* bits, int* channels);
/* 设备拔插 / 默认设备切换事件计数（只读，供 Python 诊断"是否发生过热切换"）。 */
ADC_API int adc_mic_device_events(void);

/* ---- 单设备录制会话（一个 SinkWriter，H264 + AAC 两路流）------------- */

/* 创建会话。
 *   out_dir_utf8 : 输出目录（UTF-8），临时文件写在同目录。
 *   stem_utf8    : 文件前缀（如 record_<serial>_<ts>）。
 *   width/height : 视频分辨率（偶数，由 Python 侧保证）。
 *   fps_num/den  : 名义帧率（仅用于缺时间戳时的 duration 估算）。
 *   audio_rate/bits/channels : 必须与 adc_mic_format 回读值一致，否则音频流
 *                              媒体类型对不上，Finalize 会失败。
 * 成功返回句柄（>0）并把首个临时文件路径写入 first_tmp_utf8；失败返回 0。 */
ADC_API long long adc_session_create(const char* out_dir_utf8,
                                     const char* stem_utf8,
                                     int width, int height,
                                     int fps_num, int fps_den,
                                     int audio_rate, int audio_bits, int audio_channels,
                                     char* first_tmp_utf8, int first_tmp_cap);

/* 喂入一段裸 H.264 ES（annex-B：00 00 00 01 / 00 00 01 起始码）。
 * native 负责：起始码→length-prefixed、SPS/PPS 提取、按 AU 切分并打 QPC 时间戳。
 * 返回 0 成功；非 0 为 HRESULT。 */
ADC_API int adc_session_write_video(long long handle, const unsigned char* data, int len);

/* 通知该会话"麦克风已停"：worker 会把音频队列排空并补齐静音到 stop 时刻，
 * 之后不再接受音频，但视频仍可继续写入，直到 adc_session_finalize。 */
ADC_API int adc_session_mark_mic_stop(long long handle);

/* 主动排空音频队列：供上层定时器周期性调用（必须在 adc_init 所在的同一 worker
 * 线程）。音频写入因此与 video sample 解耦——视频流稀疏/中断时音频仍能持续写入
 * SinkWriter，避免队列积压。幂等，队列为空时无副作用。返回 0。 */
ADC_API int adc_session_drain_audio(long long handle);

/* 结束会话：排空音频 → Finalize SinkWriter → 把所有已完成段**原子发布**
 * （*.tmp → 正式 mp4）。成功返回 0，并把正式文件路径列表（UTF-8，分号分隔）
 * 写入 published_utf8。失败返回 HRESULT，临时文件保留在 out_dir 供排查。 */
ADC_API int adc_session_finalize(long long handle, char* published_utf8, int published_cap);

/* 取消会话（用户点"取消"）：不 Finalize、不发布，删除所有临时文件。幂等。 */
ADC_API void adc_session_discard(long long handle);

/* 释放会话对象（在 finalize/discard 之后调用；内部幂等）。 */
ADC_API void adc_session_destroy(long long handle);

/* 诊断：当前会话的统计（累计视频字节、音频帧、丢弃帧、队列峰值毫秒）。
 * 返回 0 成功。 */
ADC_API int adc_session_stats(long long handle, long long* video_bytes,
                              long long* audio_frames, long long* dropped_frames,
                              int* queue_peak_ms);

#ifdef __cplusplus
}
#endif
#endif /* ADC_MF_SINK_H */
