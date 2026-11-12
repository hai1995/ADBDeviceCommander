/* jsdom 前端行为测试：Logcat 过滤预设（保存 / 应用 / 覆盖 / 删除 / 启动恢复）

   预设存的是**过滤表达式文本**（config.json 的 lc_presets，JSON 字符串），
   不存级别 / 仅异常。核心回归：
     * 保存当前表达式并在下拉里出现；
     * 切换预设立刻回填表达式；
     * 同名保存要二次确认，确认后覆盖而不是新增；
     * 删除要二次确认，删完落盘；
     * 重启后按配置恢复，且表达式与预设一致时下拉自动选上；
     * 手改表达式后下拉退回「（无）」，避免「显示是预设 A、实际条件已变」。 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.join(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "frontend/index.html"), "utf8");
const js = fs.readFileSync(path.join(ROOT, "frontend/js/app.js"), "utf8");

process.on("unhandledRejection", () => {});

let pass = 0, fail = 0;
function ok(cond, name, extra) {
  if (cond) { pass++; console.log("  ✓ " + name); }
  else { fail++; console.log("  ✗ " + name + (extra ? "（" + extra + "）" : "")); }
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

// 记录所有 save_settings 的 patch：预设必须真的落盘，否则重启就丢
let savedPatches = [];

function mkEnv(settings) {
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  let round = 0;
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function () {
          if (k === "boot") return Promise.resolve({ ok: true });
          if (k === "save_settings") {
            savedPatches.push(arguments[0] || {});
            return Promise.resolve({ ok: true });
          }
          if (k === "take_events") {
            const b = round++ === 0
              ? [{ kind: "booted", payload: {
                    version: "v-test", warnings: [], commands: [],
                    settings: settings || {},
                  } }]
              : [];
            return Promise.resolve(b);
          }
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  return { window, doc: window.document };
}

async function boot(settings) {
  savedPatches = [];
  const { window, doc } = mkEnv(settings);
  // 必须等 booted 事件真正被处理（顶部状态变成「已就绪」），否则 HTML 里自带的
  // 「（无）」选项会让断言抢在配置恢复之前跑起来。
  await waitFor(() => doc.getElementById("pill").textContent === "已就绪",
                6000, "booted");
  // 分步加载：预设下拉（#lc-preset）属于 Logcat 页的数据，启动时**不**加载，
  // 切到 Logcat 页时才恢复。所以本文件的每个用例都要先切过去。
  switchTab(doc, "logcat");
  return { window, doc };
}

// 切到指定的主 tab（与用户点页签同一条路径：switchMainTab → prepareTab）
function switchTab(doc, key) {
  const btn = doc.querySelector('.tab-btn[data-tab="' + key + '"]');
  if (btn) btn.click();
}

function typeFilter(window, doc, kw) {
  const filter = doc.getElementById("lc-filter");
  filter.value = kw;
  filter.dispatchEvent(new window.Event("input", { bubbles: true }));
}
const lastPresetPatch = () => {
  const list = savedPatches.filter((p) => Object.prototype.hasOwnProperty.call(p, "lc_presets"));
  return list.length ? JSON.parse(list[list.length - 1].lc_presets) : null;
};

(async () => {
  console.log("\n[1] 保存当前表达式为预设");
  {
    const { window, doc } = await boot({});
    const sel = doc.getElementById("lc-preset");
    const kw = "pkg:com.demo.app -tag:Noise";
    typeFilter(window, doc, kw);
    await sleep(420);          // 输入防抖 250ms
    doc.getElementById("lc-preset-save").click();
    const opened = await waitFor(
      () => !doc.getElementById("input-modal").classList.contains("hidden"), 3000, "名称弹窗");
    ok(opened, "点「存为预设」弹出名称输入框");
    doc.getElementById("input-field").value = "我的应用";
    doc.getElementById("input-yes").click();
    await waitFor(() => sel.options.length === 2, 2000, "预设出现在下拉");
    ok(sel.options.length === 2, "下拉里新增一条预设", sel.options.length + " 项");
    ok(sel.options[1] && sel.options[1].textContent === "我的应用", "预设名称正确");
    const saved = lastPresetPatch();
    ok(saved && saved.length === 1 && saved[0].kw === kw,
       "表达式已落盘（save_settings.lc_presets）", JSON.stringify(saved));
    ok(doc.getElementById("lc-preset-del").disabled === false,
       "选中预设后「删除」按钮可用");
  }

  console.log("\n[2] 切换预设 → 回填表达式");
  {
    const { window, doc } = await boot({
      lc_presets: JSON.stringify([{ name: "崩溃与错误", kw: "level:EF" }]),
    });
    const filter = doc.getElementById("lc-filter");
    filter.value = "";
    typeFilter(window, doc, "");
    await sleep(420);
    const sel = doc.getElementById("lc-preset");
    sel.value = "0";
    sel.dispatchEvent(new window.Event("change", { bubbles: true }));
    await sleep(80);
    ok(filter.value === "level:EF", "表达式被预设覆盖", filter.value);
    ok(sel.value === "0", "下拉仍停在刚选的预设");
  }

  console.log("\n[3] 同名保存需要确认，确认后覆盖而不是新增");
  {
    const { window, doc } = await boot({
      lc_presets: JSON.stringify([{ name: "我的应用", kw: "tag:A" }]),
    });
    typeFilter(window, doc, "tag:B");
    await sleep(420);
    doc.getElementById("lc-preset-save").click();
    await waitFor(() => !doc.getElementById("input-modal").classList.contains("hidden"), 2000, "名称弹窗");
    doc.getElementById("input-field").value = "我的应用";
    doc.getElementById("input-yes").click();
    const asked = await waitFor(
      () => !doc.getElementById("confirm-modal").classList.contains("hidden"), 2000, "覆盖确认");
    ok(asked, "同名保存弹出覆盖确认");
    doc.getElementById("confirm-yes").click();
    await waitFor(() => {
      const s = lastPresetPatch();
      return s && s.length === 1 && s[0].kw === "tag:B";
    }, 2000, "覆盖落盘");
    const saved = lastPresetPatch();
    ok(saved && saved.length === 1, "预设数量仍为 1（覆盖而非新增）", JSON.stringify(saved));
    ok(saved && saved[0].kw === "tag:B", "内容已更新为当前表达式");
  }

  console.log("\n[4] 删除预设需要确认，删完落盘");
  {
    const { window, doc } = await boot({
      lc_presets: JSON.stringify([{ name: "A", kw: "tag:A" }]),
    });
    const sel = doc.getElementById("lc-preset");
    sel.value = "0";
    sel.dispatchEvent(new window.Event("change", { bubbles: true }));
    await sleep(60);
    doc.getElementById("lc-preset-del").click();
    const asked = await waitFor(
      () => !doc.getElementById("confirm-modal").classList.contains("hidden"), 2000, "删除确认");
    ok(asked, "删除前弹出确认");
    doc.getElementById("confirm-yes").click();
    await waitFor(() => sel.options.length === 1, 2000, "预设被移除");
    ok(sel.options.length === 1, "下拉只剩「（无）」", sel.options.length + " 项");
    ok((lastPresetPatch() || []).length === 0, "删除结果已落盘（空数组）",
       JSON.stringify(lastPresetPatch()));
    ok(doc.getElementById("lc-preset-del").disabled === true,
       "没有选中预设时「删除」按钮禁用");
  }

  console.log("\n[5] 启动恢复：表达式与预设一致时自动选中");
  {
    const { doc } = await boot({
      lc_keyword: "level:EF",
      lc_presets: JSON.stringify([{ name: "崩溃", kw: "level:EF" }]),
    });
    ok(doc.getElementById("lc-filter").value === "level:EF", "表达式按配置恢复");
    ok(doc.getElementById("lc-preset").value === "0", "下拉自动选上匹配的预设");
  }

  console.log("\n[6] 手改表达式后下拉退回「（无）」");
  {
    const { window, doc } = await boot({
      lc_keyword: "level:EF",
      lc_presets: JSON.stringify([{ name: "崩溃", kw: "level:EF" }]),
    });
    typeFilter(window, doc, "level:E");
    await sleep(420);
    ok(doc.getElementById("lc-preset").value === "", "与预设不一致时回到「（无）」");
    ok(doc.getElementById("lc-preset-del").disabled === true,
       "回到「（无）」后「删除」按钮禁用");
  }

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
