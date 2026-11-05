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

  console.log("\n通过 " + pass + " / 失败 " + fail);
  clearTimeout(watchdog);
  process.exit(fail ? 1 : 0);
})();
