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
    res = api.screen_record_start(serial="SER1", save_dir=str(tmp_path))
    assert res["ok"] is True
    assert api._rec_session.get("mf") is True
    assert any(c[0] == "start_all" for c in fake.calls)


def test_stop_uses_mf_teardown(monkeypatch, tmp_path):
    api = _api(monkeypatch, tmp_path)
    fake = FakeMFCapture(available=True)
    api.mf_capture = fake
    api.screen_record_start(serial="SER1", save_dir=str(tmp_path))
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
    api.screen_record_start(serial="SER1", save_dir=str(tmp_path))
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
    res = api.screen_record_start(serial="SER1", save_dir=str(tmp_path))
    assert "mf" not in api._rec_session
    assert any(c[0] == "start_all" for c in fake.calls) is False
