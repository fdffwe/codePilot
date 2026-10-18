"""LangGraph 编排器：实现 domain/ports::AgentOrchestrator。

把框架的 ``astream(updates)`` 转译为领域 ``AgentEvent``；框架类型不外泄。
HITL：非只读工具在工具节点 ``interrupt()``，``resume`` 用 ``Command(resume=)`` 继续。
见规范 §10。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command, Interrupt

from codepilot.domain.entities import Approval, Message, ToolCall
from codepilot.domain.events import (
    AgentEvent,
    ApprovalRequiredEvent,
    ErrorEvent,
    MessageEvent,
    RunFinishedEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from codepilot.domain.ports import Executor, WorkspaceProvider
from codepilot.infrastructure.agent.graph import build_graph
from codepilot.infrastructure.agent.mappers import from_ai_message, to_lc_message
from codepilot.infrastructure.agent.state import AgentState
from codepilot.infrastructure.agent.tools import TOOLS, RunDeps
from codepilot.infrastructure.providers import ChatModelFactory

_log = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = (
    "你是 codePilot，一个本地编码助手。你可以调用工具读取/写入工作区文件、"
    "列出目录、执行命令。写入与执行命令需要用户确认后再进行。"
    "请先用工具了解现状，再采取行动；只操作工作区内路径。"
)

WorkspaceFactory = Callable[[str], WorkspaceProvider]


class LangGraphOrchestrator:
    def __init__(
        self,
        *,
        checkpointer: BaseCheckpointSaver[str],
        model_factory: ChatModelFactory,
        workspace_factory: WorkspaceFactory,
        executor: Executor,
        command_timeout_s: float,
        max_iterations: int,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    ) -> None:
        self._graph = build_graph().compile(checkpointer=checkpointer)
        self._model_factory = model_factory
        self._workspace_factory = workspace_factory
        self._executor = executor
        self._command_timeout_s = command_timeout_s
        self._max_iterations = max_iterations
        self._system_prompt = system_prompt
        self._runs: dict[str, RunDeps] = {}
        self._session_ids: dict[str, str] = {}
        self._seq: dict[str, int] = {}

    async def stream(
        self,
        *,
        run_id: str,
        session_id: str,
        model: str,
        messages: Sequence[Message],
        workspace_path: str,
    ) -> AsyncIterator[AgentEvent]:
        deps = self._make_deps(model, workspace_path)
        self._runs[run_id] = deps
        self._session_ids[run_id] = session_id
        self._seq[run_id] = 0
        payload: AgentState = {
            "messages": self._prepare_input(messages),
            "workspace_path": workspace_path,
            "session_id": session_id,
            "run_id": run_id,
            "iterations": 0,
            "max_iterations": self._max_iterations,
        }
        updates = self._graph.astream(
            payload, self._config(run_id), stream_mode="updates"
        )
        async for event in self._translate(updates, run_id):
            yield event

    async def resume(self, run_id: str, *, approved: bool) -> AsyncIterator[AgentEvent]:
        if run_id not in self._runs:
            yield ErrorEvent(
                run_id=run_id, seq=self._next(run_id), message="未知的 run，无法恢复"
            )
            return
        updates = self._graph.astream(
            Command(resume=approved), self._config(run_id), stream_mode="updates"
        )
        async for event in self._translate(updates, run_id):
            yield event

    # --- 内部 ---

    def _make_deps(self, model: str, workspace_path: str) -> RunDeps:
        workspace = self._workspace_factory(workspace_path)
        bound = self._model_factory(model).bind_tools(TOOLS)
        return RunDeps(
            workspace=workspace,
            executor=self._executor,
            model=bound,
            command_timeout_s=self._command_timeout_s,
        )

    def _prepare_input(self, messages: Sequence[Message]) -> list[AnyMessage]:
        prepared: list[AnyMessage] = [SystemMessage(content=self._system_prompt)]
        prepared.extend(to_lc_message(m) for m in messages if m.role.value != "system")
        return prepared

    def _config(self, run_id: str) -> RunnableConfig:
        return {
            "configurable": {
                "thread_id": run_id,
                "codepilot_deps": self._runs[run_id],
            }
        }

    def _next(self, run_id: str) -> int:
        seq = self._seq.get(run_id, 0)
        self._seq[run_id] = seq + 1
        return seq

    async def _translate(
        self,
        updates: AsyncIterator[dict[str, Any]],
        run_id: str,
    ) -> AsyncIterator[AgentEvent]:
        pending: dict[str, tuple[str, dict[str, object]]] = {}
        interrupted = False
        try:
            async for update in updates:
                if "__interrupt__" in update:
                    interrupted = True
                    for intr in update["__interrupt__"]:
                        yield self._approval_event(run_id, intr)
                    continue
                for node, value in update.items():
                    for event in self._node_events(run_id, node, value, pending):
                        yield event
        except Exception as exc:
            _log.warning(
                "agent_run_failed", extra={"run_id": run_id, "error": str(exc)}
            )
            yield ErrorEvent(run_id=run_id, seq=self._next(run_id), message=str(exc))
            return

        if not interrupted:
            snapshot = await self._graph.aget_state(self._config(run_id))
            if not snapshot.next:
                yield RunFinishedEvent(
                    run_id=run_id,
                    seq=self._next(run_id),
                    iterations=int(snapshot.values.get("iterations", 0)),
                )

    def _node_events(
        self,
        run_id: str,
        node: str,
        value: dict[str, Any],
        pending: dict[str, tuple[str, dict[str, object]]],
    ) -> list[AgentEvent]:
        events: list[AgentEvent] = []
        if node == "agent":
            for msg in value.get("messages", []):
                if not isinstance(msg, AIMessage):
                    continue
                text, calls = from_ai_message(msg)
                tool_calls = tuple(
                    ToolCall(id=cid, name=name, arguments=args)
                    for cid, name, args in calls
                )
                for cid, name, args in calls:
                    pending[cid] = (name, args)
                events.append(
                    MessageEvent(
                        run_id=run_id,
                        seq=self._next(run_id),
                        content=text,
                        tool_calls=tool_calls,
                    )
                )
                events.extend(
                    ToolCallEvent(run_id=run_id, seq=self._next(run_id), call=call)
                    for call in tool_calls
                )
        elif node == "tools":
            for msg in value.get("messages", []):
                cid = str(getattr(msg, "tool_call_id", ""))
                name, args = pending.pop(cid, (str(getattr(msg, "name", "")), {}))
                call = ToolCall(id=cid, name=name, arguments=args)
                ok = getattr(msg, "status", "success") != "error"
                events.append(
                    ToolResultEvent(
                        run_id=run_id,
                        seq=self._next(run_id),
                        call=call,
                        output=str(msg.content),
                        ok=ok,
                    )
                )
        return events

    def _approval_event(self, run_id: str, intr: Interrupt) -> ApprovalRequiredEvent:
        value = intr.value if isinstance(intr.value, dict) else {}
        approval = Approval(
            id=str(intr.id),
            session_id=self._session_ids.get(run_id, ""),
            run_id=run_id,
            tool=str(value.get("tool", "")),
            payload=dict(value.get("arguments") or {}),
            preview=str(value.get("preview", "")),
            risk=str(value.get("risk", "medium")),
        )
        return ApprovalRequiredEvent(
            run_id=run_id, seq=self._next(run_id), approval=approval
        )
