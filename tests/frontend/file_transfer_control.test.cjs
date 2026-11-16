/* jsdom 前端行为测试：传输防呆 + 下载进度 + 真取消。

   覆盖：
     * 行内「下载」→ 入统一队列（⬇ 图标、downloading 态），调 file_download 带 task_id；
     * 后端 file_download 事件按 task_id 刷新百分比 → done → 完成；
     * 进行中的项有「取消」按钮，点击调 file_transfer_cancel 并立即标「已取消」；
     * 传输进行中：切设备 / 切目录被拦截（按钮置灰、状态栏提示）；
     * 传输结束（done 事件）后自动解锁。
*/
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
    await sleep(30);
  }
  console.log("    (waitFor 超时: " + label + ")");
  return false;
}

async function boot() {
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
  const { window } = dom;
  const pending = [
    { kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
    { kind: "devices", payload: { items: [{ serial: "A1", ok: true, checked: true }] } },
    { kind: "file", payload: { serial: "A1", path: "/sdcard", entries: [] } },
  ];
  const calls = [];
  const apiStub = new Proxy({}, {
    get(t, k) {
      if (k === "then") return undefined;
      return function (...args) {
        calls.push({ fn: String(k), args });
        if (k === "boot") return Promise.resolve({ version: "v-test", warnings: [], commands: [], adb: "/usr/bin/adb", save_dir: "/tmp" });
        if (k === "take_events") return Promise.resolve(pending.splice(0, pending.length));
        return Promise.resolve({ ok: true });
      };
    },
  });
  window.pywebview = { api: apiStub };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  await sleep(500);
  return { window, calls, pending };
}

function items(doc) { return Array.from(doc.querySelectorAll("#upload-queue-list .upload-item")); }
function dlCalls(calls) { return calls.filter((c) => c.fn === "file_download"); }
function fireDown(window, pending, ev) { pending.push({ kind: "file_download", payload: ev }); }
function clickRowDownload(window) {
  const body = window.document.getElementById("file-body");
  const tr = window.document.createElement("tr");
  tr.dataset.path = "/sdcard/big.bin";
  tr.dataset.name = "big.bin";
  const td = window.document.createElement("td");
  const btn = window.document.createElement("button");
  btn.dataset.act = "download";
  td.appendChild(btn); tr.appendChild(td); body.appendChild(tr);
  btn.click();
}
function statusText(doc) { const e = doc.getElementById("status"); return e ? e.textContent : ""; }

(async () => {
  console.log("\n[1] 行内下载 → 入队（downloading / ⬇），调 file_download 带 task_id");
  {
    const { window, calls, pending } = await boot();
    clickRowDownload(window);
    await waitFor(() => dlCalls(calls).length === 1, 4000, "download call");
    const call = dlCalls(calls)[0];
    ok(!!call, "调用了 file_download");
    ok(call.args[0] === "A1" && call.args[1] === "/sdcard/big.bin", "参数含设备与远端路径");
    ok(typeof call.args[3] === "string" && call.args[3], "带 task_id：" + call.args[3]);
    const its = items(window.document);
    ok(its.length === 1, "队列出现一项");
    ok(its[0].className.indexOf("upload-downloading") !== -1, "状态为 downloading：" + its[0].className);
    ok(its[0].textContent.indexOf("⬇") !== -1, "下载项用 ⬇ 图标");
    window.close();
  }

  console.log("\n[2] 后端进度事件刷新百分比 → done 完成，并自动解锁");
  {
    const { window, calls, pending } = await boot();
    clickRowDownload(window);
    await waitFor(() => dlCalls(calls).length === 1, 4000, "download call");
    const id = dlCalls(calls)[0].args[3];
    // 防呆延迟 1.5s 激活（小文件秒传不锁）；等它锁上再断言
    await sleep(1700);
    ok(window.document.getElementById("file-refresh").disabled, "持续传输中「刷新」被禁用");
    ok(window.document.getElementById("file-path").readOnly, "传输中路径输入框只读");
    fireDown(window, pending, { task_id: id, serial: "A1", name: "big.bin", remote: "/sdcard/big.bin", status: "downloading", percent: 45 });
    await waitFor(() => items(window.document)[0] && items(window.document)[0].textContent.indexOf("45%") !== -1, 3000, "45%");
    ok(items(window.document)[0].textContent.indexOf("45%") !== -1, "进度刷新到 45%");
    fireDown(window, pending, { task_id: id, serial: "A1", name: "big.bin", remote: "/sdcard/big.bin", status: "done", percent: 100, local: "/tmp/big.bin" });
    await waitFor(() => items(window.document)[0] && items(window.document)[0].className.indexOf("upload-done") !== -1, 3000, "done");
    ok(items(window.document)[0].className.indexOf("upload-done") !== -1, "转完成态");
    ok(window.document.getElementById("file-refresh").disabled === false, "完成后「刷新」解锁");
    window.close();
  }

  console.log("\n[3] 进行中项有「取消」按钮：点击调 file_transfer_cancel 并标已取消");
  {
    const { window, calls, pending } = await boot();
    clickRowDownload(window);
    await waitFor(() => items(window.document).length === 1, 4000, "one item");
    await sleep(1700);  // 等防呆锁上，才能验证取消后解锁
    ok(window.document.getElementById("file-refresh").disabled, "取消前按钮处于锁定态");
    const cancel = items(window.document)[0].querySelector('[data-uact="cancel"]');
    ok(!!cancel, "进行中项有取消按钮");
    cancel.click();
    await waitFor(() => calls.some((c) => c.fn === "file_transfer_cancel"), 3000, "cancel call");
    const cc = calls.find((c) => c.fn === "file_transfer_cancel");
    ok(!!cc, "调用了 file_transfer_cancel");
    ok(cc.args[0] === dlCalls(calls)[0].args[3], "取消用的是同一个 task_id");
    ok(items(window.document)[0].textContent.indexOf("已取消") !== -1, "界面立即标记已取消");
    ok(window.document.getElementById("file-refresh").disabled === false, "取消后解锁");
    window.close();
  }

  console.log("\n[4] 传输中切目录被拦截（路径回退 + 提示）");
  {
    const { window, calls, pending } = await boot();
    clickRowDownload(window);
    await waitFor(() => dlCalls(calls).length === 1, 4000, "download call");
    await sleep(1700);  // 等防呆激活
    const pathInput = window.document.getElementById("file-path");
    const before = pathInput.value;
    pathInput.value = "/data";
    pathInput.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await sleep(100);
    ok(pathInput.value === before, "传输中切目录被拦截，路径回退到 " + before);
    ok(/传输进行中/.test(statusText(window.document)), "给出提示：" + statusText(window.document));
    ok(!calls.some((c) => c.fn === "file_list" && c.args[1] === "/data"), "未真正列新目录");
    window.close();
  }

  console.log("\n==============================================");
  console.log("结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
