/* jsdom 前端行为测试：Logcat「开始抓取」按钮的回弹条件
   —— 抓取结束后「开始抓取」必须重新可点（只要还有受控设备）。
   回归背景：onLogcatCapture 的 stopped / error 分支早前把条件写成
   `checkedDevices().length > 0`（有设备反而置灰），于是一轮抓取结束后按钮一直是
   灰的；由于设备列表只在「有变化」时才重渲染，用户再也开不了下一轮抓取。 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.join(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "frontend/index.html"), "utf8");
const js = fs.readFileSync(path.join(ROOT, "frontend/js/app.js"), "utf8");

process.on("unhandledRejection", () => {});

let pass = 0, fail = 0;
function ok(cond, name) {
  if (cond) { pass++; console.log("  ✓ " + name); }
  else { fail++; console.log("  ✗ " + name); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
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

const dev = (checked) => ([
  { serial: "A1", model: "Pixel", state: "device", ok: true, checked: checked },
]);

/** 按「每轮 take_events 消费一批」的方式喂事件（与真实 400ms 轮询一致）。 */
async function bootBatched(batches) {
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
  const { window } = dom;
  let round = 0;
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          if (k === "boot") {
            return Promise.resolve({ version: "v-test", warnings: [], commands: [], adb: "adb" });
          }
          if (k === "take_events") { const b = batches[round] || []; round++; return Promise.resolve(b); }
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  return window;
}

(async () => {
  console.log("\n[1] 抓取按钮态：running → stopped → error → 无受控设备");
  {
    const batches = [
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
       { kind: "devices", payload: { items: dev(true) } }],
      [{ kind: "logcat_capture", payload: { status: "running" } }],
      [{ kind: "logcat_capture", payload: { status: "stopped" } }],
      [{ kind: "logcat_capture", payload: { status: "error", text: "boom" } }],
      [{ kind: "devices", payload: { items: dev(false) } }],
      [{ kind: "logcat_capture", payload: { status: "stopped" } }],
    ];
    const window = await bootBatched(batches);
    const doc = window.document;
    const capStart = doc.getElementById("lc-cap-start");
    const capStop = doc.getElementById("lc-cap-stop");

    ok(await waitFor(() => capStart.disabled === false, 4000, "初始可点"),
       "有受控设备时「开始抓取」初始可点");
    ok(capStop.disabled === true, "空闲时「停止抓取」禁用");

    ok(await waitFor(() => doc.getElementById("lc-cap-status").textContent === "采集中…", 4000, "running"),
       "running 事件后状态文案为「采集中…」");
    ok(capStart.disabled === true, "抓取中「开始抓取」禁用");
    ok(capStop.disabled === false, "抓取中「停止抓取」可点");

    ok(await waitFor(() => doc.getElementById("lc-cap-status").textContent === "空闲", 4000, "stopped"),
       "stopped 事件后状态文案回到「空闲」");
    ok(capStart.disabled === false, "stopped 后仍有受控设备 → 「开始抓取」必须恢复可点（回归点）");
    ok(capStop.disabled === true, "stopped 后「停止抓取」禁用");

    ok(await waitFor(() => doc.getElementById("lc-cap-status").textContent === "错误", 4000, "error"),
       "error 事件后状态文案为「错误」");
    ok(capStart.disabled === false, "error 后仍有受控设备 → 「开始抓取」必须恢复可点（可重试）");
    ok(capStop.disabled === true, "error 后「停止抓取」禁用");

    ok(await waitFor(() => doc.querySelector("#device-list .device-card.selected") === null, 4000, "取消勾选"),
       "设备取消勾选事件已生效（卡片无 selected）");
    ok(await waitFor(() => doc.getElementById("lc-cap-status").textContent === "空闲", 4000, "再次 stopped"),
       "再次 stopped 事件已处理");
    ok(capStart.disabled === true, "没有受控设备时「开始抓取」禁用");
  }

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
