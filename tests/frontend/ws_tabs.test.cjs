/* jsdom 前端行为测试：指令台工作区（子 tab / 多开）
   —— 每个工作区是一套完整的「指令台 + 指令输出」，可开 N 个、各自独立。

   回归背景：只做「多几块面板」是假的多开 —— 命令仍共用一条会话、输出仍写进
   同一个容器，用户在新 tab 里点执行会看到别人的输出、或者半天没有输出。所以
   这里逐条盯行为：
     1) 新建后确实多出一整套面板，且文档里**没有重复 id**（否则 getElementById
        认错人，第 2 个 tab 的按钮全都不好使）；
     2) 执行时把工作区 id 一起下发；
     3) 输出/停止按钮态按事件里的 ws 精确分流，不串台；
     4) 关闭工作区会通知后端杀会话，默认工作区不给关；
     5) 数量上限有明确提示，重启后按 config.json 恢复布局；
     6) 重启后回到上次停留的工作区（cmd_active_ws 存名字，对不上则回退第一个）。
*/
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

/** 起一个可动态推事件的假后端。 */
function mkEnv(settings) {
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const calls = [];
  let queue = [{
    kind: "booted",
    payload: { version: "v-test", warnings: [], commands: [], settings: settings || {} },
  }];
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          calls.push({ api: k, args });
          if (k === "boot") return Promise.resolve({ ok: true });
          if (k === "take_events") {
            const b = queue;
            queue = [];
            return Promise.resolve(b);
          }
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState",
    { value: "complete", configurable: true });
  window.eval(js);
  return {
    window,
    doc: window.document,
    calls,
    push: (...evs) => { queue.push(...evs); },
  };
}

const wsTabs = (doc) => Array.from(doc.querySelectorAll("#ws-tabs .ws-tab"));
const panels = (doc) => Array.from(doc.querySelectorAll(".tab[data-tab='cmd'] .ws-panel"));
const roleIn = (panel, role) => panel.querySelector('[data-role="' + role + '"]');
const activePanel = (doc) => doc.querySelector(".tab[data-tab='cmd'] .ws-panel.active");

(async () => {
  console.log("\n[0] 入口存在性（旧实现没有这些，回退验证时最先在这里失败）");
  {
    const { doc } = mkEnv();
    ok(!!doc.getElementById("ws-tabs"), "指令页顶部有工作区 tab 条（#ws-tabs）");
    ok(!!doc.getElementById("btn-ws-add"), "有「新建工作区」按钮（#btn-ws-add）");
    ok(!!doc.querySelector('.tab[data-tab="cmd"] .ws-panel'),
      "工作区面板带 .ws-panel 标记（否则多开无法隐藏/切换）");
    if (fail) {
      console.log("\n结果：多工作区入口不存在，后续用例不再执行");
      process.exit(1);
    }
  }

  console.log("\n[1] 初始只有一个工作区，且默认工作区就是页面里原有那套面板");
  {
    const { doc } = mkEnv();
    // tab 由事件驱动渲染（booted 到达后才有），静态 HTML 里没有
    await waitFor(() => wsTabs(doc).length > 0, 3000, "首个工作区 tab");
    const tabs = wsTabs(doc);
    ok(tabs.length === 1, "启动只有一个工作区 tab（实际 " + tabs.length + "）");
    ok(!!tabs[0] && /工作区\s*1/.test(tabs[0].textContent), "默认工作区叫「工作区 1」");
    ok(!!tabs[0] && tabs[0].classList.contains("active"), "默认工作区是选中态");
    ok(panels(doc).length === 1, "只有一套指令台面板");
    ok(!!doc.getElementById("console") && !!doc.getElementById("cmd-input"),
      "默认工作区仍保留原有 id（#console / #cmd-input），旧页面与测试不受影响");
    ok(!!tabs[0] && tabs[0].querySelector(".ws-x") === null,
      "默认工作区没有关闭键（关不掉）");
  }

  console.log("\n[2] 新建工作区：多出一整套面板，且文档里没有重复 id");
  {
    const { doc, calls } = mkEnv();
    doc.getElementById("btn-ws-add").click();
    ok(await waitFor(() => wsTabs(doc).length === 2, 3000, "第二个 tab"),
      "点「新建工作区」后出现第 2 个 tab（实际 " + wsTabs(doc).length + "）");
    ok(panels(doc).length === 2, "面板也跟着多一套");
    ok(doc.querySelectorAll(".ws-panel.active").length === 1,
      "同一时刻只有一个工作区可见（不叠在一起）");
    ok(activePanel(doc) === panels(doc)[1], "新建后自动切到新工作区");

    // 重复 id 是这类「克隆 DOM」实现最容易踩的坑：两个 #console 会让
    // getElementById / label for / CSS #id 全部认错人。
    const ids = Array.from(doc.querySelectorAll(".tab[data-tab='cmd'] [id]"))
      .map((el) => el.id);
    const dup = ids.filter((x, i) => ids.indexOf(x) !== i);
    ok(dup.length === 0, "克隆面板没有重复 id（重复项：" + dup.join(",") + "）");
    ok(doc.querySelectorAll("#console").length === 1, "文档里只有一个 #console");

    const p2 = panels(doc)[1];
    ok(roleIn(p2, "console").children.length === 0, "新工作区的输出是空的（不复制旧内容）");
    ok(roleIn(p2, "cmd-input").value === "", "新工作区的输入框是空的");
    ok(calls.some((c) => c.api === "ws_open" && c.args[0] === "w2"),
      "新建时通知后端登记工作区（ws_open w2）");
  }

  console.log("\n[3] 在新工作区执行命令：工作区 id 要一起下发");
  {
    const { doc, calls } = mkEnv();
    doc.getElementById("btn-ws-add").click();
    await waitFor(() => panels(doc).length === 2);
    const p2 = panels(doc)[1];
    roleIn(p2, "cmd-input").value = "adb shell getprop ro.product.model";
    roleIn(p2, "btn-run").click();
    const run = calls.filter((c) => c.api === "run_custom");
    ok(run.length === 1, "点执行下发 run_custom");
    ok(run[0].args[0] === "adb shell getprop ro.product.model", "命令文本正确");
    ok(run[0].args[1] === "w2", "第二个参数带上工作区 id（实际：" + run[0].args[1] + "）");

    // 默认工作区仍然只带文本：老调用签名（一个参数）不能被改坏
    doc.getElementById("cmd-input").value = "adb devices";
    doc.getElementById("btn-run").click();
    const run2 = calls.filter((c) => c.api === "run_custom");
    ok(run2.length === 2 && run2[1].args[1] === "w1",
      "默认工作区下发 w1（不会串到别的工作区）");
  }

  console.log("\n[4] 输出按 ws 分流：不串台");
  {
    const { doc, push } = mkEnv();
    doc.getElementById("btn-ws-add").click();
    await waitFor(() => panels(doc).length === 2);
    push({ kind: "console", payload: { kind: "out", text: "只属于工作区 2 的一行", ws: "w2" } });
    ok(await waitFor(
      () => /只属于工作区 2/.test(roleIn(panels(doc)[1], "console").textContent),
      3000, "w2 输出"),
      "带 ws=w2 的输出进了第 2 个面板");
    ok(!/只属于工作区 2/.test(doc.getElementById("console").textContent),
      "默认工作区的面板没有被写入（不串台）");

    push({ kind: "console", payload: { kind: "out", text: "默认工作区的一行" } });
    ok(await waitFor(
      () => /默认工作区的一行/.test(doc.getElementById("console").textContent),
      3000, "w1 输出"),
      "不带 ws 的输出仍进默认工作区（向后兼容）");
    ok(!/默认工作区的一行/.test(roleIn(panels(doc)[1], "console").textContent),
      "第 2 个面板也没有被串入");
  }

  console.log("\n[5] 停止按钮态按工作区同步");
  {
    const { doc, push } = mkEnv();
    doc.getElementById("btn-ws-add").click();
    await waitFor(() => panels(doc).length === 2);
    const p2 = panels(doc)[1];
    ok(roleIn(p2, "btn-stop").disabled === true, "新工作区初始「停止」不可点");

    push({ kind: "stop_state", payload: { running: true, ws: "w2" } });
    ok(await waitFor(() => roleIn(panels(doc)[1], "btn-stop").disabled === false,
      3000, "w2 停止按钮启用"),
      "工作区 2 的命令跑起来后它自己的「停止」可用");
    ok(doc.getElementById("btn-stop").disabled === true,
      "默认工作区的「停止」不受影响（不该被点亮）");
    ok(wsTabs(doc)[1].classList.contains("is-busy"),
      "第 2 个 tab 上有「正在执行」指示（切走后也看得见）");
  }

  console.log("\n[6] 清空输出只清自己那一块");
  {
    const { doc, calls } = mkEnv();
    doc.getElementById("btn-ws-add").click();
    await waitFor(() => panels(doc).length === 2);
    const p2 = panels(doc)[1];
    roleIn(p2, "btn-clear-console").click();
    ok(await waitFor(() => calls.some((c) => c.api === "clear_output"), 2000, "clear_output"),
      "点清空下发 clear_output");
    const co = calls.filter((c) => c.api === "clear_output").pop();
    ok(co.args[0] === "w2", "带上工作区 id（实际：" + co.args[0] + "）");
  }

  console.log("\n[7] 关闭工作区：通知后端杀会话，面板真正移除");
  {
    const { doc, calls } = mkEnv();
    doc.getElementById("btn-ws-add").click();
    await waitFor(() => panels(doc).length === 2);
    wsTabs(doc)[1].querySelector(".ws-x").click();
    ok(await waitFor(() => calls.some((c) => c.api === "ws_close" && c.args[0] === "w2"),
      3000, "ws_close"), "关闭时通知后端（ws_close w2）");
    ok(await waitFor(() => panels(doc).length === 1, 3000, "面板移除"),
      "面板从文档里移除（不是只隐藏）");
    ok(wsTabs(doc).length === 1, "tab 也回到 1 个");
    ok(activePanel(doc) === panels(doc)[0], "关闭当前工作区后自动回到默认工作区");
  }

  console.log("\n[7b] 已关闭工作区的在途事件必须丢弃，不能倒进默认工作区");
  {
    // 关闭工作区时后端先 stop_run 再 ws_close：kill 生效前会话仍可能吐出最后
    // 几行输出，也可能还有一条在途的 stop_state。旧实现的事件分流会「找不到
    // 就回落到 w1」—— 于是关掉的工作区的日志被倒进工作区 1，stop_state 还会
    // 把工作区 1 正在跑的命令的「停止」按钮熄灭，用户就再也停不掉它了。
    // closeWorkspace 明确承诺「其中的输出一并丢弃」，这里守住这个语义。
    const { doc, push } = mkEnv();
    doc.getElementById("btn-ws-add").click();
    await waitFor(() => panels(doc).length === 2, 3000, "第二个 tab");
    wsTabs(doc)[1].querySelector(".ws-x").click();
    ok(await waitFor(() => panels(doc).length === 1, 3000, "面板移除"),
      "工作区 2 已关闭");

    // 默认工作区此刻正在执行：停止按钮可用、tab 上有执行指示
    push({ kind: "stop_state", payload: { running: true, ws: "w1" } });
    ok(await waitFor(() => doc.getElementById("btn-stop").disabled === false, 3000,
      "w1 停止按钮启用"), "工作区 1 的命令跑起来了（停止按钮可用）");

    // 关闭后的残留事件 + 一条用于确认「这批事件已被处理」的正常输出
    push({ kind: "console", payload: { kind: "out", text: "关闭后迟到的输出", ws: "w2" } });
    push({ kind: "stop_state", payload: { running: false, ws: "w2" } });
    push({ kind: "console", payload: { kind: "out", text: "工作区1仍在正常输出" } });
    ok(await waitFor(() => /工作区1仍在正常输出/.test(
      doc.getElementById("console").textContent), 3000, "w1 正常输出"),
      "后续事件已被处理（下面两条断言不是空等）");

    ok(!/关闭后迟到的输出/.test(doc.getElementById("console").textContent),
      "已关闭工作区的输出没有倒进默认工作区面板");
    ok(doc.getElementById("btn-stop").disabled === false,
      "已关闭工作区的 stop_state 没有熄灭默认工作区的「停止」按钮");
    ok(wsTabs(doc)[0].classList.contains("is-busy"),
      "默认工作区的 tab 仍显示「正在执行」（执行态没被别人清掉）");
  }

  console.log("\n[8] 数量上限有明确提示，不会静默失败");
  {
    const { doc } = mkEnv();
    for (let i = 0; i < 12; i += 1) doc.getElementById("btn-ws-add").click();
    await sleep(120);
    ok(panels(doc).length === 8, "最多 8 个工作区（实际 " + panels(doc).length + "）");
    ok(/最多同时开\s*8\s*个工作区/.test(doc.getElementById("status").textContent),
      "超限时状态栏说明原因（不是点了没反应）");
  }

  console.log("\n[9] 重启后按 config.json 恢复工作区布局");
  {
    const { doc } = mkEnv({ cmd_workspaces: "工作区 1,工作区 2,抓日志" });
    ok(await waitFor(() => wsTabs(doc).length === 3, 3000, "恢复 3 个 tab"),
      "启动即恢复 3 个工作区（实际 " + wsTabs(doc).length + "）");
    const names = wsTabs(doc).map((t) => t.textContent.replace(/×/g, "").trim());
    ok(names[2] === "抓日志", "自定的工作区名也一起恢复（实际：" + names[2] + "）");
    ok(panels(doc).length === 3, "每个工作区都有一套面板");
  }

  console.log("\n[10] 记住上次停留的工作区（cmd_active_ws）");
  {
    const { doc, calls } = mkEnv({
      cmd_workspaces: "工作区 1,工作区 2,抓日志", cmd_active_ws: "抓日志",
    });
    const restored = await waitFor(() => wsTabs(doc).length === 3, 3000, "恢复 3 个 tab");
    ok(restored, "启动恢复 3 个工作区（实际 " + wsTabs(doc).length + "）");
    await waitFor(() => activePanel(doc) === panels(doc)[2], 3000, "选中抓日志");
    ok(activePanel(doc) === panels(doc)[2], "启动停在上次的工作区「抓日志」");
    const activeSaves = () => calls.filter((c) => c.api === "save_settings" &&
      c.args[0] && "cmd_active_ws" in c.args[0]);
    ok(activeSaves().length === 0, "启动恢复不回写 cmd_active_ws（不白写盘）");

    // 切到第一个 → 落盘
    wsTabs(doc)[0].dispatchEvent(new doc.defaultView.Event("click", { bubbles: true }));
    await sleep(80);
    ok(activeSaves().length === 1 &&
       activeSaves()[0].args[0].cmd_active_ws === "工作区 1",
       "点第一个 tab → 落盘 cmd_active_ws=工作区 1（实际 " +
       (activeSaves().length ? activeSaves()[0].args[0].cmd_active_ws : "无") + "）");

    // 再点当前这个：没换工作区，不该重复写
    wsTabs(doc)[0].dispatchEvent(new doc.defaultView.Event("click", { bubbles: true }));
    await sleep(80);
    ok(activeSaves().length === 1, "再点当前工作区不重复写盘（仍 1 次）");

    // 配置里的名字已经不存在 → 回退第一个，而不是一个都不选
    const { doc: d2 } = mkEnv({
      cmd_workspaces: "工作区 1,工作区 2", cmd_active_ws: "早就删了",
    });
    await waitFor(() => wsTabs(d2).length === 2, 3000, "恢复 2 个");
    await waitFor(() => activePanel(d2) === panels(d2)[0], 3000, "回退第一个");
    ok(activePanel(d2) === panels(d2)[0],
       "cmd_active_ws 名字对不上 → 回退第一个工作区");
  }

  console.log("\n结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})().catch((e) => {
  // 断言里踩到 undefined 时不能静默挂着（unhandledRejection 被吞掉的坑）
  console.error("测试脚本自身出错：", e);
  process.exit(1);
});
