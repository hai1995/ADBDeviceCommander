/* jsdom 前端行为测试：Logcat 抓取完毕的全局 toast 通知
   —— 停止抓取 / 打包完成必须弹 toast（用户可能已切到别的页签，看不到状态栏）；
      已打包的场景 stopped 不得再重复弹一条（packaged 标记二选一）。 */
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

/** 按「每轮 take_events 消费一批」的方式喂事件（与真实轮询一致）。 */
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

const toastTexts = (doc) =>
  Array.from(doc.querySelectorAll(".toast .toast-body")).map((n) => n.textContent);

(async () => {
  console.log("\n[1] 未打包的 stopped：必须弹「抓取完毕」toast");
  {
    const batches = [
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
       { kind: "devices", payload: { items: dev(true) } }],
      [{ kind: "logcat_capture", payload: { status: "running" } }],
      [{ kind: "logcat_capture",
         payload: { status: "stopped", path: "D:/log/logcat_A1_x.txt",
                    lines: 1234, size: 2048, packaged: false } }],
    ];
    const window = await bootBatched(batches);
    const doc = window.document;
    ok(await waitFor(() => toastTexts(doc).some((t) => t.includes("Logcat 抓取完毕")), 4000, "stopped toast"),
       "stopped（未打包）弹出「Logcat 抓取完毕」toast");
    const texts = toastTexts(doc);
    ok(texts.some((t) => t.includes("1234") && t.includes("logcat_A1_x.txt")),
       "toast 含行数与文件名：" + JSON.stringify(texts));
    window.close();
  }

  console.log("\n[2] 勾选打包：zipped 弹「已打包」toast，stopped(packaged) 不重复");
  {
    const batches = [
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
       { kind: "devices", payload: { items: dev(true) } }],
      [{ kind: "logcat_capture", payload: { status: "running" } }],
      [{ kind: "logcat_capture",
         payload: { status: "zipped", path: "D:/log/logcat_A1_x.txt.zip",
                    src: "D:/log/logcat_A1_x.txt", text: "已打包：D:/log/logcat_A1_x.txt.zip" } },
       { kind: "logcat_capture",
         payload: { status: "stopped", path: "D:/log/logcat_A1_x.txt",
                    lines: 1234, size: 512, packaged: true } }],
    ];
    const window = await bootBatched(batches);
    const doc = window.document;
    ok(await waitFor(() => toastTexts(doc).some((t) => t.includes("已打包")), 4000, "zipped toast"),
       "zipped 弹出「已打包」toast");
    // 等 stopped 事件也被消费后：不得出现第二条「抓取完毕」
    await waitFor(() => toastTexts(doc).length >= 1, 2000, "settle");
    await sleep(600);   // 多等一轮轮询，确保 packaged 的 stopped 已被处理
    const doneCount = toastTexts(doc).filter((t) => t.includes("Logcat 抓取完毕")).length;
    ok(doneCount === 1, "打包场景只弹一条（zipped），stopped(packaged) 不重复弹，实际 " + doneCount);
    window.close();
  }

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
