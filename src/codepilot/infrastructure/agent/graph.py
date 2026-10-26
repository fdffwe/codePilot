"""LangGraph 单图：agent → prepare → approval(自环) → execute → agent。

- agent：调用模型（已绑定工具）。
- prepare：按审批策略把本轮 tool_calls 分成“直接执行 / 待审批 / 待回答 / 已失败”。
- approval：每次只处理一个交互并 ``interrupt()`` 一次；还有下一个就经条件边自环，
  没有则进入 execute。一个节点只含一个 interrupt，恢复时不再重放整个调用循环。
- execute：按原顺序执行所有放行/已批准的调用，产出 ToolMessage。

工具以 LangChain ``StructuredTool`` 执行（schema 与参数校验由框架归口），
安全/风险/预览等元数据挂在 ``tool.metadata``。见规范 §10「图约定」。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langchain_core.messages import AIMessage, ToolCall, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel, ValidationError

from codepilot.core.errors import DomainError
from codepilot.domain.approval import Decision
from codepilot.domain.enums import ToolSafety
from codepilot.infrastructure.agent.state import AgentState
from codepilot.infrastructure.agent.tools import (
    TOOLS_BY_NAME,
    AskUserArgs,
    _deps,
)


async def agent_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    deps = _deps(config)
    response = await deps.model.ainvoke(state["messages"])
    return {
        "messages": [response],
        "iterations": state.get("iterations", 0) + 1,
    }


def _try_preview(
    tool: BaseTool, call: Mapping[str, Any]
) -> tuple[BaseModel | None, str | None]:
    """校验参数并渲染审批预览；参数非法或无可渲染器时返回 (None, None)。"""
    schema = tool.args_schema
    if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
        return None, None
    try:
        args = schema.model_validate(call.get("args") or {})
    except ValidationError:
        return None, None
    render = (tool.metadata or {}).get("preview")
    return args, render(args) if callable(render) else None


def prepare_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """把本轮调用分类；审批决策在此冻结，重放时不会因会话允许变化而漂移。"""
    last = state["messages"][-1]
    empty = {
        "pending": [],
        "cursor": 0,
        "answers": {},
        "rejected": {},
        "errors": {},
    }
    if not isinstance(last, AIMessage):
        return empty

    deps = _deps(config)
    pending: list[dict[str, Any]] = []
    errors: dict[str, str] = {}

    for call in last.tool_calls:
        name = str(call["name"])
        call_id = str(call["id"])
        args = dict(call.get("args") or {})
        tool = TOOLS_BY_NAME.get(name)
        if tool is None:
            errors[call_id] = f"未知工具：{name}"
            continue

        metadata = tool.metadata or {}
        safety = metadata.get("safety", ToolSafety.WRITE)
        parsed, preview = _try_preview(tool, call)
        if parsed is None:
            # 参数非法：交给 execute 里 ainvoke 回传校验错误
            continue

        if safety is ToolSafety.ASK:
            if isinstance(parsed, AskUserArgs):
                pending.append(
                    {
                        "kind": "question",
                        "call_id": call_id,
                        "tool": name,
                        "question": parsed.question,
                        "options": list(parsed.options),
                    }
                )
            continue

        decision = deps.policy.decide(
            session_id=deps.session_id,
            tool=name,
            args=args,
            safety=safety,
        )
        if decision.decision is Decision.DENY:
            errors[call_id] = f"策略拒绝：{decision.reason}"
        elif decision.decision is Decision.ASK:
            pending.append(
                {
                    "kind": "approval",
                    "call_id": call_id,
                    "tool": name,
                    "arguments": args,
                    "preview": preview or "",
                    "risk": decision.risk,
                }
            )

    return {
        "pending": pending,
        "cursor": 0,
        "answers": {},
        "rejected": {},
        "errors": errors,
    }


def approval_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """处理当前一个交互；只有一个 ``interrupt()``，其余交给条件边自环。

    连续多个待审批调用合并为一批，一次确认整批；提问会截断批次，仍逐个处理，
    以保持与模型调用顺序一致。
    """
    pending = state.get("pending") or []
    cursor = state.get("cursor", 0)
    if cursor >= len(pending):
        return {"cursor": cursor}

    item = pending[cursor]

    if item.get("kind") == "question":
        answer = interrupt(
            {
                "kind": "question",
                "tool": item.get("tool", ""),
                "question": item.get("question", ""),
                "options": list(item.get("options") or []),
            }
        )
        answers = dict(state.get("answers") or {})
        answers[str(item["call_id"])] = str(answer)
        return {"answers": answers, "cursor": cursor + 1}

    end = cursor
    while end < len(pending) and pending[end].get("kind") == "approval":
        end += 1
    batch = pending[cursor:end]

    if len(batch) == 1:
        payload: dict[str, Any] = {
            "kind": "approval",
            "tool": item.get("tool", ""),
            "arguments": item.get("arguments") or {},
            "preview": item.get("preview", ""),
            "risk": item.get("risk", "medium"),
        }
    else:
        payload = {
            "kind": "approvals",
            "items": [
                {
                    "tool": entry.get("tool", ""),
                    "arguments": entry.get("arguments") or {},
                    "preview": entry.get("preview", ""),
                    "risk": entry.get("risk", "medium"),
                }
                for entry in batch
            ],
        }

    approved = bool(interrupt(payload))
    rejected = dict(state.get("rejected") or {})
    for entry in batch:
        rejected[str(entry["call_id"])] = not approved
    return {"rejected": rejected, "cursor": end}


async def _invoke(
    tool: BaseTool, call: ToolCall, config: RunnableConfig
) -> ToolMessage:
    """执行工具；领域异常转成 error 结果，避免终止整个 run。

    按 ``tool_call_id`` 缓存结果：execute 节点若因重试被再次执行，已完成调用
    直接复用上次结果，避免副作用重复生效。
    """
    deps = _deps(config)
    name = str(call["name"])
    call_id = str(call["id"])
    if call_id in deps.done:
        return deps.done[call_id]
    try:
        result = await tool.ainvoke(call, config)
    except DomainError as exc:
        result = ToolMessage(
            content=f"错误：{exc}",
            tool_call_id=call_id,
            status="error",
            name=name,
        )
    deps.done[call_id] = result
    return result


async def execute_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """执行本轮所有调用，按原顺序产出 ToolMessage。"""
    last = state["messages"][-1]
    if not isinstance(last, AIMessage):
        return {"messages": []}

    answers = state.get("answers") or {}
    rejected = state.get("rejected") or {}
    errors = state.get("errors") or {}
    # 审批项执行前统一清空，避免下一轮 prepare 之前残留
    reset: dict[str, Any] = {
        "pending": [],
        "cursor": 0,
        "answers": {},
        "rejected": {},
        "errors": {},
    }
    results: list[ToolMessage] = []

    for call in last.tool_calls:
        name = str(call["name"])
        call_id = str(call["id"])

        if call_id in errors:
            results.append(
                ToolMessage(
                    content=errors[call_id],
                    tool_call_id=call_id,
                    status="error",
                    name=name,
                )
            )
            continue

        if rejected.get(call_id):
            results.append(
                ToolMessage(
                    content="用户拒绝了该操作。",
                    tool_call_id=call_id,
                    status="error",
                    name=name,
                )
            )
            continue

        if call_id in answers:
            results.append(
                ToolMessage(
                    content=answers[call_id],
                    tool_call_id=call_id,
                    name=name,
                )
            )
            continue

        tool = TOOLS_BY_NAME.get(name)
        if tool is None:
            results.append(
                ToolMessage(
                    content=f"未知工具：{name}",
                    tool_call_id=call_id,
                    status="error",
                    name=name,
                )
            )
            continue

        results.append(await _invoke(tool, call, config))

    return {**reset, "messages": results}


def _route_after_agent(state: AgentState) -> str:
    last = state["messages"][-1]
    if not getattr(last, "tool_calls", None):
        return END
    if state.get("iterations", 0) >= state.get("max_iterations", 0):
        return END
    return "prepare"


def _route_after_prepare(state: AgentState) -> str:
    return "approval" if state.get("pending") else "execute"


def _route_after_approval(state: AgentState) -> str:
    cursor = state.get("cursor", 0)
    return "approval" if cursor < len(state.get("pending") or []) else "execute"


def build_graph() -> StateGraph[AgentState]:
    graph: StateGraph[AgentState] = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("prepare", prepare_node)
    graph.add_node("approval", approval_node)
    graph.add_node("execute", execute_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent", _route_after_agent, {"prepare": "prepare", END: END}
    )
    graph.add_conditional_edges(
        "prepare", _route_after_prepare, {"approval": "approval", "execute": "execute"}
    )
    graph.add_conditional_edges(
        "approval",
        _route_after_approval,
        {"approval": "approval", "execute": "execute"},
    )
    graph.add_edge("execute", "agent")
    return graph
