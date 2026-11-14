"""backend.controllers —— WebApi 的各领域 Mixin 集合。"""

from .apk import ApkMixin
from .autorefresh import AutoRefreshMixin
from .base import WebApiBase
from .commands import CommandMixin
from .device import DeviceMixin
from .deviceinfo import DeviceInfoMixin
from .file import FileMixin
from .logcat import LogcatMixin
from .perf import PerfMixin
from .record import RecordMixin
from .screenshot import ScreenshotMixin
from .settings import SettingsMixin
from .update import UpdateMixin

__all__ = [
    "WebApiBase",
    "DeviceMixin",
    "CommandMixin",
    "AutoRefreshMixin",
    "LogcatMixin",
    "SettingsMixin",
    "ApkMixin",
    "DeviceInfoMixin",
    "UpdateMixin",
    "ScreenshotMixin",
    "RecordMixin",
    "PerfMixin",
    "FileMixin",
]
