# -*- coding: utf-8 -*-
"""
backend —— Web 版服务层（pywebview 后端）
=========================================
职责：线程/进程调度、状态管理、与前端的事件通信。
不直接 import tkinter / ttkbootstrap；纯逻辑来自 core 包。

核心对象：
  bus.BackendBus    线程安全事件总线（Python -> 前端轮询拉取）
  controller.WebApi pywebview js_api 暴露给前端的统一动作入口
"""
