"""主窗口：无边框圆角窗口 + 组合各视图。

只负责装配与转发；业务逻辑经 ChatViewModel → application。见规范 §15。
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QCloseEvent, QMouseEvent, QResizeEvent
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from codepilot import __version__
from codepilot.core.config import Settings
from codepilot.domain.entities import Approval, Question, Session
from codepilot.ui.bridge import EventBridge
from codepilot.ui.viewmodels import ChatViewModel
from codepilot.ui.views import (
    ActivityBar,
    ChatView,
    FileTreePanel,
    MainTabs,
    SessionSidebar,
    TitleBar,
    Toast,
)

_RESIZE_MARGIN = 6


def _apply_margins(layout: QVBoxLayout, margin: int) -> None:
    layout.setContentsMargins(margin, margin, margin, margin)


class _RootFrame(QWidget):
    """窗口内容根：圆角由 QSS 施加；转发鼠标事件给主窗口做缩放。"""

    def __init__(self, window: MainWindow) -> None:
        super().__init__(window)
        self._window = window
        self.setObjectName("Root")
        self.setMouseTracking(True)
        # QWidget 子类默认不绘制 QSS 背景，显式开启才会画出米白底与圆角
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._window.handle_root_press(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._window.handle_root_move(event)


class MainWindow(QMainWindow):
    closed = Signal()

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
        self._pending_question: Question | None = None
        self._option_buttons: list[QPushButton] = []

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
        self._outer = outer
        _apply_margins(outer, _RESIZE_MARGIN)
        outer.setSpacing(0)

        self._title_bar = TitleBar(
            f"{self._settings.app_name} {__version__}", self._root
        )
        outer.addWidget(self._title_bar)

        content = QHBoxLayout()
        content.setContentsMargins(6, 0, 6, 0)
        content.setSpacing(0)

        self._activity = ActivityBar(self._root)
        content.addWidget(self._activity, 0)

        # 中栏：会话 / 文件 两个面板，按活动栏图标切换
        self._side_stack = QStackedWidget(self._root)
        self._sidebar = SessionSidebar(self._side_stack)
        self._sessions = self._sidebar.sessions  # 供测试/兼容访问
        self._file_tree = FileTreePanel(self._side_stack)
        self._side_stack.addWidget(self._sidebar)
        self._side_stack.addWidget(self._file_tree)
        content.addWidget(self._side_stack, 0)

        # 右侧主区：对话 + 文件标签页
        self._tabs = MainTabs(self._build_conversation(), self._root)
        content.addWidget(self._tabs, 1)
        outer.addLayout(content, 1)

        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().showMessage(
            f"数据目录：{self._settings.data_dir}  |  模型：{self._settings.llm_model}"
        )

        self._toast = Toast(self._root)

    def _build_conversation(self) -> QWidget:
        panel = QWidget(self._root)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._chat = ChatView(panel)
        layout.addWidget(self._chat, 1)

        self._question_box = self._build_question_box(panel)
        self._question_box.setVisible(False)
        layout.addWidget(self._question_box)

        self._approval_box = self._build_approval_box(panel)
        self._approval_box.setVisible(False)
        layout.addWidget(self._approval_box)
        return panel

    def _build_question_box(self, parent: QWidget) -> QFrame:
        box = QFrame(parent)
        box.setObjectName("QuestionCard")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        title = QLabel("需要你的补充", box)
        title.setObjectName("QuestionTitle")
        self._question_text = QLabel(box)
        self._question_text.setObjectName("QuestionText")
        self._question_text.setWordWrap(True)

        self._question_options = QWidget(box)
        self._question_options_layout = QHBoxLayout(self._question_options)
        self._question_options_layout.setContentsMargins(0, 0, 0, 0)
        self._question_options_layout.setSpacing(8)

        row = QHBoxLayout()
        self._question_input = QLineEdit(box)
        self._question_input.setObjectName("QuestionInput")
        self._question_input.setPlaceholderText("输入你的回答，回车提交…")
        self._question_submit = QPushButton("提交", box)
        self._question_submit.setObjectName("Primary")
        self._question_submit.setCursor(Qt.CursorShape.PointingHandCursor)
        row.addWidget(self._question_input, 1)
        row.addWidget(self._question_submit, 0)

        layout.addWidget(title)
        layout.addWidget(self._question_text)
        layout.addWidget(self._question_options)
        layout.addLayout(row)

        self._question_submit.clicked.connect(
            lambda: self._submit_answer(self._question_input.text())
        )
        self._question_input.returnPressed.connect(
            lambda: self._submit_answer(self._question_input.text())
        )
        return box

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
        self._title_bar.minimizeRequested.connect(self.showMinimized)
        self._title_bar.maximizeRequested.connect(self._toggle_maximize)
        self._title_bar.closeRequested.connect(self.close)
        self._sidebar.createRequested.connect(self._on_new_session)
        self._sidebar.sessionActivated.connect(self._on_session_clicked)
        self._chat.sendRequested.connect(self._on_send)
        self._allow_button.clicked.connect(lambda: self._resolve(True))
        self._reject_button.clicked.connect(lambda: self._resolve(False))

        self._activity.panelSelected.connect(self._side_stack.setCurrentIndex)
        self._tabs.saveRequested.connect(self._vm.save_workspace_file)

        self._file_tree.directoryExpandRequested.connect(self._vm.list_workspace_dir)
        self._file_tree.fileActivated.connect(self._vm.read_workspace_file)

        self._vm.sessionsChanged.connect(self._on_sessions_changed)
        self._vm.errorOccurred.connect(self._on_error)
        self._vm.busyChanged.connect(self._on_busy)
        self._vm.workspaceEntriesLoaded.connect(self._file_tree.set_entries)
        self._vm.workspaceFileLoaded.connect(self._open_file_tab)
        self._vm.workspaceFileSaved.connect(self._tabs.mark_saved)

        self._bridge.messageReceived.connect(lambda t: self._append("助手", t))
        self._bridge.toolCalled.connect(
            lambda name, args: self._append("工具", f"{name} {args}")
        )
        self._bridge.toolResult.connect(self._on_tool_result)
        self._bridge.approvalRequested.connect(self._on_approval)
        self._bridge.questionAsked.connect(self._on_question)
        self._bridge.runFinished.connect(self._on_run_finished)
        self._bridge.errorOccurred.connect(self._on_agent_error)

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
        self._side_stack.setCurrentIndex(1)  # 切到文件面板
        self._activity.set_current(1)
        self._tabs.show_chat()
        self._append("系统", f"已打开会话：{session.title}（{session.workspace_path}）")

    def _on_sessions_changed(self, sessions: list[Session]) -> None:
        self._sidebar.set_sessions(sessions)

    def _on_tool_result(self, output: str, ok: bool) -> None:
        self._append("输出" if ok else "输出(失败)", output)

    def _on_approval(self, approval: Approval) -> None:
        self._pending_question = None
        self._question_box.setVisible(False)
        self._pending_approval = approval
        self._approval_label.setText(f"{approval.tool}（风险：{approval.risk}）")
        self._approval_preview.setPlainText(approval.preview)
        self._approval_box.setVisible(True)
        self._notify("agent 已暂停", f"{approval.tool} 等待你确认")

    def _on_question(self, question: Question) -> None:
        self._pending_approval = None
        self._approval_box.setVisible(False)
        self._pending_question = question
        self._question_text.setText(question.text)
        self._set_question_options(question.options)
        self._question_input.clear()
        self._question_box.setVisible(True)
        self._question_input.setFocus()
        self._notify("agent 已暂停", "等待你回答问题")

    def _set_question_options(self, options: tuple[str, ...]) -> None:
        while self._question_options_layout.count():
            item = self._question_options_layout.takeAt(0)
            if item is None:
                break
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._option_buttons = []
        for option in options[:8]:
            button = QPushButton(option, self._question_options)
            button.setObjectName("Ghost")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda _checked=False, text=option: self._submit_answer(text)
            )
            self._question_options_layout.addWidget(button)
            self._option_buttons.append(button)
        self._question_options_layout.addStretch(1)
        self._question_options.setVisible(bool(options))

    def _submit_answer(self, text: str) -> None:
        question = self._pending_question
        answer = text.strip()
        if question is None or not answer:
            return
        # 先清 pending 再拉起协程，避免双击重复 resume
        self._pending_question = None
        self._question_box.setVisible(False)
        self._question_input.clear()
        self._append("我", answer)
        self._vm.answer_question(question, answer)

    def _resolve(self, approved: bool) -> None:
        if self._pending_approval is None:
            return
        self._approval_box.setVisible(False)
        self._vm.resolve_approval(self._pending_approval.id, approved)
        self._pending_approval = None

    def _on_run_finished(self, iterations: int) -> None:
        self._pending_approval = None
        self._pending_question = None
        self._approval_box.setVisible(False)
        self._question_box.setVisible(False)
        self._notify("agent 已停止", f"本轮工作结束（共 {iterations} 轮）")

    def _on_agent_error(self, message: str) -> None:
        self._append("错误", message)
        self._notify("agent 已停止", "运行出错，已终止")

    def _notify(self, title: str, body: str) -> None:
        """应用内浮层提醒；窗口不在前台时尽力置前并闪烁任务栏。"""
        self._toast.show_message(title, body)
        if not self.isVisible() or self.isActiveWindow():
            return
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()
        QApplication.alert(self, 0)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        toast = getattr(self, "_toast", None)
        if toast is not None:
            toast.reposition()

    def _on_busy(self, busy: bool) -> None:
        self._chat.set_busy(busy)
        self.statusBar().showMessage("运行中…" if busy else "就绪")

    def _on_error(self, message: str) -> None:
        self._append("错误", message)

    def _open_file_tab(self, path: str, content: str) -> None:
        self._tabs.open_file(path, content)

    def _append(self, who: str, text: str) -> None:
        self._chat.add_message(who, text)

    def closeEvent(self, event: QCloseEvent) -> None:
        super().closeEvent(event)
        self.closed.emit()

    # --- 无边框窗口：拖动/缩放 ---

    def _toggle_maximize(self) -> None:
        """最大化/还原，并切换 Root 的圆角与边距。"""
        maximize = not self.isMaximized()
        if maximize:
            self.showMaximized()
        else:
            self.showNormal()
        # 最大化时去掉圆角与外边距，避免露缝
        self._root.setProperty("maximized", "true" if maximize else "false")
        self._root.style().unpolish(self._root)
        self._root.style().polish(self._root)
        _apply_margins(self._outer, 0 if maximize else _RESIZE_MARGIN)

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
