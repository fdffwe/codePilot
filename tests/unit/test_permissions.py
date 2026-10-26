"""权限白名单解析与生效测试（Claude 风格 JSON）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codepilot.core.errors import ValidationError
from codepilot.domain.approval import ApprovalMode, ApprovalPolicy, Decision
from codepilot.domain.enums import ToolSafety
from codepilot.infrastructure.permissions import load_rules_file, parse_permissions


def _policy(raw: dict[str, object], *, mode: ApprovalMode = ApprovalMode.DEFAULT):
    rules = parse_permissions(json.dumps(raw))
    return ApprovalPolicy(mode=mode, rules=rules)


def _decide(
    policy: ApprovalPolicy,
    tool: str,
    args: dict[str, object],
    safety: ToolSafety,
) -> Decision:
    return policy.decide(session_id="s1", tool=tool, args=args, safety=safety).decision


def test_allow_rules_skip_prompt_for_write_and_command() -> None:
    policy = _policy(
        {
            "permissions": {
                "allow": ["Bash(uv run pytest:*)", "Edit(src/**)"],
            }
        }
    )

    assert (
        _decide(
            policy,
            "run_command",
            {"argv": ["uv", "run", "pytest", "-q"]},
            ToolSafety.EXEC,
        )
        is Decision.ALLOW
    )
    assert (
        _decide(
            policy,
            "edit_file",
            {"path": "src/a.py", "old_string": "a", "new_string": "b"},
            ToolSafety.WRITE,
        )
        is Decision.ALLOW
    )
    assert (
        _decide(
            policy,
            "write_file",
            {"path": "src/a.py", "content": "x"},
            ToolSafety.WRITE,
        )
        is Decision.ASK
    )


def test_deny_and_ask_rules_keep_precedence() -> None:
    policy = _policy(
        {
            "permissions": {
                "allow": ["Bash(git commit:*)", "Bash(git push:*)"],
                "ask": ["Bash(git commit:*)"],
                "deny": ["Bash(git push:*)"],
            }
        }
    )

    assert (
        _decide(
            policy,
            "run_command",
            {"argv": ["git", "commit", "-m", "x"]},
            ToolSafety.EXEC,
        )
        is Decision.ASK
    )
    assert (
        _decide(
            policy,
            "run_command",
            {"argv": ["git", "push", "origin", "main"]},
            ToolSafety.EXEC,
        )
        is Decision.DENY
    )


def test_high_risk_command_still_asks_even_if_allowed() -> None:
    policy = _policy({"permissions": {"allow": ["Bash(rm -rf:*)", "Bash(sudo:*)"]}})

    assert (
        _decide(
            policy, "run_command", {"argv": ["rm", "-rf", "build"]}, ToolSafety.EXEC
        )
        is Decision.ASK
    )
    # 硬拒绝不受白名单影响
    assert (
        _decide(policy, "run_command", {"argv": ["sudo", "ls"]}, ToolSafety.EXEC)
        is Decision.DENY
    )


def test_permissions_file_cannot_be_written_by_agent() -> None:
    policy = _policy({"permissions": {"allow": ["Write(**)"]}})

    assert (
        _decide(
            policy,
            "write_file",
            {"path": ".codepilot/permissions.json", "content": "{}"},
            ToolSafety.WRITE,
        )
        is Decision.DENY
    )
    assert (
        _decide(
            policy,
            "edit_file",
            {
                "path": "repo/.codepilot/permissions.json",
                "old_string": "a",
                "new_string": "b",
            },
            ToolSafety.WRITE,
        )
        is Decision.DENY
    )


def test_command_cannot_touch_permissions_file() -> None:
    policy = _policy({"permissions": {"allow": ["Bash(python:*)", "Bash(tee:*)"]}})

    for argv in (
        [
            "python",
            "-c",
            "open('.codepilot/permissions.json', 'w').write('{}')",
        ],
        ["tee", ".codepilot/permissions.json"],
    ):
        assert (
            _decide(policy, "run_command", {"argv": argv}, ToolSafety.EXEC)
            is Decision.DENY
        ), argv


def test_top_level_sections_and_bare_tool_are_supported() -> None:
    policy = _policy({"allow": ["write_file"]})

    assert (
        _decide(policy, "write_file", {"path": "any/where.py"}, ToolSafety.WRITE)
        is Decision.ALLOW
    )


def test_invalid_config_is_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_permissions("not json")
    with pytest.raises(ValidationError):
        parse_permissions('{"permissions": {"allow": "Bash(ls)"}}')
    with pytest.raises(ValidationError):
        parse_permissions('{"permissions": {"allow": ["Bash(ls"]}}')
    with pytest.raises(ValidationError):
        parse_permissions('{"permissions": {"allow": ["Nope(ls)"]}}')


def test_load_rules_file_missing_or_invalid_returns_empty(tmp_path: Path) -> None:
    assert load_rules_file(tmp_path / "missing.json") == ()

    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    assert load_rules_file(bad) == ()
