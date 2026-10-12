"""活动栏：最左侧的竖向图标列表，切换中栏显示哪个面板。

仿 VSCode 的 activity bar：图标按钮互斥选中，只发 ``panelSelected`` 意图信号。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

# (图标字形, 提示文字)，顺序即面板索引
_ITEMS: tuple[tuple[str, str], ...] = (
    ("☰", "会话"),
    ("▤", "文件"),
)


class ActivityBar(QWidget):
    panelSelected = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ActivityBar")
        self.setFixedWidth(48)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 10)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for index, (glyph, tip) in enumerate(_ITEMS):
            button = QToolButton(self)
            button.setObjectName("ActivityButton")
            button.setText(glyph)
            button.setToolTip(tip)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda _checked=False, i=index: self.panelSelected.emit(i)
            )
            self._group.addButton(button, index)
            layout.addWidget(button)
        layout.addStretch(1)
        self.set_current(0)  # 默认选中第一个面板

    def set_current(self, index: int) -> None:
        button = self._group.button(index)
        if button is not None:
            button.setChecked(True)
