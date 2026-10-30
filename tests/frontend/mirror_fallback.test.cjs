/* jsdom 前端行为测试：工具页「备用投屏」（没装 scrcpy 时的两条降级链路）

   后端降级顺序（scrcpy → screenrecord 管道 → screencap 低帧率预览）由
   tests/test_backend_mirror.py 与 tests/test_backend_controller.py 锁定；
   这里只锁前端：区块结构、点击后调用的后端口径、预览区的显示与隐藏、
   参数回填与落盘（含数值夹取）。 */
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

/** 假后端：mirror_probe / mirror_start 的返回可按用例定制。 */
function mkEnv(opts) {
  opts = opts || {};
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const calls = [];
  let round = 0;
  const settings = opts.settings || {};
  const batches = [
    [{ kind: "booted",
       payload: { version: "v-test", warnings: [], adb: "adb", commands: [],
                  settings } },
     { kind: "devices",
       payload: { items: opts.noDevice ? [] :
                  [{ serial: "S1", model: "M", state: "device", ok: true, checked: true }] } }],
  ];
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          calls.push({ fn: k, args });
          if (k === "boot") {
            return Promise.resolve({ version: "v-test", warnings: [], commands: [],
                                     adb: "adb", settings });
          }
          if (k === "take_events") { const b = batches[round] || []; round++; return Promise.resolve(b); }
          if (k === "scrcpy_probe") {
            return Promise.resolve(opts.scrcpyProbe || { ok: false, note: "未找到 scrcpy" });
          }
          if (k === "mirror_probe") {
            return Promise.resolve(opts.probe || {
              scrcpy: { ok: false, note: "未找到 scrcpy" },
              player: { ok: true, kind: "mpv", path: "/usr/bin/mpv", note: "来自系统 PATH" },
            });
          }
          if (k === "mirror_start") {
            return Promise.resolve(opts.startRes || {
              ok: true, started: [{ serial: "S1", mode: "pipe", frame_url: "" }],
              skipped: [], failed: [],
            });
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

const callsOf = (calls, fn) => calls.filter((c) => c.fn === fn);
const savedPatch = (calls, key) => {
  const hit = callsOf(calls, "save_settings").filter((c) => c.args[0] && key in c.args[0]);
  return hit.length ? hit[hit.length - 1].args[0][key] : undefined;
};
const click = (doc, id) => doc.getElementById(id).dispatchEvent(
  new doc.defaultView.Event("click", { bubbles: true }));

/* 看门狗：断言抛错会被 unhandledRejection 吞掉，而预览的 setInterval 又不停，
   进程会挂住（曾卡死整套前端测试）。到点按当前结果强制退出。 */
const WATCHDOG_MS = 30000;

(async () => {
  const watchdog = setTimeout(() => {
    console.log("    (看门狗触发：疑似断言抛错导致未收尾，按当前结果退出)");
    process.exit(fail ? 1 : 0);
  }, WATCHDOG_MS);

  console.log("\n[1] 备用投屏区块结构完整");
  {
    const { window } = mkEnv();
    const doc = window.document;
    ok(await waitFor(() => !!doc.getElementById("tool-mirror"), 3000, "页面就绪"),
       "工具页已渲染");
    ok(!!doc.getElementById("tool-mirror"), "存在「备用投屏」按钮");
    ok(!!doc.getElementById("tool-mirror-stop"), "存在「停止投屏」按钮");
    ok(!!doc.getElementById("mirror-state"), "存在备用投屏状态行");
    ok(!!doc.getElementById("mirror-preview") && !!doc.getElementById("mirror-view"),
       "存在内嵌预览区（低帧率预览用）");
    ok(doc.getElementById("mirror-preview").hidden === true, "预览区默认隐藏");
    ok(doc.getElementById("tool-mirror-stop").disabled === true, "未投屏时「停止」不可点");
    ok(!!doc.getElementById("mirror-size") && !!doc.getElementById("mirror-bitrate")
       && !!doc.getElementById("mirror-fps") && !!doc.getElementById("mirror-player-path"),
       "分辨率 / 码率 / 帧率 / 播放器路径 四个参数项齐备");
  }

  console.log("\n[2] 无受控设备时备用投屏按钮禁用");
  {
    const { window } = mkEnv({ noDevice: true });
    const doc = window.document;
    ok(await waitFor(() => doc.getElementById("tool-mirror")
      && doc.getElementById("tool-mirror").disabled === true, 3000, "按钮禁用"),
      "没有勾选设备 → 「备用投屏」不可点");
  }

  console.log("\n[3] 探测结果预告会落到哪一档");
  {
    // 装了 scrcpy：提示优先用上方按钮
    const a = mkEnv({ probe: { scrcpy: { ok: true, version: "2.4", path: "/b/scrcpy" },
                               player: { ok: false } } });
    ok(await waitFor(() => {
      const el = a.window.document.getElementById("mirror-state");
      return el && /scrcpy/.test(el.textContent);
    }, 3000, "scrcpy 提示"), "已装 scrcpy → 提示直接用上方按钮");

    // 没 scrcpy 但有播放器
    const b = mkEnv({ probe: { scrcpy: { ok: false },
                               player: { ok: true, kind: "mpv", path: "/usr/bin/mpv" } } });
    ok(await waitFor(() => {
      const el = b.window.document.getElementById("mirror-state");
      return el && /mpv/.test(el.textContent) && /screenrecord/.test(el.textContent);
    }, 3000, "播放器提示"), "有播放器 → 提示走 screenrecord → mpv 播放器窗口");

    // 两者都没有
    const c = mkEnv({ probe: { scrcpy: { ok: false }, player: { ok: false } } });
    ok(await waitFor(() => {
      const el = c.window.document.getElementById("mirror-state");
      return el && /低帧率预览/.test(el.textContent);
    }, 3000, "兜底提示"), "都没有 → 提示会退化到低帧率预览");
  }

  console.log("\n[4] 点击备用投屏：管道档（画面在播放器窗口，不占预览区）");
  {
    const { window, calls } = mkEnv({
      startRes: { ok: true, started: [{ serial: "S1", mode: "pipe", frame_url: "" }],
                  skipped: [], failed: [] },
    });
    const doc = window.document;
    ok(await waitFor(() => doc.getElementById("tool-mirror")
      && !doc.getElementById("tool-mirror").disabled, 3000, "按钮可用"), "有设备 → 按钮可点");
    click(doc, "tool-mirror");
    ok(await waitFor(() => callsOf(calls, "mirror_start").length > 0, 3000, "调用后端"),
       "点击后调用了 mirror_start");
    const call = callsOf(calls, "mirror_start")[0];
    ok(call.args[0] === null && call.args[1] === "pipe",
       "按「受控设备 + 管道优先」下发（不重复走 scrcpy）");
    ok(await waitFor(() => {
      const el = doc.getElementById("mirror-state");
      return el && el.classList.contains("ok");
    }, 3000, "状态 ok"), "成功后状态行标记为 ok");
    ok(doc.getElementById("mirror-preview").hidden === true,
       "管道档画面在独立播放器窗口 → 内嵌预览区保持隐藏");
  }

  console.log("\n[5] 点击备用投屏：自动降级到低帧率预览（画面内嵌）");
  {
    const { window, calls } = mkEnv({
      startRes: { ok: true,
                  started: [{ serial: "S1", mode: "snap",
                              frame_url: "http://127.0.0.1:12345/frame?serial=S1" }],
                  skipped: [], failed: [] },
    });
    const doc = window.document;
    await waitFor(() => doc.getElementById("tool-mirror")
      && !doc.getElementById("tool-mirror").disabled, 3000, "按钮可用");
    click(doc, "tool-mirror");
    ok(await waitFor(() => doc.getElementById("mirror-preview").hidden === false,
                     3000, "预览区显示"), "降级到低帧率预览 → 内嵌预览区显示出来");
    ok(await waitFor(() => {
      const img = doc.getElementById("mirror-view");
      return img && /frame\?serial=S1/.test(img.getAttribute("src") || "");
    }, 3000, "帧地址"), "img 指向后端帧服务的地址");
    ok(/&t=/.test(doc.getElementById("mirror-view").getAttribute("src") || ""),
       "帧地址带时间戳参数（强制浏览器每次重新取帧）");
    ok(doc.getElementById("mirror-state").textContent.indexOf("低帧率预览") >= 0,
       "状态行说明当前是低帧率预览档");
  }

  console.log("\n[6] 启动失败时给出原因，且不显示预览");
  {
    const { window } = mkEnv({
      startRes: { ok: false, started: [], skipped: [],
                  failed: [{ serial: "S1", reason: "设备端 screenrecord 未输出画面" }] },
    });
    const doc = window.document;
    await waitFor(() => doc.getElementById("tool-mirror")
      && !doc.getElementById("tool-mirror").disabled, 3000, "按钮可用");
    click(doc, "tool-mirror");
    ok(await waitFor(() => {
      const el = doc.getElementById("mirror-state");
      return el && el.classList.contains("err") && /screenrecord/.test(el.textContent);
    }, 3000, "错误状态"), "失败原因显示在状态行（不是一句「投屏未启动」了事）");
    ok(doc.getElementById("mirror-preview").hidden === true, "失败时不显示预览区");
  }

  console.log("\n[7] 停止投屏：关闭预览并停掉后端会话");
  {
    const { window, calls } = mkEnv({
      startRes: { ok: true,
                  started: [{ serial: "S1", mode: "snap",
                              frame_url: "http://127.0.0.1:12345/frame?serial=S1" }],
                  skipped: [], failed: [] },
    });
    const doc = window.document;
    await waitFor(() => doc.getElementById("tool-mirror")
      && !doc.getElementById("tool-mirror").disabled, 3000, "按钮可用");
    click(doc, "tool-mirror");
    await waitFor(() => doc.getElementById("mirror-preview").hidden === false, 3000, "预览起");
    ok(doc.getElementById("tool-mirror-stop").disabled === false, "投屏中「停止」可点");
    click(doc, "tool-mirror-stop");
    ok(await waitFor(() => callsOf(calls, "mirror_stop").length > 0, 3000, "调用停止"),
       "点击后调用了 mirror_stop");
    ok(await waitFor(() => doc.getElementById("mirror-preview").hidden === true,
                     3000, "预览关闭"), "预览区收起（不再后台刷帧）");
    ok(doc.getElementById("tool-mirror-stop").disabled === true, "停止后「停止」回到不可点");
  }

  console.log("\n[8] 参数回填与落盘（含越界夹取）");
  {
    const { window, calls } = mkEnv({
      settings: { mirror_size: "720x1280", mirror_bitrate: 12,
                  mirror_fps: 4, mirror_player_path: "D:/tools/mpv" },
    });
    const doc = window.document;
    ok(await waitFor(() => {
      const el = doc.getElementById("mirror-size");
      return el && el.value === "720x1280";
    }, 3000, "分辨率回填"), "启动回填投屏分辨率");
    ok(doc.getElementById("mirror-bitrate").value === "12", "启动回填码率");
    ok(doc.getElementById("mirror-fps").value === "4", "启动回填预览帧率");
    ok(doc.getElementById("mirror-player-path").value === "D:/tools/mpv", "启动回填播放器路径");

    // 手填越界值：必须夹回合法区间（0 帧率会让后端疯狂抓帧）
    const fps = doc.getElementById("mirror-fps");
    fps.value = "0";
    fps.dispatchEvent(new window.Event("change", { bubbles: true }));
    await sleep(60);
    ok(fps.value === "1", "帧率填 0 → 夹到 1");
    ok(savedPatch(calls, "mirror_fps") === 1, "夹取后的帧率落盘");

    const br = doc.getElementById("mirror-bitrate");
    br.value = "999";
    br.dispatchEvent(new window.Event("change", { bubbles: true }));
    await sleep(60);
    ok(br.value === "50", "码率填 999 → 夹到 50");
    ok(savedPatch(calls, "mirror_bitrate") === 50, "夹取后的码率落盘");

    const sz = doc.getElementById("mirror-size");
    sz.value = "540x960";
    sz.dispatchEvent(new window.Event("change", { bubbles: true }));
    await sleep(60);
    ok(savedPatch(calls, "mirror_size") === "540x960", "分辨率原样落盘");
  }

  clearTimeout(watchdog);
  console.log("\n" + "=".repeat(46));
  console.log(`结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail ? 1 : 0);
})();
