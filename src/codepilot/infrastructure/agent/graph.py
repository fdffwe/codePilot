"""LangGraph 单图：agent ↔ tools 循环。

- agent 节点：调用模型（已绑定工具）。
- tools 节点：逐条执行工具调用；非只读工具在执行前 ``interrupt()`` 等待人工确认。
见规范 §10「图约定」。
"""

from __future__ import annotations

from typing import Any, cast

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from codepilot.core.errors import DomainError
from codepilot.domain.enums import ToolSafety
from codepilot.infrastructure.agent.state import AgentState
from codepilot.infrastructure.agent.tools import TOOL_SPECS, RunDeps


def _deps(config: RunnableConfig) -> RunDeps:
    return cast(RunDeps, config["configurable"]["codepilot_deps"])


async def agent_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    deps = _deps(config)
    response = await deps.model.ainvoke(state["messages"])
    return {
        "messages": [response],
        "iterations": state.get("iterations", 0) + 1,
    }


async def tools_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    deps = _deps(config)
    last = state["messages"][-1]
    if not isinstance(last, AIMessage):
        return {"messages": []}
    results: list[ToolMessage] = []
    for call in last.tool_calls:
        name = str(call["name"])
        spec = TOOL_SPECS.get(name)
        if spec is None:
            results.append(
                ToolMessage(
                    content=f"未知工具：{name}", tool_call_id=call["id"], status="error"
                )
            )
            continue

        args = spec.args_model.model_validate(call.get("args") or {})
        if spec.safety is not ToolSafety.READ:
            decision = interrupt(
                {
                    "tool": spec.name,
                    "arguments": args.model_dump(),
                    "preview": spec.preview(args),
                    "risk": spec.risk,
                }
            )
            if not decision:
                results.append(
                    ToolMessage(
                        content="用户拒绝了该操作。",
                        tool_call_id=call["id"],
                        status="error",
                    )
                )
                continue
        try:
            output = await spec.run(deps, args)
            results.append(ToolMessage(content=output, tool_call_id=call["id"]))
        except DomainError as exc:
            results.append(
                ToolMessage(
                    content=f"错误：{exc}", tool_call_id=call["id"], status="error"
                )
            )
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
