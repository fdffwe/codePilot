"""ChatService 单测（内存替身 + 脚本化 orchestrator）。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from codepilot.application.chat_service import ChatService
from codepilot.application.event_bus import EventBus
from codepilot.application.events import RunStarted
from codepilot.core.errors import (
    DomainError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from codepilot.domain.entities import Approval, Message, Question, Session, ToolCall
from codepilot.domain.enums import MessageRole
from codepilot.domain.events import (
    AgentEvent,
    ApprovalRequiredEvent,
    ApprovalsRequiredEvent,
    MessageEvent,
    QuestionRequiredEvent,
    RunFinishedEvent,
)


class InMemorySessions:
    def __init__(self) -> None:
        self.data: dict[str, Session] = {}

    async def add(self, session: Session) -> None:
        self.data[session.id] = session

    async def update(self, session: Session) -> None:
        self.data[session.id] = session

    async def get(self, session_id: str) -> Session | None:
        return self.data.get(session_id)

    async def list(self) -> list[Session]:
        return list(self.data.values())


class InMemoryMessages:
    def __init__(self) -> None:
        self.data: dict[str, list[Message]] = {}

    async def append(self, session_id: str, message: Message) -> None:
        self.data.setdefault(session_id, []).append(message)

    async def list(self, session_id: str) -> list[Message]:
        return list(self.data.get(session_id, []))


class InMemoryApprovals:
    def __init__(self) -> None:
        self.data: dict[str, Approval] = {}

    async def add(self, approval: Approval) -> None:
        self.data[approval.id] = approval

    async def get(self, approval_id: str) -> Approval | None:
        return self.data.get(approval_id)

    async def resolve(self, approval_id: str, *, approved: bool) -> None:
        if approval_id in self.data:
            self.data[approval_id].status = (
                "approved" if approved else "rejected"  # type: ignore[assignment]
            )

    async def list_pending(self, session_id: str) -> list[Approval]:
        return [a for a in self.data.values() if a.session_id == session_id]


class FakeOrchestrator:
    def __init__(self, first: list[AgentEvent], second: list[AgentEvent]) -> None:
        self._first = first
        self._second = second
        self.resumed: list[tuple[str, bool]] = []
        self.answered: list[tuple[str, str]] = []
        self.remembered: list[tuple[str, str, dict[str, object]]] = []

    def _bind(self, event: AgentEvent, run_id: str, session_id: str) -> AgentEvent:
        if isinstance(event, ApprovalRequiredEvent):
            approval = replace(event.approval, run_id=run_id, session_id=session_id)
            return replace(event, run_id=run_id, approval=approval)
        if isinstance(event, ApprovalsRequiredEvent):
            approvals = tuple(
                replace(a, run_id=run_id, session_id=session_id)
                for a in event.approvals
            )
            return replace(event, run_id=run_id, approvals=approvals)
        if isinstance(event, QuestionRequiredEvent):
            question = replace(event.question, run_id=run_id, session_id=session_id)
            return replace(event, run_id=run_id, question=question)
        return replace(event, run_id=run_id)

    async def stream(
        self,
        *,
        run_id: str,
        session_id: str,
        model: str,
        messages: Sequence[Message],
        workspace_path: str,
    ) -> AsyncIterator[AgentEvent]:
        for event in self._first:
            yield self._bind(event, run_id, session_id)

    async def resume(self, run_id: str, *, approved: bool) -> AsyncIterator[AgentEvent]:
        self.resumed.append((run_id, approved))
        for event in self._second:
            yield replace(event, run_id=run_id)

    async def answer(self, run_id: str, *, text: str) -> AsyncIterator[AgentEvent]:
        self.answered.append((run_id, text))
        for event in self._second:
            yield replace(event, run_id=run_id)

    def remember_approval(
        self, session_id: str, tool: str, arguments: dict[str, object]
    ) -> None:
        self.remembered.append((session_id, tool, dict(arguments)))


def _service(
    orchestrator: FakeOrchestrator,
    *,
    allowlist: list[Path],
    bus: EventBus | None = None,
) -> tuple[ChatService, InMemoryMessages, InMemoryApprovals, EventBus]:
    messages = InMemoryMessages()
    approvals = InMemoryApprovals()
    event_bus = bus or EventBus()
    service = ChatService(
        sessions=InMemorySessions(),
        messages=messages,
        approvals=approvals,
        orchestrator=orchestrator,
        bus=event_bus,
        allowlist=allowlist,
        default_model="fake",
    )
    return service, messages, approvals, event_bus


async def test_create_session_persists_and_publishes(tmp_path: Path) -> None:
    service, _, _, bus = _service(FakeOrchestrator([], []), allowlist=[tmp_path])
    seen: list[object] = []
    bus.subscribe(seen.append)

    session = await service.create_session(workspace_path=tmp_path)

    assert session.workspace_path == str(tmp_path.resolve())
    assert any(ev.__class__.__name__ == "SessionCreated" for ev in seen)
    assert [s.id for s in await service.list_sessions()] == [session.id]


async def test_create_session_rejects_disallowed_path(tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    service, _, _, _ = _service(FakeOrchestrator([], []), allowlist=[other])
    with pytest.raises(PermissionDeniedError):
        await service.create_session(workspace_path=tmp_path)


async def test_send_persists_user_and_assistant(tmp_path: Path) -> None:
    orchestrator = FakeOrchestrator(
        [
            MessageEvent(run_id="r", seq=0, content="你好"),
            RunFinishedEvent(run_id="r", seq=1, iterations=1),
        ],
        [],
    )
    service, messages, _, bus = _service(orchestrator, allowlist=[tmp_path])
    seen: list[object] = []
    bus.subscribe(seen.append)

    session = await service.create_session(workspace_path=tmp_path)
    await service.send(session.id, "帮我做点事")

    stored = await messages.list(session.id)
    assert [m.role for m in stored] == [MessageRole.USER, MessageRole.ASSISTANT]
    assert stored[1].content == "你好"
    assert any(isinstance(ev, RunStarted) for ev in seen)


async def test_send_surfaces_approval_and_resolve_continues(tmp_path: Path) -> None:
    call = ToolCall(id="c1", name="write_file", arguments={"path": "a.py"})
    approval = Approval(
        id="a1",
        session_id="",
        run_id="r",
        tool="write_file",
        payload={"path": "a.py"},
        preview="+ x",
    )
    orchestrator = FakeOrchestrator(
        [
            MessageEvent(run_id="r", seq=0, content="", tool_calls=(call,)),
            ApprovalRequiredEvent(run_id="r", seq=1, approval=approval),
        ],
        [
            MessageEvent(run_id="r", seq=0, content="写好了"),
            RunFinishedEvent(run_id="r", seq=1, iterations=2),
        ],
    )
    service, messages, approvals, _ = _service(orchestrator, allowlist=[tmp_path])
    session = await service.create_session(workspace_path=tmp_path)

    await service.send(session.id, "写个文件")
    assert await approvals.get("a1") is not None
    # 暂停时只有用户消息入库
    assert [m.role for m in await messages.list(session.id)] == [MessageRole.USER]

    await service.resolve_approval("a1", approved=True)
    resolved = await approvals.get("a1")
    assert resolved is not None
    assert orchestrator.resumed == [(resolved.run_id, True)]
    stored = await messages.list(session.id)
    assert stored[-1].role == MessageRole.ASSISTANT
    assert stored[-1].content == "写好了"


async def test_resolve_approval_can_remember_for_session(tmp_path: Path) -> None:
    call = ToolCall(id="c1", name="write_file", arguments={"path": "a.py"})
    approval = Approval(
        id="a1",
        session_id="",
        run_id="r",
        tool="write_file",
        payload={"path": "a.py"},
        preview="+ x",
    )
    orchestrator = FakeOrchestrator(
        [
            MessageEvent(run_id="r", seq=0, content="", tool_calls=(call,)),
            ApprovalRequiredEvent(run_id="r", seq=1, approval=approval),
        ],
        [RunFinishedEvent(run_id="r", seq=0, iterations=1)],
    )
    service, _, _, _ = _service(orchestrator, allowlist=[tmp_path])
    session = await service.create_session(workspace_path=tmp_path)
    await service.send(session.id, "写个文件")

    await service.resolve_approval("a1", approved=True, remember=True)

    assert orchestrator.remembered == [(session.id, "write_file", {"path": "a.py"})]


async def test_rejected_approval_is_not_remembered(tmp_path: Path) -> None:
    approval = Approval(
        id="a1",
        session_id="",
        run_id="r",
        tool="write_file",
        payload={"path": "a.py"},
        preview="+ x",
    )
    orchestrator = FakeOrchestrator(
        [ApprovalRequiredEvent(run_id="r", seq=0, approval=approval)],
        [RunFinishedEvent(run_id="r", seq=0, iterations=1)],
    )
    service, _, _, _ = _service(orchestrator, allowlist=[tmp_path])
    session = await service.create_session(workspace_path=tmp_path)
    await service.send(session.id, "写个文件")

    await service.resolve_approval("a1", approved=False, remember=True)

    assert orchestrator.remembered == []


async def test_resolve_approvals_handles_batch_and_resumes_once(
    tmp_path: Path,
) -> None:
    approvals = (
        Approval(
            id="a1",
            session_id="",
            run_id="r",
            tool="write_file",
            payload={"path": "a.py"},
            preview="+ a",
        ),
        Approval(
            id="a2",
            session_id="",
            run_id="r",
            tool="write_file",
            payload={"path": "b.py"},
            preview="+ b",
        ),
    )
    orchestrator = FakeOrchestrator(
        [ApprovalsRequiredEvent(run_id="r", seq=0, approvals=approvals)],
        [RunFinishedEvent(run_id="r", seq=0, iterations=1)],
    )
    service, _, repo, _ = _service(orchestrator, allowlist=[tmp_path])
    session = await service.create_session(workspace_path=tmp_path)
    await service.send(session.id, "写两个文件")
    assert set(repo.data) == {"a1", "a2"}

    await service.resolve_approvals(["a1", "a2"], approved=True, remember=True)

    assert repo.data["a1"].status == "approved"
    assert repo.data["a2"].status == "approved"
    assert orchestrator.resumed == [(repo.data["a1"].run_id, True)]
    assert orchestrator.remembered == [
        (session.id, "write_file", {"path": "a.py"}),
        (session.id, "write_file", {"path": "b.py"}),
    ]


async def test_resolve_approvals_rejects_cross_run_batch(tmp_path: Path) -> None:
    orchestrator = FakeOrchestrator([], [])
    service, _, repo, _ = _service(orchestrator, allowlist=[tmp_path])
    session = await service.create_session(workspace_path=tmp_path)
    for approval_id, run_id in (("a1", "r1"), ("a2", "r2")):
        await repo.add(
            Approval(
                id=approval_id,
                session_id=session.id,
                run_id=run_id,
                tool="write_file",
                payload={},
                preview="",
            )
        )

    with pytest.raises(ValidationError):
        await service.resolve_approvals(["a1", "a2"], approved=True)
    assert orchestrator.resumed == []


async def test_question_surfaces_not_persisted_and_answer_continues(
    tmp_path: Path,
) -> None:
    call = ToolCall(id="c1", name="ask_user", arguments={"question": "用哪个？"})
    question = Question(
        id="q1",
        session_id="",
        run_id="r",
        text="用哪个？",
        options=("alpha", "beta"),
    )
    orchestrator = FakeOrchestrator(
        [
            MessageEvent(run_id="r", seq=0, content="", tool_calls=(call,)),
            QuestionRequiredEvent(run_id="r", seq=1, question=question),
        ],
        [
            MessageEvent(run_id="r", seq=0, content="好的，用 alpha"),
            RunFinishedEvent(run_id="r", seq=1, iterations=2),
        ],
    )
    service, messages, approvals, bus = _service(orchestrator, allowlist=[tmp_path])
    seen: list[object] = []
    bus.subscribe(seen.append)
    session = await service.create_session(workspace_path=tmp_path)

    await service.send(session.id, "改代码")
    surfaced = next(e for e in seen if isinstance(e, QuestionRequiredEvent))
    assert surfaced.question.session_id == session.id
    # 提问广播、不落审批表；暂停时只有用户消息入库
    assert approvals.data == {}
    assert [m.role for m in await messages.list(session.id)] == [MessageRole.USER]

    await service.answer_question(session.id, surfaced.run_id, "alpha")
    assert orchestrator.answered == [(surfaced.run_id, "alpha")]
    stored = await messages.list(session.id)
    assert stored[-1].role == MessageRole.ASSISTANT
    assert stored[-1].content == "好的，用 alpha"


async def test_empty_answer_is_rejected(tmp_path: Path) -> None:
    service, _, _, _ = _service(FakeOrchestrator([], []), allowlist=[tmp_path])
    session = await service.create_session(workspace_path=tmp_path)
    with pytest.raises(ValidationError):
        await service.answer_question(session.id, "r1", "   ")


async def test_resolve_unknown_approval_raises(tmp_path: Path) -> None:
    service, _, _, _ = _service(FakeOrchestrator([], []), allowlist=[tmp_path])
    with pytest.raises(NotFoundError):
        await service.resolve_approval("nope", approved=True)


async def test_workspace_listing_and_reading_via_factory(tmp_path: Path) -> None:
    from codepilot.infrastructure.workspace import LocalDirectWorkspace

    def factory(path: str) -> LocalDirectWorkspace:
        return LocalDirectWorkspace(path, allowlist=[tmp_path])

    service = ChatService(
        sessions=InMemorySessions(),
        messages=InMemoryMessages(),
        approvals=InMemoryApprovals(),
        orchestrator=FakeOrchestrator([], []),
        bus=EventBus(),
        allowlist=[tmp_path],
        default_model="fake",
        workspace_factory=factory,
    )
    session = await service.create_session(workspace_path=tmp_path)
    await factory(str(tmp_path)).write_text("a.txt", "hello")

    entries = await service.list_workspace_entries(session.id)
    assert [(e.name, e.is_dir) for e in entries] == [("a.txt", False)]
    assert await service.read_workspace_file(session.id, "a.txt") == "hello"

    await service.write_workspace_file(session.id, "a.txt", "改动")
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "改动"


async def test_workspace_methods_require_factory(tmp_path: Path) -> None:
    service, _, _, _ = _service(FakeOrchestrator([], []), allowlist=[tmp_path])
    session = await service.create_session(workspace_path=tmp_path)
    with pytest.raises(DomainError):
        await service.list_workspace_entries(session.id)
