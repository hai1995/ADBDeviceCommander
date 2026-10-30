/* jsdom 前端行为测试：「保存到文件」导出文件名净化

   回归点：无线 ADB 序列号形如 192.168.1.5:5555 含冒号，而冒号是 Windows
   的非法文件名字符。后端所有落盘路径（截图/录屏/logcat 抓取）都过了
   safe_name，前端导出的 a.download 却直接裸拼序列号 —— 「保存到文件」在
   无线设备上会下载失败或被静默改名。修复：前端同样过一遍 safeFileName。 */
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
  let round = 0;
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function () {
          if (k === "boot") return Promise.resolve({ ok: true });
          if (k === "take_events") { const b = batches[round] || []; round++; return Promise.resolve(b); }
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  // jsdom 没有实现 URL.createObjectURL：先打桩，否则 saveLogcat 在设 download 前就抛
  window.URL.createObjectURL = () => "blob:fake";
  window.URL.revokeObjectURL = () => {};
  // 捕获下载点击：记录每个被点击锚点的 download 文件名
  const downloads = [];
  window.HTMLAnchorElement.prototype.click = function () {
    downloads.push(this.download);
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  return { window, downloads };
}

const dev = (serial, checked) => ({ serial, model: "Pixel", state: "device", ok: true, checked });
const mkLines = (n) => Array.from({ length: n }, (_, i) => ({
  raw: `01-01 00:00:00.000  1000  1000 I Tag: msg ${i}`,
  level: "I", tag: "Tag", msg: "msg " + i, exc: false,
}));
const ILLEGAL = /[<>:"/\\|?*]/;

(async () => {
  console.log("\n[1] 无线序列号（含冒号）：导出文件名必须净化，不能带非法字符");
  {
    const { window, downloads } = mkEnv([
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
    await sleep(120);
    ok(downloads.length === 1, "点击「保存到文件」触发一次下载（实际 " + downloads.length + " 次）");
    const name = downloads[0] || "";
    ok(name.startsWith("logcat_") && name.endsWith(".txt"),
       "文件名形如 logcat_<序列号>_<时间戳>.txt（实际：" + name + "）");
    ok(!ILLEGAL.test(name),
       "文件名不含 Windows 非法字符（冒号等）（实际：" + name + "）");
    ok(name.indexOf("192.168.1.5") >= 0,
       "净化后仍保留序列号主体，可辨识是哪台设备（实际：" + name + "）");
  }

  console.log("\n[2] 普通序列号：文件名不受影响");
  {
    const { window, downloads } = mkEnv([
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
       { kind: "devices", payload: { items: [dev("A1", true)] } }],
      [{ kind: "logcat", payload: {
        serial: "A1", status: "append", lines: mkLines(5), total: 5, exc: 0 } }],
    ]);
    const doc = window.document;
    await waitFor(() => doc.getElementById("lc-counter").textContent.indexOf("行数: 5") === 0,
                  4000, "A1 缓冲 5 行");

    doc.getElementById("lc-save").dispatchEvent(new window.Event("click", { bubbles: true }));
    await sleep(120);
    const name = downloads[0] || "";
    ok(/^logcat_A1_\d+\.txt$/.test(name),
       "普通序列号导出为 logcat_A1_<时间戳>.txt（实际：" + name + "）");
  }

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
