"""LangGraph SQLite 检查点。

把图状态持久化到独立 sqlite 文件（thread_id = run_id），支撑 interrupt 恢复。
见规范 §10「持久化」。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


@asynccontextmanager
async def open_sqlite_checkpointer(db_path: Path) -> AsyncIterator[AsyncSqliteSaver]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as saver:
        yield saver
