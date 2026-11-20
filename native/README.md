# adc_mf_sink —— 同源录屏 native 扩展

视频（设备端 `screenrecord --output-format=h264 -` 的裸 H.264 ES）与麦克风
（本机 WASAPI capture）在**同一个 Media Foundation SinkWriter** 里按统一
QPC（100ns）时基写入，直接产出 `H264 + AAC` 的 MP4。无 ffmpeg、无第三方
二进制、无 GPL；只依赖 Windows 系统 DLL，MSVC 编译。

## 接口与线程模型

见 `adc_mf_sink.h` 的注释。要点：

- `adc_init` 在**专用 MTA worker 线程**调用；UI 线程（STA）调用会返回
  `RPC_E_CHANGED_MODE (0x80010106)`，Python 层转成中文错误。
- 每设备一个 `adc_session_create`（一个 SinkWriter，H264 + AAC 两路流）。
- Python 读 adb stdout 的 H264 字节块 → `adc_session_write_video`。
- 麦克风由 native 内部 WASAPI 线程采集，**广播**给所有 session（多设备
  全场共用一条），每 session 有自己的 5s 有界队列，超限明确失败。
- stop：`adc_session_mark_mic_stop` → `adc_session_finalize`（排空音频 →
  Finalize → 原子发布 `*.tmp.mp4` → `*.mp4`，moov 前置于 mdat）。
- 取消：`adc_session_discard`（不发布，删临时文件）；强杀后 `.tmp` 永不
  冒充成功产物，启动扫目录清 `.tmp`。
- 分段：每 `SEGMENT_SECONDS_(170)` 一个完整可播 MP4，同目录临时文件 +
  成功关闭后 `MoveFileEx` 原子发布。

## 构建

```bat
cmake -S native -B native/build -A x64
cmake --build native/build --config Release
cmake --install native/build --prefix backend
```

需要 Visual Studio 2022 Build Tools（含 Windows 10/11 SDK）。产物
`backend/adc_mf_sink.dll` 由 `backend/mf_native.py` 用 ctypes 加载。

## 必须在真机核对 / 验证的项（禁止凭记忆上线）

源码里所有 `[NEEDS-VERIFY]` 注释对应下列条目，需在 Win11 x64 上按
Microsoft Learn 逐条核对：

1. **moov 前置（`MF_MPEG4SINK_MOOV_BEFORE_MDAT`）已移除**：真机开启录音走
   同源路径时，收尾稳定报 `SinkWriter::Finalize 失败（0x80070005 / 拒绝访问）`。
   根因是该属性要求 sink 在 Finalize 阶段对同一输出文件做二次 seek/remux 把 moov
   搬到头部，这一步在真机被拒。此前音频 overflow 修复让 finalize 第一次真正走到
   `Finalize()`，才暴露出这个一直被 overflow 提前 return 掩盖的问题。本项目录屏
   保存在本地、由本机播放器双击播放，moov 在尾部完全可播，不需要 faststart；已
   改回 sink 默认的 moov-after-mdat 布局（`MFCreateSinkWriterFromURL` 的
   pAttributes 传 nullptr）。新增源码守卫测试锁定该属性不被重新引入。
2. **H264 compressed-in/identical-out**：`MFVideoFormat_H264` + 压缩输入
   相同输出是「Using the Sink Writer」文档明确支持的组合（remux 不转码）。
   但 SPS/PPS 的注入方式（`MF_MT_MPEG_SEQUENCE_HEADER`、AVCC 长度前缀
   还是 annex-B、AddStream 前必须就位）需真机验证。当前实现已在
   `write_video` 里缓存 SPS/PPS，并在 `config_video_stream` 的 AddStream 前
   以 `MF_MT_MPEG_SEQUENCE_HEADER` 注入；**首段 writer 创建早于首帧**，此刻
   缓存可能为空，若首段 Finalize 失败/不可播，需把首段 writer 创建推迟到
   收到 SPS/PPS 之后（第 2 段起缓存已就位、自动生效）。
3. **AAC 编码**：`MFAudioFormat_AAC` 输出让系统 AAC MFT 编码；需核对系统
   AAC 编码器支持的 PCM 输入（位深/采样率/声道）。裸 PCM 直喂 MP4 sink
   会在 Finalize 报 `0xC00D4A45`（用户实测），必须用 AAC 输出。
4. **WASAPI**：显式 capture endpoint（`GetDefaultAudioEndpoint(eCapture)`
   或指定 `GetDevice(id)`），**不设置** `AUDCLNT_STREAMFLAGS_LOOPBACK`
   （禁回放声）；`IMMDeviceEnumerator` 默认设备切换（`GetId` 变化）重建
   `IAudioClient` 的时序。
5. **时间戳**：H264 ES 无内建时间戳，native 按 AU 顺序补 QPC 时间戳；
   AAC sample 是否要求严格等距、60min 累积漂移，须实机测。
6. **NAL 跨块**：Python 按块读 adb stdout，单条 NAL 可能跨两个块；
   `mf_native.py` 的 `NalBuffer` 已做块间缓冲，只吐出「后面已出现下一起始码」
   的完整 NAL，末条留到 `flush()`（已修重复发送 bug）。需真机验证 screenrecord
   在画面静止时是否仍持续出帧——`write_video` 借此周期性 drain 音频队列，
   若长时间无视频帧，音频队列可能积压触发 5s 上限。

## 平台下限 / 未专项验证项

- 下限：Windows 7（`MFCreateSinkWriterFromURL` 起支持；移除 moov 前置属性后
  不再受 Win8 下限约束）；目标 Win11 x64。
- 未专项验证：ARM64、HDR、多显示器拓扑变化、休眠唤醒后的设备句柄恢复、
  各 ROM 对 `--output-format=h264` 的支持率。
