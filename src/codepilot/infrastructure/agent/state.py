"""LangGraph 状态定义。"""

from __future__ import annotations

from typing import Annotated, TypedDict

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
