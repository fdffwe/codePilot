"""WSL 输入法后端适配测试。"""

from __future__ import annotations

from codepilot.ui.input_method import _detect_wsl, configure_input_method


def test_wsl_sets_xim_and_xcb() -> None:
    env: dict[str, str] = {}

    configure_input_method(env, is_wsl=True)

    assert env == {"QT_IM_MODULE": "xim", "QT_QPA_PLATFORM": "xcb"}


def test_non_wsl_is_noop() -> None:
    env: dict[str, str] = {}

    configure_input_method(env, is_wsl=False)

    assert env == {}


def test_existing_values_are_preserved() -> None:
    env = {"QT_IM_MODULE": "fcitx", "QT_QPA_PLATFORM": "wayland"}

    configure_input_method(env, is_wsl=True)

    assert env == {"QT_IM_MODULE": "fcitx", "QT_QPA_PLATFORM": "wayland"}


def test_detect_wsl_from_env_marker() -> None:
    assert _detect_wsl({"WSL_DISTRO_NAME": "Ubuntu"}) is True
    assert _detect_wsl({"WSL_INTEROP": "/run/WSL/1_interop"}) is True
