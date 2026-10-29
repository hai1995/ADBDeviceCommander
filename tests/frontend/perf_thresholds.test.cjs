/* jsdom 前端行为测试：性能监控「告警阈值」设置弹窗

   后端解析 / 校验 / 写盘由 tests/test_backend_perf.py 与 test_backend_controller.py
   锁定；这里只锁前端：
   1) 四行规则由后端下发的 items 渲染（方向 / 单位 / 理由都不在前端硬编码）；
   2) 取消勾选 = 提交 null（关闭该条），数值框与选中状态联动；
   3) 非法值 / 保存失败时弹窗不关、把原因显示出来（不能假装成功）；
   4) 保存成功后新阈值立刻作用于指标卡标红 —— 否则用户改完看不到任何变化。 */
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

const ITEMS = [
  { key: "fps", title: "帧率", unit: "FPS", dir: "min", value: 45, default: 45,
    min: 1, max: 240, hint: "60Hz 屏掉到 45 以下肉眼可见不跟手" },
  { key: "jank", title: "卡顿率", unit: "%", dir: "max", value: 8, default: 8,
    min: 0, max: 100, hint: "8% 已意味着每 12 帧卡 1 帧" },
  { key: "temp", title: "电池温度", unit: "℃", dir: "max", value: 42, default: 42,
    min: 0, max: 90, hint: "42℃ 以上电池开始降频" },
  { key: "cpu", title: "CPU", unit: "%", dir: "max", value: 85, default: 85,
    min: 1, max: 100, hint: "超过 85% 调度开始互相抢占" },
];

const DEFAULT_PAYLOAD = {
  thresholds: { fps: { min: 45 }, jank: { max: 8 }, temp: { max: 42 }, cpu: { max: 85 } },
  rules: { fps: "帧率 FPS < 45", jank: "卡顿率 % > 8", temp: "电池温度 ℃ > 42", cpu: "CPU % > 85" },
  items: ITEMS,
  crit_ratio: 25,
  expr: "fps<45,jank>8,temp>42,cpu>85",
  default_expr: "fps<45,jank>8,temp>42,cpu>85",
  custom: false,
  off: false,
  errors: [],
};

function fakeCtx() {
  const ctx = {
    texts: [], dashes: 0,
    setTransform() {}, clearRect() {}, beginPath() {}, closePath() {},
    moveTo() {}, lineTo() {}, arc() {}, rect() {}, roundRect() {}, fillRect() {},
    save() {}, restore() {}, stroke() {}, fill() {}, measureText() { return { width: 24 }; },
    fillText(t) { ctx.texts.push(String(t)); },
    setLineDash() { ctx.dashes++; },
    createLinearGradient() { return { addColorStop() {} }; },
  };
  return ctx;
}

function mkEnv(opts) {
  const cfg = opts || {};
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const ctx = fakeCtx();
  const calls = [];
  let round = 0;

  window.HTMLCanvasElement.prototype.getContext = function () { return ctx; };
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
                                     adb: "adb", settings: {} });
          }
          if (k === "take_events") {
            const b = round === 0
              ? [{ kind: "devices",
                   payload: { items: [{ serial: "S1", model: "Pixel 7", state: "device",
                                        ok: true, checked: true }] } }]
              : [];
            round++;
            return Promise.resolve(b);
          }
          if (k === "perf_thresholds") return Promise.resolve(cfg.payload || DEFAULT_PAYLOAD);
          if (k === "perf_set_thresholds") {
            return Promise.resolve(cfg.onSet ? cfg.onSet(args[0]) : { ok: true,
              ...DEFAULT_PAYLOAD, thresholds: { fps: { min: 55 } }, rules: { fps: "帧率 FPS < 55" },
              items: ITEMS.map((i) => (i.key === "fps" ? { ...i, value: 55 } : i)), custom: true });
          }
          if (k === "perf_start") {
            return Promise.resolve({
              ok: true, serial: "S1", interval: 1.0,
              info: { serial: "S1", model: "Pixel 7", pkg: "" },
              sessions: { S1: { serial: "S1", model: "Pixel 7", pkg: "" } },
              failed: {},
            });
          }
          if (k === "perf_poll") {
            const p = cfg.poll;
            return Promise.resolve(p || { running: true, samples: [], sessions: {} });
          }
          if (k === "perf_stop") return Promise.resolve({ ok: true, samples: 1 });
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  return { window, ctx, calls };
}

const click = (doc, id) => doc.getElementById(id).dispatchEvent(
  new doc.defaultView.Event("click", { bubbles: true }));
const rows = (doc) => Array.from(doc.querySelectorAll("#perf-th-rows .th-row"));
const hidden = (doc) => doc.getElementById("perf-th-modal").classList.contains("hidden");

(async () => {
  const watchdog = setTimeout(() => {
    console.log("    (看门狗触发：按当前结果退出)");
    process.exit(fail ? 1 : 0);
  }, 30000);

  console.log("\n[1] 弹窗按后端下发的 items 渲染四行");
  {
    const { window, calls } = mkEnv({});
    const doc = window.document;
    await waitFor(() => calls.some((c) => c.fn === "perf_thresholds"), 3000, "阈值下发");
    ok(hidden(doc), "初始不显示");
    click(doc, "perf-th");
    ok(await waitFor(() => !hidden(doc), 2000, "打开弹窗"), "点「阈值」按钮打开弹窗");
    await waitFor(() => rows(doc).length === 4, 3000, "四行渲染");
    const rs = rows(doc);
    ok(rs.length === 4, "渲染 4 行（实际 " + rs.length + "）");
    ok(rs.map((r) => r.dataset.key).join(",") === "fps,jank,temp,cpu", "顺序与后端一致");
    ok(rs[0].querySelector(".th-op").textContent === "低于"
       && rs[1].querySelector(".th-op").textContent === "高于",
       "方向由后端 dir 决定（FPS 低于 / 其余高于）");
    ok(rs[0].querySelector(".th-val").value === "45"
       && rs[0].querySelector(".th-unit").textContent === "FPS",
       "数值与单位回填（45 FPS）");
    ok(rs.every((r) => r.classList.contains("on")), "四项默认全部启用");
    ok(rs[1].querySelector(".th-hint").textContent.includes("12 帧"),
       "取值理由展示在行内（不是藏在 title 里）");
  }

  console.log("\n[2] 取消勾选 = 关闭该项（提交 null）");
  {
    const { window, calls } = mkEnv({});
    const doc = window.document;
    await waitFor(() => calls.some((c) => c.fn === "perf_thresholds"), 3000, "阈值下发");
    click(doc, "perf-th");
    await waitFor(() => rows(doc).length === 4, 3000, "四行渲染");
    const jankRow = rows(doc)[1];
    const cb = jankRow.querySelector(".th-on");
    cb.checked = false;
    cb.dispatchEvent(new window.Event("change", { bubbles: true }));
    ok(!jankRow.classList.contains("on"), "取消勾选后该行置灰（.on 移除）");
    const fpsVal = rows(doc)[0].querySelector(".th-val");
    fpsVal.value = "55";
    click(doc, "perf-th-save");
    ok(await waitFor(() => calls.some((c) => c.fn === "perf_set_thresholds"), 3000, "提交"),
       "点保存提交给后端");
    const sent = calls.find((c) => c.fn === "perf_set_thresholds").args[0];
    ok(sent.fps === 55, "改动后的数值按数字提交（55）");
    ok(sent.jank === null, "未勾选的项提交 null（= 关闭）");
    ok(sent.temp === 42 && sent.cpu === 85, "未改动的项按原值提交");
    ok(await waitFor(() => hidden(doc), 3000, "关闭"), "保存成功后自动关闭弹窗");
  }

  console.log("\n[3] 后端拒绝时不关弹窗、显示原因");
  {
    const { window } = mkEnv({
      onSet: () => ({ ok: false, errors: ["帧率 的阈值 999 超出合理范围 1~240"] }),
    });
    const doc = window.document;
    await waitFor(() => doc.getElementById("perf-th").dataset.icon, 2000, "初始化");
    click(doc, "perf-th");
    await waitFor(() => rows(doc).length === 4, 3000, "四行渲染");
    rows(doc)[0].querySelector(".th-val").value = "999";
    click(doc, "perf-th-save");
    const err = doc.getElementById("perf-th-err");
    ok(await waitFor(() => !err.hidden, 3000, "错误提示"), "显示错误条");
    ok(/超出合理范围/.test(err.textContent), "错误文案透传后端原因");
    ok(!hidden(doc), "弹窗保持打开（用户可改完再存）");
  }

  console.log("\n[4] 空值 / 非数字在本地就拦住，不发请求");
  {
    const { window, calls } = mkEnv({});
    const doc = window.document;
    await waitFor(() => calls.some((c) => c.fn === "perf_thresholds"), 3000, "阈值下发");
    click(doc, "perf-th");
    await waitFor(() => rows(doc).length === 4, 3000, "四行渲染");
    rows(doc)[0].querySelector(".th-val").value = "";
    click(doc, "perf-th-save");
    ok(await waitFor(() => !doc.getElementById("perf-th-err").hidden, 2000, "本地校验"),
       "空值直接提示");
    ok(!calls.some((c) => c.fn === "perf_set_thresholds"), "未发出保存请求");
  }

  console.log("\n[5] 恢复默认只改界面，不落盘");
  {
    const { window, calls } = mkEnv({
      payload: { ...DEFAULT_PAYLOAD,
                 thresholds: { fps: { min: 55 } },
                 items: ITEMS.map((i) => (i.key === "fps" ? { ...i, value: 55 } : i)) },
    });
    const doc = window.document;
    await waitFor(() => calls.some((c) => c.fn === "perf_thresholds"), 3000, "阈值下发");
    click(doc, "perf-th");
    await waitFor(() => rows(doc).length === 4, 3000, "四行渲染");
    ok(rows(doc)[0].querySelector(".th-val").value === "55", "当前值为自定义的 55");
    click(doc, "perf-th-reset");
    ok(rows(doc)[0].querySelector(".th-val").value === "45", "恢复默认后回填 45");
    ok(!calls.some((c) => c.fn === "perf_set_thresholds"), "未点保存前不写盘");
  }

  console.log("\n[6] 保存后新阈值立刻作用于标红");
  {
    // 50 FPS 在基线（45）下合格；把阈值改成 55 后应立即切红
    const poll = { running: true, sessions: { S1: {
      running: true, seq: 2, info: { serial: "S1", model: "Pixel 7" },
      samples: [
        { seq: 1, t: 1793200000, cpu: 20.0, fps: 50.0 },
        { seq: 2, t: 1793200001, cpu: 20.0, fps: 50.0 },
      ],
    } } };
    const { window } = mkEnv({ poll });
    const doc = window.document;
    await waitFor(() => doc.getElementById("perf-start").disabled === false, 3000, "设备就绪");
    click(doc, "perf-start");
    ok(await waitFor(() => doc.getElementById("perf-v-fps").textContent === "50", 4000, "读数"),
       "收到 50 FPS 样本");
    ok(!doc.getElementById("perf-stat-fps").classList.contains("warn"),
       "基线 45 下不告警");
    click(doc, "perf-th");
    await waitFor(() => rows(doc).length === 4, 3000, "四行渲染");
    rows(doc)[0].querySelector(".th-val").value = "55";
    click(doc, "perf-th-save");
    ok(await waitFor(() => doc.getElementById("perf-stat-fps").classList.contains("warn"),
                     3000, "改阈值后切红"),
       "阈值改为 55 后同一读数立刻切红");
  }

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  clearTimeout(watchdog);
  process.exit(fail ? 1 : 0);
})();
