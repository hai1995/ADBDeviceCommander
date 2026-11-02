/* jsdom 前端行为测试：logcat 抓取遇设备掉线时，UI 必须保持「采集中」而非误切「空闲」，
   且结束若带时间缺口必须明确告警（不得伪装成「✓ 抓取完毕」）。

   回归点：录屏 + 满缓冲全级别 logcat 同时跑时设备 USB 抖动掉线，后端会进入
   「等重连」并推 logcat_capture{status:"reconnecting"}；重连窗口耗尽则推
   stopped{gap:true}。前端若把 reconnecting 当 stopped 处理，界面会错误地回到「空闲」、
   用户以为抓取已结束（实际还在等重连续写）；若把 gap 的 stopped 当成功，用户拿到的是
   一份带缺口的日志却以为是完整的。 */
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
  console.log("\n[1] 设备掉线（reconnecting）→ 界面保持「采集中」，不误切「空闲」");
  {
    const batches = [
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
       { kind: "devices", payload: { items: dev(true) } }],
      [{ kind: "logcat_capture", payload: {
        status: "running", path: "/tmp/logcat_A1_001.txt" } }],
      [{ kind: "logcat_capture", payload: {
        status: "reconnecting", path: "/tmp/logcat_A1_001.txt",
        text: "设备 A1 掉线，logcat 抓取等待重连（最长 900 秒，期间已抓到的日志不会丢）" } }],
    ];
    const window = await bootBatched(batches);
    const doc = window.document;
    const status = doc.getElementById("status");
    const capStatus = doc.getElementById("lc-cap-status");
    const startBtn = doc.getElementById("lc-cap-start");
    const stopBtn = doc.getElementById("lc-cap-stop");

    ok(await waitFor(() => capStatus.textContent.indexOf("等待重连") >= 0, 4000, "reconnecting 文案"),
       "状态文案显示「等待重连」");
    ok(await waitFor(() => startBtn.disabled === true, 4000, "开始禁用"),
       "重连等待期间「开始抓取」仍禁用（仍在抓）");
    ok(await waitFor(() => stopBtn.disabled === false, 4000, "停止可用"),
       "重连等待期间「停止抓取」仍可用（用户可主动结束）");
    ok(await waitFor(() => status.textContent.indexOf("掉线") >= 0, 4000, "掉线告警"),
       "状态栏给出掉线警告");
    // 关键：绝不能把 reconnecting 当成 stopped 复位成「空闲」
    ok(capStatus.textContent !== "空闲",
       "reconnecting 不得把状态复位成「空闲」（否则用户以为抓取结束了）");
  }

  console.log("\n[2] 重连窗口耗尽（stopped + gap）→ 明确告警时间缺口，不报「抓取完毕」");
  {
    const batches = [
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
       { kind: "devices", payload: { items: dev(true) } }],
      [{ kind: "logcat_capture", payload: {
        status: "running", path: "/tmp/logcat_A1_002.txt" } }],
      [{ kind: "logcat_capture", payload: {
        status: "stopped", path: "/tmp/logcat_A1_002.txt", lines: 120, size: 8192,
        packaged: false, gap: true,
        text: "（注意：抓取期间设备曾掉线，文件含时间缺口标记，缺失时段见文件内 [logcat] 标记）" } }],
    ];
    const window = await bootBatched(batches);
    const doc = window.document;
    const status = doc.getElementById("status");
    const capStatus = doc.getElementById("lc-cap-status");

    ok(await waitFor(() => capStatus.textContent === "空闲", 4000, "回到空闲"),
       "结束态回到「空闲」");
    ok(await waitFor(() => doc.getElementById("lc-cap-start").disabled === false, 4000, "开始可点"),
       "「开始抓取」恢复可点");
    ok(await waitFor(() => status.textContent.indexOf("时间缺口") >= 0, 4000, "缺口告警"),
       "状态栏明确告警「时间缺口」");
    ok(status.textContent.indexOf("抓取完毕") < 0,
       "带缺口的结束不得报「✓ Logcat 抓取完毕」（否则用户以为日志完整）");
    ok(status.textContent.indexOf("缺口") >= 0,
       "文案必须点明缺口而非「完整」");
  }

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
