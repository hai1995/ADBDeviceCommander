/* jsdom 前端行为测试：Logcat 监控——后台设备事件不污染前台 UI + 清空后计数从零起算

   两个回归点：
   1) 设备移除回收 / 双监控竞态时，后台设备的 running/stopped/error 事件也会
      推过来 —— 旧实现无条件重置全局按钮态与状态文案，会把前台正在监控的
      界面错误拨回「空闲」（停止按钮禁用、日志还在滚），再被新一轮 running
      拨回「采集中」，来回闪烁。修复后：lcSerial 已锁定且事件 serial 不是它
      时，只发 pushStatus 提示、不动前台 UI。
   2) 「清空」只重置前端缓冲，后端 worker 的 total/exc 是**会话累计值**且不会
      归零 —— 旧实现清空后直接拿 append 里的累计 total 回填计数，第一条新
      日志一到，计数跳回清空前的数字（视图空了、计数却很大）。修复后按
      清空基线折算，显示「清空后」的行数；重启监控（新 worker，total 从 0
      起算）时基线一并归零。 */
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
    await sleep(20);
  }
  console.log("    (waitFor 超时: " + label + ")");
  return false;
}

function mkEnv(batches) {
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  let round = 0;
  const calls = [];
  const queue = [];                       // 运行期追加的事件批次
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          calls.push({ fn: String(k), args });
          if (k === "boot") {
            return Promise.resolve({ version: "v-test", warnings: [], commands: [], adb: "adb" });
          }
          if (k === "take_events") {
            const b = round < batches.length ? batches[round] : queue.shift() || [];
            round++;
            return Promise.resolve(b);
          }
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  return { window, calls, doc: window.document, push: (b) => queue.push(b) };
}

const dev = (serial, checked) => ({ serial, model: "Pixel", state: "device", ok: true, checked });
function click(window, el) { el.dispatchEvent(new window.Event("click", { bubbles: true })); }
const lcEv = (payload) => ({ kind: "logcat", payload });

(async () => {
  console.log("\n[1] 后台设备的 running/stopped/error 不污染前台监控 UI");
  {
    const { window, doc, push } = mkEnv([
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
       { kind: "devices", payload: { items: [dev("A1", true)] } }],
    ]);
    await waitFor(() => doc.getElementById("lc-dev").textContent === "设备: A1", 4000, "设备联动");
    const start = doc.getElementById("lc-start");
    const stop = doc.getElementById("lc-stop");
    click(window, start);
    await waitFor(() => doc.getElementById("lc-status").textContent === "采集中…", 4000, "采集中");
    ok(doc.getElementById("lc-status").textContent === "采集中…", "监控 A1 已开始");

    // 后台设备 B2 的三个会话事件依次推来
    push([lcEv({ serial: "B2", status: "stopped" })]);
    await waitFor(() => Array.from(doc.querySelectorAll("#status .line"))
      .some((d) => false) || true, 100, "等事件消费");
    await sleep(500);
    ok(doc.getElementById("lc-status").textContent === "采集中…",
       "后台 stopped 不把前台拨回「空闲」（实际：" + doc.getElementById("lc-status").textContent + "）");
    ok(stop.disabled === false && start.disabled === true, "按钮态不被后台 stopped 重置");

    push([lcEv({ serial: "B2", status: "running" })]);
    await sleep(500);
    ok(doc.getElementById("lc-status").textContent === "采集中…",
       "后台 running 不覆盖前台状态");
    ok(doc.getElementById("lc-stop").classList.contains("danger") === true,
       "停止按钮保持监控中的红色样式");

    push([lcEv({ serial: "B2", status: "error", text: "后台设备出错" })]);
    await sleep(500);
    ok(doc.getElementById("lc-status").textContent === "采集中…",
       "后台 error 不覆盖前台状态");
    ok(Array.from(doc.querySelectorAll("#status .line"))
       .some((d) => d.textContent.includes("后台设备出错")),
       "后台 error 仍以状态栏提示告知（不吞消息）");

    // 当前设备的 stopped 仍要正常复位 UI
    push([lcEv({ serial: "A1", status: "stopped", total: 0, exc: 0 })]);
    await waitFor(() => doc.getElementById("lc-status").textContent === "空闲", 4000, "复位空闲");
    ok(doc.getElementById("lc-status").textContent === "空闲", "当前设备的 stopped 正常复位 UI");
    ok(stop.disabled === true && start.disabled === false, "按钮态随当前设备会话结束复位");
  }

  console.log("\n[2] 清空后计数从零起算：不被后端会话累计 total 冲回");
  {
    const { window, doc, push } = mkEnv([
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
       { kind: "devices", payload: { items: [dev("A1", true)] } }],
    ]);
    await waitFor(() => doc.getElementById("lc-dev").textContent === "设备: A1", 4000, "设备联动");
    click(window, doc.getElementById("lc-start"));
    await waitFor(() => doc.getElementById("lc-status").textContent === "采集中…", 4000, "采集中");

    const ln = (msg) => ({ raw: "08-29 10:00:00.000  100  100 I Tag: " + msg,
                           level: "I", tag: "Tag", msg: msg, pid: "100", tid: "100", exc: false });
    push([lcEv({ serial: "A1", status: "append", lines: [ln("a"), ln("b")], total: 100, exc: 3 })]);
    await waitFor(() => doc.getElementById("lc-counter").textContent.includes("行数: 100"), 4000, "累计计数");
    ok(doc.getElementById("lc-counter").textContent.includes("行数: 100"),
       "清空前显示会话累计（实际：" + doc.getElementById("lc-counter").textContent + "）");

    // 清空：按钮点击（本地重置 + 后端 clear 事件）
    click(window, doc.getElementById("lc-clear"));
    await waitFor(() => doc.getElementById("lc-counter").textContent.includes("行数: 0"), 4000, "清零");
    ok(doc.getElementById("lc-counter").textContent.includes("行数: 0"),
       "清空后计数归零（实际：" + doc.getElementById("lc-counter").textContent + "）");

    // 清空后第一条 append 仍带会话累计 total=105（不是从 0 重新累计）
    push([lcEv({ serial: "A1", status: "append", lines: [ln("c"), ln("d"), ln("e"), ln("f"), ln("g")],
                 total: 105, exc: 3 })]);
    await sleep(600);
    ok(doc.getElementById("lc-counter").textContent.includes("行数: 5"),
       "清空后计数按基线折算为 5，不跳回 105（实际：" + doc.getElementById("lc-counter").textContent + "）");
    ok(doc.getElementById("lc-counter").textContent.includes("异常: 0"),
       "异常计数同样按基线折算（实际：" + doc.getElementById("lc-counter").textContent + "）");

    // 后端 clear 事件到达（晚于本地点击）：重复记基线不得再折损
    push([lcEv({ serial: "A1", status: "clear" })]);
    await sleep(300);
    push([lcEv({ serial: "A1", status: "append", lines: [ln("h")], total: 110, exc: 3 })]);
    await sleep(600);
    ok(doc.getElementById("lc-counter").textContent.includes("行数: 5"),
       "二次清空基线取累计口径，计数仍正确（实际：" + doc.getElementById("lc-counter").textContent + "）");
  }

  console.log("\n[3] 重启监控（新会话）：基线归零，新会话计数从 0 起算");
  {
    const { window, doc, push } = mkEnv([
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
       { kind: "devices", payload: { items: [dev("A1", true)] } }],
    ]);
    await waitFor(() => doc.getElementById("lc-dev").textContent === "设备: A1", 4000, "设备联动");
    click(window, doc.getElementById("lc-start"));
    await waitFor(() => doc.getElementById("lc-status").textContent === "采集中…", 4000, "采集中");
    const ln = (msg) => ({ raw: "08-29 10:00:00.000  100  100 I Tag: " + msg,
                           level: "I", tag: "Tag", msg: msg, pid: "100", tid: "100", exc: false });
    push([lcEv({ serial: "A1", status: "append", lines: [ln("a")], total: 80, exc: 1 })]);
    await waitFor(() => doc.getElementById("lc-counter").textContent.includes("行数: 80"), 4000, "累计");
    // 停止 → 重新开始：新一轮 worker 的 total 从 0 重新累计
    click(window, doc.getElementById("lc-stop"));
    await sleep(300);
    click(window, doc.getElementById("lc-start"));
    await waitFor(() => doc.getElementById("lc-status").textContent === "采集中…", 4000, "重新采集中");
    push([lcEv({ serial: "A1", status: "append", lines: [ln("b")], total: 2, exc: 0 })]);
    await sleep(600);
    ok(doc.getElementById("lc-counter").textContent.includes("行数: 2"),
       "新会话 total 从 0 起算、旧基线不吃掉计数（实际：" + doc.getElementById("lc-counter").textContent + "）");
  }

  console.log("\n结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
