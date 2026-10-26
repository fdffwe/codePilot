"""会话侧栏：卡片式会话列表（标题 + 工作目录副标题）。"""

from __future__ import annotations

from PySide6.QtCore import (
    QModelIndex,
    QPersistentModelIndex,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from codepilot.domain.entities import Session
from codepilot.ui import theme


class SessionItemDelegate(QStyledItemDelegate):
    """绘制两行会话卡片：标题 + 工作目录。"""

    _HEIGHT = 48

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        return QSize(option.rect.width(), self._HEIGHT)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect.adjusted(2, 1, -2, -1)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        if selected or hovered:
            painter.setBrush(
                QColor(theme.PRIMARY) if selected else QColor(theme.PRIMARY_SOFT)
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, 8, 8)

        title = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        session = index.data(Qt.ItemDataRole.UserRole)
        subtitle = getattr(session, "workspace_path", "") or ""

        painter.setPen(QColor("#FFFFFF") if selected else QColor(theme.TEXT))
        title_font = QFont(option.font)
        title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        title_rect = QRect(rect.left() + 10, rect.top() + 6, rect.width() - 20, 18)
        painter.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            painter.fontMetrics().elidedText(
                title, Qt.TextElideMode.ElideRight, title_rect.width()
            ),
        )

        painter.setPen(QColor("#F3E4DA") if selected else QColor(theme.MUTED))
        sub_font = QFont(option.font)
        sub_font.setPointSizeF(max(8.0, option.font.pointSizeF() - 1.5))
        painter.setFont(sub_font)
        sub_rect = QRect(rect.left() + 10, rect.top() + 25, rect.width() - 20, 16)
        painter.drawText(
            sub_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            painter.fontMetrics().elidedText(
                subtitle, Qt.TextElideMode.ElideMiddle, sub_rect.width()
            ),
        )
        painter.restore()


class SessionSidebar(QWidget):
    createRequested = Signal()
    sessionActivated = Signal(object)  # Session

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(248)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(10)

        title = QLabel("会话", self)
        title.setObjectName("SidebarTitle")
        layout.addWidget(title)

        self._new_button = QPushButton("＋  新建会话", self)
        self._new_button.setObjectName("Primary")
        self._new_button.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self._new_button)

        self._sessions = QListWidget(self)
        self._sessions.setObjectName("Sessions")
        self._sessions.setItemDelegate(SessionItemDelegate(self._sessions))
        self._sessions.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._sessions.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        layout.addWidget(self._sessions, 1)

        self._new_button.clicked.connect(self.createRequested.emit)
        self._sessions.itemClicked.connect(self._on_item_clicked)

    @property
    def sessions(self) -> QListWidget:
        """会话列表控件（供主窗口/测试访问）。"""
        return self._sessions

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        session = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(session, Session):
            self.sessionActivated.emit(session)

    def set_sessions(self, sessions: list[Session]) -> None:
        self._sessions.clear()
        for session in sessions:
            item = QListWidgetItem(session.title)
            item.setData(Qt.ItemDataRole.UserRole, session)
            self._sessions.addItem(item)

    def select_session(self, session_id: str) -> None:
        """按 id 选中会话（列表刷新后恢复高亮）。"""
        for index in range(self._sessions.count()):
            item = self._sessions.item(index)
            session = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(session, Session) and session.id == session_id:
                self._sessions.setCurrentItem(item)
                return
