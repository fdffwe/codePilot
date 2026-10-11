"""领域对象 ↔ ORM 行 的映射。

框架类型不越过仓储边界；此处是唯一的转换点。见规范 §10 映射层约定。
"""

from __future__ import annotations

from codepilot.domain.entities import Approval, Message, Session, ToolCall
from codepilot.domain.enums import ApprovalStatus, MessageRole, SessionStatus
from codepilot.infrastructure.db.orm.models import (
    ApprovalRow,
    MessageRow,
    SessionRow,
)


def session_to_domain(row: SessionRow) -> Session:
    return Session(
        id=row.id,
        title=row.title,
        workspace_path=row.workspace_path,
        model=row.model,
        status=SessionStatus(row.status),
        created_at=row.created_at,
    )


def session_to_row(entity: Session) -> SessionRow:
    return SessionRow(
        id=entity.id,
        title=entity.title,
        workspace_path=entity.workspace_path,
        model=entity.model,
        status=str(entity.status),
        created_at=entity.created_at,
    )


def _tool_calls_to_domain(raw: list[dict[str, object]]) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for item in raw:
        raw_args = item.get("arguments")
        arguments = dict(raw_args) if isinstance(raw_args, dict) else {}
        calls.append(
            ToolCall(
                id=str(item["id"]),
                name=str(item["name"]),
                arguments=arguments,
            )
        )
    return calls


def _tool_calls_to_json(calls: list[ToolCall]) -> list[dict[str, object]]:
    return [
        {"id": call.id, "name": call.name, "arguments": call.arguments}
        for call in calls
    ]


def message_to_domain(row: MessageRow) -> Message:
    return Message(
        role=MessageRole(row.role),
        content=row.content,
        tool_calls=_tool_calls_to_domain(row.tool_calls),
    )


def message_to_row(session_id: str, entity: Message) -> MessageRow:
    return MessageRow(
        session_id=session_id,
        role=str(entity.role),
        content=entity.content,
        tool_calls=_tool_calls_to_json(entity.tool_calls),
    )


def approval_to_domain(row: ApprovalRow) -> Approval:
    return Approval(
        id=row.id,
        session_id=row.session_id,
        run_id=row.run_id,
        tool=row.tool,
        payload=dict(row.payload),
        preview=row.preview,
        risk=row.risk,
        status=ApprovalStatus(row.status),
    )


def approval_to_row(entity: Approval) -> ApprovalRow:
    return ApprovalRow(
        id=entity.id,
        session_id=entity.session_id,
        run_id=entity.run_id,
        tool=entity.tool,
        payload=entity.payload,
        preview=entity.preview,
        risk=entity.risk,
        status=str(entity.status),
    )
