"""P1 端到端：真实仓储 + 真实编排器 + 真实工作区/执行器（仅 LLM 用 Fake）。

覆盖 DoD 主链路：建会话（绑定目录）→ 助手请求写文件 → 人工确认 → 落盘并回写消息。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from codepilot.application.chat_service import ChatService
from codepilot.application.event_bus import EventBus
from codepilot.domain.enums import MessageRole
from codepilot.domain.events import ApprovalRequiredEvent
from codepilot.infrastructure.agent import LangGraphOrchestrator
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
from codepilot.infrastructure.executor import LocalExecutor
from codepilot.infrastructure.providers import FakeChatModelFactory
from codepilot.infrastructure.workspace import LocalDirectWorkspace


@pytest.fixture
async def service(
    tmp_path: Path,
) -> AsyncIterator[tuple[ChatService, EventBus, SqlMessageRepository]]:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "a.txt").write_text("hello", encoding="utf-8")

    engine = create_db_engine(tmp_path / "codepilot.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)

    orchestrator = LangGraphOrchestrator(
        checkpointer=InMemorySaver(),
        model_factory=FakeChatModelFactory(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "write_file",
                            "args": {"path": "out.py", "content": "print(1)\n"},
                            "id": "c1",
                        }
                    ],
                ),
                AIMessage(content="已写好 out.py"),
            ]
        ),
        workspace_factory=lambda p: LocalDirectWorkspace(p, allowlist=[tmp_path]),
        executor=LocalExecutor(),
        command_timeout_s=10,
        max_iterations=5,
    )
    bus = EventBus()
    messages = SqlMessageRepository(factory)
    try:
        yield (
            ChatService(
                sessions=SqlSessionRepository(factory),
                messages=messages,
                approvals=SqlApprovalRepository(factory),
                orchestrator=orchestrator,
                bus=bus,
                allowlist=[tmp_path],
                default_model="fake",
            ),
            bus,
            messages,
        )
    finally:
        await engine.dispose()
    _ = root


async def test_write_flow_end_to_end(
    service: tuple[ChatService, EventBus, SqlMessageRepository], tmp_path: Path
) -> None:
    chat, bus, messages = service
    events: list[object] = []
    bus.subscribe(events.append)

    session = await chat.create_session(workspace_path=tmp_path / "ws")
    await chat.send(session.id, "帮我建 out.py")

    approval_event = next(e for e in events if isinstance(e, ApprovalRequiredEvent))
    assert approval_event.approval.tool == "write_file"
    assert not (tmp_path / "ws" / "out.py").exists()  # 确认前不动盘

    await chat.resolve_approval(approval_event.approval.id, approved=True)

    assert (tmp_path / "ws" / "out.py").read_text(encoding="utf-8") == "print(1)\n"
    stored = await messages.list(session.id)
    assert stored[0].role is MessageRole.USER
    assert stored[-1].role is MessageRole.ASSISTANT
    assert stored[-1].content == "已写好 out.py"
