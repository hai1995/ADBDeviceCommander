"""同源录制 EDR 误报缓解：native 中间产物收敛到系统 TEMP 的回归测试。

背景：企业 EDR（亚信）的"未授权文件加密"行为检测会把"用户目录里写高熵
半成品 → 改名 → 批量删"判定为勒索行为。同源录制改用系统 TEMP 作 native
工作目录，成品只在 finalize 成功后 copy 回用户保存目录。

本测试用会真实落盘的 FakeNative 覆盖：工作目录隔离、成品回搬、目录清理、
copy 失败明确上报（不误报成功）。真机 native 行为不在此覆盖。
"""
import importlib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

mcs = importlib.import_module("backend.mf_capture_service")


class _FakeProc:
    def __init__(self):
        import io
        self.stdout = io.BytesIO(b"\x00\x00\x01\x65" + b"\xaa" * 16)
        self.stderr = io.BytesIO(b"")

    def poll(self):
        return None

    def terminate(self):
        pass

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


class DiskNative:
    """finalize 时在工作目录真实落一个 .mp4，返回其完整路径。"""

    def __init__(self):
        self._available = True
        self.error = ""
        self.worker = type("W", (), {"stop": lambda self: None})()
        self.out_dirs = []
        self.finalized = []
        self.fail_copy = False

    @property
    def available(self):
        return True

    def start_worker(self):
        return self.worker

    def last_error(self):
        return ""

    def mic_start(self, *a):
        return 0

    def mic_stop(self):
        pass

    def mic_format(self):
        return (48000, 16, 2)

    def session_create(self, out_dir, stem, w, h, fn, fd, ar, ab, ach):
        self.out_dirs.append(out_dir)
        return 1, os.path.join(out_dir, stem + "_p1.tmp.mp4")

    def session_write_video(self, h, data):
        pass

    def session_mark_mic_stop(self, h):
        pass

    def session_drain_audio(self, h):
        pass

    def session_finalize(self, h):
        out_dir = self.out_dirs[-1]
        final = os.path.join(out_dir, "record_final.mp4")
        if self.fail_copy:
            # 不落盘：模拟 finalize 报了产物但文件不存在
            return [final]
        with open(final, "wb") as f:
            f.write(b"\x00\x00\x00\x18ftypmp42" + b"\xab" * 64)
        self.finalized.append(final)
        return [final]

    def session_discard(self, h):
        pass

    def session_destroy(self, h):
        pass


def _start(monkeypatch, native, save_dir):
    monkeypatch.setattr(mcs.subprocess, "Popen", lambda cmd, **kw: _FakeProc())
    svc = mcs.MFCaptureService(native=native)
    ok, reason, firsts = svc.start_all(["s1"], save_dir, {}, {}, None)
    assert ok is True, reason
    return svc


def test_native_uses_temp_workdir_not_save_dir(monkeypatch, tmp_path):
    """native 的 out_dir 必须是系统 TEMP 工作目录，不是用户保存目录。"""
    save = tmp_path / "save"
    save.mkdir()
    native = DiskNative()
    svc = _start(monkeypatch, native, str(save))
    try:
        work = native.out_dirs[0]
        assert work != str(save), "native 不应直接写用户保存目录"
        assert os.path.isdir(work), "工作目录应真实存在"
        assert os.path.basename(work).startswith("adc_mf_")
    finally:
        svc.stop_all()


def test_finalized_product_copied_back_to_save_dir(monkeypatch, tmp_path):
    """finalize 成功后，成品必须出现在用户保存目录，且工作目录被清理。"""
    save = tmp_path / "save"
    save.mkdir()
    native = DiskNative()
    svc = _start(monkeypatch, native, str(save))
    work = native.out_dirs[0]
    out = svc.stop_all()
    paths, err = out["s1"]
    assert err == ""
    assert len(paths) == 1
    assert paths[0] == str(save / "record_final.mp4")
    assert os.path.isfile(paths[0]), "成品必须真实落地到保存目录"
    # 工作目录（含 .tmp.mp4 中间态）收尾后删除
    assert not os.path.exists(work), "工作目录应在 stop_all 后清理"


def test_cancel_cleans_workdir_without_publish(monkeypatch, tmp_path):
    """取消时不发布成品，且工作目录被清理。"""
    save = tmp_path / "save"
    save.mkdir()
    native = DiskNative()
    svc = _start(monkeypatch, native, str(save))
    work = native.out_dirs[0]
    svc.cancel_all()
    assert not os.path.exists(work), "取消后工作目录也应清理"
    assert not (save / "record_final.mp4").exists(), "取消不应发布成品"


def test_missing_product_is_reported_not_fake_success(monkeypatch, tmp_path):
    """finalize 报了产物但文件不存在时：不能返回虚构成果路径。"""
    save = tmp_path / "save"
    save.mkdir()
    native = DiskNative()
    native.fail_copy = True
    svc = _start(monkeypatch, native, str(save))
    out = svc.stop_all()
    paths, err = out["s1"]
    # finalize 报了产物却没落盘 → 不入产物列表 + 明确上报，绝不误报成功
    assert paths == []
    assert "未落盘" in err
    assert not (save / "record_final.mp4").exists()
