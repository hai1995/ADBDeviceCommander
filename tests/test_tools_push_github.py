# -*- coding: utf-8 -*-
"""tools/push_github.py（源码推送 GitHub）的单元测试。

这个脚本的价值全在「安全」和「别骗人」两件事上，所以测试也压在这两点：
  * token 绝不能出现在 remote URL、命令行回显、报错文本里；
  * 提示里的「多少个文件」「提交了什么」必须与真实情况一致。
"""
import base64
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import push_github as pg  # noqa: E402

TOKEN = "github_pat_TESTONLY_abcdefghijklmnopqrstuvwxyz0123456789"


# --------------------------------------------------------------------------- #
# 凭证读取：优先级与容错
# --------------------------------------------------------------------------- #
def _cred(tmp_path, content):
    p = tmp_path / ".git-credential"
    p.write_text(content, encoding="utf-8")
    return p


def test_token_from_cli_wins_over_everything(tmp_path, monkeypatch):
    monkeypatch.setattr(pg, "CRED_FILE", _cred(tmp_path, '{"token":"from-file"}'))
    monkeypatch.setenv("GH_TOKEN", "from-env")
    tok, src, err = pg.load_token("from-cli")
    assert (tok, err) == ("from-cli", "")
    assert "命令行" in src


def test_token_from_env_before_file(tmp_path, monkeypatch):
    monkeypatch.setattr(pg, "CRED_FILE", _cred(tmp_path, '{"token":"from-file"}'))
    monkeypatch.setenv("GH_TOKEN", "from-env")
    tok, src, _ = pg.load_token()
    assert tok == "from-env" and "GH_TOKEN" in src


def test_token_falls_back_to_second_env_name(tmp_path, monkeypatch):
    """GH_TOKEN 没设时还要认 GITHUB_TOKEN（GitHub Actions 里用后者）。"""
    monkeypatch.setattr(pg, "CRED_FILE", tmp_path / "nope")
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "from-gh-actions")
    tok, src, _ = pg.load_token()
    assert tok == "from-gh-actions" and "GITHUB_TOKEN" in src


def test_token_file_accepts_json(tmp_path, monkeypatch):
    monkeypatch.setattr(pg, "CRED_FILE", _cred(tmp_path, json.dumps({"token": TOKEN})))
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert pg.load_token()[0] == TOKEN


def test_token_file_accepts_bare_line(tmp_path, monkeypatch):
    """直接放一行裸 token 也要能用（手写文件时最省事的写法）。"""
    monkeypatch.setattr(pg, "CRED_FILE", _cred(tmp_path, TOKEN + "\n"))
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert pg.load_token()[0] == TOKEN


def test_broken_json_credential_explains_how_to_fix(tmp_path, monkeypatch):
    """文件写坏了要说清正确格式，而不是抛个 JSONDecodeError 给用户看。"""
    monkeypatch.setattr(pg, "CRED_FILE", _cred(tmp_path, "{token: 没引号}"))
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    tok, _src, err = pg.load_token()
    assert tok == ""
    assert "合法 JSON" in err and "token" in err


def test_missing_credential_tells_where_to_put_it(tmp_path, monkeypatch):
    monkeypatch.setattr(pg, "CRED_FILE", tmp_path / "absent")
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    tok, _src, err = pg.load_token()
    assert tok == ""
    assert "GH_TOKEN" in err and ".git-credential" in err
    assert "gitignore" in err, "要说明这个文件已被忽略，否则用户不敢写"


def test_saved_credential_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(pg, "CRED_FILE", tmp_path / ".git-credential")
    pg.save_token(TOKEN)
    assert json.loads(pg.CRED_FILE.read_text(encoding="utf-8"))["token"] == TOKEN
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert pg.load_token()[0] == TOKEN


# --------------------------------------------------------------------------- #
# 打码与认证头：token 不能漏
# --------------------------------------------------------------------------- #
def test_mask_never_reveals_full_token():
    m = pg._mask(TOKEN)
    assert TOKEN not in m
    assert m.endswith(TOKEN[-4:]) or m.endswith("）"), m
    assert pg._mask("") == "(空)"


def test_auth_header_is_basic_and_contains_no_plaintext():
    h = pg._auth_header(TOKEN)
    assert h.startswith("http.extraHeader=Authorization: Basic ")
    assert TOKEN not in h, "认证头里不能出现 token 明文"
    raw = base64.b64decode(h.split("Basic ", 1)[1]).decode()
    assert raw == "x-access-token:%s" % TOKEN


def test_push_url_stays_clean(monkeypatch, tmp_path, capsys):
    """核心安全断言：推出去的 URL 必须是干净地址，token 只在认证头里。"""
    monkeypatch.setattr(pg, "CRED_FILE", _cred(tmp_path, json.dumps({"token": TOKEN})))
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    calls = _stub_git(monkeypatch)

    assert pg.main([]) == 0

    push = [c for c in calls if "push" in c]
    assert len(push) == 1, calls
    joined = " ".join(push[0])
    assert TOKEN not in joined, "token 不能进 URL"
    assert "--token-string" not in joined
    assert "@github.com" not in joined, "URL 里不能带 user:token@"
    assert "http.extraHeader=Authorization: Basic " in joined

    out = capsys.readouterr().out
    assert TOKEN not in out, "控制台回显里不能出现 token"


# --------------------------------------------------------------------------- #
# 提交说明与状态
# --------------------------------------------------------------------------- #
def test_auto_message_names_the_areas_touched():
    msg = pg._auto_message([(" M", "core/apk.py"), (" M", "frontend/js/app.js"),
                            ("??", "tests/x.py")])
    assert "core" in msg and "frontend" in msg and "tests" in msg
    assert "3 个文件" in msg


def test_auto_message_dedupes_areas():
    msg = pg._auto_message([(" M", "core/a.py"), (" M", "core/b.py"),
                            (" M", "core/c.py")])
    assert msg.count("core") == 1, msg
    assert "3 个文件" in msg


def test_auto_message_without_changes_is_neutral():
    assert pg._auto_message([]) == "同步"


def test_repo_state_skips_credential_file(monkeypatch):
    """凭证一旦被误 add 进去，也不该出现在「将要提交」的清单里。"""
    _stub_git(monkeypatch, status_lines="?? .git-credential\n M core/a.py\n")
    monkeypatch.setattr(pg, "_has_git_repo", lambda: True)
    _branch, items = pg.repo_state()
    paths = [p for _c, p in items]
    assert "core/a.py" in paths
    assert ".git-credential" not in paths


def test_status_works_without_any_token(monkeypatch, tmp_path, capsys):
    """--status 只读本地状态，不该因为没配 token 就拒绝工作。"""
    monkeypatch.setattr(pg, "CRED_FILE", tmp_path / "absent")
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(pg, "_has_git_repo", lambda: True)
    _stub_git(monkeypatch, status_lines=" M core/a.py\n")
    assert pg.main(["--status"]) == 0
    out = capsys.readouterr().out
    assert "1 个文件有改动" in out and "core/a.py" in out


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def _stub_git(monkeypatch, status_lines=" M core/a.py\n", push_rc=0,
              push_out="", commit_rc=0, commit_out=""):
    """把 git 调用换成记录器，返回被调用过的参数列表。"""
    calls = []

    def fake_run(args, timeout=180, check=False):
        calls.append(list(args))
        joined = " ".join(args)
        if "status" in args:
            return 0, status_lines
        if "rev-parse" in args and "--abbrev-ref" in args:
            return 0, "main\n"
        if "symbolic-ref" in args:
            return 0, "main\n"
        if "remote" in args and "get-url" in args:
            return 0, pg.DEFAULT_REMOTE + "\n"
        if "config" in args and "user.email" in args:
            return 0, "someone@example.com\n"
        if "commit" in args:
            return commit_rc, commit_out or "[main abc1234] ok\n"
        if "push" in args:
            return push_rc, push_out
        if "rev-parse" in args and "--short" in args:
            return 0, "abc1234\n"
        if "log" in args:
            return 0, "提交说明\n"
        if "init" in args or "add" in args:
            return 0, ""
        if "status" in joined:
            return 0, status_lines
        return 0, ""

    monkeypatch.setattr(pg, "_run", fake_run)
    monkeypatch.setattr(pg, "_has_git_repo", lambda: True)
    return calls


def _subcommands(calls):
    """从记录下来的参数里取出真正的 git 子命令。

    `_git` 会把 `-c key=value` 插在子命令之前（认证头就是这么传的），
    所以不能简单取 args[1] —— 那样只会拿到一串 `-c`。
    """
    out = []
    for c in calls:
        a = list(c)[1:]                 # 去掉开头的 "git"
        i = 0
        while i < len(a) and a[i] == "-c":
            i += 2
        if i < len(a):
            out.append(a[i])
    return out


def test_commit_and_push_happen_in_order(monkeypatch, tmp_path):
    monkeypatch.setattr(pg, "CRED_FILE", _cred(tmp_path, json.dumps({"token": TOKEN})))
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    calls = _stub_git(monkeypatch)

    assert pg.main(["-m", "修个 bug"]) == 0

    kinds = _subcommands(calls)
    assert "add" in kinds and "commit" in kinds and "push" in kinds
    assert kinds.index("add") < kinds.index("commit") < kinds.index("push")
    commit = [c for c in calls if "commit" in c][0]
    assert commit[commit.index("-m") + 1] == "修个 bug"


def test_no_changes_still_pushes_without_commit(monkeypatch, tmp_path):
    """工作区干净时不该硬造一个空提交，但推送要照做（也许上次推送失败了）。"""
    monkeypatch.setattr(pg, "CRED_FILE", _cred(tmp_path, json.dumps({"token": TOKEN})))
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    calls = _stub_git(monkeypatch, status_lines="")

    assert pg.main([]) == 0

    kinds = _subcommands(calls)
    assert "commit" not in kinds, "干净工作区不该 commit"
    assert "push" in kinds


def test_push_failure_returns_nonzero_and_masks_token(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(pg, "CRED_FILE", _cred(tmp_path, json.dumps({"token": TOKEN})))
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    # 模拟 git 把 token 吐回错误信息（真实场景：某些版本会回显认证头）
    _stub_git(monkeypatch, push_rc=128, push_out="fatal: Authentication failed for token %s" % TOKEN)

    assert pg.main([]) == 1
    out = capsys.readouterr().out
    assert TOKEN not in out, "报错里必须打码"
    assert "***" in out


@pytest.mark.parametrize("raw,hint", [
    ("remote: Invalid username or password.", "token 无效或已过期"),
    ("fatal: unable to access: The requested URL returned error: 403", "权限不足"),
    ("fatal: unable to access: Could not resolve host: github.com", "网络问题"),
    ("! [rejected] main -> main (non-fast-forward)", "git pull --rebase"),
    ("error: src refspec main does not match any", "还没有任何提交"),
    ("something totally unexpected", "未归类的失败"),
])
def test_push_failure_hints(raw, hint, capsys):
    pg._explain_push_failure(raw, TOKEN)
    out = capsys.readouterr().out
    assert hint in out, out


def test_push_failure_explains_private_repo_permission(monkeypatch, tmp_path, capsys):
    """私有仓库最常见的失败是 token 没勾 Contents 写权限，提示要说到点上。"""
    monkeypatch.setattr(pg, "CRED_FILE", _cred(tmp_path, json.dumps({"token": TOKEN})))
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    _stub_git(monkeypatch, push_rc=128, push_out="remote: Permission to x denied (403)")
    pg.main([])
    out = capsys.readouterr().out
    assert "Contents: Read and write" in out


def test_dry_run_does_not_touch_remote(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(pg, "CRED_FILE", _cred(tmp_path, json.dumps({"token": TOKEN})))
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    calls = _stub_git(monkeypatch)

    assert pg.main(["--dry-run"]) == 0

    kinds = _subcommands(calls)
    assert "add" not in kinds and "commit" not in kinds and "push" not in kinds
    out = capsys.readouterr().out
    assert "将执行" in out and TOKEN not in out


# --------------------------------------------------------------------------- #
# 与真仓库的一致性：文档登记过的远端必须和脚本里的一致
# --------------------------------------------------------------------------- #
def test_default_remote_points_at_expected_repo():
    assert pg.DEFAULT_REMOTE == "https://github.com/hai1995/ADBDeviceCommander.git"
    assert pg.BRANCH == "main"


def test_gitignore_covers_credential_and_runtime_config():
    """凭证与运行时配置必须在 .gitignore 里，否则一次 `git add -A` 就泄。"""
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pat in (".git-credential", "config.json", "*.wav"):
        assert pat in text, posix_msg(pat)


def posix_msg(pat):
    return ".gitignore 缺少 %s：这条不写，一次 git add -A 就会把它带进仓库" % pat
