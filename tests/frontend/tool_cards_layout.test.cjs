/* jsdom 前端行为测试：工具页三张卡（截图 / 录屏 / 投屏）竖排 + 各自的收起按钮

   版式走过的弯路：先是三张卡各占一整行（投屏要往下滚），后来把「截图 / 录屏」
   并成两列（两列内容量差太多、勾选项被挤成两行）。现在统一成「自上而下一列 +
   每张卡标题栏可收起」——想看的展开，不看的收成一行标题。这里锁四件事：
   1) 结构：三张卡是工具页 section 的直接子元素，按 截图 → 录屏 → 投屏 排列，
      每张都有 .tool-h--toggle 标题与 .tool-body 内容区；
   2) 样式：没有两列网格（退回并排会在这里失败），收起态真的隐藏 .tool-body；
   3) 行为：点标题只折自己那张卡，收起态各自落盘（shot_collapsed /
      rec_collapsed / scrcpy_collapsed），三张互不牵连；
   4) 回填：启动时按各自的键还原收起态，缺省保持 HTML 的展开态。 */
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

const CARDS = [
  { id: "shot-card", toggle: "shot-toggle", body: "shot-body", key: "shot_collapsed" },
  { id: "rec-card", toggle: "rec-toggle", body: "rec-body", key: "rec_collapsed" },
  { id: "apk-card", toggle: "apk-toggle", body: "apk-body", key: "apk_collapsed" },
  { id: "scrcpy-card", toggle: "scrcpy-toggle", body: "scrcpy-body", key: "scrcpy_collapsed" },
];

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
const savedPrefs = (calls) =>
  calls.filter((c) => c.fn === "save_settings").map((c) => c.args[0]);
const folded = (doc, id) => doc.getElementById(id).classList.contains("collapsed");

(async () => {
  const watchdog = setTimeout(() => {
    console.log("    (看门狗触发：疑似断言抛错导致未收尾，按当前结果退出)");
    process.exit(fail ? 1 : 0);
  }, 60000);

  console.log("[1] 结构：四张卡竖排、各自带折叠标题与内容区");
  {
    const doc = new JSDOM(html).window.document;
    const tools = doc.querySelector('section.tab[data-tab="tools"]');
    ok(!!tools, "工具页 section 存在");

    const cards = Array.from(tools.querySelectorAll(":scope > .tool-card"));
    ok(cards.length === 4, "四张卡都是 section 的直接子元素（实际 " + cards.length + "）");
    ok(cards.map((c) => c.id).join(",") === "shot-card,rec-card,apk-card,scrcpy-card",
       "自上而下：截图 → 录屏 → 应用安装 → 投屏（实际 " + cards.map((c) => c.id).join(",") + "）");
    ok(!tools.querySelector(".tool-pair"), "没有并排用的 .tool-pair 容器");

    CARDS.forEach((d) => {
      const card = doc.getElementById(d.id);
      ok(!!card, "#" + d.id + " 存在");
      const h = card.querySelector(":scope > .tool-h--toggle");
      ok(!!h && h.id === d.toggle, "#" + d.id + " 有可点标题 #" + d.toggle);
      ok(h && h.getAttribute("aria-expanded") === "true",
         "#" + d.id + " 初始 aria-expanded=true（展开）");
      ok(h && h.getAttribute("aria-controls") === d.body,
         "#" + d.id + " 的 aria-controls 指向 #" + d.body);
      const body = card.querySelector(":scope > .tool-body");
      ok(!!body && body.id === d.body, "#" + d.id + " 有内容区 #" + d.body);
      ok(!!card.querySelector(".tool-chevron"), "#" + d.id + " 标题右侧有折叠箭头");
    });

    // 交互元素必须都在内容区里：否则收起时按钮仍露在标题下，看着像没收起
    ok(doc.querySelector("#shot-body #tool-shot"), "截图按钮在 #shot-body 内");
    ok(doc.querySelector("#rec-body #tool-rec"), "开始录制按钮在 #rec-body 内");
    ok(doc.querySelector("#apk-body #apk-install"), "安装按钮在 #apk-body 内");
    ok(doc.querySelector("#scrcpy-body #tool-scrcpy"), "投屏按钮在 #scrcpy-body 内");
    ok(doc.querySelector("#scrcpy-body #mirror-preview"),
       "备用投屏的预览块在 #scrcpy-body 内（收起时一并隐藏）");
  }

  console.log("\n[2] 样式：一列堆叠 + 收起真的隐藏内容");
  {
    ok(!/\.tool-pair\s*\{/.test(css), "样式表里没有 .tool-pair 两列网格");
    const b = block(".tool-card {");
    ok(!!b && /margin-bottom:\s*14px/.test(b),
       ".tool-card 仍靠 margin-bottom 拉开竖向间距（不依赖 grid gap）");
    ok(/\.tool-card\.collapsed\s+\.tool-body\s*\{\s*display:\s*none/.test(css),
       ".tool-card.collapsed .tool-body 设了 display:none");
    ok(/\.tool-card\.collapsed\s+\.tool-chevron\s*\{\s*transform:\s*rotate\(-90deg\)/.test(css),
       "收起时箭头转 -90°（指向右 = 已折叠）");
    ok(/\.tool-h--toggle\s*\{\s*cursor:\s*pointer/.test(css),
       "折叠标题是手型光标（可点）");
  }

  console.log("\n[3] 点标题只折自己那张卡，收起态各自落盘");
  {
    const { window, calls } = await boot();
    const doc = window.document;
    ok(await waitFor(() => !!doc.getElementById("shot-toggle"), 4000, "页面就绪"),
       "四张卡渲染完成");
    ok(!folded(doc, "shot-card") && !folded(doc, "rec-card")
       && !folded(doc, "apk-card") && !folded(doc, "scrcpy-card"),
       "初始四张卡都是展开态");

    click(doc, doc.getElementById("shot-toggle"));
    await sleep(80);
    ok(folded(doc, "shot-card"), "点截图标题 → 截图卡收起");
    ok(!folded(doc, "rec-card"), "录屏卡不受影响");
    ok(!folded(doc, "apk-card"), "应用安装卡不受影响");
    ok(!folded(doc, "scrcpy-card"), "投屏卡不受影响");
    ok(doc.getElementById("shot-toggle").getAttribute("aria-expanded") === "false",
       "收起后 aria-expanded=false");
    ok(await waitFor(() => savedPrefs(calls).some((p) => p.shot_collapsed === true),
                     3000, "shot_collapsed"),
       "收起态落盘 shot_collapsed=true");
    ok(!savedPrefs(calls).some((p) => "rec_collapsed" in p),
       "没有顺手把 rec_collapsed 也写一遍");

    // 键盘等价：role=button 必须能用 Enter / 空格触发
    doc.getElementById("scrcpy-toggle").dispatchEvent(
      new window.KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await sleep(60);
    ok(folded(doc, "scrcpy-card"), "Enter 键也能折叠投屏卡");
    doc.getElementById("rec-toggle").dispatchEvent(
      new window.KeyboardEvent("keydown", { key: " ", bubbles: true }));
    await sleep(60);
    ok(folded(doc, "rec-card"), "空格键也能折叠录屏卡");

    click(doc, doc.getElementById("shot-toggle"));
    await sleep(80);
    ok(!folded(doc, "shot-card"), "再点一次展开");
    ok(await waitFor(() => {
      const last = savedPrefs(calls).filter((p) => "shot_collapsed" in p).pop();
      return last && last.shot_collapsed === false;
    }, 3000, "shot_collapsed=false"), "展开态同样落盘（false）");
    window.close();
  }

  console.log("\n[4] 启动按各自键还原收起态");
  {
    const { window } = await boot({ shot_collapsed: true, scrcpy_collapsed: true });
    const doc = window.document;
    ok(await waitFor(() => folded(doc, "shot-card"), 4000, "截图卡还原"),
       "shot_collapsed=true → 截图卡启动即收起");
    ok(folded(doc, "scrcpy-card"), "scrcpy_collapsed=true → 投屏卡启动即收起");
    ok(!folded(doc, "rec-card"), "没给 rec_collapsed 的录屏卡保持展开（不被连带）");
    window.close();
  }

  console.log("\n[5] 缺省 / 非法值保持展开（不被误折）");
  {
    const { window } = await boot({ shot_collapsed: "yes" });
    const doc = window.document;
    ok(await waitFor(() => !!doc.getElementById("shot-toggle"), 4000, "页面就绪"),
       "页面就绪");
    ok(!folded(doc, "shot-card"), "字符串 \"yes\" 不是布尔 → 保持 HTML 的展开态");
    window.close();
  }

  console.log("\n[6] 录屏卡：音频 / 麦克风 / 级别行已撤掉，只剩 4 个开关");
  {
    const doc = new JSDOM(html).window.document;
    ["rec-devaudio", "rec-mic", "rec-levels", "rec-lc-levels"].forEach((id) => {
      ok(!doc.getElementById(id), "#" + id + " 已从界面上撤掉");
    });
    const opts = doc.querySelector("#rec-body .rec-opts");
    ok(!!opts, "开关容器 .rec-opts 仍在 #rec-body 内");
    const ids = Array.from(opts.querySelectorAll("input[type=checkbox]"))
      .map((c) => c.id);
    ok(ids.join(",") === "rec-logcat,rec-zip,rec-pointer-location,rec-show-touches",
       "只剩 同步 logcat / 打包 zip / 指针位置 / 触摸圆点（实际 " + ids.join(",") + "）");
    ok(ids.indexOf("rec-logcat") === 0, "「同步录制 logcat」仍是第一个开关");
  }

  clearTimeout(watchdog);
  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
