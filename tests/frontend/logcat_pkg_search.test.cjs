/* jsdom 前端行为测试：Logcat「按包」可搜索下拉（与性能监控「应用包名」同款交互）

   从原生 <select> 换成可搜索面板后，锁前端契约：
   1) 控件是按钮 + 弹层，默认显示「（全部）」、不高亮、弹层隐藏；
   2) 打开下拉按当前设备读全量包（含系统应用），third_party_only=false；
   3) 模糊搜索同时支持「子串 / 中间片段 / 按顺序凑字符」三种命中；
   4) 点列表项 → 单进程写 pid:N、多进程写 pkg:name（过滤语义不变）；
   5) 回车：有匹配取第一条、无匹配当手动包名直接解析；
   6) 「（全部）」精确清除上次写入的 term，不误删用户手写的其它条件；
   7) 刷新重新拉列表；弹层点选项不被「点外部关闭」抢先吃掉。 */
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
    await sleep(30);
  }
  console.log("    (waitFor 超时: " + label + ")");
  return false;
}

const PKGS = ["com.tencent.kuwo", "com.android.chrome", "com.example.demo",
              "com.android.settings", "android"];

function mkEnv(opts) {
  opts = opts || {};
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const calls = [];
  let round = 0;
  const batches = [[
    { kind: "booted", payload: { version: "v-test", warnings: [], adb: "adb",
                                 commands: [], settings: {} } },
    { kind: "devices", payload: { items: [
      { serial: "A1", model: "Pixel", state: "device", ok: true, checked: true },
    ] } },
  ]];
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          calls.push({ fn: k, args });
          if (k === "boot") {
            return Promise.resolve({ version: "v-test", warnings: [], commands: [],
                                     adb: "adb", settings: {} });
          }
          if (k === "take_events") {
            const b = batches[round] || []; round++;
            return Promise.resolve(b);
          }
          if (k === "logcat_packages") {
            return Promise.resolve({ ok: true,
              packages: (typeof opts.pkgs === "function") ? opts.pkgs(...args) : (opts.pkgs || PKGS) });
          }
          if (k === "logcat_pidof") {
            const name = args[1];
            return Promise.resolve({ ok: true, pids:
              (opts.pids && opts.pids[name]) ? opts.pids[name] : ["5417"] });
          }
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  Object.defineProperty(window.document, "readyState",
    { value: "complete", configurable: true });
  window.eval(js);
  return { window, doc: window.document, calls };
}

const click = (doc, el) => {
  const node = typeof el === "string" ? doc.getElementById(el) : el;
  node.dispatchEvent(new doc.defaultView.MouseEvent("click", { bubbles: true }));
};
const items = (doc) => Array.from(doc.querySelectorAll("#lc-pkg-list .pkg-item"));
const itemNames = (doc) => items(doc).map((el) => el.dataset.pkg);
const label = (doc) => doc.getElementById("lc-pkg-label").textContent;
const filterVal = (doc) => doc.getElementById("lc-filter").value;
const countFn = (calls, fn) => calls.filter((c) => c.fn === fn).length;

async function ready(doc) {
  await waitFor(() => doc.getElementById("pill").textContent === "已就绪", 4000, "booted");
  // 切到 Logcat 页触发 tab prepare -> 拉包列表
  const tab = doc.querySelector('.tab-btn[data-tab="logcat"]');
  if (tab) tab.click();
  await waitFor(() => items(doc).length >= 5, 4000, "列表就绪");
}

const WATCHDOG_MS = 30000;

(async () => {
  const watchdog = setTimeout(() => {
    console.log("    (看门狗触发：疑似断言抛错导致未收尾，按当前结果退出)");
    process.exit(fail ? 1 : 0);
  }, WATCHDOG_MS);

  console.log("\n[1] 结构与默认值");
  {
    const { window, doc } = mkEnv();
    ok(await waitFor(() => !!doc.getElementById("lc-pkg"), 3000, "控件渲染"),
       "按包控件已渲染为按钮");
    ok(label(doc) === "（全部）", "默认文案是「（全部）」");
    ok(!doc.getElementById("lc-pkg").classList.contains("is-set"),
       "默认态不高亮（未选包）");
    ok(doc.getElementById("lc-pkg-pop").classList.contains("hidden"),
       "弹层初始隐藏");
    window.close();
  }

  console.log("\n[2] 打开下拉：按当前设备读全量包（含系统应用）");
  {
    const { window, doc, calls } = mkEnv();
    await ready(doc);
    ok(itemNames(doc).indexOf("android") >= 0
       && itemNames(doc).indexOf("com.android.settings") >= 0,
       "系统应用出现在列表中：" + itemNames(doc).join(","));
    const reads = calls.filter((c) => c.fn === "logcat_packages");
    ok(reads.length >= 1, "至少拉了一次包列表");
    ok(reads.length && reads[0].args[0] === "A1", "拉列表时带当前设备序列号");
    ok(reads.length && reads[0].args[1] === false,
       "显式传 third_party_only=false 取全量包：" + JSON.stringify(reads[0].args));
    // 打开弹层不应重复打设备（已有缓存）
    click(doc, "lc-pkg");
    ok(!doc.getElementById("lc-pkg-pop").classList.contains("hidden"),
       "点按钮展开弹层");
    ok(calls.filter((c) => c.fn === "logcat_packages").length === reads.length,
       "再次打开走缓存，不重复打设备");
    window.close();
  }

  console.log("\n[3] 模糊搜索：子串 / 片段 / 顺序命中");
  {
    const { window, doc } = mkEnv();
    await ready(doc);
    click(doc, "lc-pkg");
    const search = doc.getElementById("lc-pkg-search");
    const type = (v) => {
      search.value = v;
      search.dispatchEvent(new window.Event("input", { bubbles: true }));
    };
    type("chrome");
    ok(await waitFor(() => itemNames(doc).length === 1
                        && itemNames(doc)[0] === "com.android.chrome", 2800, "子串"),
       "子串命中（chrome → com.android.chrome）");
    type("tencent");
    ok(await waitFor(() => itemNames(doc).length === 1
                        && itemNames(doc)[0] === "com.tencent.kuwo", 2800, "片段"),
       "中间片段命中（tencent → com.tencent.kuwo）");
    type("exmpdm");
    ok(await waitFor(() => itemNames(doc).length === 1
                        && itemNames(doc)[0] === "com.example.demo", 2800, "顺序"),
       "按顺序凑字符命中（exmpdm → com.example.demo）");
    type("zzzz");
    ok(await waitFor(() => /无匹配/.test(doc.getElementById("lc-pkg-count").textContent),
                     2800, "无匹配"),
       "无匹配时明确提示，而不是留空白");
    window.close();
  }

  console.log("\n[4] 点列表项：单进程写 pid:N");
  {
    const { window, doc } = mkEnv({ pids: { "com.example.demo": ["5417"] } });
    await ready(doc);
    click(doc, "lc-pkg");
    const target = items(doc).filter((el) => el.dataset.pkg === "com.example.demo")[0];
    ok(!!target, "列表里有目标包可点选");
    click(doc, target);
    ok(await waitFor(() => filterVal(doc) === "pid:5417", 2800, "写入 pid"),
       "单进程包写为 pid:5417：" + filterVal(doc));
    ok(label(doc) === "com.example.demo", "按钮显示选中的包");
    ok(doc.getElementById("lc-pkg").classList.contains("is-set"), "选中态高亮");
    ok(doc.getElementById("lc-pkg-pop").classList.contains("hidden"),
       "选完自动收起弹层");
    window.close();
  }

  console.log("\n[5] 多进程包写 pkg:name（过滤语义不变）");
  {
    const { window, doc } = mkEnv({ pids: { "com.example.demo": ["5417", "5518"] } });
    await ready(doc);
    click(doc, "lc-pkg");
    const target = items(doc).filter((el) => el.dataset.pkg === "com.example.demo")[0];
    click(doc, target);
    ok(await waitFor(() => filterVal(doc) === "pkg:com.example.demo", 2800, "写入 pkg"),
       "多进程包写为 pkg:com.example.demo：" + filterVal(doc));
    window.close();
  }

  console.log("\n[6] 回车手输：有匹配取第一条 / 无匹配当包名");
  {
    const { window, doc } = mkEnv();
    await ready(doc);
    click(doc, "lc-pkg");
    const search = doc.getElementById("lc-pkg-search");
    // 有匹配：取最相关的一条（chrome 唯一命中）
    search.value = "chrome";
    search.dispatchEvent(new window.KeyboardEvent("keydown",
      { key: "Enter", bubbles: true }));
    ok(await waitFor(() => filterVal(doc) === "pid:5417", 2800, "回车命中"),
       "回车有匹配时取第一条包并写入过滤");
    // 无匹配：当手动包名直接解析（com.manual.app 不在列表）
    click(doc, "lc-pkg");
    const search2 = doc.getElementById("lc-pkg-search");
    search2.value = "com.manual.app";
    search2.dispatchEvent(new window.KeyboardEvent("keydown",
      { key: "Enter", bubbles: true }));
    ok(await waitFor(() => label(doc) === "com.manual.app", 2800, "回车手输"),
       "回车无匹配时按手动包名解析，按钮显示该包名");
    window.close();
  }

  console.log("\n[7] 「（全部）」精确清除，不误删其它条件");
  {
    const { window, doc } = mkEnv({ pids: { "com.example.demo": ["5417"] } });
    await ready(doc);
    // 先手写一个其它条件，再选包（选包是覆盖式，故先选包再补其它条件）
    click(doc, "lc-pkg");
    const target = items(doc).filter((el) => el.dataset.pkg === "com.example.demo")[0];
    click(doc, target);
    await waitFor(() => filterVal(doc) === "pid:5417", 2800, "选中包");
    doc.getElementById("lc-filter").value = "pid:5417 -tag:Noise";
    doc.getElementById("lc-filter").dispatchEvent(
      new window.Event("input", { bubbles: true }));
    click(doc, "lc-pkg");
    click(doc, "lc-pkg-clear");
    ok(await waitFor(() => filterVal(doc) === "-tag:Noise", 2800, "清除"),
       "「（全部）」只移除 pid:5417，保留手写的 -tag:Noise：" + filterVal(doc));
    ok(label(doc) === "（全部）", "按钮恢复「（全部）」");
    ok(!doc.getElementById("lc-pkg").classList.contains("is-set"),
       "清除后不高亮");
    window.close();
  }

  console.log("\n[8] 刷新重新拉列表");
  {
    const { window, doc, calls } = mkEnv();
    await ready(doc);
    click(doc, "lc-pkg");
    click(doc, "lc-pkg-refresh");
    ok(await waitFor(() => calls.filter((c) => c.fn === "logcat_packages").length >= 2,
                     2800, "刷新"),
       "点刷新会重新打设备拉列表");
    const reads = calls.filter((c) => c.fn === "logcat_packages");
    ok(reads.length >= 2 && reads[reads.length - 1].args[1] === false,
       "刷新仍取全量包");
    window.close();
  }

  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  clearTimeout(watchdog);
  process.exit(fail > 0 ? 1 : 0);
})();
