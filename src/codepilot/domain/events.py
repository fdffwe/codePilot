"""Agent 运行时事件（领域对象，无框架依赖）。

由 ``AgentOrchestrator`` 以流的方式产出；application 转成应用事件后交给 GUI。
``seq`` 为同一 run 内单调递增序号，用于保序与去重。见规范 §10「流式」。
"""

from __future__ import annotations

from dataclasses import dataclass

from codepilot.domain.entities import Approval, Question, ToolCall


@dataclass(frozen=True, slots=True)
class AgentEvent:
    """所有 Agent 事件的基类。"""

    run_id: str
    seq: int


@dataclass(frozen=True, slots=True)
class TokenEvent(AgentEvent):
    """助手输出的增量文本片段。"""

    text: str


@dataclass(frozen=True, slots=True)
class MessageEvent(AgentEvent):
    """助手一条完整消息；含工具调用意图时 ``tool_calls`` 非空。"""

    content: str
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolCallEvent(AgentEvent):
    """一次工具调用开始。"""

    call: ToolCall


@dataclass(frozen=True, slots=True)
class ToolResultEvent(AgentEvent):
    """一次工具调用结束。"""

    call: ToolCall
    output: str
    ok: bool


@dataclass(frozen=True, slots=True)
class ApprovalRequiredEvent(AgentEvent):
    """写/执行类工具需人工确认；run 在此暂停，待 ``resume``。"""

    approval: Approval


@dataclass(frozen=True, slots=True)
class QuestionRequiredEvent(AgentEvent):
    """Agent 需要用户澄清；run 在此暂停，待 ``answer``。"""

    question: Question


@dataclass(frozen=True, slots=True)
class RunFinishedEvent(AgentEvent):
    """run 正常结束。"""

    iterations: int


@dataclass(frozen=True, slots=True)
class ErrorEvent(AgentEvent):
    """run 因错误终止。"""

    message: str
