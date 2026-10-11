"""对话用例：新建会话、发起对话、处理确认。

只依赖 domain/ports 抽象；编排 AgentOrchestrator 的事件流并落库。见规范 §2。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from pathlib import Path
from uuid import uuid4

from codepilot.application.event_bus import EventBus
from codepilot.application.events import RunStarted, SessionCreated
from codepilot.core.errors import NotFoundError
from codepilot.core.paths import ensure_allowed
from codepilot.domain.entities import Message, Session
from codepilot.domain.enums import MessageRole
from codepilot.domain.events import (
    AgentEvent,
    ApprovalRequiredEvent,
    MessageEvent,
    RunFinishedEvent,
)
from codepilot.domain.ports import (
    AgentOrchestrator,
    ApprovalRepository,
    MessageRepository,
    SessionRepository,
)


class ChatService:
    def __init__(
        self,
        *,
        sessions: SessionRepository,
        messages: MessageRepository,
        approvals: ApprovalRepository,
        orchestrator: AgentOrchestrator,
        bus: EventBus,
        allowlist: Iterable[str | Path],
        default_model: str,
    ) -> None:
        self._sessions = sessions
        self._messages = messages
        self._approvals = approvals
        self._orchestrator = orchestrator
        self._bus = bus
        self._allowlist = list(allowlist)
        self._default_model = default_model

    async def list_sessions(self) -> list[Session]:
        return await self._sessions.list()

    async def create_session(
        self,
        *,
        workspace_path: str | Path,
        title: str = "",
        model: str | None = None,
    ) -> Session:
        workspace = ensure_allowed(workspace_path, self._allowlist)
        path = Path(workspace)
        session = Session(
            id=uuid4().hex,
            title=title or path.name or str(path),
            workspace_path=str(path),
            model=model or self._default_model,
        )
        await self._sessions.add(session)
        self._bus.publish(SessionCreated(session))
        return session

    async def send(self, session_id: str, text: str) -> None:
        session = await self._require_session(session_id)
        await self._messages.append(
            session_id, Message(role=MessageRole.USER, content=text)
        )
        history = await self._messages.list(session_id)
        run_id = uuid4().hex
        self._bus.publish(RunStarted(run_id=run_id, session_id=session_id))
        events = self._orchestrator.stream(
            run_id=run_id,
            session_id=session_id,
            model=session.model,
            messages=history,
            workspace_path=session.workspace_path,
        )
        await self._drive(events, session)

    async def resolve_approval(self, approval_id: str, *, approved: bool) -> None:
        approval = await self._approvals.get(approval_id)
        if approval is None:
            raise NotFoundError(f"审批不存在：{approval_id}")
        await self._approvals.resolve(approval_id, approved=approved)
        session = await self._require_session(approval.session_id)
        events = self._orchestrator.resume(approval.run_id, approved=approved)
        await self._drive(events, session)

    # --- 内部 ---

    async def _require_session(self, session_id: str) -> Session:
        session = await self._sessions.get(session_id)
        if session is None:
            raise NotFoundError(f"会话不存在：{session_id}")
        return session

    async def _drive(self, events: AsyncIterator[AgentEvent], session: Session) -> None:
        final_text = ""
        async for event in events:
            self._bus.publish(event)
            if isinstance(event, MessageEvent) and event.content:
                final_text = event.content
            elif isinstance(event, ApprovalRequiredEvent):
                await self._approvals.add(event.approval)
            elif isinstance(event, RunFinishedEvent) and final_text:
                await self._messages.append(
                    session.id,
                    Message(role=MessageRole.ASSISTANT, content=final_text),
                )
                final_text = ""
