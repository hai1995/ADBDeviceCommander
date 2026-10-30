/* jsdom 前端行为测试：「复制」按钮连点后文案不能卡在「已复制」

   回归点：原 flashCopy 在每次点击时都把当前按钮文案记成「原文案」，连点两次时第二次
   读到的是已经是「已复制」，于是恢复阶段把按钮永久停在「已复制」上（再点也不会复原）。
   修复后只在计时器未结束时记录一次原文案，并复用同一个计时器，连点也能正常还原。 */
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
          if (k === "boot") return Promise.resolve({ version: "v-test", warnings: [], commands: [], adb: "adb" });
          if (k === "take_events") { const b = batches[round] || []; round++; return Promise.resolve(b); }
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  // 复制按钮在真实 WebView2 走 navigator.clipboard；jsdom 两者都未实现，桩成成功才能
  // 走到 flashCopy(true) → 「已复制」这条路径，验证「已复制 → 计时后还原」。
  const _c = { writeText: () => Promise.resolve() };
  try { Object.defineProperty(window.navigator, "clipboard", { configurable: true, value: _c }); } catch (e) {}
  try { Object.defineProperty(window.document, "execCommand", { configurable: true, value: () => true }); } catch (e) {}
  return window;
}
// 等状态栏出现一行（轮询从 take_events 消费的 tool/status 事件才会渲染），否则
// copyStatus 会因取不到文本直接 flashCopy(false)，点不出「已复制」。
function waitStatusReady(doc, ms = 4000) {
  return waitFor(() => doc.querySelectorAll("#status .line").length > 0, ms, "状态栏就绪");
}
function clickCopy(btn) { const w = btn.ownerDocument.defaultView; btn.dispatchEvent(new w.Event("click", { bubbles: true })); }

(async () => {
  console.log("\n[1] 复制按钮：连点两次后文案必须恢复为「复制」");
  {
    const window = mkEnv([
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
       { kind: "tool", payload: { type: "info", text: "hello status line" } }],
    ]);
    const doc = window.document;
    const btn = doc.getElementById("btn-copy-status");
    ok(btn.textContent === "复制", "初始文案为「复制」（实际：" + btn.textContent + "）");
    await waitStatusReady(doc);
    clickCopy(btn);
    await sleep(40);
    clickCopy(btn);
    await sleep(40);
    ok(btn.textContent === "已复制", "两次点击后文案为「已复制」（实际：" + btn.textContent + "）");
    const restored = await waitFor(() => btn.textContent === "复制", 3000, "恢复为复制");
    ok(restored, "连点后文案恢复为「复制」（实际：" + btn.textContent + "），未卡在「已复制」");
  }

  console.log("\n[2] 不连点：单次复制后也会在计时结束后恢复");
  {
    const window = mkEnv([
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
       { kind: "tool", payload: { type: "info", text: "hi" } }],
    ]);
    const doc = window.document;
    const btn = doc.getElementById("btn-copy-status");
    await waitStatusReady(doc);
    clickCopy(btn);
    await sleep(40);
    ok(btn.textContent === "已复制", "单点后文案为「已复制」（实际：" + btn.textContent + "）");
    const restored = await waitFor(() => btn.textContent === "复制", 3000, "恢复为复制");
    ok(restored, "单次复制后也能恢复为「复制」");
  }

  console.log("\n[3] 计时结束后再次点击仍能正常闪烁并还原");
  {
    const window = mkEnv([
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
       { kind: "tool", payload: { type: "info", text: "again" } }],
    ]);
    const doc = window.document;
    const btn = doc.getElementById("btn-copy-status");
    await waitStatusReady(doc);
    clickCopy(btn);
    await sleep(1400);                                   // 等过闪烁窗口
    ok(btn.textContent === "复制", "首轮闪烁已结束，文案回到「复制」");
    clickCopy(btn);
    await sleep(40);
    ok(btn.textContent === "已复制", "再次点击仍切换到「已复制」");
    const restored = await waitFor(() => btn.textContent === "复制", 3000, "再次恢复");
    ok(restored, "再次点击后也能恢复为「复制」");
  }

  console.log("\n结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
