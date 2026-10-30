/* jsdom 前端行为测试：文件页在「没有受控设备」时必须有反馈、且不留陈旧选择态

   两个回归点（都在 renderFileDev / 文件按钮上）：
   1) renderFileDev() 在 firstChecked() 为 null 时只清空表格就 return，
      fileAnchor 与「已选 N 项 / 下载选中 / 删除选中」不复位 —— 取消勾选最后一台
      设备后，表格空了但批量按钮仍亮着、还写着「已选 3 项」，点了没有任何反应。
   2) 刷新 / 上级 / 新建文件夹 / 新建文件 / 上传在 fileSerial 为 null 时照样调
      后端（file_list(null, ...)），后端返回 {"ok": false, "reason": "no_device"}
      却不下发任何状态；前端也忽略返回值 —— 用户点了按钮，界面上零反馈。
      批量下载 / 批量删除早就有「请先勾选设备」的提示，这里补齐其余入口。 */
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
async function waitFor(fn, ms = 4000, label = "") {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    let v = false;
    try { v = !!fn(); } catch (e) { v = false; }
    if (v) return true;
    await sleep(20);
  }
  console.log("    (waitFor 超时: " + label + ")");
  return false;
}

function mkEnv(stack) {
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const calls = [];
  let round = 0;
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          calls.push({ fn: String(k), args });
          if (k === "boot") {
            return Promise.resolve({ version: "v-test", warnings: [], commands: [], adb: "adb" });
          }
          if (k === "take_events") {
            const b = stack[round] || [];
            round++;
            return Promise.resolve(b);
          }
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  window.prompt = () => "新名字";
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  return { window, calls, doc: window.document };
}

const dev = (checked) => ({ serial: "A1", model: "Pixel", state: "device", ok: true, checked });
const ENTRIES = [
  { name: "..", is_dir: true, size: 0, date: "", perm: "drwxr-xr-x" },
  { name: "a.txt", is_dir: false, size: 10, date: "", perm: "-rw-r--r--" },
  { name: "b.txt", is_dir: false, size: 20, date: "", perm: "-rw-r--r--" },
];
function click(window, el) {
  el.dispatchEvent(new window.Event("click", { bubbles: true }));
}
function statusText(doc) {
  return Array.from(doc.querySelectorAll("#status .line")).map((d) => d.textContent).join("\n");
}

(async () => {
  console.log("\n[1] 取消勾选最后一台设备后：清空列表 + 复位选择态");
  {
    const { window, doc } = mkEnv([
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
       { kind: "devices", payload: { items: [dev(true)] } }],
      [{ kind: "file", payload: { serial: "A1", path: "/sdcard", entries: ENTRIES } }],
      [{ kind: "devices", payload: { items: [dev(false)] } }],
    ]);
    await waitFor(() => doc.querySelectorAll("#file-body tr").length === 3, 4000, "目录渲染");
    ok(doc.querySelectorAll("#file-body tr").length === 3, "文件表格渲染 3 行");

    // 勾选两个文件，制造「已选 2 项」（父目录「..」没有复选框，故为 2 个）
    const selAll = doc.getElementById("file-sel-all");
    selAll.checked = true;
    selAll.dispatchEvent(new window.Event("change", { bubbles: true }));
    await waitFor(() => doc.getElementById("file-sel-count").textContent === "已选 2 项",
                  4000, "选择计数");
    ok(doc.getElementById("file-sel-count").textContent === "已选 2 项",
       "勾选后计数为「已选 2 项」（实际：" + doc.getElementById("file-sel-count").textContent + "）");
    ok(doc.getElementById("file-batch-dl").disabled === false, "「下载选中」变为可用");

    // 取消勾选设备
    await waitFor(() => doc.querySelectorAll("#file-body tr").length === 0, 4000, "列表清空");
    ok(doc.querySelectorAll("#file-body tr").length === 0, "取消勾选设备后表格清空");
    ok(doc.getElementById("file-sel-count").textContent === "已选 0 项",
       "选择计数同步归零（实际：" + doc.getElementById("file-sel-count").textContent + "）");
    ok(doc.getElementById("file-batch-dl").disabled === true, "「下载选中」回到禁用");
    ok(doc.getElementById("file-batch-del").disabled === true, "「删除选中」回到禁用");
  }

  console.log("\n[2] 没有受控设备时：各文件入口都必须给出「请先勾选设备」反馈");
  {
    const { window, calls, doc } = mkEnv([
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
       { kind: "devices", payload: { items: [] } }],
    ]);
    await sleep(600);
    const before = calls.filter((c) => c.fn.startsWith("file_")).length;

    await waitFor(() => doc.getElementById("file-dev-now").textContent === "未选设备", 3000, "无设备");
    ok(doc.getElementById("file-dev-now").textContent === "未选设备", "顶部显示「未选设备」");

    click(window, doc.getElementById("file-refresh"));
    click(window, doc.getElementById("file-up"));
    click(window, doc.getElementById("file-mkdir"));
    click(window, doc.getElementById("file-touch"));
    await sleep(80);

    const after = calls.filter((c) => c.fn.startsWith("file_")).length;
    ok(after === before,
       "无设备时不再向后端发无效请求（调用数 " + before + " -> " + after + "）");
    const st = statusText(doc);
    ok((st.match(/请先勾选设备/g) || []).length >= 4,
       "刷新/上级/新建文件夹/新建文件都给出了「请先勾选设备」提示（实际命中 "
       + ((st.match(/请先勾选设备/g) || []).length) + " 次）");
  }

  console.log("\n结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
