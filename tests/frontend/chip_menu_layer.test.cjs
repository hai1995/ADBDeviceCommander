/* jsdom 前端测试：快捷命令卡的 ⋯ 菜单层叠 / 弹出方向
 *
 * 现场问题是「点了 ⋯ 之后菜单被下面的按钮压住」。根因不是 popup 的 z-index
 * 太小，而是它被困在 kebab 自己的层叠上下文里（kebab 一带 z-index 就自成一层，
 * popup 的 20 只在这一小层里比较）。所以修复要点落在「整张卡片抬层」上，
 * 这个文件把三件事钉住：
 *   1) CSS：卡片级 chip-menu-open / chip-menu-up 两条规则存在且数值正确；
 *   2) 行为：点 ⋯ 给卡片加 chip-menu-open，再点 / 点菜单项都会撤掉；
 *   3) 方向：下方空间不足时加 chip-menu-up（否则最后一行的菜单被滚动容器裁掉）。
 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.join(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "frontend/index.html"), "utf8");
const js = fs.readFileSync(path.join(ROOT, "frontend/js/app.js"), "utf8");
const css = fs.readFileSync(path.join(ROOT, "frontend/css/app.css"), "utf8");

let pass = 0, fail = 0;
function ok(c, n) {
  if (c) { pass++; console.log("  ✓ " + n); }
  else { fail++; console.log("  ✗ " + n); }
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
const click = (win, el) => el.dispatchEvent(new win.Event("click", { bubbles: true }));

// 三条用户自定义命令（非 builtin 才有 ⋯ 菜单）
const COMMANDS = [
  { id: "c1", name: "[J01] 云听-冷热启动时间", cmd: "adb shell echo 1", builtin: false },
  { id: "c2", name: "[J01] TOC-切U盘模式", cmd: "adb shell echo 2", builtin: false },
  { id: "c3", name: "[J01] TOB-切U盘模式", cmd: "adb shell echo 3", builtin: false },
];

function mkEnv() {
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const calls = [];
  const pending = [
    { kind: "booted", payload: { version: "v-test", warnings: [], adb: "adb",
                                 commands: COMMANDS, settings: {} } },
    { kind: "devices", payload: { items: [
      { serial: "A1", model: "Pixel", ok: true, checked: true, state: "device" },
    ] } },
  ];
  const impl = {
    boot: () => Promise.resolve({ version: "v-test", warnings: [], adb: "adb",
                                  commands: COMMANDS, settings: {} }),
    take_events: () => Promise.resolve(pending.splice(0)),
    default_save_dir: () => Promise.resolve({ dir: "" }),
    save_settings: (patch) => { calls.push({ fn: "save_settings", args: [patch] }); return Promise.resolve({ ok: true }); },
  };
  window.pywebview = {
    api: new Proxy(impl, {
      get(t, k) {
        if (k === "then") return undefined;
        if (k in t) return t[k];
        return () => Promise.resolve({ ok: true });
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  return { window, doc: window.document, calls };
}

const watchdog = setTimeout(() => {
  console.log("    (看门狗触发：疑似断言抛错导致未收尾)");
  process.exit(fail ? 1 : 0);
}, 60000);

(async () => {
  console.log("[A] CSS：抬层与弹出方向两条规则");
  {
    ok(/\.cmd-chip\.chip-menu-open\s*\{[^}]*z-index\s*:\s*30/.test(css),
      "菜单展开时整张卡片抬到 z-index:30（不只抬 kebab）");
    ok(/\.cmd-chip\.chip-menu-up\s+\.chip-popup\s*\{[^}]*bottom\s*:\s*calc\(100% - 2px\)/.test(css),
      "空间不足时菜单改为贴卡片上沿弹出");
    const kebab = css.match(/\.cmd-chip \.chip-kebab \{[^}]*\}/);
    ok(kebab && !/z-index\s*:/.test(kebab[0]), "kebab 本体仍不设 z-index（不破坏原有修复）");
  }

  const env = mkEnv();
  const { window, doc } = env;
  doc.querySelector('.tab-btn[data-tab="cmd"]').click();
  const gotChips = await waitFor(() => doc.querySelectorAll(".cmd-chips .cmd-chip").length >= 3,
                                4000, "命令卡渲染");
  ok(gotChips, "三条自定义命令已渲染成卡片");

  const chip = doc.querySelectorAll(".cmd-chips .cmd-chip")[0];
  const kebab = chip && chip.querySelector(".chip-kebab");
  const popup = chip && chip.querySelector(".chip-popup");
  ok(!!kebab && !!popup, "卡片上有 ⋯ 与菜单节点");

  console.log("\n[B] 点 ⋯ → 卡片抬层；再点 / 点菜单项 → 撤销");
  {
    click(window, kebab);
    ok(kebab.classList.contains("is-open"), "点一下菜单展开");
    ok(chip.classList.contains("chip-menu-open"),
      "同时给**整张卡片**加 chip-menu-open（只抬 kebab 时 popup 出不了层叠上下文）");

    click(window, kebab);
    ok(!kebab.classList.contains("is-open"), "再点一下收起");
    ok(!chip.classList.contains("chip-menu-open"), "收起时卡片撤掉抬层");

    click(window, kebab);
    ok(chip.classList.contains("chip-menu-open"), "再次展开仍会抬层");
    const item = popup.querySelector(".chip-popup-item");
    click(window, item);
    ok(!chip.classList.contains("chip-menu-open"),
      "点了菜单项（复制）后卡片也要撤掉抬层，否则一直压着别人");
  }

  console.log("\n[C] 悬停展开同样抬层");
  {
    kebab.classList.remove("is-open");
    chip.classList.remove("chip-menu-open");
    kebab.dispatchEvent(new window.Event("mouseenter", { bubbles: false }));
    await sleep(30);
    ok(kebab.classList.contains("is-open"), "鼠标移入菜单展开");
    ok(chip.classList.contains("chip-menu-open"), "悬停展开也走同一套抬层逻辑");

    kebab.dispatchEvent(new window.Event("mouseleave", { bubbles: false }));
    await sleep(260);        // 代码里留了 160ms 的隐藏延迟
    ok(!chip.classList.contains("chip-menu-open"), "移出后延迟收起并撤掉抬层");
  }

  console.log("\n[D] 弹出方向：下方放不下就向上弹");
  {
    // 默认（jsdom 里几何全 0）：下方空间充足，不加 chip-menu-up
    kebab.classList.remove("is-open");
    chip.classList.remove("chip-menu-open", "chip-menu-up");
    click(window, kebab);
    ok(!chip.classList.contains("chip-menu-up"), "空间充足时向下弹");

    // 模拟「最后一行命令」：卡片贴到窗口底部，下方只剩 8px
    const saved = chip.getBoundingClientRect;
    chip.getBoundingClientRect = () => ({
      top: 740, bottom: 760, left: 0, right: 120, width: 120, height: 20,
    });
    kebab.classList.remove("is-open");
    chip.classList.remove("chip-menu-open", "chip-menu-up");
    click(window, kebab);
    ok(chip.classList.contains("chip-menu-up"),
      "卡片贴底时改为向上弹（否则菜单被 #cmd-groups 底边裁掉）");

    chip.getBoundingClientRect = saved;
    click(window, kebab);          // 收起，恢复干净状态
  }

  clearTimeout(watchdog);
  console.log("\n==============================================");
  console.log("结果：" + pass + " 通过 / " + fail + " 失败");
  console.log("==============================================");
  process.exit(fail ? 1 : 0);
})();
