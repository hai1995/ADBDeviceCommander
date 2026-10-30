# -*- coding: utf-8 -*-
"""
core.builtin_commands —— 程序内置的「通用」快捷命令（与用户 quick_commands.json 解耦）。

设计动机
--------
旧版把所有命令（含大量可移植的通用 adb / 设备指令）都堆在 quick_commands.json 里，
其中又混入了许多**个人/项目专属**内容（固定路径 D:\\BUG、写死的 android-sdk 路径、
车机账号密码、VIN 码、J01/CEI 等项目指令）。两类混在一起，既不通用、也不好维护。

本模块把「任意装有 adb 的机器都能用、不依赖个人路径/凭据」的命令抽离为**程序内置默认**，
打包进 exe，保证即使 quick_commands.json 为空/损坏，工具也自带一套常用通用指令。

与用户自定义的关系（优先级）
----------------------------
core.commands.load_commands 在加载用户 quick_commands.json 后与本列表合并：
  * 同名（去掉 [标签] 前缀后的核心名相同）—— 用户已有一份，内置被压制，避免重复显示；
  * 同 id —— 用户的精确覆盖内置（便于用户改写某条内置）；
  * 其余内置补齐。
因此「用户自定义优先」，内置只是兜底默认；带个人路径/密码/项目专属的指令仍应留在
用户的 quick_commands.json 里（本模块刻意不包含它们）。
"""
# 每条均为 normalize_commands 产出的归一化格式：
#   {"id", "name", "labels", "commands": [{"command", "delay"}], "clickCount", "builtin"}
# labels 统一为 ["内置"]：内置命令在界面上独立成一个标签组，并恒排在所有
# 用户命令分组的最下方（见 frontend/js/app.js renderCmdGroups 的排序），
# 避免兜底默认命令混在用户自己的分组里干扰查找。
# section 是「内置」组内的二级分组（连接与投屏 / 显示辅助 / 按键 / 屏幕状态 /
# 网络 / 应用与信息）：49 条平铺在一行里要横跨两三屏，分组后一次只看一类。
# 刻意不复用 labels —— labels 决定一级分组和顶部标签过滤条，把六个细分塞进
# 标签条只会让「通用 / 常用 / 内置」被内置命令的细分淹掉。二级分组顺序由
# 前端常量 BUILTIN_SECTIONS 决定（这里只写归属，不写次序）。
BUILTIN_COMMANDS = [
    {
        "id": "bi.adb-status", "name": "ADB连接状态", "labels": ["内置"], "section": "连接与投屏",
        "clickCount": 0, "builtin": True,
        # 标记用纯 ASCII 的 [OK]/[NO]：会话管道的编码是系统区域默认（中文 Windows
        # 为 cp936），✅/❌ 这类字符编码不进 GBK，会被 errors="replace" 换成 "?"，
        # 状态行变成「[2026-…] ? ADB设备已连接」，一眼看不出是成功还是失败。
        "commands": [{"delay": 100, "command":
            '''while($true){ $t=Get-Date -Format "yyyy-MM-dd HH:mm:ss"; $d=adb devices | Select-String "device$"; if($d){ Write-Host "[$t] [OK] ADB设备已连接" -ForegroundColor Green; $d | ForEach-Object { Write-Host "- $($_.Line.Split()[0])" -ForegroundColor Cyan } }else{ Write-Host "[$t] [NO] 未检测到ADB设备" -ForegroundColor Red }; Start-Sleep 2 }'''}]},
    {
        "id": "bi.scrcpy", "name": "Scrcpy投屏", "labels": ["内置"], "section": "连接与投屏",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command": "scrcpy"}]},
    {
        "id": "bi.current-activity", "name": "获取当前 Activity", "labels": ["内置"], "section": "应用与信息",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command":
            'adb shell dumpsys window | findstr "mCurrentFocus"'}]},
    {
        "id": "bi.kill-activity", "name": "杀掉当前 Activity", "labels": ["内置"], "section": "应用与信息",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command":
            r'''adb shell dumpsys window | sls mCurrentFocus | %{ if ($_ -match '(\S+)/') { adb shell am force-stop $Matches[1] } }'''}]},
    {
        "id": "bi.update-time", "name": "更新设备时间", "labels": ["内置"], "section": "应用与信息",
        "clickCount": 0, "builtin": True,
        "commands": [
            {"delay": 100, "command": "adb root"},
            {"delay": 1000, "command":
                '''$currentDate = Get-Date -Format "MMddHHmmyyyy.ss"; adb shell "date $currentDate"'''}]},
    {
        "id": "bi.wifi-priority", "name": "优先使用WIFI", "labels": ["内置"], "section": "连接与投屏",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command":
            "adb shell settings put global is_allow_apna_use_wifi 1"}]},
    {
        "id": "bi.pointer-on", "name": "开启指针位置", "labels": ["内置"], "section": "显示辅助",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command":
            "adb shell settings put system pointer_location 1"}]},
    {
        "id": "bi.pointer-off", "name": "关闭指针位置", "labels": ["内置"], "section": "显示辅助",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command":
            "adb shell settings put system pointer_location 0"}]},
    {
        "id": "bi.touch-on", "name": "开启触摸圆点", "labels": ["内置"], "section": "显示辅助",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command":
            "adb shell settings put system show_touches 1"}]},
    {
        "id": "bi.touch-off", "name": "关闭触摸圆点", "labels": ["内置"], "section": "显示辅助",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command":
            "adb shell settings put system show_touches 0"}]},
    {
        "id": "bi.reboot", "name": "重启设备", "labels": ["内置"], "section": "按键",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command": "adb reboot"}]},
    {
        "id": "bi.model-version", "name": "设备型号与系统版本", "labels": ["内置"], "section": "应用与信息",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command":
            "adb shell getprop ro.product.model; adb shell getprop ro.build.version.release; adb shell getprop ro.build.version.sdk"}]},
    {
        "id": "bi.screen-spec", "name": "屏幕分辨率与密度", "labels": ["内置"], "section": "应用与信息",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command":
            "adb shell wm size; adb shell wm density"}]},
    {
        "id": "bi.list-packages", "name": "列出全部应用包名", "labels": ["内置"], "section": "应用与信息",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command": "adb shell pm list packages"}]},
    {
        "id": "bi.tcpip", "name": "开启无线调试(5555)", "labels": ["内置"], "section": "连接与投屏",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command":
            '''adb tcpip 5555; Write-Host "已开启无线调试，请用 adb connect 设备IP:5555 连接" -ForegroundColor Green'''}]},
    {
        "id": "bi.serial", "name": "设备序列号", "labels": ["内置"], "section": "应用与信息",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command": "adb get-serialno"}]},
    {
        "id": "bi.wake-unlock", "name": "亮屏并上滑解锁", "labels": ["内置"], "section": "按键",
        "clickCount": 0, "builtin": True,
        # 必须用 224（KEYCODE_WAKEUP）而不是 26（KEYCODE_POWER）：26 是**电源开关**，
        # 屏幕本来就亮着时按下去等于熄屏，紧接着的上滑自然毫无效果 —— 命令名说「亮屏」，
        # 实际效果却是把屏幕关掉。224 只在熄屏时点亮，亮屏时是空操作。
        "commands": [
            {"delay": 100, "command": "adb shell input keyevent 224"},
            {"delay": 1000, "command": "adb shell input swipe 540 1800 540 600 300"}]},
    {
        "id": "bi.restart-adb", "name": "重启ADB服务", "labels": ["内置"], "section": "连接与投屏",
        "clickCount": 0, "builtin": True,
        "commands": [
            {"delay": 1000, "command": "adb kill-server"},
            {"delay": 1000, "command": "adb start-server"},
            {"delay": 1000, "command": "adb devices"}]},
    {
        "id": "bi.root-adb", "name": "root", "labels": ["内置"], "section": "连接与投屏",
        "clickCount": 0, "builtin": True,
        "commands": [
            {"delay": 0, "command": "adb root"}
        ]
    },
    {
        "id": "bi.remount-adb", "name": "remount", "labels": ["内置"], "section": "连接与投屏",
        "clickCount": 0, "builtin": True,
        "commands": [
            {"delay": 0, "command": "adb remount"}
        ]
    },

    # ------------------------------------------------------------------ #
    # 按键与屏幕：日常测试里最高频的一组（息屏/亮屏/三个导航键/音量）。
    # 全部用 input keyevent，不依赖 root、不改任何设置，点完即生效。
    # 注意 223/224（SLEEP/WAKEUP）与 26（POWER）的区别：26 是电源**开关**，
    # 亮屏时按下去等于熄屏；223 只在亮屏时熄屏、224 只在熄屏时点亮，
    # 各自都是单向操作，才不会出现「点了亮屏结果黑屏」。
    # ------------------------------------------------------------------ #
    {
        "id": "bi.screen-off", "name": "息屏", "labels": ["内置"], "section": "按键",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command": "adb shell input keyevent 223"}]},
    {
        "id": "bi.screen-on", "name": "亮屏", "labels": ["内置"], "section": "按键",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command": "adb shell input keyevent 224"}]},
    {
        "id": "bi.key-back", "name": "返回键", "labels": ["内置"], "section": "按键",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command": "adb shell input keyevent 4"}]},
    {
        "id": "bi.key-home", "name": "主页键", "labels": ["内置"], "section": "按键",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command": "adb shell input keyevent 3"}]},
    {
        "id": "bi.key-recents", "name": "多任务键", "labels": ["内置"], "section": "按键",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command": "adb shell input keyevent 187"}]},
    {
        "id": "bi.vol-up", "name": "音量加", "labels": ["内置"], "section": "按键",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command": "adb shell input keyevent 24"}]},
    {
        "id": "bi.vol-down", "name": "音量减", "labels": ["内置"], "section": "按键",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command": "adb shell input keyevent 25"}]},
    {
        "id": "bi.vol-mute", "name": "静音切换", "labels": ["内置"], "section": "按键",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command": "adb shell input keyevent 164"}]},
    {
        "id": "bi.home-desktop", "name": "回到桌面", "labels": ["内置"], "section": "按键",
        "clickCount": 0, "builtin": True,
        # 用隐式 Intent 起 HOME：不写死 launcher 包名，各家 ROM 都适用
        "commands": [{"delay": 100, "command":
            "adb shell am start -a android.intent.action.MAIN -c android.intent.category.HOME"}]},

    # ------------------------------------------------------------------ #
    # 屏幕状态与旋转：抓图 / 录屏前把画面「摆正」的一组。
    # stayon true 是「充电时不熄屏」，跑长脚本时最有用的一个开关。
    # ------------------------------------------------------------------ #
    {
        "id": "bi.stayon-on", "name": "充电时保持常亮", "labels": ["内置"], "section": "屏幕状态",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command": "adb shell svc power stayon true"}]},
    {
        "id": "bi.stayon-off", "name": "取消充电常亮", "labels": ["内置"], "section": "屏幕状态",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command": "adb shell svc power stayon false"}]},
    {
        "id": "bi.rot-portrait", "name": "锁定竖屏", "labels": ["内置"], "section": "屏幕状态",
        "clickCount": 0, "builtin": True,
        # 关掉重力感应再指定方向：只写 user_rotation 时，设备一转就被系统改回去
        "commands": [{"delay": 100, "command":
            "adb shell settings put system accelerometer_rotation 0; adb shell settings put system user_rotation 0"}]},
    {
        "id": "bi.rot-landscape", "name": "锁定横屏", "labels": ["内置"], "section": "屏幕状态",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command":
            "adb shell settings put system accelerometer_rotation 0; adb shell settings put system user_rotation 1"}]},
    {
        "id": "bi.rot-auto", "name": "恢复自动旋转", "labels": ["内置"], "section": "屏幕状态",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command":
            "adb shell settings put system accelerometer_rotation 1"}]},

    # ------------------------------------------------------------------ #
    # 网络开关：车机 / 手机测试里常要「断网复现」。
    # 飞行模式用 `cmd connectivity`（Android 11+）：直接写 settings 不会触发
    # 系统实际切换，还必须发广播，而广播需要额外权限；新接口一句话搞定。
    # ------------------------------------------------------------------ #
    {
        "id": "bi.airplane-on", "name": "开启飞行模式", "labels": ["内置"], "section": "网络",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command":
            "adb shell cmd connectivity airplane-mode enable"}]},
    {
        "id": "bi.airplane-off", "name": "关闭飞行模式", "labels": ["内置"], "section": "网络",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command":
            "adb shell cmd connectivity airplane-mode disable"}]},
    {
        "id": "bi.wifi-on", "name": "打开 WiFi", "labels": ["内置"], "section": "网络",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command": "adb shell svc wifi enable"}]},
    {
        "id": "bi.wifi-off", "name": "关闭 WiFi", "labels": ["内置"], "section": "网络",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command": "adb shell svc wifi disable"}]},
    {
        "id": "bi.data-on", "name": "打开移动数据", "labels": ["内置"], "section": "网络",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command": "adb shell svc data enable"}]},
    {
        "id": "bi.data-off", "name": "关闭移动数据", "labels": ["内置"], "section": "网络",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command": "adb shell svc data disable"}]},
    {
        "id": "bi.wlan-ip", "name": "查看 WLAN IP", "labels": ["内置"], "section": "网络",
        "clickCount": 0, "builtin": True,
        # 只筛 inet 行：`ip addr` 全量输出二三十行，找那一行 IP 很费眼
        "commands": [{"delay": 100, "command":
            "adb shell ip addr show wlan0 | Select-String 'inet '"}]},

    # ------------------------------------------------------------------ #
    # 性能与调试：判定「卡顿是应用还是系统」时的几把常用尺子。
    # 关动画是为了排除转场时间对启动耗时的影响，测完记得恢复。
    # ------------------------------------------------------------------ #
    {
        "id": "bi.anim-off", "name": "关闭系统动画", "labels": ["内置"], "section": "显示辅助",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command":
            "adb shell settings put global window_animation_scale 0; "
            "adb shell settings put global transition_animation_scale 0; "
            "adb shell settings put global animator_duration_scale 0"}]},
    {
        "id": "bi.anim-on", "name": "恢复系统动画", "labels": ["内置"], "section": "显示辅助",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command":
            "adb shell settings put global window_animation_scale 1; "
            "adb shell settings put global transition_animation_scale 1; "
            "adb shell settings put global animator_duration_scale 1"}]},
    {
        "id": "bi.kill-all", "name": "清理后台进程", "labels": ["内置"], "section": "应用与信息",
        "clickCount": 0, "builtin": True,
        # am kill-all 只杀「可安全回收」的后台进程，不动前台与常驻服务，
        # 比 force-stop 温和：清完还能接着测，不用重新拉起应用
        "commands": [{"delay": 100, "command": "adb shell am kill-all"}]},
    {
        "id": "bi.logcat-clear", "name": "清空 logcat 缓冲区", "labels": ["内置"], "section": "应用与信息",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command": "adb shell logcat -c"}]},
    {
        "id": "bi.battery", "name": "电池与温度信息", "labels": ["内置"], "section": "应用与信息",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command": "adb shell dumpsys battery"}]},
    {
        "id": "bi.storage", "name": "存储空间", "labels": ["内置"], "section": "应用与信息",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command": "adb shell df -h /data /sdcard"}]},
    {
        "id": "bi.meminfo", "name": "内存概况", "labels": ["内置"], "section": "应用与信息",
        "clickCount": 0, "builtin": True,
        # /proc/meminfo 有四十多行，只取前 6 行（总量 / 空闲 / 可用）够看
        "commands": [{"delay": 100, "command":
            "adb shell cat /proc/meminfo | Select-Object -First 6"}]},
    {
        "id": "bi.third-party", "name": "列出第三方应用", "labels": ["内置"], "section": "应用与信息",
        "clickCount": 0, "builtin": True,
        "commands": [{"delay": 100, "command": "adb shell pm list packages -3"}]},
]
