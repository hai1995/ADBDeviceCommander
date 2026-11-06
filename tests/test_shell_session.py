# -*- coding: utf-8 -*-
"""core.shell.ShellSession 的端到端行为（用 sh 顶替 powershell）。

为什么用 sh 跑：Linux 测试机上没有 powershell，但**出问题的那套机制与 shell
种类无关**——持久会话逐行读 stdin，靠一行「结束标记」判断命令跑完；一旦序列里
出现裸子 shell（powershell / cmd / bash / sh 都算），内层进程就会抢走同一个
stdin：

  1. 后面每条命令连同调用方写入的结束标记都被内层读走，外层收不到；
  2. `exit` 那一行内层读走后直接退出，stdio 缓冲里预读的结束标记一并丢弃
     ——外层从阻塞返回后再也等不到标记，`run()` 只能永远挂着。

第 2 条正是用户报的「执行那条设备指令序列后整程序卡死」的成因：卡住的是持有
执行锁的 worker，后续命令全部排队。这里用 sh 把这条链路真实跑一遍。
"""
import sys
import time

import pytest

from core.shell import ShellSession, _kill_tree


class ShSession(ShellSession):
    """把会话程序换成 sh 的 ShellSession：其余逻辑（读线程 / sentinel / kill）全用真的。"""

    @staticmethod
    def _shell_args():
        return ["sh"]

    @staticmethod
    def _init_script():
        return ":"

    @staticmethod
    def _sentinel_stmt(tag):
        return 'echo "%s|done"' % tag


@pytest.fixture
def sess():
    out = []
    s = ShSession(output_callback=out.append)
    s.out_lines = out
    yield s
    try:
        s.kill()
    except Exception:
        pass


def test_plain_command_roundtrip(sess):
    """普通命令：写进去、等到结束标记、输出被捕获。"""
    assert sess.run("echo hello", timeout=5) is True
    assert "hello" in sess.out_lines


def test_interactive_mode_does_not_wait_for_sentinel(sess):
    """直通模式只写不等：返回 True，且把会话标成交互态。

    这里不等是**故意的**：进入子 shell 后写结束标记只会被内层读走，
    等下去就是死等。
    """
    assert sess.run("sh", interactive=True) is True
    assert sess.in_interactive_shell is True


def test_bare_subshell_then_exit_does_not_hang(sess):
    """用户那条序列的核心：裸 powershell → ... → exit。

    修复前 `run("exit")` 永远等不到结束标记（标记被内层预读走了），整条序列
    卡死在第 7 条上。修复后 exit 走直通，且退出后会话能立刻继续用。
    """
    assert sess.run("sh", interactive=True) is True
    assert sess.run("echo inner", interactive=True) is True
    assert sess.run("exit", interactive=True) is True
    sess.leave_interactive()
    # 子进程退出是异步生效的：给一点间隔再写下一条（controller 里也有同样的宽限）
    time.sleep(0.2)
    assert sess.run("echo after", timeout=5) is True
    assert "after" in sess.out_lines
    assert sess.in_interactive_shell is False


def test_sentinel_is_not_written_in_interactive_mode(sess):
    """直通模式绝不能写结束标记。

    写下去的话，`adb shell` 会把 `Write-Output ("__DONE_x__|...")` 当成**设备端
    shell 命令**执行（command not found），而裸 powershell 那边则是标记被内层
    吞掉。两种都是错。
    """
    sess.run("sh", interactive=True)
    sess.run("echo probe", interactive=True)
    time.sleep(0.3)
    assert not any("__DONE_" in line for line in sess.out_lines), sess.out_lines


def test_timeout_returns_false_instead_of_hanging(sess):
    """兜底超时：读 stdin / 长阻塞的命令必须能自己放行。

    没有这层，`run()` 会永久阻塞并占着执行锁，界面就是「卡死、点不动」。
    """
    t0 = time.time()
    assert sess.run("sleep 5", timeout=1) is False
    assert time.time() - t0 < 5, "超时应当及时返回，不能等满 sleep"


def test_session_recovers_after_timeout(sess):
    """超时会把会话杀掉，下一次 run 必须自动重连——否则一次超时就废掉全局。"""
    assert sess.run("sleep 5", timeout=1) is False
    assert sess.run("echo back", timeout=5) is True
    assert "back" in sess.out_lines


def test_timeout_reason_reaches_output_callback(sess):
    """超时原因必须送到 output_callback，不能只丢进没人读的 out_queue。

    生产环境（backend/controllers/base.py）构造会话时一定传 output_callback，
    队列压根没人消费：早前「⏱ 命令执行超过 N 秒」只入队，用户看到指令台输出
    戛然而止，界面上没有任何解释，只能反复重试。
    """
    assert sess.run("sleep 5", timeout=1) is False
    assert any("超过 1 秒" in line for line in sess.out_lines), sess.out_lines


def test_last_error_explains_why_it_failed(sess):
    """失败要给得出原因（供调用方拼提示），且不能被 kill 的「已停止」盖掉。"""
    assert sess.last_error == "", "初始状态不该带失败原因"
    assert sess.run("sleep 5", timeout=1) is False
    assert "超过 1 秒" in sess.last_error, sess.last_error


def test_last_error_cleared_after_success(sess):
    """成功一次就要把上次的失败原因清掉，否则下条命令会背上一轮的锅。"""
    assert sess.run("sleep 5", timeout=1) is False
    assert sess.run("echo ok", timeout=5) is True
    assert sess.last_error == ""


def test_session_death_is_reported_not_silent(sess):
    """会话进程自己没了（被安全软件杀 / 崩溃）时，必须说清是「意外结束」。

    这种情况 run() 返回 False，若只记成笼统的「已被停止」，用户会以为是自己
    误点了停止按钮——真相是 powershell 已经退出并被重建。
    """
    assert sess.run("kill -9 $$", timeout=5) is False
    assert "意外结束" in sess.last_error, sess.last_error


def test_kill_marks_aborted_and_clears_interactive(sess):
    """kill 要同时置中止位、清交互态：前者让等待方立刻让出，后者让停止按钮熄灭。"""
    sess.run("sh", interactive=True)
    assert sess.in_interactive_shell is True
    sess.kill()
    assert sess.aborted is True
    assert sess.in_interactive_shell is False


def test_kill_closes_stdin_pipe(sess):
    """kill 后要显式关闭父侧 stdin。

    进程终止瞬间的写入 flush 失败被吞后，未发出的数据仍压在 TextIOWrapper
    缓冲里；不显式 close 时，GC 回收该文件对象会再 flush 一次，撞上半关闭
    的管道抛 BrokenPipeError —— pytest 标成 PytestUnraisableExceptionWarning。
    stdout 刻意不关：reader 线程还在等旧管道真正 EOF（fd 复用风险）。
    """
    sess.run("sh", interactive=True)
    proc = sess.proc
    sess.kill()
    assert proc.stdin.closed
    assert not proc.stdout.closed


def test_leave_interactive_only_resets_flag(sess):
    """`exit` 只退出内层 shell，外层会话仍在：复位标志即可，不能顺手杀进程。"""
    sess.run("sh", interactive=True)
    sess.leave_interactive()
    assert sess.in_interactive_shell is False
    time.sleep(0.2)
    assert sess.run("echo alive", timeout=5) is True


@pytest.mark.skipif(sys.platform.startswith("win"), reason="非 Windows 上无进程树可杀")
def test_kill_tree_is_noop_off_windows(sess):
    """非 Windows 返回 False，调用方据此回退到普通 terminate。"""
    assert _kill_tree(sess.proc) is False
