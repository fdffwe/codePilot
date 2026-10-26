"""LangGraph 编排器：实现 domain/ports::AgentOrchestrator。

把框架的 ``astream(updates)`` 转译为领域 ``AgentEvent``；框架类型不外泄。
HITL：非只读工具在工具节点 ``interrupt()``，``resume`` 用 ``Command(resume=)`` 继续。
见规范 §10。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, AnyMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command, Interrupt

from codepilot.domain.entities import Approval, Message, Question, ToolCall
from codepilot.domain.events import (
    AgentEvent,
    ApprovalRequiredEvent,
    ErrorEvent,
    MessageEvent,
    QuestionRequiredEvent,
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
    "你是 codePilot，一个本地编码助手。你可以调用工具读取/写入/编辑工作区文件、"
    "列出目录、按通配/正则检索代码、执行命令。"
    "查找文件与符号时优先用 glob/grep 定位，再用 read_file 精读相关文件。"
    "修改已有文件时优先用 edit_file 做局部替换，而非整体重写。"
    "需求不明确、缺少关键信息或存在多种合理做法时，先用 ask_user 向用户澄清，"
    "不要臆测；用户的回答会作为该工具的结果返回。"
    "写入与执行命令需要用户确认后再进行。"
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
        # run_id → 当前暂停等待的类型（approval / question），用于防止 resume 错配
        self._pending_kind: dict[str, str] = {}

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
        async for event in self._resume_with(
            run_id, approved, expected_kind="approval"
        ):
            yield event

    async def answer(self, run_id: str, *, text: str) -> AsyncIterator[AgentEvent]:
        async for event in self._resume_with(run_id, text, expected_kind="question"):
            yield event

    # --- 内部 ---

    async def _resume_with(
        self, run_id: str, value: bool | str, *, expected_kind: str
    ) -> AsyncIterator[AgentEvent]:
        if run_id not in self._runs:
            yield ErrorEvent(
                run_id=run_id, seq=self._next(run_id), message="未知的 run，无法恢复"
            )
            return
        pending = self._pending_kind.get(run_id)
        if pending != expected_kind:
            # resume 按调用顺序匹配，类型错配会把 bool 当成回答喂给模型
            waiting = {"approval": "审批", "question": "用户回答"}.get(
                pending or "", "无"
            )
            expected = "审批" if expected_kind == "approval" else "用户回答"
            yield ErrorEvent(
                run_id=run_id,
                seq=self._next(run_id),
                message=f"当前等待{waiting}，不能提交{expected}",
            )
            return
        self._pending_kind.pop(run_id, None)
        updates = self._graph.astream(
            Command(resume=value), self._config(run_id), stream_mode="updates"
        )
        async for event in self._translate(updates, run_id):
            yield event

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
                        interrupt_event = self._interrupt_event(run_id, intr)
                        self._pending_kind[run_id] = (
                            "question"
                            if isinstance(interrupt_event, QuestionRequiredEvent)
                            else "approval"
                        )
                        yield interrupt_event
                    continue
                for node, value in update.items():
                    for event in self._node_events(run_id, node, value, pending):
                        yield event
        except Exception as exc:
            self._pending_kind.pop(run_id, None)
            _log.warning(
                "agent_run_failed", extra={"run_id": run_id, "error": str(exc)}
            )
            yield ErrorEvent(run_id=run_id, seq=self._next(run_id), message=str(exc))
            return

        if not interrupted:
            self._pending_kind.pop(run_id, None)
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
                fallback_name = str(getattr(msg, "name", "") or "")
                name, args = pending.pop(cid, (fallback_name, {}))
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

    def _interrupt_event(
        self, run_id: str, intr: Interrupt
    ) -> ApprovalRequiredEvent | QuestionRequiredEvent:
        value = intr.value if isinstance(intr.value, dict) else {}
        if value.get("kind") == "question":
            question = Question(
                # interrupt id 是 namespace 哈希，同节点多次中断会重复，改用独立 id
                id=uuid4().hex,
                session_id=self._session_ids.get(run_id, ""),
                run_id=run_id,
                text=str(value.get("question", "")),
                options=tuple(str(option) for option in value.get("options") or []),
            )
            return QuestionRequiredEvent(
                run_id=run_id, seq=self._next(run_id), question=question
            )
        return self._approval_event(run_id, intr)

    def _approval_event(self, run_id: str, intr: Interrupt) -> ApprovalRequiredEvent:
        value = intr.value if isinstance(intr.value, dict) else {}
        approval = Approval(
            # 同节点内多个 interrupt 共享 id，审批要落库，必须用唯一 id
            id=uuid4().hex,
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
