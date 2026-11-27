/* jsdom 前端行为测试：文件页「常用路径」快速跳转条

   四个回归点：
   1) 默认值：config.json 里没有 file_fav_paths 时（首次使用 / 手改损坏），
      必须落默认 ["/sdcard"]，界面上有东西可点，而不是空条；
   2) 点击 chip = 把路径填进地址栏并触发 file_list 跳转；未勾选设备时给出
      「请先勾选设备」反馈、不调 file_list（与其余文件入口同一守卫）；
   3) 添加：点「＋」弹输入框并默认带入当前浏览目录，确认后新增 chip 且
      save_settings 落盘 file_fav_paths（JSON 字符串，与 cmd_history 同约定）；
   4) 删除：点 chip 上的 × 移除该路径并落盘；删光后回退默认值（不留空条），
      启动时从 settings.file_fav_paths 恢复用户配置。 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.join(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "frontend/index.html"), "utf8");
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
    await sleep(20);
  }
  console.log("    (waitFor 超时: " + label + ")");
  return false;
}

function mkEnv(stack, settings) {
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
          calls.push({ fn: String(k), args });
          if (k === "boot") {
            return Promise.resolve({ version: "v-test", warnings: [], commands: [], adb: "adb",
                                     settings: settings || {} });
          }
          if (k === "take_events") {
            const b = stack[round] || [];
            round++;
            return Promise.resolve(b);
          }
          return Promise.resolve({ ok: true });
        };
      },
    }),
  };
  window.prompt = () => null;
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  return { window, calls, doc: window.document };
}

const dev = (checked) => ({ serial: "A1", model: "Pixel", state: "device", ok: true, checked });
function click(window, el) {
  el.dispatchEvent(new window.Event("click", { bubbles: true }));
}
function statusText(doc) {
  return Array.from(doc.querySelectorAll("#status .line")).map((d) => d.textContent).join("\n");
}
function favGos(doc) {
  return Array.from(doc.querySelectorAll("#file-fav-chips .fav-chip .fav-go"));
}
function savedFav(calls) {
  const hit = calls.filter((c) => c.fn === "save_settings" && c.args[0] && "file_fav_paths" in c.args[0]);
  return hit.length ? JSON.parse(hit[hit.length - 1].args[0].file_fav_paths) : null;
}

(async () => {
  console.log("\n[1] 默认值：无配置时落 [\"/sdcard\"]，点击 chip 填地址栏并跳转");
  {
    const { window, calls, doc } = mkEnv([
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
       { kind: "devices", payload: { items: [dev(true)] } }],
    ]);
    await waitFor(() => favGos(doc).length === 1, 4000, "默认 chip");
    ok(favGos(doc).length === 1 && favGos(doc)[0].textContent === "/sdcard",
       "默认渲染一个 /sdcard chip（实际：" + favGos(doc).map((b) => b.textContent).join(",") + "）");

    click(window, favGos(doc)[0]);
    await waitFor(() => calls.some((c) => c.fn === "file_list" && c.args[1] === "/sdcard"), 4000, "file_list(/sdcard)");
    ok(doc.getElementById("file-path").value === "/sdcard", "地址栏已填入 /sdcard");
  }

  console.log("\n[2] 未勾选设备：点击 chip 给「请先勾选设备」，不调 file_list");
  {
    const { window, calls, doc } = mkEnv([
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
       { kind: "devices", payload: { items: [] } }],
    ]);
    await waitFor(() => favGos(doc).length === 1, 4000, "默认 chip");
    const before = calls.filter((c) => c.fn === "file_list").length;
    click(window, favGos(doc)[0]);
    await sleep(400);
    ok(calls.filter((c) => c.fn === "file_list").length === before, "未勾选设备时不调 file_list");
    ok(statusText(doc).includes("请先勾选设备"), "给出「请先勾选设备」反馈");
  }

  console.log("\n[3] 添加：点「＋」默认带入当前目录，确认后新增 chip 并落盘");
  {
    const { window, calls, doc } = mkEnv([
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
       { kind: "devices", payload: { items: [dev(true)] } },
       { kind: "file", payload: { serial: "A1", path: "/sdcard/DCIM", entries: [] } }],
    ]);
    await waitFor(() => doc.getElementById("file-path").value === "/sdcard/DCIM", 4000, "浏览目录");
    click(window, doc.querySelector("#file-fav-chips .fav-add"));
    await waitFor(() => !doc.getElementById("input-modal").classList.contains("hidden"), 4000, "输入弹窗");
    ok(doc.getElementById("input-modal").classList.contains("hidden") === false, "「＋」弹出输入框");
    ok(doc.getElementById("input-field") && doc.getElementById("input-field").value === "/sdcard/DCIM",
       "输入框默认带入当前浏览目录（实际：" + doc.getElementById("input-field").value + "）");
    doc.getElementById("input-field").value = "/data/local/tmp";
    click(window, doc.getElementById("input-yes"));
    await waitFor(() => favGos(doc).length === 2, 4000, "新 chip");
    ok(favGos(doc).map((b) => b.textContent).join("|") === "/sdcard|/data/local/tmp",
       "确认后新增 chip（实际：" + favGos(doc).map((b) => b.textContent).join(",") + "）");
    await waitFor(() => savedFav(calls) && savedFav(calls).length === 2, 4000, "落盘");
    ok(JSON.stringify(savedFav(calls)) === JSON.stringify(["/sdcard", "/data/local/tmp"]),
       "save_settings 落盘 file_fav_paths（实际：" + JSON.stringify(savedFav(calls)) + "）");
  }

  console.log("\n[4] 删除与恢复：× 移除并落盘；删光回退默认；启动恢复用户配置");
  {
    const { window, calls, doc } = mkEnv([
      [{ kind: "booted", payload: { version: "v-test", warnings: [], commands: [],
                                    settings: { file_fav_paths: JSON.stringify(["/sdcard/DCIM", "/data/local/tmp"]) } } },
       { kind: "devices", payload: { items: [dev(true)] } }],
    ]);
    await waitFor(() => favGos(doc).length === 2, 4000, "恢复配置");
    ok(favGos(doc).map((b) => b.textContent).join("|") === "/sdcard/DCIM|/data/local/tmp",
       "启动从 settings.file_fav_paths 恢复两个 chip");

    // 删第一个：× 是 chip 里第二个 button
    const del = doc.querySelectorAll("#file-fav-chips .fav-chip")[0].querySelector(".fav-del");
    click(window, del);
    await waitFor(() => favGos(doc).length === 1, 4000, "删除 chip");
    ok(favGos(doc)[0].textContent === "/data/local/tmp", "× 移除对应 chip（剩 " + favGos(doc)[0].textContent + "）");
    await waitFor(() => savedFav(calls), 4000, "落盘");
    ok(JSON.stringify(savedFav(calls)) === JSON.stringify(["/data/local/tmp"]),
       "删除后落盘（实际：" + JSON.stringify(savedFav(calls)) + "）");

    // 删到空：回退默认 /sdcard
    click(window, doc.querySelector("#file-fav-chips .fav-chip .fav-del"));
    await waitFor(() => favGos(doc).length === 1 && favGos(doc)[0].textContent === "/sdcard", 4000, "回退默认");
    ok(favGos(doc)[0].textContent === "/sdcard", "删光后回退默认 /sdcard，不留空条");
  }

  console.log("\n结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
