/* jsdom 前端行为测试：大目录（上千行）渲染与行级交互。

   背景：文件页每次刷新都整体重建表格。旧实现逐行 appendChild（N 次布局）并给
   每行挂 5~6 个监听器（勾选框 change / 名称 click / 三个操作按钮 click）——
   2000 行就是上万个闭包常驻，列表刷新一次可感卡顿。

   现改为 DocumentFragment 批量插入 + #file-body 上的事件委托。本测试守住
   「改成委托后行为不变」：行全部渲染出来、行内按钮能触发对应 API、单击名称
   能进目录、勾选能更新已选计数。 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.join(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "frontend/index.html"), "utf8");
const js = fs.readFileSync(path.join(ROOT, "frontend/js/app.js"), "utf8");

process.on("unhandledRejection", (e) => {
  console.log("!! unhandledRejection:", e && e.stack ? e.stack : e);
});

let pass = 0, fail = 0;
function ok(c, n) {
  if (c) { pass++; console.log("  ✓ " + n); }
  else { fail++; console.log("  ✗ " + n); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitFor(fn, ms = 4000, label = "") {
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

const N = 600;   // 600 个文件 + 1 个目录 + 1 个「..」

function bigEntries() {
  const list = [
    { name: "..", is_dir: true },
    { name: "Download", is_dir: true },
  ];
  for (let i = 0; i < N; i++) {
    list.push({ name: "f" + i + ".txt", is_dir: false, size: i, date: "2024-01-01 10:00", perm: "-rw-r--r--" });
  }
  return list;
}

function rowByName(doc, name) {
  return Array.from(doc.querySelectorAll("#file-body tr"))
    .find((tr) => (tr.dataset && tr.dataset.name) === name) || null;
}

function clickAct(row, label) {
  const btn = Array.from(row.querySelectorAll("td.act button"))
    .find((b) => b.textContent.trim() === label);
  if (!btn) return false;
  btn.dispatchEvent(new btn.ownerDocument.defaultView.Event("click", { bubbles: true }));
  return true;
}

(async () => {
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
  const { window } = dom;
  const queue = [
    { kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
    { kind: "devices", payload: { items: [{ serial: "A1", ok: true, checked: true }] } },
    { kind: "file", payload: { serial: "A1", path: "/sdcard", entries: bigEntries() } },
  ];
  const calls = [];
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          calls.push({ fn: String(k), args });
          if (k === "boot") return Promise.resolve({ version: "v-test", warnings: [], commands: [], adb: "/usr/bin/adb", save_dir: "/tmp" });
          if (k === "take_events") return Promise.resolve(queue.splice(0, queue.length));
          if (k === "window_toggle_max") return Promise.resolve({ max: true });
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  const doc = window.document;

  console.log("\n[1] 一次性渲染 " + (N + 2) + " 行");
  ok(await waitFor(() => doc.querySelectorAll("#file-body tr").length === N + 2, 5000,
                   "整表渲染"), "行数 = " + (N + 2));
  ok(doc.querySelectorAll("#file-body .file-check").length === N + 1,
     "除「..」外每行一个勾选框（实得 " + doc.querySelectorAll("#file-body .file-check").length + "）");

  console.log("\n[2] 行内按钮走事件委托：点「下载」下发 file_download");
  const row = rowByName(doc, "f42.txt");
  ok(!!row, "找到 f42.txt 那一行");
  ok(row && clickAct(row, "下载"), "点击该行「下载」");
  await sleep(80);
  const dl = calls.filter((c) => c.fn === "file_download");
  ok(dl.length === 1, "下发一次 file_download（实得 " + dl.length + "）");
  if (dl.length) {
    ok(dl[0].args[0] === "A1", "序列号正确");
    ok(dl[0].args[1] === "/sdcard/f42.txt", "路径 = 当前目录 + 文件名（实得 " + dl[0].args[1] + "）");
  }

  console.log("\n[3] 单击目录名进入下级目录");
  const dirRow = rowByName(doc, "Download");
  const nameCell = dirRow && dirRow.querySelector("td.name");
  ok(!!nameCell, "找到 Download 行的名称单元格");
  if (nameCell) {
    nameCell.dispatchEvent(new window.Event("click", { bubbles: true }));
    await sleep(80);
    const ls = calls.filter((c) => c.fn === "file_list");
    ok(ls.length >= 1 && ls[ls.length - 1].args[1] === "/sdcard/Download",
       "file_list 目标 = /sdcard/Download（实得 " + (ls.length ? ls[ls.length - 1].args[1] : "无") + "）");
  }

  console.log("\n[4] 勾选框 change 仍能更新「已选」计数");
  const cb = row && row.querySelector(".file-check");
  ok(!!cb, "找到 f42.txt 的勾选框");
  if (cb) {
    cb.checked = true;
    cb.dispatchEvent(new window.Event("change", { bubbles: true }));
    await sleep(40);
    const cnt = doc.getElementById("file-sel-count");
    ok(cnt && cnt.textContent.includes("1"), "已选 1 项（实得 " + (cnt && cnt.textContent) + "）");
    ok(doc.getElementById("file-batch-del") && doc.getElementById("file-batch-del").disabled === false,
       "「删除选中」按钮可用");
  }

  console.log("\n" + "=".repeat(46));
  console.log("结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
