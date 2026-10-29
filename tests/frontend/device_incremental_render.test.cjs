/* jsdom 前端行为测试：设备列表增量渲染 + 宽限期「重连中」展示
   —— 刷新时复用卡片 DOM 节点（不全量重建），且不会因更新重复绑定事件
      （点了卡片只下发一次 toggle_device）；
   —— 宽限内设备以置灰卡片继续展示（state=reconnecting），不瞬间消失；
   —— 真正 gone（不在 items 里）才移除卡片；空列表有提示行。 */
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

async function boot(events) {
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
  const { window } = dom;
  const queue = events.slice();
  const calls = [];
  const apiStub = new Proxy({}, {
    get(t, k) {
      if (k === "then") return undefined;
      return function (...args) {
        calls.push({ fn: String(k), args });
        if (k === "boot") return Promise.resolve({ ok: true });
        if (k === "take_events") return Promise.resolve(queue.splice(0, queue.length));
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

const BOOT = { kind: "booted", payload: { version: "v-test", warnings: [], commands: [], state_labels: { reconnecting: "短暂失联（重连中）" } } };
const dev = (serial, extra) => Object.assign({
  serial, model: "Pixel", state: "device", ok: true, checked: true,
}, extra || {});

(async () => {
  console.log("\n[1] 首刷两张卡；再刷相同列表应复用同一批 DOM 节点");
  const t = await boot([
    BOOT,
    { kind: "devices", payload: { items: [dev("A1"), dev("B2", { checked: false })] } },
  ]);
  const doc = t.window.document;
  ok(await waitFor(() => doc.querySelectorAll("#device-list .device-card").length === 2, 3000, "两张卡"),
     "两台设备卡片已渲染");
  const cardA = doc.querySelectorAll("#device-list .device-card")[0];
  const cardB = doc.querySelectorAll("#device-list .device-card")[1];

  // 同样内容再推一次（模拟自动轮询的 devices 事件）：节点必须原样复用
  t.push({ kind: "devices", payload: { items: [dev("A1"), dev("B2", { checked: false })] } });
  await sleep(250);
  const cardA2 = doc.querySelectorAll("#device-list .device-card")[0];
  ok(cardA2 === cardA, "无变化刷新复用同一卡片节点（未整表重建）");

  console.log("\n[2] 勾选态变化只更新属性，且不重复绑定事件（点卡片只下发一次）");
  t.push({ kind: "devices", payload: { items: [dev("A1"), dev("B2", { checked: true })] } });
  await sleep(250);
  ok(cardB.classList.contains("selected"), "B2 勾选后卡片带 selected 样式");
  t.calls.length = 0;
  cardB.dispatchEvent(new t.window.MouseEvent("click", { bubbles: true }));
  await sleep(120);
  const toggles = t.calls.filter((c) => c.fn === "toggle_device");
  ok(toggles.length === 1, "更新后的卡片点击只下发 1 次 toggle_device（实际 " + toggles.length + " 次）");
  ok(toggles.length && toggles[0].args[0] === "B2" && toggles[0].args[1] === false,
     "下发的是 B2 取消勾选");

  console.log("\n[3] 宽限期设备（reconnecting）置灰保留，不瞬间消失");
  t.push({ kind: "devices", payload: { items: [
    dev("A1"),
    { serial: "B2", model: "X10", state: "reconnecting", ok: false, checked: true },
  ] } });
  await sleep(250);
  const cards = doc.querySelectorAll("#device-list .device-card");
  ok(cards.length === 2, "B2 宽限内仍展示（实际 " + cards.length + " 张卡）");
  const b2 = cards[1];
  ok(b2.classList.contains("off"), "宽限卡片置灰（off）");
  ok(b2.querySelector(".dot").className.includes("wait"), "圆点为重连中样式（wait）");
  ok(b2.querySelector("input[type='checkbox']").disabled === true, "复选框禁用");
  ok(/重连中/.test(b2.textContent), "状态文案含「重连中」");
  ok(b2.querySelector(".meta").textContent === "X10", "保留最后已知型号 X10");
  ok(b2.classList.contains("selected"), "宽限内保留勾选样式");

  console.log("\n[4] 真正 gone（不在 items）才移除卡片；空列表有提示行");
  t.push({ kind: "devices", payload: { items: [dev("A1")] } });
  ok(await waitFor(() => doc.querySelectorAll("#device-list .device-card").length === 1, 3000, "剩 1 张卡"),
     "gone 设备卡片被移除");
  t.push({ kind: "devices", payload: { items: [] } });
  ok(await waitFor(() => doc.querySelectorAll("#device-list .device-card").length === 0, 3000, "空列表"),
     "空列表无卡片");
  ok(/无已连接设备/.test(doc.getElementById("device-list").textContent), "空列表显示提示行");

  console.log("\n==============================================");
  console.log("结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
