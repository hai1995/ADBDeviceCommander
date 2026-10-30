# -*- coding: utf-8 -*-
"""backend.controllers —— WebApi 的各领域 Mixin 集合。"""

from .base import WebApiBase
from .device import DeviceMixin
from .commands import CommandMixin
from .autorefresh import AutoRefreshMixin
from .logcat import LogcatMixin
from .settings import SettingsMixin
from .apk import ApkMixin
from .deviceinfo import DeviceInfoMixin
from .update import UpdateMixin
from .screenshot import ScreenshotMixin
from .record import RecordMixin
from .perf import PerfMixin
from .file import FileMixin

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
