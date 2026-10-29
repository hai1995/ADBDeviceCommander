/* jsdom 前端行为测试：工具页「设备截图 ▸ 同步至粘贴板」开关
   —— 默认勾选、把布尔值随截图动作下发、改开关要写进 settings.json、
      以及启动时要按后端下发的偏好回填（而不是永远停在 HTML 的默认值上）。

   回归背景：这个功能以前不存在，最怕的是「开关只是个摆设」——UI 上勾了，
   后端压根没收到；或者用户关过一次，下次打开又被 HTML 的默认 checked 覆盖回去。 */
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

const dev = () => ([
  { serial: "A1", model: "Pixel", state: "device", ok: true, checked: true },
]);

/** 起一个带调用记录的假后端：boot 里可指定 settings（模拟 settings.json 偏好）。 */
function mkEnv(settings) {
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const window_ = window;
  const calls = [];
  let round = 0;
  // 与真实后端一致：boot() 只回 {ok:true}，真正的 booted 载荷由 take_events 送达
  // （前端的偏好回填写在 onBooted 里，不打这个事件就测不到「按偏好回填」）。
  const batches = [
    [
      { kind: "booted", payload: {
        version: "v-test", warnings: [], commands: [],
        settings: settings || {},
      } },
      { kind: "devices", payload: { items: dev() } },
    ],
  ];  window_.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          calls.push({ api: k, args: args });
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
  // feed：往轮询队列补一批事件（模拟后端后续广播，如截图完成 shot_state）
  return { window, calls, feed: (b) => batches.push(b) };
}

const waitShot = (calls) => waitFor(
  () => calls.some((c) => c.api === "screenshot"), 2000, "screenshot 调用");

(async () => {
  console.log("\n[1] 默认状态：HTML 里就是勾选的（默认开启）");
  {
    const { window } = mkEnv();
    const cb = window.document.getElementById("shot-clipboard");
    ok(!!cb, "存在「同步至粘贴板」复选框");
    ok(cb.checked === true, "默认勾选（用户装上就用得上）");
    ok(/粘贴板/.test(window.document.getElementById("tool-shot").parentElement.textContent)
       || /粘贴板/.test(window.document.querySelector("[data-tab='tools']").textContent),
       "截图卡片里能读到这个选项");
  }

  console.log("\n[2] 点击截图：勾选态要随动作一起下发给后端");
  {
    const { window, calls, feed } = mkEnv();
    const ready = await waitFor(
      () => window.document.querySelectorAll("#device-list .device-card").length > 0,
      3000, "设备卡片渲染");
    ok(ready, "设备列表已渲染");
    const shotBtn = window.document.getElementById("tool-shot");
    shotBtn.click();
    ok(await waitShot(calls), "点击后调用了 screenshot");
    ok(shotBtn.disabled === true, "点击后按钮禁用（截图在途，防连点）");
    const shot = calls.find((c) => c.api === "screenshot");
    ok(shot.args[1] === true, "默认勾选时应下发 to_clipboard=true（实际 " + shot.args[1] + "）");

    // 与生产一致：截图完成后端广播 shot_state(running=false)，按钮恢复可用，
    // 否则在途禁用会把下一次点击（下面验证 to_clipboard=false 的载体）挡掉
    feed([{ kind: "shot_state", payload: { running: false } }]);
    ok(await waitFor(() => !shotBtn.disabled, 3000, "按钮恢复"),
       "shot_state(running=false) 后按钮恢复，才能进行下一次截图");

    // 取消勾选后再点一次
    const cb = window.document.getElementById("shot-clipboard");
    cb.checked = false;
    cb.dispatchEvent(new window.Event("change"));
    ok(await waitFor(
      () => calls.some((c) => c.api === "save_settings"
        && c.args[0].shot_to_clipboard === false), 3000, "save_settings 落盘"),
       "取消勾选要持久化到 settings.json（shot_to_clipboard=false）");
    calls.length = 0;
    window.document.getElementById("tool-shot").click();
    ok(await waitShot(calls), "第二次点击也调用了 screenshot");
    const shot2 = calls.find((c) => c.api === "screenshot");
    ok(shot2.args[1] === false, "关闭后应下发 to_clipboard=false（实际 " + shot2.args[1] + "）");
  }

  console.log("\n[3] 重新打开时按已保存的偏好回填");
  {
    const { window } = mkEnv({ save_dir: "D:\\shots", shot_to_clipboard: false });
    ok(await waitFor(
      () => window.document.getElementById("shot-clipboard").checked === false,
      3000, "按偏好取消勾选"),
       "上次被关掉时，启动后不应是勾选态");
  }
  {
    const { window } = mkEnv({ save_dir: "D:\\shots", shot_to_clipboard: true });
    ok(await waitFor(
      () => window.document.getElementById("shot-clipboard").checked === true,
      3000, "按偏好勾选"),
       "用户显式开启时，启动后是勾选态");
  }
  {
    const { window } = mkEnv({ save_dir: "D:\\shots" });
    ok(await waitFor(
      () => window.document.getElementById("shot-clipboard").checked === true,
      3000, "缺省保持默认"),
       "settings.json 里没这一项时保持默认开启");
  }

  console.log("\n结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
