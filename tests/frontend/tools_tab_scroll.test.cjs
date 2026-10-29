/* jsdom 前端测试：工具页滚动容器锁定（CSS / HTML 约定）。
   背景（用户实报）：工具页右侧区域高度超出后没有地方往下滚——目录行 +
   两张工具卡是纯堆叠，既没有 Logcat 视图 / 文件表格那样的 flex 生长区，
   tab 自身也没有滚动，超出部分被 .content 的 overflow:hidden 直接裁掉。
   修复：.tab[data-tab="tools"] 开滚动 + 子项 flex:none。
   本文件防止回归：修错选择器、漏 flex:none、或把规则挪丢都不行。 */
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

console.log("\n[F] 工具页滚动容器：高度超出可完整滚出（用户实报修复锁定）");

// ---- 1) 工具页 tab 自身即滚动容器 ----
const tt = cssBlock('.tab[data-tab="tools"]');
ok(!!tt, ".tab[data-tab=\"tools\"] 有专用规则（修复不能丢）");
ok(/overflow:\s*auto/.test(tt), "工具页 overflow:auto（超出即出滚动条，不再被 .content 裁掉）");

// ---- 2) 子项不参与列向压缩：超出即滚，而不是先被压瘪再回弹 ----
const kids = cssBlock('.tab[data-tab="tools"] > *');
ok(!!kids && /flex:\s*none/.test(kids),
   "工具页直接子项 flex:none（目录行 / 工具卡保持固有高度）");

// ---- 3) 工具页结构保持完整：目录行 + 两张工具卡仍在 ----
const toolsStart = html.indexOf('<section class="tab" data-tab="tools">');
const toolsEnd = html.indexOf("</section>", toolsStart);
ok(toolsStart >= 0 && toolsEnd > toolsStart, "index.html 存在工具页 section");
const toolsBlock = html.slice(toolsStart, toolsEnd);
ok(/id="tool-dir"/.test(toolsBlock) && /id="tool-open"/.test(toolsBlock),
   "保存目录行在位（tool-dir / tool-open）");
ok(/id="tool-shot"/.test(toolsBlock), "设备截图卡在位（tool-shot）");
ok(/id="tool-rec"/.test(toolsBlock) && /id="rec-zip"/.test(toolsBlock),
   "设备录屏卡在位（tool-rec / rec-zip，含竖排开关组）");

console.log("\n==============================================");
console.log("结果：" + pass + " 通过 / " + fail + " 失败");
process.exit(fail ? 1 : 0);
