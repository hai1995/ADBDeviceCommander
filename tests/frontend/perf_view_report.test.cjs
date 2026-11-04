/* jsdom 前端行为测试：性能监控「查看报告」按钮
   —— 在「导出报告」之后新增，点击打开报告所在目录（保存目录）。

   回归点：用户希望能直接打开报告目录。按钮复用 open_save_dir（与工具页
   「打开目录」同一套后端调用），点击即打开保存目录。 */
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

function mkEnv(batches, saveDir) {
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
          if (k === "default_save_dir") return Promise.resolve({ ok: true, dir: saveDir || "D:\\out" });
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  return { window, calls };
}

(async () => {
  console.log("\n[1] 存在「查看报告」按钮，且位于「导出报告」之后");
  {
    const { window } = mkEnv([
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
       { kind: "devices", payload: { items: [{ serial: "A1", model: "Pixel", state: "device", ok: true, checked: true }] } }],
    ]);
    const doc = window.document;
    await waitFor(() => doc.getElementById("perf-export") != null, 3000, "perf 控件就绪");
    ok(!!doc.getElementById("perf-view"), "存在「查看报告」按钮");
    ok(!!doc.getElementById("perf-export"), "存在「导出报告」按钮");
    const order = ["perf-export", "perf-view"].map((id) => doc.getElementById(id));
    ok(order[0].compareDocumentPosition(order[1]) & window.Node.DOCUMENT_POSITION_FOLLOWING,
       "「查看报告」在「导出报告」之后（DOM 顺序）");
  }

  console.log("\n[2] 点击「查看报告」→ 调用 open_save_dir 打开报告目录");
  {
    const { window, calls } = mkEnv([
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
       { kind: "devices", payload: { items: [{ serial: "A1", model: "Pixel", state: "device", ok: true, checked: true }] } }],
    ], "D:\\reports");
    const doc = window.document;
    await waitFor(() => doc.getElementById("perf-view") != null, 3000, "perf 控件就绪");
    doc.getElementById("perf-view").dispatchEvent(new window.Event("click", { bubbles: true }));
    const called = await waitFor(
      () => calls.some((c) => c.api === "open_save_dir"), 2000, "open_save_dir 调用");
    ok(called, "点击后调用了 open_save_dir");
    const call = calls.find((c) => c.api === "open_save_dir");
    ok(call.args[0] === "D:\\reports" || call.args[0] == null,
       "打开的是保存目录（实际：" + call.args[0] + "）");
  }

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
