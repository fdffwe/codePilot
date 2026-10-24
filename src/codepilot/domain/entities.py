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


@dataclass(frozen=True, slots=True)
class WorkspaceEntry:
    """工作区目录中的一个条目（用于文件树展示）。"""

    name: str
    path: str  # 工作区相对路径，POSIX 分隔符
    is_dir: bool


@dataclass(frozen=True, slots=True)
class Question:
    """Agent 向用户发起的澄清提问；run 暂停等待回答。"""

    id: str
    session_id: str
    run_id: str
    text: str
    options: tuple[str, ...] = ()


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
