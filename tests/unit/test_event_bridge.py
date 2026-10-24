"""事件桥单测：应用/领域事件 → Qt 信号。"""

from __future__ import annotations

from codepilot.application.event_bus import EventBus
from codepilot.application.events import RunStarted
from codepilot.domain.entities import Approval, Question, ToolCall
from codepilot.domain.events import (
    ApprovalRequiredEvent,
    ErrorEvent,
    MessageEvent,
    QuestionRequiredEvent,
    RunFinishedEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from codepilot.ui.bridge import EventBridge


def _bridge() -> tuple[EventBus, EventBridge]:
    bus = EventBus()
    return bus, EventBridge(bus)


def test_run_started_maps_to_signal() -> None:
    bus, bridge = _bridge()
    hits: list[object] = []
    bridge.runStarted.connect(lambda: hits.append(True))
    bus.publish(RunStarted(run_id="r1", session_id="s1"))
    assert hits == [True]


def test_message_event_emits_content_and_skips_empty() -> None:
    bus, bridge = _bridge()
    texts: list[str] = []
    bridge.messageReceived.connect(texts.append)
    bus.publish(MessageEvent(run_id="r1", seq=1, content="你好"))
    bus.publish(MessageEvent(run_id="r1", seq=2, content=""))
    assert texts == ["你好"]


def test_tool_call_and_result_map_to_signals() -> None:
    bus, bridge = _bridge()
    calls: list[tuple[str, str]] = []
    results: list[tuple[str, bool]] = []
    bridge.toolCalled.connect(lambda n, a: calls.append((n, a)))
    bridge.toolResult.connect(lambda out, ok: results.append((out, ok)))
    call = ToolCall(id="c1", name="read_file", arguments={"path": "a.py"})
    bus.publish(ToolCallEvent(run_id="r1", seq=1, call=call))
    bus.publish(ToolResultEvent(run_id="r1", seq=2, call=call, output="ok", ok=True))
    assert calls == [("read_file", str({"path": "a.py"}))]
    assert results == [("ok", True)]


def test_approval_requested_carries_entity() -> None:
    bus, bridge = _bridge()
    got: list[Approval] = []
    bridge.approvalRequested.connect(got.append)
    approval = Approval(
        id="a1",
        session_id="s1",
        run_id="r1",
        tool="write_file",
        payload={},
        preview="+1 -0",
    )
    bus.publish(ApprovalRequiredEvent(run_id="r1", seq=3, approval=approval))
    assert got == [approval]


def test_question_required_maps_to_question_signal() -> None:
    bus, bridge = _bridge()
    got: list[Question] = []
    bridge.questionAsked.connect(got.append)
    question = Question(id="q1", session_id="s1", run_id="r1", text="用哪个？")
    bus.publish(QuestionRequiredEvent(run_id="r1", seq=2, question=question))
    assert got == [question]


def test_run_finished_and_error_map_to_signals() -> None:
    bus, bridge = _bridge()
    iters: list[int] = []
    errors: list[str] = []
    bridge.runFinished.connect(iters.append)
    bridge.errorOccurred.connect(errors.append)
    bus.publish(RunFinishedEvent(run_id="r1", seq=4, iterations=3))
    bus.publish(ErrorEvent(run_id="r1", seq=5, message="boom"))
    assert iters == [3]
    assert errors == ["boom"]
