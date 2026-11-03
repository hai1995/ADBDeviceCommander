/* jsdom 前端测试：录屏「取消」按钮 + 分段提示语沉到区块下方
   —— ① 录错了一场时，用户要能「取消」：停止并删除本次产物，不合并、不打包；
      ② 「取消」就挨着「停止」，误点一次等于删掉刚录的东西（没有回收站），
         必须先确认再动手；用户点「否」时一个后端调用都不许发；
      ③ 那大段「约每 3 分钟自动分段」说明是**说明**不是操作：它在操作区块
         （按钮 + 开关）下方，别再把「开始录制」挤到屏幕下半截。
   回归背景：以前「录错了」唯一出口是「停止」——它一定走合成 / 打包，用户拿到
   一个「✓ 已打包」的 zip，还得自己去目录里一个个删。 */
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
const statusText = (doc) => (doc.querySelector("#status") || {}).textContent || "";

function boot(overrides, confirmAnswer) {
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  let round = 0;
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          if (overrides && overrides[k]) return overrides[k].apply(null, args);
          if (k === "boot") {
            return Promise.resolve({ version: "v-test", warnings: [], commands: [], adb: "adb" });
          }
          if (k === "take_events") {
            // 第一轮喂一条「已勾选一台设备」：工具页按钮的可用性只由勾选态决定，
            // 没有设备时「开始录制」本来就是灰的，测不到取消按钮的真实状态机。
            if (round++ === 0) {
              return Promise.resolve([
                { kind: "devices", payload: { items: [{ serial: "A1", ok: true, checked: true }] } },
              ]);
            }
            return Promise.resolve([]);
          }
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  // 原生 confirm：jsdom 里没有实现（调用只会在控制台报 not implemented 并返回
  // undefined = falsy），所以这里必须显式打桩，否则测的根本不是用户点「是」的分支。
  window.confirm = () => confirmAnswer !== false;
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  return window;
}

/* 看门狗：断言里踩到 null（旧界面根本没有这些节点）会抛错，异常又被
   unhandledRejection 吞掉、jsdom 的定时器又不会停 —— 进程会一直挂着。
   到点按当前结果退出，保证失败是「失败」而不是「卡死」。 */
const watchdog = setTimeout(() => {
  console.log("    (看门狗触发：疑似断言抛错导致未收尾)");
  process.exit(fail ? 1 : 0);
}, 30000);
watchdog.unref && watchdog.unref();

(async () => {
  // ---------- 1) 静态：按钮存在、初始不可点 ----------
  const d0 = new JSDOM(html);
  const doc0 = d0.window.document;
  const cancel0 = doc0.getElementById("tool-rec-cancel");
  ok(!!cancel0, "录屏卡必须有「取消」按钮");
  ok((cancel0 && cancel0.textContent.trim()) === "取消", "按钮文案就是「取消」");
  ok(cancel0 && cancel0.disabled === true, "未录制时「取消」不可点（没有会话可取消）");
  ok(cancel0 && /删除/.test(cancel0.getAttribute("title") || ""),
    "悬停提示要写明会删除文件（不能让人以为只是中止）");
  ok(cancel0 && cancel0.getAttribute("data-icon") === "trash",
    "取消用垃圾桶图标，与「停止」的方块图标区分开");
  const row = cancel0 && cancel0.parentElement;
  ok(row && row.classList.contains("tool-row"), "取消与开始/停止同一行（操作区块）");
  // 配色：警示色（琥珀），刻意不是 .danger —— 录制中「停止」本身就是红块呼吸，
  // 两键同色等于没区分，用户照样点错。这条断言盯的就是「不许退回中性灰，也不
  // 许和停止撞色」。
  ok(cancel0 && cancel0.classList.contains("warn"),
    "取消用警示色 .warn（与停止的中性灰 / 红区分开）");
  ok(cancel0 && !cancel0.classList.contains("danger"),
    "取消不能是 .danger：会与录制中的「停止」撞色");
  ok(/\.btn\.warn\s*\{/.test(css),
    "样式表里确实定义了 .btn.warn（否则 class 加了也是灰的）");
  ok(/\.btn\.warn:hover\s*\{/.test(css), ".btn.warn 有 hover 态（不然像禁用）");
  ok(/\.btn\.warn:disabled/.test(css), ".btn.warn 有禁用态（否则灰不掉，看着一直可点）");
  const stop0 = doc0.getElementById("tool-rec-stop");
  ok(stop0 && !stop0.classList.contains("warn"),
    "「停止」不用警示色（保留红色 = 当前运行态的语义）");

  // ---------- 2) 静态：分段提示语沉到操作区块下方 ----------
  const body = doc0.getElementById("rec-body");
  const hint = body.querySelector(".rec-limit");
  const btnRow = body.querySelector(".tool-row");
  const opts = body.querySelector(".rec-opts");
  ok(!!hint && !!btnRow && !!opts, "三块都在 #rec-body 内");
  const order = Array.from(body.children);
  ok(order.indexOf(hint) > order.indexOf(btnRow),
    "分段提示语要排在按钮行之后（说明沉底，别把按钮挤下去）");
  ok(order.indexOf(hint) > order.indexOf(opts),
    "分段提示语也要排在开关组之后");
  ok(order[order.length - 1] === hint, "提示语是录屏卡的最后一块（真正在「区块下方」）");
  ok(/3\s*分钟/.test(hint.textContent) && /合并/.test(hint.textContent),
    "提示语内容本身不能丢（3 分钟 / 合并仍要写明）");

  // ---------- 3) 行为：点「否」不发任何请求 ----------
  let cancelCalls = 0;
  {
    const win = boot({ screen_record_cancel: () => { cancelCalls++; return Promise.resolve({ ok: true }); } }, false);
    const doc = win.document;
    ok(await waitFor(() => doc.getElementById("tool-rec") && !doc.getElementById("tool-rec").disabled,
      3000, "启动后「开始录制」应可点"), "有受控设备时「开始录制」可点");
    doc.getElementById("tool-rec").click();
    ok(await waitFor(() => doc.getElementById("tool-rec-cancel") &&
      !doc.getElementById("tool-rec-cancel").disabled, 2000, "录制中取消可点"),
      "开始录制后「取消」应可点");

    doc.getElementById("tool-rec-cancel").click();
    await sleep(120);
    ok(cancelCalls === 0, "确认框里点「否」时不许调用后端（误点不能删数据）");
    ok(!doc.getElementById("tool-rec-cancel").disabled, "放弃取消后按钮仍可点");
  }

  // ---------- 4) 行为：点「是」→ 调后端、有即时反馈、结束后按钮态复位 ----------
  let releaseCancel;
  const pending = new Promise((r) => { releaseCancel = r; });
  let calls = 0;
  const win = boot({
    screen_record_cancel: () => { calls++; return pending; },
  }, true);
  const doc = win.document;
  ok(await waitFor(() => doc.getElementById("tool-rec") && !doc.getElementById("tool-rec").disabled,
    3000, "启动后「开始录制」应可点"), "有受控设备时「开始录制」可点");
  doc.getElementById("tool-rec").click();
  ok(await waitFor(() => doc.getElementById("tool-rec-cancel") &&
    !doc.getElementById("tool-rec-cancel").disabled, 2000, "录制中取消可点"),
    "录制中「取消」可点");

  doc.getElementById("tool-rec-cancel").click();
  ok(await waitFor(() => /正在取消录制/.test(statusText(doc)), 2000, "取消即时反馈"),
    "点「取消」后要立刻落一条「正在取消录制…」（删除要好几秒，不能干等）");
  ok(calls === 1, "确认后应调用一次 screen_record_cancel");
  ok(doc.getElementById("tool-rec-cancel").disabled,
    "取消在途时按钮禁用（连点第二次只会撞上已清空的会话）");
  ok(doc.getElementById("tool-rec").disabled, "取消在途时「开始录制」也不可点");

  releaseCancel({ ok: true, removed: 2 });
  ok(await waitFor(() => !doc.getElementById("tool-rec").disabled, 2000, "取消后退回未录制态"),
    "取消完成后「开始录制」恢复可点");
  ok(doc.getElementById("tool-rec-cancel").disabled, "取消完成后「取消」回到不可点");
  ok(doc.getElementById("tool-rec-stop").disabled, "取消完成后「停止」也应不可点");

  console.log("\n==============================================");
  console.log("结果：" + pass + " 通过 / " + fail + " 失败");
  console.log("==============================================");
  process.exit(fail ? 1 : 0);
})();
