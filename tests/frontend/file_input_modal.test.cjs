/* jsdom 前端测试：文件页的「输入 / 确认」弹窗（替代 window.prompt / window.confirm）
 *
 * 为什么必须自绘：pywebview 各版本对 window.prompt / window.confirm 的支持并不一致，
 * 部分版本里 prompt 直接返回 null、confirm 返回 undefined。那会让
 *   · 重命名 / 新建文件夹 / 新建文件 —— 点了毫无反应（连报错都没有）；
 *   · `if (!confirm(...)) return` 的批量删除 —— **跳过确认直接删**（不可恢复）。
 * 本文件锁住这条边界：
 *   [0] 输入弹窗存在，且打开时焦点在输入框、内容被全选；
 *   [1] 「确定」按输入值下发；空白名等同于取消（不拼出空的路径）；
 *   [2] Esc / 遮罩 / 「取消」三个出口都不下发；
 *   [3] 新建文件夹 / 新建文件都走自绘弹窗（并把名称拼在当前目录下）；
 *   [4] 批量删除必须经确认：取消 → 不下发；确认 → 才下发；
 *   [5] 全程一次都没有调用原生 window.prompt / window.confirm。
 */
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
const clickEl = (doc, el) => el.dispatchEvent(new doc.defaultView.Event("click", { bubbles: true }));
const press = (doc, el, key) => el.dispatchEvent(new doc.defaultView.KeyboardEvent("keydown",
  { key: key, bubbles: true, cancelable: true }));

const ENTRIES = [
  { name: "..", is_dir: true },
  { name: "a.txt", is_dir: false, size: 12 },
  { name: "b.txt", is_dir: false, size: 34 },
];

async function boot(opts) {
  opts = opts || {};
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const calls = [];
  const queue = [
    { kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
    { kind: "devices", payload: { items: [{ serial: "A1", ok: true, checked: true }] } },
    { kind: "file", payload: { serial: "A1", path: "/sdcard/Download",
                               entries: opts.entries || ENTRIES } },
  ];
  window.__nativePrompt = 0;
  window.__nativeConfirm = 0;
  window.prompt = () => { window.__nativePrompt += 1; return null; };
  window.confirm = () => { window.__nativeConfirm += 1; return true; };
  const impl = {
    boot: () => Promise.resolve({ version: "v-test", warnings: [], commands: [],
                                  adb: "/usr/bin/adb", save_dir: "/tmp" }),
    take_events: () => Promise.resolve(queue.splice(0, queue.length)),
    default_save_dir: () => Promise.resolve({ dir: "" }),
    // 显式实现也要记账：父目录行上翻 / 刷新都靠 file_list 的调用次数判断
    file_list: (...args) => {
      calls.push({ fn: "file_list", args });
      return Promise.resolve({ ok: true });
    },
  };
  window.pywebview = {
    api: new Proxy(impl, {
      get(t, k) {
        if (k === "then") return undefined;
        if (k in t) return t[k];
        return function (...args) {
          calls.push({ fn: String(k), args });
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  const doc = window.document;
  await waitFor(() => doc.querySelectorAll("#file-body tr").length >= 2, 4000, "文件列表渲染");
  return { window, doc, calls };
}

const callsOf = (calls, fn) => calls.filter((c) => c.fn === fn);
const modalOpen = (doc, id) => {
  const m = doc.getElementById(id);
  return !!m && !m.classList.contains("hidden");
};

const watchdog = setTimeout(() => {
  console.log("    (看门狗触发：疑似断言抛错导致未收尾)");
  process.exit(fail ? 1 : 0);
}, 90000);

(async () => {
  console.log("[0] 输入弹窗结构 + 打开时聚焦并全选");
  {
    const { doc } = await boot();
    ok(!!doc.getElementById("input-modal"), "有应用内输入弹窗");
    ok(!!doc.getElementById("input-field") && !!doc.getElementById("input-yes") &&
       !!doc.getElementById("input-no"), "输入框 / 确定 / 取消 都在");
    clickEl(doc, doc.getElementById("file-mkdir"));
    await sleep(60);
    ok(modalOpen(doc, "input-modal"), "点「新建文件夹」弹出输入框");
    const field = doc.getElementById("input-field");
    ok(doc.activeElement === field, "焦点在输入框（可以直接敲字）");
    ok(field.selectionStart === 0 && field.selectionEnd === field.value.length,
       "内容全选（重命名时直接敲新名即可）");
  }

  console.log("\n[1] 确定 → 按输入值下发；空白名等同取消");
  {
    const { doc, calls } = await boot();
    clickEl(doc, doc.getElementById("file-mkdir"));
    await sleep(40);
    doc.getElementById("input-field").value = "  newdir  ";
    clickEl(doc, doc.getElementById("input-yes"));
    await sleep(60);
    const mk = callsOf(calls, "file_mkdir");
    ok(mk.length === 1, "下发一次 file_mkdir");
    ok(mk.length && mk[0].args[1] === "/sdcard/Download/newdir",
       "名称去空白后拼在当前目录下（实得 " + (mk[0] && mk[0].args[1]) + "）");
    ok(!modalOpen(doc, "input-modal"), "确认后弹窗关闭");

    const before = mk.length;
    clickEl(doc, doc.getElementById("file-touch"));
    await sleep(40);
    doc.getElementById("input-field").value = "   ";
    clickEl(doc, doc.getElementById("input-yes"));
    await sleep(80);
    ok(callsOf(calls, "file_touch").length === 0,
       "空白名不下发（否则会拼出 /sdcard/Download/ 这种目录路径）");
    ok(mk.length === before, "上一次的操作没有重复下发");
  }

  console.log("\n[2] Esc / 遮罩 / 取消：三个出口都不下发");
  {
    const { doc, calls } = await boot();
    const open = async () => {
      clickEl(doc, doc.getElementById("file-mkdir"));
      await sleep(40);
    };
    await open();
    press(doc, doc, "Escape");
    await sleep(60);
    ok(!modalOpen(doc, "input-modal"), "Esc 关闭弹窗");
    ok(callsOf(calls, "file_mkdir").length === 0, "Esc 不下发 file_mkdir");

    await open();
    clickEl(doc, doc.getElementById("input-no"));
    await sleep(60);
    ok(!modalOpen(doc, "input-modal") && callsOf(calls, "file_mkdir").length === 0,
       "「取消」不下发");

    await open();
    clickEl(doc, doc.getElementById("input-modal"));   // 点遮罩（弹窗自身）
    await sleep(60);
    ok(!modalOpen(doc, "input-modal") && callsOf(calls, "file_mkdir").length === 0,
       "点遮罩不下发");
  }

  console.log("\n[3] 新建文件同样走自绘弹窗");
  {
    const { doc, calls } = await boot();
    clickEl(doc, doc.getElementById("file-touch"));
    await sleep(40);
    doc.getElementById("input-field").value = "note.md";
    clickEl(doc, doc.getElementById("input-yes"));
    await sleep(60);
    const tc = callsOf(calls, "file_touch");
    ok(tc.length === 1 && tc[0].args[1] === "/sdcard/Download/note.md",
       "file_touch 目标 = 当前目录 + 新名（实得 " + (tc[0] && tc[0].args[1]) + "）");
  }

  console.log("\n[4] 批量删除必须经确认（不能跳过直接删）");
  {
    const { doc, calls } = await boot();
    Array.from(doc.querySelectorAll("#file-body .file-check")).forEach((c) => {
      c.checked = true;
    });
    doc.getElementById("file-sel-all").checked = true;
    clickEl(doc, doc.getElementById("file-batch-del"));
    await sleep(60);
    ok(modalOpen(doc, "confirm-modal"), "点「删除选中」先弹确认框");
    ok(callsOf(calls, "file_remove").length === 0, "未确认前不下发 file_remove");
    const text = doc.getElementById("confirm-text").textContent || "";
    ok(/a\.txt/.test(text) || /b\.txt/.test(text), "确认框里列出要删的项（实际：" + text.replace(/\n/g, " | ") + "）");

    clickEl(doc, doc.getElementById("confirm-no"));
    await sleep(60);
    ok(callsOf(calls, "file_remove").length === 0, "点「否」不下发 file_remove");

    clickEl(doc, doc.getElementById("file-batch-del"));
    await sleep(60);
    clickEl(doc, doc.getElementById("confirm-yes"));
    await sleep(80);
    const rm = callsOf(calls, "file_remove");
    ok(rm.length === 1, "点「是」才下发 file_remove");
    ok(rm.length && rm[0].args[1].length === 2, "带上了勾选的 2 个路径（实得 " +
       (rm[0] && rm[0].args[1].length) + "）");
  }

  console.log("\n[5] 全程不依赖原生 window.prompt / window.confirm");
  {
    const { window } = await boot();
    ok(window.__nativePrompt === 0 && window.__nativeConfirm === 0,
       "一次都没碰原生 prompt / confirm（pywebview 里它们可能是空实现）");
  }

  console.log("\n[6] 父目录行（..）不给「重命名 / 删除」按钮");
  {
    const { doc, calls } = await boot();
    const rows = Array.from(doc.querySelectorAll("#file-body tr"));
    const parentRow = rows.find((tr) => tr.dataset.name === "..");
    ok(!!parentRow, "第一行是父目录 ..");
    const acts = Array.from(parentRow.querySelectorAll("td.act button"))
      .map((b) => b.textContent.trim());
    ok(acts.length === 0,
       "父目录行没有任何操作按钮（实得：" + (acts.join(",") || "无") + "）");
    ok(!!parentRow.querySelector("td.act"),
       "空的操作单元格仍在（其它行按列对齐，不会错位）");

    const fileRow = rows.find((tr) => tr.dataset.name === "a.txt");
    const fileActs = Array.from(fileRow.querySelectorAll("td.act button"))
      .map((b) => b.textContent.trim()).sort().join(",");
    ok(fileActs === "下载,删除,查看,重命名" || fileActs === "下载,删除,查看,重命名".split(",").sort().join(","),
       "普通文件行四个操作都在（实得：" + fileActs + "）");

    // 父目录行仍可点击上翻（导航能力不能一起被删掉）
    const nameCell = parentRow.querySelector("td.name");
    clickEl(doc, nameCell);
    await sleep(60);
    ok(callsOf(calls, "file_list").length >= 1, "点父目录行仍会上翻一级");
  }

  clearTimeout(watchdog);
  console.log("\n结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
