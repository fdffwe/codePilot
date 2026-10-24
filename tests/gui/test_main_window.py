"""主窗口冒烟测试（offscreen）：装配 ViewModel + 事件桥后能构建并有基本交互。"""

from __future__ import annotations

import asyncio

import pytest

from codepilot.application.event_bus import EventBus
from codepilot.core.config import Settings
from codepilot.domain.entities import Approval, Question, Session
from codepilot.ui.bridge import EventBridge
from codepilot.ui.main_window import MainWindow
from codepilot.ui.viewmodels import ChatViewModel
from codepilot.ui.views import Toast


class StubChatService:
    """只提供界面所需的只读接口与回答记录。"""

    def __init__(self, sessions: list[Session]) -> None:
        self._sessions = sessions
        self.answered: list[tuple[str, str, str]] = []

    async def list_sessions(self) -> list[Session]:
        return list(self._sessions)

    async def answer_question(self, session_id: str, run_id: str, text: str) -> None:
        self.answered.append((session_id, run_id, text))


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


@pytest.mark.asyncio
async def test_question_card_submit_option_calls_service(qtbot, tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / ".codepilot")
    service = StubChatService([])
    window = MainWindow(settings, ChatViewModel(service), EventBridge(EventBus()))  # type: ignore[arg-type]
    qtbot.addWidget(window)
    question = Question(
        id="q1",
        session_id="s1",
        run_id="r1",
        text="用哪个名字？",
        options=("alpha", "beta"),
    )

    window._on_question(question)
    assert window._pending_question is question
    assert window._question_text.text() == "用哪个名字？"
    assert len(window._option_buttons) == 2
    assert not window._question_box.isHidden()

    window._option_buttons[1].click()
    await asyncio.sleep(0)

    assert service.answered == [("s1", "r1", "beta")]
    assert window._pending_question is None
    assert window._question_box.isHidden()


@pytest.mark.asyncio
async def test_question_blank_answer_is_ignored(qtbot, tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / ".codepilot")
    service = StubChatService([])
    window = MainWindow(settings, ChatViewModel(service), EventBridge(EventBus()))  # type: ignore[arg-type]
    qtbot.addWidget(window)

    window._on_question(Question(id="q1", session_id="s1", run_id="r1", text="？"))
    window._question_input.setText("   ")
    window._question_submit.click()
    await asyncio.sleep(0)

    assert service.answered == []
    assert window._pending_question is not None
    assert not window._question_box.isHidden()


@pytest.mark.asyncio
async def test_question_and_approval_cards_are_exclusive(qtbot, tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / ".codepilot")
    window = MainWindow(
        settings, ChatViewModel(StubChatService([])), EventBridge(EventBus())  # type: ignore[arg-type]
    )
    qtbot.addWidget(window)

    window._on_question(Question(id="q1", session_id="s1", run_id="r1", text="？"))
    window._on_approval(
        Approval(
            id="a1",
            session_id="s1",
            run_id="r2",
            tool="write_file",
            payload={},
            preview="+ x",
        )
    )
    assert window._pending_question is None
    assert window._question_box.isHidden()
    assert not window._approval_box.isHidden()


@pytest.mark.asyncio
async def test_run_finished_notifies_and_clears_question(qtbot, tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / ".codepilot")
    window = MainWindow(
        settings, ChatViewModel(StubChatService([])), EventBridge(EventBus())  # type: ignore[arg-type]
    )
    qtbot.addWidget(window)

    window._on_question(Question(id="q1", session_id="s1", run_id="r1", text="？"))
    window._on_run_finished(4)

    assert window._pending_question is None
    assert window._question_box.isHidden()
    assert window._toast.title == "agent 已停止"
    assert "4" in window._toast.body


def test_toast_auto_hides(qtbot) -> None:
    toast = Toast(timeout_ms=20)
    qtbot.addWidget(toast)

    toast.show_message("完成", "ok")
    assert not toast.isHidden()

    qtbot.wait(100)
    assert toast.isHidden()
