/* jsdom 前端行为测试：Toast 超限淘汰不得死循环（窗口卡死）

   回归点：showToast 末尾的淘汰循环

       while (els.toastWrap.childElementCount > TOAST_MAX) {
         const oldest = els.toastWrap.firstElementChild;
         if (oldest === el) break;
         dismissToast(oldest, true);
       }

   而 dismissToast 开头是 `if (!el || el._toastGone) return;` —— 对一个「已经点了关闭、
   但退场动画 / 400ms 兜底计时器还没到点」的 toast，它直接 return、节点仍在 DOM 里，
   于是 childElementCount 不变、循环永不推进：JS 线程被占满，定时器再也无法触发，
   整个窗口永久卡死（实测错误提示连发时命中）。

   修复：dismissToast 对已标记退场的节点直接 remove()，淘汰循环再补一层
   「本轮必须真的删掉一个节点」的兜底。下面既做行为验证，也锁住这两道防线。 */
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
    await sleep(20);
  }
  console.log("    (waitFor 超时: " + label + ")");
  return false;
}

// 队列式环境：可以随时 push 事件，交给下一次 take_events 轮询消费
function mkEnv() {
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const queue = [];
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function () {
          if (k === "boot") {
            return Promise.resolve({ version: "v-test", warnings: [], commands: [], adb: "adb" });
          }
          if (k === "take_events") return Promise.resolve(queue.splice(0, queue.length));
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  return { window, queue, push: (e) => queue.push(e) };
}

const ERR = (t) => ({ kind: "status", payload: { type: "err", text: t } });
function click(window, el) {
  el.dispatchEvent(new window.Event("click", { bubbles: true }));
}

(async () => {
  console.log("\n[1] 已退场的 toast 再次被关闭时必须真的从 DOM 移除");
  {
    const env = mkEnv();
    const doc = env.window.document;
    const wrap = doc.getElementById("toast-wrap");
    env.push({ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } });
    for (let i = 0; i < 4; i++) env.push(ERR("错误 " + i));

    const got4 = await waitFor(() => wrap.childElementCount === 4, 4000, "4 条 toast");
    ok(got4, "4 条错误提示产生 4 个 toast（实际 " + wrap.childElementCount + "）");

    const oldest = wrap.firstElementChild;
    click(env.window, oldest);                     // 第一次：进入退场流程（节点暂留）
    ok(oldest.isConnected, "第一次关闭：节点仍在 DOM（等退场动画 / 兜底计时器）");
    click(env.window, oldest);                     // 第二次：修复后应直接摘除
    ok(!oldest.isConnected,
       "已退场的 toast 再被关闭时应立即摘除（旧实现会原地留着 → 淘汰循环死循环）");
    ok(wrap.childElementCount === 3,
       "重复关闭后只剩 3 个 toast（实际 " + wrap.childElementCount + "）");
  }

  console.log("\n[2] 超过上限时淘汰循环必须推进（不能卡死窗口）");
  {
    const env = mkEnv();
    const doc = env.window.document;
    const wrap = doc.getElementById("toast-wrap");
    env.push({ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } });
    for (let i = 0; i < 4; i++) env.push(ERR("批量错误 " + i));
    await waitFor(() => wrap.childElementCount === 4, 4000, "4 条 toast");

    // 先把最旧的一条推入「已退场但未移除」状态，再追加一条触发淘汰循环 ——
    // 这正是旧代码死循环的时序。
    const oldest = wrap.firstElementChild;
    click(env.window, oldest);
    ok(oldest.isConnected, "最旧 toast 处于退场中（节点暂留）");
    env.push(ERR("第五条"));
    // 注意不能只等 childElementCount === 4：那在追加之前就已经成立。
    // 等到「队首不再是那条退场中的 toast」才说明第 5 条已被消费、淘汰已完成。
    const settled = await waitFor(() => wrap.firstElementChild !== oldest,
                                  2000, "淘汰完成");
    ok(settled && wrap.childElementCount === 4,
       "追加第 5 条后淘汰循环正常收尾，同屏仍为 4 条（实际 " + wrap.childElementCount + "）");
    ok(!oldest.isConnected, "最旧的 toast 已被淘汰出 DOM");
  }

  console.log("\n[3] 源码层面锁住两道防线（防止回归时又变成死循环）");
  {
    ok(/if \(el\._toastGone\) \{[\s\S]{0,200}?el\.remove\(\)/.test(js),
       "dismissToast 对已退场节点直接 remove()");
    ok(/if \(!oldest \|\| oldest === el\) break;/.test(js),
       "淘汰循环对空节点 / 自身有 break 保护");
    ok(/if \(oldest\.isConnected\) oldest\.remove\(\);/.test(js),
       "淘汰循环每轮强制保证前进（兜底 remove）");
  }

  console.log("\n结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
