/* jsdom 前端行为测试：性能监控页「设置」——需要监测/显示的指标可自行勾选。

   回归点：
   1) 默认值：无配置时七项全监测、卡片全可见，弹窗七个勾选框全勾；
   2) 取消电量/温度并保存：对应卡片隐藏、save_settings 落盘 perf_metrics、
      弹窗关闭；点击「开始监控」时 perf_start 第 4 参只带启用项（后端据此
      真正裁剪设备端 adb 命令，而不只是隐藏卡片）；
   3) 启动恢复：settings.perf_metrics 为合法子集时只显示对应卡片；
   4) 防呆：全取消给错误提示且不落盘；非法/空配置回退全部；收藏的曲线指标
      被关掉时自动切到剩余第一项；「恢复默认」只改界面、不落盘。 */
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
    await sleep(20);
  }
  console.log("    (waitFor 超时: " + label + ")");
  return false;
}

let lastDom = null;
function mkEnv(settings) {
  // 上一实例里的事件/轮询定时器会继续跑，多实例叠加会把事件循环拖死；
  // jsdom 的 window.close() 会一并清掉它们。
  if (lastDom) { try { lastDom.window.close(); } catch (e) { /* 已关 */ } }
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const calls = [];
  let round = 0;
  // jsdom 无 canvas 实现，桩一个空上下文，避免绘图分支抛错
  window.HTMLCanvasElement.prototype.getContext = function () {
    return { setTransform() {}, clearRect() {}, beginPath() {}, closePath() {},
      moveTo() {}, lineTo() {}, arc() {}, rect() {}, roundRect() {}, fillRect() {},
      save() {}, restore() {}, stroke() {}, fill() {}, fillText() {},
      measureText() { return { width: 24 }; },
      createLinearGradient() { return { addColorStop() {} }; } };
  };
  Object.defineProperty(window.HTMLElement.prototype, "clientWidth",
    { configurable: true, get() { return 820; } });
  Object.defineProperty(window.HTMLElement.prototype, "clientHeight",
    { configurable: true, get() { return 320; } });
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          calls.push({ fn: String(k), args });
          if (k === "boot") {
            return Promise.resolve({ version: "v-test", warnings: [], commands: [],
                                     adb: "adb", settings: settings || {} });
          }
          if (k === "take_events") {
            const b = (round++ === 0) ? [
              { kind: "booted", payload: { version: "v-test", warnings: [], commands: [],
                                           settings: settings || {} } },
              { kind: "devices", payload: { items: [
                { serial: "S1", model: "Pixel 7", state: "device", ok: true, checked: true }] } },
            ] : [];
            return Promise.resolve(b);
          }
          if (k === "perf_start") {
            return Promise.resolve({ ok: true, serial: "S1", info: {
              serial: "S1", model: "Pixel 7", pkg: "com.foo" } });
          }
          if (k === "perf_poll") {
            return Promise.resolve({ running: true, seq: 0, samples: [], info: {} });
          }
          if (k === "perf_stop") return Promise.resolve({ ok: true, samples: 0 });
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  lastDom = dom;
  return { window, calls, doc: window.document };
}

const ALL = ["cpu", "mem_used", "pss", "fps", "jank", "batt", "temp"];
function click(doc, id) {
  doc.getElementById(id).dispatchEvent(new doc.defaultView.Event("click", { bubbles: true }));
}
function shownCards(doc) {
  return ALL.filter((k) => {
    const el = doc.getElementById("perf-stat-" + k);
    return el && !el.hidden;
  });
}
function boxes(doc) {
  return Array.from(doc.querySelectorAll("#perf-metrics-rows .pm-on"));
}
function checkedBoxes(doc) {
  return boxes(doc).filter((b) => b.checked).map((b) => b.dataset.metric);
}
function savedPatch(calls, key) {
  const hit = calls.filter((c) => c.fn === "save_settings" && c.args[0] && key in c.args[0]);
  return hit.length ? hit[hit.length - 1].args[0][key] : undefined;
}
const callsOf = (calls, fn) => calls.filter((c) => c.fn === fn);

// jsdom 实例里的轮询定时器会在进程后台继续跑，多实例串联时可能拖住退出；
// 看门狗保证测试进程一定结束（正常结束时会清掉）。
let watchdog = setTimeout(() => {
  console.log("\n结果：" + pass + " 通过 / " + fail + " 失败（看门狗超时）");
  process.exit(fail ? 1 : 0);
}, 25000);

(async () => {
  console.log("\n[1] 默认值：七项全监测，弹窗七个勾选框全勾");
  {
    const { window, doc } = mkEnv({});
    await waitFor(() => doc.getElementById("perf-metrics-btn"), 4000, "按钮就绪");
    ok(shownCards(doc).length === 7, "无配置时七张指标卡全可见（实际：" + shownCards(doc).join(",") + "）");
    click(doc, "perf-metrics-btn");
    ok(!doc.getElementById("perf-metrics-modal").classList.contains("hidden"), "点「设置」弹出监测项弹窗");
    ok(boxes(doc).length === 7 && checkedBoxes(doc).length === 7, "弹窗七项且全勾");
    click(doc, "perf-metrics-cancel");
  }

  console.log("\n[2] 取消电量/温度并保存：卡片隐藏 + 落盘 + perf_start 只带启用项");
  {
    const { window, calls, doc } = mkEnv({});
    // 等设备事件处理完（start 按钮解锁）再改设置：否则随后到达的 booted 会把
    // 刚保存的 perfEnabled 用空配置重置回全部。
    await waitFor(() => doc.getElementById("perf-start").disabled === false, 4000, "设备就绪");
    click(doc, "perf-metrics-btn");
    boxes(doc).filter((b) => b.dataset.metric === "batt" || b.dataset.metric === "temp")
      .forEach((b) => { b.checked = false; b.dispatchEvent(new window.Event("change", { bubbles: true })); });
    ok(checkedBoxes(doc).length === 5, "界面上取消勾选后剩五项");
    click(doc, "perf-metrics-save");
    ok(doc.getElementById("perf-metrics-modal").classList.contains("hidden"), "保存后弹窗关闭");
    ok(shownCards(doc).join(",") === "cpu,mem_used,pss,fps,jank",
       "电量/温度卡片即时隐藏（实际：" + shownCards(doc).join(",") + "）");
    ok(JSON.stringify(savedPatch(calls, "perf_metrics")) ===
       JSON.stringify(["cpu", "mem_used", "pss", "fps", "jank"]),
       "perf_metrics 落盘且不含 batt/temp（实际：" + JSON.stringify(savedPatch(calls, "perf_metrics")) + "）");
    // 点开始监控，检查第 4 个参数
    await waitFor(() => doc.getElementById("perf-start").disabled === false, 4000, "设备就绪");
    click(doc, "perf-start");
    await waitFor(() => callsOf(calls, "perf_start").length === 1, 4000, "perf_start");
    const args = callsOf(calls, "perf_start")[0].args;
    ok(args.length >= 4 && JSON.stringify(args[3]) ===
       JSON.stringify(["cpu", "mem_used", "pss", "fps", "jank"]),
       "perf_start 第 4 参只传启用项（实际：" + JSON.stringify(args[3]) + "）");
    click(doc, "perf-stop");
  }

  console.log("\n[3] 启动恢复：配置里只有 cpu/fps 时只显示两张卡");
  {
    const { doc } = mkEnv({ perf_metrics: ["cpu", "fps"] });
    await waitFor(() => shownCards(doc).length === 2, 4000, "恢复两张卡");
    ok(shownCards(doc).join(",") === "cpu,fps", "启动时按 perf_metrics 恢复可见卡片");
    click(doc, "perf-metrics-btn");
    ok(checkedBoxes(doc).join(",") === "cpu,fps", "弹窗按恢复的配置勾选");
  }

  console.log("\n[4] 防呆：全取消不落盘；收藏指标被关掉自动切；非法配置回退全部");
  {
    const { window, calls, doc } = mkEnv({});
    await waitFor(() => doc.getElementById("perf-metrics-btn"), 4000, "按钮就绪");
    click(doc, "perf-metrics-btn");
    boxes(doc).forEach((b) => { b.checked = false; b.dispatchEvent(new window.Event("change", { bubbles: true })); });
    click(doc, "perf-metrics-save");
    ok(!doc.getElementById("perf-metrics-err").hidden &&
       doc.getElementById("perf-metrics-err").textContent.includes("至少保留一项"),
       "全部取消时提示「至少保留一项」");
    ok(!doc.getElementById("perf-metrics-modal").classList.contains("hidden"), "全取消时弹窗不关闭");
    ok(savedPatch(calls, "perf_metrics") === undefined, "全取消不落盘");
    // 恢复默认只改界面
    click(doc, "perf-metrics-reset");
    ok(checkedBoxes(doc).length === 7, "「恢复默认」让界面重新全勾");
    ok(savedPatch(calls, "perf_metrics") === undefined, "「恢复默认」本身不落盘");
  }
  {
    // 收藏的曲线是 batt，但启用项里没有它 -> 自动切到 cpu
    const { doc } = mkEnv({ perf_metrics: ["cpu", "fps"], perf_metric: "batt" });
    await waitFor(() => shownCards(doc).length === 2, 4000, "恢复两张卡");
    const on = doc.querySelector("#perf-stats .perf-stat.on");
    ok(on && on.dataset.metric === "cpu", "被关掉的收藏指标自动切到 cpu（实际：" + (on && on.dataset.metric) + "）");
    ok(doc.getElementById("perf-chart-title").textContent.includes("CPU"), "图表标题同步为 CPU");
  }
  {
    const { doc } = mkEnv({ perf_metrics: ["bogus", ""] });
    await waitFor(() => shownCards(doc).length === 7, 4000, "非法配置回退全部");
    ok(shownCards(doc).length === 7, "非法配置回退为全部七项");
  }
  {
    // json 字符串写法（手改配置）同样认
    const { doc } = mkEnv({ perf_metrics: JSON.stringify(["cpu", "temp"]) });
    await waitFor(() => shownCards(doc).length === 2, 4000, "字符串配置恢复");
    ok(shownCards(doc).join(",") === "cpu,temp", "JSON 字符串形式的配置同样生效");
  }

  // CSS 必须显式压过 [hidden] 的 UA 样式（.perf-stat 是 flex）
  ok(/\.perf-stat\[hidden\]\s*\{\s*display:\s*none/.test(
       fs.readFileSync(path.join(ROOT, "frontend/css/app.css"), "utf8")),
     "CSS 显式隐藏未监测的指标卡");

  clearTimeout(watchdog);
  console.log("\n结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
