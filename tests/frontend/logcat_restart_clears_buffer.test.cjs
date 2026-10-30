/* jsdom 前端行为测试：重新开始 Logcat 监控必须丢弃上一轮的日志缓冲

   回归点：startLc() 只清了视图（lcView.innerHTML = ""）与渲染队列，没有重置
   lcBuffers[lcSerial]。于是重新监控后，onLogcat 的 "append" 会把新会话的行
   接在**上一轮的 lines 数组**尾部：

     · 用户改一下级别 / 关键字 / 仅异常 → renderLogcat() 从缓冲全量重建，
       早已「清空」的旧日志（最多 3000 行）又整片冒出来；
     · 「保存到文件」→ bufToText() 会把上一轮 + 本轮的行写进同一个文件。

   修复：startLc 里一并把该设备的缓冲置空。 */
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

function mkEnv() {
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const queue = [];
  const calls = [];
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          calls.push({ fn: String(k), args });
          if (k === "boot") {
            return Promise.resolve({ version: "v-test", warnings: [], commands: [], adb: "adb" });
          }
          if (k === "take_events") return Promise.resolve(queue.splice(0, queue.length));
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  return { window, queue, calls, push: (e) => queue.push(e) };
}

const mkLines = (n, from = 0) => Array.from({ length: n }, (_, i) => ({
  raw: `01-01 00:00:00.000  1000  1000 I Tag: 第${from + i}行`,
  level: "I", tag: "Tag", msg: "第" + (from + i) + "行", exc: false,
}));
function click(window, el) {
  el.dispatchEvent(new window.Event("click", { bubbles: true }));
}

(async () => {
  const env = mkEnv();
  const doc = env.window.document;
  env.push({ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } });
  env.push({ kind: "devices", payload: { items: [{ serial: "A1", model: "Pixel", state: "device", ok: true, checked: true }] } });

  const view = doc.getElementById("lc-view");
  const counter = doc.getElementById("lc-counter");
  const startBtn = doc.getElementById("lc-start");
  const stopBtn = doc.getElementById("lc-stop");

  await waitFor(() => doc.getElementById("lc-dev").textContent === "设备: A1", 4000, "设备联动");
  ok(doc.getElementById("lc-dev").textContent === "设备: A1", "空闲态自动联动到受控设备 A1");

  // ---- 第一轮监控：30 行 ----
  click(env.window, startBtn);
  await waitFor(() => env.calls.some((c) => c.fn === "logcat_start"), 2000, "首次 logcat_start");
  env.push({ kind: "logcat", payload: { serial: "A1", status: "append", lines: mkLines(30), total: 30, exc: 0 } });
  await waitFor(() => view.childNodes.length === 30, 4000, "首轮 30 行入视图");
  ok(view.childNodes.length === 30, "首轮监控渲染 30 行（实际 " + view.childNodes.length + "）");
  ok(counter.textContent === "行数: 30 · 异常: 0", "首轮计数 30（实际：" + counter.textContent + "）");

  // ---- 停止 -> 重新开始 ----
  click(env.window, stopBtn);
  ok(stopBtn.disabled === true, "停止后「停止」按钮回到禁用态");
  click(env.window, startBtn);
  await waitFor(() => env.calls.filter((c) => c.fn === "logcat_start").length === 2, 2000, "二次 logcat_start");
  ok(view.childNodes.length === 0, "重新开始时视图立即清空（实际 " + view.childNodes.length + " 行）");

  // ---- 第二轮：只有 5 行 ----
  env.push({ kind: "logcat", payload: { serial: "A1", status: "append", lines: mkLines(5, 100), total: 5, exc: 0 } });
  await waitFor(() => view.childNodes.length === 5, 4000, "二轮 5 行入视图");
  ok(view.childNodes.length === 5, "二轮监控渲染 5 行（实际 " + view.childNodes.length + "）");

  // ---- 触发全量重渲染：缓冲里不该残留上一轮的 30 行 ----
  doc.getElementById("lc-levels").dispatchEvent(
    new env.window.Event("change", { bubbles: true }));
  await sleep(60);
  ok(view.childNodes.length === 5,
     "重渲染后仍只有本轮 5 行，上一轮日志不回流（实际 " + view.childNodes.length + " 行）");

  // ---- 「保存到文件」的内容同样不应混入上一轮 ----
  let saved = null;
  const origCreate = env.window.URL.createObjectURL;
  env.window.URL.createObjectURL = (blob) => { saved = blob; return "blob:fake"; };
  env.window.URL.revokeObjectURL = () => {};
  // jsdom 的 Blob 不实现 text()，改从 FileReader 读，保证内容可断言
  let savedText = "";
  env.window.HTMLAnchorElement.prototype.click = function () {};
  const origBlob = env.window.Blob;
  env.window.Blob = function (parts, opts) {
    savedText = (parts || []).join("");
    return new origBlob(parts, opts);
  };
  click(env.window, doc.getElementById("lc-save"));
  await sleep(60);
  ok(!savedText.includes("第0行"),
     "「保存到文件」不含上一轮的行（第0行）");
  ok(savedText.includes("第100行"),
     "「保存到文件」包含本轮的行（第100行）");
  env.window.URL.createObjectURL = origCreate;

  console.log("\n结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
