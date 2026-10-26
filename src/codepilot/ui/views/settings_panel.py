"""设置面板：审批模式、权限白名单入口与会话信息。

只持有界面状态并发出意图信号；真正切换模式/读取白名单经 ViewModel → application。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from codepilot.domain.entities import Session

# (值, 显示名, 说明)，顺序即下拉顺序
_MODES: tuple[tuple[str, str, str], ...] = (
    ("plan", "只读（plan）", "写文件与执行命令一律拒绝"),
    ("default", "默认（default）", "写文件与执行命令需确认"),
    ("auto-edit", "自动编辑（auto-edit）", "写文件自动放行，执行命令需确认"),
    ("yolo", "全部放行（yolo）", "全部放行，高危命令仍被拒绝"),
)


class SettingsPanel(QWidget):
    modeChanged = Signal(str)  # ApprovalMode.value
    editPermissionsRequested = Signal()

    def __init__(
        self,
        *,
        approval_mode: str,
        user_permissions_path: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Settings")
        self.setFixedWidth(280)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 14, 12, 12)
        outer.setSpacing(10)

        title = QLabel("设置", self)
        title.setObjectName("SidebarTitle")
        outer.addWidget(title)

        scroll = QScrollArea(self)
        scroll.setObjectName("SettingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        body.setObjectName("SettingsBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(6)

        # --- 审批模式 ---
        layout.addWidget(self._section("审批模式"))
        self._mode = QComboBox(body)
        self._mode.setObjectName("SettingsCombo")
        for value, label, _ in _MODES:
            self._mode.addItem(label, value)
        self._description = self._hint(body)
        layout.addWidget(self._mode)
        layout.addWidget(self._description)
        layout.addWidget(
            self._hint(body, "切换后对下一轮对话生效，进行中的 run 不变。")
        )
        self._set_mode(approval_mode)
        self._mode.currentIndexChanged.connect(self._on_mode_index)

        # --- 权限白名单 ---
        layout.addSpacing(8)
        layout.addWidget(self._section("权限白名单"))
        layout.addWidget(
            self._hint(
                body,
                "在工作区 permissions.json 中配置 allow/ask/deny；"
                "命中 allow 的调用免确认，高危命令仍会询问。",
            )
        )
        layout.addWidget(self._path(body, "工作区：.codepilot/permissions.json"))
        self._edit_permissions = QPushButton("编辑工作区白名单", body)
        self._edit_permissions.setObjectName("Ghost")
        self._edit_permissions.setCursor(Qt.CursorShape.PointingHandCursor)
        self._edit_permissions.clicked.connect(self.editPermissionsRequested.emit)
        layout.addWidget(self._edit_permissions)
        layout.addWidget(self._path(body, f"用户级：{user_permissions_path}"))
        layout.addWidget(
            self._hint(body, "用户级文件由外部编辑，改动在下一轮对话生效。")
        )

        # --- 当前会话 ---
        layout.addSpacing(8)
        layout.addWidget(self._section("当前会话"))
        self._workspace = self._value(body, "工作区：未选择会话")
        self._model = self._value(body, "模型：—")
        layout.addWidget(self._workspace)
        layout.addWidget(self._model)

        layout.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

    # --- 对外 ---

    def set_mode(self, mode: str) -> None:
        """外部同步模式（不触发 modeChanged，避免回环）。"""
        self._set_mode(mode)

    def set_session(self, session: Session | None) -> None:
        if session is None:
            self._workspace.setText("工作区：未选择会话")
            self._model.setText("模型：—")
            return
        self._workspace.setText(f"工作区：{session.workspace_path}")
        self._model.setText(f"模型：{session.model}")

    # --- 内部 ---

    def _on_mode_index(self, index: int) -> None:
        value = self._mode.itemData(index)
        if value:
            self._sync_description(str(value))
            self.modeChanged.emit(str(value))

    def _set_mode(self, mode: str) -> None:
        for index in range(self._mode.count()):
            if self._mode.itemData(index) == mode:
                was_blocked = self._mode.blockSignals(True)
                self._mode.setCurrentIndex(index)
                self._mode.blockSignals(was_blocked)
                self._sync_description(mode)
                return

    def _sync_description(self, mode: str) -> None:
        for value, _, description in _MODES:
            if value == mode:
                self._description.setText(description)
                return

    def _section(self, text: str) -> QLabel:
        label = QLabel(text, self)
        label.setObjectName("SettingsSection")
        return label

    def _hint(self, parent: QWidget, text: str = "") -> QLabel:
        label = QLabel(text, parent)
        label.setObjectName("SettingsHint")
        label.setWordWrap(True)
        return label

    def _path(self, parent: QWidget, text: str) -> QLabel:
        label = QLabel(text, parent)
        label.setObjectName("SettingsPath")
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    def _value(self, parent: QWidget, text: str) -> QLabel:
        label = QLabel(text, parent)
        label.setObjectName("SettingsValue")
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label
