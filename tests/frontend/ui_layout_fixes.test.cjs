/* jsdom 前端测试：本轮 UI 反馈修复的静态锁定（CSS / HTML 约定）。
   锁定四项修复，防止回归：
   1. 设备指令页：.cmd-layout 补回缺失的 flex 基础布局（此前退化成 block
      堆叠，左侧指令台把指令输出区挤成屏幕底部一条 —— 用户实报）；
   2. 左栏命令分组区独立滚动：命令再多也在栏内滚，输出区永远全高；
   3. 左侧设备栏头部允许换行 + 标题不断词（此前中文被挤成「已连接设/备」）；
   4. Logcat 缓冲区默认选中「全部」。 */
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "frontend/index.html"), "utf8");
const css = fs.readFileSync(path.join(ROOT, "frontend/css/app.css"), "utf8");

let pass = 0, fail = 0;
function ok(c, n) {
  if (c) { pass++; console.log("  ✓ " + n); }
  else { fail++; console.log("  ✗ " + n); }
}
function cssBlock(sel) {
  const i = css.indexOf(sel + " {");
  return i < 0 ? "" : css.slice(i, css.indexOf("}", i));
}

console.log("\n[F] UI 反馈修复：指令台分栏 / 设备栏头部 / 缓冲区默认值");

// ---- 1) .cmd-layout 基础布局（曾整块缺失）----
const cl = cssBlock(".cmd-layout");
ok(!!cl, ".cmd-layout 有基础布局规则（不再只有窄屏媒体查询里的半条）");
ok(/display:\s*flex/.test(cl), ".cmd-layout 为 flex 行（左右分栏，非 block 堆叠）");
ok(/flex:\s*1/.test(cl), ".cmd-layout 吃满 tab 高度");
ok(/min-height:\s*0/.test(cl), ".cmd-layout min-height:0（flex 嵌套可压缩）");

// ---- 2) 左右两栏的伸缩策略 ----
const pl = cssBlock(".cmd-layout .panel-left");
ok(/width:\s*\d+(\.\d+)?(px|%)/.test(pl), "指令台左栏有显式宽度（width，px 或 %）");
ok(/flex:\s*none/.test(pl), "指令台左栏不伸缩（flex:none，宽度交给分隔条拖）");
ok(/overflow:\s*hidden/.test(pl), "指令台左栏 overflow:hidden（内容内部自行滚动）");
const pr = cssBlock(".cmd-layout .panel-right");
ok(/flex:\s*1/.test(pr), "指令输出栏 flex:1 吃剩余宽度");
ok(/min-width:\s*0/.test(pr), "指令输出栏 min-width:0（长输出不撑破布局）");

// ---- 3) 左栏命令分组区独立滚动 ----
const cg = cssBlock(".cmd-layout .panel-left #cmd-groups");
ok(!!cg && /overflow:\s*auto/.test(cg), "#cmd-groups 独立滚动（命令再多不挤没输出区）");
ok(!!cg && /flex:\s*1/.test(cg) && /min-height:\s*0/.test(cg),
   "#cmd-groups flex:1 + min-height:0（正确参与左栏 flex 列）");

// ---- 4) 设备栏头部换行 ----
const sh = cssBlock(".sidebar-head");
ok(!!sh && /flex-wrap:\s*wrap/.test(sh),
   ".sidebar-head flex-wrap:wrap（窄设备栏整组换行，不再硬挤一行）");
const st = cssBlock(".sidebar-title");
ok(!!st && /white-space:\s*nowrap/.test(st),
   ".sidebar-title white-space:nowrap（「已连接设备」整体不断行）");

// ---- 5) Logcat 缓冲区默认「全部」----
const selStart = html.indexOf('<select id="lc-buf"');
const selEnd = html.indexOf("</select>", selStart);
ok(selStart >= 0 && selEnd > selStart, "index.html 存在 #lc-buf 下拉");
const selBlock = html.slice(selStart, selEnd);
ok(/<option selected>全部（main\+system\+events\+crash）<\/option>/.test(selBlock),
   "缓冲区默认选中「全部（main+system+events+crash）」");
ok((selBlock.match(/selected/g) || []).length === 1,
   "该下拉有且仅有一个 selected 项（不出现多默认）");

console.log("\n==============================================");
console.log("结果：" + pass + " 通过 / " + fail + " 失败");
process.exit(fail ? 1 : 0);
