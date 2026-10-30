/* jsdom 前端行为测试：①关于页铺满内容区；②设备栏 / 指令台分隔条可拖动调宽。
   验证：
   1. 关于页 CSS 不再有 560px 窄约束（铺满）；
   2. 两个分隔条存在于正确 DOM 位置（面板之间），且带 col-resize 光标样式；
   3. 拖动改变左侧面板宽度；低于最小值被钳制；超过「容器宽 - 右侧保留」被钳制；
   4. 拖动中分隔条与 body 带拖动态 class；松手移除；
   5. 双击分隔条重置为默认宽度（清掉内联 width）。 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.join(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "frontend/index.html"), "utf8");
const js = fs.readFileSync(path.join(ROOT, "frontend/js/app.js"), "utf8");
const css = fs.readFileSync(path.join(ROOT, "frontend/css/app.css"), "utf8");

process.on("unhandledRejection", (e) => { console.log("!! unhandledRejection:", e && e.stack ? e.stack : e); });

let pass = 0, fail = 0;
function ok(c, n) {
  if (c) { pass++; console.log("  ✓ " + n); }
  else { fail++; console.log("  ✗ " + n); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function cssBlock(sel) {
  const i = css.indexOf(sel + " {");
  return i < 0 ? "" : css.slice(i, css.indexOf("}", i));
}

async function boot() {
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
  const { window } = dom;
  const apiStub = new Proxy({}, {
    get(t, k) {
      if (k === "then") return undefined;
      return function () { return Promise.resolve({ ok: true }); };
    },
  });
  window.pywebview = { api: apiStub };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  await sleep(600);
  return window;
}

(async () => {
  console.log("\n[E] 关于页铺满 + 区块可拖动调宽");

  // 1) 关于页铺满：不再有 560px 居中窄约束
  const aboutCss = cssBlock(".about");
  ok(!!aboutCss && /max-width:\s*560px/.test(aboutCss) === false,
    "关于页不再有 max-width:560px 窄约束");
  ok(!!aboutCss && /width:\s*100%/.test(aboutCss), "关于页铺满内容区宽度");

  // 2) 分隔条位置与样式
  const spCss = cssBlock(".splitter");
  ok(!!spCss && /col-resize/.test(spCss), "分隔条带 col-resize 拖动光标");
  ok(/设备栏 ↔ 内容区分隔条/.test(html), "设备栏与内容区之间有分隔条");
  ok(/指令台 ↔ 指令输出分隔条/.test(html), "指令台与指令输出之间有分隔条");

  const window = await boot();
  const doc = window.document;

  // 3) DOM 顺序：左面板 → 分隔条 → 右区域
  const rowKids = Array.from(doc.querySelector(".main-row").children)
    .map((el) => el.id || el.className);
  ok(rowKids.indexOf("device-sidebar") < rowKids.indexOf("sidebar-splitter")
     && rowKids.indexOf("sidebar-splitter") < rowKids.indexOf("tab-area"),
     "设备栏分隔条位于设备栏与内容区之间");
  const cmdKids = Array.from(doc.querySelector(".cmd-layout").children)
    .map((el) => el.id || el.className);
  ok(cmdKids.indexOf("cmd-panel-left") < cmdKids.indexOf("cmd-splitter"),
     "指令台分隔条位于指令台与指令输出之间");

  // 4) 拖动改变宽度（jsdom 布局全为 0，需桩掉 getBoundingClientRect）
  const sidebar = doc.getElementById("device-sidebar");
  const splitter = doc.getElementById("sidebar-splitter");
  const row = sidebar.parentElement;
  const rect = (w) => ({ width: w, left: 0, right: w, top: 0, bottom: 0, x: 0, y: 0, height: 0 });
  sidebar.getBoundingClientRect = () => rect(280);
  row.getBoundingClientRect = () => rect(1200);

  const pd = (x) => new window.MouseEvent("pointerdown", { clientX: x, bubbles: true, button: 0 });
  const pm = (x) => new window.MouseEvent("pointermove", { clientX: x, bubbles: true });
  const pu = (x) => new window.MouseEvent("pointerup", { clientX: x, bubbles: true });

  splitter.dispatchEvent(pd(100));
  ok(splitter.classList.contains("dragging"), "按下后分隔条进入拖动态");
  ok(doc.body.classList.contains("col-resizing"), "拖动中 body 进入 col-resizing（禁选文本）");
  splitter.dispatchEvent(pm(200));
  ok(sidebar.style.width === "380px", "向右拖 100px → 设备栏宽 280→380px（实际 " + sidebar.style.width + "）");

  // 低于最小值（200）被钳制
  splitter.dispatchEvent(pm(-1000));
  ok(sidebar.style.width === "200px", "左拖过界 → 钳制在最小值 200px（实际 " + sidebar.style.width + "）");

  // 超过「容器宽 - 右侧保留 480」= 720 被钳制
  splitter.dispatchEvent(pm(2000));
  ok(sidebar.style.width === "720px", "右拖过界 → 钳制在 1200-480=720px（实际 " + sidebar.style.width + "）");

  splitter.dispatchEvent(pu(2000));
  ok(!splitter.classList.contains("dragging") && !doc.body.classList.contains("col-resizing"),
    "松手后移除拖动态 class");

  // 5) 双击重置默认宽度
  splitter.dispatchEvent(new window.MouseEvent("dblclick", { bubbles: true }));
  ok(sidebar.style.width === "", "双击分隔条 → 重置为默认宽度（清掉内联样式）");

  // 6) 指令台分隔条同样生效（最小 240，右侧至少留 360）
  const cmdLeft = doc.getElementById("cmd-panel-left");
  const cmdSp = doc.getElementById("cmd-splitter");
  cmdLeft.getBoundingClientRect = () => rect(340);
  // 可用宽度取「最近的可见容器」.tab-area（指令台 tab 的父级），不再是
  // parentElement（.cmd-layout 自身可能已被拖宽到溢出屏幕）——桩要跟着改
  const tabArea = doc.querySelector(".tab-area");
  tabArea.getBoundingClientRect = () => rect(1000);
  cmdSp.dispatchEvent(pd(0));
  cmdSp.dispatchEvent(pm(-500));
  ok(cmdLeft.style.width === "240px", "指令台左拖过界 → 钳制在 240px（实际 " + cmdLeft.style.width + "）");
  cmdSp.dispatchEvent(pm(500));
  ok(cmdLeft.style.width === "640px", "指令台右拖 500 → 340→840，但容器 1000-360=640 钳制（实际 " + cmdLeft.style.width + "）");
  cmdSp.dispatchEvent(pu(500));
  cmdSp.dispatchEvent(new window.MouseEvent("dblclick", { bubbles: true }));
  ok(cmdLeft.style.width === "", "指令台分隔条双击重置");

  // 7) 窗口缩放动态适配：重拖到 640 后把容器缩到 800，已拖出的内联宽度
  //    必须被重钳到 800-360=440（只缩不增），否则右侧输出仍被顶出屏幕
  cmdSp.dispatchEvent(pd(0));
  cmdSp.dispatchEvent(pm(500));           // → 640px
  cmdSp.dispatchEvent(pu(500));
  ok(cmdLeft.style.width === "640px", "重拖指令台至钳位上界 640px（实际 " + cmdLeft.style.width + "）");
  tabArea.getBoundingClientRect = () => rect(800);
  window.dispatchEvent(new window.Event("resize"));
  ok(cmdLeft.style.width === "440px", "窗口缩到 800 → 内联宽度重钳为 800-360=440px（实际 " + cmdLeft.style.width + "）");
  tabArea.getBoundingClientRect = () => rect(1400);
  window.dispatchEvent(new window.Event("resize"));
  ok(cmdLeft.style.width === "440px", "窗口放大不回涨（只缩不增，用户拖宽意愿不被覆盖）（实际 " + cmdLeft.style.width + "）");
  cmdSp.dispatchEvent(new window.MouseEvent("dblclick", { bubbles: true }));
  ok(cmdLeft.style.width === "", "指令台分隔条双击重置");

  window.close();

  console.log("\n==============================================");
  console.log("结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
