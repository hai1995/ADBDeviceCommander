/* jsdom 前端测试：录屏「停止录制 / 取消录制」+ 二次确认弹窗 + 分段提示沉底
   —— ① 按钮名要带「录制」二字：「停止」「取消」单独挂在这里，脱离上下文会被
         误读成「停止刷新」「取消选择」；
      ② 「取消录制」删掉的东西没有回收站，且紧挨着「停止录制」，必须先过一道
         **应用内**二次确认弹窗：用户点「否」时一个后端调用都不许发；
      ③ 那大段「约每 3 分钟自动分段」说明是**说明**不是操作：它在操作区块
         （按钮 + 开关）下方，别再把「开始录制」挤到屏幕下半截。
   回归背景：以前「录错了」唯一出口是「停止」——它一定走合成 / 打包，用户拿到
   一个「✓ 已打包」的 zip，还得自己去目录里一个个删。
   为什么弹窗必须是自绘而不是 window.confirm：pywebview 各版本对 confirm 的
   支持并不一致，在部分版本里它返回 undefined，于是 `!confirm(...)` 恒为 true ——
   点「取消录制」会一声不响地什么都不做。文件末尾有一条专门盯着这件事的断言。 */
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
const confirmShown = (doc) => {
  const m = doc.getElementById("confirm-modal");
  return !!m && !m.classList.contains("hidden");
};
const key = (win, k, extra) => {
  win.document.dispatchEvent(new win.KeyboardEvent("keydown",
    Object.assign({ key: k, bubbles: true, cancelable: true }, extra || {})));
};

function boot(overrides, opts) {
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const queue = [];
  let round = 0;
  // 让用例能把后端事件塞进轮询队列（模拟录制被中断、状态跳变）
  window.__push = (ev) => queue.push(ev);
  window.__nativeConfirmCalls = 0;
  // 打桩成「有调用就记账」：末尾那条断言靠它来证明代码根本没走原生 confirm。
  // 返回值给 true 是故意的 —— 万一有人改回 confirm，流程会继续走删除分支，
  // 「弹窗没出现」这条断言就会立刻炸，而不是被一个 false 悄悄盖住。
  window.confirm = () => { window.__nativeConfirmCalls += 1; return true; };
  // 模拟「裁剪过的界面 / 版本错配的 index.html」：确认弹窗节点根本不存在
  if (opts && opts.stripConfirm) {
    const m = window.document.getElementById("confirm-modal");
    if (m) m.remove();
  }
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
            return Promise.resolve(queue.splice(0, queue.length));
          }
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  return window;
}

/* 进到「录制中」：等设备就绪 → 点开始 → 等取消键亮起。 */
async function startRecording(win) {
  const doc = win.document;
  const ready = await waitFor(() => doc.getElementById("tool-rec") &&
    !doc.getElementById("tool-rec").disabled, 3000, "启动后「开始录制」应可点");
  if (!ready) return false;
  doc.getElementById("tool-rec").click();
  return await waitFor(() => doc.getElementById("tool-rec-cancel") &&
    !doc.getElementById("tool-rec-cancel").disabled, 2500, "录制中取消可点");
}

/* 看门狗：断言里踩到 null（旧界面根本没有这些节点）会抛错，异常又被
   unhandledRejection 吞掉、jsdom 的定时器又不会停 —— 进程会一直挂着。
   到点按当前结果退出，保证失败是「失败」而不是「卡死」。 */
const watchdog = setTimeout(() => {
  console.log("    (看门狗触发：疑似断言抛错导致未收尾)");
  process.exit(fail ? 1 : 0);
}, 40000);
watchdog.unref && watchdog.unref();

(async () => {
  // ---------- 1) 静态：按钮存在、文案、初始不可点 ----------
  const d0 = new JSDOM(html);
  const doc0 = d0.window.document;
  const cancel0 = doc0.getElementById("tool-rec-cancel");
  const stop0 = doc0.getElementById("tool-rec-stop");
  ok(!!cancel0, "录屏卡必须有「取消录制」按钮");
  ok((cancel0 && cancel0.textContent.trim()) === "取消录制",
    "按钮文案是「取消录制」而不是光秃秃的「取消」（实际："
    + (cancel0 && cancel0.textContent.trim()) + "）");
  ok((stop0 && stop0.textContent.trim()) === "停止录制",
    "按钮文案是「停止录制」而不是「停止」（实际："
    + (stop0 && stop0.textContent.trim()) + "）");
  ok(cancel0 && cancel0.disabled === true, "未录制时「取消录制」不可点（没有会话可取消）");
  ok(cancel0 && /删除/.test(cancel0.getAttribute("title") || ""),
    "悬停提示要写明会删除文件（不能让人以为只是中止）");
  ok(cancel0 && cancel0.getAttribute("data-icon") === "trash",
    "取消用垃圾桶图标，与「停止录制」的方块图标区分开");
  const row = cancel0 && cancel0.parentElement;
  ok(row && row.classList.contains("tool-row"), "取消与开始/停止同一行（操作区块）");
  // 配色：警示色（琥珀），刻意不是 .danger —— 录制中「停止录制」本身就是红块呼吸，
  // 两键同色等于没区分，用户照样点错。
  ok(cancel0 && cancel0.classList.contains("warn"),
    "取消用警示色 .warn（与停止的中性灰 / 红区分开）");
  ok(cancel0 && !cancel0.classList.contains("danger"),
    "取消不能是 .danger：会与录制中的「停止录制」撞色");
  ok(/\.btn\.warn\s*\{/.test(css),
    "样式表里确实定义了 .btn.warn（否则 class 加了也是灰的）");
  ok(/\.btn\.warn:hover\s*\{/.test(css), ".btn.warn 有 hover 态（不然像禁用）");
  ok(/\.btn\.warn:disabled/.test(css), ".btn.warn 有禁用态（否则灰不掉，看着一直可点）");
  ok(stop0 && !stop0.classList.contains("warn"),
    "「停止录制」不用警示色（保留红色 = 当前运行态的语义）");
  // 三个按钮都带「录制」：名字本身要说清动作落在什么上，不能靠上下文补
  ok(["tool-rec", "tool-rec-stop", "tool-rec-cancel"].every((id) => {
    const el = doc0.getElementById(id);
    return el && /录制/.test(el.textContent);
  }), "三个按钮的名字里都带「录制」，单独看也说得清");

  // ---------- 2) 静态：二次确认弹窗就位且默认隐藏 ----------
  const modal0 = doc0.getElementById("confirm-modal");
  ok(!!modal0, "界面里必须有确认弹窗节点（缺了它，取消就只能静默放弃）");
  ok(modal0 && modal0.classList.contains("hidden"), "确认弹窗默认隐藏（不能一进来就挡住界面）");
  ok(modal0 && modal0.getAttribute("role") === "dialog"
    && modal0.getAttribute("aria-modal") === "true",
    "弹窗按 dialog 语义声明（读屏软件才知道这是个模态框）");
  const yes0 = doc0.getElementById("confirm-yes");
  const no0 = doc0.getElementById("confirm-no");
  ok(!!yes0 && !!no0, "弹窗里既有「是」也有「否」");
  // 「是」与「否」的位置：否在前、是在后（右手惯性落点是末位，别把删除放那儿）
  ok(no0 && yes0 && no0.nextElementSibling === yes0,
    "「否」排在「是」前面（末位是默认的手掌落点，不该放删除）");
  ok(/\.confirm-modal\s*\{[^}]*z-index:\s*60/.test(css),
    "确认弹窗的 z-index 压在普通弹窗之上（否则从别的弹窗里叫它时点了没反应）");
  ok(/\.confirm-box\s*\{[^}]*width:\s*440px/.test(css),
    "确认框是窄框（不能沿用 .modal-box 的 80%，那看着像内容弹窗）");

  // ---------- 3) 静态：分段提示语沉到操作区块下方 ----------
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
  ok(/60\s*秒/.test(hint.textContent) && /合并/.test(hint.textContent)
     && /重启/.test(hint.textContent),
    "提示语内容本身不能丢（60 秒 / 合并 / 重启分别保存仍要写明）");

  // ---------- 4) 点「取消录制」→ 弹窗出现，焦点在「否」，一个请求都没发 ----------
  {
    let cancelCalls = 0;
    const win = boot({ screen_record_cancel: () => { cancelCalls++; return Promise.resolve({ ok: true }); } });
    const doc = win.document;
    ok(await startRecording(win), "进入录制中");
    ok(!confirmShown(doc), "没点之前弹窗不该自己冒出来");

    doc.getElementById("tool-rec-cancel").click();
    ok(await waitFor(() => confirmShown(doc), 1500, "弹窗出现"), "点「取消录制」后弹出确认框");
    ok(cancelCalls === 0, "弹窗刚出现时不许有任何后端调用（还没确认）");
    ok(doc.getElementById("confirm-no") === doc.activeElement,
      "默认焦点在「否」上（顺手一个回车不该删数据）");
    ok(/删除/.test(doc.getElementById("confirm-text").textContent),
      "弹窗正文要写清会删除（不能只说「确定取消吗」）");
    ok(/停止录制/.test(doc.getElementById("confirm-text").textContent),
      "正文要指出想保留就点「停止录制」——用户常常只是选错了按钮");
    ok(doc.getElementById("confirm-yes").classList.contains("warn"),
      "「是」用警示色（这个动作会丢东西）");

    // ---------- 5) 点「否」→ 关窗、零调用、按钮仍可点 ----------
    doc.getElementById("confirm-no").click();
    await sleep(80);
    ok(!confirmShown(doc), "点「否」后弹窗关闭");
    ok(cancelCalls === 0, "点「否」时一个后端调用都不许发（误点不能删数据）");
    ok(!doc.getElementById("tool-rec-cancel").disabled, "放弃取消后按钮仍可点");
    ok(win.__nativeConfirmCalls === 0, "全程没有调用原生 window.confirm");
  }

  // ---------- 6) Esc / 点遮罩 / 点 × 全都等于「否」 ----------
  {
    let cancelCalls = 0;
    const win = boot({ screen_record_cancel: () => { cancelCalls++; return Promise.resolve({ ok: true }); } });
    const doc = win.document;
    await startRecording(win);

    // Esc
    doc.getElementById("tool-rec-cancel").click();
    await waitFor(() => confirmShown(doc), 1500, "弹窗出现");
    key(win, "Escape");
    await sleep(60);
    ok(!confirmShown(doc), "按 Esc 关闭弹窗");
    ok(cancelCalls === 0, "Esc = 否，不删任何东西");

    // 点遮罩（弹窗自身而不是白框）
    doc.getElementById("tool-rec-cancel").click();
    await waitFor(() => confirmShown(doc), 1500, "弹窗再次出现");
    doc.getElementById("confirm-modal").click();
    await sleep(60);
    ok(!confirmShown(doc), "点空白遮罩关闭弹窗");
    ok(cancelCalls === 0, "点遮罩 = 否，不删任何东西");

    // 点 ×
    doc.getElementById("tool-rec-cancel").click();
    await waitFor(() => confirmShown(doc), 1500, "弹窗第三次出现");
    doc.getElementById("confirm-x").click();
    await sleep(60);
    ok(!confirmShown(doc), "点右上角 × 关闭弹窗");
    ok(cancelCalls === 0, "点 × = 否，不删任何东西");
  }

  // ---------- 7) Esc 只回答这个弹窗，不顺手关掉背后的状态面板 ----------
  {
    const win = boot({});
    const doc = win.document;
    await startRecording(win);
    const ticker = doc.getElementById("status-ticker");
    if (ticker) ticker.click();
    await sleep(80);
    const statusOpen = doc.getElementById("status-modal")
      && !doc.getElementById("status-modal").classList.contains("hidden");
    if (!statusOpen) {
      console.log("    (状态面板没打开，跳过这条)");
    } else {
      doc.getElementById("tool-rec-cancel").click();
      await waitFor(() => confirmShown(doc), 1500, "弹窗出现");
      key(win, "Escape");
      await sleep(60);
      ok(!confirmShown(doc), "Esc 关掉确认弹窗");
      ok(!doc.getElementById("status-modal").classList.contains("hidden"),
        "背后的状态面板不受牵连（一次 Esc 只该关一层）");
    }
  }

  // ---------- 8) 点「是」→ 恰好一次调用 + 即时反馈 + 在途锁定 + 收尾复位 ----------
  let releaseCancel;
  const pending = new Promise((r) => { releaseCancel = r; });
  let calls = 0;
  {
    const win = boot({ screen_record_cancel: () => { calls++; return pending; } });
    const doc = win.document;
    await startRecording(win);

    doc.getElementById("tool-rec-cancel").click();
    await waitFor(() => confirmShown(doc), 1500, "弹窗出现");
    doc.getElementById("confirm-yes").click();
    ok(await waitFor(() => /正在取消录制/.test(statusText(doc)), 2000, "取消即时反馈"),
      "点「是」后要立刻落一条「正在取消录制…」（删除要好几秒，不能干等）");
    ok(calls === 1, "确认后应调用一次 screen_record_cancel（实际 " + calls + "）");
    ok(!confirmShown(doc), "点「是」后弹窗立即关闭（不能停在原地等后端）");
    ok(doc.getElementById("tool-rec-cancel").disabled,
      "取消在途时按钮禁用（连点第二次只会撞上已清空的会话）");
    ok(doc.getElementById("tool-rec").disabled, "取消在途时「开始录制」也不可点");

    releaseCancel({ ok: true, removed: 2 });
    ok(await waitFor(() => !doc.getElementById("tool-rec").disabled, 2000, "取消后退回未录制态"),
      "取消完成后「开始录制」恢复可点");
    ok(doc.getElementById("tool-rec-cancel").disabled, "取消完成后「取消录制」回到不可点");
    ok(doc.getElementById("tool-rec-stop").disabled, "取消完成后「停止录制」也应不可点");
  }

  // ---------- 9) 连点两次「取消录制」：只发一次删除请求 ----------
  {
    let c2 = 0;
    const win = boot({ screen_record_cancel: () => { c2++; return Promise.resolve({ ok: true }); } });
    const doc = win.document;
    await startRecording(win);

    doc.getElementById("tool-rec-cancel").click();
    doc.getElementById("tool-rec-cancel").click();   // 手抖的第二下
    await sleep(120);
    ok(c2 === 0, "两次点击都还停在确认阶段，一个请求都没发");
    doc.getElementById("confirm-yes").click();
    await sleep(200);
    ok(c2 === 1, "确认后只发一次删除请求（实际 " + c2 + "）");
  }

  // ---------- 10) 弹窗开着时录制自己结束了 ----------
  {
    let c3 = 0;
    const win = boot({ screen_record_cancel: () => { c3++; return Promise.resolve({ ok: true }); } });
    const doc = win.document;
    await startRecording(win);

    doc.getElementById("tool-rec-cancel").click();
    await waitFor(() => confirmShown(doc), 1500, "弹窗出现");
    // 设备拔线 / 进程死亡 / 摸到 20 段上限：后端广播 running=false
    win.__push({ kind: "rec_state", payload: { running: false } });
    ok(await waitFor(() => doc.getElementById("tool-rec-cancel").disabled, 2500, "录制结束"),
      "录制自己结束后「取消录制」置灰");
    doc.getElementById("confirm-yes").click();
    await sleep(200);
    ok(c3 === 0, "会话已经没了，不该再向后端要「取消」（否则只换回一句 no_session）");
    ok(!/取消录屏失败/.test(statusText(doc)),
      "也不该把「已经结束」报成「取消录屏失败」");
    ok(/无需取消|已经结束/.test(statusText(doc)), "要说明一句「已经结束，没有需要取消的内容」");
  }

  // ---------- 11) 界面里根本没有确认弹窗时：默认判否 ----------
  {
    let c4 = 0;
    const win = boot({ screen_record_cancel: () => { c4++; return Promise.resolve({ ok: true }); } },
      { stripConfirm: true });
    const doc = win.document;
    await startRecording(win);
    doc.getElementById("tool-rec-cancel").click();
    await sleep(200);
    ok(c4 === 0, "没有确认弹窗时绝不擅自删除（宁可什么都不做）");
    ok(/确认弹窗|无法确认/.test(statusText(doc)),
      "并且要说出原因（沉默地什么都不做 = 用户以为按钮坏了）："
      + statusText(doc));
  }

  // ---------- 12) 全程不依赖原生 window.confirm ----------
  {
    let c5 = 0;
    const win = boot({ screen_record_cancel: () => { c5++; return Promise.resolve({ ok: true }); } });
    const doc = win.document;
    await startRecording(win);
    doc.getElementById("tool-rec-cancel").click();
    await waitFor(() => confirmShown(doc), 1500, "弹窗出现");
    doc.getElementById("confirm-yes").click();
    await sleep(200);
    ok(c5 === 1, "走完整条取消流程");
    ok(win.__nativeConfirmCalls === 0,
      "全程一次都没碰 window.confirm（pywebview 里它可能返回 undefined，"
      + "那会让「取消」变成点了没反应）");
  }

  console.log("\n==============================================");
  console.log("结果：" + pass + " 通过 / " + fail + " 失败");
  console.log("==============================================");
  process.exit(fail ? 1 : 0);
})();
