/* jsdom 前端行为测试：复选框 → 开关样式约定（纯 CSS，无 DOM/结构改动）。
   用正则断言样式表内容即可 —— 不需要真实渲染。
   目的：防止后续改动把开关悄悄退回浏览器原生方框，或破坏密集场景的小尺寸变体。 */
const fs = require("fs");
const path = require("path");

const ROOT = "../../";
// 统一换行：本仓库提交进 git 的是 CRLF 文本，而下面的断言里有按 `\n` 写死的
// 多行选择器（见 [B] 段）。不归一化的话，这套断言只在「工作副本恰好是 LF」的
// 机器上通过，干净检出（CRLF）必然 4 条失败 —— 属测试自身缺陷。
const lf = (s) => s.replace(/\r\n/g, "\n");
const css = lf(fs.readFileSync(path.join(__dirname, ROOT, "frontend/css/app.css"), "utf8"));
const html = lf(fs.readFileSync(path.join(__dirname, ROOT, "frontend/index.html"), "utf8"));
const js = lf(fs.readFileSync(path.join(__dirname, ROOT, "frontend/js/app.js"), "utf8"));

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

console.log("\n[A] 全局开关基样式（默认尺寸）");
{
  const base = block('input[type="checkbox"] {');
  ok(!!base, "input[type=checkbox] 基规则存在");
  ok(/appearance:\s*none/.test(base || "") && /-webkit-appearance:\s*none/.test(base || ""),
    "appearance:none 抹掉浏览器原生方框（含 -webkit- 前缀）");
  ok(/width:\s*36px/.test(base || "") && /height:\s*20px/.test(base || ""),
    "轨道为标准尺寸 36×20");
  ok(/border-radius:\s*999px/.test(base || ""), "轨道为胶囊形（全圆角）");
  ok(/box-shadow:\s*inset/.test(base || ""), "轨道有内阴影（凹陷质感）");
  ok(/transition:/.test(base || ""), "轨道状态切换有过渡动画");
  ok(/vertical-align:\s*middle/.test(base || ""), "垂直居中对齐（表格/行内混排不乱）");

  const knob = block('input[type="checkbox"]::after {');
  ok(!!knob, "滑块伪元素规则存在");
  ok(/content:\s*""/.test(knob || ""), "滑块用 content 伪元素绘制（无需额外 DOM）");
  ok(/border-radius:\s*50%/.test(knob || ""), "滑块为圆形");
  ok(/position:\s*absolute/.test(knob || "") && /left:\s*2px/.test(knob || ""),
    "滑块绝对定位在轨道左端");
  ok(/linear-gradient/.test(knob || ""), "滑块为渐变（立体小圆钮）");

  const on = block('input[type="checkbox"]:checked {');
  ok(!!on, ":checked 选中态规则存在");
  ok(/linear-gradient/.test(on || ""), "选中态为渐变填充（非纯色）");
  ok(/0 0 8px/.test(on || ""), "选中态带外发光光晕");
  const knobOn = block('input[type="checkbox"]:checked::after {');
  ok(/left:\s*18px/.test(knobOn || ""), "选中态滑块平移到右端（left 18px）");

  ok(/input\[type="checkbox"\]:focus-visible/.test(css) && /outline:/.test(block('input[type="checkbox"]:focus-visible {') || ""),
    "键盘聚焦有焦点环（focus-visible 不影响鼠标点击）");
  const dis = block('input[type="checkbox"]:disabled {');
  ok(/opacity:\s*\.45/.test(dis || "") && /cursor:\s*not-allowed/.test(dis || ""),
    "禁用态半透明 + 禁止光标（如离线设备卡的复选框）");
}

console.log("\n[B] 密集场景小尺寸变体（Logcat 级别开关；文件区已独立为方框复选框）");
{
  // 小尺寸开关变体现在只覆盖两处级别行（实时监控 / 落盘抓取）；文件区多选已改为
  // 方框复选框，见下方 [B2]。录屏那处级别行已随「全量抓取」一起撤掉。
  const small = "#lc-levels input[type=\"checkbox\"],\n"
    + "#lc-cap-levels input[type=\"checkbox\"]";
  const b = block(small);
  ok(!!b, "密集场景小尺寸开关规则存在（监控 / 抓取级别）");
  ok(/width:\s*28px/.test(b || "") && /height:\s*16px/.test(b || ""),
    "小轨道为 28×16（不挤爆行高）");
  const knob = block('#lc-levels input[type="checkbox"]::after,\n'
    + '#lc-cap-levels input[type="checkbox"]::after {');
  ok(/width:\s*10px/.test(knob || "") && /height:\s*10px/.test(knob || ""),
    "小滑块为 10×10");
  const knobOn = block('#lc-levels input[type="checkbox"]:checked::after,\n'
    + '#lc-cap-levels input[type="checkbox"]:checked::after {');
  ok(/left:\s*14px/.test(knobOn || ""),
    "小开关选中态滑块位移正确（轨道内宽 26 - 滑块 10 - 边距 2 = 14px）");
  // 文件区复选框由 app.js 动态创建，仍带 .file-check 类（供 [B2] 的方框样式命中）
  ok(/file-check/.test(js), "app.js 动态文件行复选框仍带 .file-check 类");
}

console.log("\n[B2] 文件区多选：方块复选框（与全局开关区分，且与主题协调）");
{
  const b = block("#file-body .file-check,\n#file-sel-all {");
  ok(!!b, "文件区复选框专用规则存在（不再复用开关变体）");
  ok(/width:\s*17px/.test(b || "") && /height:\s*17px/.test(b || ""),
    "方框为 17×17（比开关小、贴合表格行高）");
  ok(/border-radius:\s*4px/.test(b || ""), "方框圆角 4px（方块而非胶囊）");
  ok(!/999px/.test(b || ""), "不是胶囊开关（无 999px 圆角）");
  ok(/background:\s*var\(--surface-2\)/.test(b || ""), "未选态为面板底色");
  const on = block("#file-body .file-check:checked,\n#file-sel-all:checked {");
  ok(/linear-gradient/.test(on || ""), "选中态为磷光青渐变（沿用主题强调色）");
  ok(/0 0 8px/.test(on || ""), "选中态带微光晕");
  const mark = block("#file-body .file-check::after,\n#file-sel-all::after {");
  ok(/border-width:\s*0 2px 2px 0/.test(mark || ""), "对勾用「右+下」两条边绘制");
  ok(/rotate\(45deg\)/.test(mark || ""), "对勾旋转 45°（纯 CSS 勾形）");
  ok(/opacity:\s*0/.test(mark || ""), "未选态对勾隐藏");
  const markOn = block("#file-body .file-check:checked::after,\n#file-sel-all:checked::after {");
  ok(/opacity:\s*1/.test(markOn || ""), "选中态显示对勾");
  // 开关变体两处级别行不得再混入文件区（避免两套样式互相覆盖）
  const smallSel = "#lc-levels input[type=\"checkbox\"],\n"
    + "#lc-cap-levels input[type=\"checkbox\"]";
  ok(!/file-check/.test(smallSel), "小尺寸开关变体不再包含文件区复选框");
  ok(!/rec-levels/.test(css), "录屏级别行的样式已随控件一并删除（无残留死样式）");
}

console.log("\n[C] 结构完整性：复选框集合未被意外改动");
{
  const boxes = html.match(/<input type="checkbox"/g) || [];
  ok(boxes.length === 28,
    "index.html 静态复选框为 28 个（keep-input×1 + 监控级别×6 + 抓取级别×6 + Logcat×3 + 工具×5 + APK 安装选项×3 + 诊断包×1 + 全选×1 + 命令编辑「仅输入」×1 + 应用包名「含系统应用」×1）"
    + " -> 实际 " + boxes.length);
  ok(!/appearance:\s*checkbox/.test(css),
    "没有任何地方把开关退回原生 appearance:checkbox");
  ok(!/type="radio"/.test(html), "未误把单选按钮带入本套开关体系");
  // 动态生成的复选框（设备卡 / 文件行）不依赖特定 id，天然命中全局规则
  ok(/cb\.type = "checkbox"/.test(js), "app.js 动态复选框仍为原生 checkbox（全局开关样式自动生效）");
}

console.log("\n[D] 动效偏好");
{
  ok(/prefers-reduced-motion/.test(css),
    "尊重系统「减少动画」偏好（关闭开关过渡）");
}

console.log("\n[E] 录屏开关横向换行布局（一行尽量多放，减小纵向占高）");
{
  ok(/class="rec-opts"/.test(html), "录屏卡片存在 .rec-opts 开关容器");
  // 4 个录屏开关必须全部收进 .rec-opts，按钮不混入。
  // 块提取按 <div>/</div> 配平：用「第一个 </div>」截断会把后面的开关漏掉
  // （rec-opts 里曾嵌套过级别行）——曾经踩过，故用配平而不是字符串截断。
  function divBlock(src, openIdx) {
    const re = /<div\b[^>]*>|<\/div>/g;
    re.lastIndex = openIdx;
    let depth = 0, m;
    while ((m = re.exec(src))) {
      if (m[0].charAt(1) === "/") {
        depth--;
        if (depth === 0) return src.slice(openIdx, m.index + m[0].length);
      } else depth++;
    }
    return null;
  }
  const optsBlock = divBlock(html, html.indexOf('<div class="rec-opts">'));
  ok(!!optsBlock, ".rec-opts 块可按 <div>/</div> 配平完整提取");
  ["rec-logcat", "rec-zip", "rec-pointer-location", "rec-show-touches"].forEach((id) => {
    ok(new RegExp('id="' + id + '"').test(optsBlock || ""),
      "开关 #" + id + " 收在 .rec-opts 内（换行排布）");
  });
  ok(!/tool-rec/.test(optsBlock || ""), "开始/停止按钮不混入开关容器（按钮独占一行）");
  const b = block(".rec-opts {");
  ok(!!b && /flex-wrap:\s*wrap/.test(b || ""),
    ".rec-opts 横向自动换行（一行尽量多放几个开关，减小纵向占高）");
  ok(!!b && /align-items:\s*center/.test(b || ""), ".rec-opts 垂直居中对齐");
  ok(!!b && /gap:\s*6px\s+18px/.test(b || ""), "开关行列间距紧凑（gap: 6px 18px）");
  const chk = block(".rec-opts .chk {");
  ok(!!chk && /width:\s*auto/.test(chk || ""),
    ".rec-opts 内的开关按内容宽度排列（可一行多个，不再整行独占）");
  // 音频 / 麦克风两项已撤掉（采集链路没做完），界面上不应再有它们的开关
  ["rec-devaudio", "rec-mic"].forEach((id) => {
    ok(!new RegExp('id="' + id + '"').test(html),
      "#" + id + " 已从界面移除（功能未实现，不留假开关）");
  });
}

console.log("\n[F] 顶栏无重复品牌标题（原生标题栏已展示应用名）");
{
  ok(!/class="brand"/.test(html), "index.html 无 .brand 品牌标题（与原生标题栏重复）");
  ok(!/id="ver"/.test(html), "顶栏不再挂版本号元素 #ver");
  ok(/id="about-ver"/.test(html), "「关于」页仍展示版本号 #about-ver");
  ok(!/\.brand\s*\{/.test(css), "CSS 无 .brand 规则（已随品牌区一并清理）");
  ok(!/els\.ver/.test(js), "app.js 无 els.ver 引用（不会对已删除元素报错）");
}

console.log("\n" + "=".repeat(46));
console.log(`结果：${pass} 通过 / ${fail} 失败`);
process.exit(fail ? 1 : 0);
