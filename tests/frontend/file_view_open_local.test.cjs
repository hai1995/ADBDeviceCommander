/* jsdom 前端行为测试：大文件「查看」弹窗 —— 路径后带「查看」按钮 + 关闭换成图标。
   验证：
   1. 大文件（已拉取到本地）弹窗：标题含本地路径，「查看」按钮可见；
   2. 点「查看」→ 调 api.open_local_file(本地路径)，直接尝试打开文件；
   3. 小文件（直接 cat 内容）弹窗：「查看」按钮隐藏；
   4. 关闭按钮是图标（class=modal-x、内容为 ×，不再是文字「关闭」），点击后弹窗关闭。 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.join(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "frontend/index.html"), "utf8");
const js = fs.readFileSync(path.join(ROOT, "frontend/js/app.js"), "utf8");
const css = fs.readFileSync(path.join(ROOT, "frontend/css/app.css"), "utf8");

process.on("unhandledRejection", (e) => { console.log("!! unhandledRejection:", e && e.stack ? e.stack : e); });

let pass = 0, fail = 0;
function ok(c, n) {
  if (c) { pass++; console.log("  ✓ " + n); }
  else { fail++; console.log("  ✗ " + n); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

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
  console.log("\n[D] 大文件查看弹窗：查看按钮 + 关闭图标");
  const LOCAL = "C:\\Users\\OD-HUA\\AppData\\Local\\Temp\\adb_view_144427d13_logcat.txt";
  const { window, calls } = await boot([
    { kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
    { kind: "file_view", payload: {
      serial: "A1", path: "/logcat/logcat.txt", text: null,
      local: LOCAL, note: "文件较大(14090440 字节)，已拉到本地临时文件",
    } },
  ]);
  const doc = window.document;

  // 1) 弹窗打开，标题含本地路径
  const modal = doc.getElementById("modal");
  ok(!modal.classList.contains("hidden"), "file_view 事件后弹窗打开");
  ok(doc.getElementById("modal-title").textContent.indexOf(LOCAL) >= 0,
    "标题含已拉取到本地的路径");

  // 2) 「查看」按钮可见（大文件场景）
  const btnView = doc.getElementById("modal-open-local");
  ok(btnView.hidden === false, "大文件场景显示「查看」按钮");
  ok(btnView.textContent.trim() === "查看", "按钮文案为「查看」");
  ok(/btn tiny/.test(btnView.className), "「查看」按钮走立体按钮样式（btn tiny）");

  // 3) 关闭按钮是图标：class=modal-x、内容为 ×，不再是文字「关闭」
  const btnClose = doc.getElementById("modal-close");
  ok(btnClose.className.indexOf("modal-x") >= 0, "关闭按钮换成图标类（modal-x）");
  ok(btnClose.textContent.trim() === "×", "关闭按钮内容为 × 图标（不再是文字「关闭」）");
  ok(btnClose.textContent.indexOf("关闭") < 0, "关闭按钮不再含文字「关闭」");

  // 4) 点「查看」→ 调 open_local_file(本地路径)
  btnView.click();
  await sleep(120);
  const openCalls = calls.filter((c) => c.fn === "open_local_file");
  ok(openCalls.length === 1 && openCalls[0].args[0] === LOCAL,
    "点「查看」→ 调 api.open_local_file(本地路径)，直接尝试打开文件");

  // 5) 点关闭图标 → 弹窗关闭
  btnClose.click();
  ok(modal.classList.contains("hidden"), "点关闭图标 → 弹窗关闭");

  // 6) 小文件场景（直接 cat 到内容）：「查看」按钮应隐藏
  const { window: w2 } = await boot([
    { kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
    { kind: "file_view", payload: {
      serial: "A1", path: "/sdcard/small.txt", text: "hello\nworld", local: null,
    } },
  ]);
  const doc2 = w2.document;
  ok(!doc2.getElementById("modal").classList.contains("hidden"), "小文件弹窗也打开");
  ok(doc2.getElementById("modal-open-local").hidden === true,
    "小文件场景（内容已在弹窗内）隐藏「查看」按钮");
  ok(doc2.getElementById("modal-body").textContent.indexOf("hello") >= 0,
    "小文件内容直接显示在弹窗里");
  w2.close();

  // 7) 关闭图标必须是立体渐变 + 落影（不能是扁平灰圆点）
  function cssBlock(sel) {
    const i = css.indexOf(sel + " {");
    return i < 0 ? "" : css.slice(i, css.indexOf("}", i));
  }
  const mx = cssBlock(".modal-x");
  ok(!!mx && /linear-gradient\(180deg/.test(mx), "关闭图标 .modal-x 是立体渐变");
  ok(!!mx && /0 2px 5px/.test(mx), "关闭图标带落影");

  console.log("\n==============================================");
  console.log("结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
