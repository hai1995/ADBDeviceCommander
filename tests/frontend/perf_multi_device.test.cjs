/* jsdom 前端行为测试：性能监控「多设备对比」

   后端的多会话编排由 tests/test_backend_controller.py 锁定；这里只锁前端：
   1) 勾选多台时设备位文案与 perf_start 的调用口径（第一参 null = 全选）；
   2) 按 sessions 结构把每台设备的增量样本分别归位，图例出现且读数各是各的；
   3) 点图例切焦点设备 → 指标卡读数跟着换；
   4) 停止后的总点数是各设备之和；导出多份时的提示文案。

   jsdom 无 canvas / 无布局，故桩一个 2d 上下文与固定尺寸（与 perf_tab 一致）。 */
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

function fakeCtx() {
  const ctx = {
    setTransform() {}, clearRect() {}, beginPath() {}, closePath() {},
    moveTo() {}, lineTo() {}, arc() {}, rect() {}, roundRect() {},
    fillRect() {}, save() {}, restore() {}, stroke() {}, fill() {},
    fillText() {}, measureText() { return { width: 24 }; },
    createLinearGradient() { return { addColorStop() {} }; },
  };
  return ctx;
}

const DEVICES = [
  { serial: "A1", model: "Pixel 7", state: "device", ok: true, checked: true },
  { serial: "B2", model: "Pixel 7", state: "device", ok: true, checked: true },
];

function mkEnv(opts) {
  opts = opts || {};
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const calls = [];
  const ctx = fakeCtx();
  let round = 0;
  const pollQueue = (opts.polls || []).slice();

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
            const b = round === 0 ? [{ kind: "devices", payload: { items: DEVICES } }] : [];
            round++;
            return Promise.resolve(b);
          }
          if (k === "perf_start") {
            return Promise.resolve(opts.startRes || {
              ok: true, serial: "A1", interval: 1.0,
              info: { serial: "A1", model: "Pixel 7", pkg: "", android: "13", size: "1080x2340" },
              sessions: {
                A1: { serial: "A1", model: "Pixel 7", pkg: "" },
                B2: { serial: "B2", model: "Pixel 7", pkg: "" },
              },
              failed: {},
            });
          }
          if (k === "perf_poll") {
            const next = pollQueue.shift();
            return Promise.resolve(next || { running: true, samples: [], sessions: {} });
          }
          if (k === "perf_stop") return Promise.resolve({ ok: true, samples: 3 });
          if (k === "perf_export") {
            return Promise.resolve(opts.exportRes || {
              ok: true, html: "/tmp/perf_A1.html", csv: "/tmp/perf_A1.csv",
              rows: 3, sessions: 2, files: [],
            });
          }
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  return { window, calls };
}

const click = (doc, el) => el.dispatchEvent(
  new doc.defaultView.Event("click", { bubbles: true }));
const callsOf = (calls, fn) => calls.filter((c) => c.fn === fn);

const POLL1 = {
  running: true,
  sessions: {
    A1: { running: true, seq: 2, info: { serial: "A1", model: "Pixel 7" },
          samples: [{ seq: 1, t: 1793200000, cpu: 11.0 }, { seq: 2, t: 1793200001, cpu: 12.0 }] },
    B2: { running: true, seq: 1, info: { serial: "B2", model: "Pixel 7" },
          samples: [{ seq: 1, t: 1793200000, cpu: 55.0 }] },
  },
};

(async () => {
  const watchdog = setTimeout(() => {
    console.log("    (看门狗触发：疑似断言抛错导致未收尾，按当前结果退出)");
    process.exit(fail ? 1 : 0);
  }, 30000);

  console.log("\n[1] 多设备：设备位文案与 perf_start 口径");
  {
    const { window, calls } = mkEnv();
    const doc = window.document;
    ok(await waitFor(() => doc.getElementById("perf-start").disabled === false, 3000, "设备就绪"),
       "两台受控设备就绪");
    ok(/等 2 台/.test(doc.getElementById("perf-dev").textContent),
       "设备位显示「当前设备 等 2 台」");
    click(doc, doc.getElementById("perf-start"));
    ok(await waitFor(() => callsOf(calls, "perf_start").length === 1, 3000, "perf_start"),
       "点击后调用 perf_start");
    ok(callsOf(calls, "perf_start")[0].args[0] === null,
       "第一参为 null（由后端取全部受控设备，多台即对比）");
    ok(await waitFor(() => /监控中/.test(doc.getElementById("perf-state").textContent),
                     3000, "状态"),
       "状态行进入「监控中」");

    const legend = doc.getElementById("perf-legend");
    ok(await waitFor(() => legend && legend.hidden === false, 3000, "图例出现"),
       "多设备时图例出现");
    ok(doc.querySelectorAll("#perf-legend .perf-lg").length === 2,
       "图例按设备各一项（2 项）");
  }

  console.log("\n[2] 增量样本按设备归位 + 图例读数");
  {
    const { window, calls } = mkEnv({ polls: [POLL1] });
    const doc = window.document;
    await waitFor(() => doc.getElementById("perf-start").disabled === false, 3000, "设备就绪");
    click(doc, doc.getElementById("perf-start"));
    ok(await waitFor(() => doc.getElementById("perf-v-cpu").textContent === "12", 4000, "A1 读数"),
       "焦点设备（A1）读数取到 12");
    const items = Array.from(doc.querySelectorAll("#perf-legend .perf-lg"));
    ok(items.length === 2, "两台设备各一项图例");
    ok(/12/.test(items[0].textContent) && /55/.test(items[1].textContent),
       "图例分别显示各自最新读数（12 / 55）");
    ok(/Pixel 7/.test(items[0].textContent), "图例显示型号");
    // 第二次 poll 的游标：各设备各自 seq，互不干扰
    await waitFor(() => callsOf(calls, "perf_poll").length >= 2, 4000, "第二次 poll");
    const polls = callsOf(calls, "perf_poll");
    const cursor = polls[polls.length - 1].args[0];
    ok(cursor && cursor.A1 === 2 && cursor.B2 === 1,
       "第二次轮询按设备分别带上游标 {A1:2, B2:1}");

    console.log("\n[3] 点图例切焦点设备");
    // 图例每轮轮询都会重建节点，必须重新查询——点旧引用不会冒泡到容器
    click(doc, doc.querySelectorAll("#perf-legend .perf-lg")[1]);
    ok(await waitFor(() => doc.getElementById("perf-v-cpu").textContent === "55", 3000, "切换"),
       "指标卡读数切到 B2 的 55");
    ok(items[1].classList.contains("on") || doc.querySelectorAll("#perf-legend .perf-lg.on").length === 1,
       "仅一个图例项处于选中态");
  }

  console.log("\n[4] 停止：总点数为各设备之和");
  {
    const { window } = mkEnv({ polls: [POLL1] });
    const doc = window.document;
    await waitFor(() => doc.getElementById("perf-start").disabled === false, 3000, "设备就绪");
    click(doc, doc.getElementById("perf-start"));
    await waitFor(() => doc.getElementById("perf-v-cpu").textContent === "12", 4000, "有数据");
    click(doc, doc.getElementById("perf-stop"));
    ok(await waitFor(() => /已停止/.test(doc.getElementById("perf-state").textContent),
                     3000, "停止文案"),
       "状态行显示已停止");
    ok(/3 个采样点/.test(doc.getElementById("perf-state").textContent),
       "总点数 3（A1 两点 + B2 一点）");
  }

  console.log("\n[5] 多份报告导出提示");
  {
    const { window } = mkEnv({
      polls: [POLL1],
      exportRes: { ok: true, html: "/tmp/perf_A1.html", rows: 3, sessions: 2, files: [] },
    });
    const doc = window.document;
    await waitFor(() => doc.getElementById("perf-start").disabled === false, 3000, "设备就绪");
    click(doc, doc.getElementById("perf-start"));
    await waitFor(() => doc.getElementById("perf-export").disabled === false, 4000, "可导出");
    click(doc, doc.getElementById("perf-export"));
    ok(await waitFor(() => /2 份报告/.test(doc.getElementById("perf-state").textContent),
                     3000, "导出提示"),
       "状态行提示已生成 2 份报告");
  }

  console.log("\n[6] 单设备时图例隐藏（避免无意义噪音）");
  {
    const { window } = mkEnv({
      startRes: {
        ok: true, serial: "A1", interval: 1.0,
        info: { serial: "A1", model: "Pixel 7", pkg: "" },
        sessions: { A1: { serial: "A1", model: "Pixel 7", pkg: "" } },
        failed: {},
      },
      polls: [{ running: true, sessions: { A1: { running: true, seq: 1,
        info: { serial: "A1", model: "Pixel 7" },
        samples: [{ seq: 1, t: 1793200000, cpu: 9.0 }] } } }],
    });
    const doc = window.document;
    await waitFor(() => doc.getElementById("perf-start").disabled === false, 3000, "设备就绪");
    click(doc, doc.getElementById("perf-start"));
    await waitFor(() => doc.getElementById("perf-v-cpu").textContent === "9", 4000, "有数据");
    ok(doc.getElementById("perf-legend").hidden === true,
       "单设备时图例保持隐藏");
  }

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  clearTimeout(watchdog);
  process.exit(fail ? 1 : 0);
})();
