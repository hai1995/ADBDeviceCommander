# -*- coding: utf-8 -*-
"""
core.commands —— 快捷命令归一化 / 加载 / 运行目录多文件合并去重。

启动时扫描「程序运行目录」（exe 同目录 / 开发态项目根）下所有有效命令合集
json（commands.json / quick_commands.json / 其它顶层为数组或对象的 *.json），
多份则合并去重后使用；一份都没有时在该目录生成 commands.json。
逻辑与旧 Tk 版同源，Web 版统一引用此处。
"""
import json
import os
import re
import uuid

from core.constants import program_dir
from core.builtin_commands import BUILTIN_COMMANDS

DEMO_COMMANDS = [
    {"id": "demo", "name": "[通用] 示例-查看时间", "labels": ["通用"],
     "commands": [{"delay": 100, "command": "adb shell date"}]},
]

# ---------------------------------------------------------------------------
# 运行目录下的「命令合集」文件约定
# ---------------------------------------------------------------------------
# 启动时扫描运行目录（exe 同目录 / 开发态项目根）下所有 *.json：
#   · commands.json        —— 首选 / 程序自动生成的标准文件名（本需求新增）
#   · quick_commands.json  —— 历史文件名，继续兼容（老用户 / 旧版分发）
#   · 目录里其它 *.json     —— 只要顶层是数组 / 对象且能解析，也当作命令合集一并合并
# 非命令类 json（配置）排除，避免把 config.json 当命令解析。
PRIMARY_COMMAND_FILE = "commands.json"
LEGACY_COMMAND_FILE = "quick_commands.json"
_NON_COMMAND_FILES = {"config.json"}

# 去掉命令名开头的 [标签] 前缀，得到用于「同名压制」比对的核心名。
_LABEL_RE = re.compile(r"^\s*\[[^\]]*\]\s*")
_WS_RE = re.compile(r"\s+")


def core_name(name):
    """命令核心名：去掉 [标签] 前缀并折叠空白，用于判断用户是否已有一份等价命令。

    折叠空白可避免「获取当前 Activity」与「获取当前Activity」这类仅空格差异被
    误判为两条不同命令而产生重复（用户 json 与内置默认命名习惯可能不一致）。
    """
    return _WS_RE.sub("", _LABEL_RE.sub("", name or "")).strip()


# ---------------------------------------------------------------------------
# 运行目录扫描 / 多文件合并 / 去重
# ---------------------------------------------------------------------------
def command_scan_dir():
    """命令合集文件的扫描目录 = 程序运行目录（exe 同目录 / 开发态项目根）。

    刻意不用 resource_path：frozen 下它会回退到 _MEIPASS 临时解包目录，那里
    每次运行都重新解压、不可写，也不是用户眼里的「运行目录」。单独抽成函数
    也便于测试替换。
    """
    return program_dir()


def _iter_candidate_files(directory):
    """列出目录下可能承载命令合集的 *.json（已排除配置 / 隐藏 / 临时文件）。"""
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    skip = {n.lower() for n in _NON_COMMAND_FILES}
    out = []
    for name in names:
        low = name.lower()
        if not low.endswith(".json"):
            continue
        if low in skip:
            continue
        # 导出备份（export_commands_save 写到运行目录的 commands_export_<时间>.json）
        # 不当作输入：否则用户「导出→删除某条→重启」会被导出文件又加回来。
        if low.startswith("commands_export_"):
            continue
        if name.startswith((".", "~$")) or low.endswith(".tmp"):
            continue
        p = os.path.join(directory, name)
        if os.path.isfile(p):
            out.append(p)

    # 优先级：commands.json > quick_commands.json > 其它（按文件名）。先出现的
    # 在去重时胜出，因此标准文件优先，其余作为补充。
    def _key(p):
        base = os.path.basename(p).lower()
        rank = 0 if base == PRIMARY_COMMAND_FILE else (
            1 if base == LEGACY_COMMAND_FILE else 2)
        return (rank, base)

    out.sort(key=_key)
    return out


def _read_json(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def _command_sig(c):
    """命令内容指纹（命令文本 + 间隔），用于判重时确认「内容确实一样」。"""
    try:
        return tuple((str(e.get("command", "")), int(e.get("delay", 0) or 0))
                     for e in c.get("commands", []))
    except Exception:
        return tuple()


def dedupe_commands(cmds):
    """跨文件去重：**同名（核心名）且同内容**、或 **同 id 且同内容** 才视为重复。

    刻意不「仅按名字」去重：同一功能在多个项目 / 标签下各存一份（例如 [J01] 清缓存
    与 [CEI] 清缓存 指向不同包名）是用户的合理用法，只按名字合并会直接丢数据。
    只有名字（或 id）与命令内容都一致时，才判定为重复，保留先出现者；同名同内容的
    重复项会把标签取并集。返回 (去重后列表, 被去除的条数)。
    """
    out = []
    by_id, by_core = {}, {}
    removed = 0
    for c in cmds:
        cid = c.get("id")
        cn = core_name(c.get("name", ""))
        sig = _command_sig(c)
        dup = None
        if cid and (cid, sig) in by_id:
            dup = by_id[(cid, sig)]
        elif cn and (cn, sig) in by_core:
            dup = by_core[(cn, sig)]
        if dup is not None:
            if cn and (cn, sig) in by_core:      # 同名同内容：并入标签，别丢分组
                for lb in c.get("labels", []):
                    if lb not in dup.setdefault("labels", []):
                        dup["labels"].append(lb)
            removed += 1
            continue
        out.append(c)
        if cid:
            by_id[(cid, sig)] = c
        if cn:
            by_core[(cn, sig)] = c
    return out, removed


def discover_commands(directory=None):
    """扫描目录、读取所有有效命令合集文件、合并去重。

    返回 (commands, warnings, files)：
      - commands：合并去重后的用户命令（未并入内置）
      - warnings：读取 / 解析 / 合并 / 生成过程中的提示
      - files：实际读取到的文件路径（按优先级排序）

    目录下**没有任何有效文件**时，在此目录生成 commands.json（预置示例），
    并把这份内容当作唯一来源返回。
    """
    directory = directory or command_scan_dir()
    warnings = []
    per_file = []       # [(path, normalized_cmds)]

    for p in _iter_candidate_files(directory):
        base = os.path.basename(p)
        try:
            raw = _read_json(p)
        except Exception as ex:
            warnings.append("命令文件读取失败：%s（%s）" % (base, ex))
            continue
        if not isinstance(raw, (list, dict)):
            warnings.append("命令文件 %s 顶层既不是数组也不是对象，已忽略" % base)
            continue
        try:
            cmds, w = normalize_commands(raw)
        except Exception as ex:
            warnings.append("命令文件 %s 解析异常：%s" % (base, ex))
            continue
        for msg in w:
            warnings.append("%s：%s" % (base, msg))
        per_file.append((p, cmds))

    if not per_file:
        # 没有有效命令合集文件 → 在运行目录生成 commands.json。
        # `_write_json_atomic` **返回 bool 而不抛异常**，所以这里不能再用
        # try/except 判成败：目录只读 / 磁盘满时异常根本不会发生，界面照样收到
        # 「已在运行目录生成 commands.json」—— 而磁盘上什么都没有，用户下次
        # 启动又看到同一条提示，来回找那个并不存在的文件。
        target = os.path.join(directory, PRIMARY_COMMAND_FILE)
        starter, _ = normalize_commands(DEMO_COMMANDS)
        if _write_json_atomic(target, DEMO_COMMANDS):
            warnings.append(
                "未检测到有效的命令合集文件，已在运行目录生成 %s（可直接编辑其中命令）"
                % PRIMARY_COMMAND_FILE)
        else:
            warnings.append(
                "未检测到有效的命令合集文件，且无法在运行目录生成 %s"
                "（目录只读 / 磁盘空间不足？）——本次先用内置示例命令，"
                "重启后不会保留。请把程序放到可写目录，或自行放一份命令合集 json"
                % PRIMARY_COMMAND_FILE)
        per_file = [(target, starter)]

    merged = []
    for _p, cmds in per_file:
        merged.extend(cmds)
    merged, removed = dedupe_commands(merged)
    if len(per_file) > 1 or removed:
        warnings.append(
            "已合并 %d 个命令文件%s"
            % (len(per_file), ("，去重 %d 条" % removed) if removed else ""))
    return merged, warnings, [p for p, _ in per_file]


def primary_command_path(directory=None):
    """用户命令的写入目标：优先 commands.json，其次历史 quick_commands.json；
    两者都不存在时返回 commands.json 路径（写入时创建）。"""
    directory = directory or command_scan_dir()
    p_primary = os.path.join(directory, PRIMARY_COMMAND_FILE)
    p_legacy = os.path.join(directory, LEGACY_COMMAND_FILE)
    if os.path.exists(p_primary):
        return p_primary
    if os.path.exists(p_legacy):
        return p_legacy
    return p_primary



def normalize_commands(raw):
    """把各种 electerm 快捷命令导出格式归一化为程序内部格式：
        [{"id": str, "name": str, "labels": [str],
          "commands": [{"command": str, "delay": int}], ...}]

    兼容小伙伴文件的常见差异：
      - 顶层：list 或 dict（取字典的 values）
      - 分组字段：`labels` / `tags` / `group`
      - commands：`字符串` 或 `数组`
      - 数组元素：dict（`command` / `cmd` / `script` 字段都认）或 纯字符串
      - 无 name 时回退 `id` / `title`
      - `inputOnly`（electerm「仅输入」标记）：命令只填入输入框、不自动执行
    无法解析出任何可执行命令的条目会被跳过，并收集 warning 反馈给用户。

    健壮性约束（本轮加固）：**任何一条坏数据都不能让整个加载失败**。
    手写 / 别处导出的 json 里 `"id": 1`、`"command": ["adb","devices"]` 这类
    类型错误很常见，而 load_commands 的调用方（boot）没有兜底 —— 一次 TypeError
    就会让程序「启动后一条命令都没有」且界面只说「未就绪」。因此这里对所有取自
    文件的字段做类型规整：非字符串一律转成字符串或跳过并告警，绝不外抛。
    """
    warnings = []
    items = raw
    if isinstance(raw, dict):
        items = list(raw.values())
    elif not isinstance(raw, list):
        warnings.append("快捷命令顶层结构既不是数组也不是对象（实际：%s），已全部忽略"
                        % type(raw).__name__)
        return [], warnings

    out = []
    used_ids = set()
    for idx, c in enumerate(items):
        if not isinstance(c, dict):
            warnings.append("第 %d 条命令不是对象（实际：%s），已跳过"
                            % (idx + 1, type(c).__name__))
            continue

        name = (c.get("name") or c.get("title") or c.get("id")
                or ("命令%d" % (idx + 1)))
        if not isinstance(name, str):
            name = str(name)

        # id：缺失 / 重复都补一个稳定的唯一值。
        # 旧实现原样保留（缺失即 ""），于是「没有 id」或「复制粘贴出重复 id」的多条
        # 命令在 run_command 里全都命中第一条 —— 点哪个都执行同一条命令，点击计数
        # 也会同时加到所有同名条目上，把「常用命令靠前」的排序带偏。
        raw_id = c.get("id")
        cid = raw_id.strip() if isinstance(raw_id, str) else (
            str(raw_id) if isinstance(raw_id, (int, float)) and not isinstance(raw_id, bool) else "")
        if not cid or cid in used_ids:
            cid = "auto%d" % (idx + 1)
            while cid in used_ids:
                cid += "_"
        used_ids.add(cid)

        # 分组标签归一化为 list
        raw_labels = c.get("labels")
        if raw_labels is None:
            raw_labels = c.get("tags")
        if raw_labels is None:
            raw_labels = c.get("group")
        if isinstance(raw_labels, str):
            labels = [raw_labels]
        elif isinstance(raw_labels, (list, tuple)):
            labels = [str(x) for x in raw_labels if x]
        else:
            labels = []
        if not labels:
            labels = ["其他"]

        # commands：字符串 / 数组 都兼容
        raw_cmds = c.get("commands")
        entries = []
        if isinstance(raw_cmds, str):
            if raw_cmds.strip():
                entries = [{"command": raw_cmds.strip(), "delay": 0}]
        elif isinstance(raw_cmds, (list, tuple)):
            for j, e in enumerate(raw_cmds):
                if isinstance(e, str):
                    if e.strip():
                        entries.append({"command": e.strip(), "delay": 0})
                elif isinstance(e, dict):
                    cmd = None
                    for key in ("command", "cmd", "script"):
                        v = e.get(key)
                        if v is not None:
                            cmd = v
                            break
                    if isinstance(cmd, str) and cmd.strip():
                        try:
                            d = int(e.get("delay", 0) or 0)
                        except Exception:
                            d = 0
                        entries.append({"command": cmd.strip(), "delay": d})
                    elif cmd is not None:
                        # 例如 {"command": ["adb", "devices"]}：类型不对，跳过并告警，
                        # 而不是让 .strip() 抛 AttributeError 把整次加载带崩。
                        warnings.append(
                            "命令「%s」第 %d 个子项的 command 不是字符串（实际：%s），已跳过"
                            % (name, j + 1, type(cmd).__name__))
                else:
                    warnings.append("命令「%s」第 %d 个子项格式无法识别，已跳过"
                                    % (name, j + 1))
        # raw_cmds 为 None / 其他类型时不报错，交给下方"空命令"判断

        if not entries:
            warnings.append("命令「%s」未解析到任何可执行命令，已跳过" % name)
            continue

        try:
            clicks = int(c.get("clickCount", 0) or 0)
        except Exception:
            clicks = 0

        # inputOnly：electerm 的「仅输入」标记 —— 点击命令卡片时只把命令文本
        # 填进指令输入框，由用户确认后手动「执行」，不直接下发。缺省 / 类型
        # 不对都按 False 处理（容错，见 normalize_commands 的健壮性约束）。
        input_only = _as_bool(c.get("inputOnly"))

        out.append({
            "id": cid, "name": name,
            "labels": labels, "commands": entries,
            # 使用频次（用于前端「常用命令靠前」排序；点击后由后端回写）
            "clickCount": clicks,
            # electerm 仅输入模式：True 时点击只填入输入框，不直接执行
            "inputOnly": input_only,
        })
    return out, warnings


def _as_bool(v) -> bool:
    """把 JSON 里的各种写法统一成 bool：真 bool 原样；字符串 "true"/"1"/
    "yes" 也认（手写 json 常见）；其余（含 None）一律 False，绝不外抛。"""
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "on")
    if isinstance(v, (int, float)):
        return bool(v)
    return False


def save_click_deltas(deltas):
    """把点击计数增量写回 quick_commands.json（尽力而为，失败静默）。

    读最新文件 -> 按 id 累加 clickCount -> 原样写回。只动 clickCount 字段，
    comments / 分组结构 / 用户手改的任何格式都保留；文件只读或不存在时
    静默放弃（计数是锦上添花，不能因此打扰命令下发）。

    同一 id 出现多次（用户复制粘贴造成）时**只累加到第一条**：旧实现会给每条
    同 id 条目都加一遍，点一次等于点 N 次，把「常用命令靠前」的排序带偏。

    id 比对按 normalize_commands 的归一化规则做（数字 id → 字符串）：用户 json
    里写 `"id": 1`（数字）时，内存态命令的 id 是 "1"，直接拿原始值 1 来比对比不中
    —— 点击计数对这类命令永远写不回文件，「常用靠前」静默失效。
    """
    if not deltas:
        return
    p = primary_command_path()
    try:
        with open(p, encoding="utf-8-sig") as f:
            raw = json.load(f)
    except Exception:
        return
    items = list(raw.values()) if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return
    changed = False
    applied = set()
    for c in items:
        if not isinstance(c, dict):
            continue
        cid = c.get("id")
        # 与 normalize_commands 的 id 归一化保持一致：字符串原样；int/float 转字符串；
        # 其余（bool / None / list …）不可能有对应内存态 id，跳过。
        if isinstance(cid, str):
            key = cid.strip()
        elif isinstance(cid, (int, float)) and not isinstance(cid, bool):
            key = str(cid)
        else:
            key = ""
        if key and key in deltas and key not in applied:
            applied.add(key)
            try:
                old = int(c.get("clickCount", 0) or 0)
            except Exception:
                old = 0
            c["clickCount"] = old + deltas[key]
            changed = True
    if not changed:
        return
    _write_json_atomic(p, raw)


def _write_json_atomic(path, data):
    """原子写 JSON：先写临时文件再 os.replace，避免半个文件覆盖掉用户数据。

    `open(path, "w")` 会先把原文件截断为 0 字节，此时若进程崩溃 / 断电 / 磁盘写满，
    用户的命令文件就变成空文件或半截 JSON —— 下次启动全部回退到内置默认。

    **返回是否真的写成功**（不能吞掉）：调用方 save_user_commands 要把失败如实
    回报给界面。早前这里 catch 后什么都不说，于是「目录只读 / 磁盘满」时界面照样
    弹「✓ 命令已保存（N 条）」，用户下次启动才发现刚改的命令全没了。

    临时文件用**唯一名**：点击计数（防抖 Timer 线程）与界面保存（js_api 线程）
    可能同时落盘，固定 <path>.tmp 会让两个写入流互相截断 —— os.replace 之后
    文件里可能是「半份 A + 半份 B」的坏 JSON，下次启动整份命令库丢失。
    """
    tmp = "%s.%s.tmp" % (path, uuid.uuid4().hex[:8])
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False


def merge_builtins(user_cmds):
    """把内置默认命令并入用户命令列表：用户自定义优先。

    优先级：
      * 同 id —— 用户的精确覆盖内置（便于用户改写某条内置）；
      * 同名（去掉 [标签] 前缀后的核心名相同）—— 用户已有一份等价命令，
        内置被压制，避免重复显示；
      * 其余内置命令补齐，保证程序自带一套通用默认（即使 quick_commands.json
        为空/损坏也能用）。
    返回新列表，不修改入参。

    并入的内置命令统一补齐 `inputOnly=False`（浅拷贝，不动模块级常量）：
    内置命令都是「点一下就执行」的通用指令，不参与 electerm 仅输入模式；
    字段补齐是为了让 booted 载荷里每条命令的键一致（前端无需判 undefined）。
    """
    user_cmds = list(user_cmds)
    user_ids = {c.get("id") for c in user_cmds if isinstance(c, dict)}
    user_cores = {core_name(c.get("name", "")) for c in user_cmds
                  if isinstance(c, dict)}
    out = list(user_cmds)
    for b in BUILTIN_COMMANDS:
        if b.get("id") in user_ids:
            continue
        if core_name(b.get("name", "")) in user_cores:
            continue
        item = dict(b)
        item["inputOnly"] = _as_bool(b.get("inputOnly"))
        out.append(item)
    return out


def load_commands(directory=None):
    """扫描运行目录下的命令合集文件，合并去重后并入内置默认命令。

    - 目录里的 *.json（除去 config.json 等非命令文件）只要顶层是数组 / 对象且能
      解析，都当作命令合集：多份则合并 + 去重（见 discover_commands）。
    - 一份有效文件都没有时，在运行目录生成 commands.json（预置示例）后再加载。
    - 最终把内置默认命令并入（用户自定义优先、内置兜底），返回 (commands, warnings)。

    健壮性：任何读取 / 解析失败都只记 warning，绝不让 boot 抛出去（否则程序启动后
    一条命令都没有、界面只显示「未就绪」）。文件按 utf-8-sig 读，兼容记事本 BOM。
    """
    try:
        cmds, warnings, _files = discover_commands(directory or command_scan_dir())
    except Exception as ex:
        return merge_builtins([]), [
            "快捷命令加载出现异常：%s（已回退到内置默认）" % ex]
    if not cmds:
        return merge_builtins([]), warnings + [
            "未解析到任何用户命令，已回退到内置默认"]
    return merge_builtins(cmds), warnings


def save_user_commands(commands):
    """把（前端维护的）用户命令列表整体写回命令合集文件（原子写）。

    写入目标由 primary_command_path 决定：优先 commands.json，其次历史
    quick_commands.json（两者都不存在则创建 commands.json）。

    只写用户自定义命令，不写内置默认——内置由 merge_builtins 在加载时补齐，
    写进文件只会制造两份重复、且下次 merge 时按 id/同名压制，反而把内置
    的角标语义弄丢。commands 来源是前端归一化后的结构（id/name/labels/
    commands/clickCount/inputOnly），直接 dump 即保持文件既有格式（list），
    避免下次启动又被 load_commands 重新归一化掉格式。

    返回 (ok, 错误文本)：写盘失败必须让界面知道（只读目录 / 磁盘满 / 文件被
    占用都是真实场景），否则「已保存」的提示与磁盘上的旧内容互相矛盾。
    """
    p = primary_command_path()
    if _write_json_atomic(p, commands or []):
        return True, None
    return False, "无法写入 %s（目录只读 / 磁盘空间不足 / 文件被占用？）" % p
