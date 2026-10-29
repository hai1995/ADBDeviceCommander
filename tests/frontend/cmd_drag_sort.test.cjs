/* jsdom 前端行为测试：指令卡「长按拖动排序」

   为什么单独一份：这件事有三条硬约束，任何一条破了都比「排不了序」更糟 ——
   1) 短按仍然是「执行命令」，不能被拖动逻辑吞掉；
   2) 长按拖动松手后浏览器补发的那一下 click 必须被吃掉，否则「排个序」会顺手
      把那台设备上的命令真的执行一遍；
   3) 顺序要落盘（config.json 的 cmd_order）并在下次启动时原样恢复，
      没被拖过的分组继续按点击频次自动排（常用靠前），不能被一次性冻死。 */
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
  const ctx = {};
  ["setTransform", "clearRect", "beginPath", "closePath", "moveTo", "lineTo",
   "arc", "rect", "roundRect", "fillRect", "save", "restore", "stroke", "fill",
   "fillText", "strokeText"].forEach((k) => { ctx[k] = () => {}; });
  ctx.measureText = () => ({ width: 24 });
  ctx.createLinearGradient = () => ({ addColorStop() {} });
  return ctx;
}

// 两张芯片一行排开：每张 100 宽、间距 0 → 中线在 50，clientX 80 即「落在右半边」
const RECT = { left: 0, right: 100, top: 0, bottom: 24, width: 100, height: 24, x: 0, y: 0 };

function mkEnv(opts) {
  opts = opts || {};
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const calls = [];
  const settings = opts.settings || {};
  const commands = opts.commands || [
    { id: "a", name: "A 命令", labels: ["其他"], commands: [{ command: "adb shell date" }], clickCount: 9 },
    { id: "b", name: "B 命令", labels: ["其他"], commands: [{ command: "adb shell ls" }], clickCount: 5 },
    { id: "c", name: "C 命令", labels: ["其他"], commands: [{ command: "adb shell whoami" }], clickCount: 1 },
  ];
  let round = 0;
  const batches = [[
    { kind: "booted",
      payload: { version: "v-test", warnings: [], adb: "adb",
                 commands: commands, settings: settings } },
    { kind: "devices",
      payload: { items: [{ serial: "S1", model: "Pixel 7", state: "device",
                           ok: true, checked: true }] } },
  ]];

  window.HTMLCanvasElement.prototype.getContext = () => fakeCtx();
  Object.defineProperty(window.HTMLElement.prototype, "clientWidth",
    { configurable: true, get() { return 820; } });
  Object.defineProperty(window.HTMLElement.prototype, "clientHeight",
    { configurable: true, get() { return 320; } });
  window.Element.prototype.getBoundingClientRect = () => RECT;

  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          calls.push({ fn: k, args });
          if (k === "boot") {
            return Promise.resolve({ version: "v-test", warnings: [],
                                     commands: commands, adb: "adb",
                                     settings: settings });
          }
          if (k === "take_events") {
            const b = batches[round] || []; round++;
            return Promise.resolve(b);
          }
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState",
    { value: "complete", configurable: true });
  window.eval(js);
  return { window, calls };
}

const callsOf = (calls, fn) => calls.filter((c) => c.fn === fn);
const savedPatch = (calls, key) => {
  const hit = callsOf(calls, "save_settings").filter((c) => c.args[0] && key in c.args[0]);
  return hit.length ? hit[hit.length - 1].args[0][key] : undefined;
};
const chips = (doc) => Array.from(doc.querySelectorAll("#cmd-groups .cmd-chip"));
const chipIds = (doc) => chips(doc).map((el) => el.dataset.cmdId);
const chipOf = (doc, id) => doc.querySelector('.cmd-chip[data-cmd-id="' + id + '"]');
const pointer = (window, type, target, clientX) => {
  const ev = new window.MouseEvent(type, {
    bubbles: true, cancelable: true, clientX: clientX == null ? 10 : clientX, clientY: 10, button: 0,
  });
  (target || window).dispatchEvent(ev);
};
const clickChip = (window, el) => {
  el.dispatchEvent(new window.MouseEvent("click", { bubbles: true, cancelable: true }));
};

const WATCHDOG_MS = 30000;

(async () => {
  const watchdog = setTimeout(() => {
    console.log("    (看门狗触发：疑似断言抛错导致未收尾，按当前结果退出)");
    process.exit(fail ? 1 : 0);
  }, WATCHDOG_MS);

  console.log("\n[1] 默认排序：组内按点击频次降序（常用靠前）");
  {
    const { window } = mkEnv();
    const doc = window.document;
    ok(await waitFor(() => chips(doc).length === 3, 3000, "指令卡渲染"),
       "三条指令渲染成卡片");
    ok(chipIds(doc).join(",") === "a,b,c", "未拖过 → 按 clickCount(9/5/1) 降序");
    ok(!!doc.querySelector(".cmd-drag-hint"), "标题行有「长按卡片可拖动排序」提示");
    window.close();
  }

  console.log("\n[2] 短按 = 普通点击：照旧执行命令，不写 cmd_order");
  {
    const { window, calls } = mkEnv();
    const doc = window.document;
    await waitFor(() => chips(doc).length === 3, 3000, "指令卡渲染");
    const chip = chipOf(doc, "b");
    pointer(window, "pointerdown", chip, 10);
    await sleep(120);                       // 远小于 400ms 长按阈值
    pointer(window, "pointerup", chip, 10);
    clickChip(window, chip);
    ok(await waitFor(() => callsOf(calls, "run_command").length === 1, 3000, "执行命令"),
       "短按后 click 正常执行命令");
    ok(callsOf(calls, "run_command")[0].args[0] === "b", "执行的是被点的那一条");
    ok(savedPatch(calls, "cmd_order") === undefined, "短按不写 cmd_order");
    window.close();
  }

  console.log("\n[3] 长按拖动：换位 + 落盘 + 不误执行");
  {
    const { window, calls } = mkEnv();
    const doc = window.document;
    await waitFor(() => chips(doc).length === 3, 3000, "指令卡渲染");
    const src = chipOf(doc, "c");     // 把最后一条 C 拖到最前面
    const dst = chipOf(doc, "a");
    pointer(window, "pointerdown", src, 10);
    await sleep(460);                 // 超过 400ms 长按阈值
    ok(src.classList.contains("is-dragging"), "长按后进入拖动态（卡片抬起）");
    ok(doc.body.classList.contains("cmd-sorting"), "拖动中整页切抓取光标");
    // 落在 A 的右半边（clientX 80 > 中线 50）→ 插到 A 后面
    doc.elementFromPoint = () => dst;
    pointer(window, "pointermove", window, 80);
    ok(await waitFor(() => chipIds(doc).join(",") === "a,c,b", 2000, "实时换位"),
       "指针移到目标卡片上即时换位（A C B）");
    pointer(window, "pointerup", window, 80);
    ok(await waitFor(() => savedPatch(calls, "cmd_order") === "a,c,b", 3000, "落盘"),
       "松手把新顺序写进 cmd_order");
    ok(!doc.body.classList.contains("cmd-sorting"), "松手后退出拖动态");
    // 浏览器在 pointerup 之后还会补一个 click：必须被吃掉
    clickChip(window, src);
    await sleep(80);
    ok(callsOf(calls, "run_command").length === 0,
       "拖动松手后的 click 被拦截（没有顺手执行命令）");
    ok(chipIds(doc).join(",") === "a,c,b", "重绘后顺序与落盘结果一致");
    window.close();
  }

  console.log("\n[4] 顺序回填：config.json 里的 cmd_order 优先于点击频次");
  {
    const { window } = mkEnv({ settings: { cmd_order: "c,b,a" } });
    const doc = window.document;
    ok(await waitFor(() => chips(doc).length === 3, 3000, "指令卡渲染"),
       "三条指令渲染成卡片");
    ok(await waitFor(() => chipIds(doc).join(",") === "c,b,a", 2000, "回填顺序"),
       "首屏即按 cmd_order 排序（不再看 clickCount）");
    window.close();
  }

  console.log("\n[5] 只冻结被拖的分组：其它分组仍按点击频次自动排");
  {
    const cmds = [
      { id: "x1", name: "X1", labels: ["X 组"], commands: [{ command: "adb shell a" }], clickCount: 1 },
      { id: "x2", name: "X2", labels: ["X 组"], commands: [{ command: "adb shell b" }], clickCount: 9 },
      { id: "y1", name: "Y1", labels: ["Y 组"], commands: [{ command: "adb shell c" }], clickCount: 2 },
      { id: "y2", name: "Y2", labels: ["Y 组"], commands: [{ command: "adb shell d" }], clickCount: 7 },
    ];
    // 只给 X 组记了手工顺序；Y 组没记 → Y 组仍按频次（Y2 在前）
    const { window } = mkEnv({ commands: cmds, settings: { cmd_order: "x1,x2" } });
    const doc = window.document;
    await waitFor(() => chips(doc).length === 4, 3000, "指令卡渲染");
    const groups = Array.from(doc.querySelectorAll(".cmd-group")).map((g) => ({
      title: g.querySelector(".cmd-group-title").textContent,
      ids: Array.from(g.querySelectorAll(".cmd-chip")).map((el) => el.dataset.cmdId),
    }));
    const xg = groups.filter((g) => g.title === "X 组")[0];
    const yg = groups.filter((g) => g.title === "Y 组")[0];
    ok(xg && xg.ids.join(",") === "x1,x2", "X 组按 cmd_order（x1 在前，即使点击更少）");
    ok(yg && yg.ids.join(",") === "y2,y1", "Y 组未拖过 → 仍按点击频次（y2 在前）");
    window.close();
  }

  console.log("\n[6] 拖出阈值 = 取消长按（不误判成拖动）");
  {
    const { window, calls } = mkEnv();
    const doc = window.document;
    await waitFor(() => chips(doc).length === 3, 3000, "指令卡渲染");
    const src = chipOf(doc, "a");
    pointer(window, "pointerdown", src, 10);
    // 长按计时器还没到点就移动了 40px：用户其实是在滚动 / 划走
    pointer(window, "pointermove", window, 60);
    await sleep(460);
    ok(!src.classList.contains("is-dragging"), "位移超阈值后不再进入拖动态");
    pointer(window, "pointerup", window, 60);
    await sleep(60);
    ok(savedPatch(calls, "cmd_order") === undefined, "未拖动就不写 cmd_order");
    ok(chipIds(doc).join(",") === "a,b,c", "顺序保持原样");
    window.close();
  }

  clearTimeout(watchdog);
  console.log("\n" + "=".repeat(46));
  console.log("结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
