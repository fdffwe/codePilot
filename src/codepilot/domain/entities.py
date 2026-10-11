"""领域实体（stdlib dataclass，无框架依赖）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from codepilot.domain.enums import (
    ApprovalStatus,
    MessageRole,
    SessionStatus,
)


@dataclass(slots=True)
class ToolCall:
    """一次工具调用。id 用于幂等与结果关联。"""

    id: str
    name: str
    arguments: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class Message:
    role: MessageRole
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass(slots=True)
class ExecResult:
    """命令执行结果。"""

    exit_code: int
    stdout: str
    stderr: str
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


@dataclass(slots=True)
class Session:
    id: str
    title: str
    workspace_path: str
    model: str
    status: SessionStatus = SessionStatus.ACTIVE
    created_at: datetime | None = None


@dataclass(slots=True)
class Approval:
    """待确认的写/执行操作。"""

    id: str
    session_id: str
    run_id: str
    tool: str
    payload: dict[str, object]
    preview: str
    risk: str = "medium"
    status: ApprovalStatus = ApprovalStatus.PENDING
