/* jsdom 前端行为测试：状态信息抽离到顶栏跑马灯 + 点击弹窗看全量
   背景：原先底部常驻的 .status-bar 已撤除（内容区整块让给 logcat / 文件表格），
   核心运行信息改为顶栏右侧横向滚动条，点击展开完整历史弹窗，#status 住在弹窗里。
   覆盖：结构改法本身、状态行仍只有一个 DOM、跑马灯内容/语义色、弹窗开关三路径、
        清空后回到空态、滚动只加在内容超宽时。 */
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
function mkEnv(batches) {
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
  const { window } = dom;
  let round = 0;
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
  return window;
}
const statusLines = (doc) => Array.from(doc.querySelectorAll("#status .line")).map((d) => d.textContent);
const tickerText = (doc) => doc.getElementById("ticker-seq-a").textContent;
function click(el) {
  const w = el.ownerDocument.defaultView;
  el.dispatchEvent(new w.Event("click", { bubbles: true }));
}
function pressKey(win, key) {
  win.document.dispatchEvent(new win.KeyboardEvent("keydown", { key, bubbles: true }));
}
const modalOpen = (doc) => !doc.getElementById("status-modal").classList.contains("hidden");

(async () => {
  console.log("\n[1] 结构：底部状态栏已撤除，跑马灯与状态弹窗就位");
  ok(!/class="status-bar"/.test(html), "HTML 中已无 .status-bar 常驻栏");
  ok(/id="status-ticker"/.test(html), "顶栏存在 #status-ticker 跑马灯按钮");
  ok(/id="status-modal"/.test(html), "存在 #status-modal 状态弹窗");
  ok(/id="btn-copy-status"/.test(html) && /id="btn-clear-status"/.test(html),
     "弹窗内保留「复制 / 清空」按钮");
  // #status 必须住在弹窗内：全局只此一份 DOM，关闭时随弹窗一起隐藏
  ok(/id="status-modal"[\s\S]*?id="status"/.test(html), "#status 位于状态弹窗内部");

  console.log("\n[2] 状态行仍写入 #status，跑马灯同步显示最近状态");
  {
    const window = mkEnv([
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
       { kind: "tool", payload: { type: "info", text: "刷新完成：3 台设备" } },
       { kind: "tool", payload: { type: "ok", text: "已保存截图 A1.png" } }],
    ]);
    const doc = window.document;
    ok(await waitFor(() => statusLines(doc).length >= 2, 4000, "状态行就绪"), "状态行写入 #status");
    ok(statusLines(doc).includes("已保存截图 A1.png"), "#status 含最新一条状态文本");
    ok(await waitFor(() => tickerText(doc).indexOf("刷新完成") >= 0, 4000, "跑马灯刷新"),
       "跑马灯文本包含最近状态");
    ok(tickerText(doc).indexOf("已保存截图") >= 0, "跑马灯带最新一条（不只是第一条）");
    ok(doc.getElementById("ticker-count").textContent === "2", "计数显示已积累的行数");
    ok(/ok/.test(doc.getElementById("ticker-led").className),
       "状态灯跟随最近一条的语义色（此处为 ok）");
    ok(doc.querySelectorAll("#status-ticker-seq-a, #ticker-seq-a").length === 1 &&
       doc.querySelector("#ticker-seq-b"), "跑马灯有第二份同内容轨道用于无缝循环");
  }

  console.log("\n[3] 点击跑马灯打开弹窗，×/ESC/点背景都能关");
  {
    const window = mkEnv([
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
       { kind: "tool", payload: { type: "warn", text: "已跳过 root 切换" } }],
    ]);
    const doc = window.document;
    await waitFor(() => statusLines(doc).length > 0, 4000, "状态行就绪");
    ok(modalOpen(doc) === false, "初始为关闭状态");
    click(doc.getElementById("status-ticker"));
    ok(modalOpen(doc), "点击跑马灯 → 弹窗打开");
    ok(statusLines(doc).includes("已跳过 root 切换"), "弹窗复用同一份 #status（含全部历史）");

    click(doc.getElementById("status-modal-close"));
    ok(modalOpen(doc) === false, "点 × → 关闭");

    click(doc.getElementById("status-ticker"));
    pressKey(window, "Escape");
    ok(modalOpen(doc) === false, "ESC → 关闭");

    click(doc.getElementById("status-ticker"));
    const modal = doc.getElementById("status-modal");
    click(modal);   // 点背景（事件 target 就是 .modal 本身）
    ok(modalOpen(doc) === false, "点背景 → 关闭");
  }

  console.log("\n[4] 清空：DOM 与跑马灯一起回到空态");
  {
    // 分两轮投递：第一轮先落一条（跑马灯该显示出来），第二轮再 clear。
    // 若与 clear 同批到达，那条状态压根没渲染过就被清掉，跑马灯自然一直是空态。
    const window = mkEnv([
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
       { kind: "tool", payload: { type: "info", text: "第一条" } }],
      [{ kind: "tool", payload: { type: "clear" } }],
    ]);
    const doc = window.document;
    ok(await waitFor(() => tickerText(doc).indexOf("第一条") >= 0, 4000, "先出现一条"),
       "先出现一条状态");
    ok(await waitFor(() => doc.getElementById("ticker-count").textContent === "0", 4000, "清空生效"),
       "clear 事件后计数归零");
    ok(statusLines(doc).length === 0, "#status 已清空");
    ok(tickerText(doc).indexOf("暂无状态") >= 0, "跑马灯回到空态提示");
    ok(!/ok|warn|err/.test(doc.getElementById("ticker-led").className),
       "空态时状态灯不带语义色");
  }

  console.log("\n[5] 滚动：只在内容宽于视口时加 .rolling（jsdom 无布局 → 不加）");
  {
    const window = mkEnv([
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } }],
    ]);
    const doc = window.document;
    await sleep(60);
    ok(!doc.getElementById("status-ticker").classList.contains("rolling"),
       "内容不超宽时不滚动（不会无意义地一直飘）");
    // 两份轨道内容必须一致，否则循环接缝处会看到内容跳变
    ok(doc.getElementById("ticker-seq-a").textContent ===
       doc.getElementById("ticker-seq-b").textContent,
       "两份轨道内容完全一致（首尾相接不跳变）");
  }

  console.log("\n结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();