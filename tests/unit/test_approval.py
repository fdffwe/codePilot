"""审批策略单测：模式默认、硬拒绝、规则与会话允许。"""

from __future__ import annotations

from codepilot.domain.approval import (
    ApprovalMode,
    ApprovalPolicy,
    ApprovalRule,
    Decision,
    SessionAllowlist,
)
from codepilot.domain.enums import ToolSafety


def _decide(
    policy: ApprovalPolicy,
    tool: str,
    args: dict[str, object],
    safety: ToolSafety,
    *,
    session_id: str = "s1",
) -> Decision:
    return policy.decide(
        session_id=session_id, tool=tool, args=args, safety=safety
    ).decision


def _write(policy: ApprovalPolicy, path: str = "a.py") -> Decision:
    return _decide(
        policy,
        "write_file",
        {"path": path, "content": "x"},
        ToolSafety.WRITE,
    )


def _exec(policy: ApprovalPolicy, *argv: str) -> Decision:
    return _decide(policy, "run_command", {"argv": list(argv)}, ToolSafety.EXEC)


def test_mode_matrix() -> None:
    plan = ApprovalPolicy(mode=ApprovalMode.PLAN)
    default = ApprovalPolicy(mode=ApprovalMode.DEFAULT)
    auto_edit = ApprovalPolicy(mode=ApprovalMode.AUTO_EDIT)
    yolo = ApprovalPolicy(mode=ApprovalMode.YOLO)

    assert _write(plan) is Decision.DENY
    assert _write(default) is Decision.ASK
    assert _write(auto_edit) is Decision.ALLOW
    assert _write(yolo) is Decision.ALLOW

    assert _exec(plan, "ls") is Decision.DENY
    assert _exec(default, "ls") is Decision.ASK
    assert _exec(auto_edit, "ls") is Decision.ASK
    assert _exec(yolo, "ls") is Decision.ALLOW

    read = ApprovalPolicy(mode=ApprovalMode.PLAN)
    assert (
        _decide(read, "read_file", {"path": "a.py"}, ToolSafety.READ) is Decision.ALLOW
    )


def test_hard_denied_commands_are_never_allowed() -> None:
    yolo = ApprovalPolicy(mode=ApprovalMode.YOLO)
    for argv in (
        ("sudo", "ls"),
        ("rm", "-rf", "/"),
        ("rm", "-rf", "~"),
        ("dd", "if=/dev/zero", "of=/dev/sda"),
        ("sh", "-c", ":(){:|:&};:"),
        ("chmod", "-R", "777", "/"),
    ):
        assert _exec(yolo, *argv) is Decision.DENY, argv


def test_regular_destructive_command_is_high_risk_but_askable() -> None:
    policy = ApprovalPolicy()
    decision = policy.decide(
        session_id="s1",
        tool="run_command",
        args={"argv": ["rm", "-rf", "build"]},
        safety=ToolSafety.EXEC,
    )
    assert decision.decision is Decision.ASK
    assert decision.risk == "high"


def test_command_risk_levels() -> None:
    policy = ApprovalPolicy()

    def risk(*argv: str) -> str:
        return policy.decide(
            session_id="s1",
            tool="run_command",
            args={"argv": list(argv)},
            safety=ToolSafety.EXEC,
        ).risk

    assert risk("git", "push", "origin", "main") == "high"
    assert risk("npm", "install") == "high"
    assert risk("uv", "run", "pytest") == "medium"
    assert risk("echo", "hi") == "medium"


def test_explicit_deny_rule_beats_session_allow() -> None:
    policy = ApprovalPolicy(
        rules=(
            ApprovalRule(
                tool="write_file",
                decision=Decision.DENY,
                path="secrets/**",
                reason="敏感目录",
            ),
        )
    )
    args = {"path": "secrets/key.py", "content": "x"}
    policy.remember("s1", "write_file", args)

    decision = policy.decide(
        session_id="s1", tool="write_file", args=args, safety=ToolSafety.WRITE
    )
    assert decision.decision is Decision.DENY
    assert "敏感目录" in decision.reason


def test_allow_rule_by_argv_prefix() -> None:
    policy = ApprovalPolicy(
        rules=(
            ApprovalRule(
                tool="run_command",
                decision=Decision.ALLOW,
                argv_prefix=("uv", "run", "pytest"),
            ),
        )
    )

    assert _exec(policy, "uv", "run", "pytest", "-q") is Decision.ALLOW
    assert _exec(policy, "uv", "run", "pytestx") is Decision.ASK
    assert _exec(policy, "uv", "run", "black") is Decision.ASK


def test_session_allowlist_matches_exact_operation_only() -> None:
    policy = ApprovalPolicy()

    write_args = {"path": "a.py", "content": "x"}
    policy.remember("s1", "write_file", write_args)
    assert _write(policy, "a.py") is Decision.ALLOW
    assert _write(policy, "b.py") is Decision.ASK
    # 不同会话互不影响
    assert (
        _decide(
            policy,
            "write_file",
            write_args,
            ToolSafety.WRITE,
            session_id="s2",
        )
        is Decision.ASK
    )

    policy.remember("s1", "run_command", {"argv": ["echo", "hi"]})
    assert _exec(policy, "echo", "hi") is Decision.ALLOW
    assert _exec(policy, "echo", "bye") is Decision.ASK


def test_session_allowlist_ignores_read_only_tools() -> None:
    allowlist = SessionAllowlist()
    allowlist.add("s1", "read_file", {"path": "a.py"})
    assert not allowlist.allows("s1", "read_file", {"path": "a.py"})
