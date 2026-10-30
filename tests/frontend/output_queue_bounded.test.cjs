/* jsdom 前端行为测试：待渲染输出队列必须有上限（防「最小化后恢复」一次性插入几万行）

   回归点：pushLine 往 _outQueues 里无条件 push，而队列只由 requestAnimationFrame
   排空。窗口最小化时 WebView2 会节流 / 暂停 rAF，但 400ms 的事件轮询照常跑 —— 于是
   队列无限增长；恢复窗口的那一帧要一次性创建并插入几万个 DOM 节点（随后绝大多数又被
   trimHead 裁掉），形成一次数秒的同步长任务，界面直接卡死。

   修复：队列按容器限长（= 容器最终保留的行数 CONSOLE_MAX_LINES），超出丢弃最旧。
   多出来的行本来就会被裁掉，可见结果完全不变。

   本测试不测耗时（在 CI 上不稳定），而是统计「一次 flush 实际创建了多少个行节点」：
   没有限流时约等于压入的总行数，有限流时不会超过上限。 */
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

const BURST = 20000;      // 远超 CONSOLE_MAX_LINES(3000)

const BOOT_EVT = { kind: "booted",
                   payload: { version: "v-test", warnings: [], commands: [], adb: "adb" } };

// 大批状态事件一次性下发（模拟被节流期间积压的输出）
const BURST_EVTS = (() => {
  const out = [];
  for (let i = 0; i < BURST; i++) {
    out.push({ kind: "status", payload: { type: "info", text: "行 " + i } });
  }
  return out;
})();

(async () => {
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const doc = window.document;

  // 先把 rAF 换成「只记录回调、永不自动执行」，模拟最小化窗口时 rAF 被节流。
  // 必须在 eval(app.js) 之前装好，才能保证所有 pushLine 都堆在队列里。
  let rafCb = null;
  window.requestAnimationFrame = (cb) => { rafCb = cb; return 1; };

  // 统计行节点创建次数（flush 时真正的开销来源）
  const origCreate = doc.createElement.bind(doc);
  let created = 0;
  doc.createElement = (tag, ...rest) => {
    if (String(tag).toLowerCase() === "div") created++;
    return origCreate(tag, ...rest);
  };

  let round = 0;
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function () {
          if (k === "boot") {
            return Promise.resolve({ version: "v-test", warnings: [], commands: [], adb: "adb" });
          }
          if (k === "take_events") {
            round++;
            if (round === 1) return Promise.resolve([BOOT_EVT]);
            if (round === 2) return Promise.resolve(BURST_EVTS);
            return Promise.resolve([]);
          }
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(doc, "readyState", { value: "complete", configurable: true });
  window.eval(js);

  // 等第二批（20000 条）被处理完：全部压进队列，rAF 桩不会执行 flush
  const t0 = Date.now();
  while (round < 3 && Date.now() - t0 < 8000) await sleep(20);
  ok(round >= 3, "大批状态事件已被消费（全部压入待渲染队列，flush 尚未运行）");

  const status = doc.getElementById("status");
  ok(rafCb !== null, "存在待执行的 flush 回调（模拟 rAF 被节流）");

  const before = created;
  if (typeof rafCb === "function") {
    rafCb();                              // 手动触发那一帧 = 恢复窗口后的第一次重绘
  }
  const inserted = created - before;

  ok(status.childElementCount <= 3000,
     "状态区最终行数不超过 3000（实际 " + status.childElementCount + "）");
  ok(inserted <= 3200,
     "一次 flush 创建的行节点数受限（实际 " + inserted + "，未限流时约 " + BURST + "）");

  console.log("\n结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
