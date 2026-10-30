# -*- coding: utf-8 -*-
"""
core.apk —— APK 安装的纯逻辑（参数拼装 + 输出解析 + 失败原因翻译）
====================================================================
`adb install` 的输出对使用者很不友好：成功只有一行 `Success`，失败则是
`Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE: Package com.x signatures do not
match...]` —— 一串英文错误码 + 设备端原文。本模块把它翻成「下一步做什么」，
例如签名不一致要「先卸载旧包」，版本降级要「勾选允许降级」。

  * install_args(...)        选项 → `adb install` 的参数（顺序稳定，便于测试）
  * parse_install_output(t)  adb 输出 → {ok, code, message}
  * format_size(n)           字节 → "12.3 MB"（安装包体积展示用）

注意：**成功判定不能只看 returncode**。adb 客户端在 `install` 失败时也会以
0 退出（错误在设备端），真正的结论只在输出的 `Success` / `Failure [...]` 里。
"""
import re

# 失败码 → 用户能照着做的说明。键是设备的 INSTALL_* 常量，值是中文建议。
INSTALL_REASONS = {
    "INSTALL_FAILED_ALREADY_EXISTS":
        "设备上已有同包名应用，勾选「覆盖安装（-r）」再试",
    "INSTALL_FAILED_VERSION_DOWNGRADE":
        "设备上的版本更高，勾选「允许降级（-d）」再试（或先卸载旧版本）",
    "INSTALL_FAILED_UPDATE_INCOMPATIBLE":
        "签名不一致：先卸载设备上的旧应用再装（测试包与正式包签名通常不同）",
    "INSTALL_FAILED_INSUFFICIENT_STORAGE":
        "设备存储空间不足：清理后再装（安装大约需要 2~3 倍 APK 体积的临时空间）",
    "INSTALL_FAILED_INVALID_APK":
        "安装包不完整或不是合法 APK（拷贝过程可能损坏，重新拷一份）",
    "INSTALL_FAILED_INVALID_URI":
        "安装包路径无效：确认文件还在、没有被安全软件锁住",
    "INSTALL_FAILED_NO_MATCHING_ABIS":
        "CPU 架构不匹配：设备是 arm64/arm，装的是 x86 包（找对应架构的 APK）",
    "INSTALL_FAILED_OLDER_SDK":
        "设备 Android 版本低于应用要求（minSdk 太高）",
    "INSTALL_FAILED_NEWER_SDK":
        "应用要求更高的 Android 版本（targetSdk 超过设备）",
    "INSTALL_FAILED_USER_RESTRICTED":
        "系统禁止安装：打开「开发者选项 → USB 安装」，或关闭「MIUI 优化 / 纯净模式」等限制",
    "INSTALL_FAILED_VERIFICATION_FAILURE":
        "安装校验失败：临时关闭「验证应用」（部分国产 ROM 的开发者选项里有）",
    "INSTALL_FAILED_TEST_ONLY":
        "这是 testOnly 调试包：用 `adb install -t` 安装（勾选「覆盖安装」不解决，需要 -t 选项）",
    "INSTALL_FAILED_DEPRECATED_SDK_VERSION":
        "应用的目标 SDK 已被该系统拒绝（targetSdk 过低），换新版本包",
    "INSTALL_FAILED_CONFLICTING_PROVIDER":
        "与已装应用冲突（同名 ContentProvider），先卸载冲突应用",
    "INSTALL_FAILED_DEXOPT":
        "设备端 dex 优化失败：多为空间不足或 ROM 异常，重启后再试",
    "INSTALL_PARSE_FAILED_NOT_APK":
        "文件不是 APK（扩展名对但内容不是 zip 包），确认选中的文件",
    "INSTALL_PARSE_FAILED_NO_CERTIFICATES":
        "APK 未签名：debug 包需用 debug 证书重新签名",
    "INSTALL_PARSE_FAILED_INCONSISTENT_CERTIFICATES":
        "APK 内签名不一致（多渠道打包污染），重新出一份干净包",
    "INSTALL_CANCELED_BY_USER":
        "设备上取消了安装（部分 ROM 会弹「是否安装」确认框）",
}

_SYS_HINTS = (
    ("device offline", "设备离线：重新插线或重连无线调试后再装"),
    ("device not found", "设备已断开：检查数据线 / 无线连接"),
    ("no devices/emulators found", "没有可用设备：先勾选一台在线设备"),
    ("insufficient permissions", "没有写入权限：确认设备已授权 USB 调试"),
    ("failed to stat", "找不到安装包文件：确认路径存在且未被移动"),
    ("error: closed", "adb 连接被关闭：重试一次；反复出现可 adb kill-server"),
)


def install_args(replace=True, downgrade=False, grant=False, test_only=False):
    """拼 `adb install` 的参数（不含 adb 与 apk 路径）。

    顺序固定为 -r/-d/-g/-t：`adb install` 的参数与位置无关，但固定顺序让
    日志与测试断言可读、可比对。
    """
    args = ["install"]
    if replace:
        args.append("-r")
    if downgrade:
        args.append("-d")
    if grant:
        args.append("-g")
    if test_only:
        args.append("-t")
    return args


def parse_install_output(text):
    """解析 `adb install` 的合并输出（stdout + stderr）。

    返回 `{ok, code, message}`：
      * ok       成功 / 失败
      * code     设备端的 INSTALL_* 码（成功时为空）
      * message  中文说明（成功时是「安装成功」）
    """
    t = (text or "")
    low = t.lower()

    m = re.search(r"failure\s*\[\s*([A-Za-z_]+)\s*(?::\s*([^\]]*))?\]", t, re.I)
    if m:
        code = m.group(1).upper()
        detail = (m.group(2) or "").strip()
        reason = INSTALL_REASONS.get(code)
        if reason:
            return {"ok": False, "code": code,
                    "message": "%s（%s）" % (reason, code)}
        if code.startswith("INSTALL_PARSE_FAILED"):
            return {"ok": False, "code": code,
                    "message": "安装包解析失败（%s）：包可能损坏或签名异常" % code}
        return {"ok": False, "code": code,
                "message": (detail or code) + "（%s）" % code}

    # 没有 `Failure [...]` 的失败：设备离线 / 文件不存在等 adb 客户端错误
    for needle, hint in _SYS_HINTS:
        if needle in low:
            return {"ok": False, "code": "", "message": hint}

    if re.search(r"(^|\n)\s*success\s*($|\n)", low) or low.strip().endswith("success"):
        return {"ok": True, "code": "", "message": "安装成功"}

    if "performing streamed install" in low and "failure" not in low:
        # 老 adb 只在流式安装时打这一行，随后才是 Success；走到这里说明输出被
        # 截断了（进程被杀）。按失败处理，并给出可执行的下一步。
        return {"ok": False, "code": "",
                "message": "安装结果不完整（adb 输出被中断），重试一次；反复出现可 adb kill-server"}

    tail = [ln.strip() for ln in t.strip().splitlines() if ln.strip()]
    detail = tail[-1][:160] if tail else "无输出"
    return {"ok": False, "code": "", "message": "安装失败：" + detail}


def format_size(num):
    """字节数 → 人读的体积（1 位小数；负数 / 非法值返回空串）。"""
    try:
        n = float(num)
    except (TypeError, ValueError):
        return ""
    if n < 0:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            if unit == "B":
                return "%d B" % int(n)
            return "%.1f %s" % (n, unit)
        n /= 1024.0
    return ""
