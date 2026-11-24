/* jsdom 前端测试：运行日志每行都要带 [HH:MM:SS] 时间戳。

   背景：长录制收尾跨分钟、夹杂设备失联/重连，没有时间戳就无法判断
   「哪一步卡了多久、先后是否颠倒」。守卫状态日志行与顶栏跑马灯都带戳，
   且 toast / 告警弹窗保留原文（瞬时提示带戳冗余）。 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = "../../";
const html = fs.readFileSync(path.join(__dirname, ROOT, "frontend/index.html"), "utf8");
const js = fs.readFileSync(path.join(__dirname, ROOT, "frontend/js/app.js"), "utf8");

let pass = 0, fail = 0;
function ok(cond, name) {
  if (cond) { pass++; console.log("  ✓ " + name); }
  else { fail++; console.log("  ✗ " + name); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitFor(fn, ms = 5000, label = "") {
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
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true,
                                url: "http://localhost/" });
  const { window } = dom;
  const queue = [
    { kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
  ];
  const impl = {
    boot: () => Promise.resolve({ version: "v-test", warnings: [], commands: [],
                                  adb: "/usr/bin/adb", save_dir: "/tmp" }),
    take_events: () => Promise.resolve(queue.splice(0, queue.length)),
    default_save_dir: () => Promise.resolve({ dir: "" }),
  };
  window.pywebview = {
    api: new Proxy(impl, {
      get(t, k) {
        if (k === "then") return undefined;
        if (k in t) return t[k];
        return function () { return Promise.resolve({ ok: true }); };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  const doc = window.document;
  await waitFor(() => !!doc.getElementById("status"), 4000, "status 容器就绪");
  const push = async (kind, payload, cond) => {
    queue.push({ kind, payload });
    if (cond) return waitFor(cond, 3000, "事件落地 " + kind);
    await sleep(700);
    return true;
  };
  return { window, doc, push };
}

const STAMP = /^\[\d{2}:\d{2}:\d{2}\] /;

(async () => {
  console.log("[1] 源码含时间戳工具且只作用于状态行");
  {
    ok(/function logStamp\(\)/.test(js), "定义了 logStamp() 时间戳函数");
    ok(/pushLine\(els\.status, stamped, cls\)/.test(js), "状态日志行用带戳文本");
    ok(/pushTicker\(stamped, cls\)/.test(js), "顶栏跑马灯用带戳文本");
    ok(/showToast\(type, text\)/.test(js), "toast 保留原文");
    ok(/items: \[\{ level: type, text: text \}\]/.test(js), "告警弹窗保留原文");
  }

  console.log("\n[2] 后端推送的状态行落地后带时间戳");
  {
    const { doc, push } = await boot();
    await push("status", { type: "info", text: "▶ 正在启动录屏…" },
      () => (doc.getElementById("status") || {}).textContent.indexOf("正在启动录屏") >= 0);
    const lines = Array.from(doc.querySelectorAll("#status .line"));
    const matched = lines.find((el) => el.textContent.indexOf("正在启动录屏") >= 0);
    ok(!!matched, "状态行已落地");
    ok(!!matched && STAMP.test(matched.textContent),
       "状态行以 [HH:MM:SS] 开头：" + (matched ? matched.textContent : "无"));
    ok(!!matched && matched.textContent.indexOf("▶ 正在启动录屏…") >= 0,
       "原文完整保留（时间戳只是前缀）");
  }

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
