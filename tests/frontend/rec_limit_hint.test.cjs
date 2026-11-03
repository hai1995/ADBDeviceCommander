/* jsdom 前端测试：录屏「建议最大录制时长」提示 + 点击后的即时反馈
   —— ① 卡片里必须常驻一句上限说明（Android screenrecord 单段 180 秒）；
      ② 点「开始 / 停止」后界面要立刻有状态，不能干等后端收尾返回。
   回归背景：录屏按钮点下去后只有按钮变灰，收尾要「停设备端 → 拉视频 → 打包」
   好几秒，用户以为点空了又点第二次；而 180 秒上限更是到点才暴露，
   此前界面上没有任何一处写过这件事。 */
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
async function waitFor(fn, ms = 3000, label = "") {
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

function boot(overrides) {
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
  const { window } = dom;
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          if (overrides && overrides[k]) return overrides[k].apply(null, args);
          if (k === "boot") {
            return Promise.resolve({ version: "v-test", warnings: [], commands: [], adb: "adb" });
          }
          if (k === "take_events") return Promise.resolve([]);
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  return window;
}

(async () => {
  // ---------- 1) 静态：录屏卡片里常驻上限提示 ----------
  const d0 = new JSDOM(html);
  const hint = d0.window.document.querySelector("#rec-body .rec-limit");
  ok(!!hint, "录屏卡片必须常驻「建议最大录制时长」提示");
  const txt = (hint && hint.textContent) || "";
  ok(/3\s*分钟/.test(txt), "提示语要给出具体建议时长（3 分钟）");
  ok(/180/.test(txt), "要说明 180 秒这个硬上限（用户才知道到点为什么切段）");
  ok(/(自动)?分段/.test(txt), "要说明程序会自己分段");
  ok(/(无需|不用).*(操作|手动)/.test(txt), "要明确告诉用户不需要手动干预");
  ok(/接上|续录/.test(txt), "要说清到点会自动接着录下一段，而不是就此停掉");
  ok(/间隙/.test(txt), "段间有约 1 秒录不到的缝隙，必须如实告知（不能让人以为视频是连续的）");

  // ---------- 2) 行为：点击后立刻有状态，不等收尾返回 ----------
  let releaseStop;
  const stopPending = new Promise((r) => { releaseStop = r; });
  const win = boot({
    screen_record_stop: () => stopPending,
  });
  const doc = win.document;
  await waitFor(() => doc.querySelector("#tool-rec") && !doc.querySelector("#tool-rec").disabled,
    "启动后「开始录制」应可点");

  doc.querySelector("#tool-rec").click();
  const started = await waitFor(
    () => /正在启动录屏/.test((doc.querySelector("#status") || {}).textContent || ""),
    2000, "启动即时反馈");
  ok(started, "点「开始录制」后要立刻落一条「正在启动录屏…」");
  ok(await waitFor(() => doc.querySelector("#tool-rec-stop") && !doc.querySelector("#tool-rec-stop").disabled,
    2000, "进入录制中"), "启动成功后「停止」应可点");

  doc.querySelector("#tool-rec-stop").click();
  const stopping = await waitFor(
    () => /正在停止录屏并收尾/.test((doc.querySelector("#status") || {}).textContent || ""),
    2000, "停止即时反馈");
  ok(stopping, "点「停止」后要立刻落一条「正在停止录屏并收尾…」（不能干等几秒）");

  releaseStop({ ok: true });
  await sleep(50);

  console.log("\n==============================================");
  console.log("结果：" + pass + " 通过 / " + fail + " 失败");
  console.log("==============================================");
  process.exit(fail ? 1 : 0);
})();
