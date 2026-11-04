/* jsdom 前端测试：新版本提示弹窗的提示语修整 + 保存目录按钮文案

   回归：提示语从「覆盖当前目录即可 + config.json 是你的设置」改为
   「只用新包里的 exe 覆盖同名 exe；其余 *.json 配置文件请勿替换或删除」。
   同时确认三处保存目录的「选择」按钮存在、打开按钮更名为「打开目录」。
   这些多为静态文案，不依赖 app.js 启动，直接读 index.html。 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.join(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "frontend/index.html"), "utf8");

process.on("unhandledRejection", () => {});

let pass = 0, fail = 0;
function ok(cond, name) {
  if (cond) { pass++; console.log("  ✓ " + name); }
  else { fail++; console.log("  ✗ " + name); }
}

(async () => {
  const watchdog = setTimeout(() => {
    console.log("    (看门狗触发)");
    process.exit(fail ? 1 : 0);
  }, 20000);

  console.log("\n[1] 新版本提示语：只建议覆盖 exe，json 配置需保留");
  {
    const doc = new JSDOM(html).window.document;
    const hint = (doc.getElementById("update-hint") || {}).textContent || "";
    ok(/只用新包里的 exe/.test(hint), "提示语要求只覆盖 exe（实际：" + hint.trim() + "）");
    ok(/请勿替换或删除/.test(hint), "明确说 *.json 配置请勿替换或删除");
    ok(/\*\.json/.test(hint), "提到 *.json 配置文件这一大类");
    ok(!/覆盖当前目录即可/.test(hint), "不再笼统说「覆盖当前目录即可」");
    ok(!/config\.json 是你的设置/.test(hint), "不再只提 config.json 一个（已扩展到 *.json）");
  }

  console.log("\n[2] 三处保存目录：新增「选择」按钮，打开按钮更名为「打开目录」");
  {
    const doc = new JSDOM(html).window.document;
    ["lc", "tool", "file"].forEach((k) => {
      const pick = doc.getElementById(k + "-pick");
      const open = doc.getElementById(k + "-open");
      ok(!!pick, k + " 页有「选择」按钮");
      ok(pick && pick.textContent.trim() === "选择", k + " 「选择」按钮文案正确");
      ok(!!open, k + " 页有打开按钮");
      ok(open && open.textContent.trim() === "打开目录",
        k + " 打开按钮已更名为「打开目录」（实际：" + (open && open.textContent.trim()) + "）");
    });
  }

  console.log("\n通过 " + pass + " / 失败 " + fail);
  process.exit(fail ? 1 : 0);
})();
