/* jsdom 前端行为测试：「上传」按钮走原生对话框 + 路径直传 + 无进度兜底。

   背景（用户报的两个真实问题）：
     1. 上传大文件时进度条从 0% 直接跳到 100%；
     2. 状态栏报「调用后端失败：请求超时（15s）」。
   两者同源：`<input type=file>` 只给 File 对象，整个文件被编码成 base64 过一次
   js_api 桥，几百 MB 光序列化就要几十秒。桥被独占期间 callApi 15s 超时，
   take_events 轮询排队拿不到进度事件 —— 等桥腾出来 push 已经结束。

   覆盖：
     * 点「上传」按钮弹原生对话框（file_upload_pick），不再把内容过桥；
     * 后端下发的 task_id 直接建成队列项，状态「上传中」；
     * file_upload 事件按 task_id 刷新百分比 → done / failed 带原因；
     * 失败项点「重试」→ 走 file_upload_path（按原路径重推，用户不必重选文件）；
     * push 阶段长时间没有新进度 → 切不确定态（upload-stale），进度条不装死；
     * 取消选择静默，不当失败弹红条。
*/
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.join(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "frontend/index.html"), "utf8");
const js = fs.readFileSync(path.join(ROOT, "frontend/js/app.js"), "utf8");

process.on("unhandledRejection", () => {});

let pass = 0, fail = 0;
function ok(c, n) {
  if (c) { pass++; console.log("  ✓ " + n); }
  else { fail++; console.log("  ✗ " + n); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitFor(fn, ms = 4000, label = "") {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    let v = false; try { v = !!fn(); } catch (e) { v = false; }
    if (v) return true;
    await sleep(30);
  }
  console.log("    (waitFor 超时: " + label + ")");
  return false;
}

async function boot(handlers) {
  const pending = [
    { kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
    { kind: "devices", payload: { items: [{ serial: "A1", ok: true, checked: true }] } },
    { kind: "file", payload: { serial: "A1", path: "/sdcard", entries: [] } },
  ];
  const calls = [];
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const apiStub = new Proxy({}, {
    get(t, k) {
      if (k === "then") return undefined;
      return function (...args) {
        calls.push({ fn: String(k), args });
        if (handlers && handlers[k]) return handlers[k](...args);
        if (k === "boot") {
          return Promise.resolve({
            version: "v-test", warnings: [], commands: [],
            adb: "/usr/bin/adb", save_dir: "/tmp",
          });
        }
        if (k === "take_events") return Promise.resolve(pending.splice(0, pending.length));
        return Promise.resolve({ ok: true });
      };
    },
  });
  window.pywebview = { api: apiStub };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  await sleep(500);
  return { window, calls, pending };
}

function items(doc) { return Array.from(doc.querySelectorAll("#upload-queue-list .upload-item")); }
function metaOf(doc) {
  const m = doc.querySelector("#upload-queue-list .upload-meta");
  return m ? m.textContent : "";
}
function fireUpload(pending, ev) { pending.push({ kind: "file_upload", payload: ev }); }
function clickUploadBtn(window) {
  window.document.getElementById("file-upload-btn")
    .dispatchEvent(new window.Event("click", { bubbles: true }));
}

const ITEM = {
  task_id: "p1", path: "/data/big.bin", name: "big.bin",
  size: 2048, remote: "/sdcard/big.bin",
};

(async () => {
  console.log("\n[1] 点「上传」弹原生对话框：路径直传，内容不过 js_api 桥");
  {
    let resolvePick = null;
    const { window, calls, pending } = await boot({
      file_upload_pick: () => new Promise((r) => { resolvePick = r; }),
    });
    const doc = window.document;
    await waitFor(() => /设备: A1/.test(doc.getElementById("file-dev-now").textContent),
                   3000, "设备就绪");
    ok(doc.getElementById("upload-queue").hidden === true, "无任务时队列面板隐藏");

    clickUploadBtn(window);
    ok(await waitFor(() => calls.some((c) => c.fn === "file_upload_pick"), 3000, "pick 调用"),
       "「上传」按钮走原生文件对话框");
    const pickCall = calls.find((c) => c.fn === "file_upload_pick");
    ok(pickCall.args[0] === "A1", "把设备序列号传给后端：" + JSON.stringify(pickCall.args));
    ok(pickCall.args[1] === "/sdcard", "把当前目录传给后端：" + JSON.stringify(pickCall.args));

    resolvePick({ ok: true, items: [ITEM] });
    ok(await waitFor(() => items(doc).length === 1, 3000, "队列项"),
       "后端下发的 task_id 直接建成队列项");
    ok(doc.getElementById("upload-queue").hidden === false, "队列面板展开");
    const row = items(doc)[0];
    ok(row.dataset.task === "p1", "队列项绑定后端给的 task_id：" + row.dataset.task);
    ok(row.className.indexOf("upload-uploading") !== -1, "状态为上传中：" + row.className);
    ok(metaOf(doc) === "0%", "起始 0%：" + metaOf(doc));
    ok(!calls.some((c) => c.fn === "file_upload_data"),
       "路径直传不该再调 file_upload_data（内容不过桥）");
    ok(await waitFor(() => calls.some((c) => c.fn === "file_upload_path"),
                     3000, "启动 push"),
       "队列项建好后才让后端启动 push（避免 done 事件先到被丢掉）");
    const start = calls.find((c) => c.fn === "file_upload_path");
    ok(start.args[1] === "/data/big.bin" && start.args[3] === "p1",
       "首次提交也用原路径与同一个 task_id：" + JSON.stringify(start.args));
    window.close();
  }

  console.log("\n[2] 后端进度事件按 task_id 刷新百分比 → done");
  {
    const { window, pending } = await boot({
      file_upload_pick: () => Promise.resolve({ ok: true, items: [ITEM] }),
    });
    const doc = window.document;
    await waitFor(() => /设备: A1/.test(doc.getElementById("file-dev-now").textContent),
                   3000, "设备就绪");
    clickUploadBtn(window);
    await waitFor(() => items(doc).length === 1, 3000, "队列项");

    fireUpload(pending, { task_id: "p1", status: "uploading", percent: 37,
                          name: "big.bin", remote: "/sdcard/big.bin", serial: "A1" });
    ok(await waitFor(() => metaOf(doc) === "37%", 3000, "37%"),
       "push 百分比刷新到对应项：" + metaOf(doc));

    fireUpload(pending, { task_id: "p1", status: "uploading", percent: 82,
                          name: "big.bin", remote: "/sdcard/big.bin", serial: "A1" });
    ok(await waitFor(() => metaOf(doc) === "82%", 3000, "82%"), "继续刷新：" + metaOf(doc));

    fireUpload(pending, { task_id: "p1", status: "done", percent: 100,
                          name: "big.bin", remote: "/sdcard/big.bin", serial: "A1" });
    ok(await waitFor(() => metaOf(doc) === "完成", 3000, "完成"), "done → 完成态：" + metaOf(doc));
    ok(items(doc)[0].className.indexOf("upload-done") !== -1, "行也切到 done 态");
    window.close();
  }

  console.log("\n[3] 失败显示原因，点「重试」按原路径重推（不必重选文件）");
  {
    const { window, calls, pending } = await boot({
      file_upload_pick: () => Promise.resolve({ ok: true, items: [ITEM] }),
    });
    const doc = window.document;
    await waitFor(() => /设备: A1/.test(doc.getElementById("file-dev-now").textContent),
                   3000, "设备就绪");
    clickUploadBtn(window);
    await waitFor(() => items(doc).length === 1, 3000, "队列项");

    fireUpload(pending, { task_id: "p1", status: "failed",
                          error: "adb: error: failed to copy: remote offline",
                          name: "big.bin", remote: "/sdcard/big.bin", serial: "A1" });
    ok(await waitFor(() => metaOf(doc) === "失败", 3000, "失败"), "failed → 失败态");
    const row = items(doc)[0];
    const why = row.querySelector(".upload-err");
    ok(!!why && why.textContent.indexOf("remote offline") !== -1,
       "失败原因直接显示在行内：" + (why && why.textContent));

    const retry = row.querySelector('[data-uact="retry"]');
    ok(!!retry, "失败项给出「重试」按钮");
    retry.dispatchEvent(new window.Event("click", { bubbles: true }));
    ok(await waitFor(() => calls.some((c) => c.fn === "file_upload_path"), 3000, "重试调用"),
       "重试走 file_upload_path（后端按原路径重推）");
    const rc = calls.filter((c) => c.fn === "file_upload_path").pop();
    ok(rc.args[0] === "A1" && rc.args[1] === "/data/big.bin"
       && rc.args[2] === "/sdcard/big.bin" && rc.args[3] === "p1",
       "重试沿用原路径与 task_id：" + JSON.stringify(rc.args));
    ok(calls.filter((c) => c.fn === "file_upload_pick").length === 1,
       "重试不该再弹一次文件对话框");
    ok(await waitFor(() => metaOf(doc) === "0%", 3000, "重试回到上传中"),
       "重试后回到上传中：" + metaOf(doc));
    window.close();
  }

  console.log("\n[4] push 阶段长时间没有百分比：切不确定态，进度条不装死");
  {
    const { window } = await boot({
      file_upload_pick: () => Promise.resolve({ ok: true, items: [ITEM] }),
    });
    const doc = window.document;
    await waitFor(() => /设备: A1/.test(doc.getElementById("file-dev-now").textContent),
                   3000, "设备就绪");
    clickUploadBtn(window);
    await waitFor(() => items(doc).length === 1, 3000, "队列项");
    ok(items(doc)[0].className.indexOf("upload-stale") === -1, "刚提交时还是普通进度态");
    ok(await waitFor(() => items(doc)[0]
        && items(doc)[0].className.indexOf("upload-stale") !== -1, 4000, "stale"),
       "1.5s 没有新进度 → 切成不确定态（纯色进度条 + 传输中…）");
    ok(metaOf(doc) === "传输中…", "文案改为「传输中…」而不是钉在 0%：" + metaOf(doc));
    const fill = items(doc)[0].querySelector(".upload-bar > i");
    ok(!!fill, "进度条填充元素存在");
    ok(fill && fill.style.width !== "100%",
       "stale 态进度条不铺满（实际：" + (fill ? fill.style.width : "?") + "）");
    ok(fill && fill.style.width === "0%",
       "没有实际百分比时是空槽而非满格（实际：" + (fill ? fill.style.width : "?") + "）");
    window.close();
  }

  console.log("\n[5] 取消选择静默；后端报错要说出来");
  {
    const { window } = await boot({
      file_upload_pick: () => Promise.resolve({ ok: false, reason: "cancelled" }),
    });
    const doc = window.document;
    await waitFor(() => /设备: A1/.test(doc.getElementById("file-dev-now").textContent),
                   3000, "设备就绪");
    clickUploadBtn(window);
    await sleep(400);
    ok(items(doc).length === 0, "取消不产生队列项");
    ok(doc.getElementById("upload-queue").hidden === true, "队列面板保持隐藏");
    window.close();
  }

  {
    const { window } = await boot({
      file_upload_pick: () => Promise.resolve({ ok: false, reason: "no_device" }),
    });
    const doc = window.document;
    await waitFor(() => /设备: A1/.test(doc.getElementById("file-dev-now").textContent),
                   3000, "设备就绪");
    clickUploadBtn(window);
    ok(await waitFor(() => /no_device/.test(doc.getElementById("status").textContent || ""),
                     3000, "错误提示"),
       "非取消的失败要报到状态栏：" + (doc.getElementById("status").textContent || ""));
    window.close();
  }

  console.log("\n==============================================");
  console.log("结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})().catch((e) => {
  // 断言里访问到不存在的元素会抛错：这里必须立刻退出并报出来，否则 jsdom 的
  // 轮询定时器会让进程一直挂着，跑测试的人只看到「卡住」而不是「哪一行错了」。
  console.error("测试异常：", (e && e.stack) || e);
  process.exit(1);
});
