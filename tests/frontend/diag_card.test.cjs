/* jsdom 前端测试：工具页「诊断包」卡片
 *
 * 这是一个「出事之后立刻要用」的入口，锁四件事：
 *   1) 结构：卡片在工具页里，按钮 / 复选框 / 行数下拉都在，默认值与后端 schema 对齐；
 *   2) 门禁：没有受控设备时按钮禁用，有设备才可点（与截图 / 安装同一套 syncToolButtons）；
 *   3) 下发：点一下就把「是否含 logcat + 行数」传给后端，并立刻进入「正在收集」态；
 *   4) 收尾：后端 diag_state(running) 驱动按钮恢复；产物经 tool 事件把文件名写回卡片，
 *      失败（没有任何产物）时卡片回到「未收集」。
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

function mkEnv(opts) {
  opts = opts || {};
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const calls = [];
  const pending = [
    { kind: "booted", payload: { version: "v-test", warnings: [], adb: "adb",
                                 commands: [], settings: opts.settings || {} } },
    { kind: "devices", payload: { items: opts.devices || DEVICES } },
  ];
  let diagResult = opts.diagResult || { ok: true, devices: ["A1"] };
  const impl = {
    boot: () => Promise.resolve({ version: "v-test", warnings: [], adb: "adb",
                                  commands: [], settings: opts.settings || {} }),
    take_events: () => Promise.resolve(pending.splice(0)),
    default_save_dir: () => Promise.resolve({ dir: "" }),
    save_settings: (patch) => {
      calls.push({ fn: "save_settings", args: [patch] });
      return Promise.resolve({ ok: true });
    },
    diag_collect: (serial, withLogcat, lines) => {
      calls.push({ fn: "diag_collect", args: [serial, withLogcat, lines] });
      return Promise.resolve(diagResult);
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
  console.log("[A] 结构：卡片与控件都在");
  {
    const { doc } = mkEnv();
    ok(!!doc.getElementById("diag-card"), "工具页有诊断包卡片");
    ok(!!doc.getElementById("diag-collect"), "有「收集诊断包」按钮");
    ok(!!doc.getElementById("diag-logcat"), "有「含 logcat 尾部」复选框");
    ok(!!doc.getElementById("diag-lines"), "有行数下拉");
    const opt = doc.querySelectorAll("#diag-lines option");
    ok(opt.length >= 4, "行数下拉有多个档位");
    ok(doc.getElementById("diag-logcat").checked, "「含 logcat」默认勾选（与后端默认一致）");
    const sel = doc.getElementById("diag-lines");
    ok(sel.value === "2000", "行数默认 2000（与 core.prefs 的 diag_logcat_lines 一致）");
  }

  console.log("\n[B] 门禁：没有受控设备时不能点");
  {
    const { doc } = mkEnv({ devices: [] });
    doc.querySelector('.tab-btn[data-tab="tools"]').click();
    await sleep(120);
    ok(doc.getElementById("diag-collect").disabled,
      "无设备时「收集诊断包」禁用（后端也会拒绝，前端不该让用户白点）");
  }

  console.log("\n[C] 下发：点一下就把选项传给后端");
  {
    const { doc, window, calls } = mkEnv();
    doc.querySelector('.tab-btn[data-tab="tools"]').click();
    await waitFor(() => !doc.getElementById("diag-collect").disabled, 4000, "按钮可用");
    ok(!doc.getElementById("diag-collect").disabled, "有受控设备时按钮可用");

    // 改行数 + 关掉 logcat，确认落盘与下发都跟着走
    const sel = doc.getElementById("diag-lines");
    sel.value = "5000";
    change(window, sel);
    ok(calls.some((c) => c.fn === "save_settings"
      && c.args[0].diag_logcat_lines === 5000), "行数改动即时落盘");

    click(window, doc.getElementById("diag-collect"));
    const got = await waitFor(() => calls.some((c) => c.fn === "diag_collect"),
                              4000, "diag_collect 调用");
    ok(got, "点击后调用了后端 diag_collect");
    const call = calls.find((c) => c.fn === "diag_collect");
    ok(call.args[0] === null, "未指定设备时传 null（= 对全部受控设备收集）");
    ok(call.args[1] === true, "把「含 logcat」开关传下去");
    ok(call.args[2] === 5000, "把行数传下去");
    ok(/正在收集/.test(doc.getElementById("diag-result").textContent),
      "点击后立刻显示「正在收集…」（不等后端事件，秒级耗时里给即时反馈）");
  }

  console.log("\n[D] 收尾：diag_state 恢复按钮，tool 事件把文件名写回卡片");
  {
    const { doc, window, pending } = mkEnv();
    doc.querySelector('.tab-btn[data-tab="tools"]').click();
    await waitFor(() => !doc.getElementById("diag-collect").disabled, 4000, "按钮可用");
    click(window, doc.getElementById("diag-collect"));
    await waitFor(() => /正在收集/.test(doc.getElementById("diag-result").textContent),
                  3000, "收集态");

    pending.push({ kind: "tool", payload: { type: "diag", serial: "A1",
      path: "D:\\shots\\diag_A1_20261029_190000.zip" } });
    pending.push({ kind: "diag_state", payload: { running: false } });
    const done = await waitFor(
      () => !doc.getElementById("diag-collect").disabled, 5000, "按钮恢复");
    ok(done, "收到 diag_state(running=false) 后按钮恢复可点");
    const txt = doc.getElementById("diag-result").textContent;
    ok(/diag_A1_20261029_190000\.zip/.test(txt), "卡片上显示产出的文件名");
    ok(doc.getElementById("diag-result").title.indexOf("D:\\shots") === 0,
      "title 里保留完整路径（鼠标悬停可见）");
  }

  console.log("\n[E] 失败：没有任何产物时卡片复位为「未收集」");
  {
    const { doc, window, pending } = mkEnv({ diagResult: { ok: false, reason: "busy" } });
    doc.querySelector('.tab-btn[data-tab="tools"]').click();
    await waitFor(() => !doc.getElementById("diag-collect").disabled, 4000, "按钮可用");
    click(window, doc.getElementById("diag-collect"));
    await sleep(80);
    pending.push({ kind: "diag_state", payload: { running: false } });
    const reset = await waitFor(
      () => doc.getElementById("diag-result").textContent === "未收集",
      5000, "复位");
    ok(reset, "后端拒绝后卡片回到「未收集」，不会一直卡在「正在收集」");
    ok(!doc.getElementById("diag-collect").disabled, "按钮也恢复可点（可以重试）");
  }

  console.log("\n[F] 设置回填：boot 下发的 diag_* 生效");
  {
    const { doc } = mkEnv({ settings: { diag_with_logcat: false, diag_logcat_lines: 50000 } });
    const yes = await waitFor(() => doc.getElementById("diag-lines").value === "50000",
                              4000, "行数回填");
    ok(yes, "行数按 config.json 回填");
    ok(!doc.getElementById("diag-logcat").checked, "「含 logcat」按 config.json 回填为不勾");
    ok(doc.getElementById("diag-lines").disabled,
      "不勾 logcat 时行数下拉置灰（灰掉而不是隐藏，避免按钮左右跳）");
  }

  clearTimeout(watchdog);
  console.log("\n" + "=".repeat(46));
  console.log("diag_card: " + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
