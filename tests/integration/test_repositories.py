"""仓储集成测试（临时 SQLite）。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from codepilot.domain.entities import Approval, Message, Session, ToolCall
from codepilot.domain.enums import ApprovalStatus, MessageRole
from codepilot.domain.ports import (
    ApprovalRepository,
    MessageRepository,
    SessionRepository,
)
from codepilot.infrastructure.db.engine import (
    create_db_engine,
    create_session_factory,
)
from codepilot.infrastructure.db.orm.base import Base
from codepilot.infrastructure.db.repositories import (
    SqlApprovalRepository,
    SqlMessageRepository,
    SqlSessionRepository,
)


@pytest.fixture
async def repos(
    tmp_path: Path,
) -> AsyncIterator[
    tuple[SqlSessionRepository, SqlMessageRepository, SqlApprovalRepository]
]:
    engine = create_db_engine(tmp_path / "codepilot.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    try:
        yield (
            SqlSessionRepository(factory),
            SqlMessageRepository(factory),
            SqlApprovalRepository(factory),
        )
    finally:
        await engine.dispose()


def _session(sid: str = "s1") -> Session:
    return Session(
        id=sid,
        title="demo",
        workspace_path="/tmp/ws",
        model="deepseek-chat",
    )


def test_implementations_satisfy_ports(
    repos: tuple[SqlSessionRepository, SqlMessageRepository, SqlApprovalRepository],
) -> None:
    sessions, messages, approvals = repos
    assert isinstance(sessions, SessionRepository)
    assert isinstance(messages, MessageRepository)
    assert isinstance(approvals, ApprovalRepository)


async def test_session_add_get_list_update(
    repos: tuple[SqlSessionRepository, SqlMessageRepository, SqlApprovalRepository],
) -> None:
    sessions, _, _ = repos
    await sessions.add(_session())
    fetched = await sessions.get("s1")
    assert fetched is not None and fetched.title == "demo"

    fetched.title = "renamed"
    await sessions.update(fetched)
    assert (await sessions.get("s1")).title == "renamed"  # type: ignore[union-attr]

    assert [s.id for s in await sessions.list()] == ["s1"]
    assert await sessions.get("missing") is None


async def test_message_append_and_list_preserves_tool_calls(
    repos: tuple[SqlSessionRepository, SqlMessageRepository, SqlApprovalRepository],
) -> None:
    sessions, messages, _ = repos
    await sessions.add(_session())
    call = ToolCall(id="c1", name="read_file", arguments={"path": "a.py"})
    await messages.append("s1", Message(role=MessageRole.USER, content="hi"))
    await messages.append(
        "s1", Message(role=MessageRole.ASSISTANT, content="", tool_calls=[call])
    )

    loaded = await messages.list("s1")
    assert [m.role for m in loaded] == [MessageRole.USER, MessageRole.ASSISTANT]
    assert loaded[0].content == "hi"
    assert loaded[1].tool_calls == [call]


async def test_approval_resolve_and_list_pending(
    repos: tuple[SqlSessionRepository, SqlMessageRepository, SqlApprovalRepository],
) -> None:
    sessions, _, approvals = repos
    await sessions.add(_session())
    await approvals.add(
        Approval(
            id="a1",
            session_id="s1",
            run_id="r1",
            tool="write_file",
            payload={"path": "a.py"},
            preview="+ x",
        )
    )
    assert [a.id for a in await approvals.list_pending("s1")] == ["a1"]

    await approvals.resolve("a1", approved=True)
    resolved = await approvals.get("a1")
    assert resolved is not None and resolved.status is ApprovalStatus.APPROVED
    assert await approvals.list_pending("s1") == []
