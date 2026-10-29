/* jsdom 前端行为测试：Logcat 页「实时监控 / 落盘抓取」双卡重组 + 打包开关收敛。
   背景（用户要求）：
     1) 取消「超 15M 自动打包zip」——只保留「结束后打包 zip」且默认开启；
     2) 旧布局五段平铺（目录行 + 监控条 + 过滤条 + 抓取条 + 视图），监控与抓取
        混杂难懂，重组为两张视觉独立的卡片。
   本测试锁定：
     - HTML 结构：两张 .lc-card、关键元素各归其卡、#lc-buf 在卡外共享行；
     - 开关语义：#lc-cap-zipstop 默认勾选、#lc-cap-autozip 已不存在、
       app.js 不再引用 lcCapAuto / rolled；
     - 行为：开始/停止抓取下发的参数（防止 autozip 第四参悄悄复活）。 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.join(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "frontend/index.html"), "utf8");
const js = fs.readFileSync(path.join(ROOT, "frontend/js/app.js"), "utf8");
const css = fs.readFileSync(path.join(ROOT, "frontend/css/app.css"), "utf8");

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

/** 打桩 pywebview 桥，记录 capture 相关 API 调用参数供断言。 */
function bootRecording(calls) {
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
  const { window } = dom;
  let round = 0;
  const batches = [
    [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
     { kind: "devices", payload: { items: dev(true) } }],
    [{ kind: "logcat_capture", payload: { status: "running" } }],
  ];
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          calls.push({ api: k, args });
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
  console.log("\n[1] HTML 静态结构：双卡 + 元素归属");
  {
    const dom = new JSDOM(html, { url: "http://localhost/" });
    const doc = dom.window.document;
    const cards = doc.querySelectorAll('.tab[data-tab="logcat"] .lc-card');
    ok(cards.length === 2, "Logcat 页应有两张 .lc-card（监控 / 抓取），实际 %d", cards.length);

    const capCard = cards[0], monCard = cards[1];
    ok(capCard && capCard.querySelector(".lc-card-h") &&
       /落盘抓取/.test(capCard.querySelector(".lc-card-h").textContent),
       "第一张卡是抓取卡（高频操作在上，用户要求）");
    ok(monCard && monCard.classList.contains("grow"), "第二张卡是监控卡（grow，吃满剩余高度）");
    ok(monCard && monCard.querySelector(".lc-card-h") &&
       /实时监控/.test(monCard.querySelector(".lc-card-h").textContent),
       "监控卡标题为「实时监控」");

    // 监控卡：控制条 + 过滤条 + 日志视图都在卡内
    for (const id of ["lc-start", "lc-stop", "lc-clear", "lc-save", "lc-status",
                      "lc-counter", "lc-filter", "lc-levels", "lc-only-exc",
                      "lc-autoscroll", "lc-view"]) {
      ok(monCard && monCard.querySelector("#" + id) !== null,
         "监控元素 #%s 位于监控卡内", id);
    }
    // 抓取卡：开关 + 开始/停止 + 状态都在卡内
    for (const id of ["lc-cap-zipstop", "lc-cap-start", "lc-cap-stop", "lc-cap-status"]) {
      ok(capCard && capCard.querySelector("#" + id) !== null,
         "抓取元素 #%s 位于抓取卡内", id);
    }
    // 缓冲区是共用输入：在卡外（顶部共享行）
    const buf = doc.getElementById("lc-buf");
    ok(buf !== null, "#lc-buf 存在");
    ok(buf && !monCard.contains(buf) && !capCard.contains(buf),
       "#lc-buf 在两张卡之外（监控/抓取共用）");
    ok(monCard && monCard.querySelector("#lc-buf") === null,
       "监控卡内不应再出现缓冲区选择（避免共用设置归属含混）");
    // 视图只属于监控卡（抓取不渲染）
    ok(capCard && capCard.querySelector("#lc-view") === null,
       "抓取卡内不应出现日志视图");
  }

  console.log("\n[2] 开关语义：只留「结束后打包 zip」且默认开启");
  {
    const dom = new JSDOM(html, { url: "http://localhost/" });
    const doc = dom.window.document;
    ok(doc.getElementById("lc-cap-autozip") === null, "#lc-cap-autozip 已移除");
    const zipstop = doc.getElementById("lc-cap-zipstop");
    ok(zipstop !== null && zipstop.checked === true, "#lc-cap-zipstop 默认勾选");
    ok(!/lcCapAuto/.test(js), "app.js 不再引用 lcCapAuto");
    ok(!/"rolled"/.test(js) && !/status === "rolled"/.test(js),
       "app.js 不再处理 rolled 分包事件");
    ok(/\.lc-card\b/.test(css) && /\.lc-card\.grow/.test(css),
       "app.css 定义了 .lc-card / .lc-card.grow 规则");
    ok(/\.lc-card \.lc-ctrls/.test(css), "app.css 对卡内控制条做了去盒化");
  }

  console.log("\n[3] 行为：抓取参数不再携带 autozip");
  {
    const calls = [];
    const window = bootRecording(calls);
    const doc = window.document;
    ok(await waitFor(() => doc.getElementById("lc-cap-start").disabled === false, 4000, "初始可点"),
       "有受控设备时「开始抓取」初始可点");
    doc.getElementById("lc-cap-start").click();
    await sleep(50);
    const startCall = calls.find((c) => c.api === "logcat_capture_start");
    ok(startCall !== undefined, "点击后调用了 logcat_capture_start");
    ok(startCall && startCall.args.length === 4,
       "logcat_capture_start 收 4 个参数（serial/目录/缓冲区/级别数组），实际 %d",
       startCall ? startCall.args.length : -1);
    ok(startCall && Array.isArray(startCall.args[2]),
       "第三参数为缓冲区数组：%r", startCall ? startCall.args[2] : null);
    ok(startCall && Array.isArray(startCall.args[3]) && startCall.args[3].length === 6,
       "第四参数为级别数组，默认全选 V/D/I/W/E/F 共 6 级：%r",
       startCall ? startCall.args[3] : null);

    // 抓取中（running 事件）才允许点停止——与真实时序一致
    ok(await waitFor(() => doc.getElementById("lc-cap-stop").disabled === false, 4000, "停止可点"),
       "running 事件后「停止抓取」可点");
    doc.getElementById("lc-cap-stop").click();
    await sleep(50);
    const stopCall = calls.find((c) => c.api === "logcat_capture_stop");
    ok(stopCall !== undefined, "点击后调用了 logcat_capture_stop");
    ok(stopCall && stopCall.args[1] === true,
       "默认勾选状态下停止抓取下发 zip_on_stop=true，实际 %r",
       stopCall ? stopCall.args[1] : null);
  }

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
