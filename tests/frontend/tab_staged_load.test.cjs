/* jsdom 前端测试：主 tab 分步加载（按需准备）
 *
 * 用户诉求：「快速启动好程序的加载页，然后再去加载用户上次的停留页，
 * 待用户进行 tab 的切换后，再去对应加载 tab，等完整的 tab 都切换过之后，
 * 那就都完整加载出来了。」
 *
 * 这轮把它落成「每个 tab 一个 prepare 回调，切到它时才跑一次」：
 * 启动关键路径上只准备「用户马上要看的那一页」，其余的等切过去再准备。
 *
 * 锁四件事：
 *   [1] 启动时**不**做别的 tab 的活（Logcat 的设备调用、关于页的版本检查
 *       都不该发生）—— 这正是提速的地方；
 *   [2] 切到某个 tab 时，那一页的数据才到位（Logcat 包列表 / 关于页更新状态）；
 *   [3] prepare **只跑一次**：切走再切回来不会重复打设备（否则「按包过滤」
 *       下拉每次切页都要等 1~3 秒的设备回话）；
 *   [4] 启动时恢复上次停留的那一页时，那一页立刻就绪（用户点开就看到内容）。
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

const DEVICES = [{ serial: "A1", model: "Pixel", ok: true, checked: true, state: "device" }];

function mkEnv(opts) {
  opts = opts || {};
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const calls = [];
  const settings = opts.settings || {};
  const pending = [
    { kind: "booted", payload: { version: "v-test", warnings: [], adb: "adb",
                                 commands: [], settings } },
    { kind: "devices", payload: { items: opts.devices || DEVICES } },
  ];
  const impl = {
    boot: () => Promise.resolve({ version: "v-test", warnings: [], adb: "adb",
                                  commands: [], settings }),
    take_events: () => Promise.resolve(pending.splice(0)),
    default_save_dir: () => Promise.resolve({ dir: "" }),
    save_settings: (patch) => {
      calls.push({ fn: "save_settings", args: [patch] });
      return Promise.resolve({ ok: true });
    },
    // Logcat 的「按包过滤」下拉要打设备（pm list packages -3，1~3 秒）。
    // 分步加载后，这次设备调用应当**只在切到 Logcat 页时**发生。
    logcat_packages: () => {
      calls.push({ fn: "logcat_packages", args: [] });
      return Promise.resolve({ ok: true, packages: ["com.demo.app"] });
    },
    // 关于页的版本更新状态（本地读取，但仍是桥接往返）
    update_info: () => {
      calls.push({ fn: "update_info", args: [] });
      return Promise.resolve({ ok: true, version: "v-test", enabled: true,
                              checking: false, last: null, skipped: "" });
    },
  };
  window.pywebview = {
    api: new Proxy(impl, {
      get(t, k) {
        if (k === "then") return undefined;
        if (k in t) return t[k];
        return () => Promise.resolve({ ok: true });
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  return { window, doc: window.document, calls };
}

const countFn = (calls, fn) => calls.filter((c) => c.fn === fn).length;

function clickTab(doc, key) {
  const btn = doc.querySelector('.tab-btn[data-tab="' + key + '"]');
  if (btn) btn.click();
}

async function boot(opts) {
  const env = mkEnv(opts);
  await waitFor(() => env.doc.getElementById("pill").textContent === "已就绪",
                6000, "booted");
  return env;
}

(async () => {
  console.log("\n[1] 启动时不碰别的 tab 的活");
  {
    const { calls } = await boot({});
    // 停在默认页「设备指令」：Logcat 的设备调用与关于页的版本检查都不该发生
    ok(countFn(calls, "logcat_packages") === 0,
       "启动时没有打设备拉包列表（那是 Logcat 页的活）");
    ok(countFn(calls, "update_info") === 0,
       "启动时没有去拉关于页的更新状态（那是关于页的活）");
  }

  console.log("\n[2] 切到 Logcat 页 → 那页的数据才到位");
  {
    const { doc, calls } = await boot({});
    clickTab(doc, "logcat");
    await waitFor(() => countFn(calls, "logcat_packages") === 1, 4000, "切到 Logcat");
    ok(countFn(calls, "logcat_packages") === 1,
       "切到 Logcat 页时打了一次设备拉包列表");
    const sel = doc.getElementById("lc-pkg");
    await waitFor(() => sel.options.length >= 2, 4000, "包列表填充");
    ok(sel.options.length >= 2,
       "「按包过滤」下拉被填充（全部 + 1 个包）", sel.options.length + " 项");
  }

  console.log("\n[3] 切到关于页 → 更新状态才回填");
  {
    const { doc, calls } = await boot({});
    clickTab(doc, "about");
    await waitFor(() => countFn(calls, "update_info") === 1, 4000, "切到关于页");
    ok(countFn(calls, "update_info") === 1,
       "切到关于页时拉了一次更新状态");
  }

  console.log("\n[4] prepare 只跑一次：切走再切回来不重复打设备");
  {
    const { doc, calls } = await boot({});
    clickTab(doc, "logcat");
    await waitFor(() => countFn(calls, "logcat_packages") === 1, 4000, "第一次切到");
    clickTab(doc, "cmd");
    await sleep(80);
    clickTab(doc, "logcat");
    await sleep(200);
    ok(countFn(calls, "logcat_packages") === 1,
       "切走再切回 Logcat，设备调用没有重复发生（实际 "
       + countFn(calls, "logcat_packages") + " 次）");
  }

  console.log("\n[5] 启动就停在 Logcat → 那一页立刻就绪");
  {
    const { doc, calls } = await boot({ settings: { main_active_tab: "logcat" } });
    // 恢复上次停留的那一页时，它的 prepare 也要跑 —— 用户点开就看到内容
    await waitFor(() => countFn(calls, "logcat_packages") === 1, 4000, "启动即准备");
    ok(countFn(calls, "logcat_packages") === 1,
       "启动恢复到 Logcat 页时立刻准备了它（不用等用户再点一次）");
    const sel = doc.getElementById("lc-pkg");
    await waitFor(() => sel.options.length >= 2, 4000, "包列表填充");
    ok(sel.options.length >= 2, "恢复的那一页数据直接就位", sel.options.length + " 项");
  }

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail > 0 ? 1 : 0);
})();
