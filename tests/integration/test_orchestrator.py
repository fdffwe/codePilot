"""LangGraph 编排器集成测试（Fake 模型 + 临时工作区 + 内存 checkpoint）。"""

from __future__ import annotations

import sys
from pathlib import Path

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from codepilot.domain.entities import Message
from codepilot.domain.enums import MessageRole
from codepilot.domain.events import (
    ApprovalRequiredEvent,
    ErrorEvent,
    MessageEvent,
    QuestionRequiredEvent,
    RunFinishedEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from codepilot.infrastructure.agent import LangGraphOrchestrator
from codepilot.infrastructure.executor import LocalExecutor
from codepilot.infrastructure.providers import FakeChatModelFactory
from codepilot.infrastructure.workspace import LocalDirectWorkspace


def _tool_call(name: str, args: dict, cid: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": cid}])


def _orchestrator(responses: list[AIMessage], root: Path) -> LangGraphOrchestrator:
    return LangGraphOrchestrator(
        checkpointer=InMemorySaver(),
        model_factory=FakeChatModelFactory(responses),
        workspace_factory=lambda p: LocalDirectWorkspace(p, allowlist=[root]),
        executor=LocalExecutor(),
        command_timeout_s=10,
        max_iterations=5,
    )


def _user(text: str) -> Message:
    return Message(role=MessageRole.USER, content=text)


async def test_read_flow_emits_tool_events_and_finishes(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello world", encoding="utf-8")
    orch = _orchestrator(
        [
            _tool_call("read_file", {"path": "a.txt"}, "c1"),
            AIMessage(content="读完了"),
        ],
        tmp_path,
    )

    events = [
        ev
        async for ev in orch.stream(
            run_id="r1",
            session_id="s1",
            model="fake",
            messages=[_user("读一下 a.txt")],
            workspace_path=str(tmp_path),
        )
    ]

    assert any(
        isinstance(e, ToolCallEvent) and e.call.name == "read_file" for e in events
    )
    result = next(e for e in events if isinstance(e, ToolResultEvent))
    assert "hello world" in result.output and result.ok
    assert any(isinstance(e, MessageEvent) and e.content == "读完了" for e in events)
    assert isinstance(events[-1], RunFinishedEvent)


async def test_write_requires_approval_and_resumes(tmp_path: Path) -> None:
    orch = _orchestrator(
        [
            _tool_call("write_file", {"path": "new.py", "content": "x = 1\n"}, "c1"),
            AIMessage(content="已创建"),
        ],
        tmp_path,
    )

    first = [
        ev
        async for ev in orch.stream(
            run_id="r2",
            session_id="s1",
            model="fake",
            messages=[_user("写个文件")],
            workspace_path=str(tmp_path),
        )
    ]
    approval = next(e for e in first if isinstance(e, ApprovalRequiredEvent))
    assert approval.approval.tool == "write_file"
    assert not (tmp_path / "new.py").exists()  # 未确认不动盘
    assert not any(isinstance(e, RunFinishedEvent) for e in first)

    second = [ev async for ev in orch.resume("r2", approved=True)]
    assert (tmp_path / "new.py").read_text(encoding="utf-8") == "x = 1\n"
    result = next(e for e in second if isinstance(e, ToolResultEvent))
    assert result.ok
    assert isinstance(second[-1], RunFinishedEvent)


async def test_write_rejected_does_not_write(tmp_path: Path) -> None:
    orch = _orchestrator(
        [
            _tool_call("write_file", {"path": "new.py", "content": "x = 1\n"}, "c1"),
            AIMessage(content="好，不写了"),
        ],
        tmp_path,
    )
    first = [
        ev
        async for ev in orch.stream(
            run_id="r3",
            session_id="s1",
            model="fake",
            messages=[_user("写个文件")],
            workspace_path=str(tmp_path),
        )
    ]
    assert any(isinstance(e, ApprovalRequiredEvent) for e in first)

    second = [ev async for ev in orch.resume("r3", approved=False)]
    assert not (tmp_path / "new.py").exists()
    result = next(e for e in second if isinstance(e, ToolResultEvent))
    assert not result.ok
    assert isinstance(second[-1], RunFinishedEvent)


async def test_iteration_cap_stops_loop(tmp_path: Path) -> None:
    # 永远要求调用工具，应在上限处停止而非死循环
    orch = _orchestrator(
        [_tool_call("list_dir", {"path": "."}, "c1")],
        tmp_path,
    )
    orch._max_iterations = 2
    events = [
        ev
        async for ev in orch.stream(
            run_id="r4",
            session_id="s1",
            model="fake",
            messages=[_user("一直列目录")],
            workspace_path=str(tmp_path),
        )
    ]
    assert isinstance(events[-1], RunFinishedEvent)
    assert events[-1].iterations <= 2


async def test_ask_user_pauses_and_answer_resumes(tmp_path: Path) -> None:
    orch = _orchestrator(
        [
            _tool_call(
                "ask_user",
                {"question": "用哪个名字？", "options": ["alpha", "beta"]},
                "q1",
            ),
            AIMessage(content="好的，用 alpha"),
        ],
        tmp_path,
    )
    first = [
        ev
        async for ev in orch.stream(
            run_id="r6",
            session_id="s1",
            model="fake",
            messages=[_user("改代码")],
            workspace_path=str(tmp_path),
        )
    ]
    asked = next(e for e in first if isinstance(e, QuestionRequiredEvent))
    assert asked.question.text == "用哪个名字？"
    assert asked.question.options == ("alpha", "beta")
    assert asked.question.session_id == "s1"
    assert not any(isinstance(e, ApprovalRequiredEvent) for e in first)
    assert not any(isinstance(e, RunFinishedEvent) for e in first)

    second = [ev async for ev in orch.answer("r6", text="alpha")]
    result = next(e for e in second if isinstance(e, ToolResultEvent))
    assert result.output == "alpha"
    assert result.ok
    assert result.call.name == "ask_user"
    assert any(
        isinstance(e, MessageEvent) and e.content == "好的，用 alpha" for e in second
    )
    assert isinstance(second[-1], RunFinishedEvent)


async def test_ask_user_invalid_args_do_not_pause(tmp_path: Path) -> None:
    orch = _orchestrator(
        [
            _tool_call("ask_user", {}, "q1"),  # 缺 question
            AIMessage(content="参数不对"),
        ],
        tmp_path,
    )
    events = [
        ev
        async for ev in orch.stream(
            run_id="r7",
            session_id="s1",
            model="fake",
            messages=[_user("提问")],
            workspace_path=str(tmp_path),
        )
    ]
    assert not any(isinstance(e, QuestionRequiredEvent) for e in events)
    assert not any(isinstance(e, ApprovalRequiredEvent) for e in events)
    result = next(e for e in events if isinstance(e, ToolResultEvent))
    assert not result.ok
    assert isinstance(events[-1], RunFinishedEvent)


async def test_ask_user_then_write_requires_approval(tmp_path: Path) -> None:
    orch = _orchestrator(
        [
            _tool_call("ask_user", {"question": "写什么？"}, "q1"),
            _tool_call("write_file", {"path": "a.py", "content": "x = 1\n"}, "w1"),
            AIMessage(content="完成"),
        ],
        tmp_path,
    )
    first = [
        ev
        async for ev in orch.stream(
            run_id="r8",
            session_id="s1",
            model="fake",
            messages=[_user("改代码")],
            workspace_path=str(tmp_path),
        )
    ]
    assert any(isinstance(e, QuestionRequiredEvent) for e in first)

    second = [ev async for ev in orch.answer("r8", text="写个变量")]
    assert any(isinstance(e, ApprovalRequiredEvent) for e in second)
    assert not (tmp_path / "a.py").exists()
    assert not any(isinstance(e, RunFinishedEvent) for e in second)

    third = [ev async for ev in orch.resume("r8", approved=True)]
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "x = 1\n"
    assert isinstance(third[-1], RunFinishedEvent)


async def test_answer_wrong_kind_is_rejected(tmp_path: Path) -> None:
    orch = _orchestrator(
        [
            _tool_call("ask_user", {"question": "继续吗？"}, "q1"),
            AIMessage(content="好的"),
        ],
        tmp_path,
    )
    first = [
        ev
        async for ev in orch.stream(
            run_id="r9",
            session_id="s1",
            model="fake",
            messages=[_user("提问")],
            workspace_path=str(tmp_path),
        )
    ]
    assert any(isinstance(e, QuestionRequiredEvent) for e in first)

    wrong = [ev async for ev in orch.resume("r9", approved=True)]
    assert len(wrong) == 1 and isinstance(wrong[0], ErrorEvent)

    right = [ev async for ev in orch.answer("r9", text="继续")]
    assert isinstance(right[-1], RunFinishedEvent)


async def test_multiple_writes_get_distinct_approval_ids(tmp_path: Path) -> None:
    batch = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "write_file",
                "args": {"path": "a.py", "content": "a"},
                "id": "c1",
            },
            {
                "name": "write_file",
                "args": {"path": "b.py", "content": "b"},
                "id": "c2",
            },
        ],
    )
    orch = _orchestrator([batch, AIMessage(content="完成")], tmp_path)
    first = [
        ev
        async for ev in orch.stream(
            run_id="r10",
            session_id="s1",
            model="fake",
            messages=[_user("写两个文件")],
            workspace_path=str(tmp_path),
        )
    ]
    first_approval = next(e for e in first if isinstance(e, ApprovalRequiredEvent))

    second = [ev async for ev in orch.resume("r10", approved=True)]
    second_approval = next(e for e in second if isinstance(e, ApprovalRequiredEvent))
    assert first_approval.approval.id != second_approval.approval.id

    third = [ev async for ev in orch.resume("r10", approved=True)]
    assert (tmp_path / "a.py").exists() and (tmp_path / "b.py").exists()
    assert isinstance(third[-1], RunFinishedEvent)


async def test_approved_effect_not_replayed_on_later_resume(tmp_path: Path) -> None:
    """interrupt 恢复会重放 tools_node；已执行的副作用不得再执行一次。"""
    append = [
        sys.executable,
        "-c",
        "open('log.txt', 'a', encoding='utf-8').write('x')",
    ]
    batch = AIMessage(
        content="",
        tool_calls=[
            {"name": "run_command", "args": {"argv": append}, "id": "c1"},
            {"name": "run_command", "args": {"argv": append}, "id": "c2"},
        ],
    )
    orch = _orchestrator([batch, AIMessage(content="完成")], tmp_path)

    first = [
        ev
        async for ev in orch.stream(
            run_id="r11",
            session_id="s1",
            model="fake",
            messages=[_user("追加两次")],
            workspace_path=str(tmp_path),
        )
    ]
    assert next(e for e in first if isinstance(e, ApprovalRequiredEvent))
    assert not (tmp_path / "log.txt").exists()

    # 批准 c1：执行一次，随后停在 c2 审批
    second = [ev async for ev in orch.resume("r11", approved=True)]
    assert (tmp_path / "log.txt").read_text(encoding="utf-8") == "x"
    assert next(e for e in second if isinstance(e, ApprovalRequiredEvent))

    # 批准 c2：重放时 c1 必须复用缓存，否则会写成 "xxx"
    third = [ev async for ev in orch.resume("r11", approved=True)]
    assert (tmp_path / "log.txt").read_text(encoding="utf-8") == "xx"
    assert isinstance(third[-1], RunFinishedEvent)


async def test_invalid_tool_args_do_not_abort_run(tmp_path: Path) -> None:
    # 参数校验失败应回传 error 结果让模型自纠，而非终止整个 run（P4）
    orch = _orchestrator(
        [
            _tool_call("read_file", {}, "c1"),  # 缺 path
            AIMessage(content="参数不对"),
        ],
        tmp_path,
    )
    events = [
        ev
        async for ev in orch.stream(
            run_id="r5",
            session_id="s1",
            model="fake",
            messages=[_user("读文件")],
            workspace_path=str(tmp_path),
        )
    ]
    result = next(e for e in events if isinstance(e, ToolResultEvent))
    assert not result.ok
    assert isinstance(events[-1], RunFinishedEvent)
