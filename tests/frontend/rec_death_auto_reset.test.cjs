/* jsdom 前端行为测试：录屏进程意外死亡时，后端 rec_state 事件必须把界面切回「开始录制」。

   回归：录屏中途执行 adb root 会杀掉设备端 screenrecord，后端自动收尾会话并广播
   rec_state(running=false)。前端若不处理该事件，界面会一直停在「录制中」——
   后端早已结束，用户再点「停止」只会得到 no_session（使用说明「录屏被中断」条）。 */
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
  console.log("\n[1] 点击「开始录制」→ 录制中按钮态");
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
  const { window } = dom;
  let round = 0;
  const batches = [
    [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
     { kind: "devices", payload: { items: DEV } }],
    [],   // 之后轮询为空，直到 rec_state 到来
    [{ kind: "rec_state", payload: { running: false, reason: "died" } }],
  ];
  const calls = [];
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          calls.push({ fn: String(k), args });
          if (k === "boot") return Promise.resolve({ version: "v-test", warnings: [], commands: [], adb: "adb" });
          if (k === "take_events") { const b = batches[round] || []; round++; return Promise.resolve(b); }
          if (k === "screen_record_start") return Promise.resolve({ ok: true, ts: "ts1" });
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  const doc = window.document;
  const stopBtn = doc.getElementById("tool-rec-stop");
  const startBtn = doc.getElementById("tool-rec");

  await waitFor(() => startBtn.disabled === false, 4000, "boot + 设备渲染");
  startBtn.dispatchEvent(new window.Event("click", { bubbles: true }));
  await sleep(30);
  ok(calls.some((c) => c.fn === "screen_record_start"), "已下发 screen_record_start");
  ok(startBtn.disabled === true, "录制中「开始录制」禁用");
  ok(stopBtn.disabled === false, "录制中「停止」可用");
  ok(stopBtn.classList.contains("danger"), "录制中「停止」为红色");
  ok(doc.getElementById("rec-logcat").disabled === true, "录制中选项被锁定");

  console.log("\n[2] rec_state(running=false) → 界面自动切回「开始录制」");
  // 等到含 rec_state 的那批事件被轮询消费（400ms 一轮）
  await waitFor(() => stopBtn.disabled === true && !stopBtn.classList.contains("danger"),
                6000, "rec_state 复位");
  ok(stopBtn.disabled === true, "复位后「停止」禁用");
  ok(!stopBtn.classList.contains("danger"), "复位后移除红色");
  ok(!stopBtn.classList.contains("live"), "复位后移除呼吸光晕");
  ok(startBtn.disabled === false, "复位后「开始录制」恢复可点");
  ok(doc.getElementById("rec-logcat").disabled === false, "复位后选项解锁");
  ok(doc.getElementById("rec-zip").disabled === false, "复位后「压缩 zip」选项解锁");
  ok(doc.getElementById("tool-shot").disabled === false, "复位后截图按钮可用");

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
