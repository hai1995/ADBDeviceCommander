#!/usr/bin/env python3
"""CI 发版闸门：校验打包进产物的 native DLL 就是当前源码编译出来的那份。

背景
----
用户只从 GitHub Release 下载 exe，从不本地编译。同源录制的所有修复都在
native/adc_mf_sink.cpp（C++），必须经 CI 重新编译成 backend/adc_mf_sink.dll
才会进入产物。此前 CI 虽然每版都跑 cmake，但**从不校验编出来的 DLL 是否是
最新源码**：一旦 CMake 缓存命中旧目标、install 拷了陈旧 dll、或有人改了
工作流漏掉编译步骤，产物就会带着旧 DLL 静默发出去，用户反复测到早已修复
的错误（真机三次原样复现 0xC00D4A45，而修复其实从没进过包）。

做法
----
native 源码里有一个随语义变更手动更新的构建指纹常量 kBuildId，并经
`adc_build_id()` 导出。本脚本：

1. 从 native/adc_mf_sink.cpp 解析源码声明的 kBuildId（正则，不 import C++）；
2. 加载 backend/adc_mf_sink.dll，调用 adc_build_id() 读出 DLL 内的指纹；
3. 两者必须完全一致，否则以非 0 退出，CI 立即变红、不发版。

老 DLL（没有 adc_build_id 导出）或加载失败一律视为不一致 —— 这正是要拦的
「旧 DLL 混进产物」。

用法
----
    python tools/check_native_dll.py                       # 校验仓库默认路径
    python tools/check_native_dll.py --dll path/to.dll     # 指定 DLL
    python tools/check_native_dll.py --source path/to.cpp  # 指定源码

退出码：0 = 一致；1 = 参数/文件错误；2 = 指纹不一致；3 = DLL 加载/符号错误。

本脚本同时导出纯函数 source_build_id() / dll_build_id() / verify()，供单测
在 Windows 之外（无真实 DLL）用假 loader 覆盖全部分支。
"""
from __future__ import annotations

import argparse
import ctypes
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CPP = ROOT / "native" / "adc_mf_sink.cpp"
DEFAULT_DLL = ROOT / "backend" / "adc_mf_sink.dll"

# 与 native/adc_mf_sink.cpp 中 `static const char* const kBuildId = "...";` 对齐。
_K_BUILD_ID_RE = re.compile(r'\bkBuildId\b\s*=\s*"([^"]+)"')


def source_build_id(cpp_path) -> str:
    """解析源码声明的构建指纹；解析不到返回空串。"""
    text = Path(cpp_path).read_text(encoding="utf-8")
    m = _K_BUILD_ID_RE.search(text)
    return m.group(1).strip() if m else ""


def _default_load(path):
    """真实加载：ctypes.CDLL 并配置 adc_build_id 的 restype。"""
    lib = ctypes.CDLL(str(path))
    fn = lib.adc_build_id
    fn.restype = ctypes.c_char_p          # 返回 const char*，否则会被当 int 截断
    fn.argtypes = []
    return lib


def dll_build_id(dll_path, *, load=None) -> str:
    """读取 DLL 内导出的构建指纹。

    load: 可注入的加载器（单测用），签名 ``load(path) -> object``，返回对象需有
          ``adc_build_id`` 可调用属性。默认用 ctypes.CDLL。
    返回空串表示：无该符号 / 调用失败 / 读到的不是合法字符串 —— 均视为旧 DLL。
    """
    loader = load or _default_load
    try:
        lib = loader(dll_path)
        fn = getattr(lib, "adc_build_id", None)
        if fn is None:
            return ""
        raw = fn()
        if isinstance(raw, bytes):
            return raw.decode("utf-8", "replace").strip()
        if isinstance(raw, str):
            return raw.strip()
        return ""
    except Exception:  # noqa: BLE001  DLL 损坏/缺导出/平台不支持都归为「读不到」
        return ""


def verify(cpp_path=DEFAULT_CPP, dll_path=DEFAULT_DLL, *, load=None):
    """返回 (ok: bool, code: int, message: str)。

    code: 0 一致 / 1 文件缺失 / 2 指纹不一致 / 3 DLL 加载读不到指纹。
    """
    cpp = Path(cpp_path)
    dll = Path(dll_path)
    if not cpp.is_file():
        return False, 1, f"找不到 native 源码：{cpp}"
    if not dll.is_file():
        return False, 1, (
            f"找不到 {dll}：请先在 CI 执行 native 编译三步（cmake 配置 / build / "
            "install --prefix backend），确认编译步骤没有失败。")

    src_id = source_build_id(cpp)
    if not src_id:
        return False, 1, (
            f"源码 {cpp.name} 里解析不到 kBuildId 常量——"
            "构建指纹守卫不能被悄悄移除。")

    dll_id = dll_build_id(dll, load=load)
    if not dll_id:
        return False, 3, (
            f"无法从 {dll.name} 读取构建指纹（缺 adc_build_id 导出或加载失败）："
            "这几乎总是「旧 DLL / 未重新编译」——请在 CI 重新编译并 --install。")
    if dll_id != src_id:
        return False, 2, (
            f"native DLL 构建指纹与源码不一致：源码={src_id}，DLL={dll_id}。"
            "说明产物里是旧 DLL（CMake 缓存命中 / install 拷了陈旧文件），"
            "请清理 native/build 后重新完整编译。")
    return True, 0, f"native DLL 构建指纹一致：{dll_id}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="校验 native DLL 与源码的构建指纹一致")
    ap.add_argument("--dll", default=str(DEFAULT_DLL), help="DLL 路径")
    ap.add_argument("--source", default=str(DEFAULT_CPP), help="native cpp 源码路径")
    args = ap.parse_args(argv)

    ok, code, msg = verify(args.source, args.dll)
    if ok:
        print(f"[OK] {msg}")
        return 0
    print(f"[失败] {msg}", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
