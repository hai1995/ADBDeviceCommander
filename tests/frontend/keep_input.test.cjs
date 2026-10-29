/* jsdom 前端行为测试：设备指令输入框「保留输入内容」开关
   —— 默认勾选（开启）：点「执行」后输入框保留内容；
      关闭：每次执行（含回车）后清空输入框，并落盘 settings.json；
      下次启动按已存偏好回填，不被 HTML 默认值覆盖。

   回归背景：与「同步至粘贴板」同款语义——最怕开关只是个摆设，或者用户关过
   一次，下次打开又被 HTML 的默认 checked 覆盖回去。 */
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

/** 起一个带调用记录的假后端：booted 载荷里可指定 settings（模拟 settings.json）。 */
function mkEnv(settings) {
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const calls = [];
  let round = 0;
  const batches = [
    [
      { kind: "booted", payload: {
        version: "v-test", warnings: [], commands: [],
        settings: settings || {},
      } },
    ],
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

const runCustoms = (calls) => calls.filter((c) => c.api === "run_custom");

(async () => {
  console.log("\n[1] 默认状态：HTML 里就是勾选的（默认开启）");
  {
    const { window } = mkEnv();
    const cb = window.document.getElementById("keep-input");
    ok(!!cb, "存在「保留输入内容」复选框");
    ok(cb.checked === true, "默认勾选（用户装上就不被清空打扰）");
    ok(/保留输入内容/.test(
      window.document.querySelector("section.tab[data-tab='cmd']").textContent),
       "指令页里能读到这个选项");
  }

  console.log("\n[2] 开启（默认）：点「执行」后输入框保留内容");
  {
    const { window, calls } = mkEnv();
    const doc = window.document;
    const input = doc.getElementById("cmd-input");
    input.value = "adb shell dumpsys battery";
    doc.getElementById("btn-run").click();
    ok(await waitFor(() => runCustoms(calls).length === 1, 2000, "run_custom 调用"),
       "点击执行下发 run_custom");
    ok(runCustoms(calls)[0].args[0] === "adb shell dumpsys battery",
       "下发的是输入框里的命令文本");
    await sleep(60);
    ok(input.value === "adb shell dumpsys battery",
       "执行后输入框内容保留（实际：" + input.value + "）");
  }

  console.log("\n[3] 关闭：点「执行」后输入框清空，并落盘 keep_input=false");
  {
    const { window, calls } = mkEnv();
    const doc = window.document;
    const cb = doc.getElementById("keep-input");
    const input = doc.getElementById("cmd-input");
    cb.checked = false;
    cb.dispatchEvent(new window.Event("change"));
    ok(await waitFor(
      () => calls.some((c) => c.api === "save_settings"
        && c.args[0].keep_input === false), 3000, "save_settings 落盘"),
       "取消勾选要持久化到 settings.json（keep_input=false）");
    input.value = "adb shell wm size";
    doc.getElementById("btn-run").click();
    ok(await waitFor(() => runCustoms(calls).length === 1, 2000, "run_custom 调用"),
       "点击执行下发 run_custom");
    await sleep(60);
    ok(input.value === "", "关闭后执行即清空输入框（实际：" + input.value + "）");
    ok(doc.getElementById("btn-cmd-input-clear").hidden === true,
       "清空后输入框右侧的 × 一并隐藏");

    // 回车路径同样遵守该开关
    input.value = "adb shell df";
    input.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await sleep(60);
    ok(input.value === "", "回车执行后同样清空（实际：" + input.value + "）");
  }

  console.log("\n[4] 重新打开时按已保存的偏好回填");
  {
    const { window } = mkEnv({ keep_input: false });
    ok(await waitFor(
      () => window.document.getElementById("keep-input").checked === false,
      3000, "按偏好取消勾选"),
       "上次被关掉时，启动后不应是勾选态");
  }
  {
    const { window } = mkEnv({ keep_input: true });
    ok(await waitFor(
      () => window.document.getElementById("keep-input").checked === true,
      3000, "按偏好勾选"),
       "用户显式开启时，启动后是勾选态");
  }
  {
    const { window } = mkEnv({ save_dir: "D:\\x" });
    ok(await waitFor(
      () => window.document.getElementById("keep-input").checked === true,
      3000, "缺省保持默认"),
       "settings.json 里没这一项时保持默认开启");
  }

  console.log("\n结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
