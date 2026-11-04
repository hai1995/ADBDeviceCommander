/* jsdom 前端行为测试：工具页「设备截图 ▸ 自动保存文件」开关
   —— 默认勾选、勾选态随截图动作下发（api.screenshot 第 3 个参数）、
      取消勾选要写进 settings.json、以及启动按已保存偏好回填。

   回归背景：这个开关决定截图是否写入保存目录。最怕「开关是个摆设」——
   UI 上勾了后端没收到；或者用户关过一次，下次打开又被 HTML 的默认 checked
   覆盖回去（于是保存目录被一堆不想留的截图占满，正是用户要关它的原因）。 */
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

function mkEnv(settings) {
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const window_ = window;
  const calls = [];
  let round = 0;
  const batches = [
    [
      { kind: "booted", payload: {
        version: "v-test", warnings: [], commands: [],
        settings: settings || {},
      } },
      { kind: "devices", payload: { items: dev() } },
    ],
  ];
  window_.pywebview = {
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
  return { window, calls, feed: (b) => batches.push(b) };
}

const waitShot = (calls) => waitFor(
  () => calls.some((c) => c.api === "screenshot"), 2000, "screenshot 调用");

(async () => {
  console.log("\n[1] 默认状态：HTML 里就是勾选的（默认开启）");
  {
    const { window } = mkEnv();
    const cb = window.document.getElementById("shot-save-file");
    ok(!!cb, "存在「自动保存文件」复选框");
    ok(cb.checked === true, "默认勾选（用户装上就落盘）");
    ok(/自动保存文件/.test(window.document.getElementById("tool-shot").parentElement.textContent)
       || /自动保存文件/.test(window.document.querySelector("[data-tab='tools']").textContent),
       "截图卡片里能读到这个选项");
  }

  console.log("\n[2] 点击截图：勾选态要随动作一起下发给后端（第 3 个参数）");
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
    ok(shot.args[2] === true, "默认勾选时应下发 save_file=true（实际 " + shot.args[2] + "）");

    // 与生产一致：截图完成后端广播 shot_state(running=false)，按钮恢复可用
    feed([{ kind: "shot_state", payload: { running: false } }]);
    ok(await waitFor(() => !shotBtn.disabled, 3000, "按钮恢复"),
       "shot_state(running=false) 后按钮恢复，才能进行下一次截图");

    // 取消勾选后再点一次
    const cb = window.document.getElementById("shot-save-file");
    cb.checked = false;
    cb.dispatchEvent(new window.Event("change"));
    ok(await waitFor(
      () => calls.some((c) => c.api === "save_settings"
        && c.args[0].shot_save_file === false), 3000, "save_settings 落盘"),
       "取消勾选要持久化到 settings.json（shot_save_file=false）");
    calls.length = 0;
    window.document.getElementById("tool-shot").click();
    ok(await waitShot(calls), "第二次点击也调用了 screenshot");
    const shot2 = calls.find((c) => c.api === "screenshot");
    ok(shot2.args[2] === false, "关闭后应下发 save_file=false（实际 " + shot2.args[2] + "）");
  }

  console.log("\n[3] 重新打开时按已保存的偏好回填");
  {
    const { window } = mkEnv({ save_dir: "D:\\shots", shot_save_file: false });
    ok(await waitFor(
      () => window.document.getElementById("shot-save-file").checked === false,
      3000, "按偏好取消勾选"),
       "上次被关掉时，启动后不应是勾选态");
  }
  {
    const { window } = mkEnv({ save_dir: "D:\\shots", shot_save_file: true });
    ok(await waitFor(
      () => window.document.getElementById("shot-save-file").checked === true,
      3000, "按偏好勾选"),
       "用户显式开启时，启动后是勾选态");
  }
  {
    const { window } = mkEnv({ save_dir: "D:\\shots" });
    ok(await waitFor(
      () => window.document.getElementById("shot-save-file").checked === true,
      3000, "缺省保持默认"),
       "settings.json 里没这一项时保持默认开启");
  }

  console.log("\n结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
