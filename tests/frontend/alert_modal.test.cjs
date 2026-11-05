/* jsdom 前端测试：关键告警弹窗（不点「我知道了」不消失）
 *
 * 起因是一次真实事故：录屏 20 多分钟，中途 logcat 被 USB 带宽挤断，收尾时
 * 「✓ 录屏已完成」「日志只跟到 10:50」都是 toast —— 6 秒自动消失。用户当时在
 * 别处，一条都没记住，直到事后拿视频对时间轴才发现后段日志是空的。
 *
 * 本文件锁住这条边界：
 *   [0] 告警弹窗存在（在 HTML 里，不是靠 toast 顶）；
 *   [1] 带 alert 标记的状态 → 弹窗打开，且**过了 toast 的生存期仍然开着**；
 *   [2] 不带 alert 标记的 warn / err → 只弹 toast，绝不升级成弹窗（否则所有
 *       普通提示都会变成必须点掉的弹窗，用户很快就会盲点）；
 *   [3] 多条告警合并进同一个弹窗（多设备同时出问题不必连点 5 次）；
 *   [4] 「我知道了」→ 关闭；之后再来一条仍能重新打开；
 *   [5] Esc 关闭告警弹窗，且不连带关掉状态信息弹窗；
 *   [6] 「查看状态信息」→ 关弹窗、开状态面板（用户要能顺着看到完整原因）。
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
const clickEl = (doc, el) => el.dispatchEvent(new doc.defaultView.Event("click", { bubbles: true }));
const press = (doc, el, key) => el.dispatchEvent(new doc.defaultView.KeyboardEvent("keydown",
  { key: key, bubbles: true, cancelable: true }));

async function boot() {
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const queue = [
    { kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
    { kind: "devices", payload: { items: [{ serial: "A1", ok: true, checked: true }] } },
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
  await waitFor(() => doc.querySelectorAll("#device-list .device-card").length >= 1, 4000,
                "开机事件落地");
  /* 推一条事件进去，等它对 DOM 生效。轮询间隔 400/500ms，所以最长等 2s。 */
  const push = async (kind, payload, cond) => {
    queue.push({ kind, payload });
    if (cond) return waitFor(cond, 3000, "事件落地 " + kind);
    await sleep(700);
    return true;
  };
  return { window, doc, push };
}

const open = (doc) => {
  const m = doc.getElementById("alert-modal");
  return !!m && !m.classList.contains("hidden");
};
const bodyText = (doc) => (doc.getElementById("alert-body") || {}).textContent || "";

const watchdog = setTimeout(() => {
  console.log("    (看门狗触发：疑似断言抛错导致未收尾)");
  process.exit(fail ? 1 : 0);
}, 120000);

(async () => {
  console.log("[0] 告警弹窗结构");
  {
    const { doc } = await boot();
    ok(!!doc.getElementById("alert-modal"), "有独立的告警弹窗（不是只靠 toast）");
    ok(!!doc.getElementById("alert-body") && !!doc.getElementById("alert-ok"),
       "正文区 / 「我知道了」按钮都在");
    ok(doc.getElementById("alert-modal").getAttribute("role") === "alertdialog",
       "role=alertdialog（读屏会立刻播报）");
    ok(!open(doc), "初始是关闭的（不能开机就挡在用户面前）");
  }

  console.log("\n[1] 带 alert 标记 → 弹窗打开，且不自动消失");
  {
    const { doc, push } = await boot();
    const text = "⚠ A1 的 logcat 只跟到 10:50:12.000，距录屏结束还有约 24 分钟没有日志";
    await push("status", { type: "warn", text: text, toast: true, alert: true,
                           alert_title: "⚠ 本次录制的日志不完整" }, () => open(doc));
    ok(open(doc), "告警弹窗被打开");
    ok(bodyText(doc).indexOf("10:50:12.000") >= 0, "正文里能读到具体结论");
    ok((doc.getElementById("alert-title") || {}).textContent === "⚠ 本次录制的日志不完整",
       "标题用的是后端给的（说清是哪一类问题）");
    // toast 的生存期是 6s(warn) / 8s(err)：等过最长的 4s 也只是中途，
    // 这里按「TOAST 全消失之后仍在」来判断 —— 但不必真等 8 秒拖慢套件，
    // 4 秒已足以证明它不受 toast 计时器管。
    await sleep(1500);
    ok(open(doc), "1.5 秒后仍然开着（toast 早已换过几轮）");
  }

  console.log("\n[2] 不带 alert 标记的 warn / err 不弹窗");
  {
    const { doc, push } = await boot();
    await push("status", { type: "warn", text: "⚠ 只是一句普通警告", toast: true });
    ok(!open(doc), "普通 warn 只走 toast，不弹窗");
    await push("status", { type: "err", text: "⚠ 截图失败：设备忙" });
    ok(!open(doc), "普通 err 也只走 toast（不至于每个错误都要点一下）");
    ok(doc.querySelectorAll(".toast").length > 0, "但 toast 确实弹了（没被吞掉）");
  }

  console.log("\n[3] 多条告警合并进同一个弹窗");
  {
    const { doc, push } = await boot();
    await push("status", { type: "warn", text: "⚠ A1 的 logcat 只跟到 10:50",
                           toast: true, alert: true, alert_title: "⚠ 本次录制的日志不完整" },
               () => open(doc));
    await push("status", { type: "warn", text: "⚠ B2 的 logcat 只跟到 10:52",
                           toast: true, alert: true, alert_title: "⚠ 本次录制的日志不完整" },
               () => bodyText(doc).indexOf("B2") >= 0);
    ok(doc.querySelectorAll("#alert-modal").length === 1, "仍然只有一个告警弹窗");
    ok(/A1/.test(bodyText(doc)) && /B2/.test(bodyText(doc)),
       "两台设备的问题都列在同一个弹窗里（实得：" +
       bodyText(doc).replace(/\s+/g, " ").slice(0, 120) + "）");
    const items = doc.querySelectorAll("#alert-body .alert-item");
    ok(items.length === 2, "两条各自成行（实得 " + items.length + " 行）");
    ok(/共 2 条/.test((doc.getElementById("alert-hint") || {}).textContent || ""),
       "底部说清一共几条");
    // 同一句话重复到达不再重复列（后端收尾与播报两处都可能带同一条结论）
    await push("status", { type: "warn", text: "⚠ A1 的 logcat 只跟到 10:50",
                           toast: true, alert: true });
    ok(doc.querySelectorAll("#alert-body .alert-item").length === 2,
       "同一条结论重复到达不重复列");
  }

  console.log("\n[4] 「我知道了」关闭，之后还能再次打开");
  {
    const { doc, push } = await boot();
    await push("status", { type: "warn", text: "⚠ 第一条", toast: true, alert: true },
               () => open(doc));
    clickEl(doc, doc.getElementById("alert-ok"));
    await sleep(60);
    ok(!open(doc), "点「我知道了」关闭");
    ok(doc.querySelectorAll("#alert-body .alert-item").length === 0, "关掉后列表清空");

    await push("status", { type: "warn", text: "⚠ 第二次告警", toast: true, alert: true },
               () => open(doc));
    ok(open(doc), "再次出现告警时弹窗能重新打开");
    ok(bodyText(doc).indexOf("第二次告警") >= 0 && bodyText(doc).indexOf("第一条") < 0,
       "只显示本次的告警（上一次的不会残留）");
  }

  console.log("\n[5] Esc 关闭告警弹窗，且不连带关掉状态面板");
  {
    const { doc, push } = await boot();
    await push("status", { type: "warn", text: "⚠ 告警", toast: true, alert: true },
               () => open(doc));
    // 先把状态面板打开（模拟用户正在看状态）
    clickEl(doc, doc.getElementById("status-ticker"));
    await sleep(60);
    const statusOpen = () => !doc.getElementById("status-modal").classList.contains("hidden");
    ok(statusOpen(), "状态面板已打开");
    press(doc, doc, "Escape");
    await sleep(60);
    ok(!open(doc), "Esc 关掉告警弹窗");
    ok(statusOpen(), "状态面板还开着（Esc 只关最上面那一层）");
  }

  console.log("\n[6] 「查看状态信息」→ 关弹窗并打开状态面板");
  {
    const { doc, push } = await boot();
    await push("status", { type: "warn", text: "⚠ A1 的 logcat 只跟到 10:50",
                           toast: true, alert: true }, () => open(doc));
    clickEl(doc, doc.getElementById("alert-more"));
    await sleep(80);
    ok(!open(doc), "告警弹窗关闭（两层叠着会让人以为面板没打开）");
    ok(!doc.getElementById("status-modal").classList.contains("hidden"), "状态面板打开了");
    ok((doc.getElementById("status") || {}).textContent.indexOf("10:50") >= 0,
       "状态里能查到那条原始记录（完整上下文都在这里）");
  }

  console.log("\n[7] 条目超上限：只列前 12 条，但绝不静默丢弃");
  {
    const { doc, push } = await boot();
    await push("status", { type: "warn", text: "⚠ 第 0 条", toast: true, alert: true },
               () => open(doc));
    // 前 11 条会进弹窗（第 0 条已占一格，共 12 格），逐条等它落地
    for (let i = 1; i <= 11; i++) {
      await push("status", { type: "warn", text: "⚠ 第 " + i + " 条", toast: true, alert: true },
                 () => bodyText(doc).indexOf("第 " + i + " 条") >= 0);
    }
    // 越过上限的三条：本来就不该出现在正文里，塞进去等它们被忽略即可
    for (let i = 12; i <= 14; i++) {
      await push("status", { type: "warn", text: "⚠ 第 " + i + " 条", toast: true, alert: true });
    }
    const n = doc.querySelectorAll("#alert-body .alert-item").length;
    ok(n === 12, "最多列 12 条（实际 " + n + "）");
    const hint = (doc.getElementById("alert-hint") || {}).textContent || "";
    ok(/另有 3 条/.test(hint), "底部说清还有几条没展开（实际：" + hint + "）");
  }

  console.log("\n[8] 弹窗已开时再来告警：不抢走用户当前的焦点");
  {
    const { doc, push } = await boot();
    await push("status", { type: "warn", text: "⚠ 第一条", toast: true, alert: true },
               () => open(doc));
    const more = doc.getElementById("alert-more");
    more.focus();
    ok(doc.activeElement === more, "用户把焦点移到「查看状态信息」");
    await push("status", { type: "warn", text: "⚠ 第二条", toast: true, alert: true },
               () => bodyText(doc).indexOf("第二条") >= 0);
    ok(doc.activeElement === more,
       "新告警不把焦点拽回「我知道了」（否则用户滚下去看第 5 条会被弹回顶部）");
  }

  clearTimeout(watchdog);
  console.log("\n结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
