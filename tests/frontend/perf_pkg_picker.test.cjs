/* jsdom 前端行为测试：性能监控「应用包名」选择器（下拉 + 模糊搜索）

   后端读包名 / 缓存在 tests/test_backend_perf.py 与 test_backend_controller.py
   里锁定；这里只锁前端契约：
   1) 默认值是「跟随前台应用」（空串），不是「必须先填个包名」；
   2) 下拉打开始终带设备序列号去读列表，只列第三方应用，勾「含系统应用」才加；
   3) 模糊搜索能命中「中间连续片段」与「按顺序凑出来」两种输入；
   4) 选中 / 手输 / 全系统三种取值都落盘到 perf_pkg，并原样传给 perf_start；
   5) 读取失败时把原因写在弹层里，不假装成功（列表空 ≠ 设备上没有应用）。 */
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

function fakeCtx() {
  const ctx = {};
  ["setTransform", "clearRect", "beginPath", "closePath", "moveTo", "lineTo",
   "arc", "rect", "roundRect", "fillRect", "save", "restore", "stroke", "fill",
   "fillText", "strokeText"].forEach((k) => { ctx[k] = () => {}; });
  ctx.measureText = () => ({ width: 24 });
  ctx.createLinearGradient = () => ({ addColorStop() {} });
  return ctx;
}

const PKGS = {
  ok: true, serial: "S1",
  third: ["com.tencent.kuwo", "com.android.chrome", "com.example.demo"],
  system: ["com.android.settings", "com.android.systemui"],
};

function mkEnv(opts) {
  opts = opts || {};
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const calls = [];
  const settings = opts.settings || {};
  const commands = opts.commands || [
    { id: "a", name: "查看时间", labels: ["其他"],
      commands: [{ command: "adb shell date" }], clickCount: 0 },
  ];
  const pkgs = opts.pkgs || PKGS;
  let round = 0;
  const batches = [[
    { kind: "booted",
      payload: { version: "v-test", warnings: [], adb: "adb",
                 commands: commands, settings: settings } },
    { kind: "devices",
      payload: { items: [{ serial: "S1", model: "Pixel 7", state: "device",
                           ok: true, checked: true }] } },
  ]];

  window.HTMLCanvasElement.prototype.getContext = () => fakeCtx();
  Object.defineProperty(window.HTMLElement.prototype, "clientWidth",
    { configurable: true, get() { return 820; } });
  Object.defineProperty(window.HTMLElement.prototype, "clientHeight",
    { configurable: true, get() { return 320; } });

  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          calls.push({ fn: k, args });
          if (k === "boot") {
            return Promise.resolve({ version: "v-test", warnings: [],
                                     commands: commands, adb: "adb",
                                     settings: settings });
          }
          if (k === "take_events") {
            const b = batches[round] || []; round++;
            return Promise.resolve(b);
          }
          if (k === "perf_list_packages") {
            const res = (typeof pkgs === "function") ? pkgs(...args) : pkgs;
            return Promise.resolve(res);
          }
          if (k === "perf_start") {
            return Promise.resolve({ ok: true, serial: "S1", interval: 1.0,
              info: { serial: "S1", model: "Pixel 7", pkg: "", pkg_mode: "auto",
                      android: "13", size: "1080x2340" } });
          }
          if (k === "perf_poll") {
            return Promise.resolve({ running: true, seq: 0, samples: [], info: {} });
          }
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState",
    { value: "complete", configurable: true });
  window.eval(js);
  return { window, calls };
}

const callsOf = (calls, fn) => calls.filter((c) => c.fn === fn);
const savedPatch = (calls, key) => {
  const hit = callsOf(calls, "save_settings").filter((c) => c.args[0] && key in c.args[0]);
  return hit.length ? hit[hit.length - 1].args[0][key] : undefined;
};
const click = (doc, el) => {
  const node = typeof el === "string" ? doc.getElementById(el) : el;
  node.dispatchEvent(new doc.defaultView.Event("click", { bubbles: true }));
};
const items = (doc) => Array.from(doc.querySelectorAll("#perf-pkg-list .pkg-item"));
const itemNames = (doc) => items(doc).map((el) => el.dataset.pkg);
const label = (doc) => doc.getElementById("perf-pkg-label").textContent;

const WATCHDOG_MS = 30000;

(async () => {
  const watchdog = setTimeout(() => {
    console.log("    (看门狗触发：疑似断言抛错导致未收尾，按当前结果退出)");
    process.exit(fail ? 1 : 0);
  }, WATCHDOG_MS);

  console.log("\n[1] 结构与默认值：默认跟随前台应用");
  {
    const { window } = mkEnv();
    const doc = window.document;
    ok(await waitFor(() => !!doc.getElementById("perf-start"), 3000, "页面就绪"),
       "选择器已渲染");
    ok(label(doc) === "跟随前台应用", "默认文案是「跟随前台应用」（不是空输入框）");
    ok(doc.getElementById("perf-pkg-pop").classList.contains("hidden"),
       "弹层初始隐藏");
    ok(doc.querySelectorAll("#perf-pkg-modes .pkg-mode").length === 2,
       "提供「跟随前台应用 / 监控全系统」两个内置项");
    ok(!doc.getElementById("perf-pkg").classList.contains("is-set"),
       "默认态不高亮（未锁定任何应用）");
    window.close();
  }

  console.log("\n[2] 打开下拉：按当前设备读取应用列表（只列第三方）");
  {
    const { window, calls } = mkEnv();
    const doc = window.document;
    await waitFor(() => doc.getElementById("perf-start").disabled === false, 3000, "设备就绪");
    click(doc, "perf-pkg");
    ok(!doc.getElementById("perf-pkg-pop").classList.contains("hidden"),
       "点按钮展开弹层");
    ok(await waitFor(() => items(doc).length === 3, 3000, "列表渲染"),
       "第三方应用全部列出（3 个）");
    const read = callsOf(calls, "perf_list_packages");
    ok(read.length === 1, "只读一次设备（不重复打 adb）");
    ok(read.length && read[0].args[0] === "S1", "读取时带上当前设备序列号");
    ok(read.length && read[0].args[1] === false, "首次打开不强制刷新（走后端缓存）");
    ok(itemNames(doc).indexOf("com.android.settings") < 0,
       "未勾「含系统应用」时不列系统应用");
    ok(/共 3 个/.test(doc.getElementById("perf-pkg-count").textContent),
       "计数与列表一致");
    window.close();
  }

  console.log("\n[3] 模糊搜索");
  {
    const { window } = mkEnv();
    const doc = window.document;
    await waitFor(() => doc.getElementById("perf-start").disabled === false, 3000, "设备就绪");
    click(doc, "perf-pkg");
    await waitFor(() => items(doc).length === 3, 3000, "列表渲染");
    const search = doc.getElementById("perf-pkg-search");
    const type = (v) => {
      search.value = v;
      search.dispatchEvent(new window.Event("input", { bubbles: true }));
    };
    type("chrome");
    ok(await waitFor(() => itemNames(doc).length === 1 && itemNames(doc)[0] === "com.android.chrome",
                     2800, "子串命中"),
       "子串命中（chrome → com.android.chrome）");
    type("tencent");
    ok(await waitFor(() => itemNames(doc).length === 1
                        && itemNames(doc)[0] === "com.tencent.kuwo", 2800, "片段命中"),
       "中间片段命中（tencent → com.tencent.kuwo）");
    type("comkwo");
    ok(await waitFor(() => itemNames(doc).length === 1
                        && itemNames(doc)[0] === "com.tencent.kuwo", 2800, "顺序命中"),
       "按顺序凑字符也能命中（comkwo → com.tencent.kuwo）");
    type("zzzz");
    ok(await waitFor(() => /无匹配/.test(doc.getElementById("perf-pkg-count").textContent),
                     2800, "无匹配"),
       "无匹配时明确提示，而不是留一片空白");
    window.close();
  }

  console.log("\n[4] 选中应用：按钮显示 + 落盘 perf_pkg");
  {
    const { window, calls } = mkEnv();
    const doc = window.document;
    await waitFor(() => doc.getElementById("perf-start").disabled === false, 3000, "设备就绪");
    click(doc, "perf-pkg");
    await waitFor(() => items(doc).length === 3, 3000, "列表渲染");
    const target = items(doc).filter((el) => el.dataset.pkg === "com.tencent.kuwo")[0];
    click(doc, target);
    ok(label(doc) === "com.tencent.kuwo", "按钮改为显示选中的包名");
    ok(doc.getElementById("perf-pkg").classList.contains("is-set"), "锁定态高亮");
    ok(await waitFor(() => savedPatch(calls, "perf_pkg") === "com.tencent.kuwo", 3000, "落盘"),
       "选择结果写入 config.json");
    ok(doc.getElementById("perf-pkg-pop").classList.contains("hidden"),
       "选完自动收起弹层");
    window.close();
  }

  console.log("\n[5] 全系统模式：界面文案 + 传给 perf_start 的取值");
  {
    const { window, calls } = mkEnv();
    const doc = window.document;
    await waitFor(() => doc.getElementById("perf-start").disabled === false, 3000, "设备就绪");
    click(doc, "perf-pkg");
    const sys = doc.querySelector('#perf-pkg-modes .pkg-mode[data-pkg="__system__"]');
    click(doc, sys);
    ok(label(doc) === "监控全系统", "按钮显示「监控全系统」");
    ok(await waitFor(() => savedPatch(calls, "perf_pkg") === "__system__", 3000, "落盘"),
       "全系统以 __system__ 落盘（与「空串 = 跟随前台」区分开）");
    click(doc, "perf-start");
    ok(await waitFor(() => callsOf(calls, "perf_start").length === 1, 3000, "启动监控"),
       "点「开始监控」");
    const args = callsOf(calls, "perf_start")[0].args;
    ok(args[2] === "__system__", "perf_start 原样带上 __system__");
    window.close();
  }

  console.log("\n[6] 含系统应用开关");
  {
    const { window, calls } = mkEnv();
    const doc = window.document;
    await waitFor(() => doc.getElementById("perf-start").disabled === false, 3000, "设备就绪");
    click(doc, "perf-pkg");
    await waitFor(() => items(doc).length === 3, 3000, "列表渲染");
    const box = doc.getElementById("perf-pkg-all");
    box.checked = true;
    box.dispatchEvent(new window.Event("change", { bubbles: true }));
    ok(await waitFor(() => items(doc).length === 5, 3000, "含系统应用"),
       "勾选后系统应用一并列出（3 + 2）");
    const sysItem = items(doc).filter((el) => el.dataset.pkg === "com.android.settings")[0];
    ok(sysItem && sysItem.classList.contains("is-sys"), "系统应用带 .is-sys 标记");
    ok(sysItem && /系统/.test(sysItem.textContent), "系统应用行尾有「系统」角标");
    ok(await waitFor(() => savedPatch(calls, "perf_pkg_all") === true, 3000, "开关落盘"),
       "开关状态写入 config.json");
    window.close();
  }

  console.log("\n[7] 读取失败：把原因显示出来，不假装成功");
  {
    const { window } = mkEnv({ pkgs: { ok: false, reason: "设备无响应：device offline" } });
    const doc = window.document;
    await waitFor(() => doc.getElementById("perf-start").disabled === false, 3000, "设备就绪");
    click(doc, "perf-pkg");
    ok(await waitFor(() => /offline/.test(doc.getElementById("perf-pkg-count").textContent)
                     || /offline/.test(doc.getElementById("perf-pkg-list").textContent),
                     3000, "失败原因"),
       "失败原因写在弹层里（含 offline）");
    ok(items(doc).length === 0, "失败时列表为空（不残留上次结果）");
    window.close();
  }

  console.log("\n[8] 刷新按钮强制重读");
  {
    const { window, calls } = mkEnv();
    const doc = window.document;
    await waitFor(() => doc.getElementById("perf-start").disabled === false, 3000, "设备就绪");
    click(doc, "perf-pkg");
    await waitFor(() => items(doc).length === 3, 3000, "列表渲染");
    click(doc, "perf-pkg-refresh");
    ok(await waitFor(() => callsOf(calls, "perf_list_packages").length === 2, 3000, "二次读取"),
       "点「刷新」重新读一次设备");
    const last = callsOf(calls, "perf_list_packages").slice(-1)[0];
    ok(last.args[1] === true, "刷新时带 refresh=true（绕过后端缓存）");
    window.close();
  }

  console.log("\n[9] 回填：config.json 里的值决定初始文案");
  {
    const { window } = mkEnv({ settings: { perf_pkg: "__system__" } });
    const doc = window.document;
    ok(await waitFor(() => label(doc) === "监控全系统", 3000, "回填全系统"),
       "上次选的是全系统 → 初始文案即「监控全系统」");
    window.close();
  }
  {
    const { window } = mkEnv({ settings: { perf_pkg: "com.foo.bar" } });
    const doc = window.document;
    ok(await waitFor(() => label(doc) === "com.foo.bar", 3000, "回填包名"),
       "上次锁定的是包名 → 初始文案即该包名");
    ok(doc.getElementById("perf-pkg").classList.contains("is-set"),
       "锁定态高亮跟着回填");
    window.close();
  }

  clearTimeout(watchdog);
  console.log("\n" + "=".repeat(46));
  console.log("结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
