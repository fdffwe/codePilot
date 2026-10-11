"""主窗口冒烟测试（offscreen）：装配 ViewModel + 事件桥后能构建并有基本交互。"""

from __future__ import annotations

import asyncio

import pytest

from codepilot.application.event_bus import EventBus
from codepilot.core.config import Settings
from codepilot.domain.entities import Approval, Session
from codepilot.ui.bridge import EventBridge
from codepilot.ui.main_window import MainWindow
from codepilot.ui.viewmodels import ChatViewModel


class StubChatService:
    """只提供界面所需的只读接口。"""

    def __init__(self, sessions: list[Session]) -> None:
        self._sessions = sessions

    async def list_sessions(self) -> list[Session]:
        return list(self._sessions)


@pytest.mark.asyncio
async def test_main_window_builds_and_lists_sessions(qtbot, tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / ".codepilot")
    session = Session(id="s1", title="会话一", workspace_path=str(tmp_path), model="m")
    viewmodel = ChatViewModel(StubChatService([session]))  # type: ignore[arg-type]
    bridge = EventBridge(EventBus())

    window = MainWindow(settings, viewmodel, bridge)
    qtbot.addWidget(window)
    await asyncio.sleep(0)  # 让 load_sessions 的异步任务跑完

    assert "codePilot" in window.windowTitle()
    assert window.centralWidget() is not None
    assert window._sessions.count() == 1
    assert window._sessions.item(0).text() == "会话一"


@pytest.mark.asyncio
async def test_approval_card_reflects_pending(qtbot, tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / ".codepilot")
    viewmodel = ChatViewModel(StubChatService([]))  # type: ignore[arg-type]
    bridge = EventBridge(EventBus())
    window = MainWindow(settings, viewmodel, bridge)
    qtbot.addWidget(window)

    window._on_approval(
        Approval(
            id="a1",
            session_id="s1",
            run_id="r1",
            tool="write_file",
            payload={"path": "a.py"},
            preview="+ x",
        )
    )
    assert window._pending_approval is not None
    assert "write_file" in window._approval_label.text()
