"""持久化端口（仓储）。实现见 infrastructure/db。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from codepilot.domain.entities import Approval, Message, Session


@runtime_checkable
class SessionRepository(Protocol):
    async def add(self, session: Session) -> None: ...

    async def update(self, session: Session) -> None: ...

    async def get(self, session_id: str) -> Session | None: ...

    async def list(self) -> list[Session]: ...


@runtime_checkable
class MessageRepository(Protocol):
    async def append(self, session_id: str, message: Message) -> None: ...

    async def list(self, session_id: str) -> list[Message]: ...


@runtime_checkable
class ApprovalRepository(Protocol):
    async def add(self, approval: Approval) -> None: ...

    async def get(self, approval_id: str) -> Approval | None: ...

    async def resolve(self, approval_id: str, *, approved: bool) -> None: ...

    async def list_pending(self, session_id: str) -> list[Approval]: ...
