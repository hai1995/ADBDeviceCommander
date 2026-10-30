# -*- coding: utf-8 -*-
"""pytest 全局配置与测试辅助。

只提供一个辅助函数 `patch_ctrl`，供所有需要 patch WebApi 依赖的用例复用。

背景（为什么需要它）
--------------------
WebApi 的方法实现已物理拆分到 ``backend.controllers`` 的各个领域子模块
（base / device / commands / autorefresh / logcat / settings / apk /
deviceinfo / update / screenshot / record / perf / file）。每个子模块通过
``from backend.controller import X`` 拿到模块级名字的**副本**，方法运行时
查找的是子模块自己的全局命名空间。

因此测试里 ``monkeypatch.setattr("backend.controller.load_prefs", ...)``
只改了 ``backend.controller`` 这一个命名空间，子模块持有的副本纹丝不动，
patch 会静默落空（表现为「假件没生效、代码走了真实分支」这类难查的失败）。

`patch_ctrl` 统一把名字打到**所有引用它的子模块**以及 ``backend.controller``
本身，让拆分后的行为与单文件时代完全一致。用例侧只需要：

    patch_ctrl(monkeypatch, "load_prefs", lambda: {"save_dir": want})

注意：这里**只处理命名空间名字**。若 patch 的是被导入模块对象自身的属性
（如 ``monkeypatch.setattr(ctrl.updater, "check", ...)``、
``monkeypatch.setattr(ctrl.subprocess, "run", ...)``），由于所有模块共享同一个
对象，直接 patch 即可，无需本函数。
"""
import backend.controller as ctrl
from backend.controllers import (
    base, device, commands, autorefresh, logcat, settings, apk, deviceinfo,
    update, screenshot, record, perf, file,
)

# 所有承载 WebApi 方法的子模块（顺序即 WebApi 的 MRO 逆序，仅用于遍历）
_MIXIN_MODS = [base, device, commands, autorefresh, logcat, settings, apk,
               deviceinfo, update, screenshot, record, perf, file]


def patch_ctrl(monkeypatch, name, val):
    """把模块级名字同时 patch 到所有引用它的 controllers 子模块与 controller。

    :param monkeypatch: pytest 的 monkeypatch 夹具（负责用例结束后自动回滚）
    :param name: 要替换的模块级名字，如 ``"load_prefs"``
    :param val: 替换后的对象（假函数 / 假类 / 常量值）
    :return: 是否至少命中一个子模块（False 通常意味着名字写错了，便于排查）
    """
    hit = False
    for mod in _MIXIN_MODS:
        if hasattr(mod, name):
            monkeypatch.setattr(mod, name, val)
            hit = True
    # controller 自身也打一份：部分名字只在其顶层被读取（如常量导出）
    monkeypatch.setattr(ctrl, name, val)
    return hit
