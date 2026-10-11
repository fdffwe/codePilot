"""模型工厂契约（基础设施内部接缝）。

Agent 引擎（infrastructure/agent）通过本工厂获得可绑定工具的聊天模型；
领域/应用层不感知。框架类型仅在本层出现。见规范 §10。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from langchain_core.language_models import BaseChatModel


@runtime_checkable
class ChatModelFactory(Protocol):
    def __call__(self, model: str) -> BaseChatModel:
        """按模型名构建聊天模型（流式）。"""
