/* jsdom 前端行为测试：启动阶段不许永久停在「连接中…」
 *
 * 现场问题的形状：程序偶发启动后一直显示「连接中…」，设备不刷新、命令台空白，
 * 没有任何报错，只能重开程序。根因是 start() 的启动链上**任何一步**抛异常或
 * 不返回，后面的动作（尤其是事件轮询与 5s 兜底）就再没有机会执行：
 *
 *   start() → default_save_dir() [无超时] → api.boot() → 启动轮询 + 兜底
 *
 * 三种可复现的触发方式（本测试逐个钉住）：
 *   A) 桥接方法返回的 Promise 永不 resolve（default_save_dir 卡死）；
 *   B) window.pywebview.api 已出现、但 boot 方法还没注入（直接调用抛 TypeError）；
 *   C) boot 调用失败 / 超时（后端其实已启动，只是响应丢了）。
 *
 * 修复后必须满足：轮询先于初始化启动；default_save_dir 有超时；boot 方法
 * 可等待；失败有可见提示（启动重试中 / 启动失败），且 5s 兜底照常生效。
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
async function waitFor(fn, ms = 6000, label = "") {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    let v = false;
    try { v = !!fn(); } catch (e) { v = false; }
    if (v) return true;
    await sleep(50);
  }
  console.log("    (waitFor 超时: " + label + ")");
  return false;
}

process.on("unhandledRejection", (e) => {
  console.log("    (未处理的 Promise 拒绝：" + ((e && e.message) || e) + ")");
});

const watchdog = setTimeout(() => {
  console.log("    (看门狗触发：疑似断言抛错导致未收尾)");
  process.exit(fail ? 1 : 0);
}, 60000);

const BOOTED = { kind: "booted", payload: {
  version: "v-test", warnings: [], adb: "adb", commands: [], settings: {},
}};

function mkEnv(impl) {
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  window.pywebview = { api: impl(window) };
  Object.defineProperty(window.document, "readyState",
                        { value: "complete", configurable: true });
  window.eval(js);
  return window;
}

const pillOf = (window) => {
  const p = window.document.getElementById("pill");
  return p ? p.textContent : "";
};
const statusOf = (window) => {
  const s = window.document.getElementById("status");
  return s ? s.textContent : "";
};

(async () => {
  console.log("\n[A] default_save_dir 永不返回：boot 仍必须发出，界面不能卡死");
  {
    let bootCalled = 0;
    const pending = [];
    const window = mkEnv(() => ({
      default_save_dir: () => new Promise(() => {}),   // 永不 resolve
      boot: () => { bootCalled++; return Promise.resolve({ ok: true }); },
      take_events: () => Promise.resolve(pending.splice(0)),
      save_settings: () => Promise.resolve({ ok: true }),
    }));
    // 5s 超时之后才会轮到 boot —— 断言「最终」而不是「立刻」
    const called = await waitFor(() => bootCalled > 0, 9000, "boot 下发");
    ok(called, "default_save_dir 卡死时 boot 仍被调用（超时放行，不是无限等待）");
    pending.push(BOOTED);
    const ready = await waitFor(() => pillOf(window) === "已就绪", 6000, "已就绪");
    ok(ready, "booted 事件到达后状态变为「已就绪」（实际：" + pillOf(window) + "）");
    window.close();
  }

  console.log("\n[B] api 对象先出现、boot 方法后注入：不许 TypeError 中断启动");
  {
    let bootCalled = 0;
    const pending = [];
    const impl = {
      take_events: () => Promise.resolve(pending.splice(0)),
      default_save_dir: () => Promise.resolve({ dir: "" }),
      save_settings: () => Promise.resolve({ ok: true }),
    };
    const window = mkEnv(() => impl);
    // 模拟桥接的分步注入：api 已存在，但 boot 600ms 后才挂上
    setTimeout(() => {
      impl.boot = () => { bootCalled++; return Promise.resolve({ ok: true }); };
    }, 600);
    const called = await waitFor(() => bootCalled > 0, 6000, "boot 注入后下发");
    ok(called, "等待 boot 真正可调用后才发起（没有因 undefined 调用而中断）");
    pending.push(BOOTED);
    ok(await waitFor(() => pillOf(window) === "已就绪", 6000, "已就绪"),
       "启动最终完成（实际：" + pillOf(window) + "）");
    window.close();
  }

  console.log("\n[C] boot 调用失败：给出可见提示，且轮询仍在跑（可自愈）");
  {
    let attempts = 0;
    const pending = [];
    const window = mkEnv(() => ({
      default_save_dir: () => Promise.resolve({ dir: "" }),
      boot: () => {
        attempts++;
        // 第一次失败，第二次（3s 后的重试）成功 —— 模拟后端已启动、响应丢失
        return attempts === 1 ? Promise.reject(new Error("桥接瞬断"))
                              : Promise.resolve({ ok: true, replayed: true });
      },
      take_events: () => Promise.resolve(pending.splice(0)),
      save_settings: () => Promise.resolve({ ok: true }),
    }));
    ok(await waitFor(() => /启动请求未完成|启动初始化失败/.test(statusOf(window)),
                      6000, "失败提示"),
       "启动失败 / 重试有可见提示，而不是安静地停在「连接中…」");
    ok(await waitFor(() => attempts >= 2, 8000, "自动重试"),
       "3 秒后自动重试 boot（后端 boot 幂等，重放 booted 载荷即可恢复）");
    pending.push(BOOTED);
    ok(await waitFor(() => pillOf(window) === "已就绪", 6000, "重试后已就绪"),
       "重试成功后回到「已就绪」（实际：" + pillOf(window) + "）");
    window.close();
  }

  clearTimeout(watchdog);
  console.log("\n" + "=".repeat(46));
  console.log("boot_stuck_connection: " + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
