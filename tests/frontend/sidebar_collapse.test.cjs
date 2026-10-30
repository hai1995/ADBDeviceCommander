/* jsdom 前端行为测试：设备栏（已连接设备列表）侧边栏收起 / 展开
   需求：设备栏可折叠成窄轨让内容区用满宽度，也可一键展开；
   收起状态跨会话记忆（config.json 的 sidebar_collapsed），重启恢复。

   这里锁定：
     1. 收起按钮位于设备栏头部、标题之前（箭头 « / » 随状态翻转）；
     2. CSS 收起态规则：48px 窄轨 / 分隔条隐藏 / 设备列表与 DEVICES、
        按钮组隐藏，但设备数徽章保留（只藏单位「台」）、标题文字转为
        竖排「铭牌」标签；整轨可点展开（热区委托，按钮目标除外）；
     3. 点击切换 class + 落盘 save_settings(sidebar_collapsed)；
     4. 收起时清掉分隔条拖出的内联宽度（否则 class 规则被内联压过，
        根本收不起来）；展开时原样恢复（用户拖过的宽度不丢）；
     5. 窗口缩放时重钳逻辑不许把收起态弹开（内联已清 → 跳过）；
     6. booted.settings 回填收起状态，且回填不反向写盘。 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.join(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "frontend/index.html"), "utf8");
const js = fs.readFileSync(path.join(ROOT, "frontend/js/app.js"), "utf8");
const css = fs.readFileSync(path.join(ROOT, "frontend/css/app.css"), "utf8");

process.on("unhandledRejection", (e) => { console.log("!! unhandledRejection:", e && e.stack ? e.stack : e); });

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
function cssBlock(sel) {
  const i = css.indexOf(sel + " {");
  return i < 0 ? "" : css.slice(i, css.indexOf("}", i));
}

/** 起一个带调用记录的假后端：booted 载荷可指定 settings。 */
function mkEnv(opts) {
  opts = opts || {};
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const calls = [];
  let round = 0;
  const batches = [
    [{ kind: "booted", payload: {
        version: "v-test", warnings: [], commands: [],
        settings: opts.settings || {},
        settings_warnings: [],
        config_path: "C:\\ADB\\config.json",
        save_dir_effective: "",
        save_dir_note: null,
        lc_buffers: {},
      } }],
  ];
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          calls.push({ api: k, args });
          if (k === "boot") return Promise.resolve({ ok: true });
          if (k === "take_events") {
            const b = batches[round] || [];
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

const saved = (calls, key) =>
  calls.filter((c) => c.api === "save_settings" && c.args[0] && key in c.args[0]);

/** 等启动流程跑到 bindUI + boot + 首个事件轮次（applyBootSettings 已执行）。 */
async function booted(win, calls) {
  if (!await waitFor(() => calls.some((c) => c.api === "boot"), 4000, "boot")) return false;
  if (!await waitFor(() => calls.some((c) => c.api === "take_events"), 4000, "take_events")) return false;
  await sleep(300);   // booted 事件在 Promise 续体里处理，给一拍落地
  return true;
}

(async () => {
  console.log("\n[1] 静态：按钮位置与 CSS 收起态规则");
  {
    const btnAt = html.indexOf('<button id="btn-sidebar-collapse"');
    const titleAt = html.indexOf('class="sidebar-title"');
    const headAt = html.indexOf('class="sidebar-head"');
    ok(btnAt > headAt && btnAt < titleAt,
       "收起按钮在设备栏头部内、标题之前（贴着标题，语义即「收起本栏」）");
    ok(/aria-expanded="true"/.test(html.slice(btnAt, btnAt + 200)),
       "按钮带 aria-expanded（无障碍：折叠状态可被读出）");

    const rail = cssBlock(".main-row.sidebar-collapsed .device-sidebar");
    ok(!!rail && /width:\s*48px/.test(rail), "收起态设备栏缩为 48px 窄轨");
    ok(!!rail && /cursor:\s*pointer/.test(rail), "收起态整轨 pointer 光标（点轨即展开）");
    const sp = cssBlock(".main-row.sidebar-collapsed #sidebar-splitter");
    ok(!!sp && /display:\s*none/.test(sp), "收起态隐藏分隔条（拖着 48px 的轨没意义）");
    const hidden = cssBlock(".main-row.sidebar-collapsed .device-list");
    ok(!!hidden && /display:\s*none/.test(hidden), "收起态隐藏设备列表本体");
    // 同一条规则的选择器列表（在 { 之前）应收掉 DEVICES / 按钮组 / 设备列表，
    // 但不再包含标题文字——它转为竖排铭牌标签，是收起态的「身份」
    const ruleStart = css.indexOf(".main-row.sidebar-collapsed .side-sub");
    const selectorList = ruleStart >= 0 ? css.slice(ruleStart, css.indexOf("{", ruleStart)) : "";
    ok(selectorList.indexOf(".main-row.sidebar-collapsed .sidebar-actions") >= 0
       && selectorList.indexOf(".main-row.sidebar-collapsed .device-list") >= 0,
       "收起态把 DEVICES / 按钮组 / 设备列表一起隐藏（同规则一组）");
    ok(selectorList.indexOf(".sidebar-title-text") < 0,
       "标题文字不在隐藏名单里——收起态改为竖排铭牌标签");
    const vlabel = cssBlock(".main-row.sidebar-collapsed .sidebar-title-text");
    ok(!!vlabel && /writing-mode:\s*vertical-rl/.test(vlabel),
       "标题文字竖排（vertical-rl）：「已连接设备」五个字竖着读，像仪器铭牌");
    const unit = cssBlock(".main-row.sidebar-collapsed .count-unit");
    ok(!!unit && /display:\s*none/.test(unit),
       "收起态藏掉计数单位「台」——徽章只留等宽数字（N 台 → N）");
    const railBtn = cssBlock(".main-row.sidebar-collapsed .sidebar-collapse-btn");
    ok(!!railBtn && /width:\s*28px/.test(railBtn) && /border-radius/.test(railBtn),
       "» 展开钮在收起态方块化（28px 定宽 + 圆角，不再是文字小按钮）");
    const railHover = cssBlock(".main-row.sidebar-collapsed .sidebar-collapse-btn:hover");
    ok(!!railHover && /box-shadow/.test(railHover) && /--accent/.test(railHover),
       "» 按钮悬停点磷光青辉光（与面板主强调色一致）");
    const nameplate = cssBlock(".main-row.sidebar-collapsed .sidebar-title");
    ok(!!nameplate && /margin-top:\s*auto/.test(nameplate) && /border-top/.test(nameplate),
       "铭牌组钉在轨底（margin-top:auto）且带发丝线分隔");
  }

  console.log("\n[2] 默认展开态");
  {
    const { window, calls } = mkEnv();
    const doc = window.document;
    ok(await booted(window, calls), "启动流程完成");
    const row = doc.querySelector(".main-row");
    const btn = doc.getElementById("btn-sidebar-collapse");
    ok(!row.classList.contains("sidebar-collapsed"), "默认展开（无 collapsed class）");
    ok(btn.textContent === "«", "展开态箭头为 «（实际 " + btn.textContent + "）");
    ok(btn.getAttribute("aria-expanded") === "true", "aria-expanded=true");
    ok(saved(calls, "sidebar_collapsed").length === 0,
       "settings 缺省时不写盘（保持界面默认即可）");
    window.close();
  }

  console.log("\n[3] 点击切换 + 落盘");
  {
    const { window, calls } = mkEnv();
    const doc = window.document;
    await booted(window, calls);
    const row = doc.querySelector(".main-row");
    const btn = doc.getElementById("btn-sidebar-collapse");

    btn.click();
    ok(row.classList.contains("sidebar-collapsed"), "点一下 → 收起（class 加上）");
    ok(btn.textContent === "»", "收起态箭头翻转为 »");
    ok(btn.title === "展开设备栏", "tooltip 变为「展开设备栏」");
    ok(btn.getAttribute("aria-expanded") === "false", "aria-expanded=false");
    ok(await waitFor(() => {
      const hit = saved(calls, "sidebar_collapsed").pop();
      return hit && hit.args[0].sidebar_collapsed === true;
    }, 3000, "save true"),
       "收起即时落盘 save_settings({sidebar_collapsed: true})");

    btn.click();
    ok(!row.classList.contains("sidebar-collapsed"), "再点一下 → 展开（class 移除）");
    ok(btn.textContent === "«" && btn.getAttribute("aria-expanded") === "true",
       "箭头与 aria 回到展开态");
    ok(await waitFor(() => {
      const hit = saved(calls, "sidebar_collapsed").pop();
      return hit && hit.args[0].sidebar_collapsed === false;
    }, 3000, "save false"),
       "展开即时落盘 save_settings({sidebar_collapsed: false})");
    window.close();
  }

  console.log("\n[4] 内联宽度：收起清掉、展开原样恢复");
  {
    const { window, calls } = mkEnv();
    const doc = window.document;
    await booted(window, calls);
    const row = doc.querySelector(".main-row");
    const btn = doc.getElementById("btn-sidebar-collapse");
    const sidebar = doc.getElementById("device-sidebar");
    // 模拟用户先用分隔条把设备栏拖到 350px（内联宽度）
    sidebar.style.width = "350px";
    // jsdom 无布局：桩一个足够宽的行容器，避免 reclamp 把 350 钳到 200
    const rect = (w) => ({ width: w, left: 0, right: w, top: 0, bottom: 0, x: 0, y: 0, height: 0 });
    row.getBoundingClientRect = () => rect(1400);

    btn.click();
    ok(sidebar.style.width === "",
       "收起时清掉内联宽度——否则内联会压过 class 规则，栏根本收不起来"
       + "（实际 " + JSON.stringify(sidebar.style.width) + "）");
    btn.click();
    ok(sidebar.style.width === "350px",
       "展开时恢复收起前的宽度 350px（用户拖过的宽度不丢，实际 "
       + sidebar.style.width + "）");
    window.close();
  }

  console.log("\n[5] 窗口缩放不许把收起态弹开");
  {
    const { window, calls } = mkEnv();
    const doc = window.document;
    await booted(window, calls);
    const row = doc.querySelector(".main-row");
    const btn = doc.getElementById("btn-sidebar-collapse");
    const sidebar = doc.getElementById("device-sidebar");
    btn.click();                       // 收起（内联已清）
    window.dispatchEvent(new window.Event("resize"));   // 触发 reclampSplitters
    await sleep(50);
    ok(row.classList.contains("sidebar-collapsed") && sidebar.style.width === "",
       "缩放窗口后仍是收起态（内联为空 → 重钳跳过，不会钳回 200px 弹开）");
    window.close();
  }

  console.log("\n[6] booted.settings 回填收起状态（重启恢复）");
  {
    const { window, calls } = mkEnv({ settings: { sidebar_collapsed: true } });
    const doc = window.document;
    ok(await booted(window, calls), "启动流程完成");
    const row = doc.querySelector(".main-row");
    const btn = doc.getElementById("btn-sidebar-collapse");
    ok(row.classList.contains("sidebar-collapsed"),
       "上次收起 → 重启后保持收起（class 由回填加上）");
    ok(btn.textContent === "»", "回填后箭头为 »（与收起态一致）");
    ok(saved(calls, "sidebar_collapsed").length === 0,
       "回填不反向写盘（刚读出来的值不再 save 回去）");
    window.close();
  }

  console.log("\n[8] 收起态：点窄轨可展开，点 « 按钮不被委托顶回");
  {
    const { window, calls } = mkEnv();
    const doc = window.document;
    await booted(window, calls);
    const row = doc.querySelector(".main-row");
    const btn = doc.getElementById("btn-sidebar-collapse");
    btn.click();                       // 先收起
    ok(row.classList.contains("sidebar-collapsed"), "先收起");
    // 点窄轨内的竖排标签（非按钮目标）→ 整轨热区生效，展开
    doc.querySelector(".sidebar-title-text")
       .dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    ok(!row.classList.contains("sidebar-collapsed"),
       "点窄轨内的标签 → 展开（整轨热区，不只 » 按钮可展开）");
    ok(await waitFor(() => {
      const hit = saved(calls, "sidebar_collapsed").pop();
      return hit && hit.args[0].sidebar_collapsed === false;
    }, 3000, "save false via rail"),
       "点轨展开同样落盘 sidebar_collapsed=false");
    // 再收起：点 « 按钮后事件冒泡到轨委托，必须因目标在按钮内而被跳过，
    // 否则会「刚收起又被展开」，表现为按钮失灵
    btn.click();
    await sleep(50);
    ok(row.classList.contains("sidebar-collapsed"),
       "点 « 按钮只收起（轨委托跳过按钮目标，不会把它顶回展开）");
    window.close();
  }

  console.log("\n[9] settings 为缺省 / 非法值时不动");
  {
    const { window, calls } = mkEnv({ settings: { sidebar_collapsed: "false" } });
    const doc = window.document;
    await booted(window, calls);
    ok(!doc.querySelector(".main-row").classList.contains("sidebar-collapsed"),
       "字符串 \"false\" 不是布尔值 → 不回填（后端 sanitize 会纠正为 false）");
    window.close();
  }

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
