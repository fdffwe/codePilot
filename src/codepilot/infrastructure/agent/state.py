"""LangGraph 状态定义。"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    """单图状态；messages 用 add_messages reducer 累积。"""

    messages: Annotated[list[AnyMessage], add_messages]
    workspace_path: str
    session_id: str
    run_id: str
    iterations: int
    max_iterations: int
    # 本轮待交互项（审批/提问）；approval 节点逐个处理并推进 cursor
    pending: list[dict[str, Any]]
    cursor: int
    answers: dict[str, str]
    rejected: dict[str, bool]
    # 无需交互但已确定失败（未知工具/策略拒绝），由 execute 节点产出错误结果
    errors: dict[str, str]
