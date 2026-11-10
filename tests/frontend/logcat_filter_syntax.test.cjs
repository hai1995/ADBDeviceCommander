/* jsdom 前端行为测试：Logcat 过滤表达式语法（与后端 core/logcat.py 同一套语义）

   覆盖：
     * tag: / msg: / pid:（精确）/ tid: / level:（多字母）
     * - 前缀排除，与包含条件混合
     * 无前缀 = 整行原文搜索（兼容旧行为）
     * pkg: 通过后端 logcat_pidof 解析成 pid 集合后匹配
     * 「按包」下拉：选中包 → 写入过滤表达式
     * 右键菜单提供「按 Tag 过滤 / 排除此 Tag / 按 PID 过滤 / 排除此 PID」

   这套用例的意义：前端必须与后端判得一样。两边规则一旦漂移，用户会看到
   「实时刷新时少了几行」这种最难排查的现象——后端放行、前端又滤掉，
   或者反过来。 */
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
async function waitFor(fn, ms = 6000, label = "") {
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

const dev = (serial) => ({ serial, model: "Pixel", state: "device", ok: true, checked: true });

function line(level, tag, msg, pid, tid) {
  return {
    raw: `11-10 11:23:59.667  ${pid}  ${tid} ${level} ${tag}: ${msg}`,
    level, tag, msg, pid: String(pid), tid: String(tid), exc: false,
  };
}

function mkEnv(batches, apiExtra) {
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
  const { window } = dom;
  let round = 0;
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function () {
          if (k === "boot") return Promise.resolve({ ok: true });
          if (k === "take_events") {
            const b = batches[round] || []; round++;
            return Promise.resolve(b);
          }
          if (apiExtra && apiExtra[k]) return apiExtra[k].apply(null, arguments);
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  return { window };
}

async function bootWith(lines, apiExtra) {
  const { window } = mkEnv([
    [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
     { kind: "devices", payload: { items: [dev("A1")] } }],
    [{ kind: "logcat", payload: {
      serial: "A1", status: "append", lines: lines, total: lines.length, exc: 0 } }],
  ], apiExtra);
  const doc = window.document;
  // 必须等到 logcat 批次真正进缓冲（行数 = 预期总行数），不能只等 /行数:\s*\d+/
  // —— 初始「行数: 0」也会匹配，测试会抢在追加事件之前开始断言。
  await waitFor(
    () => doc.getElementById("lc-counter").textContent.indexOf("行数: " + lines.length) === 0,
    8000, "缓冲就绪");
  return { window, doc };
}

async function applyFilter(doc, kw) {
  const filter = doc.getElementById("lc-filter");
  filter.value = kw;
  filter.dispatchEvent(new doc.defaultView.Event("input", { bubbles: true }));
  // 输入防抖 250ms
  await sleep(450);
}

const counterOf = (doc) => doc.getElementById("lc-counter").textContent;
const hitCount = (doc) => {
  const m = /命中:\s*(\d+)/.exec(counterOf(doc));
  return m ? Number(m[1]) : null;
};

(async () => {
  console.log("\n[1] tag: / -tag: 包含与排除");
  {
    const lines = [
      line("I", "AppTag", "hello", 100, 101),
      line("I", "NoiseTag", "spam", 100, 101),
      line("I", "OtherTag", "world", 100, 101),
    ];
    const { doc } = await bootWith(lines);
    await applyFilter(doc, "tag:AppTag");
    ok(hitCount(doc) === 1, "tag:AppTag 只命中 1 行", counterOf(doc));

    await applyFilter(doc, "-tag:NoiseTag");
    ok(hitCount(doc) === 2, "-tag:NoiseTag 排掉噪音后剩 2 行", counterOf(doc));

    await applyFilter(doc, "tag:AppTag -msg:hello");
    ok(hitCount(doc) === 0, "包含 + 排除同时生效（tag 命中但 msg 被排除）", counterOf(doc));
  }

  console.log("\n[2] pid: 精确匹配（不是子串）");
  {
    const lines = [
      line("I", "T", "a", 4170, 1),
      line("I", "T", "b", 41, 2),
    ];
    const { doc } = await bootWith(lines);
    await applyFilter(doc, "pid:4170");
    ok(hitCount(doc) === 1, "pid:4170 只命中 4170，不命中 41", counterOf(doc));
    await applyFilter(doc, "pid:41");
    ok(hitCount(doc) === 1, "pid:41 只命中 41", counterOf(doc));
    await applyFilter(doc, "-pid:41");
    ok(hitCount(doc) === 1, "-pid:41 只排掉 41", counterOf(doc));
  }

  console.log("\n[3] level: 多字母（回归：旧后端写成子串判断永不命中）");
  {
    const lines = [
      line("V", "T", "v", 1, 1),
      line("D", "T", "d", 1, 1),
      line("I", "T", "i", 1, 1),
      line("W", "T", "w", 1, 1),
      line("E", "T", "e", 1, 1),
    ];
    const { doc } = await bootWith(lines);
    await applyFilter(doc, "level:EW");
    ok(hitCount(doc) === 2, "level:EW 命中 W/E 两行", counterOf(doc));
  }

  console.log("\n[4] 无前缀 = 整行原文（进程名等非 tag/msg 字段也能搜到）");
  {
    const lines = [
      { raw: "11-10 11:23:59.667  100  101 I T: x com.demo.app:remote",
        level: "I", tag: "T", msg: "x", pid: "100", tid: "101", exc: false },
      line("I", "T", "nothing here", 200, 201),
    ];
    const { doc } = await bootWith(lines);
    await applyFilter(doc, "remote");
    ok(hitCount(doc) === 1, "无前缀在整行里搜，命中进程名里的 remote", counterOf(doc));
  }

  console.log("\n[5] pkg: 依赖后端解析的 pid 集合");
  {
    const lines = [
      line("I", "T", "main", 5417, 1),
      line("I", "T", "remote", 5518, 1),
      line("I", "T", "other", 9999, 1),
    ];
    const { doc } = await bootWith(lines, {
      logcat_pidof: () => Promise.resolve({ ok: true, pids: ["5417", "5518"] }),
    });
    await applyFilter(doc, "pkg:com.demo.app");
    await waitFor(() => hitCount(doc) === 2, 4000, "pkg 解析后命中 2");
    ok(hitCount(doc) === 2, "pkg:com.demo.app 命中该包的两个进程", counterOf(doc));
  }

  console.log("\n[6] 「按包」下拉：选中包 → 写入过滤表达式");
  {
    const lines = [line("I", "T", "main", 5417, 1)];
    const { window, doc } = await bootWith(lines, {
      logcat_packages: () => Promise.resolve({ ok: true, packages: ["com.demo.app", "com.other"] }),
      logcat_pidof: () => Promise.resolve({ ok: true, pids: ["5417"] }),
    });
    const sel = doc.getElementById("lc-pkg");
    const filled = await waitFor(() => sel.options.length >= 3, 4000, "包列表填充");
    ok(filled, "设备确定后包下拉被填充（全部 + 2 个包）", sel.options.length + " 项");

    sel.value = "com.demo.app";
    sel.dispatchEvent(new window.Event("change", { bubbles: true }));
    const applied = await waitFor(
      () => doc.getElementById("lc-filter").value === "pid:5417", 4000, "写入 pid 过滤");
    ok(applied, "单进程包被改写为可读可编辑的 pid:5417",
       doc.getElementById("lc-filter").value);
  }

  console.log("\n[7] 右键菜单：按 Tag / 排除 Tag / 按 PID / 排除 PID");
  {
    const lines = [line("I", "CrashTag", "boom", 5417, 5430)];
    const { window, doc } = await bootWith(lines);
    const view = doc.getElementById("lc-view");
    const lnEl = view.querySelector(".lc-line");
    ok(!!lnEl, "日志行已渲染");
    if (lnEl) {
      const ev = new window.MouseEvent("contextmenu", {
        bubbles: true, cancelable: true, clientX: 40, clientY: 40,
      });
      lnEl.dispatchEvent(ev);
      await sleep(120);
      const menuText = (doc.querySelector(".ctx-menu") || { textContent: "" }).textContent;
      ok(menuText.indexOf("按 Tag 过滤") >= 0, "菜单含「按 Tag 过滤」", menuText);
      ok(menuText.indexOf("排除此 Tag") >= 0, "菜单含「排除此 Tag」", menuText);
      ok(menuText.indexOf("按 PID 过滤") >= 0, "菜单含「按 PID 过滤」", menuText);
      ok(menuText.indexOf("排除此 PID") >= 0, "菜单含「排除此 PID」", menuText);
    }
  }

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
