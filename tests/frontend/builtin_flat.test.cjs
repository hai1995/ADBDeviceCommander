/* jsdom 前端行为测试：「内置」命令为扁平列表（顶部筛选 + 卡片小标签）

   曾经为了「49 条平铺两屏」，内置命令按用途做了二级分组、可折叠、一键全折。
   现在改成：顶部一排适用设备筛选（全部 / 通用 / 车机 / 手机）+ 一条扁平
   chips，每条卡片自带 通用 / 车机 / 手机 小标签。这里锁定四件事：
   1) 不再出现任何二级分组 / 折叠结构（.cmd-section、.cmd-fold-all 均无）；
   2) 「内置」组里只有一条 chips，条数 = 全部内置命令；
   3) 筛选条在 chips 之上，卡片小标签正确（用户自定义卡片不带）；
   4) 关键字仍可按用途名（后端 section）命中，分组去掉不丢搜索能力。 */
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

function bi(id, name, section, scope) {
  const c = { id, name: "[内置] " + name, labels: ["内置"],
              commands: [{ command: "adb shell true", delay: 0 }],
              clickCount: 0, builtin: true, section };
  if (scope) c.scope = scope;
  return c;
}

const COMMANDS = [
  bi("bi.adb-status", "ADB连接状态", "连接与投屏"),
  bi("bi.scrcpy", "Scrcpy投屏", "连接与投屏"),
  bi("bi.root-adb", "root", "连接与投屏", "车机"),
  bi("bi.pointer-on", "开启指针位置", "显示辅助"),
  bi("bi.touch-on", "开启触摸圆点", "显示辅助"),
  bi("bi.screen-off", "息屏", "按键"),
  bi("bi.wake-unlock", "亮屏并上滑解锁", "按键", "手机"),
  bi("bi.rot-auto", "恢复自动旋转", "屏幕状态"),
  bi("bi.stayon-on", "充电时保持常亮", "屏幕状态"),
  bi("bi.wifi-on", "打开 WiFi", "网络"),
  bi("bi.wlan-ip", "查看 WLAN IP", "网络"),
  bi("bi.battery", "电池与温度信息", "应用与信息", "手机"),
  { id: "u1", name: "[通用] 我的命令", labels: ["通用"],
    commands: [{ command: "git status", delay: 0 }], clickCount: 0, builtin: false },
];

async function boot(opts) {
  opts = opts || {};
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
  const { window } = dom;
  const calls = [];
  let round = 0;
  const settings = opts.settings || {};
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          calls.push({ fn: k, args });
          if (k === "boot") {
            return Promise.resolve({ version: "v-test", warnings: [], commands: COMMANDS,
                                     adb: "adb", settings });
          }
          if (k === "take_events") {
            const b = round === 0
              ? [{ kind: "booted",
                   payload: { version: "v-test", warnings: [], adb: "adb",
                              commands: COMMANDS, settings } }]
              : [];
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
  return { window, calls };
}

const chipsIn = (root) => Array.from(root.querySelectorAll(".cmd-chip"));
const builtinGroup = (doc) =>
  Array.from(doc.querySelectorAll("#cmd-groups .cmd-group")).find((g) => {
    const t = g.querySelector(".cmd-group-title");
    return t && t.textContent.indexOf("内置") === 0;
  });

(async () => {
  const watchdog = setTimeout(() => {
    console.log("    (看门狗触发：疑似断言抛错导致未收尾，按当前结果退出)");
    process.exit(fail ? 1 : 0);
  }, 60000);

  const { window } = await boot();
  const doc = window.document;
  ok(await waitFor(() => doc.querySelectorAll("#cmd-groups .cmd-chip").length === 13,
                   4000, "13 张卡片"),
     "全部命令已渲染（12 条内置 + 1 条用户）");

  console.log("\n[1] 不再有二级分组 / 折叠结构");
  {
    ok(doc.querySelectorAll("#cmd-groups .cmd-section").length === 0,
       "没有 .cmd-section 段结构");
    ok(doc.querySelectorAll("#cmd-groups .cmd-sections").length === 0,
       "没有 .cmd-sections 容器");
    ok(!doc.querySelector("#cmd-groups .cmd-fold-all"),
       "没有「全部折叠」按钮");
  }

  console.log("\n[2] 「内置」组只有一条扁平 chips");
  {
    const g = builtinGroup(doc);
    ok(!!g, "「内置」一级分组仍在");
    ok(g.querySelectorAll(".cmd-chips").length === 1, "只有一条 chips 容器");
    ok(chipsIn(g).length === 12, "12 条内置命令全部平铺（实际 " +
       chipsIn(g).length + "）");
  }

  console.log("\n[3] 筛选条在顶部，卡片带适用设备小标签");
  {
    const g = builtinGroup(doc);
    const bar = g.querySelector(".cmd-scope-bar");
    const chips = g.querySelector(".cmd-chips");
    ok(!!bar, "顶部有设备类型筛选条");
    ok(!!bar && !!chips && (bar.compareDocumentPosition(chips) &
       window.Node.DOCUMENT_POSITION_FOLLOWING) !== 0, "筛选条排在 chips 之前");
    const tagOf = (name) => {
      const c = chipsIn(g).find(
        (x) => (x.querySelector(".chip-label") || {}).textContent === name);
      const t = c && c.querySelector(".chip-scope");
      return t ? t.textContent : null;
    };
    ok(tagOf("[内置] Scrcpy投屏") === "通用", "未标 scope 的按「通用」显示");
    ok(tagOf("[内置] root") === "车机", "root 标「车机」");
    ok(tagOf("[内置] 电池与温度信息") === "手机", "电池信息标「手机」");
    ok(chipsIn(g).every((c) => !!c.querySelector(".chip-scope")),
       "每条内置卡片都带小标签");
    const userChip = chipsIn(doc).find(
      (c) => (c.querySelector(".chip-label") || {}).textContent === "[通用] 我的命令");
    ok(userChip && !userChip.querySelector(".chip-scope"),
       "用户自定义卡片不带适用设备小标签");
  }

  console.log("\n[4] 关键字仍可按用途名命中（分组去掉不丢搜索）");
  {
    const input = doc.getElementById("cmd-filter");
    input.value = "网络";              // 没有命令名含「网络」，只能靠 section 命中
    input.dispatchEvent(new window.Event("input", { bubbles: true }));
    ok(await waitFor(() => doc.querySelectorAll("#cmd-groups .cmd-chip").length === 2,
                     3000, "命中 2 条"),
       "搜「网络」命中该用途的 2 条（实际 " +
       doc.querySelectorAll("#cmd-groups .cmd-chip").length + "）");
  }

  window.close();
  clearTimeout(watchdog);
  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
