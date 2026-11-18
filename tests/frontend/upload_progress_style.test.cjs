/* 前端样式契约测试：上传/下载共用的进度条必须是纯色，不要跑马灯。

   用户反馈：进度条出现「一段一段的虚线在流动」的跑马灯效果，希望和下载完成态
   一样是纯色背景。效果来自 .upload-item.upload-stale .upload-bar > i 的
   repeating-linear-gradient + @keyframes upload-stripe —— 传输中超过 1.5s 没有新
   百分比（adb 缓冲住不吐百分比）时触发。

   这里把 CSS 作为契约锁定：stale 态只能纯色填充，条纹渐变与动画/keyframes 必须
   彻底移除，避免以后又被加回来。同时确认上传与下载共用同一套进度条渲染，保证
   两者样式天然一致。 */
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..", "..");
const css = fs.readFileSync(path.join(ROOT, "frontend/css/app.css"), "utf8");
const js = fs.readFileSync(path.join(ROOT, "frontend/js/app.js"), "utf8");

let pass = 0, fail = 0;
function ok(c, n) {
  if (c) { pass++; console.log("  ✓ " + n); }
  else { fail++; console.log("  ✗ " + n); }
}

/* 取 .upload-item.upload-stale .upload-bar > i 的规则体（到第一个 } 为止）。 */
function staleRule() {
  const m = css.match(/\.upload-item\.upload-stale \.upload-bar > i\s*\{([^}]*)\}/);
  return m ? m[1] : "";
}

console.log("\n[1] 不确定态进度条：纯色背景，无跑马灯");
{
  const rule = staleRule();
  ok(!!rule, "存在 .upload-item.upload-stale .upload-bar > i 规则");
  ok(/background\s*:\s*var\(--accent\)/.test(rule),
     "stale 态用纯色主题色填充（实际：" + rule.trim().replace(/\s+/g, " ") + "）");
  ok(!/repeating-linear-gradient/.test(rule), "stale 态不再用虚线渐变");
  ok(!/animation\s*:/.test(rule), "stale 态不再挂动画");
  ok(!/background-position/.test(rule), "stale 态不再挪动背景位置");
}

console.log("\n[2] 跑马灯动画 / keyframes 已从样式表移除");
{
  ok(!/@keyframes\s+upload-stripe/.test(css), "upload-stripe keyframes 已删除");
  ok(!/upload-stripe/.test(css), "样式表里没有 upload-stripe 残留引用");
  ok(!/repeating-linear-gradient\(\s*90deg\s*,\s*var\(--accent\)/.test(css),
     "进度条相关的条纹渐变已清除");
}

console.log("\n[3] 上传与下载共用同一套进度条渲染");
{
  ok(/bar\.className\s*=\s*"upload-bar"/.test(js), "进度条统一用 .upload-bar");
  ok(/const isDown\s*=\s*t\.kind\s*===\s*"down"/.test(js),
     "上传/下载走同一个渲染函数，kind 只决定箭头");
}

console.log("\n[4] 传输中进度条长度：只认真实进度，绝不铺满");
{
  ok(!/t\.status === "done" \|\| stale\s*\?\s*100/.test(js),
     "stale 态不再强制把进度条拉满");
  ok(/t\.status === "done"\s*\?\s*100/.test(js), "只有完成态才铺满进度条");
  ok(/:\s*pct\)\s*\+\s*"%"/.test(js), "传输中用最后收到的实际百分比决定宽度");
  ok(/Math\.min\(99,\s*rawPct\)/.test(js),
     "传输中百分比封顶 99%（后端会在 done 前先报 100）");
}

console.log("\n==============================================");
console.log("结果：" + pass + " 通过 / " + fail + " 失败");
process.exit(fail ? 1 : 0);
