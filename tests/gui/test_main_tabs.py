"""主区标签页测试：开文件、脏标记、保存信号、关闭行为。"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from codepilot.ui.views.main_tabs import MainTabs


def _tabs(qtbot) -> MainTabs:
    chat = QWidget()
    tabs = MainTabs(chat)
    qtbot.addWidget(tabs)
    return tabs


def test_open_file_adds_tab_and_focuses(qtbot) -> None:
    tabs = _tabs(qtbot)

    tabs.open_file("src/a.py", "print(1)")

    assert tabs.count() == 2
    assert tabs.tabText(1) == "a.py"
    assert tabs.currentWidget() is tabs._editors["src/a.py"]
    assert tabs._editors["src/a.py"].toPlainText() == "print(1)"


def test_open_same_file_reuses_tab(qtbot) -> None:
    tabs = _tabs(qtbot)

    tabs.open_file("a.py", "x")
    tabs.open_file("a.py", "y")

    assert tabs.count() == 2
    assert tabs._editors["a.py"].toPlainText() == "x"  # 已打开则不再覆盖


def test_edit_marks_dirty_and_save_emits(qtbot) -> None:
    tabs = _tabs(qtbot)
    tabs.open_file("a.py", "x")
    emitted: list[tuple[str, str]] = []
    tabs.saveRequested.connect(lambda p, c: emitted.append((p, c)))

    editor = tabs._editors["a.py"]
    editor.document().setModified(True)
    assert tabs.tabText(1) == "● a.py"

    tabs._request_save("a.py", editor)
    assert emitted == [("a.py", "x")]

    tabs.mark_saved("a.py")
    assert tabs.tabText(1) == "a.py"


def test_chat_tab_cannot_be_closed(qtbot) -> None:
    tabs = _tabs(qtbot)

    tabs._on_close_requested(0)

    assert tabs.count() == 1


def test_closing_file_tab_removes_editor(qtbot) -> None:
    tabs = _tabs(qtbot)
    tabs.open_file("a.py", "x")

    tabs._on_close_requested(1)

    assert tabs.count() == 1
    assert "a.py" not in tabs._editors


def test_show_chat_focuses_first_tab(qtbot) -> None:
    tabs = _tabs(qtbot)
    tabs.open_file("a.py", "x")

    tabs.show_chat()

    assert tabs.currentIndex() == 0
