"""文件树懒加载测试。"""

from __future__ import annotations

from codepilot.domain.entities import WorkspaceEntry
from codepilot.ui.views.file_tree import FileTreePanel


def test_reset_seeds_root_and_requests_root_dir(qtbot) -> None:
    panel = FileTreePanel()
    qtbot.addWidget(panel)
    requested: list[str] = []
    panel.directoryExpandRequested.connect(requested.append)

    panel.reset("proj")

    assert panel._tree.topLevelItemCount() == 1
    assert panel._tree.topLevelItem(0).text(0) == "proj"
    assert requested == ["."]  # 根展开即请求根目录


def test_set_entries_populates_lazily(qtbot) -> None:
    panel = FileTreePanel()
    qtbot.addWidget(panel)
    panel.reset("proj")
    root = panel._tree.topLevelItem(0)

    panel.set_entries(
        ".",
        [
            WorkspaceEntry(name="src", path="src", is_dir=True),
            WorkspaceEntry(name="a.py", path="a.py", is_dir=False),
        ],
    )

    assert root.childCount() == 2
    assert root.child(0).text(0) == "src"
    assert root.child(1).text(0) == "a.py"
    # 目录带占位子节点，文件不带
    assert root.child(0).childCount() == 1
    assert root.child(1).childCount() == 0


def test_file_activation_emits_path(qtbot) -> None:
    panel = FileTreePanel()
    qtbot.addWidget(panel)
    activated: list[str] = []
    panel.fileActivated.connect(activated.append)
    panel.reset("proj")
    panel.set_entries(".", [WorkspaceEntry(name="a.py", path="a.py", is_dir=False)])

    item = panel._tree.topLevelItem(0).child(0)
    panel._on_activated(item)

    assert activated == ["a.py"]


def test_expanding_dir_requests_its_path(qtbot) -> None:
    panel = FileTreePanel()
    qtbot.addWidget(panel)
    expanded: list[str] = []
    panel.directoryExpandRequested.connect(expanded.append)
    panel.reset("proj")
    expanded.clear()
    panel.set_entries(".", [WorkspaceEntry(name="src", path="src", is_dir=True)])

    panel._on_expanded(panel._tree.topLevelItem(0).child(0))

    assert expanded == ["src"]
