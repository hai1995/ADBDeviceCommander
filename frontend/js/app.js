"use strict";
/* ADB 设备指令台 —— Web 版逻辑（多 tab 版）
   事件桥：boot() 初始化；take_events() 轮询拉增量；各 tab 渲染 + 动作下发。 */
(() => {
  const $ = (id) => document.getElementById(id);
  const els = {
    pill: $("pill"),    btnRefresh: $("btn-refresh"), btnAll: $("btn-all"),
    btnRun: $("btn-run"), btnStop: $("btn-stop"),
    btnClearStatus: $("btn-clear-status"), btnClearConsole: $("btn-clear-console"),
    devCount: $("dev-count"), devCountUnit: $("dev-count-unit"), devList: $("device-list"),
    cmdGroups: $("cmd-groups"),
    cmdFilter: $("cmd-filter"), cmdTags: $("cmd-tags"),
    cmdCount: $("cmd-count"), btnCmdClear: $("btn-cmd-clear"),
    btnCmdInputClear: $("btn-cmd-input-clear"),
    cmdPrompt: $("cmd-prompt"),
    status: $("status"), console: $("console"),
    btnCopyStatus: $("btn-copy-status"),
    // 状态信息：顶栏跑马灯（概览）+ 弹窗（全量历史，#status 就住在弹窗里）
    statusTicker: $("status-ticker"), tickerLed: $("ticker-led"),
    tickerViewport: $("ticker-viewport"), tickerTrack: $("ticker-track"),
    tickerSeqA: $("ticker-seq-a"), tickerSeqB: $("ticker-seq-b"),
    tickerCount: $("ticker-count"),
    statusModal: $("status-modal"), statusModalClose: $("status-modal-close"),
    cmdInput: $("cmd-input"), overlay: $("overlay"),
    keepInput: $("keep-input"),
    tabs: $("tabs"),
    // 主题切换（深 / 浅 / 随系统）：三态分段控件，落盘 config.json 的 theme
    themeSwitch: $("theme-switch"),
    // logcat
    lcStart: $("lc-start"), lcStop: $("lc-stop"),
    lcClear: $("lc-clear"), lcStatus: $("lc-status"),
    lcCounter: $("lc-counter"), lcDev: $("lc-dev"), lcFilter: $("lc-filter"),
    lcPkg: $("lc-pkg"),
    lcPreset: $("lc-preset"), lcPresetSave: $("lc-preset-save"),
    lcPresetDel: $("lc-preset-del"),
    lcLevels: $("lc-levels"), lcOnlyExc: $("lc-only-exc"),
    lcAuto: $("lc-autoscroll"), lcBuf: $("lc-buf"), lcView: $("lc-view"),
    lcCapZipstop: $("lc-cap-zipstop"),
    lcCapStart: $("lc-cap-start"), lcCapStop: $("lc-cap-stop"),
    lcCapStatus: $("lc-cap-status"), lcCapLevels: $("lc-cap-levels"),
    lcDir: $("lc-dir"), lcOpen: $("lc-open"), lcPick: $("lc-pick"),
    // tools
    toolDir: $("tool-dir"), toolOpen: $("tool-open"), toolPick: $("tool-pick"),
    toolShot: $("tool-shot"), shotClipboard: $("shot-clipboard"),
    shotSaveFile: $("shot-save-file"),
    shotPreview: $("shot-preview"), shotPreviewFrame: $("shot-preview-frame"),
    shotPreviewImg: $("shot-preview-img"), shotPreviewGrip: $("shot-preview-grip"),
    shotPreviewLoading: $("shot-preview-loading"),
    shotPreviewLoadingText: $("shot-preview-loading-text"),
    shotPreviewName: $("shot-preview-name"),
    toolRec: $("tool-rec"),
    toolRecStop: $("tool-rec-stop"),
    toolRecCancel: $("tool-rec-cancel"),
    recElapsed: $("rec-elapsed"), recElapsedT: $("rec-elapsed-t"),
    recLogcat: $("rec-logcat"), recMic: $("rec-mic"), recZip: $("rec-zip"),
    recPointerLocation: $("rec-pointer-location"), recShowTouches: $("rec-show-touches"),
    // 应用安装（APK）
    apkPick: $("apk-pick"), apkInstall: $("apk-install"), apkFile: $("apk-file"),
    apkReplace: $("apk-replace"), apkDowngrade: $("apk-downgrade"),
    apkGrant: $("apk-grant"),
    // 诊断包（设备信息 / 日志尾部 / 进程 / 应用 / ANR 一次收齐）
    diagCollect: $("diag-collect"), diagLogcat: $("diag-logcat"),
    diagLines: $("diag-lines"), diagResult: $("diag-result"),
    // 无线调试（Wi-Fi ADB）
    btnWifi: $("btn-wifi"), wifiModal: $("wifi-modal"),
    wifiAddr: $("wifi-addr"), wifiConnect: $("wifi-connect"),
    wifiTcpip: $("wifi-tcpip"), wifiTcpipState: $("wifi-tcpip-state"),
    wifiConnected: $("wifi-connected"), wifiRecent: $("wifi-recent"),
    wifiClose: $("wifi-close"), wifiClose2: $("wifi-close2"),
    // 设备信息
    devinfoModal: $("devinfo-modal"), devinfoTitle: $("devinfo-title"),
    devinfoRows: $("devinfo-rows"), devinfoCopy: $("devinfo-copy"),
    devinfoRefresh: $("devinfo-refresh"),
    devinfoClose: $("devinfo-close"), devinfoClose2: $("devinfo-close2"),
    // 工具区子 tab（截图 / 录屏 / 投屏 / 应用安装 / 诊断包）：每项一个子 tab，
    // 整页展示该项全部功能；顺序可长按拖动调整，落盘 tool_tab_order。
    // 投屏（调用本机 scrcpy）
    toolScrcpy: $("tool-scrcpy"), scrcpyDetect: $("tool-scrcpy-detect"),
    scrcpyPath: $("scrcpy-path"), scrcpyState: $("scrcpy-state"),
    // 备用投屏（没装 scrcpy 时的 screenrecord 管道 / 低帧率预览）
    toolMirror: $("tool-mirror"), toolMirrorStop: $("tool-mirror-stop"),
    mirrorState: $("mirror-state"), mirrorPreview: $("mirror-preview"),
    mirrorView: $("mirror-view"), mirrorSize: $("mirror-size"),
    mirrorFrame: $("mirror-frame"), mirrorGrip: $("mirror-grip"),
    mirrorBitrate: $("mirror-bitrate"), mirrorFps: $("mirror-fps"),
    mirrorPlayerPath: $("mirror-player-path"),
    // 性能监控
    perfDev: $("perf-dev"), perfInterval: $("perf-interval"),
    // 目标应用选择器（下拉 + 模糊搜索）：按钮显示当前选择，弹层里搜索 / 挑选
    perfPkgBtn: $("perf-pkg"), perfPkgLabel: $("perf-pkg-label"),
    perfPkgPop: $("perf-pkg-pop"), perfPkgSearch: $("perf-pkg-search"),
    perfPkgList: $("perf-pkg-list"), perfPkgModes: $("perf-pkg-modes"),
    perfPkgAll: $("perf-pkg-all"), perfPkgCount: $("perf-pkg-count"),
    perfPkgRefresh: $("perf-pkg-refresh"),
    perfStart: $("perf-start"), perfStop: $("perf-stop"), perfExport: $("perf-export"),
    perfView: $("perf-view"),
    perfState: $("perf-state"), perfStats: $("perf-stats"),
    perfCanvas: $("perf-canvas"), perfEmpty: $("perf-empty"),
    perfTip: $("perf-tip"), perfCross: $("perf-cross"),
    perfBand: $("perf-band"), perfRange: $("perf-range"),
    perfLegend: $("perf-legend"),
    perfChartTitle: $("perf-chart-title"), perfChartSub: $("perf-chart-sub"),
    perfThBtn: $("perf-th"), perfThModal: $("perf-th-modal"),
    perfThRows: $("perf-th-rows"), perfThErr: $("perf-th-err"),
    perfThSave: $("perf-th-save"), perfThCancel: $("perf-th-cancel"),
    perfThClose: $("perf-th-close"), perfThReset: $("perf-th-reset"),
    // files
    fileDevNow: $("file-dev-now"), filePath: $("file-path"), fileUp: $("file-up"),
    fileRefresh: $("file-refresh"), fileMkdir: $("file-mkdir"),
    fileTouch: $("file-touch"), fileUpload: $("file-upload"),
    fileUploadBtn: $("file-upload-btn"),
    fileBody: $("file-body"),
    fileDir: $("file-dir"), fileOpen: $("file-open"), filePick: $("file-pick"),
    fileSelAll: $("file-sel-all"), fileBatchDl: $("file-batch-dl"),
    fileBatchDel: $("file-batch-del"), fileSelCount: $("file-sel-count"),
    fileTableWrap: $("file-table-wrap"), fileDropOverlay: $("file-drop-overlay"),
    // about
    aboutVer: $("about-ver"), aboutAdb: $("about-adb"),
    aboutCmd: $("about-cmd"), aboutDev: $("about-dev"), aboutWarn: $("about-warn"),
    aboutAdbDir: $("about-adb-dir"), aboutAdbSave: $("about-adb-save"),
    aboutCmdTimeout: $("about-cmd-timeout"),
    aboutConfigPath: $("about-config-path"),
    // 版本更新：关于页一行（自动检查 + 上次结果 + 手动检查）+ 新版本弹窗
    aboutUpdateAuto: $("about-update-auto"),
    aboutUpdateState: $("about-update-state"),
    aboutUpdateCheck: $("about-update-check"),
    updateModal: $("update-modal"), updateTitle: $("update-title"),
    updateCurrent: $("update-current"), updateLatest: $("update-latest"),
    updateSize: $("update-size"), updateNotes: $("update-notes"),
    updateHint: $("update-hint"), updateClose: $("update-close"),
    updateSkip: $("update-skip"), updateLater: $("update-later"),
    updateDownload: $("update-download"),
    aboutConfigOpen: $("about-config-open"),
    aboutManual: $("about-manual"),
    aboutSubtabs: Array.from(document.querySelectorAll(".about-subtab")),
    aboutPanes: Array.from(document.querySelectorAll(".about-pane")),
    // modal
    modal: $("modal"), modalTitle: $("modal-title"),
    modalBody: $("modal-body"), modalClose: $("modal-close"),
    modalOpenLocal: $("modal-open-local"),
    // 二次确认弹窗（应用内自绘，见 askConfirm）
    confirmModal: $("confirm-modal"), confirmTitle: $("confirm-title"),
    confirmText: $("confirm-text"), confirmYes: $("confirm-yes"),
    confirmNo: $("confirm-no"), confirmX: $("confirm-x"),
    // 输入弹窗（应用内自绘，见 askInput）
    inputModal: $("input-modal"), inputTitle: $("input-title"),
    inputLabel: $("input-label"), inputField: $("input-field"),
    inputHint: $("input-hint"), inputYes: $("input-yes"),
    inputNo: $("input-no"), inputX: $("input-x"),
    // 关键告警弹窗（不点「我知道了」不消失，见 showAlert）
    alertModal: $("alert-modal"), alertTitle: $("alert-title"),
    alertBody: $("alert-body"), alertHint: $("alert-hint"),
    alertOk: $("alert-ok"), alertX: $("alert-x"), alertMore: $("alert-more"),
    // 命令编辑弹窗
    cmdEdit: $("cmd-edit-modal"),
    cmdEditModal: $("cmd-edit-modal"), cmdEditTitle: $("cmd-edit-title"),
    cmdEditName: $("cmd-edit-name"), cmdEditLabels: $("cmd-edit-labels"),
    cmdEditCmds: $("cmd-edit-cmds"), cmdEditInputOnly: $("cmd-edit-inputonly"),
    cmdEditSave: $("cmd-edit-save"), cmdEditCancel: $("cmd-edit-cancel"),
    cmdEditClose: $("cmd-edit-close"), cmdEditDelete: $("cmd-edit-delete"),
    cmdNew: $("btn-cmd-new"),
    // 指令台工作区（子 tab）：tab 条 / 新建按钮 / 提示语
    wsTabs: $("ws-tabs"), btnWsAdd: $("btn-ws-add"), wsHint: $("ws-hint"),
    cmdImport: $("btn-cmd-import"), cmdImportFile: $("cmd-import-file"),
    cmdExport: $("btn-cmd-export"),
    cmdExportModal: $("cmd-export-modal"), cmdExportText: $("cmd-export-text"),
    cmdExportCopy: $("cmd-export-copy"), cmdExportSave: $("cmd-export-save"),
    cmdExportClose: $("cmd-export-close"), cmdExportClose2: $("cmd-export-close2"),
    // 可拖动分隔条（设备栏 / 指令台 ↔ 指令输出）
    sidebarSplitter: $("sidebar-splitter"), deviceSidebar: $("device-sidebar"),
    sidebarCollapseBtn: $("btn-sidebar-collapse"),
    // toast
    toastWrap: $("toast-wrap"),
  };

  // 设备状态中文说明。默认表是启动瞬间的兜底；booted 后由后端下发
  // state_labels 覆盖（单一数据源，见 core/constants.STATE_LABEL）。
  let stateLabels = {
    device: "在线", unauthorized: "未授权", offline: "离线",
    recovery: "Recovery", sideload: "Sideload", "no permissions": "无权限",
  };
  const LV_DESC = { V: "详细", D: "调试", I: "信息", W: "警告", E: "错误", F: "致命" };
  const CONSOLE_MAX_LINES = 3000;
  const LC_MAX_LINES = 20000;       // 单设备 logcat 缓冲上限（环形）
  const LC_RENDER_CAP = 3000;       // 全量重建（过滤变更/切设备）时最多渲染行数
  const LC_VIEW_MAX = 3000;         // 视图内最多保留的 DOM 行节点数（超出从头部裁剪）
  const LC_PER_FRAME = 300;         // 分帧渲染：每帧最多插入的 DOM 行数
  const LC_QUEUE_MAX = 20000;       // 待渲染队列上限（超出丢弃最旧，防积压爆炸）
  const LC_DEBOUNCE_MS = 250;       // 关键字过滤防抖（与 core/constants 同值）

  let api = null;
  let devices = [];
  let booted = false;
  let lcSerial = null;              // 当前 logcat 监控设备
  let lcRunning = false;            // 是否正在监控（监控中不自动切设备）
  // 丢弃开关：点了停止（或设备被移除强停）后，总线上还在途的 append 事件
  // 属于已结束的会话——不入队、不缓冲。没有它，「点了停止，界面还滚滚地
  // 刷好几秒」（待渲染队列深时上游行全在排队）；清了队列还要拦住后续在途
  // 行，停止才是真的即时。
  let lcDropping = false;
  let lcBuffers = {};               // serial -> {lines:[], total, exc}
  let lcCapRunning = false;      // 抓取是否进行中（控制抓取开始/停止按钮态）
  let shotInFlight = false;      // 截图是否在途（后端 shot_state 驱动，锁「立即截图」）
  let lcFilterTimer = null;      // 关键字过滤防抖定时器
  let lcFilterHits = null;       // 当前关键字在缓冲里命中的行数（null = 未过滤/未知）
  let lcCapSerial = null;        // 正在抓取的设备（与 lcSerial 解耦：抓取期间
                                 // 改勾选不会停错设备，也不会停不下来）
  let fileSerial = null;            // 当前文件浏览设备
  let filePath = "/";
  let fileAnchor = null;            // 批量选择的锚点（Shift 区间选择的起点，值为复选框 value）
  let modalLocalPath = null;        // 查看弹窗里已拉取到本地的文件路径（「查看」按钮用）
  let allCommands = [];             // 全量快捷命令（供筛选/标签过滤使用）
  let mirrorFrameUrl = "";          // 低帧率预览的帧地址（非空 = 预览在跑）
  let mirrorTimer = null;           // 低帧率预览的刷新定时器

  /* 指令台历史（跨工作区共享、落盘）。
     用一个环形数组：每次执行成功 push 新命令，同一命令紧跟重复执行不重复入队
     （翻 ↑ 时看到的是「上次真敲过的那一条」，不是一堆一模一样的 adb devices）。
     持久化键 cmd_history，启动恢复时截到最后 N 条。
     每个工作区各自记 _histIdx（翻 ↑↓ 的当前位置）与 _histDraft（翻之前编辑中的
     原样）——不共享这俩状态，否则 w1 翻到第 3 条切到 w2 也会继承它的位置。 */
  const CMD_HIST_MAX = 200;
  let cmdHistory = [];
  let cmdHistoryLoaded = false;
  function _loadCmdHistory(s) {
    if (cmdHistoryLoaded) return;
    cmdHistoryLoaded = true;
    // 启动时从 booted.settings.cmd_history 读（config.json 落盘，下次启动恢复）。
    // 用 Array.isArray 兼容未来可能升级成数组（现在是 JSON 字符串也 parse）。
    try {
      if (Array.isArray(s)) cmdHistory = s.slice(-CMD_HIST_MAX);
      else if (typeof s === "string" && s.trim()) {
        const arr = JSON.parse(s);
        if (Array.isArray(arr)) cmdHistory = arr.slice(-CMD_HIST_MAX);
      }
    } catch (e) {}
  }
  function _pushCmdHistory(text) {
    text = (text || "").trim();
    if (!text) return;
    const last = cmdHistory[cmdHistory.length - 1];
    if (last === text) return;                 // 紧邻重复不重复入队
    cmdHistory.push(text);
    if (cmdHistory.length > CMD_HIST_MAX)
      cmdHistory.splice(0, cmdHistory.length - CMD_HIST_MAX);
    // 节流落盘：翻历史时不会持续持久化，只有 Enter 执行时才走到这里
    try { persistPref("cmd_history", JSON.stringify(cmdHistory)); } catch (e) {}
  }
  // 预注册一批常见 adb 命令作为 Tab 补全候选（第一词补全用）。
  // allCommands 里是用户的卡片命令，而 adb / powershell 原生命令不属于
  // 那一类——Tab 补全第一词时应该都列出来。
  const BUILTIN_CMD_FIRST_WORDS = [
    "adb","Get-Location","Set-Location","Get-ChildItem","Get-Process","Get-Service",
    "Stop-Process","Stop-Service","Start-Service","Get-NetAdapter","Get-NetIPAddress",
    "Select-String","Get-Content","Get-ItemProperty","Set-ItemProperty",
    "Get-WmiObject","Get-CimInstance","Invoke-WebRequest","curl","dir","ls","pwd",
    "Get-History","Clear-History","Remove-Item","Copy-Item","Move-Item","New-Item",
    "Get-Volume","Get-Disk","ipconfig","netstat","tasklist","taskkill","ping"
  ];

  // 主 tab（设备指令 / 工具 / 性能监控 / Logcat / 文件 / 关于）当前停留项。
  // 落盘 main_active_tab，下次启动由 restoreMainTab 恢复（与工具区子 tab 同一套约定）。
  let mainActiveTab = "cmd";

  /* ---------------- 指令台工作区（子 tab / 多开） ----------------
     每个工作区是一套完整的「指令台 + 指令输出」，后端各自一条独立会话，
     所以能真的同时跑；指令库（命令本身）仍全局共享一份 —— 多开是为了并行
     做事，不是养多份互相不知道对方存在的命令表。

     实现要点：默认工作区（w1）的元素就是 index.html 里原有的那批（id 不变，
     既有页面与测试全都按 id 找它）。新建的工作区靠**克隆 w1 的面板**得到，
     克隆体把每个 [id] 改成 data-role —— 同一份文档里不能有重复 id，而
     CSS/查询又需要认得出「这里是输出区」。取元素统一走 wsRole()，两边的
     写法因此一致。 */
  const WS_MAX = 8;                 // 工作区上限（后端 WS_MAX 同值，双保险）
  const WS_NAME_MAX = 24;           // 工作区名长度上限（与后端 ws_open 的截断一致）
  const wsMap = new Map();          // id -> 工作区对象
  let wsActive = "w1";              // 当前显示的工作区
  let wsRestoring = false;          // 启动恢复布局期间：不要回写 cmd_active_ws
  let wsSeq = 1;                    // 新建时用的序号（w2、w3…），不复用已关闭的
  let wsRenaming = null;            // 正在重命名的工作区 id（渲染让路，见 renderWsTabs）
  let wsRenameReplay = false;       // 重命名期间被跳过的渲染，结束后补一次
  // 指令台左栏收起态（38px 窄轨 + 展开按钮）。偏好是全局的（config.json 里只有
  // 一个 cmd_panel_collapsed），启动恢复与新建工作区都套同一份；每块面板收起前
  // 的内联宽度各自记在自己的工作区对象上（只有被分隔条拖过才存在）。
  let cmdPanelCollapsed = false;

  function wsRole(root, role) {
    if (!root) return null;
    return root.querySelector('[data-role="' + role + '"]')
      || root.querySelector("#" + role);
  }

  function wsOf(id) {
    return wsMap.get(id) || wsMap.get("w1") || null;
  }

  /* 事件分流用**严格**查找：后端事件里的 ws 可能指向一个刚被关掉的工作区
     （关闭时先 stop_run，kill 生效前会话仍可能吐出最后几行输出，或有一条在途
     的 stop_state）。若这里像 wsOf 那样回落到 w1，这些输出会被写进默认工作区的
     面板、stop_state 还会把 w1 的「停止」按钮态改成别人的状态 —— 用户看到的
     正是「关掉的工作区把内容倒进了工作区 1」。closeWorkspace 对用户的承诺是
     「其中的输出一并丢弃」，故找不到就丢弃，不回落。 */
  function wsEventTarget(id) {
    return wsMap.get(id || "w1") || null;
  }

  function curWs() {
    return wsOf(wsActive);
  }

  /* ---------------- 按钮图标（统一内联 SVG，跟随 currentColor 适配主题） ----------------
     图标集中在此一处定义，HTML 上只需给按钮加 data-icon="名字"，脚本启动时注入；
     好处：几十个按钮不必各写一大段内联 SVG，线条风格（24 网格 / 2px 描边 / 圆角端点）
     统一，也方便随时增删。目录 / 文件表格里动态生成的按钮走 mkAct(text, act, icon)
     复用同一套图标（点击由 #file-body 的事件委托统一处理，不再逐行挂监听）。 */
  const BTN_ICONS = {
    "select-all": '<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
    "refresh": '<path d="M23 4v6h-6"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>',
    "plus": '<path d="M12 5v14"/><path d="M5 12h14"/>',
    "trash": '<path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/>',
    "play": '<path d="M7 4l13 8-13 8z"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="1.5"/>',
    "folder": '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
    "folder-plus": '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/><path d="M12 11v6"/><path d="M9 14h6"/>',
    "file-plus": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M12 12v6"/><path d="M9 15h6"/>',
    "camera": '<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/>',
    "record": '<circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2.3" fill="currentColor" stroke="none"/>',
    "monitor": '<rect x="2" y="4" width="20" height="13" rx="2"/><path d="M8 21h8"/><path d="M12 17v4"/>',
    "pulse": '<path d="M2 12h4l3-8 4 16 3-8h6"/>',
    "report": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M8 17v-3"/><path d="M12 17v-6"/><path d="M16 17v-4"/>',
    "sliders": '<path d="M4 6h9"/><path d="M19 6h1"/><circle cx="16" cy="6" r="2.2"/><path d="M4 12h3"/><path d="M13 12h7"/><circle cx="10" cy="12" r="2.2"/><path d="M4 18h9"/><path d="M19 18h1"/><circle cx="16" cy="18" r="2.2"/>',
    "arrow-up": '<path d="M12 19V5"/><path d="M5 12l7-7 7 7"/>',
    // 返回上级（corner-up-left）：上一步/回退到父目录
    "corner-up-left": '<polyline points="9 14 4 9 9 4"/><path d="M20 20v-7a4 4 0 0 0-4-4H4"/>',
    // 使用说明（book / 手册）
    "book": '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
    "upload": '<path d="M12 15V4"/><path d="M7 9l5-5 5 5"/><path d="M5 20h14"/>',
    "download": '<path d="M12 4v11"/><path d="M7 11l5 5 5-5"/><path d="M5 20h14"/>',
    "eye": '<path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"/><circle cx="12" cy="12" r="3"/>',
    "edit": '<path d="M17 3a2.83 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5z"/>',
    "save": '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><path d="M17 21v-8H7v8"/><path d="M7 3v5h8"/>',
    "copy": '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    // 无线调试（Wi-Fi ADB）：扇形信号 + 中心点
    "wifi": '<path d="M2 8.5a15 15 0 0 1 20 0"/><path d="M5.5 12.5a10 10 0 0 1 13 0"/><path d="M9 16.5a5 5 0 0 1 6 0"/><circle cx="12" cy="20" r="1"/>',
    // 应用安装包：盒子 + 向下的箭头
    "package": '<path d="M21 8l-9-5-9 5v8l9 5 9-5z"/><path d="M3 8l9 5 9-5"/><path d="M12 13v8"/>',
    "x": '<path d="M18 6L6 18"/><path d="M6 6l12 12"/>',
    // 指令台收起 / 展开（窄轨里的那一个可点目标）：必须存在于图标表里，
    // 否则 data-icon 注入时取不到图形，按钮就是一个看不见的空壳
    "caret-left": '<path d="M15 5l-7 7 7 7"/>',
    "caret-right": '<path d="M9 5l7 7-7 7"/>',
  };
  const SVG_NS = "http://www.w3.org/2000/svg";
  function makeIcon(name) {
    const inner = BTN_ICONS[name];
    if (!inner) return null;
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("class", "btn-ic");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    svg.innerHTML = inner;   // 图标串为本文件内定义的静态可信内容
    return svg;
  }
  /* 给带 data-icon 的按钮注入图标（幂等；已有内联 svg 的按钮跳过，避免出现双图标）。
     插入到 firstChild 之前，标签文字作为后续文本节点保留，textContent 不变。 */
  function decorateIcons(root) {
    (root || document).querySelectorAll("[data-icon]").forEach((el) => {
      if (el.dataset.iconDone === "1") return;
      el.dataset.iconDone = "1";
      if (el.querySelector("svg")) return;
      const svg = makeIcon(el.dataset.icon);
      if (svg) el.insertBefore(svg, el.firstChild);
    });
  }

  /* ---------------- 通用工具 ---------------- */
  function setPill(text, cls) {
    els.pill.textContent = text;
    els.pill.className = "pill" + (cls ? " " + cls : "");
  }
  // 指令输出 / 状态区：高频输出（大段命令回显、状态流）时，把行压入队列、下一帧
  // 一次性用 DocumentFragment 插入，只在末尾读一次 scrollHeight——避免逐行 appendChild
  // + 每行强制重排（logcat 区已用同样手法规避，这里对齐）。各容器独立队列。
  const _outQueues = new Map();   // container -> [{text, cls, forceScroll}]
  let _outFrame = null;

  function _flushOut() {
    _outFrame = null;
    for (const [container, items] of _outQueues) {
      _outQueues.delete(container);
      if (!items.length) continue;
      // 同一容器语义一致（状态区不强制跟随 / 指令输出区始终滚到底），any 即为强制
      const forceScroll = items.some((it) => it.forceScroll);
      // 插入前判定是否接近底部：非强制区仅在用户已贴近底部时才跟随，不打扰回看历史
      const nearBottom = container.scrollTop + container.clientHeight >= container.scrollHeight - 24;
      const frag = document.createDocumentFragment();
      for (const it of items) {
        const div = document.createElement("div");
        div.className = "line" + (it.cls ? " " + it.cls : "");
        div.textContent = it.text;
        frag.appendChild(div);
      }
      container.appendChild(frag);
      trimHead(container, CONSOLE_MAX_LINES);
      if (forceScroll || nearBottom) container.scrollTop = container.scrollHeight;
    }
  }

  function pushLine(container, text, cls, forceScroll) {
    let q = _outQueues.get(container);
    if (!q) { q = []; _outQueues.set(container, q); }
    q.push({ text, cls, forceScroll: !!forceScroll });
    // 队列上限 = 容器最终保留的行数：多出来的行无论插不插进去都会被 trimHead 裁掉，
    // 插了纯属白干。没有这道限流时，窗口最小化期间 WebView2 会节流
    // requestAnimationFrame，而 400ms 的事件轮询照常把行压进队列 —— 恢复窗口的
    // 那一帧要一次性创建并插入几万个 DOM 节点（随后又删掉绝大多数），形成一次数秒的
    // 同步长任务，界面直接卡住。只保留最新的一批即可，可见结果完全不变。
    if (q.length > CONSOLE_MAX_LINES) q.splice(0, q.length - CONSOLE_MAX_LINES);
    if (_outFrame === null) {
      if (window.requestAnimationFrame) _outFrame = window.requestAnimationFrame(_flushOut);
      else _outFrame = setTimeout(_flushOut, 16);
    }
  }

  // 清空某容器：DOM 与待渲染队列一起清，供 clear 事件 / 列表重渲前调用，
  // 否则上一批尚未 flush 的队列会在清空后又把旧行插回来。
  function clearOut(container) {
    _outQueues.delete(container);
    container.innerHTML = "";
  }

  /** 把后端 ShellSession.current_dir 转成 cmd 风格 prompt：
   *  - Windows 路径（盘符开头）→ "PS D:\Foo\Bar>"
   *  - Unix 路径（/ 开头）→ "$ /home/user>"
   *  - 其他/空 → ">"
   *  路径过长时保持原样（CSS 里 max-width + text-overflow 处理省略）。 */
  function formatPrompt(cwd) {
    if (!cwd) return ">";
    cwd = String(cwd).trim();
    if (!cwd) return ">";
    if (/^[A-Za-z]:[\\/]/.test(cwd)) return "PS " + cwd + ">";   // Windows 盘符
    if (cwd.startsWith("/")) return "$ " + cwd + ">";            // Unix
    return cwd + ">";
  }

  /* 一次性裁剪容器头部超出的行。
     逐行 removeChild 每删一行触发一次重排：日志/输出密集时（一次 flush 插入
     几百行、同时裁掉几百行）足以造成可感卡顿。用 Range 把待删区间一次删掉，
     把 N 次重排压成 1 次。返回实际删除的行数。 */
  function trimHead(container, maxLines) {
    const over = container.childElementCount - maxLines;
    if (over <= 0) return 0;
    const last = container.children[over - 1];   // 待删区间 = [0, over-1]
    if (!last) {
      const n = container.childElementCount;
      container.textContent = "";
      return n;
    }
    const range = document.createRange();
    range.setStartBefore(container.firstElementChild);
    range.setEndAfter(last);
    range.deleteContents();
    return over;
  }
  const pushStatus = (type, text, opts) => {
    // 状态信息只有一处 DOM（弹窗里的 #status）；顶栏跑马灯是它的概览投影。
    const cls = type === "err" ? "err" : type === "warn" ? "warn"
             : type === "ok" ? "ok" : type === "info" ? "info" : "dim";
    pushLine(els.status, text, cls);
    pushTicker(text, cls);
    // 高优先级提示语：错误级一律弹 toast；后端显式 toast 标记的警告也弹
    if (type === "err" || (opts && opts.toast)) showToast(type, text);
    // 关键告警：**不点就不消失**的弹窗。与 toast 并存 —— toast 负责「此刻在看屏幕」
    // 的那部分注意力，弹窗负责「人不在、或正在别处点」的那部分。少任何一层都会
    // 重演「录屏好好的、日志少了 24 分钟却没人知道」。
    if (opts && opts.alert) {
      showAlert({ title: opts.alertTitle || "", items: [{ level: type, text: text }] });
    }
  };

  /* ---------------- 顶栏状态跑马灯（全局运行信息概览） ----------------
     状态行有两个去处：弹窗里的 #status（全量、可框选复制，唯一 DOM）与这里的
     跑马灯（最近几条的横向滚动概览）。DOM 由 pushLine 批量插入，跑马灯另用
     一个轻量数组镜像 —— 它只需要「最近几行 + 最新一条的语义色」，没必要从
     DOM 里回读，更不能让每次 flush 都重排一遍 DOM。 */
  const TICKER_LINES = 6;         // 跑马灯最多带几条（多了滚太快，读不清）
  const TICKER_MS = 220;          // 刷新节流：一批命令回显可能瞬间几十行
  const statusLog = [];           // {text, cls} 镜像，与 #status 的行上限一致
  let _tickerTimer = null;

  function pushTicker(text, cls) {
    statusLog.push({ text: text, cls: cls });
    // 上限与 DOM 侧 CONSOLE_MAX_LINES 一致：跑马灯只是镜像，不做第二套裁剪口径
    if (statusLog.length > CONSOLE_MAX_LINES)
      statusLog.splice(0, statusLog.length - CONSOLE_MAX_LINES);
    if (_tickerTimer !== null) return;
    _tickerTimer = setTimeout(() => { _tickerTimer = null; renderTicker(); }, TICKER_MS);
  }

  function clearStatus() {
    clearOut(els.status);
    statusLog.length = 0;
    renderTicker();
  }

  function fillTickerSeq(node, items) {
    node.textContent = "";
    items.forEach((it, i) => {
      if (i) {
        const sep = document.createElement("span");
        sep.className = "tk-sep";
        sep.textContent = "·";
        node.appendChild(sep);
      }
      const s = document.createElement("span");
      s.className = "tk " + (it.cls || "");
      s.textContent = it.text;
      node.appendChild(s);
    });
  }

  function renderTicker() {
    if (!els.statusTicker || !els.tickerSeqA) return;
    const items = statusLog.length
      ? statusLog.slice(-TICKER_LINES)
      : [{ cls: "dim", text: "暂无状态 · 点击查看完整信息" }];
    fillTickerSeq(els.tickerSeqA, items);
    fillTickerSeq(els.tickerSeqB, items);       // 第二份同内容：左移 50% 无缝接上
    const last = statusLog.length ? items[items.length - 1] : null;
    els.tickerLed.className = "ticker-led" + (last && last.cls !== "dim" ? " " + last.cls : "");
    els.tickerCount.textContent = String(statusLog.length);
    els.statusTicker.title = last && statusLog.length
      ? "点击查看完整状态信息（最新：" + last.text + "）" : "点击查看完整状态信息";
    // 只有内容宽于视口才滚动（jsdom 无布局，实测宽度恒为 0 → 不加 .rolling）
    const need = els.tickerSeqA.offsetWidth > els.tickerViewport.clientWidth;
    els.statusTicker.classList.toggle("rolling", need);
    if (need) {
      // 滚动时长按内容长度给（约 46px/s，太快看不清、太慢要等），下限 14s
      els.statusTicker.style.setProperty(
        "--tk-dur", Math.max(14, (els.tickerSeqA.offsetWidth || 0) / 46) + "s");
      // 重启动画：内容变长后若从原进度续走，新行会有一段时间看不见
      els.tickerTrack.style.animation = "none";
      void els.tickerTrack.offsetWidth;        // 强制重排让 animation 重置生效
      els.tickerTrack.style.animation = "";
    }
  }

  /* ---------------- 状态信息弹窗（跑马灯点击展开） ----------------
     #status 一直住在弹窗里，关闭只是整块随弹窗隐藏 —— 不做「搬进搬出」的 DOM
     搬家，避免搬动过程中丢失选区或打断未落地的渲染队列。 */
  function openStatusModal() {
    if (!els.statusModal) return;
    els.statusModal.classList.remove("hidden");
    els.status.scrollTop = els.status.scrollHeight;   // 打开即看最新
    if (els.statusModalClose) els.statusModalClose.focus();
  }
  function closeStatusModal() {
    if (els.statusModal) els.statusModal.classList.add("hidden");
  }
  // 指令输出区：任何新内容都默认滚动到底部（forceScroll=true）
  // kind 决定配色：cmd 是用户下的命令（accent），err 是报错，info 是程序在命令流
  // 里的说明（比如「已进入交互式子 shell」）。除这三种以外统统按普通输出渲染。
  const CONSOLE_KINDS = { cmd: "cmd", err: "err", info: "info", ok: "ok", warn: "warn" };
  // 输出按工作区分流：事件的 ws 指向哪块面板就写哪块。默认工作区不带 ws 字段
  // （后端单工作区时代的载荷一字不差），故 p.ws || "w1"。
  const pushConsole = (kind, text, wsId) => {
    const ws = wsOf(wsId);
    if (!ws || !ws.consoleEl) return;
    pushLine(ws.consoleEl, text, CONSOLE_KINDS[kind] || "", true);
  };

  /* ---------------- Toast（高优先级提示弹窗） ----------------
     触发规则（在 pushStatus 中统一判定）：
       * type === 'err'   —— 所有错误级提示自动弹 toast（截图失败 / 录屏失败 /
         下载失败 / 命令未找到 …），与用户给的「⚠ 截图失败 …」示例一致；
       * 后端显式 toast 标记 —— 部分「关键但非错误」的警告（如麦克风启动失败、
         设备音频采集失败、录屏收尾失败）也弹 toast 强提醒。
     弹窗与状态信息并存：toast 负责即时强提醒（切 tab 也能看到），状态信息负责
     常驻可回看（顶栏跑马灯 + 点击弹窗）。纯 DOM/CSS/JS，兼容 pywebview。 */
  const TOAST_MAX = 4;                       // 同屏最多可见条数，超出淘汰最旧
  const TOAST_MS = { err: 8000, warn: 6000, ok: 4000, info: 4000 };

  function showToast(type, text) {
    if (!els.toastWrap) return;
    const ms = TOAST_MS[type] || 5000;
    const el = document.createElement("div");
    el.className = "toast toast--" + (type || "info");
    el.setAttribute("role", "alert");

    const body = document.createElement("div");
    body.className = "toast-body";
    body.textContent = text || "";

    const close = document.createElement("button");
    close.className = "toast-close";
    close.type = "button";
    close.setAttribute("aria-label", "关闭");
    close.textContent = "×";

    const bar = document.createElement("div");
    bar.className = "toast-bar";

    el.appendChild(close);
    el.appendChild(body);
    el.appendChild(bar);

    // 点击 toast 本体关闭；但用户在复制文本（有选区）时不误关
    el.addEventListener("click", () => {
      const sel = window.getSelection && window.getSelection();
      if (sel && String(sel)) return;
      dismissToast(el);
    });
    close.addEventListener("click", (e) => { e.stopPropagation(); dismissToast(el); });

    els.toastWrap.appendChild(el);
    // 倒计时进度条：宽度从 100% 收缩到 0
    if (window.requestAnimationFrame) {
      requestAnimationFrame(() => {
        bar.style.transition = "width " + ms + "ms linear";
        bar.style.width = "0%";
      });
    } else {
      bar.style.width = "0%";
    }
    // 超出同屏上限时淘汰最旧（避免叠加过多）。
    // 必须保证每轮循环都真的移除一个节点：dismissToast 对「正在退场动画中」的
    // 节点旧实现会直接 return，childElementCount 不变 → 这里的 while 变成死循环，
    // JS 线程被占满、定时器再也无法触发，整个窗口就此永久卡死。
    while (els.toastWrap.childElementCount > TOAST_MAX) {
      const oldest = els.toastWrap.firstElementChild;
      if (!oldest || oldest === el) break;
      dismissToast(oldest, true);
      if (oldest.isConnected) oldest.remove();   // 兜底：确保循环一定推进
    }
    const timer = setTimeout(() => dismissToast(el), ms);
    el._toastTimer = timer;
  }

  function dismissToast(el, immediate) {
    if (!el) return;
    if (el._toastGone) {
      // 已经处于退场流程（动画 / 兜底计时器还没到点）：这里必须直接把节点摘掉。
      // 旧实现直接 return，调用方（超限淘汰循环）会因此永远无法推进 → 界面卡死。
      el.remove();
      return;
    }
    el._toastGone = true;
    if (el._toastTimer) clearTimeout(el._toastTimer);
    const reduce = window.matchMedia
      && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (immediate || reduce) { el.remove(); return; }
    el.classList.add("toast--out");
    el.addEventListener("transitionend", () => el.remove(), { once: true });
    setTimeout(() => el.remove(), 400);   // transitionend 兜底
  }


  /* ---------------- 受控设备（统一来源） ----------------
     左侧已勾选的在线设备 = 受控设备列表。
     · 多设备功能（设备指令/工具）：对全部受控设备广播。
     · 单设备功能（文件/Logcat）：取其中第一个作为当前活跃设备，并随勾选自动联动。
     所有 tab 共用同一份过滤逻辑，保证行为一致。 */
  function checkedDevices() { return devices.filter((d) => d.ok && d.checked); }
  function firstChecked() { const d = checkedDevices()[0]; return d ? d.serial : null; }

  /* 全局 API 调用超时（秒）。pywebview bridge 不一定支持 AbortController，
     这里用 Promise.race 实现——超时后前端不再 await，按钮/等待态立即恢复；
     后端请求仍可能在跑（对于 refresh 等后台操作，后端会通过事件总线推送
     结果，不受超时影响）。某些长操作应显式传 timeout=0 禁用超时：
     · take_events —— 只是从 deque 取事件，正常情况下微秒级返回；
     · screen_record_stop / screen_record_cancel —— 收尾链路（拉视频 /
       ffmpeg 合并 / 打包）远超 15 秒，超时只会制造「假失败 + 真成功」并存的
       报错，还会提前解锁按钮；后端各步有界、promise 必然落定，不怕等。 */
  const API_TIMEOUT_S = 15;

  async function callApi(promise, timeout = API_TIMEOUT_S) {
    if (timeout === 0) {
      try { return await promise; }
      catch (e) {
        pushStatus("err", "调用后端失败：" + (e && e.message ? e.message : e));
        return null;
      }
    }
    let timer;
    const timeoutPromise = new Promise((_, rej) => {
      timer = setTimeout(() => rej(new Error(`请求超时（${timeout}s）`)), timeout * 1000);
    });
    try {
      return await Promise.race([promise, timeoutPromise]);
    } catch (e) {
      pushStatus("err", "调用后端失败：" + (e && e.message ? e.message : e));
      return null;
    } finally {
      clearTimeout(timer);
    }
  }

  /* 通用按钮等待态：耗时操作点击后，除了禁用之外再给一个看得见的转圈。
     只负责视觉与 aria，**不改 disabled** —— 各业务的禁用/恢复各有自己的
     状态机（截图 shot_state、安装 apk_state…），这里若顺手放开会把状态冲掉。
     幂等：重复 set true/false 都安全。 */
  function markBtnBusy(btn, busy) {
    if (!btn) return;
    const on = !!busy;
    btn.classList.toggle("is-loading", on);
    if (on) btn.setAttribute("aria-busy", "true");
    else btn.removeAttribute("aria-busy");
  }

  /* ---------------- 二次确认弹窗（应用内自绘） ----------------
     为什么不用 window.confirm：pywebview 各版本对它的支持并不一致 —— 部分版本里
     它是个空函数，调用返回 undefined，于是 `!confirm(...)` 恒为 true，点「取消录制」
     会**一声不响地什么都不做**：按钮像坏的、没有提示、数据也没删。这类「点了没
     反应」是最难自查的静默失败，而它偏偏发生在「删除」这个最不该含糊的入口上。
     自绘还顺带换来两件事：默认焦点落在「否」（顺手一个回车不会删数据），以及
     能把「到底删哪些文件」写清楚，而不是一句笼统的「确定要取消吗」。

     askConfirm(opts) → Promise<boolean>：只有用户明确点了「是」才 resolve(true)。
     其余一切出口（否 / × / 遮罩 / Esc / 界面里没有这个弹窗）都是 false。
     调用方只认 true —— 没确认就绝不动手。 */
  let confirmResolve = null;     // 当前等待中的那次确认（同一时刻只允许一个）

  function askConfirm(opts) {
    const o = opts || {};
    return new Promise((resolve) => {
      if (!els.confirmModal || !els.confirmYes || !els.confirmNo) {
        // 界面里没有这个弹窗（裁剪过的 HTML / 版本错配）：**直接判否**。
        // 绝不能「没有弹窗就当他同意了」—— 那正好是删数据最不该走的分支。
        // 但也不能一声不响：按钮点了毫无反应，用户只会以为程序卡了。
        pushStatus("warn", "⚠ 无法确认：界面里缺少确认弹窗，已按「否」处理，未做任何删除");
        resolve(false);
        return;
      }
      // 已经有一个在等：先把上一个判否收掉。否则旧的那个 Promise 永远不 resolve，
      // 它的调用方就一直卡在 await 上（按钮已锁、状态栏停在「正在…」）。
      const prev = confirmResolve;
      confirmResolve = null;
      if (prev) prev(false);

      if (els.confirmTitle) els.confirmTitle.textContent = o.title || "确认操作";
      if (els.confirmText) els.confirmText.textContent = o.text || "";
      els.confirmYes.textContent = o.yes || "确定";
      els.confirmNo.textContent = o.no || "取消";
      // 「是」的配色跟着后果走：会删东西的才用警示色，普通确认用强调色。
      // 两个类都显式 toggle（不是只加不减）：同一个弹窗会复用，残留上一次的
      // 配色会让「只是普通确认」看起来像「要删东西」。
      els.confirmYes.classList.toggle("warn", !!o.danger);
      els.confirmYes.classList.toggle("accent", !o.danger);

      confirmResolve = resolve;
      els.confirmModal.classList.remove("hidden");
      // 默认焦点给「否」：弹窗里最容易被顺手按下的是回车，落在「否」上才是安全侧
      try { els.confirmNo.focus(); } catch (_) { /* 个别环境没有 focus */ }
    });
  }

  /* 关闭弹窗并给出答案。重复关闭是安全的（后一次 no-op）：
     点「是」之后紧接着按 Esc，不能让同一个 Promise 被 resolve 两次。 */
  function settleConfirm(answer) {
    if (!els.confirmModal) return;
    els.confirmModal.classList.add("hidden");
    const fn = confirmResolve;
    confirmResolve = null;
    if (fn) fn(answer === true);
  }

  /* Tab 在弹窗内循环：焦点跑到背后的界面上，键盘用户的下一次回车就可能落在
     背后的某个按钮上 —— 弹窗还开着，看起来就像弹窗失灵。 */
  function trapConfirmTab(e) {
    if (!els.confirmModal || els.confirmModal.classList.contains("hidden")) return;
    const items = [els.confirmNo, els.confirmYes, els.confirmX]
      .filter((el) => el && !el.disabled);
    if (!items.length) return;
    e.preventDefault();
    const cur = items.indexOf(document.activeElement);
    const next = e.shiftKey
      ? (cur <= 0 ? items.length - 1 : cur - 1)
      : (cur === items.length - 1 ? 0 : cur + 1);
    try { items[next].focus(); } catch (_) { /* 同上 */ }
  }

  /* ---------------- 输入弹窗（应用内自绘，替代 window.prompt） ----------------
     与 confirm 同一个理由：pywebview 各版本对 prompt 的支持也不一致，部分版本直接
     返回 null —— 那样「重命名 / 新建文件 / 新建文件夹」会点了毫无反应，连报错都没
     有。askInput(opts) → Promise<string|null>：只有用户明确点「确定」且内容非空才给
     字符串，其余出口（取消 / × / 遮罩 / Esc / 界面里没有这个弹窗）一律 null。 */
  let inputResolve = null;      // 当前等待中的那次输入（同一时刻只允许一个）
  const INPUT_MAX = 120;        // 输入长度上限（挡住误粘贴整段文本，不是业务限制）

  function askInput(opts) {
    const o = opts || {};
    return new Promise((resolve) => {
      if (!els.inputModal || !els.inputField || !els.inputYes || !els.inputNo) {
        // 与确认弹窗同样的取舍：缺弹窗时**绝不当成用户输入了内容**，
        // 但要吭一声，否则用户只会觉得按钮坏了。
        pushStatus("warn", "⚠ 界面里缺少输入弹窗，已取消这次操作，未做任何改动");
        resolve(null);
        return;
      }
      // 已经有一个在等：先把上一个判取消收掉，否则它的调用方永远卡在 await 上
      const prev = inputResolve;
      inputResolve = null;
      if (prev) prev(null);

      if (els.inputTitle) els.inputTitle.textContent = o.title || "输入";
      if (els.inputLabel) els.inputLabel.textContent = o.label || "";
      if (els.inputHint) els.inputHint.textContent = o.hint || "";
      els.inputYes.textContent = o.ok || "确定";
      els.inputNo.textContent = o.cancel || "取消";
      els.inputField.value = o.value || "";
      els.inputField.placeholder = o.placeholder || "";
      els.inputField.maxLength = o.maxLength || INPUT_MAX;

      inputResolve = resolve;
      els.inputModal.classList.remove("hidden");
      // 默认聚焦并全选：重命名最常见的是「改个后缀 / 改一段」，全选后直接敲新的
      try { els.inputField.focus(); els.inputField.select(); } catch (_) { /* 个别环境没有 focus */ }
    });
  }

  /* 关闭输入弹窗并给出答案。重复关闭安全（后一次 no-op）：点了「确定」再按 Esc
     不能让同一个 Promise 被 resolve 两次。 */
  function settleInput(ok) {
    if (!els.inputModal || els.inputModal.classList.contains("hidden")) return;
    const raw = els.inputField ? els.inputField.value : "";
    els.inputModal.classList.add("hidden");
    const fn = inputResolve;
    inputResolve = null;
    if (!fn) return;
    const text = String(raw == null ? "" : raw).trim();
    fn(ok && text ? text : null);   // 空白名等同于取消，不让调用方去拼一个空路径
  }

  function trapInputTab(e) {
    if (!els.inputModal || els.inputModal.classList.contains("hidden")) return;
    const items = [els.inputField, els.inputNo, els.inputYes, els.inputX]
      .filter((el) => el && !el.disabled);
    if (!items.length) return;
    e.preventDefault();
    const cur = items.indexOf(document.activeElement);
    const next = e.shiftKey
      ? (cur <= 0 ? items.length - 1 : cur - 1)
      : (cur === items.length - 1 ? 0 : cur + 1);
    try { items[next].focus(); } catch (_) { /* 同上 */ }
  }

  /* ---------------- 关键告警弹窗（不点「我知道了」不消失） ----------------
     出发点是一次真实的坏结果：用户录屏 20 多分钟，中途 USB 带宽被满缓冲 logcat
     占满、抓取被断开，收尾时「✓ 录屏已完成」和「日志只跟到 10:50」一前一后弹了
     toast —— 每条 6 秒自动消失。人当时在别的地方，一条都没记住，直到事后拿视频
     时间轴去对日志，才发现后 24 分钟是空的，那时既补不回来也说不清断在哪。

     结论就是：**「产物可能已经残缺」这类事不能靠会自己消失的提示**。toast 适合
     「顺带说一声」，而这种提示必须挡在用户面前、由他亲手关掉。几条设计取舍：

       · 不自动消失（没有计时器），也没有「淡出」路径；
       · 多条合并进**同一个**弹窗：多台设备同时出问题时连弹 5 个窗口，用户只会
         一顿乱点，等于没看；合并后他能一次看完再关。
       · 「查看状态信息」把完整过程摆出来（哪台设备、断在哪、为什么），弹窗里
         只放结论 —— 正文太长就没人读了。
       · Esc / × / 点遮罩都能关：误触不该让人以为界面卡住；关掉也只是少看一眼，
         状态栏里那条记录还在，不会丢。 */
  const alertItems = [];        // 当前弹窗里正在展示的条目 {level, text}
  let alertTitle = "";          // 首个触发者的标题（后来的不覆盖：先到的更贴近主因）
  let alertDropped = 0;         // 超出上限未展开的条数（底部小字说清，不静默丢）
  const ALERT_MAX_ITEMS = 12;   // 上限：再多也不是「一条条读」，不如去看状态信息

  function showAlert(opts) {
    const o = opts || {};
    const incoming = (o.items || (o.text ? [{ level: o.level, text: o.text }] : []))
      .filter((it) => it && it.text);
    if (!incoming.length) return false;
    if (!els.alertModal || !els.alertBody || !els.alertOk) {
      // 界面里没有这个弹窗（裁剪过的 HTML / 版本错配）：退回 toast，
      // 绝不能一声不响 —— 这正是本功能要消灭的那种「静默」。
      incoming.forEach((it) => showToast(it.level || "warn", it.text));
      return false;
    }
    if (!alertItems.length) alertTitle = o.title || "⚠ 需要确认的重要提示";
    incoming.forEach((it) => {
      // 同一句话不重复列（后端可能在收尾与播报两处都带同一条结论）
      if (alertItems.some((x) => x.text === it.text)) return;
      // 超上限不再往弹窗里塞（正文太长就没人读了），但也不静默丢掉：
      // 记下来在底部小字里说「还有 N 条见状态信息」，否则用户会以为就这些。
      if (alertItems.length >= ALERT_MAX_ITEMS) { alertDropped += 1; return; }
      alertItems.push({ level: it.level || "warn", text: it.text });
    });
    const wasOpen = alertOpen();
    renderAlert();
    els.alertModal.classList.remove("hidden");
    // 焦点落在唯一主动作上：Tab 出去不会落到背后的界面上，回车也只是关掉它。
    // 只在「弹窗本来没开」时抢一次：多条告警连续到达时反复 focus 会把用户
    // 正在读的位置顶回按钮上（他自己滚下去看第 5 条，下一台设备一报又跳回顶部）。
    if (!wasOpen) {
      try { els.alertOk.focus(); } catch (_) { /* 个别环境没有 focus */ }
    }
    return true;
  }

  function renderAlert() {
    if (!els.alertBody) return;
    if (els.alertTitle) els.alertTitle.textContent = alertTitle;
    els.alertBody.textContent = "";
    alertItems.forEach((it, i) => {
      const row = document.createElement("div");
      row.className = "alert-item alert-item--" + it.level;
      // 多条时才编号：一条时前面挂个「1.」纯属噪音
      row.textContent = (alertItems.length > 1 ? (i + 1) + ". " : "") + it.text;
      els.alertBody.appendChild(row);
    });
    if (els.alertHint) {
      const more = alertDropped
        ? "另有 " + alertDropped + " 条未在此展开，见状态信息。" : "";
      els.alertHint.textContent = (alertItems.length > 1
        ? "共 " + alertItems.length + " 条。" + more
        : "原因与处理过程都记在状态信息里（点击顶栏跑马灯也能打开）。" + more);
    }
  }

  function closeAlert() {
    if (!els.alertModal) return;
    els.alertModal.classList.add("hidden");
    alertItems.length = 0;
    alertTitle = "";
    alertDropped = 0;
    // 顺手把列表清空：留着旧条目虽然看不见（弹窗隐藏），但下一次打开若某条
    // 因为去重被跳过，屏幕上就会混进上一轮的残留 —— 那种「我没看到的告警
    // 怎么还在」比多清一次 DOM 难查得多。
    if (els.alertBody) els.alertBody.textContent = "";
    if (els.alertHint) els.alertHint.textContent = "";
  }

  function alertOpen() {
    return !!els.alertModal && !els.alertModal.classList.contains("hidden");
  }

  function trapAlertTab(e) {
    if (!alertOpen()) return;
    const items = [els.alertMore, els.alertOk, els.alertX]
      .filter((el) => el && !el.disabled);
    if (!items.length) return;
    e.preventDefault();
    const cur = items.indexOf(document.activeElement);
    const next = e.shiftKey
      ? (cur <= 0 ? items.length - 1 : cur - 1)
      : (cur === items.length - 1 ? 0 : cur + 1);
    try { items[next].focus(); } catch (_) { /* 同上 */ }
  }

  /* ---------------- 事件路由 ----------------
     逐条兜底：pollOnce 用递归 setTimeout 续约，任何一个 handler 抛异常都会让
     那一次续约**根本执行不到** —— 事件轮询从此彻底停止，界面表现为「日志不
     再滚、状态栏不再动、设备不刷新、会话按钮卡住」，只能重开程序。
     真实触发过：某台设备 logcat 行里混进非预期结构（协议漂移 / 手改 payload），
     或某个渲染函数踩到空节点。这里按事件逐条隔离，同一类事件只提示一次
     （坏数据可能每 400ms 来一条，不能让它把状态栏刷爆）。 */
  const _evErrNotified = Object.create(null);
  function safeHandleEvent(ev) {
    try {
      handleEvent(ev);
    } catch (e) {
      const kind = (ev && ev.kind) || "?";
      if (_evErrNotified[kind]) return;
      _evErrNotified[kind] = true;
      const msg = (e && e.message) ? e.message : String(e);
      try {
        pushStatus("err", "事件处理失败（" + kind + "）：" + msg
          + " —— 已跳过该事件，后续事件继续处理");
      } catch (_) { /* 状态栏本身出错也不能再往外抛 */ }
    }
  }

  function handleEvent(ev) {
    const p = ev.payload || {};
    switch (ev.kind) {
      case "booted": onBooted(p); break;
      case "devices":
        devices = p.items || [];
        renderDevices(); renderFileDev(); renderPerfDev(); onAbout();
        // 无线设备是「连上/断开」时才出现在列表里的：弹窗开着时同步刷新，
        // 否则用户刚连上却看到「当前没有无线设备」，会以为没成功。
        if (els.wifiModal && !els.wifiModal.classList.contains("hidden")) refreshWifi();
        break;
      case "console": {
        const ws = wsEventTarget(p.ws || "w1");
        if (!ws || !ws.consoleEl) break;
        if (p.kind === "clear") clearOut(ws.consoleEl);
        else if (p.kind === "prompt") {
          // cmd 风格 prompt：ShellSession 非交互 run 结束后通过 sentinel|path
          // 上报当前 cwd → 后端 bus.push console({kind:"prompt", cwd})
          if (ws.promptEl) ws.promptEl.textContent = formatPrompt(p.cwd);
        }
        else pushConsole(p.kind, p.text || "", ws.id);
        break;
      }
      case "status":
        if (p.type === "clear") clearStatus();
        else pushStatus(p.type, p.text || "", {
          toast: !!p.toast, alert: !!p.alert, alertTitle: p.alert_title || "",
        });
        break;
      case "tool":
        if (p.type === "clear") clearStatus();
        else if (["ok", "info", "err", "warn"].includes(p.type))
          pushStatus(p.type, p.text || "", {
            toast: !!p.toast, alert: !!p.alert, alertTitle: p.alert_title || "",
          });
        else if (p.type === "diag" && p.path) {
          // 诊断包产物：卡片里留一行指向结果 —— 状态栏/toast 会被后面的消息刷走，
          // 而「刚才那个包到底存哪了」是紧接着要用的信息。
          if (els.diagResult) {
            els.diagResult.textContent = String(p.path).split(/[\\/]/).pop() || p.path;
            els.diagResult.title = p.path;
            els.diagResult.classList.remove("dim");
          }
        } else if (p.type === "screenshot" && p.path) {
          // 每次截屏完在卡片下方生成预览图（默认宽度自适应、可拖拽改大小）
          showShotPreview(p.path);
        }
        break;
      case "stop_state": {
        // 停止按钮态按工作区同步：一个 tab 里点停止只该熄掉它自己那颗按钮。
        // 顺带把「该 tab 正在执行」的指示点一起同步 —— 用户切走后仍能看出
        // 哪个工作区有活在跑。运行按钮同步转圈：只认后端 stop_state 事件
        // （每条命令开始/结束都会推），不做乐观猜测，永远不会卡住。
        const ws = wsEventTarget(p.ws || "w1");
        if (!ws) break;
        if (ws.stopBtn) ws.stopBtn.disabled = !p.running;
        markBtnBusy(ws.runBtn, p.running);
        ws.busy = !!p.running;
        markWsBusy(ws);
        break;
      }
      case "rec_state": setRecRunning(!!p.running); break;
      case "shot_state": setShotRunning(!!p.running); break;
      case "apk_state": setApkRunning(!!p.running); break;
      case "diag_state": setDiagRunning(!!p.running); break;
      case "update_state": setUpdateChecking(!!p.running); break;
      case "update": onUpdateResult(p); break;
      case "logcat": onLogcat(p); break;
      case "logcat_capture": onLogcatCapture(p); break;
      case "file": onFile(p); break;
      case "file_view": onFileView(p); break;
    }
  }

  /* ---------------- 启动 ---------------- */
  function hasApi() { return !!(window.pywebview && window.pywebview.api); }

  /* 等待 pywebview 桥接就绪：pywebviewready 事件 + 200ms 轮询双保险，
     timeoutMs 内等不到即 resolve，由调用方决定下一步（不抛出、不卡死）。 */
  function waitForApi(timeoutMs) {
    return new Promise((resolve) => {
      const onReady = () => { window.removeEventListener("pywebviewready", onReady); resolve(); };
      window.addEventListener("pywebviewready", onReady);
      const deadline = Date.now() + timeoutMs;
      const timer = setInterval(() => {
        if (hasApi() || Date.now() > deadline) {
          clearInterval(timer); window.removeEventListener("pywebviewready", onReady); resolve();
        }
      }, 200);
    });
  }

  /* 等待某个桥接方法真正可调用：window.pywebview.api 可能先出现、方法后注入，
     只看 api 对象在不在（hasApi）并不足以保证 api.boot 已是函数。 */
  function waitForApiMethod(name, timeoutMs) {
    return new Promise((resolve) => {
      const deadline = Date.now() + timeoutMs;
      const timer = setInterval(() => {
        if (api && typeof api[name] === "function") {
          clearInterval(timer); resolve(true);
        } else if (Date.now() > deadline) {
          clearInterval(timer); resolve(false);
        }
      }, 100);
    });
  }

  async function start() {
    if (!hasApi()) await waitForApi(5000);
    if (!hasApi()) {
      /* 兜底自愈：桥接注入理论上随页面就绪到达，但可能被拖慢（典型场景：
         外链资源挂起 → 页面 load 不完成 → pywebview 在 NavigationCompleted
         才注入桥接 → pywebviewready 迟到）。此时先出遮罩说明情况，但保持后台
         等待——桥接一旦到达就自动收起遮罩并继续启动，不再永久卡在遮罩上。 */
      els.overlay.classList.remove("hidden");
      await waitForApi(600000); // 继续等 10 分钟
      if (!hasApi()) return;    // 确实没有桥接（如直接用浏览器打开），留在遮罩页
      els.overlay.classList.add("hidden");
    }
    api = window.pywebview.api;
    bindUI();
    /* 事件轮询与「booted 5s 兜底」必须先于任何一次初始化调用就位：它们是整个
       界面唯一的两条自愈通道。放在初始化之后时，只要其中一步抛异常 / 不返回，
       轮询就没机会启动 —— 界面永久停在「连接中…」，没有任何提示、也不会自己
       恢复（用户实报的偶发症状）。 */
    startEventLoop();
    try {
      /* 桥接对象就绪 ≠ 方法可调用。方法还没注入时直接 api.boot() 会抛
         TypeError 把 start() 整个中断（同样是永久「连接中…」），先等它出现。 */
      await waitForApiMethod("boot", 8000);
      await initSaveDirDefault();
      const res = await callApi(api.boot());
      if (res && res.ok === false && res.reason === "shutting_down") {
        setPill("已退出", "err");
      } else if (!res) {
        /* 调用失败 / 超时：后端可能其实已经启动，只是这次响应丢了。
           3 秒后重试一次 —— 后端 boot 幂等，已启动会重发 booted 载荷，
           于是前端仍能回到「已就绪」，而不是干等在「连接中…」。 */
        pushStatus("warn", "启动请求未完成，3 秒后自动重试…");
        setPill("启动重试中…", "warn");
        setTimeout(() => { if (!booted) callApi(api.boot()); }, 3000);
      }
    } catch (e) {
      // 兜底：宁可给出「启动失败 + 真实原因」，也不能安静地停在「连接中…」
      setPill("启动失败", "err");
      pushStatus("err", "启动初始化失败：" + (e && e.message ? e.message : e));
    }
  }

  /* 事件轮询 + 启动兜底。抽出来是为了让它在任何初始化动作**之前**就跑起来：
     轮询链一旦断了，界面就没有任何自愈路径。 */
  function startEventLoop() {
    // 事件轮询：空闲时退避到 500ms（降低无事件时的 IPC 频率，省 CPU/电池），
    // 一旦收到事件立即回到 400ms（日志/控制台/状态流动时保持跟手）。用递归
    // setTimeout 而非 setInterval，便于动态调整间隔。
    // 退避档只到 500ms 而不是更久：截图/录屏/logcat 抓取完成是用户可感的
    // 强反馈，轮询间隔直接决定 toast 的出现延迟，1s 档下「点完截图干等一秒
    // 才见提示」的体感明显。
    // 大批量（logcat 洪流，单次即取满行预算）时不等待间隔、立即续取：
    // 总线积压越快排空，前端渲染追上新数据的延迟越低。
    let pollMs = 400;
    // try/finally 是这里的硬约束：无论 take_events 失败、还是某条事件处理抛错，
    // 续约都必须发生。否则轮询链一断，界面就永久冻在那一刻（没有任何自愈路径，
    // 因为下一次续约正是被跳过的那个 setTimeout）。
    const pollOnce = async () => {
      let flooded = false;
      try {
        const events = await callApi(api.take_events(), 0);   // 不超时：take_events 只是从 deque 取事件
        flooded = !!(events && events.length >= 200);
        if (events && events.length) {
          if (pollMs !== 400) pollMs = 400;
          events.forEach(safeHandleEvent);
        } else if (pollMs !== 500) {
          pollMs = 500;
        }
      } catch (e) {
        /* callApi 已兜住桥接异常；能走到这里说明是事件分发之外的意外
           （例如 events 不是数组）。保持沉默但绝不中断轮询。 */
      } finally {
        setTimeout(pollOnce, flooded ? 0 : pollMs);
      }
    };
    setTimeout(pollOnce, pollMs);
    // 启动后 5s 内没收到 booted 事件的兜底：强制启用设备按钮，
    // 防止「boot 成功了但 booted 事件丢失/延迟」导致按钮永远 disabled。
    setTimeout(() => {
      if (!booted) {
        booted = true;   // 防止 onBooted 后续被重复执行
        setPill("已就绪（延迟）", "warn");
        pushStatus("warn", "⚠ 启动初始化稍有延迟，已自动启用设备刷新按钮");
        if (els.btnRefresh) els.btnRefresh.disabled = false;
        if (els.btnAll) els.btnAll.disabled = false;
      }
    }, 5000);
  }

  /* 保存目录默认值：来自后端 WebApi.default_save_dir（= 后端 _default_save_dir），
     与截图/录屏/下载实际写入的位置严格同源。失败时静默留空，不打扰用户。
     必须带超时：这是启动阶段第一个桥接调用，若桥接尚未真正接通，它的 Promise
     可能永不 resolve —— 无超时会把 start() 永久挡在这里（界面停在「连接中…」）。 */
  async function initSaveDirDefault() {
    if (els.toolDir.value) return;
    let dir = "";
    try {
      if (api && typeof api.default_save_dir === "function") {
        const r = await callApi(api.default_save_dir(), 5);
        if (r && r.dir) dir = String(r.dir);
      }
    } catch (e) { dir = ""; }
    if (dir) setSaveDirInputs(dir);
  }

  function onBooted(p) {
    booted = true;
    setPill("已就绪", "ok");
    (p.warnings || []).forEach((w) => pushStatus("warn", "⚠ " + w));
    els.btnRefresh.disabled = false;
    els.btnAll.disabled = false;
    // 后端单一数据源下发：设备状态标签 / logcat 缓冲区选项 / 用户偏好
    if (p.state_labels) stateLabels = p.state_labels;
    if (p.lc_buffers) buildLcBufferOptions(p.lc_buffers);
    if (p.settings) applyBootSettings(p.settings);
    // settings.json 里被防错机制纠正过的配置（手写错类型 / 非法级别）：
    // 逐条提示，让用户知道「这项没按你写的生效，已恢复默认」，
    // 而不是哪天莫名发现开关复位、却不知道去哪查。
    (p.settings_warnings || []).forEach((w) => pushStatus("warn", "⚠ 配置已纠正：" + w));
    // 关于页展示配置文件位置：用户拷走这一个文件即可在别的电脑同步设置
    if (els.aboutConfigPath && p.config_path) {
      els.aboutConfigPath.textContent = p.config_path;
      els.aboutConfigPath.title = p.config_path;
    }
    // 保存目录失效回退：配置里的绝对路径在本机不存在 → 已改用默认目录。
    // 配置文件里的原值保持不动（那是源机器上的正确路径）。
    if (p.save_dir_note) pushStatus("warn", "⚠ " + p.save_dir_note);
    if (p.adb_ok === false) {
      els.aboutAdbDir.classList.add("err");
      pushStatus("warn", "⚠ 未检测到 adb：可在「关于」页填写 adb 所在目录后保存并刷新。");
    }
    renderCommands(p.commands || []);
    onAbout(p);
    // 指令台历史（跨工作区共享、持久化）：从 config.json 恢复。
    _loadCmdHistory(p.settings && p.settings.cmd_history);
    // 按包过滤的下拉：启动时先把包列表拉回来（设备可能是上次记住的）
    refreshLcPackages();
    // 过滤预设（自定义的常用表达式，落盘在 config.json 的 lc_presets）
    _loadLcPresets(p.settings && p.settings.lc_presets);
    // 主 tab 回到上次停留项：必须排在 renderCommands 之后 —— 切到「性能监控」
    // 要按已勾选的设备渲染目标设备条，切到「设备指令」要求指令卡已经画好。
    // 设备勾选态若还没下发，devices 事件到达时 renderPerfDev 会再补一次。
    restoreMainTab(p.settings && p.settings.main_active_tab);
    // 版本更新状态（开关 + 上次检查结果）。单独一次调用而不是塞进 booted 载荷：
    // 它是「可选的附加信息」，取不到也不该影响启动主流程。
    loadUpdateInfo();
  }

  // 后端下发的缓冲区选项（label -> 实际缓冲区名列表）重建下拉；
  // 保留用户上次选择，匹配不到则落回第一项。
  function buildLcBufferOptions(map) {
    if (!els.lcBuf || typeof map !== "object") return;
    const cur = els.lcBuf.value;
    els.lcBuf.innerHTML = "";
    Object.keys(map).forEach((label) => {
      const opt = document.createElement("option");
      opt.value = label;
      opt.textContent = label;
      opt.dataset.values = JSON.stringify(map[label] || [label]);
      els.lcBuf.appendChild(opt);
    });
    const exists = Array.from(els.lcBuf.options).some((o) => o.value === cur);
    if (exists) els.lcBuf.value = cur;
  }

  // booted.settings 回填偏好控件（adb 目录输入框等）；输入框红框状态
  // 由 onBooted 依据顶层 adb_ok 统一设置
  function applyBootSettings(s) {
    if (!s || typeof s !== "object") return;
    // 设备栏收起状态（布局偏好，跨会话记忆）：缺省 / 非布尔 → 展开态不动
    if (typeof s.sidebar_collapsed === "boolean") {
      applySidebarCollapsed(s.sidebar_collapsed, false);
    }
    // 指令台左栏收起状态（跨会话记忆）：老 config.json 缺此键 → 保持展开。
    // 多工作区共用这一个偏好，已注册的逐个套用；之后新建 / 恢复出来的工作区
    // 由 bindWorkspace 末尾按 cmdPanelCollapsed 自动继承。
    if (typeof s.cmd_panel_collapsed === "boolean") {
      cmdPanelCollapsed = s.cmd_panel_collapsed;
      wsMap.forEach((ws) => applyCmdCollapsed(ws, cmdPanelCollapsed, false));
    }
    if (typeof s.save_dir === "string" && s.save_dir) setSaveDirInputs(s.save_dir);
    if (typeof s.adb_dir === "string") els.aboutAdbDir.value = s.adb_dir;
    // 命令超时保护：整数秒（0 = 不限制）。老 config.json 缺此键时 UI 留空，
    // 后端默认 0（不限制）；用户手动填值后下次启动 applyBootSettings 回填。
    if (els.aboutCmdTimeout && typeof s.cmd_timeout === "number"
        && Number.isFinite(s.cmd_timeout)) {
      els.aboutCmdTimeout.value = String(Math.round(s.cmd_timeout));
    }
    // 缺省不写就保持 HTML 的默认勾选（默认开启）；用户显式设过值则以设置为准
    if (els.shotClipboard && typeof s.shot_to_clipboard === "boolean") {
      els.shotClipboard.checked = s.shot_to_clipboard;
    }
    // 「自动保存文件」：缺省不写就保持 HTML 默认勾选（默认开启）；用户显式
    // 设过值则以设置为准。关闭后截图不往保存目录落盘（只进预览/剪贴板）。
    if (els.shotSaveFile && typeof s.shot_save_file === "boolean") {
      els.shotSaveFile.checked = s.shot_save_file;
    }
    if (typeof s.keep_input === "boolean") {
      // 「保留输入内容」是全局设置：所有工作区一起回填
      wsMap.forEach((ws) => { if (ws.keepEl) ws.keepEl.checked = s.keep_input; });
    }
    // 指令台工作区布局（上次开了几个 tab、各叫什么、停在哪个）：必须在
    // renderCommands 之前恢复，否则首屏只渲染默认工作区，切到新开的 tab 会是空的。
    if (typeof s.cmd_workspaces === "string" || typeof s.cmd_active_ws === "string") {
      restoreWorkspaces(s.cmd_workspaces, s.cmd_active_ws);
    }
    // 指令台搜索关键字：恢复后立即重跑一次过滤，界面与实际过滤结果一致
    const ws1 = wsOf("w1");
    if (ws1 && ws1.filterEl && typeof s.cmd_filter === "string" && s.cmd_filter) {
      ws1.filterEl.value = s.cmd_filter;
      applyCmdFilter(ws1);
    }
    // 指令卡手动排序（拖动后落盘）：必须在 renderCommands 之前读进来，
    // 否则首屏按点击频次排完、再被重排一次，用户会看到卡片跳一下。
    if (typeof s.cmd_order === "string") loadCmdOrder(s.cmd_order);
    // 内置命令的设备类型筛选（通用 / 车机 / 手机）：同样要先于首屏渲染恢复，
    // 否则用户上次选的是「车机」，启动后却先看到全部、再被筛一次。
    // 非法值（手改 config.json）直接忽略，保持「全部」。
    if (typeof s.builtin_scope === "string"
        && BUILTIN_SCOPES.indexOf(s.builtin_scope) >= 0) {
      builtinScope = s.builtin_scope;
    }
    // ---- Logcat 实时监控 ----
    if (els.lcFilter && typeof s.lc_keyword === "string") els.lcFilter.value = s.lc_keyword;
    if (els.lcOnlyExc && typeof s.lc_only_exc === "boolean") els.lcOnlyExc.checked = s.lc_only_exc;
    if (els.lcAuto && typeof s.lc_autoscroll === "boolean") els.lcAuto.checked = s.lc_autoscroll;
    if (els.lcBuf && typeof s.lc_buffer === "string" && s.lc_buffer) {
      // 选项由后端 lc_buffers 重建；存的值匹配不到时保持 buildLcBufferOptions
      // 的回落（当前/第一项），不强行写入一个不存在的 option
      const exists = Array.from(els.lcBuf.options).some((o) => o.value === s.lc_buffer);
      if (exists) els.lcBuf.value = s.lc_buffer;
    }
    if (els.lcLevels && Array.isArray(s.lc_levels)) setLevelChecks(els.lcLevels, s.lc_levels);
    // ---- Logcat 落盘抓取 ----
    if (els.lcCapZipstop && typeof s.lc_cap_zipstop === "boolean") {
      els.lcCapZipstop.checked = s.lc_cap_zipstop;
    }
    if (els.lcCapLevels && Array.isArray(s.lc_cap_levels)) {
      setLevelChecks(els.lcCapLevels, s.lc_cap_levels);
    }
    // ---- 录屏（指针位置 / 触摸圆点默认开启，缺省时保持 HTML 勾选）----
    if (els.recLogcat && typeof s.rec_logcat === "boolean") els.recLogcat.checked = s.rec_logcat;
    // 电脑麦克风默认关闭：只有配置里显式写 true 才勾上（录的是本机麦克风说话声）
    if (els.recMic && typeof s.rec_mic === "boolean") els.recMic.checked = s.rec_mic;
    if (els.recZip && typeof s.rec_zip === "boolean") els.recZip.checked = s.rec_zip;
    if (els.recPointerLocation && typeof s.rec_pointer_location === "boolean") {
      els.recPointerLocation.checked = s.rec_pointer_location;
    }
    if (els.recShowTouches && typeof s.rec_show_touches === "boolean") {
      els.recShowTouches.checked = s.rec_show_touches;
    }
    // 工具子 tab 顺序（长按拖动后落盘 tool_tab_order）：必须在重建之后读进来，
    // 否则首屏按 HTML 默认序排好、再被重排一次，用户会看到顺序跳一下。
    if (typeof s.tool_tab_order === "string") loadToolTabOrder(s.tool_tab_order);
    applyToolTabOrder();
    // 恢复到上次停留的子 tab（tool_active_tab）；没记过 / key 已失效则回退截图。
    // persist:false —— 启动回填不该再写一次盘。
    switchToolTab(typeof s.tool_active_tab === "string" && s.tool_active_tab
      ? s.tool_active_tab : "shot", { persist: false });
    // Logcat 子 tab（落盘抓取 / 实时监控）：恢复到上次停留项；没记过 / key 已失效
    // 则回退落盘抓取。persist:false —— 启动回填不写盘。
    switchLcTab(typeof s.lc_active_tab === "string" && s.lc_active_tab
      ? s.lc_active_tab : "capture", { persist: false });
    // ---- APK 安装选项（默认值只写在 core/prefs.py 一处，此处仅回填）----
    if (els.apkReplace && typeof s.apk_replace === "boolean") {
      els.apkReplace.checked = s.apk_replace;
    }
    if (els.apkDowngrade && typeof s.apk_downgrade === "boolean") {
      els.apkDowngrade.checked = s.apk_downgrade;
    }
    if (els.apkGrant && typeof s.apk_grant === "boolean") {
      els.apkGrant.checked = s.apk_grant;
    }
    // ---- 诊断包选项（默认值同样只写在 core/prefs.py 一处）----
    if (els.diagLogcat && typeof s.diag_with_logcat === "boolean") {
      els.diagLogcat.checked = s.diag_with_logcat;
      if (els.diagLines) els.diagLines.disabled = !s.diag_with_logcat;
    }
    if (els.diagLines && s.diag_logcat_lines != null) {
      const want = String(s.diag_logcat_lines);
      // 只回填下拉里存在的档位：用户把手改的 777 读进来时，select.value 赋一个
      // 不存在的值会变成空字符串，界面上就是「行数」那格莫名其妙空白。
      const hit = Array.prototype.some.call(
        els.diagLines.options, (o) => o.value === want);
      if (hit) els.diagLines.value = want;
    }
    if (els.scrcpyPath && typeof s.scrcpy_path === "string") {
      els.scrcpyPath.value = s.scrcpy_path;
    }
    // 备用投屏参数（播放器路径 / 分辨率 / 码率 / 预览帧率）
    if (els.mirrorPlayerPath && typeof s.mirror_player_path === "string") {
      els.mirrorPlayerPath.value = s.mirror_player_path;
    }
    if (els.mirrorSize && typeof s.mirror_size === "string") {
      els.mirrorSize.value = s.mirror_size;
    }
    if (els.mirrorBitrate && s.mirror_bitrate != null) {
      els.mirrorBitrate.value = String(s.mirror_bitrate);
    }
    if (els.mirrorFps && s.mirror_fps != null) {
      els.mirrorFps.value = String(s.mirror_fps);
    }
    // 预览区大小（0 = 自适应）：上次拖到多大，这次投屏还原成多大
    if (typeof s.mirror_view_w === "number" || typeof s.mirror_view_h === "number") {
      applyMirrorViewSize(s.mirror_view_w, s.mirror_view_h);
    }
    // 截图预览区大小（0 = 自适应）：上次拖到多大，这次截屏还原成多大
    if (typeof s.shot_preview_w === "number" || typeof s.shot_preview_h === "number") {
      applyShotPreviewSize(s.shot_preview_w, s.shot_preview_h);
    }
    // 性能监控：目标包名 / 采样间隔 / 图表指标
    if (typeof s.perf_pkg === "string") setPerfPkg(s.perf_pkg, true);
    if (els.perfPkgAll && typeof s.perf_pkg_all === "boolean") {
      els.perfPkgAll.checked = s.perf_pkg_all;
    }
    if (els.perfInterval && typeof s.perf_interval_ms === "number") {
      els.perfInterval.value = String(s.perf_interval_ms);
    }
    if (typeof s.perf_metric === "string" && PERF_METRICS[s.perf_metric]) {
      setPerfMetric(s.perf_metric, false);
    }
    // ---- 主题（深 / 浅 / 随系统）----
    // 还原上次选择的模式：HTML 默认深色（与 :root 默认一致，无闪白），浅色 /
    // system 在这里才真正套上。persist:false —— 启动回填不该再写一次盘；
    // 原生标题栏已由 main.py 的 _theme_window 在窗口就绪时按 config.theme 套好。
    setTheme(THEME_MODES.includes(s.theme) ? s.theme : "dark", { persist: false });
  }

  // 级别复选框组同步：只勾 levels 里的（空数组 = 全不勾，合法语义）。
  // 容器里没有的级别忽略——实时监控与落盘抓取两处容器结构相同，共用本助手。
  function setLevelChecks(container, levels) {
    if (!container || !Array.isArray(levels)) return;
    const set = new Set(levels.map(String));
    Array.from(container.querySelectorAll("input")).forEach((c) => {
      c.checked = set.has(c.value);
    });
  }

  // 单个偏好项即时持久化（settings.json，跨会话记忆）。
  // 保存失败不打扰用户（后端已尽力而为：磁盘满 / 只读时静默保持现状），
  // 但也不抛异常打断当前操作。
  function persistPref(key, value) {
    if (!key) return;
    const patch = {};
    patch[key] = value;
    callApi(api.save_settings(patch));
  }

  // 一次落多个键：拖拽改大小这种「成对」的参数（宽 + 高）分两次写会各触发一次
  // 读-合并-写，第二次读到的是第一次落盘后的文件，但界面里若同时有别的改动，
  // 中间的半截状态也可能被写出去。合成一次更稳。
  function persistPrefs(patch) {
    if (!patch || !Object.keys(patch).length) return;
    callApi(api.save_settings(patch));
  }

  // 级别复选框组当前勾选的值数组（顺序固定 V/D/I/W/E/F，与后端 VALID_LEVELS 对齐）
  // ------------------------------------------------------------------ //
  // 主题（dark / light / system）：落盘的是「模式」而非「解析后的颜色」——
  // system 模式要跟随系统 prefers-color-scheme，所以这里只存模式，真正写到
  // <html data-theme> 的颜色由 resolveThemeAttr 在每次切换 / 系统变化时解析。
  // 原生标题栏联动交后端 set_theme（仅 Windows 生效，其它平台静默返回）。
  // ------------------------------------------------------------------ //
  const THEME_MODES = ["dark", "light", "system"];
  let _themeMql = null;          // 系统主题 MediaQuery，只挂一次监听
  let _themeMode = "dark";       // 当前模式（深 / 浅 / 随系统）

  function resolveThemeAttr(mode) {
    // 把模式解析成真正写到 <html data-theme> 的值（dark / light）
    if (mode === "system") {
      const mql = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)");
      return mql && mql.matches ? "dark" : "light";
    }
    return mode === "light" ? "light" : "dark";
  }

  function applyThemeAttr() {
    const attr = resolveThemeAttr(_themeMode);
    if (attr === "light") document.documentElement.dataset.theme = "light";
    else if (document.documentElement.dataset.theme) delete document.documentElement.dataset.theme;
  }

  function syncThemeSwitch() {
    if (!els.themeSwitch) return;
    els.themeSwitch.querySelectorAll(".theme-opt").forEach((b) => {
      const active = b.dataset.themeMode === _themeMode;
      b.classList.toggle("active", active);
      b.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  function bindSystemThemeListener() {
    // 只挂一次：系统主题变化时，仅当当前模式为 system 才重新解析应用。
    if (!window.matchMedia || _themeMql) return;
    _themeMql = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => { if (_themeMode === "system") applyThemeAttr(); };
    if (_themeMql.addEventListener) _themeMql.addEventListener("change", handler);
    else if (_themeMql.addListener) _themeMql.addListener(handler); // 旧版 Safari
  }

  function setTheme(mode, opts) {
    if (!THEME_MODES.includes(mode)) mode = "dark";
    _themeMode = mode;
    applyThemeAttr();
    syncThemeSwitch();
    bindSystemThemeListener();
    opts = opts || {};
    // 落盘模式（不是解析值），下次启动 applyBootSettings 还原同一模式
    if (opts.persist !== false) {
      try { persistPref("theme", mode); } catch (e) {}
    }
    // 联动原生标题栏（仅 Windows 生效，其它平台后端静默返回，不影响切换）
    if (opts.syncNative !== false && api && api.set_theme) {
      try { api.set_theme(mode); } catch (e) {}
    }
  }

  function levelsOf(container) {
    if (!container) return null;
    return Array.from(container.querySelectorAll("input:checked")).map((c) => c.value);
  }

  /* ---------------- 设备区（共享 sidebar 渲染） ----------------
     增量渲染：按 serial 缓存卡片 DOM 节点，每次 devices 事件只更新有变化的
     属性（勾选态 / 在线态 / 型号 / 状态文案），新增的建卡、消失的移除。
     自动轮询每 5s 一次，旧实现整表 clearOut + 逐个 createElement + 逐个绑
     事件，既无谓打断 hover / 焦点，也让整片节点重排重绘——设备多时、状态
     抖动（offline↔device 漂移）时尤其明显。 */
  const devCards = new Map();    // serial -> {root, cb, dot, serialEl, metaEl, stateEl}
  let devEmptyNode = null;       // 「（无已连接设备）」提示行（复用同一节点）

  function buildDeviceCard(d) {
    const card = document.createElement("div");
    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.checked = !!d.checked; cb.disabled = !d.ok;
    const dot = document.createElement("span");
    const info = document.createElement("div");
    info.className = "info";
    const serial = document.createElement("div");
    serial.className = "serial";
    const meta = document.createElement("div");
    meta.className = "meta";
    info.appendChild(serial); info.appendChild(meta);
    const st = document.createElement("span");
    st.className = "state";
    // ⓘ 设备信息：卡片其余区域是「勾选 / 取消」，这个按钮必须 stopPropagation，
    // 否则点一下信息就把设备取消勾选了（最典型的误操作）。
    const infoBtn = document.createElement("button");
    infoBtn.type = "button";
    infoBtn.className = "dev-info";
    infoBtn.title = "查看设备信息（型号 / 系统版本 / 分辨率 / 电量 / 存储）";
    infoBtn.setAttribute("aria-label", "查看设备信息");
    infoBtn.textContent = "i";
    infoBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      openDeviceInfo(d.serial);
    });
    card.appendChild(cb); card.appendChild(dot); card.appendChild(info); card.appendChild(infoBtn); card.appendChild(st);
    card.addEventListener("click", (e) => {
      // 点在复选框上时，浏览器/ jsdom 会翻转 checked 并触发 change（change
      // 监听已经下发过一次）；click 再冒泡到卡片，若这里不 return 就会
      // 重复下发第二次 toggle_device（后端重复广播设备列表）。
      if (e.target === cb) return;
      if (cb.disabled) return;
      cb.checked = !cb.checked;
      toggleDevice(d.serial, cb.checked);
    });
    cb.addEventListener("change", () => toggleDevice(d.serial, cb.checked));
    const node = { root: card, cb, dot, serialEl: serial, metaEl: meta, stateEl: st };
    node.root._devSerial = d.serial;
    updateDeviceCard(node, d);
    return node;
  }

  function updateDeviceCard(n, d) {
    const root = n.root;
    const cls = "device-card"
      + (d.ok ? "" : " off")
      + (d.checked ? " selected" : "");
    if (root.className !== cls) root.className = cls;
    if (n.cb.checked !== !!d.checked) n.cb.checked = !!d.checked;
    if (n.cb.disabled === d.ok) n.cb.disabled = !d.ok;
    const dotCls = "dot " + (d.ok ? "ok" : d.state === "reconnecting" ? "wait" : "bad");
    if (n.dot.className !== dotCls) n.dot.className = dotCls;
    const serial = d.serial || "";
    if (n.serialEl.textContent !== serial) n.serialEl.textContent = serial;
    const model = d.model || "unknown model";
    if (n.metaEl.textContent !== model) n.metaEl.textContent = model;
    const stateText = d.ok ? "在线"
      : (stateLabels[d.state] || d.state || "不可用") + " · 已禁用";
    if (n.stateEl.textContent !== stateText) n.stateEl.textContent = stateText;
    // 序列号在窄栏里会被省略号截断（无线设备是 ip:port，尾巴才是端口），
    // title 带上完整序列号，悬停即可确认是哪台。
    const title = (d.ok ? "点击切换勾选" : "该设备当前不可下发命令")
      + " · " + serial;
    if (root.title !== title) root.title = title;
  }

  function renderDevices() {
    // 铭牌（徽章 + 标题文字）统一走 refreshSidebarNameplate：展开态恒显
    // 「N 台 + 已连接设备」；折叠态若勾选了设备则改显「N + 已选中设备」
    // （见 sidebar 区的同名函数）。0 台时单位一并隐藏，避免徽章空了还挂
    // 个「台」字。
    refreshSidebarNameplate();
    const usable = devices.filter((d) => d.ok);
    const allChecked = usable.length > 0 && usable.every((d) => d.checked);
    els.btnAll.textContent = allChecked ? "取消选择" : "全选";
    // 空列表提示行：无设备时确保存在（复用同一节点），有设备时移除
    if (!devices.length) {
      if (!devEmptyNode || !devEmptyNode.isConnected) {
        devEmptyNode = document.createElement("div");
        devEmptyNode.className = "line dim";
        devEmptyNode.textContent = "（无已连接设备）";
      }
      els.devList.appendChild(devEmptyNode);
    } else if (devEmptyNode && devEmptyNode.isConnected) {
      devEmptyNode.remove();
    }
    // 顺序对齐：仅当现有 DOM 顺序与期望顺序不一致时才逐条 append（append 已
    // 存在的节点会移动它；顺序一致时逐条 append 是无谓开销，先比较可全省）。
    const want = devices.map((d) => d.serial);
    const cur = Array.prototype.map.call(
      els.devList.querySelectorAll(".device-card"),
      (el) => el._devSerial);
    const sameOrder = want.length === cur.length
      && want.every((s, i) => s === cur[i]);
    devices.forEach((d) => {
      let n = devCards.get(d.serial);
      if (!n) {
        n = buildDeviceCard(d);
        devCards.set(d.serial, n);
      } else {
        updateDeviceCard(n, d);
      }
      if (!sameOrder) els.devList.appendChild(n.root);
    });
    // 移除已消失（真正 gone / 超宽限）设备的卡片节点
    const seen = new Set(want);
    for (const [s, n] of devCards) {
      if (!seen.has(s)) {
        n.root.remove();
        devCards.delete(s);
        // 同时回收该设备的 logcat 缓冲：每个条目最多 20000 行，热插拔 / 无线调试
        // 场景下若只增不减，历史设备的日志会一直占着内存到进程结束。
        if (!lcRunning || s !== lcSerial) delete lcBuffers[s];
      }
    }
    // Logcat 自动联动：未监控时跟随左侧第一个勾选设备，监控中不打断
    if (!lcRunning) {
      const next = firstChecked();   // 受控设备第一个（与文件 tab 同源）
      if (next !== lcSerial) {
        lcSerial = next;
        renderLogcat();
        refreshLcPackages();
        // 表达式里可能有 pkg:，换了设备就必须按新设备重新解析 pid：
        // 只重绘的话缓存里没有这台设备的映射，会一直显示「命中 0 行」，
        // 而界面看上去一切正常（这两台设备的缓存还互相不通用）。
        lcRefreshPkgPids(true);
        syncLcPkgTimer();
      }
    }
    syncToolButtons();
    // 抓取开始按钮：不在抓取中且至少有一个受控设备时可点（与监控按钮解耦）
    els.lcCapStart.disabled = lcCapRunning || !checkedDevices().length;
  }

  async function toggleDevice(serial, on) {
    const res = await callApi(api.toggle_device(serial, on));
    if (res && res.ok === false) pushStatus("warn", "⚠ 设备不可操作：" + serial);
  }

  /* ---------------- 指令区（含筛选 + 标签过滤） ----------------
     命令库全局一份，但**每个工作区各有自己的筛选词与标签选择**：在工作区 2
     里筛「网络」不该把工作区 1 的列表一起筛掉（那两块面板本来就在看不同的
     东西）。因此 renderCmdTags / applyCmdFilter 都按工作区走。 */
  function renderCommands(list) {
    allCommands = list || [];
    wsMap.forEach((ws) => {
      if (ws.tags) ws.tags.clear();
      renderCmdTags(ws);
      applyCmdFilter(ws);
    });
  }

  /* 命令库变更（增删改 / 导入）后刷新**所有**工作区：各 tab 看的是同一份库，
     只刷当前那块会让切回去的 tab 停在旧列表上（用户以为命令丢了）。 */
  function renderAllWs() {
    wsMap.forEach((ws) => {
      renderCmdTags(ws);
      applyCmdFilter(ws);
    });
  }

  /* 标签/分组排序：用户自己的命令永远在上方，「通用」居首，「内置」恒置最底。
     内置命令是程序兜底默认（core/builtin_commands.py），与用户 json 解耦；
     混在用户分组里会干扰查找，故独立成组并钉在最后（用户点「内置」标签
     也可单独过滤查看）。 */
  function tagRank(t) {
    if (t === "通用") return 0;   // 最前
    if (t === "内置") return 2;   // 最后
    return 1;                     // 其余按字母序排中间
  }
  function byTagOrder(a, b) {
    const d = tagRank(a) - tagRank(b);
    return d !== 0 ? d : (a < b ? -1 : a > b ? 1 : 0);
  }

  /* 「内置」命令的适用设备轴：scope 回答「在哪类设备上有意义」，卡片上打
     小角标，组内再给一排筛选按钮。缺省（后端没写 scope）一律按「通用」——
     绝大多数命令两类设备都能用，只有明确偏向某一类的才显式标注
     （见 core/builtin_commands.py）。
     注：早年「内置」组内还有一层二级分组（连接与投屏 / 显示辅助 / 按键 /
     屏幕状态 / 网络 / 应用与信息，可折叠），用户反馈层级太多、找命令反而
     费劲，已整体撤掉 —— 内置组与其余分组一样直接平铺 chips；后端数据里的
     section 字段保留，仅作为搜索关键词使用（见 applyCmdFilter）。 */
  const BUILTIN_SCOPES = ["通用", "车机", "手机"];
  let builtinScope = "";               // 空串 = 全部（落 config.json 的 builtin_scope）
  // scope -> CSS 类后缀：类名不用中文，避免选择器 / 工具链的兼容问题
  const SCOPE_CLASS = { "通用": "comm", "车机": "car", "手机": "phone" };

  // 标签过滤条：根据全部命令的 labels 生成可点选标签（多选 OR）
  function renderCmdTags(ws) {
    ws = ws || curWs();
    if (!ws || !ws.tagsEl) return;
    const tags = new Set();
    allCommands.forEach((c) => (c.labels || []).forEach((l) => tags.add(l)));
    const arr = Array.from(tags).sort(byTagOrder);
    ws.tagsEl.innerHTML = "";
    arr.forEach((t) => {
      const chip = document.createElement("button");
      chip.className = "cmd-tag" + (ws.tags.has(t) ? " active" : "");
      chip.textContent = t;
      chip.addEventListener("click", () => {
        if (ws.tags.has(t)) ws.tags.delete(t); else ws.tags.add(t);
        chip.classList.toggle("active");
        applyCmdFilter(ws);
      });
      ws.tagsEl.appendChild(chip);
    });
  }

  // 实时筛选：文字（命令名 + 命令内容）AND 已选标签（命中任一标签即保留）
  function applyCmdFilter(ws) {
    ws = ws || curWs();
    if (!ws) return;
    const kw = ((ws.filterEl && ws.filterEl.value) || "").toLowerCase().trim();
    const filtered = allCommands.filter((c) => {
      if (ws.tags.size > 0) {
        const labels = c.labels || [];
        if (!labels.some((l) => ws.tags.has(l))) return false;
      }
      if (kw) {
        // 搜索域含 section（后端数据的用途归属）与 scope（适用设备）：想找
        // 「网络」相关的一批命令、或只记得「车机专用」时，记不住具体名字
        // 也能筛出来。section 不再参与界面分组（二级分组已撤），但作为
        // 搜索关键词仍有效——搜「网络」照样能捞出一排 WiFi 命令。
        const hay = (c.name + " " + (c.section || "") + " "
          + (c.builtin ? scopeNameOf(c) : "") + " "
          + (c.commands || []).map((x) => x.command).join(" ")).toLowerCase();
        if (!hay.includes(kw)) return false;
      }
      return true;
    });
    renderCmdGroups(filtered, ws);
    if (ws.countEl) {
      // 设备类型筛选只作用于内置命令：计数要跟着可见卡片走，否则「手机」
      // 只剩 4 张卡、右上角却还写着 12 条，用户会以为筛坏了。
      const shown = builtinScope
        ? filtered.filter((c) => !c.builtin || scopeNameOf(c) === builtinScope).length
        : filtered.length;
      ws.countEl.textContent = "命中 " + shown + " / " + allCommands.length + " 条";
    }
  }

  // 文字筛选防抖：大指令集（从 electerm 导入可能数百条）下，每次按键全量重渲卡片会
  // 卡顿。标签点选 / 清空是离散操作，保持即时（直接调用 applyCmdFilter）。
  function onCmdFilterInput(ws) {
    ws = ws || curWs();
    if (!ws) return;
    // 搜索框尾部 clear-x：有内容才显示
    if (ws.clearFilterBtn) ws.clearFilterBtn.hidden = !ws.filterEl || !ws.filterEl.value;
    if (ws.filterTimer !== null) clearTimeout(ws.filterTimer);
    ws.filterTimer = setTimeout(() => { ws.filterTimer = null; applyCmdFilter(ws); }, 120);
  }

  function renderCmdGroups(list, ws) {
    ws = ws || curWs();
    if (!ws || !ws.groupsEl) return;
    const host = ws.groupsEl;
    const groups = {};
    list.forEach((c) => {
      const label = (c.labels && c.labels.length ? c.labels[0] : "其他") || "其他";
      (groups[label] = groups[label] || []).push(c);
    });
    clearOut(host);
    const keys = Object.keys(groups).sort(byTagOrder);
    if (!keys.length) {
      pushLine(host, "（无匹配命令）", "dim");
      return;
    }
    for (const label of keys) {
      // 组内排序：拖过的分组用手动顺序，没拖过的仍按使用频次降序（常用靠前）
      const items = sortCmdGroup(groups[label]);
      const box = document.createElement("div"); box.className = "cmd-group";
      const title = document.createElement("div");
      title.className = "cmd-group-title"; title.textContent = label;
      box.appendChild(title);
      // 「内置」组：先按设备类型（scope）收窄，再与其余分组一样平铺 chips。
      // 早年的二级分组（连接与投屏 / 按键 / 网络等，可折叠）已按用户反馈撤掉
      // ——层级太多找命令反而费劲；scope 筛选条保留，是组内唯一的二次收窄。
      if (label === "内置") {
        const scoped = filterByScope(items);
        box.appendChild(mkScopeBar());
        if (!scoped.length) {
          pushLine(box, "（该子标签下暂无内置命令）", "dim");
        } else {
          const chips = document.createElement("div"); chips.className = "cmd-chips";
          scoped.forEach((c) => chips.appendChild(mkCmdChip(c, ws.id)));
          box.appendChild(chips);
        }
      } else {
        const chips = document.createElement("div"); chips.className = "cmd-chips";
        items.forEach((c) => chips.appendChild(mkCmdChip(c, ws.id)));
        box.appendChild(chips);
      }
      host.appendChild(box);
    }
  }

  /* 命令的适用设备：后端缺省 / 手写坏值一律按「通用」——宁可多显示，
     也不能让一条命令因为在界面上被归错类而「消失」。 */
  function scopeNameOf(c) {
    return BUILTIN_SCOPES.indexOf(c.scope) >= 0 ? c.scope : "通用";
  }

  function filterByScope(items) {
    if (!builtinScope) return items;
    return items.filter((c) => scopeNameOf(c) === builtinScope);
  }

  /* 「内置」组内的设备类型筛选条：全部 / 通用 / 车机 / 手机。
     纯展示层筛选（不影响命令本身可用性），状态全局共享并落 config.json
     的 builtin_scope；切换后所有工作区一起重渲，避免切 tab 才「突然变」。 */
  function mkScopeBar() {
    const bar = document.createElement("div");
    bar.className = "cmd-scope-bar";
    [["", "全部"]].concat(BUILTIN_SCOPES.map((s) => [s, s])).forEach((pair) => {
      const val = pair[0], txt = pair[1];
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "cmd-scope" + (builtinScope === val ? " active" : "");
      btn.textContent = txt;
      btn.title = val ? "只看适用于「" + txt + "」的内置命令"
                      : "显示全部内置命令";
      btn.addEventListener("click", () => {
        if (builtinScope === val) return;
        builtinScope = val;
        persistPref("builtin_scope", builtinScope);
        renderAllWs();
      });
      bar.appendChild(btn);
    });
    return bar;
  }

  /* 最近的「会裁剪内容」的祖先（overflow 非 visible），用于判断菜单能往哪弹。
     命令列表就住在 `#cmd-groups { overflow:auto }` 里，菜单超出它的底边会被
     直接裁掉——不是被别的按钮压住，而是根本没画出来。 */
  function chipClipBox(el) {
    let p = el.parentElement;
    while (p && p !== document.body) {
      const cs = getComputedStyle(p);
      if (/(auto|scroll|hidden)/.test(cs.overflowY)) return p;
      p = p.parentElement;
    }
    return null;
  }

  /* 展开 / 收起卡片的 ⋯ 菜单（复制 / 修改 / 删除）。

     两个坑都在这一处收口：

     1) 层级。「菜单被下面的按钮压住」的根因不是 popup 的 z-index 不够小：
        popup 是 kebab 的子节点，kebab 一带 z-index（is-open 时的 30）就自成
        层叠上下文，popup 的 20 只在这个小上下文里比较，出不来。此时若再有一
        层祖先参与层叠（或 WebView 对 flex item 的处理不同），DOM 顺序更靠后
        的卡片就会整块压在菜单上。对策是把**整张卡片**抬到 30 —— 菜单跟着上
        去，与「谁先谁后」无关。

     2) 裁剪。列表在 `#cmd-groups { overflow:auto }` 里，最后一两行命令的菜单
        向下弹出时会超出滚动容器底边被裁。这里量一遍上下剩余空间，下方放不下
        且上方更宽裕就改成向上弹（.chip-menu-up）。 */
  function setChipMenu(chip, menu, open) {
    menu.classList.toggle("is-open", open);
    chip.classList.toggle("chip-menu-open", open);
    if (!open) {
      chip.classList.remove("chip-menu-up");
      // 焦点若还留在 kebab 上，CSS 的 :focus-within 会把 popup 继续显示着，
      // 而整卡的抬层刚刚已经撤了 —— 菜单就成了「显示着却被兄弟卡片压住」的
      // 僵尸态（点一下 ⋯ 后层级骤降正是这条路径：hover 先开 → 点击 toggle
      // 关闭 → 焦点留在 kebab 上维持显示）。收起时把焦点一并交还，让「显示」
      // 与「抬层」同进同退。
      if (menu.contains(document.activeElement)) menu.blur();
      return;
    }
    const popup = menu.querySelector(".chip-popup");
    if (!popup) return;
    const cr = chip.getBoundingClientRect();
    const h = popup.offsetHeight || 96;
    const box = chipClipBox(chip);
    const boxTop = box ? box.getBoundingClientRect().top : 0;
    const boxBottom = box ? box.getBoundingClientRect().bottom : window.innerHeight;
    const below = boxBottom - cr.bottom;
    const above = cr.top - boxTop;
    chip.classList.toggle("chip-menu-up", below < h + 8 && above > below);
  }

  /* 同一时刻只允许一张卡的 ⋯ 菜单开着：开另一张之前把别家先收掉。
     没有这条约束时，触摸屏上依次点两个 ⋯ 会同时开着两份菜单，各自都抬层，
     视觉上「谁在上」取决于 DOM 顺序而不是用户的最新意图。 */
  function closeOpenChipMenus(exceptChip) {
    document.querySelectorAll(".cmd-chip.chip-menu-open").forEach((ch) => {
      if (ch === exceptChip) return;
      const kb = ch.querySelector(".chip-kebab");
      if (kb) setChipMenu(ch, kb, false);
    });
  }
  // 点空白处（任何不在 ⋯/菜单上的地方）收起所有展开中的菜单：触摸屏没有
  // hover，「点一下开、点别处收」是唯一说得通的开合方式。
  document.addEventListener("click", (ev) => {
    const t = ev.target;
    if (t && t.closest && t.closest(".chip-kebab")) return;   // ⋯ 自己管（已 stopPropagation，双保险）
    closeOpenChipMenus(null);
  });

  /* 单张指令卡。抽成函数是因为同一条命令可能出现在多个分组里（用户组 /
     内置组共用一套渲染）——同一套卡片逻辑不能抄两遍，否则改角标 / 菜单时
     必然漏掉一边。 */
  function mkCmdChip(c, wsId) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "cmd-chip"; chip.title = c.name;
    // 拖动排序靠这个 id 认「哪条命令被挪到了哪儿」：DOM 顺序只是一时的画面，
    // 真正落盘的是 id 序列（同名 / 重排 / 过滤后重建都不会错位）。
    chip.dataset.cmdId = c.id || "";
    if (c.builtin) {
      // 程序内置默认命令：加角标样式 + 提示，便于与用户自定义区分
      chip.classList.add("cmd-chip--builtin");
      chip.title = c.name + "（程序内置默认，可在 quick_commands.json 用相同 id 覆盖）";
    }
    if (c.inputOnly) {
      // electerm「仅输入」模式：点击只填入输入框，不直接执行
      chip.classList.add("cmd-chip--inputonly");
      chip.title = c.name + "（仅输入：点击填入上方输入框，确认后点「执行」）";
    }
    const lbl = document.createElement("span");
    lbl.className = "chip-label"; lbl.textContent = c.name;
    chip.appendChild(lbl);
    if (c.builtin) {
      // 适用设备小角标（通用 / 车机 / 手机）：说明「这条命令在哪类设备上
      // 有意义」，不影响是否可执行；无法识别的 scope 按「通用」显示。
      const sc = scopeNameOf(c);
      const tag = document.createElement("span");
      tag.className = "chip-scope chip-scope--" + (SCOPE_CLASS[sc] || "comm");
      tag.textContent = sc;
      chip.appendChild(tag);
    }
    // 用户自定义命令：右侧固定 ⋯ 菜单（hover 弹出 复制 / 修改 / 删除）；内置命令不可改
    if (!c.builtin) {
      const menu = document.createElement("span");
      menu.className = "chip-kebab";
      menu.tabIndex = 0;
      menu.setAttribute("role", "button");
      menu.setAttribute("aria-label", "更多操作");
      menu.title = "更多操作（复制 / 修改 / 删除）";
      // 点击 kebab：阻止冒泡（不触发整张卡片的「执行」命令）。
      // 这里只负责「打开」，不再 toggle：悬停先开的菜单被点击 toggle 关掉后，
      // 焦点留在 kebab 上、:focus-within 继续显示 popup，而抬层已撤 —— 就是
      // 用户报的「点一下 ⋯ 后菜单层级变低」。收起交给移开 / 点别处 / 失焦。
      menu.addEventListener("click", (ev) => {
        ev.stopPropagation();
        closeOpenChipMenus(chip);   // 别家的先收，同一时刻只开一张
        openMenu(true);
      });
      // 键盘 Tab 聚焦 / 失焦同样走 setChipMenu：:focus-within 只负责显示、
      // 不会抬整卡，不走这里就会复现「显示着却被压住」的同一坑。
      menu.addEventListener("focus", () => openMenu(true));
      menu.addEventListener("blur", () => openMenu(false));

      // 纵向三点（kebab）SVG 图标：比字符 ⋮ 更均匀、清晰
      const dots = document.createElement("span");
      dots.className = "chip-kebab-dot";
      dots.innerHTML =
        '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">' +
        '<circle cx="12" cy="5" r="1.9"></circle>' +
        '<circle cx="12" cy="12" r="1.9"></circle>' +
        '<circle cx="12" cy="19" r="1.9"></circle>' +
        "</svg>";
      menu.appendChild(dots);

      // hover / 聚焦时弹出的功能菜单
      const popup = document.createElement("span");
      popup.className = "chip-popup";
      const ICONS = {
        dup: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"></rect><path d="M5 15V5a2 2 0 0 1 2-2h10"></path></svg>',
        edit: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"></path><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"></path></svg>',
        del: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"></path><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path></svg>',
      };
      const mkItem = (icon, label, cls, fn) => {
        const it = document.createElement("span");
        it.className = "chip-popup-item" + (cls ? " " + cls : "");
        it.innerHTML = '<span class="ic">' + icon + "</span>" + label;
        it.addEventListener("click", (ev) => { ev.stopPropagation(); setChipMenu(chip, menu, false); fn(c); });
        return it;
      };
      popup.appendChild(mkItem(ICONS.dup, "复制", "", duplicateCmd));
      popup.appendChild(mkItem(ICONS.edit, "修改", "", openCmdEdit));
      popup.appendChild(mkItem(ICONS.del, "删除", "chip-popup-item--del", deleteCmd));
      menu.appendChild(popup);
      // 展开状态统一走 setChipMenu：除了切 kebab 自身的 is-open，还要把**整张卡片**
      // 抬到兄弟之上（原因见 setChipMenu 注释），并按剩余空间决定向上还是向下弹。
      const openMenu = (open) => setChipMenu(chip, menu, open);
      // 鼠标移入显示、移出延迟隐藏：覆盖 kebab↔popup 之间的斜向死区。
      // popup 是 kebab 的子节点，指针从 kebab 移到 popup 不会触发 mouseleave，
      // 因此斜向下移动时菜单不会误关闭；延迟 160ms 也给快速穿过死区留出缓冲。
      let hideTimer = null;
      menu.addEventListener("mouseenter", () => {
        if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; }
        openMenu(true);
      });
      menu.addEventListener("mouseleave", () => {
        hideTimer = setTimeout(() => openMenu(false), 160);
      });
      menu._openMenu = openMenu;   // click 分支复用同一套抬层逻辑
      chip.appendChild(menu);
    }
    // 长按拖动松手后浏览器还会补一个 click：这段时间内把 click 吃掉，
    // 否则「只是排个序」会顺手把那条命令真的执行一遍。
    chip.addEventListener("click", (ev) => {
      if (Date.now() < cmdClickGuard) { ev.stopPropagation(); return; }
      runQuickCommand(c, wsId);
    });
    return chip;
  }

  /* ---------------- 指令卡排序：长按拖动 ----------------
     两套排序权并存：
       * 没拖过的分组 —— 按点击频次降序（常用靠前，历史行为不变）；
       * 拖过的分组   —— 以 config.json 的 cmd_order（逗号分隔命令 id）为准。
     只把「被拖的那个分组」的 id 写进 cmd_order：顺手拖一张卡不该把其它分组的
     自动排序一起冻住，之后常用的命令照样能自己浮上来。 */

  let cmdOrder = [];                    // 手动排过序的命令 id（按先后）
  let cmdDrag = null;                   // 拖动会话：{chip, wrap, timer, active}
  let cmdClickGuard = 0;                // 拖动结束后压制紧随其后的 click（时间戳）
  const CMD_LONGPRESS_MS = 400;         // 按住多久算「要拖」而不是「要执行」
  const CMD_DRAG_SLOP = 8;              // 长按判定前允许的手抖像素（超了就是滚动/误触）

  /* ---- 工具区子 tab 长按拖动排序（截图 / 录屏 / 投屏 / 安装 / 诊断）----
     与指令卡同一套长按手势：子 tab 按钮整颗可长按拖动重排；短按是切换子 tab，
     长按才进入拖动态，松手若真的拖过就压制随后的 click，避免一次操作既换位又切换。
     落盘 tool_tab_order（顺序）与 tool_active_tab（上次停留项），下次启动照旧。 */
  let toolTabOrder = [];                // 手动排过序的子 tab key（按先后）
  let toolActiveTab = "";               // 当前停留的子 tab key（用于「值没变就不写盘」）
  let lcActiveTab = "";                 // Logcat 子 tab（落盘抓取 / 实时监控）当前项
  let toolTabDrag = null;               // 拖动会话：{tab, x, y, timer, active}
  let toolTabClickGuard = 0;            // 拖动结束后压制紧随其后的 click（避免既换位又切换）
  const TOOL_LONGPRESS_MS = 400;        // 与指令卡一致：按住多久算「要拖」
  const TOOL_DRAG_SLOP = 8;             // 长按判定前允许的手抖像素
  const TOOL_GRIP_SVG =
    '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">' +
    '<circle cx="9" cy="6" r="1.6"/><circle cx="15" cy="6" r="1.6"/>' +
    '<circle cx="9" cy="12" r="1.6"/><circle cx="15" cy="12" r="1.6"/>' +
    '<circle cx="9" cy="18" r="1.6"/><circle cx="15" cy="18" r="1.6"/></svg>';

  function loadCmdOrder(raw) {
    cmdOrder = String(raw || "").split(",").map((s) => s.trim()).filter(Boolean);
  }

  // 组内排序：手动序 > 点击频次 > 名称。没进手动序的一律排在手动序之后。
  function sortCmdGroup(list) {
    return list.slice().sort((a, b) => {
      const ia = cmdOrder.indexOf(a.id), ib = cmdOrder.indexOf(b.id);
      if (ia >= 0 && ib >= 0) return ia - ib;
      if (ia >= 0) return -1;
      if (ib >= 0) return 1;
      const d = (b.clickCount || 0) - (a.clickCount || 0);
      return d !== 0 ? d : (a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
    });
  }

  // 落盘：被拖分组的完整顺序追加到 cmd_order 尾部（组内相对顺序才是有效信息，
  // 跨组不比较），顺手剔除已删除命令的 id，免得配置越滚越长。
  function saveCmdGroupOrder(ids) {
    const set = new Set(ids);
    const alive = new Set(allCommands.map((c) => c.id));
    cmdOrder = cmdOrder.filter((x) => !set.has(x)).concat(ids).filter((x) => alive.has(x));
    persistPref("cmd_order", cmdOrder.join(","));
  }

  function cmdChipTarget(ev) {
    const t = ev.target;
    if (!t || !t.closest) return null;
    if (t.closest(".chip-kebab")) return null;   // 三点菜单自己管点击，别抢
    return t.closest(".cmd-chip");
  }

  function endCmdDrag(reset) {
    const drag = cmdDrag;
    cmdDrag = null;
    if (!drag) return;
    if (drag.timer) { clearTimeout(drag.timer); drag.timer = null; }
    drag.chip.classList.remove("is-dragging");
    if (drag.wrap) drag.wrap.classList.remove("is-sorting");
    document.body.classList.remove("cmd-sorting");
    if (reset) applyCmdFilter();
  }

  // 长按计时器到点：正式进入拖动态（此时才改变视觉，短按不受影响）
  function beginCmdDrag() {
    const drag = cmdDrag;
    if (!drag) return;
    drag.timer = null;
    drag.active = true;
    drag.chip.classList.add("is-dragging");
    if (drag.wrap) drag.wrap.classList.add("is-sorting");
    document.body.classList.add("cmd-sorting");
  }

  function onCmdPointerDown(ev) {
    if (ev.button !== undefined && ev.button !== 0) return;   // 只认左键
    if (cmdDrag) endCmdDrag(false);
    const chip = cmdChipTarget(ev);
    if (!chip) return;
    cmdDrag = {
      chip: chip, wrap: chip.parentElement, active: false,
      x: ev.clientX || 0, y: ev.clientY || 0,
      timer: setTimeout(beginCmdDrag, CMD_LONGPRESS_MS),
    };
  }

  function onCmdPointerMove(ev) {
    const drag = cmdDrag;
    if (!drag) return;
    const x = ev.clientX || 0, y = ev.clientY || 0;
    if (!drag.active) {
      // 还没到长按时限就移动超阈值 = 用户想滚动 / 点别处，放弃这次长按
      if (Math.abs(x - drag.x) > CMD_DRAG_SLOP || Math.abs(y - drag.y) > CMD_DRAG_SLOP) {
        endCmdDrag(false);
      }
      return;
    }
    if (ev.cancelable) ev.preventDefault();
    const hit = (document.elementFromPoint ? document.elementFromPoint(x, y) : null);
    const over = hit && hit.closest ? hit.closest(".cmd-chip") : null;
    // 只在本组内换位：跨组拖动等于改分组，那是另一件事（改命令的标签）
    if (!over || over === drag.chip || over.parentElement !== drag.wrap) return;
    const r = over.getBoundingClientRect();
    const after = x > r.left + r.width / 2;   // 落点在中线右侧 → 插到它后面
    drag.wrap.insertBefore(drag.chip, after ? over.nextSibling : over);
  }

  function onCmdPointerUp() {
    const drag = cmdDrag;
    if (!drag) return;
    if (!drag.active) { endCmdDrag(false); return; }   // 短按 = 普通点击，交给 click
    const ids = Array.from(drag.wrap.querySelectorAll(".cmd-chip"))
      .map((el) => el.dataset.cmdId).filter(Boolean);
    endCmdDrag(false);
    cmdClickGuard = Date.now() + 350;
    saveCmdGroupOrder(ids);
    applyCmdFilter();   // 按新的 cmd_order 重排重绘（顺序与落盘结果一致）
    pushStatus("info", "✓ 指令顺序已保存（长按卡片可再次调整）");
  }

  /* 长按拖动排序：pointerdown 绑在**每个工作区**的命令列表上（各 tab 都能拖），
     move / up 只往 window 上绑一次 —— 拖动中指针很可能已经移出卡片甚至移出容器，
     挂在卡片上会收不到 update 而卡在「拖住不放」。 */
  let _cmdDragWindowBound = false;
  function bindCmdDrag(host) {
    if (!host) return;
    host.addEventListener("pointerdown", onCmdPointerDown);
    if (_cmdDragWindowBound) return;
    _cmdDragWindowBound = true;
    window.addEventListener("pointermove", onCmdPointerMove, { passive: false });
    window.addEventListener("pointerup", onCmdPointerUp);
    window.addEventListener("pointercancel", () => endCmdDrag(true));
    // 在窗口外松手收不到 pointerup：失焦也当作结束，免得卡在「拖住不放」的状态
    window.addEventListener("blur", () => endCmdDrag(true));
    // 触摸长按会同时触发系统的 contextmenu（弹「复制/粘贴」），拖动态里必须挡掉
    window.addEventListener("contextmenu", (ev) => {
      if (cmdDrag && cmdDrag.active) ev.preventDefault();
    });
  }

  /* ---------------- 命令增删改（界面实时编辑，反向同步 quick_commands.json） ----------------
     每条用户命令右侧固定 ⋯ 菜单（hover 弹出 复制 / 修改 / 删除）；顶部「＋ 新建命令」打开弹窗。
     保存时把「用户自定义命令」整体回写后端（内置默认由 merge_builtins 在加载时补齐，
     不写进用户文件）。后端 save_commands 原子写回 + 同步内存态。 */

  // 把多行命令文本解析为 [{command, delay}]；行尾 ||delay=N 设置该条下发后等待毫秒
  function parseCmdLines(text) {
    return (text || "").split("\n").map((s) => s.trim()).filter(Boolean).map((line) => {
      let delay = 0;
      const m = line.match(/\|\|delay=(\d+)\s*$/);
      if (m) { delay = parseInt(m[1], 10) || 0; line = line.replace(/\|\|delay=\d+\s*$/, "").trim(); }
      return { command: line, delay };
    });
  }

  // 收集需要写回文件的「用户命令」：过滤掉内置默认（builtin），保留点击计数
  function collectUserCommands() {
    return allCommands.filter((c) => !c.builtin).map((c) => ({
      id: c.id, name: c.name,
      labels: (c.labels && c.labels.length) ? c.labels : ["其他"],
      commands: c.commands || [],
      clickCount: c.clickCount || 0,
      inputOnly: !!c.inputOnly,
    }));
  }

  // 打开编辑弹窗：c 为 null 表示新建；c.id 为空（如「复制」克隆）也按新建处理
  function openCmdEdit(c) {
    const editing = !!(c && c.id);
    els.cmdEdit.dataset.id = (c && c.id) ? c.id : "";
    els.cmdEditTitle.textContent = editing ? "编辑命令" : "新建命令";
    els.cmdEditName.value = c ? c.name : "";
    els.cmdEditLabels.value = c ? (c.labels || []).join(", ") : "";
    els.cmdEditCmds.value = c ? (c.commands || []).map(
      (e) => e.command + (e.delay ? (" ||delay=" + e.delay) : "")).join("\n") : "";
    els.cmdEditInputOnly.checked = c ? !!c.inputOnly : false;
    els.cmdEditDelete.hidden = !editing;   // 新建 / 克隆时不显示删除
    els.cmdEditModal.classList.remove("hidden");
    els.cmdEditName.focus();
  }
  function closeCmdEdit() {
    els.cmdEditModal.classList.add("hidden"); els.cmdEdit.dataset.id = "";
  }

  // 保存（新增 / 编辑共用）：乐观更新 + 后端回写；失败回滚内存态
  async function saveCmdEdit() {
    const name = (els.cmdEditName.value || "").trim();
    if (!name) { pushStatus("warn", "⚠ 名称不能为空"); els.cmdEditName.focus(); return; }
    const labels = (els.cmdEditLabels.value || "").split(/[,，]/)
      .map((s) => s.trim()).filter(Boolean);
    const cmds = parseCmdLines(els.cmdEditCmds.value);
    if (!cmds.length) { pushStatus("warn", "⚠ 至少要填写一条命令"); els.cmdEditCmds.focus(); return; }
    const inputOnly = !!els.cmdEditInputOnly.checked;
    const editingId = els.cmdEdit.dataset.id || "";
    const backup = allCommands.map((c) => ({ ...c }));   // 失败回滚用
    if (editingId) {
      const c = allCommands.find((x) => x.id === editingId);
      if (c) { c.name = name; c.labels = labels.length ? labels : ["其他"]; c.commands = cmds; c.inputOnly = inputOnly; }
    } else {
      const nid = "u_" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
      allCommands.push({ id: nid, name, labels: labels.length ? labels : ["其他"],
        commands: cmds, clickCount: 0, inputOnly });
    }
    const user = collectUserCommands();
    const res = await callApi(api.save_commands(user));
    if (!res || !res.ok) {
      allCommands = backup.map((c) => ({ ...c }));
      pushStatus("err", "⚠ 保存失败，命令未改动（可重试）");
      return;
    }
    closeCmdEdit();
    renderAllWs();
  }

  // 删除命令（同步回写文件）
  async function deleteCmd(c) {
    if (!c) return;
    // 自绘确认（不是 window.confirm）：pywebview 部分版本里 confirm 是空函数，
    // 返回 undefined → `!confirm(...)` 恒为 true，等于**删命令不确认**。
    const yes = await askConfirm({
      title: "删除命令", text: "确定删除命令「" + c.name + "」？此操作不可恢复。",
      yes: "删除", danger: true,
    });
    if (!yes) return;
    const backup = allCommands.map((x) => ({ ...x }));
    const i = allCommands.findIndex((x) => x.id === c.id);
    if (i >= 0) allCommands.splice(i, 1);
    const user = collectUserCommands();
    const res = await callApi(api.save_commands(user));
    if (!res || !res.ok) {
      allCommands = backup.map((x) => ({ ...x }));
      pushStatus("err", "⚠ 删除失败（可重试）");
      return;
    }
    renderAllWs();
  }

  // 复制（克隆）命令：用现有数据预填编辑弹窗，另起新 id，保存即成一条新命令
  function duplicateCmd(c) {
    if (!c) return;
    const clone = {
      id: "",  // 空 id = 新建
      name: c.name + " 副本",
      labels: (c.labels || []).slice(),
      commands: (c.commands || []).map((e) => ({ ...e })),
      inputOnly: !!c.inputOnly,
    };
    openCmdEdit(clone);
  }

  /* ---------------- 命令导入 / 导出（备份 & 分享） ---------------- */

  // 导出：拉取用户命令 JSON，展示在弹窗里，可复制或落盘为文件
  async function exportCmd() {
    if (!api || !api.export_commands) return;
    const data = await callApi(api.export_commands());
    if (!data || !data.ok) {
      pushStatus("err", "⚠ 导出失败：" + ((data && data.reason) || "未知"));
      return;
    }
    const text = JSON.stringify(data.commands || [], null, 2);
    els.cmdExportText.value = text;
    els.cmdExportModal.classList.remove("hidden");
  }
  function closeCmdExport() { els.cmdExportModal.classList.add("hidden"); }
  async function copyExport() {
    const text = els.cmdExportText.value || "";
    try {
      await navigator.clipboard.writeText(text);
      pushStatus("ok", "✓ 已复制到剪贴板");
    } catch (e) {
      // 回退：选中文本由用户手动复制（pywebview 某些内核无剪贴板 API）
      els.cmdExportText.removeAttribute("readonly");
      els.cmdExportText.focus(); els.cmdExportText.select();
      try { document.execCommand("copy"); pushStatus("ok", "✓ 已复制（兼容模式）"); }
      catch (e2) { pushStatus("warn", "请手动选中复制"); }
      els.cmdExportText.setAttribute("readonly", "");
    }
  }
  async function saveExportFile() {
    if (!api || !api.export_commands_save) return;
    const data = await callApi(api.export_commands_save());
    if (!data || !data.ok) {
      pushStatus("err", "⚠ 保存失败：" + ((data && data.reason) || "未知"));
      return;
    }
    pushStatus("ok", "✓ 已导出到：" + data.path);
    // 保存成功：toast 轻提示 + 关闭弹窗（不再自动打开导出文件，避免多弹一个窗口）
    showToast("ok", "✓ 已保存到文件");
    closeCmdExport();
  }

  // 导入：优先走后端原生文件对话框（默认定位程序目录），否则降级为本地文件输入
  async function importCmdFromDialog() {
    if (!api) return;
    if (api.import_commands_dialog) {
      const data = await callApi(api.import_commands_dialog());
      if (!data || !data.ok) {
        // 用户取消选择（reason=cancelled）不提示；其它错误给出提示
        if (data && data.reason && data.reason !== "cancelled") {
          pushStatus("err", "⚠ 导入失败：" + data.reason);
        }
        return;
      }
      await reloadCommands();
      pushStatus("ok", "✓ 已导入（新增 %d 条，共 %d 条）"
        .replace("%d", data.added).replace("%d", data.total));
      return;
    }
    // 降级：不支持原生对话框时退回浏览器文件选择
    if (els.cmdImportFile) els.cmdImportFile.click();
  }

  // 导入：读取本地 JSON 文件，合并回写；支持列表 / {commands:[...]} / JSON 字符串
  async function importCmdFromFile(file) {
    if (!file) return;
    if (!api || !api.import_commands) return;
    let text;
    try { text = await file.text(); }
    catch (e) {
      // 老内核无 file.text()，回退 FileReader
      text = await new Promise((res, rej) => {
        const r = new FileReader();
        r.onload = () => res(r.result || ""); r.onerror = rej;
        r.readAsText(file);
      });
    }
    const data = await callApi(api.import_commands(text));
    if (!data || !data.ok) {
      pushStatus("err", "⚠ 导入失败：" + ((data && data.reason) || "未知"));
      return;
    }
    // 重新拉取最新命令列表（保证内置默认 + 导入结果一致）
    await reloadCommands();
    pushStatus("ok", "✓ 已导入（新增 %d 条，共 %d 条）"
      .replace("%d", data.added).replace("%d", data.total));
  }

  // 重新从后端加载命令（导入 / 外部改动后刷新）
  async function reloadCommands() {
    if (!api || !api.load_commands) return;
    const data = await callApi(api.load_commands());
    if (data && data.ok && Array.isArray(data.commands)) {
      allCommands = data.commands;
      renderAllWs();
    }
  }

  /* 快捷指令点击：
      * inputOnly（electerm 仅输入模式）—— 只把命令文本填进指令输入框，
        由用户确认后手动「执行」，不直接下发（防手滑直接跑危险/长命令）；
      * 其余 —— 直接下发，不再对命令内容做二次确认。 */
  function runQuickCommand(c, wsId) {
    if (c && c.inputOnly) { fillCmdInput(c, wsId); return; }
    callApi(api.run_command(c.id, (wsOf(wsId) || curWs()).id));
  }

  /* 仅输入模式：把命令文本并入输入框（多条子命令用 "; " 连接，PowerShell
     语句分隔符），聚焦输入框等用户确认。保留「保留输入内容」开关的语义——
     这里是用户主动点击填入，不受该开关影响。 */
  function fillCmdInput(c, wsId) {
    const ws = wsOf(wsId) || curWs();
    const text = (c.commands || []).map((e) => e.command).filter(Boolean).join("; ");
    if (!text) { pushStatus("warn", "⚠ 该命令没有可填入的文本"); return; }
    if (!ws || !ws.inputEl) return;
    ws.inputEl.value = text;
    if (ws.inputClearEl) ws.inputClearEl.hidden = !ws.inputEl.value;
    ws.inputEl.focus();
    pushStatus("info", "⌨ 已填入输入框（仅输入模式，确认后点「执行」）：" + c.name);
  }

  function clearCmdFilter(ws) {
    ws = ws || curWs();
    if (!ws) return;
    if (ws.filterEl) ws.filterEl.value = "";
    if (ws.clearFilterBtn) ws.clearFilterBtn.hidden = true;   // 清完立即隐藏 clear-x
    ws.tags.clear();
    renderCmdTags(ws);
    applyCmdFilter(ws);
    // 清空也要落盘，否则下次启动过滤词又冒出来（用户会以为没清掉）。
    // 只记默认工作区的那一份：多个 tab 各存一个过滤词进 config.json 交叉覆盖，
    // 重启后谁也恢复不成自己原本的样子，不如只保定一个。
    if (ws.id === "w1") persistPref("cmd_filter", "");
  }

  function runInput(ws) {
    ws = ws || curWs();
    if (!ws || !ws.inputEl) return;
    const text = ws.inputEl.value.trim();
    if (!text) return;
    callApi(api.run_custom(text, ws.id));
    // 命令历史（跨工作区共享、落盘）：每次执行后推入数组，↑↓ 翻历史时用。
    // 紧邻重复不重复入队（否则连发 10 次 adb devices 会让历史里全是一样的）。
    _pushCmdHistory(text);
    // 翻历史状态复位：Enter 执行后下次按 ↑ 应该回到「最新一条」。
    ws._histIdx = -1;
    ws._histDraft = "";
    // 「保留输入内容」勾选项（默认开启）：
    //  * 开启 —— 执行后保留输入框内容，方便改几个字再重发（长命令尤其顺手）；
    //  * 关闭 —— 每次执行后清空输入框，适合连发一条条不同的命令。
    // 命令文本已在上面捕获并下发，此时清空不影响本次执行。
    if (ws.keepEl && !ws.keepEl.checked) {
      ws.inputEl.value = "";
      if (ws.inputClearEl) ws.inputClearEl.hidden = true;
    }
  }

  /* ---------------- 指令台：↑↓ 翻历史 + Tab 补全 ----------------
     ↑↓：每个工作区各自记 _histIdx / _histDraft，草稿在翻出第一条之前原样保存、
     翻回去（↓ 超过最新一条）恢复。跨工作区共享的是 cmdHistory 数组本身（落盘）。
     Tab：只做「第一词命令名补全」，候选来自 BUILTIN_CMD_FIRST_WORDS + 用户卡片里
     的命令。连续 Tab 在同一前缀下循环候选；前缀一变重置循环。 */
  function _cmdHistoryNav(ws, dir) {
    if (!ws || !ws.inputEl || !cmdHistory.length) return;
    _loadCmdHistory();
    // 翻之前先原样保存草稿（还没存过 / 位置刚被重置时）
    if (ws._histIdx < 0) ws._histDraft = ws.inputEl.value;
    ws._histIdx = Math.min(cmdHistory.length - 1, ws._histIdx + dir);
    if (ws._histIdx < -1) ws._histIdx = -1;
    if (ws._histIdx < 0) {
      // ↓ 越过最新一条：回到用户原来的草稿
      ws.inputEl.value = ws._histDraft;
    } else {
      ws.inputEl.value = cmdHistory[cmdHistory.length - 1 - ws._histIdx];
    }
    if (ws.inputClearEl) ws.inputClearEl.hidden = !ws.inputEl.value;
    // 循环 Tab 补全的前缀也跟着翻历史重置：翻完再按 Tab 应该从新前缀重新补全
    ws._tabCycleIdx = -1;
    ws._tabCyclePrefix = ws.inputEl.value.trim();
  }

  function _collectCmdCompletions(prefix) {
    // 候选来源：① BUILTIN_CMD_FIRST_WORDS 里的 adb/PowerShell 命令
    //          ② allCommands 里用户卡片的命令（label / name / 每条 .command 首部词）
    //          ③ cmdHistory 里敲过的命令（可能有用户自己定义的、上面两类没有的）
    const p0 = (prefix || "").toLowerCase();
    const seen = new Set();
    const out = [];
    function push(x) {
      const v = (x || "").trim();
      if (!v) return;
      if (seen.has(v)) return;
      seen.add(v);
      out.push(v);
    }
    // ① 内置 adb / PowerShell 命令名（前缀匹配）
    BUILTIN_CMD_FIRST_WORDS.forEach((c) => {
      if (!p0 || c.toLowerCase().startsWith(p0)) push(c);
    });
    // ② 用户卡片里的命令名
    (allCommands || []).forEach((c) => {
      if (!c || !c.name) return;
      if (!p0 || c.name.toLowerCase().startsWith(p0)) push(c.name);
      (c.commands || []).forEach((e) => {
        const first = ((e && e.command) || "").trim().split(/\s+/)[0];
        if (first && (!p0 || first.toLowerCase().startsWith(p0))) push(first);
      });
    });
    // ③ 历史里敲过的（去重 + 前缀匹配）
    cmdHistory.forEach((h) => {
      const first = (h || "").trim().split(/\s+/)[0];
      if (first && (!p0 || first.toLowerCase().startsWith(p0))) push(first);
    });
    out.sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
    return out;
  }

  function _cmdTabComplete(ws, shiftBackward) {
    if (!ws || !ws.inputEl) return false;
    const val = ws.inputEl.value;
    // 光标必须在第一词范围（或刚好在第一词末尾）——否则是在补参数/路径，这版不做
    const firstSpace = val.search(/\s/);
    const firstWord = (firstSpace < 0 ? val : val.slice(0, firstSpace));
    if (/\s/.test(firstWord)) return false;          // 第一词含空格，说明已经在补参数
    const candidates = _collectCmdCompletions(firstWord);
    if (!candidates.length) return false;
    // 连续 Tab 循环：按原始前缀重置；Shift+Tab 反向
    if (ws._tabCyclePrefix !== firstWord.toLowerCase()) {
      ws._tabCycleIdx = -1;
      ws._tabCyclePrefix = firstWord.toLowerCase();
    }
    if (shiftBackward) ws._tabCycleIdx -= 1;
    else ws._tabCycleIdx += 1;
    if (ws._tabCycleIdx >= candidates.length) ws._tabCycleIdx = 0;
    if (ws._tabCycleIdx < 0) ws._tabCycleIdx = candidates.length - 1;
    const picked = candidates[ws._tabCycleIdx];
    ws.inputEl.value = picked + val.slice(firstWord.length);
    if (ws.inputClearEl) ws.inputClearEl.hidden = !ws.inputEl.value;
    // 补全完还在第一词范围：再按一次 Tab 继续循环
    return true;
  }

  /* ---------------- Logcat ---------------- */
  function lcBuffersFor(serial) {
    if (!lcBuffers[serial]) lcBuffers[serial] = { lines: [], total: 0, exc: 0 };
    return lcBuffers[serial];
  }
  function onLogcat(p) {
    const serial = p.serial;
    if (p.status === "clear") {
      lcBuffers[serial] = { lines: [], total: 0, exc: 0 };
      clearLcQueue();
    }
    if (p.status === "append") {
      // 会话已结束（点了停止 / 设备被移除 / 启动失败回滚）后的在途 append：
      // 直接丢弃。它们属于死会话，继续入队只会让「停止」迟迟停不下来。
      if (lcDropping && serial === lcSerial) return;
      const buf = lcBuffersFor(serial);
      const lines = p.lines || [];
      for (const ln of lines) buf.lines.push(ln);
      // 累计值优先信任后端（后端按整段统计，前端收到的可能只是被过滤/截断的部分）：
      // 只在后端没给值时才在前端累加。否则「异常数」会永远停在 0——因为本批行
      // 里的 exc 标记可能全为 false，而后端统计的异常在更早的批次里。
      if (p.total != null) buf.total = p.total;
      else buf.total += lines.length;
      if (p.exc != null) buf.exc = p.exc;
      else for (const ln of lines) if (ln.exc) buf.exc += 1;
      if (buf.lines.length > LC_MAX_LINES)
        buf.lines.splice(0, buf.lines.length - LC_MAX_LINES);
      // 增量追加：入队后分帧渲染，避免一次插上千行形成长任务（卡顿主因）
      if (serial === lcSerial) {
        enqueueLogcatLines(p.lines || []);   // 分帧渲染，计数在帧里统一刷新
        return;
      }
    }
    // 会话类事件的按钮态保持无条件更新（历史行为：事件流即真相）；
    // 但「清队列 + 丢弃开关」只对当前监控设备生效 —— 后台设备的监控启停
    // 不该把前台的渲染机掐掉（多设备同时监控时）。
    if (p.status === "running") {
      if (serial === lcSerial) lcDropping = false;
      els.lcStatus.textContent = "采集中…"; setLcRunning(true);
    }
    if (p.status === "stopped") {
      // stopped 时清掉待渲染队列并打上丢弃开关 —— 设备被移除强停（无点击）
      // 的路径也靠它即时收住渲染机。
      if (serial === lcSerial) { lcDropping = true; clearLcQueue(); }
      els.lcStatus.textContent = "空闲"; setLcRunning(false);
    }
    if (p.status === "error") {
      if (serial === lcSerial) lcDropping = true;
      els.lcStatus.textContent = "错误"; setLcRunning(false); pushStatus("err", "⚠ " + (p.text || "logcat 错误"));
    }
    updateLcCounter(serial);
  }

  /* ---------------- Logcat 监控态 ----------------
     采集中把「停止」按钮切成红色实心并带轻微呼吸光晕，空闲时恢复默认样式。
     disabled 与配色一并在这里收口，避免红底灰字/状态不同步。 */
  function setLcRunning(running) {
    lcRunning = running;
    els.lcStop.disabled = !running;
    els.lcStart.disabled = running;
    els.lcStop.classList.toggle("danger", running);
    els.lcStop.classList.toggle("live", running);
    // 开工/收工都重算 pkg: 的定时解析（停机后不必再起 adb 子进程刷 pid）
    syncLcPkgTimer();
    // 开工这一下强制重解析：停机期间应用可能已经重启过，缓存里的 pid 早失效了，
    // 等 5 秒定时器才第一次解析的话，刚点开始会先看到一段「命中 0 行」。
    if (running) lcRefreshPkgPids(true);
  }

  /* 过滤表达式（与后端 core/logcat.py 的 split_filter_terms / match_filter
     同一套语义，改规则必须两处同步）：
       空格分隔 = AND；- 前缀 = 排除；
       tag:/msg:/pid:/tid:/level:/pkg: 指定字段；无前缀 = 整行原文包含。 */
  const LC_FILTER_FIELDS = ["tag:", "msg:", "pid:", "tid:", "level:", "pkg:"];
  // 「设备 + 包名」-> [pid...]，由后端 adb shell pidof 解析后缓存。pid 会随应用
  // 重启变化，所以监控中每 PKG_PID_REFRESH_MS 重新解析一次（见 lcRefreshPkgPids）。
  // 必须带上设备序列号：同一包名在不同设备上的 pid 毫无关系，只按包名缓存会在
  // 切换设备后拿上一台设备的 pid 去过滤，界面显示 0 行且看起来像过滤坏了。
  let lcPkgPids = {};
  let lcPkgTimer = null;
  // 已经提示过「这个包没解析到 pid」的「设备 + 包名」：pid 每 5 秒重解析一次，
  // 不去重的话状态栏会被同一句警告刷屏。
  let lcPkgEmptyWarned = {};
  const PKG_PID_REFRESH_MS = 5000;

  function lcPkgPidKey(serial, name) {
    return (serial || "") + "\n" + name;
  }

  function lcSplitTerms(kw) {
    const out = [];
    String(kw || "").trim().split(/\s+/).forEach((raw) => {
      if (!raw) return;
      const neg = raw.length > 1 && raw.charAt(0) === "-";
      const term = neg ? raw.slice(1) : raw;
      if (term) out.push({ neg: neg, term: term });
    });
    return out;
  }
  function lcMatchTerm(ln, term) {
    const low = String(term).toLowerCase();
    for (let i = 0; i < LC_FILTER_FIELDS.length; i++) {
      const p = LC_FILTER_FIELDS[i];
      if (low.indexOf(p) !== 0) continue;
      const pat = low.slice(p.length);
      if (!pat) return true;
      if (p === "tag:") return String(ln.tag || "").toLowerCase().indexOf(pat) >= 0;
      if (p === "msg:") return String(ln.msg || "").toLowerCase().indexOf(pat) >= 0;
      if (p === "pid:") return String(ln.pid || "") === pat;
      if (p === "tid:") return String(ln.tid || "") === pat;
      if (p === "level:") return pat.indexOf(String(ln.level || "").toLowerCase()) >= 0;
      if (p === "pkg:") {
        const pids = lcPkgPids[lcPkgPidKey(lcSerial, pat)] || [];
        return pids.indexOf(String(ln.pid || "")) >= 0;
      }
    }
    // 无前缀：整行原文（与旧行为一致，覆盖 tag/msg 之外的字段）
    return String(ln.raw || "").toLowerCase().indexOf(low) >= 0;
  }
  // 单行是否通过当前过滤条件（与全量重建共用判定）
  function linePassesFilter(ln, f) {
    if (!ln.level) return true;                 // 非 threadtime 行始终保留（纯文本）
    if (!f.levels.includes(ln.level)) return false;
    if (f.onlyExc && !ln.exc) return false;
    for (let i = 0; i < f.terms.length; i++) {
      const t = f.terms[i];
      const ok = lcMatchTerm(ln, t.term);
      if (t.neg ? ok : !ok) return false;
    }
    return true;
  }
  function makeLineNode(ln) {
    const d = document.createElement("div");
    if (!ln.level) {
      d.className = "lc-line raw"; d.textContent = ln.raw;
    } else {
      d.className = "lc-line lv_" + ln.level + (ln.exc ? " exc" : "");
      d.textContent = ln.raw;
    }
    return d;
  }
  /* 分帧渲染队列
     一次 take_events 可能带回上千行（logcat 启动瞬间尤其多）。若在同一个 tick
     里把它们全部插入 DOM，就会形成几百毫秒的长任务，主线程被独占 —— 这正是
     「一开始监控，滚动就没反应」的直接原因。这里把行压进队列，每帧只渲染
     一小批，帧与帧之间把主线程还给浏览器去处理滚动和输入。 */
  let lcQueue = [];
  let lcFrameId = null;
  let lcFrameIsRaf = false;

  function enqueueLogcatLines(lines) {
    if (!lines || !lines.length) return;
    for (let i = 0; i < lines.length; i++) lcQueue.push(lines[i]);
    if (lcQueue.length > LC_QUEUE_MAX)
      lcQueue.splice(0, lcQueue.length - LC_QUEUE_MAX);
    scheduleLcFrame();
  }
  function scheduleLcFrame() {
    if (lcFrameId !== null) return;
    const step = () => {
      lcFrameId = null;
      if (!lcQueue.length) { updateLcCounter(lcSerial); return; }
      const n = Math.min(lcQueue.length, LC_PER_FRAME);
      appendLogcatLines(lcQueue.splice(0, n));
      if (els.lcAuto.checked) scheduleLcScroll();
      // 还有积压就继续排下一帧，不在这里一口气干完
      if (lcQueue.length) scheduleLcFrame();
      else updateLcCounter(lcSerial);
    };
    if (window.requestAnimationFrame) {
      lcFrameIsRaf = true;
      lcFrameId = window.requestAnimationFrame(step);
    } else {
      lcFrameIsRaf = false;
      lcFrameId = setTimeout(step, 16);
    }
  }
  function clearLcQueue() {
    lcQueue.length = 0;
    if (lcFrameId === null) return;
    if (lcFrameIsRaf && window.cancelAnimationFrame) window.cancelAnimationFrame(lcFrameId);
    else if (!lcFrameIsRaf) clearTimeout(lcFrameId);
    lcFrameId = null;
  }

  // 增量渲染：把新行（已按当前过滤）追加到视图末尾，超出上限从头部裁剪
  function appendLogcatLines(lines) {
    const f = currentLcFilter();
    const frag = document.createDocumentFragment();
    let added = 0;
    for (const ln of lines) {
      if (!linePassesFilter(ln, f)) continue;
      frag.appendChild(makeLineNode(ln));
      added++;
    }
    if (added === 0) return;
    const view = els.lcView;
    view.appendChild(frag);
    // 裁剪头部超出 DOM 上限的节点，维持稳定内存/节点数（Range 一次删一片）
    const over = view.childElementCount - LC_VIEW_MAX;
    if (over <= 0) return;
    // 自动滚动时会直接滚到底，无需维护位置；回看时才需要补偿。
    // 框选期间同样要补偿：选区存在时强滚已让路，trim 掉头部行若不补位置，
    // 视图会整体上跳、选区跟着错位。
    const keepPos = !els.lcAuto.checked || lcHasSelection();
    const before = keepPos ? view.scrollHeight : 0;
    trimHead(view, LC_VIEW_MAX);
    // 用 scrollHeight 差值一次性补偿，避免逐行读 offsetHeight 造成的强制同步布局
    if (keepPos) {
      const delta = before - view.scrollHeight;
      if (delta > 0) view.scrollTop = Math.max(0, view.scrollTop - delta);
    }
  }
  // 视图内是否存在未折叠选区（用户正在/已经框选日志）。自动滚动必须给它让路：
  // 否则每个 append 都把视图拽到底，拖选时内容一直往下跑，根本选不中。选区
  // 一出现就停止强滚；用户点空白处取消选区后，自动滚动自然恢复。
  function lcHasSelection() {
    const sel = window.getSelection && window.getSelection();
    return !!(sel && !sel.isCollapsed && sel.anchorNode
      && els.lcView.contains(sel.anchorNode));
  }
  // 用 rAF 合并滚动请求，避免每个 append 事件都触发布局
  let lcScrollScheduled = false;
  function scheduleLcScroll() {
    if (lcScrollScheduled) return;
    lcScrollScheduled = true;
    const doScroll = () => {
      lcScrollScheduled = false;
      if (els.lcAuto.checked && !lcHasSelection()) {
        els.lcView.scrollTop = els.lcView.scrollHeight;
      }
    };
    if (window.requestAnimationFrame) window.requestAnimationFrame(doScroll);
    else setTimeout(doScroll, 16);
  }
  function updateLcCounter(serial) {
    // 没有缓冲（切设备 / 设备消失 / 清空）时也必须把计数刷成 0：视图已经空了，
    // 计数却留着上一台的「行数/异常」，与眼前的空视图自相矛盾。
    const buf = lcBuffers[serial];
    let text = "行数: " + (buf ? buf.total : 0)
      + " · 异常: " + (buf ? buf.exc : 0);
    // 关键字过滤时附上命中数：让用户知道「有 N 行匹配」，过滤没反应时至少能
    // 看出是「搜到了 0 行」还是「界面卡住」，而不是对着空视图发懵。
    if (lcFilterHits != null) {
      text += " · 命中: " + lcFilterHits;
    }
    els.lcCounter.textContent = text;
  }
  function currentLcFilter() {
    const kw = (els.lcFilter.value || "");
    const levels = Array.from(els.lcLevels.querySelectorAll("input:checked"))
      .map((c) => c.value);
    const onlyExc = els.lcOnlyExc.checked;
    return { kw: kw, terms: lcSplitTerms(kw), levels, onlyExc };
  }
  // 表达式里出现 pkg: 时，先把包名解析成 pid 再重渲染；已解析的直接复用缓存。
  // 只解析「尚未解析过」的包，避免每次击键都起一遍 adb 子进程。
  function lcPkgNamesToResolve(terms) {
    const out = [];
    terms.forEach((t) => {
      const low = t.term.toLowerCase();
      if (low.indexOf("pkg:") !== 0) return;
      const name = low.slice(4).trim();
      if (name && lcPkgPids[lcPkgPidKey(lcSerial, name)] === undefined
          && out.indexOf(name) < 0) {
        out.push(name);
      }
    });
    return out;
  }
  // 解析结果落缓存；解析为空（包没在跑 / 设备读不到进程）时在状态栏说明一次。
  // 否则界面上只有「命中 0 行」，用户会以为过滤表达式写坏了。
  function lcApplyPkgPids(serial, name, pids) {
    const key = lcPkgPidKey(serial, name);
    lcPkgPids[key] = pids;
    if (pids.length) { delete lcPkgEmptyWarned[key]; return; }
    // 已切到别的设备：先不提示，等切回来那一轮再提示（否则提示与界面上的设备不符）
    if (serial !== lcSerial || lcPkgEmptyWarned[key]) return;
    lcPkgEmptyWarned[key] = true;
    pushStatus("warn", "⚠ 没找到包 " + name + " 的运行中进程"
              + "（按包过滤将显示 0 行）");
  }
  function lcRefreshPkgPids(force) {
    if (!lcSerial) return;
    const serial = lcSerial;          // 固定本次请求对应的设备，供迟到响应比对
    const names = lcPkgNamesToResolve(lcSplitTerms(els.lcFilter.value));
    if (force) {
      // 上次解析为空（包当时没跑）的也重来一次：重新启用过滤 / 切回这台设备 /
      // 开始监控时，包可能已经起来了，不能因为缓存里躺着一个空数组就一直 0 行。
      lcSplitTerms(els.lcFilter.value).forEach((t) => {
        const low = t.term.toLowerCase();
        if (low.indexOf("pkg:") !== 0) return;
        const name = low.slice(4).trim();
        const key = lcPkgPidKey(serial, name);
        if (name && lcPkgPids[key] && !lcPkgPids[key].length
            && names.indexOf(name) < 0) {
          names.push(name);
        }
      });
    }
    if (!names.length) return;
    names.forEach((name) => {
      callApi(api.logcat_pidof(serial, name)).then((r) => {
        // 解析失败（设备忙 / 包没在跑）也记成空数组：否则每次重渲染都会
        // 重新发一遍请求，形成「一直在转圈」的假象。
        lcApplyPkgPids(serial, name,
                       (r && Array.isArray(r.pids)) ? r.pids : []);
        // 迟到响应只入缓存，不重绘：此时界面已经切到别的设备了
        if (serial === lcSerial) renderLogcat();
      }).catch(() => {
        lcApplyPkgPids(serial, name, []);
        if (serial === lcSerial) renderLogcat();
      });
    });
  }
  // 监控中且表达式含 pkg: 时，按固定间隔重解析 pid（应用重启后 pid 会变）
  function syncLcPkgTimer() {
    const hasPkg = lcSplitTerms(els.lcFilter.value).some(
      (t) => t.term.toLowerCase().indexOf("pkg:") === 0);
    if (!lcRunning || !hasPkg) {
      if (lcPkgTimer !== null) { clearInterval(lcPkgTimer); lcPkgTimer = null; }
      return;
    }
    if (lcPkgTimer === null) {
      lcPkgTimer = setInterval(() => {
        // 强制重解析：只清当前设备的缓存，别的设备的缓存留着（切回去还能用）
        const prefix = (lcSerial || "") + "\n";
        Object.keys(lcPkgPids).forEach((k) => {
          if (k.indexOf(prefix) === 0) delete lcPkgPids[k];
        });
        lcRefreshPkgPids();
      }, PKG_PID_REFRESH_MS);
    }
  }
  // 全量重建：仅用于过滤条件变更 / 切换设备 / 清空 / 初始化（增量追加以外的情形）
  function triggerLcFilter() {
    // 清掉防抖定时器 + 立即重渲染 + 落盘：右键菜单直接填入 tag:/pid: 时
    // 不能等 250ms 防抖才生效（用户会觉得"点了没反应"）。
    if (lcFilterTimer !== null) { clearTimeout(lcFilterTimer); lcFilterTimer = null; }
    persistPref("lc_keyword", els.lcFilter.value);
    // pkg: 条件先解析 pid 再渲染（否则第一次填进去会显示 0 行，随后才跳出来）
    lcRefreshPkgPids(true);
    syncLcPkgTimer();
    if (lcSerial) renderLogcat();
  }
  // 「按包」下拉的数据源：设备确定后异步拉一次包列表。失败（老系统没有
  // pm / 设备刚拔掉）就保持只有「（全部）」，不打断用户。
  function refreshLcPackages() {
    if (!els.lcPkg) return;
    if (!lcSerial) {
      els.lcPkg.innerHTML = '<option value="">（全部）</option>';
      return;
    }
    const serial = lcSerial;
    callApi(api.logcat_packages(serial)).then((r) => {
      if (serial !== lcSerial) return;   // 期间又切了设备，丢弃过期结果
      const pkgs = (r && Array.isArray(r.packages)) ? r.packages : [];
      let html = '<option value="">（全部）</option>';
      pkgs.forEach((p) => {
        // 包名原样输出到 value；显示上把包名截断得更紧凑些，长包名不撑破布局
        html += '<option value="' + escAttr(p) + '">' + escHtml(p) + '</option>';
      });
      els.lcPkg.innerHTML = html;
    }).catch(() => {});
  }
  function appendLcTerm(term) {
    // 追加到现有表达式末尾（不覆盖用户已写的条件）；已存在则不重复添加。
    const cur = (els.lcFilter.value || "").trim();
    const parts = cur ? cur.split(/\s+/) : [];
    if (parts.indexOf(term) >= 0) return;
    els.lcFilter.value = cur ? (cur + " " + term) : term;
    triggerLcFilter();
  }

  /* ---------------- 过滤预设 ----------------
     常用的过滤表达式（例如「只看我的包 + 排除噪音」）每次手敲不现实。预设存的
     就是**表达式文本**（kw），不存级别 / 仅异常 —— 那两项是全局视图偏好，切预设
     时用户通常不想连带变化。落盘为 config.json 的 lc_presets（JSON 字符串，
     与 cmd_history 同一套约定：后端按未知键原样保留，不需要改 prefs 白名单）。
     上限 30 条：防止误操作把配置文件撑大，也够覆盖日常场景。 */
  const LC_PRESET_MAX = 30;
  let lcPresets = [];        // [{ name, kw }, ...]

  function _loadLcPresets(raw) {
    let list = [];
    try {
      const v = typeof raw === "string" && raw ? JSON.parse(raw) : [];
      if (Array.isArray(v)) list = v;
    } catch (_) { list = []; }   // 手改坏了就当没有，不让启动报错
    lcPresets = list.filter((p) => p && typeof p.name === "string"
      && p.name && typeof p.kw === "string").slice(0, LC_PRESET_MAX);
    renderLcPresets();
    // 上次的表达式若正好等于某个预设，启动时把它选上（免得多点一次）；
    // 只做「展示」不做应用 —— 表达式本身（lc_keyword）已经恢复，无需重渲染。
    const kw = (els.lcFilter.value || "").trim();
    const hit = lcPresets.findIndex((p) => p.kw.trim() === kw);
    if (kw && hit >= 0) selectLcPreset(String(hit));
  }
  function _persistLcPresets() {
    persistPref("lc_presets", JSON.stringify(lcPresets));
  }
  function selectLcPreset(value) {
    if (!els.lcPreset) return;
    els.lcPreset.value = lcPresets[Number(value)] ? value : "";
    if (els.lcPresetDel) els.lcPresetDel.disabled = els.lcPreset.value === "";
  }
  function renderLcPresets() {
    if (!els.lcPreset) return;
    const keep = els.lcPreset.value;
    els.lcPreset.innerHTML = "";
    const none = document.createElement("option");
    none.value = ""; none.textContent = "（无）";
    els.lcPreset.appendChild(none);
    lcPresets.forEach((p, i) => {
      const o = document.createElement("option");
      o.value = String(i); o.textContent = p.name;
      els.lcPreset.appendChild(o);
    });
    selectLcPreset(keep);
  }
  async function saveLcPreset() {
    const kw = (els.lcFilter.value || "").trim();
    if (!kw) {
      pushStatus("warn", "过滤条件为空，先写一条表达式再保存为预设");
      return;
    }
    const name = await askInput({
      title: "保存过滤预设",
      label: "预设名称",
      placeholder: "例如：我的应用 + 排除噪音",
      hint: "保存后可在「预设」下拉里一键切换；同名会提示覆盖",
      maxLength: 40,
    });
    if (!name) return;
    const dup = lcPresets.findIndex((p) => p.name === name);
    if (dup >= 0) {
      const yes = await askConfirm({
        title: "覆盖预设",
        text: "已存在同名预设「" + name + "」，用当前过滤条件覆盖它？",
        yes: "覆盖", danger: true,
      });
      if (!yes) return;
    }
    const item = { name: name, kw: kw };
    if (dup >= 0) lcPresets[dup] = item;
    else lcPresets.push(item);
    if (lcPresets.length > LC_PRESET_MAX) {
      lcPresets.splice(0, lcPresets.length - LC_PRESET_MAX);
    }
    _persistLcPresets();
    renderLcPresets();
    selectLcPreset(String(lcPresets.indexOf(item)));
    pushStatus("ok", "✓ 已保存过滤预设「" + name + "」");
  }
  async function deleteLcPreset() {
    const idx = els.lcPreset ? els.lcPreset.value : "";
    const p = idx === "" ? null : lcPresets[Number(idx)];
    if (!p) return;
    const yes = await askConfirm({
      title: "删除预设",
      text: "删除过滤预设「" + p.name + "」？（不影响当前过滤条件）",
      yes: "删除", danger: true,
    });
    if (!yes) return;
    lcPresets.splice(Number(idx), 1);
    _persistLcPresets();
    renderLcPresets();
    pushStatus("ok", "已删除预设「" + p.name + "」");
  }
  function applyLcPreset() {
    const idx = els.lcPreset ? els.lcPreset.value : "";
    const p = idx === "" ? null : lcPresets[Number(idx)];
    if (els.lcPresetDel) els.lcPresetDel.disabled = !p;
    if (!p) return;
    els.lcFilter.value = p.kw;
    triggerLcFilter();
    pushStatus("ok", "已应用预设「" + p.name + "」");
  }
  function renderLogcat() {
    // 全量重建前丢弃待渲染队列，否则残留的行会在重建后插入，顺序错乱
    clearLcQueue();
    els.lcDev.textContent = lcSerial ? "设备: " + lcSerial : "未选设备";
    if (!lcSerial) {
      // 计数也要一起归零：否则取消勾选后「行数/异常」仍停在上一台的数字
      els.lcView.innerHTML = "";
      lcFilterHits = null;
      els.lcCounter.textContent = "行数: 0 · 异常: 0";
      return;
    }
    // 切到「还没缓冲过」的设备：视图清空的同时计数一并归零
    const buf = lcBuffers[lcSerial];
    if (!buf) { els.lcView.innerHTML = ""; lcFilterHits = null; updateLcCounter(lcSerial); return; }
    const f = currentLcFilter();
    const view = els.lcView;
    // 关键字激活时，扫描**整个缓冲**（不止最后 LC_RENDER_CAP 行）：否则较早出现、
    // 已被实时渲染裁剪出视图的关键字行永远搜不到，用户会以为「过滤不灵」。
    // 命中数也一并统计，给出可解释的反馈（见 updateLcCounter）。
    let hits = 0;
    const matches = [];          // 命中行（按原顺序）
    for (let i = 0; i < buf.lines.length; i++) {
      const ln = buf.lines[i];
      if (!linePassesFilter(ln, f)) continue;
      hits += 1;
      matches.push(ln);
    }
    if (f.kw) {
      lcFilterHits = hits;
    } else {
      lcFilterHits = null;
    }
    // 渲染上限：整段匹配超过 LC_RENDER_CAP 时，保留**最近** LC_RENDER_CAP 行
    // （读最新日志是主场景），避免一次性插几千个 DOM 节点卡住界面。
    const start = Math.max(0, matches.length - LC_RENDER_CAP);
    const frag = document.createDocumentFragment();
    for (let i = start; i < matches.length; i++) {
      frag.appendChild(makeLineNode(matches[i]));
    }
    view.innerHTML = "";
    view.appendChild(frag);
    if (els.lcAuto.checked) view.scrollTop = view.scrollHeight;
    updateLcCounter(lcSerial);
  }
  /* ---------------- 日志右键菜单（选中复制） ----------------
     .lc-view 已用 CSS user-select:text 放开框选，Ctrl+C / 右键系统菜单里的
     「复制」理论上可用；但 WebView2 系统菜单是英文、不可控，且用户最常用的
     是「右键这一行 → 复制」。这里自绘一个与指令区 ⋯ 菜单同视觉的右键菜单：
       有选区           → 「复制选中内容」
       无选区、落在行上 → 「复制该行」
     复制走全局 copyToClipboard（clipboard API 优先，老内核回退 execCommand）。 */
  let lcMenuEl = null;
  function lcMenuHide() {
    if (lcMenuEl) { lcMenuEl.remove(); lcMenuEl = null; }
  }
  function copyLcText(text, label) {
    if (!text) { pushStatus("warn", "没有可复制的内容"); return; }
    copyToClipboard(text);
    // flashCopy 只会让状态栏的「复制」按钮闪一下「已复制」；这里补一条带
    // 行数的状态消息，用户不用挪视线就知道复制了多少。
    pushStatus("ok", "✓ 已复制" + label + "（"
      + (text.split("\n").length) + " 行）到剪贴板");
  }
  function lcMenuShow(x, y, items) {
    lcMenuHide();
    const m = document.createElement("div");
    m.className = "ctx-menu";
    for (const it of items) {
      const b = document.createElement("button");
      b.type = "button"; b.className = "ctx-menu-item";
      b.textContent = it.label;
      b.addEventListener("click", () => { lcMenuHide(); it.fn(); });
      m.appendChild(b);
    }
    document.body.appendChild(m);
    // 先挂载再量尺寸：按视口收敛位置，贴边右键时菜单不被裁掉
    const r = m.getBoundingClientRect();
    m.style.left = Math.max(4, Math.min(x, window.innerWidth - r.width - 8)) + "px";
    m.style.top = Math.max(4, Math.min(y, window.innerHeight - r.height - 8)) + "px";
    lcMenuEl = m;
  }
  function initLcContextMenu() {
    els.lcView.addEventListener("contextmenu", (ev) => {
      ev.preventDefault();   // 始终拦掉 WebView2 系统菜单（英文且不可控）
      const sel = window.getSelection && window.getSelection();
      const selText = sel ? sel.toString() : "";
      const items = [];
      if (selText && sel.anchorNode && els.lcView.contains(sel.anchorNode)) {
        items.push({ label: "复制选中内容", fn: () => copyLcText(selText, "选中内容") });
      } else {
        const line = ev.target && ev.target.closest
          ? ev.target.closest(".lc-line") : null;
        if (line) {
          const t = line.textContent || "";
          items.push({ label: "复制该行", fn: () => copyLcText(t, "日志行") });
          // 从整行缓存里找这条的 tag / pid（渲染时 ln 对象带这些字段）。
          // 但 line 只是 DOM，没存 ln 引用——遍历一次当前 buf 找匹配 raw。
          const raw = t;
          const allBuf = lcBuffers[lcSerial] || { lines: [] };
          const ln = allBuf.lines.find((x) => x.raw === raw);
          if (ln) {
            if (ln.tag) {
              items.push({ label: "按 Tag 过滤: " + ln.tag,
                fn: () => { els.lcFilter.value = "tag:" + ln.tag; triggerLcFilter(); } });
              items.push({ label: "排除此 Tag: " + ln.tag,
                fn: () => { els.lcFilter.value = "-tag:" + ln.tag; triggerLcFilter(); } });
            }
            if (ln.pid) {
              items.push({ label: "按 PID 过滤: " + ln.pid,
                fn: () => { els.lcFilter.value = "pid:" + ln.pid; triggerLcFilter(); } });
              items.push({ label: "排除此 PID: " + ln.pid,
                fn: () => { els.lcFilter.value = "-pid:" + ln.pid; triggerLcFilter(); } });
            }
            // 「只加条件」而不是「替换条件」的追加方式：用户常已有一条 tag:
            // 过滤，再想叠一条排除噪音；替换会把前一条冲掉，措手不及。
            if (ln.tag) {
              items.push({ label: "追加排除此 Tag",
                fn: () => { appendLcTerm("-tag:" + ln.tag); } });
            }
          }
        }
      }
      if (!items.length) return;   // 空白处右键：无内容可复制，不弹菜单
      lcMenuShow(ev.clientX, ev.clientY, items);
    });
    window.addEventListener("pointerdown", (ev) => {
      if (lcMenuEl && !lcMenuEl.contains(ev.target)) lcMenuHide();
    }, true);
    els.lcView.addEventListener("scroll", lcMenuHide, { passive: true });
    window.addEventListener("blur", lcMenuHide);
    window.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") lcMenuHide();
    });
  }
  function onLogcatCapture(p) {
    if (p.status === "running") { lcCapRunning = true; els.lcCapStatus.textContent = "采集中…"; els.lcCapStop.disabled = false; els.lcCapStart.disabled = true; markBtnBusy(els.lcCapStart, false); markBtnBusy(els.lcCapStop, false); }
    // 设备掉线 / 抓取被意外中断、正在自动重连：保持「采集中」，**不要**复位成
    // 空闲。否则界面会错误地切回「空闲」、用户以为抓取已结束（实际在等重连并
    // 续写同一文件）。这是「录屏+满缓冲全级别 logcat 同时跑也不丢日志」的关键
    // UI 不变量 —— 用户实况就是日志在录屏中途断掉却毫无察觉，事后才发现少了
    // 一大段。文案要能同时覆盖「掉线」与「被中断」两种原因，故不再写死掉线。
    if (p.status === "reconnecting") {
      lcCapRunning = true;
      els.lcCapStatus.textContent = "采集中…（已中断，正在自动重连）";
      els.lcCapStop.disabled = false;
      els.lcCapStart.disabled = true;
      markBtnBusy(els.lcCapStart, false);
      markBtnBusy(els.lcCapStop, false);
      pushStatus("warn", p.text || "⚠ logcat 抓取已中断，正在自动重连…");
      return;
    }
    // 无勾选设备时才禁用「开始抓取」（取反写反过：有设备反而点不了）
    if (p.status === "stopped") {
      lcCapRunning = false; lcCapSerial = null; els.lcCapStatus.textContent = "空闲"; els.lcCapStop.disabled = true; els.lcCapStart.disabled = !checkedDevices().length;
      markBtnBusy(els.lcCapStop, false);
      // 抓取完毕强提醒（用户可能已切去别的页签，只看得到 toast）。
      // 已打包的场景由下面的 zipped 分支弹「已打包」，这里不重复。
      const name = String(p.path || "").split(/[\\/]/).pop() || "";
      if (p.no_file) {
        // 启动瞬间就点了停止：一行没抓、也没生成文件。此时绝不能走下面的
        // 「✓ 抓取完毕：0 行」—— 「0 行」在这里的含义是「根本没开始抓」，
        // 而不是「设备当时没有日志输出」，对用户是完全不同的两个结论。
        pushStatus("info", "ℹ " + (p.text || "已停止 logcat 抓取，本次没有生成文件"));
      } else if (p.gap) {
        // 抓取期间设备曾掉线、文件含时间缺口（缺口处已写入 [logcat] 标记行）。
        // 必须如实告警，绝不能报「✓ 抓取完毕」——否则分析师对照视频流找日志时
        // 会误以为时间线连续、漏掉的那段正好在案发现场上。
        const gapMsg = "⚠ Logcat 抓取结束，文件存在时间缺口：" +
          (p.text || "缺失时段见文件内 [logcat] 标记");
        // 缺口 = 产物残缺，且这个文件事后要拿去对时间轴：光一条会自己消失的
        // toast 不够，必须让用户亲手关一次（见 showAlert）。
        pushStatus("warn", gapMsg, {
          alert: true, alertTitle: "⚠ Logcat 日志存在时间缺口",
        });
        showToast("warn", "⚠ logcat 存在时间缺口，详见文件内 [logcat] 标记");
      } else if (p.error) {
        // 写盘中途失败（磁盘满 / 目录被删 / 权限）：文件只有半截，甚至一行
        // 都没进去。后端在 stopped 上带了 error，这里绝不能再报「✓ 抓取完毕」——
        // 那会把前一条 err 提示盖掉，用户拿着半截文件去分析问题。
        const bad = "⚠ Logcat 抓取已中断：" + p.error + (name ? " → " + name : "");
        pushStatus("err", bad, {
          alert: true, alertTitle: "⚠ 日志抓取被中断，文件不完整",
        });
        showToast("err", "⚠ Logcat 抓取中断，导出的文件不完整");
      } else if (!p.packaged) {
        const done = "✓ Logcat 抓取完毕：" + (p.lines || 0) + " 行"
          + (p.size ? " · " + fmtSize(p.size) : "") + (name ? " → " + name : "");
        pushStatus("ok", done);
        showToast("ok", done);
      }
      if (p.zip_error) {
        // 勾了「结束后打包」却没打成：用户会按承诺去目录里找 zip，得说清为什么没有。
        pushStatus("warn", "⚠ Logcat " + p.zip_error);
        showToast("warn", "⚠ Logcat 打包失败，文件未压缩");
      }
    }
    if (p.status === "zipped") {
      els.lcCapStatus.textContent = "已打包";
      markBtnBusy(els.lcCapStop, false);
      const zip = "✓ Logcat 抓取完毕，已打包: " + String(p.path || "").split(/[\\/]/).pop();
      pushStatus("ok", "✓ " + (p.text || "已打包"));
      showToast("ok", zip);
    }
    if (p.status === "error") { lcCapRunning = false; lcCapSerial = null; els.lcCapStatus.textContent = "错误"; els.lcCapStop.disabled = true; els.lcCapStart.disabled = !checkedDevices().length; markBtnBusy(els.lcCapStop, false); pushStatus("err", "⚠ " + (p.text || "抓取错误")); }
  }
  /* ---------------- 工具 ---------------- */
  function syncToolButtons() {
    const any = checkedDevices().length > 0;
    // 截图在途（shot_state running=true）时保持禁用：在途中改勾选不能把它
    // 放出来，恢复时也同样尊重当前勾选态（shotInFlight 与 !any 取或）。
    els.toolShot.disabled = !any || shotInFlight;
    markBtnBusy(els.toolShot, shotInFlight);
    // 投屏同样要有受控设备才可点（scrcpy 是「一台设备一个窗口」）
    if (els.toolScrcpy) els.toolScrcpy.disabled = !any;
    // 备用投屏同理；「停止」只在真的有会话时可点
    if (els.toolMirror) els.toolMirror.disabled = !any;
    if (els.toolMirrorStop && !mirrorFrameUrl && !mirrorTimer) {
      els.toolMirrorStop.disabled = true;
    }
    // 应用安装：需要「有受控设备 + 已选安装包 + 不在安装中」
    if (els.apkInstall) els.apkInstall.disabled = !any || !apkPath || apkInFlight;
    if (els.apkInstall) markBtnBusy(els.apkInstall, apkInFlight);
    // 诊断包：有受控设备、且没有一批正在收集（收集中再点会排队出两个时间点
    // 不同的包，后端也直接拒绝，这里把按钮一起锁上是更清楚的反馈）
    if (els.diagCollect) els.diagCollect.disabled = !any || diagInFlight;
    if (els.diagCollect) markBtnBusy(els.diagCollect, diagInFlight);
    // 无线调试的「开启 5555」同样要有受控设备（首次必须走 USB）
    if (els.wifiTcpip) els.wifiTcpip.disabled = !any || wifiBusy;
    if (els.wifiTcpip) markBtnBusy(els.wifiTcpip, wifiBusy);
    // 录制中不打断：setRecRunning 已经按 running 锁定了录屏区按钮与选项，
    // 设备列表刷新时也不要在这里把它们再回拨回去。
    // 请求在途同样不打断：开始/停止都是重操作，点击后已整体禁用，
    // 这里若按「有无受控设备」回拨会把禁用态冲掉。
    if (recInFlight) return;
    if (els.toolRecStop && !els.toolRecStop.disabled) return;
    els.toolRec.disabled = !any;
  }

  /* 截图在途态：禁用/恢复「立即截图」。点击时已乐观禁用（不等后端事件，
     秒级耗时里给即时反馈），本函数处理后端 shot_state 广播——完成或异常
     收尾时恢复；与 setRecRunning 同一套路，按钮态由后端事件最终对账。 */
  function setShotRunning(running) {
    shotInFlight = running;
    syncToolButtons();
  }

  /* 录屏请求在途：开始 / 停止都是秒级耗时的重操作（起停录屏进程、拉 logcat、
     收尾转码打包），点击后立刻把两个按钮一起禁用，等真正完成/失败后才恢复，
     避免用户以为没点上而连点出并发请求。收尾由点击处理函数统一对账。 */
  let recInFlight = false;

  function setRecInFlight(busy) {
    recInFlight = busy;
    if (els.toolRec) els.toolRec.disabled = busy;
    if (els.toolRecStop) els.toolRecStop.disabled = busy;
    // 取消同样要锁：它背后是「停设备端 → 删文件」，几秒级的重操作，连点两次
    // 第二次会撞上已清空的会话，用户看到的是「没有进行中的录屏」这种莫名其妙的话。
    if (els.toolRecCancel) els.toolRecCancel.disabled = busy;
    markBtnBusy(els.toolRec, busy);
    markBtnBusy(els.toolRecStop, busy);
    markBtnBusy(els.toolRecCancel, busy);
  }

  /* ---------------- 录制时长 ----------------
     录制中在「停止录制」旁实时显示已录时长，让用户随时知道录了多久。
     计时用 performance.now()（单调时钟）：用户改系统时间、或设备校时导致主机
     时间跳变，都不会让读数突然多出一小时或少掉一段。
     起点优先用后端返回的会话开始时刻（screen_record_start 返工前那次 Popen
     到返回有 1~2 秒，只按前端点完开始的那一刻计会少算）；拿不到就从 0 起算。 */
  let recTimerId = null;     // setInterval 句柄（null = 没有在走）
  let recT0 = 0;             // 计时起点（performance.now 基准）
  let recFrozenMs = null;    // 冻结后的已录毫秒数（点停止那一刻）

  function _recNow() {
    return (typeof performance !== "undefined" && performance.now)
      ? performance.now() : Date.now();
  }

  function _fmtRecElapsed(ms) {
    const t = Math.max(0, Math.floor(ms / 1000));
    const h = Math.floor(t / 3600);
    const m = Math.floor((t % 3600) / 60);
    const s = t % 60;
    const mm = String(m).padStart(2, "0");
    const ss = String(s).padStart(2, "0");
    // 满 1 小时才补上小时位：短录制（绝大多数场景）保持 MM:SS 不啰嗦
    return h ? String(h) + ":" + mm + ":" + ss : mm + ":" + ss;
  }

  function recElapsedRender() {
    if (!els.recElapsedT) return;
    const ms = (recFrozenMs !== null) ? recFrozenMs : (_recNow() - recT0);
    els.recElapsedT.textContent = _fmtRecElapsed(ms);
  }

  function recElapsedStart(offsetMs) {
    recElapsedClear();
    // 元素缺失（老 HTML / 被裁剪的页面）时不要起空转的 interval：
    // 每 250ms 进一次渲染再直接 return，纯属白烧 CPU。
    if (!els.recElapsed || !els.recElapsedT) return;
    recT0 = _recNow() - Math.max(0, Number(offsetMs) || 0);
    els.recElapsed.hidden = false;
    els.recElapsed.classList.remove("frozen");
    recElapsedRender();
    // 250ms 一跳：秒数每过整秒就更新，不会出现「看着卡住一秒」的观感；
    // 频率足够低，长时间录制也不会有可见的 CPU 开销。
    recTimerId = setInterval(recElapsedRender, 250);
  }

  /* 点「停止 / 取消」的瞬间冻结读数：收尾（拉段 / 合并 / 打包）要十几秒，
     若继续往上走，用户看到的数字会比视频实际时长还长，反而制造困惑。 */
  function recElapsedFreeze() {
    if (recTimerId === null && recFrozenMs === null) return;
    if (recFrozenMs === null) recFrozenMs = _recNow() - recT0;
    if (recTimerId !== null) {
      clearInterval(recTimerId);
      recTimerId = null;
    }
    if (els.recElapsed) els.recElapsed.classList.add("frozen");
    recElapsedRender();
  }

  function recElapsedClear() {
    if (recTimerId !== null) {
      clearInterval(recTimerId);
      recTimerId = null;
    }
    recFrozenMs = null;
    if (els.recElapsed) {
      els.recElapsed.hidden = true;
      els.recElapsed.classList.remove("frozen");
    }
  }

  /* 录屏态：录制中把「停止」按钮切成红色实心并带轻微呼吸光晕，空闲时恢复灰。
     立即切换不等后端事件回传，避免点了没反应；复用 .btn.danger / .btn.danger.live。
     选项在录制中锁定防误改。
     除按钮点击外，后端 rec_state 事件也会驱动本函数——录屏进程意外死亡
     （adb root / adbd 重启）时后端自动收尾会话并广播 running=false，
     前端据此把界面切回「开始录制」，否则会一直停在"录制中"（后端早已结束，
     用户再点停止只会得到 no_session）。
     请求在途（recInFlight）时忽略：按钮此刻已被点击处理函数禁用，
     在途收尾时会按最终结果统一设置，中途插入的事件不与之打架。 */
  function setRecRunning(running, startedAtSec) {
    if (recInFlight) return;
    els.toolRec.disabled = running;
    els.toolRecStop.disabled = !running;
    els.toolRecStop.classList.toggle("danger", running);
    els.toolRecStop.classList.toggle("live", running);
    // 时长读数与录制态同生命周期：进来就起表（按后端给的真实开始时刻补上
    // 启动耗时），退出（用户停止 / 后端报录制意外结束）就整块收起。
    if (running) {
      const offset = startedAtSec
        ? Math.max(0, Date.now() - startedAtSec * 1000) : 0;
      recElapsedStart(offset);
    } else {
      recElapsedClear();
    }
    // 「取消」只在录制中可点：它做的事是「停止 + 删除本次产物」，没有会话时
    // 点了只会得到一句「当前没有进行中的录屏」，不如直接不给点。
    if (els.toolRecCancel) els.toolRecCancel.disabled = !running;
    els.recLogcat.disabled = running;
    if (els.recMic) els.recMic.disabled = running;
    els.recZip.disabled = running;
    els.recPointerLocation.disabled = running;
    els.recShowTouches.disabled = running;
    // 复位后同步一次工具按钮态（截图按钮的可用性只由「有无受控设备」决定，
    // 录制中未被禁用，这里调一次保证三处输入目录旁的按钮状态一致）
    syncToolButtons();
  }
  /* ---------------- 无线调试（Wi-Fi ADB） ----------------
     车机 / 长时间稳定性测试时 USB 线常常不够用：插一次线开启 5555，拔线后
     走 Wi-Fi 就能继续下发命令。入口在设备栏顶部，「开启无线调试」会顺手把
     设备 IP 读出来填进地址框——手动去设置里翻 WLAN 详情是最容易卡住的一步。 */
  let wifiBusy = false;

  function wifiOpen() {
    els.wifiModal.classList.remove("hidden");
    refreshWifi();
    if (els.wifiAddr) els.wifiAddr.focus();
  }
  function wifiClose() { els.wifiModal.classList.add("hidden"); }

  async function refreshWifi() {
    const res = await callApi(api.wifi_state());
    if (!res || res.ok === false) return;
    if (els.wifiTcpip) els.wifiTcpip.disabled = checkedDevices().length === 0;
    if (els.wifiAddr && !els.wifiAddr.value && res.recent && res.recent.length) {
      els.wifiAddr.value = res.recent[0];
    }
    renderWifiConnected(res.wireless || []);
    renderWifiRecent(res.recent || []);
  }

  function renderWifiConnected(list) {
    const box = els.wifiConnected;
    if (!box) return;
    box.innerHTML = "";
    if (!list.length) {
      const p = document.createElement("div");
      p.className = "dim wifi-empty";
      p.textContent = "（当前没有无线设备，先用 USB 线连上并开启 5555）";
      box.appendChild(p);
      return;
    }
    list.forEach((d) => {
      const row = document.createElement("div");
      row.className = "wifi-item";
      const dot = document.createElement("span");
      dot.className = "dot " + (d.ok ? "ok" : "bad");
      const info = document.createElement("div");
      info.className = "info";
      const ser = document.createElement("div");
      ser.className = "serial";
      ser.textContent = d.serial;
      const meta = document.createElement("div");
      meta.className = "meta";
      meta.textContent = (d.model || "未知型号") + (d.ok ? " · 在线" : " · 不可用");
      info.appendChild(ser); info.appendChild(meta);
      const btn = document.createElement("button");
      btn.className = "btn tiny";
      btn.type = "button";
      btn.textContent = "断开";
      btn.addEventListener("click", () => wifiDisconnect(d.serial, btn));
      row.appendChild(dot); row.appendChild(info); row.appendChild(btn);
      box.appendChild(row);
    });
  }

  function renderWifiRecent(list) {
    const box = els.wifiRecent;
    if (!box) return;
    box.innerHTML = "";
    if (!list.length) {
      const p = document.createElement("div");
      p.className = "dim wifi-empty";
      p.textContent = "（还没有连接记录，连接成功后会自动记下来）";
      box.appendChild(p);
      return;
    }
    list.forEach((addr) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "wifi-chip";
      b.textContent = addr;
      b.title = "点击直接连接 " + addr;
      b.addEventListener("click", () => {
        if (els.wifiAddr) els.wifiAddr.value = addr;
        wifiConnect();
      });
      box.appendChild(b);
    });
  }

  async function wifiConnect() {
    if (wifiBusy) return;
    const addr = (els.wifiAddr.value || "").trim();
    if (!addr) return pushStatus("warn", "请填写设备 IP（形如 192.168.1.23:5555）");
    wifiBusy = true;
    els.wifiConnect.disabled = true;
    markBtnBusy(els.wifiConnect, true);
    const old = els.wifiConnect.textContent;
    els.wifiConnect.textContent = "连接中…";
    const res = await callApi(api.wifi_connect(addr));
    els.wifiConnect.disabled = false;
    markBtnBusy(els.wifiConnect, false);
    els.wifiConnect.textContent = old;
    wifiBusy = false;
    if (res && res.ok) {
      els.wifiAddr.value = res.address || addr;
      refreshWifi();
    }
    // 失败 / 授权 / 离线等反馈已由后端统一推送（含「已检测到设备却连不上」的
    // 对账说明），前端不再重复 push —— 否则成功 / 失败会各弹两条，还与
    // device_service 的「检测到新设备」打架。
  }

  async function wifiDisconnect(addr, btn) {
    if (btn) { btn.disabled = true; markBtnBusy(btn, true); }
    const res = await callApi(api.wifi_disconnect(addr));
    if (btn) { btn.disabled = false; markBtnBusy(btn, false); }
    if (res && res.ok) refreshWifi();
    else if (res && res.reason) pushStatus("err", "✗ 断开失败：" + res.reason);
  }

  async function wifiTcpip() {
    if (wifiBusy) return;
    if (!checkedDevices().length) return pushStatus("warn", "请先在左侧勾选设备");
    wifiBusy = true;
    els.wifiTcpip.disabled = true;
    markBtnBusy(els.wifiTcpip, true);
    els.wifiTcpipState.textContent = "处理中…（需要几秒）";
    const res = await callApi(api.wifi_enable(null, null));
    wifiBusy = false;
    els.wifiTcpip.disabled = checkedDevices().length === 0;
    markBtnBusy(els.wifiTcpip, false);
    els.wifiTcpipState.textContent = "";
    if (!res) return;
    if (res.address) els.wifiAddr.value = res.address;
    const failed = (res.results || []).filter((x) => !x.ok);
    const okOnes = (res.results || []).filter((x) => x.ok);
    if (okOnes.length) {
      pushStatus("ok", "✓ 已开启无线调试：" + okOnes.map((x) =>
        x.serial + (x.address ? " → " + x.address : "")).join("；"));
    }
    failed.forEach((x) => pushStatus("warn", "⚠ " + x.serial + "：" + x.message));
    if (res.address) {
      pushStatus("info", "把设备地址填好后点「连接」，即可拔掉 USB 线。");
    }
    refreshWifi();
  }

  /* ---------------- 应用安装（APK） ---------------- */
  let apkPath = "";
  let apkInFlight = false;

  /* ---------------- 诊断包 ----------------
     后端 diag_collect 是「一串 adb 调用 + 写盘 + 打包」，单台 3~6 秒。按钮态
     与截图 / 安装同套路：点击时乐观禁用（不等事件，秒级耗时里给即时反馈），
     后端 diag_state 广播是最终对账（完成 / 异常 / 关闭都会回来）。 */
  let diagInFlight = false;

  function setDiagRunning(running) {
    diagInFlight = !!running;
    if (els.diagCollect) els.diagCollect.disabled = diagInFlight
      || checkedDevices().length === 0;
    if (els.diagCollect) markBtnBusy(els.diagCollect, diagInFlight);
    if (!diagInFlight && els.diagLines) els.diagLines.disabled = false;
    // 收尾时如果卡片上还停在「正在收集…」，说明这一批没有任何产物（失败 /
    // 关闭窗口），把它复位；有产物时 tool 事件已经先把文件名写上去了。
    if (!diagInFlight && els.diagResult
        && els.diagResult.textContent.indexOf("正在收集") === 0) {
      els.diagResult.textContent = "未收集";
      els.diagResult.title = "";
      els.diagResult.classList.add("dim");
    }
  }

  async function collectDiag() {
    if (diagInFlight) return;
    const withLogcat = !!(els.diagLogcat && els.diagLogcat.checked);
    const lines = els.diagLines ? Number(els.diagLines.value) || 0 : 0;
    diagInFlight = true;
    if (els.diagCollect) els.diagCollect.disabled = true;
    markBtnBusy(els.diagCollect, true);
    if (els.diagResult) {
      els.diagResult.textContent = "正在收集…（单台约 3~6 秒）";
      els.diagResult.classList.remove("dim");
    }
    const res = await callApi(api.diag_collect(null, withLogcat, lines));
    if (!res || res.ok === false) {
      diagInFlight = false;
      syncToolButtons();
      if (els.diagResult) {
        els.diagResult.textContent = "未收集";
        els.diagResult.classList.add("dim");
      }
      if (res && res.reason && res.reason !== "busy") {
        pushStatus("err", "⚠ 收集诊断包未开始：" + res.reason);
      }
    }
  }

  function setApkFile(name, sizeText) {
    if (!els.apkFile) return;
    if (!name) {
      els.apkFile.textContent = "未选择安装包";
      els.apkFile.classList.add("dim");
      return;
    }
    els.apkFile.textContent = name + (sizeText ? "（" + sizeText + "）" : "");
    els.apkFile.classList.remove("dim");
    els.apkFile.title = apkPath;
  }

  async function pickApk() {
    if (els.apkPick) markBtnBusy(els.apkPick, true);
    const res = await callApi(api.apk_pick());
    if (!res) { if (els.apkPick) markBtnBusy(els.apkPick, false); return; }
    if (res.ok === false) {
      if (els.apkPick) markBtnBusy(els.apkPick, false);
      if (res.reason && res.reason !== "cancelled") {
        pushStatus("warn", "⚠ 选择安装包失败：" + res.reason);
      }
      return;
    }
    if (els.apkPick) markBtnBusy(els.apkPick, false);
    apkPath = res.path || "";
    setApkFile(res.name, res.size_text);
    syncToolButtons();
  }

  async function installApk() {
    if (!apkPath) return pushStatus("warn", "请先选择 APK 安装包");
    if (!checkedDevices().length) return pushStatus("warn", "请先在左侧勾选设备");
    // 乐观禁用：安装是秒级到分钟级的动作，按钮不禁用会被连点。
    // 批次结束由后端 apk_state(running=false) 恢复，不依赖状态文案。
    apkInFlight = true;
    syncToolButtons();
    const res = await callApi(api.apk_install(
      null,
      !!(els.apkReplace && els.apkReplace.checked),
      !!(els.apkDowngrade && els.apkDowngrade.checked),
      !!(els.apkGrant && els.apkGrant.checked)));
    if (!res || res.ok === false) {
      apkInFlight = false;
      syncToolButtons();
      if (res && res.reason) pushStatus("err", "⚠ 安装未开始：" + res.reason);
    }
  }

  function setApkRunning(running) {
    apkInFlight = !!running;
    syncToolButtons();
  }

  /* ---------------- 设备信息快照 ---------------- */
  let devInfoSerial = "";
  let devInfoText = "";

  async function openDeviceInfo(serial) {
    if (!serial) return;
    devInfoSerial = serial;
    devInfoText = "";
    els.devinfoTitle.textContent = "设备信息 · " + serial;
    els.devinfoRows.innerHTML = '<div class="devinfo-empty dim">读取中…</div>';
    els.devinfoModal.classList.remove("hidden");
    await loadDeviceInfo();
  }

  async function loadDeviceInfo() {
    if (!devInfoSerial) return;
    // 记下「这次是给哪台设备读的」：连点两张卡的 ⓘ 时，先发的请求可能后回来，
    // 把后一台的弹窗内容覆盖成前一台的（标题是 B、内容是 A，最容易被当成
    // 「设备信息读错了」）。回包时对不上就直接丢弃。
    const serial = devInfoSerial;
    if (els.devinfoRefresh) markBtnBusy(els.devinfoRefresh, true);
    const res = await callApi(api.device_info(serial));
    if (!res || serial !== devInfoSerial) {
      if (els.devinfoRefresh) markBtnBusy(els.devinfoRefresh, false);
      return;
    }
    if (res.ok === false) {
      if (els.devinfoRefresh) markBtnBusy(els.devinfoRefresh, false);
      els.devinfoRows.innerHTML = "";
      const p = document.createElement("div");
      p.className = "devinfo-empty err";
      p.textContent = res.reason || "读取失败";
      els.devinfoRows.appendChild(p);
      return;
    }
    devInfoText = res.text || "";
    els.devinfoRows.innerHTML = "";
    (res.rows || []).forEach(([k, v]) => {
      const row = document.createElement("div");
      row.className = "devinfo-row";
      const kk = document.createElement("span");
      kk.className = "k";
      kk.textContent = k;
      const vv = document.createElement("span");
      vv.className = "v";
      vv.textContent = v;
      row.appendChild(kk); row.appendChild(vv);
      els.devinfoRows.appendChild(row);
    });
    if (!(res.rows || []).length) {
      // 命令全部失败（例如设备刚掉线）时会得到「成功但没有任何一项」——
      // 留个说明，别让用户对着一个空白框猜。
      const p = document.createElement("div");
      p.className = "devinfo-empty dim";
      p.textContent = "没有读到任何信息：设备可能已断开，或系统命令被限制";
      els.devinfoRows.appendChild(p);
    }
    if (els.devinfoRefresh) markBtnBusy(els.devinfoRefresh, false);
  }

  function closeDevInfo() {
    els.devinfoModal.classList.add("hidden");
    devInfoSerial = "";
  }

  function copyDevInfo() {
    if (!devInfoText) return pushStatus("warn", "还没有可复制的信息");
    const done = (ok) => pushStatus(ok ? "ok" : "warn",
      ok ? "✓ 已复制设备信息" : "复制失败：请手动选中后复制");
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(devInfoText).then(() => done(true))
        .catch(() => done(copyViaExec(devInfoText)));
    } else {
      done(copyViaExec(devInfoText));
    }
  }

  function copyViaExec(text) {
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.top = "-1000px";
      document.body.appendChild(ta);
      ta.focus(); ta.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      return ok;
    } catch (e) { return false; }
  }


  /* 工具区子 tab（截图 / 录屏 / 投屏 / 应用安装 / 诊断包）：每项一个子 tab，
     整页展示该项全部功能，互不挤压。顺序可长按拖动调整，落盘到 config.json 的
     tool_tab_order；上次停留的子 tab 记在 tool_active_tab。
     tab 的 key 一律从 DOM 推导（data-tool-tab 只在 index.html 写一份），
     将来增删一项只改 HTML，不必记得同步 JS 常量。 */
  function toolTabKeys() {
    const bar = document.getElementById("tool-subtabs");
    if (!bar) return [];
    return Array.from(bar.querySelectorAll(".tool-subtab"))
      .map((b) => b.dataset.toolTab).filter(Boolean);
  }

  function toolTabBtn(key) {
    return document.querySelector('#tool-subtabs .tool-subtab[data-tool-tab="' + key + '"]');
  }
  function toolTabPane(key) {
    return document.querySelector('#tool-panes .tool-pane[data-tool-pane="' + key + '"]');
  }

  /* 切换子 tab：只显示对应面板，其余 hidden；按钮 active / aria-selected 同步。
     persist 默认 true（用户点击 / 方向键切换都记）；启动回填时传 false，
     避免「打开就写一次盘」。 */
  function switchToolTab(key, opts) {
    const keys = toolTabKeys();
    if (!keys.length) return;
    // 配置里存的是已删除的 tab（版本变动）→ 回退到当前顺序里的第一项
    if (keys.indexOf(key) === -1) key = keys[0];
    keys.forEach((k) => {
      const active = k === key;
      const btn = toolTabBtn(k), pane = toolTabPane(k);
      if (btn) {
        btn.classList.toggle("active", active);
        btn.setAttribute("aria-selected", active ? "true" : "false");
        // roving tabindex：Tab 键只停在当前子 tab 上，切换用方向键（ARIA tabs 规范）
        btn.tabIndex = active ? 0 : -1;
      }
      if (pane) pane.hidden = !active;
    });
    const changed = toolActiveTab !== key;
    toolActiveTab = key;
    // 值没变就不写盘：连点同一个子 tab、方向键绕一圈回到原项时都省一次
    // 「读-合并-写」；启动回填（persist:false）只更新内存值。
    if (changed && (!opts || opts.persist !== false)) {
      persistPref("tool_active_tab", key);
    }
  }

  function bindToolSubtabs() {
    toolTabKeys().forEach((k) => {
      const btn = toolTabBtn(k);
      if (!btn) return;
      // 长按拖动刚结束会紧随一个 click：此时已换位，若再切换就跳回原 tab，
      // 故用 toolTabClickGuard 压制这次 click（与指令卡同思路）。
      btn.addEventListener("click", () => {
        if (toolTabClickGuard && Date.now() < toolTabClickGuard) return;
        switchToolTab(k);
      });
      btn.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); switchToolTab(k); return; }
        // 方向键 / Home / End 在子 tab 间移动并激活；顺序取 DOM（= 拖动后的视觉顺序）
        const step = ev.key === "ArrowRight" ? 1 : ev.key === "ArrowLeft" ? -1 : 0;
        if (!step && ev.key !== "Home" && ev.key !== "End") return;
        ev.preventDefault();
        const tabs = Array.from(document.querySelectorAll("#tool-subtabs .tool-subtab"));
        if (!tabs.length) return;
        const idx = tabs.indexOf(btn);
        let next;
        if (ev.key === "Home") next = 0;
        else if (ev.key === "End") next = tabs.length - 1;
        else next = (idx + step + tabs.length) % tabs.length;
        const nb = tabs[next];
        if (nb) { switchToolTab(nb.dataset.toolTab); nb.focus(); }
      });
    });
  }

  /* Logcat 子 tab（落盘抓取 / 实时监控）：与工具页同一套子 tab 视觉，但只有两项、
     顺序固定（无需长按拖动排序）。点击切换 + 方向键 / Enter / Space 激活；上次停留项
     记在 lc_active_tab（与 tool_active_tab 同一套「只记 key、失效回退」约定）。
     tab 的 key 一律从 DOM 推导（data-lc-tab 只在 index.html 写一份）。 */
  function lcTabKeys() {
    const bar = document.getElementById("lc-subtabs");
    if (!bar) return [];
    return Array.from(bar.querySelectorAll(".tool-subtab"))
      .map((b) => b.dataset.lcTab).filter(Boolean);
  }
  function lcTabBtn(key) {
    return document.querySelector('#lc-subtabs .tool-subtab[data-lc-tab="' + key + '"]');
  }
  function lcTabPane(key) {
    return document.querySelector('#lc-panes .tool-pane[data-lc-pane="' + key + '"]');
  }

  /* 切换子 tab：只显示对应面板，其余 hidden；按钮 active / aria-selected 同步。
     persist 默认 true（用户点击 / 方向键切换都记）；启动回填时传 false，
     避免「打开就写一次盘」。 */
  function switchLcTab(key, opts) {
    const keys = lcTabKeys();
    if (!keys.length) return;
    // 配置里存的是已删除的 tab（版本变动）→ 回退到当前顺序里的第一项
    if (keys.indexOf(key) === -1) key = keys[0];
    keys.forEach((k) => {
      const active = k === key;
      const btn = lcTabBtn(k), pane = lcTabPane(k);
      if (btn) {
        btn.classList.toggle("active", active);
        btn.setAttribute("aria-selected", active ? "true" : "false");
        // roving tabindex：Tab 键只停在当前子 tab 上，切换用方向键（ARIA tabs 规范）
        btn.tabIndex = active ? 0 : -1;
      }
      if (pane) pane.hidden = !active;
    });
    const changed = lcActiveTab !== key;
    lcActiveTab = key;
    // 值没变就不写盘：连点同一个子 tab、方向键绕一圈回到原项时都省一次「读-合并-写」
    if (changed && (!opts || opts.persist !== false)) {
      persistPref("lc_active_tab", key);
    }
  }

  function bindLcSubtabs() {
    lcTabKeys().forEach((k) => {
      const btn = lcTabBtn(k);
      if (!btn) return;
      btn.addEventListener("click", () => switchLcTab(k));
      btn.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); switchLcTab(k); return; }
        // 方向键在子 tab 间移动并激活；顺序取 DOM（固定两项，capture → monitor）
        const step = ev.key === "ArrowRight" ? 1 : ev.key === "ArrowLeft" ? -1 : 0;
        if (!step) return;
        ev.preventDefault();
        const tabs = Array.from(document.querySelectorAll("#lc-subtabs .tool-subtab"));
        if (!tabs.length) return;
        const idx = tabs.indexOf(btn);
        const nb = tabs[(idx + step + tabs.length) % tabs.length];
        if (nb) { switchLcTab(nb.dataset.lcTab); nb.focus(); }
      });
    });
  }

  /* ---- 子 tab 长按拖动排序（与指令卡同一套长按手势）---- */
  // 每张子 tab 左侧注入拖拽手柄（两列圆点），但长按手势绑在整颗按钮上——点哪都能拖。
  function injectToolTabGrips() {
    toolTabKeys().forEach((k) => {
      const btn = toolTabBtn(k);
      if (!btn || btn.querySelector(".tool-grip")) return;
      const grip = document.createElement("span");
      grip.className = "tool-grip";
      grip.setAttribute("aria-hidden", "true");
      grip.title = "长按拖动以调整工具顺序";
      grip.innerHTML = TOOL_GRIP_SVG;
      btn.insertBefore(grip, btn.firstChild);
    });
  }

  function loadToolTabOrder(raw) {
    toolTabOrder = String(raw || "").split(",").map((s) => s.trim()).filter(Boolean);
  }

  /* 按给定 key 顺序重排子 tab 按钮与对应面板（按钮 / 面板始终一一对应）。 */
  function reorderToolTabs(keys) {
    const bar = document.getElementById("tool-subtabs");
    const panes = document.getElementById("tool-panes");
    if (!bar || !panes) return;
    keys.forEach((k) => {
      const btn = toolTabBtn(k), pane = toolTabPane(k);
      if (btn) bar.appendChild(btn);
      if (pane) panes.appendChild(pane);
    });
  }

  /* 按保存顺序重排子 tab 按钮与对应面板（启动时 / 拖动结束后调用）。
     不在顺序表里的补到末尾 —— 以页面上真实存在的按钮 ∪ 面板为准，
     将来加一项只改 HTML 就能自动纳入，不用回来改这里。 */
  function applyToolTabOrder() {
    const bar = document.getElementById("tool-subtabs");
    const panes = document.getElementById("tool-panes");
    if (!bar || !panes || !toolTabOrder.length) return;
    const keys = [];
    const add = (k) => { if (k && keys.indexOf(k) === -1) keys.push(k); };
    Array.from(bar.querySelectorAll(".tool-subtab")).forEach((b) => add(b.dataset.toolTab));
    Array.from(panes.querySelectorAll(".tool-pane")).forEach((p) => add(p.dataset.toolPane));
    if (!keys.length) return;
    const seen = new Set();
    const order = [];
    toolTabOrder.forEach((k) => {
      if (keys.indexOf(k) !== -1 && !seen.has(k)) { order.push(k); seen.add(k); }
    });
    keys.forEach((k) => { if (!seen.has(k)) order.push(k); });
    reorderToolTabs(order);
  }

  function saveToolTabOrder() {
    const bar = document.getElementById("tool-subtabs");
    if (!bar) return;
    // 按子 tab 在 DOM 里的真实顺序排列（拖动后已重排），不要反向用固定的
    // 这个固定数组去 filter——那样只会还原成默认顺序，丢掉用户刚拖好的顺序。
    toolTabOrder = Array.from(bar.querySelectorAll(".tool-subtab"))
      .map((b) => b.dataset.toolTab);
    persistPref("tool_tab_order", toolTabOrder.join(","));
  }

  function beginToolTabDrag() {
    const d = toolTabDrag;
    if (!d) return;
    d.timer = null; d.active = true;
    d.tab.classList.add("is-dragging");
    document.body.classList.add("tool-sorting");
  }
  function endToolTabDrag() {
    const d = toolTabDrag; toolTabDrag = null;
    if (!d) return;
    if (d.timer) { clearTimeout(d.timer); d.timer = null; }
    d.tab.classList.remove("is-dragging");
    document.body.classList.remove("tool-sorting");
  }

  function onToolTabPointerDown(ev) {
    if (ev.button !== undefined && ev.button !== 0) return;   // 只认左键
    if (toolTabDrag) endToolTabDrag();
    const btn = ev.target.closest && ev.target.closest(".tool-subtab");
    if (!btn) return;
    toolTabDrag = {
      tab: btn, x: ev.clientX || 0, y: ev.clientY || 0, active: false,
      // 记录拖动前的顺序：中途按 Esc / 失焦取消时按它还原
      prev: toolTabKeys(),
      timer: setTimeout(beginToolTabDrag, TOOL_LONGPRESS_MS),
    };
  }
  function onToolTabPointerMove(ev) {
    const d = toolTabDrag;
    if (!d) return;
    const x = ev.clientX || 0, y = ev.clientY || 0;
    if (!d.active) {
      // 还没到长按时限就移动超阈值 = 用户想点别处，放弃这次长按
      if (Math.abs(x - d.x) > TOOL_DRAG_SLOP || Math.abs(y - d.y) > TOOL_DRAG_SLOP) endToolTabDrag();
      return;
    }
    if (ev.cancelable) ev.preventDefault();
    const hit = (document.elementFromPoint ? document.elementFromPoint(x, y) : null);
    const over = hit && hit.closest ? hit.closest(".tool-subtab") : null;
    const bar = document.getElementById("tool-subtabs");
    if (!over || !bar || over === d.tab) return;
    const r = over.getBoundingClientRect();
    // 子 tab 在窄窗口会换行（flex-wrap）。同一行按水平中线判断插前/插后；
    // 跨行时按垂直中线判断（指针在目标行下方 = 插到它后面），否则永远只能
    // 在「同一行内」换位，拖到第二行会插错位置。
    const cy = ev.clientY || 0;
    const sameRow = Math.abs(cy - (r.top + r.height / 2)) < r.height / 2;
    const after = sameRow
      ? (ev.clientX || 0) > r.left + r.width / 2
      : cy > r.top + r.height / 2;
    bar.insertBefore(d.tab, after ? over.nextSibling : over);
  }
  function onToolTabPointerUp() {
    const d = toolTabDrag;
    if (!d) return;
    if (!d.active) { endToolTabDrag(); return; }   // 短按 = 普通切换，交给 click
    const tab = d.tab;
    endToolTabDrag();
    toolTabClickGuard = Date.now() + 350;
    saveToolTabOrder();
    // 面板 DOM 跟着按钮一起重排：两者始终一一对应，后续按 key 查找也不会错位
    applyToolTabOrder();
    // 重排会移动节点、把焦点丢掉：还给被拖的那颗，键盘用户能接着用方向键
    restoreToolTabFocus(tab);
    pushStatus("info", "✓ 工具顺序已保存（长按子 tab 可再次调整）");
  }

  /* 重排后把焦点还给某颗子 tab。
     为什么不直接 focus()：applyToolTabOrder 里是 appendChild 移动节点，浏览器
     在「节点被移出文档」的那一刻会丢焦点，而这次复位与紧随的 focus() 谁先谁后
     并不保证（jsdom 下实测约一半概率被复位回 body）。延后一帧再聚焦最稳，用户
     无感；若这一帧里用户已经把焦点放到别处（不是 body），那就不抢回来。 */
  function restoreToolTabFocus(tab) {
    if (!tab) return;
    const doFocus = () => {
      if (!tab.isConnected) return;
      const cur = document.activeElement;
      if (cur && cur !== document.body) return;   // 用户已经去点别的控件了
      tab.focus();
    };
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(doFocus);
    else setTimeout(doFocus, 0);
  }

  /* 拖动中按 Esc 取消：顺序还原成按下前的样子，且不落盘。 */
  function cancelToolTabDrag() {
    const d = toolTabDrag;
    if (!d || !d.active) return false;
    const prev = d.prev || [];
    const tab = d.tab;
    endToolTabDrag();
    if (prev.length) reorderToolTabs(prev);
    restoreToolTabFocus(tab);            // 还原后焦点仍留在原处（同上：延后一帧）
    // 松手后还会紧跟一个 click：一并压掉，免得取消完又切走一个子 tab
    toolTabClickGuard = Date.now() + 350;
    pushStatus("info", "已取消工具顺序调整");
    return true;
  }

  let _toolTabDragBound = false;
  function bindToolTabDrag() {
    injectToolTabGrips();
    const bar = document.getElementById("tool-subtabs");
    if (bar) bar.addEventListener("pointerdown", onToolTabPointerDown);
    if (_toolTabDragBound) return;
    _toolTabDragBound = true;
    window.addEventListener("pointermove", onToolTabPointerMove, { passive: false });
    window.addEventListener("pointerup", onToolTabPointerUp);
    window.addEventListener("pointercancel", () => endToolTabDrag());
    // 在窗口外松手收不到 pointerup：失焦也当作结束，免得卡在「拖住不放」
    window.addEventListener("blur", () => endToolTabDrag());
    // Esc 取消：拖到一半后悔时按一下就能还原（不保存）
    window.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && cancelToolTabDrag()) ev.preventDefault();
    });
    // 触摸长按会同时触发系统的 contextmenu（弹「复制/粘贴」），拖动态里必须挡掉
    window.addEventListener("contextmenu", (ev) => {
      if (toolTabDrag && toolTabDrag.active) ev.preventDefault();
    });
  }

  /* ---------------- 投屏（调用本机 scrcpy，见 backend/scrcpy_service.py） ---------------- */
  function setScrcpyState(kind, text, title) {
    if (!els.scrcpyState) return;
    els.scrcpyState.className = "scrcpy-state" + (kind ? " " + kind : "");
    els.scrcpyState.textContent = text;
    els.scrcpyState.title = title || text;
  }

  /* 探测本机 scrcpy 并把结果写在按钮旁边：找到 → 显示版本 + 路径（用户能确认
     用的是哪一份）；没找到 → 直接给出安装指引，而不是只标一句"未找到"。 */
  async function probeScrcpy() {
    if (!hasApi()) { setScrcpyState("", "未就绪"); return; }
    setScrcpyState("", "检测中…");
    const res = await callApi(api.scrcpy_probe());
    if (!res) { setScrcpyState("err", "检测失败：后端无响应"); return; }
    if (res.ok) {
      const ver = String(res.version || "").replace(/^scrcpy\s*/i, "").trim();
      setScrcpyState("ok", "已就绪" + (ver ? "（" + ver + "）" : "") + " · " + res.path,
                     (res.note ? res.note + "\n" : "") + res.path);
    } else {
      setScrcpyState("err", res.note || "未找到 scrcpy", res.note || "");
    }
  }

  /* ---------------- 备用投屏（没装 scrcpy 时，见 backend/mirror_service.py） ----------------
     两条降级链路：① screenrecord 管道喂给本机播放器窗口；② screencap 轮询的低帧率
     预览（画面内嵌在本卡片里）。点「备用投屏」时后端自动挑能用的那一档。 */
  function setMirrorState(kind, text, title) {
    if (!els.mirrorState) return;
    els.mirrorState.className = "scrcpy-state" + (kind ? " " + kind : "");
    els.mirrorState.textContent = text;
    els.mirrorState.title = title || text;
  }

  /* 低帧率预览的帧刷新：后端只保留「最新一帧」并提供本机回环 HTTP 地址，
     前端给 src 追加时间戳强制重新请求（浏览器不会自己去刷同一个 URL）。 */
  function startMirrorPreview(url) {
    stopMirrorPreview();
    if (!url || !els.mirrorView) return;
    mirrorFrameUrl = url;
    if (els.mirrorPreview) els.mirrorPreview.hidden = false;
    const tick = () => {
      if (!els.mirrorView) return;
      els.mirrorView.src = url + "&t=" + Date.now();
    };
    tick();
    // 按配置帧率的两倍去取：抓帧本身有耗时，取太慢会白白掉帧
    const fps = parseInt(els.mirrorFps && els.mirrorFps.value, 10) || 2;
    mirrorTimer = setInterval(tick, Math.max(120, Math.round(500 / Math.max(1, fps))));
    if (els.toolMirrorStop) els.toolMirrorStop.disabled = false;
  }

  function stopMirrorPreview() {
    if (mirrorTimer) { clearInterval(mirrorTimer); mirrorTimer = null; }
    mirrorFrameUrl = "";
    if (els.mirrorPreview) els.mirrorPreview.hidden = true;
    if (els.mirrorView) els.mirrorView.removeAttribute("src");
    if (els.toolMirrorStop) els.toolMirrorStop.disabled = true;
  }

  /* 预览区大小（0,0 = 自适应：交给 CSS 的 max-width / max-height）。
     低帧率预览是「内嵌一张不断刷新的截图」，默认高度只有 280px，看列表、
     看文字时细节全靠猜；给个右下角手柄让它能拖大，投屏才真能当第二块屏用。 */
  const MIRROR_MIN_W = 200, MIRROR_MIN_H = 120, MIRROR_MAX_H = 900;
  let mirrorViewSize = { w: 0, h: 0 };

  function applyMirrorViewSize(w, h) {
    const nw = Math.max(0, Math.round(Number(w) || 0));
    const nh = Math.max(0, Math.round(Number(h) || 0));
    mirrorViewSize = (nw && nh) ? { w: nw, h: nh } : { w: 0, h: 0 };
    const frame = els.mirrorFrame;
    if (!frame) return;
    const sized = mirrorViewSize.w > 0;
    frame.classList.toggle("is-sized", sized);
    if (sized) {
      frame.style.width = mirrorViewSize.w + "px";
      frame.style.height = mirrorViewSize.h + "px";
    } else {
      frame.style.width = "";
      frame.style.height = "";
    }
  }

  function bindMirrorResize() {
    const grip = els.mirrorGrip;
    const frame = els.mirrorFrame;
    if (!grip || !frame) return;
    let drag = null;
    grip.addEventListener("pointerdown", (e) => {
      const fr = frame.getBoundingClientRect ? frame.getBoundingClientRect() : null;
      // 横向上限取「所在工具卡的内容宽」而不是预览框当前宽：预览框是
      // inline-flex，宽度跟着画面内容收缩，拿它当上限等于「永远只能这么宽」，
      // 用户一像素都拖不大 —— 这正是旧实现横向拖不动的根因。
      const body = frame.closest && frame.closest(".tool-body");
      drag = {
        x: e.clientX, y: e.clientY,
        // 起点用「当前实际渲染尺寸」而不是 storage 里的值：首次拖动前是自适应，
        // 两者并不相等，用存储值会让第一下拖动跳一段。
        w: mirrorViewSize.w || Math.round((fr && fr.width) || 0) || 260,
        h: mirrorViewSize.h || Math.round((fr && fr.height) || 0) || 420,
        maxW: Math.max(MIRROR_MIN_W,
          Math.round((body && body.clientWidth) || 720) - 20),
      };
      frame.classList.add("is-resizing");
      if (grip.setPointerCapture && e.pointerId != null) {
        try { grip.setPointerCapture(e.pointerId); } catch (_) { /* 部分环境不支持 */ }
      }
      e.preventDefault();
      e.stopPropagation();
    });
    grip.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const w = Math.min(drag.maxW, Math.max(MIRROR_MIN_W, drag.w + (e.clientX - drag.x)));
      const h = Math.min(MIRROR_MAX_H, Math.max(MIRROR_MIN_H, drag.h + (e.clientY - drag.y)));
      applyMirrorViewSize(w, h);
      e.preventDefault();
    });
    const end = () => {
      if (!drag) return;
      drag = null;
      frame.classList.remove("is-resizing");
      persistPrefs({ mirror_view_w: mirrorViewSize.w, mirror_view_h: mirrorViewSize.h });
    };
    grip.addEventListener("pointerup", end);
    grip.addEventListener("pointercancel", end);
    // 双击恢复自适应：拖成一条缝之后若没有还原入口，用户只能一直拖着走。
    grip.addEventListener("dblclick", (e) => {
      e.preventDefault();
      applyMirrorViewSize(0, 0);
      persistPrefs({ mirror_view_w: 0, mirror_view_h: 0 });
    });
  }

  /* 截图预览：每次截屏后在卡片下方生成，默认宽度自适应工具卡内容区最大宽度，
     右下角手柄可拖动改变大小、双击恢复自适应（复用备用投屏预览的手感）。 */
  const SHOT_PREVIEW_MIN_W = 160, SHOT_PREVIEW_MIN_H = 120, SHOT_PREVIEW_MAX_H = 1400;
  let shotPreviewSize = { w: 0, h: 0 };
  let shotPreviewSeq = 0;   // 多设备连拍时只认最后一次请求，防止旧响应覆盖新图
  let shotPreviewLastPath = "";

  function setShotPreviewLoading(loading) {
    const frame = els.shotPreviewFrame;
    if (!frame) return;
    const busy = !!loading;
    frame.classList.toggle("is-loading", busy);
    if (busy) {
      frame.classList.remove("is-error");
      frame.setAttribute("aria-busy", "true");
    } else {
      frame.removeAttribute("aria-busy");
    }
    const note = els.shotPreviewLoading;
    if (note) {
      note.hidden = !busy;
      if (busy) {
        note.classList.remove("is-error");
        note.setAttribute("role", "status");
        note.removeAttribute("tabindex");
        note.title = "";
        if (els.shotPreviewLoadingText) els.shotPreviewLoadingText.textContent = "正在生成预览…";
      }
    }
  }

  /* 预览失败不是「没反应」：遮罩变成可点击的重试按钮，保留首次失败原因，
     鼠标 / 键盘都能再来一次。读盘失败和图片解码失败走同一套。 */
  function setShotPreviewError(message) {
    const frame = els.shotPreviewFrame;
    if (frame) {
      frame.classList.remove("is-loading");
      frame.classList.add("is-error");
      frame.removeAttribute("aria-busy");
    }
    if (els.shotPreviewImg) {
      // 先清 seq 再撤 src：部分 WebView 撤掉坏图时会再触发一次 error，
      // 不标记就会把「重试中」又打回失败态。
      els.shotPreviewImg.dataset.seq = "";
      els.shotPreviewImg.removeAttribute("src");
      els.shotPreviewImg.style.visibility = "";
    }
    const note = els.shotPreviewLoading;
    if (note) {
      note.hidden = false;
      note.classList.add("is-error");
      note.setAttribute("role", "button");
      note.setAttribute("tabindex", "0");
      note.title = "点击重新生成预览";
      if (els.shotPreviewLoadingText) els.shotPreviewLoadingText.textContent = message;
    }
  }

  async function showShotPreview(path) {
    if (!els.shotPreview || !els.shotPreviewImg) return;
    const seq = ++shotPreviewSeq;
    shotPreviewLastPath = String(path || "");
    const nameOfPath = String(path || "").split(/[\\/]/).pop() || String(path || "");
    // 先亮出预览块与转圈，再去读盘：读盘 + base64 传输是秒级操作，
    // 若等结果回来才显示，用户会看到卡片下方空一块、没有任何「在做事」的迹象。
    els.shotPreview.hidden = false;
    setShotPreviewLoading(true);
    if (els.shotPreviewName) {
      els.shotPreviewName.textContent = "正在生成预览…" + (nameOfPath ? "（" + nameOfPath + "）" : "");
      els.shotPreviewName.title = path;
      els.shotPreviewName.classList.remove("err");
    }
    const res = await callApi(api.screenshot_data(path));
    if (seq !== shotPreviewSeq) return;   // 已有更新的一次预览请求，丢弃旧结果
    setShotPreviewLoading(false);
    if (!res || !res.ok || !res.data) {
      setShotPreviewError("预览生成失败 · 点击重试");
      if (els.shotPreviewName) {
        els.shotPreviewName.textContent = "预览生成失败，点击重试：" + nameOfPath;
        els.shotPreviewName.classList.add("err");
        els.shotPreviewName.title = "点击重新生成预览";
      }
      return;
    }
    if (els.shotPreviewName) els.shotPreviewName.classList.remove("err");
    els.shotPreviewImg.dataset.seq = String(seq);
    els.shotPreviewImg.src = "data:image/png;base64," + res.data;
    if (els.shotPreviewName) {
      els.shotPreviewName.textContent = res.name || path;
      els.shotPreviewName.title = path;
    }
  }

  function applyShotPreviewSize(w, h) {
    const nw = Math.max(0, Math.round(Number(w) || 0));
    const nh = Math.max(0, Math.round(Number(h) || 0));
    shotPreviewSize = (nw && nh) ? { w: nw, h: nh } : { w: 0, h: 0 };
    const frame = els.shotPreviewFrame;
    if (!frame) return;
    const sized = shotPreviewSize.w > 0;
    frame.classList.toggle("is-sized", sized);
    if (sized) {
      frame.style.width = shotPreviewSize.w + "px";
      frame.style.height = shotPreviewSize.h + "px";
    } else {
      frame.style.width = "";
      frame.style.height = "";
    }
  }

  function bindShotPreviewResize() {
    const grip = els.shotPreviewGrip;
    const frame = els.shotPreviewFrame;
    if (!grip || !frame) return;

    // 预览失败后的重试入口：鼠标点遮罩 / 键盘 Enter·Space / 点文件名都能重来。
    const retry = () => {
      if (!shotPreviewLastPath) return;
      showShotPreview(shotPreviewLastPath);
    };
    if (els.shotPreviewLoading) {
      els.shotPreviewLoading.addEventListener("click", () => {
        if (els.shotPreviewLoading.classList.contains("is-error")) retry();
      });
      els.shotPreviewLoading.addEventListener("keydown", (e) => {
        if (!els.shotPreviewLoading.classList.contains("is-error")) return;
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); retry(); }
      });
    }
    if (els.shotPreviewName) {
      els.shotPreviewName.addEventListener("click", () => {
        if (els.shotPreviewName.classList.contains("err")) retry();
      });
    }
    if (els.shotPreviewImg) {
      // base64 坏掉 / 截断时 <img> 只会显示裂图标；把失败写回遮罩，给统一重试入口。
      els.shotPreviewImg.addEventListener("error", () => {
        const seq = els.shotPreviewImg.dataset.seq;
        if (!seq || seq !== String(shotPreviewSeq)) return;
        const base = shotPreviewLastPath.split(/[\\/]/).pop() || shotPreviewLastPath;
        setShotPreviewError("预览图解码失败 · 点击重试");
        if (els.shotPreviewName) {
          els.shotPreviewName.textContent = "预览图解码失败，点击重试：" + base;
          els.shotPreviewName.classList.add("err");
          els.shotPreviewName.title = "点击重新生成预览";
        }
      });
    }

    let drag = null;
    grip.addEventListener("pointerdown", (e) => {
      const fr = frame.getBoundingClientRect ? frame.getBoundingClientRect() : null;
      // 横向上限取「所在工具卡内容区宽」而非预览框当前宽：预览框默认 width:100%，
      // 拿它当上限等于「永远只能这么宽」，用户一像素都拖不大。
      const body = frame.closest && frame.closest(".tool-body");
      drag = {
        x: e.clientX, y: e.clientY,
        w: shotPreviewSize.w || Math.round((fr && fr.width) || 0) || 320,
        h: shotPreviewSize.h || Math.round((fr && fr.height) || 0) || 480,
        maxW: Math.max(SHOT_PREVIEW_MIN_W,
          Math.round((body && body.clientWidth) || 720) - 20),
      };
      frame.classList.add("is-resizing");
      if (grip.setPointerCapture && e.pointerId != null) {
        try { grip.setPointerCapture(e.pointerId); } catch (_) { /* 部分环境不支持 */ }
      }
      e.preventDefault();
      e.stopPropagation();
    });
    grip.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const w = Math.min(drag.maxW, Math.max(SHOT_PREVIEW_MIN_W,
        drag.w + (e.clientX - drag.x)));
      const h = Math.min(SHOT_PREVIEW_MAX_H, Math.max(SHOT_PREVIEW_MIN_H,
        drag.h + (e.clientY - drag.y)));
      applyShotPreviewSize(w, h);
      e.preventDefault();
    });
    const end = () => {
      if (!drag) return;
      drag = null;
      frame.classList.remove("is-resizing");
      persistPrefs({ shot_preview_w: shotPreviewSize.w, shot_preview_h: shotPreviewSize.h });
    };
    grip.addEventListener("pointerup", end);
    grip.addEventListener("pointercancel", end);
    // 双击恢复自适应：拖成一条缝之后若没有还原入口，用户只能一直拖着走。
    grip.addEventListener("dblclick", (e) => {
      e.preventDefault();
      applyShotPreviewSize(0, 0);
      persistPrefs({ shot_preview_w: 0, shot_preview_h: 0 });
    });
  }

  /* 探测 scrcpy 与播放器各自的可用性，写进「备用投屏」的状态行 —— 用户点之前
     就能知道自己会落到哪一档，而不是点了才发现没装播放器。 */
  async function probeMirror() {
    if (!hasApi()) { setMirrorState("", "未就绪"); return; }
    setMirrorState("", "检测中…");
    const res = await callApi(api.mirror_probe());
    if (!res) { setMirrorState("err", "检测失败：后端无响应"); return; }
    const sc = res.scrcpy || {}, pl = res.player || {};
    if (sc.ok) {
      setMirrorState("ok", "已装 scrcpy，建议直接用上方按钮 · 备用档待命",
                     "备用档：优先 screenrecord 管道投屏");
      return;
    }
    if (pl.ok) {
      setMirrorState("ok", "备用档：screenrecord → " + pl.kind + " 播放器窗口",
                     pl.note + "\n" + pl.path);
    } else {
      setMirrorState("", "备用档：低帧率预览（未找到播放器）", pl.note || "");
    }
  }

  /* ---------------- 性能监控（实时曲线 + 报告导出） ----------------
     数据链路：后端一条采样线程写环形缓冲 -> 前端每 600ms 调 perf_poll(seq) 拉增量
     -> 本地拼成全量数组 -> 画布重绘（rAF 合并）。刻意**不走事件总线**：监控数据
     是「持续高频、可丢中间帧」的，走 take_events 会把状态/日志的队列预算白白吃掉。 */
  // unit 与后端 backend/perf_service.METRICS 的第四列一一对应（报告里用的也是
  // 这一套单位）：悬停提示是唯一「数字和单位写在一起」的地方，缺了就会显示
  // undefined。刻意不从后端下发——这张表还带着颜色与量程，属于前端的表现层。
  const PERF_METRICS = {
    cpu:      { title: "CPU 占用率",   color: "#34e0ea", cap: 100,  unit: "%" },
    mem_used: { title: "系统内存占用", color: "#4cc3ff", cap: null, unit: "MB" },
    pss:      { title: "应用内存 PSS", color: "#a78bfa", cap: null, unit: "MB" },
    fps:      { title: "帧率",         color: "#3ddc84", cap: null, unit: "FPS" },
    // 卡顿率不写死 0~100：真实区间卡顿率常年 1~15%，按 100 画会全挤在底部
    // 一条直线上，看不出任何波动；自适应 + 把 8% 阈值纳入范围才是能读的图。
    jank:     { title: "卡顿率",       color: "#f472b6", cap: null, unit: "%" },
    batt:     { title: "电量",         color: "#ffb454", cap: 100,  unit: "%" },
    temp:     { title: "电池温度",     color: "#ff5f6b", cap: null, unit: "℃" },
  };
  const PERF_CHART_MAX = 1600;      // 画布最多绘制的点数（超出按步长抽稀）
  const PERF_KEEP_MAX = 20000;      // 本地保留的最大采样点数（与后端环形缓冲同量级）
  const PERF_POLL_MS = 600;
  // 多设备对比的线色。单设备时曲线仍随指标变色（与仪表盘其它曲线一致），
  // 多设备时改为「一设备一色」——对比场景里认的是设备，不是指标。
  const PERF_SERIES_COLORS = ["#34e0ea", "#3ddc84", "#ffb454", "#a78bfa",
                              "#f472b6", "#4cc3ff"];

  let perfRunning = false;
  let perfTimer = null;             // 轮询定时器
  // serial -> {samples, seq, info, running}。多设备同时监控时每台一份，
  // 各设备的游标（seq）彼此独立：某台掉线重连不会让另一台重复拉取。
  let perfSessions = new Map();
  let perfFocus = "";               // 指标卡读数 / 单线模式对应的设备
  let perfMetric = "cpu";           // 当前曲线指标
  let perfInfo = {};
  let perfDrawQueued = false;
  // 告警阈值由后端下发（backend/perf_service.DEFAULT_THRESHOLDS），前端不抄一份：
  // 两份常量必然漂移，最后会出现「报告说没超标、界面标红」的自相矛盾。
  let perfThresholds = {};          // key -> {min?, max?}
  let perfRules = {};               // key -> "FPS < 45"（人话，用于 tooltip / toast）
  let perfThItems = [];             // 后端下发的四条规则元数据（方向 / 范围 / 理由）
  let perfThDefault = "";           // 内置基线的表达式（「恢复默认」用）
  let perfAlertOn = {};             // key -> true：当前处于告警中（用于边沿提示）
  let perfAlertQuiet = 0;           // 下一条告警 toast 的最早时间（节流）
  // 悬停提示用：最近一次绘制的坐标布局（指针事件里要按同一套像素换算，
  // 否则竖线会与曲线差几个像素，看起来像「标错了点」），以及当前指针 X。
  let perfGeom = null;
  let perfHoverX = null;
  // 区间框选：拖动中只记像素区间（每帧都在重算统计纯属浪费），松手才换算成
  // 时间并算一遍。perfRange 存下来是为了让「采样继续进来」时数字跟着更新。
  let perfDrag = null;              // {x0}：左键按下后的起点（已夹取到绘图区）
  let perfRange = null;             // {a, b, t0, t1, rows, …}：松手后的选区
  const PERF_RANGE_MIN = 8;         // 小于 8px 当点击处理（手抖不该出统计卡）

  function perfPrimarySerial() {
    const first = perfSessions.keys().next();
    return first.done ? "" : first.value;
  }

  function perfSamplesOf(serial) {
    const s = perfSessions.get(serial);
    return s ? s.samples : [];
  }

  function perfFocusSamples() {
    return perfSamplesOf(perfFocus || perfPrimarySerial());
  }

  function perfTotalPoints() {
    let n = 0;
    for (const s of perfSessions.values()) n += s.samples.length;
    return n;
  }

  function perfColorOf(serial) {
    const keys = Array.from(perfSessions.keys());
    const i = Math.max(0, keys.indexOf(serial));
    return PERF_SERIES_COLORS[i % PERF_SERIES_COLORS.length];
  }

  /* 设备短名：型号重复时（同型号批量测试很常见）靠序列号尾部区分。 */
  function perfLabelOf(serial) {
    const sess = perfSessions.get(serial);
    const model = sess && sess.info && sess.info.model;
    const tail = serial.length > 10 ? serial.slice(-4) : serial;
    return model ? model + " · " + tail : tail;
  }

  async function loadPerfThresholds() {
    if (!hasApi() || !api.perf_thresholds) return;
    applyPerfThresholds(await callApi(api.perf_thresholds()));
  }

  /* 阈值/规则一变就整体换掉并重算一遍：标红、虚线、toast 判定全都读这里，
     少更新一处就会出现「线画在新位置、卡片还按旧阈值红着」。 */
  function applyPerfThresholds(res) {
    if (!res || typeof res !== "object") return;
    if (res.thresholds && typeof res.thresholds === "object") {
      perfThresholds = res.thresholds;
    }
    perfRules = res.rules || {};
    perfThItems = Array.isArray(res.items) ? res.items : perfThItems;
    perfThDefault = res.default_expr || perfThDefault;
    perfAlertOn = {};                 // 规则变了，旧的「已提示」状态不再成立
    updatePerfStats();
    queuePerfDraw();
  }

  /* ---------------- 阈值设置弹窗 ----------------
     四行由后端下发的 items 渲染（方向 / 单位 / 取值范围 / 取值理由都在后端），
     前端不硬编码 —— 抄一份的下场是界面写 45、报告按 50 判。 */
  function renderPerfThresholdRows(items) {
    const box = els.perfThRows;
    if (!box) return;
    box.innerHTML = items.map((it) => {
      const on = it.value !== null && it.value !== undefined;
      // default 是 JS 保留字：用下标访问，避免个别解析器把它当关键字报错
      const val = on ? it.value : it["default"];
      const opTxt = it.dir === "min" ? "低于" : "高于";
      return '<label class="th-row' + (on ? " on" : "") + '" data-key="' + escAttr(it.key) + '">'
        + '<input type="checkbox" class="th-on"' + (on ? " checked" : "") + ">"
        + '<span class="th-name">' + escHtml(it.title) + "</span>"
        + '<span class="th-op">' + opTxt + "</span>"
        + '<span class="th-val-wrap">'
        + '<input type="number" class="inp th-val" step="any" min="' + (it.min ?? "")
        + '" max="' + (it.max ?? "") + '" value="' + (val === null || val === undefined ? "" : val) + '">'
        + '<span class="th-unit">' + escHtml(it.unit || "") + "</span></span>"
        + '<span class="th-hint">' + escHtml(it.hint || "") + "</span>"
        + "</label>";
    }).join("");
  }

  function showPerfThError(msg) {
    if (!els.perfThErr) return;
    els.perfThErr.hidden = !msg;
    els.perfThErr.textContent = msg || "";
  }

  async function openPerfThresholds() {
    if (!els.perfThModal) return;
    // 首次打开时元数据可能还没回来（boot 里那几个 await 与用户点击是并发的），
    // 现场补拉一次：打开一个空白弹窗比晚 100ms 打开糟糕得多。
    if (!perfThItems.length && hasApi() && api.perf_thresholds) {
      await loadPerfThresholds();
    }
    renderPerfThresholdRows(perfThItems);
    showPerfThError("");
    els.perfThModal.classList.remove("hidden");
  }

  function closePerfThresholds() {
    if (els.perfThModal) els.perfThModal.classList.add("hidden");
  }

  async function savePerfThresholds() {
    if (!els.perfThRows) return;
    const values = {};
    const rows = els.perfThRows.querySelectorAll(".th-row");
    for (const row of rows) {
      const key = row.dataset.key;
      const on = row.querySelector(".th-on");
      if (!on || !on.checked) { values[key] = null; continue; }
      const box = row.querySelector(".th-val");
      const raw = (box && box.value || "").trim();
      const n = Number(raw);
      if (!raw || !isFinite(n)) {
        showPerfThError("「" + (row.querySelector(".th-name") || {}).textContent
          + "」的阈值要填数字");
        return;
      }
      values[key] = n;
    }
    const res = await callApi(api.perf_set_thresholds(values));
    if (!res || !res.ok) {
      const why = (res && res.errors && res.errors[0]) || "保存失败（配置目录可能只读）";
      showPerfThError(why);
      return;
    }
    applyPerfThresholds(res);
    closePerfThresholds();
  }

  /* 是否越过阈值。min = 低于即告警（帧率），max = 高于即告警（卡顿/温度/CPU）。 */
  function perfBeyond(key, v) {
    const th = perfThresholds[key];
    if (!th || typeof v !== "number" || !isFinite(v)) return false;
    if (typeof th.min === "number" && v < th.min) return true;
    if (typeof th.max === "number" && v > th.max) return true;
    return false;
  }

  /* 进入告警的那一刻提示一次（离开后再次进入会重新提示）。
     1Hz 采样下一条抖动曲线会反复穿阈值，故 8 秒内最多弹一条 toast——
     否则状态栏会被「帧率 44.8 / 45.2」刷成跑马灯。 */
  function perfAlertEdge(key, v, who) {
    const id = (who ? who + "|" : "") + key;
    const bad = perfBeyond(key, v);
    if (!bad) { delete perfAlertOn[id]; return; }
    if (perfAlertOn[id]) return;
    perfAlertOn[id] = true;
    const now = Date.now();
    if (now < perfAlertQuiet) return;
    perfAlertQuiet = now + 8000;
    showToast("warn", (who ? who + "：" : "") + (perfRules[key] || "超出阈值")
              + "（当前 " + fmtNum(v) + "）");
  }

  function fmtNum(v) {
    if (typeof v !== "number" || !isFinite(v)) return "--";
    return Math.abs(v - Math.round(v)) < 0.05 ? String(Math.round(v)) : v.toFixed(1);
  }

  /* 拼 innerHTML 时的转义（唯一姿势）。设备型号 / 包名 / 阈值说明都可能带
     `<` `>` `&` `"`，不转义轻则截断标签，重则注进一个假按钮。 */
  function escHtml(s) {
    return String(s === null || s === undefined ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function escAttr(s) {
    return escHtml(s).replace(/'/g, "&#39;");
  }

  function renderPerfDev() {
    const list = checkedDevices();
    const s = firstChecked();
    if (els.perfDev) {
      els.perfDev.textContent = !s ? "未选设备"
        : (list.length > 1 ? "设备: " + s + " 等 " + list.length + " 台" : "设备: " + s);
      els.perfDev.classList.toggle("off", !s);
      els.perfDev.title = !s ? "请先在左侧勾选设备"
        : (list.length > 1
          ? "将同时监控 " + list.length + " 台受控设备并画在同一张图上对比"
          : "性能监控目标设备（取左侧第一台受控设备）");
    }
    syncPerfButtons();
  }

  function syncPerfButtons() {
    const any = checkedDevices().length > 0;
    if (els.perfStart) els.perfStart.disabled = !any || perfRunning;
    if (els.perfStop) els.perfStop.disabled = !perfRunning;
    // 停止后仍可导出（数据保留在本地与后端会话里），但没有样本时不给点
    if (els.perfExport) els.perfExport.disabled = perfTotalPoints() === 0;
  }

  function setPerfState(text, kind, title) {
    if (!els.perfState) return;
    els.perfState.className = "scrcpy-state" + (kind ? " " + kind : "");
    els.perfState.textContent = text || "";
    els.perfState.title = title || "";
  }

  function setPerfRunning(on) {
    perfRunning = !!on;
    if (!on && perfTimer) { clearTimeout(perfTimer); perfTimer = null; }
    syncPerfButtons();
  }

  /* 指标卡读数：当前值 + 均值/峰值/谷值。多设备时读**焦点设备**的那一份
     （焦点由图例点击切换），对比模式下把各设备数值交给图例展示。 */
  function updatePerfStats() {
    const keys = Object.keys(PERF_METRICS);
    const samples = perfFocusSamples();
    const label = perfLabelOf(perfFocus || perfPrimarySerial());
    for (const key of keys) {
      let n = 0, sum = 0, min = Infinity, max = -Infinity, last = null;
      for (const s of samples) {
        const v = s[key];
        if (typeof v !== "number" || !isFinite(v)) continue;
        n++; sum += v; last = v;
        if (v < min) min = v;
        if (v > max) max = v;
      }
      const vEl = $("perf-v-" + key), sEl = $("perf-s-" + key);
      if (vEl) vEl.textContent = last === null ? "--" : fmtNum(last);
      if (sEl) {
        // 卡片宽度只有 ~110px：写「均 25.2 · 峰 49.3 · 谷 7.1」必被截成省略号。
        // 故常显「区间」（最小~最大，一眼看出波动范围），完整的均值/峰值/谷值
        // 放进 title，报告里另有一整张统计表。
        sEl.textContent = !n ? "等待数据"
          : (n === 1 ? "采样中…" : fmtNum(min) + " ~ " + fmtNum(max));
        sEl.title = n
          ? "均 " + fmtNum(sum / n) + " · 峰 " + fmtNum(max) + " · 谷 " + fmtNum(min)
            + "（" + n + " 个采样点）"
          : "";
        const card = document.getElementById("perf-stat-" + key);
        if (card) {
          const bad = last !== null && perfBeyond(key, last);
          card.classList.toggle("warn", bad);
          const tips = [];
          if (perfSessions.size > 1 && label) tips.push("设备：" + label);
          if (bad) tips.push("⚠ " + (perfRules[key] || "超出告警阈值"));
          card.title = tips.join("\n");
        }
      }
    }
    updatePerfLegend();
    // 告警逐个设备检查（对比模式下 B2 超标不该被 A1 的正常值掩盖）
    for (const [serial, sess] of perfSessions) {
      const lastSample = sess.samples[sess.samples.length - 1];
      if (!lastSample) continue;
      const who = perfSessions.size > 1 ? perfLabelOf(serial) : "";
      for (const key of Object.keys(PERF_METRICS)) {
        const v = lastSample[key];
        if (typeof v === "number" && isFinite(v)) perfAlertEdge(key, v, who);
      }
    }
    if (els.perfChartSub) {
      const total = perfTotalPoints();
      const multi = perfSessions.size > 1 ? perfSessions.size + " 台 · " : "";
      els.perfChartSub.textContent = perfRunning
        ? "LIVE · " + multi + total + " 点"
        : (total ? "已停止 · " + multi + total + " 点" : "LIVE");
    }
  }

  /* 图例：多设备对比时才出现。显示设备短名 + 当前指标的最新读数，
     点击某一项把指标卡与末端气泡切到那台设备（再点一次不取消，避免误触空态）。
     节点逐个 createElement：设备型号来自设备端，拼 innerHTML 等于把设备名
     当 HTML 执行。 */
  function updatePerfLegend() {
    const box = els.perfLegend;
    if (!box) return;
    box.textContent = "";
    if (perfSessions.size <= 1) { box.hidden = true; return; }
    box.hidden = false;
    for (const serial of perfSessions.keys()) {
      const samples = perfSamplesOf(serial);
      let last = null;
      for (let i = samples.length - 1; i >= 0; i--) {
        const v = samples[i][perfMetric];
        if (typeof v === "number" && isFinite(v)) { last = v; break; }
      }
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "perf-lg" + (serial === perfFocus ? " on" : "");
      btn.dataset.serial = serial;
      btn.title = "切换到这台设备（指标卡与末端读数）";
      const dot = document.createElement("i");
      dot.style.background = perfColorOf(serial);
      const nm = document.createElement("span");
      nm.className = "n";
      nm.textContent = perfLabelOf(serial);
      const val = document.createElement("b");
      val.textContent = last === null ? "--" : fmtNum(last);
      btn.appendChild(dot);
      btn.appendChild(nm);
      btn.appendChild(val);
      box.appendChild(btn);
    }
  }

  function focusPerf(serial) {
    if (!perfSessions.has(serial) || serial === perfFocus) return;
    perfFocus = serial;
    updatePerfStats();
    queuePerfDraw();
  }

  /* ---------------- 曲线悬停提示（tooltip） ----------------
     逐条线取「离指针最近的那个采样点」，再取其中最近的一条作为锚点时间。
     容差 26px：超出就当作没命中——鼠标停在空白处也弹一张卡片出来，会挡住
     本来能看见的曲线，比不提示更烦人。
     多设备时每行一台（各自取离锚点最近的采样），与图例、报告口径一致。 */
  const PERF_TIP_TOL = 26;

  function perfClock(t) {
    if (!t) return "--:--:--";
    const d = new Date(t * 1000);
    const p2 = (n) => (n < 10 ? "0" + n : String(n));
    return p2(d.getHours()) + ":" + p2(d.getMinutes()) + ":" + p2(d.getSeconds());
  }

  function perfPointX(g, p, i, n) {
    return g.useTime
      ? g.padL + g.iw * ((p.t - g.tMin) / (g.tMax - g.tMin))
      : g.padL + g.iw * (i / Math.max(1, n - 1));
  }

  // 纯计算：给定指针 X 返回 {x, y, t, rows}；没命中返回 null。
  function perfTipModel(x) {
    const g = perfGeom;
    if (!g) return null;
    let anchor = null;
    for (const s of g.all) {
      const n = s.pts.length;
      for (let i = 0; i < n; i++) {
        const p = s.pts[i];
        if (p.v === null) continue;
        const px = perfPointX(g, p, i, n);
        const d = Math.abs(px - x);
        if (!anchor || d < anchor.d) anchor = { d, x: px, p };
      }
    }
    if (!anchor || anchor.d > PERF_TIP_TOL) return null;
    const rows = [];
    for (const s of g.all) {
      const n = s.pts.length;
      let pick = null;
      for (let i = 0; i < n; i++) {
        const p = s.pts[i];
        if (p.v === null) continue;
        const d = Math.abs(perfPointX(g, p, i, n) - x);
        if (!pick || d < pick.d) pick = { d, p };
      }
      if (!pick) continue;
      rows.push({ serial: s.serial, color: s.color,
                  label: perfLabelOf(s.serial), value: pick.p.v });
    }
    if (!rows.length) return null;
    return { x: anchor.x, y: g.yOf(anchor.p.v), t: anchor.p.t, rows };
  }

  function updatePerfTip() {
    const tip = els.perfTip, cross = els.perfCross;
    if (!tip) return;
    const model = perfHoverX === null ? null : perfTipModel(perfHoverX);
    if (!model) {
      if (!tip.hidden) tip.hidden = true;
      if (cross && !cross.hidden) cross.hidden = true;
      return;
    }
    const g = perfGeom;
    const meta = PERF_METRICS[perfMetric] || PERF_METRICS.cpu;
    if (cross) {
      cross.hidden = false;
      cross.style.left = Math.round(model.x) + "px";
    }
    tip.innerHTML = '<div class="pt-time">' + perfClock(model.t) + "</div>"
      + model.rows.map((r) =>
        '<div class="pt-row"><span class="pt-dot" style="background:' + r.color
        + '"></span><span class="pt-name">' + escHtml(r.label)
        + '</span><span class="pt-val">' + fmtNum(r.value)
        + "<small>" + escHtml(meta.unit) + "</small></span></div>").join("");
    tip.hidden = false;
    // 定位：优先贴竖线右侧、数值上方；靠边时翻到另一侧，卡片不被画布裁掉。
    // offsetWidth 在隐藏态下为 0（jsdom 恒为 0），退化成固定估宽即可。
    const tw = tip.offsetWidth || 148;
    const th = tip.offsetHeight || 68;
    let left = model.x + 14;
    if (left + tw > g.w - 4) left = Math.max(4, model.x - tw - 14);
    let top = model.y - th - 12;
    top = Math.max(4, Math.min(top, g.h - th - 4));
    tip.style.left = Math.round(left) + "px";
    tip.style.top = Math.round(top) + "px";
  }

  /* ---------------- 区间框选统计（按住横拖） ----------------
     悬停回答「这一刻是多少」，框选回答「这一段怎么样」——定位一次卡顿要看
     区间均值 / 最差值和超阈值次数，逐点读数反而拼不出来。
     选框与统计卡都用 DOM：拖动时只改 left/width，不触发画布重绘才跟手。 */
  function perfLocalX(e) {
    const cv = els.perfCanvas;
    if (!cv || !perfGeom) return null;
    const r = cv.getBoundingClientRect ? cv.getBoundingClientRect() : null;
    const wpx = (r && r.width) || cv.clientWidth || 0;
    if (!wpx) return null;
    const left = r && r.width ? r.left : 0;
    const x = e.clientX - left;
    return (x < 0 || x > wpx) ? null : x;
  }

  // 夹到绘图区：拖到纵轴左边或右边界外时，选区不该跟着跑出画布
  function perfClampX(g, x) {
    return Math.max(g.padL, Math.min(g.padL + g.iw, x));
  }

  function perfTimeAt(g, x) {
    const f = g.iw ? (x - g.padL) / g.iw : 0;
    return g.tMin + f * (g.tMax - g.tMin);
  }

  /* 分位数用 nearest-rank（第 ceil(p·n) 个）：小样本下比线性插值更贴近
     「第 95 个百分点上的实测值」，报告里也能照着复现。 */
  function perfPct(sorted, p) {
    if (!sorted.length) return null;
    const i = Math.min(sorted.length - 1, Math.max(0, Math.ceil(p * sorted.length) - 1));
    return sorted[i];
  }

  // 纯计算：像素区间 → 各设备统计。没有可用采样返回 null。
  function perfRangeModel(x0, x1) {
    const g = perfGeom;
    if (!g) return null;
    const a = perfClampX(g, Math.min(x0, x1));
    const b = perfClampX(g, Math.max(x0, x1));
    if (b - a < PERF_RANGE_MIN) return null;
    const meta = PERF_METRICS[perfMetric] || PERF_METRICS.cpu;
    const th = perfThresholds[perfMetric] || {};
    const thMin = typeof th.min === "number" ? th.min : null;
    const thMax = typeof th.max === "number" ? th.max : null;
    const t0 = g.useTime ? perfTimeAt(g, a) : 0;
    const t1 = g.useTime ? perfTimeAt(g, b) : 0;
    const f0 = g.iw ? (a - g.padL) / g.iw : 0;
    const f1 = g.iw ? (b - g.padL) / g.iw : 1;
    const rows = [];
    for (const s of g.all) {
      const n = s.pts.length;
      // 没有时间轴时（所有采样 t 相同，个别机型 uptime 精度不够）退回按
      // 索引比例取，总比「拖了却什么都选不中」强。
      const ia = Math.floor(f0 * n);
      const ib = Math.ceil(f1 * n);
      const vals = [];
      for (let i = 0; i < n; i++) {
        const p = s.pts[i];
        if (p.v === null) continue;
        const inside = g.useTime
          ? (p.t >= t0 - 1e-6 && p.t <= t1 + 1e-6)
          : (i >= ia && i <= ib);
        if (inside) vals.push(p.v);
      }
      if (!vals.length) continue;
      let sum = 0, over = 0;
      for (const v of vals) {
        sum += v;
        if ((thMin !== null && v < thMin) || (thMax !== null && v > thMax)) over++;
      }
      const sorted = vals.slice().sort((m, k) => m - k);
      rows.push({
        serial: s.serial, color: s.color, label: perfLabelOf(s.serial),
        n: vals.length, avg: sum / vals.length,
        min: sorted[0], max: sorted[sorted.length - 1],
        p95: perfPct(sorted, 0.95), over,
      });
    }
    if (!rows.length) return null;
    return { a, b, t0, t1, useTime: g.useTime, rows,
             unit: meta.unit, hasTh: thMin !== null || thMax !== null };
  }

  function paintPerfBand(a, b) {
    const band = els.perfBand;
    if (!band) return;
    if (a === null || b === null) { if (!band.hidden) band.hidden = true; return; }
    band.hidden = false;
    band.style.left = Math.round(Math.min(a, b)) + "px";
    band.style.width = Math.max(1, Math.round(Math.abs(b - a))) + "px";
  }

  function renderPerfRange(model) {
    const card = els.perfRange;
    if (!card) return;
    if (!model) { if (!card.hidden) card.hidden = true; return; }
    const g = perfGeom;
    const span = model.useTime
      ? perfClock(model.t0) + " – " + perfClock(model.t1)
      : "无时间轴";
    card.innerHTML =
      '<div class="pr-h"><span class="pr-t">区间统计</span>'
      + '<span class="pr-span">' + escHtml(span) + "</span>"
      + '<button type="button" class="pr-x" title="清除选区（Esc）">×</button></div>'
      + model.rows.map((r) =>
        '<div class="pr-row"><span class="pr-dot" style="background:' + r.color + '"></span>'
        + '<span class="pr-name">' + escHtml(r.label) + "</span>"
        + '<span class="pr-k">均值</span><span class="pr-v">' + fmtNum(r.avg) + "</span>"
        + '<span class="pr-k">最低</span><span class="pr-v">' + fmtNum(r.min) + "</span>"
        + '<span class="pr-k">P95</span><span class="pr-v">' + fmtNum(r.p95) + "</span>"
        + '<span class="pr-k">最高</span><span class="pr-v">' + fmtNum(r.max) + "</span>"
        + (model.hasTh
          ? '<span class="pr-over' + (r.over ? " hot" : "") + '">超阈值 ' + r.over + " 次</span>"
          : "")
        + '<span class="pr-n">' + r.n + " 点</span></div>").join("");
    card.hidden = false;
    // 贴选区右侧；右边放不下翻到左侧。offsetWidth 在隐藏态下为 0（jsdom
    // 恒为 0），退化成固定估宽即可。
    const cw = card.offsetWidth || 260;
    let left = model.b + 12;
    if (left + cw > g.w - 6) left = Math.max(6, model.a - cw - 12);
    card.style.left = Math.round(left) + "px";
  }

  function clearPerfRange() {
    perfDrag = null;
    perfRange = null;
    paintPerfBand(null, null);
    if (els.perfRange) els.perfRange.hidden = true;
  }

  /* 采样 / 指标 / 阈值变化后重算：选区像素位置不动，数字跟着新数据走——
     否则曲线往前走了，卡片里还是十秒前那一段的统计。 */
  function refreshPerfRange() {
    if (!perfRange) return;
    const model = perfRangeModel(perfRange.a, perfRange.b);
    if (!model) { clearPerfRange(); return; }
    perfRange = model;
    paintPerfBand(model.a, model.b);
    renderPerfRange(model);
  }

  function bindPerfHover() {
    const cv = els.perfCanvas;
    const wrap = cv && cv.parentElement;
    if (!wrap) return;
    wrap.addEventListener("pointermove", onPerfHover);
    wrap.addEventListener("pointerdown", onPerfDown);
    // 抬起挂在 window 上：拖到画布外再松手很常见，只听 wrap 的 pointerup
    // 会漏掉，选区就永远停在「拖动中」。
    window.addEventListener("pointerup", onPerfUp);
    // 移出画布 / 窗口失焦都要收起：否则提示会「粘」在最后的位置上，
    // 后续曲线继续刷新，卡片里却是不再变化的老数值。
    wrap.addEventListener("pointerleave", () => {
      if (perfDrag) return;                    // 拖动中移出去不算「离开」
      perfHoverX = null; updatePerfTip();
    });
    window.addEventListener("blur", () => { perfHoverX = null; updatePerfTip(); });
    // 双击还原、Esc 清除：都比「再拖一次盖掉」更符合直觉
    wrap.addEventListener("dblclick", () => clearPerfRange());
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && perfRange) clearPerfRange();
    });
    if (els.perfRange) {
      // 卡片内容会在每次重绘时替换，监听挂在卡片本身（它不会被替换）
      els.perfRange.addEventListener("click", (e) => {
        const t = e.target;
        if (t && t.classList && t.classList.contains("pr-x")) clearPerfRange();
      });
    }
  }

  function onPerfDown(e) {
    if (!perfGeom) return;
    if (typeof e.button === "number" && e.button !== 0) return;
    const x = perfLocalX(e);
    if (x === null) return;
    perfDrag = { x0: perfClampX(perfGeom, x) };
    // 拖动期间收起悬停提示：选区边线和十字线叠在一起会分不清谁是谁
    perfHoverX = null;
    updatePerfTip();
    const wrap = els.perfCanvas.parentElement;
    if (wrap && wrap.setPointerCapture && e.pointerId !== undefined) {
      try { wrap.setPointerCapture(e.pointerId); } catch (err) { /* 不支持不影响功能 */ }
    }
  }

  function onPerfUp(e) {
    if (!perfDrag) return;
    const start = perfDrag.x0;
    perfDrag = null;
    const x = perfLocalX(e);
    const end = (x === null || !perfGeom) ? start : perfClampX(perfGeom, x);
    const model = perfRangeModel(start, end);
    if (!model) { clearPerfRange(); return; }   // 太窄 = 当成点击，顺手清掉旧选区
    perfRange = model;
    paintPerfBand(model.a, model.b);
    renderPerfRange(model);
  }

  function onPerfHover(e) {
    const x = perfLocalX(e);
    if (perfDrag) {
      // 拖动中：只更新色带，不弹提示也不出统计（松手才算一次）
      if (x === null) return;
      paintPerfBand(perfDrag.x0, perfClampX(perfGeom, x));
      return;
    }
    perfHoverX = x;
    updatePerfTip();
  }

  function queuePerfDraw() {
    if (perfDrawQueued) return;
    perfDrawQueued = true;
    const run = () => { perfDrawQueued = false; drawPerfChart(); };
    if (window.requestAnimationFrame) window.requestAnimationFrame(run);
    else setTimeout(run, 16);
  }

  /* 画布重绘：DPR 自适应 + 抽稀 + 断点 + 多设备分色。
     没有数据的时段画成断线而不是连一条假直线（那会把「设备掉线」画成
     「运行平稳」）。多设备时横轴统一用**时间**而非索引：各设备采样点数可能
     不同（某台中途掉线/重连），按索引对齐会把两条曲线整体错位几百毫秒。 */
  function drawPerfChart() {
    const cv = els.perfCanvas;
    if (!cv || !cv.getContext) return;
    const wrap = cv.parentElement;
    const w = Math.round(wrap ? wrap.clientWidth : 0);
    const h = Math.round(wrap ? wrap.clientHeight : 0);
    // 页签未激活时容器尺寸为 0：此时画出来的是 0×0 位图，切回来会一片空白
    if (w < 40 || h < 40) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
      cv.width = Math.round(w * dpr);
      cv.height = Math.round(h * dpr);
    }
    const ctx = cv.getContext("2d");
    if (!ctx || !ctx.setTransform) return;      // jsdom / 无 canvas 环境静默跳过
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const meta = PERF_METRICS[perfMetric] || PERF_METRICS.cpu;
    const multi = perfSessions.size > 1;

    // 组装各设备的时间序列（一次遍历算完全局时间范围与数据量）
    const all = [];
    let total = 0, tMin = Infinity, tMax = -Infinity;
    for (const [serial, sess] of perfSessions) {
      const pts = sess.samples.map((s) => {
        const v = s[perfMetric];
        const t = s.t || 0;
        if (t) { if (t < tMin) tMin = t; if (t > tMax) tMax = t; }
        return { t, v: typeof v === "number" && isFinite(v) ? v : null };
      });
      total += pts.length;
      all.push({
        serial, pts,
        color: multi ? perfColorOf(serial) : meta.color,
        focus: serial === (perfFocus || perfPrimarySerial()),
      });
    }
    if (els.perfEmpty) els.perfEmpty.hidden = total > 0;
    if (total < 2) {
      perfGeom = null;              // 没数据时悬停提示一并失效
      updatePerfTip();
      clearPerfRange();             // 选区也没法换算了，一起收掉
      ctx.fillStyle = "#6e8299";
      ctx.font = "11px 'JetBrains Mono', monospace";
      ctx.textAlign = "center";
      ctx.fillText(total ? "正在采样…" : "--", w / 2, h / 2);
      return;
    }

    const padL = 46, padR = 12, padT = 12, padB = 20;
    const iw = Math.max(10, w - padL - padR);
    const ih = Math.max(10, h - padT - padB);
    const useTime = isFinite(tMin) && tMax > tMin;

    // 阈值线：取该指标的唯一阈值（min 或 max）。落在可视范围内才画，
    // 但下面的 Y 轴范围会主动把它纳进来——否则读数一旦远离阈值
    // （fps 掉到 30 而阈值 45），自动缩放会把阈值线挤出画布，
    // 恰恰在最该看见它的时候消失。
    const th = perfThresholds[perfMetric];
    const thVal = th
      ? (typeof th.min === "number" ? th.min
        : (typeof th.max === "number" ? th.max : null))
      : null;

    let lo = Infinity, hi = -Infinity;
    for (const s of all) {
      for (const p of s.pts) {
        if (p.v === null) continue;
        if (p.v < lo) lo = p.v;
        if (p.v > hi) hi = p.v;
      }
    }
    if (lo === Infinity) { lo = 0; hi = 1; }
    if (thVal !== null) { lo = Math.min(lo, thVal); hi = Math.max(hi, thVal); }
    if (meta.cap !== null) { lo = 0; hi = meta.cap; }
    else if (hi - lo < 1e-9) { lo = Math.max(0, lo - 1); hi = hi + 1; }
    else {
      const pad = (hi - lo) * 0.12;
      lo = Math.max(0, lo - pad);
      hi = hi + pad;
    }

    const xOf = (p, i, n) => (useTime
      ? padL + iw * ((p.t - tMin) / (tMax - tMin))
      : padL + iw * (i / Math.max(1, n - 1)));
    const yOf = (v) => padT + ih * (1 - (v - lo) / (hi - lo));

    // 留给悬停提示复用（同一套像素换算，见 perfTipModel / updatePerfTip）
    perfGeom = { all, useTime, tMin, tMax, padL, padR, padT, padB, w, h, iw, ih, lo, hi, yOf };

    // 网格 + 纵轴刻度
    ctx.font = "10px 'JetBrains Mono', monospace";
    ctx.textBaseline = "middle";
    ctx.textAlign = "right";
    for (let k = 0; k <= 4; k++) {
      const val = lo + (hi - lo) * k / 4;
      const y = Math.round(yOf(val)) + 0.5;
      ctx.strokeStyle = "rgba(126, 166, 204, .13)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(padL, y);
      ctx.lineTo(w - padR, y);
      ctx.stroke();
      ctx.fillStyle = "#6e8299";
      ctx.fillText(fmtNum(Math.round(val * 10) / 10), padL - 6, y);
    }

    // 阈值参考线（虚线 + 右下角标签）：告警只在数字上体现不够——
    // 看趋势时必须能一眼看出「曲线压过线了」，而不是自己记住 45 这个数。
    if (thVal !== null && thVal >= lo && thVal <= hi) {
      const ty = Math.round(yOf(thVal)) + 0.5;
      ctx.save();
      if (ctx.setLineDash) ctx.setLineDash([5, 4]);
      ctx.strokeStyle = "rgba(255, 95, 107, .55)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(padL, ty);
      ctx.lineTo(w - padR, ty);
      ctx.stroke();
      if (ctx.setLineDash) ctx.setLineDash([]);
      ctx.restore();
      ctx.font = "9px 'JetBrains Mono', monospace";
      ctx.fillStyle = "rgba(255, 143, 154, .9)";
      ctx.textAlign = "right";
      ctx.textBaseline = "bottom";
      ctx.fillText("阈值 " + fmtNum(thVal), w - padR - 2, ty - 2);
    }

    // 焦点设备最后画（压在最上层），其余按插入顺序
    const order = all.slice().sort((a, b) => (a.focus ? 1 : 0) - (b.focus ? 1 : 0));
    const baseY = padT + ih;
    let bubble = null;

    for (const s of order) {
      // 抽稀：只影响绘制，统计与导出始终用全量
      let pts = s.pts;
      if (pts.length > PERF_CHART_MAX) {
        const step = Math.ceil(pts.length / PERF_CHART_MAX);
        const thinned = [];
        for (let i = 0; i < pts.length; i += step) thinned.push(pts[i]);
        if (thinned[thinned.length - 1] !== pts[pts.length - 1]) {
          thinned.push(pts[pts.length - 1]);
        }
        pts = thinned;
      }
      const n = pts.length;
      const segs = [];
      let cur = [];
      pts.forEach((p, i) => {
        if (p.v === null) { if (cur.length) { segs.push(cur); cur = []; } return; }
        cur.push({ x: xOf(p, i, n), y: yOf(p.v) });
      });
      if (cur.length) segs.push(cur);

      for (const seg of segs) {
        if (seg.length === 1) {
          ctx.fillStyle = s.color;
          ctx.beginPath();
          ctx.arc(seg[0].x, seg[0].y, 1.8, 0, Math.PI * 2);
          ctx.fill();
          continue;
        }
        // 面积渐变只在单设备时画：多条半透明面积叠在一起会糊成一片，
        // 反而看不清哪条是哪条。
        if (!multi) {
          const grad = ctx.createLinearGradient(0, padT, 0, baseY);
          grad.addColorStop(0, s.color + "3d");
          grad.addColorStop(1, s.color + "00");
          ctx.beginPath();
          ctx.moveTo(seg[0].x, baseY);
          seg.forEach((p) => ctx.lineTo(p.x, p.y));
          ctx.lineTo(seg[seg.length - 1].x, baseY);
          ctx.closePath();
          ctx.fillStyle = grad;
          ctx.fill();
        }

        ctx.beginPath();
        seg.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
        ctx.strokeStyle = s.color;
        ctx.lineWidth = s.focus ? 1.8 : 1.5;
        ctx.lineJoin = "round";
        ctx.lineCap = "round";
        ctx.stroke();
      }

      const lastSeg = segs.length ? segs[segs.length - 1] : null;
      let lastVal = null;
      for (let i = pts.length - 1; i >= 0; i--) {
        if (pts[i].v !== null) { lastVal = pts[i].v; break; }
      }
      if (lastSeg && lastSeg.length && multi) {
        const p = lastSeg[lastSeg.length - 1];
        ctx.beginPath();
        ctx.arc(p.x, p.y, s.focus ? 3.2 : 2.4, 0, Math.PI * 2);
        ctx.fillStyle = s.color;
        ctx.fill();
      }
      if (s.focus && lastSeg && lastSeg.length && lastVal !== null) {
        bubble = { x: lastSeg[lastSeg.length - 1].x, y: lastSeg[lastSeg.length - 1].y,
                   color: s.color, val: lastVal };
      }
    }

    // 末端光标点 + 数值气泡（只标焦点设备，多设备时避免一堆气泡挡住曲线）
    if (bubble) {
      ctx.beginPath();
      ctx.arc(bubble.x, bubble.y, 3.4, 0, Math.PI * 2);
      ctx.fillStyle = bubble.color;
      ctx.shadowColor = bubble.color;
      ctx.shadowBlur = 10;
      ctx.fill();
      ctx.shadowBlur = 0;

      const txt = fmtNum(bubble.val);
      ctx.font = "600 11px 'JetBrains Mono', monospace";
      const tw = ctx.measureText(txt).width + 10;
      const bx = Math.min(w - padR - tw, Math.max(padL, bubble.x - tw / 2));
      const by = Math.max(padT + 1, bubble.y - 20);
      ctx.fillStyle = "rgba(10, 15, 22, .88)";
      ctx.strokeStyle = bubble.color;
      ctx.lineWidth = 1;
      if (ctx.roundRect) {
        ctx.beginPath();
        ctx.roundRect(bx, by, tw, 16, 4);
        ctx.fill();
        ctx.stroke();
      } else {
        ctx.fillRect(bx, by, tw, 16);
      }
      ctx.fillStyle = bubble.color;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(txt, bx + tw / 2, by + 8);
    }

    // 首尾时间
    const t0 = useTime ? tMin : (all[0] && all[0].pts[0] ? all[0].pts[0].t : 0);
    const t1 = useTime ? tMax
      : (all[0] && all[0].pts.length ? all[0].pts[all[0].pts.length - 1].t : 0);
    const hhmm = perfClock;      // 与悬停提示共用同一个时间格式
    ctx.font = "10px 'JetBrains Mono', monospace";
    ctx.fillStyle = "#6e8299";
    ctx.textBaseline = "alphabetic";
    ctx.textAlign = "left";
    ctx.fillText(hhmm(t0), padL, h - 6);
    ctx.textAlign = "right";
    ctx.fillText(hhmm(t1), w - padR, h - 6);
    // 采样在持续进来：指针停在原处时提示里的数值也要跟着刷新
    updatePerfTip();
    // 选区同理：曲线在往前长，区间数字必须跟着重算（超阈值次数尤其容易过期）
    refreshPerfRange();
  }

  function setPerfMetric(key, persist) {
    if (!PERF_METRICS[key]) return;
    perfMetric = key;
    document.querySelectorAll("#perf-stats .perf-stat").forEach((el) => {
      const on = el.dataset.metric === key;
      el.classList.toggle("on", on);
      el.setAttribute("aria-pressed", on ? "true" : "false");
    });
    if (els.perfChartTitle) els.perfChartTitle.textContent = PERF_METRICS[key].title;
    updatePerfLegend();           // 图例里的读数跟着指标走
    queuePerfDraw();
    if (persist) persistPref("perf_metric", key);
  }

  /* 把一台设备的一次 poll 结果并入本地会话表。返回是否真的多了采样点。 */
  function perfIngestOne(serial, snap) {
    if (!serial || !snap) return false;
    let sess = perfSessions.get(serial);
    if (!sess) {
      sess = { samples: [], seq: 0, info: {}, running: false, error: "" };
      perfSessions.set(serial, sess);
    }
    if (snap.info) sess.info = Object.assign({}, sess.info, snap.info);
    const before = sess.samples.length;
    if (Array.isArray(snap.samples) && snap.samples.length) {
      sess.samples = sess.samples.concat(snap.samples);
      if (sess.samples.length > PERF_KEEP_MAX) {
        sess.samples = sess.samples.slice(sess.samples.length - PERF_KEEP_MAX);
      }
    }
    if (typeof snap.seq === "number" && snap.seq > sess.seq) sess.seq = snap.seq;
    if (typeof snap.running === "boolean") sess.running = snap.running;
    if (typeof snap.error === "string") sess.error = snap.error;
    return sess.samples.length > before;
  }

  /* 兼容两种返回结构：新后端 {sessions:{serial: snap}}；旧结构/测试替身的
     扁平 {samples, seq, info, running}（当作一台设备处理）。 */
  function perfIngest(res) {
    if (!res) return false;
    let grew = false;
    if (res.sessions && typeof res.sessions === "object") {
      for (const serial of Object.keys(res.sessions)) {
        if (perfIngestOne(serial, res.sessions[serial])) grew = true;
      }
    } else if (Array.isArray(res.samples)) {
      const key = (res.info && res.info.serial) || firstChecked() || "_";
      if (perfIngestOne(key, res)) grew = true;
      if (res.info && res.info.serial) perfInfo = res.info;
    } else {
      return false;
    }
    if (!perfFocus || !perfSessions.has(perfFocus)) perfFocus = perfPrimarySerial();
    // 没有新点时不重算全量统计、也不重绘画布：1Hz 采样 + 600ms 轮询下，
    // 每轮都全量遍历 7 个指标 × 上万个点纯属白烧 CPU。
    if (grew) updatePerfStats();
    else updatePerfLegend();
    syncPerfButtons();
    if (grew) queuePerfDraw();
    return grew;
  }

  function perfCursor() {
    const out = {};
    for (const [serial, s] of perfSessions) out[serial] = s.seq || 0;
    return out;
  }

  async function perfPollOnce() {
    perfTimer = null;
    if (!hasApi()) return;
    // 同 pollOnce：续约必须无条件发生。perfIngest 里要做排序 / 画图 / 阈值判定，
    // 任何一个采样点结构异常抛错，都会让曲线永久停在那一帧（界面还显示"采集中"，
    // 用户以为设备卡了，实际是前端轮询链断了）。
    try {
      const cursor = perfCursor();
      const res = await callApi(api.perf_poll(
        Object.keys(cursor).length ? cursor : 0));
      if (res) {
        if (res.info && res.info.serial) perfInfo = res.info;
        perfIngest(res);
        // 后端所有会话都退出（设备掉线 / adb 挂了）时把界面拉回停态并说明原因
        if (typeof res.running === "boolean" && res.running !== perfRunning) {
          setPerfRunning(res.running);
          if (!res.running) {
            let why = res.error || "";
            if (!why && res.sessions) {
              for (const k of Object.keys(res.sessions)) {
                if (res.sessions[k] && res.sessions[k].error) {
                  why = res.sessions[k].error;
                  break;
                }
              }
            }
            setPerfState("监控已中断" + (why ? "：" + why : ""), "err", why);
          }
        }
      }
    } catch (e) {
      try {
        setPerfState("性能数据处理异常：" + ((e && e.message) || e)
          + "（采样仍在后台继续，曲线可能缺几个点）", "err", "");
      } catch (_) { /* 提示本身失败也不能中断轮询 */ }
    } finally {
      if (perfRunning) perfTimer = setTimeout(perfPollOnce, PERF_POLL_MS);
    }
  }

  /* ---------------- 目标应用选择器（下拉 + 模糊搜索） ----------------
     三种互斥取值（落盘在 config.json 的 perf_pkg）：
       ""            跟随前台应用：后端每 10 次采样重探一次，切 App 自动跟过去
       "__system__"  监控全系统：只采整机指标（CPU / 系统内存 / 电量 / 温度）
       包名          锁定某个应用：PSS / 帧率 / 卡顿这些应用级指标才有意义
     「跟随前台」沿用空串、不新造值：老配置文件里的包名照旧生效，老版本读到空串
     也仍然理解成「跟随前台」。 */

  const PERF_PKG_SYSTEM = "__system__";
  const PERF_PKG_RE = /^[A-Za-z0-9_][A-Za-z0-9_.]*$/;
  const PERF_PKG_ROWS_MAX = 300;   // 一次最多渲染多少行（系统应用全开时能上千）
  let perfPkg = "";                // 当前选择（与 config.json 的 perf_pkg 同步）
  let perfPkgCache = null;         // {serial, third:[], system:[]}
  let perfPkgLoading = false;

  function perfPkgText(v) {
    if (!v) return "跟随前台应用";
    if (v === PERF_PKG_SYSTEM) return "监控全系统";
    return v;
  }

  function perfInfoPkgText(info) {
    info = info || {};
    if (info.pkg_mode === "system") return "全系统（仅整机指标）";
    if (info.pkg) return info.pkg + (info.pkg_mode === "auto" ? "（跟随前台）" : "");
    return "跟随前台（未探测到）";
  }

  function syncPerfPkg() {
    if (!els.perfPkgBtn) return;
    els.perfPkgLabel.textContent = perfPkgText(perfPkg);
    els.perfPkgBtn.classList.toggle("is-set", !!perfPkg);
    els.perfPkgBtn.title = perfPkg
      ? "当前目标：" + perfPkgText(perfPkg) + "（点击更换）"
      : "默认跟随前台应用：操作哪个 App 就监控哪个（点击可锁定某个应用 / 全系统）";
  }

  function setPerfPkg(v, silent) {
    perfPkg = (v || "").trim();
    syncPerfPkg();
    if (silent) return;
    persistPref("perf_pkg", perfPkg);
    // 后端只在 perf_start 那一刻读一次 pkg：监控进行中改目标必须说清何时生效，
    // 否则用户会盯着曲线等「换个应用」，以为没生效。
    if (perfRunning) {
      showToast("info", "目标已改为「" + perfPkgText(perfPkg) + "」，下次开始监控生效");
    }
  }

  // 模糊匹配：先按子串命中（越靠前分越高），再退化成「按顺序出现即可」
  // （com.kwo 也能命中 com.tencent.kuwo）。完全不命中返回 -1。
  function perfPkgScore(needle, hay) {
    if (!needle) return 0;
    const at = hay.indexOf(needle);
    if (at >= 0) return 1000 - at;
    let pos = 0, gaps = 0, last = -1;
    for (let i = 0; i < needle.length; i++) {
      const hit = hay.indexOf(needle.charAt(i), pos);
      if (hit < 0) return -1;
      if (last >= 0) gaps += hit - last - 1;
      last = hit; pos = hit + 1;
    }
    return 500 - gaps;
  }

  function perfPkgRows() {
    if (!perfPkgCache) return [];
    const kw = ((els.perfPkgSearch && els.perfPkgSearch.value) || "").trim().toLowerCase();
    const sys = new Set(perfPkgCache.system || []);
    const all = (perfPkgCache.third || []).concat(perfPkgCache.system || []);
    const withSys = !!(els.perfPkgAll && els.perfPkgAll.checked);
    const rows = [];
    all.forEach((pkg) => {
      const isSys = sys.has(pkg);
      if (isSys && !withSys) return;
      const score = kw ? perfPkgScore(kw, pkg.toLowerCase()) : 0;
      if (kw && score < 0) return;
      rows.push({ pkg: pkg, sys: isSys, score: score });
    });
    rows.sort((a, b) => (b.score - a.score) || (a.pkg < b.pkg ? -1 : a.pkg > b.pkg ? 1 : 0));
    return rows;
  }

  function renderPerfPkgModes() {
    if (!els.perfPkgModes) return;
    Array.from(els.perfPkgModes.querySelectorAll(".pkg-mode")).forEach((b) => {
      const v = b.dataset.pkg === "auto" ? "" : (b.dataset.pkg || "");
      b.classList.toggle("on", v === perfPkg);
    });
  }

  function renderPerfPkgList() {
    if (!els.perfPkgList) return;
    const list = els.perfPkgList;
    list.innerHTML = "";
    const tip = (text) => {
      const d = document.createElement("div");
      d.className = "pkg-tip";
      d.textContent = text;
      list.appendChild(d);
    };
    const setCount = (text) => { if (els.perfPkgCount) els.perfPkgCount.textContent = text; };
    if (perfPkgLoading) { setCount(""); tip("正在读取设备上的应用…"); return; }
    if (!perfPkgCache) {
      setCount("");
      tip(checkedDevices().length ? "点「刷新」读取设备上的应用" : "请先在左侧勾选一台设备");
      return;
    }
    const rows = perfPkgRows();
    setCount(rows.length
      ? ("共 " + rows.length + " 个"
         + (rows.length > PERF_PKG_ROWS_MAX ? "，显示前 " + PERF_PKG_ROWS_MAX : ""))
      : "无匹配");
    if (!rows.length) { tip("（无匹配应用，可直接回车使用输入的包名）"); return; }
    rows.slice(0, PERF_PKG_ROWS_MAX).forEach((r) => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "pkg-item" + (r.sys ? " is-sys" : "") + (r.pkg === perfPkg ? " on" : "");
      item.dataset.pkg = r.pkg;
      item.setAttribute("role", "option");
      item.setAttribute("aria-selected", r.pkg === perfPkg ? "true" : "false");
      const name = document.createElement("span");
      name.className = "pkg-item-n";
      name.textContent = r.pkg;
      item.appendChild(name);
      if (r.sys) {
        const tag = document.createElement("span");
        tag.className = "pkg-item-t";
        tag.textContent = "系统";
        item.appendChild(tag);
      }
      list.appendChild(item);
    });
  }

  async function loadPerfPkgs(force) {
    const serial = perfFocus || perfPrimarySerial() || firstChecked() || "";
    if (!serial) { perfPkgCache = null; renderPerfPkgList(); return; }
    if (!force && perfPkgCache && perfPkgCache.serial === serial) return;
    if (!api || typeof api.perf_list_packages !== "function") {
      perfPkgCache = null;
      renderPerfPkgList();
      if (els.perfPkgCount) els.perfPkgCount.textContent = "后端不支持读取应用列表";
      return;
    }
    perfPkgLoading = true;
    renderPerfPkgList();
    const res = await callApi(api.perf_list_packages(serial, !!force));
    perfPkgLoading = false;
    if (!res || res.ok === false) {
      perfPkgCache = null;
      renderPerfPkgList();
      if (els.perfPkgCount) {
        els.perfPkgCount.textContent = (res && (res.message || res.reason)) || "读取失败";
      }
      return;
    }
    perfPkgCache = { serial: res.serial || serial, third: res.third || [],
      system: res.system || [] };
    renderPerfPkgList();
  }

  function openPerfPkgPop() {
    if (!els.perfPkgPop) return;
    els.perfPkgPop.classList.remove("hidden");
    if (els.perfPkgBtn) els.perfPkgBtn.setAttribute("aria-expanded", "true");
    if (els.perfPkgSearch) { els.perfPkgSearch.value = ""; els.perfPkgSearch.focus(); }
    renderPerfPkgModes();
    renderPerfPkgList();
    loadPerfPkgs(false);
  }

  function closePerfPkgPop() {
    if (!els.perfPkgPop || els.perfPkgPop.classList.contains("hidden")) return;
    els.perfPkgPop.classList.add("hidden");
    if (els.perfPkgBtn) els.perfPkgBtn.setAttribute("aria-expanded", "false");
  }

  // 回车：有匹配就取最相关的那条；一条都没匹配就当「手动输入包名」用
  // （后端有白名单校验，非法值不会漏进设备端脚本）。
  function applyPerfPkgTyped() {
    const raw = ((els.perfPkgSearch && els.perfPkgSearch.value) || "").trim();
    if (!raw) { closePerfPkgPop(); return; }
    const rows = perfPkgRows();
    if (rows.length) { setPerfPkg(rows[0].pkg); closePerfPkgPop(); return; }
    if (!PERF_PKG_RE.test(raw)) {
      showToast("warn", "包名只能含字母 / 数字 / 下划线 / 点，例如 com.tencent.kuwo");
      return;
    }
    setPerfPkg(raw);
    closePerfPkgPop();
  }

  function bindPerfPkgPicker() {
    if (!els.perfPkgBtn || !els.perfPkgPop) return;
    syncPerfPkg();
    els.perfPkgBtn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      if (els.perfPkgPop.classList.contains("hidden")) openPerfPkgPop();
      else closePerfPkgPop();
    });
    // 弹层内点击不冒泡到 document（否则「点选项」会先被外面的关闭逻辑吃掉）
    els.perfPkgPop.addEventListener("click", (ev) => ev.stopPropagation());
    document.addEventListener("click", closePerfPkgPop);
    if (els.perfPkgSearch) {
      els.perfPkgSearch.addEventListener("input", renderPerfPkgList);
      els.perfPkgSearch.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter") { ev.preventDefault(); applyPerfPkgTyped(); }
        else if (ev.key === "Escape") { ev.preventDefault(); closePerfPkgPop(); }
      });
    }
    if (els.perfPkgModes) {
      els.perfPkgModes.addEventListener("click", (ev) => {
        const b = ev.target && ev.target.closest ? ev.target.closest(".pkg-mode") : null;
        if (!b) return;
        setPerfPkg(b.dataset.pkg === "auto" ? "" : (b.dataset.pkg || ""));
        closePerfPkgPop();
      });
    }
    if (els.perfPkgList) {
      // 事件委托：列表可能有几百行，逐行绑监听会在每次重绘后堆积
      els.perfPkgList.addEventListener("click", (ev) => {
        const it = ev.target && ev.target.closest ? ev.target.closest(".pkg-item") : null;
        if (!it) return;
        setPerfPkg(it.dataset.pkg || "");
        closePerfPkgPop();
      });
    }
    if (els.perfPkgAll) {
      els.perfPkgAll.addEventListener("change", () => {
        persistPref("perf_pkg_all", !!els.perfPkgAll.checked);
        renderPerfPkgList();
      });
    }
    if (els.perfPkgRefresh) {
      els.perfPkgRefresh.addEventListener("click", () => loadPerfPkgs(true));
    }
  }

  async function startPerf() {
    const list = checkedDevices();
    if (!list.length) { showToast("warn", "请先在左侧勾选至少一台受控设备"); return; }
    const ms = Math.min(10000, Math.max(200, parseInt(els.perfInterval.value, 10) || 1000));
    els.perfInterval.value = String(ms);
    perfSessions = new Map();
    perfFocus = "";
    perfInfo = {};
    perfAlertOn = {};
    perfAlertQuiet = 0;
    updatePerfStats();
    queuePerfDraw();
    setPerfState("启动中…");
    markBtnBusy(els.perfStart, true);
    // 第一个参数传 null：交给后端取「全部受控设备」，多台即进入对比模式
    const res = await callApi(api.perf_start(
      null, ms, perfPkg));
    markBtnBusy(els.perfStart, false);
    if (!res || res.ok === false) {
      const why = (res && (res.error || res.reason)) || "未知原因";
      setPerfState("启动失败", "err", why);
      showToast("err", "性能监控启动失败：" + why);
      return;
    }
    // 先按返回的会话表铺好设备名：第一帧样本到之前图例就有内容可显示
    if (res.sessions) {
      for (const serial of Object.keys(res.sessions)) {
        perfSessions.set(serial, {
          samples: [], seq: 0, info: res.sessions[serial] || {},
          running: true, error: "",
        });
      }
    }
    perfFocus = perfPrimarySerial();
    perfInfo = res.info || {};
    const count = perfSessions.size || 1;
    setPerfRunning(true);
    setPerfState(
      count > 1 ? "监控中 · " + count + " 台设备" : "监控中 · " + (perfInfo.model || res.serial),
      "ok",
      "应用：" + perfInfoPkgText(perfInfo) + "\n分辨率：" + (perfInfo.size || "--")
      + "\n采样间隔：" + (res.interval || ms / 1000) + " 秒");
    if (res.failed && Object.keys(res.failed).length) {
      const names = Object.keys(res.failed).join("、");
      showToast("warn", "以下设备未能开始监控：" + names);
    }
    updatePerfStats();
    if (perfTimer) clearTimeout(perfTimer);
    perfTimer = setTimeout(perfPollOnce, 300);
  }

  async function stopPerf() {
    markBtnBusy(els.perfStop, true);
    await callApi(api.perf_stop());
    setPerfRunning(false);
    // 收尾再拉一次：把停止瞬间还在路上的采样点补齐，别让最后几秒缺口
    const cursor = perfCursor();
    const res = await callApi(api.perf_poll(
      Object.keys(cursor).length ? cursor : 0));
    if (res) perfIngest(res);
    setPerfState("已停止 · " + perfTotalPoints() + " 个采样点");
    updatePerfStats();
    queuePerfDraw();
    markBtnBusy(els.perfStop, false);
  }

  async function exportPerf() {
    if (!perfTotalPoints()) { showToast("warn", "还没有采样数据，先开始监控"); return; }
    els.perfExport.disabled = true;
    markBtnBusy(els.perfExport, true);
    setPerfState("正在生成报告…");
    const res = await callApi(api.perf_export());
    markBtnBusy(els.perfExport, false);
    els.perfExport.disabled = false;
    if (!res || res.ok === false) {
      setPerfState("导出失败", "err", (res && res.reason) || "");
      showToast("err", "报告导出失败：" + ((res && res.reason) || "未知原因"));
      return;
    }
    if (res.sessions > 1) {
      setPerfState("已生成 " + res.sessions + " 份报告" + (res.compare ? " + 对比" : ""),
                   "ok", res.compare || res.html);
      showToast("ok", "✓ 已生成 " + res.sessions + " 份性能报告"
                + (res.compare ? " + 1 份对比报告" : "")
                + "（共 " + res.rows + " 个采样点）");
    } else {
      setPerfState("报告：" + res.html, "ok", res.html);
      showToast("ok", "✓ 性能报告已生成（" + res.rows + " 个采样点）");
    }
    // 报告就是拿来读的：导出后直接用默认浏览器打开（与「命令导出」不同，
    // 那个是回传给别人的文本，弹编辑器反而打断操作）。
    // 多设备时优先打开对比报告：它才是这一轮真正要看的那份。
    const openPath = res.compare || res.html;
    if (openPath && api.open_local_file) callApi(api.open_local_file(openPath));
  }
  /* ---------------- 文件 ---------------- */
  function renderFileDev() {
    // 文件 tab 与 Logcat 完全对齐：随左侧受控设备自动联动，取第一个作为当前浏览设备
    const next = firstChecked();
    els.fileDevNow.textContent = next ? "设备: " + next : "未选设备";
    const changed = next !== fileSerial;
    fileSerial = next;
    if (!next) {
      // 无受控设备：清空表格，同时复位选择态——否则「已选 N 项」与批量按钮
      // 会停在空表格上（按钮可点但点了没用），与 onFile 的失败分支不一致。
      els.fileBody.innerHTML = "";
      fileAnchor = null;
      els.fileSelAll.checked = false;
      updateFileSel();
      return;
    }
    if (changed) {
      // 设备切换后，旧设备的浏览路径在新设备上多半不存在（如 /data/local/tmp、
      // /log/logcat）：继续照旧路径列目录会直接报「无权限 / 目录不存在」。故切换
      // 设备时复位到根，从根目录重新加载，而不是停在上一台设备的某个子目录。
      // 注意区分：自动轮询刷新时 firstChecked 不变（changed=false），不会打扰浏览
      // ——旧实现在这里无条件 gotoPath()，设备状态一抖动（offline↔device）就重新
      // 列目录：一次 adb 子进程 + 整张表重建，正是「界面偶尔一顿」的来源之一。
      els.filePath.value = "/";
      filePath = "/";
      gotoPath();
    }
  }
  function onFile(p) {
    if (p.error) {
      // 迟到的「别人」的错误：用户已经切到另一台设备，这份错误与眼前的列表无关，
      // 照它清空会把当前设备的文件区误判成「目录不可访问」（成功分支早就做了这个
      // 校验，错误分支漏了 —— 设备切得越快越容易踩到）。
      if (p.serial && fileSerial && p.serial !== fileSerial) return;
      pushStatus("err", "⚠ " + p.error);
      // 目录列不出来分两种，处理方式不同：
      //  · 失败的正是「当前正在浏览的目录」自身（刷新当前目录失败：车机无 root /
      //    无权限 / 目录已不存在等）。此时继续展示该目录上一次成功时的内容是陈旧且
      //    误导的（例：/log/logcat 已不可访问，列表却仍列着 logcat.txt）。故清空
      //    列表并复位选择态，让文件区刷新为空白。
      //  · 进入的是「另一个目录」失败（如进 /data 无权限）：停留在当前目录、保留原
      //    列表，仅把输入框回退到当前目录（filePath），避免停在一个进不去的路径。
      if (sameDir(p.path || "/", filePath)) {
        els.fileBody.innerHTML = "";
        fileAnchor = null;
        els.fileSelAll.checked = false;
        updateFileSel();
      } else {
        els.filePath.value = filePath;
      }
      return;
    }
    if (p.serial !== fileSerial) return;
    els.filePath.value = p.path || "/";
    filePath = p.path || "/";
    fileAnchor = null;            // 新目录 = 新的选择上下文，避免 Shift 区间跨目录串选
    renderFileEntries(p.entries || []);
    els.fileSelAll.checked = false;
    updateFileSel();
  }

  /* 渲染目录条目。
     两处性能取舍（/sdcard 常见几百到两千项，每次刷新都会重来一遍）：
       · DocumentFragment 批量插入：逐行 appendChild 是 N 次布局，改用片段只在
         最后触发一次；
       · 不给每行挂监听器（旧实现每行 5~6 个：勾选框 change、名称 click、三个
         操作按钮 click），2000 行就是上万个闭包常驻内存。改为在 #file-body 上
         各挂一个（见 bindFileBodyEvents），按行上的 data-* 定位。 */
  function renderFileEntries(entries) {
    const body = els.fileBody;
    body.textContent = "";
    const frag = document.createDocumentFragment();
    entries.forEach((e) => {
      const tr = document.createElement("tr");
      if (e.is_dir) tr.className = "dir";
      tr.dataset.name = e.name;
      tr.dataset.path = fullPath(e.name);
      // 选择列：每行一个复选框（父目录「..」不参与批量选择）
      const sel = document.createElement("td"); sel.className = "col-sel";
      if (e.name !== "..") {
        const cb = document.createElement("input");
        cb.type = "checkbox"; cb.className = "file-check";
        cb.value = fullPath(e.name);
        sel.appendChild(cb);
      }
      const name = document.createElement("td"); name.className = "name";
      name.textContent = (e.is_dir ? "📁 " : "📄 ") + e.name;
      name.style.cursor = "pointer";
      name.title = e.is_dir && e.name !== ".." ? "单击进入目录" : "单击切换选择（支持 Ctrl / Shift）";
      const size = document.createElement("td"); size.textContent = fmtSize(e.size);
      const date = document.createElement("td"); date.textContent = e.date || "";
      const perm = document.createElement("td"); perm.textContent = e.perm || "";
      const act = document.createElement("td"); act.className = "act";
      /* 父目录行（".."）只作导航入口，不给操作按钮：
         「重命名」= `mv /sdcard/Download/.. /sdcard/Download/x`，等于把**父目录
         整个搬走**；「删除」= `rm -rf .../Download/..`，等于删掉上一级。对用户
         毫无意义，却恰好是最容易被误点的一行（它永远排在第一行）。
         留着空单元格，列的宽度与其它行对齐。 */
      if (e.name !== "..") {
        if (!e.is_dir) {
          act.appendChild(mkAct("下载", "download", "download"));
          act.appendChild(mkAct("查看", "view", "eye"));
        }
        act.appendChild(mkAct("重命名", "rename", "edit"));
        act.appendChild(mkAct("删除", "delete", "trash"));
      }
      tr.appendChild(sel); tr.appendChild(name); tr.appendChild(size); tr.appendChild(date); tr.appendChild(perm); tr.appendChild(act);
      frag.appendChild(tr);
    });
    body.appendChild(frag);
  }

  /* #file-body 的事件委托：一次绑定，服务所有行（行内容随刷新整体重建）。 */
  function bindFileBodyEvents() {
    const body = els.fileBody;
    if (!body) return;
    body.addEventListener("click", (ev) => {
      const t = ev.target;
      if (!t || !t.closest) return;
      const tr = t.closest("tr");
      if (!tr || !tr.dataset) return;
      const actBtn = t.closest("[data-act]");
      if (actBtn) {
        fileRunAction(actBtn.dataset.act, tr.dataset.path || "",
                      tr.dataset.name || "", actBtn);
        return;
      }
      if (!t.closest("td.name")) return;        // 只认「名称」列
      const nm = tr.dataset.name || "";
      if (nm === "..") { els.filePath.value = dirOf(filePath); gotoPath(); return; }
      if (tr.classList.contains("dir")) {
        els.filePath.value = filePath.replace(/\/$/, "") + "/" + nm;
        gotoPath();
        return;
      }
      const cb = tr.querySelector(".file-check");
      if (!cb) return;
      if (ev.shiftKey && fileAnchor) {
        shiftSelectFiles(cb.value);
      } else {
        cb.checked = !cb.checked;
        fileAnchor = cb.value;
      }
      updateFileSel();
    });
    body.addEventListener("change", (ev) => {
      const cb = ev.target;
      if (!cb || !cb.classList || !cb.classList.contains("file-check")) return;
      fileAnchor = cb.value;
      updateFileSel();
    }, true);   // 捕获阶段：真实 change 会冒泡，但捕获不依赖构造方是否传 bubbles
  }

  /* 文件页「名称」输入的校验（重命名 / 新建文件夹 / 新建文件）。
     只接受当前目录里的**一项**，不接受路径分隔符：
      · 带 / 时 `mv old new` 的语义等于「移动到别处」，用户以为在改名，文件却搬走了；
      · 根目录下再拼 "/x" 还会得到 "//x"（早前就有过这个 bug）。
     返回 {ok, name, why}；与原名相同时 ok=false 且 why 为空（静默跳过，不打扰）。 */
  function validateEntryName(raw, oldName) {
    const name = String(raw == null ? "" : raw).trim();
    if (!name) return { ok: false, why: "名称不能为空" };
    if (name === "." || name === "..") return { ok: false, why: "「.」和「..」是目录保留名" };
    if (name.indexOf("/") !== -1 || name.indexOf("\\") !== -1) {
      return { ok: false, why: "名称不能包含 / 或 \\（这里只做改名，不做移动）" };
    }
    if (oldName && name === oldName) return { ok: false, why: "" };
    return { ok: true, name: name };
  }

  /* 行内操作按钮（委托到 #file-body，见 bindFileBodyEvents）。 */
  async function fileRunAction(act, path, name, btn) {
    if (!path) return;
    if (act === "download") {
      if (btn) { btn.disabled = true; markBtnBusy(btn, true); }
      await callApi(api.file_download(fileSerial, path, null));
      if (btn) { markBtnBusy(btn, false); btn.disabled = false; }
    } else if (act === "view") {
      if (btn) { btn.disabled = true; markBtnBusy(btn, true); }
      await callApi(api.file_view(fileSerial, path));
      if (btn) { markBtnBusy(btn, false); btn.disabled = false; }
    } else if (act === "rename") {
      // 目标必须是「当前目录 + 新名」：早前用 dirOf(filePath)（当前目录的
      // **父目录**）拼接，在 /sdcard/Download 里改名会把文件搬到 /sdcard，
      // 根目录还会拼出 "//d.txt"。
      // 用自绘输入框：pywebview 部分版本里 window.prompt 返回 null，改名会点了没反应。
      askInput({ title: "重命名", label: "新名称：", value: name, ok: "重命名",
                 hint: "只改当前目录里的名字，不能带 /（不做移动）" }).then((n) => {
        if (n === null) return;
        const v = validateEntryName(n, name);
        if (!v.ok) { if (v.why) pushStatus("err", "⚠ " + v.why); return; }
        callApi(api.file_rename(fileSerial, path, fullPath(v.name)));
      });
    } else if (act === "delete") {
      askConfirm({ title: "删除文件",
                   text: "确定删除以下项目？此操作不可恢复。\n" + path,
                   yes: "删除", danger: true }).then(async (yes) => {
        if (!yes) return;
        if (btn) { btn.disabled = true; markBtnBusy(btn, true); }
        await callApi(api.file_remove(fileSerial, [path]));
        if (btn) { markBtnBusy(btn, false); btn.disabled = false; }
      });
    }
  }

  function mkAct(text, act, icon) {
    const b = document.createElement("button"); b.className = "btn tiny";
    b.dataset.act = act;
    if (icon) { const svg = makeIcon(icon); if (svg) b.appendChild(svg); }
    b.appendChild(document.createTextNode(text)); return b;
  }
  /* 文件批量操作：勾选态直接读 DOM（刷新后自然清空，无需维护额外状态）。 */
  function fileCheckedPaths() {
    return Array.from(document.querySelectorAll("#file-body .file-check:checked"))
      .map((c) => c.value).filter(Boolean);
  }
  function updateFileSel() {
    const checks = Array.from(document.querySelectorAll("#file-body .file-check"));
    const n = checks.filter((c) => c.checked).length;
    els.fileSelCount.textContent = "已选 " + n + " 项";
    els.fileBatchDl.disabled = n === 0;
    els.fileBatchDel.disabled = n === 0;
    // 全选框：仅当存在可选项且全部勾选时为选中
    els.fileSelAll.checked = checks.length > 0 && n === checks.length;
  }
  /* Shift 区间选择：以锚点（fileAnchor）到点击行为端点，选中区间内全部、取消区间外。 */
  function shiftSelectFiles(clickedValue) {
    const checks = Array.from(document.querySelectorAll("#file-body .file-check"));
    const iC = checks.findIndex((c) => c.value === clickedValue);
    if (iC < 0) return;
    const iA = checks.findIndex((c) => c.value === fileAnchor);
    if (iA < 0) { checks[iC].checked = true; fileAnchor = clickedValue; return; }
    const lo = Math.min(iA, iC), hi = Math.max(iA, iC);
    checks.forEach((c, i) => { c.checked = (i >= lo && i <= hi); });
    fileAnchor = clickedValue;
  }
  function fullPath(name) {
    if (name.startsWith("/")) return name;
    return (filePath.replace(/\/$/, "") + "/" + name);
  }
  function dirOf(p) {
    const t = (p || "/").replace(/\/$/, "");
    const i = t.lastIndexOf("/");
    return i <= 0 ? "/" : t.slice(0, i);
  }
  // 目录路径归一化（去尾部斜杠，空则视为根），用于判断两次列目录请求是否同一目录。
  function normDir(s) { const t = (s || "/").replace(/\/+$/, ""); return t || "/"; }
  function sameDir(a, b) { return normDir(a) === normDir(b); }
  function gotoPath() {
    if (els.fileRefresh) markBtnBusy(els.fileRefresh, true);
    const p = callApi(api.file_list(fileSerial, els.filePath.value.trim() || "/"));
    Promise.resolve(p).then(() => { if (els.fileRefresh) markBtnBusy(els.fileRefresh, false); });
  }
  function onFileView(p) {
    p = p || {};
    modalLocalPath = p.local || null;
    if (modalLocalPath) { els.modalTitle.textContent = "已拉取到本地：" + modalLocalPath; }
    else { els.modalTitle.textContent = "查看：" + (p.path || ""); }
    els.modalBody.textContent = p.text || (p.note || "（空）");
    // 只有「已拉取到本地」的大文件才给「查看」按钮：小文件内容已在弹窗里
    els.modalOpenLocal.hidden = !modalLocalPath;
    els.modal.classList.remove("hidden");
  }
  /* 上传一批文件：复用现有 base64 + api.file_upload_data 通道（与点击「上传」一致）。
     拖拽与「上传」按钮共用本函数，避免两份逻辑漂移。 */
  function uploadFiles(files) {
    if (!files || !files.length) return;
    if (!fileSerial) { pushStatus("warn", "⚠ 请先在左侧勾选一台设备（文件上传需要目标设备）"); return; }
    /* 目标设备与目录先快照：FileReader 是异步的，读完时用户完全可能已经切到
       另一台设备 / 另一个目录。原实现在 onload 里读 fileSerial / filePath，于是
       「提示写的是 /sdcard/Download，文件却传到了 /sdcard/DCIM」这种错位。
       提示语也用它，保证「说的」和「做的」是同一个目录。 */
    const serial = fileSerial;
    const dir = filePath;
    const pathOf = (nm) => (dir.replace(/\/$/, "") + "/" + nm);
    let n = 0;
    // 一批文件的读取 / 传输可能在途多个；等到最后一个回来再收掉「上传」转圈。
    let pending = 0;
    const uploadBegin = () => {
      if (pending++ === 0 && els.fileUploadBtn) markBtnBusy(els.fileUploadBtn, true);
    };
    const uploadEnd = () => {
      if (pending > 0 && --pending === 0 && els.fileUploadBtn) {
        markBtnBusy(els.fileUploadBtn, false);
      }
    };
    Array.from(files).forEach((f) => {
      const reader = new FileReader();
      uploadBegin();
      reader.onload = async () => {
        try {
          const b64 = (reader.result || "").split(",").pop() || "";
          if (!b64) {
            /* 读到的内容为空（文件在读取瞬间被删 / 被独占锁住 / 磁盘掉线）：
               空串传到后端会写成一个 0 字节文件，然后照常报「✓ 上传完成」——
               用户在设备上拿到一个空文件，还以为传成功了。 */
            pushStatus("err", "⚠ 上传失败 " + f.name + "：读到的内容为空（文件被占用或已删除）");
            return;
          }
          await callApi(api.file_upload_data(serial, f.name, b64, pathOf(f.name)));
        } finally {
          uploadEnd();
        }
      };
      /* 读取失败（被占用 / 无权限 / 文件已不在）时既不触发 onload 也不报错：
         旧实现下用户只看到「⬆ 已提交上传 N 个文件」，之后什么都不会发生。 */
      reader.onerror = () => {
        const why = (reader.error && reader.error.message) || "读取失败";
        pushStatus("err", "⚠ 无法读取 " + f.name + "：" + why);
        uploadEnd();
      };
      try {
        reader.readAsDataURL(f);
      } catch (e) {
        pushStatus("err", "⚠ 无法读取 " + f.name + "：" + ((e && e.message) || e));
        uploadEnd();
      }
      n++;
    });
    pushStatus("info", "⬆ 已提交上传 " + n + " 个文件到 " + dir);
  }
  function fmtSize(n) {
    if (!n && n !== 0) return "";
    if (n < 1024) return n + " B";
    const u = ["KB", "MB", "GB", "TB"];
    let x = n / 1024;
    for (const unit of u) { if (x < 1024) return (x >= 10 ? x.toFixed(0) : x.toFixed(1)) + " " + unit; x /= 1024; }
    return x.toFixed(0) + " TB";
  }

  /* ---------------- 关于 ---------------- */
  function onAbout(p) {
    if (p && p.version) els.aboutVer.textContent = p.version;
    if (p && p.adb) els.aboutAdb.textContent = p.adb;
    if (p && p.commands) els.aboutCmd.textContent = p.commands.length;
    if (p && p.warnings) els.aboutWarn.textContent = p.warnings.join("\n");
    const online = devices.filter((d) => d.ok).length;
    els.aboutDev.textContent = online + " / " + devices.length;
  }

  /* ---------------- 版本更新 ----------------
     后端每 12 小时自动查一次（见 backend/controller.py 的 _update_loop），查到新版
     推一条 update 事件，这里负责弹窗。三条「不打扰」规则：
       · 自动检查失败（断网 / 限流）不弹 —— 用户没问，别把网络问题当报错砸给他；
       · 点过「跳过此版本」的，后端已把事件标成 silenced，这里不再弹；
       · 「稍后」只关窗不记忆 —— 下次启动仍会提醒一次，那是真该提醒的。 */
  let updateChecking = false;
  let updateShown = null;          // 弹窗当前展示的结果（下载 / 跳过要用它的 version）
  // 收到过「实时结果」后，启动回填就不再覆盖关于页文字。
  // 真实竞态：booted 与 update 事件可能在同一批轮询里到达——onBooted 里的
  // loadUpdateInfo() 是异步的，它的响应会比同批事件更晚落地，于是把刚显示的
  // 「有新版本 2026.1103.1200」盖回「尚未检查」。回填天生是旧数据，不该赢。
  let updateEventSeen = false;

  function setUpdateChecking(on) {
    updateChecking = !!on;
    if (els.aboutUpdateCheck) {
      els.aboutUpdateCheck.disabled = updateChecking;
      markBtnBusy(els.aboutUpdateCheck, updateChecking);
      els.aboutUpdateCheck.textContent = updateChecking ? "检查中…" : "检查";
    }
  }

  /* 关于页那一行只放「结论」，细节进 title（悬停可看全文）。 */
  function setUpdateStateText(res) {
    const b = els.aboutUpdateState;
    if (!b) return;
    b.classList.remove("err", "ok", "dim");
    if (!res) {
      b.textContent = "尚未检查";
      b.title = "程序启动 8 秒后会自动查一次；也可点右侧「检查」立即查";
      b.classList.add("dim");
      return;
    }
    if (res.status === "update") {
      b.textContent = "有新版本 " + (res.version || "");
      b.title = "当前 " + (res.current || "") + " → " + (res.version || "")
        + "；点「检查」可再看说明与下载入口";
    } else if (res.status === "latest") {
      b.textContent = "已是最新（" + (res.current || "") + "）";
      b.title = "";
    } else if (res.status === "ahead") {
      b.textContent = "开发版（" + (res.current || "") + "）";
      b.title = "本机版本比发布版新：" + (res.version || "");
    } else {
      const msg = res.error || "检查失败";
      b.textContent = msg.length > 46 ? msg.slice(0, 46) + "…" : msg;
      b.title = msg;
      b.classList.add("err");
    }
  }

  /* 拉一次版本信息（只读，不发网络请求）：回填开关与「上次检查结果」。 */
  async function loadUpdateInfo() {
    const info = await callApi(api.update_info());
    if (!info || info.ok === false) return;
    if (els.aboutUpdateAuto && typeof info.enabled === "boolean") {
      els.aboutUpdateAuto.checked = info.enabled;
    }
    setUpdateChecking(!!info.checking);
    // 已有实时结果就不回填（回填是上次会话的旧数据，会盖掉刚到的结果）
    if (!updateEventSeen) setUpdateStateText(info.last || null);
  }

  async function checkUpdateManual() {
    if (updateChecking) return;
    setUpdateChecking(true);         // 乐观禁用：后端广播回来之前先给出反馈
    if (els.aboutUpdateState) {
      els.aboutUpdateState.classList.remove("dim", "err", "ok");
      els.aboutUpdateState.textContent = "正在检查…";
      els.aboutUpdateState.title = "";
    }
    const res = await callApi(api.update_check(true));
    // 被拒（正在查 / 正在退出）时不擅自复位：真正的收尾由 update_state 广播负责，
    // 这里复位会和后台线程抢同一个按钮状态。
    if (!res || res.ok === false) {
      if (!res || res.reason !== "busy") setUpdateChecking(false);
    }
  }

  function fmtMB(n) {
    n = Number(n) || 0;
    return n > 0 ? (n / 1048576).toFixed(1) + " MB" : "";
  }

  function showUpdateModal(res) {
    if (!els.updateModal) return;
    updateShown = res || null;
    const cur = (res && res.current) || (els.aboutVer && els.aboutVer.textContent) || "";
    if (els.updateTitle) {
      els.updateTitle.textContent = res && res.version
        ? "发现新版本 " + res.version : "发现新版本";
    }
    if (els.updateCurrent) els.updateCurrent.textContent = cur || "—";
    if (els.updateLatest) els.updateLatest.textContent = (res && res.version) || "—";
    if (els.updateSize) {
      els.updateSize.textContent = fmtMB(res && res.asset && res.asset.size);
    }
    if (els.updateNotes) {
      const notes = (res && res.notes) || "";
      els.updateNotes.textContent = notes
        || "（这个版本没有填写更新说明，可在下载页查看提交记录。）";
    }
    // 没有下载地址时不能给一个「点了没反应」的按钮
    if (els.updateDownload) els.updateDownload.disabled = !(res && res.url);
    els.updateModal.classList.remove("hidden");
  }

  function hideUpdateModal() {
    if (els.updateModal) els.updateModal.classList.add("hidden");
  }

  function onUpdateResult(p) {
    p = p || {};
    updateEventSeen = true;
    setUpdateStateText(p);
    if (p.status === "update" && !p.silenced) showUpdateModal(p);
  }

  /* ---------------- 可拖动分隔条 ----------------
     左右拖动改变左侧面板宽度（设备栏 / 指令台）。钳制在
     [min, 可用宽 - 右侧保留] 之间，防止把面板拖没或压垮右侧；
     双击分隔条重置为默认宽度。拖动中用 pointer capture 保证
     指针移出窗口仍能跟手，松手即收。

     「可用宽」必须取**真实可见**的布局容器（.tab-area / .main-row）而不是
     左面板自己的父元素：父元素（.cmd-layout）可能已经被超宽的左面板撑得
     比可视区还宽，拿它的宽度做钳制等于「越拖越宽」—— 右侧「指令输出」
     被顶出屏幕外（用户实报「横向拖动时右侧内容被挤出屏幕」。
     此外窗口缩放时要把已拖出的内联宽度**重新钳制**（动态适配）：否则从
     大窗口缩回小窗口后，左面板仍握着旧宽度，右侧照样被顶出屏幕。 */
  const _splitters = [];        // [{panel, min, reserve}] 供 resize 重钳
  function splitterAvailWidth(panel) {
    const area = panel.closest(".tab-area") || panel.closest(".main-row")
      || panel.parentElement;
    return area ? area.getBoundingClientRect().width : 0;
  }
  // 窗口缩放后重钳内联宽度：只缩不增（用户拖宽的需求不被缩放覆盖）
  function reclampSplitters() {
    for (const s of _splitters) {
      const w = parseFloat(s.panel.style.width);
      if (!isFinite(w)) continue;            // 没拖过（走 CSS 默认宽度）
      const avail = splitterAvailWidth(s.panel);
      const maxW = Math.max(s.min, avail - s.reserve);
      s.panel.style.width = Math.max(s.min, Math.min(maxW, w)) + "px";
    }
  }
  function bindSplitter(splitter, leftPanel, min, reserveRight) {
    if (!splitter || !leftPanel) return null;
    // 返回记录本身：关闭工作区时要把它从 _splitters 里摘掉，否则那块面板
    // 已经不在文档里了，窗口缩放还在对它的内联宽度做钳制（白算，且越攒越多）。
    const rec = { panel: leftPanel, min: min, reserve: reserveRight };
    _splitters.push(rec);
    let dragging = false, startX = 0, startW = 0;
    splitter.addEventListener("pointerdown", (e) => {
      if (e.button !== undefined && e.button !== 0) return;   // 只响应左键
      dragging = true;
      startX = e.clientX;
      startW = leftPanel.getBoundingClientRect().width;
      splitter.classList.add("dragging");
      document.body.classList.add("col-resizing");
      if (splitter.setPointerCapture) {
        try { splitter.setPointerCapture(e.pointerId); } catch (_) {}
      }
      e.preventDefault();
    });
    splitter.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      // 以真实可见容器宽度钳制（而非父元素，见上注）
      const avail = splitterAvailWidth(leftPanel);
      const maxW = Math.max(min, avail - reserveRight);
      let w = startW + (e.clientX - startX);
      w = Math.max(min, Math.min(maxW, w));
      leftPanel.style.width = w + "px";
    });
    const end = (e) => {
      if (!dragging) return;
      dragging = false;
      splitter.classList.remove("dragging");
      document.body.classList.remove("col-resizing");
      if (splitter.releasePointerCapture && e && e.pointerId !== undefined) {
        try { splitter.releasePointerCapture(e.pointerId); } catch (_) {}
      }
    };
    splitter.addEventListener("pointerup", end);
    splitter.addEventListener("pointercancel", end);
    // 双击重置为默认宽度（清掉内联样式即回到 CSS 里的 280px，窄屏 232px）
    splitter.addEventListener("dblclick", () => { leftPanel.style.width = ""; });
    return rec;
  }

  /* ---------------- 设备栏收起 / 展开（侧边栏折叠） ----------------
     点标题前的 « 按钮：整栏缩为 38px 窄轨（CSS .main-row.sidebar-collapsed），
     只留展开按钮与设备数徽章，内容区吃满宽度；分隔条同步隐藏。

     内联 width 的处理是这里的关键：分隔条拖动写的是 style.width（内联），
     会压过一切 class 规则——所以收起时先把内联值存下来再清掉，让 collapsed
     规则生效；展开时原样还回（用户拖过的宽度不丢，没拖过则回 CSS 默认）。
     若图省事直接给内联写 38px，reclampSplitters() 会在窗口缩放时把它钳回
     最小值 200px——表现为「缩放一下窗口，设备栏又弹开了」。

     状态落盘 sidebar_collapsed（config.json），下次启动由 applyBootSettings
     恢复；boot 回填时 persist=false，不把刚读出来的值又写回去。 */
  let _sidebarPreCollapseW = null;
  function sidebarCollapsed() {
    const row = document.querySelector(".main-row");
    return !!(row && row.classList.contains("sidebar-collapsed"));
  }
  /* 折叠态铭牌随勾选联动：窄轨底部是「徽章 + 竖排文字」的小铭牌，默认显示
     「N / 已连接设备」。但收起后用户的每一发操作都作用于**受控（勾选）**
     设备，此时「选中几台」比「连了几台」更值得贴在铭牌上——所以有勾选时
     改显「N / 已选中设备」；一台没选时改显红色「未选中任何设备」——收起后
     用户看不到列表里的勾选框，若还显示「已连接设备」会让用户误以为当前
     操作有目标设备，一发指令下去只会撞上「未选择设备」的报错（用户实报）。
     红色 + 告警色块让「现在没有任何操作目标」一眼可见。
     展开态列表就摊在旁边，勾选状态一目了然，铭牌恒为「N 台 + 已连接设备」，
     不受勾选影响。
     renderDevices（设备事件 / 勾选广播）与 applySidebarCollapsed（收起 /
     展开）都调这里，保证两条触发路径收敛到同一份显示逻辑。 */
  function refreshSidebarNameplate() {
    const collapsed = sidebarCollapsed();
    const sel = devices.filter((d) => d.checked).length;
    const showSel = collapsed && sel > 0;
    const warn = collapsed && sel === 0;   // 收起但没有任何受控设备 → 红色警示
    if (els.devCount) {
      els.devCount.textContent = warn
        ? ""
        : (showSel ? String(sel) : (devices.length ? String(devices.length) : ""));
    }
    if (els.devCountUnit) els.devCountUnit.hidden = warn || !devices.length;
    const label = els.deviceSidebar
      && els.deviceSidebar.querySelector(".sidebar-title-text");
    if (label) {
      const want = warn ? "未选中任何设备" : (showSel ? "已选中设备" : "已连接设备");
      if (label.textContent !== want) label.textContent = want;
      if (label.classList.contains("warn") !== warn) {
        label.classList.toggle("warn", warn);
      }
    }
  }
  function applySidebarCollapsed(collapsed, persist = true) {
    const row = document.querySelector(".main-row");
    if (!row || !els.deviceSidebar) return;
    row.classList.toggle("sidebar-collapsed", !!collapsed);
    refreshSidebarNameplate();   // 收起 / 展开都要重算铭牌（选中态只在折叠态显出）
    if (collapsed) {
      _sidebarPreCollapseW = els.deviceSidebar.style.width;   // "350px" 或 ""
      els.deviceSidebar.style.width = "";
    } else if (_sidebarPreCollapseW !== null) {
      els.deviceSidebar.style.width = _sidebarPreCollapseW;
      _sidebarPreCollapseW = null;
      reclampSplitters();   // 恢复后按当前窗口宽度重钳，防止顶出右侧内容
    }
    const btn = els.sidebarCollapseBtn;
    if (btn) {
      // 与指令台的收起钮共用同一套图标（caret-left / caret-right）：两处
      // 表示同一件事，风格必须一致。data-icon 只在启动时注入一次，改它不会
      // 重绘，所以这里直接替换 svg（与 applyCmdCollapsed 同一手法）。
      setBtnIcon(btn, collapsed ? "caret-right" : "caret-left");
      btn.title = collapsed ? "展开设备栏" : "收起设备栏";
      btn.setAttribute("aria-expanded", String(!collapsed));
    }
    // 收起态给整条窄轨挂 title 与 pointer 光标（CSS 配合）：除了展开钮，
    // 点轨道空白 / 徽章 / 竖排标签也能展开——窄轨没有第二个可点目标，
    // 整轨即热区（见 bindUI 里的 click 委托）。
    if (els.deviceSidebar) {
      els.deviceSidebar.title = collapsed ? "点击展开设备栏" : "";
    }
    if (persist) persistPref("sidebar_collapsed", !!collapsed);
  }

  /* ---------------- 关于页子 tab（概览 / 使用说明）---------------- */
  let _manualLoaded = false;
  function bindAboutSubtabs() {
    els.aboutSubtabs.forEach((btn) => {
      btn.addEventListener("click", () => {
        const which = btn.dataset.aboutTab;
        els.aboutSubtabs.forEach((b) =>
          b.classList.toggle("active", b === btn));
        els.aboutPanes.forEach((p) =>
          p.hidden = (p.dataset.aboutPane !== which));
        if (which === "manual" && !_manualLoaded) loadManual();
      });
    });
  }
  // 使用说明内容由后端 get_manual() 提供（exe 内置副本经 resource_path 读取），
  // 不再以独立文件随包分发，避免维护两份脱节的文案。
  async function loadManual() {
    _manualLoaded = true;
    const res = await callApi(api.get_manual());
    if (!res || !res.ok) {
      if (els.aboutManual)
        els.aboutManual.textContent =
          "（使用说明暂不可用：" + ((res && res.reason) || "未知错误") + "）";
      _manualLoaded = false;   // 允许下次重试
      return;
    }
    if (els.aboutManual) els.aboutManual.textContent = res.text || "（内容为空）";
  }

  /* ---------------- 指令台工作区：注册 / 克隆 / 切换 / 关闭 ----------------
     默认工作区就是 index.html 里那套面板（id 全部保留，既有页面与测试按 id
     找它）。新增工作区靠克隆它得到：克隆体剥掉全部 id、改留 data-role ——
     同一份文档里不能有两个 #console，而查询又要认得出「这里是输出区」，所以
     取元素统一走 wsRole()，两条路径共用一套查法。 */
  function wsHarvest(root) {
    return {
      root: root,
      consoleEl: wsRole(root, "console"),
      promptEl: wsRole(root, "cmd-prompt"),
      inputEl: wsRole(root, "cmd-input"),
      inputClearEl: wsRole(root, "btn-cmd-input-clear"),
      runBtn: wsRole(root, "btn-run"),
      stopBtn: wsRole(root, "btn-stop"),
      clearConsoleBtn: wsRole(root, "btn-clear-console"),
      groupsEl: wsRole(root, "cmd-groups"),
      filterEl: wsRole(root, "cmd-filter"),
      tagsEl: wsRole(root, "cmd-tags"),
      countEl: wsRole(root, "cmd-count"),
      clearFilterBtn: wsRole(root, "btn-cmd-clear"),
      toggleBtn: wsRole(root, "btn-cmd-toggle"),
      keepEl: wsRole(root, "keep-input"),
      splitterEl: wsRole(root, "cmd-splitter"),
      leftPanelEl: wsRole(root, "cmd-panel-left"),
      newBtn: wsRole(root, "btn-cmd-new"),
      importBtn: wsRole(root, "btn-cmd-import"),
      importFileEl: wsRole(root, "cmd-import-file"),
      exportBtn: wsRole(root, "btn-cmd-export"),
    };
  }

  function registerWs(id, name, root) {
    // 默认工作区沿用 HTML 里的 id（测试 / 样式都认它），克隆体只有 data-role。
    // 这里统一补上 data-role，wsRole() 因此两边共用一套查法。
    root.querySelectorAll("[id]").forEach((el) => {
      if (!el.dataset.role) el.dataset.role = el.id;
    });
    root.dataset.ws = id;
    const ws = Object.assign({
      id: id, name: name || id, busy: false,
      tags: new Set(), filterTimer: null, saveTimer: null, splitterRec: null,
    }, wsHarvest(root));
    wsMap.set(id, ws);
    bindWorkspace(ws);
    renderWsTabs();      // 注册即刷新 tab 条：新工作区的 tab 立刻可点
    return ws;
  }

  /* 指令台左栏收起 / 展开（38px 窄轨，见 CSS .cmd-layout.collapsed）。
     两个关键约束：
     1. 分隔条拖动写的是**内联** style.width，会压过一切 class 规则——收起时先把
        内联宽度存起来并清空，展开时原样还回，窄轨宽度才能真的生效；
     2. 按钮图标要跟着方向换。decorateIcons 是「只注入一次」的幂等逻辑，改
        data-icon 不会重绘，所以这里直接替换按钮里的 svg。 */
  function applyCmdCollapsed(ws, collapsed, persist = true) {
    if (!ws || !ws.root || !ws.leftPanelEl) return;
    collapsed = !!collapsed;
    ws.root.classList.toggle("collapsed", collapsed);
    if (collapsed) {
      ws.preCollapseW = ws.leftPanelEl.style.width;
      ws.leftPanelEl.style.width = "";
    } else if (ws.preCollapseW !== undefined) {
      ws.leftPanelEl.style.width = ws.preCollapseW;
      ws.preCollapseW = undefined;
      reclampSplitters();   // 恢复后按当前窗口宽度重钳，防止顶出右侧内容
    }
    cmdPanelCollapsed = collapsed;
    const btn = ws.toggleBtn;
    if (btn) {
      setBtnIcon(btn, collapsed ? "caret-right" : "caret-left");
      btn.title = collapsed ? "展开指令台" : "收起指令台，给输出区更大空间";
      btn.setAttribute("aria-label", btn.title);
      btn.setAttribute("aria-expanded", String(!collapsed));
    }
    if (persist) persistPref("cmd_panel_collapsed", collapsed);
  }

  function setBtnIcon(btn, name) {
    if (!btn) return;
    btn.dataset.icon = name;
    const old = btn.querySelector("svg");
    if (old && old.parentNode) old.parentNode.removeChild(old);
    const svg = makeIcon(name);
    if (svg) btn.insertBefore(svg, btn.firstChild);
    btn.dataset.iconDone = "1";
  }

  /* 判断一次 click 是否落在某个 <button> 上。
     为什么不用 e.target.closest("button")：收起 / 展开按钮的处理器会在同一次
     事件派发里调用 setBtnIcon，把被点击的 svg / path 换掉并脱离 DOM。等事件
     冒泡到父级「整轨可点展开」委托时，e.target 已经是脱离态，closest 再也找
     不到祖先 button，委托就会误把「点按钮收起」当成「点轨道空白展开」，立刻
     又把面板顶回去——表现为「点 icon 中心收不起来」。
     composedPath() 在事件分发瞬间算好整条路径，不受后续 DOM 变动影响，能稳稳
     命中当时的 button。没有 composedPath 的老旧环境回退到 e.target.closest。 */
  function clickOnButton(e) {
    if (e && typeof e.composedPath === "function") {
      return e.composedPath().some((el) =>
        el && el.nodeType === 1 && typeof el.closest === "function" && el.closest("button"));
    }
    return !!(e && e.target && typeof e.target.closest === "function" && e.target.closest("button"));
  }

  /* 一个工作区里所有交互都在这儿绑一次（默认工作区与克隆体共用同一套代码，
     不会出现「第 2 个 tab 的按钮点了没反应」这种分叉 bug）。 */
  function bindWorkspace(ws) {
    // 每个工作区自己的翻历史状态：切 tab 翻到第 3 条，切回来应该还是第 3 条
    // 而不是回到第 1 条；但历史数组本身是全局共享的。
    ws._histIdx = -1;
    ws._histDraft = "";
    ws._tabCycleIdx = -1;           // 当前 Tab 补全会话在候选列表里的位置
    ws._tabCyclePrefix = "";        // 本轮补全的原始前缀（换了就重置循环）

    if (ws.runBtn) ws.runBtn.addEventListener("click", () => runInput(ws));
    if (ws.inputEl) {
      ws.inputEl.addEventListener("keydown", (e) => {
        if (e.key === "Enter") runInput(ws);
        else if (e.key === "ArrowUp" || e.key === "ArrowDown") {
          _cmdHistoryNav(ws, e.key === "ArrowUp" ? -1 : +1);
          e.preventDefault();
        } else if (e.key === "Tab") {
          // Tab 补全：只做「第一词命令名」——路径/参数补全需要后端逐目录探测，
          // 复杂度远高于收益。Shift+Tab 反向循环；连续 Tab 在同一前缀下循环候选。
          const ok = _cmdTabComplete(ws, !!(e.shiftKey));
          if (ok) e.preventDefault();
        } else if (e.key === "Escape") {
          // Esc：清输入 + 清翻历史状态（像终端那样）。
          if (ws.inputEl.value) {
            ws.inputEl.value = "";
            ws._histIdx = -1;
            ws._histDraft = "";
            ws._tabCycleIdx = -1;
            ws._tabCyclePrefix = "";
            if (ws.inputClearEl) ws.inputClearEl.hidden = true;
            e.preventDefault();
          }
        } else {
          // 任何其它按键都属于「用户正在编辑草稿」：翻历史位置立刻失效，
          // 下一次按 ↑ 应该回到「最新一条」（与 PowerShell 的 Get-History 行为一致）。
          // 但别把方向键 / 修饰键也覆盖掉。
          if (!e.ctrlKey && !e.metaKey && !e.altKey
              && e.key.length === 1) {
            ws._histIdx = -1;
          }
          // Tab 循环状态也仅在下一次 Tab 到来时按前缀匹配判定，这里不用动。
        }
      });
      ws.inputEl.addEventListener("input", () => {
        if (ws.inputClearEl) ws.inputClearEl.hidden = !ws.inputEl.value;
      });
      if (ws.inputClearEl) ws.inputClearEl.hidden = !ws.inputEl.value;
    }
    if (ws.inputClearEl) {
      ws.inputClearEl.addEventListener("click", () => {
        if (ws.inputEl) ws.inputEl.value = "";
        ws.inputClearEl.hidden = true;
        if (ws.inputEl) ws.inputEl.focus();
      });
    }
    if (ws.keepEl) {
      // 「保留输入内容」是一项**设置**，不是某个 tab 的私有状态：改一处，
      // 所有工作区跟着变。各 tab 各自记的话，用户会以为别的 tab 坏了。
      ws.keepEl.checked = els.keepInput ? els.keepInput.checked : ws.keepEl.checked;
      ws.keepEl.addEventListener("change", () => {
        const on = !!ws.keepEl.checked;
        wsMap.forEach((w) => { if (w.keepEl) w.keepEl.checked = on; });
        persistPref("keep_input", on);
      });
    }
    if (ws.stopBtn) {
      ws.stopBtn.addEventListener("click", async () => {
        if (ws.stopBtn.disabled) return;
        // 终止进程要走一次 adb kill，秒级；stop_state 事件到达后自动恢复。
        markBtnBusy(ws.stopBtn, true);
        await callApi(api.stop_run(ws.id));
        markBtnBusy(ws.stopBtn, false);
      });
    }
    if (ws.clearConsoleBtn) {
      ws.clearConsoleBtn.addEventListener("click", () => callApi(api.clear_output(ws.id)));
    }
    if (ws.filterEl) {
      ws.filterEl.addEventListener("input", () => {
        onCmdFilterInput(ws);
        // 过滤词落盘（只记默认工作区那份）：多个 tab 各存一个进 config.json，
        // 读回来必然互相覆盖，谁也恢复不成自己原本的样子，不如只保定一个。
        if (ws.id !== "w1") return;
        if (ws.saveTimer) clearTimeout(ws.saveTimer);
        ws.saveTimer = setTimeout(() => {
          ws.saveTimer = null;
          persistPref("cmd_filter", (ws.filterEl.value || "").trim());
        }, 400);
      });
    }
    if (ws.clearFilterBtn) {
      ws.clearFilterBtn.addEventListener("click", () => clearCmdFilter(ws));
    }
    // 命令库的增删改：弹窗是全局的，每个工作区面板上的按钮都开到同一处
    if (ws.newBtn) ws.newBtn.addEventListener("click", () => openCmdEdit(null));
    if (ws.importBtn) ws.importBtn.addEventListener("click", importCmdFromDialog);
    if (ws.importFileEl) {
      ws.importFileEl.addEventListener("change", (e) => {
        const f = e.target.files && e.target.files[0];
        if (f) importCmdFromFile(f);
        e.target.value = "";   // 允许重复导入同一文件
      });
    }
    if (ws.exportBtn) ws.exportBtn.addEventListener("click", exportCmd);
    // 长按拖动排序：绑在本工作区的列表上（每个 tab 都能拖）
    bindCmdDrag(ws.groupsEl);
    // 左右分栏：每个工作区各自一条分隔条、各自记宽度
    if (ws.splitterEl && ws.leftPanelEl) {
      ws.splitterRec = bindSplitter(ws.splitterEl, ws.leftPanelEl, 240, 360);
    }
    // 指令台收起 / 展开：按钮住在左栏标题行里，收起后左栏就是那条 38px 窄轨，
    // 按钮是轨内唯一的可点目标。整条轨也接一份 click（点空白 / 悬停都能展开）；
    // 落在按钮上的点击必须跳过——按钮处理器先执行，事件再冒泡到这里，不跳过会
    // 立刻又被展开，表现为「怎么也收不起来」（与设备栏同一处细节）。
    if (ws.toggleBtn) {
      ws.toggleBtn.addEventListener("click", () => {
        applyCmdCollapsed(ws, !ws.root.classList.contains("collapsed"));
      });
    }
    if (ws.leftPanelEl) {
      ws.leftPanelEl.addEventListener("click", (e) => {
        if (!ws.root.classList.contains("collapsed")) return;
        if (clickOnButton(e)) return;
        applyCmdCollapsed(ws, false);
      });
    }
    // 新建 / 恢复工作区时继承当前的全局收起偏好（启动恢复的顺序不保证）
    if (cmdPanelCollapsed) applyCmdCollapsed(ws, true, false);
  }

  /* 克隆默认工作区的面板。必须剥 id：留着就是一份文档里两个 #console。 */
  function cloneWsPanel(id) {
    const src = $("cmd-ws-w1");
    if (!src) return null;
    const node = src.cloneNode(true);
    node.removeAttribute("id");
    node.classList.remove("active");
    node.removeAttribute("data-ws");
    node.querySelectorAll("[id]").forEach((el) => {
      if (!el.dataset.role) el.dataset.role = el.id;
      el.removeAttribute("id");
    });
    // 新工作区从空白开始：克隆会把默认工作区现有的输出、命令卡片、筛选词
    // 一起带过来 —— 那是「复制粘贴」而不是「开一个新的」。
    ["console", "cmd-groups", "cmd-tags"].forEach((role) => {
      const el = wsRole(node, role);
      if (el) el.innerHTML = "";
    });
    const cnt = wsRole(node, "cmd-count");
    if (cnt) cnt.textContent = "";
    const flt = wsRole(node, "cmd-filter");
    if (flt) flt.value = "";
    const inp = wsRole(node, "cmd-input");
    if (inp) inp.value = "";
    const ic = wsRole(node, "btn-cmd-input-clear");
    if (ic) ic.hidden = true;
    const st = wsRole(node, "btn-stop");
    if (st) st.disabled = true;
    // 左栏宽度是内联 px（默认工作区可能被拖过），不该带进新工作区
    const left = wsRole(node, "cmd-panel-left");
    if (left) left.style.width = "";
    return node;
  }

  function nextWsId() {
    wsSeq += 1;
    while (wsMap.has("w" + wsSeq)) wsSeq += 1;
    return "w" + wsSeq;
  }

  /* 新工作区的默认名字。不能直接用 "工作区 " + (size+1)：用户把「工作区 1」
     改名成「抓日志」之后，再新建就又是「工作区 2」，而 tab 条上已经有一个叫
     「工作区 2」的了 —— 两个同名 tab，分不出来。所以跳过已占用的名字。 */
  function nextWsName() {
    const used = new Set();
    wsMap.forEach((w) => used.add(w.name));
    for (let n = wsMap.size + 1; ; n += 1) {
      const cand = "工作区 " + n;
      if (!used.has(cand)) return cand;
    }
  }

  function addWorkspace(persist = true, silent = false, wanted = "") {
    if (wsMap.size >= WS_MAX) {
      if (!silent) {
        pushStatus("warn", "⚠ 最多同时开 " + WS_MAX + " 个工作区"
          + "（每个工作区都是一条独立的常驻会话，再开只会互相抢屏幕和进程）");
      }
      return null;
    }
    const host = document.querySelector('.tab[data-tab="cmd"]');
    const id = nextWsId();
    // 名字从创建的那一刻就定下来：重启恢复时按 cmd_workspaces 里的自定义名开，
    // 顺手交给 ws_open —— 否则后端只记着「工作区 3」，改名后的状态栏前缀对不上。
    const name = sanitizeWsName(wanted) || nextWsName();
    const node = cloneWsPanel(id);
    if (!host || !node) return null;
    host.appendChild(node);
    const ws = registerWs(id, name, node);
    renderCmdTags(ws);
    applyCmdFilter(ws);
    activateWs(id);
    if (persist) persistWs();
    if (api && api.ws_open) {
      callApi(api.ws_open(id, name)).then((res) => {
        if (res && res.ok === false) {
          pushStatus("warn", "⚠ " + (res.reason || "工作区创建失败"));
        }
      });
    }
    return ws;
  }

  async function closeWorkspace(id) {
    const ws = wsMap.get(id);
    if (!ws) return;
    if (id === "w1") {
      pushStatus("warn", "默认工作区不能关闭（启动时的那一套面板就是它）");
      return;
    }
    if (ws.busy) {
      // 还有命令在跑：先停再关。直接关会留下一个「界面上已经没有了、却还在
      // 往这块面板写输出」的会话 —— 用户看不到任何东西，也停不掉它。
      await callApi(api.stop_run(id));
      pushStatus("info", "已停止「" + ws.name + "」里正在执行的命令");
    }
    if (api && api.ws_close) await callApi(api.ws_close(id));
    if (ws.splitterRec) {
      const i = _splitters.indexOf(ws.splitterRec);
      if (i >= 0) _splitters.splice(i, 1);
    }
    if (ws.filterTimer) clearTimeout(ws.filterTimer);
    if (ws.saveTimer) clearTimeout(ws.saveTimer);
    if (ws.root && ws.root.parentNode) ws.root.parentNode.removeChild(ws.root);
    wsMap.delete(id);
    if (wsActive === id) {
      const first = wsMap.keys().next().value;
      if (first) activateWs(first);
    }
    renderWsTabs();
    persistWs();
    pushStatus("info", "已关闭「" + ws.name + "」（其中的输出一并丢弃）");
  }

  function activateWs(id, opts) {
    const ws = wsMap.get(id);
    if (!ws) return;
    const prev = wsActive;
    wsActive = id;
    wsMap.forEach((w) => w.root.classList.toggle("active", w.id === id));
    // 这里**不重建** tab 条：innerHTML 一清，双击的第二下就落在了一个刚创建
    // 的新节点上，浏览器因此不补发 dblclick —— 双击改名的入口会时灵时不灵。
    renderWsTabState();
    // 切回来补一次重绘：隐藏期间窗口可能缩过，左栏的内联宽度已被钳制过
    if (ws.filterEl) applyCmdFilter(ws);
    // 记住上次停留的工作区（存名字；名字为空时用 id 兜底，与 persistWs 一致）。
    // 只在真的换了工作区时写，启动恢复期间（wsRestoring）由 restoreWorkspaces
    // 显式选中，不回写 —— 否则开几个工作区就往盘里写几次。
    if (prev !== id && !wsRestoring && (!opts || opts.persist !== false)) {
      persistPref("cmd_active_ws", sanitizeWsName(ws.name) || ws.id);
    }
  }

  function markWsBusy(ws) {
    if (!els.wsTabs || !ws) return;
    const tab = els.wsTabs.querySelector('.ws-tab[data-ws="' + ws.id + '"]');
    if (tab) tab.classList.toggle("is-busy", !!ws.busy);
  }

  /* ---------------- 工作区重命名 ----------------
     多开之后「工作区 2 / 工作区 3」谁是谁全靠记：一个在抓 logcat、一个在刷机、
     一个临时敲 adb 查东西。名字就是 config.json 里 cmd_workspaces 那一串，后端
     ws_open 也拿它做状态栏前缀，所以改名要做三件事：改本地名字、落盘、通知后端。
     少最后一步，tab 上写着「刷机」，状态栏却还是「[工作区 3] ✓ 完成」—— 两边
     对不上，用户会以为是别人在跑。 */
  function wsTabEl(id) {
    return els.wsTabs
      ? els.wsTabs.querySelector('.ws-tab[data-ws="' + id + '"]') : null;
  }

  function sanitizeWsName(raw) {
    // 逗号是 cmd_workspaces 的分隔符：名字里带上它，重启后这个工作区会被拆成
    // 两个（多出来那个是空面板），而用户根本想不到是自己名字里那个逗号干的。
    return String(raw == null ? "" : raw)
      .replace(/[,，]/g, " ")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, WS_NAME_MAX);
  }

  function wsTabTitle(ws) {
    return ws.name + "（点击切换，双击或 F2 重命名；各工作区独立执行、输出互不串台）";
  }

  function wsCloseTitle(ws) {
    return "关闭「" + ws.name + "」（其中的输出一并丢弃）";
  }

  /* 把新名字同步到 tab 上的三处文字：名字、悬停提示、关闭键的提示。
     这一步刻意就地改而不重建 tab（原因见 activateWs）：重建会把用户「刚点下去
     的那一下」连同节点一起丢掉，那一击就白点了。 */
  function syncWsTabText(ws) {
    const tab = wsTabEl(ws.id);
    if (!tab || !ws) return;
    const lab = tab.querySelector(".ws-label");
    if (lab) lab.textContent = ws.name;
    tab.title = wsTabTitle(ws);
    const x = tab.querySelector(".ws-x");
    if (x) {
      x.title = wsCloseTitle(ws);
      x.setAttribute("aria-label", "关闭 " + ws.name);
    }
  }

  /* 输入框宽度跟着字数走（等宽字体下 1ch = 1 个字符的宽度）。 */
  function fitWsRename(input) {
    const n = Math.max(6, Math.min(WS_NAME_MAX, input.value.length + 1));
    input.style.width = n + "ch";
  }

  function beginWsRename(id) {
    const ws = wsMap.get(id);
    const tab = wsTabEl(id);
    if (!ws || !tab || wsRenaming) return;
    const label = tab.querySelector(".ws-label");
    if (!label) return;
    wsRenaming = id;
    const input = document.createElement("input");
    input.type = "text";
    input.className = "ws-rename";
    input.value = ws.name;
    input.maxLength = WS_NAME_MAX;
    input.setAttribute("aria-label", "工作区名称");
    tab.classList.add("is-renaming");
    label.replaceWith(input);
    fitWsRename(input);
    // 整段选中：改名十有八九是「整条换掉」，不是改一个字
    input.focus();
    if (input.select) input.select();
    let cancelled = false;
    input.addEventListener("input", () => fitWsRename(input));
    input.addEventListener("keydown", (e) => {
      e.stopPropagation();   // 别让 Enter / 空格冒泡到 tab 的切换处理（会把焦点抢走）
      if (e.key === "Enter") { e.preventDefault(); input.blur(); }
      else if (e.key === "Escape") { e.preventDefault(); cancelled = true; input.blur(); }
    });
    // blur 是唯一的提交点：Enter 也走 blur，因此不会出现「回车提交一次、失焦
    // 又提交一次」的双写。
    input.addEventListener("blur", () => endWsRename(id, !cancelled));
    input.addEventListener("click", (e) => e.stopPropagation());
    input.addEventListener("dblclick", (e) => e.stopPropagation());
  }

  function endWsRename(id, commit) {
    const ws = wsMap.get(id);
    const tab = wsTabEl(id);
    const input = tab ? tab.querySelector(".ws-rename") : null;
    const raw = input ? input.value : "";
    // 先清标记：acceptWsName 里可能触发渲染，被「重命名中不重建」挡住就白改了
    wsRenaming = null;
    if (input) {
      const label = document.createElement("span");
      label.className = "ws-label";
      label.textContent = ws ? ws.name : "";
      input.replaceWith(label);
    }
    if (tab) tab.classList.remove("is-renaming");
    if (commit && ws) acceptWsName(ws, raw);
    // 名字可能刚被改过：文字与提示同步成最终值（取消时就是原值）
    if (ws) syncWsTabText(ws);
    if (wsRenameReplay) {
      wsRenameReplay = false;
      // 补一次被让路的渲染。推迟到下一拍：结束改名的原因常常是「点了另一个
      // tab」，此刻手指还在按下与抬起之间，现在重建节点会让那一击落到已摘除的
      // 元素上 —— 浏览器只把 click 派给仍连通的共同祖先，切 tab 就白点了。
      setTimeout(() => { if (!wsRenaming) renderWsTabs(); }, 0);
    }
  }

  function acceptWsName(ws, raw) {
    const nm = sanitizeWsName(raw);
    if (!nm) {
      // 空名字没有可落盘的意义（重启后会被 filter(Boolean) 丢掉，紧随其后的
      // 名字会往前挪一位，工作区全错位），直接拒绝并说清楚。
      pushStatus("warn", "⚠ 工作区名不能为空，仍叫「" + ws.name + "」");
      return false;
    }
    if (nm === ws.name) return false;   // 没改：不落盘、不打扰
    const old = ws.name;
    ws.name = nm;
    persistWs();
    // 改的是当前停留的那个：cmd_active_ws 里存的是名字，不改就指向一个
    // 已经不存在的名字，下次启动会莫名回退到第一个工作区。
    if (ws.id === wsActive) persistPref("cmd_active_ws", nm);
    // 默认工作区不用通知后端：它的状态播报本来就不带前缀（单工作区时代的文案
    // 一字不变），登记了也用不上。
    if (ws.id !== "w1" && api && api.ws_open) callApi(api.ws_open(ws.id, nm));
    pushStatus("info", "已重命名：「" + old + "」→「" + nm + "」");
    return true;
  }

  /* 只刷新 tab 的「状态类」，不重建节点（见 activateWs 里的注释）。 */
  function renderWsTabState() {
    if (!els.wsTabs) return;
    wsMap.forEach((ws) => {
      const tab = wsTabEl(ws.id);
      if (!tab) return;
      const active = ws.id === wsActive;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", active ? "true" : "false");
      tab.classList.toggle("is-busy", !!ws.busy);
    });
    updateWsHint();
  }

  function updateWsHint() {
    if (!els.wsHint) return;
    // 提示里带上改名这条：双击是「没人告诉你就发现不了」的交互，写在 tab 旁边
    // 才有人用得上 —— 否则多开几个之后还是靠数序号认人。
    els.wsHint.textContent = wsMap.size > 1
      ? "共 " + wsMap.size + " 个工作区，各自独立执行、指令库共用；双击 tab 名可重命名"
      : "每个工作区各有一条独立会话，可同时执行；双击 tab 名可重命名";
  }

  function renderWsTabs() {
    if (!els.wsTabs) return;
    // 重命名进行中不重建 tab 条：innerHTML 一清空，正在输入的那个 <input> 就没了，
    // 用户打到一半的名字直接丢。当前的重绘入口（新建 / 关闭 / 恢复布局）都走不到
    // 「改名途中」这一刻，但这条约束不能靠调用顺序去赌：少这一行，将来任何一处
    // 新加的重绘就是一次「打着字突然没了」，而且极难复现。
    if (wsRenaming) { wsRenameReplay = true; return; }
    els.wsTabs.innerHTML = "";
    wsMap.forEach((ws) => {
      const active = ws.id === wsActive;
      const tab = document.createElement("div");
      tab.className = "ws-tab" + (active ? " active" : "") + (ws.busy ? " is-busy" : "");
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-selected", active ? "true" : "false");
      tab.tabIndex = 0;
      tab.dataset.ws = ws.id;
      tab.title = wsTabTitle(ws);
      const dot = document.createElement("span");
      dot.className = "ws-dot";
      dot.setAttribute("aria-hidden", "true");
      tab.appendChild(dot);
      const label = document.createElement("span");
      label.className = "ws-label";
      label.textContent = ws.name;
      tab.appendChild(label);
      tab.addEventListener("click", () => activateWs(ws.id));
      tab.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activateWs(ws.id); }
        // 键盘用户的改名入口（双击是鼠标习惯，纯键盘够不着）
        else if (e.key === "F2") { e.preventDefault(); beginWsRename(ws.id); }
      });
      // 双击 tab 名重命名。多开之后光靠「工作区 N」根本分不清谁是谁。
      tab.addEventListener("dblclick", (ev) => {
        // 双击「关闭」键也会冒泡到 tab 上：用户两次点叉想关掉，结果进了输入框，
        // 关不掉还多出一个改名框。
        if (ev.target && ev.target.classList && ev.target.classList.contains("ws-x")) return;
        beginWsRename(ws.id);
      });
      if (ws.id !== "w1") {
        // 关闭键用 span 而非 button：button 里嵌 button 是非法结构，浏览器
        // 会把内层按钮拆到外边，点关闭变成点切换。
        const x = document.createElement("span");
        x.className = "ws-x";
        x.textContent = "×";
        x.setAttribute("role", "button");
        x.dataset.role = "ws-close";
        x.title = wsCloseTitle(ws);
        x.setAttribute("aria-label", "关闭 " + ws.name);
        x.addEventListener("click", (ev) => {
          ev.stopPropagation();
          closeWorkspace(ws.id);
        });
        tab.appendChild(x);
      }
      els.wsTabs.appendChild(tab);
    });
    updateWsHint();
  }

  function persistWs() {
    const names = [];
    // 空名会破坏「按序号还原」的对齐（重启后 filter(Boolean) 把它丢掉，后面
    // 的名字整体前移一位，工作区全错位），所以兜底成 id。
    wsMap.forEach((ws) => names.push(sanitizeWsName(ws.name) || ws.id));
    persistPref("cmd_workspaces", names.join(","));
  }

  /* 恢复上次的工作区布局（config.json 的 cmd_workspaces，逗号分隔的名字）。
     第一个名字对应默认工作区（它总是存在），其余按顺序补开。
     名字必须在这一步交给 addWorkspace（它随 ws_open 一起送给后端），不能开完
     再改 ws.name：那样后端记的还是「工作区 3」，重启后状态栏前缀与 tab 对不上。
     cmd_active_ws 记的是上次停留的那个，全部开完后按名字选中它。 */
  function restoreWorkspaces(raw, activeName) {
    const names = String(raw || "").split(",").map((s) => s.trim()).filter(Boolean);
    // 恢复期间 addWorkspace 会逐个 activate：先压住「写 cmd_active_ws」，
    // 等全部开完再选中目标，避免启动时连写好几次盘。
    wsRestoring = true;
    try {
      if (names.length > 1) {
        const w1 = wsMap.get("w1");
        if (w1 && sanitizeWsName(names[0])) w1.name = sanitizeWsName(names[0]);
        for (let i = 1; i < names.length && wsMap.size < WS_MAX; i += 1) {
          addWorkspace(false, true, names[i]);
        }
      }
      // 按名字匹配（兼容旧值里存的是内部 id 的情况）；找不到（改过名 / 已关闭 /
      // 配置被手改）就落回默认工作区，而不是让页面空着一个都不选。
      const want = sanitizeWsName(activeName);
      let target = "";
      if (want) {
        wsMap.forEach((w, id) => {
          if (!target && (sanitizeWsName(w.name) === want || w.id === want)) target = id;
        });
      }
      activateWs(target || "w1", { persist: false });
    } finally {
      wsRestoring = false;
    }
    renderWsTabs();
  }

  /* ---------------- 主 tab（设备指令 / 工具 / 性能监控 / Logcat / 文件 / 关于） ----------------
     与工具区子 tab 同一套约定：合法 key 从 DOM 派生（增删一项只改 index.html），
     上次停留项落盘 main_active_tab、启动按它恢复，值没变就不写盘。 */
  function mainTabKeys() {
    if (!els.tabs) return [];
    return Array.from(els.tabs.querySelectorAll(".tab-btn"))
      .map((b) => b.dataset.tab).filter(Boolean);
  }

  function switchMainTab(key, opts) {
    const keys = mainTabKeys();
    if (!keys.length) return;
    // 配置里存的是已删除的 tab（版本变动删了某项 / 手改坏）→ 回退到第一项
    if (keys.indexOf(key) === -1) key = keys[0];
    els.tabs.querySelectorAll(".tab-btn").forEach((b) =>
      b.classList.toggle("active", b.dataset.tab === key));
    document.querySelectorAll(".tab").forEach((t) =>
      t.classList.toggle("active", t.dataset.tab === key));
    // 性能页的 canvas 在隐藏时尺寸为 0，切回来必须重画一次，
    // 否则会留下一张空位图（监控仍在跑，但曲线一片空白）。
    if (key === "perf") { renderPerfDev(); queuePerfDraw(); }
    const changed = mainActiveTab !== key;
    mainActiveTab = key;
    // 值没变就不写盘：重复点当前 tab 时省一次「读-合并-写」；
    // 启动回填（persist:false）只更新内存值，不会「一打开就写一次盘」。
    if (changed && (!opts || opts.persist !== false)) {
      persistPref("main_active_tab", key);
    }
  }

  /* 启动时按 main_active_tab 回到上次那个主 tab（没记过 / 失效 → 设备指令）。
     必须在 onBooted 里 renderCommands 之后调用：切到「性能监控」时要按已勾选的
     设备渲染目标设备条，切到「设备指令」时指令卡得已经画好。 */
  function restoreMainTab(key) {
    if (typeof key !== "string" || !key) return;
    if (mainTabKeys().indexOf(key) === -1) return;   // 失效就保持 HTML 默认（设备指令）
    if (key === mainActiveTab) return;
    switchMainTab(key, { persist: false });
  }

  /* ---------------- UI 绑定 ---------------- */
  function bindUI() {
    // 采用原生标题栏（含 min/max/close），不再自绘窗口按钮与 Win32 拖拽。
    // （遗留代码随 v2026.0908.2228 清理，见 README。）
    renderTicker();          // 空态提示，先把跑马灯填上占位文案

    // tab 切换（实际切换收在 switchMainTab，启动恢复与点击走同一条路径）
    els.tabs.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => switchMainTab(btn.dataset.tab));
    });
    // 主题切换（深 / 浅 / 随系统）：点击即对应当前模式套色并落盘 + 联动原生标题栏
    if (els.themeSwitch) {
      els.themeSwitch.querySelectorAll(".theme-opt").forEach((b) => {
        b.addEventListener("click", () => setTheme(b.dataset.themeMode));
      });
    }
    // 设备指令
    // 设备刷新：防连点 + finally 兜底恢复（后端即使不返回，按钮也不会永久锁死）
    els.btnRefresh.addEventListener("click", async () => {
      if (!els.btnRefresh || els.btnRefresh.disabled) return;
      els.btnRefresh.disabled = true;
      markBtnBusy(els.btnRefresh, true);
      try {
        const res = await callApi(api.refresh_devices());
        // 后端返回 running=true 表示已有刷新在进行（boot() 首轮刷新 / 自动轮询撞上）
        if (res && res.running) {
          pushStatus("info", "ℹ 设备刷新正在进行中，完成后列表会自动更新");
        }
      } finally {
        els.btnRefresh.disabled = false;
        markBtnBusy(els.btnRefresh, false);
      }
    });
    els.btnAll.addEventListener("click", () => callApi(api.toggle_all()));
    // ---------- 指令台工作区（子 tab）----------
    // 默认工作区就是 HTML 里那套面板：注册后由 bindWorkspace 统一绑事件，
    // 与后来克隆出来的工作区走完全相同的代码路径（不留「第 1 个 tab 和别的
    // tab 行为不一致」这种分叉）。原先散在这里的指令台绑定因此整体移了过去。
    registerWs("w1", "工作区 1", $("cmd-ws-w1"));
    if (els.btnWsAdd) els.btnWsAdd.addEventListener("click", () => addWorkspace());
    els.btnClearStatus.addEventListener("click", () => callApi(api.clear_status()));
    // 命令增删改：新建 / 保存 / 取消 / 删除 / 快捷键
    els.cmdEditSave.addEventListener("click", saveCmdEdit);
    els.cmdEditCancel.addEventListener("click", closeCmdEdit);
    els.cmdEditClose.addEventListener("click", closeCmdEdit);
    els.cmdEditDelete.addEventListener("click", () => {
      const id = els.cmdEdit.dataset.id;
      if (id) { const c = allCommands.find((x) => x.id === id); if (c) deleteCmd(c); }
      closeCmdEdit();
    });
    els.cmdEditName.addEventListener("keydown", (e) => { if (e.key === "Enter") saveCmdEdit(); });
    els.cmdEditCmds.addEventListener("keydown", (e) => { if (e.key === "Escape") closeCmdEdit(); });
    // 命令导入 / 导出（备份 & 分享）
    // 导入：优先用后端原生文件对话框（默认定位到程序目录，见 import_commands_dialog）；
    // 若运行环境不支持该 API，则降级为浏览器原生 <input type=file>（无默认定位）。
    els.cmdImport.addEventListener("click", importCmdFromDialog);
    els.cmdImportFile.addEventListener("change", (e) => {
      const f = e.target.files && e.target.files[0];
      if (f) importCmdFromFile(f);
      e.target.value = "";   // 允许重复导入同一文件
    });
    els.cmdExport.addEventListener("click", exportCmd);
    els.cmdExportClose.addEventListener("click", closeCmdExport);
    els.cmdExportClose2.addEventListener("click", closeCmdExport);
    els.cmdExportCopy.addEventListener("click", copyExport);
    els.cmdExportSave.addEventListener("click", saveExportFile);
    els.cmdExportModal.addEventListener("click", (e) => {
      if (e.target === els.cmdExportModal) closeCmdExport();
    });
    // 状态信息复制（弹窗内）
    els.btnCopyStatus.addEventListener("click", copyStatus);
    // logcat
    els.lcStart.addEventListener("click", async () => {
      const s = firstSelected(); if (!s) return pushStatus("warn", "请先勾选设备");
      lcSerial = s;
      refreshLcPackages();
      // 后端可能因「已在监控中 / 设备不可用」返回 ok:false：此时必须回滚按钮态，
      // 否则界面永远停在「采集中」、开始按钮被锁死，用户无从恢复。
      markBtnBusy(els.lcStart, true);
      const res = await startLc();
      markBtnBusy(els.lcStart, false);
      if (!res || res.ok === false) {
        pushStatus("err", "⚠ 监控未能启动"
          + (res && res.reason ? "（" + res.reason + "）" : ""));
        els.lcStatus.textContent = "空闲"; setLcRunning(false);
        return;
      }
      // 立即置为采集中：不必等后端事件回传，避免点了没反应的观感
      els.lcStatus.textContent = "采集中…"; setLcRunning(true);
      lcDropping = false;   // 新会话开门：放行后续 append（running 事件也会再兜一次）
    });
    els.lcStop.addEventListener("click", () => {
      callApi(api.logcat_stop(lcSerial));
      // 立刻停掉前端渲染机：待渲染队列深时（上限 20000 行）若不清，帧循环
      // 会继续滚很久 —— 「点了停止，程序要很久才停下来」的直接原因。
      clearLcQueue();
      lcDropping = true;    // 在途的 append 属于已结束会话，丢弃
      els.lcStatus.textContent = "空闲"; setLcRunning(false);
    });
    els.lcClear.addEventListener("click", () => {
      // 未选设备时 lcSerial 为 null，直接写 lcBuffers[null] 会留下垃圾键
      if (!lcSerial) return pushStatus("warn", "请先开始监控并选择设备");
      lcBuffers[lcSerial] = { lines: [], total: 0, exc: 0 };
      renderLogcat();
      callApi(api.logcat_clear(lcSerial));
    });
    // 日志右键菜单（选中复制 / 复制该行）：依赖 els.lcView，绑一次即可
    initLcContextMenu();
    // 关键字输入防抖：每敲一个字都全量重建 DOM 会明显卡顿（与
    // core/constants.LOGCAT_RERENDER_DEBOUNCE_MS 同值）。级别/仅异常是离散操作，
    // 立即生效，不防抖。关键字同时落盘（防抖末尾存一次，别每敲一个字写盘）。
    els.lcFilter.addEventListener("input", () => {
      if (lcFilterTimer !== null) clearTimeout(lcFilterTimer);
      lcFilterTimer = setTimeout(() => {
        lcFilterTimer = null;
        persistPref("lc_keyword", els.lcFilter.value);
        // 表达式里可能刚出现/改掉 pkg:（这是唯一需要异步解析的字段）
        lcRefreshPkgPids();
        syncLcPkgTimer();
        // 手工改过条件：与已选预设不再一致时把下拉退回「（无）」
        const idx = els.lcPreset ? els.lcPreset.value : "";
        const preset = idx === "" ? null : lcPresets[Number(idx)];
        if (preset && preset.kw.trim() !== els.lcFilter.value.trim()) {
          selectLcPreset("");
        }
        if (lcSerial) renderLogcat();
      }, LC_DEBOUNCE_MS);
    });
    // 预设：选中即应用；手改表达式后若与预设不再一致，下拉自动回到「（无）」，
    // 否则界面会显示「当前是预设 A」而实际过滤条件已经变了。
    if (els.lcPreset) els.lcPreset.addEventListener("change", applyLcPreset);
    if (els.lcPresetSave) els.lcPresetSave.addEventListener("click", saveLcPreset);
    if (els.lcPresetDel) els.lcPresetDel.addEventListener("click", deleteLcPreset);
    els.lcLevels.addEventListener("change", () => {
      persistPref("lc_levels", levelsOf(els.lcLevels));
      if (lcSerial) renderLogcat();
    });
    els.lcOnlyExc.addEventListener("change", () => {
      persistPref("lc_only_exc", !!els.lcOnlyExc.checked);
      if (lcSerial) renderLogcat();
    });
    // 「按包」下拉：选中即把 pid: 条件写进过滤框（而不是 pkg:）——下拉里的包
    // 我们在选中这一刻就能解析出 pid，写成显式 pid: 后表达式是可读、可编辑、
    // 可复制的，用户也能在此基础上再补 -tag: 之类的排除条件。
    if (els.lcPkg) {
      els.lcPkg.addEventListener("change", () => {
        const name = els.lcPkg.value;
        if (!name) return;
        if (!lcSerial) return;
        const serial = lcSerial;      // 响应回来时用户可能已切设备，缓存要记在发起方设备上
        callApi(api.logcat_pidof(serial, name)).then((r) => {
          const pids = (r && Array.isArray(r.pids)) ? r.pids : [];
          if (serial !== lcSerial) return;   // 迟到的解析结果不再改写当前过滤框
          if (!pids.length) {
            // 包没在跑：明确说出来，否则用户以为过滤坏了。同时记下「已提示」，
            // 免得监控中的 5 秒重解析再补一句重复的警告。
            lcPkgEmptyWarned[lcPkgPidKey(serial, name.toLowerCase())] = true;
            pushStatus("warn", "⚠ 包 " + name + " 当前没有在运行（pid 为空），"
                      + "先把它启动起来再过滤");
            return;
          }
          // 多进程包（如含 :remote）会产生多个 pid，用空格 AND 会变成「同时等于
          // 两个 pid」永远不成立；所以多 pid 时改用 pkg: 交给后端/前端按集合匹配。
          if (pids.length === 1) {
            els.lcFilter.value = "pid:" + pids[0];
          } else {
            lcApplyPkgPids(lcSerial, name.toLowerCase(), pids);
            els.lcFilter.value = "pkg:" + name;
          }
          triggerLcFilter();
        }).catch(() => {});
      });
    }
    // 自动滚动 / 缓冲区：不触发重渲染，只记忆选择（下次启动 / 下次抓取生效）
    els.lcAuto.addEventListener("change", () => persistPref("lc_autoscroll", !!els.lcAuto.checked));
    els.lcBuf.addEventListener("change", () => persistPref("lc_buffer", els.lcBuf.value));
    els.lcCapZipstop.addEventListener("change", () => {
      persistPref("lc_cap_zipstop", !!els.lcCapZipstop.checked);
    });
    els.lcCapLevels.addEventListener("change", () => {
      persistPref("lc_cap_levels", levelsOf(els.lcCapLevels));
    });
    els.lcCapStart.addEventListener("click", async () => {
      const s = firstSelected(); if (!s) return pushStatus("warn", "请先勾选设备");
      lcCapSerial = s;   // 记下抓取目标：停止时必须停这一台，不能用当前监控设备
      // 启动要 adb 建进程 + 打开文件；先给「启动中」转圈，running 事件到达后收掉。
      // 不立刻禁用：后端 already_running / 启动失败时不会有 running 事件，
      // 禁用后按钮就再也点不动了；重复点由后端幂等拒绝。
      markBtnBusy(els.lcCapStart, true);
      // 级别过滤：V/D/I/W/E/F 全勾（默认）= 全量抓取；只勾一部分则只落盘
      // 对应级别的行（非 threadtime 格式行始终原样写盘，避免丢元信息）
      const res = await callApi(api.logcat_capture_start(s, saveDir(), buffers(), levelsOf(els.lcCapLevels)));
      if (!res || res.ok === false) markBtnBusy(els.lcCapStart, false);
    });
    els.lcCapStop.addEventListener("click", async () => {
      const s = lcCapSerial || lcSerial;
      if (!s) return pushStatus("warn", "当前没有正在抓取的设备");
      // 停止要等进程收尾 + 可能打包，秒级；在 stopped / zipped / error 事件里收掉转圈。
      els.lcCapStop.disabled = true;
      markBtnBusy(els.lcCapStop, true);
      const res = await callApi(api.logcat_capture_stop(s, els.lcCapZipstop.checked));
      if (!res || res.ok === false) {
        markBtnBusy(els.lcCapStop, false);
        els.lcCapStop.disabled = !lcCapRunning;
      }
    });
    // tools
    els.toolOpen.addEventListener("click", () => callApi(api.open_save_dir(saveDir())));
    els.lcOpen.addEventListener("click", () => callApi(api.open_save_dir(saveDir())));
    els.fileOpen.addEventListener("click", () => callApi(api.open_save_dir(saveDir())));
    // 「选择」：弹出系统文件夹对话框代替手动输入路径
    // 三档结果必须分开处理：选中 → 写输入框并落盘；取消 → 静默（不打扰）；
    // 打不开 → 必须说一句。旧实现把后两者都当「取消」吞掉，于是按钮点下去
    // 毫无反应 —— 用户只能反复点，还以为程序卡了。
    // 点击瞬间先禁用：Windows 上首次弹对话框要几百毫秒，没有反馈会被当成没点上。
    [["lcPick", els.lcDir], ["toolPick", els.toolDir], ["filePick", els.fileDir]]
      .forEach(([key, input]) => {
        if (!els[key] || !input) return;
        els[key].addEventListener("click", async () => {
          const btn = els[key];
          if (btn.disabled) return;
          btn.disabled = true;
          markBtnBusy(btn, true);
          try {
            const res = await callApi(api.select_save_dir((input.value || "").trim()));
            if (res && res.ok && res.path) {
              input.value = res.path;
              // 复用现有 change 逻辑：镜像到另两处输入 + 落盘 + 状态提示
              input.dispatchEvent(new window.Event("change", { bubbles: true }));
            } else if (res && res.reason === "unsupported") {
              pushStatus("warn",
                "当前环境无法弹出文件夹选择框，请直接输入保存目录路径");
            }
            // cancelled：用户自己取消，不提示；error：后端已播报原因，不重复
          } finally {
            markBtnBusy(btn, false);
            btn.disabled = false;
          }
        });
      });
    // 截图开关「同步至粘贴板」：布尔值直接随截图动作下发（即时生效，不依赖
    // settings.json 是否写成功），同时落盘到 settings.json 供下次启动沿用。
    els.toolShot.addEventListener("click", async () => {
      // 截图 = 设备采集 + USB 传输 + 落盘（+剪贴板解码），耗时以秒计。按钮
      // 不禁用的话，用户等待中会连点、或以为"点了没反应"。点击即禁用给出
      // 「进行中」反馈；完成后由后端 shot_state(running=false) 恢复。后端
      // 直接拒绝（未勾选设备）或桥接异常时按调用结果就地恢复——绝不把
      // 按钮永久锁死。
      if (els.toolShot.disabled) return;
      els.toolShot.disabled = true;
      markBtnBusy(els.toolShot, true);
      const res = await callApi(api.screenshot(
        null, !!(els.shotClipboard && els.shotClipboard.checked),
        !!(els.shotSaveFile && els.shotSaveFile.checked)));
      if (!res || res.ok === false) syncToolButtons();
    });
    if (els.shotClipboard) {
      els.shotClipboard.addEventListener("change", () => {
        persistPref("shot_to_clipboard", !!els.shotClipboard.checked);
      });
    }
    if (els.shotSaveFile) {
      els.shotSaveFile.addEventListener("change", () => {
        persistPref("shot_save_file", !!els.shotSaveFile.checked);
      });
    }
    // 录屏各开关一律即时记忆（config.json），下次启动沿用以往配置。
    // 同步 logcat 只留一个开关：级别与缓冲区不再可调（全量抓取才可能复现问题，
    // 少勾一级就少一条线索，而用户往往事后才发现漏了哪一级）。
    [["recLogcat", "rec_logcat"], ["recMic", "rec_mic"], ["recZip", "rec_zip"],
     ["recPointerLocation", "rec_pointer_location"],
     ["recShowTouches", "rec_show_touches"]].forEach(([el, key]) => {
      if (els[el]) els[el].addEventListener("change", () => persistPref(key, !!els[el].checked));
    });
    // 工具区子 tab：点击切换 + 长按拖动排序（与指令卡同一套长按手势）
    bindToolSubtabs();
    bindToolTabDrag();
    // Logcat 子 tab：落盘抓取 / 实时监控（顺序固定，无需拖动排序）
    bindLcSubtabs();
    // ---- 应用安装（APK）----
    if (els.apkPick) els.apkPick.addEventListener("click", pickApk);
    if (els.apkInstall) els.apkInstall.addEventListener("click", installApk);
    // 三个安装选项即时落盘（与截图/录屏开关同一套语义：改完下次启动沿用）
    [["apkReplace", "apk_replace"], ["apkDowngrade", "apk_downgrade"],
     ["apkGrant", "apk_grant"]].forEach(([el, key]) => {
      if (els[el]) els[el].addEventListener("change", () => persistPref(key, !!els[el].checked));
    });
    // ---- 诊断包 ----
    if (els.diagCollect) els.diagCollect.addEventListener("click", collectDiag);
    if (els.diagLogcat) {
      els.diagLogcat.addEventListener("change", () => {
        persistPref("diag_with_logcat", !!els.diagLogcat.checked);
        // 不勾 logcat 时行数无意义：灰掉而不是隐藏（隐藏会让下面的按钮左右跳）
        if (els.diagLines) els.diagLines.disabled = !els.diagLogcat.checked;
      });
    }
    if (els.diagLines) {
      els.diagLines.addEventListener("change", () => {
        const n = Number(els.diagLines.value) || 0;
        if (n > 0) persistPref("diag_logcat_lines", n);
      });
    }
    // ---- 无线调试（Wi-Fi ADB）----
    if (els.btnWifi) els.btnWifi.addEventListener("click", wifiOpen);
    if (els.wifiClose) els.wifiClose.addEventListener("click", wifiClose);
    if (els.wifiClose2) els.wifiClose2.addEventListener("click", wifiClose);
    if (els.wifiConnect) els.wifiConnect.addEventListener("click", wifiConnect);
    if (els.wifiTcpip) els.wifiTcpip.addEventListener("click", wifiTcpip);
    if (els.wifiAddr) {
      els.wifiAddr.addEventListener("keydown", (e) => {
        if (e.key === "Enter") wifiConnect();
        if (e.key === "Escape") wifiClose();
      });
    }
    if (els.wifiModal) {
      // 点背景关闭（与命令导出 / 阈值弹窗同一手感）
      els.wifiModal.addEventListener("click", (e) => {
        if (e.target === els.wifiModal) wifiClose();
      });
    }
    // ---- 设备信息 ----
    if (els.devinfoClose) els.devinfoClose.addEventListener("click", closeDevInfo);
    if (els.devinfoClose2) els.devinfoClose2.addEventListener("click", closeDevInfo);
    if (els.devinfoRefresh) els.devinfoRefresh.addEventListener("click", loadDeviceInfo);
    if (els.devinfoCopy) els.devinfoCopy.addEventListener("click", copyDevInfo);
    if (els.devinfoModal) {
      els.devinfoModal.addEventListener("click", (e) => {
        if (e.target === els.devinfoModal) closeDevInfo();
      });
    }
    // ---- 投屏（scrcpy）----
    if (els.toolScrcpy) {
      els.toolScrcpy.addEventListener("click", async () => {
        // 先在途禁用：scrcpy 启动要等 START_SETTLE 确权，连点会开出重复窗口
        els.toolScrcpy.disabled = true;
        markBtnBusy(els.toolScrcpy, true);
        setScrcpyState("", "启动中…");
        const res = await callApi(api.scrcpy_start(null));
        if (res && res.ok) {
          const n = (res.started || []).length, s = (res.skipped || []).length;
          setScrcpyState("ok", (n ? "已开启 " + n + " 个投屏窗口" : "已在投屏中")
                              + (s ? "（" + s + " 台已在投屏）" : ""), res.path || "");
        } else if (res && res.reason === "scrcpy_not_found") {
          setScrcpyState("err", res.note || "未找到 scrcpy", res.note || "");
        } else if (res && res.reason === "no_device") {
          setScrcpyState("err", "请先在左侧勾选受控设备");
        } else if (res && res.failed && res.failed.length) {
          setScrcpyState("err", res.failed[0].serial + "：" + res.failed[0].reason);
        } else if (res) {
          setScrcpyState("err", "投屏未启动");
        }
        markBtnBusy(els.toolScrcpy, false);
        syncToolButtons();   // 恢复按钮可用性（无受控设备时仍保持禁用）
      });
    }
    if (els.scrcpyDetect) {
      els.scrcpyDetect.addEventListener("click", () => probeScrcpy());
    }
    if (els.scrcpyPath) {
      // 失焦 / 回车时落盘并立即重新探测：用户填完路径就能马上看到是否可用
      els.scrcpyPath.addEventListener("change", async () => {
        const v = (els.scrcpyPath.value || "").trim();
        persistPref("scrcpy_path", v);
        await probeScrcpy();
      });
    }
    probeScrcpy();

    // ---- 备用投屏（没装 scrcpy 时：screenrecord 管道 → 低帧率预览）----
    if (els.toolMirror) {
      els.toolMirror.addEventListener("click", async () => {
        els.toolMirror.disabled = true;
        markBtnBusy(els.toolMirror, true);
        setMirrorState("", "启动中…");
        const res = await callApi(api.mirror_start(null, "pipe"));
        const label = { pipe: "播放器窗口（screenrecord）", snap: "低帧率预览（screencap）",
                        scrcpy: "scrcpy" };
        if (res && res.ok && res.started && res.started.length) {
          const snap = res.started.find((x) => x.mode === "snap");
          const names = res.started.map((x) => x.serial).join("、");
          setMirrorState("ok", "已投屏：" + names + " · "
            + res.started.map((x) => label[x.mode] || x.mode).join(" / "),
            "备用投屏已开启");
          // 只有低帧率预览是内嵌画面；管道投屏在独立播放器窗口里
          if (snap && snap.frame_url) {
            startMirrorPreview(snap.frame_url);
          } else {
            stopMirrorPreview();
            if (els.toolMirrorStop) els.toolMirrorStop.disabled = false;
          }
        } else if (res && res.reason === "no_device") {
          setMirrorState("err", "请先在左侧勾选受控设备");
        } else if (res && res.failed && res.failed.length) {
          setMirrorState("err", res.failed[0].serial + "：" + res.failed[0].reason);
        } else {
          setMirrorState("err", "投屏未启动");
        }
        markBtnBusy(els.toolMirror, false);
        syncToolButtons();
      });
    }
    if (els.toolMirrorStop) {
      els.toolMirrorStop.addEventListener("click", async () => {
        if (els.toolMirrorStop.disabled) return;
        els.toolMirrorStop.disabled = true;
        markBtnBusy(els.toolMirrorStop, true);
        stopMirrorPreview();
        await callApi(api.mirror_stop(null));
        markBtnBusy(els.toolMirrorStop, false);
        setMirrorState("", "已停止");
      });
    }
    // 参数落盘（数值先夹到合法区间，避免手填 0 帧率把后端轮询打满）
    if (els.mirrorSize) {
      els.mirrorSize.addEventListener("change", () =>
        persistPref("mirror_size", (els.mirrorSize.value || "").trim()));
    }
    // 夹取规则：填了数字就夹进合法区间（0 → 下限），没填/乱填才回默认值。
    // 若一律 `|| 默认`，用户填 0 会拿到默认值 2 而不是下限 1，和界面显示的
    // min/max 自相矛盾。
    const clampInt = (raw, lo, hi, dflt) => {
      const n = parseInt(raw, 10);
      return Math.min(hi, Math.max(lo, isNaN(n) ? dflt : n));
    };
    if (els.mirrorBitrate) {
      els.mirrorBitrate.addEventListener("change", () => {
        const n = clampInt(els.mirrorBitrate.value, 1, 50, 8);
        els.mirrorBitrate.value = String(n);
        persistPref("mirror_bitrate", n);
      });
    }
    if (els.mirrorFps) {
      els.mirrorFps.addEventListener("change", () => {
        const n = clampInt(els.mirrorFps.value, 1, 10, 2);
        els.mirrorFps.value = String(n);
        persistPref("mirror_fps", n);
      });
    }
    bindMirrorResize();
    bindShotPreviewResize();
    if (els.mirrorPlayerPath) {
      els.mirrorPlayerPath.addEventListener("change", async () => {
        const v = (els.mirrorPlayerPath.value || "").trim();
        persistPref("mirror_player_path", v);
        await probeMirror();
      });
    }
    probeMirror();

    // ---- 性能监控 ----
    if (els.perfStats) {
      els.perfStats.querySelectorAll(".perf-stat").forEach((card) => {
        const pick = () => setPerfMetric(card.dataset.metric, true);
        card.addEventListener("click", pick);
        card.addEventListener("keydown", (e) => {
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); }
        });
      });
    }
    if (els.perfStart) els.perfStart.addEventListener("click", startPerf);
    if (els.perfStop) els.perfStop.addEventListener("click", stopPerf);
    if (els.perfExport) els.perfExport.addEventListener("click", exportPerf);
    // 查看报告：导出后想翻看刚生成的报告时，一键打开报告所在目录（保存目录），
    // 不用回工具页再点「打开目录」。与「打开目录」同一套后端 open_save_dir。
    if (els.perfView) {
      els.perfView.addEventListener("click", () => {
        callApi(api.open_save_dir(saveDir()));
      });
    }
    if (els.perfThBtn) els.perfThBtn.addEventListener("click", openPerfThresholds);
    if (els.perfThSave) els.perfThSave.addEventListener("click", savePerfThresholds);
    if (els.perfThCancel) els.perfThCancel.addEventListener("click", closePerfThresholds);
    if (els.perfThClose) els.perfThClose.addEventListener("click", closePerfThresholds);
    if (els.perfThReset) {
      // 只改界面上的值，等用户点「保存」才落盘：误点一下就把自定义阈值清掉
      // 且无法撤销，是最容易招人骂的交互。
      els.perfThReset.addEventListener("click", () => {
        renderPerfThresholdRows(perfThItems.map((it) => Object.assign({}, it, {
          value: it["default"] === undefined ? null : it["default"],
        })));
        showPerfThError("");
      });
    }
    if (els.perfThModal) {
      els.perfThModal.addEventListener("click", (e) => {
        if (e.target === els.perfThModal) closePerfThresholds();   // 点遮罩关闭
      });
      // 取消勾选 = 关闭该项：数值框跟着置灰，避免「关着却还显示一个数字」
      els.perfThModal.addEventListener("change", (e) => {
        const t = e.target;
        if (t && t.classList && t.classList.contains("th-on")) {
          const row = t.closest(".th-row");
          if (row) row.classList.toggle("on", t.checked);
        }
      });
    }
    if (els.perfLegend) {
      // 图例项用事件委托：多设备时每次轮询都会重建图例节点，
      // 逐个绑定会在几秒内堆出成百上千个监听器。
      els.perfLegend.addEventListener("click", (e) => {
        const btn = e.target && e.target.closest ? e.target.closest(".perf-lg") : null;
        if (btn && btn.dataset.serial) focusPerf(btn.dataset.serial);
      });
    }
    if (els.perfInterval) {
      els.perfInterval.addEventListener("change", () => {
        const ms = clampInt(els.perfInterval.value, 200, 10000, 1000);
        els.perfInterval.value = String(ms);
        persistPref("perf_interval_ms", ms);
      });
    }
    bindPerfPkgPicker();
    bindPerfHover();
    renderPerfDev();
    updatePerfStats();
    queuePerfDraw();
    loadPerfThresholds();

    els.toolRec.addEventListener("click", async () => {
      if (recInFlight) return;      // 启动在途：按钮已禁用，这里再兜一道
      // 第 2 参（设备音频）固定 false：设备端 tinycap 需 root、机型差异大，未开放；
      // 第 3 参（电脑麦克风）跟随界面开关；第 7 参（logcat 级别）固定 null ——
      // 录屏配套 logcat 一律全量抓取，不做级别过滤。
      setRecInFlight(true);
      if (els.toolRec) els.toolRec.title = "正在启动录屏，请稍候…";
      /* 多台设备要各自拉起 screenrecord 并确认它真的活着（每台约 1.5 秒，
         已并行化），这段时间界面除了按钮变灰没有任何动静，用户很容易以为
         点空了又去点第二次。先落一条状态，说明正在进行什么。 */
      pushStatus("info", "▶ 正在启动录屏…");
      let res = null;
      try {
        res = await callApi(api.screen_record_start(
          null, false, !!(els.recMic && els.recMic.checked), saveDir(),
          els.recLogcat.checked, els.recZip.checked, null,
          !!els.recPointerLocation.checked, !!els.recShowTouches.checked));
      } finally {
        setRecInFlight(false);
        if (els.toolRec) els.toolRec.title = "";
      }
      if (!res || res.ok === false) {
        /* 后端在全部设备启动失败时会自动撤销会话残留并返回 ok:false；
           这里回滚按钮态，避免 UI 卡在“录制中”却没有任何会话可停。
           原因优先用后端给的 message（人话）。reason 是机器码
           （recording / no_device / start_failed …）：直接拼给用户就是
           「⚠ 录屏未能启动（recording）」，既看不懂又说不出下一步；
           而这些分支后端都已各自播报过一句人话，故不再重复贴代码。 */
        const why = res && res.message;
        pushStatus("err", "⚠ 录屏未能启动" + (why ? "：" + why : ""));
        setRecRunning(false);
        return;
      }
      setRecRunning(true, res && res.started);
    });
    els.toolRecStop.addEventListener("click", async () => {
      if (recInFlight) return;      // 停止在途：收尾（转码 / 打包）要十几秒，防连点
      setRecInFlight(true);
      // 冻结在「点下去」这一刻：后面是十几秒收尾，数字不该继续往上走
      recElapsedFreeze();
      if (els.toolRecStop) els.toolRecStop.title = "正在停止录屏并收尾，请稍候…";
      /* 收尾是「停设备端 → 等 moov 写完 → 拉视频 → 合成 → 打包」，几秒起步；
         这期间调用还没返回，按钮已禁用，界面若一句话都没有，用户会以为点空了。 */
      pushStatus("info", "⏹ 正在停止录屏并收尾（停止设备端 → 拉取视频 → 打包），请稍候…");
      let res = null;
      try {
        /* timeout=0：收尾链路是「停设备端 → 等写回 moov → 拉视频 → ffmpeg 合并
           → 打包 zip」，多段大视频 + 慢 USB 时远超 15 秒。默认超时会让前端先报
           一条「请求超时（15s）」的假失败（后端其实还在跑、最终会成功），还会
           提前解锁按钮 —— 此时用户再点「开始录制」会撞上后端还没清完的会话。
           后端全程通过事件总线推送各阶段进度（拉取 / 合并 / 打包），且整条链路
           各步都有界（moov 等待、pull 重试、ffmpeg 自身退出），promise 一定会
           落定，禁用超时不会挂死 UI。 */
        res = await callApi(api.screen_record_stop(), 0);
      } finally {
        setRecInFlight(false);
        if (els.toolRecStop) els.toolRecStop.title = "";
      }
      if (res && res.ok === false && res.message) {
        /* 同样只认 message：reason 是机器码。no_session（后端已用 info 说明
           「当前没有进行中的录屏」）刻意不带 message —— 它不算失败，不该
           再弹一条 err toast 把「已经停了」说成「停止失败」。 */
        pushStatus("err", "⚠ 停止录屏失败：" + res.message);
      }
      setRecRunning(false);
    });
    /* 取消录制：停止并删除本次已产生的文件（不合并、不打包）。
       为什么要有它：录错了（选错设备 / 场景不对 / 只是点错了「开始」）时，
       以前唯一的出口是「停止录制」——那会把几段合成、打包、再告诉你「已完成」，
       用户得自己进目录一个个删。取消 = 这次的东西一个都不留。
       与「停止录制」紧挨着，误点一次就等于把刚录的东西删掉且没有回收站，
       所以必须先过一道二次确认（应用内弹窗，不用 window.confirm，见 askConfirm）。 */
    if (els.toolRecCancel) {
      els.toolRecCancel.addEventListener("click", async () => {
        if (recInFlight) return;
        const yes = await askConfirm({
          title: "取消本次录制？",
          text: "本次已经录到的内容会被删除，且无法恢复：\n"
            + "· 视频分段（含已自动拉回本地的段）\n"
            + "· 同步抓取的 logcat\n"
            + "· 麦克风录音（若开了）\n\n"
            + "不合并、不打包，保存目录里不会留下本次的任何文件。\n"
            + "想保留已经录到的内容，请点「停止录制」。",
          yes: "是，全部删除",
          no: "否，保留",
          danger: true,
        });
        if (!yes) return;
        /* 弹窗开着的这几秒里，录制可能已经自己结束了（设备拔线 / 进程死亡 /
           触摸到 20 段上限，后端都会广播 running=false 并把按钮置灰）。
           此时再往后端要「取消」只会拿到 no_session，还会被这里报成
           「取消录屏失败」，用户看着一句莫名其妙的失败提示发懵。
           状态栏本来就已经由后端说明过，这里只需安静收手。 */
        if (recInFlight) return;
        if (els.toolRecCancel && els.toolRecCancel.disabled) {
          pushStatus("info", "ℹ 录制已经结束，没有需要取消的内容");
          return;
        }
        setRecInFlight(true);
        recElapsedFreeze();
        if (els.toolRecCancel) els.toolRecCancel.title = "正在停止设备端录制并删除文件…";
        /* 取消要「停设备端 → 等拉取收尾 → 删文件」，几秒起步；期间按钮全灰，
           没有一句话用户会以为点空了。 */
        pushStatus("info", "🗑 正在取消录制并删除本次产生的文件…");
        let res = null;
        try {
          /* timeout=0：与「停止录制」同理 —— 取消也要「停设备端（等 moov）→
             删文件」，多设备逐台收尾可能超 15 秒；后端有界且会推进度事件，
             禁用超时避免假失败 + 提前解锁按钮。 */
          res = await callApi(api.screen_record_cancel(), 0);
        } finally {
          setRecInFlight(false);
          if (els.toolRecCancel) {
            els.toolRecCancel.title = "取消本次录制：停止并删除刚录到的文件，不合并、不打包";
          }
        }
        if (res && res.ok === false && res.reason !== "no_session") {
          /* 只认 message（reason 是机器码）；no_session 不算失败 —— 后端已用
             info 说明「当前没有进行中的录屏」，再说成「取消失败」纯属误导。 */
          pushStatus("err", "⚠ 取消录屏失败："
            + (res.message || res.reason || "未知原因")
            + "；本次产物可能仍有残留，请检查保存目录");
        }
        // 无论成败都回到「未录制」：后端在 finally 里已经清掉会话，
        // 界面若还停在「录制中」，用户点停止只会得到 no_session。
        setRecRunning(false);
      });
    }
    // 保存目录（工具 / Logcat / 文件 三处输入共享）：任一输入实时镜像到另两处，
    // 失焦/回车时写入 settings.json（下次启动 default_save_dir 直接用它）。
    [els.toolDir, els.lcDir, els.fileDir].forEach((el) => {
      el.addEventListener("input", () => {
        const v = el.value;
        [els.toolDir, els.lcDir, els.fileDir].forEach((o) => {
          if (o && o !== el && o.value !== v) o.value = v;
        });
      });
      el.addEventListener("change", async () => {
        const dir = (el.value || "").trim();
        setSaveDirInputs(dir);
        const res = await callApi(api.save_settings({ save_dir: dir }));
        // 后端会回报「本机实际生效的目录」：用户填了一个本机不存在的路径时
        // 必须立刻说清已改用默认目录，而不是等下次截图失败才发现。
        // 配置文件里的原值保持不动（那是源机器上的正确路径）。
        const note = res && res.settings && res.settings._save_dir_note;
        if (note) {
          pushStatus("warn", "⚠ " + note);
        } else if (res && res.settings && res.settings._save_dir_effective) {
          pushStatus("ok", "✓ 保存目录已生效：" + res.settings._save_dir_effective);
        }
      });
    });
    // 关于页「打开目录」：打开 config.json 所在目录，用户直接拷走该文件
    // 即可在另一台电脑同步全部设置。
    if (els.aboutConfigOpen) {
      els.aboutConfigOpen.addEventListener("click", () => {
        const p = (els.aboutConfigPath && els.aboutConfigPath.textContent) || "";
        // 只取目录部分：路径形如 C:\...\config.json
        const dir = p.replace(/[\\/][^\\/]*$/, "");
        if (!dir || dir === p) {
          pushStatus("warn", "⚠ 配置文件位置未知，无法打开目录");
          return;
        }
        callApi(api.open_save_dir(dir));
      });
    }
    // 关于页 adb 目录保存：改配置立即注入 PATH 并回测可用性
    els.aboutAdbSave.addEventListener("click", async () => {
      const dir = (els.aboutAdbDir.value || "").trim();
      const res = await callApi(api.save_settings({ adb_dir: dir }));
      const adbRes = await callApi(api.adb_status());
      const ok = !!(res && res.ok);
      els.aboutAdbDir.classList.toggle("err", !ok);
      if (adbRes) {
        els.aboutAdb.textContent = adbRes.ok ? (adbRes.version || adbRes.path || "adb") : "adb 未就绪（未在 PATH 中找到）";
        els.aboutAdbDir.classList.toggle("err", !adbRes.ok);
      }
      pushStatus(ok ? "ok" : "err",
        ok ? (adbRes && adbRes.ok ? "✓ 已保存 adb 目录，adb 可用了" : "已保存（但未检测到可用的 adb）")
           : "保存失败，请检查目录可写");
      // 目录配好后立即用新 PATH 刷新一次设备列表
      if (ok && adbRes && adbRes.ok) callApi(api.refresh_devices());
    });
    // 关于页「命令超时保护」：数字输入框失焦时即时持久化（0~3600 秒）。
    // 非法值（空 / 负数 / 非数字）交给后端 sanitize_prefs 回退默认 0，
    // 前端只做基本夹取保证 UI 一致显示。
    if (els.aboutCmdTimeout) {
      els.aboutCmdTimeout.addEventListener("blur", () => {
        const raw = els.aboutCmdTimeout.value || "";
        let v = parseInt(raw, 10);
        if (!Number.isFinite(v) || v < 0) v = 0;
        if (v > 3600) v = 3600;
        els.aboutCmdTimeout.value = String(v);
        persistPref("cmd_timeout", v);
        if (v === 0) {
          pushStatus("ok", "✓ 命令超时保护已关闭（0 = 不限制）");
        } else {
          pushStatus("ok", "✓ 命令超时保护已设为 " + v + " 秒");
        }
      });
      // 回车即保存（和其他输入框交互一致）
      els.aboutCmdTimeout.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); els.aboutCmdTimeout.blur(); }
      });
    }
    // ---- 版本更新（关于页一行 + 新版本弹窗）----
    if (els.aboutUpdateCheck) els.aboutUpdateCheck.addEventListener("click", checkUpdateManual);
    if (els.aboutUpdateAuto) {
      els.aboutUpdateAuto.addEventListener("change", () => {
        // 关掉只是「别自动打扰我」：手动「检查」按钮仍然可用（后端也是这么分的）
        persistPref("update_check", !!els.aboutUpdateAuto.checked);
      });
    }
    if (els.updateClose) els.updateClose.addEventListener("click", hideUpdateModal);
    if (els.updateLater) els.updateLater.addEventListener("click", hideUpdateModal);
    // ---- 关于页子 tab（概览 / 使用说明）----
    bindAboutSubtabs();
    if (els.updateDownload) {
      els.updateDownload.addEventListener("click", () => {
        const url = updateShown && updateShown.url;
        if (!url) {
          pushStatus("warn", "⚠ 这个版本没有提供下载地址，请到仓库的 Releases 页面手动取包");
          return;
        }
        callApi(api.update_open(url));
        hideUpdateModal();
      });
    }
    if (els.updateSkip) {
      els.updateSkip.addEventListener("click", () => {
        const v = updateShown && updateShown.version;
        if (v) callApi(api.update_skip(v));
        hideUpdateModal();
      });
    }
    // files
    els.fileUp.addEventListener("click", () => {
      if (!fileSerial) return pushStatus("warn", "请先勾选设备");
      els.filePath.value = dirOf(filePath); gotoPath();
    });
    els.fileRefresh.addEventListener("click", () => {
      if (!fileSerial) return pushStatus("warn", "请先勾选设备");
      gotoPath();
    });
    els.filePath.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        if (!fileSerial) return pushStatus("warn", "请先勾选设备");
        gotoPath();
      }
    });
    els.fileMkdir.addEventListener("click", () => {
      if (!fileSerial) return pushStatus("warn", "请先勾选设备");
      // 自绘输入框（window.prompt 在 pywebview 部分版本里返回 null，点了没反应）
      askInput({ title: "新建文件夹", label: "文件夹名称：", ok: "创建",
                 hint: "建在当前目录 " + filePath + " 下" }).then((n) => {
        if (n === null) return;
        const v = validateEntryName(n);
        if (!v.ok) { if (v.why) pushStatus("err", "⚠ " + v.why); return; }
        callApi(api.file_mkdir(fileSerial, filePath.replace(/\/$/, "") + "/" + v.name));
      });
    });
    els.fileTouch.addEventListener("click", () => {
      if (!fileSerial) return pushStatus("warn", "请先勾选设备");
      askInput({ title: "新建文件", label: "文件名称：", ok: "创建",
                 hint: "建在当前目录 " + filePath + " 下（内容为空）" }).then((n) => {
        if (n === null) return;
        const v = validateEntryName(n);
        if (!v.ok) { if (v.why) pushStatus("err", "⚠ " + v.why); return; }
        callApi(api.file_touch(fileSerial, filePath.replace(/\/$/, "") + "/" + v.name));
      });
    });
    els.fileUpload.addEventListener("change", (e) => {
      uploadFiles(e.target.files);
      e.target.value = "";   // 允许重复上传同名文件
    });
    // 文件批量操作：全选 / 下载选中 / 删除选中
    els.fileSelAll.addEventListener("change", () => {
      document.querySelectorAll("#file-body .file-check").forEach((c) => { c.checked = els.fileSelAll.checked; });
      updateFileSel();
    });
    // 行级交互（进目录 / 切换选中 / 行内按钮）全部委托在 #file-body 上，
    // 一次绑定服务所有行 —— 见 renderFileEntries 的说明。
    bindFileBodyEvents();
    // 文件区拖拽上传：拖入显示遮罩，松手把文件上传到当前目录（与「上传」按钮共用 uploadFiles）
    const dz = els.fileTableWrap;
    if (dz) {
      ["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => {
        if (!e.dataTransfer || !Array.from(e.dataTransfer.types || []).includes("Files")) return;
        e.preventDefault(); e.stopPropagation();
        els.fileDropOverlay.classList.add("show");
      }));
      dz.addEventListener("dragleave", (e) => {
        e.preventDefault(); e.stopPropagation();
        if (!dz.contains(e.relatedTarget)) els.fileDropOverlay.classList.remove("show");
      });
      dz.addEventListener("drop", (e) => {
        e.preventDefault(); e.stopPropagation();
        els.fileDropOverlay.classList.remove("show");
        const dt = e.dataTransfer;
        if (dt && dt.files && dt.files.length) uploadFiles(dt.files);
      });
    }
    els.fileBatchDl.addEventListener("click", () => {
      const paths = fileCheckedPaths();
      if (!paths.length) return;
      if (!fileSerial) return pushStatus("warn", "请先勾选设备");
      const dir = saveDir();
      els.fileBatchDl.disabled = true;
      markBtnBusy(els.fileBatchDl, true);
      Promise.all(paths.map((p) => callApi(api.file_download(fileSerial, p, dir)))).then(() => {
        markBtnBusy(els.fileBatchDl, false);
        updateFileSel();   // 按当前勾选数恢复可用性
      });
      pushStatus("info", "已发起下载 " + paths.length + " 个文件" + (dir ? " 到 " + dir : ""));
    });
    els.fileBatchDel.addEventListener("click", () => {
      const paths = fileCheckedPaths();
      if (!paths.length) return;
      if (!fileSerial) return pushStatus("warn", "请先勾选设备");
      // 自绘确认：pywebview 部分版本里 confirm 返回 undefined → `!confirm(...)`
      // 恒为 true，批量删除（不可恢复）会**跳过确认直接执行**。
      // 确认框里列出要删哪些，比一句笼统的「确定删 3 个项」有用得多。
      const preview = paths.slice(0, 8).join("\n")
        + (paths.length > 8 ? "\n…（共 " + paths.length + " 项）" : "");
      askConfirm({ title: "批量删除",
                   text: "确定删除选中的 " + paths.length + " 个项？此操作不可恢复。\n" + preview,
                   yes: "删除", danger: true }).then((yes) => {
        if (!yes) return;
        els.fileBatchDel.disabled = true;
        markBtnBusy(els.fileBatchDel, true);
        Promise.resolve(callApi(api.file_remove(fileSerial, paths))).then(() => {
          markBtnBusy(els.fileBatchDel, false);
          updateFileSel();
        });
      });
    });
    // modal
    els.modalClose.addEventListener("click", () => els.modal.classList.add("hidden"));
    // 状态信息：顶栏跑马灯点击展开全量历史。×/ESC/点背景都能关——它是随时可回看的
    // 监控面板，比内容弹窗更常用，误开之后必须能零成本关掉。
    els.statusTicker.addEventListener("click", openStatusModal);
    els.statusModalClose.addEventListener("click", closeStatusModal);
    els.statusModal.addEventListener("click", (e) => {
      if (e.target === els.statusModal) closeStatusModal();
    });
    /* 二次确认弹窗：四个出口（否 / × / 遮罩 / Esc）全部收成「否」，
       只有点「是」才 resolve(true)。 */
    if (els.confirmModal) {
      els.confirmYes.addEventListener("click", () => settleConfirm(true));
      els.confirmNo.addEventListener("click", () => settleConfirm(false));
      if (els.confirmX) els.confirmX.addEventListener("click", () => settleConfirm(false));
      // 点遮罩（弹窗自身而不是那块白框）= 否：误点一下空白不该等于「确认删除」。
      els.confirmModal.addEventListener("click", (e) => {
        if (e.target === els.confirmModal) settleConfirm(false);
      });
    }
    /* 输入弹窗：出口同确认弹窗（取消 / × / 遮罩 / Esc 一律 null），
       另外「确定」也可用回车提交（输入框里敲回车是最顺手的动作）。 */
    if (els.inputModal) {
      els.inputYes.addEventListener("click", () => settleInput(true));
      els.inputNo.addEventListener("click", () => settleInput(false));
      if (els.inputX) els.inputX.addEventListener("click", () => settleInput(false));
      els.inputModal.addEventListener("click", (e) => {
        if (e.target === els.inputModal) settleInput(false);
      });
      if (els.inputField) {
        els.inputField.addEventListener("keydown", (e) => {
          if (e.key === "Enter") { e.preventDefault(); settleInput(true); }
        });
      }
    }
    /* 关键告警弹窗：四个出口都只是「知道了」，不做任何动作 —— 它只负责让用户
       真的看见一次。唯一有副作用的是「查看状态信息」：先把弹窗关掉再开状态
       面板，两层弹窗叠着会让人以为面板被弹窗盖住了（它确实会被盖住）。 */
    if (els.alertModal) {
      if (els.alertOk) els.alertOk.addEventListener("click", closeAlert);
      if (els.alertX) els.alertX.addEventListener("click", closeAlert);
      els.alertModal.addEventListener("click", (e) => {
        if (e.target === els.alertModal) closeAlert();
      });
      if (els.alertMore) {
        els.alertMore.addEventListener("click", () => {
          closeAlert();
          openStatusModal();
        });
      }
    }
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      // 关键告警弹窗在最上层（z-index 最高）：Esc 只关它，不能顺手把底下的
      // 确认框 / 状态面板一起关掉 —— 那会让用户以为「按 Esc 拒绝了删除」，
      // 而实际上那个确认框被悄悄回答了。
      if (alertOpen()) { e.preventDefault(); closeAlert(); return; }
      // 输入弹窗最优先：它开着时 Esc 只关它。输入弹窗与确认弹窗不会同时开，
      // 但顺序仍按「后开的在上面」写，免得将来叠用时关错那一层。
      if (els.inputModal && !els.inputModal.classList.contains("hidden")) {
        e.preventDefault();
        settleInput(false);
        return;
      }
      // 确认弹窗次之：它开着的时候，Esc 只回答这个弹窗（= 否）。
      // 不能顺带把背后的状态面板也关掉 —— 用户会以为「Esc 关掉了删除确认」，
      // 直到下次想看状态才发现那个窗口也没了。
      if (els.confirmModal && !els.confirmModal.classList.contains("hidden")) {
        e.preventDefault();
        settleConfirm(false);
        return;
      }
      if (!els.statusModal.classList.contains("hidden")) { closeStatusModal(); return; }
      // 无线调试 / 设备信息：同样是「点开就想随手关掉」的查看类弹窗
      if (els.wifiModal && !els.wifiModal.classList.contains("hidden")) { wifiClose(); return; }
      if (els.devinfoModal && !els.devinfoModal.classList.contains("hidden")) closeDevInfo();
    });
    // Tab 焦点圈在确认 / 输入弹窗内（与上面那条 Escape 分开：那条一进来就把非 Esc 滤掉了）
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Tab") return;
      if (alertOpen()) { trapAlertTab(e); return; }
      if (els.inputModal && !els.inputModal.classList.contains("hidden")) { trapInputTab(e); return; }
      trapConfirmTab(e);
    });
    // 大文件「查看」：直接调系统默认程序打开已拉取到本地的临时文件
    els.modalOpenLocal.addEventListener("click", () => {
      if (!modalLocalPath) return;
      callApi(api.open_local_file(modalLocalPath));
    });
    // 可拖动分隔条：设备栏（最小 200px，右侧内容至少留 480px）。
    // 指令台分隔条由 bindWorkspace 按工作区各绑一份（含默认工作区），这里不再
    // 重复绑定——多绑一份会在拖动时写两次宽度、并在 _splitters 里留下重复记录。
    bindSplitter(els.sidebarSplitter, els.deviceSidebar, 200, 480);
    // 设备栏收起 / 展开：状态落盘 sidebar_collapsed，重启后由 applyBootSettings 恢复
    if (els.sidebarCollapseBtn) {
      els.sidebarCollapseBtn.addEventListener("click", () => {
        applySidebarCollapsed(!sidebarCollapsed());
      });
    }
    // 收起态下整条窄轨都是「展开」热区：点空白 / 徽章 / 竖排标签都能展开
    // （窄轨里没有其他可点目标，整轨即按钮的延伸）。关键约束：落在按钮上的
    // 点击必须跳过——点 « 收起时按钮处理器先执行，事件再冒泡到本委托，若不
    // 跳过就会立刻又被展开，表现为「怎么也收不起来」。
    if (els.deviceSidebar) {
      els.deviceSidebar.addEventListener("click", (e) => {
        if (!sidebarCollapsed()) return;
        if (clickOnButton(e)) return;
        applySidebarCollapsed(false);
      });
    }
    // 窗口缩放动态适配：把拖出过的内联宽度按新的可见宽度重钳，
    // 避免窗口变小后左面板仍握旧宽把右侧内容顶出屏幕
    window.addEventListener("resize", reclampSplitters);
    // 窗口尺寸变化时性能曲线要重算像素尺寸（canvas 位图不会自动跟着 CSS 拉伸，
    // 不重画会变模糊或被裁切）。
    window.addEventListener("resize", queuePerfDraw);
  }

  function firstSelected() { return firstChecked(); }
  // 当前选中的 logcat 缓冲区名列表。优先读 booted 下发的 option dataset
  // （后端单一数据源），没有时回退内置静态映射（保持启动瞬间可用）。
  function buffers() {
    const opt = els.lcBuf && els.lcBuf.selectedOptions
      ? els.lcBuf.selectedOptions[0] : null;
    if (opt && opt.dataset && opt.dataset.values) {
      try { return JSON.parse(opt.dataset.values); } catch (e) { /* 落到回退 */ }
    }
    const fallback = {
      "main（主日志）": ["main"], "system（系统）": ["system"],
      "events（事件）": ["events"], "crash（崩溃）": ["crash"],
      "全部（main+system+events+crash）": ["main", "system", "events", "crash"],
    };
    return (els.lcBuf && fallback[els.lcBuf.value]) || ["main"];
  }
  // 保存目录三处输入（工具 / Logcat / 文件）共享同一值：其一变更即同步其余两处。
  function setSaveDirInputs(value) {
    [els.toolDir, els.lcDir, els.fileDir].forEach((el) => {
      if (el && el.value !== value) el.value = value;
    });
  }
  function saveDir() { return (els.toolDir.value || "").trim() || undefined; }
  function startLc() {
    // 重新开监控：立刻清掉上一轮的视图与计数，不等首帧回来才刷新
    els.lcView.innerHTML = "";
    clearLcQueue();
    // 同时丢弃上一轮的日志缓冲：否则新会话的 append 会接在旧 lines 数组尾部，
    // 一旦触发重渲染（改级别 / 关键字 / 仅异常），上一轮的日志会重新冒出来
    // （视图已清空，缓冲却还留着旧行）。
    if (lcSerial) lcBuffers[lcSerial] = { lines: [], total: 0, exc: 0 };
    updateLcCounter(null);
    // 返回 Promise：调用方据此判断后端是否真的启动了（失败要回滚按钮态）
    // 注意：关键字只在前端做即时过滤（见 linePassesFilter / renderLogcat），
    // 不再下发给后端 logcat_start。原因：后端按「启动那一刻」的关键字预过滤后，
    // 缓冲里只剩当时命中的行 —— 之后改关键字只能越缩越窄、清掉关键字也回不来，
    // 正是用户反映「输入账号绑定下方不显示」的根因之一。后端只按级别 + 仅异常
    // 预过滤（这俩是流量闸门，仍需要它控制总线体量）；关键字交给前端对完整
    // 缓冲做实时过滤，既能搜到较早被裁剪出视图的行，也能在清空后还原全部。
    return callApi(api.logcat_start(lcSerial, buffers(),
      Array.from(els.lcLevels.querySelectorAll("input:checked")).map((c) => c.value),
      "", els.lcOnlyExc.checked));
  }

  /* ---------------- 状态信息选中复制 ----------------
     优先复制用户在状态信息区（弹窗内的 #status）框选的文本；无选区则复制全部状态文本。
     WebView2 下 navigator.clipboard 可能不可用，回退 execCommand('copy')。 */
  function copyStatus() {
    const text = getStatusSelectionOrAll();
    if (!text) { flashCopy(false); return; }
    copyToClipboard(text);
  }
  function getStatusSelectionOrAll() {
    const sel = window.getSelection && window.getSelection();
    const text = sel ? sel.toString() : "";
    if (text && sel.anchorNode && els.status.contains(sel.anchorNode)) return text;
    const lines = els.status.querySelectorAll(".line");
    if (!lines.length) return "";
    return Array.from(lines).map((d) => d.textContent).join("\n");
  }
  function copyToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(() => flashCopy(true))
        .catch(() => fallbackCopy(text));
    } else {
      fallbackCopy(text);
    }
  }
  function fallbackCopy(text) {
    try {
      const ta = document.createElement("textarea");
      ta.value = text; ta.style.position = "fixed"; ta.style.top = "-1000px";
      document.body.appendChild(ta); ta.focus(); ta.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      flashCopy(ok);
    } catch (e) { flashCopy(false); }
  }
  // 「复制」提示的连点保护：同一个按钮只维护一个计时器与一份原文案。
  // 旧实现每次点击都重新记住「当前文案」当作原文案 —— 第二次点击会把「已复制」
  // 记成原文案，其计时器又在第一次的计时器之后恢复，按钮就永久停在「已复制」。
  let copyFlashTimer = null;
  let copyFlashOrig = null;
  function flashCopy(ok) {
    const b = els.btnCopyStatus;
    if (!b) return;
    if (copyFlashTimer === null) {
      copyFlashOrig = b.textContent;   // 只在没有进行中的提示时记录原文案
    } else {
      clearTimeout(copyFlashTimer);    // 连点：复用同一个计时器，不重复记录
    }
    b.textContent = ok ? "已复制" : "复制失败";
    copyFlashTimer = setTimeout(() => {
      copyFlashTimer = null;
      b.textContent = copyFlashOrig;
      copyFlashOrig = null;
    }, 1200);
  }

  // 脚本位于 body 末尾，此时静态 DOM 已就绪，直接给按钮补图标（幂等，可安全重跑）
  decorateIcons(document);

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else { start(); }
})();
