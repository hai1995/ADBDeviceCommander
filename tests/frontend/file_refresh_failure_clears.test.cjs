/* jsdom 前端行为测试：文件页「当前目录无法访问」时文件区应清空。
   复现：车机无 root / 无权限，正在浏览的目录（如 /log/logcat）刷新时列不出来，
   列表却仍停留在该目录上一次成功时的内容（logcat.txt），陈旧且误导。修复后
   onFile 收到「失败路径 == 当前浏览目录」的 error 会清空列表并复位选择态。
   同时校验「进入其它目录失败」（失败路径 != 当前目录）仍保留原列表的旧行为。 */
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

const DEV_EVT = { kind: "devices", payload: { items: [{ serial: "A1", ok: true, checked: true }] } };
const BOOT_EVT = { kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } };

(async () => {
  // ---- 场景 1：当前目录刷新失败 -> 清空列表 ----
  console.log("\n[A] 当前目录（/log/logcat）刷新失败：文件区应清空");
  const t1 = await boot([
    BOOT_EVT,
    DEV_EVT,
    { kind: "file", payload: { serial: "A1", path: "/log/logcat", entries: [
      { name: "..", is_dir: true },
      { name: "logcat.txt", size: 43000000, date: "2026-09-18 16:21", perm: "-rw-rw----" },
    ] } },
  ]);
  const doc1 = t1.window.document;
  const input1 = doc1.getElementById("file-path");
  const listed = await waitFor(() => doc1.querySelectorAll("#file-body tr").length === 2, 3000, "初始列出 2 行");
  ok(listed, "初始已列出 /log/logcat（2 行，实际 " + doc1.querySelectorAll("#file-body tr").length + "）");
  ok(input1.value === "/log/logcat", "输入框为 /log/logcat（实际：" + input1.value + "）");

  // 全选后应显示「已选 1 项」，用于验证清空时选择态也被复位
  doc1.getElementById("file-sel-all").checked = true;
  doc1.getElementById("file-sel-all").dispatchEvent(new t1.window.Event("change"));
  await sleep(30);

  // 模拟刷新当前目录失败（失败路径 == 当前目录）
  t1.push({ kind: "file", payload: { serial: "A1", path: "/log/logcat",
    error: "列出目录失败 /log/logcat: ls: /log/logcat/: No such file or directory" } });

  const cleared = await waitFor(() => doc1.querySelectorAll("#file-body tr").length === 0, 3000, "列表被清空");
  ok(cleared, "当前目录刷新失败后列表被清空（实际 " + doc1.querySelectorAll("#file-body tr").length + " 行）");
  ok(doc1.getElementById("file-sel-count").textContent === "已选 0 项",
     "选择计数复位为「已选 0 项」（实际：" + doc1.getElementById("file-sel-count").textContent + "）");
  ok(doc1.getElementById("file-batch-dl").disabled === true, "批量下载按钮置灰");
  ok(doc1.getElementById("file-batch-del").disabled === true, "批量删除按钮置灰");

  // ---- 场景 2：进入其它目录失败 -> 保留原列表（回归保护）----
  console.log("\n[B] 进入其它目录（/data）失败：应保留当前目录列表");
  const t2 = await boot([
    BOOT_EVT,
    DEV_EVT,
    { kind: "file", payload: { serial: "A1", path: "/", entries: [
      { name: "..", is_dir: true },
      { name: "sdcard", is_dir: true },
      { name: "data", is_dir: true },
    ] } },
  ]);
  const doc2 = t2.window.document;
  const input2 = doc2.getElementById("file-path");
  const listed2 = await waitFor(() => doc2.querySelectorAll("#file-body tr").length === 3, 3000, "初始列出 3 行");
  ok(listed2, "初始已列出 /（3 行）");

  input2.value = "/data";
  t2.push({ kind: "file", payload: { serial: "A1", path: "/data",
    error: "列出目录失败 /data: ls: /data/.: Permission denied" } });

  const reverted = await waitFor(() => input2.value === "/", 3000, "输入框回退到 /");
  ok(reverted, "进入 /data 失败后输入框回退到当前目录 /（实际：" + input2.value + "）");
  await sleep(120);
  ok(doc2.querySelectorAll("#file-body tr").length === 3, "列表保留原目录内容（3 行未变）");

  console.log("\n==============================================");
  console.log("结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
