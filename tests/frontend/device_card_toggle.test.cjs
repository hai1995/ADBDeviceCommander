/* jsdom 前端行为测试：设备卡片勾选只能下发一次 toggle_device
   回归背景：卡片 click 监听与复选框 change 监听同时绑定，点在复选框上时
   「浏览器已翻转 checked + click 冒泡到卡片」会触发两次 toggle_device
   （同一台设备重复下发、后端重复广播设备列表）。 */
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

async function boot() {
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
  const { window } = dom;
  const calls = [];
  let round = 0;
  const batches = [
    [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [], adb: "adb" } },
     { kind: "devices", payload: { items: [
        { serial: "A1", model: "Pixel", state: "device", ok: true, checked: true },
        { serial: "B2", model: "X10", state: "offline", ok: false, checked: false },
     ] } }],
  ];
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          calls.push({ fn: k, args });
          if (k === "boot") return Promise.resolve({ version: "v-test", warnings: [], commands: [], adb: "adb" });
          if (k === "take_events") { const b = batches[round] || []; round++; return Promise.resolve(b); }
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  return { window, calls };
}

(async () => {
  const { window, calls } = await boot();
  const doc = window.document;
  ok(await waitFor(() => doc.querySelectorAll("#device-list .device-card").length === 2, 4000, "设备卡片"),
     "两台设备卡片已渲染");
  await sleep(150);

  const toggles = () => calls.filter((c) => c.fn === "toggle_device");
  const cardAt = (i) => doc.querySelectorAll("#device-list .device-card")[i];

  console.log("\n[1] 点击复选框本身：只下发一次 toggle_device");
  {
    const cb = cardAt(0).querySelector("input[type='checkbox']");
    ok(cb.checked === true, "复选框初始为已勾选");
    calls.length = 0;
    cb.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    await sleep(80);
    ok(toggles().length === 1,
       "点击复选框只下发 1 次 toggle_device（实际 " + toggles().length + " 次）");
    if (toggles().length) {
      ok(toggles()[0].args[0] === "A1" && toggles()[0].args[1] === false,
         "下发的是 A1 取消勾选（checked=false）");
    }
  }

  console.log("\n[2] 点击卡片空白处：翻转勾选并只下发一次");
  {
    calls.length = 0;
    const card = cardAt(0);
    const cb = card.querySelector("input[type='checkbox']");
    card.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    await sleep(80);
    ok(toggles().length === 1,
       "点击卡片空白处只下发 1 次 toggle_device（实际 " + toggles().length + " 次）");
    ok(cb.checked === true, "卡片点击后复选框翻转为勾选（原为未勾选）");
    if (toggles().length) {
      ok(toggles()[0].args[1] === true, "下发的是勾选（checked=true）");
    }
  }

  console.log("\n[3] 不可操作设备：复选框禁用、卡片点击不下发");
  {
    const cb = cardAt(1).querySelector("input[type='checkbox']");
    ok(cb.disabled === true, "离线设备复选框禁用");
    calls.length = 0;
    cardAt(1).dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    await sleep(80);
    ok(toggles().length === 0, "点击离线设备卡片不下发 toggle_device");
  }

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
