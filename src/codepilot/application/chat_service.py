"""对话用例：新建会话、发起对话、处理确认。

只依赖 domain/ports 抽象；编排 AgentOrchestrator 的事件流并落库。见规范 §2。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterable
from pathlib import Path
from uuid import uuid4

from codepilot.application.event_bus import EventBus
from codepilot.application.events import RunStarted, SessionCreated
from codepilot.core.errors import DomainError, NotFoundError, ValidationError
from codepilot.core.paths import ensure_allowed
from codepilot.domain.entities import Message, Session, WorkspaceEntry
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
    WorkspaceProvider,
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
        workspace_factory: Callable[[str], WorkspaceProvider] | None = None,
    ) -> None:
        self._sessions = sessions
        self._messages = messages
        self._approvals = approvals
        self._orchestrator = orchestrator
        self._bus = bus
        self._allowlist = list(allowlist)
        self._default_model = default_model
        self._workspace_factory = workspace_factory

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

    async def resolve_approval(
        self, approval_id: str, *, approved: bool, remember: bool = False
    ) -> None:
        approval = await self._approvals.get(approval_id)
        if approval is None:
            raise NotFoundError(f"审批不存在：{approval_id}")
        await self._approvals.resolve(approval_id, approved=approved)
        if approved and remember:
            # 只记住用户明确允许的相同操作；拒绝不产生规则
            self._orchestrator.remember_approval(
                approval.session_id, approval.tool, approval.payload
            )
        session = await self._require_session(approval.session_id)
        events = self._orchestrator.resume(approval.run_id, approved=approved)
        await self._drive(events, session)

    async def answer_question(self, session_id: str, run_id: str, text: str) -> None:
        """回答 agent 的澄清提问并继续 run（问题/回答本身不落库）。"""
        answer = text.strip()
        if not answer:
            raise ValidationError("回答不能为空")
        session = await self._require_session(session_id)
        events = self._orchestrator.answer(run_id, text=answer)
        await self._drive(events, session)

    async def list_workspace_entries(
        self, session_id: str, path: str = "."
    ) -> list[WorkspaceEntry]:
        """列出会话工作区内某一目录的条目（供文件树）。"""
        workspace = self._workspace_for(await self._require_session(session_id))
        return await workspace.list_entries(path)

    async def read_workspace_file(self, session_id: str, path: str) -> str:
        """读取会话工作区内的文件内容（供预览）。"""
        workspace = self._workspace_for(await self._require_session(session_id))
        return await workspace.read_text(path)

    async def write_workspace_file(
        self, session_id: str, path: str, content: str
    ) -> None:
        """把编辑后的内容写回会话工作区内的文件。"""
        workspace = self._workspace_for(await self._require_session(session_id))
        await workspace.write_text(path, content)

    # --- 内部 ---

    def _workspace_for(self, session: Session) -> WorkspaceProvider:
        if self._workspace_factory is None:
            raise DomainError("工作区不可用：未注入 workspace_factory")
        return self._workspace_factory(session.workspace_path)

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
