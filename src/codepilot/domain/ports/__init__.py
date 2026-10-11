"""领域端口（抽象接口）。

外层（infrastructure）提供实现，上层（application/ui）只依赖这些抽象。
见 docs/DEVELOPMENT_GUIDELINES.md §2 与 docs/TECHNICAL_DESIGN.md §6.7。
"""

from __future__ import annotations

from codepilot.domain.ports.agent import AgentOrchestrator
from codepilot.domain.ports.executor import Executor, OutputCallback
from codepilot.domain.ports.repositories import (
    ApprovalRepository,
    MessageRepository,
    SessionRepository,
)
from codepilot.domain.ports.workspace import WorkspaceProvider

__all__ = [
    "AgentOrchestrator",
    "ApprovalRepository",
    "Executor",
    "MessageRepository",
    "OutputCallback",
    "SessionRepository",
    "WorkspaceProvider",
]
