"""工作区文件树：懒加载展开，单击文件请求预览。

只发意图信号；实际读取经 ViewModel → application 层，Widget 不碰文件系统。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from codepilot.domain.entities import WorkspaceEntry

_PATH_ROLE = Qt.ItemDataRole.UserRole


class FileTreePanel(QWidget):
    directoryExpandRequested = Signal(str)  # 工作区相对目录路径
    fileActivated = Signal(str)  # 工作区相对文件路径
    refreshRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setMinimumWidth(200)
        self.setMaximumWidth(320)
        self._loaded: set[str] = set()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 14, 12, 12)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title = QLabel("文件", self)
        title.setObjectName("SidebarTitle")
        self._refresh = QToolButton(self)
        self._refresh.setObjectName("SidebarAction")
        self._refresh.setText("⟳")
        self._refresh.setToolTip("刷新文件树")
        self._refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh.clicked.connect(self.refreshRequested.emit)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self._refresh)
        layout.addLayout(header)

        self._tree = QTreeWidget(self)
        self._tree.setObjectName("FileTree")
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(14)
        self._tree.setAnimated(True)
        self._tree.setUniformRowHeights(True)
        layout.addWidget(self._tree, 1)

        self._tree.itemExpanded.connect(self._on_expanded)
        self._tree.itemActivated.connect(self._on_activated)
        self._tree.itemClicked.connect(self._on_activated)

    # --- 对外槽 ---

    def reset(self, label: str) -> None:
        """打开新会话时重置为单一根节点并展开。"""
        self._loaded.clear()
        self._tree.clear()
        root = QTreeWidgetItem([label])
        root.setData(0, _PATH_ROLE, (".", True))
        self._add_placeholder(root)
        self._tree.addTopLevelItem(root)
        root.setExpanded(True)

    def set_entries(self, path: str, entries: list[WorkspaceEntry]) -> None:
        """用某目录的条目填充对应节点。"""
        self._loaded.add(path)
        parent = self._find(path)
        if parent is None:
            return
        parent.takeChildren()
        for entry in entries:
            child = QTreeWidgetItem([entry.name])
            child.setData(0, _PATH_ROLE, (entry.path, entry.is_dir))
            if entry.is_dir:
                self._add_placeholder(child)
            parent.addChild(child)

    # --- 内部 ---

    def _add_placeholder(self, item: QTreeWidgetItem) -> None:
        # 占位子节点：让目录显示展开箭头；展开时被 set_entries 替换
        item.addChild(QTreeWidgetItem([""]))

    def _find(self, path: str) -> QTreeWidgetItem | None:
        root = self._tree.invisibleRootItem()
        stack: list[QTreeWidgetItem] = []
        for index in range(root.childCount()):
            child = root.child(index)
            if child is not None:
                stack.append(child)
        while stack:
            node = stack.pop()
            data = node.data(0, _PATH_ROLE)
            if data is not None and data[0] == path:
                return node
            for index in range(node.childCount()):
                child = node.child(index)
                if child is not None:
                    stack.append(child)
        return None

    def _on_expanded(self, item: QTreeWidgetItem) -> None:
        data = item.data(0, _PATH_ROLE)
        if data is None or not data[1]:
            return
        path = str(data[0])
        if path not in self._loaded:
            self.directoryExpandRequested.emit(path)

    def _on_activated(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        data = item.data(0, _PATH_ROLE)
        if data is not None and not data[1]:
            self.fileActivated.emit(str(data[0]))
