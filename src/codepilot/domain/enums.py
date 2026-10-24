"""领域枚举。"""

from __future__ import annotations

from enum import StrEnum


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class SessionStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ToolSafety(StrEnum):
    """工具安全等级；write/exec 需人工确认，ask 向用户提问。"""

    READ = "read"
    WRITE = "write"
    EXEC = "exec"
    ASK = "ask"
