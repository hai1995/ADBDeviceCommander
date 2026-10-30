# ADB 设备指令台（ADB Device Commander）

一个面向**多台 Android 设备**同时连接场景的 Windows GUI 小工具。
把你在 electerm 里常用的快捷指令集中进来，点击即可下发；程序会自动识别 `adb`
命令并拼接 `-s <设备序列号>`，彻底告别「more than one device」的报错。

当前界面为 **pywebview + HTML/CSS/JS** 的 Web 版（深色「仪器面板」主题），
后端逻辑在 `backend/` + `core/`，纯逻辑层可单测、可复用。Tk 版已弃用移除，
本仓库仅维护 Web 版。

---

## 架构

界面（前端）与能力（后端）彻底分离，三层各司其职：

```
ADBDeviceCommander/
├── main.py               # pywebview 宿主：创建窗口 + 生命周期（薄，不含业务）
├── frontend/             # 界面（HTML/CSS/JS，纯展示，无业务逻辑）
│   ├── index.html        # 多 tab 骨架：设备指令 / Logcat / 工具 / 文件 / 关于
│   ├── css/app.css       # 仪器面板主题（暗底 + 磷光青 + 等宽数字）
│   └── js/app.js         # 事件路由 + 各 tab 渲染 + 动作下发
├── backend/              # 服务层（状态 / 线程 / 设备 / 事件桥 / 工具）
│   ├── bus.py            # 线程安全事件总线（前端 take_events 轮询拉取）
│   ├── state.py          # 集中状态管理（生命周期 / 运行态，唯一数据源）
│   ├── workers.py        # 后台工作线程（去重 / 记档 / 优雅关闭）
│   ├── device_service.py # 设备快照 / 增量刷新 / 勾选保留
│   ├── controller.py     # WebApi：pywebview js_api 统一动作入口（薄桥）
│   ├── device_proc.py    # 设备端进程优雅收尾（screenrecord/tinycap：-INT → 等写回 → 才 -TERM）
│   ├── logcat_service.py # Logcat 实时监控 / 抓取（写文件 / 按级别过滤 / 结束后打包 zip）
│   ├── screen_service.py # 截图（screencap）/ 录屏（screenrecord）
│   ├── audio_service.py  # 电脑麦克风(WinMM) + 设备音频(tinycap) + ffmpeg 合成
│   │                     # （实现保留，但界面已撤掉这两个开关：链路未跑通，见「工具」）
│   └── file_service.py   # 文件管理（ls 解析 / 增删改 / 上传下载 / 查看）
├── core/                 # 纯逻辑（无 UI 依赖，可被任意前端复用）
│   ├── constants.py      # 常量 / 正则 / 状态翻译 / resource_path / ls 解析
│   ├── commands.py       # 快捷命令归一化（含 electerm inputOnly）/ clickCount 回写
│   ├── prefs.py          # config.json（保存目录 / adb 目录 / 各开关与过滤条件）读写、类型防错与 PATH 注入
│   ├── clipboard.py      # 图片写**系统**剪贴板（ctypes 零依赖 + 可选 numpy 加速解码，供截图同步用）
│   ├── imgbytes.py       # 图片字节归一化：跳过前导杂字节、按签名识别 PNG/JPEG/…、裁尾部垃圾
│   ├── devices.py        # 设备解析与增量 diff
│   ├── shell.py          # 持久 PowerShell 会话
│   ├── logcat.py         # logcat 行分类 / 异常识别
│   ├── rootguard.py      # adb root/unroot 切换识别 + 设备 root 状态查询（防断录屏）
│   ├── wireless.py       # 无线调试：地址校验 / 设备 IP 提取 / adb connect·tcpip 输出解析
│   ├── apk.py            # APK 安装：参数拼装 / 输出解析 / INSTALL_FAILED_* 中文翻译
│   ├── devinfo.py        # 设备信息快照：一次 adb shell 取全（getprop/wm/battery/df/mem）
│   ├── diag.py           # 诊断包：设备信息/日志尾部/进程 TOP/应用清单/ANR 一次收齐并打 zip
│   ├── tmpfiles.py       # 系统临时目录里「本程序遗留副本」的保守清理（只碰自己的前缀）
│   ├── update.py         # 版本检查：版本比较 / Release 解析 / 挑 Windows 资产 / 失败翻译（不发请求，opener 注入）
│   ├── win_theme.py      # 原生标题栏套用界面深色（DWM 属性，Win10/11，纯逻辑可单测）
│   └── envcheck.py       # 启动前环境预检（WebView2/依赖/adb，纯判定可单测）
├── adb_inject.py         # 纯逻辑：adb/scrcpy 的 -s 自动拼接（可单测）
├── requirements.txt      # 依赖（pywebview / webview 运行时）
├── build.py              # PyInstaller 一键打包成 exe
├── assets/app.ico        # 程序图标
├── tools/                # 版本号递增（bump_version.py）+ 扁平 zip 打包（package.py）
│                         #   + 源码推送 GitHub（push_github.py，token 不进版本库）
├── .github/workflows/    # CI：每次 push 跑全量测试；打 tag 自动构建并发 Release
├── tests/                # 单元测试（backend/* + core/* 纯逻辑）+ 前端 jsdom 测试
├── 使用说明.txt           # 给最终使用者的简明说明（打进 exe 内部，在程序「关于 → 使用说明」里阅读）
└── README.md
```

**事件通信**：后台线程只 `bus.push(kind, payload)`，前端每 400ms `api.take_events()`
拉增量（模拟旧 Tk 版 `_poll_queue` 语义，天然适配 logcat 大流量，并规避
pywebview `evaluate_js` 的跨线程限制）。空闲时轮询退避到 500ms（省 CPU/电池，
又不让「截图/录屏/抓取完成」的 toast 迟到）；一旦有事件立即回到 400ms。
事件种类：`booted` / `devices` / `console` / `status` / `tool` / `stop_state` /
`rec_state` / `shot_state` / `apk_state` / `diag_state` / `update_state` / `update` /
`logcat` / `logcat_capture` / `file` / `file_view`。

**分发是逐条隔离的**：任何一条事件的处理函数抛异常都只丢弃它自己 —— 同一批里
后面的事件照常处理，轮询续约也一定发生（`try/finally`）。否则一条坏事件就能让
事件轮询链彻底断掉，界面从此静默停摆（不报错、不弹窗，只是什么都不再更新）。

---

## 运行与打包

### 运行（开发 / 调试）

```bat
pip install -r requirements.txt
python main.py            # Web 版（pywebview 宿主）
python main.py --debug    # 附加 WebView2 开发者工具（调前端用）
```

> `requirements.txt` 里的 **numpy 是可选加速项**：装了之后「截图同步至剪贴板」
> 的 PNG 解码走向量化（1080x2400 快一倍以上，没装自动回退纯 Python，结果一致）。

> 必须用**项目 venv** 里的 python（`venv\Scripts\python.exe`）。直接用系统 `python`
> 可能命中 WindowsApps 占位程序而不启动；直接用浏览器打开 `frontend/index.html`
> 会显示「未检测到 pywebview」遮罩——必须经 `main.py` 启动。

### 打包成 exe（推荐给同事用）

```bat
python build.py                # 单文件 exe（默认，分发用）
python build.py --onedir       # 目录模式：启动更快、缺文件时更好排查
python build.py --console      # 保留控制台窗口（排查「闪一下就没」）
python build.py --bump         # 打包前先用 tools/bump_version.py 递增版本号
python build.py --dry-run      # 只打印将要执行的 PyInstaller 命令
python build.py --no-deps      # 跳过依赖检查与自动安装
```

产物为 `dist\ADB设备指令台.exe` 一个文件，放在任意目录即可双击运行。
`frontend/` 与使用说明都只打进 exe 内部（界面代码与说明使用者无需也不会去改）；
分发目录因此只有 exe 本体，最干净、最不会误伤同事已有的个人数据。分发的 `dist\` 内容：

| 文件 | 说明 |
| --- | --- |
| `ADB设备指令台.exe` | 主程序（单文件，双击运行，无需 Python） |

> 使用说明不再以独立文件随包分发，而是内置于 exe，在程序「关于 → 使用说明」子 tab 里直接阅读。

> **刻意不随版本分发的内容**：`commands.json`（快捷指令库）与 `config.json`（各项配置）
> 都是「用户使用后才在 exe 同目录产生的个人数据」——前者首次打开自动生成默认指令库，
> 后者在用户第一次改动设置时落盘（启动时若缺失则全部走界面默认值）。把它们打进每个版本，
> 同事重装 / 升级就会覆盖掉自己先前调好的命令库与设置，因此 dist/ 里只给 exe 与说明，
> 运行时缺失时程序均会自动重建默认值。`assets/` 仅构建期用于 exe 图标，也不随分发目录提供。

> **首次运行弹「WebView2 Runtime 未安装 / 版本过旧」**：Web 版界面依赖 Windows 的
> WebView2 Runtime（需 **121 及以上**），较新 Win10/11 已自带；缺失请到
> https://developer.microsoft.com/microsoft-edge/webview2/ 下载安装包，以管理员身份
> 运行安装，装完重开 exe 即可。

> **打包报 `PermissionError` / `set_exe_build_timestamp` 失败**：这是 PyInstaller
> 收尾给 exe 打时间戳时文件被占用（杀毒软件实时扫描 / 网盘同步 / 上一版 exe 还在运行）。
> build.py 会分情况处理：exe 已完整落盘时只警告、继续发布；否则中文提示「退出运行中的
> 程序 + 把工程目录加进杀毒排除项」后退出。手动处理：任务管理器确认无「ADB设备指令台.exe」
> 残留进程，将 `D:\Code\ADBDeviceCommander`（或你的工程目录）加入 Windows 安全中心 →
> 病毒和威胁防护 → 管理设置 → 排除项，重跑 `python build.py`。

### 一条命令出「发给同事」的包

```bat
python build.py --package      # exe 打完后，再压一个 ADBDeviceCommander_v<版本>_win64.zip
python build.py --package --zip   # 同时产出发给同事的分发件 + 源码分发包
```

产物 `dist\ADBDeviceCommander_v<版本>_win64.zip` 里只有 `exe` 本体（使用说明已内置于
exe，不再以独立文件随包），套在与 zip 同名的顶层目录下。分发包刻意只含 exe：`commands.json` / `config.json`
是用户使用后才产生的个人数据，打了反而会让同事重装覆盖自己先前的命令库与设置；`assets/`
仅构建期用于 exe 图标、不随分发目录提供。

> 名字里的 `_win64` 不是装饰：更新检查按这个后缀从 Release 资产里挑 Windows 包
> （`core.update.ASSET_SUFFIX`），改名会让自动更新退化成「随便挑一个 zip」。
> `tests/test_build.py` 有断言盯着这两处一致。

### 打源码分发包（二次开发 / review 用）

```bat
python build.py --zip        # 打完 exe 后，额外产出干净源码 zip
python build.py --zip-only   # 跳过 PyInstaller，只产出源码 zip
```

产物为 `dist\ADBDeviceCommander_v<版本号>.zip`。**不要直接「整个文件夹右键压缩」**——
会把 `tests\frontend\node_modules`（约 26 MB）和一堆 `__pycache__` 打进去。
`make_source_zip()` 内置排除规则（node_modules / `__pycache__` / `.pytest_cache` /
build / dist / .git / config.json / settings.json / `*.pyc` 等）。

包内所有文件都挂在**与 zip 同名的顶层目录**下（`ADBDeviceCommander_v2026.1029.1649/`）：
解压不会把 `main.py` / `core` / `frontend` 散落一地；顶层也没有 `index.html`，
云端导入时不会被误判成「网页包」而解包成一个取不到文件的空壳页面。

### 推送到 GitHub（版本留档 / 换机取回）

远端：`https://github.com/hai1995/ADBDeviceCommander.git`（**私有**仓库，含个人命令库）。

```bat
python tools\push_github.py --status        :: 只看状态，不动仓库、不需要 token
python tools\push_github.py                 :: 有改动就提交（说明自动生成）并推送
python tools\push_github.py -m "修菜单层叠"  :: 指定提交说明
python tools\push_github.py --init          :: 首次：git init + 首次提交 + 关联远端 + 推送
python tools\push_github.py --dry-run       :: 只打印将要做什么
```

**第一次用要先放凭证**（只需一次，二选一）：

```bat
:: 方式 1：写文件（推荐，之后一直有效）
echo {"token":"github_pat_xxx"} > .git-credential

:: 方式 2：只在本条命令里给（换机器 / CI 用，不落盘）
set GH_TOKEN=github_pat_xxx && python tools\push_github.py
```

读取顺序是 **`--token` > `GH_TOKEN` / `GITHUB_TOKEN` > `.git-credential`**。
`.git-credential` 在 `.gitignore` 里，不会被 `git add -A` 带上。

> **为什么不直接把 token 写进 remote URL**：那样 token 会明文躺在 `.git/config`，
> 而且 `git push` 一旦失败会把**整条 URL 连同 token** 打回控制台——随手截图发群里就泄了。
> `push_github.py` 改用 `http.extraHeader` 只在本次命令注入认证头：
> remote 保持干净地址，git 的回显与报错里都不含 token；连推送失败时打印的
> git 原文都会先把 token 换成 `***`。

推送失败的提示是翻译过的，直接说下一步：

| git 原始输出 | 脚本给出的下一步 |
| --- | --- |
| `Authentication failed` / `Invalid username or password` | token 失效，去 GitHub 重新生成后更新 `.git-credential` |
| `403` / `Permission denied` | 私有仓库要求 token 勾 **Contents: Read and write**，细粒度 token 还要把该仓库加进 Repository access |
| `Could not resolve host` | 网络/代理问题 |
| `non-fast-forward` | 远端有本地没有的提交，先 `git pull --rebase origin main` |
| `src refspec ... does not match any` | 本地还没提交过任何东西 |

### CI/CD：打一个 tag 就自动构建发版

`.github/workflows/build.yml` 分两个 job：

| job | 运行环境 | 触发 | 做什么 |
| --- | --- | --- | --- |
| `test` | ubuntu-latest | 每次 push / PR | `pytest` 全量（约 940 项）+ 前端 61 个 jsdom 用例 |
| `windows` | windows-latest | push 到 main / 打 tag / 手动 | 装依赖 → 校验 tag 与源码 `VERSION` 一致 → `build.py --package --zip` → 生成 `sha256sums.txt` → 上传 artifact → tag 时发 Release |

打 tag 之后的两三分钟，Releases 页面就有 `ADBDeviceCommander_v<版本>_win64.zip`
（给同事的）、源码包（给要看代码的）和 `sha256sums.txt`。同事的下载地址因此固定成
「最新 Release」，不用再问「现在该用哪版」。

发版只剩两步：

```bat
python tools\bump_version.py --apply
git commit -am "第二十四轮：…" && git tag v2026.1103.1200 && git push --tags
```

两个刻意的设计：

* **tag 与 `core/constants.py` 的 `VERSION` 不一致直接失败**。Release 标题、
  zip 文件名、程序自报版本号三处一旦不一致，用户看到的「我有新版」和实际下到的
  包就对不上，事后极难排查。
* **同一 tag 重跑不报错**：`gh release view` 能查到就 `gh release upload --clobber`
  补传附件，查不到才 `gh release create`。否则「重新跑一次流水线」会因
  「Release 已存在」红掉。

> 资产名是显式列出来的，不用 `dist/*.zip` 通配：那样源码包与分发件会混在一起
> 传两遍，`gh` 因同名重复直接报错。

### 进仓库的是什么

`.gitignore` 挡掉运行产物与凭证，避免「一次 `git add -A` 把不该传的带上」：

| 忽略项 | 原因 |
| --- | --- |
| `config.json` / `settings.json` | 运行时个人配置，含本机绝对路径 |
| `commands.json` | 用户个人命令库（含私人 adb 指令 / 项目内部命令），**不进仓库**、也不随 dist 分发；首次启动在运行目录自动生成默认示例（避免覆盖用户已有命令库） |
| `*.wav` | 设备音频回环的调试录音（`adb_devaudio_<序列号>_<时间>.wav`），运行产物 |
| `.git-credential` | 推送凭证 |
| `dist/` `build/` `dist_stage/` `*.spec` `*.exe` | 打包产物 |
| `__pycache__/` `*.pyc` `.pytest_cache/` | 缓存 |
| `tests/frontend/node_modules/` | 前端测试依赖（约 26 MB，`npm i` 可重建） |
| `crash_*.log` | 崩溃日志，含 traceback 与本机路径 |

`commands.json`（快捷指令库）**不**进仓库、也**不**随 dist 分发——它是用户个人命令集合（可能含私人 / 内部指令），按 `config.json` 同类处理：仓库里没有时，程序首次启动会在运行目录自动生成一份默认示例；因此干净检出运行时首次打开也有命令可用，而重新分发不会覆盖用户已有的命令库。

---

## `-s` 自动拼接规则

| 命令类型 | 行为 |
| --- | --- |
| `adb shell …` / `reboot` / `pull` / `install` 等 | 自动拼 `-s <serial>` |
| `adb -s 0612333… …`（已写死序列号） | **替换为**所选设备序列号 |
| `adb devices` / `kill-server` / `start-server` / `connect` 等全局子命令 | **不注入** `-s`，原样全局执行 |
| `adb.exe …`（绝对路径写法） | 同 `adb` 规则 |
| `scrcpy` | 自动拼 `-s`，多台设备弹多个投屏 |
| `python` / `git` / `appium` / `cd` 等非 adb 命令 | 原样执行，**不循环** |

**多设备循环规则**：只有「含需要指定设备的命令（adb/scrcpy 且会被注入 `-s`）」
的快捷指令才会按设备循环；纯 PC 命令（如跑 pytest、git）只执行一次，避免重复。

---

## 界面说明

整体布局：**左侧常驻「设备栏」**（跨页签共享、始终可见）+ **右侧页签区** +
**顶栏右上角「状态信息」跑马灯**（点击弹窗看全量）。六个 tab 顺序：
设备指令 / 工具 / 性能监控 / Logcat / 文件 / 关于。

| tab | 作用 | 设备模式 |
| --- | --- | --- |
| **设备指令** | 左侧勾选设备 + 按标签分组的快捷指令 + 自定义命令输入框；右侧「指令输出」面板（I/O 分流）。标签条中**「内置」独立成组、恒置最底**（不与用户命令混排）；兼容 electerm 的 `"inputOnly": true`——点击仅填入输入框、确认后手动执行。**内置命令 49 条**（连接与投屏 / 显示辅助（指针位置·触摸圆点·系统动画）/ 按键 / 屏幕状态 / 网络 / 应用与信息 六类，可分可折叠、状态记在 config.json 的 `builtin_folded`，组标题带「全部折叠 / 全部展开」，搜索框也能按类名筛；筛选时自动展开），装好 adb 即可用；用户命令文件里有同名条目时内置那条自动让位。**命令序列里的裸 `powershell` / `cmd` / `bash` 按交互式直通**（只写入不等返回，后续命令送进这个子 shell，`exit` 退出后恢复逐条执行），**单条命令有 120 秒兜底超时**（`cmd_timeout` 可调，0 = 不限制）——否则一条读 stdin 的命令会把执行通道占死，表现为「整程序卡死、后续命令点不动」。 | 多设备广播 |
| **工具** | 五张卡**自上而下竖排**（截图 / 录屏 / 应用安装 / 诊断包 / 投屏），每张标题栏单击即可收起 / 展开，收起态**各记各的**（`shot_collapsed` / `rec_collapsed` / `apk_collapsed` / `diag_collapsed` / `scrcpy_collapsed`）——常看的展开、不看的收成一行，屏高自己掌控。截图（screencap→PNG，**可选同步至系统粘贴板**）；录屏（screenrecord，手动停止；**指针位置 / 触摸圆点默认开启**——指针位置 = 画面常驻准星并跟随触摸（`settings put system pointer_location 1`），触摸圆点 = 触摸时屏幕出圆点（`settings put system show_touches 1`），均为系统级 overlay、全 Android 版本可用，停止录屏自动恢复设备原设置，回顾录像时能直观看到操作位置；「同步录制 logcat」**一律全量**：`adb logcat -b all` 覆盖设备上全部缓冲区，且不做级别过滤、不截断——录屏配套日志是事后复现的唯一物证，不提供"精简"选项）；Logcat 抓取（落盘 txt / 结束后可选打包 zip）。**设备音频 / 电脑麦克风两项已从界面撤掉**（采集链路未跑通，成片一直是无声的，不再给假承诺）。备用投屏的内嵌预览**右下角有拖拽手柄**，按住即可拖大（等比缩放留黑边），双击恢复自适应，大小记进 `config.json`。**应用安装**：选本地 APK → 一键装到全部受控设备（每台一个后台线程，`-r` 覆盖 / `-d` 允许降级 / `-g` 授予全部运行时权限三个开关，默认只勾覆盖）；失败码（签名不一致 / 版本降级 / 空间不足 / ABI 不匹配 …）翻成中文并给出下一步，`testOnly` 包自动改用 `-t` 重试一次，全部结束后汇总一条 toast。 | 多设备广播 |
| **性能监控** | 类 PerfDog 的实时面板：**「应用包名」下拉选择**（从设备已安装应用里挑，支持模糊搜索；默认跟随前台应用，也可切「监控全系统」只采整机指标，或直接手输包名回车生效）；CPU（/proc/stat 差分）、整机内存（MemTotal−MemAvailable）、应用 PSS（dumpsys meminfo）、帧率（dumpsys gfxinfo 帧数差分）、**卡顿率**（Δ卡顿帧 ÷ Δ总帧，区间值而非累计百分比）、电量 / 电池温度（dumpsys battery）。七张指标卡即当前值 + 采样区间，点卡片切换下方曲线；**多设备同时勾选即自动分色对比**（同图多线 + 图例读数，点图例切焦点）；**阈值告警**（内置基线 FPS<45 / 卡顿>8% / 温度>42℃ / CPU>85%，可点「阈值」自行修改，落到 config.json 的 perf_thresholds）：越线指标卡切红、状态栏提示、曲线画虚线参考线，报告里单列「阈值告警」卡片（超标点 / 占比 / 最差值 / 最长持续）并**在曲线上给超标时段打红色色带**。一键导出 **HTML 报告**（统计 min/avg/max/P95 + 七条曲线 + 告警 + 明细）与 **CSV**（原始数据）；**多设备时额外生成一份横向对比报告**（设备信息表 + 指标对比矩阵 + 七张多线图 + 告警汇总）。采样间隔 200~10000ms，默认 1s；数据缺口断线不连线。**鼠标在曲线上移动即出竖线 + 数值卡片**（时间点 + 每台设备该时刻读数与单位，多设备一行一台）；**按住横拖可框选区间**，松手给出该区间均值 / 最低 / P95 / 最高 / 超阈值次数（双击、Esc、× 清除）。不注入、不装 APK、不需 root。 | 多设备（最多 4 台，自动对比） |
| **Logcat** | 分「落盘抓取 / 实时监控」两张卡片（抓取在上：留证据 / 发同事是更高频场景）：抓取写入本地 txt（**按级别过滤**，全选 = 全量，「结束后打包 zip」默认开启）；监控（关键字 / 级别 / 缓冲区 / 仅异常 过滤、异常高亮、保存到文件）仅查看不写文件、吃满剩余高度。两卡相互独立、可同时进行。 | 单设备（随受控设备自动联动） |
| **文件** | 类 Android Studio Device Explorer：路径栏 + 表格浏览，上传 / 下载 / 删除 / 新建 / 重命名 / 查看内容；单击文件名切换选择，支持 Ctrl 加选 / Shift 区间选、双击目录进入、批量下载 / 删除。 | 单设备（随受控设备自动联动） |
| **关于** | 版本 / adb 状态与目录（可填写保存）/ 快捷命令数 / 在线设备 / 启动警告 + 功能概览。 | — |

- **设备栏（全局常驻）**：设备卡片（点击勾选下发目标，显示型号与状态；仅可操作
  设备可勾选）；顶部「无线 / 刷新设备 / 全选 / 取消选择」。切到任意 tab 都可见，
  勾选变化实时刷新所有依赖设备的功能。卡片上的 **ⓘ** 打开「设备信息」（型号 / 厂商 /
  系统版本 / Android 版本 / ABI / 分辨率与密度 / 电量温度 / 存储 / 内存 / 开机时长，
  一次 `adb shell` 取全）；序列号过长被省略号截断时，悬停卡片可看完整值。
- **无线调试（Wi-Fi ADB）**：设备栏顶部「无线」→ 弹窗里连接 / 断开无线设备。
  输入 `192.168.1.23`（端口默认 5555）或整条 `adb connect …` 粘进去都能识别；
  「对勾选设备开启无线调试」会先读设备自身 IP（`ip route` / `ip -4 addr`）再执行
  `adb tcpip 5555`，并把读到的 `IP:5555` 直接填进地址框——省掉去设置里翻 WLAN 详情
  这一步。最近连接记 5 条（`wifi_recent`），点一下即重连。
- **状态信息（全局常驻）**：设备插拔、刷新、截图/录屏/音频/打包、命令执行/停止
  等**程序运行信息**统一收在这里。原先的底部常驻面板已撤除（内容区整块让给
  logcat / 文件表格），改为**顶栏右上角的横向跑马灯**：只滚动显示最近几条，
  鼠标悬停即暂停（停下来读一行），左侧状态灯颜色跟随最新一条的语义
  （绿=成功 / 黄=警告 / 红=错误 / 青=提示）；**点击展开弹窗**看完整历史，
  弹窗内可「复制 / 清空」、可框选部分文本复制，`×` / `Esc` / 点背景都能关。
  「指令输出」（仅设备指令 tab）只显示手动输入的命令与响应，两者严格分流。
- **全局 Toast（完成强提醒）**：**关键完成事件**一律在屏幕右上角弹 toast，
  切到任何 tab 都不会错过——截图完成（单设备一张一条；多设备批量到齐后
  汇总一条，报成功/失败计数）、录屏完成（含合成 / 打包，汇总一条）、Logcat
  抓取完毕（含打包，与状态栏同源不重复）；错误级提示（截图失败 / 录屏失败 /
  下载失败 / 麦克风启动失败等）同样弹 toast。toast 4~8 秒自动消退、可点击关闭，
  同屏最多 4 条；明细（逐台路径 / 合成信息）仍以状态栏跑马灯 + 弹窗为准。
- **截图进行中的按钮态**：点「立即截图」后按钮立即禁用（截图 = 设备采集 +
  USB 传输 + 落盘，耗时以秒计），完成 / 失败后自动恢复；期间重复点击被拦截，
  不会重复下发。后端未受理（如未勾选设备）时按钮即刻恢复，不会卡在禁用态。
- **多设备 vs 单设备**：`设备指令` 与 `工具` 对所有「受控设备」广播；`Logcat` 与
  `文件` 为单设备，自动以第一个受控设备为当前目标、随勾选实时联动（顶部蓝色
  `设备: XXXX` 指示）。
- **配置持久化（config.json）**：保存目录（工具 / Logcat / 文件 三页共享）、adb
  目录、截图「同步至粘贴板」、「保留输入内容」、指令台搜索关键字、设备栏收起状态、
  Logcat 过滤条件
  （关键字 / 级别 / 仅异常 / 自动滚动 / 缓冲区 / 抓取打包 / 抓取级别）、录屏各开关
  （同步 logcat / 打包 / **指针位置** / **触摸圆点**）、三张工具卡各自的收起态
  （`shot_collapsed` / `rec_collapsed` / `scrcpy_collapsed`）、
  单条命令兜底超时（`cmd_timeout`，默认 120 秒，0 = 不限制）、
  无线调试（`wifi_port` / `wifi_recent`）、APK 安装选项与安装卡收起态
  （`apk_replace` / `apk_downgrade` / `apk_grant` / `apk_collapsed`）
  全部即时落盘到 exe 旁的 **`config.json`**，每次启动自动恢复以往配置；任一修改
  实时同步到相关控件，留空 / 缺省回退默认（保存目录留空回退
  `%USERPROFILE%/Pictures/ADB` 或 `$HOME/Pictures/ADB`）。
  首次运行若在 exe 同目录未发现 `config.json`，程序会全部走界面默认值；用户在界面
  改动任意设置后才会落盘一份 `config.json`。`dist\` 不再自带 `config.json`——避免重装 /
  升级覆盖同事先前调好的设置（打开目录看不到配置项属正常，改动一次即生成）。
- **配置可拷贝、可跨设备同步**：所有设置集中在这**一个** `config.json` 里
  （位置在「关于」页可直接看到，点「打开目录」即可定位）。把它拷到另一台电脑的
  程序目录下，全部设置（开关 / 过滤条件 / 保存路径）一并同步过去。
  - **路径失效自动回退**：`save_dir` 是绝对路径，源机上的
    `C:\Users\张三\Pictures\ADB` 在新机上通常不存在。此时程序**本机改用默认
    目录**并在状态信息里 `⚠ 配置里的保存目录在本机不存在，已改用默认目录：…`
    提示，绝不往一个不存在的路径里写文件（否则你会以为同步成功了，其实全丢）。
    **配置文件里的原值保持不动** —— 那是源机器上的正确路径，回拷回去依然有效；
    想在本机长期用别的目录，在界面上改一次保存目录即可。
  - **旧版自动迁移**：早期版本把配置写在 `settings.json`。升级后程序会检测到它，
    自动迁移一份到 `config.json` 并提示一次；旧文件保留不删（可作备份）。
- **配置防错**：`config.json` 手改写错类型（布尔写成字符串 `"true"`、路径写成
  数字、级别拼错）时，启动自动纠正该项为默认值并在状态信息里 `⚠ 配置已纠正：…` 提示，
  绝不静默复位也绝不让错误值生效；未知字段原样保留（不抹用户内容）；文件损坏 /
  带 BOM / 只读时静默回退默认，不打断启动；写入走「临时文件 + 原子替换」，
  中途崩溃不会把配置写成半截 JSON。
- **原生标题栏跟随主题**：窗口用系统标题栏（保留贴边分屏 / 双击最大化 / 高 DPI），
  配色由 DWM 属性改成与界面同色（`core/win_theme.py`：深色模式 + 标题栏/文字/边框
  三个颜色，Win11 全套、Win10 1809+ 至少深色模式，非 Windows 静默跳过）——
  系统是浅色主题时也不会在深色界面上压一根近白的标题栏。
- **分隔条拖动与窗口缩放**：设备栏 ↔ 内容区、指令台 ↔ 指令输出两条分隔条均可拖动
  （双击重置）。拖动按**真实可见容器宽度**钳制（右栏至少保留 360px），窗口缩放时
  自动重钳已拖出的宽度（只缩不增）——右侧「指令输出」不会被挤出屏幕。
- **设备栏收起 / 展开**：点设备栏标题前的 **«** 按钮，「已连接设备」整栏折叠成
  48px 窄轨——顶部是方块化的 **»** 展开钮（悬停点磷光青），底部钉着设备数徽章
  （只留等宽数字）与一条竖排的「已连接设备」铭牌；内容区用满宽度。再点 **»**、
  或点窄轨空白处即展开，并恢复收起前拖好的宽度。收起状态记入 `config.json`
  （`sidebar_collapsed`），下次启动保持——窗口缩放也不会把它弹回展开。
- **停止**：当前命令卡住（`appium` 服务、`scrcpy`、长耗时测试）时点它终止
  （也可终止 logcat / 录屏）。
- **临时文件不会越攒越多**：文件页「查看」遇到大文件 / 二进制时会把文件 pull 到
  系统临时目录再交给系统程序打开（大文件经事件总线直传会把界面卡死）。这类副本
  没有任何界面入口可删，堆积起来能吃掉几个 GB。现在两处兜底：**每次查看前**清掉
  「最近 8 个之外、且超过 10 分钟」的旧副本（正在看的那份一定保留）；**每次启动**清掉
  上一轮遗留超过 1 小时的副本。只碰 `adb_view_` 前缀、只删普通文件、不跟符号链接，
  单个文件删不掉（被占用）就跳过（`core/tmpfiles.py`）。
- **诊断包（出事之后一步留证）**：工具页「诊断包」卡一点，把这台机器此刻的现场
  收齐打成一个 zip —— `device.txt`（型号 / 系统 / 分辨率 / 电量 / 存储 / 内存 / 开机时长）、
  `props.txt`（`getprop` 全量）、`logcat.txt`（尾部 N 行，可不含）、`process.txt`
  （内存 TOP 15 + `ps` 原始表）、`apps.txt`（第三方 / 系统应用包名清单与总数）、`anr.txt`
  （前台 Activity + `lastanr` + `/data/anr`、`/data/tombstones` 列表）、`meta.json`
  （收集时间 / 程序版本 / 每份文件的来源命令与字节数 / 缺失原因）。整包只读设备状态，
  不影响正在跑的 logcat / 录屏；某一段读不到（如 `/data/anr` 无权限）只让那个文件写一行
  中文说明，整包照常产出。多台勾选时逐台顺序收集（logcat 密集调用并行只会互相排队）。

---

## 分发给同事 / 使用说明

给最终使用者的完整说明已内置于程序，在 **「关于 → 使用说明」** 子 tab 里直接阅读
（源码在仓库根 `使用说明.txt`，`build.py` 把它打进 exe 内部、不再以独立文件随包
分发；改说明请只编辑它，避免源码与内置副本漂移）。给同事的要点：

1. **整体拷贝**：把 `dist\` 整个文件夹拷走，不要只发 exe——`commands.json`
   必须和 exe 同目录，编辑它才能生效。更省事的做法是直接发
   `dist\ADBDeviceCommander_v<版本>_win64.zip`（`python build.py --package` 或 CI 产出），
   解压出来就是「exe + json + assets + 说明」一整套。
2. **使用前**：设备开 USB 调试、电脑 adb 可用（或程序里填 adb.exe 绝对路径）、
   连数据线并在设备上点允许调试。
3. **加 / 改指令**：直接编辑同目录的 `commands.json`（兼容 electerm 导出），
   重启程序生效；解析不出的条目会被跳过并在输出区用 `⚠` 提示，不会崩。
4. **常见问题**：`more than one device` → 去掉命令里写死的 `-s`；`未授权` → 在设备
   上点允许；改了 json 没效果 → 确认同目录且已重启。
5. **启动报「WebView2 过旧 / 缺失」**：按上文链接安装 WebView2 Runtime（≥121）即可。

---

## 版本更新提示（程序内）

程序会自己看有没有新版，不需要用户来问「现在该用哪版」。

| 环节 | 行为 |
| --- | --- |
| 时机 | 启动后 8 秒查一次（避开展台初始化），之后每 **12 小时**一次；「关于」页的「检查」按钮随时可手动查 |
| 判定 | 读**静态** `releases/latest/download/latest.json`（GitHub CDN，无认证无限流），把版本号与源码 `VERSION` 按 `年.月日.时分` 逐段比较；静态源取不到（首次发版 / 被网络拦截）才退回 REST API |
| 提示 | 只有「确实更新」才弹窗：版本号对比 + 更新说明（过长截断）+ 资产体积，按钮为 **去下载 / 稍后 / 跳过此版本** |
| 下载 | 点「去下载」用系统浏览器打开发布页，**程序不自己替换自身** |
| 静默 | 自动检查失败（断网 / 限流）不弹窗，只在「关于」页留一行可读原因；「已是最新」「本机是开发版」也不弹 |

> **为什么优先静态 `latest.json` 而不是 REST API**：GitHub 匿名 REST 接口是
> **60 次/小时/IP**。这不是理论值——实测时一台机器（同一出口 IP）用完额度后
> 任何匿名请求都返回 `403 API rate limit exceeded`。同事多人共用公司同一个出口
> IP 时，更新检查会在最需要的时候集体失效，而用户只看到「查不到」。静态地址走
> CDN、响应体几百字节、不需要 token，是唯一稳的那条路。CI 每次发版都会把
> `latest.json` 作为 Release 附件上传，内容与 API 返回同构（`version` / `notes` /
> `url` / `assets[]`），两条路共用同一份解析代码。

为什么不自动替换：exe 正在运行时 Windows 不允许覆盖自身，自动更新只有两条路——
写一个 `.bat` 等进程退出后替换（杀毒软件对「脚本延迟改可执行文件」高度敏感，十有八九
被拦），或要求管理员权限（同事机器上等于让程序弹 UAC）。两条都比「让用户点一下下载」
更糟，所以这里只做「发现 + 说清楚」。

三个可配置项（`config.json`，也能在「关于」页勾）：

| 键 | 默认 | 含义 |
| --- | --- | --- |
| `update_check` | `true` | 是否自动检查；关掉后「检查」按钮仍可手动查 |
| `update_feed` | 空 | 留空 = 内置多源（静态 `latest.json` → REST API）。内网部署时填自建的 `version.json` 地址（字段只要 `version` / `notes` / `url`），**填了就只查它**，不会再偷偷去连 GitHub |
| `update_skipped_version` | 空 | 点过「跳过此版本」的版本号；同版本不再自动弹窗，更高版本发布后照常提示 |

> **隐私/安全边界**：打开下载页只放行 http(s) 且主机在 GitHub 域名（或 `update_feed`
> 配置的域名）内的地址。否则一旦更新源被换掉，一条 `http://随便什么域名/b.exe` 就能
> 让程序替用户打开可执行文件下载——那等于把「装什么」的决定权交出去了。

---

## 设计要点与健壮性

- **持久 PowerShell 会话**：`powershell -NoProfile -Command -` 常驻，忠实还原
  electerm 终端语义——`cd`、虚拟环境激活、`$env:PYTHONPATH` 等跨命令状态保留；
  命令零改动，PowerShell 语法原样透传。
- **UI 线程安全**：后台线程只往线程安全的 `backend.bus` push 事件，前端
  `take_events()` 主动拉增量，顺带规避 pywebview `evaluate_js` 跨线程限制。
- **截图链路提速（可感延迟优先）**：截图本身的大头在设备端采集 + USB 传输
  （`exec-out screencap -p` 已是最快路径），PC 侧能抠的是四件事——
  ① `boot()` 后台预热 adb server，冷启的数百毫秒不落在「第一次截图」上；
  ② 剪贴板同步的 PNG 解码（`core/clipboard.py`）可选走 numpy 向量化
  （filter 0/1/2 与 BGR 换位整行/整图完成，1080x2400 快一倍以上；没装 numpy
  自动回退纯 Python，两条路径输出逐字节一致、有对拍测试），且「已保存」反馈
  提前到写盘后立即推送，不再被 1~2 秒的解码阻塞；③ 事件轮询空闲退避只到
  500ms（而非 1s），完成 toast 不迟到；④ 「立即截图」点击即禁用、完成后恢复
  （后端 `shot_state` 在途计数驱动，见下条）。
- **截图在途禁用（按钮态自愈）**：点击「立即截图」后按钮立即禁用——截图耗时
  以秒计，禁用既是"在跑了"的即时反馈，也防连点。后端按 worker 入口/出口维护
  在途计数（`_shot_state_change`，0<->1 翻转才广播 `shot_state`，批量 N 台也
  只有一对 true/false），成败甚至 worker 抛异常都经 `finally` 平衡，按钮不会
  假死；后端直接拒绝（未勾选设备）或桥接异常时前端按调用结果就地恢复。
- **剪贴板写入的三层防线（Windows）**：① ctypes 直投 CF_DIB + CF_PNG，整段
  序列重试 3 轮（远程桌面 / 安全软件 / 剪贴板历史工具对剪贴板的持有都是短暂的）；
  ② 仍败则 PowerShell -STA + .NET `Clipboard.SetImage` 兜底——**图片字节经
  stdin 送进子进程，它完全不碰截图文件**：用户机器上的真实故障是 GDI+
  `FromFile` 抛「内存不足」，根因是刚落盘的 PNG 被反病毒 / 同步工具瞬时独占
  锁住，GDI+ 打不开文件时把所有错误都归成这一句；字节本就在我们内存里
  （`copy_image` 的 raw），管带过去这一类失败从此不存在。兜底也重试 2 轮；
  ③ 兜底脚本把 `[Console]::OutputEncoding` 设为 UTF8、Python 侧再多编码兜底
  解码，中文错误信息不再是「ʱ쳣ڴ治㡣」式乱码。最终失败时原因带两阶段明细
  （直接写入 / 兜底），图片落盘这个主结果永远不受影响。
- **图片字节先归一化再落盘 / 再进剪贴板**（`core/imgbytes.py`）：少数车机 /
  定制 ROM 的 `screencap -p` 会在 PNG 前先吐几行自己的文本，字节流于是
  「开头不是图片签名」。后果有两层且都很难查——落盘的文件看图软件打不开；
  复制到剪贴板时 `raw.startswith(PNG magic)` 为假，ctypes 那条只投
  CF_PNG/CF_DIB 的分支被整段跳过，退到 GDI+ 报一句与真相无关的「参数无效」，
  用户看到的却是「剪贴板被占用，请重试」。现在统一在前 4KB 内按签名定位真实
  起点、PNG 裁到 IEND、JPEG 裁到 EOI；认不出就直说「无法识别」并给出头部
  十六进制。截图落盘走同一条路径，磁盘上的文件因此一定是能打开的图。
- **快捷命令 ⋯ 菜单的层叠与弹出方向**：popup 是 kebab 的子节点，kebab 一带
  z-index 就自成层叠上下文，popup 的 `z-index:20` 只在这一小层里比较、出不来，
  DOM 顺序更靠后的卡片会整块压在菜单上（现场表现是「菜单被下面的按钮压住」）。
  所以展开时把**整张卡片**抬到 30（`.chip-menu-open`），与兄弟顺序无关；
  另外列表住在 `#cmd-groups{overflow:auto}` 里，最后一两行命令的菜单向下弹会
  被容器底边裁掉，故按上下剩余空间决定方向（`.chip-menu-up`）。
- **全局 Toast（完成强提醒）**：关键完成事件（截图 / 录屏 / Logcat 抓取完毕）
  与错误级提示一律弹 toast，切 tab 也不错过；多设备批量不逐台刷屏，由后端
  汇总计数后弹一条（见「界面说明」）。
- **关闭即清理**：窗口关闭时 `WebApi.shutdown()` 幂等收尾——终止 PowerShell 会话、
  停掉 logcat 监控/抓取、录屏与设备音频（含设备端进程），再等待后台线程退出。
- **录屏启动兜底**：启动链路的任何失败都**不会锁死录屏**——麦克风启动失败
  （无麦克风设备 / 被占用）降级为「本次无麦克风录制」并 toast 说明（该路径现在
  只能由 API 直接调用触发，界面上已无麦克风开关）；其它未预期异常由
  `screen_record_start` 统一捕获，自动撤销半启动会话（麦 / 设备音频 /
  同步 logcat / 已启动的录屏）后返回 `start_error`。会话标记只在收尾 `finally`
  里清零，守卫永不残留「已在录制」的假状态（无麦克风机器曾因此永久无法录屏）。
- **录屏进程意外死亡自愈**：录屏中途执行 `adb root` / 设备重启 adbd 会杀掉设备端
  `screenrecord`（本地 adb 客户端随之退出）。`VideoRecorder` 为每场录屏起了个
  watcher 线程标记这种「无人停止却退出」，`controller` 的自动轮询每秒取一次标记，
  命中即走与手动停止相同的完整收尾（优雅停掉其余设备 / 麦 / 设备音频、恢复指针
  位置 / 触摸圆点、合成与打包照常），并广播 `rec_state` 让前端把按钮切回「开始录制」；
  死亡设备的残片不合成音频、源文件保留在保存目录，文案明确「视频不完整」。
  没有这条链路，界面会一直停在「录制中」，用户点停止后才在约 10 秒的 pull
  重试后看到一句「缺 moov 头」。
- **root 切换保护（防断录屏的第一道闸）**：`adb root` / `adb unroot` 会重启
  adbd，是录屏被断的最常见原因。`core/rootguard.py` + `WebApi._skip_root_switch`
  在下发前逐设备判断：① 已在目标状态的重复切换直接跳过（零收益的无谓重启）；
  ② 状态确实要变、但该设备有进行中的录屏 / 设备音频 / logcat 监控抓取时也跳过
  并 toast 说明（多设备只拦有任务的那台，其余照常执行；复合命令
  `adb root && …` 无法只跳一段，整条拦下）；③ 引号内仅「提到」root 的命令
  （`git commit -m "adb root 修复"`）不误伤。
- **录屏可视化增强（系统设置 overlay，与录屏命令彻底解耦）**：指针位置 /
  触摸圆点都通过 `adb shell settings put system pointer_location|show_touches 1`
  打开——它们是屏幕 overlay，会被 screenrecord 原样录进视频，且**全 Android
  版本可用**。早期实现走设备端 `screenrecord --show-pointer`，该参数仅
  Android 10+ 的部分二进制支持，定制 ROM / 云手机 / 模拟器上报的 SDK 与实际
  二进制不一致时会直接 `unrecognized option` 把录屏搞挂（已实测），故彻底改为
  系统设置方案；两个 overlay 的收尾与备份同一套机制——录前读原值备份、开启，停止 /
  启动失败撤销 / 异常撤销三条收尾路径统一恢复（原值为 `null` 走
  `settings delete`，不留用户从未创建的条目）；读不到原值的设备**不恢复**
  （防错优先于功能完整）。
- **输出限流**：指令输出最多 3000 行；logcat 后端缓冲 20000 行、视图 DOM 上限
  3000 行、单次拉取限 2000 行。
- **无线调试的地址校验（安全边界）**：`core/wireless.normalize_endpoint()` 把用户输入
  规范成 `host:port` 才拼进 `adb connect <addr>` 的参数位——主机名走白名单
  （字母/数字/点/横线），带空格、分号、引号的输入直接拒绝。顺手认三种粘贴现实：
  整条 `adb connect 1.2.3.4:5555`、`tcp://…/`、`[fe80::1]:5555`。设备 IP 的挑选顺序是
  「默认路由的 src → 任一网段 src → `ip -4 addr` 的 global」，网卡按 wlan0 > wlan1 >
  其它 wlan* > eth* 排——车机常同时挂着调试 Wi-Fi 与车载以太网，挑错了连的是另一张网。
- **APK 安装的成功判定不看退出码**：`adb install` 失败时也可能返回 0（错误在设备端），
  结论只在输出的 `Success` / `Failure [INSTALL_FAILED_*]` 里；因此解析器只认这两个标记，
  并把 20 多个失败码翻成「下一步做什么」（签名不一致 → 先卸载；版本降级 → 勾 -d；
  ABI 不匹配 → 换包）。`testOnly` 包自动补 `-t` 重试一次——CI 出的调试包默认带这个
  标记，让用户自己看错误码再去查参数是没必要的摩擦。
- **设备信息一次取全**：`getprop` 全量 + `wm size/density` + `dumpsys battery` + `df /data`
  + `/proc/meminfo` + `/proc/uptime` 拼成一条 `adb shell`，用 `@@` 标记分段（逐条调用要
  1~2 秒，点开弹窗先白屏两秒）；解析按「最后一个百分比列」定位 df 的数字列，因此
  1K-blocks 与 `-h` 式 `4.0G` 两种 ROM 输出都能读。容量单位跟着数量级走（剩余几十 MB
  就写 MB，不写「0.0 GB」）——按固定单位四舍五入会让「还有 50 MB」看着像「已经满了」。
- **长任务的互斥放在后端，不靠界面**：`workers.spawn(key)` 遇到同名存活线程会复用而
  不重启，所以「同一批安装在跑时再点一次」必须由 `apk_install()` 直接拒绝（而不是重置
  批次账），否则第二次点击会「假开始」，前一批的结果还会记进后一批。凡是「有会话账」
  的后台动作都按这条处理：**入口互斥 + 事件驱动恢复**，界面禁用只是提示。
- **弱签名要二次校验**：`core/imgbytes` 认格式的签名表里，BMP 只有 `BM` 两个字节——
  前导文本里的 `MB` / `BMW` / base64 都会命中，切出一段「认得出却解不开」的假图片。
  因此 BMP 候选额外过一遍文件头合理性校验（保留字段为 0、DIB 头长度在白名单、偏移与
  大小落在实际字节内）。两字节级的签名都必须这样处理，否则「容忍前导垃圾」本身会变成
  新的故障源。
- **启动前环境预检**：`core/envcheck.py` + `main.py._preflight()` 在建窗**前**检查
  WebView2 / pywebview，缺失弹原生中文提示；**adb 缺失不阻断启动**，以「未配置 adb」
  状态进界面，在「关于」页填入 adb 目录保存后即注入 PATH 生效。
- **全局崩溃兜底**：`sys.excepthook` + `threading.excepthook`，未捕获异常落盘
  `crash_<时间戳>.log` 并弹原生提示；`--windowed` 打包的 exe 崩溃不再「闪一下就没」。

---

## 二次开发

- **改主题**：配色集中在 `frontend/css/app.css` 一个文件（当前为仪器面板主题：
  暗底 `#0b0f14`、磷光青 `#34e0ea`，与 `core/constants.py` 的 `ACCENT` 对应）。
- **加指令**：编辑 `commands.json`（electerm 导出格式）。内置默认命令
  （`core/builtin_commands.py`，通用不依赖个人路径，标签为「内置」）与用户 json
  合并，同名 / 同 `id` 用户命令优先覆盖；带个人路径的项目专属指令仍留在 json 里。
  条目上写 `"inputOnly": true` 即进入 electerm「仅输入」模式：点击只把命令文本
  填进输入框，由用户确认后手动「执行」（防手滑直接跑危险 / 长命令）。
- **加功能**：前端在 `frontend/index.html` + `frontend/js/app.js` 加入口，后端在
  `backend/controller.py` 的 `WebApi` 上暴露动作方法，能力下沉到
  `backend/*_service.py`，耗时操作 `workers.spawn()` 到后台线程、结果走 `bus` 回传；
  `-s` 注入规则集中在 `adb_inject.py`。
- **跑测试**：`tests/test_inject.py` 保证拼接逻辑不回归；`tests/frontend/` 为 jsdom
  前端测试（需 `npm install`，之后 `npm test` 一键跑完，单个文件也可
  `node xxx.test.cjs`）。
