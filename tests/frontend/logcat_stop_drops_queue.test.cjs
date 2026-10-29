/* jsdom 前端行为测试：点「停止」即时收住渲染机 + 死会话在途行丢弃。
   验证：
   1. 监控中推入大批日志（队列有积压）时点停止 → 帧循环立刻停止
      （不再继续渲染积压 —— 「点了停止，程序要很久才停下来」的修复）；
   2. 停止后总线里还在途的 append 事件被丢弃（不入队、不计数）；
   3. 按钮态 / 状态文案 / 行数计数在停止后保持冻结；
   4. 重新开始监控后渲染恢复（丢弃开关已复位，不会把新会话也误杀）。 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.join(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "frontend/index.html"), "utf8");
const js = fs.readFileSync(path.join(ROOT, "frontend/js/app.js"), "utf8");

process.on("unhandledRejection", (e) => { console.log("!! unhandledRejection:", e && e.stack ? e.stack : e); });

let pass = 0, fail = 0;
function ok(c, n) {
  if (c) { pass++; console.log("  ✓ " + n); }
  else { fail++; console.log("  ✗ " + n); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitFor(fn, ms = 4000, label = "") {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    let v = false;
    try { v = !!fn(); } catch (e) { v = false; }
    if (v) return true;
    await sleep(30);
  }
  console.log("    (waitFor 超时: " + label + ")");
  return false;
}

function mkLines(n, excFrom = -1) {
  const out = [];
  for (let i = 0; i < n; i++) {
    const exc = excFrom >= 0 && i >= excFrom;
    out.push({
      raw: "08-29 10:00:00.000  1  1 I Tag: line " + i,
      level: "I", tag: "Tag", msg: "line " + i, exc,
    });
  }
  return out;
}

// 初始事件随 boot 预装载：首轮 poll（~400ms）即取走，设备渲染 + Logcat
// 自动联动（未监控时跟随第一个勾选设备）在点击前完成 —— 与真实启动时序一致。
async function boot(initial) {
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
  const { window } = dom;
  const queue = (initial || []).slice();
  const calls = [];
  const apiStub = new Proxy({}, {
    get(t, k) {
      if (k === "then") return undefined;
      return function (...args) {
        calls.push({ fn: String(k), args });
        if (k === "boot") {
          return Promise.resolve({ ok: true, version: "v-test", warnings: [], commands: [] });
        }
        if (k === "take_events") {
          return Promise.resolve(queue.splice(0, queue.length));
        }
        return Promise.resolve({ ok: true });
      };
    },
  });
  window.pywebview = { api: apiStub };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  await sleep(500);
  return { window, calls, push: (e) => queue.push(e) };
}

const evBooted = { kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } };
const evDevices = { kind: "devices", payload: { items: [
  { serial: "A1", model: "Pixel", state: "device", ok: true, checked: true },
] } };

(async () => {
  console.log("\n[G] 停止即时性：清队列 + 丢弃在途 append");

  const { window, calls, push } = await boot([evBooted, evDevices]);
  const doc = window.document;
  const view = doc.getElementById("lc-view");
  const stopBtn = doc.getElementById("lc-stop");
  const startBtn = doc.getElementById("lc-start");
  const counter = doc.getElementById("lc-counter");

  await waitFor(() => doc.querySelector("#device-list .device-card") !== null,
    3000, "设备卡渲染");
  await waitFor(() => counter.textContent.indexOf("行数: 0") >= 0, 3000, "自动联动计数就绪");

  // 开始监控（lcSerial = A1）
  startBtn.click();
  await waitFor(() => calls.some((c) => c.fn === "logcat_start"), 3000, "logcat_start 下发");
  ok(calls.some((c) => c.fn === "logcat_start" && c.args[0] === "A1"),
     "开始监控已下发 logcat_start(A1)");
  await waitFor(() => stopBtn.disabled === false, 3000, "监控态按钮");
  ok(stopBtn.disabled === false && startBtn.disabled === true,
     "监控中按钮态（停止可点 / 开始禁用）");

  // 推入 2000 行（超过单帧 300 行的渲染能力 → 队列必有积压）
  push({ kind: "logcat", payload: { serial: "A1", status: "running" } });
  push({ kind: "logcat", payload: { serial: "A1", status: "append",
    lines: mkLines(2000), total: 2000, exc: 0 } });
  await waitFor(() => view.childElementCount >= 600, 4000, "首批帧渲染");
  ok(view.childElementCount >= 600 && view.childElementCount < 2000,
     "分帧渲染进行中：已渲染 " + view.childElementCount + " 行（未一次性插完，队列有积压）");

  // ---- 关键：记录当前行数后同一 tick 内点停止 ----
  const countBefore = view.childElementCount;
  const counterBefore = counter.textContent;
  stopBtn.click();
  ok(calls.some((c) => c.fn === "logcat_stop" && c.args[0] === "A1"),
     "停止已下发 logcat_stop(A1)");

  // 停止后立刻推「在途」append（停止前发出、poll 还没来得及取的事件）
  push({ kind: "logcat", payload: { serial: "A1", status: "append",
    lines: mkLines(500, 0), total: 2500, exc: 0 } });

  await sleep(500);   // 足够跑几十帧：若未修复，积压+在途行会继续滚

  ok(view.childElementCount === countBefore,
     "停止后视图行数冻结在 " + countBefore + "（实际 " + view.childElementCount
     + "）—— 积压队列已清、在途行被丢弃");
  ok(counter.textContent === counterBefore,
     "行数计数冻结（「" + counterBefore + "」，未混入在途行的 total=2500）");
  ok(stopBtn.disabled === true && startBtn.disabled === false,
     "按钮态回到空闲（停止禁用 / 开始可点）");
  ok(doc.getElementById("lc-status").textContent === "空闲", "状态文案回到空闲");

  // 恢复监控后放行：新会话的 append 必须正常渲染（丢弃开关已复位）。
  // 注意 startLc() 会清空视图与缓冲，因此断言新会话的 100 行渲染出来。
  startBtn.click();
  await waitFor(() => calls.filter((c) => c.fn === "logcat_start").length >= 2,
    3000, "二次 logcat_start");
  await waitFor(() => stopBtn.disabled === false, 3000, "重新进入监控态");
  push({ kind: "logcat", payload: { serial: "A1", status: "running" } });
  push({ kind: "logcat", payload: { serial: "A1", status: "append",
    lines: mkLines(100), total: 100, exc: 0 } });
  await waitFor(() => view.childElementCount >= 100, 4000, "新会话恢复渲染");
  ok(view.childElementCount >= 100,
     "重新开始监控后渲染恢复（当前 " + view.childElementCount + " 行）");

  window.close();

  console.log("\n==============================================");
  console.log("结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
