/* jsdom 前端行为测试：Logcat 计数只跟随当前设备

   回归点：renderLogcat() 在「没有设备」或「当前设备还没缓冲过」时提前 return，
   忘了刷新计数条 —— 视图已经空了，计数却还留着上一台设备的行数/异常数，
   与眼前的空视图自相矛盾（README 明确承诺「切设备 / 清空后计数立即刷新」）。 */
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

// 按「轮」投递事件：第 N 轮 take_events 返回第 N 批，用来精确控制切设备的时序
function mkEnv(batches) {
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
  const { window } = dom;
  let round = 0;
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function () {
          if (k === "boot") return Promise.resolve({ version: "v-test", warnings: [], commands: [], adb: "adb" });
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

const dev = (serial, checked) => ({ serial, model: "Pixel", state: "device", ok: true, checked });
const COUNTER_0 = "行数: 0 · 异常: 0";
const mkLines = (n) => Array.from({ length: n }, (_, i) => ({
  raw: `01-01 00:00:00.000  1000  1000 I Tag: msg ${i}`,
  level: "I", tag: "Tag", msg: "msg " + i, exc: false,
}));

(async () => {
  console.log("\n[1] 切到「还没缓冲过」的设备：视图清空，计数必须归零");
  {
    const window = mkEnv([
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
       { kind: "devices", payload: { items: [dev("A1", true), dev("B1", false)] } }],
      // A1 先缓冲出一批数据，制造出非 0 的计数
      [{ kind: "logcat", payload: { serial: "A1", status: "append", lines: mkLines(50), total: 50, exc: 3 } }],
      // 取消勾选 A1、改勾 B1：未监控时空闲态会自动把当前设备切到 B1
      [{ kind: "devices", payload: { items: [dev("A1", false), dev("B1", true)] } }],
    ]);
    const doc = window.document;
    const counter = doc.getElementById("lc-counter");
    const view = doc.getElementById("lc-view");

    await waitFor(() => counter.textContent === "行数: 50 · 异常: 3", 4000, "A1 计数");
    ok(counter.textContent === "行数: 50 · 异常: 3", "A1 缓冲后计数为 50/3（实际：" + counter.textContent + "）");
    ok(view.childNodes.length === 50, "A1 视图渲染 50 行（实际 " + view.childNodes.length + "）");

    await waitFor(() => doc.getElementById("lc-dev").textContent === "设备: B1", 4000, "切到 B1");
    ok(doc.getElementById("lc-dev").textContent === "设备: B1", "当前设备已切到 B1");
    ok(counter.textContent === COUNTER_0, "切到无缓冲的 B1 后计数归零（实际：" + counter.textContent + "）");
    ok(view.childNodes.length === 0, "切到无缓冲的 B1 后视图清空（实际 " + view.childNodes.length + " 行）");
  }

  console.log("\n[2] 设备全部消失：视图与计数一起归零");
  {
    const window = mkEnv([
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
       { kind: "devices", payload: { items: [dev("A1", true)] } }],
      [{ kind: "logcat", payload: { serial: "A1", status: "append", lines: mkLines(20), total: 20, exc: 1 } }],
      [{ kind: "devices", payload: { items: [] } }],
    ]);
    const doc = window.document;
    const counter = doc.getElementById("lc-counter");

    await waitFor(() => counter.textContent === "行数: 20 · 异常: 1", 4000, "A1 计数");
    ok(counter.textContent === "行数: 20 · 异常: 1", "有设备时计数正常（实际：" + counter.textContent + "）");

    await waitFor(() => doc.getElementById("lc-dev").textContent === "未选设备", 4000, "设备清空");
    ok(doc.getElementById("lc-dev").textContent === "未选设备", "设备清空后标签为「未选设备」");
    ok(counter.textContent === COUNTER_0, "无设备时计数归零（实际：" + counter.textContent + "）");
  }

  console.log("\n[3] 修好后计数仍能正常累加（不是把计数写死成 0）");
  {
    const window = mkEnv([
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
       { kind: "devices", payload: { items: [dev("B1", true)] } }],
      [{ kind: "logcat", payload: { serial: "B1", status: "append", lines: mkLines(7), total: 7, exc: 1 } }],
      [{ kind: "logcat", payload: { serial: "B1", status: "append", lines: mkLines(3), total: 10, exc: 2 } }],
    ]);
    const doc = window.document;
    const counter = doc.getElementById("lc-counter");

    await waitFor(() => counter.textContent === "行数: 10 · 异常: 2", 4000, "B1 累加");
    ok(counter.textContent === "行数: 10 · 异常: 2", "第二批后计数累加到 10/2（实际：" + counter.textContent + "）");
    ok(doc.getElementById("lc-view").childNodes.length === 10, "视图共 10 行");
  }

  console.log("\n[4] 点击「开始监控」后计数立即归零，不等首帧");
  {
    const window = mkEnv([
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
       { kind: "devices", payload: { items: [dev("A1", true)] } }],
      [{ kind: "logcat", payload: { serial: "A1", status: "append", lines: mkLines(30), total: 30, exc: 4 } }],
      [],
    ]);
    const doc = window.document;
    const counter = doc.getElementById("lc-counter");

    await waitFor(() => counter.textContent === "行数: 30 · 异常: 4", 4000, "A1 计数");
    ok(counter.textContent === "行数: 30 · 异常: 4", "监控前已有一轮旧计数（实际：" + counter.textContent + "）");

    doc.getElementById("lc-start").dispatchEvent(new window.Event("click", { bubbles: true }));
    await sleep(50);
    ok(counter.textContent === COUNTER_0, "点开始后计数立即归零（实际：" + counter.textContent + "）");
    ok(doc.getElementById("lc-view").childNodes.length === 0, "点开始后视图清空");
  }

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
