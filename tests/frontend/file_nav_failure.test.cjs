/* jsdom 前端行为测试：文件页「进入无权限目录失败」时输入框应停留在当前目录。
   复现：点 /data 后后端报 Permission denied，输入框曾被错误地留在 /data，而列表仍
   是上一级；修复后 onFile 收到 error 会把输入框回退到当前目录（filePath）。 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.join(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "frontend/index.html"), "utf8");
const js = fs.readFileSync(path.join(ROOT, "frontend/js/app.js"), "utf8");

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
  return { window, calls, push: (e) => queue.push(e) };
}

(async () => {
  console.log("\n[B] 进入无权限目录失败：输入框应停留在当前目录，而非显示失败路径");
  const { window, push } = await boot([
    { kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
    { kind: "devices", payload: { items: [{ serial: "A1", ok: true, checked: true }] } },
    { kind: "file", payload: { serial: "A1", path: "/", entries: [
      { name: "..", is_dir: true },
      { name: "sdcard", is_dir: true },
      { name: "data", is_dir: true },
    ] } },
  ]);
  const doc = window.document;
  const input = doc.getElementById("file-path");

  ok(input.value === "/", "初始目录输入框为 /（实际：" + input.value + "）");

  // 模拟点击 data 目录：点击处理函数会把输入框先置为 /data 再请求（复现 bug 前置状态）
  input.value = "/data";
  // 后端返回错误事件（路径为失败的 /data）
  push({ kind: "file", payload: { serial: "A1", path: "/data", error: "列出目录失败 /data: ls: /data/.: Permission denied" } });

  const reverted = await waitFor(() => input.value === "/", 3000, "输入框回退到 /");
  ok(reverted, "进入 /data 失败后，输入框回退停留在当前目录 /（实际：" + input.value + "）");
  // 列表内容仍是上一级（未因失败而清空或跳走）
  ok(doc.querySelectorAll("#file-body tr").length === 3, "列表仍停留在原目录（3 行未变）");

  console.log("\n==============================================");
  console.log("结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
