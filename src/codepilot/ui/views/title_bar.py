"""自绘标题栏：拖动移动窗口 + 最小化/最大化/关闭。

无边框窗口没有系统标题栏，拖动优先用 ``startSystemMove``（Qt6），
不可用时回退为手动 ``move``。见规范 §15。
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal, SignalInstance
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QWidget


class TitleBar(QWidget):
    minimizeRequested = Signal()
    maximizeRequested = Signal()
    closeRequested = Signal()

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TitleBar")
        self.setFixedHeight(42)
        self._drag_offset: QPoint | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 8, 0)
        layout.setSpacing(4)

        self._title = QLabel(title, self)
        self._title.setObjectName("TitleText")
        layout.addWidget(self._title)
        layout.addStretch(1)

        layout.addWidget(self._button("—", "WinButton", self.minimizeRequested))
        layout.addWidget(self._button("▢", "WinButton", self.maximizeRequested))
        layout.addWidget(self._button("✕", "WinClose", self.closeRequested))

    def _button(self, text: str, name: str, signal: SignalInstance) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName(name)
        button.setText(text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(signal.emit)
        return button

    # --- 拖动 ---

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        handle = self.window().windowHandle()
        if handle is not None and handle.startSystemMove():
            event.accept()
            return
        self._drag_offset = (
            event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
        )
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._drag_offset is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            self.window().move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.maximizeRequested.emit()
            event.accept()
