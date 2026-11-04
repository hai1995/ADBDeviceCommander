/* jsdom 前端测试：工具页卡片顺序（投屏默认第三位 + 长按拖动排序 + 持久化）

   回归：
   [0] 默认顺序：截图 → 录屏 → 投屏 → 应用安装 → 诊断包（投屏已挪到录屏下方）；
       每张卡标题栏注入一个拖拽手柄（.tool-grip）。
   [1] 启动按保存顺序恢复：settings.tool_card_order 命中时 DOM 重排成该顺序，
       落盘值里没有的卡（如未来新增）补到末尾。
   [2] 长按手势：标题栏长按需 ≥400ms 才进入拖动态（is-dragging + body.tool-sorting）；
       短按（不等待）不触发拖动，仍是普通折叠点击。
   [3] 拖动中换位 + 松手落盘：stub elementFromPoint 模拟指针扫到目标卡，验证 DOM
       真被重排；松手调用 save_settings 写入 tool_card_order；随后紧跟的 click 被
       toolClickGuard 压制（不会「拖一下卡反而折起」）。 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.join(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "frontend/index.html"), "utf8");
const css = fs.readFileSync(path.join(ROOT, "frontend/css/app.css"), "utf8");
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

function mkEnv(opts) {
  opts = opts || {};
  const overrides = opts.overrides || {};
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const calls = [];
  const queue = [];
  let round = 0;
  window.__push = (ev) => queue.push(ev);
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          calls.push({ fn: k, args });
          if (overrides[k]) return overrides[k].apply(null, args);
          if (k === "boot") {
            return Promise.resolve({ ok: true, version: "v-test", warnings: [], adb: "adb" });
          }
          if (k === "take_events") {
            round++;
            if (round === 1) {
              return Promise.resolve([{ kind: "booted", payload: {
                version: "v-test", warnings: [], commands: [], adb: "adb",
                settings: opts.settings || {},
              } }]);
            }
            return Promise.resolve(queue.splice(0, queue.length));
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

function pointerEvent(window, type, x, y) {
  const ev = new window.Event(type, { bubbles: true });
  Object.defineProperty(ev, "clientX", { value: x });
  Object.defineProperty(ev, "clientY", { value: y });
  Object.defineProperty(ev, "pointerId", { value: 1 });
  return ev;
}

// 工具页卡片（不含顶部「保存目录」那一行）的当前 id 顺序
function toolOrder(doc) {
  return Array.from(
    doc.querySelectorAll('.tab[data-tab="tools"] > .tool-card')
  ).map((c) => c.id);
}

(async () => {
  const watchdog = setTimeout(() => {
    console.log("    (看门狗触发)");
    process.exit(fail ? 1 : 0);
  }, 40000);

  console.log("\n[0] 默认顺序：投屏在录屏下方（第三位），且每张卡有拖拽手柄");
  {
    const { window } = mkEnv();
    const doc = window.document;
    const okReady = await waitFor(() => doc.querySelector('.tab[data-tab="tools"] > .tool-card'), 3000, "就绪");
    ok(okReady, "工具页已渲染");
    const order = toolOrder(doc);
    ok(JSON.stringify(order) ===
       JSON.stringify(["shot-card", "rec-card", "scrcpy-card", "apk-card", "diag-card"]),
       "默认顺序 = 截图→录屏→投屏→安装→诊断（投屏第三位）: " + order.join(","));
    // 5 张卡各注入一个手柄
    const grips = doc.querySelectorAll('.tab[data-tab="tools"] .tool-grip');
    ok(grips.length === 5, "5 张卡各有一个 .tool-grip 手柄（实际 " + grips.length + "）");
    ok(/\.tool-grip\s*\{[^}]*cursor:\s*grab/.test(css), "手柄 cursor: grab（暗示可拖动）");
    ok(/\.tool-card\.is-dragging\s*\{[^}]*z-index:\s*40/.test(css),
       "拖动中的卡抬到最上层（is-dragging z-index:40）");
    ok(/body\.tool-sorting[^{]*\{[^}]*cursor:\s*grabbing/.test(css),
       "拖动进行中整页 cursor: grabbing");
  }

  console.log("\n[1] 启动按保存顺序恢复（tool_card_order 命中即重排）");
  {
    const saved = "diag-card,apk-card,rec-card,scrcpy-card,shot-card";
    const { window } = mkEnv({ settings: { tool_card_order: saved } });
    const doc = window.document;
    const reordered = await waitFor(
      () => JSON.stringify(toolOrder(doc)) === JSON.stringify(saved.split(",")),
      4000, "按保存顺序重排");
    ok(reordered, "DOM 重排成保存顺序: " + toolOrder(doc).join(","));
    // 顺序表外的卡补到末尾：把 shot-card 从表头去掉，它应落在最后
    const { window: w2 } = mkEnv({ settings: { tool_card_order: "apk-card,diag-card" } });
    const d2 = w2.document;
    const r2 = await waitFor(
      () => JSON.stringify(toolOrder(d2)) ===
            JSON.stringify(["apk-card", "diag-card", "shot-card", "rec-card", "scrcpy-card"]),
      4000, "未知卡补末尾");
    ok(r2, "表中没有的卡（shot/rec/scrcpy）补到末尾: " + toolOrder(d2).join(","));
  }

  console.log("\n[2] 长按手势：长按需等待才进拖动态，短按不触发");
  {
    const { window } = mkEnv();
    const doc = window.document;
    await waitFor(() => doc.getElementById("shot-card"), 3000, "就绪");
    const header = doc.querySelector("#shot-card .tool-h--toggle");
    const card = doc.getElementById("shot-card");
    // 短按：down 后立刻 up，不等待长按时限
    header.dispatchEvent(pointerEvent(window, "pointerdown", 10, 10));
    header.dispatchEvent(pointerEvent(window, "pointerup", 10, 10));
    ok(!card.classList.contains("is-dragging"), "短按不进入拖动态");
    ok(!doc.body.classList.contains("tool-sorting"), "短按不挂 tool-sorting");

    // 长按：down 后等待 > 400ms，计时器到点才激活
    header.dispatchEvent(pointerEvent(window, "pointerdown", 10, 10));
    await waitFor(() => card.classList.contains("is-dragging"), 1500, "长按激活");
    ok(card.classList.contains("is-dragging"), "长按 ≥400ms 后进入拖动态");
    ok(doc.body.classList.contains("tool-sorting"), "拖动进行中 body.tool-sorting 挂上");
    header.dispatchEvent(pointerEvent(window, "pointerup", 10, 10));
    ok(!card.classList.contains("is-dragging"), "松手后退出拖动态");
  }

  console.log("\n[3] 拖动换位 + 松手落盘 + 紧随 click 被压制");
  {
    const { window, calls } = mkEnv();
    const doc = window.document;
    await waitFor(() => doc.getElementById("shot-card"), 3000, "就绪");
    const header = doc.querySelector("#shot-card .tool-h--toggle");
    const card = doc.getElementById("shot-card");
    const target = doc.getElementById("diag-card");
    // stub 命中：指针永远落在 diag-card 上 → 把 shot 拖到它后面
    doc.elementFromPoint = () => target;

    const before = toolOrder(doc).join(",");
    header.dispatchEvent(pointerEvent(window, "pointerdown", 10, 10));
    await waitFor(() => card.classList.contains("is-dragging"), 1500, "长按激活");
    window.dispatchEvent(pointerEvent(window, "pointermove", 200, 300));
    const moved = await waitFor(
      () => toolOrder(doc).join(",") === "rec-card,scrcpy-card,apk-card,diag-card,shot-card",
      2000, "拖动换位");
    ok(moved, "拖动后 shot 被移到 diag 之后: " + toolOrder(doc).join(",") + "（前=" + before + "）");

    window.dispatchEvent(pointerEvent(window, "pointerup", 200, 300));
    await sleep(20);
    const saves = calls.filter((c) => c.fn === "save_settings");
    ok(saves.length >= 1, "松手后写入配置");
    const patch = saves[saves.length - 1].args[0] || {};
    ok(patch.tool_card_order === "rec-card,scrcpy-card,apk-card,diag-card,shot-card",
       "落盘 tool_card_order 与拖后顺序一致: " + patch.tool_card_order);

    // 紧随的 click 应被 toolClickGuard 压制：不折起
    ok(!card.classList.contains("collapsed"), "拖动前 shot 卡未折起");
    header.dispatchEvent(new window.Event("click", { bubbles: true }));
    ok(!card.classList.contains("collapsed"), "拖动后的 click 被压制，不折叠");
  }

  console.log("\n[4] 折叠开关仍可用（回归：改动未破坏单击折起）");
  {
    const { window } = mkEnv();
    const doc = window.document;
    await waitFor(() => doc.getElementById("shot-card"), 3000, "就绪");
    const header = doc.querySelector("#shot-card .tool-h--toggle");
    const card = doc.getElementById("shot-card");
    ok(!card.classList.contains("collapsed"), "初始展开");
    header.dispatchEvent(new window.Event("click", { bubbles: true }));
    ok(card.classList.contains("collapsed"), "单击标题栏可折叠");
    header.dispatchEvent(new window.Event("click", { bubbles: true }));
    ok(!card.classList.contains("collapsed"), "再次单击可展开");
  }

  clearTimeout(watchdog);
  console.log("\n" + (fail ? "✗ 有失败" : "✓ 全部通过") +
              "  pass=" + pass + " fail=" + fail);
  process.exit(fail ? 1 : 0);
})();
