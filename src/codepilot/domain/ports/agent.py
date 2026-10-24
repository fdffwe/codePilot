"""Agent 编排端口。

唯一允许上层触及 Agent 引擎的入口；实现（LangChain + LangGraph）在
``infrastructure/agent``。框架类型不得穿过本端口。见规范 §10。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Protocol, runtime_checkable

from codepilot.domain.entities import Message
from codepilot.domain.events import AgentEvent


@runtime_checkable
class AgentOrchestrator(Protocol):
    def stream(
        self,
        *,
        run_id: str,
        session_id: str,
        model: str,
        messages: Sequence[Message],
        workspace_path: str,
    ) -> AsyncIterator[AgentEvent]:
        """启动一次 run，流式产出事件；遇到需确认的工具会发审批事件后暂停。"""

    def resume(self, run_id: str, *, approved: bool) -> AsyncIterator[AgentEvent]:
        """对暂停中的 run 给出审批结论并继续，流式产出后续事件。"""

    def answer(self, run_id: str, *, text: str) -> AsyncIterator[AgentEvent]:
        """回答暂停中的 run 的澄清提问并继续，流式产出后续事件。"""
