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
    monkeypatch.setattr("backend.controller.load_prefs", lambda: {})
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
    monkeypatch.setattr("backend.controller.load_prefs", lambda: {"save_dir": want})

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
