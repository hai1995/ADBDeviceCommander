/* jsdom 前端行为测试：Logcat 实时监控「过滤」完善
   —— 关键字在整段缓冲里搜索（不止最后 3000 行），且清空后能还原全部行。

   回归点：用户反映「输入 账号绑定，下方区域没显示出对应文字」。原实现
   renderLogcat 只扫描缓冲最后 LC_RENDER_CAP(3000) 行，较早出现、已被实时裁剪
   出视图的命中行永远搜不到；且关键字下发给后端做启动期预过滤后，缓冲里只剩当时
   命中的行，清掉关键字也回不来。现在：关键字第 3 个参数不再下发（缓冲保留完整），
   前端对整段缓冲做实时过滤，并扫描所有行。 */
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
async function waitFor(fn, ms = 6000, label = "") {
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
          if (k === "boot") return Promise.resolve({ ok: true });
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

const dev = (serial) => ({ serial, model: "Pixel", state: "device", ok: true, checked: true });

(async () => {
  // 4000 行缓冲：关键字「账号绑定」只出现在第 100 行（远早于最后 3000 行）。
  // 若只扫最后 3000 行，这行永远搜不到；扫描整段缓冲才能把它揪出来。
  const N = 4000, HIT = 100;
  const lines = [];
  for (let i = 0; i < N; i++) {
    const msg = (i === HIT) ? "账号绑定成功" : ("普通日志行 " + i);
    lines.push({
      raw: `01-01 00:00:00.000  1000  1000 I Tag: ${msg}`,
      level: "I", tag: "Tag", msg: msg, exc: false,
    });
  }

  console.log("\n[1] 关键字命中的是较早的行（不在最后 3000 行）→ 整段扫描应能显示");
  {
    const { window } = mkEnv([
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
       { kind: "devices", payload: { items: [dev("A1")] } }],
      [{ kind: "logcat", payload: {
        serial: "A1", status: "append", lines: lines, total: N, exc: 0 } }],
    ]);
    const doc = window.document;
    await waitFor(() => doc.getElementById("lc-counter").textContent.indexOf("行数: 4000") === 0,
                  8000, "缓冲 4000 行");

    const filter = doc.getElementById("lc-filter");
    filter.value = "账号绑定";
    filter.dispatchEvent(new window.Event("input", { bubbles: true }));
    // input 防抖 250ms 后才触发 renderLogcat
    const shown = await waitFor(
      () => doc.getElementById("lc-view").textContent.indexOf("账号绑定成功") >= 0,
      4000, "早期命中行渲染出来");
    ok(shown, "较早出现的「账号绑定」在过滤后应显示在下方区域（整段扫描）");
    const counter = doc.getElementById("lc-counter").textContent;
    ok(/命中:/.test(counter), "计数器应显示命中数（实际：" + counter + "）");
    ok(/命中:\s*1/.test(counter), "命中数应为 1（实际：" + counter + "）");
  }

  console.log("\n[2] 清空关键字 → 还原全部行");
  {
    const { window } = mkEnv([
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
       { kind: "devices", payload: { items: [dev("A1")] } }],
      [{ kind: "logcat", payload: {
        serial: "A1", status: "append", lines: lines, total: N, exc: 0 } }],
    ]);
    const doc = window.document;
    await waitFor(() => doc.getElementById("lc-counter").textContent.indexOf("行数: 4000") === 0,
                  8000, "缓冲 4000 行");
    const filter = doc.getElementById("lc-filter");
    filter.value = "账号绑定";
    filter.dispatchEvent(new window.Event("input", { bubbles: true }));
    await waitFor(() => /命中:\s*1/.test(doc.getElementById("lc-counter").textContent), 4000, "命中 1");
    filter.value = "";
    filter.dispatchEvent(new window.Event("input", { bubbles: true }));
    const restored = await waitFor(
      () => !/命中:/.test(doc.getElementById("lc-counter").textContent),
      4000, "清空关键字");
    ok(restored, "清空关键字后不再显示命中数（实际：" + doc.getElementById("lc-counter").textContent + "）");
  }

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
