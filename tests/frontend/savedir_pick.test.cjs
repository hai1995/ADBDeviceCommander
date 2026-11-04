/* jsdom 前端测试：保存目录「选择」按钮（代替手动输入） + 打开按钮更名

   回归：三处保存目录（工具 / Logcat / 文件）各自新增「选择」按钮，点击后弹系统
   文件夹对话框，把选中的路径写回输入框并落盘；原「打开」按钮更名为「打开目录」。
   用与 mirror_resize / settings_persist 同款的 harness，额外支持 overrides 指定 api 方法。 */
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
    await sleep(40);
  }
  console.log("    (waitFor 超时: " + label + ")");
  return false;
}

function mkEnv(opts) {
  opts = opts || {};
  const overrides = opts.overrides || {};
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const calls = [];
  const queue = [];
  let round = 0;
  window.__push = (ev) => queue.push(ev);
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          calls.push({ fn: k, args });
          if (overrides[k]) return overrides[k].apply(null, args);
          if (k === "boot") {
            return Promise.resolve({ ok: true, version: "v-test", warnings: [], adb: "adb" });
          }
          if (k === "take_events") {
            round++;
            if (round === 1) {
              return Promise.resolve([{ kind: "booted", payload: {
                version: "v-test", warnings: [], commands: [], adb: "adb",
                settings: opts.settings || {},
              } }]);
            }
            return Promise.resolve(queue.splice(0, queue.length));
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

(async () => {
  const watchdog = setTimeout(() => {
    console.log("    (看门狗触发)");
    process.exit(fail ? 1 : 0);
  }, 30000);

  console.log("\n[1] 点击「选择」：弹对话框，选中路径写回输入框并落盘");
  {
    const { window, calls } = mkEnv({
      overrides: {
        select_save_dir: () => Promise.resolve({ ok: true, path: "D:\\picked" }),
      },
    });
    const doc = window.document;
    await waitFor(() => doc.getElementById("tool-pick") && doc.getElementById("tool-dir"), 3000, "就绪");
    const dir = doc.getElementById("tool-dir");
    dir.value = "D:\\old";
    doc.getElementById("tool-pick").click();
    const set = await waitFor(() => doc.getElementById("tool-dir").value === "D:\\picked", 3000, "路径写回");
    ok(set, "选中路径写回工具页输入框");
    ok(doc.getElementById("lc-dir").value === "D:\\picked", "同步镜像到 Logcat 页");
    ok(doc.getElementById("file-dir").value === "D:\\picked", "同步镜像到文件页");
    const saved = calls.filter((c) => c.fn === "save_settings" && c.args[0] && c.args[0].save_dir === "D:\\picked");
    ok(saved.length >= 1, "路径落盘到 save_settings（save_dir=D:\\picked）");
  }

  console.log("\n[2] 对话框返回非 ok（不支持 / 取消）：不改动输入框、不落盘");
  {
    const { window, calls } = mkEnv({
      overrides: {
        select_save_dir: () => Promise.resolve({ ok: false, reason: "unsupported" }),
      },
    });
    const doc = window.document;
    await waitFor(() => doc.getElementById("tool-pick"), 3000, "就绪");
    const dir = doc.getElementById("tool-dir");
    dir.value = "D:\\keep";
    const saveBefore = calls.filter((c) => c.fn === "save_settings").length;
    doc.getElementById("tool-pick").click();
    await sleep(150);
    ok(doc.getElementById("tool-dir").value === "D:\\keep", "未选中路径时输入框原值不动");
    const saveAfter = calls.filter((c) => c.fn === "save_settings").length;
    ok(saveAfter === saveBefore, "没有触发 save_settings（不落盘）");
  }

  console.log("\n通过 " + pass + " / 失败 " + fail);
  process.exit(fail ? 1 : 0);
})();
