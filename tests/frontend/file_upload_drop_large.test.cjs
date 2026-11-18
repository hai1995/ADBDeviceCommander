/* jsdom 前端行为测试：拖拽上传大文件必须「明确拦截 + 弹窗引导」，而不是入队后
   走一条注定失败的通道。

   背景（真实用户反馈）：用「上传」按钮选一个 414MB 的压缩包能成功，但把同一个
   文件直接拖进程序就失败，队列里留一条「读到的内容为空」。根因是两条通道不同：
     * 拖拽 / 文件选择 → 浏览器只给 File 对象、没有本地路径，submitUpload 要把整个
       文件 FileReader.readAsDataURL 转成 base64 经 js_api 桥送后端 —— 大文件这一趟
       读出来是空的；
     * 「上传」按钮 → pickUploadFiles 走原生对话框拿到本地路径，后端直接 adb push。
   所以大文件拖拽应当直接拦下，用高优先级弹窗（showAlert，不点不消失）说清楚原因
   并给出操作建议，而不是让用户对着一条失败记录干瞪眼。

   锁定：
     [1] 拖拽超大文件 → 弹窗打开、标题/正文说清「大文件不支持拖拽」+「上传」按钮建议；
     [2] 被拦的大文件不入队、不调 file_upload_data（避免注定失败的过桥）；
     [3] 小文件拖拽照常上传（别把拦截做过头）；
     [4] 大小混合：大的拦、小的传，两不误；
     [5] 弹窗层级足够、role=alertdialog、需主动关闭；
     [6] 上限提高到 200MB 后，一百多MB的 APK 仍可正常拖拽上传（不被误拦）。 */
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
async function waitFor(fn, ms = 3000, label = "") {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    let v = false; try { v = !!fn(); } catch (e) { v = false; }
    if (v) return true;
    await sleep(30);
  }
  console.log("    (waitFor 超时: " + label + ")");
  return false;
}

function makeReader() {
  return function () {
    function FakeReader() {
      this.onload = null; this.onerror = null; this.error = null; this.result = null;
    }
    FakeReader.prototype.readAsDataURL = function () {
      setTimeout(() => {
        this.result = "data:application/zip;base64,aGVsbG8=";
        if (this.onload) this.onload();
      }, 5);
    };
    return FakeReader;
  };
}

async function boot() {
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
  const { window } = dom;
  const queue = [
    { kind: "booted", payload: { version: "v-test", warnings: [], commands: [] } },
    { kind: "devices", payload: { items: [{ serial: "A1", ok: true, checked: true }] } },
    { kind: "file", payload: { serial: "A1", path: "/sdcard", entries: [] } },
  ];
  const calls = [];
  const apiStub = new Proxy({}, {
    get(t, k) {
      if (k === "then") return undefined;
      return function (...args) {
        calls.push({ fn: String(k), args });
        if (k === "boot") return Promise.resolve({ version: "v-test", warnings: [], commands: [], adb: "/usr/bin/adb", save_dir: "/tmp" });
        if (k === "take_events") return Promise.resolve(queue.splice(0, queue.length));
        return Promise.resolve({ ok: true });
      };
    },
  });
  window.pywebview = { api: apiStub };
  window.FileReader = makeReader()();
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  await sleep(600);
  return { window, calls };
}

/* 构造带 size 的假文件 + 触发文件区的 drop 事件。 */
function dropFiles(window, files) {
  const dz = window.document.getElementById("file-table-wrap");
  const ev = new window.Event("drop", { bubbles: true, cancelable: true });
  Object.defineProperty(ev, "dataTransfer", {
    value: { files: files, types: ["Files"] }, configurable: true,
  });
  dz.dispatchEvent(ev);
}
const mkFile = (name, size) => ({ name, size });
const alertOpen = (doc) => {
  const m = doc.getElementById("alert-modal");
  return !!m && !m.classList.contains("hidden");
};
const alertText = (doc) => (doc.getElementById("alert-body") || {}).textContent || "";
const alertTitle = (doc) => (doc.getElementById("alert-title") || {}).textContent || "";
const queueText = (doc) => (doc.getElementById("upload-queue-list") || {}).textContent || "";
const clickEl = (doc, el) => el.dispatchEvent(new doc.defaultView.Event("click", { bubbles: true }));

(async () => {
  const MB = 1024 * 1024;

  console.log("\n[1] 拖拽超大文件：弹窗打开，说清原因与操作建议");
  {
    const { window, calls } = await boot();
    const doc = window.document;
    dropFiles(window, [mkFile("Downloads_5.zip", 414 * MB)]);
    ok(await waitFor(() => alertOpen(doc), 3000, "alert open"), "大文件拖拽触发弹窗");
    ok(/大文件/.test(alertTitle(doc)) && /拖拽/.test(alertTitle(doc)),
       "标题点明「大文件不支持拖拽」（实际：" + alertTitle(doc) + "）");
    const t = alertText(doc);
    ok(/Downloads_5\.zip/.test(t), "正文列出被拦的文件名");
    ok(/上传.*按钮|按钮.*上传/.test(t), "正文给出「点上传按钮」的操作建议（实际：" + t.slice(0, 160) + "）");
    ok(!calls.some((c) => c.fn === "file_upload_data"),
       "被拦的大文件不调 file_upload_data（不走注定失败的过桥）");
    window.close();
  }

  console.log("\n[2] 被拦大文件不入上传队列");
  {
    const { window } = await boot();
    const doc = window.document;
    dropFiles(window, [mkFile("huge.bin", 500 * MB)]);
    await waitFor(() => alertOpen(doc), 3000, "alert open");
    ok(queueText(doc).indexOf("huge.bin") < 0,
       "大文件没进上传队列（没有留一条永远失败的红色记录）");
    window.close();
  }

  console.log("\n[3] 小文件拖拽照常上传（别把拦截做过头）");
  {
    const { window, calls } = await boot();
    const doc = window.document;
    dropFiles(window, [mkFile("tiny.txt", 4 * MB)]);
    const sent = await waitFor(() => calls.some((c) => c.fn === "file_upload_data"), 3000, "upload called");
    ok(sent, "小文件仍会走 file_upload_data 正常上传");
    ok(!alertOpen(doc), "小文件不弹「大文件」告警");
    ok(queueText(doc).indexOf("tiny.txt") >= 0, "小文件出现在上传队列");
    window.close();
  }

  console.log("\n[4] 大小混合：大的拦、小的传，两不误");
  {
    const { window, calls } = await boot();
    const doc = window.document;
    dropFiles(window, [mkFile("big.zip", 300 * MB), mkFile("small.txt", 2 * MB)]);
    await waitFor(() => alertOpen(doc), 3000, "alert open");
    const t = alertText(doc);
    ok(/big\.zip/.test(t) && !/small\.txt/.test(t), "弹窗只列被拦的大文件");
    const sent = await waitFor(() => calls.some((c) => c.fn === "file_upload_data"), 3000, "small uploaded");
    ok(sent, "同一批里的小文件照常上传");
    ok(queueText(doc).indexOf("small.txt") >= 0 && queueText(doc).indexOf("big.zip") < 0,
       "队列里只有小文件");
    window.close();
  }

  console.log("\n[5] 弹窗本身：层级与关闭方式");
  {
    const { window } = await boot();
    const doc = window.document;
    dropFiles(window, [mkFile("huge.bin", 414 * MB)]);
    await waitFor(() => alertOpen(doc), 3000, "alert open");
    const m = doc.getElementById("alert-modal");
    ok(m.getAttribute("role") === "alertdialog", "role=alertdialog（读屏立刻播报）");
    ok(!!doc.getElementById("alert-ok"), "有「我知道了」按钮，需主动关闭（不自动消失）");
    clickEl(doc, doc.getElementById("alert-ok"));
    await sleep(60);
    ok(!alertOpen(doc), "点「我知道了」可关闭弹窗");
    window.close();
  }

  console.log("\n[6] 一百多MB的 APK 可拖拽（上限提高到 200MB 的回归）");
  {
    const { window, calls } = await boot();
    const doc = window.document;
    dropFiles(window, [mkFile("app-release.apk", 120 * MB)]);
    const sent = await waitFor(() => calls.some((c) => c.fn === "file_upload_data"),
                               3000, "apk upload called");
    ok(sent, "120MB 的 APK 仍可拖拽上传（不被误拦）");
    ok(!alertOpen(doc), "120MB 的 APK 不弹「大文件」告警");
    ok(queueText(doc).indexOf("app-release.apk") >= 0, "APK 正常进入上传队列");
    window.close();
  }

  console.log("\n==============================================");
  console.log("结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
