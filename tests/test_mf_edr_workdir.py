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
    ok, reason, _firsts = svc.start_all(["s1"], save_dir, {}, {}, None)
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
    # [延迟清理] 收尾瞬间不再批量删除：工作目录原样留在 TEMP，绝不在
    # "点停止"这一刻 rmtree（避开 EDR 勒索特征的写→改名→删序列）。
    # 目录由下次启动的 tmpfiles.sweep_workdirs 后台清理，见专项测试。
    assert os.path.isdir(work), "收尾不删工作目录，删除推迟到下次启动"


def test_cancel_defers_workdir_cleanup_without_publish(monkeypatch, tmp_path):
    """取消时不发布成品，工作目录同样留待下次启动清理（收尾零删除）。"""
    save = tmp_path / "save"
    save.mkdir()
    native = DiskNative()
    svc = _start(monkeypatch, native, str(save))
    work = native.out_dirs[0]
    svc.cancel_all()
    assert os.path.isdir(work), "取消收尾不删工作目录，删除推迟到下次启动"
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


def test_publish_does_not_overwrite_existing_product(monkeypatch, tmp_path):
    """保存目录已有同名视频时：成品回拷必须补 _2，不覆盖上一场用户产物。

    与项目其它产物链路（截图/logcat/perf/命令导出/wav）的 unique_path 约定
    对齐。A 方案把成品从 work_dir copy 回 save_dir 时若直接用 basename 落盘，
    同秒 stop→start（stem 时间戳相同）会静默覆盖上一份视频，故加此回归。
    """
    save = tmp_path / "save"
    save.mkdir()
    (save / "record_final.mp4").write_bytes(b"OLD_USER_VIDEO")
    native = DiskNative()
    svc = _start(monkeypatch, native, str(save))
    out = svc.stop_all()
    paths, err = out["s1"]
    assert err == ""
    assert paths == [str(save / "record_final_2.mp4")]
    assert (save / "record_final.mp4").read_bytes() == b"OLD_USER_VIDEO"
    assert (save / "record_final_2.mp4").exists()

    # 再次录制：连同名 _2 也已被占，应落到 _3，且前两份都不动
    svc2 = _start(monkeypatch, native, str(save))
    out2 = svc2.stop_all()
    paths2, _ = out2["s1"]
    assert paths2 == [str(save / "record_final_3.mp4")]
    assert (save / "record_final.mp4").read_bytes() == b"OLD_USER_VIDEO"
    assert (save / "record_final_2.mp4").exists()


def test_deferred_workdir_cleaned_by_next_boot_sweep(monkeypatch, tmp_path):
    """停止后遗留的工作目录，在下次启动由 sweep_workdirs 后台清理。

    串起完整链路：本次 stop 不删（上面已断言）→ 模拟下次启动调用 sweep →
    旧工作目录被递归删除，而用户保存目录里的成品不受影响。
    """
    from core import tmpfiles
    import tempfile

    save = tmp_path / "save"
    save.mkdir()
    # 把工作目录重定向到 tmp_path（默认落系统 TEMP），这样 sweep 只扫这一处，
    # 测试互不干扰、也不碰真机 TEMP。
    real_mkdtemp = tempfile.mkdtemp
    monkeypatch.setattr(
        tempfile, "mkdtemp",
        lambda prefix="": real_mkdtemp(prefix=prefix, dir=str(tmp_path)))
    native = DiskNative()
    svc = _start(monkeypatch, native, str(save))
    work = native.out_dirs[0]
    out = svc.stop_all()
    published = out["s1"][0][0]
    assert os.path.isdir(work), "前提：收尾不删"
    assert os.path.isfile(published), "前提：成品已回拷"

    # 下次启动的后台清理：工作目录足够旧（注入 now 前进），应被递归删除。
    stat = tmpfiles.sweep_workdirs(
        min_age_s=60.0, directory=str(tmp_path), now=9999999999.0)
    assert stat["removed"] >= 1, stat
    assert not os.path.exists(work), "下次启动时旧工作目录应被清理"
    assert os.path.isfile(published), "清理工作目录绝不能碰用户保存目录的成品"
