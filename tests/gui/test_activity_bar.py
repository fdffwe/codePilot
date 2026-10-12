"""活动栏图标切换测试。"""

from __future__ import annotations

from codepilot.ui.views.activity_bar import ActivityBar


def test_click_emits_panel_index(qtbot) -> None:
    bar = ActivityBar()
    qtbot.addWidget(bar)
    seen: list[int] = []
    bar.panelSelected.connect(seen.append)

    bar._group.button(1).click()

    assert seen == [1]
    assert bar._group.button(1).isChecked()


def test_set_current_checks_button(qtbot) -> None:
    bar = ActivityBar()
    qtbot.addWidget(bar)

    bar.set_current(0)

    assert bar._group.button(0).isChecked()
    assert not bar._group.button(1).isChecked()
