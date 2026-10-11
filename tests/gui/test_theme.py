"""主题与主窗口外观冒烟测试。"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from codepilot.core.config import Settings
from codepilot.ui import theme


def test_stylesheet_contains_palette() -> None:
    qss = theme.build_stylesheet()
    assert theme.BG in qss
    assert theme.PRIMARY in qss
    assert "border-radius" in qss
    assert "#Root" in qss


def test_apply_theme_sets_stylesheet(qapp: QApplication) -> None:
    theme.apply_theme(qapp)
    assert qapp.styleSheet() == theme.build_stylesheet()


@pytest.mark.asyncio
async def test_main_window_root_and_theme(qtbot, tmp_path) -> None:
    from codepilot.application.event_bus import EventBus
    from codepilot.ui.bridge import EventBridge
    from codepilot.ui.main_window import MainWindow
    from codepilot.ui.viewmodels import ChatViewModel

    class Stub:
        async def list_sessions(self) -> list:
            return []

    qapp = QApplication.instance()
    if qapp is not None:
        theme.apply_theme(qapp)

    window = MainWindow(
        Settings(data_dir=tmp_path), ChatViewModel(Stub()), EventBridge(EventBus())  # type: ignore[arg-type]
    )
    qtbot.addWidget(window)
    assert window._root.objectName() == "Root"
