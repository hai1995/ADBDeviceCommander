# 修复说明

- **第一轮**：录屏启动失败（`screenrecord: unrecognized option '--show-pointer'`）。
- **第二轮**：录屏可视化语义修正 / 内置命令核实 / 配置持久化核实 / 剪贴板加固。
- **第三轮**（本文末「第三轮」一节）：状态信息抽离为顶栏跑马灯 + 点击弹窗。
- **第五轮**（本文末「第五轮」一节）：打包产物自带 `config.json`，配置从「打包那一刻」就可加载。
- **第六轮**（本文末「第六轮」一节）：「已连接设备」栏增加侧边栏收起 / 展开。
- **第十轮**（本文末「第十轮」一节）：性能监控增强——区间卡顿率曲线 / 多设备对比 / 阈值告警。
- **第十一轮**（本文末「第十一轮」一节）：阈值可配置 / 报告超标色带 / 多设备对比报告。
- **第十二轮**（本文末「第十二轮」一节）：指令卡长按拖动排序 / 应用包名下拉（模糊搜索 + 跟随前台 + 全系统）。
- **第十三轮**（本文末「第十三轮」一节）：曲线悬停提示 / 内置命令 21→49 条 / 投屏预览可拖大小 / 截图·录屏并排 / 标题栏配色。
- **第十四轮**（本文末「第十四轮」一节）：性能曲线区间框选统计（均值 / 最低 / P95 / 最高 / 超阈值次数）。
- **第十五轮**（本文末「第十五轮」一节）：内置命令分六组、可折叠、可搜索。
- **第十六轮**（本文末「第十六轮」一节）：修「序列里含 powershell / exit 导致整程序卡死」——裸子 shell 直通 + exit 复位 + 120 秒兜底超时。
- **第十七轮**（本文末「第十七轮」一节）：工具页改回竖排（三张卡各自可收起）/录屏 logcat 改全量（取消级别筛选）/ 撤掉未实现的音频与麦克风开关。
- **第十八轮**（本文末「第十八轮」一节）：无线调试（Wi-Fi ADB，含自动读设备 IP）/ APK 一键安装（批量 + 失败码中文解释）/ 设备信息快照（设备卡 ⓘ）。
- **第十九轮**（本文末「第十九轮」一节）：修快捷命令 ⋯ 菜单被下方按钮压住（整卡抬层 + 空间不足向上弹）/ 修车机截图「开头不是 PNG」导致剪贴板报「参数无效」。
- **第二十轮**（本文末「第二十轮」一节）：主动复查——APK 连点「假开始」、设备信息连点串台、BMP 弱签名误判、剩余空间显示 0.0 GB 等 9 处。
- **第二十一轮**（本文末「第二十一轮」一节）：接入 GitHub 源码推送（`tools/push_github.py`，token 不进版本库/不回显）；修「token 明文被打进源码包」；修两条恒真的打包测试断言。
- **第二十二轮**（本文末「第二十二轮」一节）：录屏自动分段续录 + 收尾**合并为一个完整 mp4**（`ffmpeg -f concat -c copy`，不重编码）；界面写明三个特殊点（拼接点约 1 秒画面缺失 / 依赖 ffmpeg / 上限 20 段）。
- **第二十三轮**（本文末「第二十三轮」一节）：设备指令页支持**多工作区**（子 tab，最多 8 个）——每套「指令台 + 指令输出」各有一条独立会话，可同时跑、输出互不串台；停止 / 清空 / 筛选都按工作区生效。
- **第二十四轮**（本文末「第二十四轮」一节）：录屏增加**取消**（停止并**删除**本次产物，不合并、不打包；不 pull 当前段、只删文件不删目录、删不掉要点名）；「约每 3 分钟自动分段」提示语沉到卡片**最下方**；写明 Win11 首次运行弹 SmartScreen「发布者未知」是**没签名**、不是缺东西。
- **第二十五轮**（本文末「第二十五轮」一节）：「取消」改用新增的**警示色** `.btn.warn`（琥珀，刻意不用红 —— 录制中的「停止」本身就是红块呼吸，同色等于没区分）；工作区 tab **双击改名**（或 F2），名字同时落 tab、`config.json`、后端登记三处；顺带修掉「重启恢复时自定义名没交给后端」与「改名后新建会撞名」。
- **第二十六轮**（本文末「第二十六轮」一节）：「停止 / 取消」更名为**「停止录制 / 取消录制」**；「取消录制」的二次确认从 `window.confirm` 换成**应用内自绘弹窗**（pywebview 各版本对 `confirm` 支持不一致，返回 undefined 时 `!confirm(...)` 恒真 —— 点了没反应、什么也不删，是最难自查的静默失败）；四个出口（否 / × / 遮罩 / Esc）全等于「否」，默认焦点在「否」。
- **第二十七轮**（本文末「第二十七轮」一节）：性能报告的七张曲线从自绘 SVG 换成**内联 ECharts**（十字准星 + 读数框 tooltip / 点图例隐藏 / 滚轮缩放）；**库内联进报告**以保断网双击可用（不走 CDN，断网空白属最坏静默失败）；曲线数据抽稀使 8000 点报告仍 < 1.2MB；缺库自动回退 SVG + 明示横幅。
- **第二十八轮**（本文末「第二十八轮」一节）：主动复查上一轮 —— 修**抽稀后时间戳乱序**（ECharts time 轴按数组顺序连线，乱序让曲线在每个桶里折返：图能出、形状错）；修**对比图超标红点超 400 时直接切片**（长会话后半段一个红点都没有，读者会得出「后半段全达标」的假结论）；**ECharts 初始化失败改为明示原因**（原来只剩 7 个空白块）；补 3 条回归用例。
- **第二十九轮**（本文末「第二十九轮」一节）：车机截图报「分辨率有问题」——**不是没 root**（`screencap` 普通 shell 权限即可）。真因是 `adb exec-out` 的 PNG 字节在个别 Windows adb / 车机上被换行转换，签名还认得、IHDR 的宽高与 CRC 已坏，旧实现照旧落盘成坏图。现在落盘前校验 PNG 头，坏头当场拒绝并给出 `adb shell screencap -p` + `adb pull` 的替代路径。
- **第三十轮**（本文末「第三十轮」一节）：把上一轮的「建议你手敲 adb pull」升级为**自动降级重试**（exec-out 坏 → 设备端落盘 + pull → 清理远端与 `.part`）；并新增 `adb shell echo` 探测，把**车机 shell 需要授权密码**（adbd 停在 `Password:`，所有命令都只是「没有输出」）与**定制系统收紧 shell 权限**、**USB 调试未授权**、**设备掉线**分开报——四种情况各有各的提示语，都不再说「截图失败」了事，也不再让人误以为是「没 root」。

---

# 第二轮：录屏可视化语义 / 内置命令 / 配置持久化 / 剪贴板

本轮针对你反馈的 4 个问题逐条处理。其中 **2 与 3 经代码核实，项目里本就已实现**
（附核实证据），真正改动的是 **1 与 4**。

---

## 1. 录屏「指针显示 / 触控显示」语义修正（已改）

### 你反馈的问题
两个开关的文字描述不对。正确的对应关系是：

| 开关 | 你指出的真实语义 | 改前实际实现 |
| --- | --- | --- |
| 指针显示 | `shell settings put system pointer_location 1` | 设备端 `screenrecord --show-pointer` |
| 触控显示 | `shell settings put system show_touches 1` | 已是系统设置，实现正确 |

### 为什么必须改
`--show-pointer` 是**设备端 screenrecord 的命令行参数**，只有 Android 10+
的部分二进制才认。定制 ROM / 云手机 / 模拟器上报的 SDK 与实际二进制可能
不一致（设备报 SDK 30、二进制却是不含该参数的老版本），传参即
`unrecognized option` 退出，**整场录屏启动即失败**——这正是你第一轮遇到的那句报错。
（第一轮曾用「usage 探测 + 去参重试」绕过，但那是在给一个语义本就错误的开关打补丁。）

### 改法
彻底删掉 `--show-pointer` 机制，两个开关统一走**系统设置 overlay**：

- 指针位置 → `settings put system pointer_location 1`
- 触摸圆点 → `settings put system show_touches 1`

两者都是屏幕 overlay，会被 screenrecord 原样录进视频，且**全 Android 版本可用**，
与录屏命令彻底解耦——可视化从此不可能再把录屏本身搞挂。

### 改动文件
- `backend/screen_service.py`：删除 `--show-pointer` 相关全部机制
  （`_supports_show_pointer` / `_rejected_show_pointer` / `start(show_pointer=…)`
  / 重试分支）；新增通用 `get_system_setting()` / `set_system_setting()`
  （`None` 或 `"null"` → `settings delete`，不留用户从未创建的条目）。
- `backend/controller.py`：`screen_record_start(..., pointer_location=True,
  show_touches=True)`；`_enable_show_touches` → `_enable_overlay(serial, key,
  prev_field)`；`_restore_show_touches` → `_restore_overlays(sess)`，遍历
  `pointer_location_prev` / `show_touches_prev` 两个备份表，三条收尾路径
  （停止 / 启动失败撤销 / 异常撤销）统一恢复。
- `frontend/index.html`：勾选框 id `rec-show-pointer` → `rec-pointer-location`，
  文案改为「指针位置（画面常驻准星，跟随触摸）」「触摸圆点（触摸时屏幕出圆点）」，
  说明文字点明是 `settings put system` 系统 overlay。
- `frontend/js/app.js`：5 处 `recShowPointer` → `recPointerLocation`
  （元素映射、下发、持久化列表、录屏中置灰）。
- `core/prefs.py`：偏好键 `rec_show_pointer` → `rec_pointer_location`，
  并加**旧键迁移表** `_KEY_MIGRATION`——你以前显式关掉过指针显示的话，
  升级后不会悄悄复位；新键已存在时以新键为准。

### 安全性
沿用「防错优先于功能完整」原则：读不到设备原值（adb 瞬断）时**不写设置、
也不恢复**，绝不把用户原来的 `0` 瞎删。

---

## 2. 内置命令：4 条本就存在（核实，非新增）

你要求的 4 条命令，项目里**已经实现**，位于 `core/builtin_commands.py`：

| 命令 id | 标题 | 实际命令 |
| --- | --- | --- |
| `bi.pointer-on` | `[内置] 开启指针位置` | `adb shell settings put system pointer_location 1` |
| `bi.pointer-off` | `[内置] 关闭指针位置` | `adb shell settings put system pointer_location 0` |
| `bi.touch-on` | `[内置] 开启触摸圆点` | `adb shell settings put system show_touches 1` |
| `bi.touch-off` | `[内置] 关闭触摸圆点` | `adb shell settings put system show_touches 0` |

命名沿用 electorm 惯例的「`xxx-on` / `xxx-off` + 中文标题」格式。
`merge_builtins` 会把它们并入 `quick_commands.json`，**「内置」组恒置最底**、
不与你的自定义命令混排；与你的同名命令冲突时以你的为准
（你的 `quick_commands.json` 里已有这 4 条同名命令，显示的是你的版本，功能一致）。

> 也就是说：这项无需改动，功能已具备。

---

## 3. 配置持久化：本就实现（核实，非新增）

你说的「这项功能还未实现」，实际代码里**整条链路都在**，并已端到端验证通过：

- `core/prefs.py`：`settings.json` 读写，`sanitize` 类型防错、原子写入、
  兼容 utf-8-bom；
- `frontend/js/app.js` 的 `applyBootSettings`：启动时把配置逐项下发到控件；
- 每个开关变更即时 `persistPref` → `save_settings` 落盘到 exe 旁的
  `settings.json`；下次启动 `boot()` 恢复。

**验证方式**：模拟一次「改配置 → 保存 → 重启 → 读回」，确认
`boot()` 下发 settings、`save_settings` 落盘、`load_prefs` 恢复全部字段，
包括本轮改名的 `rec_pointer_location`。

> 也就是说：这项无需改动。若你实际遇到过「重启后配置丢失」，请告诉我具体是
> 哪个开关——可能是 `settings.json` 写到了临时目录或被占用，请另行定位。

---

## 4. 剪贴板写入失败（已改）

### 你反馈的错误
> 复制到粘贴板失败：Windows 剪贴板写入失败（SetClipboardData 未接受该数据）

### 根因
`core/clipboard.py` 的 Windows 实现一次成不成即放弃：
`OpenClipboard` 成功 → `EmptyClipboard` 成功 → `SetClipboardData` 返回 NULL
→ 直接报错。而 `SetClipboardData` 失败在很多机器上是**短暂**的——第三方
程序正握着剪贴板：远程桌面会话（rdpclip 卡住）、安全软件 / 剪贴板历史工具
（Ditto、360、电脑管家）、Win10+ 云剪贴板同步。这些持有通常几百毫秒就松开。

### 改法（三层）
1. **整段序列重试 3 轮**：`开 → 清 → 投 → 关` 作为一整体重试，轮间退避
   0.1 / 0.2 秒（全程 < 1 秒，跑在后台线程，不卡界面）。
2. **PowerShell + .NET 兜底**：三轮全败则调
   `powershell -NoProfile -STA -Command "…[System.Windows.Forms.Clipboard]::SetImage(…)"`。
   这是**独立进程、另一条 API 路径**——我们进程被安全软件拦时常它能写进去；
   顺带补上 ctypes 路径只认 PNG 的短板（JPG/BMP 也能复制了）。
   用 `-STA` 是因为 .NET 剪贴板 API 要求单线程套户；带 `CREATE_NO_WINDOW`
   避免控制台窗口闪一下。
3. **错误提示写成人话**：说明常见原因（远程桌面 / 安全软件 / 剪贴板工具占用）
   并给出「重试截图或先手动复制一次内容」的可执行建议，不再只丢一句
   `SetClipboardData 未接受该数据`。

**注意**：截图本身**始终先落盘**，剪贴板失败只影响「直接粘贴」这一步，
状态栏会照旧提示图片已保存的位置。

---

## 验证

- 全量测试 **446 passed**。
- `tests/test_backend_screen.py`（24）：新增回归
  `test_start_never_passes_show_pointer_to_screenrecord`——断言录屏命令**严禁**
  再带 `--show-pointer`，且 `VideoRecorder.start` 签名里没有该参数；
  另覆盖 `settings get/put/delete` 三条路径与失败不冒泡。
- `tests/test_backend_controller.py`：overlay 备份/恢复用例改为
  `get_system_setting/set_system_setting`，「启动失败撤销」用例扩展为断言
  **两个 overlay 都要恢复**（否则你的设备会一直满屏准星）。
- `tests/test_core_prefs.py`：新增旧键迁移两个用例（旧键沿用到新键、新键优先）。
- `tests/test_core_clipboard.py`：新增三个用例——「首轮 `SetClipboardData`
  全败、第二轮放行 → 报成功」「ctypes 全败 → PowerShell 兜底成功
  （校验 `-STA` 与路径转义）」「全败时提示含远程桌面/安全软件字样」。
- 端到端复核：模拟「SDK 30 + 老 binary」的设备，录屏一次启动成功且不带
  `--show-pointer`；overlay 在停止 / 启动失败撤销两条路径均按原值恢复。

---

## 附：一轮修复的最终去向

一轮针对 `unrecognized option '--show-pointer'` 的临时方案（usage 探测 +
去参重试）已随本轮第 1 项**整体移除**——因为根因不是「参数不兼容」，
而是「用错了实现方式」。现在 `screenrecord` 命令行**不再携带任何可视化参数**，
可视化一律由系统设置 overlay 承担，从机制上杜绝同类失败。
---

# 第三轮：状态信息抽离为顶栏跑马灯 + 点击弹窗

## 你提的需求
把几个 tab 下各自的状态信息栏**抽离出来**，程序核心运行信息改成**滚动条**形式放在
**全局右上角**，**点击弹出弹窗**单独展示。

## 改动前的样子
上一轮已经把各 tab 里的状态栏合并成了「底部全局常驻面板」（`.status-bar`，高 200px，
占住内容区底部一条）。它有两个实际问题：
1. **长期占空间**：Logcat 实时监控视图、文件表格各少显示约 200px 的行；
2. **信息被淹没**：几百行状态里，用户想找的往往只是最近一两条，却要滚动一条
   200px 高的窄带。

## 现在的样子

| 位置 | 承载 |
| --- | --- |
| **顶栏右上角跑马灯** | 最近 6 条核心运行信息，横向滚动；左侧状态灯颜色跟随最新一条的语义（绿=成功 / 黄=警告 / 红=错误 / 青=提示）；右侧显示已积累行数 |
| **点击跑马灯 → 弹窗** | 全量历史（与原面板内容一致），可滚动、可框选、可「复制 / 清空」；`×` / `Esc` / 点背景都能关 |
| **底部** | **不再有任何常驻栏**，内容区整块让给内容 |

细节：
- **悬停即暂停**：鼠标移上去滚动停住（`animation-play-state: paused`），停下来读
  一行；移开继续滚。
- **无缝循环**：轨道里放**两份完全相同**的内容，整体左移 50% 正好接回起点，
  循环处不会出现内容跳变。
- **不无意义地飘**：只有内容宽于视口时才加 `.rolling`（JS 实测宽度后决定）；
  一条短状态就静止不动，不一直飘。
- **滚动时长按内容长度给**（约 46px/s，下限 14s）：短句滚得慢不晃眼，长句不至于
  等很久才看完。

## 实现要点
- **全局只此一份 DOM**：`#status` 直接住在弹窗里（`#status-modal` 内），关闭弹窗
  只是整块随弹窗隐藏。刻意**不做「搬进搬出」的 DOM 搬家**——那会在搬动过程中
  丢选区、打断尚未落地的渲染队列。跑马灯是它的「概览投影」：另用一个轻量数组
  `statusLog` 镜像最近状态（上限与 DOM 侧 `CONSOLE_MAX_LINES` 一致），刷新按
  220ms 节流，避免一批命令回显瞬间重排几十次 DOM。
- **原有行为零回归**：状态行照旧走 `pushLine` 的 rAF 批量插入与 3000 行裁剪；
  「复制」按钮的连点保护、清空事件、toast 规则、`output_queue_bounded` /
  `file_no_device_guard` / `status_copy_flash` 等既有用例依赖的 `#status .line`
  与 `getElementById("status")` 全部保持不变。
- **ESC / 背景点击关闭**：状态弹窗是随时要回看的监控面板，比内容弹窗更常用，
  误开后必须零成本关掉。

## 顺带修掉的两处「陈年欠账」
上一轮改名（`rec_show_pointer` → `rec_pointer_location`）时，前端 jsdom 测试
因为环境里没装 jsdom 从未真正跑过，留下两个仍按旧命名断言的用例。装了 jsdom
后第一次全量运行即暴露：`rec_visual_toggles`（还在找 `rec-show-pointer`）与
`settings_persist`（还在断言 `rec_show_pointer`）。两个文件已同步到新命名与新文案，
现在分别 25 / 56 全过。

## 验证
- 新增 `tests/frontend/status_ticker_modal.test.cjs`（25 项全过），覆盖：
  结构改法本身（HTML 已无 `.status-bar`、`#status` 在弹窗内）、状态行仍只有一份
  DOM、跑马灯内容与语义灯、计数、弹窗三路径开关（`×` / `Esc` / 背景）、
  清空后回到空态、滚动仅在超宽时启用、两份轨道内容一致。
- 前端全量 37 个测试文件全部通过；Python 全量 **446 passed**。

## 测试脚手架里踩到的两个坑（顺手记一笔）

1. **静默吞错导致测试进程永久挂起**：`rec_visual_toggles` 这类用例里有
   `process.on("unhandledRejection", () => {})`，本意是忽略无害的异步拒绝，
   结果把断言里抛出的 `TypeError` 也一起吞了——async IIFE 中途夭折，
   末尾的 `process.exit()` 永远不执行，而 jsdom 的 `pretendToBeVisual: true`
   会持续喂定时器，进程就再也退不出去了（实测两次各挂 15 分钟无任何输出）。
   修法：给该文件加 30 秒看门狗，超时按当前失败计数强制退出；断言本身
   仍用 try/catch 计数。修完后前端全量从「永远跑不完」变成 **37 文件 0 失败、
   86 秒**。教训：静默兜底必须带日志或看门狗，否则「静默失败」会伪装成
   「测试卡住」，极难定位。
2. **样式类白名单要跟着新控件更新**：`ui_style_card_tabs` 有一条断言是
   「所有 `button` 都必须命中既定的样式类集合」，用来防止出现没被样式化的
   裸按钮。跑马灯按钮 `.ticker` 刻意没有做成 `.btn` 的按键块（它是胶囊形的
   信息载体，不是操作按钮），但它同样是已样式化的控件，因此把 `ticker`
   加入了允许列表并加了注释说明意图——而不是把按钮硬改成 `.btn` 形状来
   迁就断言。

## 视觉验证
用 Chromium headless（`--headless=new --virtual-time-budget`）对注入假
`window.pywebview` 事件的桩页面实拍两张图确认：
- 跑马灯条正常横向滚动，两端渐隐遮罩生效，行数计数在右，**底部已无任何
  常驻栏**，内容区延伸到底部；
- 弹窗「状态信息 STATUS」标题、说明、复制/清空/× 按钮齐全，全量历史带
  语义色（绿/黄/红/青），四角括号仪器风格保留。


---

# 第四轮：配置统一为可编辑的 config.json（跨设备同步）

## 你提的需求
把程序**所有**开关、过滤条件、保存路径等设置，都落到运行目录下一个可编辑的
配置文件（`config.json`）里，便于在不同设备之间同步设置。

## 改前 / 改后
| | 改前 | 改后 |
| --- | --- | --- |
| 配置文件名 | `settings.json` | **`config.json`**（旧文件自动迁移，保留为备份） |
| 覆盖范围 | 20 项（缺 `cmd_filter`） | **21 项**（新增指令台搜索关键字） |
| 跨设备可用性 | **不可用**：绝对路径在新机不存在就直接写坏目录 | **可用**：路径失效自动回退默认目录 + 明确提示，配置文件原值不动 |
| 配置位置 | 用户得自己找 | 「关于」页直接显示绝对路径 + 「打开目录」一键定位 |

## 三个关键设计决策

### 1. 旧 `settings.json` → `config.json` 自动迁移
启动时若 `config.json` 不存在而 `settings.json` 存在：读旧文件 → 写入
`config.json` → 提示一次「已从旧版 settings.json 迁移到 config.json」。

- **旧文件保留不删**：它是用户升级前的配置备份，删了就再也回不去；
- **只在 `config.json` 缺失时触发**：绝不用旧文件覆盖用户已有的新文件；
- 旧文件损坏时静默跳过（不迁移、不报错、不打断启动）。

### 2. 路径失效自动回退（这是「跨设备同步」真正的难点）
`save_dir` 是**绝对路径**。源机上的 `C:\Users\OD-HUANGHAI\Pictures\ADB`
拷到另一台电脑后该路径根本不存在。若照原样使用，程序会往一个不存在的路径
里写文件——用户以为「同步成功了」，实际截图/录屏全丢，且毫无察觉。

规则（`core.prefs.resolve_save_dir()`）：
- 未配置 → 用默认目录（`~/Pictures/ADB`），无提示；
- 目录存在且可写 → 直接用，无提示；
- 目录**不存在** → 本机改用默认目录 + 状态栏 `⚠ 配置里的保存目录在本机不存在，
  已改用默认目录：…`；
- 目录存在但不可写 → 同样回退（措辞区分）。

**关键：回退结果绝不写回配置文件。** 文件里的原值是源设备上的正确路径，
回拷回去依然有效；写回就等于把用户的配置改坏了。

### 3. 「用户新填的目录」与「同步来的失效路径」区别对待
两者都是「目录不存在」，但性质完全不同：

| 场景 | 处理 | 理由 |
| --- | --- | --- |
| 用户在本机界面里新填 | **自动创建**并直接生效（`ensure_dir=True`） | 新填的路径本就不存在，这是正常流程，不该回退 |
| 从别的电脑同步来的 | **回退默认目录** + 提示 | 那条路径在新机多半连父目录都没有，建出来是个诡异的同名目录 |

### 4. 补齐遗漏项
`cmd_filter`（指令台搜索关键字）此前完全不落盘——它可是标准的「过滤条件」，
换台电脑继续用同一个关键字才有意义。新增落盘 + 回填（回填后立即重跑过滤，
界面与实际结果一致）+ 清空时同步清空（否则用户会以为没清掉）。

## 改动清单
| 文件 | 改动 |
| --- | --- |
| `core/prefs.py` | `PREFS_FILE` → `config.json`；新增 `LEGACY_PREFS_FILE`；新增 `_migrate_legacy_file()` / `legacy_prefs_path()` / `default_save_dir()` / `resolve_save_dir(prefs, default, ensure_dir)`；schema 增 `cmd_filter` |
| `backend/controller.py` | boot 下发 `config_path` / `save_dir_effective` / `save_dir_note`；`_default_save_dir()` 改走回退逻辑；`save_settings()` 回报 `_save_dir_effective` / `_save_dir_note`；新增 `config_info()` API |
| `frontend/index.html` | 关于页新增「配置文件」区块（路径 + 打开目录按钮 + 说明） |
| `frontend/js/app.js` | `cmd_filter` 落盘（400ms 防抖）与回填；显示配置路径；保存目录变更即时提示回退；「打开目录」按钮 |
| `frontend/css/app.css` | `.cfg-path` / `.about-note` 样式（长路径可断行、按钮推到行尾） |
| `build.py` / `tools/package.py` | 分发排除名单加 `config.json`（旧 `settings.json` 也保留排除） |

## 验证
- `tests/test_core_prefs.py`：**36 通过 / 1 跳过**（跳过的是 root 环境
  「只读目录不可写」断言——root 能写只读目录）。新增 10 例覆盖：改名、旧文件
  迁移 / 不覆盖新文件 / 损坏不迁移、路径存在 / 不存在 / 空 / 不可写四种分支、
  **回退不写回配置文件**、`cmd_filter` 落盘与类型校验。
- `tests/test_backend_controller.py`：**76 通过**。新增 4 例：boot 下发配置
  路径与回退提示、`_default_save_dir` 走回退、`save_settings` 回报生效目录、
  `config_info` 返回路径与提示。
- `tests/test_build.py`：源码包排除 `config.json` 与 `settings.json`。
- `tests/frontend/settings_persist.test.cjs`：**61 通过**。新增 4 组：
  `cmd_filter` 落盘、配置路径展示、路径失效提示上状态栏、`cmd_filter` 回填。
- 全量：Python **460 passed / 1 skipped**；前端 **37 个测试文件 0 失败**。
- Chromium headless 实拍「关于」页确认：配置文件路径正常显示、「打开目录」按钮
  在行尾且间距正常、说明文字完整、顶栏跑马灯同步显示路径失效提示。

## 踩到的一个坑
视觉验证时用 `Proxy` 做的假 pywebview 桥，`hasApi()` 判定始终为 false，
页面停在「未检测到 pywebview」遮罩上——`Proxy` 的 get 陷阱在 headless
环境下与该判定不兼容。换成**普通对象**（显式列出各 api 方法）后立刻正常。
教训：做 headless 视觉验证桩时别用 Proxy 代理整个 api，直接写普通对象最稳。

---

# 第五轮：打包产物自带 config.json（配置从「打包那一刻」就可加载）

## 你提的问题
运行 `build.py` 生成程序之后，产物里**没有** `setting.json` 这样的配置文件，
希望能有这些文件来记录程序的各项配置信息，以便后续每次启动都能加载以往的设置。

## 核实结论：运行时链路本就齐全，缺的是「打包时把文件带上」

逐层核实后，「改配置 → 落盘 → 重启 → 恢复」这条链路的每一环都在：

- `core/prefs.py`：`config.json` 读写（sanitize 防错 / 原子写 / BOM 兼容 /
  旧 `settings.json` 自动迁移）；
- `backend/controller.py`：`boot()` 把 settings 随 `booted` 下发，前端回填控件；
  各控件 change 即 `save_settings` → `save_prefs` 落盘；
- `frontend/js/app.js`：`applyBootSettings` 回填 + `persistPref` 即时落盘。

**真正的断点只有一个**：`build.py` 从不把 `config.json` 放进 `dist/`——
`SIDE_FILES` 现为空（`使用说明` 已移入程序内「关于 → 使用说明」，不再随包分发），
`BUNDLED_DATA` 也不含 `config.json`。于是打好的程序目录里没有任何配置文件：
用户看不到有哪些项可配，「设置记忆」也要等第一次改动某个开关才由 `save_prefs`
悄悄创建文件——
观感上正是「这程序没有配置文件、不保存设置」。

## 改法（三层，缺一不可）

### 1. build.py 现生成默认 config.json 进 dist/（`ensure_default_config()`）
- 默认值取自 `core.prefs.PREFS_DEFAULTS`——**schema 的单一来源**，不另存
  模板文件（两份必然漂移：模板少一个键，用户就少一项可配）；
- **绝不覆盖已存在的 config.json**：dist/ 里那份可能是用户调好的设置，
  重打包不能打回默认值（与可覆盖的 `quick_commands.json` 区别正在此——
  前者随源码分发以工程版本为准，后者是用户数据以用户版本为准）；
- 工程根下的 `config.json` 是开发者个人配置（含本机绝对路径），因此
  **生成而非拷贝**，源码分发包的排除规则原样保留。

### 2. config.json 绝不被打进 exe 内部（防「重启即丢」陷阱）
一旦它进 `BUNDLED_DATA`，同目录那份缺失时 `resource_path()` 会回退返回
`_MEIPASS` 里的内置副本——而 `_MEIPASS` 是每次运行解压的临时目录，
`save_prefs` 写进去**重启即丢**：设置看似保存成功、下次启动全部复位，
且毫无报错（最坏的 bug 形态）。因此 `core/prefs.py` 的 `prefs_path()`
也改为**恒返回 exe 同目录 / 工程根那一份**，不走 `_MEIPASS` 回退分支，
从代码层钉死这个不变量（两侧均有回归断言）。

### 3. 启动时补建（`ensure_prefs_file()` → `main._ensure_config_file()`）
用户可能手动删掉 config.json，或从源码直接跑（工程根没有该文件）。
启动即按默认值补建一份（临时文件 + 原子替换，只读目录等失败时静默跳过，
不打断启动），此后 load/save 始终有同一个文件可依。

## 改动清单
| 文件 | 改动 |
| --- | --- |
| `core/prefs.py` | 新增 `default_prefs()` / `default_prefs_json()` / `ensure_prefs_file()`；`prefs_path()` 改为恒取 exe 同目录那份（不进 `_MEIPASS`）；模块 docstring 同步 |
| `build.py` | 新增 `ensure_default_config()` 并在 `main()` 发布收尾调用；产物表加 `config.json` 行；`BUNDLED_DATA` 处注释说明为何刻意不含它 |
| `main.py` | 新增 `_ensure_config_file()` 并于启动早期调用；`_apply_user_adb_dir` docstring 里过时的 `settings.json` 表述改为 `config.json` |
| `README.md` / `使用说明.txt` | 分发表 / 关键约定 / 配置持久化段落 / 第八节补充「dist 自带默认 config.json、删了会重新生成」 |
| `tests/test_core_prefs.py` | 新增 7 例：默认值深拷贝、JSON  roundtrip、补建 / 不覆盖 / 原子写 / 只读静默失败、`prefs_path` 不进 `_MEIPASS` |
| `tests/test_build.py` | 新增 5 例：生成默认模板、不覆盖用户设置、config.json 不进 BUNDLED_DATA/SIDE_FILES、主流程发布进 dist、主流程保留已有配置 |

## 验证
- `tests/test_core_prefs.py` + `tests/test_build.py`：**82 passed / 1 skipped**
  （跳过的仍是 root 环境「只读目录不可写」老用例）。
- Python 全量：**472 passed / 1 skipped**（本轮新增 12 例）。
- 前端：`settings_persist.test.cjs` **61 通过**；全量 **37 个测试文件 0 失败**
  （本轮未改前端，仅回归确认）。
- 主流程实测：桩掉 PyInstaller 跑 `build.main()`，`dist/` 内如期出现
  `ADB设备指令台.exe` + `quick_commands.json` + **`config.json`**（内容 =
  `PREFS_DEFAULTS` 全量默认值）；预置一份 `{"save_dir": "D:\\kept"}` 后
  重打包，内容原样保留。

---

# 第六轮：「已连接设备」栏侧边栏收起 / 展开

## 你提的需求
为「已连接设备列表」区块增加一个**侧边栏展开、收起**的功能。

## 设计

| 状态 | 表现 |
| --- | --- |
| 展开（默认） | 280px 设备栏 + 分隔条 + 内容区，与从前完全一致 |
| 收起 | 整栏缩为 **38px 窄轨**：只留展开按钮（»）与**设备数徽章**（一屏几台设备，收起也看得到）；分隔条同步隐藏（拖着 38px 的轨没有意义）；内容区吃满宽度 |
| 再次展开 | 恢复**收起前**的栏宽——用户用分隔条拖过的宽度原样还回，没拖过则回 CSS 默认 |

入口是设备栏标题前的 **« / »** 按钮（`aria-expanded` 随状态翻转，键盘可操作）。
收起状态落盘 `config.json` 的 `sidebar_collapsed`，下次启动保持。

> 第七轮已把这 38px 窄轨美化为 48px「仪器脊柱」（竖排铭牌 / 数字徽章 /
> 点轨展开），见下文；内联宽度存回等机制原样沿用。

## 两个实现要点（都是踩过的坑位）

### 1. 内联 width 与 class 规则的优先级打架
分隔条拖动写的是 `style.width`（**内联**），会压过一切 class 规则。所以收起时
JS 先把内联值存下来再清掉，让 `.main-row.sidebar-collapsed .device-sidebar`
（ specificity 0-3-0，压过 `.device-sidebar` 的 0-1-0）生效；展开时原样还回。
**不能图省事直接给内联写 38px**（第七轮轨宽改 48px 后同理）——`reclampSplitters()` 会在窗口缩放时把它钳回
最小值 200px，表现为「缩放一下窗口，设备栏又弹开了」（测试 [5] 守着这个回归）。

### 2. 状态挂在行容器上，与重钳逻辑解耦
`sidebar-collapsed` class 挂在 `.main-row` 而非设备栏自身：宽度类规则要压过
`.device-sidebar` 需要更高特异性，同时「当前是否收起」对 `reclampSplitters()`
透明——收起态内联宽度为空，`parseFloat("")` 为 NaN，重钳自然跳过，无需在
重钳流程里加特判。

## 改动清单
| 文件 | 改动 |
| --- | --- |
| `frontend/index.html` | 标题前加 `#btn-sidebar-collapse` 按钮；标题文字包一层 `.sidebar-title-text`（收起时只藏文字、留徽章） |
| `frontend/css/app.css` | 新增 `.main-row.sidebar-collapsed` 一组规则（窄轨 / 藏分隔条 / 藏列表与标题文字 / 留徽章）+ 按钮样式 |
| `frontend/js/app.js` | `applySidebarCollapsed()` / `sidebarCollapsed()`；bindUI 绑点击；`applyBootSettings` 回填（`persist=false`，回填不反向写盘） |
| `core/prefs.py` | schema 新增 `sidebar_collapsed`（默认 False） |
| `tests/test_core_prefs.py` | 布尔键映射表新增显式豁免名单 `_NO_HTML_CHECKBOX_KEYS`（按钮切换类开关无复选框可对齐）；新增落盘 + 类型校验用例 |
| `tests/frontend/sidebar_collapse.test.cjs` | **新增 28 项**：静态结构 / CSS 规则、点击切换与落盘、内联宽度存回、缩放不弹开、boot 回填不写盘、非法值不回填 |
| `README.md` / `使用说明.txt` | 功能说明 + 配置清单补充 |

## 验证
- `tests/frontend/sidebar_collapse.test.cjs`：**28 通过 / 0 失败**。
- Python 全量：**473 passed / 1 skipped**（新增 1 例）。
- 前端全量：**38 个测试文件 0 失败**（新增 1 个文件；既有
  `layout_resizable` / `ui_layout_fixes` / `settings_persist` 等布局与设置用例
  全部保持通过——分隔条拖动、窄栏换行、设置持久化均无回归）。

---

# 第七轮：收起态窄轨美化（「这折叠后的样式有点丑」）

## 你提的问题
第六轮的收起态截图：38px 窄轨里只有一个裸奔的文字小按钮（»）和挤成一团的
「N 台」徽章，其余是整条没有任何引导的空格——功能有了，但像个没做完的半成品。

## 改法（视觉 + 交互各三条）

**视觉**
1. **轨宽 38 → 48px**：徽章只留数字后仍显挤，48px 给方块钮与数字徽章各自留出
   呼吸距，竖排标签也立得住；
2. **竖排铭牌**：标题文字不再一藏了之，`writing-mode: vertical-rl` 竖排成
   「已连接设备」五个字，配 `margin-top:auto` 钉在轨底、上压一发丝线——
   窄轨从「空盒」变成「贴着铭牌的仪器脊柱」，栏收了身份还在；
3. **» 钮方块化**：28px 定宽定高、surface-2 底、发丝边、等宽字体，悬停点
   磷光青 + 3px 柔光晕——与面板主强调色同一套语言；整轨 hover 时底色轻抬
   一档（surface → surface-2），提示「这一条都是可点的」。

**交互**
4. **整轨热区**：收起态下点窄轨任意空白 / 徽章 / 竖排标签都能展开（cursor
   pointer + title 提示）。实现是 aside 上的 click 委托，**必须跳过按钮目标**
   ——否则点 « 收起时冒泡回来又立刻展开，按钮「失灵」（测试 [8] 双向后死守）；
5. **计数拆数字 + 单位**：`#dev-count` 只管数字，「台」是独立 `.count-unit`，
   收起态 `display:none`——徽章从「N 台」挤成一团变成干净的等宽数字；0 台时
   徽章整体隐藏（`:has(.count-num:empty)`，不支持的引擎退化为旧版空 pill）；
6. **head 撑满轨高**：列表隐藏后头部 `flex:1` 吃满高度，钮在顶、铭牌在底的
   纵向编排才成立（收起态头部不再留 `border-bottom`——没有列表要分隔）。

## 改动清单
| 文件 | 改动 |
| --- | --- |
| `frontend/index.html` | 计数徽章拆 span；注释同步新形态 |
| `frontend/css/app.css` | 重写 `.main-row.sidebar-collapsed` 规则组（上文 1/2/3/6）+ `.count:has(.count-num:empty)` |
| `frontend/js/app.js` | `renderDevices` 数字/单位分离；`applySidebarCollapsed` 挂轨 title；bindUI 点轨展开委托 |
| `tests/frontend/sidebar_collapse.test.cjs` | 38px→48px、「标题文字隐藏」→「竖排标签」、新增单位隐藏 / 钮方块化 / 铭牌贴底断言、新增 [8] 点轨展开用例（28 → 38 项） |
| `README.md` / `使用说明.txt` | 38px → 48px 与新设计描述（本文档第六轮的历史记载原样保留，演进以本轮为准） |

## 验证
- 前端全量：**38 个测试文件 0 失败**（本文件 38 通过）。
- Python 全量：**473 passed / 1 skipped**（本轮未改后端，回归确认）。
- Chromium 视觉实测：两态截图 + 窄轨特写逐项核对（轨宽 48、» 钮 28×28 居中、
  徽章纯数字、竖排标签贴底、点轨展开、点按钮不被顶回、0 台空徽章隐藏）。

---

# 第七轮：截图提速 + 重要通知全局 toast

本轮处理你反馈的两个问题：**① 截图整体响应偏慢，能否优化；② 截图完成 /
录屏完成 / Logcat 抓取完毕等重要通知应有全局 toast，用户感知明显**。

先说结论：截图的耗时大头在**设备端采集 + USB 传输**（`exec-out screencap -p`
已是最快路径），PC 侧真正能抠的是「剪贴板解码」与「反馈链路」两段，本轮都改了。

## 1. 截图提速（三处，按收益排序）

### 1.1 剪贴板 PNG 解码走向量化（最大头）

`core/clipboard.py` 的 `decode_png` 要给 Windows 剪贴板同时投 CF_DIB + CF_PNG，
其中 CF_DIB 需要把 PNG 解成 BGRA 像素。原实现是**纯 Python 逐字节还原 PNG
filter**，注释自述「1080x2400 约 1~2 秒」——开着「同步至粘贴板」（默认开）时，
这笔钱排在写盘之后、成功提示之前，是「点完截图干等」的最大单一因素。

改法（`requirements.txt` 新增**可选**依赖 numpy，装了才生效）：

- `_unfilter` 拆为 `_unfilter_py`（原实现，逐字节）+ `_unfilter_np`（向量化）：
  - filter 1 (Sub)：PNG 规范的 Sub 递推 `recon[x] = raw[x] + recon[x-bpp]`
    本质是**按 bpp 通道分组的前缀累加**，`cumsum` 一步算完整行；
  - filter 2 (Up)：整行加一行（uint8 溢出回绕即 `& 0xFF`）；
  - filter 0 (None)：整行拷贝；
  - filter 3/4 (Average/Paeth)：行内逐字节递推，**没有 C 层原语可向量化**，
    仍逐字节（`_filter_row_avg_paeth`）——一张图里 0/1/2 通常占多数。
- `_bgra_bottom_up` 同样拆双路径：通道换位 + 行翻转整图一步完成。
- 优先级：Pillow（若可导入）> numpy > 纯 Python；三者输出**逐字节一致**，
  `tests/test_core_clipboard.py` 用「同一输入对拍 + 独立参考实现」锁死。

本地基准（1080x2400 RGBA，随机数据）：filter 0/1/2 为主的图 **2.2 倍**
（沙箱快机器；办公慢机器上 Python 层开销占比更高，收益更明显）。

### 1.2 「已保存」反馈提前，不再被剪贴板解码阻塞

`_do_screenshot` 原来串行做：截图 → 写盘 → 解 PNG 投剪贴板 → 才推状态。
用户看到「✓ 已保存截图」要等剪贴板那 1~2 秒。现在**写盘后立即推「已保存」
toast**，剪贴板就绪后再补一条「✓ 已复制到粘贴板」状态（失败 warn 文案不变）。
图已落盘这个事实不再等任何外部资源。

### 1.3 反馈链路两处小提速

- `boot()` 后台预热 `adb start-server`（幂等、失败静默）：server 冷启一次
  数百毫秒，不该由「启动后第一次截图」承担；
- 前端事件轮询空闲退避 **1s → 500ms**：完成 toast 的出现延迟直接由轮询间隔
  决定，1s 档下「点完截图干等一秒才见提示」的体感明显（有事件时仍 400ms，
  空闲 2 次/s 空轮询的 CPU 开销可忽略）。

## 2. 重要通知全局 toast

原有 toast 只覆盖错误级与个别警告。本轮把**关键完成事件**补齐（切到任何
tab 都不错过）：

| 事件 | 行为 | 位置 |
| --- | --- | --- |
| 截图完成（单设备） | 「✓ 已保存截图: <路径>」toast，写盘后即弹 | `controller._do_screenshot` |
| 截图完成（多设备批量） | 各 worker 只记数，**全部到齐后弹一条汇总**（成功/失败计数 + 保存目录），不刷屏 | `controller._shot_batch_done` |
| 录屏完成 | 收尾（拉片/合成/打包）后弹一条汇总：有 zip 报 zip 路径，否则报文件数 + 目录 | `controller._screen_record_stop_locked` |
| Logcat 抓取完毕 | 未打包：stopped 事件弹「N 行 · 大小 → 文件名」；已打包：zipped 弹「已打包」，stopped 不再重复（新增 `packaged` 字段二选一） | `logcat_service` + `app.js onLogcatCapture` |

## 改动清单
| 文件 | 改动 |
| --- | --- |
| `core/clipboard.py` | numpy 可选加速：`_unfilter`/`_unfilter_np`/`_unfilter_py`/`_filter_row_avg_paeth`、`_bgra_bottom_up`/`_bgra_bottom_up_np`/`_bgra_bottom_up_py`；Pillow 产出也包 ndarray 走向量化 |
| `requirements.txt` | 新增可选依赖 numpy（注释说明可选与收益） |
| `backend/controller.py` | boot 预热 adb server；截图完成 toast + 批量汇总；「已保存」先于剪贴板反馈；录屏完成汇总 toast（`_session_teardown` 返回 (files, zip_path)） |
| `backend/logcat_service.py` | stopped 事件新增 `packaged` 字段（前端据此跳过重复 toast） |
| `frontend/js/app.js` | 轮询空闲退避 1s→500ms；`onLogcatCapture` 抓取完毕/已打包 toast |
| `tests/test_core_clipboard.py` | 新增 4 个对拍用例（numpy vs 纯 Python：全 filter、RGB/RGBA、unfilter/bgra 分函数） |
| `tests/test_backend_controller.py` | 新增 5 个用例（单设备 toast、反馈顺序、批量汇总一条、失败汇总、录屏完成 toast） |
| `tests/test_backend_logcat.py` | 两个既有用例补 `packaged` 字段断言 |
| `tests/frontend/logcat_capture_toast.test.cjs` | 新增前端用例（stopped/zipped toast、packaged 不重复） |
| `README.md` | 轮询间隔、numpy 依赖说明、toast 规则、截图链路提速设计要点 |

## 验证
- Python 全量：**482 passed / 1 skipped**（原 473 + 新增 9）。
- 前端全量：**39 个测试文件 0 失败**（原 38 + 新增 1）。
- 本地基准：numpy 路径与纯 Python 路径解码输出逐字节一致；filter 0/1/2 为主
  的 1080x2400 图解码快 2.2 倍。

---

# 第八轮：截图进行中禁用「立即截图」（点了就有"在跑了"的反馈）

## 问题

截图整体响应偏慢（大头在设备端采集 + USB 传输，`exec-out screencap -p` 已是最快
路径，见第七轮）。慢本身短期无法消除，但**等待中的界面反馈**可以做得更好：
旧行为点完按钮毫无变化，用户会连点、或以为"点了没反应"。

## 方案

点击即禁用、完成恢复，按钮态由后端事件最终对账（与 `rec_state` 驱动录屏按钮
同一套路）：

| 环节 | 行为 |
| --- | --- |
| 点击 | 同步禁用（不等后端事件），重复点击被守卫拦截、不重复下发 |
| 后端受理 | 每个截图 worker 入口在途 +1，0<->1 翻转时广播 `shot_state {running:true}` |
| 收尾 | worker 出口（`finally`）在途 -1，归零时广播 `running:false`，前端恢复 |
| 后端拒绝 | 未勾选设备等直接返回 `ok:false`：没有 worker 登记，前端按调用结果就地恢复 |
| 桥接异常 | `callApi` 返回 null：同样就地恢复——任何路径都不把按钮锁死 |

关键决策——**+1/-1 都放在 worker 入口/出口**（`_do_screenshot` 自己平衡），
`screenshot()` 的 spawn 路径完全不碰计数器：同步/异步 spawn、成败甚至 worker
抛异常，计数都自然平衡；批量 N 台设备只在 0<->1 翻转时推事件，按钮只禁用/
恢复一次，不闪烁。计数而非布尔：请求叠加时先结束的不会提前解开另一个的
禁用态。

## 改动清单
| 文件 | 改动 |
| --- | --- |
| `backend/controller.py` | `__init__` 新增在途计数与锁；新增 `_shot_state_change`（0<->1 翻转广播 `shot_state`）；`_do_screenshot` 拆为 try/finally 包装（入口 +1、出口 -1、批量异常也记进批次账），原实现更名 `_do_screenshot_locked`；`screenshot()` docstring 补充按钮态说明 |
| `frontend/js/app.js` | 新增 `shotInFlight` 状态与 `setShotRunning`；`handleEvent` 新增 `shot_state` 分支；`syncToolButtons` 改为 `!any \|\| shotInFlight`（并上移，录制中也不再跳过截图按钮的同步）；点击处理改乐观禁用 + 拒绝/异常恢复 |
| `tests/test_backend_controller.py` | 新增 6 个用例：单设备 true→false、批量只一对 true/false（真实线程+闸门）、无设备不广播、叠加请求保持 running、worker 异常仍恢复、批量 worker 异常仍汇总 |
| `tests/frontend/shot_button_state.test.cjs` | 新增前端用例：点击即禁用、true 保持/false 恢复、ok:false 恢复、禁击中重复点击不重复下发、无设备不触达后端 |
| `tests/frontend/screenshot_clipboard.test.cjs` | 既有用例适配新按钮生命周期：两次点击之间补 `shot_state(false)` 广播（与生产一致），并新增「点击后按钮禁用」断言 |
| `README.md` | 事件列表补 `shot_state`；截图链路提速补第 ④ 条；新增「截图在途禁用」设计要点与界面说明 |
| `使用说明.txt` | 工具页截图节补充按钮禁用/恢复说明 |

## 验证
- Python 全量：**488 passed / 1 skipped**（原 482 + 新增 6）。
- 前端全量：**40 个测试文件 0 失败**（原 39 + 新增 1）。
- 对拍确认：`shot_state` 事件序列单设备恰为 [true, false]；批量（含 worker
  异常）恰一对；无设备早退零事件。

---

# 第九轮：Logcat 抓取卡上调 / tab 去序号 / 剪贴板兜底根治「内存不足」

## 1. Logcat 两张卡调换位置（抓取在上）

「落盘抓取」是更高频的操作（留证据 / 发同事），「实时监控」是排障深读场景。
HTML 里把抓取卡移到监控卡上方；`grow`（吃满剩余高度）仍留给监控卡——日志视图
在卡内生长，抓取卡是固定高度的紧凑卡。行为零变化（app.js 全部按 ID 取元素，
不依赖 DOM 顺序）。

## 2. 顶部 tabs 去掉序号

`01 设备指令 / 02 工具 …` → 直接显示名字。序号是纯装饰（窄窗口下本就
`display:none`），去掉后 tab 更干净；CSS 里 `.tab-no` 相关规则一并清理。

## 3. 剪贴板「内存不足」报障的分析与根治

**用户报障**：`复制到粘贴板失败：Windows 剪贴板写入失败（PowerShell 兜底失败：
…Image]::FromFile('E:\log-zip\…png')…异常:ڴ治㡣…）`。

**定性**（回答「是不是单设备的问题」）：**与设备无关**——截图已成功落盘，
失败的是 PC 侧把图写进**系统剪贴板**这一步，且是全局资源被占/文件被锁类问题。
两层根因：
  1. PowerShell 兜底脚本用 `Image.FromFile(截图路径)` 加载图片，GDI+ 对
     「打不开文件」一律报「内存不足」——刚落盘的 PNG 被反病毒 / 同步工具
     （E:\ 上的 log-zip 目录正是典型目标）瞬时独占锁住时必现；
  2. 中文 Windows 上 PowerShell 的 stderr 按 GBK 输出，Python 按 UTF-8 解，
     报障文字变成「ʱ쳣ڴ治㡣」式乱码，最难读。

**修复**（`core/clipboard.py`）：
  - 图片字节改走 **stdin（base64）**，PS 侧 `FromStream` 解码——子进程完全
    不碰截图文件，第 1 类根因被消除（字节本就在 Python 内存里：copy_image
    的 raw）。raw 为空的非常规入口才回落 `FromFile(path)`；
  - PowerShell 兜底从「一次」改为**重试 2 轮**（轮间 0.3s）：剪贴板被第三方
    短暂持有时多撞一次窗口往往就进去了；
  - 脚本内置 `[Console]::OutputEncoding = UTF8`，Python 侧 `_ps_text` 多编码
    兜底（utf-8 → gbk → replace），错误信息可读；
  - 最终失败原因带**两阶段明细**（「直接写入：…」+「PowerShell 兜底失败：…」），
    报障时能直接定位是哪一层。

**测试**：`tests/test_core_clipboard.py` 更新既有 PS 兜底用例，新增 5 个：
stdin 传图契约（input = base64(整图)）、无 raw 回落 FromFile、兜底重试后成功、
GBK stderr 解出可读中文、`_ps_text` 单测、最终失败原因含两阶段明细。

## 改动清单
| 文件 | 改动 |
| --- | --- |
| `frontend/index.html` | 抓取卡移至监控卡上方（grow 留给监控卡）；5 个 tab 去掉序号 span |
| `frontend/css/app.css` | 清理 `.tab-no` 三条规则与响应式里的 `display:none` |
| `core/clipboard.py` | `_win_write_powershell(path, raw)` 重写：stdin base64 传图 + FromStream、重试 2 轮、UTF8 错误输出；新增 `_ps_text` 与 `_WIN_PS_ATTEMPTS` 等常量；`copy_windows` 传 raw、失败原因合并两阶段；模块 docstring 同步 |
| `tests/test_core_clipboard.py` | 更新 1 个既有用例，新增 6 个（见上） |
| `tests/frontend/logcat_tab_cards.test.cjs` | 双卡顺序断言改为抓取在前 |
| `README.md` | Logcat 卡片顺序描述、「剪贴板写入的三层防线」设计要点 |
| `使用说明.txt` | 抓取卡位置描述（上方）、剪贴板失败说明更新 |

## 验证
- Python 全量：**493 passed / 1 skipped**（原 488 + 新增 5）。
- 前端全量：**40 个测试文件 0 失败**。
- 生成的兜底脚本人工复核：`FromStream` 主路径 + `FromFile` 遗留分支 +
  UTF8 输出 + stdin EOF 语义均正确；GBK/UTF-8 错误文本解码有对拍用例。


---
# 第十轮：性能监控增强（卡顿率曲线 / 多设备对比 / 阈值告警）

上一轮把性能监控从零做出来（六指标 + 曲线 + 报告）。这轮把它从「能看」推到
「能用来定位和验收」，三件事依次落地。

## 1. 卡顿率独立曲线（区间值，不是累计百分比）

**问题**：gfxinfo 只给了 `Janky frames: N (x%)`，x 是**自应用启动以来**的累计值。
挂机监控两小时后，哪怕最近十分钟一直掉帧，这条线也几乎不动——它反映的是
历史平均，不是「现在卡不卡」。

**改法**：
- `parse_gfxinfo_detail()` 同时取出累计帧数与**累计卡顿帧数**（只有百分比没法
  差分，百分比的差分没有物理意义）。
- `jank_window()` 用 `Δ卡顿帧 ÷ Δ总帧` 算区间卡顿率；三种退化情形（老 ROM 没有
  Janky 行 / 界面静止没有新帧 / 应用重启计数归零）回退到累计值，而不是断线。
- 指标卡从 6 张变 7 张；CSV 同时给 `jank_percent`（区间）与
  `jank_cumulative_percent`（累计），两种口径都留档。
- 卡顿率曲线**不做 0~100 固定量程**：真实值常年 1~15%，按 100 画会全压在底部
  一条直线上，看不出任何波动。

## 2. 多设备对比

**问题**：原先定格「同一时刻只监控一台」。做对比测试时（同版本两台机、或改前
改后各一台）只能开两份程序、截两张图肉眼比。

**改法**：
- controller 的 `_perf` 单会话 → `_perfs` 字典（serial → PerfMonitor），
  `perf_start` 不传 serial 时监控**全部受控设备**，上限 `PERF_MAX_DEVICES = 4`
  （每台一条线程、每 tick 一次 `adb shell`，再多只是在 adb 队列里排队，采样
  间隔被拉长、曲线出现假台阶）。
- `perf_poll` 的 since 支持 `{serial: seq}` 逐设备游标；顶层仍保留合并后的
  `samples` 兼容旧前端与测试。
- `perf_stop(serial)` 支持只停一台；`perf_export` 每台各出一份 HTML + CSV。
- 前端：会话按设备拆成 Map，曲线**横轴改用时间**（各设备采样点数可能不同，
  按索引对齐会整体错位）；多设备时一设备一色、不画面积（半透明面积叠在一起会
  糊成一片），图例点选切焦点设备（指标卡读数与末端气泡跟随）。
- 部分设备启动失败不拖垮其余：成功几台就监控几台，失败清单单独回报。

## 3. 阈值告警

**问题**：报告里只有 min/avg/max/P95，看的人得自己判断「这算不算差」；界面
上也不提示，一段 5 分钟的掉帧要事后翻 Excel 才发现。

**改法**：
- `DEFAULT_THRESHOLDS`：帧率 < 45 / 卡顿率 > 8% / 温度 > 42℃ / CPU > 85%，
  每条都写了取值理由（45 是「肉眼能看出不跟手」的经验线，42℃ 是电池开始降频）。
- `evaluate_alerts()` 算超标点数、占比、最差值、**最长持续时长**（按样本时间差
  串连续段；单点超标用平均采样间隔兜底，不显示「持续 0 秒」），占比 ≥ 25%
  升级为 `crit`。
- 报告新增「阈值告警」卡片（无告警也会出现——「没超标」本身就是结论）。
- 界面：越线指标卡**整卡切红**（只把数字变红，余光扫不到）、卡片 title 写明
  规则、状态栏边沿提示（8 秒内最多一条，避免抖动曲线刷屏）、当前指标画红色
  虚线参考线，且 **Y 轴主动把阈值纳入范围**——否则读数远离阈值时自动缩放会把
  线挤出画布，恰恰在最该看见它的时候消失。
- 阈值只在后端定义一份，前端通过 `perf_thresholds` 取：两份常量必然漂移，
  最后会出现「报告说没超标、界面标红」的自相矛盾。

## 改动清单
| 文件 | 改动 |
| --- | --- |
| `backend/perf_service.py` | `parse_gfxinfo_detail` / `jank_window` / `DEFAULT_THRESHOLDS` / `threshold_rule_text` / `evaluate_alerts` / `_alert_card_html`；METRICS 加 jank；报告加告警卡片与卡顿曲线；CSV 加累计列 |
| `backend/controller.py` | `_perfs` 多会话；`perf_start/stop/poll/status/export` 支持多设备；新增 `perf_thresholds`；`PERF_MAX_DEVICES`；shutdown 收尾全部会话 |
| `frontend/js/app.js` | 会话 Map + 逐设备游标；多设备分色绘制（时间轴 / 图例 / 焦点切换）；卡顿率指标；阈值判定、切红、边沿提示、阈值参考线 |
| `frontend/index.html` | 第 7 张指标卡（卡顿率）；图例容器 |
| `frontend/css/app.css` | 指标卡自适应网格；`.perf-legend` / `.perf-lg`；`.perf-stat.warn` |
| `tests/test_backend_perf.py` | +13（gfxinfo 明细 / 区间卡顿率 / 告警判定 / 报告告警卡片 / CSV 列） |
| `tests/test_backend_controller.py` | +5（多会话 / 逐设备游标 / 部分失败 / 设备上限 / 阈值下发） |
| `tests/frontend/perf_multi_device.test.cjs` | 新增 18 条（图例 / 游标 / 焦点切换 / 总点数 / 多份报告） |
| `tests/frontend/perf_alerts.test.cjs` | 新增 9 条（阈值下发 / 切红 / toast / 参考线 / 恢复） |
| `tests/frontend/perf_tab.test.cjs` | 指标卡数量 6 → 7、网格断言改自适应、perf_start 第一参改 null |
| `README.md` / `使用说明.txt` | 性能监控章节重写（七指标 / 多设备 / 告警 / 报告结构） |

## 验证
- Python 全量：**606 passed / 1 skipped**（原 595 + 新增 11）。
- 前端全量：**47 个测试文件 0 失败**。
- 界面与报告预览图人工复核：多设备双线、卡顿率阈值线、帧率越线切红、
  报告告警卡片排版均正常。

---

# 第十一轮：阈值可配置 / 报告超标色带 / 多设备对比报告

上一轮结束时留了三个「还能往下做」的方向，这轮按顺序全部落地。

## 一、阈值开放为可配置

### 改了什么
- `perf_thresholds` 新增到 `config.json` schema（`core/prefs.py`），值是一个
  **表达式字符串**：`"fps<45,jank>8,temp>42,cpu>85"`。
  - 留空 = 用内置基线；`"off"` = 全部关闭；写几段就只判几段（覆盖式）。
  - 用表达式而不是嵌套 JSON：用户打开 config.json 时要能一眼看懂并直接改，
    嵌套对象既不好读，也得靠缩进猜结构。

### 为什么空串不能表示「全部关闭」
空串按其它配置项的惯例是「没配过 → 用默认」。若拿空串兼作「一条都不要」，
用户把输入框清空后，告警会**神奇地复活**成内置基线 —— 这正是最容易让人困惑
的一类行为。故显式引入 `off`。

### 新增的纯函数（`backend/perf_service.py`）
| 函数 | 职责 |
| --- | --- |
| `parse_thresholds(expr, strict)` | 表达式 → 阈值 dict + 错误列表；`strict` 用于「刚提交的设置」（有错整条作废），非 strict 用于读历史配置（能救则救） |
| `format_thresholds(th)` | 阈值 dict → 表达式（写回 config.json） |
| `default_threshold_expr()` | 内置基线的表达式文本（前端「恢复默认」） |
| `build_thresholds(values)` | 界面提交的 `{key: 数值或 null}` → 阈值 dict（与手改走同一套校验） |
| `threshold_items(th)` | 界面四行所需的元数据（方向 / 单位 / 范围 / 取值理由） |
| `THRESHOLD_META` | 四条规则的方向、合法区间、说明文案的**唯一**来源 |

### 校验拦下来的错
- `fps>50`（方向写反）、`jank>250`（越界）、`bogus<1`（未知指标）、
  `乱写<1`（连形状都不对）。
- 非法值**不写盘**：静默存下一份坏配置，用户下次启动只会看到告警莫名消失，
  无从追查。

### 界面
- 性能页工具栏新增「阈值」按钮 → 弹窗四行（勾选框 / 名称 / 低于-高于 /
  数值 / 取值理由）。
- 四行由后端下发的 `items` 渲染，前端不硬编码方向与理由 —— 抄一份的结局是
  界面写 45、报告按 50 判。
- 「恢复默认」只改界面不落盘（误点一下就把自定义阈值清掉且无法撤销）。
- 保存成功后立即重算标红与阈值线，并关闭弹窗；失败时弹窗保持打开、显示原因。

### 顺手修掉的坑
- `escHtml / escAttr` 在 `app.js` 里其实**不存在**（图例早先改成了 DOM 构建，
  两个函数从没被真正需要）。这轮拼弹窗 HTML 才暴露，已补上。
- `.th-row .th-on` 被全局 checkbox 的 iOS 滑块样式（46px 宽 + 圆形滑块）
  盖住，塞进 18px 格子后把后面的名称裁成「率」「温」——截图时才发现。
  已显式还原成主题化方块 + 纯 CSS 对勾。

## 二、报告曲线标出超标时段

- `_svg_chart()` 新增 `rule` 参数：
  - **超标色带**：连续超标点合并成一条半透明红条；单点超标宽度兜底为一个
    采样间隔（否则宽度为 0 什么都看不见，而「偶发掉一帧」恰恰最该被看见）。
  - **阈值虚线 + 行尾标签**（`≥ 45 FPS` / `≤ 85 %`）。
  - **阈值纳入纵轴量程**：只画线不扩量程的话，读数远离阈值时自动缩放会把
    线挤出画布 —— 恰恰在最该看见「合格」的时候消失。
  - 卡片标题右上角标出判定标准，不必去图上找虚线标签。
- `build_report_html(samples, info, thresholds, generated_at)` 与
  `write_report(..., thresholds)` 接受阈值；警报卡片文案从「内置基线」改为
  「判定标准」，并在全部关闭时显示「本次采样未启用阈值告警」。

## 三、多设备对比报告

新增 `build_compare_html(entries, thresholds)` / `write_compare_report(...)`：

| 区块 | 内容 |
| --- | --- |
| 概览 | 设备数 / 监控应用 / 时间范围 / 总采样点 / 生成时间 |
| 对比设备 | 型号（带色点，与曲线同色）/ 序列号 / Android / 分辨率 / 应用 / 时长 / 样本数 |
| 指标对比 | 七项指标 × 各设备，每格「均值 / 峰值」，该指标最不理想的一台标红 |
| 曲线 | 七张多线图，横轴**按时间对齐**（各设备点数不同，按序号对齐会整体错位），一设备一色 |
| 阈值告警 | 行 = 设备、列 = 各阈值项，格 = 超标占比 + 点数；`≥25%` 记严重 |

设计取舍：
- **不画超标色带，改打红点** —— 三条线叠在一起时，色带属于哪台设备无从分辨；
  红点落在哪条线上，就是哪台在那一刻不达标。红点上限 400（整段全超标时
  逐点画会让报告膨胀几 MB，而那时「满屏都是红的」本身就是结论）。
- **并列最差不标红**：两台数值相同的指标随便挑一台标红，等于给读者一个假结论。
- **≥1000 的数值取整**：`3120.0 / 3181.2` 并排时，一位小数只是噪声，还会让人
  以为后者更准。
- `label` 用「型号 · 序列号尾 4 位」：同型号批量测试时只写型号，图例会出现
  四个一模一样的名字，等于没有图例。
- 单设备不生成对比报告（没有对比可做，不该白写一份文件）。

## 改动清单

| 文件 | 改动 |
| --- | --- |
| `backend/perf_service.py` | 阈值解析/格式化/校验/界面元数据；`_svg_chart` 色带；`_svg_compare` / `build_compare_html` / `write_compare_report` / `_compare_matrix` / `_compare_alert_table` / `esc_html` / `_cell_num` |
| `backend/controller.py` | `_perf_thresholds` / `_perf_threshold_payload` / `perf_set_thresholds` / `_perf_label`；`perf_thresholds` 返回增强结构；`perf_export` 传阈值并生成对比报告 |
| `core/prefs.py` | 新增 `perf_thresholds` 键（默认空串 = 内置基线） |
| `frontend/index.html` | 「阈值」按钮 + 告警阈值弹窗 |
| `frontend/js/app.js` | `applyPerfThresholds` / 弹窗渲染与保存 / `escHtml` / `escAttr`；导出多设备时优先打开对比报告 |
| `frontend/css/app.css` | 阈值弹窗样式（含方块勾选框覆盖全局滑块） |
| `tests/test_backend_perf.py` | 阈值解析 8 条 + 色带/自定义阈值 5 条 + 对比报告 7 条 |
| `tests/test_backend_controller.py` | 阈值保存/关闭/非法/坏配置/off 5 条 + 对比导出 3 条；新增 autouse fixture 把 `config.json` 隔离到 tmp_path |
| `tests/frontend/perf_thresholds.test.cjs` | 新增 25 条（渲染 / 提交 null / 拒绝 / 本地校验 / 恢复默认 / 即时生效） |

## 验证
- Python 全量：**636 passed / 1 skipped**。
- 前端全量：**48 个测试文件 0 失败**。
- 人工复核：阈值弹窗排版、报告色带、对比报告三个区块与多线图。


---

# 第十二轮：指令卡长按拖动排序 / 应用包名下拉（模糊搜索 + 跟随前台 + 全系统）

## 你提的两条

1. 设备指令页的指令卡（小按钮）**支持长按拖动排序**；
2. 性能监控的「应用包名」改成**下拉框 + 模糊搜索**：能读设备上装了什么应用，
   默认「跟随前台应用」，也能选「监控全系统」。

## 1. 指令卡长按拖动排序

### 改前 / 改后

| | 改前 | 改后 |
| --- | --- | --- |
| 排序依据 | 只按点击次数降序，常用命令自动靠前 | 拖过的分组按你排的顺序；**没拖过的分组照旧按点击频次**自动排 |
| 交互 | 无 | 按住 0.4 秒（卡片抬起 + 磷光描边）→ 拖动换位 → 松手即存 |
| 持久化 | — | `config.json` 的 `cmd_order`（逗号分隔命令 id），下次启动原样恢复 |

### 三个必须处理的坑

1. **长按不能把「执行命令」吃掉**：短按仍然必须执行。这里靠两条闸门 ——
   0.4 秒计时器没到点就松开 = 普通点击（`endCmdDrag(false)` 直接放行）；
   计时器到点才切 `is-dragging`，`click` 照常走 `runQuickCommand`。
2. **松手后浏览器补发的 click 必须拦掉**：否则「排个序」会顺手把那条命令真的
   下发到设备上（测的是性能，结果多刷了一条 `dumpsys`）。故拖动结束写一个
   350ms 的 `cmdClickGuard` 时间戳，窗口内的 click 直接 `stopPropagation`。
3. **不能一次拖动冻结全部分组**：只把「被拖的那个分组」的 id 追加进 `cmd_order`，
   其余分组不受影响 —— 常用命令继续自己浮上来。排序键为
   「手动序 > 点击频次 > 名称」，没进手动序的一律排在手动序之后。

顺带修掉两处易错细节：
- 指针移出窗口后松手收不到 `pointerup` → 拖动态卡死；现在 `pointercancel` 与
  `window.blur` 都当作结束，恢复到重绘。
- 拖动时指针扫过别人的卡片，会把沿途每个 ⋯ 菜单都弹开（截图里一眼就看出很乱）
  → 拖动期间 `body.cmd-sorting .chip-popup { display:none }` 一律不弹。

排序落的是 **id 序列**而不是 DOM 序号：过滤、重渲、改名都不会错位；删掉的命令
id 在下次落盘时自动剔除，配置不会越滚越长。

## 2. 应用包名：下拉 + 模糊搜索（默认跟随前台 / 可切全系统）

### 改前 / 改后

| | 改前 | 改后 |
| --- | --- | --- |
| 形态 | 一个空白输入框，`placeholder` 写着「留空 = 自动跟随前台应用」 | 下拉选择器，按钮上直接显示当前目标 |
| 取值 | 只能手打包名 | ① 跟随前台应用（默认）② 监控全系统 ③ 从设备已安装应用里挑 ④ 手打包名回车 |
| 找应用 | 全靠记包名 | 模糊搜索：`chrome` / `tencent` / `comkwo` 都能命中 |

### 后端新增

- `perf_service.list_packages()`：**一次 adb 调用**同时取 `pm list packages -3`
  与全量清单（`echo @@TP` / `@@ALL` 分段），返回 `{third, system, total}`。
  为什么要两份：性能测试盯的基本都是被测 App（第三方），几百个系统应用堆进
  下拉框只会稀释搜索；但偶尔也要盯系统相机 / 桌面，所以全量一并取回，前端用
  「含系统应用」开关切换时不再走一次设备（那一次在应用多的机器上要 1~3 秒）。
- `parse_package_list()`：`package:com.x` 去前缀、去重、排序，并**用包名白名单
  过滤**——包名最终会拼进设备端 shell 脚本，`package:com.foo;reboot` 这种必须
  在入口就丢掉。
- `PerfMonitor` 新增 `SYSTEM_PKG = "__system__"` 哨兵 + `pkg_mode`
  （system / auto / manual）。全系统模式下 `self.pkg` 恒为空、脚本退回只采整机
  那一份，**PSS / 帧率 / 卡顿率一律 None** —— 它们本来就是「某个应用」的指标，
  硬凑一个「整机帧率」只会让人误读。
- `pkg_display()`：报告与状态栏共用的「监控应用」文案
  （`全系统（仅整机指标）` / `com.x（跟随前台）` / `com.x`）。
- `controller.perf_list_packages(serial, refresh)`：缓存 120 秒且**失败不缓存**
  （否则插上线后两分钟内点开下拉还是那句「读取失败」），点「刷新」绕过缓存。

### 前端

- 选择器是自绘弹层而不是原生 `<select>`：原生 select 不支持搜索，也没法在一个
  控件里混「跟随前台 / 全系统 / 具体应用」三种语义。
- 模糊匹配两级：先子串命中（越靠前分越高），再退化成「按顺序凑字符」
  （`comkwo` → `com.tencent.kuwo`）。
- 搜索框同时也是手输框：回车 = 有匹配取最相关的那条，没匹配就把输入当包名
  （前端先按 `[A-Za-z0-9_.]` 校验，后端还有一道白名单）。
- 监控进行中改目标会 toast 提示「下次开始监控生效」—— 后端只在 `perf_start`
  那一刻读一次 pkg，不说清用户会盯着曲线等。

## 改动清单

| 文件 | 改动 |
| --- | --- |
| `backend/perf_service.py` | `SYSTEM_PKG` / `pkg_display` / `parse_package_list` / `list_packages`；`PerfMonitor` 增加 `system_only` / `mode` / `info.pkg_mode`；报告三处「监控应用」改用 `pkg_display` |
| `backend/controller.py` | `perf_list_packages`（缓存 + 失败不缓存 + refresh）；`PERF_PKG_CACHE_S`；启动状态文案改用 `pkg_display` |
| `core/prefs.py` | 新增 `cmd_order`（指令卡手动顺序）、`perf_pkg_all`（含系统应用开关） |
| `frontend/index.html` | 应用包名改为「按钮 + 弹层」（搜索框 / 两个模式 / 含系统应用 / 刷新 / 列表）；指令台过滤条右侧加「长按卡片可拖动排序」提示 |
| `frontend/js/app.js` | 拖动排序子系统（`sortCmdGroup` / `saveCmdGroupOrder` / `bindCmdDrag` / 指针事件 / click 拦截）；包名选择器子系统（`fuzzyScore` / `rows` / `renderPerfPkgList` / `loadPerfPkgs` / `bindPerfPkgPicker`）；`perfPkg` 取代输入框取值 |
| `frontend/css/app.css` | 拖动排序视觉（抬起 / 抓取光标 / 拖动中禁弹菜单）；选择器弹层整套样式（含小号开关变体） |
| `build.py` | 源码分发 zip 排除 `preview_*.cjs`（开发期截图脚本，依赖本机 chromium） |
| `tests/test_backend_perf.py` | 新增 9 条：全系统模式（哨兵不落类 / 不探前台 / 应用级指标为空）、`pkg_display` 五种输入、报告文案、包名解析与白名单、`list_packages` 分段与两种失败 |
| `tests/test_backend_controller.py` | 新增 4 条：无设备、缓存命中、刷新绕过、失败不缓存、全系统透传 |
| `tests/test_core_prefs.py` | 布尔键 → HTML 复选框映射表补 `perf_pkg_all` |
| `tests/frontend/cmd_drag_sort.test.cjs` | 新增 20 条（默认频次序 / 短按照旧执行 / 长按换位落盘 / click 拦截 / 回填 / 只冻结被拖分组 / 超阈值取消长按） |
| `tests/frontend/perf_pkg_picker.test.cjs` | 新增 35 条（默认文案 / 读取与缓存口径 / 三种模糊命中 / 选中落盘 / 全系统透传 / 含系统应用 / 失败提示 / 刷新 / 回填） |
| `tests/frontend/perf_tab.test.cjs` | 包名回填与落盘断言改走新选择器 |
| `tests/frontend/ui_style_card_tabs.test.cjs`、`checkbox_switch_style.test.cjs` | 按钮样式白名单补 `pkg-*`；静态复选框 31 → 32 |
| `README.md` / `使用说明.txt` | 性能监控行补选择器说明；指令台一节补拖动排序用法；第九节补两个新配置项 |

## 验证
- Python 全量：**651 passed / 1 skipped**（本轮新增 15 条）。
- 前端全量：**50 个测试文件 0 失败**（新增 `cmd_drag_sort` 20 条 + `perf_pkg_picker` 35 条）。
- 人工复核：拖动排序进行中（卡片抬起 + 位置已换 + 不弹 ⋯ 菜单）、
  下拉列表（`tencent` 模糊命中 2 条）、「含系统应用」系统角标、
  「监控全系统」按钮文案，四张预览图逐张看过。


---

# 第十三轮：曲线悬停提示 / 内置命令扩充 / 投屏预览可拖大小 / 截图·录屏并排 / 标题栏配色

## 你提的五条

1. 性能监控的图表要有 **tooltips**；
2. 设备指令的「内置」**增加更多命令**（比如开启 / 关闭指针、开启 / 关闭触摸圆点）；
3. 备用投屏的视图**能不能拖动改变大小**；
4. 设备截图、设备录屏**横向排成一行**；
5. 原生标题栏与主题色不搭，**适配主题色**。

## 1. 性能曲线悬停提示

鼠标在曲线上移动 → 一条竖线 + 一张数值卡片：时间点、每台设备在该时刻的读数与
单位（多设备一行一台，前面的色点与曲线同色）。

几个取舍：

| 问题 | 做法 | 为什么 |
| --- | --- | --- |
| 提示画在 canvas 里还是 DOM？ | DOM（`#perf-tip` / `#perf-cross`） | 画布每帧重绘会把提示一起重画（多设备时更闪）；文本排版、圆角、阴影在 canvas 里要手算坐标 |
| 指针离采样点多远算命中？ | 26px | 不限距离则空白处也弹卡片，挡住本来能看见的曲线 |
| 纵向定位？ | 贴着命中点的数值上方，超出画布则夹住 | 卡片盖住曲线本身就没意义了 |
| 数据还在进怎么办？ | 每次重绘都刷新提示内容 | 指针停着不动时，读数不能停在几秒前的旧值 |

命中判定先用「X 距离最近」找到锚点时间，再让每台设备各取自己离锚点最近的采样点
——多设备时两台的采样时刻并不完全对齐，直接按索引取会错位。

顺带补上 `PERF_METRICS[*].unit`（`%` / `MB` / `FPS` / `℃`）：这张表原来只有标题、
颜色和量程，提示是唯一「数字和单位写在一起」的地方，缺了会显示 `undefined`。

## 2. 内置命令：21 → 49 条

**先说明一件容易误会的事**：开启 / 关闭指针位置、开启 / 关闭触摸圆点这四条
**本来就在**内置里（`bi.pointer-on` / `bi.touch-on` …）。你看不到它们，是因为
你自己的 `commands.json` 里已经有同名命令（`[通用] 开启指针位置` 等），
`merge_builtins` 按「同名让位」规则把内置那条压掉了 —— 同一条命令不该在界面上
出现两次。想看内置那四条，把命令文件里同名的删掉即可。

这一轮真正新增的是 28 条，全部单行、无需 root、不依赖个人路径：

| 分组 | 新增命令 |
| --- | --- |
| 按键与屏幕 | 息屏 / 亮屏 / 返回 / 主页 / 多任务 / 音量±/ 静音切换 / 回到桌面 |
| 屏幕状态 | 充电时保持常亮 / 取消常亮 / 锁定竖屏 / 锁定横屏 / 恢复自动旋转 |
| 网络 | 飞行模式开·关 / WiFi 开·关 / 移动数据开·关 / 查看 WLAN IP |
| 性能与调试 | 关闭系统动画 / 恢复系统动画 / 清理后台进程 / 清空 logcat / 电池与温度 / 存储空间 / 内存概况 / 列出第三方应用 |

几个刻意的选择：

- **亮屏用 224（WAKEUP），不用 26（POWER）**：26 是电源开关，屏幕亮着时按下去
  等于熄屏 —— 名字说「亮屏」，效果却是把屏关掉。
- **锁旋转要同时关掉重力感应**：只写 `user_rotation` 时设备一转就被系统改回去。
- **飞行模式用 `cmd connectivity`**（Android 11+）：直接写 settings 不触发实际切换，
  还得发广播，而广播需要额外权限。
- **清理后台用 `am kill-all` 而不是 `force-stop`**：只回收可安全释放的后台进程，
  不动前台与常驻服务，清完还能接着测。

测试锁住「成对开关必须改同一个键、值互补」「命令里不能有换行」（会话是一行一条
喂给 PowerShell 的，多行会被拆成两条执行）。

## 3. 投屏预览：拖动改大小

内嵌的预览原来固定 `max-height: 280px`，看列表、看文字基本靠猜。现在画面框
右下角有一个斜纹手柄：

- 按住拖动 → 宽高各自跟随（画面 `object-fit: contain` 等比缩放，多出来的地方
  留黑边，**不拉变形**）；
- 松手即落盘（`mirror_view_w` / `mirror_view_h`，一次写两个键），下次投屏还是
  这么大；**双击手柄**恢复自适应（存 0/0）；
- 拖太小 / 拖出卡片都夹在合理区间（最小 200×120，最大卡片宽 / 900 高）；
- 拖动起点取「当前实际渲染尺寸」而不是存储值：首次拖动前是自适应，两者不相等，
  用存储值会让第一下拖动跳一段。

## 4. 截图 / 录屏并排

`grid` 两列（左窄右宽：截图只有两个按钮，录屏有七行勾选），`align-items: start`
让两张卡各自保持自然高度；窗口窄于 1080px 退回上下排列（最小窗口 980 下两列会把
勾选文案挤成两行）。截图卡原来那一大段灰字拆成四条要点清单 —— 并排后左卡内容
偏少，顺带把卡撑到与邻居相称的高度。

## 5. 原生标题栏配色

窗口用的仍是**系统标题栏**（保留贴边分屏 / 双击最大化 / 高 DPI / 系统菜单），
只把配色改掉：

| DWM 属性 | 作用 | 生效版本 |
| --- | --- | --- |
| `DWMWA_USE_IMMERSIVE_DARK_MODE` (20，旧编号 19) | 标题栏深色 | Win10 1809+ |
| `DWMWA_CAPTION_COLOR` (35) | 标题栏底色 = 界面 `--bg` | Win11 22000+ |
| `DWMWA_TEXT_COLOR` (36) | 标题文字 = 界面 `--text` | Win11 22000+ |
| `DWMWA_BORDER_COLOR` (34) | 外框色 | Win11 22000+ |

`COLORREF` 是 **BGR** 顺序且高位为 0（`#0b0f14` → `0x00140F0B`），写成 RGB 就是
红蓝互换 —— 深蓝黑会变成暗红，单测专门盯着这一条。老系统写不进 34/35/36 时只
降级成「深色模式」，不算失败。

调用时机：`webview.start(func=...)` 的线程里轮询等窗口句柄（GUI 循环刚起时窗口
对象还没建出来），拿不到就静默放弃 —— 配色是锦上添花，任何异常都不能挡住启动。
非 Windows 全程 no-op（`core/win_theme.py` 的纯函数部分在 Linux CI 上照常可测）。

## 6. 顺手修掉：`hidden` 属性被组件样式覆盖

验收截图时发现「没投屏时预览位置空着一块、还带个破图占位」。原因是
`.mirror-preview { display: inline-flex }` 这类**作者样式盖掉了浏览器默认的
`[hidden] { display: none }`** —— `el.hidden = true` 只是给元素加了个属性，
样式该显示还是显示。

也不只这一处：`.btn` 同样是 `display: inline-flex`，于是「命令编辑」窗里的
「删除」按钮（新建命令时 `hidden = true`）、预览弹窗里的「查看」按钮（没有本地
文件可打开时）也一直露在外面。

统一在样式表顶部加一条 `[hidden] { display: none !important; }` 收口，
不再逐个组件补 `[hidden]` 规则 —— 补一个漏一个，正是这次的来路。

## 改动清单

| 文件 | 改动 |
| --- | --- |
| `core/builtin_commands.py` | 内置命令 21 → 49 条（按键 / 屏幕状态 / 旋转 / 网络 / 动画 / 设备信息） |
| `core/win_theme.py` | **新增**：COLORREF 换算、DWM 属性表、`apply_to_hwnd`（可注入 setter）、`find_window` / `attach`（轮询等窗口） |
| `core/prefs.py` | 新增 `mirror_view_w` / `mirror_view_h`（0 = 自适应，夹在 0~2400） |
| `main.py` | `_theme_window()` + `webview.start(func=…)` 挂上标题栏配色 |
| `frontend/index.html` | 截图 / 录屏包进 `.tool-pair`；预览块加 `#mirror-frame` + `#mirror-grip`；曲线容器加 `#perf-cross` / `#perf-tip`；截图卡改要点清单 |
| `frontend/js/app.js` | `perfTipModel` / `updatePerfTip` / `bindPerfHover`（悬停提示）；`applyMirrorViewSize` / `bindMirrorResize`（拖动改大小）；`PERF_METRICS` 补 `unit`；`persistPrefs`（一次写多个键） |
| `frontend/css/app.css` | `.tool-pair` 两列网格；`.mirror-frame` / `.mirror-grip`（含 contain 与拖动态描边）；`.perf-tip` / `.perf-cross`；`.tool-tips` 要点清单；**全局 `[hidden]` 兜底**（见下） |
| `tests/test_core_win_theme.py` | **新增** 22 条：BGR 换算、非法颜色、属性顺序、旧编号回退、老系统降级、句柄取值、轮询等待 |
| `tests/test_load_commands.py` | 新增 8 条：id 唯一与前缀、条目结构、单行命令、必备 id 集合、成对开关同键互补、合并 / 同名让位 |
| `tests/test_core_prefs.py` | 新增 1 条：预览尺寸落盘 / 夹取 / 0 合法 |
| `tests/frontend/perf_tooltip.test.cjs` | **新增** 19 条：命中出提示、数值 / 单位 / 设备名 / 时间、容差外收起、移出画布收起、多设备两行、无数据不弹 |
| `tests/frontend/mirror_resize.test.cjs` | **新增** 24 条：结构、拖动宽高跟随、松手一次落盘、上下限夹取、双击恢复自适应、启动还原、`[hidden]` 兜底 |
| `tests/frontend/tool_pair_layout.test.cjs` | **新增** 24 条：两卡是 `.tool-pair` 直接子元素、投屏卡仍通栏、grid 两列 / start 对齐 / 1080 断点 |
| `README.md` / `使用说明.txt` | 三行能力表补新特性；结构树补 `win_theme.py`；工具页并排与预览拖拽用法、曲线悬停用法、配置项清单 |

## 验证

- Python 全量：**682 passed / 1 skipped**（本轮新增 31 条）。
- 前端全量：**53 个测试文件 0 失败 / 1025 条断言**（新增 3 个文件，67 条）。
- 人工复核（真 Chromium 截图）：截图 / 录屏并排、预览拖大后的手柄与等比黑边、
  单设备悬停提示、多设备两行提示 —— 四张预览图逐张看过。
- 标题栏配色无法在 Linux 沙箱里出图（没有 Windows 窗口），改由 22 条单测锁定
  颜色换算与降级路径；真机效果需在 Windows 上肉眼确认一次。

# 第十四轮：性能曲线区间框选统计

## 本轮做了什么

接上一轮末尾给的方向，先做最有用的那条：**按住拖动框选一段时间，直接看这一段的统计**。

## 改前

曲线只能逐点读（上一轮的悬停提示）。要定位「刚才那 6 秒为什么卡」，得自己
在几十个点之间来回想：平均多少、最差掉到哪、有几秒压在阈值下面——逐点读数
拼不出这三个数，尤其阈值那条线附近的抖动。

## 改后

- **按住左键横拖**：半透明色带实时跟随（只改 `left/width`，不等松手）；
- **松手出统计卡**：区间起止时间 + 每台设备的 **均值 / 最低 / P95 / 最高 /
  超阈值次数 / 采样点数**，多设备一行一台，色点与曲线一致；
- **三种收法**：双击画布、按 Esc、点卡片右上角 ×；
- **拖得太窄**（不到 8 像素）按点击处理，不出卡片，顺手清掉上一次的选区——
  否则会留下一个「看得见但不属于这次操作」的假选区；
- **采样继续进来时数字跟着重算**：超阈值次数尤其容易过期，不算就等于给了一个
  越看越错的数。

## 五个实现决定

1. **选框与卡片都用 DOM，不画在 canvas 上**：拖动时只改 `left/width`，不触发
   画布重绘，才跟得上手。画在 canvas 里就是每拖一个像素重画整张图，曲线一多
   直接卡成幻灯片。
2. **P95 用 nearest-rank**（第 `ceil(0.95n)` 个），不做线性插值：几十个点的样本
   下插值会给出一个「从没实测到过」的值，报告里没法复现，也没法跟设备的原始
   数据对齐。
3. **抬起监听挂在 `window` 上，不是画布**：拖到画布外再松手太常见了，只听画布的
   `pointerup` 会漏掉，选区就永远停在「拖动中」，后续再也框不动。
4. **拖动期间强制收起悬停提示**：选区边界线 + 十字竖线叠在一起，分不清哪条是
   哪条；而且拖动时数值每帧都在变，提示反而在干扰。
5. **`refreshPerfRange()` 跟每次重绘一起跑**：曲线在往前长，区间数字必须跟着更新，
   否则卡片里永远是刚松手那一刻的统计，越看越不对。

## 一个兜底

没有时间轴的极端情况（所有采样 `t` 相同，个别机型 uptime 精度不够）会退回按
**索引比例**取点：精度差一点，但总比「拖了却什么都选不中」强。

## 改动清单

| 文件 | 改动 |
| --- | --- |
| `frontend/index.html` | 画布容器内新增 `#perf-band`（色带）与 `#perf-range`（统计卡）；图表提示补「按住横拖一段看区间统计」 |
| `frontend/js/app.js` | `perfLocalX` / `perfClampX` / `perfTimeAt` / `perfPct`（像素→时间与分位数）；`perfRangeModel`（纯计算统计）；`paintPerfBand` / `renderPerfRange` / `clearPerfRange` / `refreshPerfRange`；`onPerfDown` / `onPerfUp`，`onPerfHover` 兼顾拖动；`bindPerfHover` 补 pointerdown/up、双击、Esc、× |
| `frontend/css/app.css` | `.perf-band`（青色半透明色带 + 左右描边）、`.perf-range`（卡片）及其 `.pr-*` 行内排版；超阈值项 `.hot` 用 `--err` |
| `tests/frontend/perf_range_stats.test.cjs` | **新增** 35 条：结构、拖动出带、松手出卡、均值/最低/P95/最高/点数、超阈值次数、太窄不弹、双击/Esc/×、拖动期提示收起、多设备两行、无数据不弹 |
| `README.md` / `使用说明.txt` | 能力表与曲线用法补「框选区间看统计」 |

## 验证

- Python 全量：**682 passed / 1 skipped**（本轮未改后端，数字不变）。
- 前端全量：**54 个测试文件 0 失败**（本轮新增 1 个文件 / 35 条断言）。
- 人工复核（真 Chromium 截图）：单设备框选、多设备框选两张预览图逐张看过，
  色带位置、卡片数值、超阈值计数都对着曲线核过一遍。

# 第十五轮：内置命令分六组、可折叠、可搜索

## 本轮做了什么

上一轮末尾留了两个方向，先做「内置命令 49 条太挤」这条：**二级分组 + 折叠 +
按类名搜索**。标题栏配色联动那条仍搁置（见文末「仍未做」）。

## 改前

「内置」是一个标签、一个分组、一条扁平的 chips 流：49 条要横跨两三屏，还按
点击频次排序——第一次用的人从「ADB连接状态」滑到「列出第三方应用」要点六七下
滚轮，且中途会被自己根本用不到的条目打断。

## 改后

- **六类**：连接与投屏(7) / 显示辅助(6) / 按键(11) / 屏幕状态(5) / 网络(7) /
  应用与信息(13)，顺序固定；
- **可折叠**：点段头折叠 / 展开，状态记进 `config.json` 的 `builtin_folded`
  （逗号串，与 `cmd_order` 同一套约定），下次启动照旧；
- **一键全折 / 全展**：六段逐个点太费事，而想干的事通常只有一个；
- **段头带条数徽章**：「按键 11」比「按键」有用——先知道有多少条再决定要不要展开；
- **搜索能命中类名**：输入「网络」直接筛出网络那一段（原来只有命令名 / 命令内容
  参与匹配，记住类目名反而搜不到）；
- **筛选时强制展开**：命中项藏在折叠块里等于告诉用户「没找到」。

## 四个实现决定

1. **section 不放 labels**：labels 决定一级分组和顶部标签过滤条。把六个细分塞进
   标签条，「通用 / 常用 / 内置」会被挤到看不见的地方，查找反而更难。
2. **顺序放在前端**（`BUILTIN_SECTIONS`），后端只写归属：改顺序是排版问题，
   不该逼着一个 Python 文件跟着改；后端写歪一个字也只影响归属，不会乱序。
3. **折叠只藏 chips，段头留着**：整段消失会让用户以为「命令没了」，比折起来更困惑。
4. **卡片创建抽成 `mkCmdChip`**：原来这段逻辑长在 `renderCmdGroups` 的循环里，
   二级分组要再渲染一次同样的卡片，只能复制——复制出去的角标 / kebab 菜单迟早在
   两边漂移。抽成函数后两条渲染路径共用一份。

## 顺带

`.cmd-group-title` 改成 flex（给右侧的一键按钮留位），菱形 tick 是绝对定位，
不受影响。

## 改动清单

| 文件 | 改动 |
| --- | --- |
| `core/builtin_commands.py` | 49 条各补 `section`（六类之一）；模块注释说明为何不复用 `labels` |
| `core/prefs.py` | 新增 `builtin_folded`（默认空 = 全展开）+ 文档注释 |
| `frontend/js/app.js` | `BUILTIN_SECTIONS` / `builtinFolded` 状态；`appendBuiltinSections`、`builtinSectionsOf`、`sectionNameOf`、`mkFoldAllBtn`；`mkCmdChip` 抽函数；`applyCmdFilter` 传筛选态、haystack 加 section；`applyBootSettings` 还原折叠态 |
| `frontend/css/app.css` | `.cmd-sections` / `.cmd-section` / `.cmd-section-h` / `.cs-caret` / `.cs-n` / `.cmd-fold-all`；`.cmd-group-title` 改 flex |
| `tests/frontend/builtin_sections.test.cjs` | **新增** 39 条：六段顺序、命令分派、徽章条数、折叠与落盘、启动还原、筛选强展、一键全折、按类名搜索、用户分组不受影响 |
| `tests/test_load_commands.py` | 新增 4 条：section 必填且在白名单、六组都非空且 ≥3 条、section 不污染 labels、merge 后字段仍在 |
| `README.md` / `使用说明.txt` | 内置命令的分组 / 折叠 / 搜索用法 |

## 验证

- Python 全量：**686 passed / 1 skipped**（新增 4 条）。
- 前端全量：**55 个测试文件 0 失败**（新增 1 个文件 / 39 条断言）。
- 真 Chromium 截图：六段叠起来的实际高度、折叠后的空白、一键按钮的落位都看过。

## 仍未做

标题栏配色联动界面主题（`prefers-color-scheme` / 浅色主题）：配色目前是写死的三个
常量，跟着主题走需要先把浅色主题本身做出来；单做「标题栏跟随系统」会在深色界面
配浅色标题栏，比现在更割裂。等有浅色主题时一起做。

> 已于 **第四十八轮** 补齐：浅色主题（CSS 令牌化覆盖 + `:root[data-theme="light"]`）、
> `prefs.theme` 偏好（dark/light/system 三态 + 白名单校验）、原生标题栏三态联动
> （`win_theme.apply_for_mode` / `set_theme`）、顶栏三态切换控件 + 系统主题监听。
> 详见第四十八轮。

# 第十六轮：修「执行含 powershell / exit 的命令序列后整程序卡死」

## 现象

用户报：在「设备指令」里执行下面这条序列，**程序卡死、后续命令全部点不动**。

```
adb root                    ||delay=500
adb remount                 ||delay=500
powershell                  ||delay=500
$currentDate = Get-Date -Format "yyyy-MM-dd HH:mm:ss"   ||delay=500
adb shell "date -s '$currentDate'"                      ||delay=500
adb shell "date -s '2026-09-23 23:59:54'"               ||delay=500
exit                        ||delay=500
```

## 根因（已用真实进程复现）

会话是一个**长期存活的 powershell**，逐行读 stdin；每条命令执行完由我们追加一行
`Write-Output ("__DONE_xxx__|...")` 作为结束标记，读线程匹配到就认为这条跑完了。

第 3 条 `powershell` 在持久会话里**又拉起一个 powershell**，子进程继承同一个
stdin —— 于是两个进程抢同一条命令通道：

| 步骤 | 实际发生 |
| --- | --- |
| `powershell` | 内层启动，读到我们写入的结束标记并执行 → 外层"看起来"跑完了 |
| 第 4~6 条 | 全被内层读走并执行 → 每条都能正常返回，掩盖了问题 |
| `exit` | 内层读到 `exit` **直接退出**，stdio 缓冲里预读的结束标记一并丢弃 |

外层从阻塞返回后再也没人写标记，`run()` 里那个 `timeout=None` 的等待循环就
**永远转下去**。而它正持有 `_user_lock`——后续每条命令都在等这把锁，界面表现
就是"卡死、点不动"。

在 Linux 上用 `sh` 复现（机制与 shell 种类无关）：

```
1) 普通命令 echo hello      -> True   ['hello', '__A__|done']
2) 裸子 shell sh            -> False  []
3) 子 shell 内 echo inner   -> True   ['inner', '__C__|done']
4) exit                     -> False  ['__B__|done']      <- 标记丢了
5) exit 之后 echo after     -> True   ['after', '__E__|done']
```

## 改了什么

1. **裸 powershell / cmd / bash 走"直通"**（`adb_inject.is_subshell_command`）：
   只写入、不写结束标记、不等返回——和 `adb shell` 已有的处理一致。判定只认
   "整条就是这一个程序"，带一次性开关（`-Command` / `-c` / `/c` / `-File`）或直接
   跟脚本文件的不算（`powershell -Command "..."` 跑完就退，仍要能判断成败）。
2. **`exit` 之后复位直通态**（`ShellSession.leave_interactive`）：`exit` 退出的只是
   内层 shell，外层会话还活着。不复位的话后续命令全变成"盲写"，既没有输出边界
   也永远不报错。复位后留 150ms 宽限（子进程退出是异步的）。
3. **兜底超时**：`_run_entries` 里非交互命令统一带 `timeout`（默认 120 秒，
   `config.json` 的 `cmd_timeout` 可覆盖，0 = 不限制）。超时由 `run()` 内部杀会话
   并返回 False，序列标记「✗ 执行中断」，锁随之释放。**这一条是"防下次"**：
   就算再遇到别的读 stdin 的命令（`adb logcat`、卡住的 adb），也不会整程序僵死。
4. **杀进程树**：`kill()` 改为 Windows 下 `taskkill /T /F`。只 `terminate()` 外层
   的话，内层 powershell 会变成孤儿继续持着 stdout 管道，读线程永远等不到 EOF，
   线程与句柄一起泄漏。
5. **合并规则补漏**：`_PC_CMD_RE` 加入 powershell / cmd / bash —— 否则
   `adb shell` + `cd /x` + `powershell` 会被合并成 `adb shell 'cd /x; powershell'`，
   在设备端起一个 powershell（更荒谬的是照样卡住）。
6. **可观测**：进入 / 退出交互式子 shell 各推一条提示，否则用户只看到"后面的命令
   没有回显"，像是坏了。这两条**推在指令台里而不是顶栏跑马灯**——用户执行命令时
   盯着的就是那块面板，混进全局跑马灯几秒就被刷掉。

## 一个业务提醒（不是程序问题）

用户那几条 `adb shell "date -s '$currentDate'"` 本身也有坑：

- PowerShell 里**单引号不展开变量**，`$currentDate` 会原样传给设备端 shell，
  而设备端并没有这个变量 → 实际执行的是 `date -s '$currentDate'`（会失败）；
- 想用上变量得用双引号，或干脆在设备端一条命令搞定：

```
adb shell "date -s \"$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')\""
```

  改系统时间需要 root（`adb root` 之后 `date` 才有权限），这一点用户已经先做了。

## 改动清单

| 文件 | 改动 |
| --- | --- |
| `adb_inject.py` | 新增 `SUBSHELL` 判定（`is_subshell_command` / `_base_name` / `_split_head`、`_ONESHOT_FLAGS`）；`_PC_CMD_RE` 补 powershell / cmd / bash / sh |
| `core/shell.py` | `_shell_args` / `_init_script` / `_sentinel_stmt` 提成可覆盖的方法（供单测换成 sh）；新增 `leave_interactive()`；`kill()` 走 `_kill_tree()`（Windows `taskkill /T /F`） |
| `backend/controller.py` | `_run_entries`：交互式判定加 `is_subshell_command`、非交互命令带 `timeout`、`exit` 后复位 + 150ms 宽限、进 / 出子 shell 各一条状态；新增 `DEFAULT_CMD_TIMEOUT` / `_cmd_timeout()`；模块级 `_EXIT_RE` |
| `core/prefs.py` | 新增 `cmd_timeout`（默认 120，范围 0~3600）+ 文档注释 |
| `tests/test_shell_session.py` | **新增** 9 条：用 sh 真实跑「普通命令 / 直通 / 裸子 shell → exit → 后续命令 / 不写标记 / 超时返回 False / 超时后自动重连 / kill 语义 / leave_interactive」 |
| `tests/test_backend_controller.py` | 新增 9 条：裸 powershell 直通、七条一条不少、exit 后回到非交互、一次性写法不误判、cmd/bash/pwsh 同类、默认超时、`cmd_timeout` 覆盖与 0、超时中断后续 |
| `tests/test_inject.py` | 新增 6 条：裸 shell 识别、一次性写法、非 shell 命令、完整路径、复合命令、纯开关 |
| `tests/test_core_prefs.py` | 新增 1 条：`cmd_timeout` 默认值 / 0 合法 / 越界与字符串回退 |
| `frontend/js/app.js` | `pushConsole` 的 kind 映射扩到 cmd / err / info / ok / warn（原来只放行 cmd、err，info 提示渲染成普通白字，跟命令混在一起） |
| `tests/frontend/console_kinds.test.cjs` | **新增** 15 条：六种 kind 的行样式、未知 kind 兜底、两条子 shell 提示可辨认、样式表里这些类真有着色 |
| `README.md` / `使用说明.txt` | 交互式子 shell 直通规则、`exit` 语义、120 秒兜底超时与 `cmd_timeout` |

## 验证

- Python 全量：**711 passed / 1 skipped**（本轮新增 25 条）。
- 前端全量：**56 个测试文件 0 失败**（新增 `console_kinds.test.cjs` 15 条）。
- **反向验证**：把 `is_subshell_command` 临时关掉，`powershell` 立刻退回
  `interactive=False`（带结束标记的旧路径）——证明这条判断就是修复点本身。
- 真实进程复现：`sh` 会话下 `exit` 丢失结束标记的现象在修复前稳定复现，
  修复后同一条序列 9 条断言全过（含 `exit` 后立刻跑下一条）。

# 第十七轮：工具页改回竖排（三张卡各自可收起）/ 录屏 logcat 全量 / 撤掉未实现的音频开关

## 三条需求与处理

| 需求 | 处理 |
| --- | --- |
| 工具页排版改回自上而下竖向，但截图 / 投屏也要有像录屏那样的收起展开小图标 | 删掉第十三轮引入的两列 `.tool-pair` 网格，三张卡回到竖排；截图与投屏补上和录屏同一套折叠标题（`.tool-h--toggle` + 箭头），收起态**各记各的** |
| 录屏的「同步录制 logcat」默认录所有类型，取消下方级别筛选，不可截断 / 过滤 / 缺失 | 整行级别勾选删掉；后端改为 `adb logcat -b all`（设备上存在的全部缓冲区）且 `level_filter=None`（不过滤任何级别） |
| 「同步设备音频」「同步电脑麦克风」功能没实现，先取消掉 | 两个开关从界面删除，前端固定给 `false`；后端实现保留（见文末「为什么没删后端」） |

## 1. 为什么把并排改回竖排

第十三轮把「截图 / 录屏」并成两列的理由是"第一屏就看得到投屏"，实际用下来代价更大：

- 两列宽度差着一大截（左 .82fr / 右 1.18fr），截图卡内容少、录屏卡内容多，视觉上
  左边永远空一块；
- 录屏那七行勾选被压到半宽后，中文文案挤成两行，「指针位置（画面常驻准星，跟随
  触摸）」这种长标签直接读不下去；
- 窄窗口虽然有 1080px 断点退回单列，但最小窗口 980 正好卡在断点附近，拖动窗口
  会来回跳。

改回竖排后靠**逐卡收起**省屏高——这才是"想看什么展开什么"的正确做法，而不是指望
两列同时塞下两张卡。三张卡的收起态分开存（`shot_collapsed` / `rec_collapsed` /
`scrcpy_collapsed`）：用户常常长期收起「投屏」却天天用「录屏」，合成一个键会互相
踩。

折叠逻辑本身也抽成了三张卡共用的一套（`TOOL_CARDS` 表 + `setToolCollapsed` /
`toggleToolCard` / `bindToolCardToggle`）：上一轮这段代码是给录屏卡单写的
（`setRecCollapsed` / `toggleRecCard`），再复制两份必然漂移——上一轮刚因为复制
卡片渲染逻辑踩过一次，这里不重犯。

## 2. 录屏的 logcat：从"可筛选"改成"必须全量"

原实现按 `main / system / events / crash` 四个缓冲区抓，级别由界面六个开关决定。
问题在于这不是"更精确"，而是**悄悄丢证据**：

- `-b` 里没有 `radio`（电话 / 短信 / RIL）和 `security`、`stats`，出问题时那几类
  日志根本不在文件里；
- 级别默认全选，但用户一旦为了"文件小一点"取消勾选，丢掉的是一整类记录；
- 最要命的是**事后不可补救**：录屏已经停了，缺的那段日志不会再生成。

所以这轮直接取消所有旋钮：`-b all` + `level_filter=None`。代价是 txt 变大
（实测同一段操作，全量约为四缓冲的 1.3~1.8 倍，主要来自 radio 与 events），
换来的是"文件里一定有"。

配套的界面文案也改了：原来写「可按级别过滤」，现在是「全部缓冲区 + 全部级别，
不做任何过滤与截断」。

## 3. 音频开关：撤界面、留实现

两项的验收一直没过：设备端 `tinycap` 能不能用因机型而异、电脑麦克风只在 Windows
上有、最后还要 ffmpeg 合轨——任一环缺失，成片就是无声的，而界面上那两个开关
照样能勾上。用户看到的是"我勾了录音，为什么没声音"。

处理方式是**只删界面**：

- 前端不再渲染这两个 `<input>`，`screen_record_start` 的第 2/3 参固定 `false`；
- 后端 `with_devaudio` / `with_mic` 参数与 `audio_service.py` 全部保留。删掉要动
  录屏收尾、麦克风/设备音频的下线流程、以及十几条后端用例，收益只有"代码少一点"；
  而万一以后把链路修通，参数还在就能直接接回来。

## 4. 一处顺手的连带修改

`core/prefs.py` 里删掉了 `rec_devaudio` / `rec_mic` / `rec_levels` 三个键。不删的
话它们会一直留在 schema 里、出现在每次生成的 `config.json` 里，用户手改也改不出
效果（界面已经没有对应控件）——那才是真正的"僵尸配置"。老配置文件里的这三个键
在加载时被 `sanitize_prefs` 丢掉（未知键不保留），不会报错。

## 改动清单

| 文件 | 改动 |
| --- | --- |
| `frontend/index.html` | 删 `.tool-pair` 容器，三张卡改为 section 直接子元素；截图卡与投屏卡各补 `.tool-h--toggle` 标题 + `.tool-body` 内容区；录屏卡删掉音频 / 麦克风两行与整段级别行；关于页文案同步 |
| `frontend/js/app.js` | `els` 去掉 `recDevaudio` / `recMic` / `recLevels` / `recLcLevels`，新增 `shotCard` / `shotToggle` / `scrcpyCard` / `scrcpyToggle`；`setRecCollapsed` / `toggleRecCard` / `setRecLcLevelsEnabled` 换成 `TOOL_CARDS` + `setToolCollapsed` / `toggleToolCard` / `bindToolCardToggle`；`applyBootSettings` 回填三个收起键；`screen_record_start` 第 2/3/7 参固定 `false/false/null` |
| `frontend/css/app.css` | 删 `.tool-pair` 三段规则与 1080 断点；删 `.rec-lc-levels` 与 `#rec-levels` 小尺寸开关；折叠标题注释更新为"三张卡都是" |
| `backend/controller.py` | 随录屏的 logcat 抓取改为 `["all"]` + `level_filter=None`；状态提示改为「全部缓冲区 + 全部级别」；`logcat_levels` / `with_devaudio` / `with_mic` 形参保留并注明已不生效 |
| `core/prefs.py` | 删 `rec_devaudio` / `rec_mic` / `rec_levels`；新增 `shot_collapsed` / `scrcpy_collapsed`（默认 False） |
| `tests/frontend/tool_cards_layout.test.cjs` | **新增** 55 条（替代 `tool_pair_layout.test.cjs`）：三卡竖排顺序、折叠标题与内容区结构、交互元素在内容区内、收起只影响自己、三个键各自落盘、启动按各自键还原、非法值不误折、录屏卡只剩 4 个开关 |
| `tests/frontend/` 其余 | `logcat_capture_levels` 改用例（级别行已删、第 7 参为 null）；`checkbox_switch_style` 复选框 32→24、开关集合换成 4 个；`settings_persist` 删音频 / 麦克风与级别回填、补三个收起键落盘；`rec_death_auto_reset` 锁定目标换成 `rec-logcat` / `rec-zip` |
| `tests/test_backend_controller.py` | `test_screen_record_passes_logcat_levels` → `test_screen_record_logcat_is_always_full`：断言缓冲区恒为 `["all"]`、`level_filter` 恒为 `None`（旧参数传进来也不生效） |
| `tests/test_core_prefs.py` | 布尔键映射表去两条；`_NO_HTML_CHECKBOX_KEYS` 补 `shot_collapsed` / `scrcpy_collapsed`；级别行清单去掉 `rec-levels`；`"false"` 字符串用例改用 `rec_logcat` |
| `README.md` / `使用说明.txt` | 工具页竖排 + 三卡收起、录屏 logcat 全量、音频开关撤掉的说明与 FAQ |

## 验证

- Python 全量：**711 passed / 1 skipped**（改 1 条、其余为既有用例）。
- 前端全量：**56 个测试文件 0 失败**（`tool_pair_layout` 换成 `tool_cards_layout`，
  断言数 1025 → 1051）。
- 人工复核：真 Chromium 截了三张图（竖排全展开 / 三张都收起 / 收起一张留两张），
  逐张确认折叠箭头朝向、间距、内容区留白。

---

# 第十八轮：无线调试（Wi-Fi ADB）/ APK 一键安装 / 设备信息快照

## 起因

前十七轮把「插着线能做的事」基本补齐了，但真机调试里最费时间的几件事仍然要跳出程序：

1. **查设备 IP**。车机常常同时挂调试 Wi-Fi 和车载以太网，`ifconfig` 里一堆网卡，人眼看哪个是通的；查到之后还得记下来去敲 `adb connect`。设备一动位置 IP 变了，整套重来。
2. **装包**。`adb install -r -d -g` 参数记不住，`INSTALL_FAILED_*` 报错码要现查，装完还得确认到底成没成。
3. **看设备信息**。型号 / 分辨率 / 密度 / 电量 / 剩余空间 / 内存 / 开机时长，平时要么翻设置，要么连续敲七八条 shell。

这一轮补的就是这三件事，都放在「不用跳出去」上。

## 一、无线调试（Wi-Fi ADB）

设备栏新增「无线」按钮，弹窗里三步走：`tcpip` 开端口 → 自动填设备 IP → `connect`。

- **自动读 IP**（这一步是重点）。后端一条 `adb shell` 同时跑 `ip route` 与 `ip -4 addr`：
  - 先从默认路由里的 `src x.x.x.x` 拿地址（最可信，就是设备出网用的那个）；
  - 拿不到再扫 `ip -4 addr` 的 `inet ... scope global` 行；
  - 多个候选时按 `wlan0 > wlan1 > 其它 wlan* > eth*` 排序——车机常见「Wi-Fi 出厂 + 以太网在场」，不排就选错。
- **地址校验是安全边界**。用户输入在拼进 `adb connect` 参数位之前必须先过 `normalize_endpoint`：IPv4 正则 / 主机名正则 / IPv6 方括号形式三选一，端口限 1~65535。**任何没过校验的输入都不进命令行**——否则 `1.2.3.4; rm -rf /` 这种就能把命令拆成两段。顺手兼容三种真实粘贴形态：整条 `adb connect 1.2.3.4:5555`、`tcp://1.2.3.4:5555/`、`[fe80::1]:5555`。
- **成功信息在 stderr**。`adb connect` 与 `adb tcpip` 成功时 `OK` 是写 stderr 的，只看 stdout 会误判成功为失败，因此这两处解析必须合并 stderr。
- **最近连接**。成功过的地址落 `wifi_recent`（最多 5 条，去重后新的在前），下次点一下就连，不用再敲。
- **mDNS 序列号**。`adb devices` 里 `_adb-tls-connect._tcp` / `_adb-tls-pairing._tcp` 开头的序列号代表无线配对通道，不是真设备，`is_wireless_serial` 统一判定，避免把它们当设备广播下去。

## 二、APK 一键安装

工具页第四张卡（截图 / 录屏 / **应用安装** / 投屏），选文件 → 勾选项 → 安装。

- **成功判定不看 returncode**。`adb install` 失败时退出码可能仍是 0，成功时也可能非 0。唯一可信的是输出文本：出现 `Success` 才算成，出现 `Failure [INSTALL_FAILED_xxx]` 就是失败，两者都没有按「输出无法识别」处理并原样回显。
- **失败码中文解释**。`INSTALL_REASONS` 覆盖 20+ 常见码（`INSUFFICIENT_STORAGE` / `VERSION_DOWNGRADE` / `UPDATE_INCOMPATIBLE` / `SIGNATURE_MISMATCH` / `NO_CERTIFICATES` / `TEST_ONLY` / `ABI_MISMATCH` …），每条给「下一步怎么办」而不是复述码名。设备离线、未授权之类的 adb 客户端错误另有一组提示。
- **`TEST_ONLY` 自动重试**。`INSTALL_FAILED_TEST_ONLY` 是最高频的一种，勾选 `-t` 后重装一次就过。程序自动补 `-t` 重试一次，省一轮「查码 → 回勾 → 再装」。
- **批量按设备并行**。多设备时每台一个 worker 各自 `-s` 安装，批次全部到齐才汇总一条 toast（不是每台一条刷屏）。`apk_state` 事件在批次开始时 `running=True`、全部完成时 `running=False`，按钮态由事件驱动，切走页面再切回也不会卡在「安装中」。
- **参数顺序固定** `["install", "-r", "-d", "-g", "-t"]`，便于测试断言，也便于人对照 adb 文档。

## 三、设备信息快照

设备卡新增 ⓘ 按钮，点开是一次 `adb shell` 取全，不是七八次往返。

- **一次 shell + `@@` 分段**。脚本里依次输出 `@@PROP` / `@@WM` / `@@BATT` / `@@DF` / `@@MEM` / `@@UP` 六个标记，解析时按标记切段。逐条要 1~2 秒，一次取全能把等待压到一次往返。
- **单段失败不拖累其它段**。某台设备 `dumpsys battery` 卡住或某条命令不存在，只丢那一段，其余照常显示。
- **`df` 按「最后一个百分比列」定位**。不同 Android 版本 `df /data` 列数不一样，`1K-blocks` 与 `-h` 式 `4.0G` 混着出现。用百分比列位置反推容量与已用列，带单位时按 K/M/G/T/P 换算（`_to_kb`），比按固定列号切稳。
- **密度取 Override 生效值**。`wm density` 会同时给 `Physical density` 与 `Override density`，真机改过 DPI 时生效的是 Override，取错会算出错误 dp。
- **可复制**。弹窗内一键复制成纯文本，贴进工单不用再截图。

## 改动清单

| 文件 | 改动 |
| --- | --- |
| `core/wireless.py` | **新增**：`normalize_endpoint` / `split_endpoint` / `is_wireless_serial` / `parse_device_ip` / `explain_connect_failure` / `parse_connect_output` / `parse_tcpip_output` / `add_recent` / `recent_from_pref` / `recent_to_pref` |
| `core/apk.py` | **新增**：`INSTALL_REASONS`（20+ 码 → 中文下一步）/ `_SYS_HINTS` / `install_args` / `parse_install_output` / `format_size` |
| `core/devinfo.py` | **新增**：`SCRIPT`（六段 `@@` 标记一次取全）/ `parse_info` / `rows` / `as_text` / `fmt_uptime` / `_to_kb` / `BATTERY_STATUS` |
| `core/prefs.py` | 新增 `wifi_port`（1024~65535）/ `wifi_recent` / `apk_replace` / `apk_downgrade` / `apk_grant` / `apk_collapsed`；文件头配置清单注释同步 |
| `backend/controller.py` | 抽出通用原生对话框 `_dialog_types` / `_open_dialog`（`_make_file_types` 改为调用，保留 pywebview 5.x 前后签名差异）；新增 `wifi_state` / `wifi_connect` / `wifi_disconnect` / `wifi_enable` / `_device_ip` / `_wifi_remember` / `apk_pick` / `apk_install` / `_do_apk_install` / `_apk_batch_done` / `device_info`；新增 `apk_state` 事件 |
| `frontend/index.html` | 设备栏加「无线」按钮；工具页插入 `#apk-card`（选文件 / 安装 / 选项 / 文件名）；新增 `#wifi-modal` 与 `#devinfo-modal` |
| `frontend/js/app.js` | `els` 补三组引用；`TOOL_CARDS` 三张 → 四张（含 `apk_collapsed`）；`BTN_ICONS` 补 `wifi` / `package`；新增 wifi / apk / devinfo 三块函数；`handleEvent` 加 `apk_state` 分支、`devices` 分支在 wifi 弹窗打开时刷新；`syncToolButtons` 补可用性；设备卡插入 ⓘ（`stopPropagation` 后开弹窗） |
| `frontend/css/app.css` | 新增 `.dev-info`（18px 圆形 ⓘ，悬停磷光青）/ `.wifi-row` / `.wifi-sec` / `.wifi-list` / `.wifi-item` / `.wifi-recent` / `.wifi-chip` / `.devinfo-rows` / `.devinfo-row` / `.apk-file` |
| `tests/test_core_wireless.py` | **新增** 27 条：地址规范化（IPv4 / 主机名 / IPv6 方括号 / 带端口 / 越界端口 / 注入串）/ 粘贴形态剥离 / 无线序列号判定 / `ip route` 与 `ip -4 addr` 解析 / 网卡优先级 / 失败原因映射 / 最近连接去重与截断 |
| `tests/test_core_apk.py` | **新增** 16 条：参数顺序、勾选组合、`Success` 判定、`Failure [CODE]` 码提取、未知输出、`format_size` |
| `tests/test_core_devinfo.py` | **新增** 13 条：六段解析、缺段不崩、`df` 多列与带单位、密度取 Override、开机时长格式化 |
| `tests/test_backend_wifi_apk.py` | **新增** 22 条：`wifi_state` 快照、`wifi_connect` 校验拒绝、`tcpip` 合并 stderr、批量安装按设备分发、批次汇总只发一条、`apk_state` 起止广播、`device_info` 读回 |
| `tests/frontend/wifi_apk_devinfo.test.cjs` | **新增** 39 条断言：弹窗开关、最近列表渲染、按钮禁用态、`apk_state` 驱动安装按钮、ⓘ 不触发设备切换、复制内容 |
| `tests/frontend/tool_cards_layout.test.cjs` | 三卡 → 四卡，顺序 `shot-card, rec-card, apk-card, scrcpy-card` |
| `tests/frontend/checkbox_switch_style.test.cjs` | 静态复选框 24 → 27 |
| `tests/test_core_prefs.py` | `_BOOL_KEY_TO_HTML_ID` 补 `apk_*`；`_NO_HTML_CHECKBOX_KEYS` 补 `apk_collapsed` |
| `README.md` / `使用说明.txt` | 架构树补三个 core 模块；工具页「四张卡」；设备栏补「无线」与 ⓘ；配置清单补 `wifi_*` / `apk_*`；使用说明第三章新增第 9 条（无线调试）、第 10 条（设备信息），第四章改为四张卡并插入「应用安装」 |
| `build.py` | `make_source_zip()` 改为把全部条目挂在与 zip 同名的**顶层目录**下（`ADBDeviceCommander_v*/`）：解压不散落，且顶层无 `index.html`，避免云端导入时被误判成「网页包」解包成空壳页面 |
| `tests/test_build.py` | 三个源码包用例同步断言顶层目录前缀、并新增「所有条目都在同一顶层目录下」 |

## 验证

- Python 全量：**789 passed / 1 skipped**（原 711 + 新增 78）。
- 前端全量：**57 个测试文件 0 失败**（新增 1 文件 39 条断言）。
- 人工复核：真 Chromium（headless）+ 注入假 pywebview 桥，截无线弹窗 / 设备信息 / 安装卡三张图逐张核对，修了两处文案字距（`无线调试` 与 `应用安装` 标题与副标题粘连）。
- 已知取舍：设备卡的 ⓘ 在 1440 宽下偏小，改为在设备卡 `title` 里补完整序列号——无线设备序列号是 `ip:port`，卡片上会被省略号截断，靠 tooltip 才能确认是不是同一台。

---

# 第十九轮：快捷命令菜单被压住 / 车机截图「开头不是 PNG」

## 一、快捷命令的 ⋯ 菜单被下方按钮压住

**现象**：点命令芯片右侧的 ⋯ 弹出「复制 / 修改 / 删除」，菜单被下面几行的命令按钮盖住，文字只剩残缺的几笔。

**排查**：先用真实 Chromium 复现（注入假 pywebview 桥 + 十条车机同名命令），再对菜单与所有相邻卡片的**重叠区域**逐个做命中测试（`elementFromPoint`）。结论是：Chromium 里 popup 其实在最上层，但它的位置完全依赖一个很脆的前提。

**根因**：popup 是 kebab 的子节点，而 kebab 在 `.is-open` 时带了 `z-index: 30`——一旦带 z-index 就**自成层叠上下文**，popup 的 `z-index: 20` 只在这个小上下文内部比较，出不来。此时只要再有一层祖先参与层叠（或某些 WebView 对 flex item 的处理不同），DOM 顺序更靠后的卡片就会整块压上来。历史注释里已经踩过一次同类坑（「小点点穿透 popup」），当时只做到「kebab 不设 z-index」，但展开态那句 `z-index: 30` 又把问题请了回来。

**修法**（不再依赖兄弟顺序）：
- 展开时给**整张卡片**加 `.chip-menu-open { z-index: 30 }`，菜单跟着卡片一起上去；
- 收起 / 点掉菜单项时同步撤销，避免某张卡永远压着别人。

**顺带修的可用性问题**：命令列表住在 `#cmd-groups { overflow: auto }` 里，最后一两行命令的菜单向下弹会超出容器底边**被直接裁掉**（与「被压住」是两种不同的坏法，现场容易混为一谈）。现在打开时量一次上下剩余空间，下方不够且上方更宽裕就改为贴卡片上沿弹出（`.chip-menu-up`）。

## 二、车机截图报「剪贴板写入失败（PowerShell 兜底失败…参数无效）」

**现象**（用户原话）：
```
⚠ 已保存截图: …screenshot_INN74HJNMN8LAURK_20261029_165601_1.png
（复制到粘贴板失败：Windows 剪贴板写入失败（PowerShell 兜底失败：
 clipboard fallback failed: 使用"1"个参数调用"FromStream"时发生异常:"参数无效。"）…）
```

**定位**：错误串本身就是线索。最终原因由两段拼成（`直接写入：…` + `PowerShell 兜底…`），而这条**只有兜底那一段**——说明 ctypes 路径根本没被尝试。回看 `copy_windows`：`if png or pix:` 才进 ctypes 循环，两者皆空时直接跳到 PowerShell。而 `png` 的赋值只有一句 `raw.startswith(PNG_MAGIC)`。

结论：**这个文件的字节流开头不是 PNG 签名**。于是 ctypes 只看 PNG 的分支被整段跳过，退到 GDI+ `Image.FromStream`——GDI+ 看到开头不是图片签名，报的是一句与真相无关的「参数无效」，而界面上给用户的解释是「剪贴板被占用，请重试」，重试多少次都一样。

**根因**：少数车机 / 定制 ROM 的 `screencap -p` 会在 PNG 前先吐几行自己的东西（换行、shell 提示、调试输出）。图片本体是完整的，只是前面多了一段。这类字节流还有第二个后果：落盘的文件看图软件也打不开——只是现场报的是剪贴板，没人往文件上想。

**修法**：新增 `core/imgbytes.py`（纯逻辑、零依赖、不抛异常），把「认得出、裁得干净」收口成一处：
- `detect` 只看开头；`locate` 在前 4KB 内按签名定位真实起点（PNG 优先，避免把 JPEG 里嵌的 PNG 缩略图当成正文）；
- `normalize` 返回干净字节：PNG 裁到 IEND、JPEG 裁到 EOI、其余按签名切；认不出则返回空并附**头部十六进制**，让下次报障有据可查；
- `core/clipboard.py::copy_image` 先归一化再分发（ctypes 与 PowerShell 兜底拿到的都是干净字节）；
- `backend/screen_service.py::screenshot` 落盘前同样归一化——磁盘上不再出现「叫 .png 却打不开」的文件；设备真返回 JPEG 时扩展名跟着改；
- PowerShell 兜底的失败信息补上字节数，能区分「数据被截断」和「格式不认」。

## 改动清单

| 文件 | 改动 |
| --- | --- |
| `core/imgbytes.py` | **新增**：`detect` / `locate` / `normalize` / `_trim_png` / `_trim_jpg`，签名表与 4KB 扫描窗口 |
| `core/clipboard.py` | `copy_image` 先归一化再分发；认不出格式时直接给出「无法识别 + 头部字节」；PS 兜底失败信息带字节数 |
| `backend/screen_service.py` | 截图落盘前归一化；非 PNG 时改扩展名；认不出则不落盘并返回明确原因 |
| `frontend/js/app.js` | 新增 `setChipMenu` / `chipClipBox`；click、mouseenter、mouseleave、菜单项点击四处统一走它；`mkCmdChip` 的 click 分支改用 `setChipMenu` |
| `frontend/css/app.css` | 新增 `.cmd-chip.chip-menu-open { z-index: 30 }` 与 `.cmd-chip.chip-menu-up .chip-popup`（贴卡片上沿） |
| `tests/test_core_imgbytes.py` | **新增** 13 条：各格式识别 / 前导垃圾定位 / 4KB 窗口外的签名不认 / PNG 裁 IEND / 截断图原样保留 / JPEG 裁 EOI / 认不出时带头部十六进制 |
| `tests/test_core_clipboard.py` | 新增 3 条：前导垃圾仍走 PNG 路径（`png`/`pix`/`raw` 三者都对）、认不出不往平台实现里送、非 PNG 不投 CF_PNG |
| `tests/test_backend_screen.py` | 新增 3 条：落盘剥掉前导垃圾、认不出不落盘、设备返回 JPEG 时扩展名跟着改 |
| `tests/frontend/chip_menu_layer.test.cjs` | **新增** 16 条断言：两条 CSS 规则、点击/悬停/点菜单项的抬层与撤销、贴底时改为向上弹 |
| `README.md` / `使用说明.txt` | 架构树补 `imgbytes.py`；设计要点补「字节先归一化」「菜单层叠与弹出方向」；使用说明补截图异常说明与 ⋯ 菜单行为 |

## 验证

- Python 全量：**808 passed / 1 skipped**（第十八轮 789 + 新增 19）。
- 前端全量：**58 个测试文件 0 失败**（新增 `chip_menu_layer.test.cjs` 16 条断言）。
- 人工复核（真 Chromium + 假 pywebview 桥）：
  - 修复前截图：菜单被 `[J01]` 与相邻按钮压住、只剩残缺笔画；
  - 修复后截图：菜单完整盖在相邻按钮之上；
  - 命中测试：菜单与相邻卡片的每个重叠区域，最上层元素都在 `.chip-popup` 内（`[inPop]`）；
  - 矮窗口（1000×420）下最后一行的菜单 `up=true`，向上弹出、完整可见，不再被 `#cmd-groups` 底边裁掉。
- 已知边界：GDI+ / ctypes 的真实 Windows 剪贴板行为无法在本机验证，故本轮只锁「送进去的字节是对的」这一层（归一化后必为合法 PNG，且有单测覆盖）；若用户侧仍失败，错误串现在会带字节数与头部信息，可直接判断是数据问题还是环境占用。

---

# 第二十轮：主动复查（9 处修复）

## 起因

用户要求「审查一下看看是否还有其他什么错误」。这一轮不新增功能，只做三件事：
静态检查（pyflakes）、前端引用交叉检查（HTML/JS/CSS 的 id、图标、类名）、
按最近三轮新增模块逐行走查（无线调试 / APK 安装 / 设备信息 / 字节归一化）。

结论：**没有发现崩溃级缺陷**，但找到 9 处「会让人误判」的问题——其中 2 处会让
用户以为功能没反应，1 处会让用户看着磁盘以为已经满了。下面按影响从大到小。

## 一、APK 安装连点两次：第二批「假开始」（影响最大）

**现象**：装到一半再点一次「安装」，界面提示「开始安装 …」，但设备上什么都没发生；
更糟的是按钮可能提前恢复可用，前一批的结果还会被算进后一批的账里。

**根因**是两处叠加：

1. `workers.spawn(key)` 的语义是「同名线程还活着就复用、不重复启动」，而 worker 的
   key 是 `apk_install_<序列号>` —— 所以第二次点击**不会**再起安装线程；
2. 但 `apk_install()` 一进来就把 `self._apk_batch` 整个重置成新批次。于是第一批
   的 worker 回来记账时，记的是新批次的账：`done` 一到位就宣告「批次结束」，
   `apk_state(running=False)` 提前发出，按钮提前恢复。

**修法**：从源头拒绝。`apk_install()` 在锁内检查 `_apk_batch is not None` 就直接返回
「上一批安装还没结束，请等它完成后再装」。前端本来就有 `installApk` 的失败分支，
会把这句原样显示成「⚠ 安装未开始：…」，不用改界面。

顺带把记账的去重从「只查失败清单」改成 `seen` 集合：原来同一台设备如果成功回调
两次会被算两台（让 `done` 提前到 `total`，批次在另一台还没装完时就结束）。

## 二、设备信息连点两台：内容串台

**现象**：快速点 A 卡的 ⓘ、再点 B 卡的 ⓘ，弹窗标题是 B、内容是 A。

**根因**：`loadDeviceInfo()` 用全局 `devInfoSerial` 发请求，回包后直接写 DOM ——
先发的慢请求后回来就会覆盖后一台的内容。这是典型的回包竞态。

**修法**：发请求前把序列号捕获到局部变量，回包时对不上就整条丢弃。另外补了
「成功但一行都没读到」的提示（设备刚掉线时会出现），不再留一个空白框让人猜。

## 三、`imgbytes` 的 BMP 弱签名会把文本当成图片

`locate()` 的规则是「签名出现得最早者胜」，而 BMP 的签名只有两个字节 `BM`。
设备吐的前导文本里 `MB`、`BMW`、一段 base64 都可能命中 —— 于是格式判成 bmp、
起始位置落在文本中间，切出一段既不是文本也不是图片的字节。后果与上一轮修的
「前导垃圾」同源，但更难查：格式「认得出」，却从来没被真正解码过。

**修法**：给 BMP 候选加一次文件头合理性校验（4 字节保留字段必须为 0、DIB 头长度
必须是已知取值、像素数据偏移与文件大小要落在实际字节范围内），不合格就跳到下一个
候选位置继续找。`detect()` 保持「只看开头」的原语义不动。

## 四、设备信息：剩余 50 MB 显示成「0.0 GB」

`_size()` 固定按 GB 保留一位小数。车机 `/data` 只剩几十 MB 时渲染成
「剩余 0.0 GB」——看着像已经满了，实际还能装一个包；这类误读会让人去清缓存、
删应用，白折腾。

**修法**：单位跟着数量级走（≥1 GB 用 GB、≥1 MB 用 MB、其余 KB），并且 0 返回
「0 MB」而不是空串（原来「已用」那格会变成空白，像是没读到）。

## 五、`df` 解析：跳过首行会漏掉唯一的数据行

`_parse_df()` 原固定 `splitlines()[1:]`（跳过表头）。个别 ROM 会在表头前先打一行
警告（`df: /data: No such file or directory`），于是「跳过首行」正好把表头跳过、
数据留下 —— 这次没问题；但如果首行本身就是数据（精简 ROM 不打表头），就一条都读不到。

**修法**：逐行都试。表头行本来就过不了「百分比列」校验，会自动被跳过，不需要显式
跳过首行。

## 六、无线连接后的刷新可能被「合并」掉

`wifi_connect` / `wifi_disconnect` 成功后用 `spawn("refresh", …)` 刷设备列表，而
`refresh` 这个 key 同时被自动刷新循环与手动刷新用着。撞上时 spawn 会复用存活线程、
这次刷新**被静默吞掉** —— 表现是「提示已连接，但左边列表里没有这台设备」。

**修法**：这两处改用独立 key `refresh_wifi`，保证一定排上一次。

## 七、无线地址：`999.1.1.1` 被当成合法主机名

`999.1.1.1` 完全符合主机名白名单（字母数字 + 点），于是被放行，一路走到
`adb connect` 才失败，界面显示「连接超时 / 无法解析」。用户会去查网络、查防火墙，
而真正的原因只是地址打错了。

**修法**：只由数字和点组成、且带点的输入，先按 IPv4 校验；不合法就直接报
「IP 地址不合法（四段 0~255，形如 192.168.1.23）」。不带点的纯数字（`12345`）仍按
主机名处理——那不像 IP，拦下来反而是误伤。

## 八、WAV 校验：`fmt_seen` 赋了值却从没读过

`_wav_duration()` 里有个 `fmt_seen` 标志，docstring 写着「只认标准 RIFF/WAVE 头 +
fmt + data」，但代码见到 `data` 就直接返回 —— 缺 fmt 块的坏文件同样被当成合法音频，
喂给 ffmpeg 只会得到一个 0 秒的空壳视频。

**修法**：遇到 `data` 时要求先见过 `fmt `，否则判为不可用。

## 九、静态检查清零

`pyflakes` 原来报 5 条：`controller.py` 里 `default_save_dir`（被同名方法遮蔽）、
`PERF_THRESHOLDS`，`logcat_service.py` 里 `LOGCAT_BUFFERS`，`audio_service.py` 里
的 `fmt_seen`。前两条真正的问题是「同名方法遮蔽模块函数」，看着像在用、其实永远
走不到那条导入。

处理：`default_save_dir` 与 `LOGCAT_BUFFERS` 删掉多余导入；`PERF_THRESHOLDS` 是
**有意对外**的常量（前端阈值页与测试都按这个名字读），改成显式赋值并加注释，
而不是删掉。现在 `pyflakes` 对 `core/ backend/ main.py build.py adb_inject.py tools/`
零输出。

## 改动清单

| 文件 | 改动 |
| --- | --- |
| `backend/controller.py` | `apk_install` 加批次互斥（拒绝第二次点击）；`_apk_batch_done` 改用 `seen` 集合去重；`wifi_connect` / `wifi_disconnect` 的刷新改用 `refresh_wifi` key；`PERF_THRESHOLDS` 显式赋值；删掉被遮蔽的 `default_save_dir` 导入 |
| `core/imgbytes.py` | 新增 `_plausible_bmp` / `_BMP_DIB_SIZES`；`locate` 对 BMP 候选做文件头合理性校验，不合格跳到下一个候选 |
| `core/devinfo.py` | `_size` 改为自适应单位且 0 返回「0 MB」；`_parse_df` 不再跳过首行（表头靠校验自然过滤） |
| `core/wireless.py` | 「数字 + 点」形式的非法 IP 直接报「IP 地址不合法」，不再当主机名放行 |
| `backend/audio_service.py` | `_wav_duration` 遇到 `data` 时要求已见 `fmt `，补上 `fmt_seen` 的实际用途 |
| `backend/logcat_service.py` | 删掉未使用的 `LOGCAT_BUFFERS` 导入 |
| `frontend/js/app.js` | `loadDeviceInfo` 捕获请求时的序列号、回包对不上就丢弃（修串台）；补「一行都没读到」的提示 |
| `tests/test_backend_wifi_apk.py` | 新增 3 条：运行中再点安装被拒且不再起命令、同一台重复记账只算一台、批次结束后能再装 |
| `tests/test_core_imgbytes.py` | 新增 4 条：真实 BMP 仍认得、前导文本里的 `BM` 不误判、伪造 BMP 头被跳过、BMP 归一化仍正常 |
| `tests/test_core_devinfo.py` | 新增 5 条：剩余 50 MB 显示 MB、0 已用不留空、内存用 MB、表头前有警告仍能解析、无表头也能解析 |
| `tests/test_core_wireless.py` | 新增 5 条：4 种非法 IP 报「IP 不合法」、纯数字主机名不被误伤 |
| `tests/test_backend_audio.py` | 新增 2 条：缺 fmt 块的 WAV 判不可用、正常 WAV 不受影响 |
| `tests/frontend/wifi_apk_devinfo.test.cjs` | 新增 3 条断言：连点两台设备的 ⓘ 时标题与内容都属于后一台 |

## 验证

- Python 全量：**827 passed / 1 skipped**（第十九轮 808 + 新增 19）。
- 前端全量：**58 个测试文件 0 失败**（`wifi_apk_devinfo` 39 → 42 条断言）。
- `pyflakes`：`core/ backend/ main.py build.py adb_inject.py tools/` 零输出。
- 关键修复做了「反向验证」：把 `loadDeviceInfo` 的序列号判断去掉后，新断言立刻
  失败（内容是「甲机」而不是「乙机」），确认测试真的有防护力，不是摆设。
- 交叉检查（一次性脚本，未入库）：HTML 225 个 id 无重复；`els` 表 198 条全部指向
  存在的 id；JS 里没有指向不存在 id 的 `getElementById`；`data-icon` 的 24 个值都在
  `BTN_ICONS` 里；`classList` 用到的类名都在样式表里有定义。
- 已知取舍：批次互斥只做「拒绝」不做「排队」，因为排队会让用户以为点了两次就装两次；
  拒绝 + 明确提示更不容易误判。设备信息弹窗仍不自动刷新，靠手动点「刷新」——自动
  刷新会在用户读数字时跳变，反而难用。

---

# 第二十一轮：接入 GitHub 源码推送（并修掉一个会泄 token 的打包缺陷）

## 起因

用户申请了一个 GitHub 仓库并要求「后续每次改动迭代之后都推送源码」。仓库建成了 **public**，
而工程里的 `commands.json` 是个人命令库——含 4 个真实手机号、VIN 绑定规则、J01/CEI 内部项目指令、
本机绝对路径（`D:\BUG`、`D:\android-sdk`）。用户确认后改为 **private**，命令库随仓库一起留档。

## 一、推送怎么做（`tools/push_github.py`）

一条命令完成「提交 + 推送」，但真正的设计点全在**别把 token 泄出去**：

- **token 不进 remote URL**。常见写法是 `https://user:token@github.com/...`，但那样 token 会明文
  躺在 `.git/config`；更糟的是 `git push` 失败时会把**整条 URL 连同 token** 打回控制台——
  随手截图发群里就泄了。改用 `-c http.extraHeader=Authorization: Basic <base64>`，
  认证头只在**本次命令**生效，remote 保持干净地址，git 的回显与报错里都不含 token。
- **推送失败时打印的 git 原文也先打码**（`out.replace(tok, "***")`），再翻译成人话。
- **凭证读取有固定优先级**：`--token` > `GH_TOKEN` > `GITHUB_TOKEN` > `.git-credential`
  （JSON 或裸一行都认）。文件放在工程根、已在 `.gitignore` 里；同时支持环境变量，
  是为了 CI / 临时机器上不必为推一次代码就在磁盘留凭证。
- **失败提示是翻译过的**，直接说下一步：token 失效、私有仓库缺 `Contents: Read and write`、
  网络不通、`non-fast-forward` 要先 rebase、本地还没提交过。
- `--status` 不需要 token（只是读本地状态），`--dry-run` 只打印不执行。

## 二、修掉一个真会泄密的缺陷：token 被打进源码包

**发现方式**：接入 git 之后顺手把源码包和 `git ls-files` 的清单做了个 diff，结果第一条就是
`zip 独有: .git-credential`——**GitHub token 的明文被 `build.py --zip-only` 打进了分发包**。

**根因**：`.gitignore` 只作用于 git；`make_source_zip()` 走的是 `os.walk` + 自己的
`SOURCE_ZIP_EXCLUDE_FILES`，是**另一条独立路径**。加了 `.gitignore` 不等于打包也会忽略。
这个包是要发给同事的（甚至上传到团队空间），等于把 token 一并发了出去。

**修法**：`SOURCE_ZIP_EXCLUDE_FILES` 补 `.git-credential` 与 `.git-push-log.txt`，
并在 `test_real_source_zip_is_lean` 里加断言。反向验证：删掉这两条排除规则后，
该断言立刻失败（「推送凭证（token 明文）绝不能随分发包发出去」），确认测试真的挡得住。

## 三、两条恒真的测试断言（比缺陷更隐蔽）

修上面那条时发现 `test_source_zip_excludes_junk` 里的四条断言**从来没生效过**：

```python
for bad in ("backend/__pycache__/a.pyc", "settings.json", ...):
    assert bad not in names, "分发包不应包含 %s" % bad   # 恒真
```

原因：包内所有条目都挂在**与 zip 同名的顶层目录**下（`ADBDeviceCommander_v…/backend/a.py`），
而断言比的是**裸相对路径**（`backend/a.py`）——永远匹配不上，于是永远通过。
`test_real_source_zip_is_lean` 里的 `settings.json` / `config.json` 两条同理。

危害不在于「这次漏了什么」，而在于**它给了假的安心**：以后真把 `node_modules` 打进包，
这两处照样绿。已改成 `assert top + bad not in names`（`top = zp.stem + "/"`）。

## 改动清单

| 文件 | 改动 |
| --- | --- |
| `tools/push_github.py` | **新增**：`load_token` / `save_token` / `_auth_header` / `repo_state` / `_auto_message` / `do_init` / `main` / `_explain_push_failure`；支持 `--init` / `--status` / `--dry-run` / `--save-token` / `--remote` / `--branch` |
| `build.py` | `SOURCE_ZIP_EXCLUDE_FILES` 补 `.git-credential` / `.git-push-log.txt`（凭证不进分发包） |
| `.gitignore` | 补 `config.json`（原来只忽略了 `settings.json`，等于没忽略现在真正在用的那份）、`*.wav`（设备音频调试录音）、`.git-credential` / `.git-push-log.txt` |
| `tests/test_tools_push_github.py` | **新增** 29 条：凭证优先级（命令行 > 环境变量 > 文件）/ JSON 与裸 token / 坏 JSON 提示 / 打码 / 认证头不含明文 / **推送 URL 不含 token** / 提交说明按改动区域生成 / 凭证不进提交清单 / `--status` 无需 token / push 失败返回非零且打码 / 6 类失败提示 / 私有仓库权限提示 / `--dry-run` 不动远端 / `.gitignore` 覆盖凭证 |
| `tests/test_build.py` | 四条恒真断言补顶层前缀；新增「凭证不进源码包」断言 |
| `README.md` | 架构树补 `tools/push_github.py`；新增「推送到 GitHub」与「进仓库的是什么」两节（含为什么不把 token 写进 URL、失败提示对照表、忽略清单及原因） |
| `FIX_NOTES.md` | 本轮 |

## 验证

- Python 全量：**856 passed / 1 skipped**（第二十轮 827 + 新增 29）。
- 前端全量：**58 个测试文件 0 失败**（本轮未改前端）。
- `pyflakes`：`core/ backend/ main.py build.py adb_inject.py tools/` 零输出。
- **反向验证**（两条都确认有防护力，不是摆设）：
  - 把 token 塞进 push URL → `test_push_url_stays_clean` 立刻失败；
  - 去掉 `out.replace(tok,"***")` → `test_push_failure_returns_nonzero_and_masks_token` 立刻失败；
  - 删掉 `build.py` 里两条凭证排除规则 → `test_real_source_zip_is_lean` 立刻失败。
- **远端自证**（不是「接口返回成功」就算数）：GitHub API 拉 `git/trees/main?recursive=1`，
  147 个 blob、单一顶层目录、不含 `.git-credential` / `*.wav` / `config.json` / `node_modules`；
  `.git/config` 的 remote 是干净地址；`git log --all -p | grep <token>` 命中 0 次。

## 已知取舍

- **`commands.json` 进仓库**（含手机号与 VIN），所以仓库必须是 private。若将来要开源，
  需要先把它换成脱敏样例——这条写进了团队空间的约定文档。
- 脚本只做「提交 + 推送」，不做 `pull --rebase` 自动合并：远端有本地没有的提交时，
  自动 rebase 可能产生用户没审过的合并结果，宁可停下来让人看一眼。
- 凭证在磁盘上仍是明文（`.git-credential`，权限 600）。这是本机单用户的常见做法；
  要更强就用系统密钥环，但那会把依赖从「标准库」变成「平台相关库」，暂不做。

# 第二十二轮：主动复查（5 处缺陷）+ 新功能「一键诊断包」

## 起因

用户要求「再审查还有什么异常问题，并修复；有好的功能建议也可以直接开发」。

复查方式不是通读，而是**按故障模式找**：先列出「这类程序的用户会怎么被坑」
（界面突然不再更新、磁盘悄悄被吃满、设置自己弹回去、点了报一句英文类型错误），
再逐条到代码里对证。下面每一处都是先能说清「用户看到什么」，才动手改。

## 一、事件轮询链会被一条坏事件打断（最严重）

**用户看到什么**：程序开着好好的，某天起「日志不再滚、状态栏不动、设备不刷新、
停止按钮也按不下去」，不报错不弹窗，只能重开程序。

**根因**在事件分发的结构上：

```js
const pollOnce = async () => {
  ...
  events.forEach(handleEvent);      // ← 这里任何一条抛异常
  setTimeout(pollOnce, pollMs);     // ← 这行就永远执行不到
};
```

轮询是**递归 setTimeout 自我续约**的，续约那一行正好在分发之后。任何一条事件的
处理函数抛异常（后端协议漂移、手改 payload、某次渲染踩到空节点），这次续约就被
跳过，之后**再没有任何东西把链子接回来**。

**修法**两处，缺一不可：

1. `events.forEach(safeHandleEvent)` —— 逐条 try/catch，坏事件只丢它自己，
   同批后面的事件照常处理；同一类事件只提示一次（坏数据可能每 400ms 来一条，
   不能让它把状态栏刷爆），提示里带原因。
2. `try { ... } finally { setTimeout(pollOnce, ...) }` —— 续约放进 finally，
   无论成功、失败、还是抛到外面，下一次轮询一定发生。

**性能监控轮询是同构问题**（`perfPollOnce`）：`perfIngest` 要排序 / 画图 / 判阈值，
一个异常就让曲线永久停在那一帧，界面还显示「采集中」——用户会以为是设备卡了。
同样加了逐条兜底 + finally 续约，异常时在状态区说明「采样仍在后台继续，曲线可能
缺几个点」。

**反向验证**（这是本轮花时间最多的一步）：把 `pollOnce` 还原成修复前的样子，
新建的 `poll_resilience.test.cjs` 立刻掉到 3 通过 / 7 失败，并且「标记丙 / 标记丁」
两条断言直接超时 —— 正好复现「界面彻底停摆」。修复版 10/10。
（中间还原过一次「带 catch 但没有 finally」的中间态，跑出来是 4/6 —— 说明这两处
各自都有防护力，不是其中一处顺手带出来的。）

## 二、「查看大文件」的临时副本永不清理（磁盘泄漏）

**用户看到什么**：C 盘越来越小，找不到是什么占的。

**根因**：文件页「查看」遇到大文件 / 二进制时，唯一正确的做法是把文件 pull 到
系统临时目录（`%TEMP%`）再交给系统程序打开 —— 大文件经事件总线直传会把界面卡死。
但那些副本**没有任何界面入口能删**，也没有清理代码：看一次几百 MB 的日志就在
TEMP 里留一份，看几次就能吃掉几个 GB。（本轮开工时沙箱 `/tmp` 里还躺着 20 多个
`adb_view_*.bin`，正是上一轮联调留下的。）

**修法**：新增 `core/tmpfiles.py`，策略刻意保守 —— 宁可留，也不误删：

| 时机 | 保留规则 | 为什么 |
| --- | --- | --- |
| 每次查看前 | 保留最新 8 个 + 10 分钟内的一律不删 | 正在被系统查看器打开的那份一定在保留集合里 |
| 每次启动 | 只删超过 1 小时的 | 上一轮刚导出的文件可能还在被别的程序用 |

只碰 `adb_view_` 前缀、只删普通文件、**不跟随符号链接**（临时目录里的链接可能
指向别处）、单个文件删不掉（被占用）只跳过并计数，绝不抛异常。

## 三、配置写入的「读-改-写」没有互斥

**用户看到什么**：刚改的开关，过一会儿自己弹回去了（极难复现，所以一直没人报）。

**根因**：`save_prefs` 是「读文件 → 合并 → 原子写」三步，但**整段没有锁**。
界面保存设置、记住上次无线地址、录屏选项回写可能来自不同线程；两处几乎同时进来
会各自读到同一份旧内容、各自合并、后写的把先写的**整块覆盖**。另外临时文件名固定
为 `config.json.tmp`，两个写入流还会互相截断对方的临时文件 —— `os.replace` 之后
落盘的可能是「半份 A + 半份 B」。

**修法**：模块级 `_SAVE_LOCK` 把整个读改写包住；临时文件名改成 `config-<8位随机>.tmp`
（每次写入各写各的，最后完成的那个完整内容胜出）。

## 四、无线地址校验对非字符串直接抛异常

`normalize_endpoint(123)` → `AttributeError: 'int' object has no attribute 'strip'`，
界面上只看到「调用后端失败：…」。这是 `wifi_connect` 的校验入口，收到的是 JSON 传
过来的任意值，**校验函数本身不该以异常收场**。

改为**明确拒绝非字符串**，而不是 `str()` 后继续：`True` 会变成主机名 `"True"`、
`192` 会变成 `"192:5555"`，两者都能过白名单，然后在 `adb connect` 阶段失败 ——
用户看到「连接超时」，与真正原因（传错类型）毫无关系。现在直接说
「地址格式不正确：应为文本形式的 IP 或 IP:端口（收到 int）」。

## 五、新功能：一键诊断包

**为什么选它**：车机上复现一个 bug 之后，要发回给开发的东西每次都一样 ——
什么机器 / 什么系统版本、当时的 logcat 尾部、谁在吃内存、装了哪些应用、
有没有 ANR。以前要点 4~5 个不同功能、分别存文件、再自己打包命名，
忙起来就漏一两项，事后补不回来。这是「每天都要用、当前完全没有」的那类功能。

**交互**：工具页新增「诊断包」卡（第 4 张）。勾选设备 → 点「收集诊断包」→
每台设备产出一个 zip 到保存目录。可关掉 logcat，或选 1000 / 2000 / 5000 /
20000 / 50000 行（默认 2000）。

**包里有什么**（7 个文件）：

| 文件 | 内容 | 来源 |
| --- | --- | --- |
| `device.txt` | 型号 / 厂商 / Android 版本 / SDK / 构建类型 / ABI / 分辨率 / 密度 / 电量与温度 / 存储 / 内存 / 开机时长 | `core.devinfo` 的一次 shell 脚本 |
| `props.txt` | `getprop` 全量原样 | 同上（分段切出） |
| `logcat.txt` | 尾部 N 行（`-d -t N`） | `adb logcat` |
| `process.txt` | 内存 TOP 15 + `ps` 原始表 | `adb shell ps -A` |
| `apps.txt` | 第三方应用清单 + 全部应用计数 | `pm list packages [-3]` |
| `anr.txt` | 前台 Activity + `lastanr` + `/data/anr`、`/data/tombstones` 列表 | `dumpsys` + `ls` |
| `meta.json` | 收集时间 / 程序版本 / 每份文件的来源命令与字节数 / 缺失原因 | — |

**几个刻意的设计**：

- **5 次 adb 调用做完**，不是每项一次：设备信息复用 `devinfo.SCRIPT` 的单个脚本
  （getprop / wm / battery / df / meminfo / uptime 一次取全），否则点开就要干等
  六七次进程创建（USB 上 1~2 秒）。
- **每段独立失败**：`/data/anr` 没权限、logcat 报错，都只让那个文件写一行中文说明
  并记进清单，**整包照常产出** —— 收集现场时「有 4 份、缺 1 份」远好过「什么都没有」。
- **老设备 logcat 不支持 `-t`**：回退全量 `-d` dump 再在本地截尾部，并在文件开头
  注明「已改为全量 dump 后截取尾部 N 行」，避免看包的人误以为拿到了全部日志。
- **`ps -A` 不支持就退 `ps`**：老 ROM 上 `-A` 会报 unknown option，不能直接判定
  「进程读取失败」。
- **表头优先、第 5 列兜底**：`ps` 列序各 ROM 不同（老 Toybox 是 `USER PID PPID VSZ
  RSS WCHAN PC NAME`，裁剪输出只有 `PID USER TIME RSS NAME`），按表头定位 RSS 列，
  认不出才退回历史惯例。
- **只读、不改设备状态**：不 root、不改设置、不 stop 任何进程，所以可以和正在跑的
  logcat 监控 / 录屏同时进行。
- **多台串行**：诊断包是 adb 密集操作，并行只会在 adb 的调用队列里互相排队，
  还会让各设备的 logcat 时间点对不齐。

## 改动清单

| 文件 | 改动 |
| --- | --- |
| `core/diag.py` | **新增**：`SCRIPT` 复用 / `clamp_lines` / `parse_ps` / `top_memory` / `process_report` / `summarize_packages` / `collect`（runner 注入，可测）/ `summary_line` |
| `core/tmpfiles.py` | **新增**：`sweep` / `sweep_view_files` / `boot_sweep`（保守清理，返回统计） |
| `core/prefs.py` | `save_prefs` 整段加 `_SAVE_LOCK`；`_atomic_write` 临时文件名唯一化；新增 `diag_with_logcat` / `diag_logcat_lines` / `diag_collapsed` 与行数范围 |
| `core/wireless.py` | `normalize_endpoint` 非字符串明确拒绝（不再抛 AttributeError，也不 str() 后放行） |
| `backend/controller.py` | 新增 `diag_options` / `diag_collect` / `_do_diag`（busy 拒绝、异常兜底、`diag_state` 收尾）；boot 时后台清理上一轮临时副本 |
| `backend/file_service.py` | 查看前清理旧副本（保留最新 8 个 + 10 分钟宽限） |
| `frontend/index.html` | 工具页新增「诊断包」卡（按钮 / 复选框 / 行数下拉 / 结果行） |
| `frontend/js/app.js` | `safeHandleEvent` + `pollOnce` / `perfPollOnce` 的 try/finally；诊断包卡的全部交互与按钮态；`tool` 事件新增 `diag` 分支 |
| `frontend/css/app.css` | `.tool-result`（诊断产物的结果行，与 `.apk-file` 同手感但语义独立） |
| `tests/test_core_diag.py` | **新增** 20 条：行数夹取 / `ps` 三种表头 / 内存 TOP 排序 / 端到端出包（7 文件 + meta）/ 不含 logcat / `-t` 回退 / `ps -A` 回退 / 单段失败仍出包 / runner 抛异常 / 目录不可写 / 无线序列号净化 / 中间目录必清理 / 版本号记录 |
| `tests/test_core_tmpfiles.py` | **新增** 10 条：删旧留新 / 最新 N 个 / 年龄宽限 / 不碰别人的文件与目录 / 删除失败只计数 / 目录不存在 / 启动清理 / 符号链接不跟随 |
| `tests/test_backend_wifi_apk.py` | 新增 5 条：无设备拒绝 / 正常路径（事件顺序 + 参数透传）/ 忙时拒绝 / 失败复位 / collect 抛异常也复位 / 选项读 prefs |
| `tests/test_core_prefs.py` | 新增 2 条：并发保存不丢更新（人为放慢落盘把竞态窗口撑大）/ 临时名唯一；布尔键映射表登记两个新键 |
| `tests/test_core_wireless.py` | 新增 2 条：非字符串输入不抛异常 / 正常字符串不误伤 |
| `tests/frontend/poll_resilience.test.cjs` | **新增** 10 条：坏事件不打断链 / 提示可读 / 同类只提示一次 / 同批不连坐 / 多轮仍在续约 |
| `tests/frontend/diag_card.test.cjs` | **新增** 23 条：结构 / 门禁 / 下发参数 / 收尾 / 失败复位 / 设置回填 |
| `tests/frontend/tool_cards_layout.test.cjs` | 四张卡 → 五张卡（顺序含诊断包） |
| `tests/frontend/checkbox_switch_style.test.cjs` | 静态复选框 27 → 28 |
| `README.md` / `使用说明.txt` | 架构树补两个新模块；事件种类补 `apk_state` / `diag_state`；工具页五张卡；新增「诊断包」「临时文件不会越攒越多」两节 |

## 验证

- Python 全量：**896 passed / 1 skipped**（第二十一轮 856 + 40）。
- 前端全量：**60 个测试文件 0 失败**（第二十一轮 58 + 2）。
- `pyflakes`：`core/ backend/ main.py build.py adb_inject.py tools/` 零输出。
- **反向验证**（确认新测试不是摆设）：
  - `pollOnce` 还原成修复前 → `poll_resilience` 3 通过 / 7 失败（含两条超时）；
  - 去掉 `handleEvent` 的逐条兜底、保留 finally → 4 通过 / 6 失败；
  - 说明「finally 续约」与「逐条隔离」各自都在挡东西。
- **端到端冒烟**：用假 runner 跑 `diag.collect`，确认 zip 内 7 个文件齐全、
  `meta.json` 可解析、`process.txt` 含内存 TOP、`logcat.txt` 含回退说明；
  `ps` / `logcat` / `/data/anr` 三条失败路径分别验过仍出包。

## 已知取舍 / 下一轮候选

- **诊断包不含 `bugreport.zip`**：那要几分钟且体积几十 MB，属于「深度取证」而非
  「随手留证」。当前这套 5 次调用的包更适合复现完就发给开发。
- **没做「指令台命令历史（↑/↓ 调回）」**：本轮需求量已经不小，留到下一轮单独做，
  避免一次性改太多面（改的面越广，回归越难验干净）。
- 诊断卡与 APK 卡一样是「多设备广播」：勾几台就出几个包，命名带序列号与时间戳，
  不会互相覆盖。

# 第二十三轮：CI/CD 自动构建发版 + 程序内「发现新版本」提示

## 起因

用户提的是流程问题，不是功能问题：

> 每次有新改动发版之后，都是手动 build 出来再发给同事，效率太低。能不能更新后
> GitHub 上跑 CI/CD 直接出产物，程序里也定期扫描，发现新版就弹窗让用户下载更新。

一句「效率太低」背后其实是四件反复出错的事，而且错在人不在代码：
忘跑测试就打包、压包时漏 `commands.json` / `assets`（同事那边指令页是空的、图标没了）、
把自己的 `config.json`（含本机绝对路径）一起发出去、发完没人记得这版对应哪个提交。

## 先定两件事，再写代码

两个决定会影响整个实现，先问清再动手，避免做完了发现方向不对：

**一、产物放哪、更新怎么拿到版本信息。** 仓库当时是 **private**，而私有仓库的
Release 资产必须带 token 才能下载——token 一旦打进 exe 就等于公开发布（谁拿到
exe 都能提取，而且那是写权限 token）。所以这不是「技术上能不能」的问题，是
「必须选一条路」：仓库转 public / 另建 public 发布仓库 / 内网共享盘。
用户选了**转 public**（工具本身无商业机密）。

> 转 public 之前先扫了 git 全历史：`git rev-list --all --objects` 逐个 cat-file
> 找 `github_pat_` / `ghp_`。5 个 blob 命中，逐个看清全是占位符
> （`github_pat_xxx`）与测试夹具（`github_pat_TESTONLY_…`），`.git-credential`
> 从未进过历史；154 个跟踪文件里没有 `config.json` / `*.wav` / `dist/`。
> 确认干净才动 `PATCH /repos {... "private": false}`。

**二、发现新版后做到哪一步。** 自动下载替换 / 只提示 + 浏览器下载 / 下载到本地由
用户覆盖。用户选了**弹窗提示 + 浏览器下载**——这也是我推荐的：exe 正在运行时
Windows 不允许覆盖自身，自动替换要么写 `.bat` 延迟替换（杀毒软件对「脚本延迟改
可执行文件」高度敏感，十有八九被拦），要么要管理员权限（同事机器上等于让程序弹
UAC）。两条都比「用户点一下下载」更糟。

## 一、CI：打一个 tag 就出包（`.github/workflows/build.yml`）

| job | 环境 | 触发 | 做什么 |
| --- | --- | --- | --- |
| `test` | ubuntu-latest | 每次 push / PR | `pytest` 全量 + 前端 61 个 jsdom 用例 |
| `windows` | windows-latest | push main / tag / 手动 | 装依赖 → 校验 tag↔VERSION → `build.py --package --zip` → sha256 → artifact → tag 时发 Release |

几个刻意的选择：

* **测试在 Linux、构建在 Windows**：`core/` 与 `backend/` 全是标准库，测试不需要
  pywebview / pyinstaller，Linux 上装 `pytest` 就能跑完（快、失败信息清楚）；
  Windows 机器启动慢，只在真要出包时才用。
* **tag 必须与 `core/constants.py` 的 `VERSION` 相同**，不同就直接 `throw`。
  Release 标题、zip 文件名、程序自报版本号三处一旦不一致，用户看到的「我有新版」
  和实际下到的包就对不上，这种问题事后极难查。
* **同一 tag 重跑不红**：`gh release view` 查到就 `gh release upload --clobber`，
  查不到才 `gh release create`。否则「重跑一次流水线」会因「Release 已存在」失败。
* **附件名显式列出**，不用 `dist/*.zip` 通配：源码包与分发件都会匹配那个通配，
  `gh` 会因同名重复报错。
* **权限只给 `contents: write`**，且只在发布那一步用 `GITHUB_TOKEN`。

## 二、`build.py --package`：把「发给同事的东西」做成一条命令

以前是手工右键压缩 `dist/`。压漏 `assets/`、压漏 `commands.json`、顺手把自己的
`config.json` 打进去，三种都发生过（后两种由用户实报）。

`make_win_package()` 固定包内容：`exe + commands.json + 使用说明.txt + assets/ +
config.json`，套一层与 zip 同名的顶层目录（解压不会把 exe 和一坨 json 散在下载
文件夹里——那会导致「exe 与 json 不同目录，json 不生效，用户改了没反应」）。

文件名 `ADBDeviceCommander_v<版本>_win64.zip` 里的 `_win64` 是**协议的一部分**：
`core.update.ASSET_SUFFIX` 靠它从 Release 资产里挑 Windows 包，改名会让自动更新
悄悄退化成「随便挑一个 zip」（可能下到源码包，解压没有 exe）。
`tests/test_build.py::test_win_package_name_matches_update_asset_suffix` 盯着这两处。

## 三、`core/update.py`：版本检查（纯逻辑，可单测）

只做判断，不发请求（`opener` 注入）、不读配置、不碰 UI：

| 函数 | 职责 |
| --- | --- |
| `parse_version` | `v2026.1029.1931` / `release-2026.1029.1931` → `(2026,1029,1931)`；**只接受字符串** |
| `is_newer` | 任一方认不出（如 `dev`）→ 一律 `False`（宁可漏报一次，不可天天误报） |
| `due` | 距上次检查是否已过 12 小时；`last` 在未来（系统时间被调回）也算到点 |
| `pick_asset` | `_win64.zip` > 任意 `.zip` > 任意 `.exe` |
| `normalize` | GitHub `releases/latest` 与自建 `version.json` 归一成同一结构 |
| `check` | 404/403/5xx/坏 JSON/连不上 全部翻译成中文，**绝不抛异常** |

`parse_version` 只收字符串这条值得单独说：早先写成「非字符串先 `str()` 再解析」，
于是 `2026` 会变成 `(2026,0,0)`——任何真版本都比它大，用户会天天看到「有新版本」
且查不出原因。宁可判无效。

## 四、后端：检查时机与「不打扰」

`update_check(force)` 立即返回、结果走 `update` 事件；`_update_loop` 在后台线程里
「等 8 秒查首次」（启动瞬间 adb 探测、命令加载、首刷设备都在抢时间），之后每
12 小时复查。

| 场景 | 行为 |
| --- | --- |
| 开关关掉（`update_check=false`）、非手动 | 直接返回 `disabled`，不发请求 |
| 12 小时内已查过、非手动 | 返回 `skipped` |
| 正在查（手动再点） | 返回 `busy` + 一句提示，**不排队**（排队会让用户把旧结果当新结果） |
| 查失败 | 节流只等 **1 小时**再试（开会切网 / VPN 掉线不该让提示消失半天） |
| 自动查 + 无新版 / 出错 | 一句话都不说（用户没问，别把断网当报错砸给他） |
| 自动查 + 有新版本 | 弹窗 + 状态栏一行 |
| 用户点过「跳过此版本」 | 自动查的事件标 `silenced=true`，不弹窗；手动查仍如实回报 |

「打开下载页」有个白名单：只放行 http(s) 且主机在 GitHub 域名（或 `update_feed`
所配置的域名）内。防的不是用户，而是**更新源被换掉之后**有人用一条
`http://随便什么域名/b.exe` 的响应让程序替用户打开可执行文件下载——那等于把
「装什么」的决定权交出去。

## 五、前端：弹窗 + 关于页一行

* 弹窗只承载「差异」：`当前 → 最新`、说明（过长截断）、资产体积、
  **去下载 / 稍后 / 跳过此版本**。
* 「稍后」只关窗不记忆（下次启动还会提醒，那是真该提醒的）；「跳过此版本」落盘。
* 关于页新增一行：自动检查开关 + 上次检查结论 + 「检查」按钮。
* 修了一个自己引入的竞态：`booted` 与 `update` 事件可能在同一批轮询里到达，
  `onBooted` 里的 `loadUpdateInfo()` 是异步的，它的响应比同批事件**更晚**落地，
  会把刚显示的「有新版本 …」盖回「尚未检查」。加 `updateEventSeen`：回填天生是
  旧数据，不该赢。（这个 bug 是前端测试先抓到的，不是读代码读出来的。）

## 六、实测踩到的两件事（都不是读代码能发现的）

**1）工作流「校验不通过」时，日志里什么都没有。**
第一版 `jobs.test.name` 里写了 `${{ env.PYTHON_VERSION }}`，GitHub 直接判
「工作流无效」：运行记录显示 failed，但 `/actions/runs/<id>/jobs` 返回
`total_count: 0` —— 没有 job 就没有日志，界面上只是一次「秒失败」。
根因是 `jobs.<id>.name` 允许的上下文只有 `github / needs / strategy / matrix /
vars / inputs`，**不含 `env`**。改成字面量 `3.11` 后正常。

**2）匿名 REST 接口会 403，而且是在最不该失败的时候。**
发完第一个 Release 后，用客户端代码真查了一次（匿名、真实网络）：

```
status  : error
error   : 更新源暂时拒绝访问（HTTP 403，通常是接口调用次数用尽）。
```

`curl -i` 看清楚了：`x-ratelimit-limit: 60`、`x-ratelimit-remaining: 0`、
`API rate limit exceeded for <出口 IP>`。也就是说**同一个出口 IP 一小时只有
60 次**。这个工具是发给同事的，一个公司通常只有一个出口 IP：十几个人每天各查
几次就贴近上限，一旦超了，所有人都会看到「查不到新版本」——而更新检查恰恰是
「大家都得知道」的功能。

于是把更新源改成**静态优先、API 兜底**：

| 顺序 | 地址 | 认证 | 限流 |
| --- | --- | --- | --- |
| 1 | `https://github.com/<o>/<r>/releases/latest/download/latest.json` | 不需要 | 无（走 CDN，几百字节） |
| 2 | `https://api.github.com/repos/<o>/<r>/releases/latest` | 匿名 | 60 次/小时/IP |

`latest.json` 由 CI 在发版后生成并作为 Release 附件上传（内容与 API 返回同构：
`version` / `notes` / `url` / `assets[]`），所以两条路共用同一份解析代码。
`check()` 按顺序试，**任一成功即返回**；全失败才报错，并在原因里注明试了几个源。
用户自己配了 `update_feed` 时只查那一个——悄悄又去连 GitHub 会让人以为配置没生效。

## 改动清单

| 文件 | 改动 |
| --- | --- |
| `.github/workflows/build.yml` | **新增**：test + windows 两个 job；tag 触发发 Release 并生成 / 上传 `latest.json`（程序内的静态版本源） |
| `core/update.py` | **新增**：版本解析 / 比较 / Release 归一化 / 失败翻译（约 330 行） |
| `build.py` | 新增 `--package`、`win_package_name()`、`make_win_package()` |
| `core/prefs.py` | 新增 `update_check` / `update_feed` / `update_skipped_version` |
| `backend/controller.py` | 新增 `update_info` / `update_check` / `update_open` / `update_skip` / `update_unskip`、`_update_loop`、URL 白名单；`boot()` 起后台检查；新增构造参数 `auto_update`（单测关掉，避免真发网络请求） |
| `frontend/index.html` | 新增 `#update-modal`；关于页新增「更新」一行 |
| `frontend/js/app.js` | `update_state` / `update` 事件、弹窗与关于页渲染、6 个按钮绑定、启动回填 |
| `frontend/css/app.css` | `.update-box` / `.update-ver` / `.update-notes` / `.about-row.up-row` |
| `tests/test_core_update.py` | **新增** 35 条（含 5 条「多源回退」：静态 404 → API、全失败报尝试数、显式配置不回流） |
| `tests/test_backend_update.py` | **新增** 27 条 |
| `tests/frontend/update_modal.test.cjs` | **新增** 46 条 |
| `tests/test_build.py` | +4 条（分发件内容 / 顶层目录 / 缺 exe 警告 / 与 `ASSET_SUFFIX` 一致） |
| `tests/test_backend_controller.py` | 5 处构造点加 `auto_update=False` |
| `tests/test_core_prefs.py` | 布尔键映射表补 `update_check → about-update-auto` |
| `tests/frontend/checkbox_switch_style.test.cjs` | 静态复选框 28 → 29 |
| `README.md` / `使用说明.txt` | 新增「CI/CD」「版本更新提示」两节 + 使用说明一条 Q&A |

## 验证

- Python 全量：**962 passed / 1 skipped**（第二十二轮 896 + 66）。
- 前端全量：**61 个测试文件 0 失败**（第二十二轮 60 + 1）。
- `pyflakes`：零输出。
- **CI 真跑过，两次都绿**（这是本轮最该验的东西，本地造不出 windows-latest）：
  - `push main`（run 40987084156）：`test` 8 步全过；`windows` 装好
    pywebview + pyinstaller、`build.py --package --zip` 出包成功、sha256 生成、
    artifact 上传成功；
  - `push tag v2026.1030.0937`（run 40988157986）：额外跑了「版本号一致性」校验，
    并创建 Release，附件为
    `ADBDeviceCommander_v2026.1030.0937_win64.zip`（23.57 MB）、
    `ADBDeviceCommander_v2026.1030.0937.zip`（0.96 MB）、`sha256sums.txt`。
  - 客户端代码对真实接口查过一次：因为限流返回 403 —— 这条实测直接促成了
    「静态 latest.json 优先」的改动（见第六节）。
- **静态源本身**：本沙箱访问不了 `github.com`（只有 `api.github.com` 通），所以
  「静态优先」在这里必然回退到 API —— 回退链路因此被真实验证过一次。静态地址
  本身用另一条路核对：从 Release 把 `latest.json` 附件拉下来（527 字节、无 BOM、
  `json.loads` 通过、`normalize()` 能取出 `version` / `url` / `assets[0].size`）。

### 发版实测（2026.1030.1008，两次 CI 都绿）

- `push main`（run 40989978769）与 `push tag v2026.1030.1008`（run 40989980583）
  两次都 success。tag 那次 12 个步骤全过，含「版本号一致性（tag 与源码 VERSION
  必须相同）」「构建（exe + 分发 zip + 源码 zip）」「生成 SHA256」
  「upload-artifact」「发布 Release」。
- 分发件实测内容（取自 CI 日志，不是本地推断）：
  `ADBDeviceCommander_v2026.1030.1008_win64.zip`，**5 个文件 / 23.6 MB /
  单一顶层目录** `ADBDeviceCommander_v2026.1030.1008_win64/`；exe 本体 23.9 MB
  （onefile）。源码包 159 个文件。
  附带一条环境事实：本沙箱拉这个 24 MB 附件会被网络掐在 20 MiB
  （`curl` 只拿到 20,971,520 字节，`zipfile` 判 `BadZipFile`），所以「分发件里
  到底有什么」只认 CI 日志，不认本地下载。
- Release 四个附件（`/releases/tags/v2026.1030.1008` 实查）：
  `..._win64.zip` 24,711,175 B、`....zip` 1,006,363 B、`latest.json` 835 B、
  `sha256sums.txt` 218 B。
- `latest.json` 逐字核对：835 字节、**无 BOM**、`json.loads` 通过；
  `version` = `2026.1030.1008`；`assets[0].size` = 24,711,175；
  `notes` 与 `git log -1 --pretty=%B` **完全一致** —— 「取提交正文当更新说明」
  这件事真的生效了，不再是一行 Full Changelog。

### 一次事故：Release 被清空

- 02:16 查 `v2026.1030.1008` 的 Release，四个附件齐全；02:23 再查 `/releases`
  返回 `[]`、`/releases/tags/v2026.1030.0958` 也 404 —— **三个 Release 全部消失**。
  同一时刻 tag ref、commit、分支都在，`githubstatus.com` 显示 All Systems
  Operational，所以不是 GitHub 故障，是「Release 被人删了」。
- 值得记住的是**恢复不用重新上传文件**：发版步骤写的是「存在则改、不存在则建」，
  重跑那次 tag 工作流（`POST /actions/runs/<id>/rerun`，或重推同一个 tag）就会
  重新出包并挂附件，天然可重入。
- 顺带加固了一条设计判断：**Release 可以被人在网页上随手删掉**，所以客户端
  不能把「查不到更新源」当致命错误。现在的处理是静默失败、过一小时再试、不弹窗。

## 已知取舍 / 下一轮候选

- **不自动替换自身**：理由见上（占用 / 杀毒 / UAC 三条路都更差）。真要自动化，
  更合适的方向是「下载 + 校验 + 提示用户关闭程序后替换」，而不是程序自己动手。
- **更新检查不看预发布版**：只读 `releases/latest`（GitHub 定义上就是「最新正式版」），
  预发布（prerelease）不会推给同事。这是有意的——同事要的是能用的版本。
- **12 小时这个间隔是拍的**：程序是常驻工具（开着就是半天），比「每次启动查」更贴合，
  又不会打接口打太勤（匿名 60 次/小时）。真要更频繁，改 `core.update.CHECK_INTERVAL_S`。

---

# 第二十二轮：自动分段续录 + 收尾合并成一个完整 MP4

## 你的要求

1. 多花一两秒 logcat 没关系，但程序要尽快响应，并在界面写明建议最大录制时长；
2. 自动分段录，不要让用户手动重开；
3. **最终必须是一个完整的 mp4**，而其中的特殊点要在程序界面里写明。

1 与 2 见上两轮提交（`b7f78a5` / `dfeaee8` / `48687d0` / `9426ecb`）。本轮处理 3。

## 为什么「分段」必须收回成「一个文件」

`screenrecord` 单段硬上限 180 秒，这是设备端限制，绕不过去。但分段是**程序的
实现手段**，不是用户的需求：他按了一次「开始录制」，期望拿到一个能从头拖到尾的
视频。把 `_p2`/`_p3` 原样抛出去，等于把「用什么工具、按什么顺序拼」变成他的作业，
而 20 个分段的顺序、`-c copy` 的参数一致性本来都不该由使用者关心。

`backend/video_join.py`（新模块）用 `ffmpeg -f concat -safe 0 -c copy` 合并：

| 做法 | 为什么 |
| --- | --- |
| `-c copy` 不重编码 | 画质与各段完全一致（无二次压缩），耗时是磁盘 IO 量级（57 分钟素材几十秒），不吃 CPU |
| 先写 `xxx_full.mp4` 再改名回 `record_<serial>_<ts>.mp4` | 中途被杀 / 磁盘满时不会留下一个「正式名」的半成品被当成成品打包 |
| 合并后按「各段时长之和」复核 | `ffmpeg` 退出码 0 **不代表拼对了**：时间基不一致时它会安静地只输出第一段。容差 `max(2s, 2%)`，不符即删半成品并回退 |
| 缺 moov 的段剔除、放进 `skipped` | 塞进 concat 会把整片时长算错；但**绝不能删**，那是用户仅有的素材 |
| 失败时一个分段都不删 | 宁可给 N 个能播的段，也不给一个播不了的成片 —— 这是本功能唯一可能造成真实损失的地方 |
| 清单文件 `finally` 删除 | 过程产物不该留在用户的保存目录里 |

## 界面：三个必须写明的特殊点

拼接点不会补帧（补帧要重编码，代价与收益不成比例），所以成片在每处拼接点是
**画面跳变**，不是静帧。不说清楚的话，用户回放时会把那一跳当成录制中断、白重录
一遍。录屏卡片的常驻提示（`frontend/index.html` 的 `.rec-limit`）现在写明：

1. 每处拼接点约 1 秒间隙，N 段就有 N-1 处、累计约 N-1 秒，**不是录制中断**；
2. 合并依赖本机 `ffmpeg`，没有时保留 `_p2`/`_p3`… 分段（每个都能单独播）并说明原因；
3. 单场上限 20 段（约 57 分钟），到上限按正常收尾处理。

`使用说明.txt`（程序内「关于 → 使用说明」）同步补了同样三条。

## 改动

| 文件 | 改动 |
| --- | --- |
| `backend/video_join.py` | **新增**：`join_segments()`（合并 + 时长复核 + 临时名），`_concat_quote`（反斜杠 / 单引号转义），`_has_moov` |
| `backend/controllers/record.py` | 收尾链里插入 `_merge_device_segments`（多段→1 个）；成品回落到不带 `_pN` 的名字；合并成功删中间段、失败一个不删；完成 toast 按「N 段已合并为 1 个完整视频」说话；音频改为整条铺在成片上并提示音画会逐步超前 |
| `backend/controllers/autorefresh.py` | 上限制 / 死亡文案改成「收尾时合并成一个视频」，不再暗示目录里会有多个分段 |
| `frontend/index.html` | `.rec-limit` 重写：合并 + 三个特殊点 |
| `README.md` / `使用说明.txt` | 工具表与自动分段一节补合并链路、复核逻辑、失败回退 |
| `tests/test_backend_video_join.py` | **新增** 10 条：单段不启 ffmpeg、残段剔除、全残报因、缺 ffmpeg、ffmpeg 报错带原话、时长不符拒收、清单清理、引号/斜杠转义、真实 ffmpeg 合并（时长 5s）、单段内容不变 |
| `tests/test_backend_controller.py` | 新增 2 条（合并成功只剩一个 mp4、合并失败一个不删）+ 给 3 条既有多段用例显式打桩「合并不可用」，回归意图不变 |
| `tests/frontend/rec_limit_hint.test.cjs` | 新增 4 条断言（合并成一个完整 mp4 / 依赖 ffmpeg / 段数上限 / N-1 处拼接点） |

## 验证

- `pytest`：1237 passed / 1 skipped（新增 12 条）。
- `pyflakes backend core tools tests`：0。
- 前端 jsdom：69 个文件 0 失败（`rec_limit_hint` 14 条通过）。
- **回退验证**：`git stash` 掉 `record.py` / `autorefresh.py` / `index.html` 后，
  新用例分别失败在行为断言上（旧代码的 toast 是「（2 段视频）」而非「已合并为 1 个
  完整视频」；旧界面没有「合并 / ffmpeg / 57 分钟 / N-1」四项），不是 patch 期的
  AttributeError —— 用 `monkeypatch.setattr(..., raising=False)` 保证这一点。

---

# 第二十三轮：设备指令页多工作区（子 tab）

## 你的要求

> 设备指令需要增加一个新需求：支持再多开 N 个出来，其界面可以在下方增加子 tab，
> 每个子 tab 都包含有 指令台、指令输出，将这两个块儿当成一个子 tab，
> 可进行 N 个的独立工作区。

## 关键判断：「独立」的界线在哪

「多几块面板」是最省事的做法，但那是**假的多开**：后端只有一条持久 shell 会话，
在新 tab 里点「执行」只是排到别人的命令后面等着 —— 面板半天没有一行输出，用户
会以为命令没发出去。所以这次动的是会话层，不是 DOM 层：

| 层次 | 做法 |
| --- | --- |
| 后端会话 | 每个工作区一套 `ShellSession` + 一把执行锁 + 一份 busy 态（默认工作区沿用历史字段，故单工作区路径零变化） |
| 事件路由 | `console` / `stop_state` 载荷带 `ws` 字段；默认工作区**不带**，与旧载荷一字不差 |
| 前端面板 | 克隆默认工作区的 DOM，剥掉全部 `id` 改留 `data-role` —— 同一份文档里不能有两个 `#console` |
| 指令库 | 全局共享一份（多开是为了并行做事，不是养多份互相不知道对方存在的命令表） |
| 筛选 | 搜索词 / 标签选择**按工作区独立**（两块面板本来就在看不同的东西）；「保留输入内容」是全局设置 |
| 停止 | `stop_run(ws)` 只 kill 那个工作区的会话，不会顺手掐掉另一个 tab 的活 |

会话**懒创建**：开 8 个 tab 不会拉起 8 个 powershell，只有真的在某个工作区执行
命令时才建那一条。会话创建放在后台 worker 里，不在 `run_command` 的调用线程里
建 —— 否则点完命令界面会卡 0.5~1.5 秒（powershell 冷启）。

克隆 DOM 后 `_splitters`（窗口缩放重钳列表）会留下死引用，关闭工作区时一并摘除；
同理 `#cmd-groups` 的 CSS 规则改成了 `.cmd-groups`（class）—— 克隆体没有 id，
按 id 写的布局规则从第 2 个工作区起全部失效，表现为「命令一多就把输出区顶出屏幕」。

## 顺带修掉的两处

1. **`test_full_segment_rolls_to_next_part` 的竞态**（既有问题，被本轮负载放大）：
   续段会为新的一段再起一个 watcher，而测试里 `Popen` 是假的、`_Proc.wait()`
   立刻返回 0 —— 那条 watcher 随即判定「远未到点就退出」并标 `died`，与用例的
   断言抢跑。现在把类上的 `_watch_exit` 换成只记调用的假函数，再由用例直接调用
   原函数对象跑一次真实判定，并顺带断言「新段也起了 watcher」。
2. **`#cmd-groups` 的 id 选择器**（见上）：改成 class，并给 `ui_layout_fixes`
   加一条「不许再用 `#cmd-groups` 写布局」的断言。

## 界面

顶部一排子 tab（比主 tab 矮一级、无边框，避免抢注意力）：`工作区 1 / 工作区 2 / …`
＋「＋ 新建工作区」＋ 右侧一句说明。正在执行的工作区 tab 上有呼吸式小圆点 ——
用户切走后它还在跑，「哪个 tab 有活在跑」必须一眼可辨，否则他会在两个 tab 之间
反复点着找。其余 tab 上的 `×` 关闭工作区：**先停掉里面正在跑的命令、再杀掉会话**
再移除面板，避免留下「界面上已经没有了、却还在往里写输出」的幽灵会话。
默认工作区不给关闭键（它就是启动时那套面板）。

工作区数量与名字记入 `config.json` 的 `cmd_workspaces`（逗号分隔的名字串，与
`cmd_order` / `builtin_folded` 同一套约定），下次启动照旧恢复。

## 改动

| 文件 | 改动 |
| --- | --- |
| `backend/controllers/base.py` | 新增工作区基础设施：`_ws_session`（懒创建 + 加锁防重复建）/ `_ws_lock` / `_ws_begin` / `_ws_end` / `_ws_publish_stop` / `_ws_status`（多工作区时状态文案带 `[工作区 N]` 前缀）/ `ws_open` / `ws_close`；`_push_console` / `_push_cmd` / `_sync_stop_state` 按线程局部的工作区定位；`shutdown` 收掉全部会话 |
| `backend/controllers/commands.py` | `run_command` / `run_custom` / `stop_run` / `_execute` / `_run_entries` / `_interruptible_sleep` 支持 `ws`；执行流程的播报改走 `_ws_status`（默认工作区不加前缀，文案零变化） |
| `backend/controllers/autorefresh.py` | `clear_output(ws)`：清空只清自己那块 |
| `core/prefs.py` | 新增 `cmd_workspaces` |
| `frontend/index.html` | 子 tab 栏 `#ws-bar`；默认工作区的 `.cmd-layout` 加 `ws-panel` / `id` / `data-ws` |
| `frontend/js/app.js` | 工作区注册表 + 克隆 + 切换 + 关闭 + 持久化；`console` / `stop_state` 按 `ws` 路由；指令台渲染 / 筛选 / 点击 / 拖拽全部按工作区 |
| `frontend/css/app.css` | `.ws-bar` / `.ws-tab` / `.ws-dot`（呼吸点）/ `.ws-x` / `.ws-hint` / `.ws-panel`；`#cmd-groups` → `.cmd-groups` |
| `tests/test_backend_workspace.py` | **新增** 12 条：独立会话 / 输出路由 / 真并行（Barrier 式硬证据）/ 只停自己 / 停止态按 ws / 关闭杀会话 / 默认工作区不可关 / 上限 / 状态前缀 / 清空作用域 / 关窗收全部 |
| `tests/frontend/ws_tabs.test.cjs` | **新增** 38 条断言：入口存在 / 新建后无重复 id / 执行带 ws / 输出不串台 / 停止态独立 / 清空带 ws / 关闭调 `ws_close` / 上限提示 / 重启恢复布局 |
| `README.md` / `使用说明.txt` | 补多工作区说明（会话隔离、指令库共用、停止按 tab、上限 8、恢复布局） |

## 验证

- `pytest`：1249 passed / 1 skipped（新增 12 条）。
- `pyflakes backend core tools tests`：0。
- 前端 jsdom：**70** 个文件 0 失败（`ws_tabs` 38 条全过）。
- **回退验证**：`git stash` 掉全部生产代码后，`ws_tabs` 在第一条断言就失败
  （旧界面没有 `#ws-tabs` / `#btn-ws-add` / `.ws-panel`），不是踩 undefined 崩掉。
- **「半吊子实现」验证**：临时把 `_ws_session` 改成「永远返回默认会话」（即只有
  面板、没有隔离），`test_backend_workspace.py` 立刻失败 6 条 —— 独立会话 / 输出
  路由 / 并行 / 只停自己 / 关闭杀会话 / 关窗收全部。这正是本功能最怕退化成的那种
  「看起来多开了，其实共用一条命令通道」。

---

# 第二十四轮：录屏「取消」（停止并删除）+ 分段提示沉底 + 首次运行 SmartScreen 说明

## 你的三个问题

1. Win11 上双击 exe 弹「Windows 已保护你的电脑 / SmartScreen 阻止了无法识别的应用
   启动，发布者：未知」——**是不是缺了什么？**
2. 设备录屏卡的「三分钟分段提示语」放到区块**下方**。
3. 设备录屏增加**取消**：开始录制后能取消，本次产生的文件删掉、不打包。

## 1. SmartScreen：不缺任何东西，是「没签名 + 没信誉」

| 判断 | 依据 |
| --- | --- |
| 不是缺 WebView2 / 运行库 | 缺运行库的表现是启动后弹中文检查窗（第 0 条），不是 SmartScreen 蓝窗 |
| 不是被杀毒判定为病毒 | 报毒会写具体威胁名（`Trojan:Win32/…`），这里写的是「无法识别的应用」 |
| 不是 exe 下载坏了 | PyInstaller 单文件 exe 被打断会直接「不是有效的 Win32 应用」，不会走到 SmartScreen |

真正的原因只有两条，缺一不可：

1. **exe 没有代码签名证书** —— 没有证书，Windows 只能显示「发布者未知」；
2. **文件在微软的下载量信誉库里没有记录** —— 同事之间传的 exe 必然没有。

两样凑齐，SmartScreen 就按「不认识 + 有风险」先拦一步。这是**基于信誉的预警**，
不是查出了恶意代码。放行方式：点「更多信息」→「仍要运行」（同一路径一般只需一次）；
若窗口里没有「更多信息」，说明被组策略锁成强制阻止，需 IT 加白名单或右键属性
勾「解除锁定」。要彻底不弹，唯一正路是买代码签名证书签名 —— 本项目不分发证书，
所以默认不带签名。

以上写成两处文档（不是只在本轮笔记里）：
- `使用说明.txt` 开头新增**【首次运行被 Windows 拦住？（不是缺东西）】**一节，
  同事拿到 exe 第一次运行就能看到；
- `README.md` 打包章节新增同样口径的提示，说明「这不是缺依赖」。

## 2. 分段提示语沉到卡片最下方

改动前卡片顺序：说明 → **一整块黄底长文** → 按钮 → 开关 → 细节说明。那块提示有
三行、约 300 字，把「开始录制 / 停止」挤到屏幕下半截，每次录屏都得先滚过它。

改动后：说明 → 按钮（开始 / 停止 / **取消**）→ 开关 → 细节说明 → **提示块沉底**。
它是**说明**、不是操作，落到卡片最后一块；内容一字未删（180 秒硬上限、170 秒分段、
拼接点约 1 秒缺失 —— N 段 N-1 处、依赖 ffmpeg、上限 20 段）。CSS 的
`.rec-limit` 外边距由 `0 0 10px` 改为 `10px 0 0`（沉底后不该再留下边距）。

## 3. 「取消」：停止并删除，不合并、不打包

「录错了」是常态：选错设备、场景不对、只想试一下。此前唯一出口是「停止」——
它必然走合成 + 打包，用户拿到一个「✓ 已打包」的 zip，还得自己进目录一个个删，
十几秒的 ffmpeg 拼接也白烧。

新增 `screen_record_cancel()`（`WebApi` → `api.screen_record_cancel`）：

| 步骤 | 做法 | 为什么 |
| --- | --- | --- |
| 停设备端 | `VideoRecorder.discard_ex()`：置 `stopping` → SIGINT / 按 PID `kill -INT` → 等本地 adb 退出 | 不置 `stopping` 会被 watcher 当成「意外中断」，触发一轮多余的自动收尾 |
| **不 pull 当前段** | `discard_ex` 与 `stop_ex` 的**唯一**区别 | 用户明确不要，把几百 MB 搬回来再删掉纯属浪费；弱网下几十秒还会让人以为卡死 |
| 停 logcat / 麦 / overlay | 全部先停下，再统一等落盘 | 文件还在写的时候删，Windows 直接拒绝（`PermissionError`） |
| 删 | 视频分段（含已并行拉回的段、`video_segs` 里「设备被拔掉时取回的段」）、logcat txt、麦克风 wav | 少一样都会在保存目录里留下「取消没生效」的证据 |
| 设备端残留 | `adb shell rm -f` 当前段与各历史段 | screenrecord 拒绝覆盖同名文件，残留会让**下一次**录屏直接启动失败 |
| 报 | 删不掉的点名说出来（warn toast） | 刚拉回的 mp4 被播放器开着时删不掉；沉默地报「取消成功」等于骗人 |

几条刻意的边界：

- **不复用 `_session_teardown`**：那条路径每一步都在「保住产物」（合成音频 / 合并
  分段 / 打包 / 失败一个段都不删），这条每一步都在「确认产物不存在」。共用一套代码，
  迟早有一边走错方向 —— 最坏是「打包后删源文件」的副作用跑进取消路径。
- **只删普通文件，目录一律跳过**：取消绝不能退化成一次递归删除。
- **`finally` 清会话**：异常也不会留下 `_rec_session` 残留（残留 = 之后每次「开始
  录制」都被守卫判成 recording，功能永久锁死）。
- 前端「取消」紧挨「停止」，点击后要过一遍 `confirm`；点「否」时**一个后端调用都
  不发**。取消在途时三个按钮全锁，防连点撞上已清空的会话。

## 改动

| 文件 | 改动 |
| --- | --- |
| `backend/screen_service.py` | 新增 `VideoRecorder.discard_ex()`（停止 + 丢弃，不 pull 当前段，设备端 `rm -f`） |
| `backend/controllers/record.py` | 新增 `screen_record_cancel` / `_screen_record_cancel_locked` / `_session_discard` / `_delete_files` |
| `frontend/index.html` | 录屏按钮行加「取消」（`data-icon="trash"`）；`.rec-limit` 整块移到卡片最下方；细节说明补一句「取消 = 停止并删除、不合并不打包」 |
| `frontend/js/app.js` | `els.toolRecCancel`；`setRecInFlight` / `setRecRunning` 纳入取消按钮；点击 → `confirm` → `screen_record_cancel` → 回到未录制态 |
| `frontend/css/app.css` | `.rec-limit` 外边距改为 `10px 0 0`（沉底） |
| `tests/test_backend_controller.py` | **新增** 7 条：删文件且不打包 / `video_segs` 与麦文件也删 / 目录不删 / 删不掉要报 / overlay 照常恢复 / 无会话不算失败 / 异常也清会话 |
| `tests/test_backend_screen.py` | **新增** 4 条：`discard_ex` 不 pull 当前段 / 交回已拉回的段 / 不被判成意外中断 / 未录制设备 |
| `tests/frontend/rec_cancel.test.cjs` | **新增** 24 条：按钮存在与初始禁用 / 提示语在按钮行之后且为最后一块 / 点「否」不发请求 / 点「是」调后端并有即时反馈 / 在途锁定 / 完成后按钮态复位 |
| `README.md` / `使用说明.txt` | SmartScreen 说明；「取消」的行为与边界；提示语位置 |

## 验证

- `pytest`：**1260 passed / 1 skipped**（新增 11 条）。
- `pyflakes backend core tools tests`：0。
- 前端 jsdom：**71** 个文件 0 失败（`rec_cancel` 24 条全过）。
- **回退验证**：`git stash` 掉生产代码后，`rec_cancel.test.cjs` 在「取消按钮存在」
  与「提示语排在按钮行之后」两条静态断言上直接失败（不是踩 undefined 崩掉；
  且加了看门狗，失败一定以退出码 1 结束而不是挂住），后端 7 条在
  `screen_record_cancel` 上失败。
- **「半吊子实现」验证**：把取消临时改成「只调用 `_screen_record_stop_locked()`」
  （= 照常合并打包、不删文件），`test_screen_record_cancel_deletes_files_without_zip`
  与 `..._pretaken_and_mic` 立刻失败 —— 断言落在「文件是否真的不在了」上，
  正是本功能唯一可能造成真实损失的地方。

---

# 第二十五轮：「取消」改警示色 + 工作区 tab 可自定义重命名

## 你的两个要求

1. 「取消」改成**警示色**（上一轮结尾我提的那个待定项，你定了：要区分）。
2. 设备命令页的工作区 tab 支持**自定义重命名**，方便多开使用。

## 1. 「取消」：新增 `.btn.warn`（琥珀），刻意**不用**红色

上一轮「停止」与「取消」都是中性灰，只靠悬停提示与确认框区分 —— 摆在一起几乎
一模一样，误点一次就是删掉刚录的东西，且没有回收站。

这轮不是简单地把「取消」刷红，而是**新开一个语义色**：

| 键 | 类 | 配色 | 含义 |
| --- | --- | --- | --- |
| 开始录制 | `.btn.ok` | 深绿 | 开始 |
| 停止（录制中） | `.btn.danger` + `.live` | 红块 + 呼吸光晕 | **这就是当前运行态**，按它收尾 |
| 取消 | `.btn.warn`（新） | 琥珀描边 + 淡底 + 轻辉光 | **这个动作会丢东西**，慢一点 |

为什么不给「取消」用 `.danger`：录制中的「停止」本身就是红块呼吸，两键同色等于
没区分，用户照样点错 —— 而且「红」在这个界面里已经被约定为「正在采集」的指示色
（Logcat 采集、投屏中都用它）。琥珀是「警示但非运行态」，两者分工清楚。

`.btn.warn` 同时补齐 `:hover`（否则看着像禁用）与 `:disabled`（否则灰不掉、看着
一直可点）——这两条都写进了测试断言，因为只加 `background` 不做这两态是这类
「新配色」最常见的半成品。

## 2. 工作区重命名：双击 tab 名（或 F2）

多开之后「工作区 2 / 工作区 3」谁是谁全靠记：一个在抓 logcat、一个在刷机、一个
临时敲 adb 查东西。名字本来就是 `config.json` 里 `cmd_workspaces` 那一串，但界面
上一直没有改名的入口（上一轮的恢复测试里甚至已经在用「抓日志」这种自定义名，
只是没人能把它设出来）。

交互：**双击 tab 上的名字** → 名字就地变输入框（整段选中，直接打字即可覆盖）→
回车确认、Esc 取消、点别处也算确认。键盘用户选中 tab 后按 **F2**。tab 条右侧的
常驻说明与每个 tab 的悬停提示都写明了这条（双击这种交互，不写出来就等于没有）。

改名要做**三件事**，少一件都能被用户看见：

| 目标 | 做法 | 少做会怎样 |
| --- | --- | --- |
| tab 文字 | 就地换回 `<span class="ws-label">` | —— |
| 落盘 | `persistPref("cmd_workspaces", …)` | 重启后名字回到「工作区 3」 |
| 后端登记 | `ws_open(id, name)`（同一个 id 再登记 = 改名） | tab 写着「刷机」，状态栏却是「[工作区 3] ✓ 完成」，用户以为是别人跑完的 |

几条刻意的边界：

- **重命名途中不重建 tab 条**（`renderWsTabs` 见 `wsRenaming` 直接让路记账）：
  `innerHTML` 一清，正在输入的 `<input>` 就没了，打到一半的名字直接丢。当前的重绘
  入口（新建 / 关闭 / 恢复布局）其实都走不到「改名途中」这一刻，这行因此是**防御性**
  的 —— 但这条约束不能靠调用顺序去赌：少这一行，将来任何一处新加的重绘就是一次
  「打着字突然没了」，且极难复现。真被跳过时，渲染在改完的下一拍补上。
- **`activateWs` 也不再重建 tab 条**，只改状态类：`innerHTML` 一清，双击的第二下
  就落在刚创建的新节点上，浏览器不补发 `dblclick` —— 双击改名会「时灵时不灵」，
  而且极难复现（得正好在切换 tab 的瞬间双击）。
- **逗号换成空格**：逗号是 `cmd_workspaces` 的分隔符，名字里带上它，重启后这个
  工作区会被拆成两个（多出来那个是空面板），用户完全想不到是自己名字里那个
  逗号干的。
- **空名拒绝**并保留原名：空串会被 `filter(Boolean)` 丢掉，紧随其后的名字整体前移
  一位，工作区全错位。落盘时也兜底成 id。
- **超长截到 24 字**，与后端 `ws_open` 的截断长度一致（前端 24、后端 24，不会出现
  「改完显示一截、状态栏又是另一截」）。
- **双击「关闭」键不进改名**：用户两次点叉是想关掉它，不是想改名。
- **默认工作区改名不通知后端**：它的状态播报本来就不带前缀（单工作区时代的文案
  一字不变），登记了也用不上。
- 顺手修掉一个「改名之后又新建会撞名」的坑：默认名从 `"工作区 " + (size+1)` 改成
  跳过已占用的名字（把「工作区 1」改名成「工作区 2」后再新建，不会出现两个
  「工作区 2」的 tab）。
- 顺带修掉上一轮留下的一个真实缺陷：**重启恢复时自定义名没有交给后端** —— 以前是
  `addWorkspace()` 先用默认名登记一次、再在本地改 `ws.name`，于是后端永远记着
  「工作区 3」。现在名字随 `addWorkspace(id, name)` 一起在 `ws_open` 时送出。

## 改动

| 文件 | 改动 |
| --- | --- |
| `frontend/css/app.css` | 新增 `.btn.warn` / `:hover` / `:active` / `:disabled`；`.ws-tab.is-renaming` 与 `.ws-rename` 输入框 |
| `frontend/index.html` | 取消按钮 `class="btn warn"`；`#ws-hint` 初始文案补「双击 tab 名可重命名」 |
| `frontend/js/app.js` | `wsRenaming` / `wsRenameReplay`；`beginWsRename` / `endWsRename` / `acceptWsName` / `sanitizeWsName` / `syncWsTabText` / `fitWsRename`；`renderWsTabState` / `updateWsHint`；`activateWs` 改为不重建 tab；`addWorkspace(persist, silent, wanted)` + `nextWsName()`；`restoreWorkspaces` 把名字随创建一起下发；`persistWs` 空名兜底 |
| `tests/frontend/ws_rename.test.cjs` | **新增** 49 条：入口 / 双击进入输入框（焦点、整段选中）/ 回车三处同步 / Esc 不落盘 / 空名拒绝 / 逗号过滤 / 24 字截断 / 重命名途中事件不冲掉输入框且忙碌点照常 / 结束改名不重建 tab 条 / 双击叉号不改名 / F2 / 不撞名 / 重启恢复把名字交给后端 / 默认工作区不打扰后端 / 同名不播报 |
| `tests/frontend/rec_cancel.test.cjs` | **新增** 7 条：`.warn` 存在 / 不是 `.danger` / CSS 有 `:hover` 与 `:disabled` / 「停止」不用警示色 |
| `tests/test_backend_workspace.py` | **新增** 3 条：改名后状态栏前缀跟着变 / 开满 8 个时仍能改名（上限只挡新建）/ 空名不改动已有名字 |
| `README.md` / `使用说明.txt` | 「取消」配色口径（琥珀 vs 红）；重命名怎么用、三条限制 |

## 验证

- `pytest`：**1263 passed / 1 skipped**（新增 3 条）。
- `pyflakes backend core tools tests`：0。
- 前端 jsdom：**72** 个文件 0 失败（新增 `ws_rename` 49 条；`rec_cancel` 30 条）。
- **回退验证**：`git stash` 掉 `frontend/` 后，`ws_rename` 在「tab 里有 `.ws-label`」
  「提示写明双击重命名」等入口断言上失败并**以退出码 1 结束**（加了看门狗，不会
  挂住）；`rec_cancel` 在 4 条配色断言上失败。
- **「半吊子实现」验证**：把改名临时改成「只改本地与落盘、不通知后端」，`ws_rename`
  立刻失败在「通知后端登记新名字」这一条上（实际收到的是旧名「工作区 2」）——
  正是「tab 与状态栏两边对不上」的那个真实后果。

---

# 第二十六轮：「停止 / 取消」更名为「停止录制 / 取消录制」+ 取消改用应用内二次确认弹窗

## 你的两个要求

1. 「停止」更名为**「停止录制」**，「取消」更名为**「取消录制」**。
2. 「取消」应当有个**二次确认弹窗**，避免误点。

## 1. 按钮名带上「录制」

单看「停止」「取消」两个词，脱离上下文会被读成「停止刷新」「取消选择」——这两颗键
并排挂在卡片里，右边就是「同步录制 logcat」「结束录制后自动压缩 zip」这些开关，
视线扫过时更容易读串。名字自己要说清动作落在什么上，不能指望用户先读一遍卡片标题。

三个按钮现在是：**开始录制 / 停止录制 / 取消录制**。四个字都在 `.tool-row` 的
`flex-wrap: wrap` 里排得下（截图确认过没有换行挤压）。

## 2. 二次确认：从 `window.confirm` 换成应用内自绘弹窗

上一轮其实已经有 `confirm()` 了，但那个「确认」在 pywebview 里**并不可靠**：

```js
if (typeof confirm === "function" && !confirm(ask)) return;
```

pywebview 各版本对 `window.confirm` 的支持并不一致。在它没被实现（或实现成空函数）
的版本里，调用返回 `undefined` —— `!undefined === true`，于是这行**直接 return**：

- 按钮点了**没有任何反应**（不弹窗、不删除、不提示）；
- 用户唯一的解释是「程序卡了」，而它其实是被自己那句「安全判断」拦下的；
- 更糟的是这行代码**看起来是对的**（还带了个 typeof 兜底），review 时很难发现。

这是典型的静默失败，而且落在「删除」这个最不该含糊的入口上。所以这轮把它换成
自绘弹窗 `askConfirm(opts) → Promise<boolean>`：**只有用户明确点了「是」才
resolve(true)**，其余一切出口都是 `false`。

| 出口 | 结果 | 为什么这么定 |
| --- | --- | --- |
| 点「是，全部删除」 | `true` | 唯一的确认路径 |
| 点「否，保留」 | `false` | —— |
| 点右上角 × | `false` | 「关掉这个框」= 不想做 |
| 点框外空白遮罩 | `false` | 误点一下空白不该等于「确认删除」 |
| 按 Esc | `false` | 全界面的 Esc 语义一直是「取消」 |
| 界面里没有这个弹窗节点 | `false` + 状态栏说明原因 | 绝不能「没弹窗就当他同意了」 |

几条刻意的细节：

- **默认焦点在「否」上**：弹窗里最容易被顺手按下的是回车，落在「否」上才是安全侧。
  「否」也排在「是」前面 —— 末位是手掌的默认落点，不该放删除。
- **Tab 圈在弹窗内**（`trapConfirmTab`）：焦点跑到背后的界面上，键盘用户的下一次
  回车就可能落在背后某个按钮上，而弹窗还开着，看起来像弹窗失灵。
- **Esc 只关这一层**：确认框开着时，Esc 先答它（= 否）并 `return`，不会顺带把背后的
  状态面板也关掉 —— 否则用户以为「Esc 关掉了删除确认」，直到下次想看状态才发现
  那个窗口也没了。
- **同一时刻只允许一个确认**：`askConfirm` 被重入时先把上一个判否。不这么做，旧的那
  个 Promise 永远不 resolve，它的调用方就一直卡在 `await` 上（按钮已锁、状态栏停在
  「正在…」）。`settleConfirm` 重复调用是 no-op，连点「是」再按 Esc 不会 resolve 两次。
- **弹窗开着时录制自己结束了**（拔线 / 进程死亡 / 摸到 20 段上限）：点「是」不再向后
  端要「取消」（会话已不在，只会换回 `no_session`，还会被报成「取消录屏失败」），
  改成一句「录制已经结束，没有需要取消的内容」。
- **正文逐条列出要删什么**（视频分段 / 已拉回的段 / logcat / 麦克风），并指出
  「想保留就点**停止录制**」—— 用户点「取消录制」常常只是选错了按钮，这句话就是
  给他的最后一次提醒。
- **`z-index: 60`**：确认框经常是在别的弹窗之上被叫起来的，压在下面等于点了没反应。
- `.confirm-box` 必须写在 `.modal-box` **之后**：两者同为单类选择器，特异性相同，
  靠先后顺序决胜；写在前面的话 `width: 80%` 会把 440px 顶掉，确认框变成一屏宽，
  看着像把内容弹窗误开成了确认框。

## 改动

| 文件 | 改动 |
| --- | --- |
| `frontend/index.html` | 按钮文案 → 开始录制 / **停止录制** / **取消录制**；新增 `#confirm-modal`（`.confirm-modal` + `.confirm-box` + `#confirm-text` + `#confirm-yes/no/x`） |
| `frontend/js/app.js` | 新增 `askConfirm` / `settleConfirm` / `trapConfirmTab`；取消按钮改为 `await askConfirm({...})` 并补「会话已结束」分支；Esc 处理让确认框优先；Tab 焦点圈在弹窗内 |
| `frontend/css/app.css` | `.confirm-modal`（z-index 60）/ `.confirm-box`（440px）/ `.confirm-text`（pre-wrap + `word-break: normal`）/ `.btn:focus-visible` 焦点环 |
| `tests/frontend/rec_cancel.test.cjs` | 重写为 **64 条**：文案 / 弹窗结构与初始隐藏 / 默认焦点在「否」/ 四个「否」出口 / 连点只发一次请求 / 弹窗期间录制结束不误报 / 缺弹窗时默认判否 / **全程零 `window.confirm` 调用** |
| `README.md` / `使用说明.txt` | 按钮新名字；二次确认的四个「否」出口与「想保留就点停止录制」 |

## 验证

- `pytest`：**1263 passed / 1 skipped**（本轮未改后端）。
- `pyflakes backend core tools tests`：0。
- 前端 jsdom：**72** 个文件 0 失败（`rec_cancel` 64 条）。
- **回退验证**：`git stash` 掉 `frontend/` 后，`rec_cancel` 在「按钮文案是取消录制」
  「界面里必须有确认弹窗节点」等 12 条断言上失败，进程**以退出码 1 结束**
  （看门狗兜住踩 null 抛出的异常，不会挂住）；恢复后 64/64 通过、退出码 0。
- **「半吊子实现」验证**：把 `askConfirm` 改成「直接 resolve(true)、不弹窗」，
  测试立刻失败 10+ 条，其中最关键的是**「点『否』时一个后端调用都不许发」** ——
  正好对应「误点一次就删掉刚录的东西」这个唯一会造成真实损失的后果。

---

# 第二十七轮：性能报告图表换成内联 ECharts（交互 tooltip）

## 问题
导出的性能报告里，七张曲线是**自绘 SVG**，提示靠 SVG 原生 `<title>`：浏览器那种
单行、有延迟、要靠逗留才弹的原生气泡。用户要的是 ECharts 那种**十字准星 + 读数框**
的交互，顺带能点图例隐藏、滚轮缩放。

## 关键取舍：为什么内联、不用 CDN
报告是「双击即看」的**离线文件**，测试机 / 内网常常没有外网。CDN 版在断网时只会
得到**一张空白图**——这正是最该避免的静默失败：用户会以为数据没采到，而不是网络
没连上。所以把 ECharts **内联进每一份报告**：单文件、断网可用，代价是体积。

- 用 **`echarts.common.min.js`（662KB）**，不是 1MB 全量包。`simple` 包在 SSR 下缺
  SVG renderer（实测 `Cannot read properties of null`），不可靠，不用。
- **体积反而没爆**：旧报告 982KB 里，悬停热区（每图 760 个带 `<title>` 的透明 rect）
  占了大头；换成 ECharts 后这些字符串整个消失，腾出的空间正好抵掉 662KB 库。再对
  曲线做**按桶抽稀**（每桶保留首末 + 极值，≤900 点/序列，尖峰不丢），8000 采样点
  的报告稳定在 **~1.02MB**，仍满足既有的 `< 1.2MB` 体积回归。

## 语义等价（图上的信息一条都不能少）
- 阈值虚线 → `markLine`（`type:"dashed"`，行尾 `≥/≤ 阈值 单位` 标签原样保留）；
- 单机超标色带 → `markArea`（`#ff5f6b` 透明 .12；**单点超标也顺延一个采样间隔**，
  否则宽度为 0 看不见「偶发掉一帧」）；
- 对比图超标红点 → `markPoint`（落在对应设备线上，上限 400，与 SVG 版同口径）；
- `None`（掉线 / 重启）→ `connectNulls:false`，断线不连成假直线；
- 对比图一设备一色 + ECharts 可点击图例（点一下隐藏那台，再点恢复）；
- 时间轴用 `type:"time"`，tooltip 按本地时区显示 `HH:MM:SS`，断点显示「—」。

## 兜底与安全
- **缺 `echarts.min.js` 不空白**：`echarts_ready()` 探测不到就自动回退到原有 SVG
  渲染，并在报告顶部挂一条琥珀色明示横幅（「图表已降级为静态 SVG」）。SVG 实现
  整段保留，既是兜底也让原有 SVG 单测继续有效。
- **`</script>` 转义**：option 以 JSON 内联进 `<script>`，`json.dumps` 后把 `</`
  转成 `<\/`。设备型号若含 `</script><script>…`，也只是脚本里的字符串，不会提前
  闭合标签（有专门用例锁死：报告里 `</script>` 恰好 2 个）。
- **打包自检**：`build.py` 新增 `REQUIRED_ASSETS = ["frontend/vendor/echarts.min.js"]`，
  `check_sources()` 缺它就**构建失败**，而不是打出一个「报告没有交互」的包。
  `frontend/` 整目录本就 `--add-data` 进 exe，新文件自动随包。

## 改动

| 文件 | 改动 |
| --- | --- |
| `frontend/vendor/echarts.min.js` | 新增，ECharts 5 精简构建（662KB），随 `frontend/` 进包 |
| `backend/perf_service.py` | 新增 `echarts_ready` / `_echarts_js` / `_axis_range` / `_downsample` / `_bad_bands` / `_echart_option` / `_echart_compare_option` / `_echarts_script` / `_echart_card`；单机与对比报告默认走 ECharts，缺库回退 SVG + 明示；`.echart` 容器样式 |
| `build.py` | `REQUIRED_ASSETS` + `check_sources()` 纳入校验 |
| `tests/test_backend_perf.py` | 新增 `_report_opts` / `_report_markup`（从 662KB 库源码里切出 option，避免拿库字样当命中）；按 option 语义重写 8 条断言；新增 `</script>` 逃逸用例 |
| `tests/test_build.py` | `check_sources` 期望值加 `REQUIRED_ASSETS`；新增 vendor 存在且随 frontend 进包 |
| `README.md` / `使用说明.txt` | 报告改为「ECharts 交互曲线、库内联、断网可用；悬停看读数 / 点图例隐藏 / 滚轮缩放」 |

## 验证
- **SSR 校验**：把 Python 产出的真实 option 喂给 `echarts.common.min.js` 的
  `init(null,null,{renderer:"svg",ssr:true})`，单机 / 对比均渲染出 `<path>` 与文字。
- **真机端到端**：无头 Chromium 以 `file://` 打开生成的 745KB 报告，DOM 里出现
  **7 个 `<canvas>`**（每图一个，ECharts 已初始化），截图确认 CPU 图有红色阈值虚线
  「≥ 85 %」、FPS 图有红色超标色带，深色配色与卡片布局正常，无空白块。
- `pytest`：**1265 passed / 1 skipped**（较上轮 +2，报告体积用例仍 < 1.2MB）。
- `pyflakes backend core tools tests`：0；`node --check frontend/js/app.js`：OK。
- 前端 jsdom：72 个文件 0 失败。
- **回退验证**：临时移走 `frontend/vendor/echarts.min.js`，`echarts_ready()` 转 False，
  报告改出 SVG + 降级横幅（不空白）；`build.py` 的资源自检同时报缺该文件。

# 第二十八轮：复查 ECharts 改造（抽稀乱序 + 红点截断）

## 问题

上一轮把报告图表换成 ECharts 后，**新引入的两个函数没有任何单测**，而它们恰好承载
旧实现里最要紧的两条不变量：「尖峰不能被抽稀丢掉」和「超标必须能被看见」。主动复查时
对着 8000 点报告逐个功能核，发现两处「图能画出来、结论却是错的」。

### 1. 抽稀后时间戳不再单调 → 曲线在桶内来回折返

`_downsample` 每个桶收集 `[首, 末, 极小, 极大]` 四个点，**按收集顺序**直接追加。
于是输出点的时间戳成段倒错 —— 4000 点实测 **28 处逆序**。ECharts 的 time 轴按数组
顺序连线，不会替你排序：曲线在每个桶里折返一下，图看着有起伏，但形状是错的；
`sampling: "lttb"` 也要求有序输入，跟着一起失效。这属于「不报错、不空白、但结论错」，
肉眼极难发现。

**修复**：桶内先按时间排序（`sorted(picks, key=lambda q: q[0])`），桶与桶之间天然递增。

### 2. 对比图红点上限 400 → 直接切片，后半段全无红点

`_echart_compare_option` 的 `bad[:400]`。长会话里超标点往往集中在前半段，取前 400 个
之后，后半段**一个红点都没有** —— 看图的人会得出「后半段全达标」这个错误结论。
复现实测：2000 点全超标，旧逻辑最后一个红点落在第 1776 秒，**末尾 224 秒空白**。

**修复**：超 400 时按**时间均匀抽样**（`bad[int(i*len/400)]`），红点覆盖全时段。

### 3. 初始化失败只剩空白块

`_echarts_script` 直接 `echarts.init(...)`，没有 try/catch，也没有「库是否真的加载
成功」的判断。服务端只检查库文件在不在 —— 文件在、但对方浏览器内核过旧、或安全
软件把内联脚本拦了时，`init` 抛错，7 个容器就是 7 个 180px 的空白块。读者会以为
「这次没采到数据」，而不是「图表没画出来」。

**修复**：库未定义时统一给每个容器写「图表初始化失败：ECharts 未加载（脚本被拦截
或浏览器版本过旧）」；`init` 与 `resize` 各自包 try/catch，单图失败不牵连其余六张。
文案用 `textContent` 写入，不拼 HTML。

## 回归测试（都做过回退验证）

| 用例 | 锁死的行为 | 回退到旧代码时 |
| --- | --- | --- |
| `test_echart_downsample_keeps_time_order_and_extremes` | 抽稀后时间严格升序、点数 ≤ cap、尖峰与首末点保留 | 失败（第 1 处逆序 10079 vs 10008） |
| `test_echart_downsample_keeps_none_gaps_and_small_series` | None 断线不被填成 0、点少时原样返回 | 失败（同上） |
| `test_compare_bad_point_cap_covers_whole_span` | 400 个红点覆盖到会话末尾 | 失败（末点 1776s < 1990s） |
| `test_report_states_reason_when_echarts_init_fails` | 未加载 / init 失败都有明确文案 | 失败（兜底分支被去掉即缺字符串） |

## 顺带核对（都没问题，不改）

- `_echart_option` 返回 None 时调用方出 `nochart` 卡片，**不会**把 null 塞进 option 数组
  导致整段脚本中断（那会让七张图全不渲染）。
- `_echart_card` 的容器 id（`ec%d`）与 option 下标**同步自增**，中间插入 nochart 也不会错位。
- 对比报告 `t_first` / `t_last` 取各设备首末样本，`perf_export` 已过滤空样本，不会 IndexError。
- 阈值 `markArea` 的单点补宽按抽稀间隔算，最宽约 6 秒 / 8000 秒会话 ≈ 0.6px，视觉可忽略。
- `core/prefs.py` 已是「唯一临时名 + `os.replace`」原子写；`core/shell.py` 已指定
  `encoding` 与 `errors="replace"`，无需动。

## 验证

- `pytest tests/test_backend_perf.py`：**98 passed**（+3）。
- 抽稀修复后 8000 点报告 **1.00MB**（< 1.2MB 守卫），时间轴严格升序，尖峰保留。
- 无头 Chromium：正常报告仍是 **7 个 canvas**；把内联库脚本删掉再打开，**7 个容器
  全部**显示「图表初始化失败：ECharts 未加载…」，不再是空白块。

# 第二十九轮：截图落盘前校验 PNG 头（「分辨率不对」的真因不是没 root）

## 现象

车机上截图失败，提示与「图片分辨率」有关。第一反应容易归因到「车机没有 root」，
但这条路走不通：

- `screencap` 是 Android 的系统命令，**普通 shell 用户就能执行**，截图本身不需要 root；
- 真正受 root 影响的是 `screenrecord` 的部分参数、`/data` 下受限目录的写入等，
  截屏不在其列；
- 若真是权限问题，adb 会在 stderr 明确回 `Permission denied`，程序原样显示，
  不会冒出「分辨率」字样。

## 真因：`exec-out` 的字节被换行转换

`screencap -p` 输出 PNG 二进制，经 `adb exec-out` 传回。个别 Windows adb 版本
（以及少数车机侧的 adb 实现）会在这条通道上做 **LF → CRLF** 转换，把数据里的
`0x0A` 改成 `0x0D 0x0A`。

后果很隐蔽：

* PNG 签名 `\x89PNG\r\n\x1a\n` 本身带 `\r\n`，开头照样认得出来；
* `normalize()` 只切前导垃圾与尾部 IEND，看不出中间被插入的字节；
* 但 IHDR 里的宽高字段 / CRC 已经被改掉 —— 落盘是一张**打不开或尺寸荒谬**的图，
  看图软件 / 剪贴板只会报一句「分辨率无效」「参数无效」，与真相（传输被改写）无关。

旧实现到这里就结束了：文件写下去，界面报「已保存截图」。用户打开才发现是坏图 ——
典型的「不报错但结果错」。

除了换行污染，还有第二种更常见的损坏：**传输被截断**。车机 4K 截图动辄几 MB，
adb 管道超时 / 断连会让字节流停在中途 —— IHDR 完整、IDAT 缺一截、没有 IEND。
这种图能通过头部校验，落盘后却打不开或只画出上半张。

## 修复

`core/imgbytes.py` 新增两个判断：

* `png_size(data)`：解析 IHDR 的 33 字节（长度 + 类型 + 13 字节数据 + CRC），
  返回 `(宽, 高)`；结构不对、CRC 不符、边长不在 0~16384 内返回 None。
  只验头、不解压 IDAT，大图也不变慢。
* `png_complete(data)`：是否以完整 IEND 块收尾；缺 IEND 即传输被截断。

`ScreenCapturer.screenshot` 在 `normalize()` 之后、落盘之前做两道校验，任何一道
不过都**不落盘**（与「认不出格式就别写坏图」同一原则）：

1. 头坏了 → 「设备返回的 PNG 头已损坏（共 N 字节，头部 …）」；
2. 缺 IEND → 「设备返回的 PNG 不完整（共 N 字节，缺少 IEND 块）」。

两条错误都直接给出车机上更可靠的替代（不经过 stdout 的文本转换）：

```
adb shell screencap -p /sdcard/s.png
adb pull /sdcard/s.png
```

## 回归测试

| 用例 | 锁死的行为 |
| --- | --- |
| `test_png_size_reads_dimensions` | 正常 PNG → (1080, 2400) |
| `test_png_size_rejects_corrupted_ihdr` | 宽改成 0 / CRC 被改 → None |
| `test_png_size_accepts_4k_and_rejects_absurd_edge` | 3840×2160 放行；20000 拒绝 |
| `test_png_size_rejects_non_png_and_truncated_head` | 非 PNG、截在 IHDR 中间 → None |
| `test_png_complete_requires_iend` | 有头无 IEND 判为不完整 |
| `test_screenshot_rejects_png_with_broken_ihdr` | 坏头不落盘、错误里带 `adb pull` |
| `test_screenshot_rejects_truncated_png` | 截断图不落盘，报「缺少 IEND」 |

回退验证：把两道校验分别改成 `if False:`，坏图 / 半张图立刻被写入磁盘
（`path` 非 None），对应用例失败。

顺带修正两条旧用例的 fixture：文件名安全 / 同秒唯一这两条原本用「PNG 签名 + 64 个
0」的假图，只关心能不能落盘。换成真实的 1×1 PNG 后，它们仍然只测文件名，不再
依赖「坏数据也能通过」这个偶然前提。

## 验证

- `pytest tests/test_core_imgbytes.py tests/test_backend_screen.py`：**71 passed**。
- 全量 `pytest` 与 `pyflakes` 见提交说明。

# 第三十轮：截图自动降级 + 分辨「adb shell 要密码」与「权限被拒」

## 现象

用户反馈车机截图失败，提示与分辨率有关；补充说明**该车机的 `adb shell` 本身要
校验密码**。上一轮只做到「识别坏图 → 拒绝落盘 → 建议改用 `adb shell screencap
-p` + `adb pull`」，有两个问题：

1. **把补救推给了人**。既然坏图有确定可行的第二条通道，就该程序自己走，而不是
   让用户复制粘贴两条命令；
2. **建议可能根本执行不了**。shell 要密码时，用户手工 `adb shell` 也进不去，
   这条建议等于空话；而程序此时只会说「设备未返回图像（adb 没有给出原因）」，
   用户完全无从判断是密码、权限、还是线松了。

## 修复一：两条取图通道，坏了自动换

```
exec-out screencap -p          ← 快、不在设备留文件；坏了（头坏 / 截断 / 空）
        ↓ 自动
shell screencap -p /sdcard/x   ← 设备端先落盘
adb pull /sdcard/x  <local>    ← sync 协议，二进制原样传输
adb shell rm -f /sdcard/x      ← 成败都清
```

* 降级拿到的字节同样过 `_validate`（头 + IEND），坏图仍然不落盘；
* pull 先写 `<目标>.part`，读入内存后立刻删掉，最终由 `_save` 统一写一次；
* 设备端临时文件名带本进程序号（`adbdc_shot_<序列号>_<n>.png`），连点不覆盖；
* 只有两条通道都失败才报错，且**两条通道的原因分别列出**——不再丢第一条的原因。

## 修复二：先探 `adb shell`，再决定要不要试 pull

`_probe_shell` 执行 `adb shell echo __ADB_SHELL_OK__`（8 秒超时），把结果分成
`ok / password / denied / unauthorized / gone / timeout / unknown`：

| 状态 | 判定依据 | 为什么必须先判 |
| --- | --- | --- |
| `password` | 输出含 `password` / `Passwd` / `login:` 等 | 车机 adbd 停在 `Password:` 等输入，任何命令都只是「没有输出」 |
| `timeout` | 8 秒内无任何响应 | 同上，且本工具没有终端可输入 |
| `denied` | `permission denied` / SELinux / `not allowed` | 定制系统收紧了 shell，pull 必然同样失败 |
| `unauthorized` | `unauthorized` / `authentication required` | USB 调试没点允许 |
| `gone` | `device not found` / `offline` | 线断了，重试无意义 |
| `ok` | 输出里带回 marker | shell 通道正常，故障只在 screencap 或传输 |

先在 `echo` 上判一次，有两个好处：**不白等**（密码 / 权限问题下 pull 会一直卡到
60 秒超时）、**不淹没原因**（一长串重试之后只剩最后一句无关报错）。

## 提示语：四种情况分开说

`_shell_blocked_text()` 按状态给不同文案，核心是**别再让人误以为是「没 root」**
（`screencap` 本来就不需要 root）：

* 密码：说明「手工执行 `adb -s <序列号> shell echo hi` 会停在 Password:」，本工具
  没有终端可代为输入，需先在车机上完成调试授权；附 adb 原话。
* 权限：明确写「screencap 不需要 root，是定制系统收紧了 shell 权限，换别的 adb
  命令同样会被拒」。
* 未授权 / 掉线 / 超时：各自给出可照做的下一步，超时时把「密码」列为第一嫌疑。

## 回归测试（全部做过回退验证）

| 用例 | 锁死的行为 | 回退后 |
| --- | --- | --- |
| `test_screenshot_falls_back_to_pull_when_exec_out_is_corrupted` | 坏头自动改走 pull，落盘与原图逐字节一致，无 `.part` 残留 | 关闭降级 → 失败 |
| `test_screenshot_stops_and_explains_when_shell_needs_password` | 提示含「授权密码」「Password:」「echo hi」 | 关闭诊断 → 失败 |
| `test_screenshot_shell_timeout_points_at_password_first` | 超时文案把密码列为首要嫌疑 | 关闭诊断 → 失败 |
| `test_screenshot_does_not_blame_root_when_shell_is_denied` | 权限被拒时点明「不需要 root」 | 关闭诊断 → 失败 |
| `test_screenshot_reports_both_channels_when_pull_also_fails` | 两条通道的原因都在 | — |
| `test_pull_capture_cleans_remote_and_part_file` | 命令序列 = screencap → pull → rm，本地无 `.part` | — |
| `test_exec_out_reports_adb_error_from_stdout` | adb 把报错打在 stdout 时仍能读到 | — |

原有 4 条「坏图拒绝」用例改为钉住降级路径（`_stub_fallback`）：坏图断言仍然成立，
只是错误文案从「建议你去敲 adb pull」变成「两条通道都试过之后的原因」。

## 端到端验证（假 adb 模拟五种车机）

| 场景 | 结果 |
| --- | --- |
| 正常 | exec-out 直接成功，落盘与原图一致 |
| exec-out 把 `0x0A` 换成 `0x0D 0x0A` | **自动降级成功**，落盘字节与原图一致（不再是坏图） |
| `shell` 回 `Password:` | 报「需要先输入授权密码」，附 adb 原话，不落任何文件 |
| `exec-out` 回 `device not found` | 报「设备当前不可用」，0 秒返回（不做无意义降级） |
| `shell echo` 挂起 30 秒 | 8 秒超时后报「没有任何响应」，密码列第一嫌疑 |

远端 `/sdcard` 无残留、本地无 `.part`、失败时保存目录为空。

## 已知取舍

* 失败路径多付一次 `echo` 探测（最多 8 秒）。正常截图完全不受影响；
* **不代输密码**：密码 / 授权码属于用户凭据，程序只提示，不尝试自动填入；
* 若某车型每次 `adb shell` 都强制要密码且无法记住授权，本工具确实无法截图——
  提示语会说明这一点，并建议先用系统命令行确认。

# 第三十一轮：内置「重启ADB」改用 taskkill 强杀进程

## 诉求
指令台内置的「重启ADB服务」只有 `kill-server → start-server → devices`。
`adb kill-server` 只是给 adb 服务发一条退出指令，**当 adb.exe 进程卡死（不响应指令）
时，服务永远起不来**，重启形同虚设。用户要求内置命令先做 `taskkill /F /IM adb.exe`，
再 kill/start-server，并用 `||delay=N` 控制每条之间的间隔。

## 修复
把 `bi.restart-adb` 升级为「重启ADB」，在 kill-server 之前先用 `taskkill` 强杀进程：

1. `taskkill /F /IM adb.exe 2>$null`（delay 100）—— 强杀进程；`2>$null` 压掉
   「找不到进程」的报错（PowerShell 语法，不是 cmd 的 `2>nul`）；
2. `adb kill-server`（delay 1000）—— 兜底清残留；
3. `adb start-server`（delay 1000）—— 拉起新服务；
4. `adb devices`（delay 1000）—— 确认设备在线。

`2>$null` 必须是 PowerShell 的重定向，持久 PowerShell 会话里才不报错。

## 回归测试
- `test_builtin_restart_adb_kills_process_before_server`：step0 必须以
  `taskkill /F /IM adb.exe` 开头且含 `2>$null`；间隔 `[100,1000,1000,1000]`；
  命令序列逐条钉死，回退旧实现会让该断言失败。

## 验证
- `pytest`：**1283 passed / 1 skipped**（较上轮 +1）。
- `pyflakes backend core tools tests`：0。
- 前端 72 文件 0 失败。

# 第三十二轮：指令台三处易用性打磨（更新提示语 / 保存目录「选择」/ 截图预览）

## 改动一：新版本提示语修整（只覆盖 exe，json 配置保留）
- 旧文：「在浏览器里下载后，退出本程序并用新包里的文件覆盖当前目录即可；
  `config.json` 是你的设置，覆盖时请保留它。」—— 笼统说「覆盖当前目录」，
  用户可能把 `quick_commands.json` 等本地配置也一并替换 / 删掉。
- 新文：「……**只用新包里的 exe 覆盖当前目录下的同名 exe** 即可；其余
  `*.json` 配置文件（`config.json`、`quick_commands.json` 等）是你的本地设置，
  **请勿替换或删除**。」
- 文件：`frontend/index.html` 的 `#update-hint`。

## 改动二：保存目录增加「选择」按钮 + 「打开」更名「打开目录」
- 三处保存目录（工具 / Logcat / 文件）各加一个「选择」按钮，点击弹系统文件夹
  对话框（`SHBrowseForFolder` + `BIF_USENEWUI`，带可粘贴路径的输入框），
  代替手动输入路径；原「打开」按钮更名为「打开目录」。
- 后端新增 `FileMixin.select_save_dir`：仅 Windows 原生支持，其它平台返回
  `unsupported`，用户取消返回 `cancelled`。
- 前端 `api.select_save_dir` 选中后写回输入框、镜像到另两处、落盘 save_settings。

## 改动三：截图完成后生成可拖拽预览图
- 截图卡片下方新增预览区：每次截屏完（`tool` 事件 `type:"screenshot"）在卡片
  下方生成预览图，默认宽度自适应工具卡内容区最大宽度。
- 后端新增 `ScreenshotMixin.screenshot_data(path)`：读落盘 PNG 返回 base64
  （带存在性 + PNG 魔数校验，避免把非图片当预览图）。
- 右下角手柄可拖动改变大小、双击恢复自适应（复用备用投屏预览的手感，
  落盘 `shot_preview_w/h`，下次启动还原）。

## 回归测试
- 后端：`test_backend_file.py`（select_save_dir 三分支）、
  `test_backend_screenshot.py`（screenshot_data 正常 / 缺失 / 非 PNG）。
- 前端：`update_hint.test.cjs`（提示语文案 + 按钮更名）、
  `savedir_pick.test.cjs`（选择回写 + 落盘）、
  `shot_preview.test.cjs`（预览渲染 + 拖拽改大小 + 双击还原）。

## 验证
- `pytest`：**1290 passed / 1 skipped**（较上轮 +7）。
- `pyflakes backend core tools tests`：0。
- 前端 75 文件 0 失败。

# 第三十三轮：投屏卡片换位 + 工具区卡片长按拖动排序

## 改动一：投屏卡片挪到录屏下方（第三位）
- 旧序：截图 → 录屏 → 应用安装 → 诊断包 → **投屏（第五）**；用户希望投屏紧挨录屏。
- 新序：截图 → 录屏 → **投屏** → 应用安装 → 诊断包（`#scrcpy-card` 从诊断包之后
  移到 `#rec-card` 之后）。HTML 默认序即此，未保存过顺序的用户直接看到新布局。

## 改动二：工具区卡片支持长按拖动排序
- 五张卡（截图 / 录屏 / 投屏 / 安装 / 诊断）标题栏注入拖拽手柄 `.tool-grip`（两列圆点图标，
  仅作视觉提示），**长按手势绑在整条标题栏上**——点哪都能拖。
- 复用指令卡那套长按手感：`pointerdown` 后需按住 ≥400ms 才进入拖动态（`is-dragging` +
  `body.tool-sorting`），中途移动超 8px 视为滚动/误触、放弃本次长按；松手若真拖过，
  则压制紧随的 `click`，避免「拖了一下卡反而折起」。
- 拖动中实时换位（`elementFromPoint` 命中目标卡、按纵向中线决定插到前/后）；松手落盘
  `tool_card_order`（逗号串，与 `cmd_order` 同一约定）。
- 启动按保存顺序恢复（`applyToolCardOrder`）：顺序表里的卡按序排，表里没有的（如未来
  新增的卡）补到末尾，不把顺序顶歪。后端 `core/prefs.py` 的 `PREFS_DEFAULTS` 注册
  `tool_card_order`（默认空 = 用 HTML 默认序）。
- CSS：`.tool-grip`（cursor:grab）、`.tool-card.is-dragging`（抬层 z-index:40 + 磷光青描边 +
  轻微放大 + 禁选中）、`body.tool-sorting`（整页 grabbing 光标）。

## 回归测试
- 前端 `tool_card_order.test.cjs`（21 条断言）：默认序投屏第三位且 5 张卡各有手柄；
  启动按保存序恢复、未知卡补末尾；长按需等待才激活、短按不触发；拖动换位 + 松手落盘
  + 紧随 click 被压制；折叠开关仍可用（回归）。
- `tool_cards_layout.test.cjs`：同步更新预期顺序为「截图→录屏→投屏→安装→诊断」，锁定新默认布局。

## 验证
- `pytest`：**1290 passed / 1 skipped**（较上轮持平）。
- `pyflakes backend core tools tests`：0。
- 前端 **76 文件 0 失败**（较上轮 +1：新增 `tool_card_order.test.cjs`）。

# 第三十四轮：无线调试「假失败 / 重复播报」修复

## 现象
用户反馈：对 USB 设备开好无线调试（tcpip 5555，已读出 IP）、填地址点「连接」后，
日志同时出现「✓ 检测到新设备：172.20.2.35:5555」与「✗ 无线连接失败：failed to
connect」，自相矛盾；且失败提示还重复弹了两条。

## 根因（两处）
1. **假失败**：`wifi_connect` 直接信任 `adb connect` 的 stderr。车机 / 手机上设备
   常常已经注册进 `adb devices`（连接握手还在路上），`adb connect` 却打印
   「failed to connect」。于是 device_service 的轮询先报「检测到新设备」，连接逻辑
   又报「连接失败」——同一台设备、同一个地址，成功与失败并存。
2. **重复播报**：`wifi_connect` 后端已 `_push_status` 了一条 `✗ 无线连接失败（addr）：`
   （toast=True），前端 `wifiConnect` 拿到 `res.reason` 后又 `pushStatus` 一条
   「✗ 无线连接失败：」，成功路径同理各弹两条。

## 修复
- 新增 `_wifi_device_state(addr)`：连接后查 `adb devices`，返回该地址的真实状态
  （`device` / `unauthorized` / `offline` / ''）。
- `wifi_connect` 改为**以 adb devices 实际状态对账**：
  * 状态为 `device` → 判连上（纠正假失败）；
  * `unauthorized` → 给「请在车机端允许 USB 调试」的准确提示；
  * `offline` → 给「已注册但连接未就绪，稍后重试」；
  * 地址根本不在列表 → 才是真失败，保留原报错文案；
  * 成功收尾抽成 `_wifi_connect_ok`（记最近 + 推成功 + 刷设备列表）。
- 前端 `wifiConnect` 去掉重复的 `pushStatus`：连接成功 / 失败 / 授权 / 离线的反馈
  统一由后端推送（含对账说明），前端不再二次播报，避免与「检测到新设备」打架。
- `shutting_down` 等末态分支也补上状态推送，保证「单一推送源」。

## 回归测试
- `test_backend_wifi_apk.py` 新增 4 条：假失败被纠偏为成功、unauthorized / offline
  给准确提示、真失败（地址不在 adb devices）不误判；并锁「失败只播一条」
  （后端单一推送源）。

## 验证
- `pytest`：**1294 passed / 1 skipped**（较上轮 +4）。
- `pyflakes backend core tools tests`：0。
- 前端 76 文件 0 失败。


# 第三十五轮：截图新增「自动保存文件」开关（默认开启）

## 现象
用户希望：不想每次截图都往保存目录塞一张图时，有个开关能关掉落盘；但仍要生成预览、
可复制到粘贴板。原截图逻辑是无条件写盘，没有这个开关。

## 修复
- `core/prefs.py` 的 `PREFS_DEFAULTS` 注册 `shot_save_file`（默认 True）。
- `backend/screen_service.ScreenCapturer.screenshot` 增加 `save_file` 参数：为 False 时
  不写保存目录，而是写到系统临时目录（前缀 `adc_shot_`，随程序退出/启动被清理），
  仍可供预览与剪贴板使用。
- `backend/controllers/screenshot.py`：`screenshot(serial, to_clipboard, save_file)` 透传
  save_file；新增 `_shot_save_file_pref`；`toast` 文案区分「已保存截图（路径）」与
  「截图完成（未保存到目录）」；批量汇总也按 `b["saved"]` 描述是否落盘。
- 前端：截图卡片在「立即截图」同一行新增「自动保存文件」复选框（默认勾选）；
  `shotSaveFile` 进 `els`，按 `shot_save_file` 偏好回填，点击随截图动作下发给
  `api.screenshot` 第 3 参数，并 `persistPref`。

## 回归测试
- 后端 `test_backend_controller.py` 新增 3 条：`save_file` 默认 True、关掉后不落盘且
  toast 提示「未保存到目录」、显式传 False 优先生效；并补齐因新增参数签名变化的
  多个内联 fake。
- 前端 `tests/frontend/screenshot_autosave.test.cjs`（14 断言）：默认勾选、随动作下发
  第 3 参数、取消持久化、启动按偏好回填。
- `tests/test_core_prefs.py` 的布尔键映射表加入 `shot_save_file`；
  `tests/frontend/checkbox_switch_style.test.cjs` 复选框计数 29→30（工具×5→×6）。

# 第三十六轮：Logcat 实时监控「保存到文件」改走后端写盘

## 现象
用户反馈：点「保存到文件」没有任何反应。

## 根因
原 `saveLogcat` 用 `a.click()` + Blob 下载。在 WebView2（本程序运行环境）下，程序化
锚点下载被静默吞掉——`URL.createObjectURL` 的 blob 链接点了没动静，文件既不出现也不报错。

## 修复
- `backend/controllers/logcat.py` 新增 `logcat_save(serial, text)`：把当前视图文本写入
  保存目录（`logcat_<序列号>_<时间戳>.txt`，`unique_path` 防重名），回传路径并推 toast；
  空内容明确拒绝（不写空文件）。
- 前端 `saveLogcat` 改为 `callApi(api.logcat_save(lcSerial, bufToText(lcSerial)))`，按
  返回结果给用户成功/失败提示。

## 回归测试
- 后端 `test_backend_controller.py` 新增 2 条：写盘落盘且回传路径、空内容被拒。
- 前端 `tests/frontend/logcat_save_filename.test.cjs` 改写为断言「点击调用
  api.logcat_save(serial, text) + 完整文本送后端 + 空缓冲不调用」；
  `tests/frontend/logcat_restart_clears_buffer.test.cjs` 同步适配新后端写盘路径。

# 第三十七轮：Logcat 实时监控过滤完善

## 现象
用户输入「账号绑定」，下方区域没显示出对应文字。

## 根因（两处）
1. `renderLogcat` 重建时只扫描缓冲最后 `LC_RENDER_CAP`(3000) 行：较早出现、已被实时
   裁剪出视图的命中行永远搜不到。
2. 关键字在后端 `logcat_start` 启动时固定预过滤：缓冲里只剩当时命中的行，之后改关键字
   只能越缩越窄、清掉关键字也回不来（`bufToText` 也就读不到早先被丢的行）。

## 修复
- 前端 `startLc` 不再把关键字下发给后端（仍发级别 + 仅异常，二者是流量闸门）；
  关键字完全在前端对**完整缓冲**做实时过滤（窄/宽都行）。
- `linePassesFilter` 的搜索范围从 `msg + tag` 扩展到整行 `raw`，tag/msg 之外字段里
  的关键字也能命中。
- `renderLogcat` 关键字激活时扫描**整个缓冲**并按命中行渲染（超 `LC_RENDER_CAP` 取最近
  一批）；计数区附「命中: N」反馈，过滤没反应时至少能看出是搜到 0 行还是界面卡住。

## 回归测试
- 前端 `tests/frontend/logcat_filter_full_buffer.test.cjs`（4 断言）：4000 行缓冲里关键字
  命中第 100 行（远早于最后 3000 行）也能显示并给出命中数；清空关键字还原全部。

# 第三十八轮：性能监控新增「查看报告」按钮

## 现象
用户希望在「导出报告」之后有一个「查看报告」入口，一键打开报告所在目录。

## 修复
- `index.html` 在 `perf-export` 之后新增 `perf-view`（查看报告）按钮。
- 前端绑定点击 → `callApi(api.open_save_dir(saveDir()))`，复用工具页「打开目录」同一套
  后端调用，打开报告（保存）目录。

## 回归测试
- 前端 `tests/frontend/perf_view_report.test.cjs`（5 断言）：按钮存在且位于导出报告之后；
  点击调用 `open_save_dir` 打开保存目录。

# 第三十九轮：工具区五项功能改为子 tab

## 现象
工具区原本是「设备截图 / 设备录屏 / 投屏 / 应用安装 / 诊断包」五张卡竖排，每张卡标题栏
可点开/收起。用户希望把这几项改成不同的**子 tab**，这样单项功能能显示得更完整，
不必靠「逐卡收起」去省高度。

## 决策（与用户确认）
- 去掉「点标题收起/展开」：子 tab 一次只显示一项功能，天然互不挤压。
- 「工具卡可长按拖动改顺序」改为「长按拖动排子 tab」，顺序落盘到 `tool_tab_order`
  （覆盖原来的 `tool_card_order`），顺序表外的 tab 补到末尾。

## 修复
- `index.html`：原五张卡整段包进 `#tool-subtabs`（`role=tablist`，5 个 `.tool-subtab`
  子 tab 按钮）+ `#tool-panes`（5 个 `.tool-pane[data-tool-pane=...]`）。每张卡标题栏从
  可折叠的 `.tool-h--toggle`（带 `.tool-chevron`）改为纯 `.tool-h`，内部控件 id 全部保留。
- `css/app.css`：删除 `.tool-h--toggle` / `.tool-chevron` / `.tool-card.collapsed` 等旧折叠
  规则；新增 `.tool-subtab`（与关于页 `.about-subtab` 同一套视觉语言：`surface` 底、`muted`
  字、选中态 `accent` 描边 + 光晕）、`.tool-subtab .tool-grip`（12×14 拖拽手柄）、
  `.tool-subtab.is-dragging`（拖动中降透明度）、`.tool-pane[hidden] { display:none }`
  （未激活面板隐藏）；清理已无用的 `.tool-grip` 旧卡级拖动态规则，仅保留
  `body.tool-sorting` 整页 `cursor:grabbing`。
- `js/app.js`：原 `TOOL_CARDS` 折叠 + 卡级拖动整套替换为 `TOOL_TABS` 子 tab 逻辑——
  `switchToolTab` / `bindToolSubtabs`（click + Enter/Space 切换，拖动后压制紧随 click）、
  `injectToolTabGrips` / `loadToolTabOrder` / `applyToolTabOrder` / `saveToolTabOrder` /
  `bindToolTabDrag`。**修复 `saveToolTabOrder` 的排序 bug**：原先用固定数组 `TOOL_TABS`
  去 `filter(bar.contains(...))`，无论 DOM 怎么拖都只会还原成默认顺序，丢失用户刚排好的
  顺序；改为直接按 `#tool-subtabs` 内 `.tool-subtab` 的真实 DOM 顺序读取。

## 回归测试
- `tool_card_order.test.cjs`（重写）：子 tab 默认顺序 / `tool_tab_order` 启动回填（未知 tab
  补末尾）/ 长按 ≥400ms 才进拖动态、短按不触发 / 拖动换位 + 松手落盘（紧随 click 被压制）/
  点击切换面板显隐。
- `tool_cards_layout.test.cjs`（重写）：5 子 tab + 5 面板结构对齐、控件都在各自面板内、无
  折叠残留（`.tool-h--toggle` / `.tool-chevron` / `collapsed`）、子 tab 切换互不牵连、默认
  激活截图子 tab、非法 `tool_tab_order` 不破坏结构、录屏面板只剩 4 个开关。
- `tools_rec_collapse_scrcpy.test.cjs`：移除折叠断言，改为子 tab 切换 / 键盘 Enter·空格
  切换 / 默认激活截图子 tab；保留投屏探测、scrcpy 启停、kebab 层级与尺寸回归。
- `settings_persist.test.cjs`：移除 `shot_collapsed` / `scrcpy_collapsed` 落盘断言，新增
  `tool_tab_order` 启动回填校验。
- `ui_style_card_tabs.test.cjs`：把 `tool-subtab` 纳入允许样式类清单。

# 第四十轮：工具子 tab 无障碍补全 + 测试健壮性

## 优化点
- 补全 ARIA tabs 语义：tablist 加 `aria-orientation`；每个子 tab 加 `id` / `aria-controls` /
  roving `tabindex`（激活项 0、其余 -1）；每个面板加 `id` / `role="tabpanel"` / `aria-labelledby`。
- 键盘导航：方向键 ←/→ 在子 tab 间移动并激活（按 DOM 视觉顺序、首尾循环），Home/End 跳首/尾；
  Enter/Space 仍可激活。
- 拖动排序中整页禁 `user-select`，避免长按拖动把子 tab 文字拉成选区。
- 清理死代码 `TOOL_TAB_SEL`；`toolTabBtn` / `toolTabPane` 查询收窄到 `#tool-subtabs` / `#tool-panes`。

## 测试健壮性修复
- `settings_persist.test.cjs` 残留一段已删除的 `shot-toggle` / `scrcpy-toggle` 点击（折叠功能已移除），
  `getElementById` 取到 null 后 `.click()` 抛异常；而该文件没有看门狗、`unhandledRejection` 又静默吞掉，
  导致整套前端测试在这里「假死」。移除残留块，并把 `unhandledRejection` 改为打印栈 + 立即退出。
- `tool_card_order.test.cjs` 增加方向键 / Home / End + roving tabindex + `role=tabpanel` / `aria-controls` 断言。

## 回归
- 受影响的 5 个前端用例全部通过：`tool_card_order` 39、`tool_cards_layout` 75、
  `tools_rec_collapse_scrcpy` 51、`ui_style_card_tabs` 36、`settings_persist` 57（均 0 失败）。

# 第四十一轮：工具子 tab 收尾优化（记忆停留项 / DOM 派生 / Esc 取消）

## 优化点
- **记忆上次停留的子 tab**：新增 `tool_active_tab`（config.json）。启动按它恢复，没记过 /
  key 已失效（版本删了某项）则回退「设备截图」。启动回填传 `persist:false`，不会「打开就写一次盘」；
  值没变（连点同一项 / 方向键绕回原项）也不重复写盘。
- **tab key 从 DOM 派生**：删掉 JS 里手写的 `TOOL_TABS` 常量，改为 `toolTabKeys()` 读取
  `#tool-subtabs .tool-subtab` 的 `data-tool-tab`；`applyToolTabOrder` 用「按钮 ∪ 面板」求并集。
  将来增删一项只改 index.html，不会出现 JS 常量与 HTML 漂移。
- **面板底部多余空白**：`.tool-pane > .tool-card` 去掉 14px 下边距——一屏只有一张卡，
  那条原本留给「下一张卡」的间距会变成滚动到底的一截空白。
- **拖动结束后同步重排面板 DOM**：按钮顺序变了，面板也按同一顺序重排（`reorderToolTabs`），
  两者始终一一对应。
- **Esc 取消拖动**：拖动中按 Esc 还原按下前的顺序、退出拖动态且不落盘（松开也不再写）；
  解决长按误触没有退路的问题。
- **窄窗口换行时拖对位置**：子 tab 栏 flex-wrap 后可能排成两行，原实现只按目标的中线做
  水平判断，跨行拖动会插错。改为同行按水平中线、跨行按垂直中线（指针在目标行下方 = 插到
  它后面）。

## 配置 schema 修正（真实漂移）
- `core/prefs.py` 更新滞后于前端：仍登记 `shot_collapsed` / `rec_collapsed` / `scrcpy_collapsed` /
  `apk_collapsed` / `diag_collapsed` / `tool_card_order`（全部已废弃），而前端实际写入的
  `tool_tab_order`、`tool_active_tab` 却没登记（靠 sanitize「未知键原样保留」侥幸能存）。
  本轮删除 6 个废弃键、登记 2 个新键，并同步 `tests/test_core_prefs.py` 的豁免名单。
  老 config.json 里的旧键不会被删（sanitize 对未知键保留），只是不再读写。

## 文档同步
- `frontend/index.html` 关于页「功能概览」：由「竖向排列的三张卡、标题栏可收起」改为
  五个子 tab + 长按排序 + 记忆停留项。
- `README.md`：工具行与「配置持久化」清单同步为子 tab 模型（`tool_tab_order` / `tool_active_tab`），
  移除 `*_collapsed` 描述。

## 回归测试
- `tool_card_order.test.cjs` 扩到 54 条：新增「面板 DOM 同步重排」、「`tool_active_tab` 回填 /
  切换落盘 / 重复点击不写盘 / 失效 key 回退」、「Esc 取消还原且不落盘」、「换行后跨行拖动
  的插入位置」。
- 通过：`tool_card_order` 54、`tool_cards_layout` 75、`tools_rec_collapse_scrcpy` 51、
  `settings_persist` 57、`ui_style_card_tabs` 36、`about_subtab_manual` 14、
  `ui_layout_fixes` 17、`tools_tab_scroll` 7、`layout_resizable` 21（均 0 失败）。
- 后端 `pytest`：1299 passed / 1 skipped；`pyflakes` 干净。

# 第四十二轮：指令台工作区记住上次停留项

## 优化点
- 新增 `cmd_active_ws`（config.json）：重启后回到上次停留的那个工作区，而不是固定回 `w1`。
  存**名字**而不是内部 id —— id 按创建顺序给，关掉中间一个再重启，同一个 id 会指向另一个
  工作区；名字对不上（改过名 / 已关闭 / 手改坏）则回退第一个，不会出现「一个都不选」。
- 只在真的换工作区时写盘：启动恢复期间用 `wsRestoring` 压住回写（否则开 N 个工作区就往
  盘里写 N 次），重复点当前 tab 也不写。
- 改名的是当前工作区时，`cmd_active_ws` 同步成新名字（否则下次启动按旧名匹配不到、莫名回退）。

## 与工具区的行为对齐
- 工具区子 tab：`tool_tab_order`（顺序）+ `tool_active_tab`（上次停留）
- 指令台工作区：`cmd_workspaces`（布局）+ `cmd_active_ws`（上次停留）

## 回归测试
- `ws_tabs.test.cjs` 扩到 47 条：新增「按 cmd_active_ws 恢复激活 tab / 往返切换落盘 /
  重复点击不写盘 / 名字失效回退第一个 / 启动恢复不写盘」。
- `ws_rename.test.cjs` 扩到 50 条：新增「改名当前工作区 → cmd_active_ws 同步」。
- 全量前端套件：79 个文件 0 失败（`run-all.cjs`，3m53s）；后端 `pytest` 1299 passed/1 skipped；
  `pyflakes` 干净。

# 第四十三轮：主 tab 记忆停留项 + 其他模块扫出的四个真实问题

## 一、主 tab 记住上次停留页（需求 1）
- 新增 `main_active_tab`（config.json）：重启回到上次那一页（设备指令 / 工具 /
  性能监控 / Logcat / 文件 / 关于），没记过或那一页已不存在则回退「设备指令」。
- 抽 `switchMainTab(key, opts)`：点击与启动恢复走同一条路径（性能页切回时的
  `renderPerfDev + queuePerfDraw` 因此只有一份），合法 key 从 DOM 派生，
  值没变不写盘、启动回填 `persist:false`（打开就写一次盘的问题同样避开）。
- 恢复点位于 `onBooted` 的 `renderCommands` 之后：切到性能页要按已勾选设备渲染
  目标设备条，切到设备指令页要求指令卡已画好；设备勾选态晚到也没关系，
  `devices` 事件里的 `renderPerfDev` 会补一次。

## 二、扫其他模块查出并修掉的真问题（需求 2）

### 1. 五处 `window.confirm` / `window.prompt`（最严重）
项目早就知道 pywebview 各版本对这两个原生方法支持不一致（`askConfirm` 的注释里
写着「部分版本里它是空函数，`!confirm(...)` 恒为 true」），但仍有五处直接用原生：

| 位置 | 后果 |
|---|---|
| 文件行「删除」 | `if (confirm(...))` → 恒 false，**单文件删除永远无效**（点了没反应） |
| 批量「删除选中」 | `if (!confirm(...)) return` → 恒 true，**跳过确认直接删多个文件**（不可恢复） |
| 命令「删除」 | 同上，**删命令没有确认** |
| 文件「重命名」 | `prompt` 返回 null，**重命名永远无效** |
| 文件「新建文件夹 / 新建文件」 | 同上，**两个入口永远无效** |

修法：新增应用内输入弹窗 `askInput(opts) → Promise<string|null>`（与确认弹窗同一
套骨架：遮罩 / × / 取消 / Esc 四个出口都是 null，空白名等同取消，回车提交，
默认聚焦并全选，Tab 焦点圈在弹窗内）。三处危险操作改走 `askConfirm`，
三处输入改走 `askInput`。**全仓已无原生 confirm / prompt 调用。**

### 2. 父目录行（`..`）带「重命名 / 删除」按钮
`..` 行是导航入口，却和其它行一样渲染了操作按钮：
- 重命名 = `mv /sdcard/Download/.. /sdcard/Download/x` —— **把父目录整个搬走**；
- 删除 = `rm -rf /sdcard/Download/..` —— 删上一级；
- 而它永远排在**第一行**，是最容易误点的一行。
现在 `..` 行只保留空的 `td.act`（列宽不错位），导航点击照旧。

### 3. 文件名校验：只改名，不搬家
`mv` 的语义是移动，所以重命名 / 新建的名称**不允许含 `/` 或 `\`**（`validateEntryName`），
空名与 `.` / `..` 一并拒绝；与原名相同则静默跳过。之前输入 `sub/x.txt` 会把文件
搬到子目录，输入 `/x` 还可能拼出 `//x`。

### 4. 两处异步竞态
- **上传目录**：`FileReader` 是异步的，原实现在 `onload` 里读 `fileSerial` / `filePath`，
  读完时用户可能已经切了设备或目录 → 「提示说传到 A，实际传到了 B」。
  现在进入函数时快照设备与目录，提示语也用同一份快照。
- **列目录失败事件**：`onFile` 的成功分支一直有 `p.serial !== fileSerial` 的迟到丢弃，
  错误分支却没有 —— 切设备时上一台迟到的 `ls` 失败会**清空当前设备的文件表格**、
  把路径栏回退。补上同样的校验。

### 5. 子 tab 拖动后的焦点竞态（测试暴露）
`applyToolTabOrder()` 用 `appendChild` 移动节点，浏览器会在「节点被移出文档」那一刻
丢焦点，这次复位与紧随的 `focus()` 谁先谁后没有保证（jsdom 下实测约一半概率被复位
回 body，`tool_card_order` 因此 6 次跑挂 3 次）。新增 `restoreToolTabFocus(tab)`：
延后一帧再聚焦，且若这一帧里用户已经把焦点放到别处（不是 body）就不抢回来；
拖动结束与 Esc 取消共用。

## 三、回归测试
- 新增 `main_tab_memory.test.cjs`（16 条）：默认页、按 `main_active_tab` 恢复、
  点击落盘、重复点击不写盘、失效 key 回退且不写盘、启动不写盘、切性能页会渲染
  目标设备条。
- 新增 `file_input_modal.test.cjs`（27 条）：输入弹窗结构与聚焦全选、确定/空白名、
  Esc/遮罩/取消三个出口、新建文件与新建文件夹、批量删除必须先确认、全程不碰原生
  prompt/confirm、父目录行无操作按钮但仍可上翻。
- `file_rename_target.test.cjs` 改写为走自绘弹窗（18 条），新增「带 / 的名称被拒绝」
  与「取消不下发」两段。
- `tool_card_order.test.cjs` 焦点断言改为等待一帧（55 条，连跑 6 次稳定）。
- 受影响用例全过：file_* 8 个文件、chip_menu_layer 26、rec_cancel 64、ws_tabs 47、
  tool_card_order 55、main_tab_memory 16、file_input_modal 27。
- 后端 `pytest`：1299 passed / 1 skipped；`pyflakes` 干净。

---

# 第四十四轮：录屏配套 logcat「后段日志整段丢失」——根因是两处真 bug 叠加

**现象（用户实报）**：录屏停止后，视频最后时间点是 11:14，同一场录制的
`logcat_*.txt` 最后一条却停在 10:50 —— 后 24 分钟一条日志都没有。界面全程只弹过
「✓ 录屏已完成」，没有任何「日志断了」的提示，直到事后拿视频时间轴去对日志才发现。

## 一、根因（两个 bug 叠在一起，缺一不可）

### 1. `device_present()` 在真机上恒返回 `None`（`backend/screen_service.py`）

```python
subprocess.run([...], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
               **adb_kwargs(timeout))     # adb_kwargs 自带 capture_output=True
```

`subprocess.run` 明确禁止 `capture_output` 与显式 `stdout=/stderr=` 同时出现，每次
调用都抛 `ValueError: stdout and stderr arguments may not be used with
capture_output.`，又被 `except Exception: return None` 吞掉 —— **函数从来没成功执行
过一次**。第二处错还叠在上面：`adb_kwargs` 是 `text=True`，比较却写成
`r.stdout.strip() == b"device"`，即便跑通也永远不等。

它不是一句日志的问题，而是三个判断的输入：

| 使用点 | 旧行为（恒 None） | 后果 |
|---|---|---|
| `LogcatCapture._worker` 掉线判定 | `device_present(...) is False` 永假 | 设备**真掉线**也走不成「等重连续写」，一律落到「设备在线」分支 |
| `LogcatCapture._wait_reconnect` | 轮询永远读到 None | 一旦进了重连等待，必然耗满 900 秒窗口才结束 |
| `_build_death_message` | `not None` 恒真 | 录屏中断原因永远被说成「设备连接已断开」 |

### 2. 「设备仍在线、`adb logcat` 自己退了」这一档，只报一句就收工

连接存活时 `adb logcat` 不会自己退出，它退出了说明是被外力打断的（logd 重启 /
adb 内部错误 / 别的工具 kill-server / **满缓冲全级别日志 + 录屏把 USB 带宽拉满**）。
旧实现 `if lines > 0: eof_unexpected = True; break` —— 就此结束，不再拉起。

两处叠起来正好是用户的现场：`adb logcat` 被 USB 带宽挤断 → `device_present` 恒 None
判不出掉线 → 走「设备在线 EOF」→ 直接收尾。而 device 端 `screenrecord` 是独立进程、
写入发生在设备本地（不占 USB），照旧录到 11:14。日志与视频就此分叉 24 分钟。

## 二、修法

### 1. `device_present()` 只传 `**adb_kwargs(...)`，按 `text=True` 比字符串
顺带新增 `device_epoch(adb, serial)`：读设备当前 Unix 时间（`shell date +%s`），
供收尾校验用。

### 2. 非用户停止的 EOF 一律「自动重启」（`LOGCAT_CAP_RESTART_*`）
与「设备掉线」同一套通道：写缺口标记 → 退避（0.4s 起、翻倍、上限 5s，用 Event
等待，**用户点停止立刻生效**）→ 重新拉起 → 继续写同一个文件。三个出口防止无限拉起：

- **连续 2 次重启都没带来任何新日志**（`LOGCAT_CAP_RESTART_NO_PROGRESS`）→ 停，
  按「意外退出、文件在此处截断」报错；
- 单次抓取最多重启 60 次（`LOGCAT_CAP_RESTART_MAX`，小时级录制里的偶发抖动够用）；
- 文件一行都没写进去时不重启（重启换不来内容）。

重启期间 `is_running()` 仍为 True（会话没结束），界面不会误切「空闲」。

### 3. 续写时把「缺失时段」写进文件（`LOGCAT_CAP_HOLE_WARN_S`）
设备环形缓冲区会滚：中断几分钟后，断连期间产生的日志已被新日志挤掉，新起的
`adb logcat` 只能从缓冲区里现存最早的那条开始重放。旧实现只写一句「恢复连接」，
文件看着是连续的 —— 这正是用户「丢了一大段却看不出」的原因。现在续写的第一条新
日志离断点超过 5 秒，就写一条明确标记：

```
--------- [logcat] 日志缺失：10:50:12.000 ~ 11:10:03.000 之间（约 1191 秒）的日志未能取回（中断期间产生的日志已滚出设备缓冲区） ---------
```

### 4. 跨天 / 设备校时：去重不再比字符串
重放去重原来直接比时间戳**字符串**：`"12-31 23:59" > "01-01 00:00"`，跨年录一整夜
之后，零点起的日志会被整体判成「比断点更早的重放」全部跳过 —— 文件就那么停在
23:59。现在凡是「看起来时间在倒流」都落到 `core.logcat.ts_epoch()` 比精确时刻
（threadtime 没有年份，按基准时间推断、晚半年以上判为上一年）；另设
`LOGCAT_CAP_REPLAY_SKIP_MAX` 兜底：跳过量远超缓冲区重放量级时，判定为设备时钟整体
回退，停止去重并写标记，而不是把之后的日志全扔掉。

### 5. 启动窗口内的「设备已消失」也要终止进程
`notice_device_gone` 若落在 `_starting` 窗口（Popen 还没返回）只加了 `_gone`，
worker 随后登记进程时并不检查它 —— 设备真拔掉、`adb logcat` 又迟迟不退出时，抓取
既停不下来也走不到掉线判定，界面永远停在「采集中」。现在登记进程时一并看 `_gone`。

### 6. 录屏收尾当场校验「日志跟到什么时候」
`_session_teardown` 打包**之前**读日志文件首尾时间戳（只读头尾各 128KB，不整文件扫描），
再用 `adb shell date +%s` 取设备当前时刻作参照 —— 双方都在设备时间轴上，不掺主机
时钟，也不会把「设备时钟比本机慢」误判成「日志丢了 24 分钟」。差值超 60 秒就播报：

> ⚠ A1 的 logcat 只跟到 10:50:12.000，距录屏结束还有约 24 分钟没有日志：
> 后段日志已丢失（文件内有 [logcat] 标记说明断点，状态栏有中断原因）

设备时钟与本机相差超 60 秒时另给一条 info（这种偏差会让视频文件名与日志时间戳
天然差出一截，极易被当成「日志丢了一段」）。结论排在「✓ 录屏已完成」**之后**播报
—— 用户视线停在最后几条，反过来的话他会以为这次录得完美无缺。

### 7. 前端 reconnecting 文案
这一档现在同时覆盖「设备掉线」与「抓取被中断后自动重启」，状态行不再写死
「设备掉线，等待重连」，改为「采集中…（已中断，正在自动重连）」，具体原因由后端
的 `text` 给出（状态栏）。

## 三、回归测试

- 新增 `tests/test_core_logcat_time.py`（11 条）：`ts_prefix` / `ts_epoch` 的正常、
  跨年回退、单调性、垃圾输入；`read_time_bounds` 的小文件、大文件（> 256KB，只读
  头尾）、尾部标记行不算时间戳、缺失 / 空文件。
- 新增 `tests/test_backend_record_logcat_coverage.py`（8 条）：24 分钟缺口告警、
  正常场景静默、文件无日志行 / 文件不存在的告警、设备时钟偏差提示、读不到设备时间
  与 adb 异常时安静跳过、收尾把结论带进会话并由「停止」播报。
- `test_backend_logcat.py` 改写并新增：设备在线 EOF 自动重启并续写、重启无进展时
  报「已截断」、续写跨空洞写缺失标记、跨天续写不丢行（固定「现在」为 2026-02-06
  让年份推断确定）、**退避期间点停止必须秒级收尾**（退避拉长到 30 秒仍要求 <1 秒
  结束，只有被唤醒才可能通过）。
- `test_backend_controller.py`：`device_present` 用例改按 `text=True` 语义给假件，
  新增一条**参数合法性**回归（复刻 `subprocess.run` 的 `capture_output` 冲突检查）。
- `test_backend_logcat_ratelimit.py`：抓取写完 3000 行后让后续重启立刻 EOF，并按
  「真日志行」计数（文件里还会有 `[logcat]` 标记行）。
- `logcat_capture_reconnect.test.cjs`：断言改为「自动重连」。

后端 `pytest`：**1323 passed / 1 skipped**；`pyflakes` 干净。
前端 `node tests/frontend/run-all.cjs`：**81 个文件、0 失败**。

---

# 第四十五轮：这类「产物残缺却没人知道」的结论，改成不点不消失的弹窗

**用户要求**：上一轮把日志丢失的结论做到了「文件里有标记 + 收尾播报」，但它
仍是一条 toast —— 4~8 秒自动消退。用户明确说：**再遇到类似情况，要明显的弹窗
提示，让他第一时间就知道**，而不是事后比对才发现。

## 一、为什么 toast 不够

上一轮修的是「日志为什么断了」；这一轮要修的是**断了之后怎么让人知道**。
toast 的定位是「顺带说一声」：它假设人正看着屏幕、且会在几秒内扫一眼右上角。
用户的实际场景恰好两条都不成立 —— 他点完「停止录屏」就去处理别的事了，回来
只看到「✓ 录屏已完成」。日志塌了 24 分钟这件事，就是这样过去的。

所以这不是「把 toast 调长一点」的问题，而是**换一种交互**：结论必须停在屏幕上，
由用户亲手关掉。同时它不能滥用 —— 弹窗一旦满天飞，用户会连看都不看就关，
真正要紧的那条也一起被关掉。判据定得很窄：

> **用户无法从界面察觉的产物残缺 → 弹窗；其余（操作结果、普通错误）→ toast。**

「录屏被意外中断」不弹窗，因为录制状态本身会变、用户当场就知道；「日志比视频
短了 24 分钟」必须弹窗，因为界面看起来一切正常。

## 二、后端：多一层 alert 通道（`backend/controllers/base.py`）

```python
_push_status(type_, text, toast=False, alert=False, alert_title="")
_push_alert(type_, text, title="")        # = toast + alert + 标题
```

`alert=True` 时 status 载荷多两个字段：`alert: true`、`alert_title`。不带 alert
的载荷与原来**逐字节一致**（既有断言全部照旧）。只有一处调用点升级：

- `record._push_logcat_notes` 的 warn 级（日志没跟到最后 / 文件不存在 / 文件里
  没有任何日志行）→ `_push_alert(..., title="⚠ 本次录制的日志不完整")`。
  info 级（设备时钟偏差）**保持** status：那是说明，不是告警。

## 三、前端：告警弹窗（`#alert-modal`）

- **不自动消失**：没有任何计时器与淡出路径。
- **多条合并**：多台设备同时出问题时全部列进同一个弹窗（编号 + 每条一行），
  而不是连弹 5 个窗口逼用户乱点。同一条结论重复到达不重复列。
- **role=alertdialog** + 焦点落在「我知道了」：键盘 / 读屏用户也能立刻感知。
- **底部「查看状态信息」**：关掉弹窗、打开状态面板 —— 弹窗里只放结论，完整
  原因链（哪台设备、断在哪、为什么）都在状态信息里。
- **Esc / × / 点遮罩都能关**：误触不该让人以为界面卡住；关掉只是少看一眼，
  状态栏那条记录还在。
- 层级 65（高于确认弹窗 60 与 toast）：它可能在确认框之上被叫起来（删除途中
  设备掉线），压在下面等于没提示。Esc / Tab 的处理顺序也是它最优先，否则
  「按 Esc 以为关掉了告警」实际关掉了背后的确认框。

Logcat 抓取侧同步升级：`stopped` 带 `gap`（时间缺口）或 `error`（写盘中断）
时也走告警弹窗 —— 同一个道理，文件不完整但界面看不出。

## 四、顺手修掉一个真 flaky（两处，都是测试自身缺陷）

整套跑时偶发 `test_capture_cross_day_timestamp_is_not_treated_as_replay` 与
`test_pull_gives_up_at_once_on_permission_denied` 失败，单跑永远通过。查下来
都不是功能问题：

1. **上一个用例的抓取 worker 还在自动重启循环里**，它调用的是下一个用例刚
   patch 进去的假 `Popen` —— 按 `call["n"]` 或 `procs.pop(0)` 计数的假件被它
   抢走一个批次，下一个用例的第二段日志就「凭空消失」。修法：假 Popen 按
   serial 分流（`_popen_by_serial`），别人的 worker 只拿到空 EOF。
2. **`test_pull_gives_up_at_once_on_permission_denied` 统计 sleep 时没限定线程**，
   后台 watcher 在窗口内的一次 sleep 就被判成「这条路径在退避」。修法：只统计
   当前线程。

这两条正是那种「本地好、整套跑挂、看起来像功能坏了」的假失败，留着会掩盖真
问题。

## 五、测试

- 新增 `tests/frontend/alert_modal.test.cjs`（30 条）：带 alert 才弹窗、1.5 秒后
  仍开着、普通 warn/err 不弹窗、多设备合并成一个弹窗、重复结论不重复列、
  「我知道了」关闭后可再次打开、Esc 只关最上层且不动状态面板、
  「查看状态信息」跳转、超上限只列 12 条但底部说清「另有 N 条」、
  弹窗已开时新告警不抢走用户当前焦点。
- `tests/test_backend_record_logcat_coverage.py` 新增 3 条：warn 结论必须带
  `alert` + `alert_title` + `toast`；info（时钟偏差）不得弹窗；
  `_push_toast` 与 `_push_alert` 的载荷分工。
- `test_backend_controller.py` 新增 1 条：勾了打包却没打成时必须播报「打包失败」
  并弹 toast（源文件一个都不能删）。

后端 `pytest`：**1327 passed / 1 skipped**；`pyflakes` 干净。
前端 `node tests/frontend/run-all.cjs`：**82 个文件、0 失败**。

---

# 第四十六轮：覆盖度校验的时区陷阱——差 8 小时的「假丢日志」

上一轮刚把「日志比视频短」做成了不点不消失的弹窗。这一轮修的是**它会误报**。

## 一、问题

logcat 的 threadtime 是**设备本地墙上时间**（`03-01 03:14:00.123`，没有年份、
没有时区）。`ts_epoch()` 把它解析成 epoch 时，用的是**主机的本地时区**：

```python
dt = datetime.datetime(y, mon, day, hh, mm, ss, ms * 1000)   # naive -> 主机时区
v = dt.timestamp()
```

而收尾校验的另一端 `device_epoch()` 拿的是 `adb shell date +%s`，是**绝对时刻**。
两端不同源：主机 +0800、设备 UTC（车机与部分定制 ROM 出厂默认）时，设备写的
`03:14` 会被当成「+0800 的 03:14」，即 UTC 前一天 19:14 —— 比设备此刻整整早
8 小时。

结果是每次录屏收尾都弹：

> ⚠ A1 的 logcat 只跟到 03:14:00.000，距录屏结束还有约 8 小时没有日志…

而实际一条没少。**假告警比不告警更糟**：用户被坑两次之后，真丢日志那一次他也
会直接点掉 —— 上一轮为了让用户看见而做的弹窗，就被这一点废掉了。

顺带还有反向风险：设备 +0800、主机 UTC 时差值变负，真缺口反而漏报。

## 二、修法

### 1. `device_clock()`：一次 shell 取回时刻 + 时区（`backend/screen_service.py`）

```python
adb -s <serial> shell date +%s%z      # -> "1793850520+0800"
```

返回 `(epoch, tz_offset_seconds)`。分两次 shell 会多一次往返，而这两段本来就在
同一行输出里。`%z` 在 toybox（Android 6+）上都支持；不认它的老 shell 会回显
`%z` 字面量，此时 `tz_offset` 留 `None`。

`device_epoch()` 随之成为无引用的薄封装，一并删掉。

### 2. `ts_epoch(ts, ref, tz_offset)`：按设备时区解析（`core/logcat.py`）

传 `tz_offset` 就构造带时区的 `datetime`，年份也用设备时区的「今年」推断
（跨年那一夜，主机与设备的「今年」可能差一年）。不传则维持原样（主机时区）
—— logcat 抓取的重连去重走的正是这条：那里比的是**同一台设备**的两条日志，
时区误差自相抵消，不受影响。

### 3. 时区拿不到时，宁可不说（`backend/controllers/record.py`）

`tz_offset` 为 `None` 就跳过「按时间戳算缺口」这一段。猜出来的差值必然是
15 分钟的整数倍（时区差一定是），与真缺口无法区分 —— 与其给一个错结论，
不如不说。设备时钟偏差那条仍然给：它只比 epoch，与时区无关。

## 三、测试

- `test_core_logcat_time.py` 新增 2 条：同一时刻在 UTC / +0800 / -0500 三种设备
  上写出不同墙上时间，解析结果必须相同；跨年 + 设备时区的年份推断。
- `test_backend_controller.py` 新增 3 条：`device_clock` 的 `+0800` / `-0500` /
  `+0000`、`%z` 不支持与带 `\r\n` 的输出、命令失败 / adb 异常 / 输出无数字。
- `test_backend_record_logcat_coverage.py` 新增 3 条：**设备 UTC + 主机 +0800
  不得产生缺口告警**（核心回归）、同一修复下 UTC 设备真少 24 分钟仍要报、
  时区未知时不猜缺口但时钟偏差照说。
- 测试里的时间戳生成改成按 `tz_offset` 用 `gmtime`：原先用 `localtime`，跑测
  机器时区不是 +0800 时会莫名其妙失败（本地过、CI 挂的经典形态）。

后端 `pytest`：**1335 passed / 1 skipped**；`pyflakes` 干净。

---

# 第四十七轮：保存目录「选择」按钮点了没反应——异常被吞成「用户取消」

**用户实报**：保存目录旁的「选择」按钮点下去毫无反应，连报错都没有。

## 一、根因：一行 ctypes 赋值，每次调用都抛

`backend/controllers/file.py` 里原本这么写：

```python
bi.pszDisplayName = ctypes.create_unicode_buffer(2048)
```

`BROWSEINFO.pszDisplayName` 的字段类型是 `c_wchar_p`，而 `create_unicode_buffer`
返回的是 `c_wchar_Array_2048`。ctypes 不做隐式转换，赋值当场抛：

```
TypeError: incompatible types, c_wchar_Array_2048 instance instead of
           c_wchar_p instance
```

这行在 `SHBrowseForFolder()` 之前，等于函数**永远走不到真正弹框那一步**。异常又被
外层的 `except Exception: return None` 吞掉，于是：

```
_win_select_folder -> None
select_save_dir    -> {"ok": false, "reason": "cancelled"}
前端               -> if (res.ok && res.path) 不成立 → 什么也不做
```

用户看到的正是「点了没反应」。而且这不是偶发 —— 在 Windows 上**每一次**都这样。

第二处隐患：`bi.hwndOwner = None`。对话框没有 owner 窗口就不受主窗口约束，会跑到
其它窗口后面去，表现同样是「点了没反应」。即便弹出来了，用户也看不见。

## 二、修法

### 1. 主路径改用 pywebview 的原生文件夹对话框

```python
win.create_file_dialog(webview.FOLDER_DIALOG, directory=<当前目录>)
```

Windows 下底层是 WinForms 的 FolderBrowserDialog：自带 owner 窗口（不会再被主窗口
盖住）、能定位到初始目录、返回值语义与项目里已有的 `_open_dialog`（选文件）一致。
签名差异沿用同一套位置参数兜底。

顺带把 `current` 参数真正用起来：对话框直接打开在当前保存目录，不用从「此电脑」
一层层点进去。

### 2. ctypes 兜底修好，保留为 fallback

pywebview 拿不到活动窗口时（极少见）仍走 `SHBrowseForFolder`：

- `bi.pszDisplayName = ctypes.cast(display, ctypes.c_wchar_p)` —— 先 cast 再赋；
- `bi.hwndOwner = GetForegroundWindow()` —— 有 owner 才会弹在本窗口之上；
- 构造 BROWSEINFO 抽成 `_build_browse_info()`，这样**在 Linux 上也能回归这段
  ctypes**（结构体字段赋值是跨平台行为，正是它坏了）。

### 3. 三种结果分开，别再糊成一个

| 结果 | 后端 | 前端 |
|---|---|---|
| 选中 | `{ok: true, path}` | 写入输入框 + 复用 change 逻辑落盘 |
| 用户取消 | `{ok: false, reason: "cancelled"}` | 静默（谁都不想被取消烦到） |
| 打不开 | `{ok: false, reason: "unsupported"/"error"}`，error 另播一条状态 | unsupported 提示「请直接输入路径」 |

旧实现把后两者都揉成 `cancelled`，前端只能一律静默 —— 这正是「按钮像没接线」的
由来。区分之后，同样的故障下次会在状态栏里明说。

### 4. 点击期间禁用按钮

Windows 上首次弹对话框要几百毫秒，没有反馈会被当成没点上而连点，反而叠出好几个
对话框。现在点击即禁用，返回后恢复（`try/finally`，异常路径也不会把按钮锁死）。

## 三、测试

- `tests/test_backend_file.py` 重写为 10 条：`_build_browse_info` 不再抛 TypeError
  （**核心回归**，直接在 Linux 上跑）、pywebview 路径的选中 / 取消 / 异常、
  拿不到窗口时的 unsupported、Windows 兜底、error 必须播报且给出退路。
- 新增 `tests/frontend/save_dir_pick.test.cjs`（15 条）：写入 + 落盘、取消静默、
  打不开必须提示、点击期间禁用并在结束后恢复、三个入口（Logcat / 工具区 /
  文件页）行为一致。

后端 `pytest`：**1341 passed / 1 skipped**；`pyflakes` 干净。
前端 `node tests/frontend/run-all.cjs`：**83 个文件、0 失败**。

# 第四十八轮：浅色主题 + 标题栏配色联动（按 FIX_NOTES「仍未做」补齐）

## 一、为什么做

`FIX_NOTES` 第四十七轮之前的「仍未做」一节明确写着：标题栏配色联动界面主题
（`prefers-color-scheme` / 浅色主题）是已知功能缺口——「配色目前是写死的三个常量，
等有浅色主题时一起做」。本轮把它落地，作为对现行项目的功能点审查与完善：让用户
在深色 / 浅色 / 跟随系统之间切换，且原生（Windows DWM）标题栏配色一并跟上，不割裂。

设计上坚持两条硬约束，确保零回归：
- **深色主题体验完全不变**（默认 = 现有行为）；
- **前端组件零改动适配**：走「语义令牌 + 主题覆盖层」路线，而非给每个组件加
  `data-theme` 判断。

## 二、改动清单

| 文件 | 改动 |
| --- | --- |
| `frontend/css/app.css` | 在 `:root` 注入「主题扩展令牌」（深色默认值与旧硬编码**逐字一致**，深色零回归）；新增 `:root[data-theme="light"]` 覆盖层（浅色配色）。再用脚本把 11 条规则共 15 处硬编码表面色替换为变量（弹窗渐变 / 媒体预览底 / 滚动条 / 外框 / 选区中心 / 设备栏轨道等），括号配平校验 660/660。 |
| `core/prefs.py` | `PREFS_DEFAULTS` 新增 `"theme": "dark"`；新增枚举白名单 `THEME_CHOICES` 与 `CHOICE_KEYS`；`sanitize_prefs` 把 CHOICE 校验分支**放在 STR 之前**（否则非法字符串会被 STR 分支当成普通文本放过）。`theme` 仅接受 `dark/light/system`。 |
| `core/win_theme.py` | 新增浅色常量 `TITLE_BG_LIGHT/TITLE_TEXT_LIGHT/TITLE_BORDER_LIGHT`；`title_attributes(mode)` 支持 `light`（写沉浸式浅色位 0 + 浅色配色）；`apply_to_hwnd` 已支持 mode 透传；新增 `_resolve_system_mode()`（读注册表 `AppsUseLightTheme`，非 Windows / 读不到回退 dark）；新增 `apply_for_mode(mode, native, pid, ...)` 统一入口（system 解析为实际深浅、优先取 native 句柄否则按 pid 查找、全程 silent）；`attach` 增加 `mode` 参数并透传（保留启动期轮询重试）。 |
| `backend/controllers/settings.py` | `SettingsMixin` 新增 `set_theme(mode)`：校验 ∈ {dark,light,system} → `win_theme.apply_for_mode(mode, pid=getpid())`；非 Windows 的 `unsupported` 视为成功，任何异常静默返回 `apply_failed`。 |
| `main.py` | `_theme_window()` 改为先读 `config.json` 的 `theme`，再 `win_theme.attach(native, mode=mode)` 套色（启动期按偏好联动原生标题栏，非 Windows / 句柄缺失静默）。 |
| `frontend/index.html` | 顶栏 pill 之后插入 `.theme-switch` 三态分段控件（深 / 浅 / 随系统）。 |
| `frontend/js/app.js` | 新增 `setTheme(mode)`：解析 system→`matchMedia`、写 `data-theme`、持久化 `persistPref("theme")`、`api.set_theme` 联动原生标题栏、监听系统主题变化；`applyBootSettings` 按 `theme` 还原（默认 dark）；`bindUI` 绑定三态点击；`els.themeSwitch` 登记。 |
| `tests/frontend/theme.test.cjs` | **新增** 20 条：控件三态齐全、默认深色、启动按 config 还原（含非法值回落）、点击切换套色 + 持久化 + 联动后端、随系统实时跟随。 |
| `tests/frontend/ui_style_card_tabs.test.cjs` | 样式审计白名单加入 `theme-opt`（顶栏主题分段按钮，刻意自成一体的胶囊造型，已样式化）。 |
| `tests/test_core_prefs.py` | 新增 2 条：`theme` 白名单校验（非法字符串 / 数字回落 dark 并告警、缺省不补写）、默认含 `theme=dark`。 |
| `tests/test_core_win_theme.py` | 新增 6 条：`apply_for_mode` 非 Windows unsupported、`light` 用浅色常量、`system` 经注册表解析、非法 mode 回落 dark、`attach` 透传 mode。 |
| `tests/test_backend_settings_theme.py` | **新增** 4 条：`set_theme` 三态调用 `apply_for_mode`、非法 mode 拒绝、unsupported 视为成功、异常被捕获。 |
| `README.md` | 新增「主题（深色 / 浅色 / 跟随系统）」小节与偏好项说明。 |

## 三、关键设计点

### 1. CSS 令牌化，深色零回归

`:root` 默认令牌维持原深色值，`[data-theme="light"]` 只覆盖与主题相关的令牌。
新增的「主题扩展令牌」（`--popup-a/b`、`--scroll-thumb*`、`--rail-a/b`、
`--overlay-center` 等）默认值**逐字等于**旧硬编码，确保旧组件在深色下像素不变。
浅色块改的是这些令牌的取值，组件靠 `var()` 自动适配——这是改动能覆盖全站而
不逐一碰组件的前提。

### 2. 偏好只存「模式」不存「解析色」

`config.json` 里存的是 `theme: "system"` 这种**模式**，不是解析后的 `light`。
真正写到 `<html data-theme>` 的颜色由 `setTheme` 在每次切换 / 系统主题变化时
解析。这样用户在 system 模式下改了系统主题，界面能实时跟随，而不必重启。

### 3. 后端只管原生标题栏，且永不阻塞切换

`set_theme` 是锦上添花：标题栏配色失败（非 Windows / DWM 不可写 / 句柄缺失）
一律静默，绝不把界面主题切换本身搞失败。system 在 Windows 上读注册表解析为
实际深浅——这与前端的 `matchMedia` 解析是两条独立路径，但结论保持一致。

### 4. 启动期联动

`main.py` 的 `_theme_window`（在 `webview.start(func=...)` 线程里、窗口就绪后跑）
读取 `config.theme` 调用 `win_theme.attach(mode=...)`；前端 `applyBootSettings`
按同一 `theme` 还原界面。两条路径收敛到同一偏好，互不冲突。

## 四、验证

- 后端 `pytest`：**1341 passed / 1 skipped**（与改动前基线完全一致，零回归）。
- 前端 `node tests/frontend/run-all.cjs`：**84 个文件、0 失败**（新增 1 个文件 /
  20 条断言，并把 `theme-opt` 补进样式审计白名单）。
- 令牌化 CSS：括号配平 660/660，浅色覆盖层存在，深色块与旧值逐字一致。
- `sanitize_prefs` 的 theme 校验：非法字符串 `neon` / 数字 `123` 均回落 `dark`
  并告警，合法 `dark/light/system` 保留，`default_prefs` 含 `"theme": "dark"`。

# 第四十九轮（`tools/push_github.py`：堵上「远端地址回显 token」的漏点）

## 一、这轮在补什么

脚本的立身之本是「token 绝不出现在控制台」。文档与测试都反复强调这一点：推送走
`http.extraHeader`（不写进 remote URL），失败时报文先打码再翻译。但 `remote_url()`
在**三处被原样打印**了：

- `_ensure_remote` 的提示（`远端已是 …` / `远端改指 …`）；
- `--status` 的「远端：…」；
- 推送成功提示「已推送 …（…）」里的 remote。

正常 remote 是干净的（`https://github.com/...`），所以历史测试桩成干净地址后一切
正常——**恰恰漏掉了**「有人 clone 时把 token 写进了 URL」这一真实路径。那个 URL 形如
`https://x-access-token:github_pat_…@github.com/...`，原样打印就等于把明文 token
打回控制台，正是脚本声称要堵的坑。

`tests/test_tools_push_github.py` 的 `test_push_url_stays_clean` 只桩了**干净** remote，
所以这个泄漏在回归测试里一直没被抓到——这是既有测试真正的盲区。

## 二、改法

新增 `_mask_url(url)`：用正则识别 `scheme://user:pass@host/path`，只把凭据段换成
`user:***`（`user@` 形式则整体换成 `***`），scheme / host / path 原样保留。仅用于
**显示**，remote 的读写逻辑仍用原始地址。三处打印统一改用 `_mask_url(remote_url())`。

测试补齐：给 `_stub_git` 加 `remote_url` 参数（默认仍是干净地址，既有测试零改动），
新增两条断言——桩成「内嵌 token 的远端地址」后，`--status` 与推送成功提示的回显里
`TOKEN` 不得出现、且必须含 `***`。这样无论 remote 里有没有 token，控制台都不会泄密。

## 三、改动清单

| 文件 | 改动 |
| --- | --- |
| `tools/push_github.py` | 新增 `_mask_url`；`_ensure_remote` / `--status` / 推送成功提示三处远端地址打印改走 `_mask_url`；模块文档补一句说明；`import re` |
| `tests/test_tools_push_github.py` | `_stub_git` 加 `remote_url` 参数；新增 `test_status_masks_token_leaked_into_remote_url` / `test_success_line_masks_token_in_remote_url` |
| `README.md` | 「推送到 GitHub」的「为什么」blockquote 补一句：远端地址显示时也会打码 |
| `FIX_NOTES.md` | 本轮 |

## 四、验证

- `python -m pytest tests/test_tools_push_github.py -q`：**31 passed**（原 29 + 新 2），零回归。
- 真实仓库（remote 确实内嵌了 token）跑 `tools/push_github.py --status`：
  远端行显示 `https://x-access-token:***@github.com/hai1995/ADBDeviceCommander.git`，
  `grep` 全文 token 命中 **0 行**——确认不再回显明文。
- `pyflakes tools/push_github.py`：零输出。

# 第五十轮（设备栏折叠铭牌随勾选联动：「已选中 N 个设备」）

## 一、这轮在补什么

设备栏收起成 48px 窄轨后，底部铭牌（徽章 + 竖排文字）恒显「N / 已连接设备」。
但收起态下用户的每一发操作都作用于**受控（勾选）**设备——此时「选中几台」比
「连了几台」更有用，而勾选状态在窄轨里恰恰一点都看不到。用户反馈：折叠时下方
文字应改为「已选中 X 个设备」。

## 二、设计取舍

- **有勾选才切**：折叠 + 有勾选设备 → 徽章显示勾选数、竖排文字改「已选中设备」；
  一台没选时回落「N / 已连接设备」——否则收起态永远「已选中0」，信息量为零。
- **展开态不受勾选影响**：列表就摊在旁边，勾选一目了然，铭牌恒为「N 台 +
  已连接设备」，与旧行为逐字一致（展开态零回归）。
- **两条触发路径收敛到一个函数**：`refreshSidebarNameplate()` 同时被
  `renderDevices()`（设备事件 / 勾选广播到达）与 `applySidebarCollapsed()`
  （收起 / 展开，含 boot 恢复）调用，徽章数字与竖排文字永远同源，不会出现
  「数字是选中数、文字还是已连接」的错位。
- 文字仍走原 `.sidebar-title-text` 节点（只换 textContent），竖排 CSS、
  column-reverse 布局、徽章隐藏单位等零改动；两条文案都是 5 字，窄轨高度不变。

## 三、改动清单

| 文件 | 改动 |
| --- | --- |
| `frontend/js/app.js` | 新增 `refreshSidebarNameplate()`；`renderDevices()` 原两行计数写入改为调它；`applySidebarCollapsed()` 切换 class 后同步刷新铭牌 |
| `tests/frontend/sidebar_nameplate.test.cjs` | **新增** 14 条：展开恒「已连接 N 台」/ 折叠 + 有勾选切「已选中 N」/ 折叠 + 全取消回落 / 勾选数联动 / 重新展开恢复 |
| `README.md` | 「设备栏收起 / 展开」一条补铭牌随勾选联动的说明 |
| `FIX_NOTES.md` | 本轮 |

## 四、验证

- `node tests/frontend/sidebar_nameplate.test.cjs`：**14 通过 / 0 失败**。
- 相关既有测试抽查（`device_card_toggle` 9、`device_incremental_render` 15、
  `layout_resizable` 21、`ui_style_card_tabs` 36、`checkbox_switch_style` 59）：全过。
- 全量前端套件：**84 个测试文件 0 失败**（main 基线 83 + 本轮新增 1 个文件）。
- `node --check frontend/js/app.js`：语法通过。

# 第五十一轮（Logcat 卡片布局改为与工具页一致的子 tabs 风格）
- 需求：Logcat 原本上下堆叠「落盘抓取 / 实时监控」两张 `.lc-card`，改为与工具页同款的
  **子 tabs 风格**——一条 `.tool-subtabs` 子 tab 条 + 两个 `.tool-pane`（tabpanel），
  一次只看一项；两个面板共享上方缓冲区 / 保存目录行（那一行留在 tab 之外）。
- 复用工具页视觉：`index.html` 套 `.tool-subtabs` / `.tool-subtab` / `.tool-panes` /
  `.tool-pane`（与工具页同一套 ARIA tabs 语义：tablist / tab / tabpanel、
  `aria-selected`、`roving tabindex`）；面板内仍是 `.lc-card`，四角括号与工具卡一致。
- 监控卡撑满高度保留：`.lc-card.grow`（实时监控）在激活面板内 `flex:1`，日志视图
  `.lc-view` 继续吃满剩余高度，不被整页滚动替代（与工具页 `overflow:auto` 的取舍相反，
  因为 Logcat 监控视图就是要占满屏幕高）。`#lc-panes` 为 flex 列、吃满剩余高度。
- 状态落盘：新增 `lc_active_tab`（PREFS_DEFAULTS 默认 `""`，与 `tool_active_tab`
  同套「只记 key、失效回退」约定）；`switchLcTab` 点击切换 + 方向键 / Enter / Space
  激活，`applyBootSettings` 回填（persist:false，启动不写盘），`bindLcSubtabs` 在
  `bindUI` 绑定。非法 key 回退「落盘抓取」。未引入工具页的「长按拖动排序」（仅两项、顺序固定）。
- 测试：`tests/frontend/logcat_subtabs.test.cjs`（23 条：默认态 / 切换面板 / 落盘键名 /
  启动回填 monitor / 非法 key 回退 / CSS 布局）；`main_tab_memory.test.cjs` 的
  面板计数由 `doc.querySelectorAll(".tool-pane")`（全文档，现已 7 个）收紧到
  `#tool-panes .tool-pane`（工具页 5 个），避免 Logcat 复用 `.tool-pane` 后误判。

后端 `pytest`：**1341 passed / 1 skipped**（基线无变化；`lc_active_tab` 仅加进 PREFS_DEFAULTS）；
`pyflakes` 干净。前端 `node tests/frontend/run-all.cjs`：**85 个文件、0 失败**（基线 83 + 本轮新增 1 个文件）。

# 第五十二轮（文档与工程一致性清理）
- 背景：代码已到第 51 轮，README / 使用说明仍停在「工具五张可折叠卡片」「内置 40 余条」
  「dist 要带 commands.json / assets」等第 17~24 轮前的描述；测试数量、CI 注释、
  `core/__init__.py` 模块清单也与实际脱节。本轮只做「让文档说真话」+ 两处低风险工程修正。
- `README.md`：架构树补全 `backend/controllers/`、`mirror/scrcpy/perf/video_join`、
  `builtin_commands/prefs/clipboard/...` 等模块与实际多 tab；测试数量改为
  **1355 项 Python + 86 个 jsdom 测试文件**；分发改为「只发 exe，commands.json /
  config.json 首次运行自动生成」；工具页描述统一为子 tab，删除「卡片收起」残留；
  设备栏按钮改为实际顺序「无线 / 全选 / 刷新」；架构标题恢复为
  `## 架构（v<版本> Web 版）`，使 `bump_version.py` 的 README 正则真正命中。
- `使用说明.txt`：工具页改为五个子 tab（拖动排序 / 键盘切换 / 记住上次）；
  内置命令 40 余条 → **49 条**；配置项清单补全（主题、工具子 tab、工作区、Logcat 子 tab、
  性能阈值、cmd_timeout、main_active_tab 等），删除五张卡的 `*_collapsed`；
  删除「程序自带 config.json、删了会重新生成」的错误说法，改为「首次运行不落盘，
  改动设置后生成，删掉恢复默认」。
- `core/__init__.py` / `frontend/index.html` / `.github/workflows/build.yml`：同步模块清单、
  tab 清单、测试文件数、版本号维护方式（`core/constants.py` 为准 + `main.py` 同值副本）。
- `core/wireless.py`：`re.split(..., 1)` 改为 `maxsplit=1`，消除 Python 3.13+ 的
  DeprecationWarning。
- `tests/test_version_tools.py`：新增 README 架构标题与当前版本一致性的断言，
  防止以后标题格式漂移导致发版时静默漏更新。
- 验证：`pytest` **1355 passed / 1 skipped**；`pyflakes` 干净；
  `node tests/frontend/run-all.cjs` **86 个文件 0 失败**。

# 第五十三轮（耗时操作等待态）
- 背景：截图预览需要后端读盘 + base64 传输（大图以秒计），但界面在结果回来前
  只把预览块置为可见 —— 用户点完「立即截图」看到下方空一块、没有任何动静，
  容易误判没生效而重复点击；安装 / 诊断 / 投屏 / Logcat 抓取 / 更新等按钮也有同样问题。
- `frontend/index.html` / `frontend/css/app.css`：
  - 预览框新增 `.shot-preview-loading` 遮罩（转圈 + 「正在生成预览…」），
    加载时 `min-height: 220px` 占住高度、隐藏旧图，避免版面塌陷后突然弹出；
  - 通用 `.btn.is-loading::after` 转圈（`btn-spin` 关键帧）与 `aria-busy`，
    只加视觉、**不擅自改 disabled**，禁用仍由各业务状态机掌握。
- `frontend/js/app.js`：
  - 新增 `markBtnBusy(btn, busy)`（幂等，只切 class/aria）；
  - `showShotPreview` 先亮遮罩再请求，生成中显示文件名，失败标记 `.err`；
    新增请求序号，多设备连拍时丢弃过期响应，防止旧图覆盖新图；
  - 接入等待态：截图 / 录屏启停 / 应用安装 / 诊断包 / scrcpy / 备用投屏启停 /
    Logcat 落盘抓取启停 / 选择 APK·目录 / 检查更新 / 文件下载 / 设备信息刷新；
  - Logcat 启动不立即禁用（后端 `already_running` 或启动失败时不会有 running 事件，
    禁用后按钮会永久点不动），重复点由后端幂等拒绝。
- `tests/frontend/loading_states.test.cjs`（新增）：锁定 CSS 转圈、预览遮罩先于数据、
  多事件驱动的按钮等待态与收尾。
- 验证：`node tests/frontend/run-all.cjs` **87 个文件 0 失败**；
  `pytest` 1355 passed / 1 skipped；`pyflakes` 干净。

# 第五十四轮（补齐剩余耗时操作等待态 + README 导航）
- 背景：第 53 轮覆盖了截图/安装/诊断/投屏/Logcat/更新等高频操作，但性能报告导出
  （多设备多份 HTML + 对比报告）、文件上传（FileReader + base64 逐文件传输）、
  批量删除、目录刷新、单文件删除、性能监控启停仍是「点了没明显反馈」。
- `frontend/js/app.js`：
  - 性能监控：开始/停止、导出报告（`perf_start` / `perf_stop` / `perf_export`）
    全程 `is-loading`；导出完成后才恢复按钮；
  - 文件上传：用 `pending` 计数把一批文件的读取与传输聚合，最后一个回包才收转圈；
    读取失败 / 空内容 / `readAsDataURL` 抛错路径也会正确 `uploadEnd`，不会卡死；
  - 文件目录刷新（含返回上级 / 手动改路径）在 `file_list` 返回前转圈；
  - 单文件删除、批量删除在确认后、`file_remove` 返回前转圈，完成按勾选数恢复。
- `frontend/index.html`：上传标签补 `id="file-upload-btn"`，供等待态定位。
- `README.md`：新增「文档导航」目录（架构用显式 `<a id="arch">` 锚点，避免版本号
  变化后锚点失效），长文档可直接跳转；界面说明同步补全等待态覆盖范围。
- `使用说明.txt`：耗时操作清单补上「性能报告导出 / 文件上传下载」。
- `tests/frontend/loading_states.test.cjs`：补性能报告导出（延迟回包期间转圈）与
  文件上传（一批传完才收圈）两段断言。
- 验证：前端 **87 个文件 0 失败**；`pytest` 1355 passed / 1 skipped。

# 第五十五轮（补齐设备/Logcat 剩余等待态）
- 背景：实时 Logcat 的「开始监控」、整屏日志「保存到文件」、顶部「刷新」设备
  在设备多或线不稳时都要秒级，仍缺少点击后的即时反馈。
- `frontend/js/app.js`：
  - 设备「刷新」：点击即锁按钮 + 转圈，`refresh_devices` 返回后恢复（防连点）；
  - Logcat 实时监控「开始」：`startLc` 在途期间转圈，成功/失败都收尾；
  - 「保存到文件」：整屏日志可能有几万行，写盘 + 编码期间给按钮转圈，
    `logcat_save` 回包（成功 / empty / 失败）后统一清除。
- `tests/frontend/loading_states.test.cjs`：补设备刷新、监控启动、日志保存三段断言。
- `README.md` / `使用说明.txt`：等待态覆盖范围同步补上设备刷新、实时监控启停、
  日志保存。
- 验证：前端 **87 个文件 0 失败**。

# 第五十六轮（指令台命令运行/终止等待态）
- 背景：设备指令页输入命令回车后，后端 worker 异步执行；命令跑几秒时只有
  tab 标题上的指示点会变，用户视线集中在输入框/运行按钮处，没有明显反馈。
  「停止」点下去也要等后端 kill 一轮，期间按钮毫无变化，容易连点。
- `frontend/js/app.js`：
  - 运行按钮随 `stop_state` 事件转圈（running=true 转、false 收）——
    只认后端事件，不做乐观猜测，不会出现「事件没到、转圈卡死」；
  - 停止按钮在 `stop_run` 请求在途期间转圈，返回后收掉；点击前先查 disabled，
    防连点。按工作区隔离：每个 tab 的 run/stop 只反映自己那条会话的状态。
- `tests/frontend/loading_states.test.cjs`：补第 9 组断言（stop_state 驱动运行转圈、
  停止请求在途转圈、结束后按钮态正确恢复）。
- `README.md`：等待态覆盖清单补上「指令台命令运行与终止」。
- 验证：`node tests/frontend/run-all.cjs` **87 个文件 0 失败**；
  `loading_states.test.cjs` 45 项全过。

# 第五十七轮（预览失败可重试 + README 快速排障）
- 背景：预览图读盘失败时只把文件名标红成「预览生成失败：xxx」，遮罩收起、
  `img` 仍可见（可能还是上一张旧图），用户既分不清「旧图 / 新图」，也没有重试入口；
  `img` 解码失败（base64 截断 / 损坏）更只剩一张裂图。
- `frontend/js/app.js`：
  - 失败遮罩复用为可点击按钮：`is-error` 态去掉转圈、换错误色、提示
    「预览生成失败 · 点击重试」；鼠标、Enter / Space、点文件名都能重新请求；
  - 失败时清掉旧 `src`，避免旧图冒充新图；
  - `<img>` `error` 事件按当前请求序号校验后写回同一失败态（base64 损坏也能重试）；
  - 重试走原有 `shotPreviewSeq`，多设备连拍时仍只认最后一次响应。
- `frontend/index.html` / `frontend/css/app.css`：遮罩文案 / 转圈拆出 id 便于切换；
  补 `is-error` 的尺寸、错误色、虚线与手型光标。
- `README.md`：新增「常见问题（快速排障）」六条速查（设备空白 / 未授权、
  more than one device、短暂失联、json 不生效、录屏无声音、更新不自动装），
  并加入文档导航；界面说明补预览失败重试。
- `使用说明.txt`：截图段落补失败重试说明。
- `tests/frontend/loading_states.test.cjs`：新增失败遮罩重试组（旧图清除、文案、
  点击后二次请求、重试成功收起）与 CSS 可点击断言。
- 验证：前端 **87 个文件 0 失败**；`loading_states.test.cjs` 55 项全过。

# 第五十八轮（全局代码扫描：pipe 泄露修复）
- 背景：对 backend/frontend 做全量静态审查，重点查 Popen 管道、事件监听、
  竞态窗口。mirror_service（管道投屏）和 screen_service（录屏）各查出
  实际 pipe 泄露 bug。
- `backend/mirror_service.py`：
  - **Bug 1：adb proc 的 stderr 是 PIPE 但从未被 drain**。player 有
    `_drain_player_err`，adb 没有。adb 的 stderr 可能输出设备掉线 /
    权限不足等报错，管道容量只有 64KB，写满后 adb 阻塞在 write 上，
    stdout 的视频流也随之停止，player 收不到新帧 → 画面卡死且续流会
    一路刷到 MAX_RESTARTS 才停。新增 `_drain_adb_err` 线程读走 stderr、
    留末尾 300 字符供秒退时报原因；`_spawn_adb()` 每次新建 proc 后
    自动启动 drain。
  - **Bug 2：错误原因从 `_tail_text(proc.stderr)` 改为读 `self._adb_err`**。
    drain 线程读完后 stream 里已无数据，再调 `stream.read()` 只会返回
    空串；进程未退出时还会阻塞到 EOF。每次重连前清空 `_adb_err`，
    避免旧段的错误混入新段。
  - **Bug 3：pipe 泄露**。`_feed_loop` 里 adb 退出后只 close stdout，
    漏了 stderr；`stop()` kill adb 后 pipe 完全不关；player 的
    stdin / stderr 也从没 close。Windows 上靠 GC 回收句柄，多段
    投屏 + 录屏累积后会短暂触发句柄耗尽。新增 `_close_player_pipes()`，
    `_close_player` / `stop` / `_feed_loop` 的各收尾路径统一 close。
  - **清理 dead code**：`_tail_text()` 全项目无调用，删掉。
- `backend/screen_service.py`：
  - **Bug 4：分段 roll 时旧 adb proc 的 pipe 被丢弃**。
    `_roll_segment_locked` 换新段 `sess["proc"] = proc` 时，旧段
    的 stdout / stderr 没有 close，每 roll 一次留一份句柄。在替换
    前主动 close。
  - **Bug 5：stop_ex 里 kill proc 后 pipe 没 close**。wait/kill 之后
    加一轮 close stdout / stderr。
- 验证：`pytest` **1355 passed / 1 skipped**；前端 **87 个文件 0 失败**。

# 第五十九轮（车机重启取回 / 取消路径 pipe / 日志覆盖度误报）
- 背景：围绕「录屏期间车机重启不能丢视频 / 日志」继续审查收尾与失败路径。
- `backend/screen_service.py`：
  - **Bug 1：设备重启后 `_pull_one` 直接放弃**。`_remote_probe` 判定设备
    offline 时，旧代码只报「pull 失败」就退出——设备明明会在几十秒后回来，
    `/data/local/tmp` 里已经录好的那一段却永久丢失。现在先
    `_wait_device_back`（最多 60 秒）等设备回到 `device`，再 probe + pull；
    回来后文件仍在就按正常路径拉取并校验 moov。新增回归用例
    （重启后临时文件仍在 → 必须能取回）。
  - **Bug 2：`discard_ex` 漏关 adb 管道**。第五十八轮修了 `stop_ex`，但后加的
    取消路径 (`discard_ex`) 在 wait/kill 之后没有 close stdout/stderr，句柄要
    等 GC 才回收；Windows 上反复「录制 → 取消」会累积句柄。补齐同一处理。
- `backend/controllers/record.py`：
  - **Bug 3：收尾耗时被算进「日志缺口」**。覆盖度校验用「现在（设备时间）−
    日志最后一条」算缺口，但这段校验发生在视频拉段 / 合并 / 打包之后，正常
    收尾多花的几十秒会被误报成「后段日志已丢失」。改为在**下发停止 logcat
    的那一刻**记下本机时刻，校验时扣掉此后流逝的时长（`since_ts`）；停止前
    就已断掉的日志仍照常告警。
- 测试：`tests/test_backend_screen.py` 新增 `test_discard_ex_closes_adb_pipes`；
  `tests/test_backend_record_logcat_coverage.py` 新增「收尾耗时不算缺口」
  与「停止前断掉仍要告警」两条。
- 验证：`pytest` **1370 passed / 1 skipped**（前端未改动）。


# 第六十轮（主动停止误报「投屏已中断」 / 死亡收尾标记丢失）
- 背景：继续审查投屏链路收尾与多设备录屏的并发路径。
- `backend/mirror_service.py`：
  - **Bug 1：主动停止投屏被报成「投屏已中断」**。`stop()` 会先 set `_stop`
    再终止 adb / 关闭播放器管道；转发线程若恰好阻塞在写播放器 stdin 上，
    写操作抛异常并被记进 `self.error`，随后 `_emit` 照常回调，界面在
    「ℹ 已停止投屏」之后紧跟一条红色「⚠ 投屏已中断」。用户刚亲手停止，
    却被告知投屏断了。现在 `_emit` 在 `_stop` 已置位时直接静默。
  - **Bug 2：低帧率预览的旧错误永不清理**。`SnapMirror._loop` 抓到帧只把
    连续失败计数清零，`self.error` 仍保留早先一次瞬时失败（adb 超时 /
    设备忙）的原因；用户随后停止预览，收尾回调把这个**早已恢复**的旧原因
    当成中断推给界面。现在成功出帧即清空 `self.error`，且停止时不再回调。
- `backend/controllers/autorefresh.py`：
  - **Bug 3：收尾线程在跑时死亡标记被取走即丢**。`died_serials()` /
    `limit_serials()` 取完即清，而 `Workers.spawn("rec-reap-dead")` 对同名
    存活线程会直接丢弃新参数 —— 多设备先后掉线时，后掉线那台的
    「被意外中断（视频不完整）」结论永久丢失。现在上一轮收尾未结束时
    先不取标记，留到下一轮轮询再取。
- 测试：`tests/test_backend_mirror.py` 新增
  `test_pipe_stop_does_not_announce_interrupt`、
  `test_snap_recovered_frame_clears_stale_error`；
  `tests/test_backend_controller.py` 新增
  `test_reap_dead_does_not_consume_markers_while_teardown_running`。
- 验证：`pytest` **1373 passed / 1 skipped**（前端未改动）。

## 2026-11-07 — kill 后显式关闭会话 stdin（消除 BrokenPipeError 回收期噪音）

- `core/shell.py`：`ShellSession.kill()` 终止进程后从不关闭父侧 `proc.stdin`。
  终止瞬间的写入（`\x03`）flush 失败被吞、数据压在 TextIOWrapper 缓冲里，
  GC 回收该文件对象时再 flush 一次，撞上半关闭管道抛 BrokenPipeError，变成
  「Exception ignored while finalizing file」噪音（pytest 标成
  PytestUnraisableExceptionWarning；生产环境 stderr 同样会偶发打印）。
  现在 `wait()` 确认退出后显式 `proc.stdin.close()`（异常吞掉）。
  `stdout` 刻意不关：reader 线程还在等旧管道真正 EOF，提前关闭有 fd 复用
  风险（旧 reader 可能读到新会话输出）。
- 测试：`tests/test_shell_session.py` 新增 `test_kill_closes_stdin_pipe`，
  并把 PytestUnraisableExceptionWarning 升级为错误回归验证（13 passed）。
- 验证：`pytest` **1374 passed / 1 skipped**，警告全部消除。

## 2026-11-07 — 设备安静时实时监控的尾部日志不再滞留到「停止」才出现

- `backend/logcat_service.py`：`LogcatMonitor._worker` 原来直接
  `for raw in proc.stdout` 阻塞读，而批量推送的「攒够 `_BATCH_MAX` 行 /
  距上次推送超过 `_FLUSH_MS`」只在**收到下一行**时才会被检查。设备安静下来
  （车机空闲、无新日志）后读循环一直阻塞，最后那几条日志（以及启动爆发期
  尾部）就一直压在 `batch` / `boot_buf` 里，直到设备再吐一行、或用户点停止
  才冒出来 —— 表现为「日志停在半路，一按停止反而全出现了」，用户会误以为
  监控挂了；若一直不再有新日志，界面就永远差最后几条。
  现在 stdout 由独立读线程（`_pump`）搬进 `queue.Queue`，消费仍留在 worker
  线程，用 `get(timeout=_FLUSH_MS)` 限时等待：超时即代表「这段时间没有新行」，
  正好按时刷新残批、或在到点时结束启动爆发期。解析与推送仍是单线程，
  事件顺序与行数计数、限流/丢弃语义完全不变。
- 测试：新增 `tests/test_backend_logcat_flush.py`，覆盖「正常批次残尾」
  与「爆发期尾部」两种设备安静场景（停止前就必须收到全部行）。
- 验证：`pytest` **1376 passed / 1 skipped**；`ruff` F/E9/B 全过。

## 2026-11-07 — 读线程队列改为有界，恢复日志洪流下的背压

- `backend/logcat_service.py`：上一轮把实时监控的 stdout 搬到独立读线程后，
  读线程与消费线程之间用的是**无界** `queue.Queue`。旧实现里读与消费在同一
  线程，管道写满会自然反压到 `adb`、再到设备端 logcat 缓冲；拆成两线程后
  这层背压消失，日志洪流（启动 dump / 满缓冲全级别）时读线程会把 adb 输出
  尽量抽干堆进队列，内存随流量无上限增长。现在队列容量固定为 `_QUEUE_MAX`
  （5000 行），`put` 满时限时阻塞 —— 队列满 → 不读 stdout → 管道满 → adb
  停写，背压链路与旧实现一致；消费循环仍用 `get(timeout=_FLUSH_MS)`，按时
  刷新残批的行为不变。`_pump` 在 adb 已退出且队列持续满时直接返回，避免
  线程卡死在 `put` 上；worker 的 finally 在终止子进程后清空队列，解开可能
  阻塞的读线程。
- 测试：`tests/test_backend_logcat_flush.py` 新增
  `test_pump_queue_is_bounded_for_backpressure`（消费端停滞时读线程最多填满
  队列，且 adb 退出后能自行结束）。
- 验证：`pytest` **1377 passed / 1 skipped**。



## 2026-11-07 — 恢复「同步录制电脑麦克风」开关（默认关闭，界面写明来源与权限）

用户反馈「录屏附带录制电脑音频没有正常工作」。核查结论：**不是权限问题** ——
当前版本界面上根本没有音频开关，前端 `screen_record_start` 的第 2/3 参写死
`false`，录出来必然无声；后端现存的 `MicRecorder` 录的是**本机麦克风**（说话
声），不是电脑正在播放的声音（系统声音回环未实现）。

- `frontend/index.html`：恢复 `#rec-mic`「同步录制电脑麦克风」开关，**默认不
  勾选**；label title 与说明文字写清：录的是本机麦克风说话声 ≠ 电脑播放的声音、
  仅 Windows、需系统「隐私和安全性 → 麦克风」允许桌面应用访问、停止时需本机
  ffmpeg 才能合成进视频。设备音频（tinycap）仍不开放（多数机型需 root）。
- `frontend/js/app.js`：开关值作为第 3 参 `with_mic` 传给后端；加进 els /
  启动回填 / 变更落盘 / 录制中锁定（与 logcat、zip 同样的生命周期）。
- `core/prefs.py`：新增 `rec_mic: False`（默认关闭，避免权限/设备占用被误当故障）。
- `backend/controllers/record.py`：麦克风启动失败的 toast 补上排查指引（系统
  麦克风隐私设置、设备被其它程序占用），更新 with_mic 的参数说明。
- `README.md` FAQ：改为说明如何开启电脑麦克风及三项前置条件。
- 测试：`checkbox_switch_style`（开关数 31、默认不勾选、文案含「本机麦克风」
  与权限位置）、`tool_cards_layout`（5 个开关顺序）、`logcat_capture_levels`
  （勾选后第 3 参为 true、录制中锁定/停止解锁）、`settings_persist`
  （rec_mic 双向落盘）、`test_core_prefs` 映射表补 `rec_mic`。
- 验证：后端 **1377 passed / 1 skipped**；前端 87 个用例文件全绿。

说明：若用户在旧版 exe 里看到「电脑音频」勾选项，那是历史版本；本次恢复的是
**麦克风**，系统声音回环仍需另行实现（WASAPI loopback / 立体声混音）。

## 2026-11-07 — 麦克风采集格式自动降级 + 缺 ffmpeg 时开局提示

恢复麦克风开关后，针对「权限已允许却仍提示启动失败」与「录完才发现没合成」
两种实际使用问题补齐：

- `backend/audio_service.py`：`waveInOpen` 不再写死 44.1kHz 立体声，改为按
  `_MIC_FORMATS`（2ch/44.1k → 2ch/48k → 1ch/48k → 1ch/44.1k → 1ch/16k）逐个
  尝试。内置单声道阵列麦、只认 48kHz 的 USB 麦常见只支持其中一部分，旧实现
  会直接返回 32（WAVERR_BADFORMAT），用户误以为权限没开。**只有 32 才降级**
  —— 设备被占用（4）、无驱动（6）等换格式也没用，必须原样报出真实原因。
  成功后用实际打开的声道/采样率写 WAV 头，避免降级后音高与时长算错。
- `backend/controllers/record.py`：勾选麦克风且本机没有 ffmpeg 时，在**开始
  录制**就 toast 告知「照常录 mic_*.wav，但停止时无法合成进视频」，而不是等
  收尾才报合成失败。麦克风仍照录，wav 保留可事后自行合成。
- 测试：`tests/test_backend_audio.py` 新增 3 条（32 降级并改用实际格式、4 不
  降级、全部不支持时报 32）；`tests/test_backend_controller.py` 新增「缺
  ffmpeg 开局提示」用例。
- 验证：`pytest` 全量通过（见下）。

## 2026-11-07 — 已关闭工作区的在途事件不再倒进默认工作区

多工作区（指令台子 tab）关闭时，前端先 `stop_run` 再 `ws_close`：kill 生效前
会话仍可能吐出最后几行输出，也可能还有一条在途的 `stop_state`。事件分流此前
复用了 `wsOf()` 的「找不到就回落到 w1」语义，于是：

- 已关闭工作区的日志被写进工作区 1 的面板，与 `closeWorkspace` 向用户承诺的
  「其中的输出一并丢弃」相矛盾；
- 更严重的是 `stop_state` 会把工作区 1 **正在执行**的命令的「停止」按钮熄灭、
  tab 上的执行指示清掉 —— 而该工作区自己的下一次 `stop_state` 要等命令结束
  才会来，期间用户无法停止它。

- `frontend/js/app.js`：新增严格的 `wsEventTarget()`（只按 `ws` 精确查
  `wsMap`，查不到返回 null），`console` / `stop_state` 两个事件分支改用它；
  `wsOf()` 的回落语义保持不变（`curWs()` 等仍需要它）。
- 测试：`tests/frontend/ws_tabs.test.cjs` 新增 [7b]：关闭工作区后推送其
  `console` / `stop_state` 残留事件，断言默认工作区面板不被写入、停止按钮与
  执行指示不被改动（先用一条正常输出确认这批事件确实已被处理，避免空等）。
  已验证该用例在修复前会失败 3 条。
- 验证：后端 **1381 passed / 1 skipped**；前端 87 个用例文件全绿。

## 2026-11-08 — 录屏续段确认不再抢先判死（车机二次掉线竞态）

「录屏期间车机重启不丢视频」依赖 `_watch_exit` 把掉线设备转入等待重启窗口。
但自动续段的「启动确认」线程 `_confirm_segment` 只睡 1.5s，而 watcher 的
`_device_online` 是一次 adb 往返、设备掉线时要等到超时 —— 车机重启刚自动
续上一段、设备又掉一次时，新段秒退，confirm 会抢在 watcher 置 `reboot_wait`
之前拿到锁并标 `died`。controller 看到 died 立刻收尾、等待线程也因
should_abort 退出，「设备回来后自动继续录制」当场被掐断，后段画面丢失。

- `backend/screen_service.py`：`_confirm_segment` 标死前做与 watcher 相同的
  一次 `_device_online` 探测；设备**明确**离线（False）时不判死，交给 watcher
  转入等待重启。探测失败（None）保持老行为判死，与 watcher 策略一致；健康
  续段在 1.5s 探活处即返回，不产生额外 adb 调用。
- 测试：`tests/test_backend_screen.py` 新增 3 条 —— 竞态回归（设备离线且
  watcher 未到时 confirm 不判死，watcher 随后正常进入等待重启，已验证该条
  修复前失败）、设备在线仍判死并写明段号、探测失败仍判死。
- 验证：全量 **1384 passed / 1 skipped**。

## 2026-11-09 — 内置命令增加「通用 / 车机 / 手机」适用设备子标签

- `core/builtin_commands.py`：新增 `scope` 字段（与 `section` 正交：用途 vs
  适用设备）。缺省即「通用」，只有明确偏向某一类的才显式标注 —— 车机：
  更新设备时间（root + date）、优先使用WIFI、root、remount；手机：亮屏并上滑
  解锁、电池与温度信息、打开/关闭移动数据。
- `backend/state.py`：`mark_booted` 的字段白名单补上 `section` 与 `scope`。
  **这是本轮发现的既有 bug**：`section` 一直没随 booted 载荷下发，前端拿到的
  恒为 `undefined`，内置命令在启动后全部落到「其他」段，按用途分组的六段只
  在导入命令后（走 `load_commands`）才短暂出现。新增回归测试覆盖。
- `core/prefs.py`：新增 `builtin_scope`（空串 = 全部），记住用户上次的筛选。
- `frontend/js/app.js` / `css/app.css`：「内置」组内新增 全部 / 通用 / 车机 /
  手机 筛选条（纯展示层收窄，段结构与段头条数跟着变）；每条内置卡片显示
  对应角标（通用灰、车机蓝、手机橙）；关键字搜索域加入 scope；计数跟随可见
  卡片。用户自定义命令不受影响。
- 测试：后端新增 scope 白名单 / 分类覆盖 / merge 透传 / mark_booted 透传
  4 条；前端新增 `builtin_scope.test.cjs`（35 条断言，含角标、筛选、落盘、
  启动还原、非法值回退、搜索命中 scope）。
- 验证：后端 **1388 passed / 1 skipped**；前端 88 个用例文件全绿。

## 2026-11-09 — 修复打包流水线 pyflakes 失败

`Run python -m pyflakes backend core tools tests` 报 3 处告警，均无行为变化：

- `backend/logcat_service.py`：`_end_boot` 的 `nonlocal` 列表去掉 `boot_dropped`
  —— 该变量在闭包里只读不写，写了 `nonlocal` 反而会被 F821/F824 类检查挑剔。
- `tests/test_backend_audio.py`：两个用例删掉未使用的
  `import backend.audio_service as au`（复制粘贴残留）。
- 验证：`pyflakes` 退出码 0；后端 **1388 passed / 1 skipped**。

## 2026-11-09 — 修复偶发永久「连接中…」+ 统一收起/展开图标

### 1. 偶发一直显示「连接中…」（前端启动链无自愈路径）

现场：启动后顶部状态永久停在「连接中…」，设备不刷新、命令台空白、无任何报错。
根因是 `start()` 把「事件轮询 + 5s 兜底」放在初始化**之后**，而初始化链上有两个
可以抛错 / 永不返回的点：

- `api.default_save_dir()` 没有超时：桥接尚未真正接通时 Promise 可能永不 resolve，
  `start()` 被永久挡住 —— 这是启动阶段第一个桥接调用，风险最高；
- `window.pywebview.api` 可能先出现、`boot` 方法后注入：此时 `api.boot()` 直接抛
  `TypeError`，`start()` 整个中断，轮询永远不会启动。

两种情况的表现完全相同：界面停在「连接中…」，既不报错也不会自己恢复。
修复（[app.js](file:///workspace/frontend/js/app.js#L1034-L1121)）：

- 事件轮询与 5s 兜底抽成 `startEventLoop()`，在**任何**初始化调用之前启动，
  自愈通道先就位；
- `default_save_dir` 走 `callApi(..., 5)`，5s 超时放行；
- 新增 `waitForApiMethod("boot", 8000)`，等方法真正可调用再下发；
- boot 调用失败 / 超时 → 状态显示「启动重试中…」并 3s 后自动重试一次；
  抛异常 → 显示「启动失败：<原因>」，不再静默卡死。

后端配合（[base.py](file:///workspace/backend/controllers/base.py#L187-L206)）：
`boot()` 改为幂等 —— 已启动时不再只回 `already_booted`（那会让页面重载 / 重试的
前端永远等不到已消费掉的 booted 事件），而是按当前 state 重建载荷、重发
`booted` + 设备快照；首刷 / 预热 / 自动轮询等副作用不重复执行。

### 2. 「已连接设备」与「指令台」的收起/展开图标统一

- 侧栏原来用文本字符 `«` / `»`，指令台用矢量 `caret-left` / `caret-right`，
  字体差异下大小、基线都不一致。侧栏改为同一套矢量图标（同一 12px 尺寸），
  状态切换时由 `setBtnIcon` 替换（[app.js](file:///workspace/frontend/js/app.js#L5992)）。
- CSS 去掉只为文本字符保留的 font 规则，展开钮仍是 28px 方块控件。

### 3. 顺带修复：源码分发包误打开发期截图

`build.py --zip` 用 `os.walk` 打包，`.uploads/`（开发期上传的截图，常有数 MB）
不在排除列表里，导致源码包从 1MB 级膨胀到 4.4MB 并顶破 `test_build` 的体积断言。
已把 `.uploads` 加入 `SOURCE_ZIP_EXCLUDE_DIRS`，并补一条显式断言。

### 测试

- 后端新增 `test_boot_replay_after_reload`（重发 booted/设备快照、会话不重建、
  轮询不重复）；`test_real_source_zip_is_lean` 补 `.uploads` 断言。
- 前端新增 [boot_stuck_connection.test.cjs](file:///workspace/tests/frontend/boot_stuck_connection.test.cjs)
  （7 条断言）：A) `default_save_dir` 永不返回仍能完成启动；B) `boot` 方法迟到注入
  不中断启动；C) boot 失败有可见提示且 3s 重试可自愈。
- 同步更新 `button_icons` / `sidebar_collapse` 的图标断言。
- 验证：后端 **1389 passed / 1 skipped**；前端 **89 个用例文件全绿**；pyflakes 0。

---

# 第六十一轮（收起按钮点 icon 中心不收 / 录屏停止触发杀软误报）

本轮修你反馈的两个 Bug。

## 1. 「已连接设备」与「指令台」的收起按钮，点 icon 中心收不起来

- 现象：点收起按钮中间的 `<` / `>` 图标本身没反应，只有点图标外面的按钮空白
  才能收起 / 展开。
- 根因：收起按钮的点击处理器会在同一次事件里调用 `setBtnIcon`，把按钮里的
  `<svg>` 替换掉（切 caret-left / caret-right）。被点击的 `<path>` / `<svg>`
  因此被脱离 DOM。事件继续冒泡到父级「整轨可点展开」委托时，委托用
  `e.target.closest("button")` 判断「是不是点在按钮上」——但 `e.target` 已
  脱离，`closest` 再也找不到祖先 `<button>`，返回 null，委托误判为「点在
  轨道空白」，立刻又把面板展开。于是表现为「点 icon 收不起来」。
- 修复（[app.js](file:///workspace/frontend/js/app.js)）：新增 `clickOnButton(e)`，
  用 `e.composedPath()` 判断点击是否落在 `<button>` 上。`composedPath()` 在
  事件分发瞬间算好整条路径，不受后续 DOM 变动影响，能稳稳命中当时的 button；
  无 `composedPath` 的老旧环境回退到 `e.target.closest`。设备侧栏与指令台两处
  委托都改用它。
- 回归测试（[sidebar_collapse.test.cjs](file:///workspace/tests/frontend/sidebar_collapse.test.cjs)
  第 [10] 节）：分别 dispatch click 到 `<svg>` 内部的 `<path>`、`<svg>` 元素
  本体，验证都能收起 / 展开；并确认收起后点窄轨标签仍能展开（整轨热区不受影响）。

## 2. 点击「结束录制」触发亚信杀软拦截，被当成病毒

- 现象：停止录屏时，杀软（亚信等启发式引擎）直接拦截并报毒。
- 根因：停止路径在主机侧做了两件启发式杀软眼里的「可疑操作」：
  1. `proc.send_signal(signal.SIGINT)` —— 给另一个进程发信号，杀软常把
     「信号注入」当成恶意行为；
  2. `adb shell kill -INT <pid>` / `pkill` —— 按 PID / 名字杀进程，命令行
     含 `kill` 也容易被启发式规则命中。
  而 screenrecord 偏偏只在 SIGINT（Ctrl-C）下才写回 moov 优雅收尾，SIGTERM
  会留下无时长的坏 mp4，所以又不能简单改成 kill。
- 修复（[screen_service.py](file:///workspace/backend/screen_service.py)）：
  改用 **PTY Ctrl-C** 优雅结束 screenrecord，主机侧只做一次管道写入：
  - 启动命令加 `adb shell -t`，强制在设备端分配 PTY；
  - Popen 加 `stdin=subprocess.PIPE`；
  - 停止 / 取消时，新增的 `_graceful_stop_proc(proc)` 往 `proc.stdin` 写一个
    `\x03`（Ctrl-C）并 flush。设备端 shell 的 PTY 行规程把它转成 SIGINT 投给
    screenrecord，与终端里手动 Ctrl-C 完全等价，screenrecord 据此写回 moov 并退出。
  - 删除 `_stop_device_screenrecord`（设备端 `kill -INT` / `pkill`）以及
    `send_signal(SIGINT)` 调用；`signal`、`kill_device_process` 的导入一并移除。
  - 兜底仍保留 `proc.kill()`（仅在 Ctrl-C 后 10 秒不退才用，杀的是我们自己
    拉起的 adb 子进程，属于常规操作）。
- 测试（[test_backend_screen.py](file:///workspace/tests/test_backend_screen.py)）：
  - `test_start_uses_unique_remote_name` 断言命令带 `-t`；
  - `test_graceful_stop_proc_writes_ctrl_c_to_stdin` /
    `test_graceful_stop_proc_handles_missing_stdin`：验证写 `\x03` 且无 stdin 不崩；
  - `test_stop_signals_device_side_screenrecord_first`、
    `test_discard_ex_uses_pty_ctrl_c_not_kill`、
    `test_stop_recording_never_kills_mirror_by_process_name`：验证 stop / discard
    全程不出现 `kill` / `pkill`，且确实发出了 Ctrl-C。
- 验证：后端 **1390 passed / 1 skipped**；前端 **89 个用例文件全绿**；pyflakes 0。
- 备注：`device_proc.kill_device_process` 仍被 `audio_service`（tinycap）和
  `mirror_service`（投屏）使用，本轮未改动 —— 如后续停止录音 / 投屏也被同类
  杀软拦截，可按同样的 PTY Ctrl-C 思路处理。

---

# 第六十二轮（PTY Ctrl-C 在 Windows ConPTY 上无效，设备端兜底 kill -INT 恢复）

## 回归场景

上一轮（第六十一轮）把录屏停止改成「PTY Ctrl-C」—— 启动命令加 `adb shell -t`
分配 PTY，停止时往本地 adb 的 stdin 写 `\x03`，想让设备端 PTY 行规程把它转成
SIGINT 投给 screenrecord。

在 Linux/Mac 上这套成立（POSIX PTY 行规程真的会把 `\x03` 转成 SIGINT）。但在
**Windows 上完全不工作**：用户实际测试后，录了 3 段全坏——

> ⚠ 第 1 段：缺 moov 头（无法播放）
> ⚠ 第 2 段：`adb pull ... Permission denied`
> ⚠ 第 3 段：设备端未生成录屏文件

## 根因链

1. **Windows ConPTY 不认 `\x03`** —— adb 在 Windows 上用的是 ConPTY（不是 POSIX
   PTY），它的行规程**不会把 `\x03` 转成 Ctrl-C 信号**，`\x03` 只是普通字节
   （甚至可能还被 ECHO 出来）。所以用户点停止时，screenrecord **根本没收到
   SIGINT**，只能等 10 秒超时后被 `proc.kill()` 杀掉；而 kill 是 TerminateProcess
   （Windows 上等价 SIGKILL），screenrecord 没机会写回 moov —— 第 1 段残片。
2. **分段滚动时旧进程 stdin pipe 没关** —— 之前只关了 stdout/stderr。新 PTY
   模式下每个 adb.exe 都有 stdin=PIPE，旧进程的 stdin 写端不关：
   - **Linux/Mac**：adb.exe 会等 stdin EOF 才能退出（它读 stdin 转发到设备端
     PTY，虽然设备端 screenrecord 已经因为 --time-limit 退了，但 adb.exe 还
     在读本地 stdin pipe，没 EOF 就永远阻塞）
   - **Windows**：ConPTY pipe 不关写端会让 adb.exe 阻塞在 ReadConsoleInput
     上（没 EOF 信号、也没新输入），watch_exit 线程永远等不到 poll() 返回，
     分段滚动时机错乱 —— 后续段各自失败。
3. **第 2、3 段是连带效应** —— 第 1 段 screenrecord 被异常终止后，设备端
   编码器可能没完全释放，续段时 screenrecord 秒退 / 文件权限被临时破坏。

## 修复（[screen_service.py](file:///workspace/backend/screen_service.py)）

跨平台**三阶段优雅停止**，Linux/Mac 优先走无杀软告警的 PTY Ctrl-C，Windows 走
跨平台共享的设备端兜底：

### 第 1 阶段：主机侧 PTY Ctrl-C（`_graceful_stop_proc`）

- **Linux/Mac**：往 stdin pipe 写 `\x03` 并 flush（POSIX PTY 行规程转成
  SIGINT，screenrecord 据此写回 moov）。**主机侧只有一次管道写入，不触发
  send_signal / kill / pkill** —— 这就是上一轮的「杀软不误报」主路径。
- **Windows**：不写 `\x03`（ConPTY 不认），只关 stdin 让 adb.exe 收到 EOF
  退出。这一阶段在 Windows 上**真正起作用的只是「关 stdin 不阻塞」**，
  给后面的设备端兜底铺路。
- **所有平台都必须关 stdin**：原来只关 stdout/stderr 是 bug。

### 第 2 阶段：设备端 kill -INT 兜底（`_device_graceful_stop`，恢复上一轮删掉的）

第 1 阶段后短等 3 秒。如果进程还没退（Windows 上几乎必然），**跨平台共享**
的兜底：`adb shell pkill -INT -f <本次录屏文件 basename>`。

**必须按命令行特征匹配、绝不能按进程名**：设备上可能同时跑着投屏用的另一条
同名 screenrecord（`screenrecord --output-format=h264 -`），按名字
`pkill screenrecord` 会连投屏一起掐断，用户眼前画面直接黑。按文件 basename
定位时，投屏那条命令行里不会有我们的文件名，所以绝对不会被误伤。

杀软误报怎么办？**Windows 上主机侧命令只是 `adb.exe -s X shell kill -INT`**，
没有 cmd.exe / powershell 执行 kill 命令，杀软启发式主要监控的是「某个正常
程序直接杀进程」（taskkill、Stop-Process、GenerateConsoleCtrlEvent），adb.exe
作为合法工具执行远程 kill 是常规操作，杀软不会盯它。上一轮真正触发杀软告警的
是 Linux 上的 `proc.send_signal(SIGINT)` —— 现在这条路已经没了。

### 第 3 阶段：`proc.kill()` 强杀

兜底的兜底。如果设备端 kill -INT 发了，screenrecord 还是没退（极少见），
10 秒超时后 `proc.kill()` 强杀。正常不该走到这里。

### 分段滚动（`_roll_segment_locked`）

旧进程的 **stdin / stdout / stderr 三条 pipe 全部主动 close**。这是之前
唯一没做的。stdin pipe 不关是 Windows 上 adb.exe 阻塞、分段滚动时机错乱的
直接原因。

### 流程对比

| | 上一轮（单阶段 PTY Ctrl-C） | 本轮（三阶段跨平台） |
|---|---|---|
| Linux/Mac | PTY Ctrl-C → 等 10s → kill | PTY Ctrl-C → 等 3s → 设备端 kill -INT（**几乎不用走到这**） → kill |
| Windows | PTY Ctrl-C（无效） → 等 10s → kill（TerminateProcess，不写 moov） | 关 stdin → 等 3s → **设备端 kill -INT（真正让 screenrecord 写 moov）** → kill |
| 杀软告警 | Linux/Mac 没杀软告警；Windows 之前 kill -INT 可能触发（待核实） | **Linux/Mac 主路径完全无杀进程行为**；Windows 主机侧只是 adb.exe |

## 测试（[test_backend_screen.py](file:///workspace/tests/test_backend_screen.py)）

- FakeProc 重构：让 `wait()` 返回后 `poll()` 必须同步变成「已退出」
  （`wait()` 说「进程退了 0」但 `poll()` 还说「还活着」是之前旧测试桩的隐藏
  bug，刚好因为这个 bug 让 stop_ex 永远走不到 kill 分支、也永远没机会测到）。
- `test_stop_signals_device_side_screenrecord_first`：验证 Ctrl-C 发出 + 设备端兜底也不会走（Linux/Mac 主路径足够优雅）。
- `test_discard_ex_uses_pty_ctrl_c_not_kill`、`test_stop_recording_never_kills_mirror_by_process_name`：discard / stop 全程有 Ctrl-C 兜底。

## 验证

- 后端 **1390 passed / 1 skipped**
- 前端 **89 个用例文件全绿**
- pyflakes 0

## 一句话总结

上一轮的 PTY Ctrl-C 只在 Linux/Mac 工作（POSIX PTY 行规程转 `\x03` → SIGINT），
Windows ConPTY 不认、实际是假工作。本轮加了跨平台设备端 kill -INT 兜底，
但**精确按文件路径匹配**（不按进程名、不杀掉投屏），Linux/Mac 继续无杀软告警，
Windows 恢复优雅停止 + 写回 moov。

---

# 第六十三轮（录屏收尾超 15 秒被前端误报「请求超时」——假失败与真成功并存）

## 用户实测日志

```
⏹ 正在停止录屏并收尾（停止设备端 → 拉取视频 → 打包），请稍候…
⏳ 190D… 共 2 段，正在合并为一个完整视频…
调用后端失败：请求超时（15s）        ← 前端 15 秒放弃等待，报错
✓ 190D… 已把 2 段合并为一个完整视频…  ← 后端随后照常完成
✓ 录屏已保存 / ✓ 产物已打包 / ✓ 录屏已完成
```

操作**实际成功**，但界面先弹了一条「请求超时（15s）」的假失败。

## 根因

前端 `callApi` 有全局 15 秒超时（`API_TIMEOUT_S`，`Promise.race` 实现）。
「停止录制」的收尾链路是「停设备端 → 等写回 moov → 拉视频 → ffmpeg 合并 →
打包 zip」——多段大视频 + 慢 USB 时远超 15 秒。超时后：

1. 前端报「调用后端失败：请求超时（15s）」，**但后端还在跑、最终成功**——
   假失败与真成功并存，用户不知道该信哪条；
2. `finally` 提前解锁按钮（`setRecInFlight(false)`）——此时后端还没清完会话，
   用户若再点「开始录制」会撞上 `recording` 冲突。

## 修复（[app.js](file:///workspace/frontend/js/app.js)）

`screen_record_stop` / `screen_record_cancel` 显式传 `timeout=0` 禁用超时
（与 `take_events` 同一机制，此前文档注释里就预留了这条路）：

- 后端整条收尾链路各步**有界**（moov 等待 3-5s、pull 重试上限、ffmpeg 自身
  退出、打包有限），promise 必然落定，禁用超时不会挂死 UI；
- 后端全程通过事件总线推送各阶段进度（拉取 / 合并 / 打包 / 已保存），界面
  不会因为没有超时就「黑箱等待」——用户看到的 ⏳/✓ 就是这些事件；
- 按钮占用态（`recInFlight`）现在与后端真实收尾期严格对齐，杜绝「界面已
  解锁、后端还在收尾」的窗口。

## 测试（[rec_limit_hint.test.cjs](file:///workspace/tests/frontend/rec_limit_hint.test.cjs) 第 3 节）

把全局超时缩到 0.05s、让停止 mock 300ms 才返回——修复前的代码会在 50ms 处
把「请求超时」写进状态栏（已用旧代码验证确实失败），修复后安静等 promise
落定、状态栏全程无报错。两个实现细节记下，防止后人重踩：

- **成功时的 ✓ 文案来自后端事件而非前端**（前端停止成功后不主动 push），
  mock 里没有事件总线，断言只能用「无报错 + 处理器跑完」；
- **`pushLine` 用 requestAnimationFrame 批量刷 DOM**（[app.js](file:///workspace/frontend/js/app.js#L366-L380)
  的 rAF 节流）——等态一解除就立刻读 `#status` 会漏掉刚入队的行，必须先等
  几帧再断言。这个坑第一版测试就踩了：断言时好时坏，排查半天才发现是异步 flush。

## 验证

- 前端 **89 个用例文件全绿**（含新增回归：旧代码 3 断言失败、新代码全过）
- 后端 `test_backend_screen.py` **69 passed**（本轮无后端改动）

---

# 第六十四轮（收起态红色警示「未选中任何设备」+ 设备卡勾选改印章式 ✅）

## 用户反馈

1. 没勾选任何设备时，设备列表收起后只显示「N / 已连接设备」，用户感知不到
   「当前没有操作目标」，一发指令就撞上「未选择设备」的报错；
2. 设备行的选中效果是 iOS 滑动开关，不显眼——要换成视觉效果更强的 ✅
   （好看艺术点的）。

## 改动 1：收起 + 无勾选 → 红色警示铭牌

[refreshSidebarNameplate](file:///workspace/frontend/js/app.js#L5906-L5926)
新增 warn 态：`collapsed && sel === 0` 时——

- 徽章清空（`:has(.count-num:empty)` 自动把 pill 藏掉），「台」一并隐藏；
- 竖排文字改「未选中任何设备」，挂 `.warn` 类；
- CSS（[app.css](file:///workspace/frontend/css/app.css#L730-L743)）：告警红
  `var(--err)` + 600 字重 + 红色文字光晕 + 2.4s 呼吸动画（`warn-breathe`），
  收起态一眼可见「现在没有任何操作目标」。

约定变为四态：折叠+有勾选 → 「N / 已选中设备」；折叠+无勾选 → 红色「未选中
任何设备」；展开态 → 恒「N 台 + 已连接设备」。

## 改动 2：设备卡勾选从滑动开关改为印章式 ✅

设备行是「选目标仪器」，一排滑动开关语义像设置项（文件区此前同样理由改过
方块复选框）。本次（[app.css](file:///workspace/frontend/css/app.css#L816-L862)）
给 `.device-card input[type="checkbox"]` 专门一套样式，全局开关 / Logcat
小开关 / 文件区方块互不影响：

- 未选：20px 圆角「空槽」——深色内嵌底 + 发丝描边，hover 绿描边提亮；
- 选中：翡翠绿三段渐变印章（#4be48a → #2ecc71 → #1fa25c）+ 白色粗对勾
  （::after 右+下两边旋转 45°，2.5px 笔画 + 白光晕 drop-shadow）+ 绿色外辉光
  + 盖章式 pop 回弹动画（`devcheck-pop`，scale .72 → 1.16 → 1，弹性曲线）；
- 键盘 focus-visible 焦点环沿用全局规则；`prefers-reduced-motion: reduce`
  的全局降级规则自动关掉两个新动画；
- 选中后卡片的磷光青描边 / 辉光不变——青（卡）+ 绿（✅）相邻色相不冲突，
  ✅ 的「已就绪」直觉一眼可读。

## 测试

- [sidebar_nameplate.test.cjs](file:///workspace/tests/frontend/sidebar_nameplate.test.cjs)
  第 [3]/[4]/[5] 节改为新约定：无勾选 → 徽章空 + 文案 + `.warn` 类；重新
  勾选 → 徽章 2 + warn 撤销；展开 → warn 撤净。**18 通过 / 0 失败**；
- 全量：后端 **1390 passed / 1 skipped**；前端 **89 文件 0 失败**（含
  checkbox_switch_style 的全局开关断言——本次只加了 `.device-card` 作用域
  规则，未动全局）。

---

# 第六十五轮（撤掉「内置」命令的二级分组，组内平铺）

## 用户反馈

内置命令里的「连接与投屏 / 显示辅助 / 按键 / 屏幕状态 / 网络 / 应用与信息」
子分类太多，找命令反而费劲——取消掉。

## 改动

### 前端（app.js / app.css）

- [renderCmdGroups](file:///workspace/frontend/js/app.js#L1707-L1749)「内置」
  分支与其余分组同构：scope 收窄后直接平铺 chips，删掉
  `BUILTIN_SECTIONS` / `builtinFolded` / `builtinSectionsOf` / `sectionNameOf` /
  `mkFoldAllBtn` / `appendBuiltinSections` 整套段结构代码（含「全部折叠 /
  全部展开」按钮与段头折叠逻辑）；`renderCmdGroups` 的 `filtering` 参数随之
  删除（唯一用途是筛选时强制展开段）；
- **scope 筛选条保留**（全部 / 通用 / 车机 / 手机 + 卡片角标）——它是设备
  类型轴，与被撤的用途分组正交，也是组内唯一的二次收窄；
- **搜索仍按用途命中**：后端数据的 `section` 字段保留（不再参与界面分组），
  搜索域继续拼进关键词——搜「网络」照样捞出一排 WiFi 命令；
- CSS 删除 `.cmd-sections` / `.cmd-section-h` / `.cs-*` / `.cmd-fold-all`
  全部死样式；`prefs.py` 删除 `builtin_folded` 默认键（旧 config.json 残留
  值按「未知键」原样保留，不报错不生效）。

### 文档

README / 使用说明 的「六类可折叠」描述改为「平铺 + 设备类型筛选 + 按用途
搜索」；builtin_commands.py 头注释同步。

## 测试

- 旧的 [builtin_sections.test.cjs]（段结构 / 折叠 / 落盘）整体替换为
  [builtin_flat.test.cjs](file:///workspace/tests/frontend/builtin_flat.test.cjs)：
  平铺同构（单一 chips 容器、无段头 / 徽章 / 全折按钮）、scope 筛选可用、
  section 关键词搜索仍命中、**不再写 builtin_folded 落盘**、CSS 无死样式
  残留——**19 通过 / 0 失败**；
- [builtin_scope.test.cjs](file:///workspace/tests/frontend/builtin_scope.test.cjs)
  撤掉段结构断言，32 通过 / 0 失败；
- 全量：后端 **1390 passed / 1 skipped**；前端 **89 文件 0 失败**。

---

# 第六十六轮（录屏配套 logcat 从「现在」开始抓，并修正覆盖度判据）

## 用户反馈

正常录了十几秒就停止，没有重启车机、没有拔线，收尾却提示
「logcat 只跟到 11-09 17:34:14.931，距录屏结束还有约 10 分 49 秒没有日志」。
打开 txt 一看 433536 行 / 56 MB，末行时间戳比录制开始（17:44:52）还早 10 分钟。

## 根因

抓取命令是 `adb logcat -v threadtime -b all`，**不带 `-T` / `-t`**。这种形态会先把
设备环形缓冲区**从最旧一行开始整段灌出**，灌完才接着实时跟流。车机 `-b all`
的缓冲动辄几十 MB，经 ADB 传输要十几秒到几十秒：

- 短录制（十几秒）在「灌历史」还没到当下时就停止了 → 文件里**全是录制开始前**
  的日志，录制期间一行都没采到；
- 收尾校验用 `设备当前时刻 - 最后一条日志` 算缺口，于是把录制开始前的那一大段
  误报成「距录屏结束还有 10 分 49 秒没有日志」——数字与录制时长完全不成比例。

## 修复

### 1. 抓取从「现在」开始（backend/logcat_service.py）

- [_logcat_cmd](file:///workspace/backend/logcat_service.py#L114-L139) 新增
  `from_now_lines` 参数：`logcat -T <n>` = 只取最近 n 行作为起点，**且不隐含
  `-d`**，随即进入实时跟流。抓取默认 `-T 1`（`LOGCAT_CAP_FROM_NOW_LINES`），
  第一行即落在录制起点附近，既没有追赶窗口，也不再白写几十 MB 历史；
- 实时监控（`LogcatMonitor`）不传该参数，行为完全不变（它需要历史）；
- 老车机 / 被裁剪的 logcat 不认 `-T`（打印用法后秒退）时自动回落：读循环
  0 行 EOF 且 `from_now` 尚未回落过 → 检查报错原文是否含 `invalid option` /
  `unknown option` / `unrecognized option` / `usage:`，命中则把设备记进
  `_no_T`（后续抓取直接走兼容命令），本次改用不带 `-T` 的命令**重试一次**；
  回落不写缺口标记、不计入「意外中断」；
- 设备抖动造成的 0 行 EOF（报错与选项无关）同样重试一次，但**不**记住
  `_no_T`，避免把偶发断连误判成「老设备」而永久退回慢路径。

### 2. 覆盖度判据（backend/controllers/record.py）

- `_rec_session` 增加 `start_host`（录制开始的宿主时刻）；
- [_logcat_coverage_notes](file:///workspace/backend/controllers/record.py#L898-L934)
  用「此刻设备-本机偏移」把 `start_host` 换算成 `start_dev`。若最后一条日志
  早于 `start_dev - 5 秒`，说明整份文件都是录制前的历史缓冲，改报：
  「没有覆盖本次录制：最后一条日志停在 X，比开始录制还早约 N —— 抓到的都是
  录制开始前的历史缓冲，本次录制期间没有采到日志」，不再拿假缺口吓人；
- 真正在录制中途断掉的，仍按原逻辑报「只跟到…距录屏结束还有约 N 没有日志」。

## 测试

- [test_backend_logcat.py](file:///workspace/tests/test_backend_logcat.py)：
  `-T` 只在该加时加；抓取默认带 `-T`；不认 `-T` 时回落一次且记住设备；
  偶发失败只重试不记住。假进程补 `eof_after` 语义（自然 EOF）——
  `block_after` 是「停在读循环等 terminate」，用它模拟「秒退」会让 worker
  永远读不到 EOF、回落分支永不执行（本次两个用例先因此失败）；
- [test_backend_record_logcat_coverage.py](file:///workspace/tests/test_backend_record_logcat_coverage.py)：
  新增「末行早于录制起点 → 报历史缓冲、不报假缺口」与「有 start_host 时
  真实缺口照样报」；
- 全量：后端 **1396 passed / 1 skipped**；pyflakes 干净；前端 **89 文件 0 失败**。

## 规范沉淀

该问题暴露的「录制配套产物必须与录制时间轴逐秒对齐」已上升为 README
「设计要点与健壮性」中的硬规范（**录制配套产物的实时准确性**）：
禁止「先灌历史再实时」的命令形态、收尾判据以录制起点为基准、监控与抓取
两条链路语义不许混用。

---

# 第六十七轮（覆盖度判断改用可验证事实，设备时钟不再参与完整性判定）

## 用户疑问

「没有同步时间的车机、或手动设置了车机时间，覆盖度判断也算误报。这个判断是不是
冗余的？只是提示还是会丢数据？记住一条准则：千万不可丢失数据。」

## 结论（先回答问题）

- **只是提示，绝不丢数据**：结论只写进 `sess["logcat_notes"]`，在「✓ 录屏已完成」
  之后播报；日志 txt 与视频照常保留 / 打包。打包中途失败时只清半成品 zip，源文件
  一律保留（[record.py](file:///workspace/backend/controllers/record.py#L1167-L1197)）。
- **不冗余，但旧判据不可用**：它想回答的是「日志有没有覆盖录制时段」，这确实是
  用户最需要知道的；错在拿「设备当前时刻 − 日志末行时间戳」当证据 —— 车机没校时
  或被人改时间，这个差值与录制时长毫无关系。

## 修复：判据换成进程侧可验证事实

### 1. 抓取侧暴露会话事实（backend/logcat_service.py）

`LogcatCapture` 新增 `_facts` 与 `capture_facts(serial)`，只记录不可能说谎的信号：

- `started_host`：抓取线程启动的本机时刻；
- `compat`：是否因设备不认 `-T` 回落到兼容模式（开头可能是历史缓冲）；
- `data_gap`：是否真的断过 —— 设备掉线、logcat 意外退出、重连后的日志空洞；
  与 `gap_written` 刻意分开：后者还包含「设备时钟回退」这种只影响排序、并不
  丢数据的标记，不能拿来判完整性；
- `lines` / `error`：写盘行数与收尾错误原文。

### 2. 收尾判据（backend/controllers/record.py）

`_logcat_coverage_notes` 改为只消费上述事实：

- 抓取起点比录制起点晚 ≥ 60 秒 → warn「录制开头这一段没有日志」（本机时钟，可靠）；
- `data_gap` → warn「录制期间中断过，[logcat] 标记处存在缺口」（唯一可确证的缺口）；
- `compat` → info「开头可能包含历史缓冲」（兼容模式仍会继续跟流，不等于残缺）；
- 设备时钟偏差 → 仅 info「对照时统一按设备时间看」，**不进完整性结论**；
- 读不到设备时间时，前三条事实照常给出结论（旧实现会整段跳过）。

删除了按设备时钟推算 `gap` / `start_dev` 的全部代码与 `since_ts` 参数；文件不存在 /
无日志行这两条基于磁盘的实际检查保留。

## 测试

[test_backend_record_logcat_coverage.py](file:///workspace/tests/test_backend_record_logcat_coverage.py)
重写为新契约，核心回归四条：未校时车机、录制中时钟跳变、设备时区不同都必须
**零告警**；真断过（`data_gap`）必须 warn 且带 alert 弹窗。另补 `capture_facts`
未知设备返回空、回落兼容记 `compat=True` 且 `data_gap=False`。

顺带修复测试基建：`adb devices -l` 这类非 logcat 调用不再混进回落用例的
`calls` 分配（先前全量跑时被残留 worker 干扰而偶发失败）。

全量：后端 **1395 passed / 1 skipped**；pyflakes 干净。

---

# 第六十八轮（录制中在「停止录制」旁显示实时时长）

## 需求

「开始录制后，在结束录制按钮处增加时长的显示，能清晰感知到录制了多久。」

## 实现

- [index.html](file:///workspace/frontend/index.html#L333-L340)：在「停止录制」**紧后面**
  加一个 `#rec-elapsed` 读数（红点 + 等宽数字），空闲时 `hidden`。
- [app.css](file:///workspace/frontend/css/app.css#L1393-L1418)：红点呼吸、等宽
  tabular-nums（秒数跳动不推动后面的按钮）；`.frozen` 停闪；`[hidden]` 显式写回
  `display:none`——作者样式的 display 会盖掉浏览器默认规则，漏了这行「隐藏」就失效。
- [app.js](file:///workspace/frontend/js/app.js#L2863-L2931)：`performance.now()`
  单调计时（改系统时间 / 校时跳变不会让读数乱跳），250ms 一跳；
  - 起点用后端 `screen_record_start` 返回的 `started`（会话真实开始时刻），补上
    拉起 screenrecord 的 1~2 秒，读数与视频时长一致；
  - 点「停止 / 取消」**那一刻**冻结读数（`.frozen`，红点停闪），收尾十几秒里不再
    上涨——否则用户看到的数字会超过视频本身；
  - `setRecRunning(false)`（含后端 `rec_state` 判定录制意外结束）整块收起；
  - 满 1 小时自动补小时位（`1:02:05`），短录制保持 `MM:SS`。
- [record.py](file:///workspace/backend/controllers/record.py#L332-L337)：启动返回体
  新增 `started`（`start_host`，epoch 秒）。

## 测试

新增 [rec_elapsed.test.cjs](file:///workspace/tests/frontend/rec_elapsed.test.cjs)（14 条）：
默认隐藏且紧贴停止按钮、按后端起点起算（65 秒 → `01:05`）、读数持续走动、点停止
立刻冻结且收尾期间不涨、完成后收起、跨小时补位、`rec_state died` 事件后收起。
后端补一条断言：`started` 必须等于会话 `start_host`。

全量：后端 **1395 passed / 1 skipped**；前端 **90 文件 0 失败**；pyflakes 干净。

## 审查修正（同一轮）

自查发现两处，已修：

1. **起点偏长**：`start_host` 记录在麦克风初始化、设备音频拉起**之前**，这些步骤
   可能耗 1~2 秒，读数会比视频长。改为各设备在 `video.start()` 前打 `t_start`，
   取启动成功里最早的一台存为 `video_start_host`，`started` 用它
   （[record.py](file:///workspace/backend/controllers/record.py#L223-L227)、
   [#L264-L270](file:///workspace/backend/controllers/record.py#L264-L270)）。
2. **空转 interval**：读数元素缺失时仍会每 250ms 起一次渲染再 return，改为
   元素不在就不起表（[app.js](file:///workspace/frontend/js/app.js#L2895-L2900)）。

确认无问题的点：点停止/取消即刻冻结，失败与 `rec_state died` 路径都会清表；
`recInFlight` 期间不会起表；`[hidden]` 显式 `display:none`；多设备取最早起录
时刻，不会因逐台启动累加；只读展示，不触碰任何产物。

---

# 第六十九轮（Logcat 过滤语法完善：排除 / 字段前缀 / 按包）

## 需求

「logcat 的实时监控…过滤出来了很多的杂项…比如我想过滤某个包的日志信息，
它也没有达到那种智能化的可以预识别」→「做，逐步将其功能完善起来」。

## 实现

一套过滤表达式，**空格 = AND**，`-` 前缀 = 排除，六个字段前缀：

| 写法 | 含义 |
| --- | --- |
| `tag:Network` / `-tag:Noise` | Tag 子串包含 / 排除 |
| `msg:timeout` | 消息正文子串 |
| `pid:4170` / `tid:901` | **精确相等**（不是子串） |
| `level:EWF` | 级别集合（多字母） |
| `pkg:com.demo.app` | 解析该包当前 pid 集合后匹配（含 `:remote` 多进程） |
| 无前缀 | 整行原文包含（兼容旧行为，能搜进程名等 tag/msg 之外的字段） |

- [core/logcat.py](file:///workspace/core/logcat.py)：新增 `FILTER_FIELDS` /
  `split_filter_terms` / `match_one_term` / `match_filter` 纯函数。
- [logcat_service.py](file:///workspace/backend/logcat_service.py)：`_classify_and_filter`
  委托 `match_filter`；新增 `pkg_pids_of`（`adb shell pidof` 优先，老系统回落 `ps`
  —— toybox `ps` 首列是 USER，要取末列等于包名的那行里**第一个纯数字字段**）；
  `LogcatMonitor` 在启动时与空转分支每 5 秒重解析 `pkg:` 的 pid（应用重启后 pid 会变）。
- [logcat.py 控制器](file:///workspace/backend/controllers/logcat.py)：新增
  `logcat_packages`（`pm list packages -3`，为空回落全量）与 `logcat_pidof`。
- [index.html](file:///workspace/frontend/index.html)：过滤框占位符写明语法；
  新增「按包」下拉（仅列第三方应用）。
- [app.js](file:///workspace/frontend/js/app.js)：前端实现**同一套语义**
  （`lcSplitTerms` / `lcMatchTerm` / `linePassesFilter`）——关键字本来就不下发后端，
  过滤发生在前端，后端那套只用于抓取路径，两边必须逐条对齐；
  「按包」单选 → 写 `pid:NNN`（可读可编辑），多进程 → 写 `pkg:name`；
  右键菜单新增「按 Tag 过滤 / 排除此 Tag / 按 PID 过滤 / 排除此 PID / 追加排除此 Tag」。

## 顺带修掉的缺陷

- `level:` 旧实现写成 `pat in 级别`（反了），`level:EWF` 永远不命中；改为
  「级别 ∈ 表达式字符集」，`level:EW` 自然成立。
- `pid:` 旧实现是子串包含，`pid:41` 会连 4170 一起过滤掉，用作排除时误伤；
  改为精确相等。
- 上一轮只改了后端语法，而前端从不下发关键字 —— 那套规则实际是死代码。
  这轮把权威实现放到前端，并在两处注释里互相指认，测试各自锁定同语义。

## 测试

- [test_backend_logcat.py](file:///workspace/tests/test_backend_logcat.py)：新增 10 条
  （排除、排除+包含、多字母级别、pid 精确、pkg 有/无解析、表达式切分、pidof 优先、
  ps 回落、解析失败返回空集）。
- [test_backend_controller.py](file:///workspace/tests/test_backend_controller.py)：新增 5 条
  （第三方包列表、回落全量、无设备、pidof 排序、参数校验）。
- 新增 [logcat_filter_syntax.test.cjs](file:///workspace/tests/frontend/logcat_filter_syntax.test.cjs)：
  16 条前端行为断言，覆盖六个字段、排除与包含混合、按包下拉写入、右键菜单四项。

全量：后端 **1416 passed / 1 skipped**；前端 **91 文件 0 失败**；pyflakes 干净。

---

# 第七十轮（Logcat 过滤预设：常用表达式一键保存 / 切换）

## 需求

「可做 常用过滤条件另存为预设。暂时不考虑多设备同时监控，因为需要保持程序整体的
轻量、运行速度快、内存占用低」。

## 实现

预设存的是**表达式文本**（`kw`），不存级别 / 仅异常 —— 那两项是全局视图偏好，
切预设时不应连带变化。

- [index.html](file:///workspace/frontend/index.html#L247-L254)：过滤框右侧新增
  「预设」下拉 + 「存为预设」「删除」两个按钮。
- [app.js](file:///workspace/frontend/js/app.js#L2851-L2954)：`lcPresets` 状态与
  `_loadLcPresets` / `renderLcPresets` / `saveLcPreset` / `deleteLcPreset` /
  `applyLcPreset`：
  - 保存走应用内输入弹窗（不用 `window.prompt`）；同名保存弹确认后**覆盖**，上限 30 条；
  - 选中即回填表达式并立即重渲染；删除需二次确认，且明说「不影响当前过滤条件」；
  - 表达式被手工改动、与已选预设不再一致时，下拉自动退回「（无）」；
  - 启动恢复时若 `lc_keyword` 正好等于某个预设，自动选上该预设。
- 落盘 `config.json` 的 `lc_presets`（JSON 字符串，与 `cmd_history` 同一套约定：
  后端对未知键原样保留，不必改 prefs 白名单）；手改坏 / 非数组 / 元素缺字段一律
  当空列表处理，不影响启动。
- [app.css](file:///workspace/frontend/css/app.css#L1264-L1268)：下拉限宽，长名称不把
  「按包 / 级别」挤到下一行。

## 测试

新增 [logcat_presets.test.cjs](file:///workspace/tests/frontend/logcat_presets.test.cjs)
（18 条）：保存并落盘、切换回填、同名覆盖（数量不增）、删除确认与落盘、启动按配置
恢复并自动选中、手改表达式后退回「（无）」。测试里等待 `#pill` 变成「已就绪」而不是
等下拉的选项数 —— HTML 自带「（无）」一项，按选项数等待会抢在配置恢复前开始断言。

全量：前端 **92 文件 0 失败**；后端未改动（1416 passed / 1 skipped）；pyflakes 干净。

---

# 第七十一轮（文件区：指向目录的符号链接被视为文件）

## 问题

截图里 `/sdcard` 实际是目录（`lrw-r--r-- sdcard -> /storage/self/primary`），
文件区却把它当文件：不能点进去，还给出「下载 / 查看」。`/bin`、`/etc`、
`/d`、`/cache` 等根目录项同理。

## 原因

`ls -la` 只看得到符号链接自身（权限位 `l` 开头），`parse_ls_output` 的
`is_dir = perm.startswith("d")` 必然为 False。普通目录本来就正常（截图里
`vendor_dlkm` / `vr` / `vr_res` 已按目录排序、只给「重命名 / 删除」）。

## 修复

[file_service.py](file:///workspace/backend/file_service.py#L99-L126) 新增
`_mark_link_dirs`：本次列出的链接**合并成一次**额外探测

    cd <目录> && for f in <链接名...>; do [ -d "$f" ] && echo D || echo F; done

`[ -d ]` 会跟随链接，指到目录的标 `is_dir=True`，指到文件 / 断链保持原样；
随后重新排序，链接目录自然排到目录组。探测失败 / 输出行数对不上时**不做任何
修改**，列表照常返回 —— 宁可显示成文件，也不能因为一条链接把整页目录打挂。

只对「本次有链接」的目录多发一次 adb 往返（根目录约 0~10 条链接；`/sdcard`
这类目录通常没有），不影响普通浏览速度。

## 测试

[test_backend_file_service.py](file:///workspace/tests/test_backend_file_service.py#L82-L142)
新增 3 条：链接到目录被标成目录且仍保留 `is_link`/`target`、探测失败保持原判断、
含空格目录的探测命令正确加引号。原有「兜底重试」用例改为不再断言总调用次数
（多出的那次正是链接探测）。

全量：后端 **1419 passed / 1 skipped**；pyflakes 干净（本轮未改前端）。

---

# 第七十二轮（设备栏收起态与右侧面板贴太紧）

## 问题

设备栏收起成 48px 窄轨后，右侧内容区直接贴着窄轨，两块圆角面板之间没有任何
留白，视觉上很挤。

## 原因

展开态这段留白是由 12px 的分隔条 `.splitter` 占着的；收起时
`#sidebar-splitter { display:none }` 把它整个隐藏，行容器的 `gap` 又是 0，
于是留白一起消失。

## 修复

[app.css](file:///workspace/frontend/css/app.css#L734-L737) 给收起态的行容器补
`gap: 12px`（与分隔条同宽），视觉节奏与展开态一致。展开态不受影响。

## 测试

[sidebar_collapse.test.cjs](file:///workspace/tests/frontend/sidebar_collapse.test.cjs#L125-L130)
静态断言新增一条：收起态 `.main-row` 必须有 12px gap。

全量：前端 **92 文件 0 失败**（47 条 sidebar_collapse 用例全过）。

---

# 第七十三轮（pkg: 过滤的两处时效问题）

## 一、日志不断流时 pid 永不刷新

第七十轮把「按包过滤」的 pid 解析做成了监控中每 5 秒刷新，但代码放在
worker 的 `queue.Empty` 分支里 —— 那是「这段时间没有新日志」才会走到的分支。
真实场景日志几乎不断，这个分支永远进不去，pid 就停在启动时那一份：应用重启
（pid 变了）后按包过滤突然一行都没有，界面也看不出任何原因。

修复：刷新判断移到 worker 循环顶部，按墙钟执行，与队列是否空闲无关
（[logcat_service.py](file:///workspace/backend/logcat_service.py#L388-L404)）。
代价是每 5 秒一次 `pidof`（约几十毫秒），比「过滤悄悄失效」划算。

## 二、pid 缓存没带设备号 + 切设备不重解析

前端缓存原本是 `包名 -> [pid]`，切换设备后仍拿上一台的 pid 去过滤；且设备切换
分支只调了 `renderLogcat()`，没有触发重解析 —— 未监控时也没有 5 秒定时器在跑，
于是切过去就**永久**停在「命中 0 行」。

修复（[app.js](file:///workspace/frontend/js/app.js)）：
- 缓存键改为「设备 + 包名」，两台设备的 pid 互不污染；
- 设备联动切换时补 `lcRefreshPkgPids()` + `syncLcPkgTimer()`；
- 定时器只清当前设备的缓存，切回去还能先用旧值；
- 迟到的 `logcat_pidof` 响应只写缓存、不重绘（此时界面可能已换设备）；
- 请求失败也写入空数组并重绘，避免「一直转圈」的假象。

## 测试

- 后端新增 [test_pkg_pid_refresh_runs_while_logs_keep_flowing](file:///workspace/tests/test_backend_logcat.py#L1833-L1857)：
  用持续吐行的假 `adb logcat` 缩小刷新周期，断言多次解析（旧实现只会解析 1 次）。
- 前端 [logcat_filter_syntax.test.cjs](file:///workspace/tests/frontend/logcat_filter_syntax.test.cjs#L221-L262)
  新增第 8 组：A1 解析到 5417、切到 B2 后必须按 6000 命中，验证「缓存隔离 + 切换重解析」。

全量：后端 **1420 passed / 1 skipped**；前端 **92 文件 0 失败**；pyflakes 干净。

---

# 第七十四轮（pkg: 解析不到进程时给出可解释的反馈）

## 现象

`pkg:com.demo.app` 里的包没在跑（或这台设备暂时读不到进程）时，界面只有
「命中 0 行」——与「表达式写错了」「级别被关掉了」长得一模一样，用户没法判断
问题出在哪。

## 修复（[app.js](file:///workspace/frontend/js/app.js#L2799-L2830)）

- 解析结果统一走 `lcApplyPkgPids()`：为空时状态栏提示一次
  「没找到包 X 的运行中进程（按包过滤将显示 0 行）」。
- 提示按「设备 + 包名」去重：监控中每 5 秒重解析一次，不会把状态栏刷满；
  中途解析成功过（包起来了）就清掉去重标记，之后再掉线还能再提示。
- 已经切走的设备不提示（提示与界面上的设备对不上等于误导），切回来那轮再提示。
- 空的解析结果不再被当成「缓存已就绪」永久沿用：重新启用过滤、切回设备、
  点开始监控时都强制重解析（`lcRefreshPkgPids(true)`），避免「应用早就启动了，
  界面却一直 0 行，非得删掉 `pkg:` 再重打一遍」。
- 「按包」下拉的空 pid 提示同步去重标记，避免随后 5 秒刷新再补一句。

## 测试

[logcat_filter_syntax.test.cjs](file:///workspace/tests/frontend/logcat_filter_syntax.test.cjs#L264-L280)
新增第 9 组：解析为空 → 状态栏出现提示；重复输入同一表达式后该提示仍只出现 1 次。

前端 **92 文件 0 失败**（本文件 21 条全过）。

---

# 第七十五轮（实时监控撤掉「保存到文件」，补性能说明）

## 需求

实时监控区不再提供「保存到文件」；同时在监控卡顶部说明：为保持性能稳定会舍弃
部分日志的显示，需要完整日志请走「落盘抓取」。

## 改动

- [index.html](file:///workspace/frontend/index.html#L255-L260)：删掉 `#lc-save`
  按钮；标题副文案由「仅查看，不写文件」改为「实时视图」；新增 `.lc-hint`
  常驻说明：「为保持性能稳定，实时监控会舍弃部分日志的显示；需要完整日志请在
  「落盘抓取」中抓取。」
- [app.css](file:///workspace/frontend/css/app.css#L1266-L1272)：`.lc-hint`
  使用 `--muted` / `--fs-sm`，深浅色主题都自动适配。
- [app.js](file:///workspace/frontend/js/app.js)：删除 `saveLogcat()`、
  `bufToText()`（仅它使用）、`safeFileName()`（仅导出功能时代的死代码）、
  `els.lcSave` 与按钮点击绑定。
- [logcat.py](file:///workspace/backend/controllers/logcat.py)：删除后端
  `logcat_save`（前端已无调用方；落盘能力仍在「落盘抓取」里）。
- 文档：README 的 Logcat 行与「耗时操作等待态」清单、`使用说明.txt` 第 4 条
  同步更新（去掉保存到文件，补性能说明）。

## 测试

- 删除 `logcat_save_filename.test.cjs` 与后端两条 `logcat_save` 用例。
- [logcat_tab_cards.test.cjs](file:///workspace/tests/frontend/logcat_tab_cards.test.cjs#L91-L104)
  反向断言监控卡**不再有** `#lc-save`，并要求 `.lc-hint` 同时包含
  「舍弃部分日志」「落盘抓取」两个关键词。
- 清理 `loading_states.test.cjs` / `logcat_restart_clears_buffer.test.cjs`
  中依赖保存按钮的段落。

全量：后端 **1418 passed / 1 skipped**；前端 **91 文件 0 失败**；pyflakes 干净。

---

# 第七十六轮（内置「获取/杀掉当前 Activity」加固与可见性回归）

## 问题

用户反馈内置命令区里看不到「获取当前 Activity」「杀掉当前 Activity」。

## 排查

后端 `load_commands` 实测返回 49 条内置命令，两条 Activity 命令都在；
`merge_builtins` 的「同名压制」只在用户命令核心名相同时才会抑制内置。
若用户 `commands.json` 里已有同名命令（哪怕只是空格差异），内置会被隐藏。
前端渲染链路经测试可正常显示这两条命令。

## 加固

既然命令已在源码里，本轮做了两处稳健性改进，避免「命令在但不好用」：

- [builtin_commands.py](file:///workspace/core/builtin_commands.py#L55-L69)：
  - 「获取当前 Activity」改为同时匹配 `mCurrentFocus` 与 `mFocusedApp`：
    新版 Android 上 `mCurrentFocus` 可能只给 Window 句柄，`mFocusedApp`
    才有完整包名/Activity，两条都打出来便于排查。
  - 「杀掉当前 Activity」加 `Select-Object -First 1`，只取第一条焦点行，
    避免历史焦点行导致对多个包重复 `force-stop`；`mCurrentFocus=null`
    时正则不匹配、不动作。

## 测试

- [test_load_commands.py](file:///workspace/tests/test_load_commands.py#L303-L315)
  重命名为 `test_builtin_kill_activity_command_text`，断言新命令文本含
  `Select-Object -First 1` 且正则反斜杠完整。
- [builtin_command_badge.test.cjs](file:///workspace/tests/frontend/builtin_command_badge.test.cjs#L129-L148)
  新增第 4 段：用两条 Activity 命令的真实 id/name 起 payload，断言前端
  渲染链路不会把它们过滤掉。

全量：后端 **1418 passed / 1 skipped**；前端 **91 文件 0 失败**。

---

# 第七十七轮（自定义命令按钮配色：bg / fg）

## 需求

命令多了以后在卡片堆里找不到自己的常用命令，希望给单条快捷命令设置
**按钮颜色**与**文字颜色**，用颜色做视觉索引。

## 数据模型

用户命令新增两个可选字段（[core/commands.py](file:///workspace/core/commands.py#L411-L421)）：

```json
{ "id": "u_x", "name": "抓日志", "bg": "#ffcc00", "fg": "#003366", ... }
```

- 只接受 `#RGB` / `#RRGGBB`（`_as_color`）：命令库是手写 / 外部导入的 JSON，
  颜色最终进内联样式，非十六进制一律丢弃 —— 只丢该字段，不影响命令本体。
- 没设置就不写字段；加载、导出、合并内置命令都会原样保留（导入后颜色不丢）。

## 前端

- 卡片渲染（[app.js](file:///workspace/frontend/js/app.js#L1958-L1967)）：合法色值
  写成内联 CSS 变量 `--chip-bg` / `--chip-fg`，加 `.cmd-chip--custom`；
  只设其中一种也生效。
- 样式（[app.css](file:///workspace/frontend/css/app.css#L1088-L1101)）：
  hover 继续用用户选的色（只做轻微提亮），否则「一悬停颜色就没了」。
- 编辑弹窗新增「按钮外观（可选）」：两个原生取色器 + 各自「默认」按钮。
  是否设置过记在 `dataset.bg/fg`（取色器永远有值，不能拿它判断「有没有设置」），
  点「默认」才清空。保存时只写设置过的字段；复制命令时配色一并复制。

## 测试

- 后端 5 条：合法 / 短色值 / 非法丢弃 / 默认无字段 / 合并内置不丢；
  导出用例补一条 `test_export_commands_keeps_custom_colors`。
- 前端新增 [cmd_custom_colors.test.cjs](file:///workspace/tests/frontend/cmd_custom_colors.test.cjs)：
  合法渲染、非法忽略、只设底色、弹窗改色保存只写 bg、点默认清空。

全量：后端 **1424 passed / 1 skipped**；前端 **92 文件 0 失败**；pyflakes 干净。

# 第七十八轮（「跳过此版本」补恢复出口）

## 发现

全局交叉核对前端 `api.*` 调用与后端 `WebApi` 公开方法时发现：`update_unskip`
后端早已实现、注释里写明「关于页提供一个『恢复提示』出口」，但前端关于页
从来没有这个入口，`update_info` 也不返回当前被跳过的版本号 —— 用户在新
版本弹窗点过「跳过此版本」后，除了手改 config.json 没有任何办法撤销，
等于一个不可逆操作。

## 修复

- [update.py](file:///workspace/backend/controllers/update.py#L24-L45)：
  `update_info` 新增 `skipped` 字段（当前被屏蔽的版本号，空串 = 无）。
- [index.html](file:///workspace/frontend/index.html#L701-L702)：
  更新行新增 `#about-update-skipped` 小按钮，默认 `hidden`。
- [app.js](file:///workspace/frontend/js/app.js#L6208-L6220)：
  新增 `renderUpdateSkipped(version)` —— 非空显示「已跳过 vX · 恢复」，
  空串藏起；`loadUpdateInfo` 启动回填时同步（重启后仍能反悔）；
  「跳过此版本」写盘成功后立即亮起（先关弹窗保即时反馈，出口亮灭由
  写盘结果决定，失败不装假成功）；点出口调 `update_unskip`，成功后藏起。

## 测试

- 后端补 `test_update_info_reports_skipped_version`：默认空 → 落盘后带出 →
  unskip 后清空。
- 前端 [update_modal.test.cjs](file:///workspace/tests/frontend/update_modal.test.cjs)
  新增 [I] 段 6 条：结构存在且默认藏起；启动回填亮起并带版本号；跳过后
  立即亮起；点恢复调 `update_unskip` 并藏起；写盘失败不亮出口。

全量：后端 **1425 passed / 1 skipped**；前端 **92 文件 0 失败**；pyflakes 干净。

# 第八十轮（双击启动加载 splash + 启动耗时量化日志）

## 问题

用户反馈：双击运行后要等好几秒才启动，这期间没有任何加载提示 / 动画，
界面空白，体验很差。

## 根因

窗口创建（`webview.create_window`）与 `index.html` 渲染之间的时间差里
没有任何东西展示。pywebview 在 Windows 上还要先拉起 WebView2 宿主进程
（冷启数百 ms ~ 1s），再加载 HTML；这段窗口底色虽然已设成 `#0b0f14`
（与最终界面一致，避免旧灰闪一下），但「纯深色 + 空无一物」的观感
仍是空白。

真正的重活（命令加载 / 建立 PowerShell 会话 / 设备首刷 / adb server 预热 /
临时文件清理 / 版本检查）本来就全部塞进 `boot()` 里**异步执行**
（`workers.spawn`），窗口显示不依赖它们——用户感知到的「等了几秒」
其实就是 WebView2 冷启 + HTML 渲染 + JS 执行到 `boot()` 返回之间，
没有任何视觉反馈。因此「重初始化异步化」这一条已经到位，本轮只需
补**首屏视觉占位**。

## 修复

- [main.py](file:///workspace/main.py#L328-L364) /
  [_launch](file:///workspace/main.py#L397-L419)：
  全链路分段耗时日志（`[boot X.XXs] crash_hooks_done / path_ready /
  preflight_done / WebApi_built / webview_imported / window_created`），
  以后再觉得慢时能一眼定位卡在哪段；**stderr 输出**（--windowed 打包的
  exe 没有控制台时看不到），不影响正常用户界面。
- [index.html](file:///workspace/frontend/index.html#L12-L54)：
  `<body>` 最顶部插入 `#boot-splash` 遮罩 —— 纯 HTML + 内联 `<style>`
  + CSS `@keyframes` 旋转点，不依赖 app.css / app.js / 任何外部资源，
  WebView2 一旦把 HTML 骨架渲染出来就立刻看到。设 `z-index: 2147483647`
  盖住主界面，背景色 `#0b0f14` 与窗口底色一致，避免过渡闪白。
- [app.js onBooted](file:///workspace/frontend/js/app.js#L1194-L1201)：
  boot 成功即 `sp.setAttribute("data-faded", "1")`，配合内联 CSS 的
  `transition: opacity 0.35s ease, visibility 0s linear 0.35s` 平滑淡出并
  移出画面。onBooted 在 boot() 重发路径也会走到（页面重载 / 超时重试），
  `data-faded` 置位后 `setAttribute` 变成空操作，天然幂等。

## 测试

- 新增 [boot_splash.test.cjs](file:///workspace/tests/frontend/boot_splash.test.cjs)
  6 条：HTML 骨架就绪、默认亮着、不淡出、有 `.dot` 指示器、样式内联、
  boot 事件触发后淡出、重发 boot 不报错（幂等）。

全量：后端 **1425 passed / 1 skipped**；前端 **93 文件 0 失败**；pyflakes 干净。

# 第八十一轮（快捷命令新增「备注」字段：编辑 + hover 提示）

## 需求

用户希望快捷命令按钮新增「备注」功能：
- 新增 / 修改 / 复制命令时可以编辑备注；
- 平时鼠标移入按钮时，title 里也能看到备注。

## 改动

### 后端

- [commands.py](file:///workspace/core/commands.py#L402-L421)：
  `normalize_commands` 新增 `note = _as_text(c.get("note"))`，
  保留非空字符串（支持多行 `\n` 原样保留），空串/None/类型
  不对一律不进 item dict（与 bg/fg 的设计一致）。
  新增辅助函数 [_as_text](file:///workspace/core/commands.py#L450-L466)：
  bool 显式挡掉（bool 是 int 子类，不能只按 int 判断），数字转字符串
  保留（用户手写 json `"note": 123` 容错），dict/list/None 一律空串。
- [export_commands](file:///workspace/backend/controllers/commands.py#L83-L99)：
  显式枚举字段里加一行 `note` 条件带出（与 bg/fg 同一风格：有才带，
  不污染空字段），保证备份 → 恢复后备注仍在。
- 其它链路（`load_commands` / `save_commands` / `merge_builtins` /
  `save_click_deltas`）都是浅拷贝原样透传，note 自动跟随。

### 前端

- [index.html](file:///workspace/frontend/index.html#L984-L987)：
  在编辑弹窗里「仅输入」复选框之后、「按钮外观」颜色块之前，插入
  `<textarea id="cmd-edit-note" rows="2">`（支持多行）。
- [app.js els](file:///workspace/frontend/js/app.js#L160)：
  注册 `cmdEditNote`。
- [mkCmdChip title 拼备注](file:///workspace/frontend/js/app.js#L1975-L1979)：
  在 title 末尾（内置 / 仅输入 / 配色的说明之后）换两行拼上 `c.note.trim()`。
  有备注才加，没有保持原来简洁 title，避免空串造成视觉杂音。
- [collectUserCommands](file:///workspace/frontend/js/app.js#L2248)：
  非空 note 才写进落盘 item（与 bg/fg 同风格，不制造空字段）。
- [openCmdEdit](file:///workspace/frontend/js/app.js#L2263-L2265)：
  原样回填 textarea。复制命令时备注一并克隆（克隆语义）。
- [saveCmdEdit](file:///workspace/frontend/js/app.js#L2293-L2316)：
  编辑路径：有 note 赋值，没 note 则 `delete c.note`；
  新建路径：非空才写进 item（与 bg/fg 对齐）。

## 测试

- 后端新增 3 条（tests/test_load_commands.py）：
  - `test_note_is_preserved_when_nonempty`（单行 / 多行）；
  - `test_note_dropped_when_empty_or_invalid`（空串 / None / bool / dict / list 丢，
    数字 123 转成字符串 "123" 保留——有意容错）；
  - `test_note_survives_merge_builtins_and_export`（merge_builtins 浅拷贝 +
    CommandMixin.export_commands 显式枚举带出）。
- 前端新增 [cmd_note.test.cjs](file:///workspace/tests/frontend/cmd_note.test.cjs)
  7 条：有 note 的 chip.title 含命令名+备注、无 note 不凭空多出空行、
  编辑弹窗里有 cmd-edit-note textarea。

全量：后端 **1428 passed / 1 skipped**；前端 **93 文件 0 失败**；pyflakes 干净。

# 第八十二轮（截图失败：设备端落盘路径加 /data/local/tmp/ 兜底 + 错误信息补全）

## 用户反馈

车机（序列号 `a5144205`）上点「截图」失败：
```
⚠ 截图失败 a5144205: 两条取图通道都没成功：
exec-out 报「设备未返回图像（adb 没有给出原因）」；
设备端落盘再 pull 报「设备端 screencap 失……」
```

两条都挂，但 `probe_shell` 通过了（否则就直接走「shell 被密码/权限拦截」那条
提示、不会继续到 pull）——说明 adb 通道本身通，只是 `screencap` 这条命令
在 exec-out 与 `/sdcard/` 落盘两条路径上都失败。

## 根因

`_pull_capture` 只试一条远程路径：`/sdcard/adbdc_shot_*.png`。

车机常见情况：
- Android 10+ 的 `/sdcard/` 是 FUSE 守护进程（sdcard-fuser）挂载的，kiosk
  / launcher-only 模式下这个守护可能没起，路径只读或甚至不存在；
- SELinux 策略把 `screencap` 二进制的写权限限制在 `/data/local/tmp/` 这类
  adb shell 用户空间，`/sdcard/` 写操作直接 `Permission denied`，但 exit
  code 可能是 0（策略层拒绝，命令本身没抛错）。

`/data/local/tmp/` 是 **adb shell 用户肯定可写** 的路径（Android 上通用
临时目录），这条路径此前完全没被尝试过。

## 修复

### [screen_service.py: _pull_capture](file:///workspace/backend/screen_service.py#L355-L453)

- 远程路径从单条 `/sdcard/...` 改成两条候选（`remote_candidates` 列表）：
  先试 `/sdcard/`，失败后 **自动 fallback 到 `/data/local/tmp/`**。
- 所有失败分支（screencap rc 非 0 / 超时 / pull 没拿回 / pull 超时 / pull
  异常）都追加到 `errs = []` 里，而不是覆盖上一个错误 —— 两条都挂时最终
  拼出 `"/sdcard/... 报 xxx；/data/local/tmp/... 报 xxx"`，用户能一眼区分
  是「路径都不可写」还是「screencap 命令本身不存在」。
- 重构为 for 循环 + 每次循环自己管理 `part` 文件清理：成功 return 前删
  `.part`，超时 / 异常 / pull 失败的 continue 分支里也各自删一次（不再
  依赖统一 finally），避免「上一轮遗留的 .part 被下一轮 pull 命中、
  误以为成功」的竞态。

### [screen_service.py: _exec_out](file:///workspace/backend/screen_service.py#L277-L296)

把原来的 "设备未返回图像（adb 没有给出原因）" 改成 **带 exit code +
完整 stderr/stdout** 的形式：
- adb 报错几乎都落在 stdout（`error: device 'xxx' not found`），两路
  都收；
- 之前只给 "adb 没有给出原因" 这种无信息文案，用户看到只会是「截图不行」，
  加了 exit code 后至少能知道是 adb 通道被掐、还是设备直接拒绝。

## 测试

新增两条（tests/test_backend_screen.py）：
- `test_pull_capture_falls_back_to_data_local_tmp`：
  `/sdcard/` screencap rc=1 → 自动 fallback 到 `/data/local/tmp/` 成功；
  调用顺序对（先 sdcard、再 data/local/tmp），.part 被清掉。
- `test_pull_capture_both_paths_fail_reports_both`：
  两条路径的 screencap 都是 rc=127（命令不存在）；返回错误里必须同时
  包含 `/sdcard/`、`/data/local/tmp/`、`退出码 127`、`not found`。

全量：后端 **1430 passed / 1 skipped**（比之前 +2）；前端 **94 文件 0 失败**
（cmd_note 已进 run-all）；pyflakes 干净。

# 第八十三轮（全面审查 + 硬约束补入 README）

## 触发

连续几轮出现「重构 / 加功能把已有路径搞崩，mock 测试因为调用次数 / 返回值
签名变了没同步改断言」这类回归：

| 轮次 | 回归点 | 原因 |
|---|---|---|
| 八十二 | 重构 `_pull_capture` 后测试挂 | 把统一 `finally: os.remove(part)` 改成分支内分别清理，漏了成功 return 路径，
   导致 `.part` 文件永远不删；重构后没跑全量就推了 |
| 七十？ | `ls -l` 诊断调用 | 临时加了 ls 探测，mock 测试计数变 4 而断言还停在 3，挂掉 |
| boot-splash | jsdom 依赖 document.body.firstChild | 首次在 `<body>` 顶部插节点，没意识到某些测试假设 body.children[0] 是别的东西 |

这些回归**都不是功能本身 bug，而是改动时漏了同步调用点 / 漏了全量回归**。
用户明确要求：不可以再出现这样的问题，并把这条写进开发约束。

## 全面审查清单（一次性过）

按「残留探针 → 调用点映射 → 测试覆盖 → 并发安全」逐层扫：

1. **残留探针**：`pyflakes backend core tools tests` 退出码 0；
   `grep -rn "TODO\|FIXME\|XXX\|后续\|暂不实现"` 扫出来的都是正常注释，没
   有遗留的临时绕过。
2. **调用点同步（grep 全链路）**：
   - `_pull_capture` 改远程路径列表 → 只有 `ScreenCapturer.screenshot` 一处
     调用，返回签名 (data, why) 不变，无需调用方改。
   - `_exec_out` 错误文案改（加入 exit code）→ 调用点同上，文案变长但
     结构不变，`screenshot` 末尾拼接串天然兼容。
   - `update_info` 加 `skipped` 字段 → 前端只在 `loadUpdateInfo` 读，
     不影响其他消费方。
   - `normalize_commands` 加 `_as_text` 分支 → 所有 merge_builtins /
     save_commands 都是浅拷贝透传，note 自动跟随；export_commands 显式
     枚举加了 note，对齐 bg/fg。
   - boot-splash 在 `<body>` 顶部插入 → grep 所有 `body.innerHTML =`，
     全部是 appendChild，没有整段替换，不会被清掉。
3. **测试覆盖映射（改动点 ↔ 对应测试）**：
   | 改动 | 对应测试 | 状态 |
   |---|---|---|
   | `_pull_capture` 加 `/data/local/tmp` fallback | `test_pull_capture_falls_back_to_data_local_tmp` | ✅ |
   | `_pull_capture` 双路径错误聚合 | `test_pull_capture_both_paths_fail_reports_both` | ✅ |
   | `.part` 清理分支覆盖 | 原有 `test_pull_capture_cleans_remote_and_part_file` | ✅ |
   | `_exec_out` 错误补 exit code + stdout/stderr | `test_exec_out_reports_adb_error_from_stdout` | ✅ |
   | update_info.skipped 字段 | `test_update_info_reports_skipped_version` | ✅ |
   | note normalize / 保留 | 后端 `test_load_commands.py` + 前端 `cmd_note.test.cjs` | ✅ |
   | boot-splash HTML | `boot_splash.test.cjs` | ✅ |
   全部绿。
4. **并发安全**：`ScreenCapturer._seq` 是 `itertools.count()` 全局迭代器，
   每次调用 `next()` 拿到唯一序号（thread-safe，C 实现）；`safe_name` 纯
   函数无状态；`_pull_capture` 里 `part` 是函数内局部变量，不同调用互不
   干扰（serial 唯一文件名）。没有跨调用共享的可变状态，并发截图安全。

## 硬约束补入 README（二次开发段 → 硬约束小节）

六条可执行的门禁规则，每次 commit 前逐条自查：

1. **改一处 = 全链路同步**：改完 grep 旧名字搜残留；
2. **重构前先写失败用例**：先证明当前代码真会挂，再重构；
3. **跑全量才能提交**：pyflakes + pytest + run-all.cjs 三者全绿才能 commit；
4. **不能加临时绕过**：禁止 try: pass / 静默吞异常；
5. **改既有路径 / 分支时补测试**：每条新分支有断言覆盖；
6. **HTML 改动要想 jsdom**：改完跑 run-all 验证 DOM 用例。

每条违反一次 commit 必须返工。

## 验证

后端 **1430 passed / 1 skipped**；前端 **94 文件 0 失败**；pyflakes 干净。
