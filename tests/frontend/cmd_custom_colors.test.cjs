/* jsdom 前端行为测试：自定义命令按钮配色（bg / fg）

   背景：命令多了之后一眼找不到常用命令，所以允许给单条命令设置按钮底色与
   文字颜色。后端 core.commands 会把非法色值丢掉（tests/test_load_commands.py），
   前端这里要锁定：
     1. 合法色值渲染成 .cmd-chip--custom + 内联 CSS 变量；
     2. 非法色值一律忽略（防手改 json 往内联样式里塞脏值）；
     3. 编辑弹窗能改 / 能恢复默认，保存时只写入设置过的那个字段。 */
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

async function boot(commands) {
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
  const { window } = dom;
  const calls = [];
  let round = 0;
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          calls.push({ fn: k, args });
          if (k === "boot") {
            return Promise.resolve({ version: "v-test", warnings: [],
                                     adb: "adb", commands });
          }
          if (k === "take_events") {
            const b = round === 0
              ? [{ kind: "booted",
                   payload: { version: "v-test", warnings: [], adb: "adb", commands } }]
              : [];
            round++;
            return Promise.resolve(b);
          }
          if (k === "save_commands") return Promise.resolve({ ok: true });
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

function chipOf(doc, text) {
  return Array.from(doc.querySelectorAll("#cmd-groups .cmd-chip"))
    .find((c) => {
      const lbl = c.querySelector(".chip-label");
      return (lbl ? lbl.textContent : c.textContent) === text;
    });
}

const mk = (extra) => Object.assign({
  id: "u1", name: "[通用] 我的命令", labels: ["通用"], builtin: false,
  commands: [{ command: "git status", delay: 0 }], clickCount: 0,
}, extra || {});

(async () => {
  console.log("[1] 样式表提供自定义配色类，hover 不会把颜色换回主题色");
  ok(/\.cmd-chip--custom\b/.test(css), "app.css 定义了 .cmd-chip--custom");
  ok(/\.cmd-chip--custom:hover\s*\{[^}]*var\(--chip-bg[,)]/.test(css),
     "hover 规则沿用 --chip-bg（否则一悬停用户选的颜色就没了）");

  console.log("\n[2] 合法配色渲染为内联变量；非法色值忽略");
  {
    const { window } = await boot([
      mk({ bg: "#ffcc00", fg: "#003366" }),
    ]);
    const doc = window.document;
    ok(await waitFor(() => !!chipOf(doc, "[通用] 我的命令"), 4000, "命令卡片"),
       "命令卡片已渲染");
    const chip = chipOf(doc, "[通用] 我的命令");
    ok(chip.classList.contains("cmd-chip--custom"), "带 cmd-chip--custom 类");
    ok(chip.style.getPropertyValue("--chip-bg") === "#ffcc00",
       "内联 --chip-bg = #ffcc00（实际：" + chip.style.getPropertyValue("--chip-bg") + "）");
    ok(chip.style.getPropertyValue("--chip-fg") === "#003366",
       "内联 --chip-fg = #003366");
    ok(chip.title.includes("自定义配色"), "tooltip 标注自定义配色");
    window.close();
  }

  {
    const { window } = await boot([
      mk({ bg: "red", fg: "url(javascript:1)" }),
      mk({ id: "u2", name: "[通用] 只有底色", bg: "#123" }),
    ]);
    const doc = window.document;
    ok(await waitFor(() => !!chipOf(doc, "[通用] 我的命令"), 4000, "命令卡片"),
       "命令卡片已渲染");
    const bad = chipOf(doc, "[通用] 我的命令");
    ok(!bad.classList.contains("cmd-chip--custom")
       && !bad.style.getPropertyValue("--chip-bg"),
       "非法色值不渲染成自定义样式");
    const onlyBg = chipOf(doc, "[通用] 只有底色");
    ok(!!onlyBg && onlyBg.classList.contains("cmd-chip--custom")
       && onlyBg.style.getPropertyValue("--chip-bg") === "#123",
       "只设底色也生效（文字继续用主题色）");
    window.close();
  }

  console.log("\n[3] 编辑弹窗：改色 → 保存只存设置过的字段");
  {
    const { window, calls } = await boot([mk()]);
    const doc = window.document;
    await waitFor(() => !!chipOf(doc, "[通用] 我的命令"), 4000, "命令卡片");
    const chip = chipOf(doc, "[通用] 我的命令");
    chip.querySelector(".chip-kebab")
      .dispatchEvent(new window.Event("click", { bubbles: true }));
    const editItem = Array.from(chip.querySelectorAll(".chip-popup-item"))
      .find((i) => i.textContent.includes("修改"));
    ok(!!editItem, "kebab 菜单里有「修改」");
    editItem.dispatchEvent(new window.Event("click", { bubbles: true }));
    ok(!doc.getElementById("cmd-edit-modal").classList.contains("hidden"),
       "编辑弹窗已打开");

    const bg = doc.getElementById("cmd-edit-bg");
    const fg = doc.getElementById("cmd-edit-fg");
    ok(doc.getElementById("cmd-edit-bg-reset").disabled
       && doc.getElementById("cmd-edit-fg-reset").disabled,
       "未设置配色时两个「默认」按钮是禁用的");

    bg.value = "#ff0000";
    bg.dispatchEvent(new window.Event("input", { bubbles: true }));
    ok(doc.getElementById("cmd-edit-bg-reset").disabled === false,
       "改了底色后「默认」按钮可用");
    // 文字色不动（保持未设置状态）

    doc.getElementById("cmd-edit-save")
      .dispatchEvent(new window.Event("click", { bubbles: true }));
    ok(await waitFor(() => calls.some((c) => c.fn === "save_commands"),
                     4000, "save_commands"),
       "保存请求已发出");
    const saved = (calls.find((c) => c.fn === "save_commands") || {}).args[0] || [];
    const item = saved.find((c) => c.id === "u1") || {};
    ok(item.bg === "#ff0000", "保存了 bg（实际：" + item.bg + "）");
    ok(!("fg" in item), "未设置 fg 时不写该字段");

    ok(await waitFor(() => {
      const c = chipOf(doc, "[通用] 我的命令");
      return c && c.style.getPropertyValue("--chip-bg") === "#ff0000";
    }, 4000, "重新渲染带色卡片"), "保存后卡片立即带上新底色");
    window.close();
  }

  console.log("\n[4] 编辑弹窗：点「默认」清掉自定义色");
  {
    const { window, calls } = await boot([mk({ bg: "#ffcc00", fg: "#003366" })]);
    const doc = window.document;
    await waitFor(() => !!chipOf(doc, "[通用] 我的命令"), 4000, "命令卡片");
    const chip = chipOf(doc, "[通用] 我的命令");
    chip.querySelector(".chip-kebab")
      .dispatchEvent(new window.Event("click", { bubbles: true }));
    Array.from(chip.querySelectorAll(".chip-popup-item"))
      .find((i) => i.textContent.includes("修改"))
      .dispatchEvent(new window.Event("click", { bubbles: true }));

    doc.getElementById("cmd-edit-bg-reset")
      .dispatchEvent(new window.Event("click", { bubbles: true }));
    doc.getElementById("cmd-edit-save")
      .dispatchEvent(new window.Event("click", { bubbles: true }));
    await waitFor(() => calls.some((c) => c.fn === "save_commands"),
                  4000, "save_commands");
    const saved = (calls.find((c) => c.fn === "save_commands") || {}).args[0] || [];
    const item = saved.find((c) => c.id === "u1") || {};
    ok(!("bg" in item), "点「默认」后不再写 bg");
    ok(item.fg === "#003366", "另一项没动，继续保留");
    window.close();
  }

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
