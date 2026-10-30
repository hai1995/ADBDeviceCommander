/* jsdom 前端行为测试：Logcat 停止按钮在监控中变红 + 侧栏无「受控设备」chip */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

// 相对本测试文件定位工程根 —— 早期版本硬编码了 "/workspace/ADBDeviceCommander"，
// 换台机器就直接 ENOENT，整组断言一个都跑不起来。
const ROOT = path.join(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "frontend/index.html"), "utf8");
const js = fs.readFileSync(path.join(ROOT, "frontend/js/app.js"), "utf8");

// start() 里的异常会变成未处理的 Promise rejection；默认策略会直接终止进程，
// 导致后面的断言一条都跑不到。这里接住，交由下方断言显式判定成败。
process.on("unhandledRejection", () => {});

let pass = 0, fail = 0;
function ok(cond, name) {
  if (cond) { pass++; console.log("  ✓ " + name); }
  else { fail++; console.log("  ✗ " + name); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// 轮询等待条件成立（事件轮询为 400ms 一轮，固定 sleep 易受调度抖动影响）
async function waitFor(fn, ms = 4000, label = "") {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    let v = false;
    try { v = !!fn(); } catch (e) { v = false; }
    if (v) return true;
    await sleep(40);
  }
  console.log("    (waitFor 超时: " + label + ")");
  return false;
}

async function boot(events) {
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
  const { window } = dom;
  const queue = events.slice();
  const calls = [];

  const apiStub = new Proxy({}, {
    get(t, k) {
      if (k === "then") return undefined;                 // 别被当成 thenable
      return function (...args) {
        calls.push({ fn: String(k), args });
        if (k === "boot") {
          return Promise.resolve({
            version: "v-test", warnings: [], commands: [],
            adb: "/usr/bin/adb", save_dir: "/tmp",
          });
        }
        if (k === "take_events") {
          const out = queue.splice(0, queue.length);
          return Promise.resolve(out);
        }
        if (k === "window_toggle_max") return Promise.resolve({ max: true });
        return Promise.resolve({ ok: true });
      };
    },
  });
  window.pywebview = { api: apiStub };

  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  await sleep(500);            // 等第一轮 take_events(400ms) + boot 完成
  return { window, calls, push: (e) => window.__push ? window.__push(e) : queue.push(e) };
}

// 常用事件
const evBooted = { kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } };
const evDevices = (list) => ({ kind: "devices", payload: { items: list } });

(async () => {
  console.log("\n[0] 启动健壮性：Windows（navigator.platform = Win32）下必须能正常 boot");
  {
    // 回归：start() 曾直接引用浏览器里不存在的 process（Node 全局）来推导默认
    // 保存目录。jsdom 的 navigator.platform 默认为 ""，恰好绕过该分支所以测不出；
    // 真实 WebView2 在 Windows 上返回 "Win32"，会抛 ReferenceError 中断 start()，
    // api.boot() 永远不会被调用 —— 界面停在「连接中…/未就绪」，整个程序不可用。
    const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
    const { window } = dom;
    Object.defineProperty(window.navigator, "platform", { value: "Win32", configurable: true });
    const calls = [];
    window.pywebview = {
      api: new Proxy({}, {
        get(t, k) {
          if (k === "then") return undefined;
          return function (...args) {
            calls.push(String(k));
            if (k === "default_save_dir") return Promise.resolve({ ok: true, dir: "C:\\Users\\tester\\Pictures\\ADB" });
            if (k === "boot") return Promise.resolve({ ok: true, version: "v-test", warnings: [], commands: [] });
            if (k === "take_events") return Promise.resolve([]);
            return Promise.resolve({ ok: true });
          };
        },
      }),
    };
    Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
    window.eval(js);
    await waitFor(() => calls.includes("boot"), 3000, "boot 下发");
    ok(calls.includes("boot"), "Win32 下 start() 未被异常中断，boot 已下发");
    ok(calls.includes("default_save_dir"), "默认保存目录改为向后端索取（单一数据源）");
    const dirVal = window.document.getElementById("tool-dir").value;
    ok(dirVal === "C:\\Users\\tester\\Pictures\\ADB", "保存目录已回填后端默认值（实际：" + dirVal + "）");
  }

  console.log("\n[1] 侧栏：不应再有「受控设备」芯片区");
  {
    const { window } = await boot([evBooted]);
    const doc = window.document;
    ok(doc.querySelector(".sidebar-foot") === null, "无 .sidebar-foot 容器");
    ok(doc.getElementById("sel-count") === null, "无 #sel-count 元素");
    ok(doc.getElementById("sel-list") === null, "无 #sel-list 元素");
    const side = doc.querySelector(".device-sidebar");
    ok(side && !side.textContent.includes("受控设备"), "侧栏内不含「受控设备」chip 文案");
    ok(doc.querySelector(".sel-chip") === null, "无 .sel-chip 元素");
    ok(doc.getElementById("device-list") !== null, "设备列表 #device-list 仍存在");
  }

  console.log("\n[2] Logcat 停止按钮：空闲态");
  {
    const { window } = await boot([evBooted]);
    const stop = window.document.getElementById("lc-stop");
    const start = window.document.getElementById("lc-start");
    ok(stop.classList.contains("danger") === false, "空闲时停止按钮无 danger 类");
    ok(stop.classList.contains("live") === false, "空闲时停止按钮无 live 类");
    ok(stop.disabled === true, "空闲时停止按钮 disabled");
    ok(start.disabled === false, "空闲时开始按钮可点");
  }

  console.log("\n[3] 点击「开始监控」→ 停止按钮立即变红");
  {
    const { window, calls } = await boot([evBooted, evDevices([
      { serial: "A1", model: "Pixel", state: "device", ok: true, checked: true },
    ])]);
    const doc = window.document;
    const stop = doc.getElementById("lc-stop");
    const start = doc.getElementById("lc-start");
    // 勾选设备后 take_events 已消费；再推一次设备事件确保渲染
    await sleep(500);
    start.dispatchEvent(new window.Event("click", { bubbles: true }));
    await sleep(30);
    ok(stop.classList.contains("danger"), "开始后停止按钮带 danger（红底）");
    ok(stop.classList.contains("live"), "开始后停止按钮带 live（呼吸光晕）");
    ok(stop.disabled === false, "开始后停止按钮可用");
    ok(start.disabled === true, "开始后开始按钮禁用");
    ok(doc.getElementById("lc-status").textContent === "采集中…", "状态文案为「采集中…」");
    ok(calls.some((c) => c.fn === "logcat_start"), "已下发 logcat_start");
  }

  console.log("\n[4] 点击「停止」→ 立即恢复默认样式");
  {
    const { window, calls } = await boot([evBooted, evDevices([
      { serial: "A1", model: "Pixel", state: "device", ok: true, checked: true },
    ])]);
    const doc = window.document;
    const stop = doc.getElementById("lc-stop");
    const start = doc.getElementById("lc-start");
    await sleep(500);
    start.dispatchEvent(new window.Event("click", { bubbles: true }));
    await sleep(30);
    stop.dispatchEvent(new window.Event("click", { bubbles: true }));
    await sleep(30);
    ok(!stop.classList.contains("danger"), "停止后移除 danger");
    ok(!stop.classList.contains("live"), "停止后移除 live");
    ok(stop.disabled === true, "停止后停止按钮 disabled");
    ok(start.disabled === false, "停止后开始按钮恢复可点");
    ok(doc.getElementById("lc-status").textContent === "空闲", "状态文案回到「空闲」");
    ok(calls.some((c) => c.fn === "logcat_stop"), "已下发 logcat_stop");
  }

  console.log("\n[6] 事件路径：running → stopped → error 的按钮态");
  {
    const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
    const { window } = dom;
    let round = 0;
    const batches = [
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } }],
      [{ kind: "logcat", payload: { serial: "A1", status: "running" } }],
      [{ kind: "logcat", payload: { serial: "A1", status: "stopped" } }],
      [{ kind: "logcat", payload: { serial: "A1", status: "error", text: "boom" } }],
    ];
    window.pywebview = {
      api: new Proxy({}, {
        get(t, k) {
          if (k === "then") return undefined;
          return function (...args) {
            if (k === "boot") return Promise.resolve({ version: "v-test", warnings: [], commands: [], adb: "adb" });
            if (k === "take_events") { const b = batches[round] || []; round++; return Promise.resolve(b); }
            return Promise.resolve({ ok: true });
          };
        },
      }),
    };
    Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
    window.eval(js);
    const doc = window.document;
    const stop = doc.getElementById("lc-stop");
    const start = doc.getElementById("lc-start");

    await waitFor(() => stop.classList.contains("danger") === false || true, 600, "boot");
    ok(stop.classList.contains("danger") === false, "初始无 danger");

    await waitFor(() => stop.classList.contains("danger"), 4000, "running");
    ok(stop.classList.contains("danger"), "running 事件后停止按钮变红");
    ok(stop.classList.contains("live"), "running 事件后带 live");
    ok(stop.disabled === false, "running 后停止按钮可用");
    ok(start.disabled === true, "running 后开始按钮禁用");
    ok(doc.getElementById("lc-status").textContent === "采集中…", "running 状态文案");

    await waitFor(() => !stop.classList.contains("danger"), 4000, "stopped");
    ok(!stop.classList.contains("danger"), "stopped 事件后移除红色");
    ok(!stop.classList.contains("live"), "stopped 事件后移除 live");
    ok(stop.disabled === true, "stopped 后停止按钮禁用");
    ok(start.disabled === false, "stopped 后开始按钮恢复");
    ok(doc.getElementById("lc-status").textContent === "空闲", "stopped 状态文案");

    await waitFor(() => doc.getElementById("lc-status").textContent === "错误", 4000, "error");
    ok(!stop.classList.contains("danger"), "error 事件后移除红色");
    ok(stop.disabled === true, "error 后停止按钮禁用");
    ok(start.disabled === false, "error 后开始按钮恢复，可重试");
    ok(doc.getElementById("lc-status").textContent === "错误", "error 状态文案");
  }

  console.log("\n[7] Logcat 增量追加（不重建 DOM）");
  {
    const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
    const { window } = dom;
    let round = 0;
    const mkLines = (n, off) => Array.from({ length: n }, (_, i) => ({
      raw: `01-01 00:00:0${(i % 10)}.000  1000  1000 I Tag${i + off}: msg ${i + off}`,
      level: "I", tag: "Tag" + (i + off), msg: "msg " + (i + off), exc: false,
    }));
    const dev = [{ serial: "A1", model: "Pixel", state: "device", ok: true, checked: true }];
    const batches = [
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
       { kind: "devices", payload: { items: dev } }],
      [{ kind: "logcat", payload: { serial: "A1", status: "running" } },
       { kind: "logcat", payload: { serial: "A1", status: "append", lines: mkLines(50, 0), total: 50, exc: 0 } }],
      [{ kind: "logcat", payload: { serial: "A1", status: "append", lines: mkLines(50, 50), total: 100, exc: 0 } }],
    ];
    window.pywebview = {
      api: new Proxy({}, {
        get(t, k) {
          if (k === "then") return undefined;
          return function (...args) {
            if (k === "boot") return Promise.resolve({ version: "v-test", warnings: [], commands: [], adb: "adb" });
            if (k === "take_events") { const b = batches[round] || []; round++; return Promise.resolve(b); }
            return Promise.resolve({ ok: true });
          };
        },
      }),
    };
    Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
    window.eval(js);
    const view = window.document.getElementById("lc-view");
    await waitFor(() => view.childNodes.length === 50, 4000, "第一批");
    const n1 = view.childNodes.length;
    const first1 = view.firstChild;
    ok(n1 === 50, "第一批 50 行（实际 " + n1 + "）");
    await waitFor(() => view.childNodes.length === 100, 4000, "第二批");
    const n2 = view.childNodes.length;
    ok(n2 === 100, "第二批追加后 100 行（实际 " + n2 + "）");
    ok(view.firstChild === first1, "首节点未被替换 → 增量追加而非全量重建");
    ok(view.textContent.includes("msg 99"), "最新行已渲染");
  }

  console.log("\n[8] 原生标题栏回归：不再有自绘窗口按钮与拖拽");
  {
    const { window, calls } = await boot([evBooted]);
    const doc = window.document;

    ok(doc.getElementById("win-min") === null, "无自绘最小化按钮 #win-min");
    ok(doc.getElementById("win-max") === null, "无自绘最大化按钮 #win-max");
    ok(doc.getElementById("win-close") === null, "无自绘关闭按钮 #win-close");
    ok(doc.querySelector(".win-btns") === null, "无 .win-btns 容器");
    ok(doc.querySelector(".topbar") !== null, "顶部栏仍在（tab + 状态胶囊）");

    // 品牌标题已移除：应用名由原生标题栏展示，tab 栏不再重复（v2026.1014.1545 去重）。
    // 版本号迁至「关于」页 #about-ver，顶栏不展示。
    ok(doc.querySelector(".brand") === null, "无重复的品牌标题（原生标题栏已展示应用名）");
    ok(doc.getElementById("ver") === null, "顶栏不再挂版本号元素 #ver");
    ok(doc.getElementById("about-ver") !== null, "「关于」页仍展示版本号 #about-ver");
    doc.querySelector(".topbar").dispatchEvent(new window.MouseEvent("mousedown", { bubbles: true, button: 0 }));
    await sleep(20);
    ok(!calls.some((c) => c.fn === "drag_window"), "顶栏 mousedown 不触发 drag_window（窗口拖拽交由原生标题栏）");
    ok(!calls.some((c) => c.fn === "window_toggle_max" || c.fn === "window_minimize" || c.fn === "window_close"),
       "boot 流程未调用任何自绘窗口控制方法");
  }

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
