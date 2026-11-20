"""
core.ffmpeg_bin —— ffmpeg 可执行文件定位（内置优先，PATH 兜底）。

背景：录屏的音视频合成 / 多段合并依赖 ffmpeg，但目标机器大多没装。
打包时由 build.py 把 imageio-ffmpeg 自带的 ffmpeg 二进制用 --add-binary
嵌进 exe（见 BUNDLED_FFMPEG），运行时这里按以下优先级解析：

  1. 内置副本：exe 同目录 / PyInstaller 解包目录(_MEIPASS) 下的 ffmpeg(.exe)。
     —— 打包用户零配置、离线可用，这是主路径。
  2. 开发态的 imageio_ffmpeg.get_ffmpeg_exe()：源码运行时依赖已在
     requirements.txt 里，直接拿它带的二进制，开发者无需另装 ffmpeg。
  3. PATH 里的 ffmpeg：以上都没有时的最后兜底（老用户自建 PATH 仍可用）。

只解析 **ffmpeg**；ffprobe 不在 imageio-ffmpeg 里，仍走 PATH，调用方
（audio_service 的 _mp4_playable / _video_duration）本来就有「取不到 ffprobe
就本地解析 MP4 头」的兜底，行为不变。
"""
import glob
import os
import shutil
import sys

from core.constants import PROJECT_ROOT
from core.longpath import path_isdir, path_isfile

# 内置二进制的精确名（优先）与 glob 模式（兼容 imageio 的版本化命名）。
# --add-binary 以 "." 嵌入包根，保留原名 ffmpeg-win-x86_64-v7.1.exe 之类，
# 故必须按模式匹配，不能只认 ffmpeg.exe。
_FFMPEG_EXACT = ("ffmpeg.exe", "ffmpeg")
_FFMPEG_GLOB = "ffmpeg*.exe" if os.name == "nt" else "ffmpeg*"


def _find_in_dir(directory):
    """在单个目录里找 ffmpeg：精确名优先，其次 glob 匹配；找不到返回 None。"""
    if not directory or not path_isdir(directory):
        return None
    for name in _FFMPEG_EXACT:
        p = os.path.join(directory, name)
        if path_isfile(p):
            return p
    for p in sorted(glob.glob(os.path.join(directory, _FFMPEG_GLOB))):
        if path_isfile(p):
            return p
    return None


def _bundled_ffmpeg():
    """返回打包内置 ffmpeg 的路径；不存在返回 None。

    查找顺序：
    - 运行文件同目录（exe 旁，便于外发覆盖）；
    - PyInstaller 解包目录 _MEIPASS（--add-binary 嵌入的原名二进制）；
    - 开发态项目根（本地放一份覆盖）。
    """
    dirs = []
    if getattr(sys, "frozen", False):
        dirs.append(os.path.dirname(os.path.abspath(sys.executable)))
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(meipass)
    if not getattr(sys, "frozen", False):
        dirs.append(PROJECT_ROOT)
    for d in dirs:
        found = _find_in_dir(d)
        if found:
            return found
    return None


def _imageio_ffmpeg():
    """开发态：从已安装的 imageio-ffmpeg 包拿二进制；拿不到返回 None。"""
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        return exe if exe and path_isfile(exe) else None
    except Exception:  # noqa: BLE001  未安装 / 包损坏都回落到 PATH
        return None


def ffmpeg_exe():
    """返回可用于 subprocess 的 ffmpeg 可执行文件路径（字符串）。

    打包用户拿到的是内置副本，完全不依赖机器是否装过 ffmpeg；开发者和
    老用户仍能回落到 imageio-ffmpeg 或 PATH。全部找不到时返回 "ffmpeg"
    ——交给 subprocess 报 FileNotFoundError，由调用方的「合成失败」分支
    转成可读提示，而不是在这里抛异常打断收尾。
    """
    p = _bundled_ffmpeg()
    if p:
        return p
    p = _imageio_ffmpeg()
    if p:
        return p
    p = shutil.which("ffmpeg")
    return p or "ffmpeg"


def ffmpeg_source():
    """诊断用：返回 'bundled' / 'imageio' / 'path' / 'missing'，便于 UI 说明来源。"""
    if _bundled_ffmpeg():
        return "bundled"
    if _imageio_ffmpeg():
        return "imageio"
    if shutil.which("ffmpeg"):
        return "path"
    return "missing"
