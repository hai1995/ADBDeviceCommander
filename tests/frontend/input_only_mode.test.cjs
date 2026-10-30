/* jsdom 前端行为测试：快捷命令的 electerm 仅输入模式（"inputOnly": true）

   需求：用户从 electerm 导出的快捷命令里带 "inputOnly": true 的条目，
   点击时只把命令文本填进指令输入框、由用户确认后手动「执行」，不直接下发。
   这里锁定三件事：
     1. inputOnly=true 的芯片带可识别的类与 tooltip；
     2. 点击它不调 run_command，输入框被填入命令文本（多条用 "; " 连接）；
     3. inputOnly=false / 缺失的普通命令点击后照旧直接执行。
   后端侧（normalize_commands / mark_booted 透传）由
   tests/test_load_commands.py 与 tests/test_backend_state.py 锁定。 */
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

async function boot(commands) {
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
  const { window } = dom;
  const calls = [];
  let round = 0;
  const batches = [
    [{ kind: "booted",
       payload: { version: "v-test", warnings: [], adb: "adb", commands } }],
  ];
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          calls.push({ fn: k, args });
          if (k === "boot") {
            return Promise.resolve({ version: "v-test", warnings: [], commands, adb: "adb" });
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

function chipOf(doc, text) {
  // 用 .chip-label 匹配芯片名：用户命令卡片内还有 kebab 弹出菜单
  // （复制/修改/删除），其文字会混入 chip.textContent，整串精确匹配会失败。
  return Array.from(doc.querySelectorAll("#cmd-groups .cmd-chip"))
    .find((c) => {
      const lbl = c.querySelector(".chip-label");
      return (lbl ? lbl.textContent : c.textContent) === text;
    });
}

const INPUT_ONLY = {
  id: "io1", name: "[通用] 仅输入改代理", labels: ["通用"], inputOnly: true,
  commands: [
    { command: "adb shell settings put global http_proxy 1.2.3.4:8080", delay: 0 },
    { command: "adb shell settings put global global_http_proxy 1.2.3.4:8080", delay: 0 },
  ],
  clickCount: 0, builtin: false,
};
const PLAIN = {
  id: "p1", name: "[通用] 直接执行", labels: ["通用"], inputOnly: false,
  commands: [{ command: "adb devices", delay: 0 }], clickCount: 0, builtin: false,
};

(async () => {
  const watchdog = setTimeout(() => {
    console.log("    (看门狗触发：疑似断言抛错导致未收尾)");
    process.exit(fail ? 1 : 0);
  }, 30000);
  console.log("[1] 样式表定义仅输入模式的芯片样式");
  ok(/\.cmd-chip--inputonly\b/.test(css), "app.css 定义了 .cmd-chip--inputonly");

  const { window, calls } = await boot([INPUT_ONLY, PLAIN]);
  const doc = window.document;
  ok(await waitFor(() => doc.querySelectorAll("#cmd-groups .cmd-chip").length === 2,
                   4000, "命令卡片"),
     "两条命令卡片已渲染");

  console.log("\n[2] inputOnly 芯片带类名 + tooltip，普通命令不带");
  {
    const io = chipOf(doc, "[通用] 仅输入改代理");
    const pl = chipOf(doc, "[通用] 直接执行");
    ok(!!io && !!pl, "两条命令都能按名字找到");
    if (io && pl) {
      ok(io.classList.contains("cmd-chip--inputonly"),
         "仅输入模式芯片带 cmd-chip--inputonly 类");
      ok(io.title.includes("仅输入"),
         "仅输入模式芯片的 tooltip 说明语义（实际：" + io.title + "）");
      ok(!pl.classList.contains("cmd-chip--inputonly"),
         "普通命令不带该样式");
    }
  }

  console.log("\n[3] 点击仅输入命令：只填输入框，不下发执行");
  {
    const io = chipOf(doc, "[通用] 仅输入改代理");
    io.click();
    await sleep(60);
    ok(!calls.some((c) => c.fn === "run_command"),
       "点击仅输入命令不得调用 run_command（实际调用：" +
       calls.map((c) => c.fn).join(",") + "）");
    const inp = doc.getElementById("cmd-input");
    ok(!!inp && inp.value ===
       "adb shell settings put global http_proxy 1.2.3.4:8080; "
       + "adb shell settings put global global_http_proxy 1.2.3.4:8080",
       "两条子命令以 \"; \" 连接填入输入框（实际：" + (inp && inp.value) + "）");
  }

  console.log("\n[4] 点击普通命令：照旧直接下发执行");
  {
    const pl = chipOf(doc, "[通用] 直接执行");
    pl.click();
    await sleep(60);
    const run = calls.find((c) => c.fn === "run_command");
    ok(!!run, "普通命令点击后调用 run_command");
    ok(run && run.args[0] === "p1", "run_command 收到该命令 id（实际：" +
       (run && run.args[0]) + "）");
  }

  console.log("\n[5] 输入框已有内容时，仅输入模式整体覆盖（不追加）");
  {
    const inp = doc.getElementById("cmd-input");
    inp.value = "adb shell pm list packages";
    const io = chipOf(doc, "[通用] 仅输入改代理");
    io.click();
    await sleep(60);
    ok(inp.value.startsWith("adb shell settings put global http_proxy"),
       "仅输入模式整体覆盖输入框内容（实际：" + inp.value.slice(0, 40) + "…）");
    ok(!inp.value.includes("pm list packages"),
       "不把旧内容拼接到新命令后面");
  }

  // 不调 window.close()：jsdom 在部分场景会挂起；直接 process.exit 结束进程。
  clearTimeout(watchdog);
  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
