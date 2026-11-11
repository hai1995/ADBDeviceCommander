"""
core —— 纯逻辑层
=================
不依赖任何 UI（tkinter / ttkbootstrap / pywebview 均不在此层 import），
可被 Web 版、CLI、测试任意复用。

模块划分：
  constants         常量、正则、状态翻译、格式化、路径解析等纯函数
  commands          快捷命令归一化 / 加载（运行目录 commands.json 多文件合并去重）
  builtin_commands  程序内置的通用快捷命令（49 条，用户同名命令优先）
  prefs             config.json 读写 / 类型防错 / PATH 注入 / 保存目录回退
  shell             持久 PowerShell 会话（ShellSession）
  logcat            logcat 行分类规则（供监控与抓取共用）
  devices           设备列表解析与增量 diff 决策
  clipboard         PNG 写系统剪贴板（可选 numpy 加速）
  imgbytes          图片字节归一化（跳过前导杂字节、按签名裁剪）
  wireless          无线调试地址校验 / 设备 IP 提取 / adb 输出解析
  apk               APK 安装参数拼装与失败码中文翻译
  devinfo           设备信息一次取全
  diag              诊断包收集与打包
  rootguard         adb root 切换识别与设备 root 状态查询
  tmpfiles          系统临时目录遗留副本清理
  update            版本检查（网络请求通过注入的 opener 执行）
  win_theme         Windows 原生标题栏深色适配
  envcheck          启动前环境预检

说明：本包是 Web 版（pywebview + backend/*）的共享逻辑底座，无 UI 依赖。
"""
