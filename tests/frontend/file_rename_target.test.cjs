/* jsdom 前端行为测试：文件页「重命名」的目标路径。
   回归：早前用 dirOf(filePath)（当前目录的**父目录**）拼目标路径，导致在
   /sdcard/Download 里重命名 a.txt 会把文件搬到 /sdcard/b.txt（等同于移动）；
   在根目录下还会拼出 "//c.txt"。目标必须是「当前目录 + 新名」。

   另外锁两件事（都是「点了没反应 / 做了别的」这类静默失败）：
     · 重命名走**自绘输入弹窗**而不是 window.prompt（pywebview 部分版本里 prompt
       返回 null，点了毫无反应）；
     · 新名带 / 时直接拒绝：`mv old new` 的语义等于移动，用户以为改名却把文件搬走。 */
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

/** 在指定行上点击「重命名」动作按钮 */
function clickRename(doc, name) {
  const rows = Array.from(doc.querySelectorAll("#file-body tr"));
  for (const tr of rows) {
    const nm = tr.querySelector(".name");
    if (!nm || !nm.textContent.includes(name)) continue;
    const btn = Array.from(tr.querySelectorAll("td.act button"))
      .find((b) => b.textContent.trim() === "重命名");
    if (btn) { btn.dispatchEvent(new doc.defaultView.Event("click", { bubbles: true })); return true; }
  }
  return false;
}

/** 在自绘输入弹窗里填值并点「确定」（替代原来的 window.prompt stub） */
async function submitInput(doc, value) {
  const modal = doc.getElementById("input-modal");
  if (!modal || modal.classList.contains("hidden")) return false;
  doc.getElementById("input-field").value = value;
  doc.getElementById("input-yes")
    .dispatchEvent(new doc.defaultView.Event("click", { bubbles: true }));
  await sleep(60);
  return true;
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
  return { window, calls, queue };
}

(async () => {
  console.log("\n[D] 文件页「重命名」目标路径 = 当前目录 + 新名");
  const { window, calls, queue } = await boot([
    { kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
    { kind: "devices", payload: { items: [{ serial: "A1", ok: true, checked: true }] } },
    { kind: "file", payload: { serial: "A1", path: "/sdcard/Download", entries: [
      { name: "..", is_dir: true },
      { name: "a.txt", is_dir: false },
    ] } },
  ]);
  const doc = window.document;
  await waitFor(() => doc.querySelectorAll("#file-body tr").length >= 2, 4000, "文件列表渲染");

  // 1) 子目录内重命名：必须是 /sdcard/Download/b.txt，而不是父目录 /sdcard/b.txt
  ok(clickRename(doc, "a.txt"), "找到并点击 a.txt 的「重命名」");
  await sleep(40);
  ok(await submitInput(doc, "b.txt"), "点「重命名」弹出应用内输入框并提交 b.txt");
  await sleep(80);
  const rn = calls.filter((c) => c.fn === "file_rename");
  ok(rn.length === 1, "重命名下发一次 file_rename");
  if (rn.length) {
    ok(rn[0].args[0] === "A1", "序列号正确");
    ok(rn[0].args[1] === "/sdcard/Download/a.txt", "旧路径 = 当前目录 + 原名（实得 " + rn[0].args[1] + "）");
    ok(rn[0].args[2] === "/sdcard/Download/b.txt",
       "新路径仍在当前目录内（实得 " + rn[0].args[2] + "）");
  }

  // 2) 根目录内重命名：必须是 /c.txt，不能拼出 //c.txt
  queue.push({ kind: "file", payload: { serial: "A1", path: "/", entries: [
    { name: "c.txt", is_dir: false },
  ] } });
  await waitFor(() => Array.from(doc.querySelectorAll("#file-body .name"))
    .some((n) => n.textContent.includes("c.txt")), 4000, "根目录文件列表渲染");
  ok(clickRename(doc, "c.txt"), "找到并点击 c.txt 的「重命名」");
  await sleep(40);
  ok(await submitInput(doc, "d.txt"), "提交新名 d.txt");
  await sleep(80);
  const rn2 = calls.filter((c) => c.fn === "file_rename");
  ok(rn2.length === 2, "第二次重命名也下发");
  if (rn2.length === 2) {
    ok(rn2[1].args[1] === "/c.txt", "根目录旧路径 = /c.txt（实得 " + rn2[1].args[1] + "）");
    ok(rn2[1].args[2] === "/d.txt", "根目录新路径 = /d.txt（实得 " + rn2[1].args[2] + "）");
  }

  console.log("\n[E] 新名带 / 时拒绝（mv 语义是移动，不是改名）");
  {
    ok(clickRename(doc, "d.txt") || clickRename(doc, "c.txt"),
       "再点一次「重命名」（文件名已按上一步断言为准）");
    await sleep(40);
    const before = calls.filter((c) => c.fn === "file_rename").length;
    ok(await submitInput(doc, "sub/e.txt"), "输入带 / 的新名并确定");
    await sleep(80);
    const after = calls.filter((c) => c.fn === "file_rename").length;
    ok(after === before, "带 / 的名称不下发 file_rename（否则等于把文件搬到别的目录）");
    const status = doc.getElementById("status").textContent || "";
    ok(/不能包含 \/|不做移动/.test(status), "状态栏说明了为什么拒绝（实际：" +
       status.split("\n").filter(Boolean).slice(-1)[0] + "）");
  }

  console.log("\n[F] 取消（Esc / 取消按钮）不下发任何改动");
  {
    // 上一步的重命名弹窗已被提交关掉；再点一次并取消
    ok(clickRename(doc, "d.txt") || clickRename(doc, "c.txt"), "打开重命名弹窗");
    await sleep(40);
    const before = calls.filter((c) => c.fn === "file_rename").length;
    doc.getElementById("input-no")
      .dispatchEvent(new doc.defaultView.Event("click", { bubbles: true }));
    await sleep(80);
    ok(calls.filter((c) => c.fn === "file_rename").length === before, "点「取消」不下发 file_rename");
    ok(doc.getElementById("input-modal").classList.contains("hidden"), "弹窗已关闭");
  }

  console.log("\n==============================================");
  console.log("结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
