"""应用内浮层提醒：短暂显示标题 + 正文，自动消失。"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


class Toast(QFrame):
    """父容器右上角的非模态提醒浮层。"""

    def __init__(
        self, parent: QWidget | None = None, *, timeout_ms: int = 3500
    ) -> None:
        super().__init__(parent)
        self._timeout_ms = timeout_ms
        self.setObjectName("Toast")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setMaximumWidth(360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(4)
        self._title = QLabel(self)
        self._title.setObjectName("ToastTitle")
        self._body = QLabel(self)
        self._body.setObjectName("ToastBody")
        self._body.setWordWrap(True)
        layout.addWidget(self._title)
        layout.addWidget(self._body)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self.hide()

    @property
    def title(self) -> str:
        return self._title.text()

    @property
    def body(self) -> str:
        return self._body.text()

    def show_message(self, title: str, body: str) -> None:
        self._title.setText(title)
        self._body.setText(body)
        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()
        self._timer.start(self._timeout_ms)

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        margin = 20
        # 避开 42px 标题栏（含窗口外边距），避免遮住窗口按钮
        top = 54
        self.move(
            max(margin, parent.width() - self.width() - margin),
            top,
        )
