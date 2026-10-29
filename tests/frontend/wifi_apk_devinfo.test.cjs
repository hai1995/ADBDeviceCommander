/* jsdom 前端测试：无线调试 / 应用安装 / 设备信息 三块新 UI
 *
 * 这三块都是「点了就要有反应」的入口，锁四件事：
 *   1) 结构：入口按钮、弹窗、复选框都在，且工具页多出的 APK 卡是竖排的一张；
 *   2) 无线：点「连接」按用户输入的地址下发；最近记录 chip 一点即连；
 *      「开启 5555」把后端读到的设备 IP 自动填进地址框（省掉手动查 IP）；
 *   3) APK：未选包时「安装」禁用；选完包启用；勾选项按当前状态下发并落盘；
 *      后端 apk_state(running) 驱动按钮禁用 / 恢复（不靠状态文案猜）；
 *   4) 设备信息：点 ⓘ **不能**把设备取消勾选（stopPropagation 的回归点）。
 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.join(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "frontend/index.html"), "utf8");
const js = fs.readFileSync(path.join(ROOT, "frontend/js/app.js"), "utf8");
const css = fs.readFileSync(path.join(ROOT, "frontend/css/app.css"), "utf8");

let pass = 0, fail = 0;
function ok(c, n) {
  if (c) { pass++; console.log("  ✓ " + n); }
  else { fail++; console.log("  ✗ " + n); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitFor(fn, ms = 4000, label = "") {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    let v = false;
    try { v = !!fn(); } catch (e) { v = false; }
    if (v) return true;
    await sleep(40);
  }
  console.log("    (waitFor 超时: " + label + ")");
  return false;
}
const click = (win, el) => el.dispatchEvent(new win.Event("click", { bubbles: true }));

const DEVICES = [
  { serial: "A1", model: "Pixel", ok: true, checked: true, state: "device" },
];

function mkEnv(settings, overrides, devices) {
  const dom = new JSDOM(html, {
    runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/",
  });
  const { window } = dom;
  const calls = [];
  const pending = [
    { kind: "booted", payload: { version: "v-test", warnings: [], adb: "adb",
                                 commands: [], settings: settings || {} } },
    { kind: "devices", payload: { items: devices || DEVICES } },
  ];
  const impl = {
    boot: () => Promise.resolve({ version: "v-test", warnings: [], adb: "adb",
                                  commands: [], settings: settings || {} }),
    take_events: () => Promise.resolve(pending.splice(0)),
    default_save_dir: () => Promise.resolve({ dir: "" }),
    save_settings: (patch) => { calls.push({ fn: "save_settings", args: [patch] }); return Promise.resolve({ ok: true }); },
    wifi_state: () => {
      calls.push({ fn: "wifi_state", args: [] });
      return Promise.resolve({
        ok: true, port: 5555, selected: ["A1"], usb: ["A1"],
        wireless: [{ serial: "192.168.1.23:5555", model: "MI 11", ok: true, state: "device" }],
        recent: ["192.168.1.23:5555", "10.0.0.8:5555"],
      });
    },
    wifi_connect: (addr) => {
      calls.push({ fn: "wifi_connect", args: [addr] });
      return Promise.resolve({ ok: true, address: addr, message: "连接成功" });
    },
    wifi_disconnect: (addr) => {
      calls.push({ fn: "wifi_disconnect", args: [addr] });
      return Promise.resolve({ ok: true });
    },
    wifi_enable: () => {
      calls.push({ fn: "wifi_enable", args: [] });
      return Promise.resolve({
        ok: true, port: 5555, address: "192.168.1.30:5555",
        results: [{ serial: "A1", ip: "192.168.1.30", address: "192.168.1.30:5555",
                    ok: true, message: "已切换为无线模式（端口 5555）" }],
      });
    },
    apk_pick: () => {
      calls.push({ fn: "apk_pick", args: [] });
      return Promise.resolve({ ok: true, path: "C:/x/demo.apk", name: "demo.apk",
                               size: 1234, size_text: "1.2 KB" });
    },
    apk_install: (...args) => {
      calls.push({ fn: "apk_install", args });
      return Promise.resolve({ ok: true, count: 1 });
    },
    device_info: (serial) => {
      calls.push({ fn: "device_info", args: [serial] });
      return Promise.resolve({ ok: true, serial, rows: [["型号", "MI 11"], ["电量", "87%（充电中）"]],
                               text: "型号: MI 11\n电量: 87%（充电中）" });
    },
    toggle_device: (serial, on) => {
      calls.push({ fn: "toggle_device", args: [serial, on] });
      return Promise.resolve({ ok: true });
    },
    ...(overrides || {}),
  };
  window.pywebview = {
    api: new Proxy(impl, {
      get(t, k) {
        if (k === "then") return undefined;
        if (k in t) return t[k];
        return () => Promise.resolve({ ok: true });
      },
    }),
  };
  Object.defineProperty(window.document, "readyState", { value: "complete", configurable: true });
  window.eval(js);
  return { window, doc: window.document, calls, pending };
}

const called = (calls, fn) => calls.filter((c) => c.fn === fn);
const savedPrefs = (calls) => called(calls, "save_settings").map((c) => c.args[0]);

const watchdog = setTimeout(() => {
  console.log("    (看门狗触发：疑似断言抛错导致未收尾)");
  process.exit(fail ? 1 : 0);
}, 60000);

(async () => {
  console.log("[A] 结构");
  {
    ok(/id="btn-wifi"[^>]*data-icon="wifi"/.test(html), "设备栏有「无线」按钮且带 wifi 图标");
    ok(/id="wifi-modal"/.test(html), "无线调试弹窗存在");
    ["wifi-addr", "wifi-connect", "wifi-tcpip", "wifi-connected", "wifi-recent"].forEach((id) => {
      ok(new RegExp('id="' + id + '"').test(html), "弹窗内有 #" + id);
    });
    ok(/id="apk-card"[\s\S]*?id="apk-replace"[\s\S]*?id="apk-downgrade"[\s\S]*?id="apk-grant"/.test(html),
      "应用安装卡含三个安装选项复选框");
    ok(/id="devinfo-modal"[\s\S]*?id="devinfo-rows"/.test(html), "设备信息弹窗存在");
    ok(/\.wifi-chip\s*\{/.test(css) && /\.devinfo-row\s+\.k\s*\{/.test(css),
      "样式表包含无线 chip 与设备信息两列布局");
    ok(/\.device-card\s+\.dev-info\s*\{/.test(css), "设备卡片 ⓘ 按钮有独立样式");
  }

  console.log("\n[B] 无线调试：连接 / 最近记录 / 开启 5555 自动带出 IP");
  {
    const { window, doc, calls } = mkEnv();
    await waitFor(() => !!doc.getElementById("btn-wifi"), 4000, "页面就绪");
    // 设备快照由 take_events 轮询送达（400ms 一次）：先等设备卡出现，
    // 否则「开启 5555」会因为「没有受控设备」被正确禁用——这是生产行为，不是 bug。
    await waitFor(() => doc.querySelectorAll("#device-list .device-card").length === 1, 4000,
      "设备快照");
    click(window, doc.getElementById("btn-wifi"));
    ok(await waitFor(() => called(calls, "wifi_state").length === 1, 3000, "wifi_state"),
      "点「无线」→ 拉取 wifi_state");
    ok(!doc.getElementById("wifi-modal").classList.contains("hidden"), "弹窗已打开");
    ok(await waitFor(() => doc.querySelectorAll("#wifi-connected .wifi-item").length === 1, 3000,
      "无线设备行"), "已连接的无线设备渲染成一行");
    ok(doc.querySelector("#wifi-connected .wifi-item .serial").textContent === "192.168.1.23:5555",
      "行内显示 ip:port");
    ok(doc.querySelectorAll("#wifi-recent .wifi-chip").length === 2, "最近连接渲染成 2 个 chip");

    // 最近记录 chip：一点即连
    click(window, doc.querySelectorAll("#wifi-recent .wifi-chip")[1]);
    await sleep(60);
    ok(called(calls, "wifi_connect").length === 1
       && called(calls, "wifi_connect")[0].args[0] === "10.0.0.8:5555",
      "点第二个 chip → 用它的地址连接");

    // 手输地址 + 回车
    const addr = doc.getElementById("wifi-addr");
    addr.value = "192.168.1.99:6666";
    addr.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await sleep(80);
    const last = called(calls, "wifi_connect").pop();
    ok(last && last.args[0] === "192.168.1.99:6666", "输入框回车 → 用输入值连接");

    // 开启 5555：把后端读到的 IP 填进地址框
    addr.value = "";
    click(window, doc.getElementById("wifi-tcpip"));
    ok(await waitFor(() => doc.getElementById("wifi-addr").value === "192.168.1.30:5555", 3000,
      "自动填 IP"), "「开启无线调试」后自动填入设备 IP:5555");
    ok(called(calls, "wifi_enable").length === 1, "调用 wifi_enable");

    window.close();
  }

  console.log("\n[C] 应用安装：选包 → 启用 → 安装参数 → apk_state 驱动按钮");
  {
    const { window, doc, calls, pending } = mkEnv();
    await waitFor(() => !!doc.getElementById("apk-install"), 4000, "页面就绪");
    await sleep(120);
    ok(doc.getElementById("apk-install").disabled === true, "未选安装包时「安装」禁用");
    ok(doc.getElementById("apk-file").textContent === "未选择安装包", "显示空态文案");

    click(window, doc.getElementById("apk-pick"));
    ok(await waitFor(() => !doc.getElementById("apk-install").disabled, 3000, "启用安装"),
      "选完包后「安装」启用");
    ok(doc.getElementById("apk-file").textContent.indexOf("demo.apk") === 0, "显示文件名");
    ok(doc.getElementById("apk-file").textContent.indexOf("1.2 KB") > 0, "显示安装包体积");

    // 默认：覆盖安装开、降级/授权关
    click(window, doc.getElementById("apk-install"));
    await sleep(80);
    let args = called(calls, "apk_install").pop().args;
    ok(args[0] === null && args[1] === true && args[2] === false && args[3] === false,
      "默认参数为「覆盖安装、不降级、不授权」");

    // 勾选「授予权限」：即时落盘，且下次安装带上
    const grant = doc.getElementById("apk-grant");
    grant.checked = true;
    grant.dispatchEvent(new window.Event("change", { bubbles: true }));
    await sleep(60);
    ok(savedPrefs(calls).some((p) => p.apk_grant === true), "勾选项即时落盘 apk_grant=true");

    pending.push({ kind: "apk_state", payload: { running: false } });
    await sleep(120);
    click(window, doc.getElementById("apk-install"));
    await sleep(80);
    args = called(calls, "apk_install").pop().args;
    ok(args[3] === true, "再次安装时下发 apk_grant=true");

    // apk_state 驱动按钮（安装中禁用 / 结束恢复）
    pending.push({ kind: "apk_state", payload: { running: true } });
    ok(await waitFor(() => doc.getElementById("apk-install").disabled, 3000, "安装中禁用"),
      "apk_state(running=true) → 安装按钮禁用");
    pending.push({ kind: "apk_state", payload: { running: false } });
    ok(await waitFor(() => !doc.getElementById("apk-install").disabled, 3000, "安装结束恢复"),
      "apk_state(running=false) → 恢复可用");

    window.close();
  }

  console.log("\n[D] 设备信息：ⓘ 打开弹窗且不误触勾选");
  {
    const { window, doc, calls } = mkEnv();
    await waitFor(() => doc.querySelectorAll("#device-list .device-card").length === 1, 4000,
      "设备卡");
    const card = doc.querySelector("#device-list .device-card");
    const info = card.querySelector(".dev-info");
    ok(!!info, "设备卡片上有 ⓘ 按钮");
    click(window, info);
    ok(await waitFor(() => called(calls, "device_info").length === 1, 3000, "device_info"),
      "点 ⓘ → 调 device_info");
    ok(called(calls, "device_info")[0].args[0] === "A1", "带的是该设备的序列号");
    ok(doc.getElementById("devinfo-modal").classList.contains("hidden") === false, "弹窗已打开");
    ok(await waitFor(() => doc.querySelectorAll("#devinfo-rows .devinfo-row").length === 2, 3000,
      "两行信息"), "两行信息已渲染");
    ok(doc.querySelector("#devinfo-rows .devinfo-row .k").textContent === "型号", "首行标签为「型号」");
    ok(called(calls, "toggle_device").length === 0,
      "点 ⓘ 不会顺带切换勾选（stopPropagation 生效）");

    // 复制：navigator.clipboard 可用时走它
    let copied = "";
    Object.defineProperty(window.navigator, "clipboard", {
      value: { writeText: (t) => { copied = t; return Promise.resolve(); } },
      configurable: true,
    });
    click(window, doc.getElementById("devinfo-copy"));
    await sleep(80);
    ok(copied.indexOf("型号: MI 11") === 0, "复制内容为纯文本设备信息");

    // Esc 关闭
    doc.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    ok(doc.getElementById("devinfo-modal").classList.contains("hidden"), "Esc 关闭设备信息弹窗");

    window.close();
  }

  console.log("[E] 设备信息：连点两台设备的 ⓘ");
  {
    // 先点 A1（故意慢），再点 B2（快）。慢的那个回来时不能覆盖快的结果——
    // 否则弹窗标题是 B2、内容是 A1，最容易被当成「信息读错了」。
    const { window, doc } = mkEnv({}, {
      device_info: (serial) => new Promise((resolve) => {
        setTimeout(() => resolve({
          ok: true, serial,
          rows: [["型号", serial === "A1" ? "甲机" : "乙机"]],
          text: "型号: " + serial,
        }), serial === "A1" ? 260 : 30);
      }),
    }, [
      { serial: "A1", model: "Pixel", ok: true, checked: true, state: "device" },
      { serial: "B2", model: "X10", ok: true, checked: false, state: "device" },
    ]);

    ok(await waitFor(() => doc.querySelectorAll("#device-list .device-card").length === 2, 3000,
      "两张设备卡"), "两台设备都渲染出来");

    const cards = doc.querySelectorAll("#device-list .device-card");
    click(window, cards[0].querySelector(".dev-info"));
    await sleep(60);
    click(window, cards[1].querySelector(".dev-info"));
    await sleep(500);            // 等慢的那个也回来

    const title = doc.getElementById("devinfo-title").textContent;
    const val = doc.querySelector("#devinfo-rows .devinfo-row .v");
    ok(title.indexOf("B2") >= 0, "标题停在最后点开的 B2（实际：" + title + "）");
    ok(val && val.textContent === "乙机", "内容也是 B2 的，慢回包被丢弃（实际：" +
      (val && val.textContent) + "）");

    window.close();
  }

  clearTimeout(watchdog);
  console.log("\n" + "=".repeat(46));
  console.log("结果：" + pass + " 通过 / " + fail + " 失败");
  process.exit(fail ? 1 : 0);
})();
