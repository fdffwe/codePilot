"""设置面板测试：模式下拉、白名单入口与会话信息。"""

from __future__ import annotations

from codepilot.domain.entities import Session
from codepilot.ui.views.settings_panel import SettingsPanel


def _panel(qtbot) -> SettingsPanel:
    panel = SettingsPanel(
        approval_mode="default",
        user_permissions_path="/home/u/.codepilot/permissions.json",
    )
    qtbot.addWidget(panel)
    return panel


def _index_of(panel: SettingsPanel, mode: str) -> int:
    for index in range(panel._mode.count()):
        if panel._mode.itemData(index) == mode:
            return index
    raise AssertionError(mode)


def test_initial_mode_is_selected_without_signal(qtbot) -> None:
    panel = _panel(qtbot)
    emitted: list[str] = []
    panel.modeChanged.connect(emitted.append)

    panel.set_mode("yolo")

    assert panel._mode.itemData(panel._mode.currentIndex()) == "yolo"
    assert "全部放行" in panel._description.text()
    assert emitted == []


def test_changing_combo_emits_mode(qtbot) -> None:
    panel = _panel(qtbot)
    emitted: list[str] = []
    panel.modeChanged.connect(emitted.append)

    panel._mode.setCurrentIndex(_index_of(panel, "plan"))

    assert emitted == ["plan"]
    assert "一律拒绝" in panel._description.text()


def test_edit_permissions_button_emits(qtbot) -> None:
    panel = _panel(qtbot)
    emitted: list[bool] = []
    panel.editPermissionsRequested.connect(lambda: emitted.append(True))

    panel._edit_permissions.click()

    assert emitted == [True]


def test_set_session_updates_info(qtbot, tmp_path) -> None:
    panel = _panel(qtbot)

    panel.set_session(
        Session(id="s1", title="t", workspace_path=str(tmp_path), model="deepseek")
    )
    assert str(tmp_path) in panel._workspace.text()
    assert "deepseek" in panel._model.text()

    panel.set_session(None)
    assert "未选择会话" in panel._workspace.text()
    assert "—" in panel._model.text()
