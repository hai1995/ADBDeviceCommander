/* jsdom 前端行为测试：Logcat 分帧渲染 + 增量追加（验证不再一次灌爆 DOM）。
   配套 backend/logcat_service.LogcatMonitor 的历史 dump 限流。 */
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
// 轮询等待条件成立（事件轮询 400ms 一轮，固定 sleep 易抖动）
async function waitFor(fn, ms = 6000, label = "") {
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

// 通用 launch：batches[i] 是第 i 轮 take_events 返回的事件列表
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

(async () => {
  console.log("\n[A] 启动爆发期：历史 dump 不会一次性灌满 DOM（分帧渲染）");
  {
    const batches = [
      [{ kind: "booted", payload: { version: "v-t", warnings: [], commands: [] } },
       { kind: "devices", payload: { items: dev } }],
      // 模拟后端一次性推来 5000 行（后端限流前的最坏情况；此处验证前端分帧）
      [{ kind: "logcat", payload: { serial: "A1", status: "running" } },
       { kind: "logcat", payload: { serial: "A1", status: "append", lines: mkLines(5000, 0), total: 5000, exc: 0 } }],
    ];
    const { window, doc } = launch(batches);
    const view = doc.getElementById("lc-view");

    // 用 MutationObserver 记录「单次 DOM 批量插入」的最大行数：
    // 分帧生效时每帧最多插入 LC_PER_FRAME(300) 行；若退化成同步全插，一次就是 5000 行。
    let maxBatch = 0;
    const mo = new window.MutationObserver((recs) => {
      for (const r of recs) {
        if (r.type === "childList") maxBatch = Math.max(maxBatch, r.addedNodes.length);
      }
    });
    mo.observe(view, { childList: true });

    const done = await waitFor(() => view.childNodes.length === 3000, 8000, "render-done");
    ok(done, "最终受 LC_VIEW_MAX 限制为 3000 行（实际 " + view.childNodes.length + "）");
    mo.disconnect();
    ok(maxBatch > 0, "确实有 DOM 插入");
    ok(maxBatch <= 300, "单次批量插入 <= 每帧上限 300，证明分帧而非一次性全插（实测 " + maxBatch + "）");
    ok(maxBatch < 5000, "未一次性插入全部 5000 行");
    window.close();   // 必须关闭：否则该实例的后台事件轮询定时器继续占用事件循环，饿死后续实例
  }

  console.log("\n[B] 增量追加：首节点不被重建（切设备/改过滤才会全量重建）");
  {
    const batches = [
      [{ kind: "booted", payload: { version: "v-t", warnings: [], commands: [] } },
       { kind: "devices", payload: { items: dev } }],
      [{ kind: "logcat", payload: { serial: "A1", status: "running" } },
       { kind: "logcat", payload: { serial: "A1", status: "append", lines: mkLines(100, 0), total: 100, exc: 0 } }],
      [{ kind: "logcat", payload: { serial: "A1", status: "append", lines: mkLines(100, 100), total: 200, exc: 0 } }],
    ];
    const { window, doc } = launch(batches);
    const view = doc.getElementById("lc-view");
    await waitFor(() => view.childNodes.length === 100, 4000, "b-100");
    const first = view.firstChild;
    ok(first && first.textContent.indexOf("msg 0") >= 0, "首节点为第 0 行");
    await waitFor(() => view.childNodes.length === 200, 4000, "b-200");
    ok(view.firstChild === first, "追加后首节点未被替换（增量而非全量重建）");
    ok(view.textContent.indexOf("msg 199") >= 0, "最新行已渲染");
    window.close();
  }

  console.log("\n[C] 自动滚动模式：持续追加不崩溃、首节点不被重建");
  {
    const batches = [
      [{ kind: "booted", payload: { version: "v-t", warnings: [], commands: [] } },
       { kind: "devices", payload: { items: dev } }],
      [{ kind: "logcat", payload: { serial: "A1", status: "running" } },
       { kind: "logcat", payload: { serial: "A1", status: "append", lines: mkLines(100, 0), total: 100, exc: 0 } }],
      [{ kind: "logcat", payload: { serial: "A1", status: "append", lines: mkLines(100, 100), total: 200, exc: 0 } }],
    ];
    const { window, doc } = launch(batches);
    const view = doc.getElementById("lc-view");
    const auto = doc.getElementById("lc-autoscroll");
    auto.checked = true;   // 开启自动滚动
    await waitFor(() => view.childNodes.length === 200, 4000, "c-200");
    ok(view.textContent.indexOf("msg 199") >= 0, "自动滚动模式下增量追加正常（200 行就位）");
    ok(view.firstChild && view.firstChild.textContent.indexOf("msg 0") >= 0, "首节点未被重建");
  }

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
