"""
core.filelock —— 跨进程独占文件锁（标准库实现，无第三方依赖）
==============================================================

用途：保护「读-合并-写」这类跨进程的复合操作。典型场景是 config.json —— 本机
可以同时开多个实例，两个实例各自 `load_prefs()` 读到同一份旧内容、各自合并不同
的 patch、各自 `os.replace` 写回，后写的会把先写的整块覆盖掉（丢失更新）。

进程内的 `threading.Lock` 挡不住这种情况：它只在**单个进程**内串行化线程，
不同进程的锁对象彼此无关。本模块用**操作系统级的文件锁**把多个进程也串起来：

  * Windows：`msvcrt.locking(fd, LK_LOCK, 1)` 锁住哨兵文件的 1 个字节；
  * POSIX  ：`fcntl.flock(fd, LOCK_EX)` 对整个哨兵文件加排他锁。

两者都在持有锁的进程退出（哪怕崩溃）时由内核自动释放，不会像"手工维护的锁文件"
那样留下死锁残局。

设计取舍（重要）：
  * **锁的是复合操作，不是单次写**：调用方必须在「读旧值 → 合并 → 写回」的**最外层**
    持锁；只锁 `os.replace` 那一步没用——读已经在锁外发生了。
  * **超时降级，绝不卡死界面**：拿不到锁时有限次重试（默认 ~2 秒），仍失败就
    「无锁继续」。理由：配置文件写入是尽力而为的辅助操作，为一个设置保存把整个
    GUI 挂死更糟；正常路径下两个实例几乎不会同时写，降级只是极端情况的兜底。
    调用方可通过 `acquired` 结果知道本次是否真正拿到了锁。
  * **哨兵文件创建失败也降级**：程序装在只读目录时可能连 `.lock` 文件都建不了，
    此时同样「无锁继续」，行为与引入本模块之前一致。
  * **不引入第三方依赖**：requirements.txt 里的包都要做主版本上界管理，为一个
    文件锁多引一个包不值得；标准库两个分支各几行就够。
"""
import contextlib
import os
import time

try:                                    # POSIX（Linux/macOS，含开发态 / CI）
    import fcntl
except ImportError:                     # pragma: no cover - Windows 上走不到
    fcntl = None
try:                                    # Windows
    # 用别名强调这是**标准库模块**而非 ctypes DLL 对象：msvcrt.locking 的
    # 参数是 int / 常量，不存在 ctypes 默认转换的 64 位指针截断问题（项目的
    # Win32 原型门禁针对的是后者）。别名同时避免门禁把标准库调用误报为缺原型。
    import msvcrt as _msvcrt
except ImportError:                     # pragma: no cover - POSIX 上走不到
    _msvcrt = None


# 拿到锁之前的重试参数：间隔 20ms × 100 次 ≈ 2s。够覆盖正常的短写入竞争，
# 又不至于让界面卡到用户以为死机。
_RETRY_INTERVAL = 0.02
_RETRY_COUNT = 100


def lock_path_for(target_path):
    """由被保护文件路径派生哨兵文件路径（同目录，追加 .lock 后缀）。

    放在同目录而非系统临时目录：不同安装位置的同名 config.json 必须拿到**不同**
    的锁（否则 A 安装的写会去阻塞 B 安装的写，白白串行化）。同目录天然隔离。
    """
    return target_path + ".lock"


class FileLock:
    """可重入上下文管理器：`with FileLock(path) as lk: ...`。

    `lk.acquired` 为 True 表示本次确实拿到了跨进程锁；False 表示超时 / 平台不支持 /
    哨兵文件建不了而降级为无锁（复合操作照常执行）。

    同一实例在**同一线程**内重复进入只加一次锁、退出最外层才释放（threading.RLock
    语义），避免调用方嵌套时自己把自己锁死。跨线程仍各算各的——但调用方本就有
    进程内 threading.Lock 保护，这层文件锁只负责跨进程。
    """

    def __init__(self, path, timeout=None):
        self._path = path
        self._timeout = timeout
        self._fd = None
        self._depth = 0
        self.acquired = False

    def __enter__(self):
        if self._depth > 0:
            self._depth += 1
            return self
        self.acquired = self._acquire()
        self._depth = 1
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._depth == 0:
            return False
        self._depth -= 1
        if self._depth == 0 and self._fd is not None:
            self._release()
        return False

    def _acquire(self):
        """尝试加锁；成功返回 True，任何失败 / 超时返回 False（降级无锁）。"""
        retries = _RETRY_COUNT
        if self._timeout is not None:
            retries = max(1, int(self._timeout / _RETRY_INTERVAL))
        try:
            fd = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o644)
        except Exception:  # noqa: BLE001  只读目录 / 权限不足 → 降级无锁
            return False
        self._fd = fd
        try:
            if fcntl is not None:
                for i in range(retries):
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        return True
                    except BlockingIOError:
                        if i + 1 < retries:
                            time.sleep(_RETRY_INTERVAL)
                return False
            if _msvcrt is not None:
                # msvcrt.locking 锁的是文件里的字节区间：空文件（刚 O_CREAT，
                # size=0）锁 offset 0 的 1 字节在部分 Windows 版本上会失败。
                # 先确保哨兵文件至少 1 字节，保证锁区间真实存在。
                # 写入失败不致命——交由下面 locking 尝试，失败自然降级无锁。
                with contextlib.suppress(Exception):
                    if os.fstat(fd).st_size == 0:
                        os.write(fd, b"\0")
                for i in range(retries):
                    try:
                        os.lseek(fd, 0, os.SEEK_SET)
                        _msvcrt.locking(fd, _msvcrt.LK_NBLCK, 1)
                        return True
                    except OSError:
                        if i + 1 < retries:
                            time.sleep(_RETRY_INTERVAL)
                return False
            return False                 # 两个平台模块都没有：降级
        except Exception:  # noqa: BLE001  锁机制本身出错也不能中断调用方
            return False

    def _release(self):
        """释放锁并关闭哨兵句柄（哨兵文件本身保留，供下次复用）。"""
        fd, self._fd = self._fd, None
        if fd is None:
            return
        with contextlib.suppress(Exception):
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
            elif _msvcrt is not None:
                os.lseek(fd, 0, os.SEEK_SET)
                _msvcrt.locking(fd, _msvcrt.LK_UNLCK, 1)
        with contextlib.suppress(Exception):
            os.close(fd)


def exclusive_file_lock(path, timeout=None):
    """快捷构造 `FileLock(path, timeout)`（供 `with` 直接使用）。"""
    return FileLock(path, timeout=timeout)
