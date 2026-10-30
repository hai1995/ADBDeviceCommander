/* jsdom 前端行为测试：文件页「单击名字切换选择 + Ctrl / Shift 区间选 + 目录进入」。
   验证：单击文件名切换对应复选框；Ctrl 加选不丢已有选择；Shift 选中锚点到点击点区间并清掉区间外；
   目录行用复选框单独选中（供批量下载/删除），单击目录名进入下级（二者互不干扰）。 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.join(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "frontend/index.html"), "utf8");
const js = fs.readFileSync(path.join(ROOT, "frontend/js/app.js"), "utf8");

process.on("unhandledRejection", (e) => { console.log("!! unhandledRejection:", e && e.stack ? e.stack : e); });

let pass = 0, fail = 0;
function ok(c, n) {
  if (c) { pass++; console.log("  ✓ " + n); }
  else { fail++; console.log("  ✗ " + n); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitFor(fn, ms = 4000, label = "") {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { let v = false; try { v = !!fn(); } catch (e) {} if (v) return true; await sleep(40); }
  console.log("    (waitFor 超时: " + label + ")"); return false;
}
function clickName(doc, name, opts = {}) {
  const w = doc.defaultView;
  const rows = Array.from(doc.querySelectorAll("#file-body tr"));
  const e = new w.Event("click", { bubbles: true });
  if (opts.shiftKey) e.shiftKey = true;
  if (opts.ctrlKey) e.ctrlKey = true;
  for (const tr of rows) {
    const nm = tr.querySelector(".name");
    if (nm && nm.textContent.includes(name)) {
      nm.dispatchEvent(e);
      return;
    }
  }
}
function isChecked(doc, name) {
  const rows = Array.from(doc.querySelectorAll("#file-body tr"));
  for (const tr of rows) {
    const nm = tr.querySelector(".name");
    const cb = tr.querySelector(".file-check");
    if (nm && nm.textContent.includes(name)) return !!cb && cb.checked;
  }
  return false;
}

async function boot(events) {
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
  const { window } = dom;
  const queue = events.slice();
  const calls = [];
  const apiStub = new Proxy({}, {
    get(t, k) {
      if (k === "then") return undefined;
      return function (...args) {
        calls.push({ fn: String(k), args });
        if (k === "boot") return Promise.resolve({ version: "v-test", warnings: [], commands: [], adb: "/usr/bin/adb", save_dir: "/tmp" });
        if (k === "take_events") return Promise.resolve(queue.splice(0, queue.length));
        if (k === "window_toggle_max") return Promise.resolve({ max: true });
        if (k === "file_list") return Promise.resolve({ ok: true });
        return Promise.resolve({ ok: true });
      };
    },
  });
  window.pywebview = { api: apiStub };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  await sleep(600);
  return { window, calls };
}

(async () => {
  console.log("\n[C] 单击名字切换选择 + Ctrl / Shift 区间选 + 双击目录进入");
  const { window, calls } = await boot([
    { kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
    { kind: "devices", payload: { items: [{ serial: "A1", ok: true, checked: true }] } },
    { kind: "file", payload: { serial: "A1", path: "/", entries: [
      { name: "..", is_dir: true },
      { name: "a.txt", is_dir: false },
      { name: "b.log", is_dir: false },
      { name: "c.dat", is_dir: false },
      { name: "sub", is_dir: true },
    ] } },
  ]);
  const doc = window.document;

  // 1) 单击名字切换对应复选框
  clickName(doc, "a.txt");
  ok(isChecked(doc, "a.txt"), "单击 a.txt 名字 → 该文件被选中");
  ok(isChecked(doc, "b.log") === false, "b.log 未选中");
  ok(/已选 1/.test(doc.getElementById("file-sel-count").textContent), "计数显示已选 1 项");

  // 再次单击同一名字 → 取消
  clickName(doc, "a.txt");
  ok(isChecked(doc, "a.txt") === false, "再次单击 a.txt 名字 → 取消选中");

  // 2) 普通单击多个 = 累加选择（不含 Ctrl 也累加，符合复选框模型）
  clickName(doc, "a.txt");
  clickName(doc, "c.dat");
  ok(isChecked(doc, "a.txt") && isChecked(doc, "c.dat"), "单击 a、c → 两者都被选中（累加）");
  ok(/已选 2/.test(doc.getElementById("file-sel-count").textContent), "计数显示已选 2 项");

  // 3) Shift 点击 b.log：锚点(c) 到 b 的区间 [b,c] 选中，区间外(a)取消
  clickName(doc, "b.log", { shiftKey: true });
  ok(isChecked(doc, "b.log") && isChecked(doc, "c.dat"), "Shift 点击 b → b、c 区间被选中");
  ok(isChecked(doc, "a.txt") === false, "Shift 区间外的 a 被取消");

  // 4) 目录：复选框可单独选中；单击目录名进入下级（两者互不干扰）
  {
    const tr = Array.from(doc.querySelectorAll("#file-body tr"))
      .find((t) => t.querySelector(".name") && t.querySelector(".name").textContent.includes("sub"));
    const cb = tr.querySelector(".file-check");
    cb.checked = true;
    cb.dispatchEvent(new window.Event("change", { bubbles: true }));
    ok(isChecked(doc, "sub"), "勾选目录行复选框 → 目录也可被选中（供批量下载/删除）");
    tr.querySelector(".name").dispatchEvent(new window.Event("click", { bubbles: true }));
    const navCalls = calls.filter((c) => c.fn === "file_list" && c.args[1] === "/sub");
    ok(navCalls.length === 1, "单击 sub 目录名 → 触发进入 /sub（file_list 下发）");
  }

  console.log("\n==============================================");
  console.log("结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
