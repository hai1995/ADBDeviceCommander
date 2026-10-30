/* jsdom 前端测试：版本更新提示（关于页一行 + 新版本弹窗）
 *
 * 锁的是「不打扰」这条线，而不是「能弹出来」：
 *   1) 结构：关于页有自动检查开关 / 结果文字 / 检查按钮；弹窗有下载 / 跳过 / 稍后；
 *   2) 事件：只有 status=update 且未被标记 silenced 时才弹窗；
 *      已是最新 / 开发版 / 检查失败一律不弹（自动检查失败更不能当报错砸给用户）；
 *   3) 动作：去下载 → 调 update_open 并带上 URL；跳过 → 调 update_skip(version)；
 *      稍后 → 只关窗（下次启动还会提醒）；
 *   4) 收尾：update_state(running) 驱动「检查」按钮的禁用与文案，最终必须复位 ——
 *      漏了这一步按钮会永久停在「检查中…」，用户再也没法手动查。
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
const click = (win, el) => el.dispatchEvent(new win.Event("click", { bubbles: true }));
const change = (win, el) => el.dispatchEvent(new win.Event("change", { bubbles: true }));

const DEVICES = [{ serial: "A1", model: "Pixel", ok: true, checked: true, state: "device" }];

const RES_UPDATE = {
  status: "update", current: "2026.1029.1931", version: "2026.1103.1200",
  notes: "1. 修了轮询断链\n2. 新增诊断包",
  url: "https://github.com/hai1995/ADBDeviceCommander/releases/tag/v2026.1103.1200",
  asset: { name: "x_win64.zip", size: 20 * 1024 * 1024 },
  error: "", silenced: false,
};

function mkEnv(opts) {
  opts = opts || {};
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const calls = [];
  // pending 队列模拟后端事件总线：测试里 push 一条，前端下一次轮询就收到
  const pending = [
    { kind: "booted", payload: { version: opts.version || "2026.1029.1931", warnings: [],
                                 adb: "adb", commands: [],
                                 settings: opts.settings || {} } },
    { kind: "devices", payload: { items: DEVICES } },
  ];
  const impl = {
    boot: () => Promise.resolve({ version: opts.version || "2026.1029.1931",
                                  warnings: [], adb: "adb", commands: [],
                                  settings: opts.settings || {} }),
    take_events: () => Promise.resolve(pending.splice(0)),
    default_save_dir: () => Promise.resolve({ dir: "" }),
    save_settings: (patch) => {
      calls.push({ fn: "save_settings", args: [patch] });
      return Promise.resolve({ ok: true });
    },
    update_info: () => Promise.resolve(Object.assign(
      { ok: true, version: "2026.1029.1931", enabled: true, checking: false, last: null },
      opts.info || {})),
    update_check: (force) => {
      calls.push({ fn: "update_check", args: [force] });
      return Promise.resolve({ ok: true, status: "started" });
    },
    update_open: (url) => {
      calls.push({ fn: "update_open", args: [url] });
      return Promise.resolve({ ok: true, url: url });
    },
    update_skip: (v) => {
      calls.push({ fn: "update_skip", args: [v] });
      return Promise.resolve({ ok: true, version: v });
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
  return { window, doc: window.document, calls, pending };
}

const watchdog = setTimeout(() => {
  console.log("    (看门狗触发：疑似断言抛错导致未收尾)");
  process.exit(fail ? 1 : 0);
}, 90000);

(async () => {
  console.log("[A] 结构：关于页一行 + 弹窗控件都在");
  {
    const { doc } = mkEnv();
    ok(!!doc.getElementById("update-modal"), "有新版本弹窗");
    ok(doc.getElementById("update-modal").classList.contains("hidden"),
      "弹窗默认隐藏（不能一开程序就压在界面上）");
    ["update-current", "update-latest", "update-notes", "update-size",
      "update-download", "update-skip", "update-later", "update-close"].forEach((id) => {
        ok(!!doc.getElementById(id), "弹窗里有 #" + id);
      });
    ok(!!doc.getElementById("about-update-auto"), "关于页有「自动检查」复选框");
    ok(doc.getElementById("about-update-auto").checked,
      "自动检查默认勾选（与 core.prefs 的 update_check 默认 True 对齐）");
    ok(!!doc.getElementById("about-update-state"), "关于页有上次检查结果");
    ok(!!doc.getElementById("about-update-check"), "关于页有「检查」按钮");
  }

  console.log("\n[B] 事件：有新版本才弹，说明与体积都填上");
  {
    const { doc, window, pending } = mkEnv();
    await waitFor(() => !doc.getElementById("about-update-check").disabled, 4000, "初始化完成");
    pending.push({ kind: "update", payload: Object.assign({}, RES_UPDATE) });
    const shown = await waitFor(
      () => !doc.getElementById("update-modal").classList.contains("hidden"),
      4000, "弹窗打开");
    ok(shown, "收到 update 事件后弹窗出现");
    ok(/2026\.1103\.1200/.test(doc.getElementById("update-title").textContent),
      "标题带上新版本号");
    ok(doc.getElementById("update-latest").textContent === "2026.1103.1200", "最新版本号正确");
    ok(doc.getElementById("update-current").textContent === "2026.1029.1931", "当前版本号正确");
    ok(/诊断包/.test(doc.getElementById("update-notes").textContent), "更新说明填进弹窗");
    ok(/20\.0 MB/.test(doc.getElementById("update-size").textContent), "资产体积换算成 MB");
    ok(doc.getElementById("update-download").disabled === false, "有下载地址时按钮可用");
    ok(/有新版本/.test(doc.getElementById("about-update-state").textContent),
      "关于页文字同步成「有新版本」");
  }

  console.log("\n[C] 不打扰：已是最新 / 开发版 / 失败都不弹窗");
  {
    const { doc, pending } = mkEnv();
    await waitFor(() => !doc.getElementById("about-update-check").disabled, 4000, "初始化完成");
    pending.push({ kind: "update", payload: { status: "latest", current: "2026.1029.1931",
                                              version: "2026.1029.1931", silenced: false } });
    await waitFor(() => /已是最新/.test(doc.getElementById("about-update-state").textContent),
                  4000, "已是最新");
    ok(doc.getElementById("update-modal").classList.contains("hidden"),
      "「已是最新」不弹窗");
    ok(/已是最新/.test(doc.getElementById("about-update-state").textContent),
      "关于页显示已是最新");
  }
  {
    const { doc, pending } = mkEnv();
    await waitFor(() => !doc.getElementById("about-update-check").disabled, 4000, "初始化完成");
    pending.push({ kind: "update", payload: { status: "ahead", current: "2026.1105.1200",
                                              version: "2026.1103.1200", silenced: false } });
    await waitFor(() => /开发版/.test(doc.getElementById("about-update-state").textContent),
                  4000, "开发版");
    ok(doc.getElementById("update-modal").classList.contains("hidden"),
      "本机版本更新（开发版）不弹窗");
  }
  {
    const { doc, pending } = mkEnv();
    await waitFor(() => !doc.getElementById("about-update-check").disabled, 4000, "初始化完成");
    pending.push({ kind: "update", payload: { status: "error", current: "2026.1029.1931",
                                              error: "检查更新失败：连不上 github.com（timed out）" } });
    await waitFor(() => doc.getElementById("about-update-state").classList.contains("err"),
                  4000, "错误态");
    ok(doc.getElementById("update-modal").classList.contains("hidden"),
      "自动检查失败不弹窗（用户没问，别把断网当成报错砸给他）");
    ok(/连不上/.test(doc.getElementById("about-update-state").textContent),
      "关于页给出可读的失败原因");
  }

  console.log("\n[D] 跳过此版本：自动检查不弹，但仍记录结果");
  {
    const { doc, pending } = mkEnv();
    await waitFor(() => !doc.getElementById("about-update-check").disabled, 4000, "初始化完成");
    pending.push({ kind: "update", payload: Object.assign({}, RES_UPDATE, { silenced: true }) });
    await waitFor(() => /有新版本/.test(doc.getElementById("about-update-state").textContent),
                  4000, "结果回填");
    ok(doc.getElementById("update-modal").classList.contains("hidden"),
      "silenced=true 时不弹窗（用户点过「跳过此版本」）");
  }

  console.log("\n[E] 动手：去下载 / 跳过 / 稍后");
  {
    const { doc, window, calls, pending } = mkEnv();
    await waitFor(() => !doc.getElementById("about-update-check").disabled, 4000, "初始化完成");
    pending.push({ kind: "update", payload: Object.assign({}, RES_UPDATE) });
    await waitFor(() => !doc.getElementById("update-modal").classList.contains("hidden"),
                  4000, "弹窗打开");
    click(window, doc.getElementById("update-download"));
    const got = await waitFor(() => calls.some((c) => c.fn === "update_open"), 3000, "update_open");
    ok(got, "点「去下载」调用了后端 update_open");
    ok(calls.find((c) => c.fn === "update_open").args[0] === RES_UPDATE.url,
      "把发布页地址原样交给后端（前端不自己拼 URL）");
    await waitFor(() => doc.getElementById("update-modal").classList.contains("hidden"),
                  3000, "弹窗关闭");
    ok(doc.getElementById("update-modal").classList.contains("hidden"), "点完下载关闭弹窗");
  }
  {
    const { doc, window, calls, pending } = mkEnv();
    await waitFor(() => !doc.getElementById("about-update-check").disabled, 4000, "初始化完成");
    pending.push({ kind: "update", payload: Object.assign({}, RES_UPDATE) });
    await waitFor(() => !doc.getElementById("update-modal").classList.contains("hidden"),
                  4000, "弹窗打开");
    click(window, doc.getElementById("update-skip"));
    await waitFor(() => calls.some((c) => c.fn === "update_skip"), 3000, "update_skip");
    const call = calls.find((c) => c.fn === "update_skip");
    ok(!!call, "点「跳过此版本」调用了 update_skip");
    ok(call.args[0] === "2026.1103.1200", "跳过的是弹窗里这个版本号");
    ok(doc.getElementById("update-modal").classList.contains("hidden"), "跳过之后关闭弹窗");
  }
  {
    const { doc, window, calls, pending } = mkEnv();
    await waitFor(() => !doc.getElementById("about-update-check").disabled, 4000, "初始化完成");
    pending.push({ kind: "update", payload: Object.assign({}, RES_UPDATE) });
    await waitFor(() => !doc.getElementById("update-modal").classList.contains("hidden"),
                  4000, "弹窗打开");
    click(window, doc.getElementById("update-later"));
    await sleep(150);
    ok(doc.getElementById("update-modal").classList.contains("hidden"), "点「稍后」关闭弹窗");
    ok(!calls.some((c) => c.fn === "update_skip"),
      "「稍后」不记版本（下次启动仍会提醒，那是真该提醒的）");
  }

  console.log("\n[F] 检查按钮：禁用态由 update_state 驱动，最终必须复位");
  {
    const { doc, window, calls, pending } = mkEnv();
    await waitFor(() => !doc.getElementById("about-update-check").disabled, 4000, "初始化完成");
    click(window, doc.getElementById("about-update-check"));
    const got = await waitFor(() => calls.some((c) => c.fn === "update_check"), 3000, "update_check");
    ok(got, "点「检查」调用 update_check");
    ok(calls.find((c) => c.fn === "update_check").args[0] === true,
      "手动检查传 force=true（要绕过 12 小时节流）");
    ok(/检查中/.test(doc.getElementById("about-update-check").textContent),
      "立刻进入「检查中…」（不等后端返回）");
    ok(doc.getElementById("about-update-check").disabled, "检查中按钮禁用");

    pending.push({ kind: "update_state", payload: { running: false } });
    const reset = await waitFor(() => !doc.getElementById("about-update-check").disabled,
                                4000, "按钮复位");
    ok(reset, "update_state(false) 后按钮恢复可用（漏了这步按钮会永久卡住）");
    ok(doc.getElementById("about-update-check").textContent === "检查", "按钮文案复位成「检查」");
  }

  console.log("\n[G] 自动检查开关：改动即落盘");
  {
    const { doc, window, calls } = mkEnv();
    await waitFor(() => !doc.getElementById("about-update-check").disabled, 4000, "初始化完成");
    const box = doc.getElementById("about-update-auto");
    box.checked = false;
    change(window, box);
    const got = await waitFor(
      () => calls.some((c) => c.fn === "save_settings" && c.args[0].update_check === false),
      3000, "落盘 update_check");
    ok(got, "关掉自动检查立刻写进 config.json（update_check=false）");
  }

  console.log("\n[H] 启动回填：上次检查结果来自 update_info");
  {
    const { doc } = mkEnv({ info: { last: { status: "update", current: "2026.1029.1931",
                                            version: "2026.1103.1200" } } });
    const back = await waitFor(
      () => /有新版本/.test(doc.getElementById("about-update-state").textContent),
      4000, "回填上次结果");
    ok(back, "启动时把上次检查结果回填到关于页");
    ok(doc.getElementById("update-modal").classList.contains("hidden"),
      "回填不弹窗（弹窗只由事件触发，避免一开程序就弹旧结果）");
  }
  {
    const { doc } = mkEnv({ info: { enabled: false } });
    await waitFor(() => doc.getElementById("about-update-auto").checked === false,
                  4000, "回填开关");
    ok(doc.getElementById("about-update-auto").checked === false,
      "config.json 里关掉过 → 复选框回填为未勾选");
  }

  clearTimeout(watchdog);
  console.log("\n结果： " + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})().catch((e) => {
  console.log("    (异常: " + (e && e.stack || e) + ")");
  process.exit(1);
});
