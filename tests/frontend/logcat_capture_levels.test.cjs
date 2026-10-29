/* jsdom 前端行为测试：Logcat 落盘抓取的级别过滤控件（录屏那处已撤掉）

   需求：抓取 log 时可定义日志等级（V/D/I/W/E/F），默认全选 = 全量。
   这里锁定：
     1. 抓取卡级别行存在，6 个复选框默认全选，点击「开始抓取」第 4 参为 6 级；
     2. 取消勾选两个级别后，下发的是剩余 4 级（顺序保持 V/D/I/W/E/F）；
     3. 录屏卡的级别行已撤掉：随录屏的 logcat 一律全量，界面上不再有这个旋钮；
     4. 点「开始录制」第 7 参固定 null（后端据此不过滤），音频 / 麦克风固定 false。
   后端侧（worker 按级别写盘、None/[] 语义、录屏恒用 -b all）由
   tests/test_backend_logcat.py 与 tests/test_backend_controller.py 锁定。 */
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

const LEVELS = ["V", "D", "I", "W", "E", "F"];

async function boot() {
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
  const { window } = dom;
  const calls = [];
  let round = 0;
  const batches = [
    [{ kind: "booted",
       payload: { version: "v-test", warnings: [], adb: "adb", commands: [] } },
     // 一台受控设备：抓取/录屏按钮的可用性依赖它
     { kind: "devices",
       payload: { items: [{ serial: "S1", model: "M", state: "device",
                            ok: true, checked: true }] } }],
  ];
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          calls.push({ fn: k, args });
          if (k === "boot") {
            return Promise.resolve({ version: "v-test", warnings: [], commands: [], adb: "adb" });
          }
          if (k === "take_events") { const b = batches[round] || []; round++; return Promise.resolve(b); }
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  return { window, calls };
}

function checkedLevels(doc, containerId) {
  return Array.from(
    doc.querySelectorAll("#" + containerId + " input:checked")).map((c) => c.value);
}

(async () => {
  console.log("[1] CSS：抓取级别行仍走小尺寸开关体系；录屏级别行已撤掉");
  ok(/#lc-cap-levels input\[type="checkbox"\]/.test(css),
     "抓取级别行命中密集场景小尺寸变体");
  ok(!/rec-levels/.test(css),
     "录屏级别行的样式已随控件删除（不留死样式）");
  ok(!/rec-lc-levels/.test(css),
     "录屏级别行的 .off 置灰态也一并删除");

  const { window, calls } = await boot();
  const doc = window.document;

  console.log("\n[2] 抓取卡级别控件：默认全选，下发为第 4 参");
  ok(await waitFor(() => !doc.getElementById("lc-cap-start").disabled,
                   4000, "抓取按钮可点"),
     "有受控设备时「开始抓取」可点");
  {
    const boxes = Array.from(doc.querySelectorAll("#lc-cap-levels input"));
    ok(boxes.length === 6, "抓取级别共 6 个复选框（实际 " + boxes.length + "）");
    ok(checkedLevels(doc, "lc-cap-levels").join("") === "VDIWEF",
       "默认全选（实际：" + checkedLevels(doc, "lc-cap-levels").join("") + "）");
    doc.getElementById("lc-cap-start").click();
    await sleep(80);
    const c = calls.find((x) => x.fn === "logcat_capture_start");
    ok(!!c, "点击后调用 logcat_capture_start");
    ok(c && Array.isArray(c.args[3]) && c.args[3].join("") === "VDIWEF",
       "第 4 参为全量级别数组（实际：" + (c && c.args[3]) + "）");

    // 取消 I/W，重新开一次抓取：先停掉上一台（同一串口会 already_running）
    doc.getElementById("lc-cap-stop").click();
    await sleep(80);
    const ibox = Array.from(doc.querySelectorAll("#lc-cap-levels input"))
      .find((x) => x.value === "I");
    const wbox = Array.from(doc.querySelectorAll("#lc-cap-levels input"))
      .find((x) => x.value === "W");
    ibox.click(); wbox.click();
    doc.getElementById("lc-cap-start").click();
    await sleep(80);
    const c2 = calls.filter((x) => x.fn === "logcat_capture_start").pop();
    ok(c2 && c2.args[3].join("") === "VDEF",
       "取消 I/W 后下发剩余级别（实际：" + (c2 && c2.args[3]) + "）");
  }

  console.log("\n[3] 录屏卡不再有级别控件：只留一个「同步录制 logcat」开关");
  {
    const lcBox = doc.getElementById("rec-logcat");
    ok(lcBox && lcBox.checked, "「同步录制 logcat」默认已勾选");
    ok(!doc.getElementById("rec-levels"), "级别复选框整行已撤掉");
    ok(!doc.getElementById("rec-lc-levels"), "级别行容器也已撤掉（不留空壳）");
  }

  console.log("\n[4] 开始录屏：第 7 参固定 null（全量），音频两项固定 false");
  {
    doc.getElementById("tool-rec").click();
    await sleep(120);
    const c = calls.find((x) => x.fn === "screen_record_start");
    ok(!!c, "点击「开始录制」调用 screen_record_start");
    // 参数序：serial, with_devaudio, with_mic, save_dir, with_logcat,
    //         zip_on_stop, logcat_levels, pointer, touches
    ok(c && c.args[6] === null,
       "第 7 参 logcat_levels = null（后端据此不过滤，实际：" +
       (c ? JSON.stringify(c.args[6]) : "-") + "）");
    ok(c && c.args[1] === false && c.args[2] === false,
       "设备音频 / 电脑麦克风固定 false（功能未实现，不给后端留错觉）");
    ok(doc.getElementById("rec-logcat").disabled === true, "录制中开关被锁定");
    doc.getElementById("tool-rec-stop").click();
    await sleep(120);
    ok(doc.getElementById("rec-logcat").disabled === false, "停止后开关解锁");
  }

  window.close();
  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
