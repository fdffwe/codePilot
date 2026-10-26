"""LangGraph 编排器集成测试（Fake 模型 + 临时工作区 + 内存 checkpoint）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from codepilot.domain.approval import ApprovalMode, ApprovalPolicy
from codepilot.domain.entities import Message
from codepilot.domain.enums import MessageRole
from codepilot.domain.events import (
    ApprovalRequiredEvent,
    ApprovalsRequiredEvent,
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


def _orchestrator(
    responses: list[AIMessage],
    root: Path,
    *,
    policy: ApprovalPolicy | None = None,
    permissions_path: Path | None = None,
) -> LangGraphOrchestrator:
    return LangGraphOrchestrator(
        checkpointer=InMemorySaver(),
        model_factory=FakeChatModelFactory(responses),
        workspace_factory=lambda p: LocalDirectWorkspace(p, allowlist=[root]),
        executor=LocalExecutor(),
        command_timeout_s=10,
        max_iterations=5,
        approval_policy=policy,
        permissions_path=permissions_path,
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


async def test_grep_flow_locates_content(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\nneedle = 2\n", encoding="utf-8")
    orch = _orchestrator(
        [
            _tool_call("grep", {"pattern": "needle"}, "c1"),
            AIMessage(content="找到了"),
        ],
        tmp_path,
    )

    events = [
        ev
        async for ev in orch.stream(
            run_id="r1g",
            session_id="s1",
            model="fake",
            messages=[_user("找 needle")],
            workspace_path=str(tmp_path),
        )
    ]

    result = next(e for e in events if isinstance(e, ToolResultEvent))
    assert result.ok and "a.py:2: needle = 2" in result.output
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


async def test_mixed_write_then_question_keeps_call_order(tmp_path: Path) -> None:
    batch = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "write_file",
                "args": {"path": "a.py", "content": "x"},
                "id": "w1",
            },
            {"name": "ask_user", "args": {"question": "继续吗？"}, "id": "q1"},
        ],
    )
    orch = _orchestrator([batch, AIMessage(content="完成")], tmp_path)

    first = [
        ev
        async for ev in orch.stream(
            run_id="r16",
            session_id="s1",
            model="fake",
            messages=[_user("写并问")],
            workspace_path=str(tmp_path),
        )
    ]
    # 交互按调用顺序逐个处理：先审批写入，再提问
    assert any(isinstance(e, ApprovalRequiredEvent) for e in first)
    assert not any(isinstance(e, QuestionRequiredEvent) for e in first)
    assert not (tmp_path / "a.py").exists()

    second = [ev async for ev in orch.resume("r16", approved=True)]
    assert any(isinstance(e, QuestionRequiredEvent) for e in second)
    assert not (tmp_path / "a.py").exists()

    third = [ev async for ev in orch.answer("r16", text="继续")]
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "x"
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


async def test_multiple_writes_share_one_batch_approval(tmp_path: Path) -> None:
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
    # 连续两个写操作合并为一张审批单，只需确认一次
    required = next(e for e in first if isinstance(e, ApprovalsRequiredEvent))
    assert [a.tool for a in required.approvals] == ["write_file", "write_file"]
    assert len({a.id for a in required.approvals}) == 2
    assert not any(isinstance(e, ApprovalRequiredEvent) for e in first)
    assert not (tmp_path / "a.py").exists()

    second = [ev async for ev in orch.resume("r10", approved=True)]
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "a"
    assert (tmp_path / "b.py").read_text(encoding="utf-8") == "b"
    assert isinstance(second[-1], RunFinishedEvent)


async def test_batch_approval_rejected_writes_nothing(tmp_path: Path) -> None:
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
    orch = _orchestrator([batch, AIMessage(content="好，不写了")], tmp_path)
    first = [
        ev
        async for ev in orch.stream(
            run_id="r17",
            session_id="s1",
            model="fake",
            messages=[_user("写两个文件")],
            workspace_path=str(tmp_path),
        )
    ]
    assert any(isinstance(e, ApprovalsRequiredEvent) for e in first)

    second = [ev async for ev in orch.resume("r17", approved=False)]
    assert not (tmp_path / "a.py").exists()
    assert not (tmp_path / "b.py").exists()
    results = [e for e in second if isinstance(e, ToolResultEvent)]
    assert len(results) == 2 and all(not r.ok for r in results)
    assert isinstance(second[-1], RunFinishedEvent)


async def test_batch_approval_then_question_keeps_order(tmp_path: Path) -> None:
    batch = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "write_file",
                "args": {"path": "a.py", "content": "a"},
                "id": "w1",
            },
            {
                "name": "write_file",
                "args": {"path": "b.py", "content": "b"},
                "id": "w2",
            },
            {"name": "ask_user", "args": {"question": "继续吗？"}, "id": "q1"},
        ],
    )
    orch = _orchestrator([batch, AIMessage(content="完成")], tmp_path)

    first = [
        ev
        async for ev in orch.stream(
            run_id="r18",
            session_id="s1",
            model="fake",
            messages=[_user("写并问")],
            workspace_path=str(tmp_path),
        )
    ]
    required = next(e for e in first if isinstance(e, ApprovalsRequiredEvent))
    assert len(required.approvals) == 2
    assert not any(isinstance(e, QuestionRequiredEvent) for e in first)

    second = [ev async for ev in orch.resume("r18", approved=True)]
    assert any(isinstance(e, QuestionRequiredEvent) for e in second)
    assert not (tmp_path / "a.py").exists()

    third = [ev async for ev in orch.answer("r18", text="继续")]
    assert (tmp_path / "a.py").exists() and (tmp_path / "b.py").exists()
    assert isinstance(third[-1], RunFinishedEvent)


async def test_approved_effects_execute_once_after_all_approvals(
    tmp_path: Path,
) -> None:
    """审批阶段不产生副作用，整批批准后 execute 按顺序各执行一次。"""
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
    required = next(e for e in first if isinstance(e, ApprovalsRequiredEvent))
    assert len(required.approvals) == 2
    assert not (tmp_path / "log.txt").exists()

    # 一次批准整批：execute 按顺序执行两次，不重复
    second = [ev async for ev in orch.resume("r11", approved=True)]
    assert (tmp_path / "log.txt").read_text(encoding="utf-8") == "xx"
    assert isinstance(second[-1], RunFinishedEvent)


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


async def test_plan_mode_denies_write_without_prompt(tmp_path: Path) -> None:
    orch = _orchestrator(
        [
            _tool_call("write_file", {"path": "a.py", "content": "x = 1\n"}, "c1"),
            AIMessage(content="没写"),
        ],
        tmp_path,
        policy=ApprovalPolicy(mode=ApprovalMode.PLAN),
    )
    events = [
        ev
        async for ev in orch.stream(
            run_id="r12",
            session_id="s1",
            model="fake",
            messages=[_user("写文件")],
            workspace_path=str(tmp_path),
        )
    ]
    assert not any(isinstance(e, ApprovalRequiredEvent) for e in events)
    result = next(e for e in events if isinstance(e, ToolResultEvent))
    assert not result.ok and "策略拒绝" in result.output
    assert not (tmp_path / "a.py").exists()
    assert isinstance(events[-1], RunFinishedEvent)


async def test_auto_edit_mode_writes_without_prompt(tmp_path: Path) -> None:
    orch = _orchestrator(
        [
            _tool_call("write_file", {"path": "a.py", "content": "x = 1\n"}, "c1"),
            AIMessage(content="写好了"),
        ],
        tmp_path,
        policy=ApprovalPolicy(mode=ApprovalMode.AUTO_EDIT),
    )
    events = [
        ev
        async for ev in orch.stream(
            run_id="r13",
            session_id="s1",
            model="fake",
            messages=[_user("写文件")],
            workspace_path=str(tmp_path),
        )
    ]
    assert not any(isinstance(e, ApprovalRequiredEvent) for e in events)
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "x = 1\n"
    assert isinstance(events[-1], RunFinishedEvent)


async def test_hard_denied_command_never_runs_or_prompts(tmp_path: Path) -> None:
    orch = _orchestrator(
        [
            _tool_call("run_command", {"argv": ["sudo", "ls"]}, "c1"),
            AIMessage(content="没执行"),
        ],
        tmp_path,
    )
    events = [
        ev
        async for ev in orch.stream(
            run_id="r14",
            session_id="s1",
            model="fake",
            messages=[_user("提权")],
            workspace_path=str(tmp_path),
        )
    ]
    assert not any(isinstance(e, ApprovalRequiredEvent) for e in events)
    result = next(e for e in events if isinstance(e, ToolResultEvent))
    assert not result.ok and "禁止执行高危命令" in result.output
    assert isinstance(events[-1], RunFinishedEvent)


async def test_session_allowed_write_skips_prompt(tmp_path: Path) -> None:
    policy = ApprovalPolicy()
    policy.remember("s1", "write_file", {"path": "a.py", "content": "x = 1\n"})
    orch = _orchestrator(
        [
            _tool_call("write_file", {"path": "a.py", "content": "x = 1\n"}, "c1"),
            AIMessage(content="写好了"),
        ],
        tmp_path,
        policy=policy,
    )
    events = [
        ev
        async for ev in orch.stream(
            run_id="r15",
            session_id="s1",
            model="fake",
            messages=[_user("写文件")],
            workspace_path=str(tmp_path),
        )
    ]
    assert not any(isinstance(e, ApprovalRequiredEvent) for e in events)
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "x = 1\n"
    assert isinstance(events[-1], RunFinishedEvent)


async def test_workspace_permissions_allow_skips_prompt(tmp_path: Path) -> None:
    config = tmp_path / ".codepilot"
    config.mkdir()
    (config / "permissions.json").write_text(
        json.dumps({"permissions": {"allow": ["write_file(src/**)"]}}),
        encoding="utf-8",
    )
    orch = _orchestrator(
        [
            _tool_call(
                "write_file", {"path": "src/new.py", "content": "x = 1\n"}, "c1"
            ),
            AIMessage(content="写好了"),
        ],
        tmp_path,
    )

    events = [
        ev
        async for ev in orch.stream(
            run_id="r19",
            session_id="s1",
            model="fake",
            messages=[_user("写文件")],
            workspace_path=str(tmp_path),
        )
    ]

    assert not any(isinstance(e, ApprovalRequiredEvent) for e in events)
    assert (tmp_path / "src" / "new.py").read_text(encoding="utf-8") == "x = 1\n"
    assert isinstance(events[-1], RunFinishedEvent)


async def test_user_permissions_file_allow_skips_prompt(tmp_path: Path) -> None:
    permissions = tmp_path / "user-permissions.json"
    permissions.write_text(
        json.dumps({"permissions": {"allow": ["write_file(**)"]}}),
        encoding="utf-8",
    )
    orch = _orchestrator(
        [
            _tool_call("write_file", {"path": "a.py", "content": "x"}, "c1"),
            AIMessage(content="写好了"),
        ],
        tmp_path,
        permissions_path=permissions,
    )

    events = [
        ev
        async for ev in orch.stream(
            run_id="r20",
            session_id="s1",
            model="fake",
            messages=[_user("写文件")],
            workspace_path=str(tmp_path),
        )
    ]

    assert not any(isinstance(e, ApprovalRequiredEvent) for e in events)
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "x"


async def test_high_risk_command_in_permissions_still_asks(tmp_path: Path) -> None:
    config = tmp_path / ".codepilot"
    config.mkdir()
    (config / "permissions.json").write_text(
        json.dumps({"permissions": {"allow": ["run_command(rm -rf:*)"]}}),
        encoding="utf-8",
    )
    (tmp_path / "build").mkdir()
    orch = _orchestrator(
        [
            _tool_call("run_command", {"argv": ["rm", "-rf", "build"]}, "c1"),
            AIMessage(content="没删"),
        ],
        tmp_path,
    )

    first = [
        ev
        async for ev in orch.stream(
            run_id="r21",
            session_id="s1",
            model="fake",
            messages=[_user("清理")],
            workspace_path=str(tmp_path),
        )
    ]
    assert any(isinstance(e, ApprovalRequiredEvent) for e in first)
    assert (tmp_path / "build").exists()

    [ev async for ev in orch.resume("r21", approved=False)]
    assert (tmp_path / "build").exists()


async def test_agent_cannot_write_permissions_file(tmp_path: Path) -> None:
    config = tmp_path / ".codepilot"
    config.mkdir()
    target = config / "permissions.json"
    original = json.dumps({"permissions": {"allow": ["write_file(**)"]}})
    target.write_text(original, encoding="utf-8")
    orch = _orchestrator(
        [
            _tool_call(
                "write_file",
                {"path": ".codepilot/permissions.json", "content": "{}"},
                "c1",
            ),
            AIMessage(content="改不了"),
        ],
        tmp_path,
    )

    events = [
        ev
        async for ev in orch.stream(
            run_id="r22",
            session_id="s1",
            model="fake",
            messages=[_user("改权限")],
            workspace_path=str(tmp_path),
        )
    ]

    assert not any(isinstance(e, ApprovalRequiredEvent) for e in events)
    result = next(e for e in events if isinstance(e, ToolResultEvent))
    assert not result.ok and "权限配置文件" in result.output
    assert target.read_text(encoding="utf-8") == original
    assert isinstance(events[-1], RunFinishedEvent)


async def test_approval_mode_can_be_switched_at_runtime(tmp_path: Path) -> None:
    orch = _orchestrator(
        [
            _tool_call("write_file", {"path": "auto.py", "content": "x = 1\n"}, "c1"),
            AIMessage(content="已写入"),
        ],
        tmp_path,
    )
    assert orch.approval_mode is ApprovalMode.DEFAULT

    orch.set_approval_mode(ApprovalMode.AUTO_EDIT)
    events = [
        ev
        async for ev in orch.stream(
            run_id="r-mode",
            session_id="s1",
            model="fake",
            messages=[_user("写个文件")],
            workspace_path=str(tmp_path),
        )
    ]

    assert orch.approval_mode is ApprovalMode.AUTO_EDIT
    assert not any(
        isinstance(e, (ApprovalRequiredEvent, ApprovalsRequiredEvent)) for e in events
    )
    assert (tmp_path / "auto.py").read_text(encoding="utf-8") == "x = 1\n"
    assert isinstance(events[-1], RunFinishedEvent)
