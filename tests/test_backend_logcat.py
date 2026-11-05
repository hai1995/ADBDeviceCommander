"""backend.logcat_service.LogcatCapture 的单元测试（不依赖真实设备）。

用可控的假 Popen 模拟 `adb logcat` 输出，配合假 bus 收集事件，验证打包策略：

  * 默认（结束后打包 zip 开启）：停止时 **打包整份 txt**（源 txt 清理）；
  * 显式关闭（zip_on_stop=False）：停止时 **不** 打包，txt 原样保留；
  * 抓取过程 **没有任何按大小触发的自动动作**：写多少行都是单文件一路
    到底——旧实现的「超 15M 自动分包打包」已按用户要求整体移除。

⚠️ 用例约定：凡是**真启动了抓取 worker** 的用例（controller 的两个
logcat_capture_start 用例），尾部必须 `_stop_capture_now(api)` 停掉并等待退出。
本文件的假 Popen 默认「永不停产出」，不收尾的 worker 会抱着读循环无限空转、
吃满 GIL，把后续所有用例拖到秒级——整套 pytest 直接被拖到假死。
"""
import os
import threading
import time

import pytest

import backend.logcat_service as ls
from backend.controller import WebApi

# patch_ctrl 见 tests/conftest.py：物理拆分后方法实现在 backend.controllers
# 子模块里，patch 必须打到子模块的命名空间才生效。
from conftest import patch_ctrl


class _FakeBus:
    def __init__(self):
        self.events = []

    def push(self, kind, payload=None):
        self.events.append({"kind": kind, "payload": payload})

    def last_capture_event(self, status):
        for e in reversed(self.events):
            if e["kind"] == "logcat_capture" and e["payload"].get("status") == status:
                return e["payload"]
        return None

    def has_capture_status(self, status):
        return any(
            e["kind"] == "logcat_capture" and e["payload"].get("status") == status
            for e in self.events)

    def has_status(self, kind, status):
        """任意通道的某个 status 是否出现过（监控 / 抓取共用）。"""
        return any(
            e["kind"] == kind and (e["payload"] or {}).get("status") == status
            for e in self.events)


class _FakeLogcatProc:
    """模拟 `adb logcat`。

    block_after：产出前 N 行后挂起（等待 terminate），用于「长时间抓取」场景，
    保证 worker 停在循环里，使 stop() 的 zip_on_stop 必然在其运行期内生效。
    不传则无限循环产出，用于验证「抓取过程不因行数/大小发生任何自动动作」。
    """

    def __init__(self, lines, block_after=None):
        self._lines = list(lines) if lines else [""]
        self._i = 0
        self._stop = False
        self._block = threading.Event()
        self._parked = threading.Event()   # 已产出 block_after 行并停在 wait
        self._max = block_after
        self.returncode = 0

    @property
    def stdout(self):
        return self

    def __iter__(self):
        return self

    def __next__(self):
        if self._stop:
            raise StopIteration
        if self._max is not None and self._i >= self._max:
            self._parked.set()             # 标记已停在循环里（供测试等待）
            self._block.wait()             # 停在循环里，直到 terminate
            raise StopIteration
        line = self._lines[self._i % len(self._lines)]
        self._i += 1
        return line

    def parked(self, timeout=5.0):
        return self._parked.wait(timeout)

    def terminate(self):
        self._stop = True
        self._block.set()

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0


def _wait_running(cap, serial, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cap.is_running(serial):
            return True
        time.sleep(0.01)
    return False


def _wait_stopped(bus, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if bus.has_capture_status("stopped"):
            return True
        time.sleep(0.02)
    return False


@pytest.mark.parametrize("kw", ["fatal", "FATAL", "Fatal"])
def test_keyword_filter_ignores_case(kw):
    """关键字过滤不区分大小写（旧实现只对全小写关键字生效，等于时灵时不灵）。"""
    rec = ls.LogcatMonitor._classify_and_filter(
        "08-29 10:23:45.123  1234  1234 E libc: Fatal signal 11\n",
        set("VDIWEF"), kw, False)
    assert rec is not None, "关键字 %r 未命中" % kw


def test_keyword_filter_rejects_unmatched():
    assert ls.LogcatMonitor._classify_and_filter(
        "08-29 10:23:45.123  1234  1234 E libc: Fatal signal 11\n",
        set("VDIWEF"), "no-such-key", False) is None


def _wait_not_running(obj, serial, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if not obj.is_running(serial):
            return True
        time.sleep(0.02)
    return False


def test_monitor_stop_terminates_subprocess(monkeypatch):
    """停止监控必须终止 adb 子进程。

    回归：旧实现只 set 一个 Event，而 worker 卡在 `for raw in proc.stdout`
    （adb 没新日志时一直阻塞），读不到下一行就永远检查不到该 Event ——
    表现为「点了停止没反应」、`adb logcat` 子进程残留、再 start 被判已在运行。
    """
    proc = _FakeLogcatProc(["08-29 10:23:45.123  1234  1234 I Tag: hi\n"],
                           block_after=1)
    monkeypatch.setattr(ls.subprocess, "Popen", lambda cmd, **kw: proc)

    bus = _FakeBus()
    mon = ls.LogcatMonitor(bus, adb_path="adb")
    assert mon.start("A1", ["main"]) is True
    # 等 worker 阻塞在 stdout 读循环里（等价于「设备长时间没有新日志」）
    assert proc.parked(5), "worker 未停在读循环内"
    assert mon.stop("A1") is True
    assert proc._stop is True, "stop() 必须终止子进程，否则监控停不掉"
    assert _wait_not_running(mon, "A1"), "停止后监控状态未复位"


def test_monitor_stop_immediately_after_start(tmp_path, monkeypatch):
    """启动瞬间就点停止：监控必须能停下来，且可以立刻重新开始。

    回归：LogcatMonitor 只有 _stops（Event）与 _procs（Popen），而 _procs 要等
    worker 里 Popen 返回后才登记。stop() 若落在这段窗口里，只置了 Event、拿不到
    proc，于是什么都没终止；worker 随后登记进程、推 running，并阻塞在
    `for raw in proc.stdout` 上 —— 只有读到下一行才会检查 stop_ev，设备安静时
    永远读不到。表现为「点了停止没反应」+ 再次 start 被判 already_running。
    LogcatCapture 早有 _stopreq 机制，监控这条路径一直漏着。
    """
    proc = _FakeLogcatProc(["08-29 10:23:45.123  1234  1234 I Tag: hi\n"],
                           block_after=0)
    holder = {}

    def slow_popen(cmd, **kw):
        time.sleep(0.25)          # 模拟 Popen 尚未返回：worker 还没登记 proc
        holder["proc"] = proc
        return proc

    monkeypatch.setattr(ls.subprocess, "Popen", slow_popen)
    bus = _FakeBus()
    mon = ls.LogcatMonitor(bus, adb_path="adb")
    assert mon.start("A1", ["main"]) is True
    # Popen 还没返回就点停止：此时 _procs 里没有进程
    assert mon.stop("A1") is True, "启动瞬间的 stop() 必须认账"
    assert _wait_not_running(mon, "A1"), "启动瞬间停止后监控状态未复位"
    assert proc._stop is True, "worker 登记进程后必须立刻收尾，否则 adb logcat 残留"
    # 状态复位后应能立刻重新开始（旧实现会一直判 already_running）
    assert mon.start("A1", ["main"]) is True, "停止后必须能重新开始监控"
    assert mon.stop("A1") is True
    # 「启动瞬间就停止」那一轮不该广播过 running：前端收到它会把状态切成
    # 「采集中…」、把「开始监控」锁上，紧接着又被 stopped 拨回来。
    assert not bus.has_status("logcat", "running"), \
        "启动瞬间就停止不该广播「运行中」"


def test_capture_stop_immediately_after_start(tmp_path, monkeypatch):
    """启动瞬间就点停止：stop 要认账，抓取线程也要能收尾。

    回归：worker 还没把 Popen 登记进 _procs 时 stop() 找不到进程就返回 False，
    「开始抓取后马上点停止」于是永远停不下来。
    """
    proc = _FakeLogcatProc(["08-29 10:23:45.123  1234  1234 I Tag: hi\n"],
                           block_after=0)
    holder = {}

    def slow_popen(cmd, **kw):
        time.sleep(0.25)          # 模拟 Popen 尚未返回：worker 还没登记 proc
        holder["proc"] = proc
        return proc

    monkeypatch.setattr(ls.subprocess, "Popen", slow_popen)
    bus = _FakeBus()
    cap = ls.LogcatCapture(bus, adb_path="adb")
    path = str(tmp_path / "logcat_R_001.txt")
    assert cap.start("R", path, ["main"]) is True
    assert cap.stop("R", zip_on_stop=False) is True, "启动瞬间的停止必须返回 True"
    assert _wait_not_running(cap, "R"), "抓取未在停止后收尾"
    assert _wait_stopped(bus), "未推 stopped 事件"


def _start_then_stop_at_once(tmp_path, monkeypatch):
    """启动后立刻点停止（stop 落在 _starting 窗口内），返回 (bus, path)。"""
    proc = _FakeLogcatProc(["08-29 10:23:45.123  1234  1234 I Tag: hi\n"],
                           block_after=0)
    holder = {}

    def slow_popen(cmd, **kw):
        time.sleep(0.15)          # 让 stop() 落在 _starting 窗口内（启动瞬间）
        holder["proc"] = proc
        return proc

    monkeypatch.setattr(ls.subprocess, "Popen", slow_popen)
    bus = _FakeBus()
    cap = ls.LogcatCapture(bus, adb_path="adb")
    path = str(tmp_path / "logcat_X_001.txt")
    assert cap.start("X", path, ["main"]) is True
    assert cap.stop("X", zip_on_stop=True) is True
    assert _wait_stopped(bus), "未推 stopped 事件"
    return bus, path


def test_capture_stopped_at_startup_is_not_broadcast_as_running(tmp_path, monkeypatch):
    """启动瞬间就点停止：不该再广播「运行中」。

    旧行为：worker 发现 stop_now 后照样推一条 running。前端收到它会把状态切成
    「采集中…」、把「开始抓取」锁上，紧接着又被 stopped 拨回来 ——
    一次从未成立的状态。
    """
    bus, _path = _start_then_stop_at_once(tmp_path, monkeypatch)
    assert not bus.has_capture_status("running"), \
        "启动瞬间就停止不该广播「运行中」"


def test_capture_stopped_at_startup_leaves_no_empty_file(tmp_path, monkeypatch):
    """启动瞬间就点停止：不留 0 字节 txt，也不报「✓ 抓到 0 行」。

    旧行为：worker 照样 open(path, "w")，于是磁盘上多出一个 0 字节 txt；前端
    随后弹「✓ Logcat 抓取完毕：0 行 → logcat_X_001.txt」。用户拿着这个空文件
    去分析，只会得出「设备当时确实没有日志输出」这个错误结论。
    """
    bus, path = _start_then_stop_at_once(tmp_path, monkeypatch)
    assert not os.path.exists(path), "一行都没抓到就不该留下 0 字节 txt"
    assert not os.path.exists(path + ".zip"), "空文件不该被打包"
    ev = bus.last_capture_event("stopped")
    assert ev.get("no_file") is True
    assert "没有生成" in (ev.get("text") or ""), "得说清本次没有生成文件"
    assert not ev.get("zip_error"), "没有文件可打包时不该报「打包失败」"


def _make_capture(bus, monkeypatch, lines, block_after=None, getsize=None):
    cap = ls.LogcatCapture(bus, adb_path="adb")
    holder = {}

    def fake_popen(cmd, **kw):
        if "logcat" in " ".join(cmd):
            holder["proc"] = _FakeLogcatProc(lines, block_after=block_after)
            return holder["proc"]
        return _FakeLogcatProc([])

    monkeypatch.setattr(ls.subprocess, "Popen", fake_popen)
    if getsize is not None:
        monkeypatch.setattr(ls.os.path, "getsize", lambda p: getsize)
    return cap, holder


def test_capture_default_no_zip_on_stop(tmp_path, monkeypatch):
    """显式关闭打包（zip_on_stop=False）-> 正常停止不打包，txt 原样保留。"""
    bus = _FakeBus()
    lines = ["08-29 10:00:00.000  1  1 I Tag: hello %d\n" % i for i in range(5)]
    cap, holder = _make_capture(bus, monkeypatch, lines, block_after=3)
    path = str(tmp_path / "logcat_X_001.txt")
    assert cap.start("X", path, ["main"]) is True
    assert _wait_running(cap, "X"), "worker 未进入运行态"
    assert holder["proc"].parked(), "假进程未停在循环内（worker 未写满 block_after 行）"
    cap.stop("X", zip_on_stop=False)
    assert _wait_stopped(bus), "worker 未推 stopped 事件"
    assert not bus.has_capture_status("zipped"), "默认不应打包"
    assert not os.path.exists(path + ".zip"), "不应生成 .zip"
    assert os.path.exists(path), "原始 txt 应保留"
    # 未打包：stopped 带 packaged=False，前端据此弹「抓取完毕」toast
    # （打包场景由 zipped 事件弹「已打包」，stopped 不重复）
    ev_stop = bus.last_capture_event("stopped")
    assert ev_stop["packaged"] is False, "未打包时 packaged 必须为 False"


def test_capture_zip_on_stop_when_requested(tmp_path, monkeypatch):
    """结束后打包 zip（zip_on_stop=True）-> 停止时打包。"""
    bus = _FakeBus()
    lines = ["08-29 10:00:00.000  1  1 I Tag: hello %d\n" % i for i in range(5)]
    cap, holder = _make_capture(bus, monkeypatch, lines, block_after=3)
    path = str(tmp_path / "logcat_X_002.txt")
    assert cap.start("X", path, ["main"]) is True
    assert _wait_running(cap, "X"), "worker 未进入运行态"
    assert holder["proc"].parked(), "假进程未停在循环内（worker 未写满 block_after 行）"
    cap.stop("X", zip_on_stop=True)
    assert _wait_stopped(bus), "worker 未推 stopped 事件"
    ev = bus.last_capture_event("zipped")
    assert ev is not None, "应推 zipped 事件"
    assert os.path.exists(path + ".zip"), "应生成 .zip"
    # 打包完成后应清理源 txt（防止内容重复占磁盘）
    assert not os.path.exists(path), "打包成功后源 txt 应被清理"
    ev_stop = bus.last_capture_event("stopped")
    assert ev_stop["size"] > 0, "stopped 事件的 size 应改为 zip 大小"
    assert ev_stop["packaged"] is True, \
        "已打包时 packaged 必须为 True（前端据此跳过重复的完成 toast）"


def test_capture_never_rolls_over_mid_capture(tmp_path, monkeypatch):
    """抓取过程没有任何按大小/行数触发的自动动作：单文件一路写到底。

    旧实现有「超 15M 自动分包打包」，已按用户要求整体移除（用户原话：
    「算了，我不是要分段打包，将其相关功能移除掉吧」）。本测试锁定新语义——
    写满 2500 行（远超旧检查点）也不得出现第二分段、不得自行打包、
    不得自行停止：一切只由用户点「停止抓取」决定。
    """
    bus = _FakeBus()
    lines = ["08-29 10:00:00.000  1  1 I Tag: line %d\n" % i for i in range(2500)]
    cap, holder = _make_capture(bus, monkeypatch, lines, block_after=2500)
    path = str(tmp_path / "logcat_X_003.txt")
    assert cap.start("X", path, ["main"]) is True
    assert holder["proc"].parked(5), "假进程未停在循环内（未写满 2500 行）"
    # 关键 1：抓取仍在运行——没有 stopped、没有 zipped、没有 rolled
    assert not bus.has_capture_status("stopped"), "抓取过程不得自行停止"
    assert not bus.has_capture_status("zipped"), "抓取过程不得自行打包"
    assert cap.is_running("X"), "抓取应仍在运行"
    # 关键 2：始终只有一个文件，没有任何 _partN 分段
    assert os.path.exists(path), "单文件应保留"
    assert not os.path.exists(path + ".zip"), "抓取过程不得生成 zip"
    parts = [p for p in os.listdir(tmp_path) if "_part" in p]
    assert not parts, "不得出现分包文件：%r" % parts
    # 手动停止并勾选打包：整份 txt 打成唯一一个 zip
    cap.stop("X", zip_on_stop=True)
    assert _wait_stopped(bus), "worker 未推 stopped 事件"
    ev = bus.last_capture_event("zipped")
    assert ev is not None, "勾了「结束后打包」应推 zipped 事件"
    assert ev["path"] == path + ".zip", "应打包唯一的那个文件"
    assert os.path.exists(path + ".zip"), "应生成 .zip"
    assert not os.path.exists(path), "打包成功后源 txt 应被清理"


def test_capture_stop_no_device_is_noop(tmp_path, monkeypatch):
    """对未启动的设备调用 stop 应安全返回 False，不抛异常。"""
    bus = _FakeBus()
    cap, _holder = _make_capture(bus, monkeypatch, [])
    assert cap.stop("never_started") is False


def test_capture_open_failure_cleans_up_and_allows_restart(tmp_path, monkeypatch):
    """落盘文件打不开（目录被删 / 磁盘掉线 / 只读）时：worker 必须正常收尾。

    回归：旧实现把 `f = open(...)` 放在 try 内、finally 里却读 `f` —— open 一失败
     finally 先抛 UnboundLocalError，后面的状态清理（_procs/_starting/_stopreq/
    _flags）全部被跳过、子进程也没 terminate：抓取永远卡在「运行中」
    （is_running 恒 True、再 start 判 already_running、用户点停止也停不掉），
    并泄漏一个 adb logcat 进程。
    """
    proc = _FakeLogcatProc(["08-29 10:00:00.000  1  1 I Tag: hi\n"])
    monkeypatch.setattr(ls.subprocess, "Popen", lambda cmd, **kw: proc)
    bus = _FakeBus()
    cap = ls.LogcatCapture(bus, adb_path="adb")
    # 指向不存在目录下的文件：open() 必然抛 FileNotFoundError
    bad_path = str(tmp_path / "no_such_dir" / "logcat_B_001.txt")
    assert cap.start("B", bad_path, ["main"]) is True
    # worker 必须自行收尾：状态复位、推 error、子进程被终止
    assert _wait_not_running(cap, "B"), "open 失败后抓取状态未复位（卡在运行中）"
    assert proc._stop is True, "open 失败后 adb logcat 子进程未被终止（泄漏）"
    err = bus.last_capture_event("error")
    assert err is not None and "抓取异常" in (err.get("text") or ""), err
    # 状态干净后应能再次 start（旧实现会永远判 already_running）
    ok_path = str(tmp_path / "logcat_B_002.txt")
    assert cap.start("B", ok_path, ["main"]) is True, "收尾后必须能重新开始抓取"
    cap.stop("B", zip_on_stop=False)
    assert _wait_not_running(cap, "B")


def _stop_capture_now(api, serial="X"):
    """立刻停掉本次真启动的抓取 worker 并等它退出（防泄漏，见模块 docstring）。

    这两个 controller 用例里的假 Popen 是**永不停产出**的（`_FakeLogcatProc([])`，
    block_after=None → 无限循环），worker 会抱着 `for raw in proc.stdout` 一直空转。
    不在用例尾部收掉它，GIL 被持续吃满，后续每个用例都被拖到约 1 秒，整套测试
    直接劣化到「假死」（实测本文件 21 个用例从约 2 秒劣化到 77 秒）。
    """
    api.logcat_capture.stop(serial, zip_on_stop=False)
    assert _wait_not_running(api.logcat_capture, serial), "抓取 worker 未在停止后退出"


def test_controller_capture_start_falls_back_to_default_dir(tmp_path, monkeypatch):
    """logcat_capture_start 收到 None 目录时回退到默认保存目录，不抛异常。"""
    fake_proc = _FakeLogcatProc([])

    def fake_popen(cmd, **kw):
        return fake_proc

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    # 隔离外部环境：config.json 里的真实 save_dir 与真实家目录都会让本用例
    # 「看心情」通过（装了偏好的机器上永远走不到回退分支），故这里固定为空偏好
    # + 临时家目录，既保证断言确定，也不在用户机器上真的建目录。
    patch_ctrl(monkeypatch, "load_prefs", lambda: {})
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))

    api = WebApi()
    api.state.adb_path = "adb"
    res = api.logcat_capture_start("X", None, ["main"])
    assert res["ok"] is True
    assert "logcat_X_" in res["path"]
    # 默认目录应为 ~/Pictures/ADB 下的文件
    assert "Pictures" in res["path"]
    _stop_capture_now(api)


def test_controller_capture_start_prefers_prefs_save_dir(tmp_path, monkeypatch):
    """config.json 里配了 save_dir 且该目录在本机存在时优先用它。

    目录必须已存在才直接采用：配置被拷到别的电脑后，源机的绝对路径在
    新机通常不存在 —— 那种情况由 resolve_save_dir 回退默认目录
    （另见 test_core_prefs 的跨设备用例），绝不往不存在的路径里写。
    """
    monkeypatch.setattr("subprocess.Popen", lambda cmd, **kw: _FakeLogcatProc([]))
    want = str(tmp_path / "my_save")
    os.makedirs(want, exist_ok=True)
    patch_ctrl(monkeypatch, "load_prefs", lambda: {"save_dir": want})

    api = WebApi()
    api.state.adb_path = "adb"
    res = api.logcat_capture_start("X", None, ["main"])
    assert res["ok"] is True
    assert res["path"].startswith(want)
    _stop_capture_now(api)


# ---------------------------------------------------------------------------
# 级别过滤：空列表 = 一个级别都不要（而不是回退成全开）
# ---------------------------------------------------------------------------
def _start_and_capture_levels(monkeypatch, level_filter):
    """启动监控并把 worker 实际收到的级别集合摘出来（worker 用替身，不起真进程）。"""
    seen = []
    done = threading.Event()

    def fake_worker(self, *args):
        seen.append(args)
        done.set()

    monkeypatch.setattr(ls.LogcatMonitor, "_worker", fake_worker)
    mon = ls.LogcatMonitor(_FakeBus(), "adb")
    if level_filter is None:
        assert mon.start("A1", ["main"]) is True
    else:
        assert mon.start("A1", ["main"], level_filter=level_filter) is True
    assert done.wait(5.0), "worker 未被拉起"
    return seen[0][2]        # args = (serial, buffers, levels, keyword, only_exc, ev)


def test_empty_level_filter_means_no_levels(monkeypatch):
    """用户取消勾选**全部**级别时前端传的是空列表 []，必须解释为「一个级别都不要」。

    回归：`set(level_filter or "VDIWEF")` 在 [] 时会回退成全开 —— 用户明明关掉了
    所有级别，后端仍把每一行都收进来（白跑一趟，且与前端空视图 + 计数对不上）。
    """
    assert _start_and_capture_levels(monkeypatch, []) == set()


def test_missing_level_filter_defaults_to_all(monkeypatch):
    """不传 level_filter（None）才是默认全开。"""
    assert _start_and_capture_levels(monkeypatch, None) == set("VDIWEF")


# ---------------------------------------------------------------------------
# 落盘抓取的级别过滤：与实时监控同语义（能识别级别的行按勾选集合过滤，
# 识别不出的行——adb 标题/分隔线——原样写盘，不丢元信息）。
# ---------------------------------------------------------------------------
def _capture_to_file(tmp_path, monkeypatch, lines, level_filter, tag):
    """起一次抓取，写完全部行后停止，返回文件内容。"""
    bus = _FakeBus()
    cap, holder = _make_capture(bus, monkeypatch, lines, block_after=len(lines))
    path = str(tmp_path / ("logcat_L_%s.txt" % tag))
    assert cap.start("L", path, ["main"], level_filter=level_filter) is True
    assert _wait_running(cap, "L"), "worker 未进入运行态"
    assert holder["proc"].parked(), "假进程未停在循环内（未写完全部行）"
    cap.stop("L", zip_on_stop=False)
    assert _wait_stopped(bus), "worker 未推 stopped 事件"
    with open(path, encoding="utf-8") as f:
        return f.read()


_ALL_LEVELS = ["V", "D", "I", "W", "E", "F"]


def _level_lines(tag):
    """每个级别各一行（threadtime 格式），行内容带 tag 便于断言归属。"""
    return ["08-29 10:00:00.000  1  1 %s Tag: %s-%s\n" % (lv, tag, lv)
            for lv in _ALL_LEVELS]


def test_capture_level_filter_writes_only_selected_levels(tmp_path, monkeypatch):
    """level_filter=["I","W"]：只有 I/W 的 threadtime 行落盘，其余级别被拦掉。"""
    lines = _level_lines("x") + ["--------- beginning of main\n"]
    text = _capture_to_file(tmp_path, monkeypatch, lines, ["I", "W"], "iw")
    assert "x-I" in text and "x-W" in text
    for lv in ("V", "D", "E", "F"):
        assert "x-%s" % lv not in text, "级别 %s 不应写盘" % lv
    # 非 threadtime 行（adb 自己的标题）原样保留，丢它反而对不上设备现场
    assert "beginning of main" in text


def test_capture_none_level_filter_means_all(tmp_path, monkeypatch):
    """level_filter=None（默认）：六个级别全写。"""
    lines = _level_lines("a")
    text = _capture_to_file(tmp_path, monkeypatch, lines, None, "none")
    for lv in _ALL_LEVELS:
        assert "a-%s" % lv in text


def test_capture_empty_level_filter_means_nothing(tmp_path, monkeypatch):
    """level_filter=[]（用户取消了全部级别）：threadtime 行一个都不写。"""
    lines = _level_lines("z") + ["--------- beginning of main\n"]
    text = _capture_to_file(tmp_path, monkeypatch, lines, [], "empty")
    for lv in _ALL_LEVELS:
        assert "z-%s" % lv not in text
    assert "beginning of main" in text, "不可识别行仍应原样写盘"


def test_controller_capture_start_passes_level_filter(tmp_path, monkeypatch):
    """controller.logcat_capture_start 必须把 level_filter 透传给抓取器。"""
    seen = {}

    def spy_start(self, serial, path, buffers, level_filter=None):
        seen["args"] = (serial, path, buffers, level_filter)
        return False        # 假装已在抓取中，避免起真线程

    monkeypatch.setattr(ls.LogcatCapture, "start", spy_start)
    api = WebApi()
    api.state.adb_path = "adb"
    res = api.logcat_capture_start("X", str(tmp_path), ["main"],
                                   level_filter=["I", "W"])
    assert res["ok"] is False and res["reason"] == "already_running", res
    assert seen["args"][0] == "X"
    assert seen["args"][2] == ["main"]
    assert seen["args"][3] == ["I", "W"]


def test_controller_capture_start_without_filter_is_none(tmp_path, monkeypatch):
    """不传级别（None）时抓取器收到的必须是 None（全量），不是 [] 或默认集合。"""
    seen = {}

    def spy_start(self, serial, path, buffers, level_filter=None):
        seen["lf"] = level_filter
        return False

    monkeypatch.setattr(ls.LogcatCapture, "start", spy_start)
    api = WebApi()
    api.state.adb_path = "adb"
    api.logcat_capture_start("X", str(tmp_path), ["main"])
    assert seen["lf"] is None


def test_level_filter_desc_hides_full_selection():
    """全选或未过滤时状态文案不带级别后缀（不刷屏）；部分勾选才显示。"""
    from backend.controller import WebApi as _Api
    assert _Api._level_filter_desc(None) == ""
    assert _Api._level_filter_desc(list("VDIWEF")) == ""
    assert _Api._level_filter_desc(["I", "W"]) == "（级别: I/W）"
    assert _Api._level_filter_desc(["E", "F"]) == "（级别: E/F）"


# ---------------------------------------------------------------------------
# 同一秒内「停止 → 再抓」：绝不能覆盖上一份结果
# ---------------------------------------------------------------------------
def _start_capture_path(tmp_path, monkeypatch):
    """以固定的时间戳启动一次抓取，返回控制器算出的路径（不真起 worker）。"""
    seen = {}

    def spy_start(self, serial, path, buffers, level_filter=None):
        seen["path"] = path
        return False          # 假装已在抓取，避免起真线程

    monkeypatch.setattr(ls.LogcatCapture, "start", spy_start)
    monkeypatch.setattr(time, "strftime", lambda fmt: "20260101_120000")
    api = WebApi()
    api.state.adb_path = "adb"
    api.logcat_capture_start("X", str(tmp_path), ["main"])
    return seen["path"]


def test_capture_path_not_overwritten_within_one_second(tmp_path, monkeypatch):
    """同一秒内再次抓取必须换个名字，不能把上一份日志截断成 0 字节。

    回归：文件名时间戳只到秒，用户「停止 → 立刻再抓」很容易落在同一秒：
    `open(path, "w")` 直接把上一次抓好的日志清空，界面上那份「已抓 N MB」的
    文件变成空文件。
    """
    first = _start_capture_path(tmp_path, monkeypatch)
    assert os.path.basename(first) == "logcat_X_20260101_120000.txt"
    with open(first, "w", encoding="utf-8") as f:
        f.write("上次抓到的内容")

    second = _start_capture_path(tmp_path, monkeypatch)
    assert second != first
    assert second.endswith("_2.txt"), second
    # 上一份内容必须原封不动
    with open(first, encoding="utf-8") as f:
        assert f.read() == "上次抓到的内容"


def test_capture_path_avoids_overwriting_existing_zip(tmp_path, monkeypatch):
    """上一份已被打包成 zip（源 txt 已删）时，同样要换名字。

    只检查 txt 是否存在是不够的：勾了「结束后打包」的抓取会把 txt 打成同名
    zip 并删掉源文件，于是 txt 不在、zip 在 —— 停止时 `ZipFile(..., "w")`
    又把这唯一一份压缩包覆盖掉。
    """
    zip_path = os.path.join(str(tmp_path), "logcat_X_20260101_120000.txt.zip")
    with open(zip_path, "wb") as f:
        f.write(b"PK\x05\x06" + b"\x00" * 18)      # 空 zip 的结尾记录

    path = _start_capture_path(tmp_path, monkeypatch)
    assert path.endswith("_2.txt"), path
    assert os.path.exists(zip_path)


class _EofProc:
    """输出完给定行就 EOF（模拟 adb 报错后自己退出）。

    `_FakeLogcatProc` 是无限循环产出的，适合「一直跑着」的场景；这里要的恰恰
    相反：设备离线时 `adb logcat` 打一行原因就退出，读循环拿到 EOF。
    """

    def __init__(self, lines):
        self._lines = list(lines)
        self._i = 0
        self.returncode = 0

    @property
    def stdout(self):
        return self

    def __iter__(self):
        return self

    def __next__(self):
        if self._i >= len(self._lines):
            raise StopIteration
        line = self._lines[self._i]
        self._i += 1
        return line

    def terminate(self):
        pass

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0


def _wait_payload(bus, kind, status, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        for e in bus.events:
            if e["kind"] == kind and (e["payload"] or {}).get("status") == status:
                return e["payload"]
        time.sleep(0.02)
    return None


def _statuses(bus, kind):
    return [(e["payload"] or {}).get("status")
            for e in bus.events if e["kind"] == kind]


def _for_serial(cmd, serial):
    """这条 adb 命令是否属于本用例的设备。

    为什么假 Popen 里要加这层过滤：上一个用例的抓取 worker 可能还在自动重启
    循环里（stopped 事件推完，还要清理 _procs / 退避 Event），它调到的是**本
    用例**刚 patch 进去的 Popen。按 `call["n"]` 或 `procs.pop(0)` 计数的假件
    会被它抢走一个批次，本用例就少一段日志 —— 表现为「跨天用例 / 空洞用例偶发
    失败」，而单跑这条永远复现不了（没有遗留线程）。按 serial 分流后，别人的
    worker 拿到的是空 EOF（立刻无进展退出），不再动本用例的批次。
    """
    return serial in cmd


def _popen_by_serial(serial, batches):
    """按 serial 分流的假 Popen：按顺序吐出 batches（每批是行列表），之后空 EOF。

    batches 用完之后的空 EOF 是给本用例的「无进展」出口（见 _EofProc 的说明）；
    别的用例遗留的 worker 同样拿空 EOF，不会消耗本用例的批次。
    """
    q = list(batches)

    def _popen(cmd, **kw):
        if not _for_serial(cmd, serial):
            return _EofProc([])
        return _EofProc(q.pop(0)) if q else _EofProc([])

    return _popen


def test_capture_offline_device_is_an_error_not_an_empty_success(tmp_path, monkeypatch):
    """设备离线：必须报错，不能报「✓ 抓取完毕：0 行」。

    旧行为：adb 的 `error: device 'A1' not found` 被原样写进 txt，紧接着推
    stopped —— 前端弹「✓ 抓取完毕：0 行」并生成一份只有一行报错的文件。用户
    以为抓到了空日志（甚至拿去做证据），实际是设备根本没连上。
    """
    proc = _EofProc(["error: device 'A1' not found\n"])
    monkeypatch.setattr(ls.subprocess, "Popen", lambda cmd, **kw: proc)

    bus = _FakeBus()
    cap = ls.LogcatCapture(bus, adb_path="adb")
    assert cap.start("A1", str(tmp_path / "a.txt"), ["main"]) is True

    payload = _wait_payload(bus, "logcat_capture", "error")
    assert payload is not None, _statuses(bus, "logcat_capture")
    assert "not found" in payload["text"], payload
    assert "stopped" not in _statuses(bus, "logcat_capture"), \
        "已经报错收尾，不能再推 stopped 把状态盖回「空闲」"


def test_monitor_offline_device_is_an_error_not_a_silent_stop(monkeypatch):
    """实时监控同理：一条日志都没收到就退出，界面必须说清原因。"""
    proc = _EofProc(["error: device 'A1' not found\n"])
    monkeypatch.setattr(ls.subprocess, "Popen", lambda cmd, **kw: proc)

    bus = _FakeBus()
    mon = ls.LogcatMonitor(bus, adb_path="adb")
    assert mon.start("A1", ["main"]) is True

    payload = _wait_payload(bus, "logcat", "error")
    assert payload is not None, _statuses(bus, "logcat")
    assert "not found" in payload["text"], payload
    assert "stopped" not in _statuses(bus, "logcat")


def test_capture_all_levels_filtered_is_not_an_offline_error(tmp_path, monkeypatch):
    """用户取消了全部级别 → 一行都不写盘，但设备是好的，不能误报「设备离线」。

    注意：抓到 1 行后被 EOF（adb logcat 自己退出）时，新逻辑会先探测设备是否真掉了。
    这里把 device_present 钉成 True（设备仍在），确保它走「正常收尾」而非「重连等待」，
    避免对「设备其实没掉线、只是 logcat 自己退了」的场景误判。
    """
    proc = _EofProc(["08-29 10:23:45.123  1234  1234 I Tag: hi\n"])
    monkeypatch.setattr(ls.subprocess, "Popen", lambda cmd, **kw: proc)
    monkeypatch.setattr(ls, "device_present", lambda *a, **k: True)

    bus = _FakeBus()
    cap = ls.LogcatCapture(bus, adb_path="adb")
    assert cap.start("A1", str(tmp_path / "b.txt"), ["main"],
                     level_filter=[]) is True

    payload = _wait_payload(bus, "logcat_capture", "stopped")
    assert payload is not None, _statuses(bus, "logcat_capture")
    assert payload["lines"] == 0
    assert "error" not in _statuses(bus, "logcat_capture")


def test_monitor_keyword_miss_is_not_an_offline_error(monkeypatch):
    """关键字一个都没命中同属「过滤后为空」，不能当成设备掉线。"""
    proc = _EofProc(["08-29 10:23:45.123  1234  1234 I Tag: hi\n"])
    monkeypatch.setattr(ls.subprocess, "Popen", lambda cmd, **kw: proc)

    bus = _FakeBus()
    mon = ls.LogcatMonitor(bus, adb_path="adb")
    assert mon.start("A1", ["main"], keyword="no-such-key") is True

    payload = _wait_payload(bus, "logcat", "stopped")
    assert payload is not None, _statuses(bus, "logcat")
    assert "error" not in _statuses(bus, "logcat")

# ---------------------------------------------------------------------------
# 抓取收尾的三种「没说出口」：写盘中断 / 打包失败 / 空文件
# ---------------------------------------------------------------------------
def test_capture_write_failure_is_not_reported_as_success(tmp_path, monkeypatch):
    """写盘失败后不能再报「抓取完毕」，stopped 必须带上中断原因。

    回归：`f.write` 抛异常（磁盘满 / 目录被删 / 权限）时，worker 先推一条
    error，紧接着 finally 又推 stopped（只带行数与大小）。前端两条 toast 里
    后到的「✓ 抓取完毕」把前一条错误盖掉 —— 用户看到的是成功，拿去分析的
    文件却只有半截。现在 stopped 带 error，前端据此改成「已中断」。
    """
    bus = _FakeBus()
    path = tmp_path / "cap_as_dir"
    path.mkdir()                       # 同名目录占位 -> open(path, "w") 直接失败
    proc = _FakeLogcatProc(["08-29 10:23:45.123  1234  1234 I x: hi\n"])
    monkeypatch.setattr(ls.subprocess, "Popen", lambda *a, **kw: proc)

    cap = ls.LogcatCapture(bus, adb_path="adb")
    assert cap.start("W", str(path), ["main"], level_filter=None) is True
    # 不调 stop()：open() 就在这里立刻失败，worker 随即自己收尾。旧写法先等
    # `is_running` 再 stop —— 那是一个毫秒级的窗口（CI 上因调度错过就直接
    # 断言失败），测的其实不是「失败后怎么报」。
    assert _wait_stopped(bus)

    assert bus.has_capture_status("error")
    st = bus.last_capture_event("stopped")
    assert st is not None
    assert st.get("error"), "写盘失败却在 stopped 上留了空原因：%r" % st


def test_capture_zip_failure_says_why(tmp_path, monkeypatch):
    """勾了「结束后打包」却没打成时，stopped 必须说明原因，源 txt 保留。

    回归：`_zip_one` 返回 None（文件被占用 / 磁盘满）后，事件只带
    packaged=False，前端也只报「抓取完毕」。用户按开关的承诺去目录里找 zip，
    找不到，也无从知道是打包失败了。
    """
    bus = _FakeBus()
    path = tmp_path / "cap.txt"
    proc = _FakeLogcatProc(["08-29 10:23:45.123  1234  1234 I x: hi\n"],
                           block_after=1)
    monkeypatch.setattr(ls.subprocess, "Popen", lambda *a, **kw: proc)
    monkeypatch.setattr(ls.LogcatCapture, "_zip_one",
                        staticmethod(lambda p: None))

    cap = ls.LogcatCapture(bus, adb_path="adb")
    assert cap.start("Z", str(path), ["main"]) is True
    assert proc.parked(5.0)
    cap.stop("Z", zip_on_stop=True)
    assert _wait_stopped(bus)

    st = bus.last_capture_event("stopped")
    assert st is not None
    assert st["packaged"] is False
    assert "打包失败" in (st.get("zip_error") or ""), st
    assert path.exists() and path.stat().st_size > 0, "打包失败时源文件必须保留"


def test_capture_zip_skipped_for_empty_file_says_why(tmp_path, monkeypatch):
    """文件为空时不会打包，但也要说一句，而不是让用户以为 zip 丢了。"""
    bus = _FakeBus()
    path = tmp_path / "empty.txt"
    proc = _FakeLogcatProc(["x\n"], block_after=0)   # 一行都不产出就停住
    monkeypatch.setattr(ls.subprocess, "Popen", lambda *a, **kw: proc)

    cap = ls.LogcatCapture(bus, adb_path="adb")
    assert cap.start("E", str(path), ["main"]) is True
    assert proc.parked(5.0)
    cap.stop("E", zip_on_stop=True)
    assert _wait_stopped(bus)

    st = bus.last_capture_event("stopped")
    assert st is not None
    assert "为空" in (st.get("zip_error") or ""), st
    assert st["packaged"] is False

# ---------------------------------------------------------------------------
# 控制器层的「点了没反应」：前端不看返回值，后端不播报就是彻底静默
# ---------------------------------------------------------------------------
def _status_texts(api):
    return [e["payload"].get("text") or "" for e in api.bus.take()
            if e["kind"] == "status"]


def test_capture_start_reports_unwritable_save_dir(tmp_path, monkeypatch):
    """保存目录建不出来时必须播报，否则「开始抓取」点了完全没反应。

    回归：`logcat_capture_start` 在 makedirs 失败时只把原因塞进返回值，
    而前端是事件驱动的（callApi 结果不看不提示）——只读盘 / 盘符不存在 /
    路径被同名文件占位时，用户点完按钮界面上一个字都没有。
    """
    api = WebApi()
    api.state.adb_path = "adb"
    blocker = tmp_path / "notdir"
    blocker.write_text("x", encoding="utf-8")     # 父路径被普通文件占位

    res = api.logcat_capture_start("X", str(blocker / "sub"), ["main"])
    assert res["ok"] is False and res["reason"] == "mkdir", res
    texts = _status_texts(api)
    assert any("无法创建保存目录" in t for t in texts), texts


def test_capture_start_reports_already_running(monkeypatch):
    """同一台设备重复开始抓取要被明确拒绝，不能静默丢弃。"""
    api = WebApi()
    api.state.adb_path = "adb"
    monkeypatch.setattr(api.logcat_capture, "start", lambda *a, **kw: False)
    res = api.logcat_capture_start("X", ".", ["main"])
    assert res["ok"] is False and res["reason"] == "already_running"
    assert any("已有 logcat 抓取在进行" in t for t in _status_texts(api))


def test_capture_stop_reports_when_nothing_running():
    """没在抓取时点「停止」也要说一句，而不是一个没有反馈的死按钮。"""
    api = WebApi()
    res = api.logcat_capture_stop("A1", zip_on_stop=False)
    assert res["ok"] is False and res["reason"] == "not_running", res
    assert any("没有进行中的 logcat 抓取" in t for t in _status_texts(api))


def test_logcat_start_reports_already_running(monkeypatch):
    """实时监控重复开始同样要有提示。"""
    api = WebApi()
    monkeypatch.setattr(api.logcat_monitor, "start", lambda *a, **kw: False)
    res = api.logcat_start("A1", ["main"])
    assert res["ok"] is False and res["reason"] == "already_running"


# ---------------------------------------------------------------------------
# 设备掉线续写：录屏 + 满缓冲全级别 logcat 同时跑时，USB 抖动掉线后抓取不能丢数据
# ---------------------------------------------------------------------------
def test_capture_reconnects_and_continues_after_device_drop(tmp_path, monkeypatch):
    """设备掉线（adb logcat EOF）后，抓取必须等重连并续写同一文件，不能静默结束。

    回归：录屏 + 满缓冲全级别 logcat 同时跑时设备 USB 抖动掉线，旧实现会在 EOF 处
    直接报「✓ 抓取完毕」、把日志在掉线处截断——后续拿视频流对照日志分析时发现日志
    缺失，功能等于废了。新实现：确认设备掉线后写入缺口标记、推 reconnecting、等重连
    成功后继续往同一文件追加。

    可控假件：第一批日志 -> EOF（模拟掉线）-> device_present 先 False 后 True
    （模拟重连）-> 第二批日志 -> EOF（设备仍在，本次抓取被外力打断）。
    此后每轮都立刻 EOF 且没有新行，触发「连续无进展」退出（不会无限重启）。
    """
    first = ["08-29 10:00:00.000  1  1 I Tag: before-drop-%d\n" % i
             for i in range(3)]
    second = ["08-29 10:00:05.000  1  1 I Tag: after-reconnect-%d\n" % i
              for i in range(3)]

    call = {"n": 0}
    def fake_popen(cmd, **kw):
        if not _for_serial(cmd, "D1"):
            return _EofProc([])         # 别的用例遗留的 worker：一句都不给
        if "logcat" in " ".join(cmd):
            call["n"] += 1
            if call["n"] == 1:
                return _EofProc(list(first))
            if call["n"] == 2:
                return _EofProc(list(second))
            return _EofProc([])     # 之后立刻 EOF 且无新行 -> 「无进展」收尾
        return _FakeLogcatProc([])
    monkeypatch.setattr(ls.subprocess, "Popen", fake_popen)

    # device_present：掉线判定与重连轮询前几次返回 False，随后 True（重连成功）
    present = {"n": 0}
    def fake_present(adb, serial, timeout=5):
        present["n"] += 1
        return present["n"] > 2
    monkeypatch.setattr(ls, "device_present", fake_present)
    # 缩短重连轮询与重启退避，让测试秒级完成
    monkeypatch.setattr(ls, "LOGCAT_CAP_RECONNECT_POLL_S", 0.02)
    monkeypatch.setattr(ls, "LOGCAT_CAP_RESTART_BACKOFF_S", 0.01)

    bus = _FakeBus()
    path = str(tmp_path / "cap_drop.txt")
    cap = ls.LogcatCapture(bus, adb_path="adb")
    assert cap.start("D1", path, ["main"]) is True

    # 等到出现 reconnecting 事件（证明掉线后没有静默结束）
    re_event = _wait_payload(bus, "logcat_capture", "reconnecting", timeout=5)
    assert re_event is not None, _statuses(bus, "logcat_capture")
    # 掉线期间抓取仍被记为「进行中」，否则回收逻辑会把它当孤儿掐断
    assert cap.is_running("D1"), "重连等待期间 is_running 必须为 True"

    # 等到最终 stopped，并确认文件里两段日志 + 缺口标记都在
    stopped = _wait_payload(bus, "logcat_capture", "stopped", timeout=5)
    assert stopped is not None, _statuses(bus, "logcat_capture")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    for i in range(3):
        assert "before-drop-%d" % i in content
        assert "after-reconnect-%d" % i in content
    assert "[logcat] 设备于" in content, "文件必须含缺口标记"
    assert "恢复连接" in content, "文件必须含重连恢复标记"
    # 不是「假成功」：经历过掉线续写，stopped 必须带 gap 标记
    assert stopped.get("gap") is True, "经历过掉线续写的抓取，stopped 必须带 gap 标记"


def test_capture_gap_on_reconnect_timeout(tmp_path, monkeypatch):
    """设备掉线后重连窗口耗尽：抓取结束但必须明确告警「文件存在时间缺口」，
    绝不能伪装成「✓ 抓取完毕」。

    可控假件：第一批日志 -> EOF（掉线）-> device_present 永远 False（设备没回来）
    -> 重连窗口耗尽 -> 结束。窗口与轮询都缩短，测试秒级完成。
    """
    first = ["08-29 10:00:00.000  1  1 I Tag: only-before-%d\n" % i
             for i in range(3)]

    def fake_popen(cmd, **kw):
        if not _for_serial(cmd, "T1"):
            return _EofProc([])         # 别的用例遗留的 worker：一句都不给
        if "logcat" in " ".join(cmd):
            return _EofProc(list(first))
        return _FakeLogcatProc([])
    monkeypatch.setattr(ls.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(ls, "device_present", lambda *a, **k: False)  # 永远不回来
    monkeypatch.setattr(ls, "LOGCAT_CAP_RECONNECT_MAX_S", 0.3)
    monkeypatch.setattr(ls, "LOGCAT_CAP_RECONNECT_POLL_S", 0.02)

    bus = _FakeBus()
    path = str(tmp_path / "cap_timeout.txt")
    cap = ls.LogcatCapture(bus, adb_path="adb")
    assert cap.start("T1", path, ["main"]) is True

    stopped = _wait_payload(bus, "logcat_capture", "stopped", timeout=5)
    assert stopped is not None, _statuses(bus, "logcat_capture")
    # 关键：不是「假成功」——必须带 gap 标记并说明文件存在时间缺口
    assert stopped.get("gap") is True, "重连失败必须带 gap 标记"
    assert stopped.get("error"), "重连失败必须说明文件存在时间缺口"
    with open(path, encoding="utf-8") as f:
        content = f.read()
    for i in range(3):
        assert "only-before-%d" % i in content
    assert "[logcat] 设备于" in content, "文件必须含缺口标记"


def test_rec_death_stops_logcat_capture_in_sync(tmp_path, monkeypatch):
    """录屏意外中断（设备掉线）时，配套 logcat 必须**同步停**并进同一个包。

    日志的唯一用途是事后按时间轴对照视频找问题。录像已经停了、日志还在往下
    写，两边就对不齐；所以这里不做任何例外：录屏怎么结束，日志就怎么结束。
    断点位置由抓取侧写入的「设备断开连接」缺口标记标明。

    回归：曾一度把「死亡设备」的抓取改成脱离会话继续跑（视频断、日志不断），
    那是错的——时间轴对不上的日志没法用来定位画面问题。
    """
    api = WebApi()
    stopped = {}

    def fake_stop(s, zip_on_stop=False):
        stopped[s] = zip_on_stop
        return True

    monkeypatch.setattr(api.logcat_capture, "stop", fake_stop)
    monkeypatch.setattr(api.logcat_capture, "is_running", lambda s: s not in stopped)
    log_path = str(tmp_path / "logcat_D1_20260101_000000.txt")
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("08-29 10:00:01.000  1  1 I Tag: hi\n")

    api._rec_session = {
        "ts": "20260101_000000", "dir": str(tmp_path), "with_devaudio": False,
        "with_mic": False, "with_zip": False, "mic_path": None,
        "mic_started": False, "videos": {}, "devaudio": {},
        "logcat_captures": {"D1": log_path},
        "pointer_location_prev": {}, "show_touches_prev": {},
        "dead": {"D1"},
    }
    # video 相关调用给安全桩：teardown 不应真去 stop 视频 / 读 overlay
    monkeypatch.setattr(api.video, "is_recording", lambda s: False)
    monkeypatch.setattr(api.video, "stop",
                        lambda s: (False, None, "not recording"))
    monkeypatch.setattr(api.video, "get_system_setting",
                        lambda *a, **k: (True, "0"))
    monkeypatch.setattr(api, "_set_device_setting", lambda *a, **k: (True, ""))
    monkeypatch.setattr(api, "_zip_paths", lambda *a, **k: None)

    files, _zpath = api._session_teardown(api._rec_session)
    assert "D1" in stopped, "录屏中断时必须同步停掉 logcat 抓取（时间轴要对齐）"
    assert log_path in files, "日志要跟着录屏进同一个产物包：%r" % (files,)


# ---------------------------------------------------------------------------
# 设备被拔掉（从设备列表消失）→ 孤儿回收不得把截断报成「✓ 抓取完毕」
# ---------------------------------------------------------------------------
class _HungProc:
    """产出给定行后就一直卡住（模拟设备拔掉后 `adb logcat` 迟迟不退出）。

    这类进程在 Windows 上很常见：光靠 stdout EOF 收尾不可靠，孤儿回收线程会
    先一步发现设备不见了，所以它必须走「掉线」通道而不是「停止」通道。
    """

    def __init__(self, lines):
        self._lines = list(lines)
        self._i = 0
        self.returncode = None
        self._released = threading.Event()

    @property
    def stdout(self):
        return self

    def __iter__(self):
        return self

    def __next__(self):
        if self._i < len(self._lines):
            line = self._lines[self._i]
            self._i += 1
            return line
        self._released.wait()          # 没被 terminate 就一直卡着
        raise StopIteration

    def poll(self):
        return None

    def terminate(self):
        self._released.set()

    def kill(self):
        self._released.set()

    def wait(self, timeout=None):
        self._released.set()
        return 0


def _drain_until(bus, kind, status, timeout=6.0):
    """把事件取走并累积，直到出现指定 kind/status；返回 (payload, 全部事件)。"""
    end = time.time() + timeout
    seen = []
    while time.time() < end:
        seen.extend(bus.take())
        for e in seen:
            if (e.get("kind") == kind
                    and (e.get("payload") or {}).get("status") == status):
                return e["payload"], seen
        time.sleep(0.02)
    return None, seen


def test_reap_gone_capture_reports_gap_not_clean_success(tmp_path, monkeypatch):
    """设备拔掉、由孤儿回收收拾抓取时，必须留缺口标记，不能报「抓取完毕」。

    真实链路（Windows 上最常见）：同时录屏 + 满缓冲 logcat，USB 抖动 / 拔线后
    `adb logcat` 迟迟不退出，autorefresh 的 _reap_gone_tools 先一步发现设备不在
    列表里。旧实现直接 stop()，worker 把 `_stopreq` 当成「用户主动停止」，收尾推
    stopped 且没有 gap —— 界面弹「✓ 抓取完毕：N 行」，文件却在掉线处截断；拿
    视频流对日志时才发现中间少一段，这个功能就等于废了。

    这里连 device_present 都返回 None（adb 查不出结论）模拟「查不到」：只有回收
    线程的「设备已消失」提示能救，仍须判定为掉线而不是正常结束。
    """
    proc = _HungProc(["08-29 10:23:45.123  1234  1234 I Tag: hi\n"])
    monkeypatch.setattr(ls.subprocess, "Popen", lambda *a, **k: proc)
    monkeypatch.setattr(ls, "device_present", lambda *a, **k: None)
    monkeypatch.setattr(ls, "LOGCAT_CAP_RECONNECT_MAX_S", 0)      # 立即超时
    monkeypatch.setattr(ls, "LOGCAT_CAP_RECONNECT_POLL_S", 0.01)

    api = WebApi()
    path = str(tmp_path / "gone.txt")
    assert api.logcat_capture.start("A1", path, ["main"]) is True
    running, _seen0 = _drain_until(api.bus, "logcat_capture", "running")
    assert running is not None, "worker 没起来"

    # 设备从设备列表里消失：孤儿回收线程通知抓取（旧实现是 stop()）
    api.devices.device_state = {}
    api._reap_gone_tools()

    stopped, seen = _drain_until(api.bus, "logcat_capture", "stopped")
    assert stopped is not None, [e.get("payload") for e in seen]
    assert stopped.get("gap") is True, (
        "设备掉线导致的截断必须带 gap，否则前端弹「✓ 抓取完毕」：%r" % (stopped,))
    assert "缺口" in (stopped.get("error") or ""), stopped
    statuses = [(e.get("payload") or {}).get("status") for e in seen
                if e.get("kind") == "logcat_capture"]
    assert "reconnecting" in statuses, (
        "设备消失时应转入等重连，而不是直接结束：%r" % (statuses,))

    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    assert "断开连接" in text, (
        "文件里必须留下掉线标记，否则时间线看着是连续的：%r" % (text,))


def test_capture_resume_skips_replayed_backlog(tmp_path, monkeypatch):
    """重连后 adb 会从缓冲区开头重放：已写过的行不能再写一遍。

    新起的 `adb logcat` 没有 -T 就从头打印整个缓冲区。同时录屏 + 满缓冲 logcat
    时缓冲区可以到几十 MB，一次 USB 抖动就会把断点之前的日志**整段**再写进
    同一个文件：时间线上出现两份相同记录，文件白白翻倍，对照视频找日志时根本
    分不清哪一段才是对应的。这里按行首 threadtime 时间戳跳过断点之前的部分。
    """
    ses1 = ["08-29 10:00:01.000  1  1 I Tag: a\n",
            "08-29 10:00:02.000  1  1 I Tag: b\n",
            "08-29 10:00:03.000  1  1 I Tag: c\n"]
    # 重连后的会话：先重放缓冲区里的三行，再接着输出新的一行
    ses2 = ses1 + ["08-29 10:00:09.000  1  1 I Tag: d\n"]
    procs = [ses1, ses2]
    # 之后的每一轮都立刻 EOF 且无新行（设备仍在，抓取被外力打断但拉不起来），
    # 触发「连续无进展」收尾 —— 否则自动重启逻辑会一直往下拉。
    monkeypatch.setattr(ls.subprocess, "Popen", _popen_by_serial("A1", procs))
    calls = {"n": 0}
    monkeypatch.setattr(ls, "LOGCAT_CAP_RESTART_BACKOFF_S", 0.01)

    def fake_present(adb, serial):
        calls["n"] += 1
        return False if calls["n"] == 1 else True    # 第一次：设备确实掉了

    monkeypatch.setattr(ls, "device_present", fake_present)
    monkeypatch.setattr(ls, "LOGCAT_CAP_RECONNECT_POLL_S", 0.01)

    bus = _FakeBus()
    cap = ls.LogcatCapture(bus, adb_path="adb")
    path = str(tmp_path / "dup.txt")
    assert cap.start("A1", path, ["main"]) is True

    payload = _wait_payload(bus, "logcat_capture", "stopped")
    assert payload is not None, _statuses(bus, "logcat_capture")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    for tag in ("a", "b", "d"):
        assert text.count("Tag: " + tag) == 1, (
            "重放的行被重复写进文件（Tag: %s）：\n%s" % (tag, text))
    # 边界行（时间戳正好等于断点那条）允许重复一次：判定用 `<` 而不是 `<=`，
    # 宁可多一行，也绝不把「同一毫秒内新产生的那条」误删——丢日志比重复严重
    # 得多。真实缓冲区重放时这点重复是可以接受的锚点。
    assert text.count("Tag: c") <= 2, text
    assert "恢复连接" in text, "缺少恢复标记，看不出断点在哪：%r" % (text,)
    assert payload["lines"] in (4, 5), payload


def test_stop_during_reconnect_takes_effect_immediately(tmp_path, monkeypatch):
    """等重连期间点停止必须立刻收尾，不能等满一个轮询间隔。

    「录屏停 → 日志同步停」靠的就是这一点：等待循环若用 sleep(轮询间隔) 睡死，
    停止最多被拖后一个间隔，日志就比视频多出这几秒，两边对不齐。
    """
    proc = _EofProc(["08-29 10:00:01.000  1  1 I Tag: a\n"])
    monkeypatch.setattr(ls.subprocess, "Popen", lambda *a, **k: proc)
    monkeypatch.setattr(ls, "device_present", lambda *a, **k: False)  # 一直没回来
    monkeypatch.setattr(ls, "LOGCAT_CAP_RECONNECT_MAX_S", 60)
    monkeypatch.setattr(ls, "LOGCAT_CAP_RECONNECT_POLL_S", 5)       # 一个间隔 5 秒

    bus = _FakeBus()
    cap = ls.LogcatCapture(bus, adb_path="adb")
    assert cap.start("A1", str(tmp_path / "wake.txt"), ["main"]) is True
    assert _wait_payload(bus, "logcat_capture", "reconnecting") is not None

    t0 = time.time()
    assert cap.stop("A1", zip_on_stop=False) is True
    stopped = _wait_payload(bus, "logcat_capture", "stopped", timeout=2.0)
    dt = time.time() - t0
    assert stopped is not None, (
        "停止没有立刻生效（等满一个轮询间隔才会收尾）：%r" % (_statuses(bus, "logcat_capture"),))
    assert dt < 1.0, "等重连期间的停止耗时 %.2fs，说明还在 sleep 而不是被唤醒" % dt


def test_capture_flushes_below_1000_lines(tmp_path, monkeypatch):
    """日志必须及时落盘：不能攒满 1000 行才 flush。

    回归：只按「每 1000 行」flush 时，末尾不足 1000 行的日志一直留在用户态
    缓冲里。程序被强杀 / 崩溃时这一段就没了 —— 而「照视频时间戳回查日志」
    最需要的往往正是断点前那几十行。
    """
    bus = _FakeBus()
    lines = ["08-29 10:00:00.%03d  1  1 I Tag: line %d\n" % (i, i)
             for i in range(5)]
    cap, holder = _make_capture(bus, monkeypatch, lines, block_after=5)
    path = str(tmp_path / "logcat_F_001.txt")
    assert cap.start("F", path, ["main"]) is True
    assert holder["proc"].parked(), "假进程未停在循环内"

    end = time.time() + 5
    got = ""
    while time.time() < end:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                got = fh.read()
            if got.count("Tag: line") >= 5:
                break
        time.sleep(0.02)
    try:
        assert got.count("Tag: line") >= 5, (
            "不足 1000 行也必须已落盘（否则崩溃即丢这段日志）：%r" % got)
    finally:
        cap.stop("F", zip_on_stop=False)
        assert _wait_not_running(cap, "F")


def test_eof_while_device_still_present_restarts_and_keeps_logging(tmp_path, monkeypatch):
    """设备还在、adb logcat 却自己退了：必须自动重启并续写，不能就此收工。

    这是用户实况对应的主场景：录屏（设备端 screenrecord）+ 满缓冲全级别 logcat
    同时跑，USB 带宽被打满 / adb 抖动时，`adb logcat` 会在设备**仍然在线**的
    情况下自己退出。旧实现只在断点处报一句「意外退出」就结束，于是录屏继续到
    11:14、配套日志的最后一条停在 10:50 —— 后 24 分钟一条不剩，直到事后拿
    时间轴比对才发现，此时已无从补救。

    新行为：写缺口标记 → 退避 → 重新拉起 → 继续写同一文件；stopped 带 gap，
    前端不会弹「✓ 抓取完毕」。
    """
    first = ["08-29 10:00:00.%03d  1  1 I Tag: before-%d\n" % (i, i)
             for i in range(3)]
    second = ["08-29 10:05:00.%03d  1  1 I Tag: after-%d\n" % (i, i)
              for i in range(3)]
    procs = [first, second]
    monkeypatch.setattr(ls.subprocess, "Popen", _popen_by_serial("E", procs))
    monkeypatch.setattr(ls, "device_present", lambda *a, **k: True)
    monkeypatch.setattr(ls, "LOGCAT_CAP_RESTART_BACKOFF_S", 0.01)

    bus = _FakeBus()
    cap = ls.LogcatCapture(bus, adb_path="adb")
    path = str(tmp_path / "logcat_E_001.txt")
    assert cap.start("E", path, ["main"]) is True

    payload = _wait_payload(bus, "logcat_capture", "stopped", timeout=8)
    assert payload is not None, _statuses(bus, "logcat_capture")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    for i in range(3):
        assert "before-%d" % i in text, "中断前的日志不能丢：%r" % text
        assert "after-%d" % i in text, (
            "重启后的日志必须续写进同一个文件（旧实现就此停住）：%r" % text)
    assert "意外中断" in text, "文件里必须留下中断标记，否则时间线看着是连续的"
    # 中断过就必须如实标记，不能报「✓ 抓取完毕」
    assert payload.get("gap") is True, payload


def test_eof_restart_gives_up_when_no_new_lines(tmp_path, monkeypatch):
    """重试也换不来任何新日志时：明确收尾并说明「已截断」，不无限重启。

    自动重启必须有出口：设备 logd 出问题 / adb 每次都秒退时，无限拉起只会
    把 CPU 和 adb 通道占满，而日志一行也不会多。连续无进展即停，并按
    「意外退出、文件在此处截断」报错。
    """
    lines = ["08-29 10:00:00.%03d  1  1 I Tag: line %d\n" % (i, i)
             for i in range(3)]
    proc = _EofProc(lines)
    monkeypatch.setattr(ls.subprocess, "Popen", lambda *a, **k: proc)
    monkeypatch.setattr(ls, "device_present", lambda *a, **k: True)
    monkeypatch.setattr(ls, "LOGCAT_CAP_RESTART_BACKOFF_S", 0.01)

    bus = _FakeBus()
    cap = ls.LogcatCapture(bus, adb_path="adb")
    path = str(tmp_path / "logcat_E_002.txt")
    assert cap.start("E", path, ["main"]) is True

    payload = _wait_payload(bus, "logcat_capture", "stopped", timeout=8)
    assert payload is not None, _statuses(bus, "logcat_capture")
    err = payload.get("error") or ""
    assert "意外退出" in err and "截断" in err, (
        "重启也拿不到新日志时必须报截断，而不是干净成功：%r" % (payload,))
    with open(path, encoding="utf-8") as f:
        assert "line 0" in f.read()


def test_capture_restart_writes_hole_marker_when_backlog_rolled_over(tmp_path, monkeypatch):
    """续写起点离断点太远时，必须写下「缺失时段」标记。

    设备缓冲区是环形的：中断几分钟后，断连期间产生的日志已经被新日志挤掉，
    新起的 `adb logcat` 只能从缓冲区里现存最早的那条开始重放。此时若只写一句
    「恢复连接」，文件看上去是连续的 —— 只有事后按视频对时间轴才会发现「这里
    少了一大段」，而那时既补不回来也说不清断在哪。
    """
    first = ["08-29 10:50:00.000  1  1 I Tag: head\n"]
    # 断点 10:50，续写起点已经是 11:10（中间 20 分钟已被缓冲区滚掉）
    second = ["08-29 11:10:00.000  1  1 I Tag: tail\n"]
    procs = [first, second]
    monkeypatch.setattr(ls.subprocess, "Popen", _popen_by_serial("H", procs))
    monkeypatch.setattr(ls, "device_present", lambda *a, **k: True)
    monkeypatch.setattr(ls, "LOGCAT_CAP_RESTART_BACKOFF_S", 0.01)

    bus = _FakeBus()
    cap = ls.LogcatCapture(bus, adb_path="adb")
    path = str(tmp_path / "hole.txt")
    assert cap.start("H", path, ["main"]) is True
    assert _wait_payload(bus, "logcat_capture", "stopped", timeout=8) is not None

    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert "日志缺失" in text, "续写跨越空洞时必须写缺失时段标记：%r" % text
    assert "10:50:00.000" in text and "11:10:00.000" in text, text


def test_capture_cross_day_timestamp_is_not_treated_as_replay(tmp_path, monkeypatch):
    """跨年/跨天续写不能被当成「重放」整体丢掉。

    旧实现在重连去重时直接比时间戳**字符串**：「12-31 23:59」>「01-01 00:00」，
    于是跨年录一整夜之后，零点起的日志会被判成「比断点更早的重放」全部跳过，
    文件就那么停在 23:59。这里用跨年的两批行验证新逻辑（比精确时刻）不丢数据。
    """
    first = ["12-31 23:59:50.000  1  1 I Tag: y1\n",
             "12-31 23:59:59.000  1  1 I Tag: y2\n"]
    second = ["01-01 00:00:05.000  1  1 I Tag: y3\n",
              "01-01 00:00:06.000  1  1 I Tag: y4\n"]
    procs = [first, second]
    monkeypatch.setattr(ls.subprocess, "Popen", _popen_by_serial("Y", procs))
    monkeypatch.setattr(ls, "device_present", lambda *a, **k: True)
    monkeypatch.setattr(ls, "LOGCAT_CAP_RESTART_BACKOFF_S", 0.01)

    bus = _FakeBus()
    cap = ls.LogcatCapture(bus, adb_path="adb")
    path = str(tmp_path / "crossday.txt")
    # 固定「现在」为 2026-02-06，让年份推断确定（否则跨年用例的结果会随运行日期变化）
    import datetime as _dt
    _ref = _dt.datetime(2026, 2, 6, 12, 0, 0).timestamp()
    _real = ls.ts_epoch
    monkeypatch.setattr(ls, "ts_epoch",
                        lambda ts, ref=None: _real(ts, ref=_ref))
    assert cap.start("Y", path, ["main"]) is True
    assert _wait_payload(bus, "logcat_capture", "stopped", timeout=8) is not None

    with open(path, encoding="utf-8") as f:
        text = f.read()
    for tag in ("y1", "y2", "y3", "y4"):
        assert "Tag: " + tag in text, "跨天后的日志被当成重放丢掉了：%r" % text


def test_stop_during_restart_backoff_takes_effect_immediately(tmp_path, monkeypatch):
    """自动重启的退避期间点停止，必须立刻收尾（不能干等一个退避间隔）。

    「录屏停 → 日志同步停」靠的就是这一点：退避本来是为了错开 USB 带宽尖峰，
    但它绝不能把用户的停止请求一起等掉 —— 那会让日志比视频多跑几十秒，
    拿两边时间轴对照时恰好错在案发现场上。
    """
    lines = ["08-29 10:00:00.%03d  1  1 I Tag: a\n" % i for i in range(3)]
    proc = _EofProc(lines)
    monkeypatch.setattr(ls.subprocess, "Popen", lambda *a, **k: proc)
    monkeypatch.setattr(ls, "device_present", lambda *a, **k: True)
    # 退避拉长到 30 秒：只有「被唤醒」才可能秒级收尾
    monkeypatch.setattr(ls, "LOGCAT_CAP_RESTART_BACKOFF_S", 30)
    monkeypatch.setattr(ls, "LOGCAT_CAP_RESTART_BACKOFF_MAX_S", 30)

    bus = _FakeBus()
    cap = ls.LogcatCapture(bus, adb_path="adb")
    assert cap.start("B1", str(tmp_path / "backoff.txt"), ["main"]) is True
    assert _wait_payload(bus, "logcat_capture", "reconnecting", timeout=5) is not None

    t0 = time.time()
    assert cap.stop("B1", zip_on_stop=False) is True
    stopped = _wait_payload(bus, "logcat_capture", "stopped", timeout=3.0)
    dt = time.time() - t0
    assert stopped is not None, _statuses(bus, "logcat_capture")
    assert dt < 1.0, "退避期间停止耗时 %.2fs，说明还在傻等而不是被唤醒" % dt
