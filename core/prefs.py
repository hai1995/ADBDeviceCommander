# -*- coding: utf-8 -*-
"""
core.prefs —— 用户配置持久化（config.json，纯逻辑 headless 可测）
====================================================================
存放可跨会话记忆的**全部用户可配置项**（开关 / 过滤条件 / 保存路径等），
统一落在运行目录（exe 同目录）下的 config.json 里。用户拷走这一个文件，
就能在另一台电脑上同步全部设置。

文件从「打包那一刻」就存在：build.py 会把一份**默认值版** config.json 放进
dist/（与 exe 同目录），用户打开目录就能看到全部可配置项；运行时若文件
缺失（用户手删 / 开发态），ensure_prefs_file() 启动即按默认值补建一份，
之后每次启动都从这一个文件加载以往的设置。

配置项清单：
  * save_dir   默认保存目录（截图 / 录屏 / 下载，三页共享）
  * adb_dir    用户手动指定的 adb 所在目录（可为空 = 用系统 PATH）
  * shot_to_clipboard  截图后是否同步写入系统剪贴板（默认开启）
  * keep_input 设备指令输入框「保留输入内容」（默认开启）
  * cmd_filter 指令台搜索框的过滤关键字
  * cmd_order  指令台卡片的拖动排序结果（逗号分隔的命令 id；留空 = 按点击频次自动排）
  * cmd_timeout  单条命令的兜底超时秒数（默认 120；0 = 不限制，慎用）
  * builtin_folded  「内置」组内二级分组的折叠状态（逗号分隔的分组名；留空 = 全展开）
  * sidebar_collapsed  设备栏（已连接设备列表）收起状态（默认展开）
  * lc_keyword / lc_levels / lc_only_exc / lc_autoscroll / lc_buffer
               Logcat 实时监控的过滤条件（关键字 / 级别 / 仅异常 / 自动滚动 / 缓冲区）
  * lc_cap_zipstop / lc_cap_levels
               Logcat 落盘抓取（结束后打包 / 级别过滤）
  * rec_logcat / rec_zip / rec_pointer_location / rec_show_touches
               录屏各开关（设备音频 / 电脑麦克风 / 同步 logcat / 结束后打包 /
               指针位置 / 触摸圆点 / 同步 logcat 的级别过滤 / 录屏卡收起状态）
  * scrcpy_path  用户手动指定的 scrcpy 目录或可执行文件（留空 = 自动探测）
  * mirror_*     备用投屏的参数（播放器路径 / 分辨率 / 码率 / 预览帧率 /
                 预览区宽高 mirror_view_w / mirror_view_h，0 = 自适应）
  * perf_pkg / perf_pkg_all / perf_interval_ms / perf_metric / perf_thresholds
               性能监控的目标应用 / 采样间隔 / 图表当前指标 / 告警阈值表达式
  * wifi_port / wifi_recent
               无线调试的端口与最近连接过的地址（逗号分隔，最新在前）
  * apk_replace / apk_downgrade / apk_grant / apk_collapsed
               APK 安装的默认选项（覆盖 / 允许降级 / 授予全部权限）与安装卡收起态

跨设备同步的两条关键约定：
  * **旧文件自动迁移**：早期版本用 settings.json 存同样的内容。启动时若
    config.json 不存在而 settings.json 存在，则读旧文件 → 写入 config.json
    → 提示一次。旧文件保留不删（用户可自行比对 / 删除）。
  * **路径失效自动回退**：save_dir 存的是绝对路径，拷到另一台电脑上该路径
    通常不存在。此时本机改用默认目录（~/Pictures/ADB）并在状态栏提示，
    但**不把回退结果写回文件**——文件里的原值是源设备上的正确路径，
    回拷回去依然有效。详见 resolve_save_dir()。

安全防错（用户手改 json / 前端传错 / 文件损坏）：
  * 只读写 prefs_path()（exe 旁可编辑的那一份，恒不进 _MEIPASS 临时目录），
    JSON 损坏 / 不存在 / 只读时静默回退默认，绝不抛异常打断启动；
  * sanitize_prefs 逐字段做类型校验：已知键存在但类型 / 取值非法时回退该项
    默认值（例如 "keep_input": "yes" → True、lc_levels 含 "Z" → 全选），
    未知键原样保留（用户手改的自定义字段 / 未来版本字段不被抹掉）；
  * 「键缺失 = 用界面默认勾选」语义不变：sanitize 不替用户补写缺失键；
  * save_prefs 采用「读-合并-写」+ 临时文件原子替换，绝不整文件覆盖，
    写入前对 patch 同样跑 sanitize——前端误传也不会把文件写坏。

设计约定：默认值集中在 PREFS_DEFAULTS 一处，前端 HTML 的默认勾选与之对齐
（新增开关时两边同步改），避免「后端默认 False、界面默认勾选」的漂移。
"""
import os
import sys
import threading

from core.constants import PROJECT_ROOT, resource_path

# save_prefs 的「读-合并-写」整体互斥锁（见 save_prefs 的说明）。
# 模块级：所有调用方共用同一把，跨线程串行化写入。
_SAVE_LOCK = threading.Lock()

PREFS_FILE = "config.json"
# 早期版本（第三轮及以前）用的配置文件名。启动时若 config.json 缺失而本文件
# 存在，则自动迁移内容到 config.json（旧文件保留不删，仅作备份）。
LEGACY_PREFS_FILE = "settings.json"

# 本进程已前插到 PATH 的 adb 目录（用于幂等与摘除）
_applied_adb_dir = None

# 合法日志级别（与 core.logcat / 前端级别复选框的 value 严格同集合）
VALID_LEVELS = ("V", "D", "I", "W", "E", "F")

# ---- 配置 schema：键 -> 默认值。缺失键不回填（走界面默认），非法值回退到此 ----
PREFS_DEFAULTS = {
    # 通用
    "save_dir": "",
    "adb_dir": "",
    "shot_to_clipboard": True,
    "keep_input": True,
    "cmd_filter": "",
    # 指令台卡片的手动排序（长按拖动后落盘）：逗号分隔的命令 id，按「先后」
    # 依次排列。只有被拖过的分组里的 id 会写进来 —— 没拖过的分组仍按点击
    # 频次自动排（常用靠前），不会因为顺手拖了一张卡就把自动排序整体冻住。
    "cmd_order": "",
    # 指令台「内置」组的二级分组折叠状态：逗号分隔的分组名（连接与投屏 /
    # 显示辅助 / 按键 / 屏幕状态 / 网络 / 应用与信息）。留空 = 全部展开。
    # 与 cmd_order 同一套「逗号串」约定：多值存成一个字符串，读写都不用
    # 处理嵌套结构，手改 config.json 也不容易写坏。
    "builtin_folded": "",
    # 单条命令的兜底超时（秒）。命令序列里任何一条读 stdin 的工具（裸
    # powershell / cmd、`adb logcat` 之类）都会永久占住执行锁，后续命令全部
    # 排队 —— 界面表现就是「卡死、点不动」。0 = 不限制（自己清楚某条要跑很久
    # 时才这么设，代价是这条出错后再也没有自动放行）。
    "cmd_timeout": 120,
    # 设备栏（已连接设备列表）收起状态：侧边栏折叠，内容区让出宽度
    "sidebar_collapsed": False,
    # Logcat 实时监控
    "lc_keyword": "",
    "lc_levels": list(VALID_LEVELS),
    "lc_only_exc": False,
    "lc_autoscroll": True,
    "lc_buffer": "",
    # Logcat 落盘抓取
    "lc_cap_zipstop": True,
    "lc_cap_levels": list(VALID_LEVELS),
    # 录屏（指针位置 / 触摸圆点默认开启：回顾操作过程时最直观。
    # rec_logcat / rec_zip 自 v2026.1028 起也改为**默认开启**：
    # 「录一段能复盘的屏」本来就要带日志、也要打包成 zip，绝大多数用户不会去关它，
    # 默认关着等于每次都要手动勾两下。老配置文件里的 false 由
    # _migrate_rec_defaults() 一次性翻转（见那里的说明）。
    "rec_logcat": True,
    "rec_zip": True,
    "rec_pointer_location": True,
    "rec_show_touches": True,
    # 工具页三张卡各自的收起态：开关项多、占屏太高，收起后只留一行标题。
    # 分开存（不是一个大布尔）：用户常常长期收起「投屏」却天天用「录屏」。
    "shot_collapsed": False,
    "rec_collapsed": False,
    "scrcpy_collapsed": False,
    "apk_collapsed": False,
    # 无线调试（Wi-Fi ADB）：
    #   wifi_port    上次用的连接端口（默认 5555；adb tcpip 换过端口的话记住它）
    #   wifi_recent  最近连接过的地址，逗号分隔、最新在前（最多 5 条）
    # 地址只是「上次连过」的快捷入口，不含任何凭证；设备 IP 变了点一下重连即可。
    "wifi_port": 5555,
    "wifi_recent": "",
    # APK 安装选项（工具页「应用安装」卡）：默认覆盖安装 —— 测试时反复装同一个
    # 包是常态，不勾 -r 每次都要先卸载，反而多一步还容易打断正在跑的用例。
    # 允许降级 / 授予全部权限都**默认关闭**：前者会静默覆盖设备上的更高版本，
    # 后者给被测应用开全部运行时权限，可能掩盖权限相关的缺陷。
    "apk_replace": True,
    "apk_downgrade": False,
    "apk_grant": False,
    # 诊断包（一键收集设备信息 / 日志尾部 / 进程 / 应用 / ANR）：
    #   diag_with_logcat   是否包含 logcat 尾部（默认包含：排障时最常要的就是它）
    #   diag_logcat_lines  尾部行数（默认 2000 ≈ 300 KB 文本，压缩后几十 KB）
    #   diag_collapsed     诊断卡收起态
    "diag_with_logcat": True,
    "diag_logcat_lines": 2000,
    "diag_collapsed": False,
    # 投屏：用户手动指定的 scrcpy 目录 / 可执行文件（空 = 自动探测）
    "scrcpy_path": "",
    # 备用投屏（没装 scrcpy 时用）：播放器路径、分辨率、码率、低帧率预览帧率。
    # mirror_size 留空 = 按设备分辨率自动缩到长边 1080。
    "mirror_player_path": "",
    "mirror_size": "",
    "mirror_bitrate": 8,
    "mirror_fps": 2,
    # 预览区大小（工具页内嵌那张截图）：0 = 自适应（CSS 限制长边 280px）。
    # 用户拖动右下角手柄后按像素记住，下次投屏还原成同样大小。
    "mirror_view_w": 0,
    "mirror_view_h": 0,
    # 性能监控（CPU / 内存 / FPS / 电量 / 温度）
    #   perf_pkg      目标应用包名（留空 = 自动跟随前台应用）
    #   perf_interval_ms 采样间隔（毫秒，夹在 200~10000）
    #   perf_metric   图表当前展示的指标（cpu / mem_used / pss / fps / jank / batt / temp）
    #   perf_thresholds 告警阈值表达式，形如 "fps<45,jank>8,temp>42,cpu>85"
    #                 留空 = 用内置基线；"off" = 关闭全部告警；写几段就只判几段
    #                 （覆盖式：删掉一段等于关掉这条）。界面上改阈值也落到这里。
    "perf_pkg": "",
    # perf_pkg_all 「应用包名」下拉框是否连系统应用一起列出来（默认只列第三方：
    #                性能测试盯的是被测 App，几百个系统应用只会稀释搜索结果）
    "perf_pkg_all": False,
    "perf_interval_ms": 1000,
    "perf_metric": "cpu",
    "perf_thresholds": "",
    # 版本更新（见 core/update.py）
    #   update_check            启动后自动检查新版本（默认开：这是「不想手动问同事
    #                           现在该用哪版」的唯一出路；关掉后仍可在关于页手动查）
    #   update_feed             更新源地址。留空 = 用 core.update.FEED_URL（GitHub
    #                           Releases）。内网部署时改成自建 version.json 地址，
    #                           字段只要 version / notes / url 三个即可。
    #   update_skipped_version  点过「跳过此版本」的版本号：同版本不再自动弹窗
    #                           （手动检查仍会如实显示，否则用户以为检查坏了）
    "update_check": True,
    "update_feed": "",
    "update_skipped_version": "",
}

# 数值型键的合法范围（含端点）：越界 / 非数字一律回退默认，避免手改 config.json
# 时把码率写成 0、把帧率写成 100 把机器压垮（帧率 100 等于每 10ms 抓一次截图）。
INT_RANGES = {
    "mirror_bitrate": (1, 50),      # Mbps：1M 够看文字，50M 已是 USB 的上限
    "mirror_fps": (1, 10),          # 低帧率预览：再高只会白烧 CPU 与 adb 带宽
    # 预览区大小：0 = 自适应；上限按 2K 屏留量，拖过头也不会写出一个比屏幕还大
    # 的尺寸（那种窗口下次启动会横跨整个桌面，用户很难再拖回来）
    "mirror_view_w": (0, 2400),
    "mirror_view_h": (0, 2400),
    "perf_interval_ms": (200, 10000),  # 性能采样间隔：一次采样本身要 200~400ms
    # 命令兜底超时：下限 5s（低于这个值连 `adb install` 都跑不完，等于天天误杀），
    # 上限 1 小时（再长就没有兜底的意义了，不如显式设 0 关掉）
    "cmd_timeout": (0, 3600),
    # 无线调试端口：1024 以下是系统保留端口（非 root 绑不上），65535 是上限
    "wifi_port": (1024, 65535),
    # 诊断包 logcat 行数：下限 100（再少没有排障价值），上限与 core.diag 的
    # MAX_LOGCAT_LINES 一致（5 万行 ≈ 7 MB，压缩后 1~2 MB，能随手发出去）
    "diag_logcat_lines": (100, 50000),
}

# 旧版键名 → 新键名（录屏「指针显示」从 screenrecord --show-pointer 参数改为
# 系统设置 pointer_location overlay，键随之改名）。加载时迁移一次：
# 用户显式关掉过指针显示的话，升级后不应发现设置悄悄复位。
_KEY_MIGRATION = {
    "rec_show_pointer": "rec_pointer_location",
}

# 一次性迁移标记键：rec_logcat / rec_zip 的**旧默认值**是 False，历史配置文件里
# 也就真实地写成了 false。这两项改成「默认开启」后，只改 PREFS_DEFAULTS 是没用
# 的——文件里那个 false 仍然胜出，升级后界面看起来毫无变化。故加载时翻转一次，
# 并把标记写进文件；标记存在就不再翻转：用户之后手动关掉，不会被下次启动又打开。
REC_DEFAULTS_FLAG = "rec_defaults_on"
REC_DEFAULTS_KEYS = ("rec_logcat", "rec_zip")

# 布尔型键（type(x) is bool 或 0/1 均可；字符串 "true" 等一律按非法回退默认，
# 避免把用户手写的 "false" 字符串在 Python 里当成真值——这正是防错要拦的）
BOOL_KEYS = frozenset(k for k, v in PREFS_DEFAULTS.items()
                      if isinstance(v, bool))
STR_KEYS = frozenset(k for k, v in PREFS_DEFAULTS.items()
                     if isinstance(v, str))
LEVEL_LIST_KEYS = frozenset(k for k, v in PREFS_DEFAULTS.items()
                            if isinstance(v, list))
# 数值型键（bool 是 int 的子类，必须先被 BOOL_KEYS 认领，故这里显式排除）
INT_KEYS = frozenset(k for k, v in PREFS_DEFAULTS.items()
                     if isinstance(v, int) and not isinstance(v, bool))


def _as_int(v, default, lo, hi):
    """宽松整数转换：只认 int / 纯数字字符串，且必须落在 [lo, hi]。

    手改 config.json 时最常写成 "8"（带引号）——直接 int() 又不是不行，
    但 "8M" 这类会抛异常；一律用 str 化后再判纯数字，既不误收也不抛错。
    """
    n = v
    if isinstance(v, str):
        s = v.strip()
        n = int(s) if s.isdigit() else None
    if isinstance(n, bool) or not isinstance(n, int):
        return default
    if n < lo or n > hi:
        return default
    return n


def default_prefs() -> dict:
    """全部配置项 + 默认值的一份新 dict（列表值深拷贝，改它不污染 schema）。

    两个使用方共用同一来源，杜绝「模板与 schema 漂移」：
      * build.py 打打包时生成 dist/ 旁的默认 config.json；
      * ensure_prefs_file() 在启动时补建缺失的配置文件。
    """
    out = {}
    for k, v in PREFS_DEFAULTS.items():
        out[k] = list(v) if isinstance(v, list) else v
    return out


def default_prefs_json() -> str:
    """默认配置的 JSON 文本（缩进 2、ensure_ascii=False、结尾换行）。

    序列化格式只此一处定义：build.py 生成的模板文件与运行时补建的配置文件
    必须字面一致，否则用户比对两份文件时会以为少了几项。
    """
    import json
    return json.dumps(default_prefs(), ensure_ascii=False, indent=2) + "\n"


def _as_bool(v, default):
    """宽松布尔转换：只认真 bool 与 0/1，其余（含 "true"/"yes" 字符串）回退默认。

    手改 config.json 时最常写错的就是把 true 写成带引号的 "true" ——
    非空字符串在多数语言里都是真值，用户写 "false" 反而得到开启，故一律不认。
    """
    if isinstance(v, bool):
        return v
    if isinstance(v, int) and not isinstance(v, bool) and v in (0, 1):
        return bool(v)
    return default


def _as_levels(v, default):
    """日志级别列表：必须是由 V/D/I/W/E/F 组成的列表（空列表 = 一个都不要，
    是合法值，不能回退）。非法（字符串 / 含未知级别 / 非列表）回退默认。"""
    if not isinstance(v, list):
        return default
    picked = [x for x in v if isinstance(x, str) and x in VALID_LEVELS]
    if len(picked) != len(v):
        return default        # 含非法元素：整项回退，不静默吞掉用户的选择
    # 去重并按 V/D/I/W/E/F 固定序返回（前端勾选顺序无关紧要，落序稳定便于比对）
    return [lv for lv in VALID_LEVELS if lv in set(picked)]


def sanitize_prefs(raw):
    """校验并清洗偏好字典，返回 (clean, warnings)。

    clean：已知键逐个过类型校验（非法 → PREFS_DEFAULTS 的默认值）；
    未知键原样保留（不抹掉用户手改内容 / 未来版本字段）。
    warnings：被纠正的键的可读说明（供启动时提示用户，不致命）。
    """
    if not isinstance(raw, dict):
        return {}, ["config.json 内容不是对象，已全部恢复默认"]
    clean = dict(raw)          # 先整体拷贝：未知键天然保留
    warnings = []
    for k, dv in PREFS_DEFAULTS.items():
        if k not in clean:
            continue           # 缺失 = 界面默认，不替用户补写
        v = clean[k]
        if k in BOOL_KEYS:
            nv = _as_bool(v, dv)
            if nv is not v:
                clean[k] = nv
                warnings.append("%s 的值 %r 不是有效的开关，已恢复为 %s"
                                % (k, v, "开" if nv else "关"))
        elif k in STR_KEYS:
            if not isinstance(v, str):
                clean[k] = dv
                warnings.append("%s 的值 %r 不是文本，已恢复为 %r" % (k, v, dv))
        elif k in LEVEL_LIST_KEYS:
            nv = _as_levels(v, dv)
            if nv != v:
                clean[k] = nv
                warnings.append("%s 的级别选择 %r 含无效项，已恢复为 %r"
                                % (k, v, nv))
        elif k in INT_KEYS:
            lo, hi = INT_RANGES.get(k, (0, 1 << 30))
            nv = _as_int(v, dv, lo, hi)
            if nv != v:
                clean[k] = nv
                warnings.append("%s 的值 %r 不是 %d~%d 的数字，已恢复为 %r"
                                % (k, v, lo, hi, nv))
    return clean, warnings


def prefs_path() -> str:
    """config.json 的落盘路径：恒为「exe 同目录 / 开发态工程根」那一份。

    刻意**不走** resource_path() 的 _MEIPASS 回退：config.json 是全部用户
    数据里唯一允许写入的文件，而 _MEIPASS 是 PyInstaller 每次运行解压出来
    的临时目录——读写它意味着「设置改完、重启即丢」，且毫无异常可查
    （最坏的一种 bug）。因此它只以「同目录可编辑文件」的形式存在：
    build.py 负责把默认副本放进 dist/，启动时 ensure_prefs_file() 补建，
    save_prefs() 原子覆盖。**它也从不被打进 exe 内部**（build.py 的
    BUNDLED_DATA 刻意不含它），见那里的注释。
    """
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(os.path.abspath(sys.executable)),
                            PREFS_FILE)
    return os.path.join(PROJECT_ROOT, PREFS_FILE)


def legacy_prefs_path() -> str:
    """旧版 settings.json 的路径（仅用于一次性迁移，迁移后不再读写）。"""
    return resource_path(LEGACY_PREFS_FILE)


def ensure_prefs_file() -> str:
    """config.json 缺失时按默认值补建一份（已存在则原样不动），返回其路径。

    解决「程序目录里根本没有配置文件」：build.py 会在 dist/ 放一份默认
    config.json，但用户可能手动删掉它、或从源码直接跑（开发态工程根没有
    该文件）。启动时补建后，load/save 始终有同一个文件可依——设置才能
    「每次启动都加载以往的」。

    写入与 save_prefs 同规格：临时文件 + os.replace 原子替换，绝不在半途
    留下截断的 JSON。**尽力而为**：exe 装在只读目录（Program Files 无管理员
    权限等）时静默失败——此时行为与从前完全一致（首次改动设置时才由
    save_prefs 尝试创建），不因补建失败打断启动。

    注意：只写「同目录 / 工程根」这一份，绝不解包临时目录（_MEIPASS）——
    写进去重启即丢，详见 prefs_path() 的说明。
    """
    p = prefs_path()
    if os.path.exists(p):
        return p
    tmp = p + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(default_prefs_json())
        os.replace(tmp, p)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
    return p


def load_prefs() -> dict:
    """读取全部偏好（已过 sanitize 校验）。文件缺失 / 损坏 / 非对象 JSON
    一律回退空 dict（= 全部走界面默认）。

    按 utf-8-sig 读：Windows 记事本「另存为 UTF-8」会写入 BOM，而
    `json.load(encoding="utf-8")` 遇 BOM 直接抛 JSONDecodeError —— 一个 BOM 就能让
    用户所有的偏好悄悄失效（退回默认值）。utf-8-sig 同时兼容无 BOM 的普通 UTF-8。
    """
    prefs, _w = load_prefs_checked()
    return prefs


def _migrate_keys(raw):
    """旧键名迁移（见 _KEY_MIGRATION）：新键缺失时才沿用旧值，并删掉旧键。

    放在 sanitize **之前**：迁移过来的值仍要过类型校验（用户把旧键手写成
    "false" 字符串时，新键会按非法值回退默认，而不是把字符串当真值）。
    """
    raw = dict(raw)
    for old, new in _KEY_MIGRATION.items():
        if old in raw:
            if new not in raw:
                raw[new] = raw[old]
            del raw[old]
    return raw


def _atomic_write(prefs: dict) -> bool:
    """把整份偏好原子写入 config.json（临时文件 + os.replace）。

    `open(path, "w")` 会先把原文件截断：此刻若进程崩溃 / 断电 / 磁盘写满，
    config.json 就变成空文件或半截 JSON，下次启动 save_dir / adb_dir / 各开关
    全部悄悄回到默认值，用户毫无察觉。所有写入路径（save_prefs / 一次性迁移）
    都必须走这里，不允许各处自己 open。

    临时文件用**唯一名**（pid + 随机串）而不是固定的 `config.json.tmp`：
    两个线程同时落盘时（设置保存 / 记住上次无线地址 / 录屏选项回写可能并发），
    固定名会让两个写入流互相截断对方的临时文件，os.replace 之后文件内容可能
    是「半份 A + 半份 B」的坏 JSON。唯一名让每次写入各写各的，谁先 replace
    谁生效，最后完成的那个的完整内容胜出。
    """
    import json
    import uuid
    p = prefs_path()
    tmp = "%s.%s.tmp" % (p, uuid.uuid4().hex[:8])
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(prefs, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
        return True
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False


def _migrate_rec_defaults(clean, warnings):
    """把「同步录制 logcat」「结束自动压缩 zip」的老 false 一次性翻成默认开启。

    只在标记键缺失时执行（老配置文件 / 首次运行），执行后标记写入文件；
    之后用户手动关掉，标记已在，不会再被翻回来。写盘失败（只读目录）时
    仅本次生效，下次启动会再翻一次——但值本来就是我们想要的默认值，无害。
    """
    if clean.get(REC_DEFAULTS_FLAG) is True:
        return clean, warnings
    flipped = [k for k in REC_DEFAULTS_KEYS if clean.get(k) is False]
    for k in flipped:
        clean[k] = True
    clean[REC_DEFAULTS_FLAG] = True
    _atomic_write(clean)
    if flipped:
        warnings = list(warnings) + [
            "录屏的「同步录制 logcat」「结束自动压缩为 zip」已改为默认开启"
            "（如不需要可在录屏卡里关掉）"]
    return clean, warnings


def _read_json_file(path):
    """读一个 JSON 文件并返回 dict；文件缺失 / 损坏 / 非对象一律返回 None。"""
    try:
        with open(path, encoding="utf-8-sig") as f:
            import json
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _migrate_legacy_file():
    """旧版 settings.json → config.json 的一次性迁移。

    只在 config.json **不存在**而 settings.json 存在时触发（绝不覆盖用户
    已有 的新文件）。迁移后旧文件保留不删：它是用户升级前的配置备份，
    删掉就再也回不去了（且拷到别的电脑上时可能还靠它还原）。

    返回迁移后的 dict（迁移失败返回 None）。
    """
    p_new = prefs_path()
    if os.path.exists(p_new):
        return None            # 已有新文件：什么都不做
    p_old = legacy_prefs_path()
    if not os.path.exists(p_old):
        return None
    data = _read_json_file(p_old)
    if not data:
        return None
    clean, _w = sanitize_prefs(_migrate_keys(data))
    try:
        import json
        tmp = p_new + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p_new)
    except Exception:
        try:
            if os.path.exists(p_new + ".tmp"):
                os.remove(p_new + ".tmp")
        except Exception:
            pass
        return None
    return clean


def load_prefs_checked():
    """同 load_prefs，但额外返回被纠正字段的说明列表（供启动时提示用户）。

    返回 (prefs, warnings)。文件缺失 / 损坏时 warnings 为空（无内容可纠正）。
    旧版 settings.json 存在而 config.json 不存在时，自动迁移并给出提示。
    """
    p = prefs_path()
    if not os.path.exists(p):
        migrated = _migrate_legacy_file()
        if migrated is not None:
            return migrated, ["已从旧版 settings.json 迁移到 config.json"
                              "（旧文件保留为备份，可自行删除）"]
    data = _read_json_file(p)
    if data is None:
        if not os.path.exists(p):
            return {}, []
        # 文件在但读不出来（损坏 / 顶层不是对象）
        try:
            with open(p, encoding="utf-8-sig") as f:
                import json
                json.load(f)
        except FileNotFoundError:
            return {}, []
        except Exception:
            return {}, []
        return {}, ["config.json 顶层不是对象，已全部恢复默认"]
    clean, warnings = sanitize_prefs(_migrate_keys(data))
    return _migrate_rec_defaults(clean, warnings)


def default_save_dir() -> str:
    """内置默认保存目录（未配置 / 配置不可用时的兜底）。

    放在 core 而非 controller：controller 与 core/prefs 都可能需要它，
    放在这里避免两处各写一份公式（两份必然漂移）。
    """
    return os.path.expanduser(os.path.join("~", "Pictures", "ADB"))


def resolve_save_dir(prefs=None, default=None, ensure_dir=False):
    """判定本机实际可用的保存目录，返回 (目录, 提示文案)。

    背景：config.json 里的 save_dir 是**绝对路径**，用户把它拷到另一台
    电脑上同步设置时，那个路径在新电脑上通常根本不存在（比如源机是
    C:\\Users\\张三\\Pictures\\ADB，新机用户名不同）。若照原样使用，
    截图/录屏会往一个不存在的路径写，用户以为"同步成功了"实则全丢。

    规则：
      * 未配置（空串）→ 用默认目录，无提示；
      * 配置的目录存在且可写 → 直接用，无提示；
      * 配置的目录**不存在** → 本机改用默认目录，并给出一条提示；
      * 配置的目录存在但不可写 → 同上（提示措辞区分）。

    ensure_dir=True 时（用户在本机界面里新填目录的场合）会先尝试把目录
    建出来再建：用户新填的路径本就不存在，这是正常流程，不该回退。
    跨设备带来的失效路径走 ensure_dir=False —— 那条路径在新机上多半
    建不出来（父目录不存在 / 无权限），与其建一个诡异的同名目录，
    不如改用默认目录并说清楚。

    关键：**不把回退结果写回配置文件**。文件里的原值是源设备上的正确
    路径，用户回拷到源机器时仍然有效；只有在本机界面里改写才会落盘。

    返回的提示文案为 None 表示一切正常。
    """
    if default is None:
        default = default_save_dir()
    if prefs is None:
        prefs = load_prefs()
    raw = prefs.get("save_dir")
    if not isinstance(raw, str) or not raw.strip():
        return default, None
    cfg = raw.strip()
    if not os.path.isdir(cfg) and ensure_dir:
        try:
            os.makedirs(cfg, exist_ok=True)
        except OSError:
            pass
    if os.path.isdir(cfg):
        if os.access(cfg, os.W_OK):
            return cfg, None
        return default, ("配置里的保存目录不可写，已改用默认目录：%s" % default)
    return default, ("配置里的保存目录在本机不存在，已改用默认目录：%s" % default)


def get_pref(key, default=None):
    """读单个偏好项（已过校验），缺失 / 文件损坏时返回 default。

    给「默认开启」这类开关用：config.json 里没写过该键时算默认，
    只有用户显式关掉（写入 false）后才不生效。
    """
    v = load_prefs().get(key)
    return default if v is None else v


def save_prefs(patch: dict) -> dict:
    """合并写入偏好，返回合并后的完整 dict（patch 先过 sanitize，
    前端误传 / 手改都不会把文件写坏）；失败时返回现有内容（尽力而为）。

    写入走 _atomic_write（临时文件 + os.replace），见那里的截断风险说明。
    读取同时兼容带 BOM 的文件（记事本另存为 UTF-8 会写 BOM）。

    **读-改-写必须整体持锁**：界面保存设置（save_settings）、记住上次无线地址
    （_wifi_remember）、录屏选项回写可能来自不同线程。没有这把锁时，两处几乎
    同时进来会各自读到同一份旧内容、各自合并、后写的把先写的**整块覆盖掉**
    —— 表现就是「刚改的开关过一会儿自己弹回去了」，且极难复现。
    """
    if not isinstance(patch, dict) or not patch:
        return load_prefs()
    # patch 同样清洗：非法值纠正后再合并（而不是原样写进文件）
    clean_patch, _w = sanitize_prefs(patch)
    with _SAVE_LOCK:
        prefs = load_prefs()
        prefs.update(clean_patch)
        _atomic_write(prefs)
        return prefs


def apply_adb_dir(adb_dir, env=None) -> bool:
    """把 adb 所在目录前插到进程 PATH；返回是否已让 PATH 里出现该 adb。

    adb_dir 支持两种写法：目录（...\\platform-tools）或 adb.exe 全路径
    （README 承诺的「程序里填 adb.exe 绝对路径」）。目录无效/为空返回 False，
    并且会摘除上一次前插的目录（配置从有到无时恢复原 PATH）。
    """
    global _applied_adb_dir
    if env is None:
        env = os.environ
    # 先处理换配置/清空：把旧的前插目录摘掉
    if _applied_adb_dir is not None:
        cur = env.get("PATH", "")
        marker = _applied_adb_dir + os.pathsep
        if cur.startswith(marker):
            env["PATH"] = cur[len(marker):]
        _applied_adb_dir = None

    if not adb_dir or not str(adb_dir).strip():
        return False
    d = str(adb_dir).strip().strip('"')
    if not d:
        return False
    # 兼容直接填 adb.exe / adb 的完整路径
    if os.path.isfile(d) and os.path.basename(d).lower() in ("adb.exe", "adb"):
        d = os.path.dirname(d)
    if not os.path.isdir(d):
        return False
    cur = env.get("PATH", "")
    marker = d + os.pathsep
    if not cur.startswith(marker):
        env["PATH"] = marker + cur
    _applied_adb_dir = d
    return True
