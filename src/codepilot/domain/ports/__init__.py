"""领域端口（抽象接口）。

外层（infrastructure）提供实现，上层（application/ui）只依赖这些抽象。
见 docs/DEVELOPMENT_GUIDELINES.md §2 与 docs/TECHNICAL_DESIGN.md §6.7。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from codepilot.domain.entities import (
    Approval,
    ExecResult,
    Message,
    Session,
)
from codepilot.domain.enums import ToolSafety


@runtime_checkable
class WorkspaceProvider(Protocol):
    """本地直连工作区：绑定一个本机目录，读写受路径校验保护。"""

    root: Path

    def read_text(self, path: str) -> str: ...

    def write_text(self, path: str, content: str) -> None: ...

    def list_dir(self, path: str = ".") -> list[str]: ...


@runtime_checkable
class Executor(Protocol):
    """命令执行器（本机子进程，无 shell）。"""

    async def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        timeout_s: float,
    ) -> ExecResult: ...


@runtime_checkable
class Tool(Protocol):
    """Agent 可调用的工具。"""

    name: str
    safety: ToolSafety
    parameters: dict[str, object]

    async def execute(self, arguments: dict[str, object]) -> str: ...


@runtime_checkable
class LLMProvider(Protocol):
    """LLM 后端抽象；实现需适配 OpenAI/Anthropic 等。"""

    def chat_stream(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, object]],
        *,
        model: str,
    ) -> AsyncIterator[object]: ...


@runtime_checkable
class SessionRepository(Protocol):
    async def add(self, session: Session) -> None: ...

    async def get(self, session_id: str) -> Session | None: ...

    async def list(self) -> list[Session]: ...


@runtime_checkable
class ApprovalRepository(Protocol):
    async def add(self, approval: Approval) -> None: ...

    async def get(self, approval_id: str) -> Approval | None: ...

    async def resolve(self, approval_id: str, *, approved: bool) -> None: ...


@runtime_checkable
class AgentOrchestrator(Protocol):
    """Agent 编排端口；实现由 infrastructure/agent 提供（LangGraph）。"""

    def stream(
        self,
        messages: Sequence[Message],
        *,
        run_id: str,
        model: str,
    ) -> AsyncIterator[object]: ...

    async def resume(self, run_id: str, *, approved: bool) -> None: ...
