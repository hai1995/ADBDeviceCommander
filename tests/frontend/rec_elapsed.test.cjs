/* jsdom 前端测试：录制中在「停止录制」旁显示已录时长。
   —— ① 空闲时整块隐藏，不占位、不制造噪音；
      ② 录制中实时走动，起点用后端返回的会话开始时刻（补上启动 screenrecord
         的 1~2 秒），满 1 小时自动补小时位；
      ③ 点「停止」瞬间冻结读数：收尾十几秒里数字不再上涨，避免读数比视频长；
      ④ 录制被后端判定意外结束（rec_state running=false）时整块收起。 */
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
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
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

const pill = (doc) => doc.querySelector("#rec-elapsed");
const pillText = (doc) => {
  const t = doc.querySelector("#rec-elapsed-t");
  return (t && t.textContent) || "";
};

(async () => {
  // ---------- 1) 静态：默认隐藏，位置紧贴「停止录制」 ----------
  {
    const d = new JSDOM(html);
    const el = d.window.document.querySelector("#rec-elapsed");
    ok(!!el, "录屏按钮区必须有录制时长元素");
    ok(!!el && el.hasAttribute("hidden"), "空闲时必须隐藏（没录制就别占地方）");
    const row = el && el.closest(".tool-row");
    ok(!!row && row.querySelector("#tool-rec-stop"),
      "时长必须与「停止录制」在同一行按钮区");
    ok(!!row && row.querySelector("#tool-rec-stop").nextElementSibling === el,
      "时长要紧贴「停止录制」（否则用户不知道这个数字是谁的）");
  }

  // ---------- 2) 录制中走动，起点取后端 started ----------
  let releaseStop;
  const stopPending = new Promise((r) => { releaseStop = r; });
  const win = boot({
    // 后端返回「会话已开始 65 秒」：前端读数必须从这里接着走，而不是 00:00
    screen_record_start: () => Promise.resolve({
      ok: true, ts: "20260101_000000", started: Date.now() / 1000 - 65,
    }),
    screen_record_stop: () => stopPending,
  });
  const doc = win.document;
  ok(await waitFor(() => doc.querySelector("#tool-rec") && !doc.querySelector("#tool-rec").disabled,
    3000, "启动完成"), "应用可正常启动，开始录制可点");

  doc.querySelector("#tool-rec").click();
  ok(await waitFor(() => pill(doc) && !pill(doc).hidden, 3000, "显示时长"),
    "进入录制后时长必须显示出来");
  ok(/^01:0\d$/.test(pillText(doc)),
    "读数必须从后端给的真实开始时刻起算（此刻应约 01:05，实际 " + pillText(doc) + "）");
  ok(!pill(doc).classList.contains("frozen"), "录制中不应是冻结态");

  const before = pillText(doc);
  await sleep(1200);
  ok(pillText(doc) !== before, "录制中读数必须持续走动（" + before + " → " + pillText(doc) + "）");

  // ---------- 3) 点停止即刻冻结，收尾期间不再上涨 ----------
  doc.querySelector("#tool-rec-stop").click();
  ok(await waitFor(() => pill(doc) && pill(doc).classList.contains("frozen"),
    2000, "冻结态"), "点「停止」后时长立即冻结"); 
  const frozen = pillText(doc);
  await sleep(800);
  ok(pillText(doc) === frozen,
    "收尾（拉段 / 合并 / 打包）期间读数不得继续上涨（冻结于 " + frozen + "）");

  releaseStop({ ok: true });
  ok(await waitFor(() => pill(doc) && pill(doc).hidden, 3000, "收尾后隐藏"),
    "停止完成后时长整块收起");
  win.close();

  // ---------- 4) 超过 1 小时补小时位 ----------
  {
    const w2 = boot({
      screen_record_start: () => Promise.resolve({
        ok: true, started: Date.now() / 1000 - 3725,   // 1:02:05
      }),
    });
    const d2 = w2.document;
    await waitFor(() => d2.querySelector("#tool-rec") && !d2.querySelector("#tool-rec").disabled,
      3000, "启动完成");
    d2.querySelector("#tool-rec").click();
    await waitFor(() => pill(d2) && !pill(d2).hidden, 3000, "显示时长");
    ok(/^1:02:0\d$/.test(pillText(d2)),
      "满 1 小时要补小时位（实际 " + pillText(d2) + "）");
    w2.close();
  }

  // ---------- 5) 录制被后端判定意外结束：整块收起 ----------
  {
    let emit = false;
    const w3 = boot({
      screen_record_start: () => Promise.resolve({ ok: true, started: Date.now() / 1000 }),
      take_events: () => Promise.resolve(
        emit ? [{ kind: "rec_state", payload: { running: false, reason: "died" } }] : []),
    });
    const d3 = w3.document;
    await waitFor(() => d3.querySelector("#tool-rec") && !d3.querySelector("#tool-rec").disabled,
      3000, "启动完成");
    d3.querySelector("#tool-rec").click();
    await waitFor(() => pill(d3) && !pill(d3).hidden, 3000, "显示时长");
    emit = true;                       // 模拟「录屏进程意外死亡」
    ok(await waitFor(() => pill(d3) && pill(d3).hidden, 3000, "事件后收起"),
      "后端报录制意外结束后，时长必须收起（不能停在过期读数上）");
    w3.close();
  }

  console.log("\n==============================================");
  console.log("结果：" + pass + " 通过 / " + fail + " 失败");
  console.log("==============================================");
  process.exit(fail ? 1 : 0);
})();
