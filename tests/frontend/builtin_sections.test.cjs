/* jsdom 前端行为测试：「内置」命令的二级分组（section）+ 折叠

   49 条内置命令平铺要横跨两三屏，界面按 section 分成六段、每段可折叠。
   这里锁定六件事：
   1) 内置组被切成六段，顺序由前端 BUILTIN_SECTIONS 决定（与 section 名一一对应）；
   2) 每条命令只出现在自己那一段里，段头徽章数字等于该段条数；
   3) 点段头折叠 / 展开，且折叠状态写进 config.json（builtin_folded）；
   4) 启动时按 builtin_folded 还原折叠态（否则「记不住」等于没做）；
   5) 筛选（关键字）时强制展开 —— 命中项藏在折叠块里等于告诉用户「没找到」；
   6) 用户自定义分组仍是扁平的 chips，不受这套分组影响。
   样式侧另锁一条：折叠必须真的隐藏 chips（.is-folded .cmd-chips { display:none }），
   只加 class 不改样式是最容易漏的一步。 */
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

const SECTIONS = ["连接与投屏", "显示辅助", "按键", "屏幕状态", "网络", "应用与信息"];

function bi(id, name, section) {
  return { id, name: "[内置] " + name, labels: ["内置"], commands: [{ command: "adb shell true", delay: 0 }],
           clickCount: 0, builtin: true, section };
}

// 六段各来两条：够验证「分到哪一段」，也不至于让断言写成长列表
const COMMANDS = [
  bi("bi.adb-status", "ADB连接状态", "连接与投屏"),
  bi("bi.scrcpy", "Scrcpy投屏", "连接与投屏"),
  bi("bi.pointer-on", "开启指针位置", "显示辅助"),
  bi("bi.touch-on", "开启触摸圆点", "显示辅助"),
  bi("bi.screen-off", "息屏", "按键"),
  bi("bi.key-home", "主页键", "按键"),
  bi("bi.rot-auto", "恢复自动旋转", "屏幕状态"),
  bi("bi.stayon-on", "充电时保持常亮", "屏幕状态"),
  bi("bi.wifi-on", "打开 WiFi", "网络"),
  bi("bi.wlan-ip", "查看 WLAN IP", "网络"),
  bi("bi.battery", "电池与温度信息", "应用与信息"),
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

const sectionOf = (doc, name) =>
  Array.from(doc.querySelectorAll("#cmd-groups .cmd-section"))
    .find((el) => el.dataset.section === name);

const chipsIn = (doc, name) => {
  const sec = sectionOf(doc, name);
  return sec ? Array.from(sec.querySelectorAll(".cmd-chip")) : [];
};

const click = (doc, el) => el.dispatchEvent(
  new doc.defaultView.Event("click", { bubbles: true }));

const savedPrefs = (calls) =>
  calls.filter((c) => c.fn === "save_settings").map((c) => c.args[0]);

(async () => {
  // 看门狗：断言里抛错会被 unhandledRejection 吞掉，进程会因残留定时器而不退出，
  // 表现出来就是「测试挂住」。——超时按当前结果收尾，并明确标出是哪一段。
  const watchdog = setTimeout(() => {
    console.log("    (看门狗触发：疑似断言抛错导致未收尾，按当前结果退出)");
    process.exit(fail ? 1 : 0);
  }, 60000);

  console.log("[1] 样式：折叠必须真的隐藏 chips");
  ok(/\.cmd-section\.is-folded\s+\.cmd-chips\s*\{\s*display:\s*none/.test(css),
     ".is-folded .cmd-chips 设了 display:none");
  ok(/\.cmd-sections\s*\{/.test(css), "app.css 定义了 .cmd-sections 容器");

  const { window, calls } = await boot();
  const doc = window.document;
  ok(await waitFor(() => doc.querySelectorAll("#cmd-groups .cmd-chip").length === 13,
                   4000, "13 张卡片"),
     "全部命令已渲染（12 条内置 + 1 条用户）");

  console.log("\n[2] 内置组切成六段，顺序与 BUILTIN_SECTIONS 一致");
  {
    const heads = Array.from(doc.querySelectorAll("#cmd-groups .cmd-section-h .cs-name"))
      .map((el) => el.textContent);
    ok(heads.length === 6, "六个段头（实际 " + heads.length + "）");
    ok(JSON.stringify(heads) === JSON.stringify(SECTIONS),
       "段头顺序固定（实际：" + heads.join(" / ") + "）");
    // 注意用 indexOf 而不是 ===：标题里还挂着「全部折叠」按钮，textContent
    // 会是「内置全部折叠」，精确比较必然失败。
    const biGroup = Array.from(doc.querySelectorAll("#cmd-groups .cmd-group"))
      .find((g) => {
        const t = g.querySelector(".cmd-group-title");
        return t && t.textContent.indexOf("内置") === 0;
      });
    ok(!!biGroup, "「内置」一级分组仍在");
    ok(biGroup.querySelectorAll(".cmd-section").length === 6,
       "六段都挂在「内置」分组内");
    ok(!!doc.querySelector("#cmd-groups .cs-n"), "段头带条数徽章");
  }

  console.log("\n[3] 每条命令只出现在自己那一段");
  {
    ok(chipsIn(doc, "按键").length === 2, "「按键」2 条");
    ok(chipsIn(doc, "网络").length === 2, "「网络」2 条");
    const names = chipsIn(doc, "网络").map((c) => c.querySelector(".chip-label").textContent);
    ok(names.indexOf("[内置] 打开 WiFi") >= 0 && names.indexOf("[内置] 查看 WLAN IP") >= 0,
       "网络段里正是那两条 WiFi 命令（实际：" + names.join(" / ") + "）");
    const badge = sectionOf(doc, "网络").querySelector(".cs-n").textContent;
    ok(badge === "2", "段头徽章条数与实际一致（" + badge + "）");
    // 用户分组不出现段结构
    const usGroup = Array.from(doc.querySelectorAll("#cmd-groups .cmd-group"))
      .find((g) => (g.querySelector(".cmd-group-title") || {}).textContent === "通用");
    ok(!!usGroup && usGroup.querySelectorAll(".cmd-section").length === 0,
       "用户自定义分组仍是扁平 chips（无段结构）");
  }

  console.log("\n[4] 点段头折叠 / 展开，并落盘");
  {
    const sec = sectionOf(doc, "按键");
    const head = sec.querySelector(".cmd-section-h");
    ok(!sec.classList.contains("is-folded"), "默认展开");
    ok(head.getAttribute("aria-expanded") === "true", "aria-expanded=true");

    click(doc, head);
    await sleep(60);
    const sec2 = sectionOf(doc, "按键");
    ok(sec2.classList.contains("is-folded"), "点击后加 is-folded（chips 由 CSS 隐藏）");
    ok(sec2.querySelector(".cmd-section-h").getAttribute("aria-expanded") === "false",
       "aria-expanded 同步为 false");
    const writes = savedPrefs(calls).filter((p) => "builtin_folded" in p);
    ok(writes.length === 1, "落盘一次 save_settings（实际 " + writes.length + " 次）");
    ok(writes.length && writes[0].builtin_folded === "按键",
       "写入 builtin_folded=按键（实际：" + (writes[0] || {}).builtin_folded + "）");

    // 再点一次展开：值应回到空串
    click(doc, sectionOf(doc, "按键").querySelector(".cmd-section-h"));
    await sleep(60);
    ok(!sectionOf(doc, "按键").classList.contains("is-folded"), "再点一次展开");
    const last = savedPrefs(calls).filter((p) => "builtin_folded" in p).pop();
    ok(last && last.builtin_folded === "", "展开后写入空串（而不是留着旧值）");
  }

  console.log("\n[5] 启动时按 builtin_folded 还原");
  {
    window.close();
    const { window: w2 } = await boot({ settings: { builtin_folded: "按键,网络" } });
    const d2 = w2.document;
    ok(await waitFor(() => d2.querySelectorAll("#cmd-groups .cmd-section").length === 6,
                     4000, "六段渲染"),
       "内置六段已渲染");
    ok(sectionOf(d2, "按键").classList.contains("is-folded"), "「按键」还原为折叠");
    ok(sectionOf(d2, "网络").classList.contains("is-folded"), "「网络」还原为折叠");
    ok(!sectionOf(d2, "显示辅助").classList.contains("is-folded"), "未列的段仍展开");
    w2.close();
  }

  console.log("\n[6] 筛选时强制展开（命中项不能被折叠藏起来）");
  {
    const { window: w3 } = await boot({ settings: { builtin_folded: "按键" } });
    const d3 = w3.document;
    await waitFor(() => d3.querySelectorAll("#cmd-groups .cmd-section").length === 6,
                 4000, "六段渲染");
    ok(sectionOf(d3, "按键").classList.contains("is-folded"), "先处于折叠态");
    const input = d3.getElementById("cmd-filter");
    input.value = "息屏";
    input.dispatchEvent(new w3.Event("input", { bubbles: true }));
    ok(await waitFor(() => {
      const s = sectionOf(d3, "按键");
      return s && !s.classList.contains("is-folded");
    }, 3000, "筛选后展开"), "输入关键字后折叠段自动展开");
    const hits = d3.querySelectorAll("#cmd-groups .cmd-chip");
    ok(hits.length === 1, "只剩命中的 1 条（实际 " + hits.length + "）");
    ok(/息屏/.test(hits[0].textContent), "命中的正是「息屏」");
    // 清空关键字后回到折叠态
    input.value = "";
    input.dispatchEvent(new w3.Event("input", { bubbles: true }));
    ok(await waitFor(() => sectionOf(d3, "按键").classList.contains("is-folded"),
                     3000, "清空后折回"), "清空关键字后恢复原来的折叠态");
    w3.close();
  }

  console.log("\n[7] 一键全折 / 全展");
  {
    const { window: w4, calls: c4 } = await boot();
    const d4 = w4.document;
    await waitFor(() => d4.querySelectorAll("#cmd-groups .cmd-section").length === 6,
                 4000, "六段渲染");
    const btn = d4.querySelector(".cmd-fold-all");
    ok(!!btn, "「内置」组标题里有 .cmd-fold-all");
    ok(btn.textContent === "全部折叠", "默认文案是「全部折叠」（当前全展开）");
    click(d4, btn);
    await sleep(60);
    ok(d4.querySelectorAll("#cmd-groups .cmd-section.is-folded").length === 6,
       "一键后六段全部折叠");
    const w1 = savedPrefs(c4).filter((p) => "builtin_folded" in p).pop();
    ok(w1 && w1.builtin_folded.split(",").length === 6,
       "六段名字一次落盘（实际：" + (w1 || {}).builtin_folded + "）");
    ok(d4.querySelector(".cmd-fold-all").textContent === "全部展开",
       "按钮文案翻转为「全部展开」");
    click(d4, d4.querySelector(".cmd-fold-all"));
    await sleep(60);
    ok(d4.querySelectorAll("#cmd-groups .cmd-section.is-folded").length === 0,
       "再点一次六段全部展开");
    const w2 = savedPrefs(c4).filter((p) => "builtin_folded" in p).pop();
    ok(w2 && w2.builtin_folded === "", "全展后落盘空串");
    w4.close();
  }

  console.log("\n[8] 搜索能命中二级分组名");
  {
    const { window: w5 } = await boot();
    const d5 = w5.document;
    await waitFor(() => d5.querySelectorAll("#cmd-groups .cmd-section").length === 6,
                 4000, "六段渲染");
    const input = d5.getElementById("cmd-filter");
    input.value = "网络";              // 没有任何命令名含「网络」，只能靠 section 命中
    input.dispatchEvent(new w5.Event("input", { bubbles: true }));
    ok(await waitFor(() => d5.querySelectorAll("#cmd-groups .cmd-chip").length === 2,
                     3000, "命中网络段"),
       "搜「网络」命中该段 2 条（实际 " +
       d5.querySelectorAll("#cmd-groups .cmd-chip").length + "）");
    const secs = Array.from(d5.querySelectorAll("#cmd-groups .cmd-section"));
    ok(secs.length === 1 && secs[0].dataset.section === "网络",
       "只剩「网络」一段（空段不占位）");
    w5.close();
  }

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
