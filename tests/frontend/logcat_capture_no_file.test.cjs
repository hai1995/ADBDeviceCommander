/* jsdom 前端行为测试：Logcat「启动瞬间就停止」不该被报成「抓取完毕：0 行」

   回归背景：后端在「还没开始抓就点了停止」（stop_now）时不再建文件，改为推
   stopped{no_file:true, text:"已停止：…本次没有生成日志文件"}。前端若仍按
   「!packaged → ✓ 抓取完毕：0 行」处理，用户看到的是「设备当时没有日志输出」
   这个错误结论——而且还照着提示去目录里找一个根本不存在的文件。 */
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
  console.log("\n[1] 启动瞬间就停止（no_file）→ 说「没生成文件」，不报「抓取完毕 0 行」");
  {
    const batches = [
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
       { kind: "devices", payload: { items: dev(true) } }],
      [{ kind: "logcat_capture", payload: {
        status: "stopped", path: "/tmp/logcat_A1_001.txt", lines: 0, size: 0,
        packaged: false,
        no_file: true,
        text: "已停止：还没开始抓取就点了停止，本次没有生成日志文件" } }],
    ];
    const window = await bootBatched(batches);
    const doc = window.document;
    const status = doc.getElementById("status");

    ok(await waitFor(() => status.textContent.indexOf("本次没有生成日志文件") >= 0, 4000, "no_file 文案"),
       "状态栏说清「本次没有生成日志文件」");
    ok(status.textContent.indexOf("抓取完毕") < 0,
       "不得出现「✓ Logcat 抓取完毕」（0 行不等于抓完了）");
    ok(!/\b0 行/.test(status.textContent), "不得出现「0 行」这种看似结论的计数");
    ok(doc.getElementById("lc-cap-status").textContent === "空闲",
       "抓取状态回到「空闲」");
    ok(doc.getElementById("lc-cap-start").disabled === false,
       "「开始抓取」恢复可点（可立刻重来）");
    // 不该弹任何 toast：no_file 是「用户自己停的」，不是失败
    const toasts = doc.querySelectorAll(".toast");
    ok(toasts.length === 0, "不弹 toast（用户主动停止，不算失败）");
  }

  console.log("\n[2] 正常抓到日志后停止 → 仍然报「抓取完毕：N 行」");
  {
    const batches = [
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
       { kind: "devices", payload: { items: dev(true) } }],
      [{ kind: "logcat_capture", payload: {
        status: "stopped", path: "/tmp/logcat_A1_002.txt", lines: 3, size: 2048,
        packaged: false } }],
    ];
    const window = await bootBatched(batches);
    const doc = window.document;
    const status = doc.getElementById("status");

    ok(await waitFor(() => status.textContent.indexOf("抓取完毕") >= 0, 4000, "完成文案"),
       "正常结束仍报「✓ Logcat 抓取完毕」");
    ok(status.textContent.indexOf("3 行") >= 0, "带上真实行数 3 行");
    ok(status.textContent.indexOf("logcat_A1_002.txt") >= 0, "带上文件名");
    ok(status.textContent.indexOf("没有生成") < 0, "正常结束不该说「没有生成文件」");
  }

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
