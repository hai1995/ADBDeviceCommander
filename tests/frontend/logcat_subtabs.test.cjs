/* jsdom 前端行为测试：Logcat 页「落盘抓取 / 实时监控」子 tab
   需求：Logcat 原本上下堆叠两张卡片，现改为与工具页一致的子 tabs 风格——
   一条子 tab 条 + 两个面板（tabpanel），一次只看一项；监控面板的日志视图仍撑满高度。
   覆盖：
     1) 默认停在「落盘抓取」、实时监控面板隐藏；
     2) 点击「实时监控」→ 切换 active、显示实时监控面板、隐藏落盘抓取面板；
     3) 再点回「落盘抓取」→ 恢复；
     4) 切换子 tab 即时落盘 save_settings（键名 lc_active_tab，与后端 schema 一致）；
     5) 启动回填：settings.lc_active_tab="monitor" → 启动即停在实时监控；
        非法 key → 回退落盘抓取；
     6) CSS：复用 .tool-subtabs / .tool-pane 视觉语言，#lc-panes 撑满高度布局存在。 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.join(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "frontend/index.html"), "utf8");
const js = fs.readFileSync(path.join(ROOT, "frontend/js/app.js"), "utf8");
const css = fs.readFileSync(path.join(ROOT, "frontend/css/app.css"), "utf8");

process.on("unhandledRejection", (e) => {
  console.error("\n[未捕获异常] " + (e && e.stack ? e.stack : e));
  process.exit(2);
});

let pass = 0, fail = 0;
function ok(cond, name) {
  if (cond) { pass++; console.log("  ✓ " + name); }
  else { fail++; console.log("  ✗ " + name); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitFor(fn, ms = 4000, label = "") {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    let v = false; try { v = !!fn(); } catch (e) { v = false; }
    if (v) return true;
    await sleep(30);
  }
  console.log("    (waitFor 超时: " + label + ")");
  return false;
}

function mkEnv(opts) {
  opts = opts || {};
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const calls = [];
  const batches = [[{ kind: "booted", payload: {
    version: "v-test", warnings: [], commands: [], adb: "adb",
    settings: opts.settings || {},
    settings_warnings: [],
    config_path: "C:\\Program Files\\ADB\\config.json",
    save_dir_effective: "", save_dir_note: null,
    lc_buffers: { "main（主日志）": ["main"],
                  "全部（main+system+events+crash）":
                    ["main", "system", "events", "crash"] },
  } }]];
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          calls.push({ api: k, args });
          if (k === "boot") return Promise.resolve({ ok: true });
          if (k === "take_events") { const b = batches.shift() || []; return Promise.resolve(b); }
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  try { Object.defineProperty(window.navigator, "clipboard", { configurable: true, value: { writeText: () => Promise.resolve() } }); } catch (e) {}
  try { Object.defineProperty(window.document, "execCommand", { configurable: true, value: () => true }); } catch (e) {}
  window.eval(js);
  return { window, doc: window.document, calls };
}

const saved = (calls, key) =>
  calls.filter((c) => c.api === "save_settings" && c.args[0] && key in c.args[0]);
const lcTab = (doc, k) => doc.querySelector('#lc-subtabs .tool-subtab[data-lc-tab="' + k + '"]');
const lcPane = (doc, k) => doc.querySelector('#lc-panes .tool-pane[data-lc-pane="' + k + '"]');

(async () => {
  console.log("\n[A] 默认态：落盘抓取可见、实时监控隐藏");
  {
    const { doc } = mkEnv();
    ok(lcTab(doc, "capture").classList.contains("active"), "落盘抓取子 tab 默认 active");
    ok(!lcTab(doc, "monitor").classList.contains("active"), "实时监控子 tab 默认未激活");
    ok(!lcPane(doc, "capture").hidden, "落盘抓取面板默认可见");
    ok(lcPane(doc, "monitor").hidden, "实时监控面板默认隐藏");
  }

  console.log("\n[B] 点击「实时监控」→ 切换面板");
  {
    const { window, doc, calls } = mkEnv();
    lcTab(doc, "monitor").dispatchEvent(
      new window.MouseEvent("click", { bubbles: true, cancelable: true }));
    ok(lcTab(doc, "monitor").classList.contains("active"), "实时监控子 tab 变为 active");
    ok(!lcTab(doc, "capture").classList.contains("active"), "落盘抓取子 tab 失活");
    ok(!lcPane(doc, "monitor").hidden, "实时监控面板显示");
    ok(lcPane(doc, "capture").hidden, "落盘抓取面板隐藏");
    const rec = saved(calls, "lc_active_tab");
    ok(await waitFor(() => saved(calls, "lc_active_tab").length >= 1, 3000, "lc_active_tab 落盘"),
      "切换触发 save_settings 落盘");
    ok(rec.length >= 1 && rec[rec.length - 1].args[0].lc_active_tab === "monitor",
      "落盘的 lc_active_tab = monitor");
  }

  console.log("\n[C] 点回「落盘抓取」→ 恢复");
  {
    const { window, doc } = mkEnv();
    lcTab(doc, "monitor").dispatchEvent(
      new window.MouseEvent("click", { bubbles: true, cancelable: true }));
    await waitFor(() => !lcPane(doc, "monitor").hidden, 2000, "show-monitor");
    lcTab(doc, "capture").dispatchEvent(
      new window.MouseEvent("click", { bubbles: true, cancelable: true }));
    ok(!lcPane(doc, "capture").hidden, "落盘抓取面板恢复显示");
    ok(lcPane(doc, "monitor").hidden, "实时监控面板再次隐藏");
    ok(lcTab(doc, "capture").classList.contains("active"), "落盘抓取子 tab 恢复 active");
  }

  console.log("\n[D] 启动回填：上次停在实时监控 → 启动即监控");
  {
    const { doc } = mkEnv({ settings: { lc_active_tab: "monitor" } });
    // booted 事件异步下发，等回填生效后再断言
    ok(await waitFor(() => lcTab(doc, "monitor").classList.contains("active"), 4000, "boot→monitor"),
      "启动时实时监控子 tab active（回填生效）");
    ok(!lcPane(doc, "monitor").hidden, "启动时实时监控面板可见");
    ok(lcPane(doc, "capture").hidden, "启动时落盘抓取面板隐藏");
  }

  console.log("\n[E] 启动回填：非法 key → 回退落盘抓取");
  {
    const { doc } = mkEnv({ settings: { lc_active_tab: "bogus" } });
    ok(await waitFor(() => lcTab(doc, "capture").classList.contains("active"), 4000, "boot→bogus回退"),
      "非法 key 回退到落盘抓取 active（回填生效）");
    ok(!lcPane(doc, "capture").hidden, "回退后落盘抓取面板可见");
    ok(lcPane(doc, "monitor").hidden, "回退后实时监控面板隐藏");
  }

  console.log("\n[F] CSS：复用工具页子 tab 视觉 + logcat 撑满布局");
  {
    ok(/\.tool-subtabs\s*\{[^}]*\}/.test(css), "存在 .tool-subtabs 规则");
    ok(/\.tool-pane\s*\[hidden\]\s*\{\s*display:\s*none/.test(css), ".tool-pane[hidden] 隐藏");
    ok(/#lc-panes\s*\{[^}]*flex:\s*1[^}]*display:\s*flex/.test(css),
      "#lc-panes 撑满高度（flex:1 + flex 列）");
    ok(/#lc-panes\s*>\s*\.tool-pane:not\(\[hidden\]\)\s*>\s*\.lc-card\.grow\s*\{[^}]*flex:\s*1/.test(css),
      "监控卡（.lc-card.grow）在激活面板内撑满");
  }

  console.log("\n[结果] " + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
