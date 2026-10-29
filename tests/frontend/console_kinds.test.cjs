/* jsdom 前端测试：指令输出区的行类型配色（console kind -> CSS class）。

   回归背景：pushConsole 原先只把 "cmd" / "err" 映射成样式类，其余 kind 一律当
   普通输出。后端在「进入 / 退出交互式子 shell」时推的是 info —— 结果这两条说明
   白花花一片，跟命令回显混在一起，用户根本看不出「程序在提示我什么」。

   info / ok / warn 三个类在 CSS 里早就有（.out .line.info 等），只是 JS 没放行。
*/
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = "../../";
const html = fs.readFileSync(path.join(__dirname, ROOT, "frontend/index.html"), "utf8");
const js = fs.readFileSync(path.join(__dirname, ROOT, "frontend/js/app.js"), "utf8");
const css = fs.readFileSync(path.join(__dirname, ROOT, "frontend/css/app.css"), "utf8");

let pass = 0, fail = 0;
function ok(cond, name) {
  if (cond) { pass++; console.log("  ✓ " + name); }
  else { fail++; console.log("  ✗ " + name); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitFor(fn, ms = 8000, label = "") {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    let v = false; try { v = !!fn(); } catch (e) { v = false; }
    if (v) return true;
    await sleep(30);
  }
  console.log("    (waitFor 超时: " + label + ")");
  return false;
}

function launch(batches) {
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
  const { window } = dom;
  let round = 0;
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function () {
          if (k === "boot") return Promise.resolve({ version: "v-t", warnings: [], commands: [], adb: "adb" });
          if (k === "take_events") { const b = batches[round] || []; round++; return Promise.resolve(b); }
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  return { window, doc: window.document };
}

const dev = [{ serial: "A1", model: "Pixel", state: "device", ok: true, checked: true }];

function lines(doc) {
  return Array.from(doc.querySelectorAll("#console .line"));
}

(async () => {
  console.log("\n[1] 六种 kind 各自映射到对应的行样式");
  {
    const batch = [
      { kind: "console", payload: { kind: "cmd", text: "C:\\adb_ws> adb root" } },
      { kind: "console", payload: { kind: "out", text: "restarting adbd as root" } },
      { kind: "console", payload: { kind: "info", text: "ℹ 已进入交互式 shell" } },
      { kind: "console", payload: { kind: "ok", text: "✓ 完成" } },
      { kind: "console", payload: { kind: "warn", text: "⚠ 注意" } },
      { kind: "console", payload: { kind: "err", text: "✗ 失败" } },
    ];
    const { doc } = launch([[{ kind: "devices", payload: { items: dev } }], batch]);
    await waitFor(() => lines(doc).length === 6, 8000, "六行渲染");
    const cls = lines(doc).map((l) => l.className);
    ok(cls[0] === "line cmd", "cmd -> line.cmd（实际 " + cls[0] + "）");
    ok(cls[1] === "line", "out -> 无额外类（实际 " + cls[1] + "）");
    ok(cls[2] === "line info", "info -> line.info（实际 " + cls[2] + "）");
    ok(cls[3] === "line ok", "ok -> line.ok（实际 " + cls[3] + "）");
    ok(cls[4] === "line warn", "warn -> line.warn（实际 " + cls[4] + "）");
    ok(cls[5] === "line err", "err -> line.err（实际 " + cls[5] + "）");
  }

  console.log("\n[2] 未知 kind 不会带出奇怪的类名");
  {
    const batch = [
      { kind: "console", payload: { kind: "whatever", text: "x" } },
      { kind: "console", payload: { text: "无 kind" } },
    ];
    const { doc } = launch([[{ kind: "devices", payload: { items: dev } }], batch]);
    await waitFor(() => lines(doc).length === 2, 8000, "两行渲染");
    ok(lines(doc).every((l) => l.className === "line"),
       "未知 / 缺失 kind 一律按普通输出");
  }

  console.log("\n[3] 子 shell 的两条提示在指令台里可辨认");
  {
    const batch = [
      { kind: "console", payload: { kind: "cmd", text: "C:\\adb_ws> powershell" } },
      { kind: "console", payload: {
          kind: "info",
          text: "» 已进入交互式 shell：后续命令直接送入该子 shell，"
              + "输入 exit 可退出并恢复逐条执行" } },
      { kind: "console", payload: { kind: "cmd", text: "C:\\adb_ws> exit" } },
      { kind: "console", payload: { kind: "info", text: "« 已退出交互式子 shell，恢复逐条执行" } },
    ];
    const { doc } = launch([[{ kind: "devices", payload: { items: dev } }], batch]);
    await waitFor(() => lines(doc).length === 4, 8000, "四行渲染");
    const infos = lines(doc).filter((l) => l.classList.contains("info"));
    ok(infos.length === 2, "两条提示都是 info 行（实际 " + infos.length + "）");
    ok(infos[0].textContent.includes("已进入交互式 shell"), "进入提示文案");
    ok(infos[1].textContent.includes("已退出交互式子 shell"), "退出提示文案");
  }

  console.log("\n[4] 样式表里这些类都真有着色（否则映射了也白映射）");
  {
    ok(/\.out \.line\.info\s*\{/.test(css), ".line.info 有样式");
    ok(/\.out \.line\.ok\s*\{/.test(css), ".line.ok 有样式");
    ok(/\.out \.line\.warn\s*\{/.test(css), ".line.warn 有样式");
    ok(/\.out \.line\.cmd\s*\{/.test(css), ".line.cmd 有样式");
    ok(/\.out \.line\.err\s*\{/.test(css), ".line.err 有样式");
  }

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
