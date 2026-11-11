/* jsdom 前端测试：adb_info 事件刷新关于页 adb 版本
 *
 * boot 阶段为省掉 `adb version` 子进程等待只做了文件级探测（adb_ok +
 * prefs 缓存版本）；后台预热线程探测到真实版本后推 adb_info 事件，
 * 关于页的 adb 行要随之刷新；探测失败时要纠正 boot「文件在」的误判。
 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.join(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "frontend/index.html"), "utf8");
const js = fs.readFileSync(path.join(ROOT, "frontend/js/app.js"), "utf8");

let pass = 0, fail = 0;
function ok(c, n) {
  if (c) { pass++; console.log("  ✓ " + n); }
  else { fail++; console.log("  ✗ " + n); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitFor(fn, ms = 5000, label = "") {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    let v = false;
    try { v = !!fn(); } catch (e) { v = false; }
    if (v) return true;
    await sleep(30);
  }
  console.log("    (waitFor 超时: " + label + ")");
  return false;
}

function mkEnv() {
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true,
    url: "http://localhost/", resources: "usable",
  });
  const w = dom.window, d = w.document;
  const pending = [];
  w.pywebview = {
    api: new Proxy({
      boot: () => Promise.resolve({
        version: "2026.1110.0836", warnings: [], adb: "adb",
        commands: [], settings: {}, state_labels: [], lc_buffers: [],
      }),
      take_events: () => Promise.resolve(pending.splice(0)),
      default_save_dir: () => Promise.resolve({ dir: "" }),
      update_info: () => Promise.resolve({ ok: true, version: "2026.1110.0836",
                                           enabled: true, checking: false,
                                           last: null, skipped: "" }),
    }, { get(t, k) { if (k === "then") return undefined;
                     if (k in t) return t[k];
                     return () => Promise.resolve({ ok: true }); } }),
  };
  Object.defineProperty(d, "readyState", { value: "complete", configurable: true });
  return { dom, w, d, pending };
}

(async () => {
  console.log("\nadb_info 事件刷新关于页 adb 版本\n");

  // ① boot 先回填缓存版本，adb_info 到达后替换成真实版本
  {
    const { w, d, pending } = mkEnv();
    w.eval(js);
    await waitFor(() => !d.getElementById("about-update-check").disabled,
                  4000, "初始化完成");
    pending.push({ kind: "booted",
                   payload: { version: "2026.1110.0836", warnings: [],
                              adb: "缓存版本 1.0.41", commands: [], settings: {},
                              state_labels: [], lc_buffers: [], adb_ok: true } });
    ok(await waitFor(() => d.getElementById("about-adb").textContent === "缓存版本 1.0.41",
                     4000, "boot 回填缓存版本"),
       "booted 先把 prefs 缓存版本填到关于页");
    pending.push({ kind: "adb_info",
                   payload: { ok: true, path: "adb",
                              version: "Android Debug Bridge version 34.0.0" } });
    ok(await waitFor(() => d.getElementById("about-adb").textContent ===
                            "Android Debug Bridge version 34.0.0",
                     4000, "adb_info 刷新真实版本"),
       "adb_info 事件到达后关于页替换为真实版本");
  }

  // ② 探测失败：纠正 boot「文件找得到」的误判
  {
    const { w, d, pending } = mkEnv();
    w.eval(js);
    await waitFor(() => !d.getElementById("about-update-check").disabled,
                  4000, "初始化完成");
    pending.push({ kind: "booted",
                   payload: { version: "2026.1110.0836", warnings: [],
                              adb: "adb", commands: [], settings: {},
                              state_labels: [], lc_buffers: [], adb_ok: true } });
    await waitFor(() => d.getElementById("about-adb").textContent === "adb",
                  4000, "boot 回填路径");
    pending.push({ kind: "adb_info",
                   payload: { ok: false, path: "adb", version: "" } });
    ok(await waitFor(() => d.getElementById("about-adb").textContent.indexOf("未就绪") >= 0,
                     4000, "adb_info 失败纠正"),
       "adb 文件在但跑不起来时，关于页被纠正为「未就绪」");
  }

  console.log("\n结果： " + pass + " 通过 / " + fail + " 失败\n");
  process.exit(fail > 0 ? 1 : 0);
})();
