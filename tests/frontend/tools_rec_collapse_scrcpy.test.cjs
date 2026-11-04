/* jsdom 前端行为测试：录屏面板（子 tab）+ 投屏（scrcpy）区块 + kebab 图标层级/尺寸

   本轮三件事：
     1. 命令卡右侧 kebab 小点点再缩小一点，且层级必须在 popup **之下**
        （此前 kebab 带 z-index 形成层叠上下文，后面卡片的点点会盖到 popup 上）；
     2. 工具页五项功能改为子 tab（截图 / 录屏 / 投屏 / 安装 / 诊断），点录屏子 tab
        切到录屏面板；并让「同步录制 logcat」「结束自动压缩为 zip」默认打开
        （logcat 现为全量，那行级别勾选已撤掉）；
     3. 工具页下方投屏区块：一键调用本机 scrcpy。

   后端侧（找 scrcpy / 拉进程 / 秒退原因）由 tests/test_backend_scrcpy.py 与
   tests/test_backend_controller.py 锁定；这里只锁前端结构与交互。 */
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

/** 假后端：booted.settings 可定制；scrcpy_* 返回可定制。 */
function mkEnv(opts) {
  opts = opts || {};
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const calls = [];
  let round = 0;
  const settings = opts.settings || {};
  const batches = [
    [{ kind: "booted",
       payload: { version: "v-test", warnings: [], adb: "adb", commands: [],
                  settings } },
     { kind: "devices",
       payload: { items: opts.noDevice ? [] :
                  [{ serial: "S1", model: "M", state: "device", ok: true, checked: true }] } }],
  ];
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          calls.push({ fn: k, args });
          if (k === "boot") {
            return Promise.resolve({ version: "v-test", warnings: [], commands: [], adb: "adb",
                                     settings });
          }
          if (k === "take_events") { const b = batches[round] || []; round++; return Promise.resolve(b); }
          if (k === "scrcpy_probe") {
            return Promise.resolve(opts.probe || {
              ok: true, path: "/usr/local/bin/scrcpy",
              version: "scrcpy 2.4 <https://github.com/Genymobile/scrcpy>",
              note: "来自系统 PATH",
            });
          }
          if (k === "scrcpy_start") {
            return Promise.resolve(opts.startRes || {
              ok: true, path: "/usr/local/bin/scrcpy",
              started: ["S1"], skipped: [], failed: [],
            });
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

const callsOf = (calls, fn) => calls.filter((c) => c.fn === fn);
const savedPatch = (calls, key) => {
  const hit = callsOf(calls, "save_settings").filter((c) => c.args[0] && key in c.args[0]);
  return hit.length ? hit[hit.length - 1].args[0][key] : undefined;
};
const subBtn = (doc, key) => doc.querySelector('.tool-subtab[data-tool-tab="' + key + '"]');
const pane = (doc, key) => doc.querySelector('.tool-pane[data-tool-pane="' + key + '"]');

/* 看门狗：断言抛错会被上面的 unhandledRejection 吞掉，jsdom 定时器又不停，
   进程会挂住（曾卡死整套前端测试）。到点按当前结果强制退出。 */
const WATCHDOG_MS = 30000;

(async () => {
  const watchdog = setTimeout(() => {
    console.log("    (看门狗触发：疑似断言抛错导致未收尾，按当前结果退出)");
    process.exit(fail ? 1 : 0);
  }, WATCHDOG_MS);

  console.log("\n[1] 两个录屏开关默认打开（同步 logcat / 结束自动压缩 zip）");
  {
    const { window } = mkEnv();
    const doc = window.document;
    ok(await waitFor(() => !!doc.getElementById("rec-logcat"), 3000, "页面就绪"),
       "录屏卡存在");
    ok(doc.getElementById("rec-logcat").checked === true, "「同步录制 logcat」默认勾选");
    ok(doc.getElementById("rec-zip").checked === true, "「结束录制后自动压缩为 zip」默认勾选");
    // 级别行已撤掉：随录屏的 logcat 一律全量（-b all + 不过滤级别），
    // 界面上不再有可勾的级别，也就没有"置灰初态"这回事了。
    ok(!doc.getElementById("rec-levels"), "级别复选框已撤掉");
    ok(!doc.getElementById("rec-lc-levels"), "级别行容器已撤掉");
  }

  console.log("\n[2] 点录屏子 tab 切到录屏面板（不再依赖折叠收起）");
  {
    const { window } = mkEnv();
    const doc = window.document;
    const btn = subBtn(doc, "rec");
    ok(await waitFor(() => !!btn, 3000, "子 tab"), "录屏子 tab 存在");
    ok(subBtn(doc, "shot").classList.contains("active"), "默认激活的是截图子 tab");
    ok(pane(doc, "shot").hidden === false, "默认截图面板可见");
    ok(pane(doc, "rec").hidden === true, "录屏面板初始 hidden");

    btn.click();
    await sleep(80);
    ok(subBtn(doc, "rec").classList.contains("active"), "点录屏子 tab → rec active");
    ok(subBtn(doc, "rec").getAttribute("aria-selected") === "true", "aria-selected 同步为 true");
    ok(pane(doc, "rec").hidden === false, "录屏面板显示");
    ok(pane(doc, "shot").hidden === true, "截图面板被隐藏（互斥切换）");
    ok(doc.getElementById("rec-card").classList.contains("collapsed") === false,
       "录屏卡不依赖 collapsed（子 tab 切面板，非折叠）");
  }

  console.log("\n[3] 键盘 Enter / 空格同样能切到录屏子 tab（可达性）");
  {
    const { window } = mkEnv();
    const doc = window.document;
    const btn = subBtn(doc, "rec");
    await waitFor(() => !!btn, 3000, "子 tab");
    btn.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await sleep(60);
    ok(subBtn(doc, "rec").classList.contains("active"), "Enter 切到录屏子 tab");
    ok(pane(doc, "rec").hidden === false, "录屏面板显示");
    subBtn(doc, "shot").dispatchEvent(new window.KeyboardEvent("keydown", { key: " ", bubbles: true }));
    await sleep(60);
    ok(subBtn(doc, "shot").classList.contains("active"), "空格切回截图子 tab");
  }

  console.log("\n[4] 启动默认激活截图子 tab（不再有 rec_collapsed 收起回填）");
  {
    const { window, calls } = mkEnv();
    const doc = window.document;
    ok(await waitFor(() => subBtn(doc, "shot"), 4000, "子 tab 就绪"),
       "子 tab 渲染完成");
    ok(subBtn(doc, "shot").classList.contains("active"), "默认截图子 tab active");
    ok(pane(doc, "shot").hidden === false, "截图面板可见");
    ok(pane(doc, "rec").hidden === true, "录屏面板初始 hidden");
    ok(doc.getElementById("rec-card").classList.contains("collapsed") === false,
       "录屏卡无 collapsed（折叠已移除）");
    ok(savedPatch(calls, "rec_collapsed") === undefined,
       "启动不写 rec_collapsed（折叠键已废弃）");
  }

  console.log("\n[5] 投屏区块：探测结果 + 未装 scrcpy 时的提示");
  {
    const { window } = mkEnv();
    const doc = window.document;
    ok(await waitFor(() => /已就绪/.test(doc.getElementById("scrcpy-state").textContent),
                     4000, "探测完成"),
       "探测成功时显示「已就绪」");
    const txt = doc.getElementById("scrcpy-state").textContent;
    ok(/2\.4/.test(txt), "显示版本号（实际：" + txt + "）");
    ok(/scrcpy/.test(txt), "显示实际使用的路径");
    ok(doc.getElementById("scrcpy-state").classList.contains("ok"), "成功态着色 .ok");
  }
  {
    const { window } = mkEnv({ probe: { ok: false, path: "", version: "",
                                        note: "未找到 scrcpy：可 winget install Genymobile.scrcpy" } });
    const doc = window.document;
    ok(await waitFor(() => /未找到/.test(doc.getElementById("scrcpy-state").textContent),
                     4000, "探测失败"),
       "未装时把安装指引显示出来（不是只写「未找到」三个字）");
    ok(doc.getElementById("scrcpy-state").classList.contains("err"), "失败态着色 .err");
  }

  console.log("\n[6] 投屏按钮：无设备禁用 / 有设备可点 / 点击调 scrcpy_start");
  {
    const { window } = mkEnv({ noDevice: true });
    const doc = window.document;
    await waitFor(() => /已就绪|未找到/.test(doc.getElementById("scrcpy-state").textContent),
                  4000, "探测完成");
    ok(doc.getElementById("tool-scrcpy").disabled === true, "没有受控设备时按钮禁用");
  }
  {
    const { window, calls } = mkEnv();
    const doc = window.document;
    ok(await waitFor(() => !doc.getElementById("tool-scrcpy").disabled, 4000, "按钮可点"),
       "有受控设备时按钮可点");
    doc.getElementById("tool-scrcpy").click();
    await sleep(150);
    const c = callsOf(calls, "scrcpy_start").pop();
    ok(!!c, "点击后调用后端 scrcpy_start");
    ok(c && c.args[0] === null, "第一参传 null（= 对全部受控设备投屏）");
    ok(/已开启 1 个投屏窗口/.test(doc.getElementById("scrcpy-state").textContent),
       "成功后面板显示已开启数量（实际：" + doc.getElementById("scrcpy-state").textContent + "）");
    ok(doc.getElementById("tool-scrcpy").disabled === false, "调用结束后按钮恢复可点");
  }

  console.log("\n[7] 投屏失败态：秒退原因写在按钮旁（不是「点了没反应」）");
  {
    const { window } = mkEnv({ startRes: {
      ok: false, path: "/usr/local/bin/scrcpy", started: [], skipped: [],
      failed: [{ serial: "S1", reason: "scrcpy 立即退出（退出码 1）：device unauthorized" }],
    } });
    const doc = window.document;
    await waitFor(() => !doc.getElementById("tool-scrcpy").disabled, 4000, "按钮可点");
    doc.getElementById("tool-scrcpy").click();
    await sleep(150);
    const t = doc.getElementById("scrcpy-state").textContent;
    ok(/unauthorized/.test(t), "显示 scrcpy 自己的报错（实际：" + t + "）");
  }

  console.log("\n[8] scrcpy 路径输入框：回填 + 失焦落盘");
  {
    const { window, calls } = mkEnv({ settings: { scrcpy_path: "D:\\tools\\scrcpy" } });
    const doc = window.document;
    const inp = doc.getElementById("scrcpy-path");
    ok(await waitFor(() => inp.value !== "", 3000, "路径回填"), "启动时回填上次的路径");
    ok(inp.value === "D:\\tools\\scrcpy", "回填值与配置一致（实际：" + inp.value + "）");
    inp.value = "C:\\scrcpy\\scrcpy.exe";
    inp.dispatchEvent(new window.Event("change", { bubbles: true }));
    await sleep(120);
    ok(savedPatch(calls, "scrcpy_path") === "C:\\scrcpy\\scrcpy.exe",
       "改动后落盘 scrcpy_path");
    ok(callsOf(calls, "scrcpy_probe").length >= 2, "改动后自动重新探测");
  }

  console.log("\n[9] CSS 回归：kebab 点点更小、层级低于 popup");
  {
    // kebab 本体所在规则块：不能带 z-index（否则形成层叠上下文，点点会盖住 popup）
    const m = css.match(/\.cmd-chip \.chip-kebab \{[^}]*\}/);
    ok(!!m, "找到 .cmd-chip .chip-kebab 规则");
    ok(m && !/z-index\s*:/.test(m[0]), "kebab 本体不设 z-index（层叠上下文修复）");
    ok(/\.cmd-chip \.chip-kebab\.is-open \{[^}]*z-index\s*:\s*30/.test(css),
       "展开态 is-open 抬到 z-index:30（兜底压住兄弟卡片）");
    const pop = css.match(/\.cmd-chip \.chip-popup \{[^}]*\}/);
    ok(pop && /z-index\s*:\s*20/.test(pop[0]), "popup 仍是 20，高于普通卡片");
    ok(pop && !/var\(--surface-1\)/.test(pop[0]),
       "popup 背景不再引用未定义的 --surface-1（防再次透明穿透）");

    const dot = css.match(/\.cmd-chip \.chip-kebab-dot svg \{[^}]*\}/);
    const size = dot && /width:\s*(\d+)px/.exec(dot[0]);
    ok(!!size, "找到点点图标尺寸规则");
    ok(size && Number(size[1]) <= 14,
       "三点点点比原来（16px）更小，实际 " + (size && size[1]) + "px");
  }

  console.log("\n[10] CSS：未激活面板隐藏；子 tab 选中态；投屏状态样式存在");
  {
    ok(/\.tool-pane\[hidden\]\s*\{\s*display:\s*none/.test(css),
       "未激活的子 tab 面板 [hidden] 隐藏");
    ok(/\.tool-subtab\.active\s*\{[^}]*var\(--accent\)/.test(css),
       "子 tab 选中态用磷光青");
    ok(/\.tool-subtab\.is-dragging\s*\{[^}]*opacity/.test(css),
       "拖动中的子 tab 降透明度");
    ok(/\.scrcpy-state\.ok/.test(css) && /\.scrcpy-state\.err/.test(css),
       "投屏状态的成功 / 失败配色存在");
  }

  clearTimeout(watchdog);
  console.log("\n==============================================");
  console.log("结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
