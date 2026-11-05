/* jsdom 前端测试：保存目录的「选择」按钮
 *
 * 背景（用户实报）：点了没反应。
 * 后端那一侧的根因是 ctypes 字段赋值抛 TypeError 被吞成「用户取消」（见
 * tests/test_backend_file.py），但**前端把它放大**了：所有非成功结果都不吭声，
 * 于是「取消」「打不开」「后端炸了」在界面上完全一样 —— 什么都看不到。
 *
 * 本文件只锁前端这一半的契约：
 *   [0] 选中路径 → 写进输入框 + 落盘（复用 change 逻辑）
 *   [1] 用户取消 → 静默（不打扰），输入框不变
 *   [2] 打不开（unsupported）→ 必须给一句话，别让人以为按钮坏了
 *   [3] 点击期间按钮禁用（连点会叠出好几个对话框），结束后恢复
 *   [4] 三个入口（Logcat / 工具区 / 文件页）行为一致
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
const clickEl = (doc, el) =>
  el.dispatchEvent(new doc.defaultView.Event("click", { bubbles: true }));

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
  ];
  // opts.pick: "ok" | "cancelled" | "unsupported" | "error"；opts.gate 为手动放行的 Promise
  const impl = {
    boot: () => Promise.resolve({ version: "v-test", warnings: [], commands: [],
                                  adb: "/usr/bin/adb", save_dir: "/tmp" }),
    take_events: () => Promise.resolve(queue.splice(0, queue.length)),
    default_save_dir: () => Promise.resolve({ dir: "" }),
    select_save_dir: (cur) => {
      calls.push({ fn: "select_save_dir", args: [cur] });
      const answer = opts.pick === "cancelled" ? { ok: false, reason: "cancelled" }
        : opts.pick === "unsupported" ? { ok: false, reason: "unsupported" }
        : opts.pick === "error" ? { ok: false, reason: "error", text: "no display" }
        : { ok: true, path: "D:\\shots" };
      return opts.gate ? opts.gate.then(() => answer) : Promise.resolve(answer);
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
  await waitFor(() => doc.querySelectorAll("#device-list .device-card").length >= 1,
                4000, "设备渲染");
  return { window, doc, calls };
}

const callsOf = (calls, fn) => calls.filter((c) => c.fn === fn);
const statusText = (doc) => (doc.getElementById("status") || {}).textContent || "";

const watchdog = setTimeout(() => {
  console.log("    (看门狗触发：疑似断言抛错导致未收尾)");
  process.exit(fail ? 1 : 0);
}, 90000);

(async () => {
  console.log("[0] 选中路径 → 写输入框 + 落盘");
  {
    const { doc, calls } = await boot({ pick: "ok" });
    const input = doc.getElementById("file-dir");
    input.value = "D:\\old";
    clickEl(doc, doc.getElementById("file-pick"));
    await waitFor(() => input.value === "D:\\shots", 3000, "路径写入");
    ok(input.value === "D:\\shots", "输入框被替换为选中目录（实得 " + input.value + "）");
    const pick = callsOf(calls, "select_save_dir");
    ok(pick.length === 1, "只弹一次对话框");
    ok(pick[0] && pick[0].args[0] === "D:\\old",
       "把当前目录传下去（对话框可定位到那里，实得 " + (pick[0] && pick[0].args[0]) + "）");
    ok(callsOf(calls, "save_settings").length >= 1, "复用 change 逻辑落盘（save_settings）");
  }

  console.log("\n[1] 用户取消 → 静默，不打扰");
  {
    const { doc } = await boot({ pick: "cancelled" });
    const input = doc.getElementById("file-dir");
    input.value = "D:\\old";
    const before = statusText(doc);
    clickEl(doc, doc.getElementById("file-pick"));
    await sleep(120);
    ok(input.value === "D:\\old", "取消不改输入框");
    ok(statusText(doc) === before, "取消不往状态栏写东西（实得：" + statusText(doc).slice(0, 40) + "）");
  }

  console.log("\n[2] 打不开 → 必须说一句（否则就是「点了没反应」）");
  {
    const { doc } = await boot({ pick: "unsupported" });
    clickEl(doc, doc.getElementById("file-pick"));
    await waitFor(() => statusText(doc).indexOf("无法弹出") >= 0, 3000, "提示落地");
    ok(statusText(doc).indexOf("无法弹出") >= 0,
       "状态栏提示环境不支持（实得：" + statusText(doc).slice(0, 60) + "）");
    ok(statusText(doc).indexOf("直接输入") >= 0, "给出可执行的退路");
  }

  console.log("\n[3] 点击期间禁用按钮，结束后恢复");
  {
    let release;
    const gate = new Promise((r) => { release = r; });
    const { doc } = await boot({ pick: "ok", gate });
    const btn = doc.getElementById("file-pick");
    ok(btn.disabled === false, "初始可用");
    clickEl(doc, btn);
    await sleep(60);
    ok(btn.disabled === true, "等待对话框期间禁用（连点会叠出多个对话框）");
    release();
    await waitFor(() => btn.disabled === false, 3000, "按钮恢复");
    ok(btn.disabled === false, "完成后恢复可用");
    ok(doc.getElementById("file-dir").value === "D:\\shots", "路径仍然写入");
  }

  console.log("\n[4] 三个入口行为一致");
  {
    for (const [btnId, inputId] of [["lc-pick", "lc-dir"], ["tool-pick", "tool-dir"],
                                    ["file-pick", "file-dir"]]) {
      const { doc } = await boot({ pick: "ok" });
      clickEl(doc, doc.getElementById(btnId));
      const input = doc.getElementById(inputId);
      await waitFor(() => input.value === "D:\\shots", 3000, btnId + " 写入");
      ok(input.value === "D:\\shots", btnId + " → " + inputId + " 已写入");
    }
  }

  clearTimeout(watchdog);
  console.log("\n结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
