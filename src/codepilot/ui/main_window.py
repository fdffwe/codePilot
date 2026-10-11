"""主窗口：无边框圆角窗口 + 组合各视图。

只负责装配与转发；业务逻辑经 ChatViewModel → application。见规范 §15。
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from codepilot import __version__
from codepilot.core.config import Settings
from codepilot.domain.entities import Approval, Session
from codepilot.ui.bridge import EventBridge
from codepilot.ui.viewmodels import ChatViewModel
from codepilot.ui.views import ChatView, FileTreePanel, SessionSidebar, TitleBar

_RESIZE_MARGIN = 6


class _RootFrame(QWidget):
    """窗口内容根：圆角由 QSS 施加；转发鼠标事件给主窗口做缩放。"""

    def __init__(self, window: MainWindow) -> None:
        super().__init__(window)
        self._window = window
        self.setObjectName("Root")
        self.setMouseTracking(True)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._window.handle_root_press(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._window.handle_root_move(event)


class MainWindow(QMainWindow):
    def __init__(
        self,
        settings: Settings,
        viewmodel: ChatViewModel,
        bridge: EventBridge,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._vm = viewmodel
        self._bridge = bridge
        self._pending_approval: Approval | None = None

        self.setWindowTitle(f"{settings.app_name} {__version__}")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(1180, 760)
        self.setMinimumSize(760, 520)
        self._build_ui()
        self._connect()
        self._vm.load_sessions()

    # --- 构建 ---

    def _build_ui(self) -> None:
        self._root = _RootFrame(self)
        self.setCentralWidget(self._root)
        outer = QVBoxLayout(self._root)
        outer.setContentsMargins(
            _RESIZE_MARGIN, _RESIZE_MARGIN, _RESIZE_MARGIN, _RESIZE_MARGIN
        )
        outer.setSpacing(0)

        outer.addWidget(
            TitleBar(f"{self._settings.app_name} {__version__}", self._root)
        )

        content = QHBoxLayout()
        content.setContentsMargins(6, 0, 6, 0)
        content.setSpacing(0)

        self._sidebar = SessionSidebar(self._root)
        self._sessions = self._sidebar.sessions  # 供测试/兼容访问
        content.addWidget(self._sidebar, 0)

        self._file_tree = FileTreePanel(self._root)
        content.addWidget(self._file_tree, 0)

        content.addWidget(self._build_conversation(), 1)
        outer.addLayout(content, 1)

        self.statusBar().showMessage(
            f"数据目录：{self._settings.data_dir}  |  模型：{self._settings.llm_model}"
        )

    def _build_conversation(self) -> QWidget:
        panel = QWidget(self._root)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._chat = ChatView(panel)
        layout.addWidget(self._chat, 1)

        self._approval_box = self._build_approval_box(panel)
        self._approval_box.setVisible(False)
        layout.addWidget(self._approval_box)
        return panel

    def _build_approval_box(self, parent: QWidget) -> QFrame:
        box = QFrame(parent)
        box.setObjectName("ApprovalCard")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        self._approval_label = QLabel(box)
        self._approval_label.setObjectName("ApprovalTitle")
        self._approval_preview = QTextEdit(box)
        self._approval_preview.setObjectName("ApprovalPreview")
        self._approval_preview.setReadOnly(True)
        self._approval_preview.setFixedHeight(120)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._allow_button = QPushButton("允许", box)
        self._allow_button.setObjectName("Primary")
        self._reject_button = QPushButton("拒绝", box)
        self._reject_button.setObjectName("Danger")
        for button in (self._allow_button, self._reject_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            buttons.addWidget(button)

        layout.addWidget(self._approval_label)
        layout.addWidget(self._approval_preview)
        layout.addLayout(buttons)
        return box

    # --- 连接 ---

    def _connect(self) -> None:
        self._sidebar.createRequested.connect(self._on_new_session)
        self._sidebar.sessionActivated.connect(self._on_session_clicked)
        self._chat.sendRequested.connect(self._on_send)
        self._allow_button.clicked.connect(lambda: self._resolve(True))
        self._reject_button.clicked.connect(lambda: self._resolve(False))

        self._file_tree.directoryExpandRequested.connect(self._vm.list_workspace_dir)
        self._file_tree.fileActivated.connect(self._vm.read_workspace_file)

        self._vm.sessionsChanged.connect(self._on_sessions_changed)
        self._vm.errorOccurred.connect(self._on_error)
        self._vm.busyChanged.connect(self._on_busy)
        self._vm.workspaceEntriesLoaded.connect(self._file_tree.set_entries)
        self._vm.workspaceFileLoaded.connect(self._show_file)

        self._bridge.messageReceived.connect(lambda t: self._append("助手", t))
        self._bridge.toolCalled.connect(
            lambda name, args: self._append("工具", f"{name} {args}")
        )
        self._bridge.toolResult.connect(self._on_tool_result)
        self._bridge.approvalRequested.connect(self._on_approval)
        self._bridge.errorOccurred.connect(lambda m: self._append("错误", m))

    # --- 槽 ---

    def _on_new_session(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "选择工作目录", str(self._settings.data_dir)
        )
        if path:
            self._vm.create_session(path)

    def _on_send(self, text: str) -> None:
        self._append("我", text)
        self._vm.send(text)

    def _on_session_clicked(self, session: Session) -> None:
        self._vm.open_session(session)
        self._file_tree.reset(session.title)
        self._append("系统", f"已打开会话：{session.title}（{session.workspace_path}）")

    def _on_sessions_changed(self, sessions: list[Session]) -> None:
        self._sidebar.set_sessions(sessions)

    def _on_tool_result(self, output: str, ok: bool) -> None:
        self._append("输出" if ok else "输出(失败)", output)

    def _on_approval(self, approval: Approval) -> None:
        self._pending_approval = approval
        self._approval_label.setText(f"{approval.tool}（风险：{approval.risk}）")
        self._approval_preview.setPlainText(approval.preview)
        self._approval_box.setVisible(True)

    def _resolve(self, approved: bool) -> None:
        if self._pending_approval is None:
            return
        self._approval_box.setVisible(False)
        self._vm.resolve_approval(self._pending_approval.id, approved)
        self._pending_approval = None

    def _on_busy(self, busy: bool) -> None:
        self._chat.set_busy(busy)
        self.statusBar().showMessage("运行中…" if busy else "就绪")

    def _on_error(self, message: str) -> None:
        self._append("错误", message)

    def _show_file(self, path: str, content: str) -> None:
        self._append("文件", f"{path}\n```\n{content}\n```")

    def _append(self, who: str, text: str) -> None:
        self._chat.add_message(who, text)

    # --- 无边框窗口：拖动/缩放 ---

    def handle_root_press(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        edges = self._edges_at(event.position().toPoint())
        if edges is None:
            return
        handle = self.windowHandle()
        if handle is not None and handle.startSystemResize(edges):
            event.accept()

    def handle_root_move(self, event: QMouseEvent) -> None:
        self._root.setCursor(
            self._cursor_for(self._edges_at(event.position().toPoint()))
        )

    def _edges_at(self, pos: QPoint) -> Qt.Edge | None:
        width = self._root.width()
        height = self._root.height()
        margin = _RESIZE_MARGIN
        edges: Qt.Edge | None = None
        candidates = (
            (Qt.Edge.LeftEdge, pos.x() <= margin),
            (Qt.Edge.RightEdge, pos.x() >= width - margin),
            (Qt.Edge.TopEdge, pos.y() <= margin),
            (Qt.Edge.BottomEdge, pos.y() >= height - margin),
        )
        for flag, active in candidates:
            if active:
                edges = flag if edges is None else edges | flag
        return edges

    @staticmethod
    def _cursor_for(edges: Qt.Edge | None) -> Qt.CursorShape:
        if edges is None:
            return Qt.CursorShape.ArrowCursor
        horizontal = edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge)
        vertical = edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge)
        if horizontal and vertical:
            return Qt.CursorShape.SizeFDiagCursor
        if horizontal:
            return Qt.CursorShape.SizeHorCursor
        if vertical:
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.ArrowCursor
