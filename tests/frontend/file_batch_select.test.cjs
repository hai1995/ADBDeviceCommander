/* jsdom 前端行为测试：文件页「批量选择 + 批量下载」。
   验证：each 文件行（除 ..）渲染复选框；全选联动；勾选后「下载选中」对每个选中文件
   下发一次 file_download，且仅针对选中的文件。 */
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
  return { window, calls };
}

(async () => {
  console.log("\n[A] 文件批量选择：每行（除 ..）渲染复选框 + 全选联动 + 下载选中下发 file_download");
  const filePayload = {
    kind: "file",
    payload: {
      serial: "A1", path: "/",
      entries: [
        { name: "..", is_dir: true },
        { name: "a.txt", is_dir: false, size: 10 },
        { name: "b.log", is_dir: false, size: 20 },
        { name: "sub", is_dir: true },
      ],
    },
  };
  const { window, calls } = await boot([
    { kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
    { kind: "devices", payload: { items: [{ serial: "A1", ok: true, checked: true }] } },
    filePayload,
  ]);
  const doc = window.document;

  const checks = doc.querySelectorAll("#file-body .file-check");
  ok(checks.length === 3, "3 个可选项（a.txt / b.log / sub）各一个复选框，.. 除外（实际 " + checks.length + "）");

  // 全选框联动：勾选后所有行选中、计数=3
  const selAll = doc.getElementById("file-sel-all");
  selAll.checked = true;
  selAll.dispatchEvent(new window.Event("change"));
  ok(Array.from(checks).every((c) => c.checked), "点「全选」后所有行复选框被勾选");
  ok(/已选 3/.test(doc.getElementById("file-sel-count").textContent), "计数显示已选 3 项");

  // 取消全选，再只勾选 a.txt / b.log
  selAll.checked = false;
  selAll.dispatchEvent(new window.Event("change"));
  const targets = Array.from(checks).filter((c) => c.value.endsWith("a.txt") || c.value.endsWith("b.log"));
  ok(targets.length === 2, "能定位到 a.txt / b.log 两个文件复选框");
  targets.forEach((c) => { c.checked = true; c.dispatchEvent(new window.Event("change")); });

  const dlBtn = doc.getElementById("file-batch-dl");
  ok(!dlBtn.disabled, "勾选后「下载选中」按钮启用");
  ok(/已选 2/.test(doc.getElementById("file-sel-count").textContent), "计数显示已选 2 项");

  // 设置共享保存目录（从文件页输入框写入，验证其同步到工具页源值并下发）
  const fileDir = doc.getElementById("file-dir");
  fileDir.value = "/shared/dir";
  fileDir.dispatchEvent(new window.Event("input"));
  ok(doc.getElementById("tool-dir").value === "/shared/dir", "文件页保存目录改动同步到共享源（tool-dir）");

  dlBtn.dispatchEvent(new window.Event("click"));
  const dlCalls = calls.filter((c) => c.fn === "file_download");
  ok(dlCalls.length === 2, "已对 2 个选中文件各下发一次 file_download（实际 " + dlCalls.length + "）");
  const sent = dlCalls.map((c) => c.args[1]).sort();
  ok(sent[0] === "/a.txt" && sent[1] === "/b.log", "下发的路径为选中文件：" + JSON.stringify(sent));
  ok(dlCalls.every((c) => c.args[2] === "/shared/dir"), "下载目标使用共享保存目录（/shared/dir）");

  console.log("\n==============================================");
  console.log("结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
