/* jsdom 前端行为测试：工作区重命名（双击 tab 名 / F2）
   —— 多开之后「工作区 2 / 工作区 3」谁是谁全靠记，名字得能自己起。

   这里盯的不是「输入框出现过」，而是改名之后到底发生了什么：
     1) 名字改的是**三重**的：tab 上的字、config.json（cmd_workspaces）、后端
        登记（ws_open 的 name）—— 少最后一步，tab 写着「刷机」、状态栏还是
        「[工作区 3] ✓ 完成」，两边对不上；
     2) 取消（Esc）与空名不该落盘、不该打扰后端；
     3) 名字里的逗号是 cmd_workspaces 的分隔符，必须挡掉（否则重启后多一个空
        面板，用户根本想不到是逗号干的）；
     4) 重命名途中来的事件不能把输入框冲掉（渲染要给它让路）；
     5) 双击「关闭」键不该进入改名（用户只是想连点两下关掉）。
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
    await sleep(30);
  }
  console.log("    (waitFor 超时: " + label + ")");
  return false;
}

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
    window, doc: window.document, calls,
    push: (...evs) => { queue.push(...evs); },
  };
}

const tabs = (doc) => Array.from(doc.querySelectorAll("#ws-tabs .ws-tab"));
const tabOf = (doc, id) => doc.querySelector('#ws-tabs .ws-tab[data-ws="' + id + '"]');
const labelOf = (doc, id) => {
  const t = tabOf(doc, id);
  return t ? (t.querySelector(".ws-label") || {}).textContent : undefined;
};
const renameInput = (doc, id) => {
  const t = tabOf(doc, id);
  return t ? t.querySelector(".ws-rename") : null;
};
const savedNames = (calls) => {
  const c = calls.filter((x) => x.api === "save_settings"
    && x.args[0] && typeof x.args[0].cmd_workspaces === "string").pop();
  return c ? c.args[0].cmd_workspaces : null;
};
const statusText = (doc) => (doc.getElementById("status") || {}).textContent || "";

/** 起界面 + 等到默认 tab 出现，返回一组便捷操作。 */
async function boot(settings) {
  const env = mkEnv(settings);
  await waitFor(() => tabs(env.doc).length > 0, 3000, "首个 tab");
  const { window } = env;
  const fire = (el, type, init) => el.dispatchEvent(
    new window.MouseEvent(type, Object.assign({ bubbles: true }, init || {})));
  const key = (el, k) => el.dispatchEvent(
    new window.KeyboardEvent("keydown", { key: k, bubbles: true }));
  const dblclick = (el) => fire(el, "dblclick");
  const open = (id) => {
    dblclick(tabOf(env.doc, id));
    return renameInput(env.doc, id);
  };
  const commit = (id, text) => {
    const inp = renameInput(env.doc, id);
    inp.value = text;
    key(inp, "Enter");
  };
  return Object.assign(env, { fire, key, dblclick, open, commit });
}

/* 断言里踩到 null 会抛错，异常又被 unhandledRejection 吞掉、jsdom 定时器又不会
   停 —— 进程会一直挂着。到点按当前结果退出，保证失败是「失败」而不是「卡死」。 */
const watchdog = setTimeout(() => {
  console.log("    (看门狗触发：疑似断言抛错导致未收尾)");
  process.exit(fail ? 1 : 0);
}, 60000);
if (watchdog.unref) watchdog.unref();

(async () => {
  console.log("\n[0] 入口存在性（旧实现没有这些，回退验证时最先在这里失败）");
  {
    const env = await boot();
    const doc = env.doc;
    ok(!!doc.querySelector("#ws-tabs .ws-tab .ws-label"),
      "tab 里的名字是 .ws-label（重命名要能单独换掉它）");
    ok(/双击.*重命名/.test(tabOf(doc, "w1").title),
      "tab 的悬停提示写明「双击重命名」（不说没人知道）");
    ok(/双击 tab 名可重命名/.test((doc.getElementById("ws-hint") || {}).textContent),
      "tab 条右侧的说明里也写了（实际：" + (doc.getElementById("ws-hint") || {}).textContent + "）");
    if (fail) {
      console.log("\n结果：重命名入口不存在，后续用例不再执行");
      process.exit(1);
    }
  }

  console.log("\n[1] 双击 tab 名：变成输入框，带当前名字、整段选中");
  {
    const env = await boot();
    const doc = env.doc;
    env.dblclick(tabOf(doc, "w1"));
    const inp = renameInput(doc, "w1");
    ok(!!inp, "双击后出现输入框（.ws-rename）");
    ok(inp && inp.value === "工作区 1", "输入框里是当前名字（实际：" + (inp && inp.value) + "）");
    ok(doc.activeElement === inp, "输入框已获得焦点（否则得先点一下才能打字）");
    ok(inp && inp.selectionStart === 0 && inp.selectionEnd === inp.value.length,
      "整段选中（改名多是整条换掉，不是改一个字）");
    ok(tabOf(doc, "w1").classList.contains("is-renaming"), "tab 进入重命名态（光标也跟着变）");
    ok(!labelOf(doc, "w1"), "原文字已让位，不会和输入框叠在一起");
  }

  console.log("\n[2] 回车提交：tab 文字 / 落盘 / 后端登记，三处都改");
  {
    const env = await boot();
    const doc = env.doc;
    doc.getElementById("btn-ws-add").click();
    await waitFor(() => tabs(doc).length === 2);
    env.open("w2");
    env.commit("w2", "抓 logcat");

    ok(await waitFor(() => labelOf(doc, "w2") === "抓 logcat", 2000, "tab 改名"),
      "tab 上的名字立刻变了（实际：" + labelOf(doc, "w2") + "）");
    ok(!renameInput(doc, "w2"), "输入框已换回文字");
    ok(!tabOf(doc, "w2").classList.contains("is-renaming"), "重命名态已清除");
    const saved = savedNames(env.calls);
    ok(saved === "工作区 1,抓 logcat", "落盘到 cmd_workspaces（实际：" + saved + "）");
    const open2 = env.calls.filter((c) => c.api === "ws_open").pop();
    ok(open2 && open2.args[0] === "w2" && open2.args[1] === "抓 logcat",
      "通知后端登记新名字（否则状态栏还是「[工作区 2]」）：" + JSON.stringify(open2 && open2.args));
    // 状态行是 rAF 批量插入的，别在这一帧里抢读
    ok(await waitFor(() => /已重命名/.test(statusText(doc)), 2000, "状态栏播报"),
      "状态栏说明改成了什么（实际：" + statusText(doc) + "）");
    ok(/抓 logcat/.test(statusText(doc)), "播报里带上了新名字（实际：" + statusText(doc) + "）");
    ok(/抓 logcat/.test(tabOf(doc, "w2").title), "悬停提示同步成新名字");
    ok(/抓 logcat/.test((tabOf(doc, "w2").querySelector(".ws-x") || {}).title || ""),
      "关闭键的提示也同步（还写着旧名字会让人以为关错）");
    // w2 正是当前停留的工作区：cmd_active_ws 存的是名字，改名必须一起更新，
    // 否则下次启动按旧名字匹配不到，会莫名回退到第一个工作区。
    const activeSaved = env.calls.filter((c) => c.api === "save_settings" &&
      c.args[0] && "cmd_active_ws" in c.args[0]);
    ok(activeSaved.length > 0 &&
       activeSaved[activeSaved.length - 1].args[0].cmd_active_ws === "抓 logcat",
       "改名的是当前工作区 → cmd_active_ws 同步成新名字");
  }

  console.log("\n[3] Esc 取消：一个字都不改，也不落盘");
  {
    const env = await boot();
    const doc = env.doc;
    env.dblclick(tabOf(doc, "w1"));
    const inp = renameInput(doc, "w1");
    inp.value = "打错的名字";
    env.key(inp, "Escape");
    await sleep(30);
    ok(labelOf(doc, "w1") === "工作区 1", "恢复原名（实际：" + labelOf(doc, "w1") + "）");
    ok(savedNames(env.calls) === null, "没有落盘");
    ok(!env.calls.some((c) => c.api === "ws_open"), "没有多余的 ws_open");
  }

  console.log("\n[4] 空名字 / 只有空格：拒绝，并说清楚为什么还是原名");
  {
    const env = await boot();
    const doc = env.doc;
    env.dblclick(tabOf(doc, "w1"));
    env.commit("w1", "   ");
    await sleep(30);
    ok(labelOf(doc, "w1") === "工作区 1", "名字没被清空（实际：" + labelOf(doc, "w1") + "）");
    ok(/不能为空/.test(statusText(doc)), "状态栏说明原因（实际：" + statusText(doc) + "）");
    ok(savedNames(env.calls) === null, "空名不落盘（落盘会破坏按序号还原的对齐）");
  }

  console.log("\n[5] 名字里的逗号：换成空格（它是 cmd_workspaces 的分隔符）");
  {
    const env = await boot();
    const doc = env.doc;
    doc.getElementById("btn-ws-add").click();
    await waitFor(() => tabs(doc).length === 2);
    env.open("w2");
    env.commit("w2", "抓日志,刷机");
    await sleep(30);
    ok(labelOf(doc, "w2") === "抓日志 刷机", "逗号变空格（实际：" + labelOf(doc, "w2") + "）");
    const saved = savedNames(env.calls);
    ok(saved === "工作区 1,抓日志 刷机",
      "落盘串里只有 2 段（多一段 = 重启后凭空多一个空工作区）：" + saved);
  }

  console.log("\n[6] 超长名字截到 24 字（与后端 ws_open 的截断一致）");
  {
    const env = await boot();
    const doc = env.doc;
    env.dblclick(tabOf(doc, "w1"));
    const inp = renameInput(doc, "w1");
    inp.value = "一二三四五六七八九十一二三四五六七八九十壹贰叁肆伍";
    env.key(inp, "Enter");
    await sleep(30);
    const nm = labelOf(doc, "w1");
    ok(nm && nm.length === 24, "截到 24 字（实际 " + (nm || "").length + "）");
    ok(inp.maxLength === 24, "输入框本身也限了 24（打到上限就不再进去）");
  }

  console.log("\n[7] 改名途中来的事件不能把输入框冲掉");
  {
    const env = await boot();
    const doc = env.doc;
    doc.getElementById("btn-ws-add").click();
    await waitFor(() => tabs(doc).length === 2);
    env.open("w2");
    const inp = renameInput(doc, "w2");
    inp.value = "打了一半";
    // 后台正好开始跑命令：会更新这个 tab 的状态（忙碌小圆点）。前端是 400ms 轮询
    // 取事件的，所以等它真的消费到 —— 否则测的是「还没发生」。
    env.push({ kind: "stop_state", payload: { running: true, ws: "w2" } });
    ok(await waitFor(() => tabOf(doc, "w2").classList.contains("is-busy"), 3000, "busy"),
      "忙碌指示照常打到这个 tab 上（改名不该让它瞎掉）");
    ok(renameInput(doc, "w2") === inp, "输入框还在，输入的内容没丢");
    ok(inp.value === "打了一半", "内容原样：" + inp.value);
    ok(inp.isConnected !== false, "输入框仍然在文档里（没有被摘掉后继续打字）");
  }

  console.log("\n[8] 双击「关闭」键不进入改名（用户只是想连点两下关掉）");
  {
    const env = await boot();
    const doc = env.doc;
    doc.getElementById("btn-ws-add").click();
    await waitFor(() => tabs(doc).length === 2);
    const x = tabOf(doc, "w2").querySelector(".ws-x");
    // 真实双击 = 两次 click + 一次 dblclick（只发 dblclick 测不到关闭键本身）
    env.fire(x, "click");
    env.dblclick(x);
    ok(!renameInput(doc, "w2"), "没有出现改名输入框");
    ok(await waitFor(() => tabs(doc).length === 1, 2000, "关掉 w2"),
      "该关的还是关掉了");
  }

  console.log("\n[9] 键盘用户：tab 上按 F2 也能改名");
  {
    const env = await boot();
    const doc = env.doc;
    const tab = tabOf(doc, "w1");
    tab.focus();
    env.key(tab, "F2");
    ok(!!renameInput(doc, "w1"), "F2 进入重命名（双击是鼠标习惯，纯键盘够不着）");
  }

  console.log("\n[10] 改名后新建工作区：不会撞名");
  {
    const env = await boot();
    const doc = env.doc;
    env.dblclick(tabOf(doc, "w1"));
    env.commit("w1", "工作区 2");
    await sleep(30);
    doc.getElementById("btn-ws-add").click();
    await waitFor(() => tabs(doc).length === 2);
    const names = tabs(doc).map((t) => (t.querySelector(".ws-label") || {}).textContent);
    ok(names[1] !== "工作区 2", "新工作区避开已占用的名字（实际：" + names.join(" / ") + "）");
    ok(names[0] === "工作区 2", "改过的名字仍然在（实际：" + names[0] + "）");
  }

  console.log("\n[11] 重启恢复：自定义名字要一起交给后端（否则状态栏前缀对不上）");
  {
    const env = await boot({ cmd_workspaces: "抓日志,刷机,临时" });
    const doc = env.doc;
    ok(await waitFor(() => tabs(doc).length === 3, 3000, "恢复 3 个"),
      "恢复 3 个工作区（实际 " + tabs(doc).length + "）");
    const names = tabs(doc).map((t) => (t.querySelector(".ws-label") || {}).textContent);
    ok(names.join("/") === "抓日志/刷机/临时", "名字按顺序恢复：" + names.join("/"));
    const opened = env.calls.filter((c) => c.api === "ws_open").map((c) => c.args);
    ok(opened.some((a) => a[0] === "w2" && a[1] === "刷机")
      && opened.some((a) => a[0] === "w3" && a[1] === "临时"),
      "创建时就带着恢复的名字去登记（不是开完再改名）：" + JSON.stringify(opened));
    ok(!opened.some((a) => a[0] === "w3" && a[1] === "工作区 3"),
      "不会先用默认名登记一遍（那一次会把后端的名字写死成「工作区 3」）");
  }

  console.log("\n[12] 默认工作区改名：只改本地与落盘，不去动后端（它本来就不带前缀）");
  {
    const env = await boot();
    const doc = env.doc;
    env.dblclick(tabOf(doc, "w1"));
    env.commit("w1", "日常 adb");
    await sleep(30);
    ok(labelOf(doc, "w1") === "日常 adb", "tab 改名了");
    ok(savedNames(env.calls) === "日常 adb", "落盘了（实际：" + savedNames(env.calls) + "）");
    ok(!env.calls.some((c) => c.api === "ws_open"), "没有多余的后端调用");
  }

  console.log("\n[13] 名字没变就提交：不落盘、不打扰");
  {
    const env = await boot();
    const doc = env.doc;
    env.dblclick(tabOf(doc, "w1"));
    env.commit("w1", "工作区 1");
    await sleep(30);
    ok(savedNames(env.calls) === null, "同名不写 config.json");
    ok(!/已重命名/.test(statusText(doc)), "也不播报（没改的事不必说）");
  }

  console.log("\n[14] 结束改名只就地更新，不重建 tab 条");
  {
    const env = await boot();
    const doc = env.doc;
    doc.getElementById("btn-ws-add").click();
    await waitFor(() => tabs(doc).length === 2);
    env.open("w1");
    const inp = renameInput(doc, "w1");
    inp.value = "日常 adb";
    const before = tabs(doc);
    // 真实浏览器里「点另一个 tab」= mousedown 触发 blur（提交）→ 紧接着 click
    inp.blur();
    const after = tabs(doc);
    ok(after.length === before.length && after.every((t, i) => t === before[i]),
      "失焦提交的同一刻没有重建 tab 条（重建会把紧跟着的那一击连同节点一起丢掉）");
    ok(labelOf(doc, "w1") === "日常 adb", "名字就地换好了（不用重建也能改字）");
    ok(!!tabOf(doc, "w2").querySelector(".ws-label"),
      "别的 tab 结构完好（标签仍在，不是被摘掉后忘了补回来）");
  }

  console.log("\n结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})().catch((e) => {
  console.error("测试脚本自身出错：", e);
  process.exit(1);
});
