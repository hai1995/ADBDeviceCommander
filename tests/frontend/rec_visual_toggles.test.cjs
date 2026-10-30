/* jsdom 前端行为测试：录屏「指针位置 / 触摸圆点」开关
   需求：录屏处增加两个可视化开关，默认开启，便于回顾录像时直观感知操作位置。

   这里锁定：
     1. 两个开关默认勾选（HTML checked），文案可读；
     2. 点「开始录制」第 8/9 参透传两个勾选态（默认 true/true）；
     3. 取消勾选后下发 false/false；
     4. 录制启动后两个开关被锁定（防录制中改无效选项），停止后恢复可点；
     5. 启动失败（ok:false）时回滚为可编辑态。
   后端侧（pointer_location / show_touches 两个系统设置 overlay 的开启与恢复）由
   tests/test_backend_screen.py 与 tests/test_backend_controller.py 锁定。 */
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
    await sleep(40);
  }
  console.log("    (waitFor 超时: " + label + ")");
  return false;
}

/** 起一个带调用记录的假后端：一台受控设备 + 可配置 screen_record_start 返回值。 */
function mkEnv(startRes) {
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const calls = [];
  let round = 0;
  const batches = [
    [{ kind: "booted",
       payload: { version: "v-test", warnings: [], adb: "adb", commands: [],
                  settings: {} } },
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
          if (k === "screen_record_start") {
            return Promise.resolve(startRes || { ok: true, ts: "20261019_120000" });
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

const recStartCalls = (calls) => calls.filter((c) => c.fn === "screen_record_start");

/* 看门狗：本文件顶部的 process.on("unhandledRejection") 会把断言里抛出的错误静默
   吞掉，于是 async IIFE 中途夭折、末尾的 process.exit 永远执行不到；而 jsdom 的
   pretendToBeVisual 会持续喂定时器，进程就挂在这里不动了——曾让整套前端测试卡死
   40 分钟（元素 id 改名后断言扑空即触发）。到点强制按当前通过/失败数退出，
   让 run-all 继续往下跑并把失败如实暴露出来。 */
const WATCHDOG_MS = 30000;

(async () => {
  const watchdog = setTimeout(() => {
    console.log("    (看门狗触发：疑似断言抛错导致未收尾，按当前结果退出)");
    process.exit(fail ? 1 : 0);
  }, WATCHDOG_MS);
  console.log("\n[1] 两个开关默认勾选（回顾录像时最直观）");
  {
    const { window } = mkEnv();
    const doc = window.document;
    ok(await waitFor(() => !!doc.getElementById("tool-rec"), 3000, "页面就绪"),
       "录屏按钮存在");
    const sp = doc.getElementById("rec-pointer-location");
    const st = doc.getElementById("rec-show-touches");
    ok(!!sp && !!st, "两个开关复选框都存在");
    ok(sp.checked === true, "指针位置默认勾选");
    ok(st.checked === true, "触摸圆点默认勾选");
    ok(/指针位置/.test(sp.parentElement.textContent || ""),
       "指针位置文案可读（实际：" + (sp.parentElement.textContent || "").trim() + "）");
    ok(/触摸圆点/.test(st.parentElement.textContent || ""),
       "触摸圆点文案可读");
    ok(/恢复设备原设置/.test(doc.body.textContent),
       "提示文案说明触摸圆点会在停止时恢复原设置");
  }

  console.log("\n[2] 默认勾选态点「开始录制」：第 8/9 参透传 true/true");
  {
    const { window, calls } = mkEnv();
    const doc = window.document;
    ok(await waitFor(() => !doc.getElementById("tool-rec").disabled,
                     4000, "录屏按钮可点"),
       "有受控设备时「开始录制」可点");
    doc.getElementById("tool-rec").click();
    await sleep(120);
    const c = recStartCalls(calls).pop();
    ok(!!c, "点击后调用 screen_record_start");
    ok(c && c.args[7] === true,
       "第 8 参 pointer_location=true（实际：" + (c && c.args[7]) + "）");
    ok(c && c.args[8] === true,
       "第 9 参 show_touches=true（实际：" + (c && c.args[8]) + "）");
    // 录制中锁定
    ok(doc.getElementById("rec-pointer-location").disabled === true,
       "录制启动后指针位置被锁定");
    ok(doc.getElementById("rec-show-touches").disabled === true,
       "录制启动后触摸圆点被锁定");
    // 停止后恢复可点
    doc.getElementById("tool-rec-stop").click();
    await sleep(120);
    ok(doc.getElementById("rec-pointer-location").disabled === false,
       "停止录制后指针位置恢复可点");
    ok(doc.getElementById("rec-show-touches").disabled === false,
       "停止录制后触摸圆点恢复可点");
  }

  console.log("\n[3] 取消勾选后点「开始录制」：第 8/9 参透传 false/false");
  {
    const { window, calls } = mkEnv();
    const doc = window.document;
    ok(await waitFor(() => !doc.getElementById("tool-rec").disabled,
                     4000, "录屏按钮可点"),
       "有受控设备时「开始录制」可点");
    doc.getElementById("rec-pointer-location").click();
    doc.getElementById("rec-show-touches").click();
    await sleep(60);
    ok(doc.getElementById("rec-pointer-location").checked === false,
       "指针位置可被用户取消");
    ok(doc.getElementById("rec-show-touches").checked === false,
       "触摸圆点可被用户取消");
    doc.getElementById("tool-rec").click();
    await sleep(120);
    const c = recStartCalls(calls).pop();
    ok(c && c.args[7] === false,
       "第 8 参 pointer_location=false（实际：" + (c && c.args[7]) + "）");
    ok(c && c.args[8] === false,
       "第 9 参 show_touches=false（实际：" + (c && c.args[8]) + "）");
  }

  console.log("\n[4] 启动失败（ok:false）：回滚按钮态，不卡在「录制中」");
  {
    const { window, calls } = mkEnv({ ok: false, reason: "no_device" });
    const doc = window.document;
    ok(await waitFor(() => !doc.getElementById("tool-rec").disabled,
                     4000, "录屏按钮可点"),
       "有受控设备时「开始录制」可点");
    doc.getElementById("tool-rec").click();
    await sleep(120);
    ok(doc.getElementById("rec-pointer-location").disabled === false,
       "启动失败后指针位置不停在锁定态");
    ok(doc.getElementById("rec-show-touches").disabled === false,
       "启动失败后触摸圆点不停在锁定态");
    const statusText = doc.getElementById("status").textContent || "";
    ok(statusText.indexOf("录屏未能启动") >= 0,
       "状态信息提示启动失败（实际：" + statusText.trim() + "）");
    ok(statusText.indexOf("no_device") >= 0,
       "失败原因（no_device）透传给用户");
  }

  console.log("\n结果：" + pass + " 通过 / " + fail + " 失败");
  clearTimeout(watchdog);
  process.exit(fail ? 1 : 0);
})();
