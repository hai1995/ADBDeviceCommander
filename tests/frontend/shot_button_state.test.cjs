/* jsdom 前端行为测试：「立即截图」按钮的在途禁用 / 恢复
   —— 点击即禁用（截图耗时以秒计，禁用是最直观的"在跑了"反馈，也防连点）；
      shot_state running=true 期间保持禁用，running=false 恢复；
      后端直接拒绝（ok:false）时按调用结果就地恢复，绝不把按钮锁死；
      禁用态下的重复点击被拦截，不重复下发。 */
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

/** 每轮 take_events 消费一批（与真实轮询一致）；shotResult 控制 screenshot 的返回。 */
async function boot(batches, shotResult) {
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
  const { window } = dom;
  let round = 0;
  const shotCalls = [];
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          if (k === "boot") {
            return Promise.resolve({ version: "v-test", warnings: [], commands: [], adb: "adb" });
          }
          if (k === "take_events") {
            const b = batches[round] || []; round++; return Promise.resolve(b);
          }
          if (k === "screenshot") { shotCalls.push(args); return Promise.resolve(shotResult); }
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  await sleep(600);   // 等 start() -> bindUI + boot + 首轮事件消费完
  return { window, shotCalls, rounds: () => round };
}

const bootBatch = () => ([
  { kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
  { kind: "devices", payload: { items: dev(true) } },
]);

(async () => {
  console.log("\n[1] 点击即禁用；running=true 保持；running=false 恢复；禁击中再点不重复下发");
  {
    const batches = [
      bootBatch(),
      [{ kind: "shot_state", payload: { running: true } }],
      [{ kind: "shot_state", payload: { running: false } }],
    ];
    const { window, shotCalls, rounds } = await boot(batches, { ok: true });
    const doc = window.document;
    const btn = doc.getElementById("tool-shot");
    ok(!btn.disabled, "前提：有勾选设备时按钮可用");

    btn.dispatchEvent(new window.Event("click"));
    ok(btn.disabled === true, "点击后按钮立即禁用（同步生效，不等后端事件）");
    ok(shotCalls.length === 1, "点击下发了 screenshot 调用");
    ok(shotCalls[0][0] === null, "serial 传 null（由后端取全部勾选设备）");

    // 禁用态下的重复点击：被守卫拦截，不重复下发
    btn.dispatchEvent(new window.Event("click"));
    await sleep(120);
    ok(shotCalls.length === 1, "禁用态下的重复点击被拦截（实际下发 " + shotCalls.length + " 次）");

    // running=true：在途中保持禁用
    ok(await waitFor(() => rounds() >= 2, 4000, "true 事件被消费"), "shot_state(true) 事件被轮询消费");
    await sleep(80);
    ok(btn.disabled === true, "shot_state running=true 期间按钮保持禁用");

    // running=false：恢复
    ok(await waitFor(() => rounds() >= 3, 4000, "false 事件被消费"), "shot_state(false) 事件被轮询消费");
    ok(await waitFor(() => !btn.disabled, 4000, "false 后恢复"), "shot_state running=false 后按钮恢复可用");
    window.close();
  }

  console.log("\n[2] 后端直接拒绝（ok:false）：按钮按调用结果恢复，不锁死");
  {
    const { window, shotCalls } = await boot(
      [bootBatch()], { ok: false, reason: "no_device" });
    const btn = window.document.getElementById("tool-shot");
    btn.dispatchEvent(new window.Event("click"));
    ok(btn.disabled === true, "点击后同样先禁用");
    ok(await waitFor(() => !btn.disabled, 4000, "拒绝后恢复"),
       "后端返回 ok:false 时按钮恢复（未勾选设备等场景不锁死）");
    ok(shotCalls.length === 1, "拒绝路径也只下发一次");
    window.close();
  }

  console.log("\n[3] 无勾选设备：按钮保持禁用，点击不触达后端");
  {
    const { window, shotCalls } = await boot(
      [[{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
        { kind: "devices", payload: { items: dev(false) } }]], { ok: true });
    const btn = window.document.getElementById("tool-shot");
    ok(btn.disabled === true, "无勾选设备时按钮禁用");
    btn.dispatchEvent(new window.Event("click"));
    await sleep(120);
    ok(shotCalls.length === 0, "禁用态点击不触达后端（实际 " + shotCalls.length + " 次）");
    window.close();
  }

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
