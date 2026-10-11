"""依赖装配（组合根）。

★ 唯一允许同时 import 各层的地方：把 settings/handler 装配成应用服务。
UI 只通过本模块拿到 ChatService 与 EventBus，不直接接触 infrastructure。
见 TDD §5.2。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig

from codepilot.application.chat_service import ChatService
from codepilot.application.event_bus import EventBus
from codepilot.core.config import Settings
from codepilot.domain.ports import WorkspaceProvider
from codepilot.infrastructure.agent import LangGraphOrchestrator
from codepilot.infrastructure.agent.checkpointer import open_sqlite_checkpointer
from codepilot.infrastructure.db.engine import (
    create_db_engine,
    create_session_factory,
)
from codepilot.infrastructure.db.repositories import (
    SqlApprovalRepository,
    SqlMessageRepository,
    SqlSessionRepository,
)
from codepilot.infrastructure.executor import LocalExecutor
from codepilot.infrastructure.providers import OpenAIChatModelFactory
from codepilot.infrastructure.workspace import LocalDirectWorkspace


@dataclass(slots=True)
class Container:
    settings: Settings
    bus: EventBus
    chat_service: ChatService


def _repo_root() -> Path:
    # src/codepilot/core/di.py -> 仓库根
    return Path(__file__).resolve().parents[3]


def _workspace_factory(settings: Settings) -> Callable[[str], WorkspaceProvider]:
    """按会话绑定的目录构造工作区；编排器与对话用例共用。"""
    return lambda path: LocalDirectWorkspace(
        path, allowlist=settings.workspace_allowlist
    )


async def _upgrade_database() -> None:
    """在独立线程跑 Alembic 迁移（其 env.py 自持 asyncio.run，避免嵌套事件循环）。"""

    def _run() -> None:
        root = _repo_root()
        cfg = AlembicConfig(str(root / "alembic.ini"))
        cfg.set_main_option("script_location", str(root / "migrations"))
        command.upgrade(cfg, "head")

    await asyncio.to_thread(_run)


@asynccontextmanager
async def build_container(settings: Settings) -> AsyncIterator[Container]:
    await _upgrade_database()

    engine = create_db_engine(settings.db_path)
    factory = create_session_factory(engine)
    stack = AsyncExitStack()
    try:
        saver = await stack.enter_async_context(
            open_sqlite_checkpointer(settings.checkpoints_path)
        )
        api_key = settings.llm_api_key
        model_factory = (
            OpenAIChatModelFactory(base_url=settings.llm_base_url, api_key=api_key)
            if api_key is not None
            else None
        )
        if model_factory is None:
            raise RuntimeError("未配置 LLM API Key（CODEPILOT_LLM_API_KEY）")

        workspace_factory = _workspace_factory(settings)
        orchestrator = LangGraphOrchestrator(
            checkpointer=saver,
            model_factory=model_factory,
            workspace_factory=workspace_factory,
            executor=LocalExecutor(max_output_bytes=settings.command_max_output_bytes),
            command_timeout_s=settings.command_timeout_s,
            max_iterations=settings.agent_max_iterations,
        )
        bus = EventBus()
        chat_service = ChatService(
            sessions=SqlSessionRepository(factory),
            messages=SqlMessageRepository(factory),
            approvals=SqlApprovalRepository(factory),
            orchestrator=orchestrator,
            bus=bus,
            allowlist=settings.workspace_allowlist,
            default_model=settings.llm_model,
            workspace_factory=workspace_factory,
        )
        yield Container(settings=settings, bus=bus, chat_service=chat_service)
    finally:
        await stack.aclose()
        await engine.dispose()
