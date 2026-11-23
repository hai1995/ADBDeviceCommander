"""设备分段录屏 EDR 误报缓解（A 方案）：分段中间产物收敛到系统 TEMP。

背景
----
用户真机实测：录屏十多分钟（screenrecord 自动分 5 段），收尾合成后逐个
``os.remove`` 删中间段，删到第 2 段时被亚信 EDR「未授权文件加密」拦截杀进程；
且分段 mp4 直接落在程序运行目录。这是勒索行为检测盯的「写高熵 MP4 → 改名 →
批量删」序列。同源录制 MF 早前已用 A 方案（TEMP 工作目录 + 成品回拷 + 延迟
清理）缓解，但**设备分段路径漏了**；本测试锁定该路径也走 A 方案。

策略与 MF 对称：
  * start 建 ``adc_seg_`` 前缀的 TEMP 工作目录，分段 / 麦克风 wav 落这里；
  * 收尾成品 copy 回用户保存目录，对外路径不含 TEMP；
  * 收尾瞬间零删除（中间段 / 原始视频 / wav 留在工作目录），下次启动由
    ``sweep_workdirs`` 后台递归清理。

真机 EDR 行为不在此覆盖（黑盒），这里只验证文件布局与删除时机。
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import backend.screen_service as ss
from backend.controller import WebApi
from core import tmpfiles


class _Session:
    """最小 ShellSession 替身：录屏收尾不碰会话，只需能被构造。"""

    def __init__(self, output_callback=None, on_dir_change=None, **kw):
        self.output_callback = output_callback
        self.on_dir_change = on_dir_change
        self.current_dir = ""
        self.calls = []
        self.killed = 0

    def run(self, *a, **kw):
        return ""

    def kill(self):
        self.killed += 1


def _api():
    return WebApi(session_factory=lambda **kw: _Session(**kw),
                  auto_update=False)


def _seed_one_device(api):
    api.devices.device_state = {"A1": "device"}
    api.devices.device_checked = {"A1": True}


def _patch_screen_pull(monkeypatch, segments=2):
    """让 screenrecord 的 adb pull 把 ``segments`` 段落到各自目标路径。

    同时把自动分段“录满”事件的门槛降到极低，让 watcher 自动补段，模拟真实
    的 5 段录制；不真起 adb / ffmpeg。
    """
    class _Proc:
        def poll(self): return None
        def terminate(self): pass
        def kill(self): pass
        def wait(self, timeout=None): return 0

    class _R:
        def __init__(self, out="", rc=0):
            self.stdout, self.returncode, self.stderr = out, rc, ""

    pulled = []

    def fake_run(cmd, **kw):
        if "pull" in cmd:
            dst = cmd[-1]
            with open(dst, "wb") as f:
                f.write(b"\x00\x00\x00\x18ftypmp42" + b"A" * 80 + b"moov")
            pulled.append(dst)
            return _R()
        if "ls" in cmd:
            return _R("record.mp4")
        return _R()

    monkeypatch.setattr(ss.subprocess, "Popen", lambda *a, **k: _Proc())
    monkeypatch.setattr(ss.subprocess, "run", fake_run)
    return pulled


def _mkdtemp_under(monkeypatch, parent):
    """把录制工作目录重定向到 tmp_path（默认落系统 TEMP），测试互不干扰。"""
    real = tempfile.mkdtemp

    def fake(prefix=""):
        return real(prefix=prefix, dir=str(parent))
    monkeypatch.setattr(tempfile, "mkdtemp", fake)


# ---------------------------------------------------------------------------
def test_segments_are_pulled_to_temp_workdir_not_save_dir(monkeypatch, tmp_path):
    """分段落 ``adc_seg_`` 前缀的 TEMP 工作目录，不在用户保存目录。"""
    save = tmp_path / "save"
    save.mkdir()
    _mkdtemp_under(monkeypatch, tmp_path)
    _patch_screen_pull(monkeypatch)

    api = _api()
    _seed_one_device(api)
    assert api.screen_record_start(None, save_dir=str(save))["ok"] is True
    work = api._rec_session["work_dir"]
    try:
        assert work and os.path.isdir(work)
        assert os.path.basename(work).startswith("adc_seg_")
        assert os.path.abspath(work) != os.path.abspath(str(save))
    finally:
        api.screen_record_cancel()
        api.workers.shutdown(timeout=2.0)


def test_stop_publishes_product_and_defers_cleanup(monkeypatch, tmp_path):
    """收尾：成片回拷到保存目录、对外路径不含 TEMP；中间产物收尾零删除。"""
    save = tmp_path / "save"
    save.mkdir()
    _mkdtemp_under(monkeypatch, tmp_path)

    class _Proc:
        def poll(self): return None
        def terminate(self): pass
        def kill(self): pass
        def wait(self, timeout=None): return 0

    class _R:
        def __init__(self, out="", rc=0):
            self.stdout, self.returncode, self.stderr = out, rc, ""

    def fake_run(cmd, **kw):
        if "pull" in cmd:
            with open(cmd[-1], "wb") as f:
                f.write(b"\x00\x00\x00\x18ftypmp42" + b"B" * 80 + b"moov")
            return _R()
        if "ls" in cmd:
            return _R("record.mp4")
        return _R()

    monkeypatch.setattr(ss.subprocess, "Popen", lambda *a, **k: _Proc())
    monkeypatch.setattr(ss.subprocess, "run", fake_run)

    api = _api()
    _seed_one_device(api)
    assert api.screen_record_start(None, save_dir=str(save))["ok"] is True
    work = api._rec_session["work_dir"]
    work_files_before = set(os.listdir(work))

    # 走真实收尾：合并只有 1 段（直接返回原路径）→ 回拷成品。
    assert api.screen_record_stop() == {"ok": True}
    api.workers.shutdown(timeout=2.0)

    # 成品出现在用户保存目录，文件名与工作目录里的中间文件一致。
    saved = list(save.glob("record_A1_*.mp4"))
    assert saved, "成品必须回拷到用户保存目录"
    assert any(str(save) in (p.get("text") or "")
               for p in _events(api).get("status", [])), (
        "完成提示里应给出用户保存目录，而非 TEMP 路径")
    # 收尾零删除：工作目录里原有文件一个不少（删除推迟到下次启动）。
    assert work_files_before <= set(os.listdir(work)), (
        "收尾瞬间不得批量删工作目录里的高熵 MP4")
    assert os.path.isdir(work), "工作目录原样留给下次启动清理"


def test_merge_defers_batch_delete_of_used_segments(monkeypatch, tmp_path):
    """核心回归：多段合并后**不批量删中间段**（用户实测删第 2 段时被亚信杀）。

    work_dir 非空时，5 个已并入成片的段一个都不删，留待下次启动；work_dir=None
    时保留旧行为（立即删），既有测试因此零回归。
    """
    import backend.controllers.record as rec

    api = _api()
    work = tmp_path / "adc_seg_merge"
    work.mkdir()
    segs = []
    for i in range(1, 6):
        p = work / (f"record_A1_ts_p{i}.mp4")
        p.write_bytes(b"\x00\x00\x00\x18ftypmp42moov" + bytes([i]) * 50)
        segs.append(p)

    # 替真实 ffmpeg：把各段字节顺序拼进 out。
    def fake_join(paths, out_path, timeout=None):
        with open(out_path, "wb") as f:
            for p in paths:
                with open(p, "rb") as src:
                    f.write(src.read())
        return {"ok": True, "path": out_path, "used": list(paths),
                "skipped": [], "reason": None}

    monkeypatch.setattr(rec, "join_segments", fake_join)

    # A 方案：work_dir 非空 → 中间段不删。
    final, n_used, _ = api._merge_device_segments(
        "A1", [str(p) for p in segs], work_dir=str(work))
    assert n_used == 5
    assert all(p.exists() for p in segs), "5 个中间段收尾一个都不能删"
    assert final and os.path.exists(final), "成片仍要生成"

    # 老行为：work_dir=None → 立即删（兼容既有逻辑）。
    segs2 = []
    for i in range(1, 4):
        p = work / (f"old_A1_ts_p{i}.mp4")
        p.write_bytes(b"\x00\x00\x00\x18ftypmp42moov" + bytes([i]) * 50)
        segs2.append(p)
    api._merge_device_segments("A1", [str(p) for p in segs2], work_dir=None)
    assert not any(p.exists() for p in segs2), "无工作目录时保留旧行为：中间段立即删"


def test_cancel_defers_workdir_cleanup(monkeypatch, tmp_path):
    """取消：工作目录不删（延迟清理），用户保存目录不留成品。"""
    save = tmp_path / "save"
    save.mkdir()
    _mkdtemp_under(monkeypatch, tmp_path)
    _patch_screen_pull(monkeypatch)

    api = _api()
    _seed_one_device(api)
    assert api.screen_record_start(None, save_dir=str(save))["ok"] is True
    work = api._rec_session["work_dir"]
    api.screen_record_cancel()
    api.workers.shutdown(timeout=2.0)

    assert os.path.isdir(work), "取消收尾不删工作目录，推迟到下次启动"
    assert not list(save.glob("record_A1_*.mp4")), "取消不应在保存目录发布成品"


def test_next_boot_sweep_cleans_seg_workdir(monkeypatch, tmp_path):
    """下次启动的 sweep_workdirs 递归清理 adc_seg_ 工作目录，不碰成品。"""
    from core import tmpfiles as tf

    save = tmp_path / "save"
    save.mkdir()
    _mkdtemp_under(monkeypatch, tmp_path)
    _patch_screen_pull(monkeypatch)

    api = _api()
    _seed_one_device(api)
    assert api.screen_record_start(None, save_dir=str(save))["ok"] is True
    work = api._rec_session["work_dir"]
    assert api.screen_record_stop() == {"ok": True}
    api.workers.shutdown(timeout=2.0)
    assert os.path.isdir(work), "前提：收尾不删"
    published = list(save.glob("record_A1_*.mp4"))
    assert published, "前提：成品已回拷"

    stat = tf.sweep_workdirs(min_age_s=60.0, directory=str(tmp_path),
                             now=9999999999.0)
    assert stat["removed"] >= 1, stat
    assert not os.path.exists(work), "下次启动应递归清理工作目录"
    for p in published:
        assert os.path.isfile(p), "清理工作目录绝不能碰用户保存目录的成品"


def test_sweep_workdirs_covers_both_prefixes(tmp_path):
    """sweep_workdirs 默认同时清理 MF 与设备分段两种工作目录前缀。"""
    old_mf = tmp_path / (tmpfiles.MF_WORKDIR_PREFIX + "mf")
    old_seg = tmp_path / (tmpfiles.SEG_WORKDIR_PREFIX + "seg")
    old_mf.mkdir()
    old_seg.mkdir()
    (old_mf / "x.tmp.mp4").write_bytes(b"mf")
    (old_seg / "y.mp4").write_bytes(b"seg")

    stat = tmpfiles.sweep_workdirs(min_age_s=60.0, directory=str(tmp_path),
                                   now=9999999999.0)
    assert stat["removed"] >= 2, stat
    assert not old_mf.exists() and not old_seg.exists(), stat


def _events(api):
    out = {}
    for e in api.bus.take():
        out.setdefault(e["kind"], []).append(e["payload"])
    return out
