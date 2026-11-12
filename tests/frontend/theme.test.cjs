/* jsdom 前端行为测试：顶栏主题切换（深 / 浅 / 随系统 三态）
   覆盖：
     [1] 控件存在且三态齐全；默认启动为深色（与 :root 默认一致，无闪白）
     [2] 启动按 config.theme 还原（light / system 解析 / 非法值回落 dark）
     [3] 点击切换：立即套色 + 持久化 save_settings({theme}) + 联动后端 set_theme
     [4] 随系统（system）跟随系统 prefers-color-scheme 变化实时改色

   回归背景：FIX_NOTES「仍未做」明确记载浅色主题 / 标题栏配色联动是功能缺口；
   本次补齐后，最怕「切换只是改了按钮高亮、界面没变色」或「system 不跟随系统」。 */
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

/** 可外部控制的 matchMedia 桩：matches 可变，支持手动触发 change。 */
function mkMatchMedia(initialMatches) {
  const state = { matches: initialMatches, listeners: [] };
  return {
    get matches() { return state.matches; },
    media: "(prefers-color-scheme: dark)",
    addEventListener(ev, fn) { if (ev === "change") state.listeners.push(fn); },
    removeEventListener() {},
    addListener(fn) { state.listeners.push(fn); },
    removeListener() {},
    __set(v) { state.matches = v; },
    __fire() { state.listeners.forEach((f) => f()); },
  };
}

/** 起一个带调用记录的假后端；settings 模拟 config.json，opts.matchMedia 注入 matchMedia 桩。 */
function mkEnv(settings, opts) {
  opts = opts || {};
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const calls = [];
  let round = 0;
  const batches = [[
    { kind: "booted", payload: {
      version: "v-test", warnings: [], commands: [], settings: settings || {} },
    },
  ]];
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          calls.push({ api: k, args });
          if (k === "boot") return Promise.resolve({ ok: true });
          if (k === "take_events") {
            const b = batches[round] || [];
            round++;
            return Promise.resolve(b);
          }
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  // 默认摘掉 jsdom 的 matchMedia（若有），避免「Not implemented」干扰；
  // 需要 system 解析的用例在 opts.matchMedia 显式注入可控桩。
  window.matchMedia = opts.matchMedia || undefined;
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  return { window, calls };
}

const themeCalls = (calls) => calls.filter((c) => c.api === "set_theme");
const saveThemeCalls = (calls) =>
  calls.filter((c) => c.api === "save_settings" && c.args[0] && "theme" in c.args[0]);
const themeOf = (window) => window.document.documentElement.dataset.theme || "dark";
const activeMode = (window) => {
  const b = window.document.querySelector(".theme-switch .theme-opt.active");
  return b ? b.dataset.themeMode : null;
};

(async () => {
  console.log("\n[1] 控件存在且三态齐全；默认启动为深色");
  {
    const { window } = mkEnv();
    const opts = window.document.querySelectorAll(".theme-switch .theme-opt");
    ok(opts.length === 3, "存在 深 / 浅 / 随 三个选项");
    const modes = Array.from(opts).map((b) => b.dataset.themeMode).sort().join(",");
    ok(modes === "dark,light,system", "三个选项分别是 dark/light/system（实际：" + modes + "）");
    ok(await waitFor(() => activeMode(window) === "dark", 3000, "默认高亮 dark"),
       "默认高亮「深」档（与 :root 默认深色一致）");
    ok(themeOf(window) === "dark" && !window.document.documentElement.hasAttribute("data-theme"),
       "默认不写 data-theme（即深色，避免浅色模式下的闪白）");
  }

  console.log("\n[2] 启动按 config.theme 还原");
  {
    const { window } = mkEnv({ theme: "light" });
    ok(await waitFor(() => themeOf(window) === "light", 3000, "套用浅色"),
       "config.theme=light 启动即浅色（data-theme=light）");
    ok(activeMode(window) === "light", "「浅」档高亮");
  }
  {
    // 非法值（如手改 config.json 写成 neon）经后端 sanitize 已回落 dark；
    // 这里直接喂原始非法值，前端也要兜底回落 dark 而非崩。
    // 注意：无 data-theme 时 themeOf 恒为 "dark"，故必须等高亮「深」档落定
    // （它只在 boot 的 setTheme 跑完 syncThemeSwitch 后才成立），否则会在
    // boot 前提前断言通过。
    const { window } = mkEnv({ theme: "neon" });
    ok(await waitFor(() => activeMode(window) === "dark", 3000, "非法值回落 dark 高亮"),
       "theme=neon（非法）回落深色且高亮「深」档");
    ok(themeOf(window) === "dark" && !window.document.documentElement.hasAttribute("data-theme"),
       "非法值不写 data-theme（即深色）");
  }
  {
    // 缺省（config.json 里没有 theme 这一项）保持默认深色
    const { window } = mkEnv({});
    ok(await waitFor(() => activeMode(window) === "dark", 3000, "缺省深色高亮"),
       "settings 无 theme 项时保持默认深色且高亮「深」档");
  }

  console.log("\n[3] 点击切换：立即套色 + 持久化 + 联动后端");
  {
    const { window, calls } = mkEnv();
    await waitFor(() => activeMode(window) === "dark", 3000, "就绪");
    const lightBtn = window.document.querySelector('.theme-switch .theme-opt[data-theme-mode="light"]');
    lightBtn.click();
    ok(await waitFor(() => themeOf(window) === "light", 2000, "点浅色套色"),
       "点「浅」后界面立即变浅色");
    ok(activeMode(window) === "light", "「浅」档高亮、其余取消");
    ok(await waitFor(() => saveThemeCalls(calls).some((c) => c.args[0].theme === "light"),
         2000, "持久化 theme=light"),
       "切换要持久化（save_settings({theme:'light'})）");
    ok(themeCalls(calls).some((c) => c.args[0] === "light"),
       "切换要联动后端 set_theme('light')（原生标题栏）");

    // 再切回深色：data-theme 应被移除（回到 :root 默认）
    const darkBtn = window.document.querySelector('.theme-switch .theme-opt[data-theme-mode="dark"]');
    darkBtn.click();
    ok(await waitFor(() => themeOf(window) === "dark"
         && !window.document.documentElement.hasAttribute("data-theme"), 2000, "点深色移除属性"),
       "点「深」后移除 data-theme（回到默认深色）");
    ok(saveThemeCalls(calls).some((c) => c.args[0].theme === "dark"),
       "切回深色同样持久化");
  }
  {
    // 随系统（system）也要持久化并以 system 形式落盘（不是解析后的颜色）
    const { window, calls } = mkEnv();
    await waitFor(() => activeMode(window) === "dark", 3000, "就绪");
    const sysBtn = window.document.querySelector('.theme-switch .theme-opt[data-theme-mode="system"]');
    sysBtn.click();
    ok(await waitFor(() => activeMode(window) === "system", 2000, "高亮 system"),
       "点「随」后高亮「随」档");
    ok(saveThemeCalls(calls).some((c) => c.args[0].theme === "system"),
       "system 以模式（而非解析颜色）落盘");
  }

  console.log("\n[4] 随系统：跟随系统主题变化实时改色");
  {
    const mql = mkMatchMedia(false); // 系统=浅色
    const { window, calls } = mkEnv({ theme: "system" }, { matchMedia: (q) => mql });
    ok(await waitFor(() => themeOf(window) === "light", 3000, "system→浅色"),
       "系统浅色时 system 模式解析为浅色");
    // 系统切到深色：触发 change，界面应实时变深
    mql.__set(true);
    mql.__fire();
    ok(await waitFor(() => themeOf(window) === "dark", 2000, "系统切换→深色"),
       "系统切到深色后界面实时变深（不刷新页面）");
    // 系统切回浅色
    const sysCallsBefore = themeCalls(calls).filter((c) => c.args[0] === "system").length;
    mql.__set(false);
    mql.__fire();
    ok(await waitFor(() => themeOf(window) === "light", 2000, "系统切换→浅色"),
       "系统切回浅色后界面实时变浅");
    // 原生标题栏也必须跟着换：它的深浅是后端读注册表（AppsUseLightTheme）解析的，
    // 前端不通知后端的话，用户在系统里切浅/深色后**界面变了、标题栏还是旧颜色**。
    // 必须比**增量**：启动时 applyBootSettings 已经调过一次 set_theme('system')，
    // 只看「有没有调过」会一直为真，抓不到这次的回归。
    const sysCallsAfter = themeCalls(calls).filter((c) => c.args[0] === "system").length;
    ok(sysCallsAfter > sysCallsBefore,
       "系统主题变化时联动后端 set_theme('system')（原生标题栏同步）");
  }

  console.log("\n结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
