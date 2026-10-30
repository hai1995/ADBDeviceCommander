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
`SIDE_FILES` 只有 `quick_commands.json` / `使用说明.txt`，`BUNDLED_DATA`
也不含它。于是打好的程序目录里没有任何配置文件：用户看不到有哪些项
可配，「设置记忆」也要等第一次改动某个开关才由 `save_prefs` 悄悄创建文件——
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

## 已知取舍 / 下一轮候选

- **不自动替换自身**：理由见上（占用 / 杀毒 / UAC 三条路都更差）。真要自动化，
  更合适的方向是「下载 + 校验 + 提示用户关闭程序后替换」，而不是程序自己动手。
- **更新检查不看预发布版**：只读 `releases/latest`（GitHub 定义上就是「最新正式版」），
  预发布（prerelease）不会推给同事。这是有意的——同事要的是能用的版本。
- **12 小时这个间隔是拍的**：程序是常驻工具（开着就是半天），比「每次启动查」更贴合，
  又不会打接口打太勤（匿名 60 次/小时）。真要更频繁，改 `core.update.CHECK_INTERVAL_S`。
