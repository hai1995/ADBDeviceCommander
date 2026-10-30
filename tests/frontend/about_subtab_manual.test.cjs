/* jsdom 前端行为测试：关于页「概览 / 使用说明」子 tab
   覆盖三件事：
   1) 默认停在「概览」、使用说明面板隐藏；
   2) 点击「使用说明」子 tab → 切换 active、显示使用说明面板、隐藏概览面板，
      并触发后端 get_manual() 把内容填进 #about-manual；
   3) 再点回「概览」→ 概览面板恢复、使用说明面板隐藏。 */
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
    let v = false; try { v = !!fn(); } catch (e) { v = false; }
    if (v) return true;
    await sleep(30);
  }
  console.log("    (waitFor 超时: " + label + ")");
  return false;
}

const MANUAL_TEXT = "ADB 设备指令台（ADB Device Commander）— 使用说明\n\n这是内置的使用说明正文。";

function mkEnv() {
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
  const { window } = dom;
  let manualCalls = 0;
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function () {
          if (k === "boot") return Promise.resolve({ version: "v-t", warnings: [], commands: [], adb: "adb" });
          if (k === "take_events") return Promise.resolve([]);
          if (k === "get_manual") { manualCalls++; return Promise.resolve({ ok: true, text: MANUAL_TEXT }); }
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  window.__manualCalls = () => manualCalls;
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  try { Object.defineProperty(window.navigator, "clipboard", { configurable: true, value: { writeText: () => Promise.resolve() } }); } catch (e) {}
  try { Object.defineProperty(window.document, "execCommand", { configurable: true, value: () => true }); } catch (e) {}
  window.eval(js);
  return { window, doc: window.document };
}

(async () => {
  console.log("\n[A] 默认态：概览可见、使用说明隐藏");
  {
    const { doc } = mkEnv();
    const overview = doc.querySelector('[data-about-pane="overview"]');
    const manual = doc.querySelector('[data-about-pane="manual"]');
    const ovTab = doc.querySelector('[data-about-tab="overview"]');
    const mnTab = doc.querySelector('[data-about-tab="manual"]');
    ok(!overview.hidden, "概览面板默认可见");
    ok(manual.hidden, "使用说明面板默认隐藏");
    ok(ovTab.classList.contains("active"), "概览子 tab 默认 active");
    ok(!mnTab.classList.contains("active"), "使用说明子 tab 默认未激活");
  }

  console.log("\n[B] 点击「使用说明」→ 切换面板 + 拉取并渲染正文");
  {
    const { window, doc } = mkEnv();
    const mnTab = doc.querySelector('[data-about-tab="manual"]');
    const overview = doc.querySelector('[data-about-pane="overview"]');
    const manual = doc.querySelector('[data-about-pane="manual"]');
    const manualEl = doc.getElementById("about-manual");
    mnTab.dispatchEvent(new window.MouseEvent("click", { bubbles: true, cancelable: true }));
    ok(mnTab.classList.contains("active"), "使用说明子 tab 变为 active");
    ok(overview.hidden === true, "概览面板隐藏");
    ok(manual.hidden === false, "使用说明面板显示");
    ok(await waitFor(() => window.__manualCalls() >= 1, 3000, "get_manual"), "触发了后端 get_manual()");
    ok(await waitFor(() => manualEl.textContent.indexOf("使用说明") >= 0, 3000, "manual-text"),
      "使用说明正文被填入 #about-manual");
  }

  console.log("\n[C] 点回「概览」→ 概览恢复、使用说明隐藏");
  {
    const { window, doc } = mkEnv();
    const ovTab = doc.querySelector('[data-about-tab="overview"]');
    const overview = doc.querySelector('[data-about-pane="overview"]');
    const manual = doc.querySelector('[data-about-pane="manual"]');
    doc.querySelector('[data-about-tab="manual"]').dispatchEvent(
      new window.MouseEvent("click", { bubbles: true, cancelable: true }));
    await waitFor(() => !manual.hidden, 2000, "show-manual");
    ovTab.dispatchEvent(new window.MouseEvent("click", { bubbles: true, cancelable: true }));
    ok(overview.hidden === false, "概览面板恢复显示");
    ok(manual.hidden === true, "使用说明面板再次隐藏");
  }

  console.log("\n[D] CSS：子 tab 与 manual 正文样式存在");
  {
    ok(/\.about-subtab\s*\{[^}]*\}/.test(css), "存在 .about-subtab 规则");
    ok(/\.about-pane\s*\{[^}]*flex-direction:\s*column/.test(css), ".about-pane 是纵向 flex");
    ok(/\.manual-body\s*\{[^}]*\}/.test(css), "存在 .manual-body 规则");
  }

  console.log("\n[结果] " + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
