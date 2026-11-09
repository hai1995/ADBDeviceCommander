/* jsdom 前端行为测试：内置命令的适用设备子标签（scope：通用 / 车机 / 手机）

   与 section（按用途分组）正交：section 回答「干什么用」，scope 回答「在哪类
   设备上有意义」。这里锁定五件事：
   1) 每条内置卡片带 scope 角标，用户自定义卡片不带；
   2) 「内置」组里有 全部 / 通用 / 车机 / 手机 一排筛选按钮，默认「全部」；
   3) 点「车机」后只剩车机命令，段结构跟着收窄（空段不占位），且筛选落盘
      config.json 的 builtin_scope；
   4) 启动时按 builtin_scope 还原（否则「记不住」等于没做）；
   5) 关键字搜索能命中 scope（记不住命令名时搜「手机」也能筛出那批）。
   样式侧另锁一条：三种角标各有对应的 CSS 类，只加 class 不写样式等于没做。 */
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
  const c = { id, name: "[内置] " + name, labels: ["内置"],
              commands: [{ command: "adb shell true", delay: 0 }],
              clickCount: 0, builtin: true, section };
  if (scope) c.scope = scope;
  return c;
}

// 通用（缺省）+ 车机 + 手机各来两条；含一条用户命令，验证角标不外溢
const COMMANDS = [
  bi("bi.scrcpy", "Scrcpy投屏", "连接与投屏"),            // 通用（后端不写 scope）
  bi("bi.root-adb", "root", "连接与投屏", "车机"),
  bi("bi.remount-adb", "remount", "连接与投屏", "车机"),
  bi("bi.screen-off", "息屏", "按键"),                    // 通用
  bi("bi.wake-unlock", "亮屏并上滑解锁", "按键", "手机"),
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

const chips = (doc) => Array.from(doc.querySelectorAll("#cmd-groups .cmd-chip"));
const chipByName = (doc, name) =>
  chips(doc).find((c) => (c.querySelector(".chip-label") || {}).textContent === name);
const scopeBtn = (doc, txt) =>
  Array.from(doc.querySelectorAll("#cmd-groups .cmd-scope"))
    .find((b) => b.textContent === txt);
const sectionNames = (doc) =>
  Array.from(doc.querySelectorAll("#cmd-groups .cmd-section"))
    .map((el) => el.dataset.section);
const click = (doc, el) => el.dispatchEvent(
  new doc.defaultView.Event("click", { bubbles: true }));
const savedPrefs = (calls) =>
  calls.filter((c) => c.fn === "save_settings").map((c) => c.args[0]);

(async () => {
  const watchdog = setTimeout(() => {
    console.log("    (看门狗触发：疑似断言抛错导致未收尾，按当前结果退出)");
    process.exit(fail ? 1 : 0);
  }, 60000);

  console.log("[1] 样式：三种角标与筛选条都有对应规则");
  ok(/\.cmd-scope-bar\s*\{/.test(css), "app.css 定义了 .cmd-scope-bar");
  ok(/\.chip-scope--comm\s*\{/.test(css), "通用角标 .chip-scope--comm");
  ok(/\.chip-scope--car\s*\{/.test(css), "车机角标 .chip-scope--car");
  ok(/\.chip-scope--phone\s*\{/.test(css), "手机角标 .chip-scope--phone");

  const { window, calls } = await boot();
  const doc = window.document;
  ok(await waitFor(() => chips(doc).length === 7, 4000, "7 张卡片"),
     "全部命令已渲染（6 条内置 + 1 条用户）");

  console.log("\n[2] 每条内置卡片带 scope 角标，缺省即「通用」");
  {
    const sc = (name) => {
      const c = chipByName(doc, name);
      const t = c && c.querySelector(".chip-scope");
      return t ? t.textContent : null;
    };
    ok(sc("[内置] Scrcpy投屏") === "通用", "未标 scope 的按「通用」显示（实际：" +
       sc("[内置] Scrcpy投屏") + "）");
    ok(sc("[内置] root") === "车机", "root 标「车机」");
    ok(sc("[内置] 亮屏并上滑解锁") === "手机", "上滑解锁标「手机」");
    const carChip = chipByName(doc, "[内置] root");
    ok(carChip.querySelector(".chip-scope").className.indexOf("chip-scope--car") >= 0,
       "车机角标用 --car 类");
    const userChip = chipByName(doc, "[通用] 我的命令");
    ok(!userChip.querySelector(".chip-scope"), "用户自定义卡片没有 scope 角标");
  }

  console.log("\n[3] 筛选条：全部 / 通用 / 车机 / 手机，默认「全部」");
  {
    const btns = Array.from(doc.querySelectorAll("#cmd-groups .cmd-scope"))
      .map((b) => b.textContent);
    ok(JSON.stringify(btns) === JSON.stringify(["全部", "通用", "车机", "手机"]),
       "四个筛选项（实际：" + btns.join(" / ") + "）");
    ok(scopeBtn(doc, "全部").classList.contains("active"), "默认「全部」高亮");
    ok(Array.from(doc.querySelectorAll("#cmd-groups .cmd-scope.active")).length === 1,
       "同一时刻只有一个筛选项高亮");
  }

  console.log("\n[4] 点「车机」：只剩车机命令，段结构跟着收窄，并落盘");
  {
    click(doc, scopeBtn(doc, "车机"));
    await sleep(80);
    const names = chips(doc).map((c) => c.querySelector(".chip-label").textContent);
    ok(names.length === 3, "2 条车机内置 + 1 条用户命令（实际 " + names.length + "）");
    ok(names.indexOf("[内置] root") >= 0 && names.indexOf("[内置] remount") >= 0,
       "两条车机命令都在");
    ok(names.indexOf("[内置] 息屏") < 0, "通用命令被筛掉");
    ok(JSON.stringify(sectionNames(doc)) === JSON.stringify(["连接与投屏"]),
       "只剩车机命令所在的「连接与投屏」段（实际：" + sectionNames(doc).join(" / ") + "）");
    ok(!doc.querySelector("#cmd-groups .cmd-fold-all"),
       "只剩一段时不显示「全部折叠」按钮");
    const w = savedPrefs(calls).filter((p) => "builtin_scope" in p).pop();
    ok(w && w.builtin_scope === "车机", "落盘 builtin_scope=车机（实际：" +
       (w || {}).builtin_scope + "）");
    ok(scopeBtn(doc, "车机").classList.contains("active"), "「车机」变为高亮");
    ok(!scopeBtn(doc, "全部").classList.contains("active"), "「全部」取消高亮");

    // 用户命令分组不受影响（它不属于内置组）
    ok(!!chipByName(doc, "[通用] 我的命令"), "用户分组照常展示");
  }

  console.log("\n[5] 点「手机」：手机命令 + 两段；再点「全部」恢复");
  {
    click(doc, scopeBtn(doc, "手机"));
    await sleep(80);
    const names = chips(doc).map((c) => c.querySelector(".chip-label").textContent);
    ok(names.length === 3, "2 条手机内置 + 1 条用户命令（实际 " + names.length + "）");
    ok(names.indexOf("[内置] 电池与温度信息") >= 0, "手机命令「电池与温度信息」在");
    ok(JSON.stringify(sectionNames(doc)) === JSON.stringify(["按键", "应用与信息"]),
       "段结构随 scope 收窄（实际：" + sectionNames(doc).join(" / ") + "）");

    click(doc, scopeBtn(doc, "全部"));
    await sleep(80);
    ok(chips(doc).length === 7, "「全部」恢复 7 张卡片");
    ok(sectionNames(doc).length === 3, "段结构恢复（实际 " + sectionNames(doc).length + " 段）");
    const last = savedPrefs(calls).filter((p) => "builtin_scope" in p).pop();
    ok(last && last.builtin_scope === "", "「全部」落盘空串");
  }

  console.log("\n[6] 启动时按 builtin_scope 还原");
  {
    window.close();
    const { window: w2 } = await boot({ settings: { builtin_scope: "手机" } });
    const d2 = w2.document;
    ok(await waitFor(() => chips(d2).length === 3, 4000, "只渲染 3 张"),
       "按保存的 scope 首屏就只渲染 3 张卡片");
    ok(scopeBtn(d2, "手机").classList.contains("active"), "「手机」按钮为高亮");
    const names = chips(d2).map((c) => c.querySelector(".chip-label").textContent);
    ok(names.indexOf("[内置] 息屏") < 0, "通用命令没有渲染出来");
    w2.close();
  }

  console.log("\n[7] 非法 builtin_scope 回退到「全部」");
  {
    const { window: w3 } = await boot({ settings: { builtin_scope: "平板" } });
    const d3 = w3.document;
    ok(await waitFor(() => chips(d3).length === 7, 4000, "7 张"),
       "手改坏的 scope 被忽略，按「全部」渲染");
    ok(scopeBtn(d3, "全部").classList.contains("active"), "回退后「全部」高亮");
    w3.close();
  }

  console.log("\n[8] 关键字搜索能命中 scope");
  {
    const { window: w4 } = await boot();
    const d4 = w4.document;
    await waitFor(() => chips(d4).length === 7, 4000, "7 张");
    const input = d4.getElementById("cmd-filter");
    input.value = "手机";               // 没有命令名 / 分组名含「手机」，只能靠 scope 命中
    input.dispatchEvent(new w4.Event("input", { bubbles: true }));
    ok(await waitFor(() => chips(d4).length === 2, 3000, "命中 2 条"),
       "搜「手机」命中 2 条手机专用命令（实际 " + chips(d4).length + "）");
    const names = chips(d4).map((c) => c.querySelector(".chip-label").textContent);
    ok(names.indexOf("[内置] 亮屏并上滑解锁") >= 0 &&
       names.indexOf("[内置] 电池与温度信息") >= 0, "命中的正是那两条");
    w4.close();
  }

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
