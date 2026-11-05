/* jsdom 前端测试：主 tab（设备指令 / 工具 / 性能监控 / Logcat / 文件 / 关于）记住上次停留项
 *
 * 锁五件事：
 *   [0] 默认停在「设备指令」（HTML 里的 active），6 个页签齐全；
 *   [1] 按 settings.main_active_tab 恢复上次那一页（页签 active 与面板 active 同步）；
 *   [2] 点击切页落盘 main_active_tab；重复点当前页不写盘（省一次读-合并-写）；
 *   [3] 配置里是失效 key（版本删了某项 / 手改坏）→ 回退第一项，且不写盘；
 *   [4] 恢复走 persist:false → 启动不写盘；切到「性能监控」时目标设备条会被渲染
 *       （canvas 隐藏时尺寸为 0，切回来必须重画，这条同时防「曲线一片空白」回归）。
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

// 当前激活的主 tab key（页签与面板必须一致，否则会出现「页签亮着、内容却是另一页」）
const activeKey = (doc) => {
  const pane = doc.querySelector("section.tab.active");
  return pane ? pane.dataset.tab : null;
};
const activeBtns = (doc) =>
  Array.from(doc.querySelectorAll(".tab-btn.active")).map((b) => b.dataset.tab);
const savedTab = (calls) => {
  const hit = calls.filter((c) => c.fn === "save_settings" && c.args[0] &&
    "main_active_tab" in c.args[0]);
  return hit.length ? hit[hit.length - 1].args[0].main_active_tab : undefined;
};

const watchdog = setTimeout(() => {
  console.log("    (看门狗触发：疑似断言抛错导致未收尾)");
  process.exit(fail ? 1 : 0);
}, 90000);

(async () => {
  console.log("[0] 默认停在「设备指令」，六个页签齐全");
  {
    const { doc } = mkEnv();
    const btns = Array.from(doc.querySelectorAll("#tabs .tab-btn"));
    ok(btns.length === 6, "顶栏 6 个页签（实际 " + btns.length + "）");
    ok(btns[0].dataset.tab === "cmd" && btns[0].classList.contains("active"),
      "第一个页签是设备指令且默认激活");
    ok(activeKey(doc) === "cmd", "默认显示设备指令页");
    ok(doc.querySelectorAll("#tool-panes .tool-pane").length === 5, "工具页五个子 tab 面板都在（顺带确认页内结构未被改坏）");
  }

  console.log("\n[1] 按 main_active_tab 恢复上次停留页");
  {
    const { doc } = mkEnv({ settings: { main_active_tab: "logcat" } });
    ok(await waitFor(() => activeKey(doc) === "logcat", 4000, "恢复到 logcat"),
      "重启回到上次的 Logcat 页（实际 " + activeKey(doc) + "）");
    ok(activeBtns(doc).join(",") === "logcat",
      "只有一个页签 active，且就是 Logcat（实际 " + activeBtns(doc).join(",") + "）");
    ok(!doc.querySelector('section.tab[data-tab="cmd"]').classList.contains("active"),
      "设备指令页已隐藏");
  }
  {
    const { doc } = mkEnv({ settings: { main_active_tab: "tools" } });
    ok(await waitFor(() => activeKey(doc) === "tools", 4000, "恢复到工具页"),
      "也能恢复到工具页");
  }

  console.log("\n[2] 点击切页落盘；重复点当前页不写盘");
  {
    const { doc, calls } = mkEnv();
    await waitFor(() => !!doc.querySelector('.tab-btn[data-tab="files"]'), 3000, "页签就绪");
    doc.querySelector('.tab-btn[data-tab="files"]').click();
    await sleep(60);
    ok(activeKey(doc) === "files", "点「文件」→ 文件页显示");
    ok(savedTab(calls) === "files", "落盘 main_active_tab=files（实际 " + savedTab(calls) + "）");

    const before = calls.filter((c) => c.fn === "save_settings" &&
      c.args[0] && "main_active_tab" in c.args[0]).length;
    doc.querySelector('.tab-btn[data-tab="files"]').click();
    await sleep(60);
    const after = calls.filter((c) => c.fn === "save_settings" &&
      c.args[0] && "main_active_tab" in c.args[0]).length;
    ok(after === before, "重复点同一页不再写盘（" + before + " → " + after + "）");
  }

  console.log("\n[3] 失效 key 回退第一项，且不写盘");
  {
    const { doc, calls } = mkEnv({ settings: { main_active_tab: "no-such-tab" } });
    await waitFor(() => activeKey(doc) === "cmd", 3000, "回退 cmd");
    await sleep(80);
    ok(activeKey(doc) === "cmd", "失效 key 回退设备指令页（不留在空白页）");
    ok(savedTab(calls) === undefined, "回退不写盘（不把兜底值当成用户选择）");
  }

  console.log("\n[4] 启动恢复不写盘；切到性能页会渲染目标设备条");
  {
    const { doc, calls } = mkEnv({ settings: { main_active_tab: "logcat" } });
    await waitFor(() => activeKey(doc) === "logcat", 4000, "恢复到 logcat");
    await sleep(120);
    ok(savedTab(calls) === undefined, "恢复回填走 persist:false，启动不写盘");

    doc.querySelector('.tab-btn[data-tab="perf"]').click();
    await sleep(120);
    ok(activeKey(doc) === "perf", "切到性能监控页");
    ok(!doc.getElementById("perf-dev").classList.contains("off"),
      "性能页目标设备条已按勾选设备渲染（隐藏期间 canvas 尺寸为 0，切回必须重画）");
  }

  clearTimeout(watchdog);
  console.log("\n结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
