"""SQLite checkpointer 集成测试。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from langchain_core.messages import AIMessage

from codepilot.domain.entities import Message
from codepilot.domain.enums import MessageRole
from codepilot.domain.events import RunFinishedEvent
from codepilot.infrastructure.agent import LangGraphOrchestrator
from codepilot.infrastructure.agent.checkpointer import open_sqlite_checkpointer
from codepilot.infrastructure.executor import LocalExecutor
from codepilot.infrastructure.providers import FakeChatModelFactory
from codepilot.infrastructure.workspace import LocalDirectWorkspace


async def test_run_persists_checkpoints_to_sqlite(tmp_path: Path) -> None:
    db = tmp_path / "checkpoints.sqlite"
    async with open_sqlite_checkpointer(db) as saver:
        orch = LangGraphOrchestrator(
            checkpointer=saver,
            model_factory=FakeChatModelFactory([AIMessage(content="ok")]),
            workspace_factory=lambda p: LocalDirectWorkspace(p, allowlist=[tmp_path]),
            executor=LocalExecutor(),
            command_timeout_s=5,
            max_iterations=3,
        )
        events = [
            ev
            async for ev in orch.stream(
                run_id="r1",
                session_id="s1",
                model="fake",
                messages=[Message(role=MessageRole.USER, content="hi")],
                workspace_path=str(tmp_path),
            )
        ]
    assert isinstance(events[-1], RunFinishedEvent)

    con = sqlite3.connect(db)
    try:
        tables = {
            row[0]
            for row in con.execute("select name from sqlite_master where type='table'")
        }
    finally:
        con.close()
    assert any("checkpoint" in name for name in tables)
