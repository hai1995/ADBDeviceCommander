/* 前端测试统一入口：顺序跑完目录下所有 *.test.cjs 并汇总结果。
   用法：在 tests/frontend 目录执行 `npm test`（先 npm install 装 jsdom）。
   单个文件也可单独跑：node <文件名>.test.cjs */
const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const files = fs.readdirSync(__dirname)
  .filter((f) => f.endsWith(".test.cjs"))
  .sort();

if (!files.length) {
  console.error("未找到任何 *.test.cjs 测试文件");
  process.exit(1);
}

let failed = 0;
for (const f of files) {
  console.log("\n===== " + f + " =====");
  const r = spawnSync(process.execPath, [path.join(__dirname, f)], {
    stdio: "inherit",
    cwd: __dirname,
  });
  if (r.status !== 0) {
    failed += 1;
    console.log("[FAIL] %s（退出码 %s）", f, r.status);
  }
}

console.log("\n" + "=".repeat(46));
console.log("共 %d 个测试文件，%d 个失败", files.length, failed);
process.exit(failed ? 1 : 0);
