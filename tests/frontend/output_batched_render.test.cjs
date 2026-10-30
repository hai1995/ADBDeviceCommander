/* jsdom 前端行为测试：指令输出 / 状态区批量渲染（对齐 logcat 区的队列+rAF 手法的回归）。
   回归背景：pushLine 原先逐行 appendChild + 每行读 scrollHeight 强制重排，大段命令回显
   （如 adb logcat / dmesg）会逐行卡顿。现压入队列、下一帧用 DocumentFragment 一次性
   插入，并受 CONSOLE_MAX_LINES(3000) 上限约束。 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = "../../";
const html = fs.readFileSync(path.join(__dirname, ROOT, "frontend/index.html"), "utf8");
const js = fs.readFileSync(path.join(__dirname, ROOT, "frontend/js/app.js"), "utf8");

let pass = 0, fail = 0;
function ok(cond, name) {
  if (cond) { pass++; console.log("  ✓ " + name); }
  else { fail++; console.log("  ✗ " + name); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitFor(fn, ms = 8000, label = "") {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    let v = false; try { v = !!fn(); } catch (e) { v = false; }
    if (v) return true;
    await sleep(30);
  }
  console.log("    (waitFor 超时: " + label + ")");
  return false;
}

function launch(batches) {
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
  const { window } = dom;
  let round = 0;
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          if (k === "boot") return Promise.resolve({ version: "v-t", warnings: [], commands: [], adb: "adb" });
          if (k === "take_events") { const b = batches[round] || []; round++; return Promise.resolve(b); }
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  return { window, doc: window.document };
}

const dev = [{ serial: "A1", model: "Pixel", state: "device", ok: true, checked: true }];
function consoleBatch(n) {
  return Array.from({ length: n }, (_, i) =>
    ({ kind: "console", payload: { kind: "out", text: "L" + i } }));
}

(async () => {
  console.log("\n[A] 输出区高频回显：合并为单次批量插入（而非逐行）");
  {
    const batches = [
      [{ kind: "booted", payload: { version: "v-t", warnings: [], commands: [] } },
       { kind: "devices", payload: { items: dev } }],
      consoleBatch(500),   // 一轮 take_events 内涌来 500 行
    ];
    const { window, doc } = launch(batches);
    const view = doc.getElementById("console");
    let maxBatch = 0;
    const mo = new window.MutationObserver((recs) => {
      for (const r of recs) {
        if (r.type === "childList") maxBatch = Math.max(maxBatch, r.addedNodes.length);
      }
    });
    mo.observe(view, { childList: true });

    const done = await waitFor(() => view.childNodes.length === 500, 8000, "render-500");
    ok(done, "500 行全部渲染（实际 " + view.childNodes.length + "）");
    mo.disconnect();
    ok(maxBatch > 1, "确实有合并插入（单次批量 >1 行）");
    ok(maxBatch === 500, "一轮 500 行合并为单次插入，证明走了队列而非逐行（实测 " + maxBatch + "）");
    // 关掉本段窗口：app.js 的事件轮询 / rAF 循环会一直跑下去，不关就会占用
    // 事件循环、饿死后续段的定时器（本文件曾因此出现「waitFor 超时但值其实已
    // 经正确」的假失败）。
    window.close();
  }

  console.log("\n[B] 超过 CONSOLE_MAX_LINES：从头部裁剪到 3000");
  {
    const batches = [
      [{ kind: "booted", payload: { version: "v-t", warnings: [], commands: [] } },
       { kind: "devices", payload: { items: dev } }],
      consoleBatch(3500),   // 超过 3000 上限
    ];
    const { window, doc } = launch(batches);
    const view = doc.getElementById("console");
    // 超时给到 20s：3500 个节点在 jsdom 里的插入 + Range 批量裁剪是**一次同步
    // 长任务**（真机 Chromium 里毫秒级，jsdom 里慢机器上可达数秒）。单线程下
    // 计时器在它跑完前根本没机会执行，8s 预算常常「任务刚结束、预算正好用完」，
    // 表现为「waitFor 超时但值其实已经正确」的假失败（实测 6 通过 / 1 失败）。
    const done = await waitFor(() => view.childNodes.length === 3000, 20000, "capped-3000");
    ok(done, "最终受上限约束为 3000 行（实际 " + view.childNodes.length + "）");
    ok(view.textContent.indexOf("L0") < 0, "最旧的 L0 已被裁剪（头部丢弃）");
    ok(view.textContent.indexOf("L3499") >= 0, "最新行 L3499 保留");
    window.close();   // 同上：不留活的轮询窗口给后续段
  }

  console.log("\n[C] clear 事件：DOM 与待渲染队列一起清空");
  {
    const batches = [
      [{ kind: "booted", payload: { version: "v-t", warnings: [], commands: [] } },
       { kind: "devices", payload: { items: dev } }],
      consoleBatch(200),
      [{ kind: "console", payload: { kind: "clear" } }],
      consoleBatch(10),
    ];
    const { window, doc } = launch(batches);
    const view = doc.getElementById("console");
    // 先等 200 行渲染：这一轮 clear 事件紧接着就来（洪流时下一轮 take_events 是
    // 立即续取），所以「看到 200」只是尽力而为的观察 —— 看不到也算正常，
    // 下面的最终态（只剩 10 行）才是本段要断言的。
    await waitFor(() => view.childNodes.length === 200, 8000, "c-200（尽力而为）");
    // clear 之后再来 10 行：最终应为 10（旧队列不会在清空后又插回）
    const done = await waitFor(() => view.childNodes.length === 10, 8000, "c-clear-10");
    ok(done, "clear 后旧行被清掉、只留新 10 行（实际 " + view.childNodes.length + "）");
    window.close();
  }

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
