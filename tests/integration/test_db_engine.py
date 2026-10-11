"""异步引擎/ORM 集成测试（临时 SQLite）。"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from codepilot.infrastructure.db.engine import (
    create_db_engine,
    create_session_factory,
)
from codepilot.infrastructure.db.orm.base import Base
from codepilot.infrastructure.db.orm.models import SessionRow


async def test_engine_creates_schema_and_persists(tmp_path: Path) -> None:
    engine = create_db_engine(tmp_path / "codepilot.db")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        factory = create_session_factory(engine)
        async with factory() as session:
            session.add(
                SessionRow(
                    id="s1",
                    title="demo",
                    workspace_path="/tmp/ws",
                    model="deepseek-v4-flash",
                )
            )
            await session.commit()

        async with factory() as session:
            row = await session.get(SessionRow, "s1")
        assert row is not None
        assert row.title == "demo"
        assert row.status == "active"
    finally:
        await engine.dispose()


async def test_sqlite_uses_wal_mode(tmp_path: Path) -> None:
    engine = create_db_engine(tmp_path / "codepilot.db")
    try:
        async with engine.connect() as conn:
            mode = (await conn.execute(text("PRAGMA journal_mode"))).scalar()
        assert str(mode).lower() == "wal"
    finally:
        await engine.dispose()
