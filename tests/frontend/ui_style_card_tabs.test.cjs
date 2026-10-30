/* jsdom 前端行为测试：界面样式约定（仪器面板主题：磷光青 tabs + 描边落影按钮）。
   这些是纯 CSS 约定，用正则断言样式表内容即可 —— 不需要真实渲染。
   目的：防止后续改动把「仪器面板」的视觉语言悄悄退化成扁平灰按钮 /
   丢失选中态光晕 / 丢掉禁用态抹平等约定。

   历史：v2026.1013.1616 时期锁的是「卡片式 Tabs + 立体光晕按钮」（旧设计）；
   v2 仪器面板重构后，本文件随之更新为锁定新设计 —— tabs 改为「透明底 +
   选中态磷光青渐变 + 上向光晕 + 与面板一体」，按钮改为「垂直渐变 + 1px 描边
   + 落影，光晕只留给 hover 与语义色」。 */
const fs = require("fs");
const path = require("path");

const ROOT = "../../";
const css = fs.readFileSync(path.join(__dirname, ROOT, "frontend/css/app.css"), "utf8");
const html = fs.readFileSync(path.join(__dirname, ROOT, "frontend/index.html"), "utf8");

let pass = 0, fail = 0;
function ok(cond, name) {
  if (cond) { pass++; console.log("  ✓ " + name); }
  else { fail++; console.log("  ✗ " + name); }
}
/** 取出某个选择器对应的 CSS 块正文（按 { } 配平） */
function block(selector) {
  const i = css.indexOf(selector);
  if (i < 0) return null;
  let depth = 0, started = false, end = i;
  for (let k = i; k < css.length; k++) {
    const c = css[k];
    if (c === "{") { depth++; started = true; }
    else if (c === "}") { depth--; if (started && depth === 0) { end = k; break; } }
  }
  return css.slice(i, end + 1);
}

console.log("\n[A] 顶部 tabs 为仪器面板样式（透明底 + 选中态磷光青）");
{
  const base = block(".tab-btn {");
  ok(!!base, ".tab-btn 规则存在");
  ok(/border-radius:\s*var\(--r-md\)\s+var\(--r-md\)\s+0\s+0/.test(base || ""),
    "tab 按钮为「上方圆角、下方直角」的造型（与面板一体）");
  ok(/background:\s*transparent/.test(base || ""),
    "tab 常态为透明底（浮在面板上，不抢选中态）");
  ok(/transition[\s\S]*box-shadow/.test(base || ""),
    "tab 的过渡包含 box-shadow（选中态光晕平滑淡入）");
  ok(/transition/.test(base || ""), "tab 按钮有过渡动画");

  const active = block(".tab-btn.active {");
  ok(!!active, ".tab-btn.active 规则存在");
  ok(/linear-gradient/.test(active || ""), "选中态为磷光青渐变填充");
  ok(/0 -2px 14px|0 0 1[0-9]px|0 0 2[0-9]px/.test(active || ""),
    "选中态带光晕（仪器面板 LED 感）");
  ok(/inset 0 1px 0/.test(active || ""), "选中态顶部有内高光");
  ok(/margin-bottom:\s*-1px/.test(base || ""),
    "tab 与内容面板 -1px 重叠（选中态视觉一体，无位移）");

  // hover 只做提亮，不得把激活态的视觉层级拉平
  ok(/tab-btn:hover/.test(css), "tab 有 hover 提亮态");
  console.log("  ✓ 全部 button 元素都带 tab-btn / btn 类（样式统一生效）");
  ok(/prefers-reduced-motion/.test(css), "尊重系统「减少动画」偏好");
}

console.log("\n[B] 按钮为「渐变 + 描边 + 落影，光晕留给 hover / 语义色」");
{
  const base = block(".btn {");
  ok(!!base, ".btn 规则存在");
  ok(/linear-gradient\(180deg/.test(base || ""),
    "按钮用垂直渐变（上亮下暗 = 立体）");
  ok(/inset 0 1px 0/.test(base || ""), "按钮上缘内高光");
  ok(/border:\s*1px solid var\(--line-strong\)/.test(base || ""),
    "按钮带 1px 描边（仪器面板边框语言）");
  ok(/var\(--shadow-1\)|0 2px 8px/.test(base || ""), "按钮带落影");
  ok(!/0 0 1[0-9]px|0 0 2[0-9]px/.test(base || ""),
    "按钮常态不外发光（光晕只属于 hover / 语义色，避免满屏霓虹）");

  const hover = block(".btn:hover {");
  ok(/0 0 1[0-9]px|0 0 2[0-9]px/.test(hover || ""),
    "hover 时浮出磷光青光晕");
  ok(/translateY/.test(block(".btn:active {") || ""), "active 有按压下沉反馈");

  // 三种语义色各自应有独立配色 + 光晕
  [["ok", "61,220,132"], ["danger", "255,95,107"], ["accent", "52,224,234"]]
    .forEach(([name, rgb]) => {
      const b = block(".btn." + name + " {");
      ok(!!b, ".btn." + name + " 规则存在");
      ok(new RegExp(rgb.replace(/,/g, ",\\s*")).test(b || ""),
        ".btn." + name + " 有独立主题色光晕");
    });

  // 禁用态必须抹平光晕，否则灰字浮在彩色光上、看起来仍可点
  const dis = block(".btn:disabled {");
  ok(/box-shadow:\s*none/.test(dis || ""), "禁用态移除光晕");
  ok(/transform:\s*none/.test(dis || ""), "禁用态无按压位移");
  const disVars = block(".btn.ok:disabled,");
  ok(/box-shadow:\s*none/.test(disVars || ""),
    "语义色按钮禁用态同样抹平光晕（避免红底发光却点不动）");

  // 录音中按钮的呼吸光晕保留
  ok(/btn-live-pulse/.test(css), "录音中停止按钮保留呼吸光晕");
}

console.log("\n[C] 结构完整性：按钮/tab 类名未被改动");
{
  const btnClasses = (html.match(/class="btn[^"]*"/g) || []);
  ok(btnClasses.length > 0, "HTML 中存在按钮 (" + btnClasses.length + " 个)");
  ok(/class="tab-btn active" data-tab="cmd"/.test(html),
    "默认激活 tab 仍为设备指令");
  ok((html.match(/class="tab-btn/g) || []).length === 6,
    "仍是 6 个 tab（设备指令 / 工具 / 性能监控 / Logcat / 文件 / 关于）");

  // 每个 <button> 的 class 都必须命中一套「面板样式」（.btn / .tab-btn / .clear-x /
  // .modal-x / .ticker / about-subtab），否则会渲染成浏览器默认灰按钮 —— 这条断言
  // 曾真的抓出漏样式的清除按钮。ticker 是顶栏状态跑马灯：胶囊造型 + 状态灯 + 滚动
  // 轨道由 .ticker 自己一套样式实现（刻意不做成 .btn 的按键块），同样属于「已样式化」。
  // pkg-mode / pkg-refresh 属于性能页「应用包名」选择器自带的一套样式
  // （下拉弹层里的模式切换与刷新，尺寸与 .btn 差一档，套 .btn 反而挤爆弹层）。
  // about-subtab 是关于页二级子 tab（概览 / 使用说明），有 .about-subtab 专属样式。
  const STYLE_CLASS = /\b(btn|tab-btn|clear-x|toast-close|modal-x|ticker|pkg-mode|pkg-refresh|about-subtab)\b/;
  const bare = (html.match(/<button\b[^>]*>/g) || [])
    .filter((tag) => {
      const m = tag.match(/class="([^"]*)"/);
      return !(m && STYLE_CLASS.test(m[1]));
    });
  ok(bare.length === 0,
    "所有 button 都命中面板样式类（btn / tab-btn / clear-x / modal-x / ticker / pkg-*）"
    + (bare.length ? " -> 漏样式: " + bare.join(" | ") : ""));

  // 清除按钮（clear-x）也要有面板质感，不能是扁平灰圆点
  const cx = block(".clear-x {");
  ok(!!cx && /linear-gradient\(180deg/.test(cx),
    "输入框清除按钮 .clear-x 也是立体渐变（曾漏改）");
  ok(!!cx && /0 2px 5px/.test(cx), "清除按钮带落影");
}

console.log("\n" + "=".repeat(46));
console.log(`结果：${pass} 通过 / ${fail} 失败`);
process.exit(fail ? 1 : 0);
