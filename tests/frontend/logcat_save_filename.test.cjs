/* jsdom 前端行为测试：「保存到文件」改走后端写盘
   —— 点击按钮调用 api.logcat_save(serial, text)，把当前视图文本交给后端落盘
      （文件名净化、落盘都移到后端，前端不再用 a.click() + Blob 下载）。

   回归点：
   1) 原实现用 a.click() 下载 blob，在 WebView2 下被静默吞掉——点了没反应。
      现在交给后端写盘，调用真实发生、后端回传路径，前端据此提示成功。
   2) 无线 ADB 序列号含冒号（Windows 非法文件名字符），文件名净化现由后端
      safe_name 统一处理，前端只负责把完整文本送过去、不丢数据。 */
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

function mkEnv(batches) {
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
  const { window } = dom;
  const calls = [];
  let round = 0;
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          calls.push({ api: k, args: args });
          if (k === "boot") return Promise.resolve({ ok: true });
          if (k === "take_events") { const b = batches[round] || []; round++; return Promise.resolve(b); }
          if (k === "logcat_save") return Promise.resolve({ ok: true, path: "D:\\out\\logcat_x.txt" });
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  return { window, calls };
}

const dev = (serial, checked) => ({ serial, model: "Pixel", state: "device", ok: true, checked });
const mkLines = (n) => Array.from({ length: n }, (_, i) => ({
  raw: `01-01 00:00:00.000  1000  1000 I Tag: msg ${i}`,
  level: "I", tag: "Tag", msg: "msg " + i, exc: false,
}));

(async () => {
  console.log("\n[1] 无线序列号（含冒号）：点「保存到文件」把完整文本交给后端落盘");
  {
    const { window, calls } = mkEnv([
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
       { kind: "devices", payload: { items: [dev("192.168.1.5:5555", true)] } }],
      [{ kind: "logcat", payload: {
        serial: "192.168.1.5:5555", status: "append",
        lines: mkLines(10), total: 10, exc: 0 } }],
    ]);
    const doc = window.document;
    await waitFor(() => doc.getElementById("lc-counter").textContent.indexOf("行数: 10") === 0,
                  4000, "无线设备缓冲 10 行");
    ok(doc.getElementById("lc-dev").textContent === "设备: 192.168.1.5:5555",
       "当前监控设备为无线序列号（实际：" + doc.getElementById("lc-dev").textContent + "）");

    doc.getElementById("lc-save").dispatchEvent(new window.Event("click", { bubbles: true }));
    const called = await waitFor(
      () => calls.some((c) => c.api === "logcat_save"), 2000, "logcat_save 调用");
    ok(called, "点击「保存到文件」调用了 api.logcat_save（不再静默下载）");
    const call = calls.find((c) => c.api === "logcat_save");
    ok(call.args[0] === "192.168.1.5:5555", "第一个参数应为当前监控序列号（实际 " + call.args[0] + "）");
    // 完整文本送过去、不丢数据：10 行都应出现在传给后端的字符串里
    const text = call.args[1] || "";
    ok(text.split("\n").length >= 10, "应把全部缓冲行传给后端（实际 " + text.split("\n").length + " 行）");
    ok(/msg 0/.test(text) && /msg 9/.test(text), "文本应包含首尾行内容");
  }

  console.log("\n[2] 空缓冲：不调用后端，避免写空文件");
  {
    const { window, calls } = mkEnv([
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
       { kind: "devices", payload: { items: [dev("A1", true)] } }],
      [{ kind: "logcat", payload: {
        serial: "A1", status: "append", lines: [], total: 0, exc: 0 } }],
    ]);
    const doc = window.document;
    await waitFor(() => doc.getElementById("lc-counter").textContent.indexOf("行数: 0") === 0,
                  4000, "A1 缓冲 0 行");

    doc.getElementById("lc-save").dispatchEvent(new window.Event("click", { bubbles: true }));
    await sleep(150);
    ok(!calls.some((c) => c.api === "logcat_save"),
       "空内容不应调用 api.logcat_save（不写空文件）");
  }

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
