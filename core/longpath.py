r"""core.longpath —— Windows 长路径（>260 字符）支持。

为什么需要
----------
Windows 的 MAX_PATH 是 260 个字符（含结尾 NUL），普通 Win32 调用不认更长的
路径 —— 除非路径带 `\\?\` 前缀（Win32 的「设备路径」形式）。本程序把用户的
保存目录、文件名统统交给系统去创建 / 读写，而同事的归档目录动辄长这样：

    D:\\工作\\2026\\客户A\\车机项目\\第二期\\录屏\\20261112_093000\\A1.png

再拼上设备名与时间戳，很容易超过 260。超了之后的症状极其难懂：不是「路径太
长」，而是「系统找不到指定的文件」——用户会去检查文件存不存在、权限够不够，
根本想不到是长度问题。adb 拉取的视频、日志、截图会**静默丢失**（界面上只说
「下载失败」）。

规则（只有一条，但必须守住）
----------------------------
* `long_path()` 只许用在**本进程自己做**的文件 I/O 上（open / os.makedirs /
  os.replace / shutil…）；
* **绝不能**用在交给外部程序的参数上 —— 尤其 `adb pull` / `adb push` 的本地
  路径！adb.exe 不认 `\\?\` 前缀，带上去会被当成一个名字里带反斜杠的怪路径，
  必然失败；
* 也**绝不能**用在展示给用户的字符串里（界面上会显示成 `\\?\D:\\...`，用户
  会以为程序坏了）。

只对**够长**的路径加前缀（阈值见 LONG_PATH_THRESHOLD），短路径原样返回 ——
于是绝大多数路径的行为完全不变，异常信息里也不会冒出看不懂的前缀。

加前缀后不能再对它做 `..` 归一化 / 相对路径解析（Win32 设备路径不认），
所以本模块**只接受完整路径**，调用方必须在最后一步（拿到完整文件名后）才加
前缀，不要给目录加完前缀再往上拼文件名。
"""
from __future__ import annotations

import ntpath
import os

# 加前缀的阈值（字符数）。
#
# Windows 的上限是 260（含结尾 NUL），实际可用 259。这里取 240 而不是更贴近
# 259：调用点里存在「先落临时名、再改名」的写法（config.json.tmp、报告的唯一
# 名后缀等），临时名会比最终名长十几字符；留 20 字符的余量，这些写法才不会
# 「最终名刚好在限内、临时名超限」。
LONG_PATH_THRESHOLD = 240

# Win32 设备路径前缀
_PREFIX = "\\\\?\\"
# UNC 前缀（\\server\share）要写成 \\?\UNC\server\share
_UNC_PREFIX = "\\\\?\\UNC\\"


def _absolute(path: str) -> str:
    """把路径绝对化（消掉 ``..``）。

    绝对路径（带盘符 / UNC）**一律按 Windows 语义**处理（ntpath），而不是
    os.path.abspath —— 后者在非 Windows 上会把 ``C:\\Users\\x`` 拼成
    ``/当前目录/C:\\Users\\x``，于是这个「纯逻辑函数」在不同平台上给出
    不同答案，单测也就没法在 Linux 上验证它的行为。相对路径才用本机规则
    （在 Windows 上运行时就是 Windows 规则）。
    """
    s = str(path)
    try:
        if os.name == "nt":
            # Windows 上用本机规则（走 Win32 的 GetFullPathName，盘符相对路径
            # ``C:foo`` 才会按「该盘符的当前目录」解析，而不是进程 cwd）
            return os.path.abspath(s)
        if ntpath.isabs(s):
            # 非 Windows 上按 **Windows 语义** 处理绝对路径：这样这个纯逻辑
            # 函数在 Linux CI 上也能给出与 Windows 一致的答案（可单测）。
            return ntpath.abspath(s)
    except Exception:
        pass
    try:
        return os.path.abspath(s)
    except Exception:
        return s


def win_long_path(path: str) -> str:
    """把 Windows 路径转成设备路径形式（够长时才加 `\\?\\` 前缀）。

    纯逻辑，不看平台：非 Windows 上的单元测试可以直接验证它的行为。

    规则：
      * 空 / None -> 原样返回；
      * 已经带 `\\?\\` 前缀 -> 原样返回（不重复加）；
      * 先绝对化（顺带消掉 `..` —— 设备路径里不允许 `..`）；
      * UNC（`\\\\server\\share`）-> `\\?\\UNC\\server\\share`；
      * 短于阈值 -> 原样返回（不制造无谓的怪路径）。
    """
    if not path:
        return path
    s = str(path)
    if s.startswith(_PREFIX):
        return s
    full = _absolute(s)
    if len(full) < LONG_PATH_THRESHOLD:
        return full
    if full.startswith("\\\\"):            # UNC：\\server\share\...
        # 已经有 \\?\UNC\ 的在上面被挡掉了，这里只需补 UNC 前缀
        return _UNC_PREFIX + full[2:]
    return _PREFIX + full


def long_path(path: str) -> str:
    """平台感知版：非 Windows 原样返回，Windows 走 win_long_path。

    用途仅限**本进程自己的**文件 I/O —— 传给 adb 的路径、显示给用户的路径
    一律不能用它（见模块头部说明）。
    """
    if os.name != "nt":
        return path
    return win_long_path(path)


def is_too_long(path: str) -> bool:
    """该路径是否长到 adb / 资源管理器也会栽跟头（用于给用户一句人话）。

    与 long_path 的阈值不同：这里问的是「交给外部程序会不会失败」，所以按
    Windows 真正的 260 上限算，并留一点给文件名。
    """
    if not path:
        return False
    full = _absolute(str(path))
    return len(full) >= 260


def explain_long_path(path: str) -> str:
    """路径过长时的中文说明（可直接拼进错误提示）。"""
    return ("目标路径 %d 个字符，超过 Windows 单条路径 260 字符的上限；"
            "请把「保存目录」改短一些（不要放在多层归档目录里），"
            "或先在资源管理器里建好目录再下载到那里。" % len(str(path or "")))
