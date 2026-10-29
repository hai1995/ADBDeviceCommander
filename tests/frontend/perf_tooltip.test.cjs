/* jsdom 前端行为测试：性能曲线「悬停提示（tooltip）」

   锁定的是三件事：
   1) 指针落在某条曲线的采样点上 → 出现竖线 + 数值卡片，数字/单位/设备名都对；
   2) 指针离开命中范围（> 26px）或移出画布 → 卡片收起，不残留一张老数值；
   3) 多设备时一行一台设备，各取自己离指针最近的采样点。

   jsdom 无 canvas / 无布局：画布上下文按 perf_multi_device 的做法桩掉（本测试
   根本不看画布绘制），尺寸靠 clientWidth/clientHeight 桩成 820×320 ——
   提示的命中判定用的是同一套坐标，宽度对不上就会「看着在点上却没提示」。 */
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
  return ev;
}

// 三个采样点：t 各差 1 秒，画布 820 宽 → x = 46 / 427 / 808
const T0 = 1793200000;
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

function clockOf(t) {
  const d = new Date(t * 1000);
  const p2 = (n) => (n < 10 ? "0" + n : String(n));
  return p2(d.getHours()) + ":" + p2(d.getMinutes()) + ":" + p2(d.getSeconds());
}

async function startWithPoll(poll) {
  const env = mkEnv({ polls: [poll] });
  const doc = env.window.document;
  await waitFor(() => doc.getElementById("perf-start").disabled === false, 3000, "设备就绪");
  click(doc, doc.getElementById("perf-start"));
  // 采样点进来后要等一帧重绘：几何信息（perfGeom）是在绘制里写入的
  await waitFor(() => doc.getElementById("perf-v-cpu").textContent === "13", 4000, "三个采样");
  await sleep(80);
  return env;
}

(async () => {
  const watchdog = setTimeout(() => {
    console.log("    (看门狗触发：疑似断言抛错导致未收尾，按当前结果退出)");
    process.exit(fail ? 1 : 0);
  }, 40000);

  console.log("\n[1] 悬停到采样点上：竖线 + 数值卡片");
  {
    const { window } = await startWithPoll(POLL_A1);
    const doc = window.document;
    const cv = doc.getElementById("perf-canvas");
    const tip = doc.getElementById("perf-tip");
    const cross = doc.getElementById("perf-cross");

    ok(!!tip && !!cross, "画布容器内有 #perf-tip 与 #perf-cross");
    ok(tip.hidden === true, "默认收起（不悬停就不显示）");

    cv.dispatchEvent(pointerEvent(window, "pointermove", 427));
    ok(await waitFor(() => tip.hidden === false, 2000, "提示出现"), "指针落在中点 → 提示出现");
    ok(/12\.5/.test(tip.textContent), "数值取最近的采样点（12.5）");
    ok(/%/.test(tip.textContent), "带单位（%）");
    ok(tip.textContent.indexOf("Pixel 7") >= 0, "带设备名（Pixel 7）");
    ok(tip.textContent.indexOf(clockOf(T0 + 1)) >= 0, "带时间（与横轴同一格式）");
    ok(cross.hidden === false, "竖线出现");
    ok(cross.style.left === "427px", "竖线落在命中点的 x 上（427px）");
    ok(/^\d+px$/.test(tip.style.left) && /^\d+px$/.test(tip.style.top),
       "卡片按像素定位（left/top 已写入）");
  }

  console.log("\n[2] 离开命中范围 / 移出画布：收起，不残留老数值");
  {
    const { window } = await startWithPoll(POLL_A1);
    const doc = window.document;
    const cv = doc.getElementById("perf-canvas");
    const tip = doc.getElementById("perf-tip");
    const cross = doc.getElementById("perf-cross");

    cv.dispatchEvent(pointerEvent(window, "pointermove", 427));
    await waitFor(() => tip.hidden === false, 2000, "先出现");

    // 距最近点 74px（> 26px 容差）：空白处不该弹卡片，否则挡住曲线
    cv.dispatchEvent(pointerEvent(window, "pointermove", 120));
    ok(await waitFor(() => tip.hidden === true, 2000, "容差外收起"), "距最近采样点 74px → 收起");
    ok(cross.hidden === true, "竖线一并收起");

    cv.dispatchEvent(pointerEvent(window, "pointermove", 427));
    await waitFor(() => tip.hidden === false, 2000, "再次出现");
    // pointerleave 不冒泡，浏览器是「指针离开容器时」直接发在容器上，
    // 这里照同样的语义投递到画布的父容器（.perf-canvas-wrap）
    cv.parentElement.dispatchEvent(new window.Event("pointerleave"));
    ok(await waitFor(() => tip.hidden === true, 2000, "pointerleave 收起"),
       "指针移出画布 → 收起");
  }

  console.log("\n[3] 多设备：一行一台，各取最近的采样点");
  {
    const { window } = await startWithPoll(POLL_BOTH);
    const doc = window.document;
    const cv = doc.getElementById("perf-canvas");
    const tip = doc.getElementById("perf-tip");

    cv.dispatchEvent(pointerEvent(window, "pointermove", 427));
    ok(await waitFor(() => tip.hidden === false, 2000, "提示出现"), "多设备也能弹提示");
    const rows = tip.querySelectorAll(".pt-row");
    ok(rows.length === 2, "两台设备各一行（2 行）");
    ok(/12\.5/.test(rows[0].textContent) && /Pixel 7/.test(rows[0].textContent),
       "A1 行：Pixel 7 / 12.5");
    // B2 只有两个点（t0、t0+1）：x=427 落在它自己的中点 46..808 上，对应 55
    ok(/55/.test(rows[1].textContent) && /Mi 11/.test(rows[1].textContent),
       "B2 行：Mi 11 / 55（按各自采样点取最近）");
    ok(tip.querySelectorAll(".pt-dot").length === 2, "每行都带一个设备色点");
  }

  console.log("\n[4] 该指标还没有数据：不弹空卡片");
  {
    const { window } = await startWithPoll(POLL_A1);
    const doc = window.document;
    const cv = doc.getElementById("perf-canvas");
    const tip = doc.getElementById("perf-tip");
    click(doc, doc.getElementById("perf-stat-temp"));
    await sleep(80);
    cv.dispatchEvent(pointerEvent(window, "pointermove", 427));
    // 温度没有采样值：这一列全空 → 没有可命中的点，提示应保持收起
    ok(tip.hidden === true, "该指标尚无数据 → 不弹空卡片");
  }

  clearTimeout(watchdog);
  console.log("\n==============================================");
  console.log("结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
