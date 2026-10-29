/* jsdom 前端行为测试：文件页切换受控设备后，浏览路径应复位到根「/」，
   而不是在新设备上继续列旧设备的子目录（如 /data/local/tmp），否则会直接
   报「无权限 / 目录不存在」。修复后 renderFileDev 在设备变化时把 filePath 复位到
   「/」并重新发起 file_list(<新设备>, "/")。自动轮询刷新（设备不变）不应打扰浏览。 */
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

const BOOT_EVT = { kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } };
const DEV_A = { kind: "devices", payload: { items: [{ serial: "A", ok: true, checked: true }] } };
const DEV_B = { kind: "devices", payload: { items: [{ serial: "B", ok: true, checked: true }] } };

(async () => {
  console.log("\n[A] 设备 A 上浏览 /data/local/tmp，再切到设备 B 应复位到根");
  const t = await boot([
    BOOT_EVT,
    DEV_A,
    { kind: "file", payload: { serial: "A", path: "/data/local/tmp", entries: [
      { name: "..", is_dir: true },
      { name: "x.txt", size: 12, date: "2026-09-18 16:21", perm: "-rw-rw----" },
    ] } },
  ]);
  const doc = t.window.document;
  const input = doc.getElementById("file-path");
  const listed = await waitFor(() => doc.querySelectorAll("#file-body tr").length === 2, 3000, "A 列出 2 行");
  ok(listed, "A 已列出 /data/local/tmp（2 行，实际 " + doc.querySelectorAll("#file-body tr").length + "）");
  ok(input.value === "/data/local/tmp", "输入框为 A 的路径 /data/local/tmp（实际：" + input.value + "）");

  // 记录当前 file_list 调用数，作为切换后的判定基准
  const n0 = t.calls.filter((c) => c.fn === "file_list").length;

  // 切换受控设备：取消 A、勾选 B
  t.push(DEV_B);
  const switched = await waitFor(() => t.calls.filter((c) => c.fn === "file_list").length > n0, 3000, "B 触发 file_list");
  ok(switched, "切到 B 后重新发起 file_list");

  const callsAfter = t.calls.filter((c) => c.fn === "file_list");
  const last = callsAfter[callsAfter.length - 1];
  ok(last && last.args[0] === "B", "最近一次 file_list 目标是设备 B（实际：" + (last && last.args[0]) + "）");
  ok(last && last.args[1] === "/", "最近一次 file_list 路径复位为根「/」（实际：" + (last && last.args[1]) + "）");
  await sleep(80);
  ok(input.value === "/", "输入框已复位为「/」（实际：" + input.value + "）");

  console.log("\n[B] 自动轮询刷新（设备不变）不应打扰当前浏览路径");
  // 再把 A 勾回来、B 取消（模拟用户在两台间切回），然后发一个「设备不变」的刷新事件
  // （仍是 B 受控），确认浏览路径不被复位。
  // 先把路径手动改到子目录，模拟用户已深入浏览
  input.value = "/sdcard/DCIM";
  t.push({ kind: "file", payload: { serial: "B", path: "/sdcard/DCIM", entries: [
    { name: "..", is_dir: true }, { name: "shot.png", size: 99, date: "x", perm: "-rw" },
  ] } });
  await waitFor(() => doc.querySelectorAll("#file-body tr").length === 2, 3000, "B 列出 2 行");
  ok(input.value === "/sdcard/DCIM", "B 路径为 /sdcard/DCIM（实际：" + input.value + "）");

  const n1 = t.calls.filter((c) => c.fn === "file_list").length;
  // 设备快照刷新但仍是 B 受控（firstChecked 不变）
  t.push({ kind: "devices", payload: { items: [
    { serial: "A", ok: true, checked: false },
    { serial: "B", ok: true, checked: true },
  ] } });
  await sleep(200);
  const callsRefresh = t.calls.filter((c) => c.fn === "file_list");
  // 设备没变 -> 不应新发起 file_list（不重置路径）
  ok(callsRefresh.length === n1, "设备不变刷新未新发起 file_list（实际 +" + (callsRefresh.length - n1) + "）");
  ok(input.value === "/sdcard/DCIM", "刷新后浏览路径保持 /sdcard/DCIM（实际：" + input.value + "）");

  console.log("\n==============================================");
  console.log("结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
