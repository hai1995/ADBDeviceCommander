/* jsdom 前端行为测试：设备栏折叠态铭牌随勾选联动
   回归背景：窄轨折叠后底部铭牌恒显「N / 已连接设备」，但收起后所有操作都
   作用于受控（勾选）设备，「选中几台」反而看不到；一台没选时若还显示
   「已连接设备」会让用户误以为有操作目标（用户实报）。现约定：
     折叠 + 有勾选  →  徽章=勾选数，竖排文字「已选中设备」；
     折叠 + 无勾选  →  徽章清空，竖排文字红色警示「未选中任何设备」（挂
                       .warn 类：告警红 + 呼吸动画，CSS 呈现）；
     展开态        →  恒为「N 台 + 已连接设备」，不受勾选影响。 */
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

const dev = (serial, checked) => ({
  serial, model: "M-" + serial, state: checked || "device",
  ok: true, checked: !!checked,
});

async function boot() {
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
  const { window } = dom;
  const calls = [];
  let round = 0;
  // 批次队列：boot 后每轮轮询取一批；测试中途 push 新批次即可模拟后端
  // 广播（toggle_device 之后 devices 事件就是这么回来的）。
  const batches = [
    [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [], adb: "adb" } },
     { kind: "devices", payload: { items: [dev("A1", true), dev("B2", false)] } }],
  ];
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          calls.push({ fn: k, args });
          if (k === "boot") return Promise.resolve({ version: "v-test", warnings: [], commands: [], adb: "adb" });
          if (k === "take_events") { const b = batches[round] || []; round++; return Promise.resolve(b); }
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  return { window, batches };
}

(async () => {
  const { window, batches } = await boot();
  const doc = window.document;
  const badge = () => doc.getElementById("dev-count").textContent;
  const label = () => doc.querySelector(".sidebar-title-text").textContent;
  const labelEl = () => doc.querySelector(".sidebar-title-text");
  const unitHidden = () => doc.getElementById("dev-count-unit").hidden;
  const collapsed = () => doc.querySelector(".main-row").classList.contains("sidebar-collapsed");

  ok(await waitFor(() => doc.querySelectorAll("#device-list .device-card").length === 2, 4000, "设备卡片"),
     "两台设备卡片已渲染");
  await sleep(120);

  console.log("\n[1] 展开态：铭牌恒为「已连接 N 台」，不受勾选影响");
  ok(!collapsed(), "初始为展开态");
  ok(badge() === "2", "徽章显示连接数 2（实际 " + badge() + "）");
  ok(label() === "已连接设备", "文字为「已连接设备」");
  ok(unitHidden() === false, "「台」单位可见");

  console.log("\n[2] 折叠 + 已勾选 1 台：铭牌切换为「已选中 N」");
  doc.getElementById("btn-sidebar-collapse").click();
  await sleep(80);
  ok(collapsed(), "进入折叠态");
  ok(badge() === "1", "徽章改为勾选数 1（实际 " + badge() + "）");
  ok(label() === "已选中设备", "文字为「已选中设备」");

  console.log("\n[3] 折叠 + 全部取消勾选：红色警示「未选中任何设备」");
  batches.push([{ kind: "devices", payload: { items: [dev("A1", false), dev("B2", false)] } }]);
  ok(await waitFor(() => badge() === "" && label() === "未选中任何设备", 4000, "警示铭牌"),
     "无勾选时铭牌改为「未选中任何设备」且徽章清空（实际 " + badge() + " / " + label() + "）");
  ok(labelEl().classList.contains("warn"), "竖排文字挂 .warn 类（红色警示，CSS 呈现）");
  ok(unitHidden(), "「台」单位一并隐藏");

  console.log("\n[4] 折叠 + 重新勾选两台：徽章跟随为 2，警示撤销");
  batches.push([{ kind: "devices", payload: { items: [dev("A1", true), dev("B2", true)] } }]);
  ok(await waitFor(() => badge() === "2" && label() === "已选中设备", 4000, "勾选数联动"),
     "两台全勾选时徽章 2 /「已选中设备」（实际 " + badge() + " / " + label() + "）");
  ok(!labelEl().classList.contains("warn"), "有勾选后 .warn 类移除");

  console.log("\n[5] 重新展开：铭牌恢复「已连接 N 台」，警示样式撤干净");
  doc.getElementById("btn-sidebar-collapse").click();
  await sleep(80);
  ok(!collapsed(), "回到展开态");
  ok(badge() === "2", "徽章恢复连接数 2（实际 " + badge() + "）");
  ok(label() === "已连接设备", "文字恢复「已连接设备」");
  ok(!labelEl().classList.contains("warn"), "展开态不挂 .warn 类");
  ok(unitHidden() === false, "「台」单位恢复可见");

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
