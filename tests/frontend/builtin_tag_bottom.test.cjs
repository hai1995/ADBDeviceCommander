/* jsdom 前端行为测试：内置命令独立成「内置」标签并恒置最底

   需求：快捷命令里的「内置」独立为一个标签，默认排在所有命令的最下方，
   避免 20 条程序默认命令冲掉用户自己的命令。这里锁定：
     1. 标签条（#cmd-tags）顺序：通用居首、其余标签按字母序居中、内置恒在最后；
     2. 分组渲染（#cmd-groups）同样把内置组排在最后；
     3. 点「内置」标签可单独过滤出内置命令（不丢过滤能力）。
   后端侧（BUILTIN_COMMANDS 的 labels 全部为「内置」、load_commands 并入后
   不污染用户的「通用」）由 tests/test_load_commands.py 锁定。 */
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

async function boot(commands) {
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
  const { window } = dom;
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
  return window;
}

// 用户命令（通用 + 设备）+ 两条内置：内置必须排最后
const CMDS = [
  { id: "u1", name: "[通用] 用户甲", labels: ["通用"], builtin: false,
    commands: [{ command: "adb devices", delay: 0 }], clickCount: 0 },
  { id: "u2", name: "[设备] 用户乙", labels: ["设备"], builtin: false,
    commands: [{ command: "adb shell getprop", delay: 0 }], clickCount: 0 },
  { id: "u3", name: "[应用] 用户丙", labels: ["应用"], builtin: false,
    commands: [{ command: "adb shell pm list packages", delay: 0 }], clickCount: 0 },
  { id: "bi.a", name: "[内置] 内置甲", labels: ["内置"], builtin: true,
    commands: [{ command: "adb reboot", delay: 0 }], clickCount: 0 },
  { id: "bi.b", name: "[内置] 内置乙", labels: ["内置"], builtin: true,
    commands: [{ command: "adb shell date", delay: 0 }], clickCount: 0 },
];

function tagTexts(doc) {
  return Array.from(doc.querySelectorAll("#cmd-tags .cmd-tag")).map((b) => b.textContent);
}
function groupTitles(doc) {
  return Array.from(doc.querySelectorAll("#cmd-groups .cmd-group-title"))
    .map((t) => t.textContent);
}

(async () => {
  console.log("[1] app.js 含内置置底排序逻辑（tagRank/byTagOrder）");
  ok(/function tagRank/.test(js) && /内置/.test(js),
     "app.js 定义了标签排序助手（通用居首、内置置底）");

  const window = await boot(CMDS);
  const doc = window.document;
  ok(await waitFor(() => doc.querySelectorAll("#cmd-groups .cmd-chip").length === 5,
                   4000, "命令卡片"),
     "五条命令卡片已渲染");

  console.log("\n[2] 标签条顺序：通用居首、其余居中、内置恒在最后");
  {
    const tags = tagTexts(doc);
    ok(tags[0] === "通用", "「通用」排在标签条最前（实际顺序：" + tags.join(" > ") + "）");
    ok(tags[tags.length - 1] === "内置",
       "「内置」排在标签条最后（实际顺序：" + tags.join(" > ") + "）");
    ok(tags.indexOf("内置") === tags.length - 1 && tags.indexOf("通用") === 0,
       "内置在通用之后、其余用户标签之后");
  }

  console.log("\n[3] 分组渲染顺序：内置组排在最后");
  {
    const groups = groupTitles(doc);
    ok(groups[groups.length - 1] === "内置",
       "内置分组在最后（实际顺序：" + groups.join(" > ") + "）");
    ok(groups[0] === "通用", "通用分组在最前");
  }

  console.log("\n[4] 点「内置」标签可单独过滤出内置命令");
  {
    const builtinTag = Array.from(doc.querySelectorAll("#cmd-tags .cmd-tag"))
      .find((b) => b.textContent === "内置");
    ok(!!builtinTag, "标签条里有「内置」标签按钮");
    if (builtinTag) {
      builtinTag.click();
      await sleep(60);
      const chips = Array.from(doc.querySelectorAll("#cmd-groups .cmd-chip"));
      ok(chips.length === 2, "过滤后只剩两条内置命令（实际 " + chips.length + "）");
      ok(chips.every((c) => c.textContent.indexOf("[内置]") === 0),
         "过滤结果都是内置命令");
    }
  }

  window.close();
  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
