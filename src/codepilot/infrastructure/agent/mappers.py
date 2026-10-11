"""domain Message ↔ LangChain BaseMessage 的双向映射。

框架类型不越过本包边界。见规范 §10「映射层」。
"""

from __future__ import annotations

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
)

from codepilot.domain.entities import Message
from codepilot.domain.enums import MessageRole


def to_lc_message(message: Message) -> AnyMessage:
    """把领域消息转成 LangChain 消息（用于构建 run 的初始输入）。"""
    match message.role:
        case MessageRole.SYSTEM:
            return SystemMessage(content=message.content)
        case MessageRole.ASSISTANT:
            return AIMessage(content=message.content)
        case _:
            # USER 及未知（如 TOOL，其 tool_call_id 属单次 run 内部）按用户输入处理
            return HumanMessage(content=message.content)


def from_ai_message(message: AIMessage) -> tuple[str, list[tuple[str, str, dict]]]:
    """从 AIMessage 提取文本与工具调用三元组 (id, name, args)。"""
    text = _as_text(message.content)
    calls = [
        (str(call["id"]), str(call["name"]), dict(call.get("args") or {}))
        for call in message.tool_calls
    ]
    return text, calls


def _as_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content)
