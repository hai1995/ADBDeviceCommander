/* jsdom 前端测试：事件轮询链的抗打断能力（一次坏事件不能冻住整个界面）
 *
 * 现场问题的形状：程序开着一切正常，某天起「日志不再滚、状态栏不动、设备不刷新、
 * 停止按钮也按不下去」，只能重开程序。根因不在任何单个功能，而在事件分发的结构：
 * pollOnce 用递归 setTimeout 续约，
 *
 *     const pollOnce = async () => { ...事件分发...; setTimeout(pollOnce, ms); }
 *
 * 只要**任意一条**事件的处理函数抛异常，那次 setTimeout 就执行不到 —— 轮询链
 * 从此断开，之后再没有任何东西把它接回来。坏事件的来源很现实：后端协议漂移、
 * 手改 payload、某个渲染函数踩到空节点。
 *
 * 怎么把「处理器抛异常」做成确定性的：把设备计数节点的 textContent setter
 * 换成抛错函数。renderDevices 的第一行就是写它，于是任何 devices 事件都会
 * 在渲染第一步炸掉 —— 这正是「某个渲染函数踩到坏节点」的最小复现，
 * 与具体 payload 长什么样无关。
 *
 * 钉住四件事：
 *   A) 抛异常的那条事件之后，同一批 / 后续事件照常处理（轮询链还活着）；
 *   B) 坏事件被跳过并给一条可读提示，且同一类事件只提示一次（不刷爆状态栏）；
 *   C) 一批里「正常 → 坏 → 正常」时，后面的正常事件不能被连坐丢掉；
 *   D) 多轮之后仍在续约（不是靠某一次偶然的重入）。
 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.join(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "frontend/index.html"), "utf8");
const js = fs.readFileSync(path.join(ROOT, "frontend/js/app.js"), "utf8");

let pass = 0, fail = 0;
function ok(c, n) {
  if (c) { pass++; console.log("  ✓ " + n); }
  else { fail++; console.log("  ✗ " + n); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitFor(fn, ms = 5000, label = "") {
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

const DEVICES = [{ serial: "A1", model: "Pixel", ok: true, checked: true, state: "device" }];

/* 修复前，处理器抛出的异常会以「未处理的 Promise 拒绝」逃离 pollOnce：
   WebView2 里表现为界面静默停摆（不报错、不弹窗，只是什么都不再更新），
   在 node 里则会把进程直接打挂。这里吞掉它，让断言自己去描述故障，
   而不是让测试以进程崩溃收场（那样看不出是哪一条断言失败）。 */
process.on("unhandledRejection", (e) => {
  console.log("    (未处理的 Promise 拒绝：" + ((e && e.message) || e) + ")");
});

const watchdog = setTimeout(() => {
  console.log("    (看门狗触发：疑似断言抛错导致未收尾)");
  process.exit(fail ? 1 : 0);
}, 90000);

function mkEnv() {
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const pending = [
    { kind: "booted", payload: { version: "v-test", warnings: [], adb: "adb",
                                 commands: [], settings: {} } },
    { kind: "devices", payload: { items: DEVICES } },
  ];
  const impl = {
    boot: () => Promise.resolve({ version: "v-test", warnings: [], adb: "adb",
                                  commands: [], settings: {} }),
    take_events: () => Promise.resolve(pending.splice(0)),
    default_save_dir: () => Promise.resolve({ dir: "" }),
    save_settings: () => Promise.resolve({ ok: true }),
  };
  window.pywebview = {
    api: new Proxy(impl, {
      get(t, k) {
        if (k === "then") return undefined;
        if (k in t) return t[k];
        return () => Promise.resolve({ ok: true });
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  return { window, doc: window.document, pending };
}

/* 让「渲染设备列表」必定抛异常：把计数节点的 textContent 写入变成炸弹 */
function poisonDeviceRender(doc) {
  const node = doc.getElementById("dev-count");
  if (!node) return false;
  Object.defineProperty(node, "textContent", {
    configurable: true,
    get() { return ""; },
    set() { throw new Error("模拟渲染异常：节点写入失败"); },
  });
  return true;
}

(async () => {
  const { doc, pending } = mkEnv();
  const statusText = () => {
    const node = doc.getElementById("status");
    return node ? node.textContent : "";
  };
  const countNotices = () =>
    (statusText().match(/事件处理失败（devices）/g) || []).length;

  const up = await waitFor(() => /A1/.test(doc.body.textContent || ""), 6000, "启动渲染");
  ok(up, "程序启动并完成首次事件分发");
  ok(poisonDeviceRender(doc), "已把设备计数节点改成「一写就抛异常」");

  console.log("\n[A] 抛异常的事件之后，后续事件仍被处理");
  {
    pending.push({ kind: "devices", payload: { items: DEVICES } });
    pending.push({ kind: "status", payload: { type: "info", text: "标记-甲-轮询仍活着" } });
    const got = await waitFor(() => statusText().indexOf("标记-甲-轮询仍活着") >= 0,
                              6000, "异常之后的正常事件");
    ok(got, "抛异常的那条没有打断轮询链：紧接着的状态事件照常渲染");
  }

  console.log("\n[B] 抛异常的事件被跳过并给出可读提示");
  {
    const notice = await waitFor(() => countNotices() > 0, 4000, "错误提示");
    ok(notice, "状态栏出现「事件处理失败（devices）」提示，而不是静默丢失");
    ok(/后续事件继续处理/.test(statusText()), "提示里说明了界面不会因此停摆");
    ok(/模拟渲染异常/.test(statusText()), "提示里带上了真实原因，便于定位");

    const before = countNotices();
    pending.push({ kind: "devices", payload: { items: DEVICES } });
    pending.push({ kind: "devices", payload: { items: DEVICES } });
    pending.push({ kind: "status", payload: { type: "info", text: "标记-乙" } });
    const alive = await waitFor(() => statusText().indexOf("标记-乙") >= 0, 5000, "标记乙");
    ok(alive, "连续多条同类坏事件之后，轮询依然在工作");
    ok(countNotices() === before,
      "同类坏事件不重复提示（否则每 400ms 一条会刷爆状态栏）");
  }

  console.log("\n[C] 一批里「正常 → 坏 → 正常」：后面的不能被连坐");
  {
    pending.push({ kind: "console", payload: { kind: "out", text: "批内-第一行" } });
    pending.push({ kind: "devices", payload: { items: DEVICES } });
    pending.push({ kind: "console", payload: { kind: "out", text: "批内-第二行" } });
    const ok2 = await waitFor(() => {
      const c = doc.getElementById("console");
      const t = c ? c.textContent : "";
      return t.indexOf("批内-第一行") >= 0 && t.indexOf("批内-第二行") >= 0;
    }, 6000, "同批事件");
    ok(ok2, "坏事件前后两条 console 输出都渲染出来了（不是整批被丢弃）");
  }

  console.log("\n[D] 多轮之后仍在续约");
  {
    pending.push({ kind: "status", payload: { type: "ok", text: "标记-丙" } });
    const a = await waitFor(() => statusText().indexOf("标记-丙") >= 0, 4000, "标记丙");
    pending.push({ kind: "status", payload: { type: "ok", text: "标记-丁" } });
    const b = await waitFor(() => statusText().indexOf("标记-丁") >= 0, 4000, "标记丁");
    ok(a && b, "连续两轮推送都被消费（轮询没有停在上一轮）");
  }

  clearTimeout(watchdog);
  console.log("\n" + "=".repeat(46));
  console.log("poll_resilience: " + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
