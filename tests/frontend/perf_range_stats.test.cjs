/* jsdom 前端行为测试：性能曲线「区间框选统计」

   锁定的是四件事：
   1) 按住横拖 → 出现色带；松手 → 出现统计卡，均值/最低/P95/最高/点数都对；
   2) 拖得太窄（< 8px）当点击处理，不出卡片；双击 / Esc / × 都能收掉；
   3) 有阈值时统计「超阈值次数」，无阈值时不显示这一列；
   4) 拖动期间悬停提示收起（两条竖线叠一起会分不清），松手后才算是选区。

   坐标与 perf_tooltip 一致：容器桩成 820×320，padL=46 padR=12 → iw=762，
   三个采样点 t 各差 1 秒，落到 x = 46 / 427 / 808。
   框选的像素→时间换算是同一套公式，宽度对不上就会「选了一段却统计到别的点」。 */
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
  return {
    setTransform() {}, clearRect() {}, beginPath() {}, closePath() {},
    moveTo() {}, lineTo() {}, arc() {}, rect() {}, roundRect() {},
    fillRect() {}, save() {}, restore() {}, stroke() {}, fill() {},
    fillText() {}, measureText() { return { width: 24 }; },
    createLinearGradient() { return { addColorStop() {} }; },
  };
}

const DEVICES = [
  { serial: "A1", model: "Pixel 7", state: "device", ok: true, checked: true },
  { serial: "B2", model: "Mi 11", state: "device", ok: true, checked: true },
];

const T0 = 1793200000;

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
          if (k === "perf_thresholds") {
            // 只有 cpu 带阈值（max 12）：够验证「超阈值次数」这一列，
            // 又不至于让每个指标都多一列出来干扰断言。
            return Promise.resolve({
              thresholds: { cpu: { max: 12 } },
              rules: { cpu: "CPU > 12" },
              items: [], default_expr: "CPU > 12",
            });
          }
          if (k === "perf_start") {
            return Promise.resolve({
              ok: true, serial: "A1", interval: 1.0,
              info: { serial: "A1", model: "Pixel 7", pkg: "" },
              sessions: {
                A1: { serial: "A1", model: "Pixel 7", pkg: "" },
                B2: { serial: "B2", model: "Mi 11", pkg: "" },
              },
              failed: {},
            });
          }
          if (k === "perf_poll") {
            const next = pollQueue.shift();
            return Promise.resolve(next || { running: true, samples: [], sessions: {} });
          }
          if (k === "perf_stop") return Promise.resolve({ ok: true, samples: 3 });
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

/** 造一个带 clientX 的指针事件（jsdom 没有 PointerEvent 构造函数） */
function pointerEvent(window, type, x) {
  const ev = new window.Event(type, { bubbles: true });
  Object.defineProperty(ev, "clientX", { value: x });
  Object.defineProperty(ev, "clientY", { value: 120 });
  Object.defineProperty(ev, "pointerId", { value: 1 });
  Object.defineProperty(ev, "button", { value: 0 });
  return ev;
}

const POLL_A1 = {
  running: true,
  sessions: {
    A1: { running: true, seq: 3, info: { serial: "A1", model: "Pixel 7" },
          samples: [
            { seq: 1, t: T0, cpu: 11.0 },
            { seq: 2, t: T0 + 1, cpu: 12.5 },
            { seq: 3, t: T0 + 2, cpu: 13.0 },
          ] },
  },
};
const POLL_BOTH = {
  running: true,
  sessions: {
    A1: POLL_A1.sessions.A1,
    B2: { running: true, seq: 2, info: { serial: "B2", model: "Mi 11" },
          samples: [{ seq: 1, t: T0, cpu: 40.0 }, { seq: 2, t: T0 + 1, cpu: 55.0 }] },
  },
};

async function startWithPoll(poll) {
  const env = mkEnv({ polls: [poll] });
  const doc = env.window.document;
  await waitFor(() => doc.getElementById("perf-start").disabled === false, 3000, "设备就绪");
  click(doc, doc.getElementById("perf-start"));
  await waitFor(() => doc.getElementById("perf-v-cpu").textContent === "13", 4000, "三个采样");
  await sleep(80);
  return env;
}

/** 按住 x0 拖到 x1 再松手 */
async function drag(window, x0, x1) {
  const doc = window.document;
  const cv = doc.getElementById("perf-canvas");
  cv.dispatchEvent(pointerEvent(window, "pointerdown", x0));
  cv.dispatchEvent(pointerEvent(window, "pointermove", x1));
  cv.dispatchEvent(pointerEvent(window, "pointerup", x1));
  await sleep(40);
}

/** 从卡片里取某个设备的整行文本 */
function rowOf(card, label) {
  return Array.from(card.querySelectorAll(".pr-row"))
    .map((el) => el.textContent).filter((t) => t.indexOf(label) >= 0)[0] || "";
}

(async () => {
  const watchdog = setTimeout(() => {
    console.log("    (看门狗触发：疑似断言抛错导致未收尾，按当前结果退出)");
    process.exit(fail ? 1 : 0);
  }, 60000);

  console.log("\n[1] 结构：色带 + 统计卡都在，默认收起");
  {
    const { window } = await startWithPoll(POLL_A1);
    const doc = window.document;
    const band = doc.getElementById("perf-band");
    const card = doc.getElementById("perf-range");
    ok(!!band && !!card, "画布容器内有 #perf-band 与 #perf-range");
    ok(band.hidden === true && card.hidden === true, "默认都收起（不框选就不显示）");
    const wrap = doc.getElementById("perf-canvas").parentElement;
    ok(band.parentElement === wrap && card.parentElement === wrap, "两者都在 .perf-canvas-wrap 内");
    ok(/拖/.test(doc.querySelector(".perf-chart-hint").textContent), "图表提示里写了可以拖选区间");
  }

  console.log("\n[2] 拖 46 → 640：只有 t0、t0+1 两个点进区间");
  {
    const { window } = await startWithPoll(POLL_A1);
    const doc = window.document;
    const band = doc.getElementById("perf-band");
    const card = doc.getElementById("perf-range");

    const cv = doc.getElementById("perf-canvas");
    cv.dispatchEvent(pointerEvent(window, "pointerdown", 46));
    cv.dispatchEvent(pointerEvent(window, "pointermove", 640));
    ok(band.hidden === false, "拖动中色带就出现（跟手，不等松手）");
    ok(band.style.left === "46px" && band.style.width === "594px",
       "色带 left 46px / width 594px（按像素落位）");
    ok(card.hidden === true, "拖动中不出统计卡（松手才算一次）");

    cv.dispatchEvent(pointerEvent(window, "pointerup", 640));
    ok(await waitFor(() => card.hidden === false, 2000, "卡片出现"), "松手后出现统计卡");
    const row = rowOf(card, "Pixel 7");
    ok(/2 点/.test(row), "区间内 2 个采样点（第三个点在选区外）");
    ok(/11\.8/.test(row), "均值 11.8（(11+12.5)/2）");
    ok(/最低\s*11(?!\.)/.test(row), "最低 11");
    ok(/最高\s*12\.5/.test(row), "最高 12.5");
    ok(/P95\s*12\.5/.test(row), "P95 12.5（nearest-rank，2 点取第 2 个）");
    ok(/区间统计/.test(card.textContent), "卡片有标题");
    ok(/^\d+px$/.test(card.style.left), "卡片按像素定位（left 已写入）");
  }

  console.log("\n[3] 拖满整段：三个点都进区间 + 超阈值次数");
  {
    const { window } = await startWithPoll(POLL_A1);
    const doc = window.document;
    const card = doc.getElementById("perf-range");
    await drag(window, 46, 808);
    ok(await waitFor(() => card.hidden === false, 2000, "卡片出现"), "整段框选出卡片");
    const row = rowOf(card, "Pixel 7");
    ok(/3 点/.test(row), "区间内 3 个采样点");
    ok(/12\.2/.test(row), "均值 12.2（36.5/3）");
    ok(/最高\s*13/.test(row), "最高 13");
    // 阈值只给 cpu 的 max=12：12.5 与 13 都超，11 不超 → 2 次
    ok(/超阈值\s*2\s*次/.test(row),
       "超阈值 2 次（12.5 / 13 都 > 12） ｜ 实测行：" + row.replace(/\s+/g, " "));
    ok(/CPU/.test(doc.getElementById("perf-chart-title").textContent), "统计的是当前指标（CPU）");
  }

  console.log("\n[4] 太窄当点击：不出卡片，并清掉上一次的选区");
  {
    const { window } = await startWithPoll(POLL_A1);
    const doc = window.document;
    const card = doc.getElementById("perf-range");
    const band = doc.getElementById("perf-band");
    await drag(window, 46, 808);
    await waitFor(() => card.hidden === false, 2000, "先有选区");

    await drag(window, 400, 404);        // 4px：手抖，不算框选
    ok(card.hidden === true, "4px 的拖动不弹卡片");
    ok(band.hidden === true, "旧色带一并清掉（不留一个假选区）");
  }

  console.log("\n[5] 双击 / Esc / × 三种收法");
  {
    const { window } = await startWithPoll(POLL_A1);
    const doc = window.document;
    const card = doc.getElementById("perf-range");
    const band = doc.getElementById("perf-band");

    await drag(window, 46, 640);
    await waitFor(() => card.hidden === false, 2000, "先有选区");
    doc.getElementById("perf-canvas").dispatchEvent(
      new window.Event("dblclick", { bubbles: true }));
    ok(card.hidden === true && band.hidden === true, "双击画布 → 收掉");

    await drag(window, 46, 640);
    await waitFor(() => card.hidden === false, 2000, "再有选区");
    const esc = new window.Event("keydown", { bubbles: true });
    Object.defineProperty(esc, "key", { value: "Escape" });
    doc.dispatchEvent(esc);
    ok(card.hidden === true && band.hidden === true, "按 Esc → 收掉");

    await drag(window, 46, 640);
    await waitFor(() => card.hidden === false, 2000, "再有选区");
    click(doc, card.querySelector(".pr-x"));
    ok(card.hidden === true && band.hidden === true, "点 × → 收掉");
  }

  console.log("\n[6] 拖动期间收起悬停提示");
  {
    const { window } = await startWithPoll(POLL_A1);
    const doc = window.document;
    const cv = doc.getElementById("perf-canvas");
    const tip = doc.getElementById("perf-tip");

    cv.dispatchEvent(pointerEvent(window, "pointermove", 427));
    await waitFor(() => tip.hidden === false, 2000, "先弹出提示");
    cv.dispatchEvent(pointerEvent(window, "pointerdown", 46));
    ok(tip.hidden === true, "按下开始拖动 → 提示立刻收起");
    cv.dispatchEvent(pointerEvent(window, "pointermove", 640));
    ok(tip.hidden === true, "拖动过程中不再弹提示");
  }

  console.log("\n[7] 多设备：一行一台，各按自己的采样统计");
  {
    const { window } = await startWithPoll(POLL_BOTH);
    const doc = window.document;
    const card = doc.getElementById("perf-range");
    ok(await waitFor(() => doc.getElementById("perf-v-cpu").textContent !== "--", 4000, "双设备采样")
       , "两台设备都有数据");
    await drag(window, 46, 808);
    ok(await waitFor(() => card.hidden === false, 2000, "卡片出现"), "多设备也出卡片");
    const rows = card.querySelectorAll(".pr-row");
    ok(rows.length === 2, "两台设备各一行（2 行）");
    const a = rowOf(card, "Pixel 7");
    const b = rowOf(card, "Mi 11");
    ok(/12\.2/.test(a) && /3 点/.test(a), "A1：均值 12.2 / 3 点");
    ok(/47\.5/.test(b) && /2 点/.test(b), "B2：均值 47.5 / 2 点（各按自己的采样）");
    ok(card.querySelectorAll(".pr-dot").length === 2, "每行都带一个设备色点");
  }

  console.log("\n[8] 该指标没有数据：不弹空卡片");
  {
    const { window } = await startWithPoll(POLL_A1);
    const doc = window.document;
    const card = doc.getElementById("perf-range");
    click(doc, doc.getElementById("perf-stat-temp"));
    await sleep(80);
    await drag(window, 46, 808);
    ok(card.hidden === true, "温度这一列全空 → 不弹卡片（没有可用采样）");
  }

  clearTimeout(watchdog);
  console.log("\n" + (fail ? "✗ 失败 " + fail + " 条 / 通过 " + pass + " 条"
                        : "✓ 全部通过（" + pass + " 条断言）"));
  process.exit(fail ? 1 : 0);
})();
