/* jsdom 前端行为测试：各项配置的文件存储（config.json 持久化）
   需求：过滤筛选、保存路径等配置每次启动恢复以往配置，并有防错默认值。

   这里锁定：
     1. HTML 默认勾选与后端 PREFS_DEFAULTS 对齐（默认开启类不被默认值覆盖）；
     2. booted.settings 快照回填全部偏好控件（含覆盖 HTML 默认勾选的场景）；
     3. settings_warnings（后端防错纠正）在状态栏可见；
     4. 每个控件的 change/input 都即时落盘 save_settings（键名与后端 schema 一致）；
     5. 配置缺失时保持界面默认（不回填、不改写）。
   后端侧（schema / sanitize / 原子写）由 tests/test_core_prefs.py 锁定。 */
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

/** 起一个带调用记录的假后端：booted 载荷可指定 settings / settings_warnings。 */
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
        settings_warnings: opts.settings_warnings || [],
        config_path: opts.config_path || "C:\\Program Files\\ADB\\config.json",
        save_dir_effective: opts.save_dir_effective || "",
        save_dir_note: opts.save_dir_note || null,
        lc_buffers: { "main（主日志）": ["main"],
                      "全部（main+system+events+crash）":
                        ["main", "system", "events", "crash"] },
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

(async () => {
  console.log("\n[1] 界面默认与后端 schema 默认对齐");
  {
    const { window } = mkEnv();
    const doc = window.document;
    const on = ["keep-input", "shot-clipboard", "lc-cap-zipstop",
                "rec-pointer-location", "rec-show-touches", "lc-autoscroll",
                "rec-logcat", "rec-zip"];
    const off = ["lc-only-exc"];
    on.forEach((id) => ok(doc.getElementById(id).checked === true,
      id + " 默认勾选（默认开启）"));
    off.forEach((id) => ok(doc.getElementById(id).checked === false,
      id + " 默认不勾选"));
  }

  console.log("\n[2] booted.settings 快照回填（覆盖 HTML 默认勾选）");
  {
    const { window } = mkEnv({ settings: {
      keep_input: false, shot_to_clipboard: false,
      lc_keyword: "crash", lc_only_exc: true, lc_autoscroll: false,
      lc_buffer: "全部（main+system+events+crash）",
      lc_levels: ["D", "I"], lc_cap_zipstop: false, lc_cap_levels: ["E"],
      rec_logcat: true, rec_zip: false,
      rec_pointer_location: false, rec_show_touches: false,
      save_dir: "D:\\shots",
    } });
    ok(await waitFor(() =>
      window.document.getElementById("keep-input").checked === false,
      3000, "keep-input 回填"),
      "上次关掉「保留输入」：启动后不勾选");
    const doc = window.document;
    ok(doc.getElementById("shot-clipboard").checked === false,
       "「同步至粘贴板」按配置取消");
    ok(doc.getElementById("lc-filter").value === "crash",
       "关键字按配置回填（实际：" + doc.getElementById("lc-filter").value + "）");
    ok(doc.getElementById("lc-only-exc").checked === true, "仅异常按配置勾选");
    ok(doc.getElementById("lc-autoscroll").checked === false, "自动滚动按配置取消");
    ok(doc.getElementById("lc-buf").value === "全部（main+system+events+crash）",
       "缓冲区按配置选中（实际：" + doc.getElementById("lc-buf").value + "）");
    const lv = (cid) => Array.from(
      doc.querySelectorAll("#" + cid + " input:checked")).map((c) => c.value).join("");
    ok(lv("lc-levels") === "DI", "实时监控级别回填 D/I（实际：" + lv("lc-levels") + "）");
    ok(doc.getElementById("lc-cap-zipstop").checked === false, "抓取打包按配置取消");
    ok(lv("lc-cap-levels") === "E", "抓取级别回填 E（实际：" + lv("lc-cap-levels") + "）");
    ok(doc.getElementById("rec-logcat").checked === true, "同步 logcat 按配置勾选");
    ok(doc.getElementById("rec-zip").checked === false, "录屏打包按配置取消");
    ok(doc.getElementById("rec-pointer-location").checked === false,
       "指针位置按配置取消（覆盖 HTML 默认勾选）");
    ok(doc.getElementById("rec-show-touches").checked === false,
       "触摸圆点按配置取消（覆盖 HTML 默认勾选）");
    ok(doc.getElementById("tool-dir").value === "D:\\shots",
       "保存目录回填到工具页（实际：" + doc.getElementById("tool-dir").value + "）");
    ok(doc.getElementById("lc-dir").value === "D:\\shots",
       "保存目录镜像到 Logcat 页");
    ok(doc.getElementById("file-dir").value === "D:\\shots",
       "保存目录镜像到文件页");
    // 三张工具卡的收起态各记各的：这里只给了录屏，另外两张必须保持展开
    ok(!doc.getElementById("shot-card").classList.contains("collapsed"),
       "截图卡没给 shot_collapsed → 保持展开");
    ok(!doc.getElementById("scrcpy-card").classList.contains("collapsed"),
       "投屏卡没给 scrcpy_collapsed → 保持展开");
  }

  console.log("\n[3] 配置缺失时保持界面默认（不回填）");
  {
    const { window } = mkEnv({ settings: {} });
    ok(await waitFor(() => !!window.document.getElementById("tool-rec"),
                     3000, "页面就绪"),
       "空 settings 不应让回填补写任何控件");
    const doc = window.document;
    ok(doc.getElementById("keep-input").checked === true, "keep-input 保持默认勾选");
    ok(doc.getElementById("rec-pointer-location").checked === true,
       "rec-pointer-location 保持默认勾选");
    ok(doc.getElementById("rec-show-touches").checked === true,
       "rec-show-touches 保持默认勾选");
    ok(doc.getElementById("tool-dir").value === "", "保存目录缺省为空");
  }

  console.log("\n[4] 防错纠正提示可见（settings_warnings）");
  {
    const { window } = mkEnv({ settings_warnings: [
      "keep_input 的值 'yes' 不是有效的开关，已恢复为 开"] });
    ok(await waitFor(() => {
      const st = window.document.getElementById("status");
      return st && /配置已纠正/.test(st.textContent || "");
    }, 3000, "纠错提示"),
      "被纠正的配置要在状态栏提示用户");
  }

  console.log("\n[5] 各控件 change/input 即时落盘（save_settings 键值对）");
  {
    const { window, calls } = mkEnv();
    const doc = window.document;
    const click = (id) => doc.getElementById(id).click();

    click("keep-input");
    ok(await waitFor(() => saved(calls, "keep_input").length &&
      saved(calls, "keep_input").pop().args[0].keep_input === false, 3000, "keep_input"),
      "取消「保留输入」→ keep_input=false");

    click("shot-clipboard");
    ok(await waitFor(() => saved(calls, "shot_to_clipboard").length &&
      saved(calls, "shot_to_clipboard").pop().args[0].shot_to_clipboard === false,
      3000, "shot_to_clipboard"),
      "取消「同步至粘贴板」→ shot_to_clipboard=false");

    const kw = doc.getElementById("lc-filter");
    kw.value = "ANR in com.demo";
    kw.dispatchEvent(new window.Event("input", { bubbles: true }));
    ok(await waitFor(() => saved(calls, "lc_keyword").length &&
      saved(calls, "lc_keyword").pop().args[0].lc_keyword === "ANR in com.demo",
      3000, "lc_keyword"),
      "关键字防抖结束后落盘 → lc_keyword");

    const dbox = Array.from(doc.querySelectorAll("#lc-levels input"))
      .find((c) => c.value === "D");
    dbox.click();
    ok(await waitFor(() => {
      const hit = saved(calls, "lc_levels").pop();
      return hit && hit.args[0].lc_levels.join("") === "VIWEF";
    }, 3000, "lc_levels"),
      "取消 D → lc_levels=[" + "VIWEF" + "]（顺序保持 V/D/I/W/E/F）");

    click("lc-only-exc");
    ok(await waitFor(() => saved(calls, "lc_only_exc").length &&
      saved(calls, "lc_only_exc").pop().args[0].lc_only_exc === true, 3000, "lc_only_exc"),
      "勾选「仅异常」→ lc_only_exc=true");

    click("lc-autoscroll");
    ok(await waitFor(() => saved(calls, "lc_autoscroll").length &&
      saved(calls, "lc_autoscroll").pop().args[0].lc_autoscroll === false,
      3000, "lc_autoscroll"),
      "取消「自动滚动」→ lc_autoscroll=false");

    const buf = doc.getElementById("lc-buf");
    buf.value = "全部（main+system+events+crash）";
    buf.dispatchEvent(new window.Event("change", { bubbles: true }));
    ok(await waitFor(() => saved(calls, "lc_buffer").length &&
      saved(calls, "lc_buffer").pop().args[0].lc_buffer ===
        "全部（main+system+events+crash）", 3000, "lc_buffer"),
      "切换缓冲区 → lc_buffer");

    click("lc-cap-zipstop");
    ok(await waitFor(() => saved(calls, "lc_cap_zipstop").length &&
      saved(calls, "lc_cap_zipstop").pop().args[0].lc_cap_zipstop === false,
      3000, "lc_cap_zipstop"),
      "取消「结束后打包」→ lc_cap_zipstop=false");

    const cbox = Array.from(doc.querySelectorAll("#lc-cap-levels input"))
      .find((c) => c.value === "V");
    cbox.click();
    ok(await waitFor(() => {
      const hit = saved(calls, "lc_cap_levels").pop();
      return hit && hit.args[0].lc_cap_levels.join("") === "DIWEF";
    }, 3000, "lc_cap_levels"),
      "抓取级别取消 V → lc_cap_levels 落盘");

    // rec-zip 默认勾选：点一次 → false，再点一次 → true（两个方向都锁）
    click("rec-zip");
    ok(await waitFor(() => saved(calls, "rec_zip").length &&
      saved(calls, "rec_zip").pop().args[0].rec_zip === false, 3000, "rec_zip=false"),
      "取消「结束录制后自动压缩」→ rec_zip=false");
    click("rec-zip");
    ok(await waitFor(() => saved(calls, "rec_zip").length &&
      saved(calls, "rec_zip").pop().args[0].rec_zip === true, 3000, "rec_zip=true"),
      "再点一次恢复 → rec_zip=true");

    click("rec-pointer-location");
    ok(await waitFor(() => saved(calls, "rec_pointer_location").length &&
      saved(calls, "rec_pointer_location").pop().args[0].rec_pointer_location === false,
      3000, "rec_pointer_location"),
      "取消「指针位置」→ rec_pointer_location=false");

    click("rec-show-touches");
    ok(await waitFor(() => saved(calls, "rec_show_touches").length &&
      saved(calls, "rec_show_touches").pop().args[0].rec_show_touches === false,
      3000, "rec_show_touches"),
      "取消「触摸圆点」→ rec_show_touches=false");

    // rec-logcat 默认勾选：点一次 → false，再点一次 → true（两个方向都锁）
    click("rec-logcat");
    ok(await waitFor(() => saved(calls, "rec_logcat").length &&
      saved(calls, "rec_logcat").pop().args[0].rec_logcat === false,
      3000, "rec_logcat=false"),
      "取消「同步录制 logcat」→ rec_logcat=false");
    click("rec-logcat");
    ok(await waitFor(() => saved(calls, "rec_logcat").length &&
      saved(calls, "rec_logcat").pop().args[0].rec_logcat === true,
      3000, "rec_logcat=true"),
      "再点一次恢复 → rec_logcat=true");

    // 三张工具卡的标题栏单击 → 各自的收起态落盘（互不牵连）
    click("shot-toggle");
    ok(await waitFor(() => saved(calls, "shot_collapsed").length &&
      saved(calls, "shot_collapsed").pop().args[0].shot_collapsed === true,
      3000, "shot_collapsed"),
      "收起截图卡 → shot_collapsed=true");
    click("scrcpy-toggle");
    ok(await waitFor(() => saved(calls, "scrcpy_collapsed").length &&
      saved(calls, "scrcpy_collapsed").pop().args[0].scrcpy_collapsed === true,
      3000, "scrcpy_collapsed"),
      "收起投屏卡 → scrcpy_collapsed=true（与截图卡分开记）");

    const dir = doc.getElementById("tool-dir");
    dir.value = "D:\\new-shots";
    dir.dispatchEvent(new window.Event("change", { bubbles: true }));
    ok(await waitFor(() => saved(calls, "save_dir").length &&
      saved(calls, "save_dir").pop().args[0].save_dir === "D:\\new-shots",
      3000, "save_dir"),
      "改保存目录 → save_dir 落盘（下次启动 default_save_dir 直接用它）");
    ok(doc.getElementById("lc-dir").value === "D:\\new-shots",
       "保存目录三处输入实时镜像");
  }

  console.log("\n[6] 指令过滤关键字落盘（cmd_filter）");
  {
    const { window, calls } = mkEnv();
    const doc = window.document;
    const f = doc.getElementById("cmd-filter");
    f.value = "install";
    f.dispatchEvent(new window.Event("input", { bubbles: true }));
    ok(await waitFor(() => saved(calls, "cmd_filter").length &&
      saved(calls, "cmd_filter").pop().args[0].cmd_filter === "install",
      3000, "cmd_filter"),
      "指令台搜索关键字防抖结束后落盘 → cmd_filter");
  }

  console.log("\n[7] 配置文件位置展示 + 保存目录失效提示");
  {
    const { window } = mkEnv({
      config_path: "D:\\Tools\\ADB\\config.json",
      save_dir_note: "配置里的保存目录在本机不存在，已改用默认目录：C:\\Users\\X\\Pictures\\ADB",
    });
    const doc = window.document;
    ok(await waitFor(() =>
      (doc.getElementById("about-config-path").textContent || "")
        .indexOf("config.json") >= 0, 3000, "配置路径"),
      "关于页展示 config.json 的绝对路径");
    ok(doc.getElementById("about-config-path").textContent
         === "D:\\Tools\\ADB\\config.json",
       "配置文件路径与后端下发一致（实际：" +
       doc.getElementById("about-config-path").textContent + "）");
    ok(await waitFor(() => {
      const st = doc.getElementById("status");
      return st && /不存在.*默认目录/.test(st.textContent || "");
    }, 3000, "路径回退提示"),
      "保存目录在本机不存在时要在状态栏提示（否则用户以为同步成功了）");
  }

  console.log("\n[8] 指令过滤关键字回填（booted.settings）");
  {
    const { window } = mkEnv({ settings: { cmd_filter: "am start" } });
    const doc = window.document;
    ok(await waitFor(() =>
      doc.getElementById("cmd-filter").value === "am start", 3000, "cmd_filter 回填"),
      "上次的指令台搜索关键字按配置回填（实际：" +
      doc.getElementById("cmd-filter").value + "）");
  }

  // 多窗口共存时不调 window.close()（jsdom 的 close 会挂起），
  // 与 keep_input.test.cjs 一致：process.exit 直接终掉整个进程。
  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
