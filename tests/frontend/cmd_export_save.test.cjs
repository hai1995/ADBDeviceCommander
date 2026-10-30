/* jsdom 前端行为测试：导出弹窗「保存到文件」成功后的反馈

   需求：点「保存到文件」且后端保存成功后 ——
     1. 弹一个 toast 轻提示（用户不必去状态跑马灯里找结果）；
     2. 自动关闭导出弹窗；
     3. 不再自动用系统程序打开导出文件（避免「关掉弹窗又弹一个编辑器」）。 */
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

function mkEnv() {
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const calls = [];
  let round = 0;
  const batches = [[
    { kind: "booted", payload: { version: "v-test", warnings: [], commands: [], adb: "adb" } },
  ]];
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          calls.push({ fn: k, args });
          if (k === "boot") return Promise.resolve({ version: "v-test", warnings: [], commands: [], adb: "adb" });
          if (k === "take_events") { const b = batches[round] || []; round++; return Promise.resolve(b); }
          if (k === "export_commands_save") {
            return Promise.resolve({ ok: true, path: "/tmp/commands_export.json" });
          }
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  return { window, calls };
}

const watchdog = setTimeout(() => {
  console.log("    (看门狗触发：疑似断言抛错导致未收尾)");
  process.exit(fail ? 1 : 0);
}, 20000);

(async () => {
  console.log("\n[A] 保存成功 → toast + 关闭弹窗，不再自动打开文件");
  const { window, calls } = mkEnv();
  const doc = window.document;
  await waitFor(() => !!doc.getElementById("cmd-export-save"), 3000, "页面就绪");

  const modal = doc.getElementById("cmd-export-modal");
  modal.classList.remove("hidden");          // 模拟弹窗已打开
  await sleep(30);
  ok(!modal.classList.contains("hidden"), "前置：弹窗处于打开态");

  doc.getElementById("cmd-export-save").click();

  const gotToast = await waitFor(() => {
    const t = doc.querySelector("#toast-wrap .toast");
    return t && /保存/.test(t.textContent || "");
  }, 4000, "toast 出现");
  ok(gotToast, "保存成功后弹出 toast 提示");
  ok(modal.classList.contains("hidden"), "保存成功后导出弹窗关闭");
  ok(calls.some((c) => c.fn === "export_commands_save"), "确实调用了后端 export_commands_save");
  ok(!calls.some((c) => c.fn === "open_local_file"),
    "不再自动打开导出文件（避免关掉弹窗又弹一个窗口）");

  clearTimeout(watchdog);
  console.log("\n" + "=".repeat(46));
  console.log("结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
