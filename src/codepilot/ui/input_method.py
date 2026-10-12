"""Linux 输入法后端适配（必须在创建 ``QApplication`` 之前调用）。

背景：PySide6 自带的 Qt 输入法插件只有 compose/ibus，不含 fcitx；而发行版的
fcitx5 Qt6 插件按更老的 Qt 构建，在 PySide6 的 Qt 上无法加载（ABI 不匹配，缺
``Qt_6_PRIVATE_API`` 符号）。WSLg 的 Wayland 合成器又不提供输入法协议，故默认
的 wayland 后端下中文输入不可用。

对策（仅作用于 WSL，且不覆盖用户已显式设置的变量）：

- ``QT_IM_MODULE=xim``：改用 Qt 内置的 XIM，对接 fcitx5 的 XIM 服务
  （``XMODIFIERS=@im=fcitx``）。
- ``QT_QPA_PLATFORM=xcb``：改走 Xwayland，XIM 才有承载。

如不希望改后端，在启动前自行设置上述任一变量即可覆盖。
"""

from __future__ import annotations

import os
from collections.abc import MutableMapping


def _detect_wsl(env: MutableMapping[str, str]) -> bool:
    if env.get("WSL_DISTRO_NAME") or env.get("WSL_INTEROP"):
        return True
    try:
        with open("/proc/version", encoding="utf-8", errors="ignore") as handle:
            return "microsoft" in handle.read().lower()
    except OSError:
        return False


def configure_input_method(
    env: MutableMapping[str, str] | None = None,
    *,
    is_wsl: bool | None = None,
) -> None:
    """在 WSL 下把 Qt 切到可用的中文输入后端；其它平台不做改动。"""
    environ = os.environ if env is None else env
    if is_wsl is None:
        is_wsl = _detect_wsl(environ)
    if not is_wsl:
        return
    environ.setdefault("QT_IM_MODULE", "xim")
    environ.setdefault("QT_QPA_PLATFORM", "xcb")
