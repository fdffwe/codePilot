"""权限配置（Claude 风格 JSON）解析：把配置项转成 ``ApprovalRule``。

格式（``permissions`` 可省略，直接在顶层写 allow/deny/ask 也可）::

    {
      "permissions": {
        "allow": [
          "run_command(uv run pytest:*)",
          "write_file(src/**)",
          "edit_file(src/**)"
        ],
        "ask": ["run_command(git commit:*)"],
        "deny": ["run_command(git push:*)"]
      }
    }

规则写作 ``工具(匹配串)``：

- 命令工具 ``run_command``：匹配串是 argv 前缀，``:*`` 可有可无；
  例 ``Bash(uv run pytest:*)`` 匹配 ``uv run pytest -q``。
- 文件工具 ``read_file/write_file/edit_file/list_dir``：匹配串是工作区相对路径的
  通配模式（``*`` 不跨目录、``**`` 递归）。
- 省略括号或匹配串为空表示该工具的任意调用；``*`` 表示任意工具。
- 兼容 Claude Code 的别名：``Bash``/``Read``/``Write``/``Edit``/``Glob``/``Grep``。

安全：这里只负责解析；硬拒绝与高风险降级由 ``domain/approval.py`` 执行。
配置文件无效或未知工具时整份忽略（失败关闭，只会变回逐次询问）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from codepilot.core.errors import ValidationError
from codepilot.domain.approval import ApprovalRule, Decision

_log = logging.getLogger(__name__)

_TOOL_ALIASES: dict[str, str] = {
    "bash": "run_command",
    "shell": "run_command",
    "run_command": "run_command",
    "read": "read_file",
    "read_file": "read_file",
    "write": "write_file",
    "write_file": "write_file",
    "edit": "edit_file",
    "edit_file": "edit_file",
    "glob": "glob",
    "grep": "grep",
    "ls": "list_dir",
    "listdir": "list_dir",
    "list_dir": "list_dir",
}

_KNOWN_TOOLS = frozenset(_TOOL_ALIASES.values())

# ask 先于 allow 注册：同一操作同时命中时，更保守的 ask 生效
_SECTIONS: tuple[tuple[str, Decision], ...] = (
    ("deny", Decision.DENY),
    ("ask", Decision.ASK),
    ("allow", Decision.ALLOW),
)


def load_rules_file(path: Path) -> tuple[ApprovalRule, ...]:
    """读取并解析权限文件；缺失或无效时返回空规则（不阻断应用）。"""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ()
    except (OSError, UnicodeDecodeError) as exc:
        _log.warning(
            "permissions_read_failed", extra={"path": str(path), "error": str(exc)}
        )
        return ()
    try:
        return parse_permissions(raw)
    except ValidationError as exc:
        _log.warning(
            "permissions_invalid", extra={"path": str(path), "error": str(exc)}
        )
        return ()


def parse_permissions(raw: str) -> tuple[ApprovalRule, ...]:
    """解析 JSON 文本；格式错误抛 ``ValidationError``。"""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"权限配置不是合法 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise ValidationError("权限配置必须是 JSON 对象")

    section = data.get("permissions", data)
    if not isinstance(section, dict):
        raise ValidationError("permissions 必须是 JSON 对象")

    rules: list[ApprovalRule] = []
    for key, decision in _SECTIONS:
        entries = section.get(key, [])
        if entries is None:
            entries = []
        if not isinstance(entries, list):
            raise ValidationError(f"permissions.{key} 必须是数组")
        for entry in entries:
            if not isinstance(entry, str):
                raise ValidationError(f"permissions.{key} 的规则必须是字符串")
            rule = _parse_rule(entry, decision)
            if rule is not None:
                rules.append(rule)
    return tuple(rules)


def _parse_rule(text: str, decision: Decision) -> ApprovalRule | None:
    text = text.strip()
    if not text:
        return None

    tool_part = text
    spec: str | None = None
    if "(" in text or ")" in text:
        if not (text.endswith(")") and "(" in text):
            raise ValidationError(f"规则格式错误：{text}")
        index = text.index("(")
        tool_part = text[:index].strip()
        spec = text[index + 1 : -1].strip()

    tool = _TOOL_ALIASES.get(tool_part.casefold(), tool_part)
    if tool != "*" and tool not in _KNOWN_TOOLS:
        raise ValidationError(f"未知工具：{tool_part}")

    if not spec or spec == "*":
        return ApprovalRule(tool=tool, decision=decision)

    if tool == "run_command":
        prefix = spec[:-2].rstrip() if spec.endswith(":*") else spec
        argv_prefix = tuple(prefix.split())
        if not argv_prefix:
            return ApprovalRule(tool=tool, decision=decision)
        return ApprovalRule(tool=tool, decision=decision, argv_prefix=argv_prefix)

    return ApprovalRule(tool=tool, decision=decision, path=spec)
