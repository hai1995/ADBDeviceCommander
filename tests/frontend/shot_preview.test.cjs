/* jsdom 前端测试：截图完成后在卡片下方生成预览图（默认自适应 + 可拖拽改大小）

   回归：每次截屏完，截图卡片下方出现预览图；默认宽度自适应工具卡内容区最大宽度，
   右下角手柄可拖动改变大小、双击恢复自适应（与备用投屏预览同一手感）。
   与 mirror_resize 同款 harness + 事件桥（window.__push 喂 take_events）。 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.join(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "frontend/index.html"), "utf8");
const css = fs.readFileSync(path.join(ROOT, "frontend/css/app.css"), "utf8");
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

function mkEnv(opts) {
  opts = opts || {};
  const overrides = opts.overrides || {};
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const calls = [];
  const queue = [];
  let round = 0;
  window.__push = (ev) => queue.push(ev);
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          calls.push({ fn: k, args });
          if (overrides[k]) return overrides[k].apply(null, args);
          if (k === "boot") {
            return Promise.resolve({ ok: true, version: "v-test", warnings: [], adb: "adb" });
          }
          if (k === "take_events") {
            round++;
            if (round === 1) {
              return Promise.resolve([{ kind: "booted", payload: {
                version: "v-test", warnings: [], commands: [], adb: "adb",
                settings: opts.settings || {},
              } }]);
            }
            return Promise.resolve(queue.splice(0, queue.length));
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

function pointerEvent(window, type, x, y) {
  const ev = new window.Event(type, { bubbles: true });
  Object.defineProperty(ev, "clientX", { value: x });
  Object.defineProperty(ev, "clientY", { value: y });
  Object.defineProperty(ev, "pointerId", { value: 1 });
  return ev;
}

// 一段合法 1x1 PNG 的 base64（前端只拼 data:image/png;base64, 校验前缀即可）
const PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGNgYGAAAAAEAAH2FzhVAAAAAElFTkSuQmCC";

(async () => {
  const watchdog = setTimeout(() => {
    console.log("    (看门狗触发)");
    process.exit(fail ? 1 : 0);
  }, 40000);

  console.log("\n[0] 结构：预览块与手柄存在，默认隐藏");
  {
    const { window } = mkEnv();
    const doc = window.document;
    const prev = doc.getElementById("shot-preview");
    const frame = doc.getElementById("shot-preview-frame");
    const img = doc.getElementById("shot-preview-img");
    const grip = doc.getElementById("shot-preview-grip");
    ok(!!prev && !!frame && !!img && !!grip, "存在预览块 / 画面框 / 预览图 / 拖拽手柄");
    ok(prev.hidden === true, "未截屏时预览块带 hidden（不占位）");
    ok(!frame.classList.contains("is-sized"), "未拖过时保持自适应（无内联尺寸）");
    ok(/\.shot-preview-grip\s*\{[^}]*cursor:\s*nwse-resize/.test(css),
       "手柄光标为 nwse-resize（暗示可拖右下角）");
    ok(/\.shot-preview-frame\.is-sized img\s*\{[^}]*object-fit:\s*contain/.test(css),
       "拖出尺寸后画面按 contain 等比缩放（不拉变形）");
    ok(/\.shot-preview-frame\s*\{[^}]*width:\s*100%/.test(css),
       "预览框默认 width:100%（自适应工具卡内容区最大宽度）");
  }

  console.log("\n[1] 截图完成后渲染预览图（data URL，可见）");
  {
    const { window } = mkEnv({
      overrides: {
        screenshot_data: () => Promise.resolve({ ok: true, data: PNG_B64, name: "shot.png" }),
      },
    });
    const doc = window.document;
    await waitFor(() => doc.getElementById("shot-preview"), 3000, "就绪");
    window.__push({ kind: "tool", payload: { type: "screenshot", path: "D:\\x\\shot.png" } });
    const shown = await waitFor(() => {
      const prev = doc.getElementById("shot-preview");
      const img = doc.getElementById("shot-preview-img");
      return prev && !prev.hidden && /^data:image\/png;base64,/.test(img.getAttribute("src") || "");
    }, 4000, "预览图出现");
    ok(shown, "收到截图事件后预览图可见且为 data URL");
    ok((doc.getElementById("shot-preview-name").textContent || "").indexOf("shot.png") >= 0,
       "预览图下方标注文件名");
  }

  console.log("\n[2] 拖动改大小：松手落盘，双击恢复自适应");
  {
    const { window, calls } = mkEnv({
      overrides: {
        screenshot_data: () => Promise.resolve({ ok: true, data: PNG_B64, name: "shot.png" }),
      },
    });
    const doc = window.document;
    const frame = doc.getElementById("shot-preview-frame");
    const grip = doc.getElementById("shot-preview-grip");
    await waitFor(() => !!frame && !!grip, 3000, "就绪");
    // 先触发一次预览，确保 resize 逻辑绑定且预览可见
    window.__push({ kind: "tool", payload: { type: "screenshot", path: "D:\\x\\shot.png" } });
    await waitFor(() => !doc.getElementById("shot-preview").hidden, 3000, "预览出现");

    grip.dispatchEvent(pointerEvent(window, "pointerdown", 100, 100));
    ok(frame.classList.contains("is-resizing"), "按下后进入拖动态");
    grip.dispatchEvent(pointerEvent(window, "pointermove", 200, 150));
    ok(frame.classList.contains("is-sized"), "拖出明确尺寸 -> is-sized");
    // jsdom 无布局：起点退化成代码兜底 320x480（见 bindShotPreviewResize 注释）
    ok(frame.style.width === "420px", "宽度 = 起点 320 + 位移 100（420px）");
    ok(frame.style.height === "530px", "高度 = 起点 480 + 位移 50（530px）");
    const savesDuringDrag = calls.filter((c) => c.fn === "save_settings").length;
    ok(savesDuringDrag === 0, "拖动过程中不落盘");

    grip.dispatchEvent(pointerEvent(window, "pointerup", 200, 150));
    const upSaves = calls.filter((c) => c.fn === "save_settings");
    ok(upSaves.length >= 1, "松手至少写一次配置");
    const patch = upSaves[upSaves.length - 1].args[0] || {};
    ok(patch.shot_preview_w === 420 && patch.shot_preview_h === 530,
       "落盘 shot_preview_w/h = 420 / 530");

    // 双击恢复自适应
    grip.dispatchEvent(pointerEvent(window, "dblclick", 200, 150));
    ok(!frame.classList.contains("is-sized"), "双击后清除 is-sized（恢复自适应）");
    ok(frame.style.width === "" && frame.style.height === "", "双击清除内联尺寸");
  }

  console.log("\n通过 " + pass + " / 失败 " + fail);
  process.exit(fail ? 1 : 0);
})();
