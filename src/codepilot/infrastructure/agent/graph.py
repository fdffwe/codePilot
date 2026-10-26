"""LangGraph 单图：agent ↔ tools 循环。

- agent 节点：调用模型（已绑定工具）。
- tools 节点：逐条执行工具调用；写/执行类工具在执行前 ``interrupt()`` 等待人工确认，
  ``ask_user`` 则以 ``interrupt()`` 暂停并等待用户回答。
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


async def _invoke(
    tool: BaseTool, call: ToolCall, config: RunnableConfig
) -> ToolMessage:
    """执行工具；领域异常转成 error 结果，避免终止整个 run。

    按 ``tool_call_id`` 缓存结果：interrupt 恢复会从头重放节点，已执行的调用
    直接复用上次结果，避免副作用重复生效。缓存检查必须在审批 ``interrupt``
    之后（本函数即调用点），否则会改变 interrupt 的调用顺序、错配 resume 值。
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


async def tools_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    last = state["messages"][-1]
    if not isinstance(last, AIMessage):
        return {"messages": []}
    results: list[ToolMessage] = []
    for call in last.tool_calls:
        name = str(call["name"])
        call_id = str(call["id"])
        tool = TOOLS_BY_NAME.get(name)
        if tool is None:
            results.append(
                ToolMessage(
                    content=f"未知工具：{name}", tool_call_id=call_id, status="error"
                )
            )
            continue

        metadata = tool.metadata or {}
        safety = metadata.get("safety", ToolSafety.WRITE)
        # 仅在参数可执行时才询问/提问；校验不过则交给 ainvoke 回传错误（无副作用）
        parsed, preview = _try_preview(tool, call)

        if safety is ToolSafety.ASK:
            # 提问由节点接管：不执行工具函数体，直接把用户回答作为工具结果
            if isinstance(parsed, AskUserArgs):
                answer = interrupt(
                    {
                        "kind": "question",
                        "tool": name,
                        "question": parsed.question,
                        "options": list(parsed.options),
                    }
                )
                results.append(
                    ToolMessage(
                        content=str(answer),
                        tool_call_id=call_id,
                        name=name,
                    )
                )
            else:
                results.append(await _invoke(tool, call, config))
            continue

        if (
            safety is not ToolSafety.READ
            and parsed is not None
            and not interrupt(
                {
                    "kind": "approval",
                    "tool": name,
                    "arguments": call.get("args") or {},
                    "preview": preview or "",
                    "risk": metadata.get("risk", "medium"),
                }
            )
        ):
            results.append(
                ToolMessage(
                    content="用户拒绝了该操作。",
                    tool_call_id=call_id,
                    status="error",
                    name=name,
                )
            )
            continue

        results.append(await _invoke(tool, call, config))
    return {"messages": results}


def _route(state: AgentState) -> str:
    last = state["messages"][-1]
    if not getattr(last, "tool_calls", None):
        return END
    if state.get("iterations", 0) >= state.get("max_iterations", 0):
        return END
    return "tools"


def build_graph() -> StateGraph[AgentState]:
    graph: StateGraph[AgentState] = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", _route, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph
