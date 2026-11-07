/* jsdom 前端行为测试：工具页「子 tab」结构（设备截图 / 设备录屏 / 投屏 /
   应用安装 / 诊断包）。

   原先是五张卡竖排、各自可收起；现改成同层级的五个子 tab，点哪个就整页显示
   那一项功能，互不挤压。这里锁四件事：
   1) 结构：#tool-subtabs 下 5 个 .tool-subtab 按钮（data-tool-tab=
      shot/rec/scrcpy/apk/diag），#tool-panes 下 5 个对应的
      .tool-pane[data-tool-pane=...]；每张卡仍是 .tool-card（.tool-h + .tool-body），
      但标题栏不再可折叠（无 .tool-h--toggle / .collapsed / .tool-chevron）；
   2) 样式：没有两列网格（退回并排会在这里失败）；未激活的面板真的被
      [hidden] 隐藏；.tool-subtab 走 tab 视觉语言（手型光标 + 选中态）；
   3) 行为：点子 tab 只切自己那一项——被点的 active、对应面板显示、其余面板
      hidden，互不牵连；
   4) 回填：启动时默认激活「设备截图」子 tab，其余面板初始化为 hidden。 */
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
function block(selector) {
  const i = css.indexOf(selector);
  if (i < 0) return null;
  let depth = 0, started = false, end = i;
  for (let k = i; k < css.length; k++) {
    const c = css[k];
    if (c === "{") { depth++; started = true; }
    else if (c === "}") { depth--; if (started && depth === 0) { end = k; break; } }
  }
  return css.slice(i, end + 1);
}

const TABS = ["shot", "rec", "scrcpy", "apk", "diag"];
const PANE_OF = {
  shot: ["tool-shot"],
  rec: ["tool-rec"],
  scrcpy: ["tool-scrcpy", "mirror-preview"],
  apk: ["apk-install"],
  diag: ["diag-build", "diag-download"],
};

async function boot(settings) {
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
  const { window } = dom;
  const calls = [];
  let round = 0;
  const st = settings || {};
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          calls.push({ fn: k, args });
          if (k === "boot") {
            return Promise.resolve({ version: "v-test", warnings: [], adb: "adb",
                                     commands: [], settings: st });
          }
          if (k === "take_events") {
            const b = round === 0
              ? [{ kind: "booted",
                   payload: { version: "v-test", warnings: [], adb: "adb",
                              commands: [], settings: st } }]
              : [];
            round++;
            return Promise.resolve(b);
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

const click = (doc, el) => el.dispatchEvent(
  new doc.defaultView.Event("click", { bubbles: true }));
const subBtn = (doc, key) => doc.querySelector('.tool-subtab[data-tool-tab="' + key + '"]');
const pane = (doc, key) => doc.querySelector('.tool-pane[data-tool-pane="' + key + '"]');

(async () => {
  const watchdog = setTimeout(() => {
    console.log("    (看门狗触发：疑似断言抛错导致未收尾，按当前结果退出)");
    process.exit(fail ? 1 : 0);
  }, 60000);

  console.log("[1] 结构：5 个子 tab + 5 个面板，顺序一致、控件都在面板内");
  {
    const doc = new JSDOM(html).window.document;
    const tools = doc.querySelector('section.tab[data-tab="tools"]');
    ok(!!tools, "工具页 section 存在");

    const subtabs = Array.from(doc.querySelectorAll("#tool-subtabs .tool-subtab"));
    ok(subtabs.length === 5, "5 个子 tab 都在 #tool-subtabs 内（实际 " + subtabs.length + "）");
    ok(subtabs.map((b) => b.dataset.toolTab).join(",") === TABS.join(","),
       "自上而下：截图 → 录屏 → 投屏 → 应用安装 → 诊断（实际 " +
       subtabs.map((b) => b.dataset.toolTab).join(",") + "）");
    ok(!tools.querySelector(".tool-pair"), "没有并排用的 .tool-pair 容器");

    const panes = Array.from(doc.querySelectorAll("#tool-panes .tool-pane"));
    ok(panes.length === 5, "5 个面板都在 #tool-panes 内（实际 " + panes.length + "）");
    ok(panes.map((p) => p.dataset.toolPane).join(",") === TABS.join(","),
       "面板顺序与子 tab 顺序对齐（实际 " +
       panes.map((p) => p.dataset.toolPane).join(",") + "）");

    // 每张卡仍是 .tool-card（.tool-h + .tool-body），但标题栏不可折叠
    TABS.forEach((key) => {
      const p = pane(doc, key);
      ok(!!p, "#" + key + " 面板存在");
      const card = p.querySelector(":scope > .tool-card");
      ok(!!card, "#" + key + " 面板里是一张 .tool-card");
      ok(!!card.querySelector(":scope > .tool-h"), "#" + key + " 卡有 .tool-h 标题（非折叠）");
      ok(!!card.querySelector(":scope > .tool-body"), "#" + key + " 卡有 .tool-body 内容区");
      ok(!card.querySelector(".tool-h--toggle"), "#" + key + " 标题栏不是可折叠 .tool-h--toggle");
      ok(!card.querySelector(".tool-chevron"), "#" + key + " 没有折叠箭头 .tool-chevron");
      ok(!card.classList.contains("collapsed"), "#" + key + " 卡不带 collapsed 收起态");
    });

    // 交互元素必须都在各自面板内，否则切到别处时按钮会跟着露出来
    ok(doc.querySelector('.tool-pane[data-tool-pane="shot"] #tool-shot'), "截图按钮在 shot 面板内");
    ok(doc.querySelector('.tool-pane[data-tool-pane="rec"] #tool-rec'), "开始录制按钮在 rec 面板内");
    ok(doc.querySelector('.tool-pane[data-tool-pane="apk"] #apk-install'), "安装按钮在 apk 面板内");
    ok(doc.querySelector('.tool-pane[data-tool-pane="scrcpy"] #tool-scrcpy'), "投屏按钮在 scrcpy 面板内");
    ok(doc.querySelector('.tool-pane[data-tool-pane="scrcpy"] #mirror-preview'),
       "备用投屏的预览块在 scrcpy 面板内（切走时一并隐藏）");
  }

  console.log("\n[2] 样式：一列面板 + 未激活面板真被隐藏 + 子 tab 走 tab 视觉");
  {
    ok(!/\.tool-pair\s*\{/.test(css), "样式表里没有 .tool-pair 两列网格");
    ok(/\.tool-pane\[hidden\]\s*\{\s*display:\s*none/.test(css),
       ".tool-pane[hidden] 设了 display:none（未激活面板隐藏）");
    const sub = block(".tool-subtab {");
    ok(!!sub, ".tool-subtab 规则存在");
    ok(/cursor:\s*pointer/.test(sub || ""), "子 tab 常态是手型光标（可点）");
    const act = block(".tool-subtab.active {");
    ok(!!act, ".tool-subtab.active 规则存在");
    ok(/var\(--accent\)/.test(act || ""), "选中态用磷光青（与全站 tab 语言一致）");
    ok(/is-dragging/.test(css) && /\.tool-subtab\.is-dragging\s*\{/.test(css),
       "拖动中的子 tab 有 is-dragging 降透明度样式");
  }

  console.log("\n[3] 点子 tab 只切自己那一项（active + 面板显隐互不牵连）");
  {
    const { window } = await boot();
    const doc = window.document;
    ok(await waitFor(() => !!subBtn(doc, "shot"), 4000, "页面就绪"),
       "子 tab 渲染完成");

    click(doc, subBtn(doc, "rec"));
    await sleep(60);
    ok(subBtn(doc, "rec").classList.contains("active"), "点录屏 → rec 子 tab active");
    ok(subBtn(doc, "shot").classList.contains("active") === false, "截图子 tab 不再 active");
    ok(pane(doc, "rec").hidden === false, "rec 面板显示");
    ok(pane(doc, "shot").hidden === true, "shot 面板被隐藏");
    ok(pane(doc, "apk").hidden === true && pane(doc, "diag").hidden === true,
       "其余面板保持 hidden");

    // 键盘等价：role=tab 必须能用 Enter / 空格触发
    subBtn(doc, "scrcpy").dispatchEvent(
      new window.KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await sleep(60);
    ok(subBtn(doc, "scrcpy").classList.contains("active"), "Enter 键也能切到投屏子 tab");
    ok(pane(doc, "scrcpy").hidden === false, "scrcpy 面板显示");
    ok(pane(doc, "rec").hidden === true, "rec 面板被隐藏");
    window.close();
  }

  console.log("\n[4] 启动默认激活「设备截图」子 tab，其余面板 hidden");
  {
    const { window } = await boot();
    const doc = window.document;
    ok(await waitFor(() => subBtn(doc, "shot"), 4000, "页面就绪"),
       "页面就绪");
    ok(subBtn(doc, "shot").classList.contains("active"), "默认 shot 子 tab active");
    ok(pane(doc, "shot").hidden === false, "shot 面板可见");
    ok(TABS.slice(1).every((k) => pane(doc, k).hidden === true),
       "其余 4 个面板初始化为 hidden");
    window.close();
  }

  console.log("\n[5] 缺省 / 非法 tab 顺序不破坏结构（回退默认）");
  {
    const { window } = await boot({ tool_tab_order: "not-a-real-tab" });
    const doc = window.document;
    ok(await waitFor(() => subBtn(doc, "shot"), 4000, "页面就绪"),
       "页面就绪");
    ok(Array.from(doc.querySelectorAll("#tool-subtabs .tool-subtab"))
         .map((b) => b.dataset.toolTab).join(",") === TABS.join(","),
       "非法顺序只落一个未知 tab 时不打乱默认顺序");
    window.close();
  }

  console.log("\n[6] 录屏面板：设备音频 / 级别行已撤掉，电脑麦克风恢复（共 5 个开关）");
  {
    const doc = new JSDOM(html).window.document;
    ["rec-devaudio", "rec-levels", "rec-lc-levels"].forEach((id) => {
      ok(!doc.getElementById(id), "#" + id + " 已从界面上撤掉");
    });
    ok(!!doc.getElementById("rec-mic"), "电脑麦克风开关已恢复（仅录本机麦克风说话声）");
    const opts = doc.querySelector("#rec-body .rec-opts");
    ok(!!opts, "开关容器 .rec-opts 仍在 #rec-pane 内");
    const ids = Array.from(opts.querySelectorAll("input[type=checkbox]"))
      .map((c) => c.id);
    ok(ids.join(",") === "rec-logcat,rec-mic,rec-zip,rec-pointer-location,rec-show-touches",
       "开关顺序：同步 logcat / 电脑麦克风 / 打包 zip / 指针位置 / 触摸圆点（实际 "
       + ids.join(",") + "）");
    ok(ids.indexOf("rec-logcat") === 0, "「同步录制 logcat」仍是第一个开关");
  }

  clearTimeout(watchdog);
  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
