/* jsdom 前端行为测试：内置快捷命令的角标 / 提示

   回归背景：booted 载荷里的命令条目丢了 `builtin` 标记时，前端 `if (c.builtin)`
   恒为假 —— 内置命令的 .cmd-chip--builtin 角标样式与「程序内置默认…」提示永远
   不会出现，界面上一眼看不出哪些命令是程序自带的（靠名字里的 [内置] 前缀兜底）。
   后端侧由 tests/test_backend_state.py 锁定「builtin 必须随 payload 下发」，
   这里锁定前端确实消费了它。 */
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

const BUILTIN = {
  id: "bi.reboot", name: "[内置] 重启设备", labels: ["通用"],
  commands: [{ command: "adb reboot", delay: 0 }], clickCount: 0, builtin: true,
};
const USER = {
  id: "u1", name: "[通用] 我的命令", labels: ["通用"],
  commands: [{ command: "git status", delay: 0 }], clickCount: 0, builtin: false,
};

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
  // 按「芯片名」查找，而不是整张卡片的 textContent：用户自定义命令的卡片里
  // 还挂着 kebab 弹出菜单（复制/修改/删除），其文字会混进 textContent，导致
  // 精确匹配失败。芯片名单独放在 .chip-label 里，用它匹配才稳定。
  return Array.from(doc.querySelectorAll("#cmd-groups .cmd-chip"))
    .find((c) => {
      const lbl = c.querySelector(".chip-label");
      return (lbl ? lbl.textContent : c.textContent) === text;
    });
}

(async () => {
  console.log("[1] 样式表必须定义内置角标类（防止类名两边漂移）");
  ok(/\.cmd-chip--builtin\b/.test(css), "app.css 定义了 .cmd-chip--builtin");

  const { window } = await boot([BUILTIN, USER]);
  const doc = window.document;
  ok(await waitFor(() => doc.querySelectorAll("#cmd-groups .cmd-chip").length === 2,
                   4000, "命令卡片"),
     "两条命令卡片已渲染");

  console.log("\n[2] builtin:true 的命令带角标 + 提示，用户命令不带");
  {
    const bi = chipOf(doc, "[内置] 重启设备");
    const us = chipOf(doc, "[通用] 我的命令");
    ok(!!bi && !!us, "两条命令都能按名字找到");
    if (bi && us) {
      ok(bi.classList.contains("cmd-chip--builtin"),
         "内置命令带 cmd-chip--builtin 角标");
      ok(bi.title.includes("程序内置默认"),
         "内置命令的 tooltip 说明来源（实际：" + bi.title + "）");
      ok(!us.classList.contains("cmd-chip--builtin"),
         "用户命令不带内置角标");
    }
  }

  console.log("\n[3] 缺少 builtin 字段（老后端 / 手写 payload）不应误判为内置");
  {
    window.close();   // 先关掉上一段窗口：它的轮询/渲染定时器会拖慢下一段
    const { window: w2 } = await boot([
      { id: "x", name: "[通用] 无标记命令", labels: ["通用"],
        commands: [{ command: "adb devices", delay: 0 }] },
    ]);
    const d2 = w2.document;
    ok(await waitFor(() => d2.querySelectorAll("#cmd-groups .cmd-chip").length === 1,
                     4000, "单条命令"),
       "单条命令已渲染");
    const c = chipOf(d2, "[通用] 无标记命令");
    ok(!!c && !c.classList.contains("cmd-chip--builtin"),
       "没有 builtin 字段的命令不加角标");
    w2.close();
  }

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
