# -*- coding: utf-8 -*-
"""门禁：用户动作失败时**必须**有提示，不能静默。

「点了没反应」是这一类 bug 最典型的症状：后端返回 `{"ok": False, "reason": ...}`，
前端不检查返回值，后端也不播报 —— 用户既看不到原因，也以为程序卡了，只能反复点。

规则：`backend/controllers/` 下凡是「会返回 ok=False」的**公共**方法，
必须二选一：

  * 自己播报（`_push_status` / `_push_toast` / `_ws_status` / `_ws_toast`）——
    这样无论前端是否检查，用户都看得到；
  * 或者列在下面的豁免名单里（前端确实检查了返回并展示原因，附理由）——
    豁免不是「放过」，而是「换个地方负责」，所以名单里的每一条都要在
    前端代码里**真的**有对应的检查（本测试会验）。

新增用户动作时忘了播报、又忘了在前端检查，这里立刻红。
"""
import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
CTRL_DIR = ROOT / "backend" / "controllers"
FRONTEND = ROOT / "frontend" / "js" / "app.js"

# 豁免：前端确实检查了返回并展示原因（逐条写明理由）
EXEMPT = {
    "apk_pick": "前端 pickApk 检查 res.ok === false 并弹警告",
    "boot": "前端启动流程检查返回，并有 3 秒自动重试",
    "device_info": "前端在弹窗里显示 res.reason",
    "export_commands": "前端 exportCmd 检查 data.ok",
    "export_commands_save": "前端 saveExportFile 检查 data.ok",
    "get_manual": "前端 loadManual 把失败原因显示在关于页",
    "import_commands": "前端 importCmdFromFile 检查 data.ok",
    "import_commands_dialog": "前端 importCmdFromDialog 检查 data.ok",
    "load_commands": "前端 reloadCommands 只在 data.ok 时才应用",
    "logcat_packages": "serial 为空时前端自己先拦（后端只对空 serial 返 ok=False）",
    "logcat_pidof": "serial/package 为空时前端自己先拦",
    "perf_list_packages": "前端把失败原因显示在包名计数处",
    "refresh_devices": "前端检查 res.running / adbRes.ok",
    "screenshot_data": "前端显示「预览生成失败」并可重试",
    "wifi_state": "仅在关窗时失败，无需打扰",
    "ws_open": "前端检查 res.ok === false 并弹警告",
    "ws_close": "前端 closeWorkspace 检查返回并提示（关窗中除外）",
}

# 前端「确实检查了返回」的判据（豁免名单里每条都要满足）
_CHECK_TOKENS = ("ok === false", "!res", "!data", "res.ok", "data.ok",
                  "res.reason", "data.reason", "res.message", ".catch(",
                  "res.running", "adbRes.ok")


def _returns_ok_false(fn):
    for node in ast.walk(fn):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            for k, v in zip(node.value.keys, node.value.values):
                if (isinstance(k, ast.Constant) and k.value == "ok"
                        and isinstance(v, ast.Constant) and v.value is False):
                    return True
    return False


def _broadcasts(fn):
    body = ast.dump(fn)
    return any(k in body for k in ("_push_status", "_push_toast",
                                    "_ws_status", "_ws_toast"))


def _controller_methods():
    for path in sorted(CTRL_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in [n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef)]:
            if fn.name.startswith("_"):
                continue          # 私有辅助方法：不直接面向前端
            if not _returns_ok_false(fn):
                continue
            yield path, fn


def test_user_action_failures_are_never_silent():
    """凡是会返回 ok=False 的控制器公共方法，都必须有人负责「告诉用户」。"""
    problems = []
    for path, fn in _controller_methods():
        if _broadcasts(fn):
            continue
        if fn.name in EXEMPT:
            continue
        problems.append("%s:%d %s() 返回 ok=False 但既不播报、也不在豁免名单里"
                        % (path.relative_to(ROOT), fn.lineno, fn.name))
    assert not problems, "\n".join(problems)


def test_exemptions_are_still_exemptions():
    """豁免名单不能变成「过期许可证」：方法名消失、或前端不再检查，都算失败。"""
    front = FRONTEND.read_text(encoding="utf-8")
    problems = []
    for name, why in EXEMPT.items():
        found_backend = any(fn.name == name for _p, fn in _controller_methods())
        if not found_backend:
            problems.append("%s：后端已没有这个方法，豁免作废" % name)
            continue
        if ("api.%s(" % name) not in front:
            problems.append("%s：前端已不再调用这个接口，豁免作废" % name)
            continue
        ok = False
        for m in re.finditer(r"api\.%s\(" % re.escape(name), front):
            block = front[m.start(): m.start() + 900]
            if any(tok in block for tok in _CHECK_TOKENS):
                ok = True
                break
        if not ok:
            problems.append("%s：前端已不再检查它的返回值，豁免作废（%s）"
                            % (name, why))
    assert not problems, "\n".join(problems)
