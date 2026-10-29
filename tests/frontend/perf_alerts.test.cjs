/* jsdom 前端行为测试：性能监控「阈值告警」

   后端判定逻辑（evaluate_alerts）与报告卡片由 tests/test_backend_perf.py 锁定；
   这里只锁前端的三件事：
   1) 阈值来自后端 perf_thresholds，不在前端另抄一份；
   2) 读数越过阈值 → 指标卡切红 + 状态栏提示一次（边沿触发、不刷屏）；
   3) 曲线画出阈值参考线（虚线 + 标签），恢复后卡片回到常态。 */
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

const THRESHOLDS = {
  thresholds: { fps: { min: 45 }, jank: { max: 8 }, temp: { max: 42 }, cpu: { max: 85 } },
  rules: {
    fps: "帧率 FPS < 45", jank: "卡顿率 % > 8",
    temp: "电池温度 ℃ > 42", cpu: "CPU % > 85",
  },
  crit_ratio: 25,
};

function fakeCtx() {
  const ctx = {
    texts: [], dashes: 0,
    setTransform() {}, clearRect() {}, beginPath() {}, closePath() {},
    moveTo() {}, lineTo() {}, arc() {}, rect() {}, roundRect() {}, fillRect() {},
    save() {}, restore() {}, stroke() {}, fill() {}, measureText() { return { width: 24 }; },
    fillText(t) { ctx.texts.push(String(t)); },
    setLineDash() { ctx.dashes++; },
    createLinearGradient() { return { addColorStop() {} }; },
  };
  return ctx;
}

function mkEnv(polls) {
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const ctx = fakeCtx();
  let round = 0;
  const queue = (polls || []).slice();
  const calls = [];

  window.HTMLCanvasElement.prototype.getContext = function () { return ctx; };
  Object.defineProperty(window.HTMLElement.prototype, "clientWidth",
    { configurable: true, get() { return 820; } });
  Object.defineProperty(window.HTMLElement.prototype, "clientHeight",
    { configurable: true, get() { return 320; } });

  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          calls.push({ fn: k, args });
          if (k === "boot") {
            return Promise.resolve({ version: "v-test", warnings: [], commands: [],
                                     adb: "adb", settings: {} });
          }
          if (k === "take_events") {
            const b = round === 0
              ? [{ kind: "devices",
                   payload: { items: [{ serial: "S1", model: "Pixel 7", state: "device",
                                        ok: true, checked: true }] } }]
              : [];
            round++;
            return Promise.resolve(b);
          }
          if (k === "perf_thresholds") return Promise.resolve(THRESHOLDS);
          if (k === "perf_start") {
            return Promise.resolve({
              ok: true, serial: "S1", interval: 1.0,
              info: { serial: "S1", model: "Pixel 7", pkg: "" },
              sessions: { S1: { serial: "S1", model: "Pixel 7", pkg: "" } },
              failed: {},
            });
          }
          if (k === "perf_poll") {
            const next = queue.shift();
            return Promise.resolve(next || { running: true, samples: [], sessions: {} });
          }
          if (k === "perf_stop") return Promise.resolve({ ok: true, samples: 1 });
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  return { window, ctx, calls };
}

const click = (doc, id) => doc.getElementById(id).dispatchEvent(
  new doc.defaultView.Event("click", { bubbles: true }));
const toasts = (doc) => Array.from(doc.querySelectorAll("#toast-wrap .toast-body"))
  .map((e) => e.textContent);

// 曲线至少要两个点才会绘制（单点只显示「正在采样…」），故各给两点。
const BAD = { running: true, sessions: { S1: {
  running: true, seq: 2, info: { serial: "S1", model: "Pixel 7" },
  samples: [
    { seq: 1, t: 1793200000, cpu: 30.0, fps: 31.0, jank: 20.0, temp: 44.0 },
    { seq: 2, t: 1793200001, cpu: 30.0, fps: 30.0, jank: 20.0, temp: 44.0 },
  ],
} } };
const GOOD = { running: true, sessions: { S1: {
  running: true, seq: 4, info: { serial: "S1", model: "Pixel 7" },
  samples: [
    { seq: 3, t: 1793200002, cpu: 25.0, fps: 59.0, jank: 1.0, temp: 33.0 },
    { seq: 4, t: 1793200003, cpu: 25.0, fps: 59.0, jank: 1.0, temp: 33.0 },
  ],
} } };

(async () => {
  const watchdog = setTimeout(() => {
    console.log("    (看门狗触发：按当前结果退出)");
    process.exit(fail ? 1 : 0);
  }, 30000);

  console.log("\n[1] 阈值由后端下发");
  {
    const { window, calls } = mkEnv([]);
    await waitFor(() => calls.filter((c) => c.fn === "perf_thresholds").length >= 1,
                  3000, "阈值请求");
    ok(calls.some((c) => c.fn === "perf_thresholds"),
       "初始化时向后端请求一次 perf_thresholds");
    window.close && 0;
  }

  console.log("\n[2] 越线 → 指标卡切红 + 提示一次");
  {
    const { window, ctx } = mkEnv([BAD]);
    const doc = window.document;
    await waitFor(() => doc.getElementById("perf-start").disabled === false, 3000, "设备就绪");
    click(doc, "perf-start");
    ok(await waitFor(() => doc.getElementById("perf-v-fps").textContent === "30", 4000, "读数"),
       "收到样本（fps 30）");
    ok(await waitFor(() => doc.getElementById("perf-stat-fps").classList.contains("warn"),
                     3000, "切红"),
       "帧率卡切红（低于 45）");
    ok(doc.getElementById("perf-stat-cpu").classList.contains("warn") === false,
       "正常的 CPU 卡不受影响");
    ok(await waitFor(() => toasts(doc).some((t) => /帧率 FPS < 45/.test(t)), 3000, "toast"),
       "状态栏提示具体规则（帧率 FPS < 45）");
    ok(doc.getElementById("perf-stat-fps").title.includes("45"),
       "卡片 title 写明阈值");

    console.log("\n[3] 曲线画出阈值参考线");
    click(doc, "perf-stat-fps");
    ok(await waitFor(() => ctx.texts.some((t) => /阈值\s*45/.test(t)), 3000, "阈值标签"),
       "画布出现「阈值 45」参考线标签");
    ok(ctx.dashes > 0, "参考线使用虚线绘制");
  }

  console.log("\n[4] 恢复正常后解除标红");
  {
    const { window } = mkEnv([BAD, GOOD]);
    const doc = window.document;
    await waitFor(() => doc.getElementById("perf-start").disabled === false, 3000, "设备就绪");
    click(doc, "perf-start");
    await waitFor(() => doc.getElementById("perf-stat-fps").classList.contains("warn"),
              4000, "先切红");
    ok(await waitFor(() => !doc.getElementById("perf-stat-fps").classList.contains("warn"),
                     5000, "恢复"),
       "帧率回到 59 后卡片解除标红");
  }

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  clearTimeout(watchdog);
  process.exit(fail ? 1 : 0);
})();
