"""领域事件单测。"""

from __future__ import annotations

import dataclasses

import pytest

from codepilot.domain.entities import Approval, Question, ToolCall
from codepilot.domain.enums import ApprovalStatus
from codepilot.domain.events import (
    AgentEvent,
    ApprovalRequiredEvent,
    ErrorEvent,
    MessageEvent,
    QuestionRequiredEvent,
    RunFinishedEvent,
    TokenEvent,
    ToolCallEvent,
    ToolResultEvent,
)


def test_token_event_is_agent_event_with_fields() -> None:
    event = TokenEvent(run_id="r1", seq=0, text="hi")
    assert isinstance(event, AgentEvent)
    assert (event.run_id, event.seq, event.text) == ("r1", 0, "hi")


def test_message_event_tool_calls_default_empty_tuple() -> None:
    event = MessageEvent(run_id="r1", seq=1, content="done")
    assert event.tool_calls == ()
    assert isinstance(event.tool_calls, tuple)


def test_message_event_carries_tool_calls() -> None:
    call = ToolCall(id="c1", name="read_file", arguments={"path": "a.py"})
    event = MessageEvent(run_id="r1", seq=1, content="", tool_calls=(call,))
    assert event.tool_calls == (call,)


def test_tool_result_event_ok_flag() -> None:
    call = ToolCall(id="c1", name="run")
    event = ToolResultEvent(run_id="r1", seq=2, call=call, output="", ok=False)
    assert event.ok is False
    assert event.call is call


def test_approval_required_event_wraps_approval() -> None:
    approval = Approval(
        id="a1",
        session_id="s1",
        run_id="r1",
        tool="write_file",
        payload={},
        preview="",
        status=ApprovalStatus.PENDING,
    )
    event = ApprovalRequiredEvent(run_id="r1", seq=3, approval=approval)
    assert event.approval.status is ApprovalStatus.PENDING


def test_question_required_event_wraps_question() -> None:
    question = Question(id="q1", session_id="s1", run_id="r1", text="用哪个？")
    event = QuestionRequiredEvent(run_id="r1", seq=3, question=question)
    assert event.question is question
    assert event.question.options == ()


def test_run_finished_and_error_events() -> None:
    assert RunFinishedEvent(run_id="r1", seq=4, iterations=2).iterations == 2
    assert ErrorEvent(run_id="r1", seq=4, message="boom").message == "boom"


def test_events_are_frozen() -> None:
    event = ToolCallEvent(run_id="r1", seq=0, call=ToolCall(id="c", name="n"))
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.seq = 9  # type: ignore[misc]
