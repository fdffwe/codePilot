"""对话气泡与代码块。

按 ``who`` 选气泡样式；正文里的 ``` 围栏切成独立 :class:`CodeBlock`。
"""

from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

_FENCE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)

_BUBBLE_BY_WHO = {
    "我": "BubbleUser",
    "助手": "BubbleAssistant",
    "工具": "BubbleTool",
    "输出": "BubbleTool",
    "输出(失败)": "BubbleTool",
    "文件": "BubbleTool",
    "错误": "BubbleError",
}


class CodeBlock(QPlainTextEdit):
    """只读代码块：深色底、等宽字体、按内容自适应高度。"""

    _MAX_HEIGHT = 320

    def __init__(self, code: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CodeBlock")
        self.setReadOnly(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setPlainText(code.rstrip("\n"))
        self.setFixedHeight(
            min(
                self.blockCount() * self.fontMetrics().lineSpacing() + 22,
                self._MAX_HEIGHT,
            )
        )


class MessageBubble(QWidget):
    """一条消息气泡。"""

    def __init__(self, who: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(_BUBBLE_BY_WHO.get(who, "BubbleAssistant"))
        self.setMaximumWidth(760)
        # QWidget 子类默认不绘制 QSS 背景，需显式开启气泡底色与圆角
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)

        position = 0
        for match in _FENCE.finditer(text):
            prose = text[position : match.start()]
            if prose.strip():
                layout.addWidget(self._label(prose.strip()))
            layout.addWidget(CodeBlock(match.group(2), self))
            position = match.end()
        tail = text[position:]
        if tail.strip():
            layout.addWidget(self._label(tail.strip()))
        if layout.count() == 0:
            layout.addWidget(self._label(text or "（空）"))

    def _label(self, content: str) -> QLabel:
        label = QLabel(content, self)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label
