"""主区标签页：对话标签 + 每个打开文件一个标签（仿 VSCode 编辑器）。

只管理标签与编辑器；读写经信号交给上层。对话标签不可关闭。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QTabBar, QTabWidget, QWidget

from codepilot.ui.views.code_editor import CodeEditor


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1] or path


class MainTabs(QTabWidget):
    saveRequested = Signal(str, str)  # path, content

    def __init__(self, chat: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MainTabs")
        self.setDocumentMode(True)
        self.setMovable(True)
        self.setTabsClosable(True)
        self._chat = chat
        self._editors: dict[str, CodeEditor] = {}

        self.addTab(chat, "对话")
        # 对话标签不留关闭按钮
        self.tabBar().setTabButton(
            self.indexOf(chat), QTabBar.ButtonPosition.RightSide, None
        )
        self.tabCloseRequested.connect(self._on_close_requested)

    def open_file(self, path: str, content: str) -> None:
        """打开（或聚焦）某文件的标签页。"""
        editor = self._editors.get(path)
        if editor is None:
            editor = CodeEditor(self)
            editor.setPlainText(content)
            editor.document().setModified(False)
            editor.document().modificationChanged.connect(
                lambda modified, p=path: self._mark_dirty(p, modified)
            )
            self._editors[path] = editor
            index = self.addTab(editor, _basename(path))
            self.setTabToolTip(index, path)
            QShortcut(
                QKeySequence.StandardKey.Save,
                editor,
                lambda e=editor, p=path: self._request_save(p, e),
            )
        self.setCurrentWidget(editor)

    def mark_saved(self, path: str) -> None:
        editor = self._editors.get(path)
        if editor is not None:
            editor.document().setModified(False)

    def show_chat(self) -> None:
        self.setCurrentWidget(self._chat)

    # --- 内部 ---

    def _mark_dirty(self, path: str, modified: bool) -> None:
        editor = self._editors.get(path)
        if editor is None:
            return
        index = self.indexOf(editor)
        prefix = "● " if modified else ""
        self.setTabText(index, f"{prefix}{_basename(path)}")

    def _request_save(self, path: str, editor: CodeEditor) -> None:
        self.saveRequested.emit(path, editor.toPlainText())

    def _on_close_requested(self, index: int) -> None:
        widget = self.widget(index)
        if widget is None or widget is self._chat:
            return
        if isinstance(widget, CodeEditor):
            for path, editor in list(self._editors.items()):
                if editor is widget:
                    del self._editors[path]
                    break
        self.removeTab(index)
        widget.deleteLater()
