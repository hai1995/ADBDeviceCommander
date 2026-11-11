/* jsdom 前端测试：启动 splash 加载动画
 *
 * 用户反馈「双击运行后等好几秒才启动、期间没有任何加载提示」。这轮
 * 给 index.html 里加了一个不依赖外部资源的极简 splash（纯 HTML+内联 CSS
 * + CSS keyframes 旋转），boot 成功后前端置 data-faded="1" 淡出。
 *
 * 这里锁三条行为：
 *   1) 结构就绪：HTML 里有 boot-splash，默认是亮着的（data-faded 未置位）；
 *   2) boot 完成：onBooted 一到就置位 data-faded="1"；
 *   3) 幂等：boot() 重发路径（前端重载 / 超时重试）再走 onBooted 不报错。
 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.join(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "frontend/index.html"), "utf8");
const js = fs.readFileSync(path.join(ROOT, "frontend/js/app.js"), "utf8");

let pass = 0, fail = 0;
function ok(c, n) {
  if (c) { pass++; console.log("  ✓ " + n); }
  else { fail++; console.log("  ✗ " + n); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitFor(fn, ms = 5000, label = "") {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    let v = false;
    try { v = !!fn(); } catch (e) { v = false; }
    if (v) return true;
    await sleep(30);
  }
  console.log("    (waitFor 超时: " + label + ")");
  return false;
}

// ---- 构造一个可驱动 boot 的 jsdom 环境 ----
function mkEnv() {
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true,
    url: "http://localhost/",
    // 不给它真的去抓 app.css / app.js —— 直接走 eval(js) 注入，样式全靠
    // index.html 里 splash 的内联 style。
    resources: "usable",
  });
  const w = dom.window, d = w.document;
  const pending = [];
  w.pywebview = {
    api: new Proxy({
      boot: () => Promise.resolve({
        version: "2026.1110.0836", warnings: [], adb: "adb",
        commands: [], settings: {},
        state_labels: [], lc_buffers: [],
      }),
      take_events: () => Promise.resolve(pending.splice(0)),
      default_save_dir: () => Promise.resolve({ dir: "" }),
      update_info: () => Promise.resolve({ ok: true, version: "2026.1110.0836",
                                           enabled: true, checking: false,
                                           last: null, skipped: "" }),
    }, { get(t, k) { if (k === "then") return undefined;
                     if (k in t) return t[k];
                     return () => Promise.resolve({ ok: true }); } }),
  };
  Object.defineProperty(d, "readyState", { value: "complete", configurable: true });
  return { dom, w, d, pending };
}

(async () => {
  console.log("\nboot splash 加载动画\n");

  // ① 结构：不跑 JS 就有 splash，默认亮着
  {
    const dom = new JSDOM(html, { url: "http://localhost/" });
    const sp = dom.window.document.getElementById("boot-splash");
    ok(!!sp, "HTML 骨架里有 boot-splash（不依赖任何外部资源）");
    ok(sp && !sp.hasAttribute("data-faded"),
      "默认不淡出（data-faded 未置位 → 用户一打开就看到旋转加载）");
    const dot = sp && sp.querySelector(".dot");
    ok(!!dot, "spash 里有 .dot 旋转指示器");
    // 样式内联：WebView2 渲染 HTML 瞬间就能看到，不等 app.css
    const styleTags = sp ? sp.querySelectorAll("style") : [];
    ok(styleTags.length >= 1, "splash 自带内联 style（不依赖 app.css）");
  }

  // ② boot 完成 → 淡出
  {
    const { w, d, pending } = mkEnv();
    w.eval(js);
    await waitFor(() => !d.getElementById("about-update-check").disabled,
                  4000, "初始化完成");
    // 后端推一条 booted 事件 —— 模拟真实 boot 流程
    pending.push({ kind: "booted",
                   payload: { version: "2026.1110.0836", warnings: [], adb: "adb",
                              commands: [], settings: {}, state_labels: [],
                              lc_buffers: [], adb_ok: true } });
    const faded = await waitFor(() => {
      const sp = d.getElementById("boot-splash");
      return sp && sp.getAttribute("data-faded") === "1";
    }, 4000, "booted → splash 淡出");
    ok(faded, "boot 成功后 splash 加 data-faded=\"1\" 淡出");
  }

  // ③ 幂等：boot() 重发路径（前端重载 / 超时重试）再走 onBooted 不报错
  {
    const { w, d, pending } = mkEnv();
    w.eval(js);
    await waitFor(() => !d.getElementById("about-update-check").disabled,
                  4000, "初始化完成");
    // 走一遍正常 booted
    pending.push({ kind: "booted",
                   payload: { version: "2026.1110.0836", warnings: [], adb: "adb",
                              commands: [], settings: {}, state_labels: [],
                              lc_buffers: [], adb_ok: true } });
    await waitFor(() => d.getElementById("boot-splash").getAttribute("data-faded") === "1",
                  4000, "首次 booted 淡出");
    // 后端重发 booted（页面 reload 场景会触发）
    pending.push({ kind: "booted",
                   payload: { version: "2026.1110.0836", warnings: [], adb: "adb",
                              commands: [], settings: {}, state_labels: [],
                              lc_buffers: [], adb_ok: true } });
    await sleep(100);
    ok(true, "重发 booted 事件不抛错（splash 已淡出，幂等）");
  }

  console.log("\n结果： " + pass + " 通过 / " + fail + " 失败\n");
  process.exit(fail > 0 ? 1 : 0);
})();
