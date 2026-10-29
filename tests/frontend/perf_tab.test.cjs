/* jsdom 前端行为测试：性能监控页签（实时读数 + 曲线 + 报告导出）

   后端采样/解析/报告由 tests/test_backend_perf.py 与
   tests/test_backend_controller.py 锁定；这里只锁前端：
   页签与区块结构、按钮禁用逻辑、perf_start/poll/stop/export 的调用口径、
   指标卡读数与切换、采样间隔夹取与落盘、窗口/后端中断后的界面复位。

   jsdom 没有 canvas 实现（getContext 返回 null），也没有布局（clientWidth=0），
   故这里桩一个 2d 上下文 + 固定尺寸，只验证「确实画了」而不验证像素。 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.join(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "frontend/index.html"), "utf8");
const js = fs.readFileSync(path.join(ROOT, "frontend/js/app.js"), "utf8");
const css = fs.readFileSync(path.join(ROOT, "frontend/css/app.css"), "utf8");

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
  const ctx = {
    strokes: 0, fills: 0, texts: 0, transforms: 0, cleared: 0,
    setTransform() { ctx.transforms++; },
    clearRect() { ctx.cleared++; },
    beginPath() {}, closePath() {}, moveTo() {}, lineTo() {},
    arc() {}, rect() {}, roundRect() {}, fillRect() {}, save() {}, restore() {},
    stroke() { ctx.strokes++; }, fill() { ctx.fills++; },
    fillText() { ctx.texts++; },
    measureText() { return { width: 24 }; },
    createLinearGradient() { return { addColorStop() {} }; },
  };
  return ctx;
}

/** 假后端：perf_poll 按队列依次返回，队列空则返回「运行中、无新样本」。 */
function mkEnv(opts) {
  opts = opts || {};
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const calls = [];
  const ctx = fakeCtx();
  let round = 0;
  const pollQueue = (opts.polls || []).slice();
  const settings = opts.settings || {};
  const batches = [
    [{ kind: "booted",
       payload: { version: "v-test", warnings: [], adb: "adb", commands: [],
                  settings } },
     { kind: "devices",
       payload: { items: opts.noDevice ? [] :
                  [{ serial: "S1", model: "Pixel 7", state: "device", ok: true, checked: true }] } }],
  ];

  // canvas 桩：jsdom 无实现
  window.HTMLCanvasElement.prototype.getContext = function () { return ctx; };
  // 布局桩：jsdom 不做排版，clientWidth/Height 恒为 0，会让绘图提前 return
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
            return Promise.resolve({ version: "v-test", warnings: [], commands: [],
                                     adb: "adb", settings });
          }
          if (k === "take_events") {
            const b = batches[round] || []; round++; return Promise.resolve(b);
          }
          if (k === "perf_start") {
            return Promise.resolve(opts.startRes || {
              ok: true, serial: "S1", interval: 1.0,
              info: { serial: "S1", model: "Pixel 7", pkg: "com.foo",
                      android: "13", size: "1080x2340" },
            });
          }
          if (k === "perf_poll") {
            const next = pollQueue.shift();
            return Promise.resolve(next || { running: true, seq: 0, samples: [], info: {} });
          }
          if (k === "perf_stop") return Promise.resolve({ ok: true, samples: 3 });
          if (k === "perf_export") {
            return Promise.resolve(opts.exportRes || {
              ok: true, html: "/tmp/perf_S1.html", csv: "/tmp/perf_S1.csv",
              rows: 3, samples: 3,
            });
          }
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  return { window, calls, ctx };
}

const callsOf = (calls, fn) => calls.filter((c) => c.fn === fn);
const savedPatch = (calls, key) => {
  const hit = callsOf(calls, "save_settings").filter((c) => c.args[0] && key in c.args[0]);
  return hit.length ? hit[hit.length - 1].args[0][key] : undefined;
};
const click = (doc, id) => doc.getElementById(id).dispatchEvent(
  new doc.defaultView.Event("click", { bubbles: true }));
const cssBlock = (sel) => {
  const i = css.indexOf(sel);
  if (i < 0) return "";
  const j = css.indexOf("}", i);
  return css.slice(i, j + 1);
};

const SAMPLES = [
  { seq: 1, t: 1793200000, cpu: 21.5, mem_used: 4100.0, pss: 320.0,
    fps: 59.4, batt: 78, temp: 31.0 },
  { seq: 2, t: 1793200001, cpu: 34.0, mem_used: 4120.0, pss: 322.5,
    fps: 58.1, batt: 78, temp: 31.2 },
];

const WATCHDOG_MS = 30000;

(async () => {
  const watchdog = setTimeout(() => {
    console.log("    (看门狗触发：疑似断言抛错导致未收尾，按当前结果退出)");
    process.exit(fail ? 1 : 0);
  }, WATCHDOG_MS);

  console.log("\n[1] 页签与区块结构");
  {
    const { window } = mkEnv();
    const doc = window.document;
    ok(await waitFor(() => !!doc.getElementById("perf-start"), 3000, "页面就绪"),
       "性能监控页已渲染");
    ok(!!doc.querySelector('.tab-btn[data-tab="perf"]'), "顶栏存在「性能监控」页签");
    ok((doc.querySelectorAll(".tab-btn").length) === 6, "共 6 个页签");
    ok(!!doc.querySelector('section.tab[data-tab="perf"]'), "存在 perf 区块");
    ok(doc.querySelectorAll("#perf-stats .perf-stat").length === 7,
       "7 张指标卡（CPU / 内存 / PSS / 帧率 / 卡顿率 / 电量 / 温度）");
    ok(!!doc.querySelector('#perf-stats .perf-stat[data-metric="jank"]'),
       "卡顿率指标卡存在（可切出独立曲线）");
    ok(!!doc.getElementById("perf-canvas"), "存在曲线画布");
    ok(doc.getElementById("perf-empty").hidden === false, "无数据时显示占位说明");
    ok(doc.getElementById("perf-stop").disabled === true, "未开始时「停止」不可点");
    ok(doc.getElementById("perf-export").disabled === true, "无数据时「导出报告」不可点");
    window.close();
  }

  console.log("\n[2] 设备联动：无受控设备时不能开始");
  {
    const { window } = mkEnv({ noDevice: true });
    const doc = window.document;
    await waitFor(() => !!doc.getElementById("perf-dev"), 3000, "页面就绪");
    ok(doc.getElementById("perf-start").disabled === true, "无设备 → 「开始监控」禁用");
    ok(/未选设备/.test(doc.getElementById("perf-dev").textContent), "设备位显示「未选设备」");
    window.close();
  }
  {
    const { window } = mkEnv();
    const doc = window.document;
    await waitFor(() => doc.getElementById("perf-start").disabled === false, 3000, "设备就绪");
    ok(doc.getElementById("perf-start").disabled === false, "有受控设备 → 「开始监控」可点");
    ok(/S1/.test(doc.getElementById("perf-dev").textContent), "设备位显示当前目标设备");
    window.close();
  }

  console.log("\n[3] 开始监控：调用口径与按钮态");
  {
    const { window, calls } = mkEnv({ polls: [{ running: true, seq: 0, samples: [] }] });
    const doc = window.document;
    await waitFor(() => doc.getElementById("perf-start").disabled === false, 3000, "设备就绪");
    click(doc, "perf-start");
    ok(await waitFor(() => callsOf(calls, "perf_start").length === 1, 3000, "perf_start"),
       "点击后调用 perf_start");
    const a = callsOf(calls, "perf_start")[0].args;
    // 第一参传 null：由后端取「全部受控设备」，多台即自动进入对比模式
    ok(a[0] === null, "第一参为 null（由后端取全部受控设备）");
    ok(a[1] === 1000, "第二参为采样间隔（毫秒，取输入框值）");
    ok(a[2] === "", "包名留空 = 自动跟随前台应用");
    ok(await waitFor(() => /监控中/.test(doc.getElementById("perf-state").textContent),
                     3000, "状态文本"),
       "状态行显示「监控中」");
    ok(doc.getElementById("perf-stop").disabled === false, "开始时「停止」可点");
    ok(doc.getElementById("perf-start").disabled === true, "监控中「开始」禁用（避免重复开）");
    window.close();
  }

  console.log("\n[4] 轮询：读数、统计与曲线");
  {
    const { window, calls, ctx } = mkEnv({
      polls: [{ running: true, seq: 2, samples: SAMPLES },
              { running: true, seq: 2, samples: [] }],
    });
    const doc = window.document;
    await waitFor(() => doc.getElementById("perf-start").disabled === false, 3000, "设备就绪");
    click(doc, "perf-start");
    ok(await waitFor(() => doc.getElementById("perf-v-cpu").textContent !== "--",
                     4000, "CPU 读数"),
       "抽样到达后 CPU 卡显示最新值");
    ok(doc.getElementById("perf-v-cpu").textContent === "34",
       "取最新一条（34%，整数不显示小数点）");
    ok(/21\.5 ~ 34/.test(doc.getElementById("perf-s-cpu").textContent),
       "统计行显示采样区间（最小~最大，卡窄不会被截断）");
    ok(/均 27\.8/.test(doc.getElementById("perf-s-cpu").title || ""),
       "均值/峰值/谷值放在悬停提示里");
    ok(doc.getElementById("perf-v-fps").textContent === "58.1", "帧率卡取最新值");
    ok(doc.getElementById("perf-v-batt").textContent === "78", "电量卡取最新值");
    ok(doc.getElementById("perf-empty").hidden === true, "有数据后隐藏占位说明");
    ok(ctx.strokes > 0, "曲线确实被绘制（stroke 被调用）");
    ok(/LIVE · 2 点/.test(doc.getElementById("perf-chart-sub").textContent),
       "曲线标题右侧显示采样点数");
    ok(callsOf(calls, "perf_poll").length >= 1, "轮询调用了 perf_poll");
    window.close();
  }

  console.log("\n[5] 指标切换：点卡片换曲线并落盘");
  {
    const { window, calls } = mkEnv({
      polls: [{ running: true, seq: 2, samples: SAMPLES }],
    });
    const doc = window.document;
    await waitFor(() => doc.getElementById("perf-start").disabled === false, 3000, "设备就绪");
    ok(doc.getElementById("perf-stat-cpu").classList.contains("on"), "默认选中 CPU 卡");
    click(doc, "perf-stat-fps");
    ok(doc.getElementById("perf-stat-fps").classList.contains("on"), "点帧率卡后它变为选中态");
    ok(!doc.getElementById("perf-stat-cpu").classList.contains("on"), "CPU 卡取消选中");
    ok(doc.getElementById("perf-stat-fps").getAttribute("aria-pressed") === "true",
       "无障碍属性同步");
    ok(doc.getElementById("perf-chart-title").textContent === "帧率", "曲线标题随之切换");
    ok(savedPatch(calls, "perf_metric") === "fps", "指标选择落盘（perf_metric）");
    window.close();
  }

  console.log("\n[6] 导出报告：调用后台 + toast + 打开报告 + 按钮复位");
  {
    const { window, calls } = mkEnv({
      polls: [{ running: true, seq: 2, samples: SAMPLES }],
    });
    const doc = window.document;
    await waitFor(() => doc.getElementById("perf-start").disabled === false, 3000, "设备就绪");
    click(doc, "perf-start");
    ok(await waitFor(() => doc.getElementById("perf-export").disabled === false,
                     4000, "导出可点"),
       "有数据后「导出报告」可点");
    click(doc, "perf-export");
    ok(await waitFor(() => callsOf(calls, "perf_export").length === 1, 3000, "perf_export"),
       "点击后调用 perf_export");
    ok(await waitFor(() => !!doc.querySelector(".toast"), 3000, "toast"),
       "导出成功弹 toast");
    ok(callsOf(calls, "open_local_file").length === 1, "自动打开生成的 HTML 报告");
    ok(/报告：/.test(doc.getElementById("perf-state").textContent), "状态行给出报告路径");
    window.close();
  }
  {
    const { window, calls } = mkEnv({
      polls: [{ running: true, seq: 2, samples: SAMPLES }],
      exportRes: { ok: false, reason: "没有采样数据" },
    });
    const doc = window.document;
    await waitFor(() => doc.getElementById("perf-start").disabled === false, 3000, "设备就绪");
    click(doc, "perf-start");
    await waitFor(() => doc.getElementById("perf-export").disabled === false, 4000, "导出可点");
    click(doc, "perf-export");
    ok(await waitFor(() => /导出失败/.test(doc.getElementById("perf-state").textContent),
                     3000, "失败态"),
       "导出失败时状态行给出失败态");
    ok(callsOf(calls, "open_local_file").length === 0, "失败时不打开任何文件");
    window.close();
  }

  console.log("\n[7] 停止监控：按钮复位、数据保留");
  {
    const { window, calls } = mkEnv({
      polls: [{ running: true, seq: 2, samples: SAMPLES },
              { running: false, seq: 2, samples: [] }],
    });
    const doc = window.document;
    await waitFor(() => doc.getElementById("perf-start").disabled === false, 3000, "设备就绪");
    click(doc, "perf-start");
    await waitFor(() => doc.getElementById("perf-v-cpu").textContent === "34", 4000, "读数");
    click(doc, "perf-stop");
    ok(await waitFor(() => callsOf(calls, "perf_stop").length === 1, 3000, "perf_stop"),
       "点击后调用 perf_stop");
    ok(await waitFor(() => doc.getElementById("perf-stop").disabled === true, 3000, "停止禁用"),
       "停止后「停止」不可点");
    ok(doc.getElementById("perf-start").disabled === false, "停止后「开始」恢复可点");
    ok(/已停止/.test(doc.getElementById("perf-state").textContent), "状态行显示已停止");
    ok(doc.getElementById("perf-export").disabled === false, "停止后仍可导出刚才的数据");
    window.close();
  }

  console.log("\n[8] 后端中断（设备掉线）→ 界面复位并说明原因");
  {
    const { window } = mkEnv({
      polls: [{ running: true, seq: 2, samples: SAMPLES },
              { running: false, seq: 2, samples: [], error: "设备无响应：device offline" }],
    });
    const doc = window.document;
    await waitFor(() => doc.getElementById("perf-start").disabled === false, 3000, "设备就绪");
    click(doc, "perf-start");
    ok(await waitFor(() => /监控已中断/.test(doc.getElementById("perf-state").textContent),
                     5000, "中断提示"),
       "running=false 时状态行提示「监控已中断」");
    ok(/offline/.test(doc.getElementById("perf-state").title || ""),
       "中断原因写进 title（悬停可看）");
    ok(doc.getElementById("perf-start").disabled === false, "界面回到可重新开始的状态");
    window.close();
  }

  console.log("\n[9] 启动回填与参数落盘");
  {
    const { window, calls } = mkEnv({
      settings: { perf_pkg: "com.tencent.kuwo", perf_interval_ms: 2000,
                  perf_metric: "fps" },
    });
    const doc = window.document;
    ok(await waitFor(() => doc.getElementById("perf-pkg-label").textContent === "com.tencent.kuwo",
                     3000, "包名回填"),
       "包名从 config.json 回填到选择器按钮");
    ok(doc.getElementById("perf-interval").value === "2000", "采样间隔回填");
    ok(doc.getElementById("perf-stat-fps").classList.contains("on"),
       "上次选中的指标被恢复");
    ok(doc.getElementById("perf-chart-title").textContent === "帧率", "曲线标题跟着恢复");

    // 间隔夹取：填 5 取下限 200，填 99999 取上限 10000
    const inp = doc.getElementById("perf-interval");
    inp.value = "5";
    inp.dispatchEvent(new window.Event("change", { bubbles: true }));
    ok(await waitFor(() => savedPatch(calls, "perf_interval_ms") === 200, 3000, "夹取下限"),
       "填 5ms → 夹到下限 200ms 并落盘");
    ok(inp.value === "200", "输入框同步显示夹取后的值");
    inp.value = "99999";
    inp.dispatchEvent(new window.Event("change", { bubbles: true }));
    ok(await waitFor(() => savedPatch(calls, "perf_interval_ms") === 10000, 3000, "夹取上限"),
       "填 99999ms → 夹到上限 10000ms");

    // 选择器不是输入框了：手输包名走「打开下拉 → 搜索框输入 → 回车」这条路
    click(doc, "perf-pkg");
    const search = doc.getElementById("perf-pkg-search");
    search.value = " com.foo ";
    search.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    ok(await waitFor(() => savedPatch(calls, "perf_pkg") === "com.foo", 3000, "包名落盘"),
       "手输包名去空白后落盘");
    ok(doc.getElementById("perf-pkg-label").textContent === "com.foo",
       "选择器按钮改为显示手输的包名");
    window.close();
  }

  console.log("\n[10] 样式回归：整页不滚动、画布铺满、指标卡网格");
  {
    const perfTab = cssBlock('.tab[data-tab="perf"]');
    ok(/overflow:\s*hidden/.test(perfTab), "性能页 overflow:hidden（曲线不跑到屏幕外）");
    const wrap = cssBlock(".perf-canvas-wrap");
    ok(/flex:\s*1/.test(wrap) && /min-height:\s*0/.test(wrap),
       "画布容器 flex:1 + min-height:0（吃掉剩余高度）");
    const cv = cssBlock(".perf-canvas-wrap canvas");
    ok(/position:\s*absolute/.test(cv), "canvas 绝对定位铺满容器（尺寸由 JS 按 DPR 设）");
    const stats = cssBlock(".perf-stats");
    ok(/grid-template-columns/.test(stats), "指标卡用 grid 等宽排布");
    // 指标会随版本增减（新增卡顿率后是 7 张）：列数用 auto-fit + 最小宽度自适应，
    // 写死 repeat(6) 会让第 7 张卡掉到第二行孤零零一张。
    ok(/repeat\(auto-fit,\s*minmax\(124px/.test(stats),
       "宽屏按可用宽度自动等分（新增指标不会掉行）");
    ok(/@media \(max-width: 1180px\)[\s\S]*repeat\(auto-fit,\s*minmax\(104px/.test(css),
       "窄窗降为更小最小宽度自适应换行，读数不被压成省略号");
    const stat = cssBlock(".perf-stat.on");
    ok(/border-color/.test(stat) && /rgba\(52, 224, 234/.test(stat),
       "选中卡用主题磷光青描边（与整体仪表语言一致）");
  }

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  clearTimeout(watchdog);
  process.exit(fail ? 1 : 0);
})();
