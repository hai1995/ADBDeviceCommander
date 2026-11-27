"""RecordMixin 的全走 MF（同源录制）分流测试。

[v36 全走 MF] 录屏不再依赖 ffmpeg：无论是否勾麦克风都走 MF（未勾麦走
native 无音轨纯视频模式 with_audio=False）；MF 不可用时明确报错，不再
回退到已删除的 ffmpeg 路径。验证 start/stop/cancel 都走 MF、会话结构带
'mf' 标记、异常撤销清理 native。真机 native 行为不在此覆盖。
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
    def __init__(self, available=True, build_id="mf-test-build"):
        self._available = available
        self._build_id = build_id
        self.calls = []
        self.started = {}

    @property
    def available(self):
        return self._available

    @property
    def build_id(self):
        return self._build_id

    def start_all(self, serials, save_dir, stems, sizes, endpoint,
                  with_audio=True):
        self.calls.append(("start_all", list(serials), save_dir,
                           bool(with_audio)))
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


def test_start_shows_native_build_id(monkeypatch, tmp_path):
    """启动成功提示必须带 native 构建指纹，供日志确认 DLL 是否重新编译。"""
    api = _api(monkeypatch, tmp_path)
    statuses = []
    api._push_status = lambda level, text, *a, **k: statuses.append((level, text))
    api.mf_capture = FakeMFCapture(available=True, build_id="mf-20261123-esdsdiag-v4")
    api.screen_record_start(serial="SER1", with_mic=True, save_dir=str(tmp_path))
    oks = [t for lvl, t in statuses if lvl == "ok" and "同源录制" in t]
    assert oks and "mf-20261123-esdsdiag-v4" in oks[-1], (
        f"启动提示应带构建指纹，实际: {oks}")


def test_start_warns_when_build_id_missing(monkeypatch, tmp_path):
    """老 DLL（无构建指纹）必须给出重编译提示，避免拿旧 DLL 反复测。"""
    api = _api(monkeypatch, tmp_path)
    statuses = []
    api._push_status = lambda level, text, *a, **k: statuses.append((level, text))
    api.mf_capture = FakeMFCapture(available=True, build_id="")
    api.screen_record_start(serial="SER1", with_mic=True, save_dir=str(tmp_path))
    oks = [t for lvl, t in statuses if lvl == "ok" and "同源录制" in t]
    assert oks and "重新编译" in oks[-1], f"应提示重编译 dll，实际: {oks}"


def test_start_goes_mf_when_available(monkeypatch, tmp_path):
    api = _api(monkeypatch, tmp_path)
    fake = FakeMFCapture(available=True)
    api.mf_capture = fake
    res = api.screen_record_start(serial="SER1", with_mic=True, save_dir=str(tmp_path))
    assert res["ok"] is True
    assert api._rec_session.get("mf") is True
    assert any(c[0] == "start_all" for c in fake.calls)


def test_start_mf_partial_failure_is_reported(monkeypatch, tmp_path):
    """多台录制部分设备失败时要逐台点名提示，不能只播「已开始」。

    回归：start_all 只要有一台成功就返回 ok=True，失败设备被丢弃（firsts
    里没有它）。旧实现这里只播成功提示，用户以为全录上了，事后才发现少了
    设备素材。
    """
    api = _api(monkeypatch, tmp_path)
    api._target_serials = lambda serial=None: ["SER1", "SER2"]
    statuses = []
    api._push_status = lambda level, text, *a, **k: statuses.append((level, text))

    class PartialFake(FakeMFCapture):
        def start_all(self, serials, save_dir, stems, sizes, endpoint,
                      with_audio=True):
            # 只 SER1 成功；SER2 首帧超时失败
            self.started = {"SER1": f"{save_dir}\\tmp_SER1.mp4"}
            return True, "", dict(self.started)

    api.mf_capture = PartialFake(available=True)
    res = api.screen_record_start(serial=None, with_mic=True, save_dir=str(tmp_path))
    assert res["ok"] is True, "至少一台成功即视为启动成功"
    errs = [t for lvl, t in statuses if lvl == "err" and "SER2" in t]
    assert errs, "失败设备 SER2 必须有点名提示，实际状态: %r" % statuses


def test_start_without_mic_uses_mf_without_audio(monkeypatch, tmp_path):
    """[v36 全走 MF] 未勾麦克风时也走 MF，但必须 with_audio=False。

    native 收到 arate=0 后不订阅 WASAPI、不建 AAC 轨，绝不"偷偷录音"。
    这是隐私/功能回归：既全走 MF 去掉 ffmpeg，又不能录进用户的声音。
    """
    api = _api(monkeypatch, tmp_path)
    fake = FakeMFCapture(available=True)
    api.mf_capture = fake
    res = api.screen_record_start(serial="SER1", with_mic=False, save_dir=str(tmp_path))
    assert res["ok"] is True
    assert api._rec_session.get("mf") is True
    starts = [c for c in fake.calls if c[0] == "start_all"]
    assert len(starts) == 1 and starts[0][3] is False, (
        f"未勾麦须走 MF 且 with_audio=False，实际: {starts}")


def test_start_with_mic_uses_mf_with_audio(monkeypatch, tmp_path):
    """[v36] 勾麦克风时走 MF 且 with_audio=True（带声录制路径不变）。"""
    api = _api(monkeypatch, tmp_path)
    fake = FakeMFCapture(available=True)
    api.mf_capture = fake
    res = api.screen_record_start(serial="SER1", with_mic=True, save_dir=str(tmp_path))
    assert res["ok"] is True
    starts = [c for c in fake.calls if c[0] == "start_all"]
    assert len(starts) == 1 and starts[0][3] is True


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


def test_mf_stop_no_video_reports_failure_not_fake_success(monkeypatch, tmp_path):
    """[真失败根治 v28] MF 收尾没产出任何视频，只有 logcat txt 时，
    完成提示绝不能谎报「✓ 录屏已完成：1 个文件已保存」。

    真机 12min 长录制：finalize 超时 + 屏障过早放弃 → 成片烂在 TEMP，
    stop_all 返回 ([], err)，但 logcat txt 仍在 → files 里有 1 个 txt。
    旧实现据 len(files) 报成功，用户去目录一看没有视频。修复后必须据实
    报失败、返回 ok=False，并把收尾错误原因带出来。
    """
    api = _api(monkeypatch, tmp_path)

    # 捕获 toast/status，验证完成提示文案
    toasts = []
    api._push_toast = lambda kind, text: toasts.append((kind, text))
    api._push_status = lambda *a, **k: None
    api._push_logcat_notes = lambda *a, **k: None

    class _NoVideoMF:
        available = True
        build_id = "mf-test"

        def start_all(self, *a, **kw):
            return True, "", {"SER1": "/tmp/reports.mp4"}

        def stop_all(self):
            # 收尾失败：没有视频成片，只有一条错误
            return {"SER1": ([], "同源合成失败：MF worker 调用超时，未捞回已发布成片")}

        def cancel_all(self):
            pass

    api.mf_capture = _NoVideoMF()

    # 构造已经在录制中的 MF 会话，附带一个存在的 logcat txt（真机情形）
    log = tmp_path / "logcat_SER1.txt"
    log.write_text("log line\n", encoding="utf-8")
    api._rec_session = {
        "ts": "20261125_150427", "dir": str(tmp_path), "with_zip": False,
        "mf": True, "videos": {}, "mic_path": None, "mic_started": True,
        "devaudio": {}, "logcat_captures": {"SER1": str(log)},
        "pointer_location_prev": {}, "show_touches_prev": {},
    }

    res = api.screen_record_stop()
    assert res["ok"] is False and res["reason"] == "no_video", res
    # 绝不能出现谎报成功的完成提示
    done_ok = [t for k, t in toasts if k == "ok" and "录屏已完成" in t]
    assert done_ok == [], f"无视频却报完成：{done_ok}"
    # 必须有明确的失败提示，且带出收尾错误原因
    fail = [t for k, t in toasts if k == "err" and "录屏失败" in t]
    assert fail, f"须如实报录屏失败，实际 toast: {toasts}"
    assert "未捞回" in fail[0] or "超时" in fail[0], fail[0]


def test_cancel_uses_mf_discard(monkeypatch, tmp_path):
    api = _api(monkeypatch, tmp_path)
    fake = FakeMFCapture(available=True)
    api.mf_capture = fake
    api.screen_record_start(serial="SER1", with_mic=True, save_dir=str(tmp_path))
    res = api.screen_record_cancel()
    assert res["ok"] is True
    assert any(c[0] == "cancel_all" for c in fake.calls)


def test_start_reports_error_when_mf_unavailable(monkeypatch, tmp_path):
    """[v36] MF 不可用时明确报错，不再回退到已删除的 ffmpeg 老路径。"""
    api = _api(monkeypatch, tmp_path)
    fake = FakeMFCapture(available=False)
    api.mf_capture = fake
    res = api.screen_record_start(serial="SER1", save_dir=str(tmp_path))
    assert res["ok"] is False and res["reason"] == "mf_unavailable", res
    assert "录屏不可用" in res["error"]
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
