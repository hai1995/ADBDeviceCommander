# 测试体系

本项目有两套测试：**Python 单测**（pytest）与**前端测试**（Node + jsdom）。
CI（`.github/workflows/build.yml` 的 `test` job）每次 push 都会先跑静态检查、
再跑这两套，全绿才允许 Windows 打包。本地提交前请按下面"一键全跑"执行同样的三步。

## 目录结构

```
tests/
├── conftest.py              # pytest 全局夹具：patch_ctrl（见下）+ 探针置空
├── test_*.py                # Python 单测，按被测模块命名（66+ 个文件）
├── frontend/
│   ├── *.test.cjs           # 前端 jsdom 测试（100+ 个文件，随迭代增长）
│   ├── run-all.cjs          # 顺序跑完所有 *.test.cjs 的入口
│   └── package.json         # 依赖 jsdom（+ playwright）
└── README.md                # 本文档
```

Python 侧大致分三类：

| 类别 | 代表文件 | 断言什么 |
| --- | --- | --- |
| 纯逻辑单测 | `test_inject.py` / `test_*.py` | `-s` 拼接、命令归一化、ls 解析、版本比较等函数的输入输出 |
| 后端行为单测 | `test_backend_mf_native.py` 等 | 用假件（monkeypatch）驱动 service / worker，验证状态机、超时、错误上报 |
| **源码守卫测试** | `test_native_sink_guards.py` | 直接读 `native/*.cpp` 源码字符串断言关键结构存在——Linux 沙箱无 Windows SDK、无法编译 native，用静态锁定代替（如"排空必须有批上限""切段不得在 write_video 内同步执行"） |

前端侧每个 `*.test.cjs` 用 jsdom 构造 DOM、加载 `frontend/js/app.js`，验证按钮态、
事件路由、渲染、弹窗、跑马灯等。新增 UI 行为时通常配一个同名测试文件。

## 运行方式

### Python 单测

```bash
python3 -m pytest -q
```

### 前端测试

```bash
cd tests/frontend
npm install            # 首次 / 依赖变更时；jsdom 约几十 MB，node_modules 已 gitignore
npm test               # = node run-all.cjs，跑完全部 *.test.cjs
node xxx.test.cjs      # 只跑单个文件，排查时用
```

> 前端测试只依赖 jsdom（纯 JS DOM 模拟），**不需要启动 pywebview / WebView2**。
> `playwright` 在 devDependencies 里，供个别需要真实浏览器的用例预留，日常 `npm test` 不依赖它。

### 一键全跑（提交前 = CI 的三道门）

在仓库根目录：

```bash
python3 -m pyflakes backend core tools tests   # ① 静态检查：未定义名 / 未用导入
python3 -m ruff check .                         # ② 防劣化门禁（CI 固定 ruff==0.17.4）
python3 -m pytest -q                            # ③ Python 全量
cd tests/frontend && npm test                   # ④ 前端全量
```

> **为什么把静态检查列在单测前**：本地 `pytest` 不覆盖 lint。历史上曾因测试里误留
> 一行未用的 `import inspect`、以及 native C++ 漏定义 `ADC_OK`，导致整条 CI 连续
> 挂掉。pyflakes/ruff 会在单测前把这类问题拦下，务必本地先过一遍。

## 写测试的约定

- **改函数签名 / 返回值 / 字段名 = 全链路同步**：调用方、前端、测试里的 mock 断言
  都要一起改，改完 `grep -rn "旧名字"` 确认无残留。
- **重构复杂逻辑前先写失败用例**：在旧代码上跑出预期失败，再改实现，用例转绿即证明
  没丢功能。
- **改既有分支至少补一条覆盖用例**：新增 fallback、错误文案、分支拆分都要有断言。
- **patch 控制器依赖用 `conftest.patch_ctrl`**：`WebApi` 已拆成多个 controller Mixin，
  每个模块持有导入名字的副本，直接 `patch("backend.controller.xxx")` 会静默落空。
  统一用 `patch_ctrl(monkeypatch, "名字", 假件)` 打到所有引用模块。
- **改 native（C++）必须升指纹并补守卫**：在 `test_native_sink_guards.py` 加静态断言
  锁定新行为，并把 `kBuildId` 升版本；真机靠日志里的指纹确认加载了新 DLL。
- **改前端 HTML / input id / 事件时序会影响 jsdom**：改完跑一遍
  `node tests/frontend/run-all.cjs`（或至少相关的 `*.test.cjs`）。

以上约定是"改功能不搞崩功能"的硬门禁，详见仓库根 `README.md` 的「二次开发 →
硬约束」一节。
