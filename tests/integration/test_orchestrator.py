"""LangGraph 编排器集成测试（Fake 模型 + 临时工作区 + 内存 checkpoint）。"""

from __future__ import annotations

from pathlib import Path

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from codepilot.domain.entities import Message
from codepilot.domain.enums import MessageRole
from codepilot.domain.events import (
    ApprovalRequiredEvent,
    MessageEvent,
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
