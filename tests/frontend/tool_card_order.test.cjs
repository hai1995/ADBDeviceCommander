/* jsdom 前端测试：工具区子 tab（截图 / 录屏 / 投屏 / 安装 / 诊断）顺序
   —— 长按拖动重排 + 持久化 + 点击切换面板。

   回归：
   [0] 默认顺序：截图 → 录屏 → 投屏 → 应用安装 → 诊断（子 tab 按钮顺序），
       每个子 tab 注入一个拖拽手柄（.tool-grip）。
   [1] 启动按保存顺序恢复：settings.tool_tab_order 命中时 DOM 重排成该顺序；
       顺序里没有的 tab（如未来新增）补到末尾。
   [2] 长按手势：子 tab 长按需 ≥400ms 才进入拖动态（is-dragging + body.tool-sorting）；
       短按（不等待）不触发拖动，仍是普通切换。
   [3] 拖动中换位 + 松手落盘：stub elementFromPoint 模拟指针扫到目标 tab，验证 DOM
       真被重排（按钮与面板同步）；松手调用 save_settings 写入 tool_tab_order；
       随后紧跟的 click 被 toolTabClickGuard 压制（不会「拖一下 tab 反而切走」）。
   [4] 点击切换面板：点某子 tab 后它 active、对应面板显示、其余面板 hidden。
   [5] 键盘导航：方向键 / Home / End 按 DOM 顺序移动并激活（首尾循环），
       roving tabindex 只让当前项可被 Tab 停住。
   [6] 记忆上次停留项：settings.tool_active_tab 命中即恢复、回填不写盘；
       配置里的 key 已失效（版本删了某项）时回退到第一项。
   [7] 拖动中按 Esc 取消：顺序还原到按下前、退出拖动态、不落盘（松手也不写）。 */
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

// 子 tab 按钮的当前 key 顺序
function toolOrder(doc) {
  return Array.from(doc.querySelectorAll("#tool-subtabs .tool-subtab"))
    .map((b) => b.dataset.toolTab);
}
function subBtn(doc, key) { return doc.querySelector('.tool-subtab[data-tool-tab="' + key + '"]'); }
function pane(doc, key) { return doc.querySelector('.tool-pane[data-tool-pane="' + key + '"]'); }

(async () => {
  const watchdog = setTimeout(() => {
    console.log("    (看门狗触发)");
    process.exit(fail ? 1 : 0);
  }, 40000);

  console.log("\n[0] 默认顺序：截图→录屏→投屏→安装→诊断（子 tab 按钮顺序），且每 tab 有手柄");
  {
    const { window } = mkEnv();
    const doc = window.document;
    const okReady = await waitFor(() => doc.querySelector("#tool-subtabs .tool-subtab"), 3000, "就绪");
    ok(okReady, "工具区子 tab 已渲染");
    const order = toolOrder(doc);
    ok(JSON.stringify(order) ===
       JSON.stringify(["shot", "rec", "scrcpy", "apk", "diag"]),
       "默认顺序 = 截图→录屏→投屏→安装→诊断（投屏第三位）: " + order.join(","));
    const grips = doc.querySelectorAll("#tool-subtabs .tool-grip");
    ok(grips.length === 5, "5 个子 tab 各有一个 .tool-grip 手柄（实际 " + grips.length + "）");
    ok(/\.tool-grip\s*\{[^}]*cursor:\s*grab/.test(css), "手柄 cursor: grab（暗示可拖动）");
    ok(/\.tool-subtab\.is-dragging\s*\{[^}]*opacity/.test(css),
       "拖动中的子 tab 降透明度（is-dragging）");
    ok(/body\.tool-sorting[^{]*\{[^}]*cursor:\s*grabbing/.test(css),
       "拖动进行中整页 cursor: grabbing（并禁 user-select）");
    ok(/body\.tool-sorting[^{]*\{[^}]*user-select:\s*none/.test(css),
       "拖动进行中禁止选中文字（user-select: none）");
    ok(doc.querySelectorAll('#tool-panes .tool-pane[role="tabpanel"]').length === 5,
       "5 个面板都标了 role=tabpanel");
    ok(subBtn(doc, "shot").getAttribute("aria-controls") === "tool-pane-shot",
       "子 tab 的 aria-controls 指向对应面板");
  }

  console.log("\n[1] 启动按保存顺序恢复（tool_tab_order 命中即重排）");
  {
    const saved = "diag,apk,rec,scrcpy,shot";
    const { window } = mkEnv({ settings: { tool_tab_order: saved } });
    const doc = window.document;
    const reordered = await waitFor(
      () => JSON.stringify(toolOrder(doc)) === JSON.stringify(saved.split(",")),
      4000, "按保存顺序重排");
    ok(reordered, "DOM 重排成保存顺序: " + toolOrder(doc).join(","));
    // 顺序表外的 tab 补到末尾：把 shot 从表头去掉，它应落在最后
    const { window: w2 } = mkEnv({ settings: { tool_tab_order: "apk,diag" } });
    const d2 = w2.document;
    const r2 = await waitFor(
      () => JSON.stringify(toolOrder(d2)) ===
            JSON.stringify(["apk", "diag", "shot", "rec", "scrcpy"]),
      4000, "未知 tab 补末尾");
    ok(r2, "表中没有的 tab（shot/rec/scrcpy）补到末尾: " + toolOrder(d2).join(","));
  }

  console.log("\n[2] 长按手势：长按需等待才进拖动态，短按不触发");
  {
    const { window } = mkEnv();
    const doc = window.document;
    await waitFor(() => subBtn(doc, "shot"), 3000, "就绪");
    const btn = subBtn(doc, "shot");
    // 短按：down 后立刻 up，不等待长按时限
    btn.dispatchEvent(pointerEvent(window, "pointerdown", 10, 10));
    btn.dispatchEvent(pointerEvent(window, "pointerup", 10, 10));
    ok(!btn.classList.contains("is-dragging"), "短按不进入拖动态");
    ok(!doc.body.classList.contains("tool-sorting"), "短按不挂 tool-sorting");

    // 长按：down 后等待 > 400ms，计时器到点才激活
    btn.dispatchEvent(pointerEvent(window, "pointerdown", 10, 10));
    await waitFor(() => btn.classList.contains("is-dragging"), 1500, "长按激活");
    ok(btn.classList.contains("is-dragging"), "长按 ≥400ms 后进入拖动态");
    ok(doc.body.classList.contains("tool-sorting"), "拖动进行中 body.tool-sorting 挂上");
    btn.dispatchEvent(pointerEvent(window, "pointerup", 10, 10));
    ok(!btn.classList.contains("is-dragging"), "松手后退出拖动态");
  }

  console.log("\n[3] 拖动换位 + 松手落盘 + 紧随 click 被压制（不切走）");
  {
    const { window, calls } = mkEnv();
    const doc = window.document;
    await waitFor(() => subBtn(doc, "shot"), 3000, "就绪");
    const btn = subBtn(doc, "shot");
    const target = subBtn(doc, "diag");
    // stub 命中：指针永远落在 diag 子 tab 上 → 把 shot 拖到它后面
    doc.elementFromPoint = () => target;

    const before = toolOrder(doc).join(",");
    btn.dispatchEvent(pointerEvent(window, "pointerdown", 10, 10));
    await waitFor(() => btn.classList.contains("is-dragging"), 1500, "长按激活");
    window.dispatchEvent(pointerEvent(window, "pointermove", 200, 300));
    const moved = await waitFor(
      () => toolOrder(doc).join(",") === "rec,scrcpy,apk,diag,shot",
      2000, "拖动换位");
    ok(moved, "拖动后 shot 被移到 diag 之后: " + toolOrder(doc).join(",") + "（前=" + before + "）");

    window.dispatchEvent(pointerEvent(window, "pointerup", 200, 300));
    await sleep(20);
    const saves = calls.filter((c) => c.fn === "save_settings");
    ok(saves.length >= 1, "松手后写入配置");
    const patch = saves[saves.length - 1].args[0] || {};
    ok(patch.tool_tab_order === "rec,scrcpy,apk,diag,shot",
       "落盘 tool_tab_order 与拖后顺序一致: " + patch.tool_tab_order);

    // 面板 DOM 也要跟着重排：按钮与面板一一对应，后续按 key 查找不会错位
    const panesOrder = Array.from(doc.querySelectorAll("#tool-panes .tool-pane"))
      .map((p) => p.dataset.toolPane);
    ok(panesOrder.join(",") === "rec,scrcpy,apk,diag,shot",
       "松手后面板 DOM 同步重排: " + panesOrder.join(","));

    // 紧随的 click 应被 toolTabClickGuard 压制：不切换（shot 仍是 active）
    ok(subBtn(doc, "shot").classList.contains("active"), "拖动前 shot 子 tab active");
    btn.dispatchEvent(new window.Event("click", { bubbles: true }));
    ok(subBtn(doc, "shot").classList.contains("active"), "拖动后的 click 被压制，不切走");
  }

  console.log("\n[4] 点击切换面板：active + 对应面板显示、其余 hidden");
  {
    const { window } = mkEnv();
    const doc = window.document;
    await waitFor(() => subBtn(doc, "shot"), 3000, "就绪");
    ok(subBtn(doc, "shot").classList.contains("active"), "默认 shot 子 tab active");
    ok(!pane(doc, "shot").hidden, "默认 shot 面板可见");
    ok(pane(doc, "rec").hidden && pane(doc, "diag").hidden, "其余面板初始 hidden");

    subBtn(doc, "rec").dispatchEvent(new window.Event("click", { bubbles: true }));
    await sleep(30);
    ok(subBtn(doc, "rec").classList.contains("active"), "点录屏 → rec active");
    ok(!pane(doc, "rec").hidden, "rec 面板显示");
    ok(pane(doc, "shot").hidden, "shot 面板被隐藏");

    subBtn(doc, "diag").dispatchEvent(new window.Event("click", { bubbles: true }));
    await sleep(30);
    ok(subBtn(doc, "diag").classList.contains("active"), "点诊断 → diag active");
    ok(!pane(doc, "diag").hidden, "diag 面板显示");
    ok(pane(doc, "rec").hidden, "rec 面板被隐藏");
  }

  console.log("\n[5] 方向键 / Home / End 在子 tab 间移动并激活（按 DOM 顺序，含循环）");
  {
    const { window } = mkEnv();
    const doc = window.document;
    await waitFor(() => subBtn(doc, "shot"), 3000, "就绪");
    const key = (el, k) =>
      el.dispatchEvent(new window.KeyboardEvent("keydown", { key: k, bubbles: true }));

    key(subBtn(doc, "shot"), "ArrowRight");
    await sleep(40);
    ok(subBtn(doc, "rec").classList.contains("active"), "ArrowRight：截图 → 录屏");
    ok(pane(doc, "rec").hidden === false, "录屏面板显示");
    key(subBtn(doc, "rec"), "ArrowRight");
    await sleep(40);
    ok(subBtn(doc, "scrcpy").classList.contains("active"), "ArrowRight：录屏 → 投屏");
    key(subBtn(doc, "scrcpy"), "ArrowLeft");
    await sleep(40);
    ok(subBtn(doc, "rec").classList.contains("active"), "ArrowLeft：投屏 → 录屏");
    key(subBtn(doc, "rec"), "End");
    await sleep(40);
    ok(subBtn(doc, "diag").classList.contains("active"), "End：跳到最后一个（诊断）");
    key(subBtn(doc, "diag"), "Home");
    await sleep(40);
    ok(subBtn(doc, "shot").classList.contains("active"), "Home：回到第一个（截图）");
    key(subBtn(doc, "shot"), "ArrowLeft");
    await sleep(40);
    ok(subBtn(doc, "diag").classList.contains("active"), "首个再 ArrowLeft 循环到最后一个（诊断）");

    // roving tabindex：只有当前子 tab 能被 Tab 键停住
    ok(subBtn(doc, "diag").tabIndex === 0, "当前子 tab tabindex=0");
    ok(subBtn(doc, "shot").tabIndex === -1, "非当前子 tab tabindex=-1");
  }

  console.log("\n[6] 记忆上次停留的子 tab（tool_active_tab）");
  {
    const { window, calls } = mkEnv({ settings: { tool_active_tab: "apk" } });
    const doc = window.document;
    const restored = await waitFor(
      () => subBtn(doc, "apk") && subBtn(doc, "apk").classList.contains("active"),
      4000, "回填上次 tab");
    ok(restored, "启动停在 tool_active_tab=apk（而不是固定回截图）");
    ok(!pane(doc, "apk").hidden && pane(doc, "shot").hidden,
       "apk 面板显示、shot 面板隐藏");
    const bootSaved = calls.filter((c) => c.fn === "save_settings")
      .map((c) => c.args[0]).filter((p) => p && "tool_active_tab" in p);
    ok(bootSaved.length === 0, "启动回填不写盘（persist:false，避免打开就刷一次盘）");

    subBtn(doc, "rec").dispatchEvent(new window.Event("click", { bubbles: true }));
    await sleep(40);
    const saves = calls.filter((c) => c.fn === "save_settings");
    const patch = saves.length ? saves[saves.length - 1].args[0] : {};
    ok(patch.tool_active_tab === "rec",
       "用户切换后落盘 tool_active_tab=rec（实际 " + patch.tool_active_tab + "）");

    // 重复点同一个子 tab 不该反复写盘（值没变，save_settings 次数不涨）
    const beforeDup = calls.filter((c) => c.fn === "save_settings").length;
    subBtn(doc, "rec").dispatchEvent(new window.Event("click", { bubbles: true }));
    await sleep(40);
    const afterDup = calls.filter((c) => c.fn === "save_settings").length;
    ok(afterDup === beforeDup, "再点同一个子 tab 不重复写盘（" + beforeDup + "→" + afterDup + "）");

    // 版本变动删了某项 → 配置里的 key 已不存在，回退到第一项而不是白屏
    const { window: w2 } = mkEnv({ settings: { tool_active_tab: "removed-tab" } });
    const d2 = w2.document;
    const fallback = await waitFor(
      () => subBtn(d2, "shot") && subBtn(d2, "shot").classList.contains("active"),
      4000, "失效 key 回退");
    ok(fallback, "tool_active_tab 存了不存在的 key → 回退默认（shot）");
  }

  console.log("\n[7] 拖动中按 Esc 取消：顺序还原、不落盘");
  {
    const { window, calls } = mkEnv();
    const doc = window.document;
    await waitFor(() => subBtn(doc, "shot"), 3000, "就绪");
    const btn = subBtn(doc, "shot");
    doc.elementFromPoint = () => subBtn(doc, "diag");
    const before = toolOrder(doc).join(",");
    btn.dispatchEvent(pointerEvent(window, "pointerdown", 10, 10));
    await waitFor(() => btn.classList.contains("is-dragging"), 1500, "长按激活");
    window.dispatchEvent(pointerEvent(window, "pointermove", 200, 300));
    const moved = await waitFor(
      () => toolOrder(doc).join(",") !== before, 2000, "拖动换位");
    ok(moved, "拖动中顺序确实变了: " + toolOrder(doc).join(",") + "（原 " + before + "）");

    window.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    await sleep(40);
    ok(toolOrder(doc).join(",") === before,
       "Esc 后顺序还原: " + toolOrder(doc).join(","));
    ok(!doc.body.classList.contains("tool-sorting"), "Esc 后退出拖动态（cursor 复原）");
    const savedBeforeUp = calls.filter(
      (c) => c.fn === "save_settings" && c.args[0] && "tool_tab_order" in c.args[0]);
    ok(savedBeforeUp.length === 0, "Esc 取消不当场落盘");

    window.dispatchEvent(pointerEvent(window, "pointerup", 200, 300));
    await sleep(20);
    const savedAfterUp = calls.filter(
      (c) => c.fn === "save_settings" && c.args[0] && "tool_tab_order" in c.args[0]);
    ok(savedAfterUp.length === 0, "取消后再松手也不落盘（顺序仍是原样）");
    ok(toolOrder(doc).join(",") === before, "松手后顺序保持原样");
  }

  clearTimeout(watchdog);
  console.log("\n" + (fail ? "✗ 有失败" : "✓ 全部通过") +
              "  pass=" + pass + " fail=" + fail);
  process.exit(fail ? 1 : 0);
})();
