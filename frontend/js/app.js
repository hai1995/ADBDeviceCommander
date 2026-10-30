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
    // logcat
    lcStart: $("lc-start"), lcStop: $("lc-stop"),
    lcClear: $("lc-clear"), lcSave: $("lc-save"), lcStatus: $("lc-status"),
    lcCounter: $("lc-counter"), lcDev: $("lc-dev"), lcFilter: $("lc-filter"),
    lcLevels: $("lc-levels"), lcOnlyExc: $("lc-only-exc"),
    lcAuto: $("lc-autoscroll"), lcBuf: $("lc-buf"), lcView: $("lc-view"),
    lcCapZipstop: $("lc-cap-zipstop"),
    lcCapStart: $("lc-cap-start"), lcCapStop: $("lc-cap-stop"),
    lcCapStatus: $("lc-cap-status"), lcCapLevels: $("lc-cap-levels"),
    lcDir: $("lc-dir"), lcOpen: $("lc-open"),
    // tools
    toolDir: $("tool-dir"), toolOpen: $("tool-open"),
    toolShot: $("tool-shot"), shotClipboard: $("shot-clipboard"),
    toolRec: $("tool-rec"),
    toolRecStop: $("tool-rec-stop"),
    recLogcat: $("rec-logcat"), recZip: $("rec-zip"),
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
    // 工具卡折叠（开关项太多、占屏太高，标题栏单击收起）：三张卡各一套
    shotCard: $("shot-card"), shotToggle: $("shot-toggle"),
    recCard: $("rec-card"), recToggle: $("rec-toggle"),
    apkCard: $("apk-card"), apkToggle: $("apk-toggle"),
    diagCard: $("diag-card"), diagToggle: $("diag-toggle"),
    scrcpyCard: $("scrcpy-card"), scrcpyToggle: $("scrcpy-toggle"),
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
    fileBody: $("file-body"),
    fileDir: $("file-dir"), fileOpen: $("file-open"),
    fileSelAll: $("file-sel-all"), fileBatchDl: $("file-batch-dl"),
    fileBatchDel: $("file-batch-del"), fileSelCount: $("file-sel-count"),
    fileTableWrap: $("file-table-wrap"), fileDropOverlay: $("file-drop-overlay"),
    // about
    aboutVer: $("about-ver"), aboutAdb: $("about-adb"),
    aboutCmd: $("about-cmd"), aboutDev: $("about-dev"), aboutWarn: $("about-warn"),
    aboutAdbDir: $("about-adb-dir"), aboutAdbSave: $("about-adb-save"),
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
    // modal
    modal: $("modal"), modalTitle: $("modal-title"),
    modalBody: $("modal-body"), modalClose: $("modal-close"),
    modalOpenLocal: $("modal-open-local"),
    // 命令编辑弹窗
    cmdEdit: $("cmd-edit-modal"),
    cmdEditModal: $("cmd-edit-modal"), cmdEditTitle: $("cmd-edit-title"),
    cmdEditName: $("cmd-edit-name"), cmdEditLabels: $("cmd-edit-labels"),
    cmdEditCmds: $("cmd-edit-cmds"), cmdEditInputOnly: $("cmd-edit-inputonly"),
    cmdEditSave: $("cmd-edit-save"), cmdEditCancel: $("cmd-edit-cancel"),
    cmdEditClose: $("cmd-edit-close"), cmdEditDelete: $("cmd-edit-delete"),
    cmdNew: $("btn-cmd-new"),
    cmdImport: $("btn-cmd-import"), cmdImportFile: $("cmd-import-file"),
    cmdExport: $("btn-cmd-export"),
    cmdExportModal: $("cmd-export-modal"), cmdExportText: $("cmd-export-text"),
    cmdExportCopy: $("cmd-export-copy"), cmdExportSave: $("cmd-export-save"),
    cmdExportClose: $("cmd-export-close"), cmdExportClose2: $("cmd-export-close2"),
    // 可拖动分隔条（设备栏 / 指令台 ↔ 指令输出）
    sidebarSplitter: $("sidebar-splitter"), deviceSidebar: $("device-sidebar"),
    sidebarCollapseBtn: $("btn-sidebar-collapse"),
    cmdSplitter: $("cmd-splitter"), cmdPanelLeft: $("cmd-panel-left"),
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
  let lcCapSerial = null;        // 正在抓取的设备（与 lcSerial 解耦：抓取期间
                                 // 改勾选不会停错设备，也不会停不下来）
  let fileSerial = null;            // 当前文件浏览设备
  let filePath = "/";
  let fileAnchor = null;            // 批量选择的锚点（Shift 区间选择的起点，值为复选框 value）
  let modalLocalPath = null;        // 查看弹窗里已拉取到本地的文件路径（「查看」按钮用）
  let allCommands = [];             // 全量快捷命令（供筛选/标签过滤使用）
  let selectedTags = new Set();     // 当前已选中的标签（多选 OR）
  let mirrorFrameUrl = "";          // 低帧率预览的帧地址（非空 = 预览在跑）
  let mirrorTimer = null;           // 低帧率预览的刷新定时器

  /* ---------------- 按钮图标（统一内联 SVG，跟随 currentColor 适配主题） ----------------
     图标集中在此一处定义，HTML 上只需给按钮加 data-icon="名字"，脚本启动时注入；
     好处：几十个按钮不必各写一大段内联 SVG，线条风格（24 网格 / 2px 描边 / 圆角端点）
     统一，也方便随时增删。目录 / 文件表格里动态生成的按钮走 mkAct(text, fn, icon)
     复用同一套图标。SVG 无文本，注入后按钮 textContent 仍是原标签文字，不影响既有断言。 */
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
  const pushConsole = (kind, text) =>
    pushLine(els.console, text, CONSOLE_KINDS[kind] || "", true);

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

  async function callApi(promise) {
    try { return await promise; }
    catch (e) {
      pushStatus("err", "调用后端失败：" + (e && e.message ? e.message : e));
      return null;
    }
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
      case "console":
        if (p.kind === "clear") clearOut(els.console);
        else pushConsole(p.kind, p.text || "");
        break;
      case "status":
        if (p.type === "clear") clearStatus();
        else pushStatus(p.type, p.text || "", p.toast ? { toast: true } : undefined);
        break;
      case "tool":
        if (p.type === "clear") clearStatus();
        else if (["ok", "info", "err", "warn"].includes(p.type))
          pushStatus(p.type, p.text || "", p.toast ? { toast: true } : undefined);
        else if (p.type === "diag" && p.path) {
          // 诊断包产物：卡片里留一行指向结果 —— 状态栏/toast 会被后面的消息刷走，
          // 而「刚才那个包到底存哪了」是紧接着要用的信息。
          if (els.diagResult) {
            els.diagResult.textContent = String(p.path).split(/[\\/]/).pop() || p.path;
            els.diagResult.title = p.path;
            els.diagResult.classList.remove("dim");
          }
        }
        break;
      case "stop_state": els.btnStop.disabled = !p.running; break;
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
    // 保存目录默认值向后端索取（单一数据源，避免前后端两份公式漂移）。
    // 浏览器里没有 process / 环境变量，前端绝不自行拼接路径；取不到就留空，
    // 后端会用同一份默认目录兜底。
    await initSaveDirDefault();
    const res = await callApi(api.boot());
    if (res && res.ok === false && res.reason === "shutting_down") {
      setPill("已退出", "err"); return;
    }
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
        const events = await callApi(api.take_events());
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
    setTimeout(() => { if (!booted) setPill("未就绪", "err"); }, 5000);
  }

  /* 保存目录默认值：来自后端 WebApi.default_save_dir（= 后端 _default_save_dir），
     与截图/录屏/下载实际写入的位置严格同源。失败时静默留空，不打扰用户。 */
  async function initSaveDirDefault() {
    if (els.toolDir.value) return;
    let dir = "";
    try {
      if (api && api.default_save_dir) {
        const r = await api.default_save_dir();
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
    if (typeof s.save_dir === "string" && s.save_dir) setSaveDirInputs(s.save_dir);
    if (typeof s.adb_dir === "string") els.aboutAdbDir.value = s.adb_dir;
    // 缺省不写就保持 HTML 的默认勾选（默认开启）；用户显式设过值则以设置为准
    if (els.shotClipboard && typeof s.shot_to_clipboard === "boolean") {
      els.shotClipboard.checked = s.shot_to_clipboard;
    }
    if (els.keepInput && typeof s.keep_input === "boolean") {
      els.keepInput.checked = s.keep_input;
    }
    // 指令台搜索关键字：恢复后立即重跑一次过滤，界面与实际过滤结果一致
    if (els.cmdFilter && typeof s.cmd_filter === "string" && s.cmd_filter) {
      els.cmdFilter.value = s.cmd_filter;
      applyCmdFilter();
    }
    // 指令卡手动排序（拖动后落盘）：必须在 renderCommands 之前读进来，
    // 否则首屏按点击频次排完、再被重排一次，用户会看到卡片跳一下。
    if (typeof s.cmd_order === "string") loadCmdOrder(s.cmd_order);
    // 内置二级分组的折叠状态：同样要在 renderCommands 之前读进来，否则首屏
    // 全展开、紧随其后又折回去，用户会看到指令区抽动一下。
    if (typeof s.builtin_folded === "string") {
      builtinFolded = new Set(s.builtin_folded.split(",")
        .map((x) => x.trim()).filter(Boolean));
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
    if (els.recZip && typeof s.rec_zip === "boolean") els.recZip.checked = s.rec_zip;
    if (els.recPointerLocation && typeof s.rec_pointer_location === "boolean") {
      els.recPointerLocation.checked = s.rec_pointer_location;
    }
    if (els.recShowTouches && typeof s.rec_show_touches === "boolean") {
      els.recShowTouches.checked = s.rec_show_touches;
    }
    // 四张工具卡的收起态（布局偏好）：缺省 / 非布尔 → 保持 HTML 的展开态
    TOOL_CARDS.forEach((d) => {
      if (typeof s[d.key] === "boolean") setToolCollapsed(d.key, s[d.key], false);
    });
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
    // 计数只写数字，「台」是独立的 .count-unit span：收起态下 CSS 把它藏掉，
    // 窄轨里只剩等宽数字徽章；展开态两者合起来仍是「N 台」。0 台时单位
    // 一并隐藏，避免徽章空了还挂个「台」字。
    els.devCount.textContent = devices.length ? String(devices.length) : "";
    if (els.devCountUnit) els.devCountUnit.hidden = devices.length === 0;
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
      if (next !== lcSerial) { lcSerial = next; renderLogcat(); }
    }
    syncToolButtons();
    // 抓取开始按钮：不在抓取中且至少有一个受控设备时可点（与监控按钮解耦）
    els.lcCapStart.disabled = lcCapRunning || !checkedDevices().length;
  }

  async function toggleDevice(serial, on) {
    const res = await callApi(api.toggle_device(serial, on));
    if (res && res.ok === false) pushStatus("warn", "⚠ 设备不可操作：" + serial);
  }

  /* ---------------- 指令区（含筛选 + 标签过滤） ---------------- */
  function renderCommands(list) {
    allCommands = list || [];
    selectedTags.clear();
    renderCmdTags();
    applyCmdFilter();
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

  /* 「内置」组内的二级分组：49 条平铺要横跨两三屏，按用途分开一次只看一类。
     顺序只由这里决定（后端只写「归属」，见 core/builtin_commands.py 的 section），
     刻意不复用 labels —— 顶部标签条要是塞进六个细分，「通用 / 常用」反而不好点。 */
  const BUILTIN_SECTIONS = ["连接与投屏", "显示辅助", "按键", "屏幕状态", "网络", "应用与信息"];
  const BUILTIN_SECTION_TAIL = "其他";
  let builtinFolded = new Set();       // 已折叠的二级分组名（落 config.json 的 builtin_folded）

  // 标签过滤条：根据全部命令的 labels 生成可点选标签（多选 OR）
  function renderCmdTags() {
    const tags = new Set();
    allCommands.forEach((c) => (c.labels || []).forEach((l) => tags.add(l)));
    const arr = Array.from(tags).sort(byTagOrder);
    els.cmdTags.innerHTML = "";
    arr.forEach((t) => {
      const chip = document.createElement("button");
      chip.className = "cmd-tag" + (selectedTags.has(t) ? " active" : "");
      chip.textContent = t;
      chip.addEventListener("click", () => {
        if (selectedTags.has(t)) selectedTags.delete(t); else selectedTags.add(t);
        chip.classList.toggle("active");
        applyCmdFilter();
      });
      els.cmdTags.appendChild(chip);
    });
  }

  // 实时筛选：文字（命令名 + 命令内容）AND 已选标签（命中任一标签即保留）
  function applyCmdFilter() {
    const kw = (els.cmdFilter.value || "").toLowerCase().trim();
    const filtered = allCommands.filter((c) => {
      if (selectedTags.size > 0) {
        const labels = c.labels || [];
        if (!labels.some((l) => selectedTags.has(l))) return false;
      }
      if (kw) {
        // 搜索域含 section（二级分组名）：想找「网络」相关的一批命令时，
        // 记不住具体名字也能一次筛出来。代价是搜「按键」会多命中两条命令名里
        // 带「按键」的条目——可接受，因为结果仍是该类的子集。
        const hay = (c.name + " " + (c.section || "") + " "
          + (c.commands || []).map((x) => x.command).join(" ")).toLowerCase();
        if (!hay.includes(kw)) return false;
      }
      return true;
    });
    // 筛选中时内置二级分组一律展开：命中项藏在折叠块里等于告诉用户「没找到」
    renderCmdGroups(filtered, !!kw || selectedTags.size > 0);
    els.cmdCount.textContent = "命中 " + filtered.length + " / " + allCommands.length + " 条";
  }

  // 文字筛选防抖：大指令集（从 electerm 导入可能数百条）下，每次按键全量重渲卡片会
  // 卡顿。标签点选 / 清空是离散操作，保持即时（直接调用 applyCmdFilter）。
  let _cmdFilterTimer = null;
  function onCmdFilterInput() {
    if (_cmdFilterTimer !== null) clearTimeout(_cmdFilterTimer);
    _cmdFilterTimer = setTimeout(applyCmdFilter, 120);
  }

  function renderCmdGroups(list, filtering) {
    const groups = {};
    list.forEach((c) => {
      const label = (c.labels && c.labels.length ? c.labels[0] : "其他") || "其他";
      (groups[label] = groups[label] || []).push(c);
    });
    clearOut(els.cmdGroups);
    const keys = Object.keys(groups).sort(byTagOrder);
    if (!keys.length) {
      pushLine(els.cmdGroups, "（无匹配命令）", "dim");
      return;
    }
    for (const label of keys) {
      // 组内排序：拖过的分组用手动顺序，没拖过的仍按使用频次降序（常用靠前）
      const items = sortCmdGroup(groups[label]);
      const box = document.createElement("div"); box.className = "cmd-group";
      const title = document.createElement("div");
      title.className = "cmd-group-title"; title.textContent = label;
      box.appendChild(title);
      // 「内置」再分一层：49 条平铺要横跨两三屏，其余分组照旧是一条扁平的 chips
      if (label === "内置") {
        const secs = builtinSectionsOf(items);
        // 段数 ≥2 才给「一键全折 / 全展」：只有一段时这个按钮没有意义
        if (secs.length > 1) title.appendChild(mkFoldAllBtn(secs));
        appendBuiltinSections(box, items, !!filtering);
      } else {
        const chips = document.createElement("div"); chips.className = "cmd-chips";
        items.forEach((c) => chips.appendChild(mkCmdChip(c)));
        box.appendChild(chips);
      }
      els.cmdGroups.appendChild(box);
    }
  }

  /* 「内置」组内的二级分组（可折叠）。折叠状态落 config.json 的 builtin_folded
     （逗号串，与 cmd_order 同一套约定），下次启动照旧——每次都要重新折一遍
     的话，这个功能等于不存在。 */
  function builtinSectionsOf(items) {
    const seen = new Set();
    items.forEach((c) => seen.add(sectionNameOf(c)));
    return BUILTIN_SECTIONS.concat([BUILTIN_SECTION_TAIL]).filter((s) => seen.has(s));
  }

  function sectionNameOf(c) {
    return BUILTIN_SECTIONS.indexOf(c.section) >= 0 ? c.section : BUILTIN_SECTION_TAIL;
  }

  // 「全部折叠 / 全部展开」：六段逐个点太费事，而真正想干的事通常只有一个
  function mkFoldAllBtn(secs) {
    const allFolded = secs.every((s) => builtinFolded.has(s));
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "cmd-fold-all";
    btn.textContent = allFolded ? "全部展开" : "全部折叠";
    btn.title = allFolded ? "展开全部 " + secs.length + " 个分组" : "折叠全部 " + secs.length + " 个分组";
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      secs.forEach((s) => (allFolded ? builtinFolded.delete(s) : builtinFolded.add(s)));
      applyCmdFilter();
      persistPref("builtin_folded", Array.from(builtinFolded).join(","));
    });
    return btn;
  }

  function appendBuiltinSections(box, items, filtering) {
    const buckets = new Map();
    items.forEach((c) => {
      const sec = sectionNameOf(c);
      if (!buckets.has(sec)) buckets.set(sec, []);
      buckets.get(sec).push(c);
    });
    const wrap = document.createElement("div");
    wrap.className = "cmd-sections";
    BUILTIN_SECTIONS.concat([BUILTIN_SECTION_TAIL]).forEach((sec) => {
      const list = buckets.get(sec);
      if (!list || !list.length) return;      // 过滤后空的分组不占位
      const folded = !filtering && builtinFolded.has(sec);
      const secBox = document.createElement("div");
      secBox.className = "cmd-section" + (folded ? " is-folded" : "");
      secBox.dataset.section = sec;
      const head = document.createElement("button");
      head.type = "button";
      head.className = "cmd-section-h";
      head.setAttribute("aria-expanded", folded ? "false" : "true");
      head.title = (folded ? "展开" : "折叠") + "「" + sec + "」（" + list.length + " 条）";
      head.innerHTML = '<span class="cs-caret" aria-hidden="true"></span>'
        + '<span class="cs-name">' + escHtml(sec) + "</span>"
        + '<span class="cs-n">' + list.length + "</span>";
      head.addEventListener("click", () => {
        // 筛选态不让折：折了也会被下一次 applyCmdFilter 重新展开，徒增困惑
        if (filtering) return;
        if (builtinFolded.has(sec)) builtinFolded.delete(sec);
        else builtinFolded.add(sec);
        applyCmdFilter();
        persistPref("builtin_folded", Array.from(builtinFolded).join(","));
      });
      const chips = document.createElement("div"); chips.className = "cmd-chips";
      list.forEach((c) => chips.appendChild(mkCmdChip(c)));
      secBox.appendChild(head); secBox.appendChild(chips);
      wrap.appendChild(secBox);
    });
    box.appendChild(wrap);
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

  /* 单张指令卡。抽成函数是因为「内置」组要按二级分组渲染（见
     appendBuiltinSections）——同一套卡片逻辑不能抄两遍，否则改角标 / 菜单时
     必然漏掉一边。 */
  function mkCmdChip(c) {
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
    // 用户自定义命令：右侧固定 ⋯ 菜单（hover 弹出 复制 / 修改 / 删除）；内置命令不可改
    if (!c.builtin) {
      const menu = document.createElement("span");
      menu.className = "chip-kebab";
      menu.tabIndex = 0;
      menu.setAttribute("role", "button");
      menu.setAttribute("aria-label", "更多操作");
      menu.title = "更多操作（复制 / 修改 / 删除）";
      // 点击 kebab：阻止冒泡（不触发整张卡片的「执行」命令），并切换菜单显隐（点击 / 触摸场景）
      menu.addEventListener("click", (ev) => {
        ev.stopPropagation();
        setChipMenu(chip, menu, !menu.classList.contains("is-open"));
      });

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
      runQuickCommand(c);
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

  function bindCmdDrag() {
    if (!els.cmdGroups) return;
    els.cmdGroups.addEventListener("pointerdown", onCmdPointerDown);
    // move / up 挂 window：拖动中指针很可能已经移出卡片甚至移出容器，
    // 挂在卡片上会收不到 update 而卡在「拖住不放」的状态。
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
    renderCmdTags(); applyCmdFilter();
  }

  // 删除命令（同步回写文件）
  async function deleteCmd(c) {
    if (!c) return;
    if (!confirm("确定删除命令「" + c.name + "」？")) return;
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
    renderCmdTags(); applyCmdFilter();
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
      renderCmdTags(); applyCmdFilter();
    }
  }

  /* 快捷指令点击：
      * inputOnly（electerm 仅输入模式）—— 只把命令文本填进指令输入框，
        由用户确认后手动「执行」，不直接下发（防手滑直接跑危险/长命令）；
      * 其余 —— 直接下发，不再对命令内容做二次确认。 */
  function runQuickCommand(c) {
    if (c && c.inputOnly) { fillCmdInput(c); return; }
    callApi(api.run_command(c.id));
  }

  /* 仅输入模式：把命令文本并入输入框（多条子命令用 "; " 连接，PowerShell
     语句分隔符），聚焦输入框等用户确认。保留「保留输入内容」开关的语义——
     这里是用户主动点击填入，不受该开关影响。 */
  function fillCmdInput(c) {
    const text = (c.commands || []).map((e) => e.command).filter(Boolean).join("; ");
    if (!text) { pushStatus("warn", "⚠ 该命令没有可填入的文本"); return; }
    els.cmdInput.value = text;
    els.btnCmdInputClear.hidden = !els.cmdInput.value;
    els.cmdInput.focus();
    pushStatus("info", "⌨ 已填入输入框（仅输入模式，确认后点「执行」）：" + c.name);
  }

  function clearCmdFilter() {
    els.cmdFilter.value = "";
    selectedTags.clear();
    renderCmdTags();
    applyCmdFilter();
    // 清空也要落盘，否则下次启动过滤词又冒出来（用户会以为没清掉）
    persistPref("cmd_filter", "");
  }

  function runInput() {
    const text = els.cmdInput.value.trim();
    if (!text) return;
    callApi(api.run_custom(text));
    // 「保留输入内容」勾选项（默认开启）：
    //  * 开启 —— 执行后保留输入框内容，方便改几个字再重发（长命令尤其顺手）；
    //  * 关闭 —— 每次执行后清空输入框，适合连发一条条不同的命令。
    // 命令文本已在上面捕获并下发，此时清空不影响本次执行。
    if (els.keepInput && !els.keepInput.checked) {
      els.cmdInput.value = "";
      els.btnCmdInputClear.hidden = true;
    }
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
  }

  // 单行是否通过当前过滤条件（与全量重建共用判定）
  function linePassesFilter(ln, f) {
    if (!ln.level) return true;                 // 非 threadtime 行始终保留（纯文本）
    if (!f.levels.includes(ln.level)) return false;
    if (f.onlyExc && !ln.exc) return false;
    if (f.kw) {
      const hay = ((ln.msg || "") + " " + (ln.tag || "")).toLowerCase();
      if (!hay.includes(f.kw)) return false;
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
    els.lcCounter.textContent = "行数: " + (buf ? buf.total : 0)
      + " · 异常: " + (buf ? buf.exc : 0);
  }
  function currentLcFilter() {
    const kw = (els.lcFilter.value || "").toLowerCase();
    const levels = Array.from(els.lcLevels.querySelectorAll("input:checked"))
      .map((c) => c.value);
    const onlyExc = els.lcOnlyExc.checked;
    return { kw, levels, onlyExc };
  }
  // 全量重建：仅用于过滤条件变更 / 切换设备 / 清空 / 初始化（增量追加以外的情形）
  function renderLogcat() {
    // 全量重建前丢弃待渲染队列，否则残留的行会在重建后插入，顺序错乱
    clearLcQueue();
    els.lcDev.textContent = lcSerial ? "设备: " + lcSerial : "未选设备";
    if (!lcSerial) {
      // 计数也要一起归零：否则取消勾选后「行数/异常」仍停在上一台的数字
      els.lcView.innerHTML = "";
      els.lcCounter.textContent = "行数: 0 · 异常: 0";
      return;
    }
    // 切到「还没缓冲过」的设备：视图清空的同时计数一并归零
    const buf = lcBuffers[lcSerial];
    if (!buf) { els.lcView.innerHTML = ""; updateLcCounter(lcSerial); return; }
    const f = currentLcFilter();
    const frag = document.createDocumentFragment();
    const view = els.lcView;
    const startIdx = Math.max(0, buf.lines.length - LC_RENDER_CAP);
    for (let i = startIdx; i < buf.lines.length; i++) {
      const ln = buf.lines[i];
      if (!linePassesFilter(ln, f)) continue;
      frag.appendChild(makeLineNode(ln));
    }
    view.innerHTML = "";
    view.appendChild(frag);
    if (els.lcAuto.checked) view.scrollTop = view.scrollHeight;
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
        }
      }
      if (!items.length) return;   // 空白处右键：无内容可复制，不弹菜单
      lcMenuShow(ev.clientX, ev.clientY, items);
    });
    // 点菜单以外 / 视图滚动 / 窗口失焦 / Esc 都收起。pointerdown 用捕获：
    // 菜单项自己的 click 在 pointerdown 之后，收起逻辑不能抢在它前面误删菜单。
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
    if (p.status === "running") { lcCapRunning = true; els.lcCapStatus.textContent = "采集中…"; els.lcCapStop.disabled = false; els.lcCapStart.disabled = true; }
    // 无勾选设备时才禁用「开始抓取」（取反写反过：有设备反而点不了）
    if (p.status === "stopped") {
      lcCapRunning = false; lcCapSerial = null; els.lcCapStatus.textContent = "空闲"; els.lcCapStop.disabled = true; els.lcCapStart.disabled = !checkedDevices().length;
      // 抓取完毕强提醒（用户可能已切去别的页签，只看得到 toast）。
      // 已打包的场景由下面的 zipped 分支弹「已打包」，这里不重复。
      if (!p.packaged) {
        const name = String(p.path || "").split(/[\\/]/).pop() || "";
        const done = "✓ Logcat 抓取完毕：" + (p.lines || 0) + " 行"
          + (p.size ? " · " + fmtSize(p.size) : "") + (name ? " → " + name : "");
        pushStatus("ok", done);
        showToast("ok", done);
      }
    }
    if (p.status === "zipped") {
      els.lcCapStatus.textContent = "已打包";
      const zip = "✓ Logcat 抓取完毕，已打包: " + String(p.path || "").split(/[\\/]/).pop();
      pushStatus("ok", "✓ " + (p.text || "已打包"));
      showToast("ok", zip);
    }
    if (p.status === "error") { lcCapRunning = false; lcCapSerial = null; els.lcCapStatus.textContent = "错误"; els.lcCapStop.disabled = true; els.lcCapStart.disabled = !checkedDevices().length; pushStatus("err", "⚠ " + (p.text || "抓取错误")); }
  }
  function bufToText(serial) {
    const buf = lcBuffers[serial]; if (!buf) return "";
    return buf.lines.map((l) => l.raw).join("\n") + "\n";
  }
  /* 文件名净化：与后端 core.constants.safe_name 同语义（Windows 非法字符 +
     首尾空白/点）。无线 ADB 序列号形如 192.168.1.5:5555 含冒号，直接拼进
     a.download 会让「保存到文件」下载失败或被静默改名——后端所有落盘路径
     （截图/录屏/logcat 抓取）早已过 safe_name，前端导出同样不能漏。 */
  function safeFileName(s) {
    const cleaned = String(s == null ? "" : s)
      .replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_")
      .replace(/^[.\s]+/, "")
      .replace(/[.\s]+$/, "");
    return cleaned || "device";
  }
  function saveLogcat() {
    if (!lcSerial) { pushStatus("warn", "请先开始监控并选择设备"); return; }
    const text = bufToText(lcSerial);
    const blob = new Blob([text], { type: "text/plain" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "logcat_" + safeFileName(lcSerial) + "_" + Date.now() + ".txt";
    a.click();
    // 立刻 revoke 会把下载掐断（WebView2 下尤其明显）：延后释放，并把节点移除。
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 5000);
  }

  /* ---------------- 工具 ---------------- */
  function syncToolButtons() {
    const any = checkedDevices().length > 0;
    // 截图在途（shot_state running=true）时保持禁用：在途中改勾选不能把它
    // 放出来，恢复时也同样尊重当前勾选态（shotInFlight 与 !any 取或）。
    els.toolShot.disabled = !any || shotInFlight;
    // 投屏同样要有受控设备才可点（scrcpy 是「一台设备一个窗口」）
    if (els.toolScrcpy) els.toolScrcpy.disabled = !any;
    // 备用投屏同理；「停止」只在真的有会话时可点
    if (els.toolMirror) els.toolMirror.disabled = !any;
    if (els.toolMirrorStop && !mirrorFrameUrl && !mirrorTimer) {
      els.toolMirrorStop.disabled = true;
    }
    // 应用安装：需要「有受控设备 + 已选安装包 + 不在安装中」
    if (els.apkInstall) els.apkInstall.disabled = !any || !apkPath || apkInFlight;
    // 诊断包：有受控设备、且没有一批正在收集（收集中再点会排队出两个时间点
    // 不同的包，后端也直接拒绝，这里把按钮一起锁上是更清楚的反馈）
    if (els.diagCollect) els.diagCollect.disabled = !any || diagInFlight;
    // 无线调试的「开启 5555」同样要有受控设备（首次必须走 USB）
    if (els.wifiTcpip) els.wifiTcpip.disabled = !any || wifiBusy;
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
  function setRecRunning(running) {
    if (recInFlight) return;
    els.toolRec.disabled = running;
    els.toolRecStop.disabled = !running;
    els.toolRecStop.classList.toggle("danger", running);
    els.toolRecStop.classList.toggle("live", running);
    els.recLogcat.disabled = running;
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
    const old = els.wifiConnect.textContent;
    els.wifiConnect.textContent = "连接中…";
    const res = await callApi(api.wifi_connect(addr));
    els.wifiConnect.disabled = false;
    els.wifiConnect.textContent = old;
    wifiBusy = false;
    if (res && res.ok) {
      els.wifiAddr.value = res.address || addr;
      pushStatus("ok", "✓ 无线调试已连接：" + (res.address || addr));
      refreshWifi();
    } else if (res && res.reason) {
      pushStatus("err", "✗ 无线连接失败：" + res.reason);
    }
  }

  async function wifiDisconnect(addr, btn) {
    if (btn) btn.disabled = true;
    const res = await callApi(api.wifi_disconnect(addr));
    if (btn) btn.disabled = false;
    if (res && res.ok) refreshWifi();
    else if (res && res.reason) pushStatus("err", "✗ 断开失败：" + res.reason);
  }

  async function wifiTcpip() {
    if (wifiBusy) return;
    if (!checkedDevices().length) return pushStatus("warn", "请先在左侧勾选设备");
    wifiBusy = true;
    els.wifiTcpip.disabled = true;
    els.wifiTcpipState.textContent = "处理中…（需要几秒）";
    const res = await callApi(api.wifi_enable(null, null));
    wifiBusy = false;
    els.wifiTcpip.disabled = checkedDevices().length === 0;
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
    const res = await callApi(api.apk_pick());
    if (!res) return;
    if (res.ok === false) {
      if (res.reason && res.reason !== "cancelled") {
        pushStatus("warn", "⚠ 选择安装包失败：" + res.reason);
      }
      return;
    }
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
    const res = await callApi(api.device_info(serial));
    if (!res || serial !== devInfoSerial) return;
    if (res.ok === false) {
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


  /* 四张工具卡（截图 / 录屏 / 应用安装 / 投屏）共用一套收起逻辑：开关项竖排
     太占高度，收起后只留一行标题，把屏高让给别的卡。收起态是布局偏好，各自
     记进 config.json（shot_collapsed / rec_collapsed / apk_collapsed /
     scrcpy_collapsed）——各记各的，收一张不会连带把另一张也折起来。 */
  const TOOL_CARDS = [
    { key: "shot_collapsed", card: "shotCard", toggle: "shotToggle" },
    { key: "rec_collapsed", card: "recCard", toggle: "recToggle" },
    { key: "apk_collapsed", card: "apkCard", toggle: "apkToggle" },
    { key: "diag_collapsed", card: "diagCard", toggle: "diagToggle" },
    { key: "scrcpy_collapsed", card: "scrcpyCard", toggle: "scrcpyToggle" },
  ];

  /* persist=false 时只改界面，用于回填设置时避免多余写盘 */
  function setToolCollapsed(key, collapsed, persist) {
    const d = TOOL_CARDS.find((x) => x.key === key);
    if (!d) return;
    const card = els[d.card];
    if (!card) return;
    card.classList.toggle("collapsed", !!collapsed);
    const tg = els[d.toggle];
    if (tg) tg.setAttribute("aria-expanded", collapsed ? "false" : "true");
    if (persist) persistPref(key, !!collapsed);
  }

  function toggleToolCard(key) {
    const d = TOOL_CARDS.find((x) => x.key === key);
    if (!d || !els[d.card]) return;
    setToolCollapsed(key, !els[d.card].classList.contains("collapsed"), true);
  }

  /* 标题栏整条是开关：单击、或键盘 Enter / 空格都等价（role=button 的可达性要求） */
  function bindToolCardToggle(key) {
    const d = TOOL_CARDS.find((x) => x.key === key);
    const tg = d && els[d.toggle];
    if (!tg) return;
    tg.addEventListener("click", () => toggleToolCard(key));
    tg.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); toggleToolCard(key); }
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
    // 第一个参数传 null：交给后端取「全部受控设备」，多台即进入对比模式
    const res = await callApi(api.perf_start(
      null, ms, perfPkg));
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
  }

  async function exportPerf() {
    if (!perfTotalPoints()) { showToast("warn", "还没有采样数据，先开始监控"); return; }
    els.perfExport.disabled = true;
    setPerfState("正在生成报告…");
    const res = await callApi(api.perf_export());
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
    const body = els.fileBody; body.innerHTML = "";
    (p.entries || []).forEach((e) => {
      const tr = document.createElement("tr");
      if (e.is_dir) tr.className = "dir";
      // 选择列：每行一个复选框（父目录「..」不参与批量选择）
      const sel = document.createElement("td"); sel.className = "col-sel";
      let cb = null;
      if (e.name !== "..") {
        cb = document.createElement("input");
        cb.type = "checkbox"; cb.className = "file-check";
        cb.value = fullPath(e.name);
        cb.addEventListener("change", () => { fileAnchor = cb.value; updateFileSel(); });
        sel.appendChild(cb);
      }
      const name = document.createElement("td"); name.className = "name";
      name.textContent = (e.is_dir ? "📁 " : "📄 ") + e.name;
      name.style.cursor = "pointer";
      name.title = e.is_dir && e.name !== ".." ? "单击进入目录" : "单击切换选择（支持 Ctrl / Shift）";
      // 单击：文件夹进入下级目录；文件切换选中（Ctrl 加选 / Shift 区间选）；「..」回到上级
      name.addEventListener("click", (ev) => {
        if (e.name === "..") { els.filePath.value = dirOf(filePath); gotoPath(); return; }
        if (e.is_dir) {
          els.filePath.value = filePath.replace(/\/$/, "") + "/" + e.name;
          gotoPath();
          return;
        }
        if (!cb) return;
        if (ev.shiftKey && fileAnchor) {
          shiftSelectFiles(cb.value);
        } else {
          cb.checked = !cb.checked;
          fileAnchor = cb.value;
        }
        updateFileSel();
      });
      const size = document.createElement("td"); size.textContent = fmtSize(e.size);
      const date = document.createElement("td"); date.textContent = e.date || "";
      const perm = document.createElement("td"); perm.textContent = e.perm || "";
      const act = document.createElement("td"); act.className = "act";
      if (!e.is_dir) {
        act.appendChild(mkAct("下载", () => callApi(api.file_download(fileSerial, fullPath(e.name), null)), "download"));
        act.appendChild(mkAct("查看", () => callApi(api.file_view(fileSerial, fullPath(e.name))), "eye"));
      }
      act.appendChild(mkAct("重命名", () => {
        // 目标必须是「当前目录 + 新名」：早前用 dirOf(filePath)（当前目录的
        // **父目录**）拼接，在 /sdcard/Download 里改名会把文件搬到 /sdcard，
        // 根目录还会拼出 "//d.txt"。
        const n = prompt("新名称：", e.name);
        if (n) callApi(api.file_rename(fileSerial, fullPath(e.name), fullPath(n)));
      }, "edit"));
      act.appendChild(mkAct("删除", () => {
        if (confirm("确定删除 " + e.name + "？")) callApi(api.file_remove(fileSerial, [fullPath(e.name)]));
      }, "trash"));
      tr.appendChild(sel); tr.appendChild(name); tr.appendChild(size); tr.appendChild(date); tr.appendChild(perm); tr.appendChild(act);
      body.appendChild(tr);
    });
    els.fileSelAll.checked = false;
    updateFileSel();
  }
  function mkAct(text, fn, icon) {
    const b = document.createElement("button"); b.className = "btn tiny";
    if (icon) { const svg = makeIcon(icon); if (svg) b.appendChild(svg); }
    b.appendChild(document.createTextNode(text));
    b.addEventListener("click", fn); return b;
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
  function gotoPath() { callApi(api.file_list(fileSerial, els.filePath.value.trim() || "/")); }
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
    let n = 0;
    Array.from(files).forEach((f) => {
      const reader = new FileReader();
      reader.onload = () => {
        const b64 = (reader.result || "").split(",").pop() || "";
        callApi(api.file_upload_data(fileSerial, f.name, b64, fullPath(f.name)));
      };
      reader.readAsDataURL(f);
      n++;
    });
    pushStatus("info", "⬆ 已提交上传 " + n + " 个文件到 " + filePath);
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
    if (!splitter || !leftPanel) return;
    _splitters.push({ panel: leftPanel, min: min, reserve: reserveRight });
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
  function applySidebarCollapsed(collapsed, persist = true) {
    const row = document.querySelector(".main-row");
    if (!row || !els.deviceSidebar) return;
    row.classList.toggle("sidebar-collapsed", !!collapsed);
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
      btn.textContent = collapsed ? "»" : "«";
      btn.title = collapsed ? "展开设备栏" : "收起设备栏";
      btn.setAttribute("aria-expanded", String(!collapsed));
    }
    // 收起态给整条窄轨挂 title 与 pointer 光标（CSS 配合）：除了 » 按钮，
    // 点轨道空白 / 徽章 / 竖排标签也能展开——窄轨没有第二个可点目标，
    // 整轨即热区（见 bindUI 里的 click 委托）。
    if (els.deviceSidebar) {
      els.deviceSidebar.title = collapsed ? "点击展开设备栏" : "";
    }
    if (persist) persistPref("sidebar_collapsed", !!collapsed);
  }

  /* ---------------- UI 绑定 ---------------- */
  function bindUI() {
    // 采用原生标题栏（含 min/max/close），不再自绘窗口按钮与 Win32 拖拽。
    // （遗留代码随 v2026.0908.2228 清理，见 README。）
    renderTicker();          // 空态提示，先把跑马灯填上占位文案

    // tab 切换
    els.tabs.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const tab = btn.dataset.tab;
        els.tabs.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b === btn));
        document.querySelectorAll(".tab").forEach((t) =>
          t.classList.toggle("active", t.dataset.tab === tab));
        // 性能页的 canvas 在隐藏时尺寸为 0，切回来必须重画一次，
        // 否则会留下一张空位图（监控仍在跑，但曲线一片空白）。
        if (tab === "perf") { renderPerfDev(); queuePerfDraw(); }
      });
    });
    // 设备指令
    els.btnRefresh.addEventListener("click", () => callApi(api.refresh_devices()));
    els.btnAll.addEventListener("click", () => callApi(api.toggle_all()));
    els.btnRun.addEventListener("click", runInput);
    els.cmdInput.addEventListener("keydown", (e) => { if (e.key === "Enter") runInput(); });
    // 「保留输入内容」开关：与截图粘贴板开关同款语义——即时生效 + 落盘
    // settings.json（keep_input），下次启动由 applyBootSettings 回填。
    if (els.keepInput) {
      els.keepInput.addEventListener("change", () => {
        persistPref("keep_input", !!els.keepInput.checked);
      });
    }
    els.btnStop.addEventListener("click", () => callApi(api.stop_run()));
    // 命令输入框 clearable：输入时显示 ×，点击清空并重新聚焦（独立按钮，不干扰指令台筛选清空）
    els.btnCmdInputClear.addEventListener("click", () => {
      els.cmdInput.value = "";
      els.btnCmdInputClear.hidden = true;
      els.cmdInput.focus();
    });
    els.cmdInput.addEventListener("input", () => {
      els.btnCmdInputClear.hidden = !els.cmdInput.value;
    });
    // 启动即按当前输入内容同步 × 显隐，避免依赖 hidden 属性反射差异
    els.btnCmdInputClear.hidden = !els.cmdInput.value;
    els.btnClearStatus.addEventListener("click", () => callApi(api.clear_status()));
    els.btnClearConsole.addEventListener("click", () => callApi(api.clear_output()));
    // 指令台筛选 / 标签过滤
    els.cmdFilter.addEventListener("input", onCmdFilterInput);
    // 搜索关键字落盘到 config.json：过滤条件属于「设置」，换台电脑继续用
    // 同一个关键字才有意义。防抖 400ms——逐键输入不该每敲一下就写一次盘。
    let _cmdFilterSaveTimer = null;
    els.cmdFilter.addEventListener("input", () => {
      if (_cmdFilterSaveTimer !== null) clearTimeout(_cmdFilterSaveTimer);
      _cmdFilterSaveTimer = setTimeout(() => {
        _cmdFilterSaveTimer = null;
        persistPref("cmd_filter", (els.cmdFilter.value || "").trim());
      }, 400);
    });
    els.btnCmdClear.addEventListener("click", clearCmdFilter);
    // 命令增删改：新建 / 保存 / 取消 / 删除 / 快捷键
    els.cmdNew.addEventListener("click", () => openCmdEdit(null));
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
      // 后端可能因「已在监控中 / 设备不可用」返回 ok:false：此时必须回滚按钮态，
      // 否则界面永远停在「采集中」、开始按钮被锁死，用户无从恢复。
      const res = await startLc();
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
    els.lcSave.addEventListener("click", saveLogcat);
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
        if (lcSerial) renderLogcat();
      }, LC_DEBOUNCE_MS);
    });
    els.lcLevels.addEventListener("change", () => {
      persistPref("lc_levels", levelsOf(els.lcLevels));
      if (lcSerial) renderLogcat();
    });
    els.lcOnlyExc.addEventListener("change", () => {
      persistPref("lc_only_exc", !!els.lcOnlyExc.checked);
      if (lcSerial) renderLogcat();
    });
    // 自动滚动 / 缓冲区：不触发重渲染，只记忆选择（下次启动 / 下次抓取生效）
    els.lcAuto.addEventListener("change", () => persistPref("lc_autoscroll", !!els.lcAuto.checked));
    els.lcBuf.addEventListener("change", () => persistPref("lc_buffer", els.lcBuf.value));
    els.lcCapZipstop.addEventListener("change", () => {
      persistPref("lc_cap_zipstop", !!els.lcCapZipstop.checked);
    });
    els.lcCapLevels.addEventListener("change", () => {
      persistPref("lc_cap_levels", levelsOf(els.lcCapLevels));
    });
    els.lcCapStart.addEventListener("click", () => {
      const s = firstSelected(); if (!s) return pushStatus("warn", "请先勾选设备");
      lcCapSerial = s;   // 记下抓取目标：停止时必须停这一台，不能用当前监控设备
      // 级别过滤：V/D/I/W/E/F 全勾（默认）= 全量抓取；只勾一部分则只落盘
      // 对应级别的行（非 threadtime 格式行始终原样写盘，避免丢元信息）
      callApi(api.logcat_capture_start(s, saveDir(), buffers(), levelsOf(els.lcCapLevels)));
    });
    els.lcCapStop.addEventListener("click", () => {
      const s = lcCapSerial || lcSerial;
      if (!s) return pushStatus("warn", "当前没有正在抓取的设备");
      callApi(api.logcat_capture_stop(s, els.lcCapZipstop.checked));
    });
    // tools
    els.toolOpen.addEventListener("click", () => callApi(api.open_save_dir(saveDir())));
    els.lcOpen.addEventListener("click", () => callApi(api.open_save_dir(saveDir())));
    els.fileOpen.addEventListener("click", () => callApi(api.open_save_dir(saveDir())));
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
      const res = await callApi(api.screenshot(
        null, !!(els.shotClipboard && els.shotClipboard.checked)));
      if (!res || res.ok === false) syncToolButtons();
    });
    if (els.shotClipboard) {
      els.shotClipboard.addEventListener("change", () => {
        persistPref("shot_to_clipboard", !!els.shotClipboard.checked);
      });
    }
    // 录屏各开关一律即时记忆（config.json），下次启动沿用以往配置。
    // 同步 logcat 只留一个开关：级别与缓冲区不再可调（全量抓取才可能复现问题，
    // 少勾一级就少一条线索，而用户往往事后才发现漏了哪一级）。
    [["recLogcat", "rec_logcat"], ["recZip", "rec_zip"],
     ["recPointerLocation", "rec_pointer_location"],
     ["recShowTouches", "rec_show_touches"]].forEach(([el, key]) => {
      if (els[el]) els[el].addEventListener("change", () => persistPref(key, !!els[el].checked));
    });
    // 三张工具卡的折叠：标题栏整条可点，收起态各自持久化
    TOOL_CARDS.forEach((d) => bindToolCardToggle(d.key));
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
        syncToolButtons();
      });
    }
    if (els.toolMirrorStop) {
      els.toolMirrorStop.addEventListener("click", async () => {
        stopMirrorPreview();
        await callApi(api.mirror_stop(null));
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
    bindCmdDrag();
    bindPerfPkgPicker();
    bindPerfHover();
    renderPerfDev();
    updatePerfStats();
    queuePerfDraw();
    loadPerfThresholds();

    els.toolRec.addEventListener("click", async () => {
      if (recInFlight) return;      // 启动在途：按钮已禁用，这里再兜一道
      // 第 2/3 参（设备音频 / 电脑麦克风）与第 7 参（logcat 级别）固定给
      // false / null：音频采集链路没做完已从界面上撤掉，logcat 一律全量抓取。
      setRecInFlight(true);
      if (els.toolRec) els.toolRec.title = "正在启动录屏，请稍候…";
      let res = null;
      try {
        res = await callApi(api.screen_record_start(
          null, false, false, saveDir(),
          els.recLogcat.checked, els.recZip.checked, null,
          !!els.recPointerLocation.checked, !!els.recShowTouches.checked));
      } finally {
        setRecInFlight(false);
        if (els.toolRec) els.toolRec.title = "";
      }
      if (!res || res.ok === false) {
        // 后端在全部设备启动失败时会自动撤销会话残留并返回 ok:false；
        // 这里回滚按钮态，避免 UI 卡在“录制中”却没有任何会话可停。
        pushStatus("err", "⚠ 录屏未能启动" + (res && res.reason ? "（" + res.reason + "）" : ""));
        setRecRunning(false);
        return;
      }
      setRecRunning(true);
    });
    els.toolRecStop.addEventListener("click", async () => {
      if (recInFlight) return;      // 停止在途：收尾（转码 / 打包）要十几秒，防连点
      setRecInFlight(true);
      if (els.toolRecStop) els.toolRecStop.title = "正在停止录屏并收尾，请稍候…";
      let res = null;
      try {
        res = await callApi(api.screen_record_stop());
      } finally {
        setRecInFlight(false);
        if (els.toolRecStop) els.toolRecStop.title = "";
      }
      if (res && res.ok === false && res.reason) {
        pushStatus("err", "⚠ 停止录屏失败：" + res.reason);
      }
      setRecRunning(false);
    });
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
      const n = prompt("文件夹名称："); if (n) callApi(api.file_mkdir(fileSerial, (filePath.replace(/\/$/, "") + "/" + n)));
    });
    els.fileTouch.addEventListener("click", () => {
      if (!fileSerial) return pushStatus("warn", "请先勾选设备");
      const n = prompt("文件名称："); if (n) callApi(api.file_touch(fileSerial, (filePath.replace(/\/$/, "") + "/" + n)));
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
      paths.forEach((p) => callApi(api.file_download(fileSerial, p, dir)));
      pushStatus("info", "已发起下载 " + paths.length + " 个文件" + (dir ? " 到 " + dir : ""));
    });
    els.fileBatchDel.addEventListener("click", () => {
      const paths = fileCheckedPaths();
      if (!paths.length) return;
      if (!fileSerial) return pushStatus("warn", "请先勾选设备");
      if (!confirm("确定删除选中的 " + paths.length + " 个项？此操作不可恢复")) return;
      callApi(api.file_remove(fileSerial, paths));
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
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      if (!els.statusModal.classList.contains("hidden")) { closeStatusModal(); return; }
      // 无线调试 / 设备信息：同样是「点开就想随手关掉」的查看类弹窗
      if (els.wifiModal && !els.wifiModal.classList.contains("hidden")) { wifiClose(); return; }
      if (els.devinfoModal && !els.devinfoModal.classList.contains("hidden")) closeDevInfo();
    });
    // 大文件「查看」：直接调系统默认程序打开已拉取到本地的临时文件
    els.modalOpenLocal.addEventListener("click", () => {
      if (!modalLocalPath) return;
      callApi(api.open_local_file(modalLocalPath));
    });
    // 可拖动分隔条：设备栏（最小 200px，右侧内容至少留 480px）/
    // 指令台（最小 240px，指令输出至少留 360px）；双击分隔条重置默认宽度
    bindSplitter(els.sidebarSplitter, els.deviceSidebar, 200, 480);
    bindSplitter(els.cmdSplitter, els.cmdPanelLeft, 240, 360);
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
        if (e.target.closest && e.target.closest("button")) return;
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
    // 一旦触发重渲染（改级别 / 关键字 / 仅异常）或「保存到文件」，上一轮的日志
    // 会重新冒出来（视图已清空，缓冲却还留着旧行）。
    if (lcSerial) lcBuffers[lcSerial] = { lines: [], total: 0, exc: 0 };
    updateLcCounter(null);
    // 返回 Promise：调用方据此判断后端是否真的启动了（失败要回滚按钮态）
    return callApi(api.logcat_start(lcSerial, buffers(),
      Array.from(els.lcLevels.querySelectorAll("input:checked")).map((c) => c.value),
      els.lcFilter.value, els.lcOnlyExc.checked));
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
