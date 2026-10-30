/* jsdom 前端行为测试：实时监控日志的「选中复制」
   覆盖四件事：
   1) .lc-view 用 CSS user-select:text 放开框选（pywebview 默认全局禁选）；
   2) 自动滚动给选区让路：视图内有选区时不再每帧拽到底，选区取消后恢复；
   3) 自绘右键菜单：无选区右键落在行上 → 「复制该行」；有选区 → 「复制选中内容」；
      空白处右键不弹菜单；点击菜单项后状态栏出现「已复制」，菜单自动收起；
   4) 菜单收起路径：点击外部 / Esc。 */
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

function mkLines(n, off) {
  return Array.from({ length: n }, (_, i) => ({
    raw: `08-29 10:00:0${(i % 10)}.000  1  1 I Tag${i + off}: msg ${i + off}`,
    level: "I", tag: "Tag" + (i + off), msg: "msg " + (i + off), exc: false,
  }));
}

function mkEnv(batches) {
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
  const { window } = dom;
  let round = 0;
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function () {
          if (k === "boot") return Promise.resolve({ version: "v-t", warnings: [], commands: [], adb: "adb" });
          if (k === "take_events") { const b = batches[round] || []; round++; return Promise.resolve(b); }
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  // 复制路径桩：clipboard API 桩成成功，才能断言「已复制」状态消息
  const _c = { writeText: () => Promise.resolve() };
  try { Object.defineProperty(window.navigator, "clipboard", { configurable: true, value: _c }); } catch (e) {}
  try { Object.defineProperty(window.document, "execCommand", { configurable: true, value: () => true }); } catch (e) {}
  window.eval(js);
  return { window, doc: window.document };
}

const dev = [{ serial: "A1", model: "Pixel", state: "device", ok: true, checked: true }];
function bootBatches(appendBatches) {
  return [
    [{ kind: "booted", payload: { version: "v-t", warnings: [], commands: [] } },
     { kind: "devices", payload: { items: dev } }],
    ...appendBatches,
  ];
}

(async () => {
  console.log("\n[A] CSS：.lc-view 放开文本选择");
  {
    // 抽出 .lc-view 的规则块（到下一个裸 } 为止）检查 user-select
    const m = css.match(/\.lc-view \{[^}]*\}/);
    ok(!!m, "能找到 .lc-view 规则块");
    ok(m && /user-select:\s*text/.test(m[0]), ".lc-view 含 user-select: text");
  }

  console.log("\n[B] 右键菜单：复制该行 / 复制选中内容 / 空白不弹");
  {
    const { window, doc } = mkEnv(bootBatches([
      [{ kind: "logcat", payload: { serial: "A1", status: "running" } },
       { kind: "logcat", payload: { serial: "A1", status: "append", lines: mkLines(5, 0), total: 5, exc: 0 } }],
    ]));
    const view = doc.getElementById("lc-view");
    ok(await waitFor(() => view.childNodes.length === 5, 4000, "lines"), "5 行日志已渲染");

    // 无选区、右键落在行上 → 「复制该行」
    const line = view.childNodes[2];
    line.dispatchEvent(new window.MouseEvent("contextmenu",
      { bubbles: true, cancelable: true, clientX: 30, clientY: 30 }));
    let menu = doc.querySelector(".ctx-menu");
    ok(!!menu, "行上右键弹出菜单");
    ok(menu && menu.textContent.indexOf("复制该行") >= 0, "菜单项为「复制该行」");
    ok(menu && menu.textContent.indexOf("复制选中内容") < 0, "无选区时不出现「复制选中内容」");
    if (menu) menu.querySelector(".ctx-menu-item").click();
    ok(!(doc.querySelector(".ctx-menu")), "点击菜单项后菜单收起");
    ok(await waitFor(() => doc.getElementById("status").textContent.indexOf("已复制") >= 0,
      3000, "copied"), "状态栏出现「已复制」提示");

    // 有选区 → 「复制选中内容」
    const sel = window.getSelection();
    sel.removeAllRanges();
    const r = doc.createRange();
    r.selectNodeContents(view.childNodes[1]);
    sel.addRange(r);
    view.childNodes[1].dispatchEvent(new window.MouseEvent("contextmenu",
      { bubbles: true, cancelable: true, clientX: 30, clientY: 40 }));
    menu = doc.querySelector(".ctx-menu");
    ok(!!menu && menu.textContent.indexOf("复制选中内容") >= 0, "有选区时菜单为「复制选中内容」");
    if (menu) menu.querySelector(".ctx-menu-item").click();

    // 空白处（视图本体，非行）右键 → 不弹菜单。注意先把上一段留下的选区
    // 清掉：选区仍在时右键弹「复制选中内容」才是正确行为（与浏览器一致）。
    sel.removeAllRanges();
    view.dispatchEvent(new window.MouseEvent("contextmenu",
      { bubbles: true, cancelable: true, clientX: 10, clientY: 10 }));
    ok(!(doc.querySelector(".ctx-menu")), "空白处右键不弹菜单");

    // Esc 收起：先弹一个再按 Esc
    line.dispatchEvent(new window.MouseEvent("contextmenu",
      { bubbles: true, cancelable: true, clientX: 30, clientY: 30 }));
    ok(!!doc.querySelector(".ctx-menu"), "菜单再次弹出（Esc 前置）");
    window.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    ok(!(doc.querySelector(".ctx-menu")), "Esc 收起菜单");
    window.close();
  }

  console.log("\n[C] 自动滚动给选区让路，选区取消后恢复");
  {
    // 三轮 append：第 1 轮后造选区（第 2 轮 append 在选区存在期间到达，滚动应暂停），
    // 取消选区后第 3 轮到达（滚动恢复）。事件 400ms 一轮，waitFor 轮询 30ms，
    // 造选区 / 取消选区都插在两轮之间的窗口里，时序足够稳。
    const { window, doc } = mkEnv(bootBatches([
      [{ kind: "logcat", payload: { serial: "A1", status: "running" } },
       { kind: "logcat", payload: { serial: "A1", status: "append", lines: mkLines(10, 0), total: 10, exc: 0 } }],
      [{ kind: "logcat", payload: { serial: "A1", status: "append", lines: mkLines(10, 10), total: 20, exc: 0 } }],
      [{ kind: "logcat", payload: { serial: "A1", status: "append", lines: mkLines(10, 20), total: 30, exc: 0 } }],
    ]));
    const view = doc.getElementById("lc-view");
    doc.getElementById("lc-autoscroll").checked = true;
    // 记录对 scrollTop 的写入次数（jsdom 无真实布局，桩掉才能观察「有没有滚」）
    let writes = 0;
    Object.defineProperty(view, "scrollTop", {
      configurable: true,
      get() { return 0; },
      set() { writes++; },
    });
    ok(await waitFor(() => view.childNodes.length === 10, 4000, "r1"), "第 1 轮 10 行就位");
    ok(await waitFor(() => writes > 0, 3000, "scroll-1"), "无选区时自动滚动在写 scrollTop");

    // 造选区（视图内、未折叠）→ 第 2 轮 append 到达时不应再写 scrollTop
    const sel = window.getSelection();
    sel.removeAllRanges();
    const r = doc.createRange();
    r.selectNodeContents(view.childNodes[0]);
    sel.addRange(r);
    const before = writes;
    ok(await waitFor(() => view.childNodes.length === 20, 5000, "r2"), "第 2 轮 10 行就位");
    await sleep(120);   // 等 rAF doScroll 机会走完
    ok(writes === before, "选区存在期间不再强制滚动（写入数 " + before + " → " + writes + "）");

    // 取消选区 → 第 3 轮 append 到达时恢复滚动
    sel.removeAllRanges();
    const mid = writes;
    ok(await waitFor(() => view.childNodes.length === 30, 5000, "r3"), "第 3 轮 10 行就位");
    ok(await waitFor(() => writes > mid, 3000, "scroll-3"),
      "选区取消后自动滚动恢复（写入 " + mid + " → " + writes + "）");
    window.close();
  }

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
