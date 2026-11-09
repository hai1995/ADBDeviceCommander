/* jsdom 前端行为测试：「内置」命令组平铺渲染（二级分组已撤）

   回归背景：「内置」组早年被切成六段二级分组（连接与投屏 / 显示辅助 /
   按键 / 屏幕状态 / 网络 / 应用与信息，各段可折叠 + 一键全折）。用户反馈
   层级太多、找命令反而费劲，已整体撤掉——内置组与其余分组一样直接平铺
   chips。这里锁定四件事：
   1) 内置组不再出现 .cmd-section / .cmd-fold-all / 段头徽章等段结构，
      全部卡片收在一个 .cmd-chips 容器里（与用户分组同构）；
   2) 组内的设备类型筛选条（全部 / 通用 / 车机 / 手机）保留且可用；
   3) 搜索仍能用 section 关键词命中（数据字段保留，仅不再参与分组）；
   4) 不再写 builtin_folded 偏好（功能删了，落盘也必须停）。
   样式侧另锁一条：.cmd-section 系列死样式不得残留。 */
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

function bi(id, name, section, scope) {
  const c = { id, name: "[内置] " + name, labels: ["内置"], commands: [{ command: "adb shell true", delay: 0 }],
           clickCount: 0, builtin: true, section };
  if (scope) c.scope = scope;
  return c;
}

const COMMANDS = [
  bi("bi.adb-status", "ADB连接状态", "连接与投屏", "车机"),
  bi("bi.scrcpy", "Scrcpy投屏", "连接与投屏", "车机"),
  bi("bi.pointer-on", "开启指针位置", "显示辅助"),
  bi("bi.touch-on", "开启触摸圆点", "显示辅助"),
  bi("bi.screen-off", "息屏", "按键"),
  bi("bi.key-home", "主页键", "按键"),
  bi("bi.rot-auto", "恢复自动旋转", "屏幕状态"),
  bi("bi.stayon-on", "充电时保持常亮", "屏幕状态"),
  bi("bi.wifi-on", "打开 WiFi", "网络"),
  bi("bi.wlan-ip", "查看 WLAN IP", "网络"),
  bi("bi.battery", "电池与温度信息", "应用与信息", "手机"),
  bi("bi.serial", "设备序列号", "应用与信息"),
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

const click = (doc, el) => el.dispatchEvent(
  new doc.defaultView.Event("click", { bubbles: true }));

const savedPrefs = (calls) =>
  calls.filter((c) => c.fn === "save_settings").map((c) => c.args[0]);

const biGroupOf = (doc) =>
  Array.from(doc.querySelectorAll("#cmd-groups .cmd-group"))
    .find((g) => {
      const t = g.querySelector(".cmd-group-title");
      return t && t.textContent.indexOf("内置") === 0;
    });

(async () => {
  // 看门狗：断言里抛错会被 unhandledRejection 吞掉，进程会因残留定时器而不退出，
  // 表现出来就是「测试挂住」。——超时按当前结果收尾，并明确标出是哪一段。
  const watchdog = setTimeout(() => {
    console.log("    (看门狗触发：疑似断言抛错导致未收尾，按当前结果退出)");
    process.exit(fail ? 1 : 0);
  }, 60000);

  console.log("[1] 样式：段结构死样式不得残留，scope 条仍在");
  ok(!/\.cmd-section[\s{.,:[]/.test(css), "app.css 已无 .cmd-section 系列规则");
  ok(!/\.cmd-fold-all/.test(css), "app.css 已无 .cmd-fold-all 规则");
  ok(/\.cmd-scope-bar\s*\{/.test(css), ".cmd-scope-bar 样式仍在（scope 筛选保留）");

  const { window, calls } = await boot();
  const doc = window.document;
  ok(await waitFor(() => doc.querySelectorAll("#cmd-groups .cmd-chip").length === 13,
                   4000, "13 张卡片"),
     "全部命令已渲染（12 条内置 + 1 条用户）");

  console.log("\n[2] 内置组平铺：无段结构，卡片收在一个 chips 容器里");
  {
    const biGroup = biGroupOf(doc);
    ok(!!biGroup, "「内置」一级分组仍在");
    ok(biGroup.querySelectorAll(".cmd-section").length === 0,
       "无 .cmd-section 段结构");
    ok(!doc.querySelector("#cmd-groups .cmd-fold-all"), "无「全部折叠」按钮");
    ok(!doc.querySelector("#cmd-groups .cs-n"), "无段头条数徽章");
    ok(biGroup.querySelectorAll(":scope > .cmd-chips").length === 1,
       "内置组只有一层 chips 容器（与用户分组同构）");
    const chips = biGroup.querySelectorAll(".cmd-chip");
    ok(chips.length === 12, "12 条内置全部平铺（实际 " + chips.length + "）");
    // 用户分组不出现段结构（保持原状）
    const usGroup = Array.from(doc.querySelectorAll("#cmd-groups .cmd-group"))
      .find((g) => (g.querySelector(".cmd-group-title") || {}).textContent === "通用");
    ok(!!usGroup && usGroup.querySelectorAll(".cmd-section").length === 0,
       "用户自定义分组仍是扁平 chips");
  }

  console.log("\n[3] scope 筛选条保留且可用");
  {
    const bar = biGroupOf(doc).querySelector(".cmd-scope-bar");
    ok(!!bar, "内置组带设备类型筛选条");
    const btns = Array.from(bar.querySelectorAll(".cmd-scope")).map((b) => b.textContent);
    ok(JSON.stringify(btns) === JSON.stringify(["全部", "通用", "车机", "手机"]),
       "筛选按钮为 全部/通用/车机/手机（实际：" + btns.join("/") + "）");
    const car = Array.from(bar.querySelectorAll(".cmd-scope"))
      .find((b) => b.textContent === "车机");
    click(doc, car);
    ok(await waitFor(() => biGroupOf(doc).querySelectorAll(".cmd-chip").length === 2,
                     3000, "车机 2 条"),
       "点「车机」只剩 2 条（adb-status / scrcpy，实际 "
       + biGroupOf(doc).querySelectorAll(".cmd-chip").length + "）");
    const all = Array.from(bar.querySelectorAll(".cmd-scope"))
      .find((b) => b.textContent === "全部");
    click(doc, all);
    ok(await waitFor(() => biGroupOf(doc).querySelectorAll(".cmd-chip").length === 12,
                     3000, "恢复 12 条"),
       "点「全部」恢复 12 条");
  }

  console.log("\n[4] 搜索仍能用 section 关键词命中（字段保留、不参与分组）");
  {
    const input = doc.getElementById("cmd-filter");
    input.value = "网络";              // 没有任何命令名含「网络」，只能靠 section 命中
    input.dispatchEvent(new window.Event("input", { bubbles: true }));
    ok(await waitFor(() => doc.querySelectorAll("#cmd-groups .cmd-chip").length === 2,
                     3000, "命中网络关键词"),
       "搜「网络」命中 2 条 WiFi 命令（实际 "
       + doc.querySelectorAll("#cmd-groups .cmd-chip").length + "）");
    ok(doc.querySelectorAll("#cmd-groups .cmd-section").length === 0,
       "命中结果也是平铺（不会冒出段结构）");
    input.value = "";
    input.dispatchEvent(new window.Event("input", { bubbles: true }));
    ok(await waitFor(() => doc.querySelectorAll("#cmd-groups .cmd-chip").length === 13,
                     3000, "清空恢复"), "清空关键字恢复全量");
  }

  console.log("\n[5] 不再写 builtin_folded 偏好");
  {
    // scope 切换会落 builtin_scope；此时不得顺带写 builtin_folded
    const writes = savedPrefs(calls);
    ok(writes.length > 0 && writes.every((w) => !("builtin_folded" in w)),
       "save_settings 调用中无 builtin_folded 键（共 " + writes.length + " 次落盘）");
  }

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
