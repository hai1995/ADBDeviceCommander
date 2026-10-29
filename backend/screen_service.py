# -*- coding: utf-8 -*-
"""
backend.screen_service —— 截图 + 录屏（视频，不含音频合成）。

  * screenshot(serial, save_dir)              对单台设备 exec-out screencap -p 写 PNG
  * VideoRecorder                              adb screenrecord 起/停 + 拉回本地

音频（设备端 tinycap / 电脑麦克风）与 ffmpeg 合成在 audio_service 中，
由 controller 在录屏会话里按需协同。本模块只负责「视频」这条线。

面向用户的状态文案一律由 controller 统一下发：本模块只**返回**结果
（路径 / 错误原因），不自行 push 事件——否则同一件事会被 controller 与
本模块各报一次，状态栏出现两行一模一样的内容。
"""
import itertools
import os
import signal
import subprocess
import threading
import time

from backend.device_proc import kill_device_process
from core import imgbytes
from core.constants import adb_kwargs, adb_popen_kwargs, no_window_flags, safe_name


class ScreenCapturer:
    # 文件名序号：时间戳只精确到秒，同一秒内的两次截图会算出**同一个路径** ——
    # 轻则后来的覆盖先前的（用户少了一张图），重则两个线程同时往同一文件写
    # （PNG 内容交错、文件损坏）。录屏远端文件名早有同样处理（见 VideoRecorder._seq）。
    _seq = itertools.count(1)

    @staticmethod
    def screenshot(adb, serial, save_dir):
        """对单台设备截图，返回本地 png 路径或 (None, 错误文本)。"""
        try:
            os.makedirs(save_dir, exist_ok=True)
        except Exception as e:
            return None, "无法创建保存目录 %s: %s" % (save_dir, e)
        ts = time.strftime("%Y%m%d_%H%M%S")
        # safe_name：无线 ADB 序列号形如 192.168.1.5:5555，冒号是 Windows
        # 文件名非法字符，不净化会让 open() 直接失败（截图静默丢失）。
        out = os.path.join(
            save_dir, "screenshot_%s_%s_%d.png" % (
                safe_name(serial), ts, next(ScreenCapturer._seq)))
        proc = None
        try:
            # 二进制管道：不能加 text/encoding（会破坏 PNG 字节），只补窗口隐藏
            proc = subprocess.Popen(
                [adb, "-s", serial, "exec-out", "screencap", "-p"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=no_window_flags())
            data, err = proc.communicate(timeout=30)
            if proc.returncode != 0 or not data:
                return None, (err or b"").decode(errors="ignore")[:200] or "空数据"
            # 归一化再落盘：部分车机 / 定制 ROM 的 screencap 会在 PNG 前先吐几行
            # 自己的东西，字节流因此「开头不是图片签名」——写下来是一张打不开的
            # 图，复制到剪贴板也会连累到 GDI+ 报「参数无效」。这里按签名切出有效
            # 段，保证磁盘上的文件就是一张能打开的图（详见 core.imgbytes）。
            data, kind, note = imgbytes.normalize(data)
            if not data:
                return None, "设备返回的图像无法识别（%s）" % note
            if kind and kind != "png":
                # 极少见：screencap 输出了 JPEG 等其它格式，扩展名跟着改，
                # 免得用户双击时被看图软件按 PNG 解析报错。
                ext = ".jpg" if kind == "jpg" else "." + kind
                out = os.path.splitext(out)[0] + ext
            # exec-out 输出为原始 PNG 二进制，禁止做任何换行翻译，原样写入
            with open(out, "wb") as f:
                f.write(data)
            return out, None
        except Exception as e:
            # 超时（设备无响应 / 被别的 adb 客户端抢锁）时 communicate() 只是抛错、
            # **不会**终止子进程：卡住的 adb exec-out 会变成孤儿进程一直挂着，
            # 且它占着 stdout 管道。这里必须显式回收（kill + 收尾读取）。
            if proc is not None:
                try:
                    proc.kill()
                    proc.communicate(timeout=5)
                except Exception:
                    pass
            return None, str(e)


# 设备端可视化 overlay 的 Settings.System 键名（录屏「指针位置 / 触摸圆点」用）。
# 二者都是**屏幕 overlay**（系统开发者选项同款），不是 screenrecord 参数：
#   * pointer_location  指针位置：画面常驻准星，跟随最近一次触摸位置；
#   * show_touches      显示触摸操作：触摸时屏幕出现圆点轨迹。
# 用系统设置而非 `screenrecord --show-pointer`（Android 10+ 才有）的原因：
# 后者在定制 ROM / 云手机 / 模拟器上上报的 SDK 与实际二进制常不一致，
# 传错参数会让整场录屏启动即失败；overlay 方案全版本可用、对录屏零风险，
# 且 overlay 画在屏幕上，会被 screenrecord 一并录进视频，目的一致。
KEY_POINTER_LOCATION = "pointer_location"
KEY_SHOW_TOUCHES = "show_touches"


class VideoRecorder:
    """单台设备的 screenrecord 会话：start() 后台录像，stop() 终止并 pull 回本地。

    bus 保留在构造参数里只为签名的稳定性（controller / 测试统一按
    (bus, adb) 构造）；本模块不再自行下发状态文案，由 controller 收口。
    """

    def __init__(self, bus, adb="adb"):
        self.bus = bus
        self.adb = adb
        self._lock = threading.Lock()
        self._sessions = {}          # serial -> dict(remote, local, proc, dir, extra)
        self._seq = itertools.count(1)  # 远端文件名序号，保证每次录制唯一

    def start(self, serial, save_dir, extra_name=None):
        """开始录屏（手动停止）。返回 (ok, 本地最终路径占位)。

        录屏只能手动停止：早期支持过「固定时长」（--time-limit + 到点自动
        pull），实际使用中手动停止更直观，该功能已移除——screenrecord
        会一直录到用户点「停止」，由 stop() 负责优雅收尾（SIGINT 写回 moov）。

        画面内的指针 / 触摸可视化（指针位置 / 触摸圆点）不走本方法：
        它们是设备系统设置的屏幕 overlay，由 controller 在录屏启动后
        另行开启、收尾时恢复（见 get_system_setting / set_system_setting）。
        """
        with self._lock:
            if serial in self._sessions:
                return False, "该设备已在录制"
        try:
            os.makedirs(save_dir, exist_ok=True)
        except Exception as e:
            return False, "无法创建保存目录 %s: %s" % (save_dir, e)
        ts = time.strftime("%Y%m%d_%H%M%S")
        base = extra_name or ts
        # 远端文件名带时间戳 + 序号：避免上一次崩溃残留的同一文件
        # 阻断本次 screenrecord 启动（screenrecord 拒绝覆盖已存在文件）。
        # 远端落到 /data/local/tmp/：该目录为 shell 所有、可写且可被 adb pull 稳定读取。
        # 远端文件名同样过 safe_name：无线序列号含冒号，adb shell 传参时
        # 冒号会被部分 ROM 的 shell 误判为分隔符，净化可保证命令稳定下发。
        remote = "/data/local/tmp/adb_rec_%s_%s_%d.mp4" % (
            safe_name(serial), ts, next(self._seq))
        # 本地文件名同样过 safe_name（无线序列号含冒号，Windows 下非法）
        local = os.path.join(
            save_dir, "record_%s_%s.mp4" % (safe_name(serial), base))
        # 关键：screenrecord 是「设备端」命令，必须经 `adb shell` 下发，而非 adb 的子命令
        # —— `adb screenrecord ...` 会直接报 `unknown command screenrecord`（这正是一直以来
        # 录屏启动即失败的真因）。落地路径用 /data/local/tmp/（shell 可写且可被 adb pull 稳定读取）。
        cmd = [self.adb, "-s", serial, "shell", "screenrecord"]
        cmd += [remote]
        proc, early_err = self._spawn_and_confirm(cmd)
        if proc is None:
            return False, early_err
        if early_err is not None:
            # 设备端 screenrecord 在 1~2s 内提前退出：权限 / 目录 / 设备状态
            # 等问题原样上报（重试无意义，还会掩盖真实错误）。
            return False, "录屏启动失败：screenrecord 提前退出%s" % (
                "（%s）" % early_err if early_err.strip() else "")
        with self._lock:
            self._sessions[serial] = {
                "remote": remote, "local": local, "proc": proc,
                "dir": save_dir, "done": threading.Event(),
            }
        # 进程意外死亡监测：adb root / 设备侧重启 adbd 会在录屏中途杀掉设备端
        # screenrecord，本地 adb 客户端随之退出。不监测的话界面会一直停在
        # 「录制中」，用户点「停止」后才在约 10 秒的 pull 重试后看到一句
        # 「缺 moov 头」。watcher 只负责**标记**（stop() 会先置 stopping，
        # 主动停止不算意外），由 controller 轮询到后自动走收尾 + 复位界面
        # （见 WebApi._reap_dead_recordings 与使用说明「录屏被中断」条）。
        threading.Thread(
            target=self._watch_exit, args=(serial, proc),
            daemon=True, name="rec-watch-%s" % serial).start()
        return True, local

    def _watch_exit(self, serial, proc):
        """阻塞等本地 adb 客户端退出；非主动停止即把会话标记为「意外死亡」。

        stop() / stop_all() 在终止进程前会先置 sess["stopping"]，因此 watcher
        醒来时看到该标记就能区分「用户主动停止」与「进程自己死了」。
        会话可能已被收尾弹掉（_pull_and_finish）——那种情况下无需标记。
        """
        try:
            proc.wait()
        except Exception:
            pass
        with self._lock:
            sess = self._sessions.get(serial)
            if (sess is not None and sess.get("proc") is proc
                    and not sess.get("stopping")):
                sess["died"] = True

    def died_serials(self):
        """取出并清除「意外退出」标记的序列号（controller 轮询调用）。

        只清 died 标记本身，会话条目保留（收尾时还要靠它拉残片），
        因此同一台设备只会被汇报一次，不会被反复收尾。
        """
        with self._lock:
            out = [s for s, sess in self._sessions.items() if sess.get("died")]
            for s in out:
                self._sessions[s].pop("died", None)
            return out

    def is_recording(self, serial):
        with self._lock:
            return serial in self._sessions

    def _spawn_and_confirm(self, cmd):
        """拉起 screenrecord 并短暂确认它真的活着。

        返回 (proc, early_err)：
        * proc 为 None 表示 Popen 本身失败，early_err 为「启动录屏失败：…」；
        * proc 非 None 但 early_err 非 None 表示进程在 1~2s 内提前退出
          （权限 / 参数错误等），early_err 为其 stderr 摘要，proc 为已退出的
          进程对象（调用方据此识别「起来了但又挂了」并决定是否重试）；
        * 两者都为空（proc 存活、early_err 为 None）才能继续往下走。
        """
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                **adb_popen_kwargs())
        except Exception as e:
            return None, "启动录屏失败：%s" % e
        try:
            if proc.poll() is None:
                time.sleep(1.5)
            if proc.poll() is not None:
                err = ""
                try:
                    err = (proc.stderr.read() or "")[:300]
                except Exception:
                    pass
                return proc, err
        except Exception:
            pass
        return proc, None

    # ---- 设备系统设置（可视化 overlay：指针位置 / 触摸圆点）----
    # 录屏的「指针位置 / 触摸圆点」是设备系统设置的屏幕 overlay（系统开发者
    # 选项同款）：录前备份原值并开启，收尾时按原值恢复。它与 screenrecord
    # 命令参数无关——不往录屏命令传任何东西，启动零风险（全 Android 版本
    # 可用），且 overlay 画在屏幕上，会被 screenrecord 一并录进视频。
    @staticmethod
    def get_system_setting(adb, serial, key):
        """读设备 Settings.System 里的键。返回 (ok, 原值字符串)。

        原值可能是 "0" / "1" / "null"（从未设置过）。ok=False 表示读不到
        （adb 不可用等），调用方应按「无法恢复」处理（不恢复优于乱恢复）。
        """
        try:
            r = subprocess.run(
                [adb, "-s", serial, "shell", "settings", "get", "system",
                 key], **adb_kwargs(10))
            if r.returncode != 0:
                return False, None
            val = (r.stdout or "").strip()
            # 老版本 settings 读不存在键时返回空串而非 "null"
            return True, (val or "null")
        except Exception:
            return False, None

    @staticmethod
    def set_system_setting(adb, serial, key, value):
        """写 / 删设备 Settings.System 键。返回是否成功（失败不抛）。

        value 为 "1" / "0" / None（None 或 "null"/空 = 删除该键，
        用于恢复「从未设置过」的设备原状）。
        """
        try:
            if value is None or str(value).strip().lower() in ("null", ""):
                cmd = [adb, "-s", serial, "shell", "settings", "delete",
                       "system", key]
            else:
                cmd = [adb, "-s", serial, "shell", "settings", "put",
                       "system", key, str(value)]
            r = subprocess.run(cmd, **adb_kwargs(10))
            return r.returncode == 0
        except Exception:
            return False

    def _stop_device_screenrecord(self, adb, serial):
        """精准结束设备端 screenrecord：用 SIGINT 让其优雅收尾（写回 moov 头），这是录出
        可播放 MP4 的关键——screenrecord 只在 SIGINT（Ctrl-C）下收尾，仅 SIGTERM 会直接被杀、
        文件没收尾（无 moov 头、没有时长、播放不了）。

        收尾顺序统一收口到 backend.device_proc.kill_device_process（录屏 / 录音共用）：
        按 PID `kill -INT` → **等它把 moov 写完** → 确认仍存活才补 `-TERM`（拿不到 PID 时
        同序退化为 pkill）。早期这里把 `-INT` 与 `-TERM` 背靠背发出去，进程很可能死在
        写 moov 的中途——等于白优雅一次，产物依旧是坏文件。
        """
        kill_device_process(adb, serial, "screenrecord")

    def stop(self, serial):
        """停止录屏并拉回本地。返回 (ok, local_path, err)。"""
        with self._lock:
            sess = self._sessions.get(serial)
            if sess is not None:
                # 告知 _watch_exit：这是用户主动停止，别把随后的进程退出当成
                # 「意外死亡」上报给 controller（否则会触发一轮多余的自动收尾）。
                sess["stopping"] = True
        if sess is None:
            return False, None, "该设备未在录制"
        proc = sess.get("proc")
        # 1) POSIX：给本地 adb 客户端发 SIGINT（等价于终端里 Ctrl-C），adb 会把中断转发给
        #    设备端 screenrecord，后者由此优雅收尾（写回 moov 头并关闭文件）。这是标准停止路径，
        #    能确保录出可播放的 MP4。Windows 不支持给子进程 send_signal(SIGINT)，改为靠下方的
        #    设备端按 PID 精准结束。
        if proc is not None and os.name != "nt":
            try:
                proc.send_signal(signal.SIGINT)
            except Exception:
                pass
        # 2) 设备端按 PID 精准结束 screenrecord（比 pkill 更通用）；并给一点时间收尾。
        self._stop_device_screenrecord(self.adb, serial)
        try:
            if proc is not None:
                proc.wait(timeout=10)
        except Exception:
            try:
                if proc is not None:
                    proc.kill()
            except Exception:
                pass
        return self._pull_and_finish(serial)

    def stop_all(self):
        """停止全部录制会话。

        每台设备单独兜异常：`stop()` 内部要写盘 / pull / 合成，任一环节抛错
        （最现实的是保存目录所在磁盘被拔掉）都不该让**后面的设备完全不被收尾** ——
        它们的设备端 screenrecord 会继续录到 Android 自带的 3 分钟上限，
        `_sessions` 里也已经 pop 掉无法重试（controller.shutdown 只是吞掉异常）。
        """
        with self._lock:
            serials = list(self._sessions.keys())
        for s in serials:
            try:
                self.stop(s)
            except Exception:
                continue

    @staticmethod
    def _remote_exists(adb, serial, remote):
        """设备端文件是否存在（screenrecord 收尾后才生成，故 stop 时需轮询等待）。"""
        try:
            r = subprocess.run(
                [adb, "-s", serial, "shell", "ls", remote], **adb_kwargs(15))
            return r.returncode == 0 and (r.stdout or "").strip() != ""
        except Exception:
            return False

    @staticmethod
    def _mp4_has_moov(path):
        """MP4 是否含 moov 头（索引在文件尾部，screenrecord 优雅收尾时写回）。
        缺 moov 即未正常收尾，会没有时长、播放不了。仅扫描头/尾各 4MB（moov 在尾部）。"""
        try:
            size = os.path.getsize(path)
            if size < 64:
                return False
            with open(path, "rb") as f:
                head = f.read(min(size, 4 * 1024 * 1024))
                if b"moov" in head:
                    return True
                f.seek(max(0, size - 4 * 1024 * 1024))
                return b"moov" in f.read()
        except Exception:
            return False

    def _pull_and_finish(self, serial):
        with self._lock:
            sess = self._sessions.pop(serial, None)
        if sess is None:
            return False, None, "会话已结束"
        local = sess["local"]
        remote = sess["remote"]
        # 保存目录可能在录制过程中消失（U 盘/移动硬盘被拔、目录被删）。旧实现在这里
        # 直接抛 OSError：异常一路冒到 controller，跳过本会话的其余收尾，也让
        # stop_all 的循环中断、后面的设备统统不再收尾。转成一条明确的失败返回。
        try:
            os.makedirs(sess["dir"], exist_ok=True)
        except Exception as e:
            return False, local, "无法创建保存目录 %s：%s" % (sess["dir"], e)
        # 收尾/落盘有延迟：device 端 screenrecord 收到 SIGTERM 后需要一点时间写回
        # moov 头并关闭文件。这里先确认远端文件已就绪，再 pull，带退避重试。
        # 注意：adb 的报错信息有时落在 stdout（而非 stderr），两路都要采集，避免
        # 把真实错误吞成一句空泛的「pull 失败」。
        last_err = "pull 失败"
        for attempt in range(6):
            if self._remote_exists(self.adb, serial, remote):
                try:
                    r = subprocess.run(
                        [self.adb, "-s", serial, "pull", remote, local],
                        **adb_kwargs(120))
                    err = ((r.stderr or "") + "\n" + (r.stdout or "")).strip()
                    if r.returncode == 0 and os.path.exists(local):
                        # 校验 MP4 已收尾（含 moov 头）：否则没有时长、播放不了
                        if not VideoRecorder._mp4_has_moov(local):
                            try:
                                subprocess.run(
                                    [self.adb, "-s", serial, "shell", "rm", "-f", remote],
                                    **adb_kwargs(10))
                            except Exception:
                                pass
                            # 状态文案由 controller 统一下发（这里只回结果）：早期在此
                            # 自行 push 一条 warn，controller 又按返回值推一条，同一次
                            # 失败会在状态栏出现两行内容重叠的提示。
                            return False, local, "录屏文件疑似未正常收尾（MP4 缺 moov 头，无法播放）"
                        # 录像结束，清理设备端临时文件
                        try:
                            subprocess.run(
                                [self.adb, "-s", serial, "shell", "rm", "-f", remote],
                                **adb_kwargs(10))
                        except Exception:
                            pass
                        # 同上：成功文案由 controller 按其上下文（是否合成音频 / 打包）
                        # 统一下发，这里再 push 一次会让状态栏出现两行相同的
                        # 「✓ 录屏已保存: <同一个路径>」。
                        return True, local, None
                    if err:
                        last_err = err[:200]
                    else:
                        last_err = "pull 返回非零但无错误输出（可能设备端文件未就绪）"
                except Exception as e:
                    last_err = str(e)[:200]
            else:
                last_err = "设备端未生成录屏文件 %s（screenrecord 可能未启动/提前退出）" % remote
            if attempt < 5:
                time.sleep(0.6 * (attempt + 1))
        return False, None, last_err
