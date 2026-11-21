"""RecordMixin 的同源录制（MF）门控分流测试。

验证：mf_capture 可用时 start/stop/cancel 走 MF 路径；不可用时回退老
ffmpeg 路径；MF 会话结构带 'mf' 标记；shutdown 取消而非发布半成品。
真机 native 行为不在此覆盖。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.controller import WebApi  # noqa: E402


class FakeSession:
    def __init__(self, **kw):
        self.output_callback = kw.get("output_callback")

    def write(self, *a, **k):
        pass


class FakeMFCapture:
    def __init__(self, available=True):
        self._available = available
        self.calls = []
        self.started = {}

    @property
    def available(self):
        return self._available

    def start_all(self, serials, save_dir, stems, sizes, endpoint):
        self.calls.append(("start_all", list(serials), save_dir))
        if not self._available:
            return False, "dll 缺失", {}
        self.started = {s: f"{save_dir}\\tmp_{s}.mp4" for s in serials}
        return True, "", dict(self.started)

    def stop_all(self):
        self.calls.append(("stop_all",))
        return {s: ([f"{save_dir}\\final_{s}.mp4"], "")
                for s, save_dir in [(k, os.path.dirname(v)) for k, v in self.started.items()]}

    def cancel_all(self):
        self.calls.append(("cancel_all",))


def _api(monkeypatch, tmp_path):
    import core.prefs as prefs
    monkeypatch.setattr(prefs, "prefs_path", lambda: str(tmp_path / "config.json"))
    monkeypatch.setattr(prefs, "legacy_prefs_path", lambda: str(tmp_path / "settings.json"))
    api = WebApi(session_factory=lambda **kw: FakeSession(**kw), auto_update=False)
    api._target_serials = lambda serial=None: ["SER1"]
    api._default_save_dir = lambda: str(tmp_path)
    api._enable_overlay = lambda *a, **k: None
    api._restore_overlays = lambda *a, **k: None
    api._push_status = lambda *a, **k: None
    api._push_toast = lambda *a, **k: None
    api._push_logcat_notes = lambda *a, **k: None
    api._mf_probe_size = lambda s: (1080, 1920)
    return api


def test_mf_usable_gate(monkeypatch, tmp_path):
    api = _api(monkeypatch, tmp_path)
    assert api._mf_usable() is False   # 默认 MFCaptureService 在无 dll 环境不可用
    api.mf_capture = FakeMFCapture(available=True)
    assert api._mf_usable() is True
    api.mf_capture = FakeMFCapture(available=False)
    assert api._mf_usable() is False


def test_start_goes_mf_when_available(monkeypatch, tmp_path):
    api = _api(monkeypatch, tmp_path)
    fake = FakeMFCapture(available=True)
    api.mf_capture = fake
    res = api.screen_record_start(serial="SER1", with_mic=True, save_dir=str(tmp_path))
    assert res["ok"] is True
    assert api._rec_session.get("mf") is True
    assert any(c[0] == "start_all" for c in fake.calls)


def test_start_without_mic_never_uses_mf(monkeypatch, tmp_path):
    """未勾麦克风时绝不能走 MF：native 会无条件采麦克风 → 偷偷录音。

    老路径的纯视频录制不需要 ffmpeg（无音频可合成），screenrecord 原生 mp4
    直接落盘，行为与 MF 改造前一致。这是隐私/功能回归测试。
    """
    api = _api(monkeypatch, tmp_path)
    fake = FakeMFCapture(available=True)   # 即使 dll 可用
    api.mf_capture = fake

    class FakeVideo:
        def start(self, s, d, extra_name=None):
            return True, f"{d}\\record_{s}.mp4"

    api.video = FakeVideo()
    res = api.screen_record_start(serial="SER1", with_mic=False, save_dir=str(tmp_path))
    assert res["ok"] is True
    assert "mf" not in api._rec_session
    assert any(c[0] == "start_all" for c in fake.calls) is False


def test_stop_uses_mf_teardown(monkeypatch, tmp_path):
    api = _api(monkeypatch, tmp_path)
    fake = FakeMFCapture(available=True)
    api.mf_capture = fake
    api.screen_record_start(serial="SER1", with_mic=True, save_dir=str(tmp_path))
    # 让 path_exists 认下假产物
    import backend.controllers.record as rec_mod
    monkeypatch.setattr(rec_mod, "path_exists", lambda p: True)
    res = api.screen_record_stop()
    assert res["ok"] is True
    assert any(c[0] == "stop_all" for c in fake.calls)
    assert api._rec_session == {}


def test_cancel_uses_mf_discard(monkeypatch, tmp_path):
    api = _api(monkeypatch, tmp_path)
    fake = FakeMFCapture(available=True)
    api.mf_capture = fake
    api.screen_record_start(serial="SER1", with_mic=True, save_dir=str(tmp_path))
    res = api.screen_record_cancel()
    assert res["ok"] is True
    assert any(c[0] == "cancel_all" for c in fake.calls)


def test_start_falls_back_when_unavailable(monkeypatch, tmp_path):
    """MF 不可用时走老路径：不应带 mf 标记。"""
    api = _api(monkeypatch, tmp_path)
    fake = FakeMFCapture(available=False)
    api.mf_capture = fake
    # 老路径需要 video.start 成功；用假件顶掉
    class FakeVideo:
        def start(self, s, d, extra_name=None):
            return True, f"{d}\\record_{s}.mp4"
    api.video = FakeVideo()
    api.screen_record_start(serial="SER1", save_dir=str(tmp_path))
    assert "mf" not in api._rec_session
    assert any(c[0] == "start_all" for c in fake.calls) is False


def test_mf_probe_size_keeps_landscape_and_caps_edge(monkeypatch, tmp_path):
    """回归：横屏车机 1920x1080 不能被旧逻辑 `w <= h` 强行改成 1080x1920
    （编码器声明竖屏、真实帧横屏 → 起不来或产出旋转/损坏视频）；长边还要
    封顶 1920，避免 4K 原始分辨率让 screenrecord 编码器初始化极慢、首帧超时。"""
    api = _api(monkeypatch, tmp_path)
    seen = {}

    def fake_plan_size(adb, serial, max_edge=1080):
        seen["max_edge"] = max_edge
        return "1920x1080"          # 模拟横屏车机 wm size 原始输出

    monkeypatch.setattr("backend.controllers.record.plan_size", fake_plan_size)
    # _api() 为其它测试 mock 了实例方法，这里取回类上的真实实现来验证。
    real_probe = api.__class__._mf_probe_size.__get__(api)
    assert real_probe("SER1") == (1920, 1080)
    assert seen["max_edge"] == 1920  # 录制上限比投屏 1080 宽松，保留画质


def test_mf_start_rejects_duplicate_session(monkeypatch, tmp_path):
    """MF 路径也要有重复启动守卫：录制中再点「开始」不能覆盖会话引用。

    回归：MF 分支过去没有这层守卫，第二次 start 会顶掉旧 native 会话，
    旧的再无引用、停止时不 finalize（MP4 缺 moov），overlay 原值也丢失。
    """
    api = _api(monkeypatch, tmp_path)
    fake = FakeMFCapture(available=True)
    api.mf_capture = fake
    res1 = api.screen_record_start(serial="SER1", with_mic=True, save_dir=str(tmp_path))
    assert res1["ok"] is True
    first_session = api._rec_session
    res2 = api.screen_record_start(serial="SER1", with_mic=True, save_dir=str(tmp_path))
    assert res2["ok"] is False and res2["reason"] == "recording"
    assert api._rec_session is first_session, "重复启动覆盖了进行中的会话"
    # start_all 只该被调用一次
    assert len([c for c in fake.calls if c[0] == "start_all"]) == 1


def test_mf_start_exception_cancels_native_resources(monkeypatch, tmp_path):
    """MF 启动链路抛异常后，异常撤销必须调 mf_capture.cancel_all()。

    回归：_cancel_half_started_rec 过去只停 video/devaudio/mic/logcat，没有
    MF 分支；而 MF 会话的 self._mic 恒为 None、video.stop 对它无效，导致
    native worker / 设备 screenrecord / TEMP 裸流全部泄漏。
    """
    api = _api(monkeypatch, tmp_path)
    fake = FakeMFCapture(available=True)
    api.mf_capture = fake
    # 让 with_logcat 抓取在 start_all 之后抛异常，触发 start 的整体 except
    api._target_serials = lambda serial=None: ["SER1"]
    real_start = api.__class__.screen_record_start.__get__(api)

    def boom(*a, **kw):
        raise RuntimeError("模拟 logcat 启动异常")

    api.logcat_capture.start = boom
    res = real_start(serial="SER1", with_mic=True, with_logcat=True, save_dir=str(tmp_path))
    assert res["ok"] is False and res["reason"] == "start_error"
    assert any(c[0] == "cancel_all" for c in fake.calls), "异常撤销未清理 MF native 会话"
    assert api._rec_session == {}
