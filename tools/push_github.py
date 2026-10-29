# -*- coding: utf-8 -*-
"""把源码推送到 GitHub（一条命令完成 提交 + 推送）。

为什么要单独写这个脚本
----------------------
直接 `git push` 有两个坑，这里逐条堵掉：

1. **token 不能落进版本库**。常见做法是把 token 写进 remote URL
   （`https://user:token@github.com/...`），但那样 token 会明文躺在 `.git/config`，
   而且 `git push` 出错时会把**整条 URL 连同 token** 打回控制台 —— 随手截图发群里就泄了。
   这里改用 `http.extraHeader` 只在**本次命令**注入认证头，remote 保持干净 URL，
   git 回显与报错里都不会出现 token。

2. **凭证要有固定的读取顺序**，否则换台机器就得改代码。优先级：
     命令行 --token  >  环境变量 GH_TOKEN / GITHUB_TOKEN  >  .git-credential 文件
   `.git-credential` 放在工程根、已在 .gitignore 里，内容是一行 JSON：
      {"token": "github_pat_xxx"}
   之所以还要支持环境变量：CI / 临时机器上不该为推一次代码就在磁盘留一份凭证。

用法
----
    python tools/push_github.py                  # 有改动就提交（消息自动生成）并推送
    python tools/push_github.py -m "修菜单层叠"   # 指定提交说明
    python tools/push_github.py --status         # 只看状态，不动仓库
    python tools/push_github.py --init           # 首次：git init + 首次提交 + 关联远端 + 推送
    python tools/push_github.py --dry-run        # 只打印将要执行的步骤

首次使用前先填一次凭证（只需一次）：

    echo {"token":"github_pat_xxx"} > .git-credential      # Windows 用 PowerShell 写

退出码：0 成功（含「没有改动，已是最新」）；1 失败（原因会打在最后一行）。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_REMOTE = "https://github.com/hai1995/ADBDeviceCommander.git"
BRANCH = "main"
CRED_FILE = ROOT / ".git-credential"

# 这些目录/文件不需要参与「是否有改动」的判断（即使被误加进暂存区也不该提交）
NEVER_COMMIT = (".git-credential", ".git-push-log.txt")


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def _out(text=""):
    try:
        print(text, flush=True)
    except UnicodeEncodeError:          # Windows 控制台 GBK 下的兜底
        print(text.encode("utf-8", "replace").decode("gbk", "replace"), flush=True)


def _run(args, timeout=180, check=False):
    """跑一条命令，返回 (returncode, 合并后的输出)。不抛异常。"""
    try:
        p = subprocess.run(args, cwd=str(ROOT), capture_output=True,
                           timeout=timeout)
    except FileNotFoundError:
        return 127, "找不到命令：%s（Git 是否已安装并加入 PATH？）" % args[0]
    except subprocess.TimeoutExpired:
        return 124, "命令超时（%ds）：%s" % (timeout, " ".join(args[:3]))
    txt = (p.stdout or b"").decode("utf-8", "replace") + \
          (p.stderr or b"").decode("utf-8", "replace")
    if check and p.returncode != 0:
        raise RuntimeError(txt.strip())
    return p.returncode, txt


def _git(*args, **kw):
    return _run(["git"] + list(args), **kw)


def _has_git_repo():
    return (ROOT / ".git").is_dir()


def _mask(tok):
    """只露头尾，用于确认「读到的是哪一个 token」。"""
    if not tok:
        return "(空)"
    if len(tok) <= 12:
        return tok[:2] + "*" * (len(tok) - 2)
    return "%s…%s（%d 位）" % (tok[:10], tok[-4:], len(tok))


# --------------------------------------------------------------------------- #
# 凭证
# --------------------------------------------------------------------------- #
def load_token(explicit=""):
    """按优先级读 token，返回 (token, 来源说明, 错误)。"""
    if explicit:
        return explicit.strip(), "命令行 --token", ""
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        v = os.environ.get(name, "").strip()
        if v:
            return v, "环境变量 %s" % name, ""
    if CRED_FILE.is_file():
        try:
            raw = CRED_FILE.read_text(encoding="utf-8").strip()
        except OSError as e:
            return "", "", "读不了 .git-credential：%s" % e
        tok = ""
        if raw.startswith("{"):
            try:
                tok = str(json.loads(raw).get("token", "")).strip()
            except ValueError:
                return "", "", ".git-credential 不是合法 JSON（应形如 {\"token\":\"…\"}）"
        else:
            tok = raw                      # 允许直接放一行裸 token
        if tok:
            return tok, ".git-credential", ""
        return "", "", ".git-credential 里没有 token 字段"
    return "", "", ("没有找到凭证：请设置环境变量 GH_TOKEN，或在工程根写 .git-credential"
                    "（内容 {\"token\":\"github_pat_…\"}，该文件已在 .gitignore 里）")


def save_token(tok):
    """把 token 写进 .git-credential（已 gitignore）。"""
    CRED_FILE.write_text(json.dumps({"token": tok.strip()}) + "\n", encoding="utf-8")
    try:
        os.chmod(CRED_FILE, 0o600)
    except OSError:
        pass                            # Windows 上 chmod 无意义，忽略


def _auth_header(tok):
    """GitHub 的 git-over-https 走 Basic 认证：用户名任意，token 当密码。"""
    pair = ("x-access-token:%s" % tok).encode("utf-8")
    return "http.extraHeader=Authorization: Basic %s" % base64.b64encode(pair).decode()


# --------------------------------------------------------------------------- #
# 仓库状态
# --------------------------------------------------------------------------- #
def repo_state():
    """返回 (分支名, [(状态码, 路径), …] 变更列表)。非仓库返回 ('', [])。"""
    if not _has_git_repo():
        return "", []
    _rc, br = _git("rev-parse", "--abbrev-ref", "HEAD")
    if _rc != 0 or not br.strip():
        # 还没有第一个提交（unborn branch）时 rev-parse 会失败，
        # 但 symbolic-ref 是能读出来的——否则会显示成「分支：(未知)」，
        # 看着像仓库坏了，其实只是还没初始化好第一个提交。
        rc2, br2 = _git("symbolic-ref", "--short", "HEAD")
        br = br2 if rc2 == 0 else ""
    branch = br.strip() if br else ""
    # -uall：未跟踪的目录默认会被折叠成一行（`?? frontend/`），
    # 那样「将有 15 项改动」实际是 15 个顶层目录、底下上百个文件，
    # 提示里的数字会骗人。展开到文件级别才对得上。
    _rc, out = _git("status", "--porcelain", "-uall")
    items = []
    for line in out.splitlines():
        if not line.strip():
            continue
        code, path = line[:2], line[3:].strip()
        if any(path.endswith(n) or path == n for n in NEVER_COMMIT):
            continue
        items.append((code, path))
    return branch, items


def remote_url():
    rc, out = _git("remote", "get-url", "origin")
    return out.strip() if rc == 0 else ""


def _ensure_remote(url):
    cur = remote_url()
    if cur == url:
        return True, "远端已是 %s" % url
    if cur:
        _git("remote", "set-url", "origin", url)
        return True, "远端改指 %s（原 %s）" % (url, cur)
    _git("remote", "add", "origin", url)
    return True, "已添加远端 %s" % url


def _ensure_identity():
    """没配 user.name / user.email 时给一份工程内默认值，避免 commit 直接失败。"""
    rc, out = _git("config", "user.email")
    if rc != 0 or not out.strip():
        _git("config", "user.email", "44248555+hai1995@users.noreply.github.com")
        _git("config", "user.name", "hai1995")
        return "已设工程内 git 身份（hai1995）"
    return ""


def _auto_message(items):
    """按改动文件自动生成一句能看懂的提交说明。"""
    n = len(items)
    if not n:
        return "同步"
    # 尽量点出改了什么区域，而不是干巴巴一句「更新」
    areas = []
    for _code, path in items:
        if path.startswith("core/"):
            areas.append("core")
        elif path.startswith("backend/"):
            areas.append("backend")
        elif path.startswith("frontend/"):
            areas.append("frontend")
        elif path.startswith("tests/"):
            areas.append("tests")
        elif path.startswith("tools/") or path in ("build.py", "main.py", "adb_inject.py"):
            areas.append("工具/入口")
        elif path.endswith(".md") or path.endswith(".txt"):
            areas.append("文档")
    seen = []
    for a in areas:
        if a not in seen:
            seen.append(a)
    head = "、".join(seen) if seen else "杂项"
    return "更新 %s（%d 个文件）" % (head, n)


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def do_init(url):
    """首次：git init + 身份 + 远端。返回 (ok, 说明列表)。"""
    logs = []
    if _has_git_repo():
        logs.append("仓库已存在，跳过 git init")
    else:
        rc, out = _git("init", "-b", BRANCH)
        if rc != 0:                     # 老版本 git 不认 -b
            _git("init")
            _git("checkout", "-b", BRANCH)
        logs.append("已初始化仓库（分支 %s）" % BRANCH)
    ident = _ensure_identity()
    if ident:
        logs.append(ident)
    ok, msg = _ensure_remote(url)
    logs.append(msg)
    return ok, logs


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="提交并推送源码到 GitHub（token 不进版本库、不进命令行回显）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-m", "--message", default="", help="提交说明；留空则按改动文件自动生成")
    ap.add_argument("--init", action="store_true", help="首次初始化仓库并关联远端")
    ap.add_argument("--remote", default=DEFAULT_REMOTE, help="远端地址（默认 %s）" % DEFAULT_REMOTE)
    ap.add_argument("--branch", default=BRANCH, help="分支名（默认 %s）" % BRANCH)
    ap.add_argument("--status", action="store_true", help="只打印状态，不做任何改动")
    ap.add_argument("--dry-run", action="store_true", help="打印将要执行的步骤，不真正提交/推送")
    ap.add_argument("--token", default="", help="直接给 token（会出现在 shell 历史里，不推荐）")
    ap.add_argument("--save-token", action="store_true",
                    help="把读到的 token 写入 .git-credential（已 gitignore），下次免填")
    args = ap.parse_args(argv)

    _out("工程目录：%s" % ROOT)

    # ---- --status：只看状态，连 token 都不需要 ----
    if args.status:
        if not _has_git_repo():
            _out("状态：尚未初始化（用 --init）")
            return 0
        branch, items = repo_state()
        _out("分支：%s" % (branch or "(未知)"))
        _out("远端：%s" % (remote_url() or "(未设置)"))
        if not items:
            _out("工作区：干净，没有待提交的改动")
        else:
            _out("工作区：%d 个文件有改动" % len(items))
            for code, path in items[:30]:
                _out("  %s %s" % (code, path))
            if len(items) > 30:
                _out("  … 另 %d 个" % (len(items) - 30))
        return 0

    tok, src, err = load_token(args.token)
    if not tok:
        _out("✗ %s" % err)
        return 1
    _out("凭证来源：%s，token %s" % (src, _mask(tok)))
    if args.save_token and src != ".git-credential":
        save_token(tok)
        _out("已写入 %s（该文件已被 .gitignore 排除）" % CRED_FILE.name)

    steps = []
    # ---- 初始化 ----
    if args.init or not _has_git_repo():
        ok, logs = do_init(args.remote)
        steps.extend(logs)
        if not ok:
            _out("✗ 初始化失败")
            return 1
    elif remote_url() != args.remote:
        _ok, msg = _ensure_remote(args.remote)
        steps.append(msg)

    if not _has_git_repo():
        _out("✗ 初始化后仍找不到 .git，已中止")
        return 1
    ident = _ensure_identity()
    if ident:
        steps.append(ident)

    # ---- 提交 ----
    _branch, items = repo_state()
    committed = False
    if items:
        msg = args.message or _auto_message(items)
        if args.dry_run:
            steps.append("将提交 %d 个文件：%s" % (len(items), msg))
        else:
            rc, out = _git("add", "-A")
            if rc != 0:
                _out("✗ git add 失败：%s" % out.strip()[:300])
                return 1
            rc, out = _git("commit", "-m", msg)
            if rc != 0:
                low = out.lower()
                if "nothing to commit" in low or "无文件要提交" in out:
                    steps.append("改动都被忽略规则过滤了，无需提交")
                else:
                    _out("✗ git commit 失败：%s" % out.strip()[:400])
                    return 1
            else:
                steps.append("已提交 %d 个文件：%s" % (len(items), msg))
                committed = True
    else:
        steps.append("工作区干净，无需提交")

    # ---- 推送 ----
    push_args = ["-c", _auth_header(tok), "push", "-u", "origin", args.branch]
    if args.dry_run:
        steps.append("将执行：git push -u origin %s（认证头仅本次有效）" % args.branch)
        for s in steps:
            _out("· %s" % s)
        return 0

    rc, out = _git(*push_args, timeout=300)
    if rc != 0:
        _out("\n".join("· %s" % s for s in steps))
        _out("✗ 推送失败（退出码 %d）" % rc)
        _explain_push_failure(out, tok)
        return 1

    rc2, hash_ = _git("rev-parse", "--short", "HEAD")
    subject = ""
    if rc2 == 0:
        _rc3, s = _git("log", "-1", "--pretty=%s")
        subject = s.strip()
    steps.append("已推送 %s → %s（%s）" % (hash_.strip(), args.branch, remote_url()))
    for s in steps:
        _out("· %s" % s)
    if committed and subject:
        _out("最近提交：%s" % subject)
    _out("✓ 完成")
    return 0


def _explain_push_failure(out, tok):
    """把常见失败翻译成「下一步做什么」，而不是甩一坨 git 原文。"""
    low = out.lower()
    safe = out.replace(tok, "***") if tok else out     # 兜底：任何情况下不留 token
    hints = []
    if "authentication failed" in low or "401" in low or "bad credentials" in low:
        hints.append("token 无效或已过期。到 GitHub → Settings → Developer settings → "
                     "Personal access tokens 重新生成，然后更新 .git-credential。")
    elif "403" in low or "permission" in low or "denied" in low:
        hints.append("token 权限不足。这个仓库是私有的，token 必须勾上 "
                     "Contents: Read and write（细粒度 token 还要把该仓库加进 "
                     "Repository access 白名单）。")
    elif "could not resolve host" in low or "failed to connect" in low or "timed out" in low:
        hints.append("网络问题：连不上 github.com。检查代理 / 防火墙，"
                     "或在能上网的机器上再推一次。")
    elif "non-fast-forward" in low or "rejected" in low or "fetch first" in low:
        hints.append("远端有本地没有的提交。先 `git pull --rebase origin %s` 再推。" % BRANCH)
    elif "src refspec" in low or "does not match any" in low:
        hints.append("本地还没有任何提交。先确认有改动被提交（`--status` 看一下）。")
    else:
        hints.append("未归类的失败，原始输出见上（已把 token 打码）。")
    for h in hints:
        _out("  → %s" % h)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        _out("\n已中断")
        sys.exit(130)
