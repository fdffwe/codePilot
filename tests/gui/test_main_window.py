"""主窗口冒烟测试（offscreen）：装配 ViewModel + 事件桥后能构建并有基本交互。"""

from __future__ import annotations

import asyncio

import pytest

from codepilot.application.event_bus import EventBus
from codepilot.core.config import Settings
from codepilot.domain.approval import ApprovalMode
from codepilot.domain.entities import Approval, Message, Question, Session
from codepilot.domain.enums import MessageRole
from codepilot.ui.bridge import EventBridge
from codepilot.ui.main_window import MainWindow
from codepilot.ui.viewmodels import ChatViewModel
from codepilot.ui.views import Toast


class StubChatService:
    """只提供界面所需的只读接口与回答记录。"""

    def __init__(self, sessions: list[Session]) -> None:
        self._sessions = sessions
        self.answered: list[tuple[str, str, str]] = []
        self.history: dict[str, list[Message]] = {}
        self.permissions = ""
        self.approval_mode = ApprovalMode.DEFAULT

    async def list_sessions(self) -> list[Session]:
        return list(self._sessions)

    async def list_messages(self, session_id: str) -> list[Message]:
        return list(self.history.get(session_id, []))

    async def answer_question(self, session_id: str, run_id: str, text: str) -> None:
        self.answered.append((session_id, run_id, text))

    async def list_workspace_entries(self, session_id: str, path: str = ".") -> list:
        return []

    async def read_workspace_permissions(self, session_id: str) -> str:
        return self.permissions

    def set_approval_mode(self, mode: ApprovalMode) -> None:
        self.approval_mode = mode


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
    assert len(window._pending_approvals) == 1
    assert "write_file" in window._approval_label.text()
    assert window._allow_button.text() == "允许"


@pytest.mark.asyncio
async def test_batch_approval_card_shows_all_items(qtbot, tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / ".codepilot")
    window = MainWindow(
        settings, ChatViewModel(StubChatService([])), EventBridge(EventBus())  # type: ignore[arg-type]
    )
    qtbot.addWidget(window)

    approvals = tuple(
        Approval(
            id=f"a{i}",
            session_id="s1",
            run_id="r1",
            tool="write_file",
            payload={"path": f"{i}.py"},
            preview=f"+ {i}",
            risk=risk,
        )
        for i, risk in ((1, "medium"), (2, "high"))
    )
    window._on_approvals(approvals)

    assert window._pending_approvals == list(approvals)
    assert "2 个操作" in window._approval_label.text()
    assert "high" in window._approval_label.text()
    assert "1.py" not in window._approval_label.text()  # 明细在预览区
    assert "+ 1" in window._approval_preview.toPlainText()
    assert "+ 2" in window._approval_preview.toPlainText()
    assert window._allow_button.text() == "全部允许"
    assert window._reject_button.text() == "全部拒绝"


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
    assert window._pending_approvals
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


@pytest.mark.asyncio
async def test_opening_session_renders_history(qtbot, tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / ".codepilot")
    session = Session(id="s1", title="历史", workspace_path=str(tmp_path), model="m")
    service = StubChatService([session])
    service.history[session.id] = [
        Message(role=MessageRole.USER, content="第一句"),
        Message(role=MessageRole.ASSISTANT, content="第二句"),
    ]
    window = MainWindow(settings, ChatViewModel(service), EventBridge(EventBus()))  # type: ignore[arg-type]
    qtbot.addWidget(window)

    window._on_session_clicked(session)
    await asyncio.sleep(0)

    assert window._current_session is session
    assert window._chat._hint is None
    # 两个气泡 + 尾部 stretch
    assert window._chat._messages.count() == 3
    assert window._sidebar._sessions.currentItem() is not None


@pytest.mark.asyncio
async def test_history_for_other_session_is_ignored(qtbot, tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / ".codepilot")
    session = Session(id="s1", title="历史", workspace_path=str(tmp_path), model="m")
    window = MainWindow(
        settings, ChatViewModel(StubChatService([session])), EventBridge(EventBus())  # type: ignore[arg-type]
    )
    qtbot.addWidget(window)

    window._on_session_opened(session)
    await asyncio.sleep(0)
    window._on_history_loaded(
        "other", [Message(role=MessageRole.USER, content="不该出现")]
    )

    assert window._chat._hint is not None


@pytest.mark.asyncio
async def test_approval_mode_switch_updates_status(qtbot, tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / ".codepilot")
    service = StubChatService([])
    window = MainWindow(
        settings, ChatViewModel(service), EventBridge(EventBus())  # type: ignore[arg-type]
    )
    qtbot.addWidget(window)

    auto_edit = next(
        i
        for i in range(window._settings_panel._mode.count())
        if window._settings_panel._mode.itemData(i) == "auto-edit"
    )
    window._settings_panel._mode.setCurrentIndex(auto_edit)

    assert service.approval_mode is ApprovalMode.AUTO_EDIT
    assert window._approval_mode == "auto-edit"
    assert "auto-edit" in window.statusBar().currentMessage()


@pytest.mark.asyncio
async def test_permissions_loaded_opens_editor_tab(qtbot, tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / ".codepilot")
    window = MainWindow(
        settings, ChatViewModel(StubChatService([])), EventBridge(EventBus())  # type: ignore[arg-type]
    )
    qtbot.addWidget(window)

    window._on_permissions_loaded(".codepilot/permissions.json", '{"permissions": {}}')

    assert window._tabs.count() == 2
    editor = window._tabs._editors[".codepilot/permissions.json"]
    assert editor.toPlainText() == '{"permissions": {}}'
