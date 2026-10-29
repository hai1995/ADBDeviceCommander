# -*- coding: utf-8 -*-
"""
core —— 纯逻辑层
=================
不依赖任何 UI（tkinter / ttkbootstrap / pywebview 均不在此层 import），
可被 Web 版、CLI、测试任意复用。

模块划分：
  constants   常量、正则、状态翻译、格式化、路径解析等纯函数
  commands    快捷命令归一化 / 加载（运行目录 commands.json 多文件合并去重）
  shell       持久 PowerShell 会话（ShellSession）
  logcat      logcat 行分类规则（供监控与抓取共用）
  devices     设备列表解析与增量 diff 决策

说明：本包是 Web 版（pywebview + backend/*）的共享逻辑底座，无 Tk 依赖。
"""
