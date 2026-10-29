/* jsdom 前端行为测试：备用投屏「预览区拖动改大小」

   备用投屏的低帧率预览是一张不断刷新的截图，默认高度只有 280px：看列表、
   看文字全靠猜。这里锁定「右下角手柄能拖动改变大小」的完整行为：
   1) 手柄存在，拖动时宽高各自跟随，拖出明确尺寸后加 is-sized（画面 contain 铺满）；
   2) 松手落盘 mirror_view_w / mirror_view_h（一次写两个键，不拆成两次）；
   3) 拖到过小 / 过大都夹在合理区间（200×120 ~ 卡片宽 / 900 高）；
   4) 双击手柄恢复自适应（清内联样式 + 落盘 0），启动时按上次的尺寸还原。

   jsdom 无布局：getBoundingClientRect 恒为 0，所以拖动起点会退化成代码里的
   兜底值（260×420），断言按这个口径写 —— 也正是「首次拖动不跳变」那条注释
   的由来。 */
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

function mkEnv(settings) {
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const calls = [];
  let round = 0;
  window.pywebview = {
    api: new Proxy({}, {
      get(t, k) {
        if (k === "then") return undefined;
        return function (...args) {
          calls.push({ fn: k, args });
          if (k === "boot") {
            return Promise.resolve({ ok: true, version: "v-test", warnings: [],
                                     adb: "adb" });
          }
          if (k === "take_events") {
            // 偏好（config.json）是随 booted 事件下发的（见 app.js 的 case "booted"），
            // 不是 boot() 的返回值：第一轮 poll 里补一条，第二拍才生效。
            round++;
            if (round === 1) {
              return Promise.resolve([{ kind: "booted", payload: {
                version: "v-test", warnings: [], commands: [], adb: "adb",
                settings: settings || {},
              } }]);
            }
            return Promise.resolve([]);
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
const savesOf = (calls) => calls.filter((c) => c.fn === "save_settings");

(async () => {
  const watchdog = setTimeout(() => {
    console.log("    (看门狗触发：疑似断言抛错导致未收尾，按当前结果退出)");
    process.exit(fail ? 1 : 0);
  }, 30000);

  console.log("\n[0] 结构：手柄在画面框内，样式约定到位");
  {
    const { window } = mkEnv();
    const doc = window.document;
    const frame = doc.getElementById("mirror-frame");
    const grip = doc.getElementById("mirror-grip");
    ok(!!frame && !!grip, "存在 #mirror-frame 与 #mirror-grip");
    ok(frame.contains(doc.getElementById("mirror-view")), "画面 img 在框内");
    ok(grip.parentElement === frame, "手柄是画面框的子元素（绝对定位挂在右下角）");
    ok(/\.mirror-grip\s*\{[^}]*cursor:\s*nwse-resize/.test(css),
       "手柄光标为 nwse-resize（暗示可拖右下角）");
    ok(/\.mirror-frame\.is-sized img\s*\{[^}]*object-fit:\s*contain/.test(css),
       "拖出尺寸后画面按 contain 等比缩放（不拉变形）");
    ok(!frame.classList.contains("is-sized"), "未拖过时保持自适应（无内联尺寸）");
    // 预览块自己声明了 display:inline-flex，会盖掉浏览器默认的 [hidden]{display:none}：
    // 没有全局兜底时「未投屏」的预览位置会空着一块（还带个破图占位）
    ok(/\[hidden\]\s*\{\s*display:\s*none\s*!important/.test(css),
       "全局 [hidden] 兜底存在（display 被组件覆盖时仍能真正隐藏）");
    const prev = doc.getElementById("mirror-preview");
    ok(prev.hidden === true, "未投屏时预览块带 hidden 属性");
  }

  console.log("\n[1] 拖动：宽高各自跟随，松手落盘");
  {
    const { window, calls } = mkEnv();
    const doc = window.document;
    const frame = doc.getElementById("mirror-frame");
    const grip = doc.getElementById("mirror-grip");
    await sleep(60);

    grip.dispatchEvent(pointerEvent(window, "pointerdown", 100, 100));
    ok(frame.classList.contains("is-resizing"), "按下后进入拖动态（显示描边）");
    grip.dispatchEvent(pointerEvent(window, "pointermove", 200, 150));
    ok(frame.classList.contains("is-sized"), "拖出明确尺寸 → is-sized");
    ok(frame.style.width === "360px", "宽度 = 起点 260 + 位移 100（360px）");
    ok(frame.style.height === "470px", "高度 = 起点 420 + 位移 50（470px）");
    ok(savesOf(calls).length === 0, "拖动过程中不落盘（避免每像素写一次配置）");

    grip.dispatchEvent(pointerEvent(window, "pointerup", 200, 150));
    ok(!frame.classList.contains("is-resizing"), "松手退出拖动态");
    const saves = savesOf(calls);
    ok(saves.length === 1, "松手只写一次配置");
    const patch = saves[0] && saves[0].args[0] || {};
    ok(patch.mirror_view_w === 360 && patch.mirror_view_h === 470,
       "一次写入宽高两个键（360 / 470）");
  }

  console.log("\n[2] 夹取：拖太小 / 拖出卡片都落在合法区间");
  {
    const { window } = mkEnv();
    const doc = window.document;
    const frame = doc.getElementById("mirror-frame");
    const grip = doc.getElementById("mirror-grip");
    await sleep(60);

    grip.dispatchEvent(pointerEvent(window, "pointerdown", 300, 300));
    grip.dispatchEvent(pointerEvent(window, "pointermove", -400, -400));
    ok(frame.style.width === "200px" && frame.style.height === "120px",
       "往左上拖过头 → 夹到最小 200×120（不会缩成看不见的一条）");
    grip.dispatchEvent(pointerEvent(window, "pointermove", 4000, 4000));
    ok(parseInt(frame.style.width, 10) <= 702, "往右下拖过头 → 宽度不超过卡片可用宽（702）");
    ok(parseInt(frame.style.height, 10) === 900, "高度上限 900（不写出比屏幕还高的框）");
    grip.dispatchEvent(pointerEvent(window, "pointerup", 4000, 4000));
  }

  console.log("\n[3] 双击手柄：恢复自适应");
  {
    const { window, calls } = mkEnv({ mirror_view_w: 520, mirror_view_h: 640 });
    const doc = window.document;
    const frame = doc.getElementById("mirror-frame");
    const grip = doc.getElementById("mirror-grip");
    await waitFor(() => frame.style.width === "520px", 3000, "还原上次尺寸");
    ok(frame.style.width === "520px" && frame.style.height === "640px",
       "启动时按上次拖出的尺寸还原（520×640）");
    ok(frame.classList.contains("is-sized"), "还原后仍是「明确尺寸」态");

    grip.dispatchEvent(new window.Event("dblclick", { bubbles: true }));
    ok(frame.style.width === "" && frame.style.height === "",
       "双击后清空内联尺寸（回到 CSS 自适应）");
    ok(!frame.classList.contains("is-sized"), "同时退出 is-sized");
    const saves = savesOf(calls);
    const patch = saves.length ? saves[saves.length - 1].args[0] : {};
    ok(patch.mirror_view_w === 0 && patch.mirror_view_h === 0,
       "落盘 0/0（下次启动仍是自适应）");
  }

  clearTimeout(watchdog);
  console.log("\n==============================================");
  console.log("结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
