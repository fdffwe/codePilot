"""主窗口冒烟测试（offscreen）。"""

from __future__ import annotations

from pathlib import Path

from pytestqt.qtbot import QtBot

from codepilot.core.config import Settings
from codepilot.ui.main_window import MainWindow


def test_main_window_builds(qtbot: QtBot, tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / ".codepilot")
    window = MainWindow(settings)
    qtbot.addWidget(window)

    assert "codePilot" in window.windowTitle()
    assert window.centralWidget() is not None
