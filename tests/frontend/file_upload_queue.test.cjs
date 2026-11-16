/* jsdom 前端行为测试：上传队列（进度展示 + 失败重试 / 免重选）。

   覆盖：
     * 选文件后立即在队列里出现一项，状态「读取中」，队列面板展开；
     * 后端 file_upload 事件把进度百分比刷新到对应项（按 task_id，不串行）；
     * done → 完成态；failed → 失败态并显示原因；
     * 失败项点「重试」→ 复用已缓存的 File 重新提交（file_upload_data 第二次调用，
       且 FileReader 收到的是同一个文件对象 —— 用户不必重新去挑文件）；
     * 点「移除 / 清除已完成」把项从队列删掉，队列空了自动收起。
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

/* 可替换的 FileReader：记录每次 readAsDataURL 收到的文件对象，可控失败。 */
function makeReader(mode, reads) {
  return function () {
    function FakeReader() {
      this.onload = null; this.onerror = null;
      this.error = null; this.result = null;
    }
    FakeReader.prototype.readAsDataURL = function (file) {
      reads.push(file);
      setTimeout(() => {
        if (mode === "empty") {
          this.result = "data:text/plain;base64,";
        } else {
          this.result = "data:text/plain;base64,aGVsbG8=";
        }
        if (this.onload) this.onload();
      }, 5);
    };
    return FakeReader;
  };
}

async function boot(mode) {
  const reads = [];
  const dom = new JSDOM(html, { runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
  const { window } = dom;
  // pending 是可控事件源：boot 后测试可往里推 file_upload 事件。
  const pending = [
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
        if (k === "take_events") return Promise.resolve(pending.splice(0, pending.length));
        return Promise.resolve({ ok: true });
      };
    },
  });
  window.pywebview = { api: apiStub };
  window.FileReader = makeReader(mode, reads)();
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  await sleep(500);
  return { window, calls, reads, pending };
}

function fireUpload(window, pending, ev) { pending.push({ kind: "file_upload", payload: ev }); }
function items(doc) { return Array.from(doc.querySelectorAll("#upload-queue-list .upload-item")); }
function uploadCalls(calls) { return calls.filter((c) => c.fn === "file_upload_data"); }
function taskIdOf(call) { return call.args[4]; }

function triggerUpload(window, name, size) {
  const inp = window.document.getElementById("file-upload");
  const file = { name: name, size: size || 100 };
  Object.defineProperty(inp, "files", { value: [file], configurable: true });
  inp.dispatchEvent(new window.Event("change"));
  return file;
}

(async () => {
  console.log("\n[1] 选文件后立即入队、显示「读取中」、面板展开，且走带进度的后端通道");
  {
    const { window, calls, pending } = await boot("ok");
    const q = window.document.getElementById("upload-queue");
    ok(q.hidden === true, "无任务时队列面板默认隐藏");
    triggerUpload(window, "big.apk", 1024);
    await waitFor(() => items(window.document).length === 1, 4000, "one item");
    ok(q.hidden === false, "有任务时队列面板展开");
    const row = items(window.document)[0];
    ok(row.className.indexOf("upload-reading") !== -1 || row.className.indexOf("upload-uploading") !== -1,
       "新项处于读取中/上传中态：" + row.className);
    await waitFor(() => uploadCalls(calls).length >= 1, 4000, "upload called");
    const call = uploadCalls(calls)[0];
    ok(!!call, "调用了 file_upload_data");
    ok(call && call.args[5] === true, "开启进度通道（progress=true）：" + JSON.stringify(call && call.args.slice(4)));
    ok(typeof taskIdOf(call) === "string" && taskIdOf(call), "带 task_id 供进度事件匹配");
    window.close();
  }

  console.log("\n[2] 后端进度事件按 task_id 更新百分比，done 转完成态");
  {
    const { window, calls, pending } = await boot("ok");
    triggerUpload(window, "x.bin");
    await waitFor(() => uploadCalls(calls).length === 1, 4000, "upload called");
    const id = taskIdOf(uploadCalls(calls)[0]);
    fireUpload(window, pending, { task_id: id, serial: "A1", name: "x.bin", remote: "/sdcard/x.bin", status: "uploading", percent: 37 });
    await waitFor(() => {
      const row = items(window.document)[0];
      return row && row.querySelector(".upload-meta") && row.querySelector(".upload-meta").textContent.trim() === "37%";
    }, 4000, "progress 37%");
    const row = items(window.document)[0];
    ok(row.querySelector(".upload-meta").textContent.trim() === "37%", "进度显示 37%");
    fireUpload(window, pending, { task_id: id, status: "done", percent: 100 });
    await waitFor(() => items(window.document)[0].className.indexOf("upload-done") !== -1, 4000, "done");
    ok(items(window.document)[0].className.indexOf("upload-done") !== -1, "done 事件转完成态");
    window.close();
  }

  console.log("\n[3] 失败事件显示原因；点「重试」复用缓存 File 重传（免重选）");
  {
    const { window, calls, pending, reads } = await boot("ok");
    triggerUpload(window, "y.bin", 2048);
    await waitFor(() => uploadCalls(calls).length === 1, 4000, "first upload");
    const firstFile = reads[0];
    const id = taskIdOf(uploadCalls(calls)[0]);
    fireUpload(window, pending, { task_id: id, status: "failed", error: "remote offline" });
    await waitFor(() => items(window.document)[0].className.indexOf("upload-failed") !== -1, 4000, "failed");
    const row = items(window.document)[0];
    ok(!!row.querySelector(".upload-err") && row.querySelector(".upload-err").textContent.includes("remote offline"),
       "失败项显示原因");
    const retry = row.querySelector('[data-uact="retry"]');
    ok(!!retry, "失败项提供「重试」按钮");
    retry.dispatchEvent(new window.Event("click", { bubbles: true }));
    await waitFor(() => uploadCalls(calls).length === 2, 4000, "retry call");
    ok(uploadCalls(calls).length === 2, "重试再次调用 file_upload_data");
    ok(reads.length === 2 && reads[1] === firstFile, "重试复用同一个缓存 File（用户免重选）");
    ok(taskIdOf(uploadCalls(calls)[1]) === id, "重试沿用同一 task_id（更新原项，不新起一行）");
    ok(items(window.document).length === 1, "重试不新增队列项");
    window.close();
  }

  console.log("\n[4] 移除与「清除已完成」：队列空了自动收起");
  {
    const { window, calls, pending } = await boot("ok");
    triggerUpload(window, "a.txt");
    await waitFor(() => uploadCalls(calls).length === 1, 4000, "upload");
    const id = taskIdOf(uploadCalls(calls)[0]);
    fireUpload(window, pending, { task_id: id, status: "done", percent: 100 });
    await waitFor(() => items(window.document)[0].className.indexOf("upload-done") !== -1, 4000, "done");
    const clear = window.document.getElementById("upload-queue-clear");
    clear.dispatchEvent(new window.Event("click", { bubbles: true }));
    await waitFor(() => items(window.document).length === 0, 4000, "cleared");
    ok(items(window.document).length === 0, "清除已完成移除了完成项");
    ok(window.document.getElementById("upload-queue").hidden === true, "队列空后自动收起");
    window.close();
  }

  console.log("\n[5] 读取为空：入队即失败，不把空内容发给后端");
  {
    const { window, calls } = await boot("empty");
    triggerUpload(window, "zero.txt");
    await waitFor(() => {
      const r = items(window.document)[0];
      return r && r.className.indexOf("upload-failed") !== -1;
    }, 4000, "empty failed");
    ok(items(window.document)[0].className.indexOf("upload-failed") !== -1, "空内容被标为失败");
    ok(uploadCalls(calls).length === 0, "空内容不调用 file_upload_data（不在设备上留空文件）");
    window.close();
  }

  console.log("\n==============================================");
  console.log("结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
