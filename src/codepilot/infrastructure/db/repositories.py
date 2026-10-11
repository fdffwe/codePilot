"""SQLAlchemy 仓储实现（满足 domain/ports 的 Repository 协议）。

每个方法独立开 Session 并提交；跨协程不共享 Session。见规范 §6/§14。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from codepilot.domain.entities import Approval, Message, Session
from codepilot.domain.enums import ApprovalStatus
from codepilot.infrastructure.db import mappers
from codepilot.infrastructure.db.orm.models import (
    ApprovalRow,
    MessageRow,
    SessionRow,
)


class SqlSessionRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    async def add(self, session: Session) -> None:
        async with self._factory() as db:
            db.add(mappers.session_to_row(session))
            await db.commit()

    async def update(self, session: Session) -> None:
        async with self._factory() as db:
            row = await db.get(SessionRow, session.id)
            if row is None:
                return
            row.title = session.title
            row.workspace_path = session.workspace_path
            row.model = session.model
            row.status = str(session.status)
            await db.commit()

    async def get(self, session_id: str) -> Session | None:
        async with self._factory() as db:
            row = await db.get(SessionRow, session_id)
        return mappers.session_to_domain(row) if row is not None else None

    async def list(self) -> list[Session]:
        async with self._factory() as db:
            rows = (
                await db.execute(
                    select(SessionRow).order_by(SessionRow.created_at.desc())
                )
            ).scalars()
        return [mappers.session_to_domain(row) for row in rows]


class SqlMessageRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    async def append(self, session_id: str, message: Message) -> None:
        async with self._factory() as db:
            db.add(mappers.message_to_row(session_id, message))
            await db.commit()

    async def list(self, session_id: str) -> list[Message]:
        async with self._factory() as db:
            rows = (
                await db.execute(
                    select(MessageRow)
                    .where(MessageRow.session_id == session_id)
                    .order_by(MessageRow.id)
                )
            ).scalars()
        return [mappers.message_to_domain(row) for row in rows]


class SqlApprovalRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    async def add(self, approval: Approval) -> None:
        async with self._factory() as db:
            db.add(mappers.approval_to_row(approval))
            await db.commit()

    async def get(self, approval_id: str) -> Approval | None:
        async with self._factory() as db:
            row = await db.get(ApprovalRow, approval_id)
        return mappers.approval_to_domain(row) if row is not None else None

    async def resolve(self, approval_id: str, *, approved: bool) -> None:
        async with self._factory() as db:
            row = await db.get(ApprovalRow, approval_id)
            if row is None:
                return
            row.status = str(
                ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
            )
            await db.commit()

    async def list_pending(self, session_id: str) -> list[Approval]:
        async with self._factory() as db:
            rows = (
                await db.execute(
                    select(ApprovalRow)
                    .where(
                        ApprovalRow.session_id == session_id,
                        ApprovalRow.status == str(ApprovalStatus.PENDING),
                    )
                    .order_by(ApprovalRow.created_at)
                )
            ).scalars()
        return [mappers.approval_to_domain(row) for row in rows]
