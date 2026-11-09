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

function boot(overrides, srcTransform) {
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
  window.eval(srcTransform ? srcTransform(js) : js);
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
  // 分段只是实现手段：用户要的是「一个完整 mp4」。提示里必须写明会合并，
  // 否则用户看到目录里蹦出 _p2 会以为程序把一次录制拆成了好几份。
  ok(/合并/.test(txt) && /完整/.test(txt), "要写明各段会合并成一个完整 mp4");
  ok(/ffmpeg/i.test(txt), "合并依赖 ffmpeg，没装时的后果必须在界面上写明");
  ok(/57\s*分钟|20\s*段/.test(txt), "段数上限（约 57 分钟）要写明，用户才知道长录制会在哪停");
  // 合并后拼接点仍是「画面缺失」而不是补帧——这句话不写，用户回放时看到
  // 跳变就会当成录制中断，白重录一遍。
  ok(/N\s*-\s*1|N-1|N−1/.test(txt), "有几段就有几处拼接点，要把这个换算关系说清");

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

  // ---------- 3) 回归：停止收尾超过全局超时不得报「请求超时」假失败 ----------
  /* 真机场景：收尾（拉视频 → ffmpeg 合并 → 打包）远超 15 秒，全局超时让前端
     先弹一条「调用后端失败：请求超时（15s）」，随后后端事件又把「✓ 已合并 /
     ✓ 已打包」推回来 —— 用户看到假失败与真成功并存，还会在按钮提前解锁后
     误点「开始录制」撞上未清完的会话。修复：stop / cancel 显式传 timeout=0。
     测试手法：把全局超时缩到 0.05s，让停止 mock 300ms 才返回 —— 修复前的
     代码会在 50ms 处把「请求超时」写进状态栏；修复后安静等 promise 落定。
     断言核心是状态栏全文无报错（✓ 文案来自后端事件而非前端，mock 里没有）；
     按钮终态仅作同步点 —— 注意 mock 里没有受控设备，setRecRunning(false) →
     syncToolButtons() 会把「开始」按钮禁掉，这与真机行为一致，不能拿来断言。 */
  {
    let stopSettled = false;
    const win3 = boot(
      { screen_record_stop: () => new Promise((r) => setTimeout(() => { stopSettled = true; r({ ok: true }); }, 300)) },
      (src) => src.replace("const API_TIMEOUT_S = 15;", "const API_TIMEOUT_S = 0.05;"),
    );
    const doc3 = win3.document;
    ok(await waitFor(() => doc3.querySelector("#tool-rec") && !doc3.querySelector("#tool-rec").disabled,
      3000, "缩短超时后启动"), "缩短超时后应用可正常启动");
    doc3.querySelector("#tool-rec").click();
    ok(await waitFor(() => doc3.querySelector("#tool-rec-stop") && !doc3.querySelector("#tool-rec-stop").disabled,
      3000, "进入录制中"), "缩短超时后仍可进入录制中");

    doc3.querySelector("#tool-rec-stop").click();
    // 同步点：等停止处理器完整跑完（300ms 落定 + in-flight 解除 + 余量）
    ok(await waitFor(() => {
        const stopBtn = doc3.querySelector("#tool-rec-stop");
        return stopBtn && stopBtn.disabled && !stopBtn.classList.contains("is-loading");
      }, 3000, "停止处理器落定") && stopSettled,
      "收尾慢于全局超时时处理器仍完整跑完（mock promise 已落定）");
    ok(stopSettled, "慢停止的 mock promise 确实已 resolve（测试等待时间足够）");
    /* pushStatus 经 pushLine 入队、requestAnimationFrame 批量刷进 #status DOM
       （见 app.js pushLine 的 rAF 节流）——等态一解除就立刻读会漏掉刚入队的
       行，这里等几帧再读，保证队列已 flush。 */
    await sleep(150);
    const statusText = (doc3.querySelector("#status") || {}).textContent || "";
    ok(!/请求超时/.test(statusText) && !/调用后端失败/.test(statusText),
      "不得出现「请求超时 / 调用后端失败」假失败");
    win3.close();
  }

  console.log("\n==============================================");
  console.log("结果：" + pass + " 通过 / " + fail + " 失败");
  console.log("==============================================");
  process.exit(fail ? 1 : 0);
})();
