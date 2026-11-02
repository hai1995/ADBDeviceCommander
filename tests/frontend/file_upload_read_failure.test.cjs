/* jsdom 前端行为测试：文件上传「读不出来」时必须说出来。

   两条都不会报错，只会静默：
     * FileReader 读失败（文件被独占锁住 / 无权限 / 读的瞬间被删）时既不触发
       onload 也不报错 —— 旧实现下用户只看到「⬆ 已提交上传 N 个文件」，
       之后再无任何动静，也不知道该不该重试；
     * 读到了但内容为空（readAsDataURL 给出 "data:...;base64,"）时，空串会
       被传给后端，后端照常写出 0 字节文件并报「✓ 上传完成」—— 设备上多出
       一个空文件，用户以为传成功了。
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
function toastTexts(doc) {
  return Array.from(doc.querySelectorAll(".toast-body")).map((n) => n.textContent || "");
}

/* 可替换的 FileReader：jsdom 自带的那份无法构造「读失败 / 空内容」两种情形。 */
function makeReader(mode) {
  return function () {
    function FakeReader() {
      this.onload = null; this.onerror = null;
      this.error = null; this.result = null;
    }
    FakeReader.prototype.readAsDataURL = function () {
      setTimeout(() => {
        if (mode === "error") {
          this.error = { message: "NotReadableError: 文件被占用" };
          if (this.onerror) this.onerror();
        } else if (mode === "empty") {
          this.result = "data:text/plain;base64,";
          if (this.onload) this.onload();
        } else {
          this.result = "data:text/plain;base64,aGVsbG8=";
          if (this.onload) this.onload();
        }
      }, 5);
    };
    return FakeReader;
  };
}

async function boot(mode) {
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
  window.FileReader = makeReader(mode)();
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  await sleep(600);
  return { window, calls };
}

function triggerUpload(window, name) {
  const inp = window.document.getElementById("file-upload");
  Object.defineProperty(inp, "files", { value: [{ name: name }], configurable: true });
  inp.dispatchEvent(new window.Event("change"));
}

(async () => {
  console.log("\n[1] FileReader 读失败：必须说出来，不能只留一句「已提交上传」");
  {
    const { window, calls } = await boot("error");
    triggerUpload(window, "locked.bin");
    const shown = await waitFor(
      () => toastTexts(window.document).some((t) => t.includes("无法读取")),
      3000, "read error toast");
    ok(shown, "读失败时弹出「无法读取 <文件名>」提示");
    ok(!calls.some((c) => c.fn === "file_upload_data"),
       "读失败时不得把空内容发给后端");
    window.close();
  }

  console.log("\n[2] 读到了但内容为空：不能上传一个 0 字节文件还报成功");
  {
    const { window, calls } = await boot("empty");
    triggerUpload(window, "zero.txt");
    const shown = await waitFor(
      () => toastTexts(window.document).some((t) => t.includes("内容为空")),
      3000, "empty content toast");
    ok(shown, "内容为空时弹出「读到的内容为空」提示");
    ok(!calls.some((c) => c.fn === "file_upload_data"),
       "内容为空时不该调用 file_upload_data（会在设备上留一个空文件）");
    window.close();
  }

  console.log("\n[3] 正常内容：照常上传（别把上面的拦截做过头）");
  {
    const { window, calls } = await boot("ok");
    triggerUpload(window, "ok.txt");
    const sent = await waitFor(
      () => calls.some((c) => c.fn === "file_upload_data"), 3000, "upload called");
    ok(sent, "正常内容仍会上传");
    const call = calls.find((c) => c.fn === "file_upload_data");
    ok(call && call.args[2] === "aGVsbG8=", "传上去的 base64 与文件内容一致");
    ok(!toastTexts(window.document).some((t) => t.includes("无法读取") || t.includes("内容为空")),
       "正常路径不该出现错误提示");
    window.close();
  }

  console.log("\n==============================================");
  console.log("结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
