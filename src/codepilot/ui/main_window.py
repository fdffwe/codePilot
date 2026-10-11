"""主窗口（P0 占位）。

P0 阶段仅建立窗口骨架与菜单/状态栏；业务界面在 P1 起接入。
Widget 不含业务逻辑，后续通过 ViewModel 调用 application 服务（规范 §15）。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from codepilot import __version__
from codepilot.core.config import Settings


class MainWindow(QMainWindow):
    """codePilot 主窗口。"""

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings

        self.setWindowTitle(f"{settings.app_name} {__version__}")
        self.resize(1100, 720)
        self._build_menu()
        self._build_central()
        self._build_status_bar()

    def _build_menu(self) -> None:
        menu = self.menuBar().addMenu("文件")
        # P0 占位：动作先禁用，P1 起接入真实逻辑
        for label in ("新建会话", "打开目录…", "退出"):
            action = QAction(label, self)
            action.setEnabled(False)
            menu.addAction(action)

    def _build_central(self) -> None:
        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("codePilot", central)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = title.font()
        font.setPointSize(28)
        font.setBold(True)
        title.setFont(font)

        hint = QLabel("P0 工程底座就绪 · 界面与功能将在后续阶段接入", central)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(title)
        layout.addWidget(hint)
        self.setCentralWidget(central)

    def _build_status_bar(self) -> None:
        bar = self.statusBar()
        bar.showMessage(
            f"数据目录：{self._settings.data_dir}  |  模型：{self._settings.llm_model}"
        )
