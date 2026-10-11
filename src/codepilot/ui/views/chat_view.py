"""对话视图：滚动消息区 + 输入行。"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from codepilot.ui.views.message_bubble import MessageBubble

_USER_WHO = {"我"}


class ChatView(QWidget):
    sendRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("Transcript")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._container = QWidget()
        self._container.setObjectName("TranscriptWidget")
        self._messages = QVBoxLayout(self._container)
        self._messages.setContentsMargins(18, 16, 18, 16)
        self._messages.setSpacing(12)
        self._messages.addStretch(1)  # 前导 stretch，有消息后移除
        self._hint: QLabel | None = QLabel(
            "选择左侧会话，或点「＋ 新建会话」绑定一个工作目录开始", self._container
        )
        self._hint.setObjectName("EmptyHint")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setWordWrap(True)
        self._messages.addWidget(self._hint)
        self._messages.addStretch(1)
        self._scroll.setWidget(self._container)
        layout.addWidget(self._scroll, 1)

        row = QHBoxLayout()
        row.setContentsMargins(18, 0, 18, 16)
        row.setSpacing(10)
        self._input = QLineEdit(self)
        self._input.setObjectName("ChatInput")
        self._input.setPlaceholderText("描述你的需求，回车发送…")
        self._send_button = QPushButton("发送", self)
        self._send_button.setObjectName("Primary")
        self._send_button.setCursor(Qt.CursorShape.PointingHandCursor)
        row.addWidget(self._input, 1)
        row.addWidget(self._send_button, 0)
        layout.addLayout(row)

        self._send_button.clicked.connect(self._emit_send)
        self._input.returnPressed.connect(self._emit_send)

    # --- 对外槽 ---

    def add_message(self, who: str, text: str) -> None:
        self._clear_empty_state()
        bubble = MessageBubble(who, text, self._container)
        wrapper = QWidget(self._container)
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        if who in _USER_WHO:
            row.addStretch(1)
            row.addWidget(bubble, 0)
        else:
            row.addWidget(bubble, 0)
            row.addStretch(1)
        self._messages.insertWidget(self._messages.count() - 1, wrapper)
        QTimer.singleShot(0, self._scroll_to_bottom)

    def set_busy(self, busy: bool) -> None:
        self._send_button.setEnabled(not busy)
        self._input.setEnabled(not busy)

    # --- 内部 ---

    def _clear_empty_state(self) -> None:
        if self._hint is None:
            return
        # removeWidget 只解除布局管理，控件仍可见，必须显式脱离父级
        self._messages.removeWidget(self._hint)
        self._hint.setParent(None)
        self._hint.deleteLater()
        self._hint = None
        self._messages.takeAt(0)  # 移除前导 stretch，消息改为顶部对齐

    def _emit_send(self) -> None:
        text = self._input.text()
        if not text.strip():
            return
        self._input.clear()
        self.sendRequested.emit(text)

    def _scroll_to_bottom(self) -> None:
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
