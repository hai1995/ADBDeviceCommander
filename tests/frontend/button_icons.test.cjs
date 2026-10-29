/* jsdom 前端测试：按钮图标（data-icon → 启动时注入内联 SVG）

   本轮为「给按钮加适配图标」锁约定：
     · app.js 集中定义图标表 BTN_ICONS，并提供 makeIcon / decorateIcons；
     · 关键操作按钮在 index.html 里只加 data-icon="名字"，启动后注入 <svg class="btn-ic">；
     · 注入后按钮 textContent 仍是原标签文字（不影响既有按文字断言的测试）；
     · 文案会被动态改写的按钮（复制 / 侧栏收起 / 关闭 ×）刻意不加图标，
       否则 textContent 一赋值就把图标抹掉、也会干扰精确文案断言；
     · 目录/文件表格里动态生成的按钮（mkAct）同样带图标。 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.join(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "frontend/index.html"), "utf8");
const js = fs.readFileSync(path.join(ROOT, "frontend/js/app.js"), "utf8");
const css = fs.readFileSync(path.join(ROOT, "frontend/css/app.css"), "utf8");

process.on("unhandledRejection", () => {});

let pass = 0, fail = 0;
function ok(c, n) {
  if (c) { pass++; console.log("  ✓ " + n); }
  else { fail++; console.log("  ✗ " + n); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitFor(fn, ms = 4000, label = "") {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    let v = false; try { v = !!fn(); } catch (e) { v = false; }
    if (v) return true;
    await sleep(40);
  }
  console.log("    (waitFor 超时: " + label + ")");
  return false;
}

function mkEnv(extraEvents) {
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  let round = 0;
  const batches = [
    [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [], adb: "adb" } },
     { kind: "devices", payload: { items: [{ serial: "A1", ok: true, checked: true }] } }]
      .concat(extraEvents || []),
  ];
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function () {
          if (k === "boot") return Promise.resolve({ version: "v-test", warnings: [], commands: [], adb: "adb" });
          if (k === "take_events") { const b = batches[round] || []; round++; return Promise.resolve(b); }
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  return { window };
}

/* 看门狗：断言抛错会被 unhandledRejection 吞掉、jsdom 定时器又不停，到点按当前结果退出。 */
const watchdog = setTimeout(() => {
  console.log("    (看门狗触发：疑似断言抛错导致未收尾)");
  process.exit(fail ? 1 : 0);
}, 30000);

(async () => {
  console.log("\n[A] 图标表 / 注入逻辑存在");
  ok(/BTN_ICONS\s*=/.test(js), "app.js 集中定义 BTN_ICONS 图标表");
  ok(/function makeIcon/.test(js) && /function decorateIcons/.test(js), "makeIcon / decorateIcons 存在");
  ok(/decorateIcons\(document\)/.test(js), "启动时对文档执行图标注入");
  ok(/\.btn svg\s*\{[^}]*width:\s*13px/.test(css), "CSS 定义 .btn svg 尺寸（13px）");
  const di = (html.match(/data-icon="/g) || []).length;
  ok(di >= 30, "index.html 至少 30 个按钮带 data-icon（实际 " + di + "）");

  console.log("\n[B] 注入后：关键按钮有图标，且标签文字不变");
  {
    const { window } = mkEnv();
    const doc = window.document;
    await waitFor(() => !!doc.getElementById("btn-refresh"), 3000, "页面就绪");
    const chk = (id, label) => {
      const b = doc.getElementById(id);
      const svg = b && b.querySelector("svg.btn-ic");
      ok(!!svg, "#" + id + " 注入了 svg.btn-ic");
      ok(!!b && b.textContent.trim() === label,
        "#" + id + " 标签仍为「" + label + "」（实际：" + (b && b.textContent.trim()) + "）");
    };
    chk("btn-refresh", "刷新");
    chk("btn-run", "执行");
    chk("tool-shot", "立即截图");
    chk("file-mkdir", "新建文件夹");
    ok(doc.getElementById("btn-cmd-new").textContent.trim() === "新建",
      "#btn-cmd-new 去掉全角＋，标签为「新建」");
  }

  console.log("\n[C] 文案会变的按钮不加图标（避免被 textContent 覆盖 / 干扰精确断言）");
  {
    const { window } = mkEnv();
    const doc = window.document;
    ok(!/data-icon/.test(doc.getElementById("btn-copy-status").outerHTML),
      "#btn-copy-status 无 data-icon");
    ok(doc.getElementById("btn-copy-status").textContent === "复制",
      "#btn-copy-status 仍为纯文字「复制」");
    ok(doc.getElementById("btn-sidebar-collapse").textContent === "«",
      "侧栏收起按钮仍为纯箭头 «");
    ok(doc.getElementById("modal-close").textContent.trim() === "×", "关闭按钮仍为 ×");
  }

  console.log("\n[D] 动态文件行操作按钮也带图标（mkAct）");
  {
    const payload = { kind: "file", payload: {
      serial: "A1", path: "/",
      entries: [{ name: "a.txt", is_dir: false, size: 1 }],
    } };
    const { window } = mkEnv([payload]);
    const doc = window.document;
    const got = await waitFor(() => doc.querySelectorAll("#file-body tr").length >= 1, 4000, "文件行");
    ok(got, "文件行已渲染");
    const row = doc.querySelector("#file-body tr");
    const acts = row ? Array.from(row.querySelectorAll(".act .btn")) : [];
    const dl = acts.find((b) => b.textContent.trim() === "下载");
    ok(!!dl && !!dl.querySelector("svg.btn-ic"), "行内「下载」按钮带图标");
    ok(!!dl && dl.textContent.trim() === "下载", "行内「下载」标签文字不变");
  }

  clearTimeout(watchdog);
  console.log("\n" + "=".repeat(46));
  console.log("结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
