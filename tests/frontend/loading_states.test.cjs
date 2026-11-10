/* jsdom 前端测试：耗时操作的「等待态」反馈

   回归：
   - 截图预览要后端读盘 + base64 传输，秒级耗时；预览块必须先亮出遮罩转圈，
     拿到数据后再换成图片，不能先空一块再突然弹出。
   - 其它秒级操作（截图 / 安装 / 诊断包 / Logcat 抓取 / scrcpy / 检查更新…）
     的按钮要有 .is-loading 转圈 + aria-busy，且结束后能恢复。
   - 通用等待态只加视觉，不擅自改 disabled（各业务状态机自己管）。
*/
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.join(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "frontend/index.html"), "utf8");
const css = fs.readFileSync(path.join(ROOT, "frontend/css/app.css"), "utf8");
const js = fs.readFileSync(path.join(ROOT, "frontend/js/app.js"), "utf8");

process.on("unhandledRejection", () => {});

let pass = 0, fail = 0;
function ok(cond, name) {
  if (cond) { pass++; console.log("  ✓ " + name); }
  else { fail++; console.log("  ✗ " + name); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitFor(fn, ms = 5000, label = "") {
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

const DEV = [{ serial: "A1", model: "Pixel", state: "device", ok: true, checked: true }];
const PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGNgYGAAAAAEAAH2FzhVAAAAAElFTkSuQmCC";

function mkEnv(overrides) {
  overrides = overrides || {};
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const calls = [];
  const queue = [];
  let round = 0;
  window.__push = (ev) => queue.push(ev);
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          calls.push({ fn: k, args });
          if (overrides[k]) return overrides[k].apply(null, args);
          if (k === "boot") {
            return Promise.resolve({ ok: true, version: "v-test", warnings: [], adb: "adb" });
          }
          if (k === "take_events") {
            round++;
            if (round === 1) {
              return Promise.resolve([
                { kind: "booted", payload: {
                  version: "v-test", warnings: [], commands: [], adb: "adb", settings: {},
                } },
                { kind: "devices", payload: { items: DEV } },
              ]);
            }
            return Promise.resolve(queue.splice(0, queue.length));
          }
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  // jsdom 无 canvas：性能页绘图会给 null 调 API；桩一个最小 2d 上下文。
  window.HTMLCanvasElement.prototype.getContext = function () {
    return {
      setTransform() {}, clearRect() {}, beginPath() {}, closePath() {},
      moveTo() {}, lineTo() {}, arc() {}, rect() {}, fillRect() {},
      save() {}, restore() {}, stroke() {}, fill() {}, fillText() {},
      measureText() { return { width: 24 }; },
      createLinearGradient() { return { addColorStop() {} }; },
    };
  };
  window.eval(js);
  return { window, calls };
}

(async () => {
  const watchdog = setTimeout(() => {
    console.log("    (看门狗触发)");
    process.exit(fail ? 1 : 0);
  }, 50000);

  console.log("\n[0] 样式：通用按钮转圈 + 预览遮罩");
  {
    ok(/\.btn\.is-loading::after\s*\{[^}]*animation: btn-spin/.test(css),
       "按钮 is-loading 有转圈动画");
    ok(/@keyframes btn-spin\s*\{/.test(css), "定义了 btn-spin 关键帧");
    ok(/\.shot-preview-frame\.is-loading\s*\{[^}]*min-height: 220px/.test(css),
       "预览生成时先占住高度（不塌成一条线）");
    ok(/\.shot-preview-loading\s*\{[^}]*position: absolute/.test(css),
       "加载遮罩覆盖预览框");
    ok(/\.shot-preview-loading\.is-error\s*\{[^}]*cursor: pointer/.test(css),
       "失败遮罩可点击重试");
  }

  console.log("\n[1] 截图预览：数据回来之前先显示加载遮罩");
  {
    let resolveShot = null;
    const { window } = mkEnv({
      screenshot_data: () => new Promise((r) => { resolveShot = r; }),
    });
    const doc = window.document;
    const prev = doc.getElementById("shot-preview");
    const frame = doc.getElementById("shot-preview-frame");
    const note = doc.getElementById("shot-preview-loading");
    const img = doc.getElementById("shot-preview-img");
    await waitFor(() => !doc.getElementById("tool-shot").disabled, 3000, "设备就绪");
    window.__push({ kind: "tool", payload: { type: "screenshot", path: "D:\\x\\shot.png" } });
    const loading = await waitFor(() => {
      return !prev.hidden && !note.hidden && frame.classList.contains("is-loading");
    }, 4000, "预览加载遮罩出现");
    ok(loading, "预览块先可见并带 is-loading 遮罩");
    ok(frame.getAttribute("aria-busy") === "true", "加载中 aria-busy=true");
    ok(!img.getAttribute("src"), "数据未回来前不写入半截图片");
    ok((doc.getElementById("shot-preview-name").textContent || "").indexOf("正在生成预览") >= 0,
       "文件名行先给出「正在生成预览…」");
    resolveShot({ ok: true, data: PNG_B64, name: "shot.png" });
    const done = await waitFor(() => note.hidden && !frame.classList.contains("is-loading"), 3000, "遮罩收起");
    ok(done, "数据到达后遮罩收起");
    ok(/^data:image\/png;base64,/.test(img.getAttribute("src") || ""), "预览图正常写入");
  }

  console.log("\n[1.5] 截图预览失败：遮罩变成可点击重试");
  {
    let calls = 0, resolveSecond = null;
    const { window } = mkEnv({
      screenshot_data: () => {
        calls++;
        if (calls === 1) return Promise.resolve({ ok: false, reason: "read_failed" });
        return new Promise((r) => { resolveSecond = r; });
      },
    });
    const doc = window.document;
    const frame = doc.getElementById("shot-preview-frame");
    const note = doc.getElementById("shot-preview-loading");
    const img = doc.getElementById("shot-preview-img");
    const name = doc.getElementById("shot-preview-name");
    await waitFor(() => !doc.getElementById("tool-shot").disabled, 3000, "设备就绪");
    window.__push({ kind: "tool", payload: { type: "screenshot", path: "D:\\x\\bad.png" } });
    const failed = await waitFor(() => !note.hidden && note.classList.contains("is-error"), 4000, "失败态");
    ok(failed, "读盘失败后遮罩显示错误态");
    ok(frame.classList.contains("is-error"), "预览框标记 is-error 并保持高度");
    ok(!img.getAttribute("src"), "失败后不保留旧图");
    ok((doc.getElementById("shot-preview-loading-text").textContent || "").indexOf("点击重试") >= 0,
       "遮罩文案提示点击重试");
    ok(name.classList.contains("err"), "文件名行也标记失败");
    note.dispatchEvent(new window.Event("click", { bubbles: true }));
    await waitFor(() => calls === 2, 3000, "重试请求");
    ok(calls === 2, "点击遮罩会重新请求预览");
    resolveSecond({ ok: true, data: PNG_B64, name: "bad.png" });
    const done = await waitFor(() => note.hidden && !frame.classList.contains("is-error"), 3000, "重试成功");
    ok(done, "重试成功后遮罩收起");
    ok(/^data:image\/png;base64,/.test(img.getAttribute("src") || ""), "重试成功后正常显示预览");
    ok(!name.classList.contains("err"), "成功后清除失败标记");
  }

  console.log("\n[2] 截图按钮：点击即转圈，shot_state 收尾后恢复");
  {
    const { window } = mkEnv({ screenshot: () => Promise.resolve({ ok: true }) });
    const doc = window.document;
    const btn = doc.getElementById("tool-shot");
    await waitFor(() => !btn.disabled, 3000, "设备就绪");
    btn.dispatchEvent(new window.Event("click", { bubbles: true }));
    ok(btn.classList.contains("is-loading"), "点击后按钮进入等待态");
    ok(btn.getAttribute("aria-busy") === "true", "等待中 aria-busy=true");
    window.__push({ kind: "shot_state", payload: { running: false } });
    const cleared = await waitFor(() => !btn.classList.contains("is-loading"), 3000, "等待态结束");
    ok(cleared, "后端 shot_state 完成后收掉转圈");
    ok(!btn.hasAttribute("aria-busy"), "完成后移除 aria-busy");
  }

  console.log("\n[3] 安装 / 诊断 / 更新：状态事件驱动按钮等待态");
  {
    const { window } = mkEnv();
    const doc = window.document;
    await waitFor(() => !doc.getElementById("tool-shot").disabled, 3000, "设备就绪");
    const apk = doc.getElementById("apk-install");
    window.__push({ kind: "apk_state", payload: { running: true } });
    await waitFor(() => apk.classList.contains("is-loading"), 3000, "安装等待态");
    ok(apk.classList.contains("is-loading"), "安装中按钮转圈");
    window.__push({ kind: "apk_state", payload: { running: false } });
    const apkDone = await waitFor(() => !apk.classList.contains("is-loading"), 3000, "安装结束");
    ok(apkDone, "安装结束收掉转圈");

    const diag = doc.getElementById("diag-collect");
    window.__push({ kind: "diag_state", payload: { running: true } });
    await waitFor(() => diag.classList.contains("is-loading"), 3000, "诊断等待态");
    ok(diag.classList.contains("is-loading"), "诊断收集中按钮转圈");
    window.__push({ kind: "diag_state", payload: { running: false } });
    ok(await waitFor(() => !diag.classList.contains("is-loading"), 3000, "诊断结束"),
       "诊断结束收掉转圈");

    const upd = doc.getElementById("about-update-check");
    window.__push({ kind: "update_state", payload: { running: true } });
    await waitFor(() => upd.classList.contains("is-loading"), 3000, "更新等待态");
    ok(upd.classList.contains("is-loading"), "检查更新时按钮转圈");
    window.__push({ kind: "update_state", payload: { running: false } });
    ok(await waitFor(() => !upd.classList.contains("is-loading"), 3000, "更新结束"),
       "检查结束收掉转圈");
  }

  console.log("\n[4] Logcat 抓取：启动中按钮转圈，running 事件后收起");
  {
    const { window } = mkEnv({ logcat_capture_start: () => new Promise(() => {}) });
    const doc = window.document;
    const start = doc.getElementById("lc-cap-start");
    await waitFor(() => !start.disabled, 3000, "设备就绪");
    start.dispatchEvent(new window.Event("click", { bubbles: true }));
    ok(start.classList.contains("is-loading"), "开始抓取后进入等待态");
    ok(start.getAttribute("aria-busy") === "true", "等待中 aria-busy=true");
    window.__push({ kind: "logcat_capture", payload: { status: "running" } });
    const running = await waitFor(() => !start.classList.contains("is-loading"), 3000, "running 事件");
    ok(running, "running 事件到达后收掉转圈");
  }

  console.log("\n[5] scrcpy 投屏：启动未返回时按钮持续转圈，返回后恢复");
  {
    let resolveStart = null;
    const { window } = mkEnv({
      scrcpy_start: () => new Promise((r) => { resolveStart = r; }),
    });
    const doc = window.document;
    const btn = doc.getElementById("tool-scrcpy");
    await waitFor(() => !btn.disabled, 3000, "设备就绪");
    btn.dispatchEvent(new window.Event("click", { bubbles: true }));
    ok(btn.classList.contains("is-loading"), "启动请求在途时按钮转圈");
    resolveStart({ ok: true, started: ["A1"], skipped: [] });
    const done = await waitFor(() => !btn.classList.contains("is-loading"), 3000, "启动完成");
    ok(done, "返回后收掉转圈");
  }

  console.log("\n[6] 性能报告导出 / 文件上传：长任务按钮等待态");
  {
    let resolveExport = null;
    const { window } = mkEnv({
      perf_start: () => Promise.resolve({ ok: true, serial: "A1", interval: 1.0, info: {} }),
      perf_poll: () => Promise.resolve({
        running: true, seq: 1,
        samples: [{ seq: 1, t: 1793200000, cpu: 21.5, mem_used: 4100.0, pss: 320.0,
                    fps: 59.4, batt: 78, temp: 31.0 }],
      }),
      perf_export: () => new Promise((r) => { resolveExport = r; }),
    });
    const doc = window.document;
    await waitFor(() => !doc.getElementById("perf-start").disabled, 3000, "设备就绪");
    doc.getElementById("perf-start").dispatchEvent(new window.Event("click", { bubbles: true }));
    await waitFor(() => !doc.getElementById("perf-export").disabled, 4000, "有采样点");
    doc.getElementById("perf-export").dispatchEvent(new window.Event("click", { bubbles: true }));
    const exp = doc.getElementById("perf-export");
    ok(exp.classList.contains("is-loading"), "生成性能报告时按钮转圈");
    ok(exp.disabled, "生成期间按钮禁用");
    resolveExport({ ok: true, html: "/tmp/p.html", rows: 1, samples: 1 });
    ok(await waitFor(() => !exp.classList.contains("is-loading"), 3000, "报告完成"),
       "报告生成后收掉转圈");
    window.close();
  }

  console.log("\n[7] 文件上传：一批文件传完才收起「上传」转圈");
  {
    let resolveUpload = null;
    const { window, calls } = mkEnv({
      file_upload_data: () => new Promise((r) => { resolveUpload = r; }),
    });
    const doc = window.document;
    const label = doc.getElementById("file-upload-btn");
    const input = doc.getElementById("file-upload");
    await waitFor(() => /设备: A1/.test(doc.getElementById("file-dev-now").textContent),
                   3000, "文件页设备就绪");
    const file = new window.File(["hello"], "a.txt", { type: "text/plain" });
    Object.defineProperty(input, "files", { value: [file], configurable: true });
    input.dispatchEvent(new window.Event("change", { bubbles: true }));
    ok(await waitFor(() => label.classList.contains("is-loading"), 3000, "上传等待态"),
       "选中文件后「上传」按钮转圈");
    await waitFor(() => calls.some((c) => c.fn === "file_upload_data"), 4000, "上传调用");
    resolveUpload({ ok: true });
    ok(await waitFor(() => !label.classList.contains("is-loading"), 3000, "上传完成"),
       "文件传完后收掉转圈");
    ok(!label.hasAttribute("aria-busy"), "完成后移除 aria-busy");
    window.close();
  }

  console.log("\n[8] 设备刷新 / 监控启动：按钮等待态");
  {
    let resolveRefresh = null, resolveLcStart = null;
    const { window } = mkEnv({
      refresh_devices: () => new Promise((r) => { resolveRefresh = r; }),
      logcat_start: () => new Promise((r) => { resolveLcStart = r; }),
    });
    const doc = window.document;
    const refresh = doc.getElementById("btn-refresh");
    await waitFor(() => !refresh.disabled, 3000, "设备就绪");
    refresh.dispatchEvent(new window.Event("click", { bubbles: true }));
    ok(refresh.classList.contains("is-loading") && refresh.disabled,
       "刷新设备时按钮转圈且防连点");
    resolveRefresh({ ok: true });
    ok(await waitFor(() => !refresh.classList.contains("is-loading"), 3000, "刷新完成"),
       "刷新返回后收掉转圈并恢复按钮");
    ok(!refresh.disabled, "刷新结束后按钮恢复可点");

    const start = doc.getElementById("lc-start");
    start.dispatchEvent(new window.Event("click", { bubbles: true }));
    ok(start.classList.contains("is-loading"), "启动监控时按钮转圈");
    resolveLcStart({ ok: true });
    ok(await waitFor(() => !start.classList.contains("is-loading"), 3000, "监控启动"),
       "监控启动后收掉转圈");
    window.close();
  }

  console.log("\n[9] 命令执行 / 终止：运行按钮随 stop_state 转圈");
  {
    let resolveStop = null;
    const { window } = mkEnv({
      stop_run: () => new Promise((r) => { resolveStop = r; }),
    });
    const doc = window.document;
    const runBtn = doc.getElementById("btn-run");
    const stopBtn = doc.getElementById("btn-stop");
    await waitFor(() => !doc.getElementById("tool-shot").disabled, 3000, "设备就绪");
    window.__push({ kind: "stop_state", payload: { running: true } });
    ok(await waitFor(() => runBtn.classList.contains("is-loading"), 3000, "命令运行中"),
       "命令开始执行后运行按钮转圈");
    ok(runBtn.getAttribute("aria-busy") === "true", "运行中 aria-busy=true");
    ok(!stopBtn.disabled, "运行中停止按钮可点");
    stopBtn.dispatchEvent(new window.Event("click", { bubbles: true }));
    ok(stopBtn.classList.contains("is-loading"), "点击停止后按钮转圈");
    resolveStop({ ok: true });
    ok(await waitFor(() => !stopBtn.classList.contains("is-loading"), 3000, "停止返回"),
       "终止请求返回后收掉停止转圈");
    window.__push({ kind: "stop_state", payload: { running: false } });
    ok(await waitFor(() => !runBtn.classList.contains("is-loading"), 3000, "命令结束"),
       "命令结束后收掉运行转圈");
    ok(stopBtn.disabled, "命令结束后停止按钮禁用");
    window.close();
  }

  console.log("\n通过 " + pass + " / 失败 " + fail);
  clearTimeout(watchdog);
  process.exit(fail ? 1 : 0);
})();
