/* jsdom 前端行为测试：录屏启动 / 停止失败时，提示里不能出现后端机器码。

   回归：后端守卫「已在录屏中」只回 {"ok": false, "reason": "recording"}，
   前端把 reason 原样拼进提示 —— 用户看到的是「⚠ 录屏未能启动（recording）」，
   一句英文机器码：既没说明现在到底在不在录，也没给出下一步（先停止）。
   同理「停止」在没有会话时回 no_session，会被说成「停止录屏失败」。

   约定：后端用 message 给人话，reason 只作机器码；前端只展示 message。 */
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

const DEV = [{ serial: "A1", model: "Pixel", state: "device", ok: true, checked: true }];

(async () => {
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
  const { window } = dom;
  let round = 0;
  const batches = [
    [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
     { kind: "devices", payload: { items: DEV } }],
  ];
  let startReply = { ok: false, reason: "recording",
                     message: "正在录屏中，如需重新开始请先点「停止录屏」" };
  const calls = [];
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          calls.push({ fn: String(k), args });
          if (k === "boot") return Promise.resolve({ version: "v-test", warnings: [], commands: [], adb: "adb" });
          if (k === "take_events") { const b = batches[round] || []; round++; return Promise.resolve(b); }
          if (k === "screen_record_start") return Promise.resolve(startReply);
          if (k === "screen_record_stop") return Promise.resolve({ ok: false, reason: "no_session" });
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  const doc = window.document;
  const startBtn = doc.getElementById("tool-rec");
  const stopBtn = doc.getElementById("tool-rec-stop");
  const statusText = () => (doc.getElementById("status") || {}).textContent || "";

  await waitFor(() => startBtn.disabled === false, 4000, "boot + 设备渲染");

  console.log("\n[1] 后端回 reason=recording：提示必须是 message 里的人话");
  startBtn.dispatchEvent(new window.Event("click", { bubbles: true }));
  await sleep(60);
  ok(calls.some((c) => c.fn === "screen_record_start"), "已下发 screen_record_start");
  ok(statusText().includes("正在录屏中"), "状态栏出现「正在录屏中」：" + statusText().slice(-60));
  ok(!statusText().includes("recording"), "状态栏不得出现机器码 recording");
  await waitFor(() => startBtn.disabled === false, 2000, "启动失败后按钮复位");
  ok(startBtn.disabled === false, "启动失败后「开始录制」恢复可点");

  console.log("\n[2] 后端回 no_session（会话已结束）：不该说成「停止录屏失败」");
  startReply = { ok: true, ts: "ts1" };
  startBtn.dispatchEvent(new window.Event("click", { bubbles: true }));
  await waitFor(() => stopBtn.disabled === false, 3000, "进入录制中");
  ok(stopBtn.disabled === false, "录制中「停止」可用");
  stopBtn.dispatchEvent(new window.Event("click", { bubbles: true }));
  await sleep(60);
  ok(!statusText().includes("停止录屏失败"), "no_session 不得报「停止录屏失败」");
  ok(!statusText().includes("no_session"), "状态栏不得出现机器码 no_session");
  await waitFor(() => startBtn.disabled === false, 2000, "停止后按钮复位");
  ok(startBtn.disabled === false, "停止后切回「开始录制」");

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
