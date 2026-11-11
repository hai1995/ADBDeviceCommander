/* jsdom 前端行为测试：命令备注（note）字段
 *
 * 后端 core.commands 已保证 note 非空时进、空时不进、类型不对不进；
 * 这里锁前端两条关键行为：
 *   1. cmd-chip hover 的 title 末尾能看到备注（有 note 时换一行拼上）；
 *   2. 没有 note 的命令 title 不应凭空多出一块；
 *   3. 编辑弹窗里有备注 textarea（结构存在）。 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.join(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "frontend/index.html"), "utf8");
const js = fs.readFileSync(path.join(ROOT, "frontend/js/app.js"), "utf8");

let pass = 0, fail = 0;
function ok(cond, name) {
  if (cond) { pass++; console.log("  ✓ " + name); }
  else { fail++; console.log("  ✗ " + name); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitFor(fn, ms = 5000, label = "") {
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

async function boot(userCmds) {
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
  const w = dom.window;
  let round = 0;
  w.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          if (k === "boot") {
            return Promise.resolve({
              version: "2026.1110.0836", warnings: [], adb: "adb",
              commands: userCmds, settings: {}, state_labels: [], lc_buffers: [],
              adb_ok: true,
            });
          }
          if (k === "take_events") {
            const b = round === 0
              ? [{ kind: "booted",
                   payload: { version: "2026.1110.0836", warnings: [], adb: "adb",
                              commands: userCmds, settings: {}, state_labels: [],
                              lc_buffers: [], adb_ok: true } }]
              : [];
            round++;
            return Promise.resolve(b);
          }
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(w.document, "readyState",
                        { value: "complete", configurable: true });
  w.eval(js);
  const d = w.document;
  await waitFor(() => !!d.querySelector(".cmd-chip"), 5000, "命令渲染");
  return { w, d };
}

(async () => {
  console.log("\n命令备注（note）\n");

  // ① 有 note 的命令：chip.title 末尾拼上备注（换一行）
  {
    const { w, d } = await boot([
      { id: "u1", name: "重启车机", labels: ["通用"],
        note: "会重启所有服务，请保存好现场数据",
        commands: [{ command: "adb reboot" }] },
    ]);
    const chip = d.querySelector(".cmd-chip");
    ok(!!chip, "有命令时渲染 cmd-chip");
    const t = chip && chip.getAttribute("title");
    ok(t && t.includes("重启车机"), "title 包含命令名");
    ok(t && t.includes("会重启所有服务"), "title 包含备注（hover 时能看到）");
  }

  // ② 没有 note 的命令：title 里不该有多余的换行/空串
  {
    const { w, d } = await boot([
      { id: "u2", name: "查看时间", labels: ["通用"],
        commands: [{ command: "adb shell date" }] },
    ]);
    const chip = d.querySelector(".cmd-chip");
    ok(!!chip, "有命令时渲染 cmd-chip");
    const t = chip && chip.getAttribute("title");
    ok(t && !/\n\n/.test(t), "无备注的命令 title 里不应出现多余的空行");
  }

  // ③ 编辑弹窗 HTML 结构里有备注 textarea（不是动态创建）
  {
    const dom = new JSDOM(html, { url: "http://localhost/" });
    const d = dom.window.document;
    ok(!!d.getElementById("cmd-edit-note"),
      "编辑弹窗里有 cmd-edit-note textarea");
    const ta = d.getElementById("cmd-edit-note");
    ok(ta && ta.tagName === "TEXTAREA", "备注字段是 <textarea>（支持多行）");
  }

  console.log("\n结果： " + pass + " 通过 / " + fail + " 失败\n");
  process.exit(fail > 0 ? 1 : 0);
})();
