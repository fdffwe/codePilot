"""主窗口（P1 最小集）。

会话列表 + 对话视图 + 目录选择 + 确认卡片 + 终端输出。
Widget 只渲染与转发用户输入，逻辑经 ChatViewModel → application。见规范 §15。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
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
        self.resize(1100, 720)
        self._build_ui()
        self._connect()
        self._vm.load_sessions()

    # --- 构建 ---

    def _build_ui(self) -> None:
        central = QWidget(self)
        root = QHBoxLayout(central)
        root.addWidget(self._build_sidebar(), 0)
        root.addWidget(self._build_conversation(), 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage(
            f"数据目录：{self._settings.data_dir}  |  模型：{self._settings.llm_model}"
        )

    def _build_sidebar(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.addWidget(QLabel("会话", panel))
        self._new_button = QPushButton("新建会话…", panel)
        layout.addWidget(self._new_button)
        self._sessions = QListWidget(panel)
        layout.addWidget(self._sessions, 1)
        panel.setFixedWidth(240)
        return panel

    def _build_conversation(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)

        self._transcript = QTextEdit(panel)
        self._transcript.setReadOnly(True)
        layout.addWidget(self._transcript, 1)

        self._approval_box = self._build_approval_box(panel)
        self._approval_box.setVisible(False)
        layout.addWidget(self._approval_box)

        row = QHBoxLayout()
        self._input = QLineEdit(panel)
        self._input.setPlaceholderText("描述你的需求，回车发送…")
        self._send_button = QPushButton("发送", panel)
        row.addWidget(self._input, 1)
        row.addWidget(self._send_button, 0)
        layout.addLayout(row)
        return panel

    def _build_approval_box(self, parent: QWidget) -> QGroupBox:
        box = QGroupBox("需要确认", parent)
        layout = QVBoxLayout(box)
        self._approval_label = QLabel(box)
        self._approval_preview = QTextEdit(box)
        self._approval_preview.setReadOnly(True)
        self._approval_preview.setFixedHeight(120)
        buttons = QHBoxLayout()
        self._allow_button = QPushButton("允许", box)
        self._reject_button = QPushButton("拒绝", box)
        buttons.addStretch(1)
        buttons.addWidget(self._allow_button)
        buttons.addWidget(self._reject_button)
        layout.addWidget(self._approval_label)
        layout.addWidget(self._approval_preview)
        layout.addLayout(buttons)
        return box

    # --- 连接 ---

    def _connect(self) -> None:
        self._new_button.clicked.connect(self._on_new_session)
        self._send_button.clicked.connect(self._on_send)
        self._input.returnPressed.connect(self._on_send)
        self._sessions.itemClicked.connect(self._on_session_clicked)
        self._allow_button.clicked.connect(lambda: self._resolve(True))
        self._reject_button.clicked.connect(lambda: self._resolve(False))

        self._vm.sessionsChanged.connect(self._on_sessions_changed)
        self._vm.errorOccurred.connect(self._on_error)
        self._vm.busyChanged.connect(self._on_busy)

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

    def _on_send(self) -> None:
        text = self._input.text()
        if not text.strip():
            return
        self._append("我", text)
        self._input.clear()
        self._vm.send(text)

    def _on_session_clicked(self, item: QListWidgetItem) -> None:
        session = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(session, Session):
            self._vm.open_session(session)
            self._transcript.append(
                f"—— 已打开会话：{session.title}（{session.workspace_path}）——"
            )

    def _on_sessions_changed(self, sessions: list[Session]) -> None:
        self._sessions.clear()
        for session in sessions:
            item = QListWidgetItem(session.title)
            item.setData(Qt.ItemDataRole.UserRole, session)
            self._sessions.addItem(item)

    def _on_tool_result(self, output: str, ok: bool) -> None:
        mark = "输出" if ok else "输出(失败)"
        self._append(mark, output)

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
        self._send_button.setEnabled(not busy)
        self._input.setEnabled(not busy)
        self.statusBar().showMessage("运行中…" if busy else "就绪")

    def _on_error(self, message: str) -> None:
        self._append("错误", message)

    def _append(self, who: str, text: str) -> None:
        self._transcript.append(f"[{who}] {text}")
