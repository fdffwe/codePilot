"""审批策略：决定一次工具调用是放行、询问还是拒绝。

纯领域逻辑，不依赖框架与 IO。决策优先级：

1. 硬拒绝（高危命令，如 ``sudo``、``rm -rf /``）——任何模式都不能放行；
2. 显式 DENY 规则；
3. 本次会话已允许的相同操作；
4. 显式 ALLOW / ASK 规则；
5. 审批模式的默认行为。

风险等级只由本模块按工具与参数判定，工具元数据或模型自评都不能下调
（OpenHands 曾因信任模型自评风险而让危险命令自动执行）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from fnmatch import fnmatchcase
from pathlib import PurePosixPath

from codepilot.domain.enums import ToolSafety


class ApprovalMode(StrEnum):
    """审批模式。默认 ``default``：读放行、写与执行询问。"""

    PLAN = "plan"  # 只读：写与执行一律拒绝
    DEFAULT = "default"  # 写与执行询问，高危命令拒绝
    AUTO_EDIT = "auto-edit"  # 编辑放行，执行仍询问
    YOLO = "yolo"  # 全部放行，硬拒绝项除外


class Decision(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """一次调用的审批结论。``risk`` 用于审批卡片展示与审计。"""

    decision: Decision
    risk: str
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ApprovalRule:
    """显式审批规则；``tool="*"`` 匹配任意工具。"""

    tool: str
    decision: Decision
    path: str | None = None
    argv_prefix: tuple[str, ...] = ()
    reason: str = ""

    def matches(self, tool: str, args: Mapping[str, object]) -> bool:
        if self.tool != "*" and self.tool != tool:
            return False
        if self.path is not None and not _match_path(
            str(args.get("path", "")), self.path
        ):
            return False
        if self.argv_prefix:
            argv = args.get("argv")
            if not isinstance(argv, (list, tuple)):
                return False
            prefix = tuple(str(item) for item in argv[: len(self.argv_prefix)])
            return prefix == self.argv_prefix
        return True


@dataclass(slots=True)
class SessionAllowlist:
    """进程内的会话级允许列表；只在当前应用进程内有效。"""

    _items: dict[str, set[tuple[str, ...]]] = field(default_factory=dict)

    def add(self, session_id: str, tool: str, args: Mapping[str, object]) -> None:
        signature = _signature(tool, args)
        if signature is not None:
            self._items.setdefault(session_id, set()).add(signature)

    def allows(self, session_id: str, tool: str, args: Mapping[str, object]) -> bool:
        signature = _signature(tool, args)
        return signature is not None and signature in self._items.get(session_id, set())

    def clear(self, session_id: str) -> None:
        self._items.pop(session_id, None)


@dataclass(slots=True)
class ApprovalPolicy:
    mode: ApprovalMode = ApprovalMode.DEFAULT
    rules: tuple[ApprovalRule, ...] = ()
    allowlist: SessionAllowlist = field(default_factory=SessionAllowlist)

    def decide(
        self,
        *,
        session_id: str,
        tool: str,
        args: Mapping[str, object],
        safety: ToolSafety,
    ) -> PolicyDecision:
        risk = _risk(tool, args, safety)

        if safety is ToolSafety.EXEC:
            denial = _command_denial(_argv(args))
            if denial is not None:
                return PolicyDecision(Decision.DENY, "high", denial)

        for rule in self.rules:
            if rule.decision is Decision.DENY and rule.matches(tool, args):
                return PolicyDecision(
                    Decision.DENY, risk, rule.reason or "命中拒绝规则"
                )

        if self.allowlist.allows(session_id, tool, args):
            return PolicyDecision(Decision.ALLOW, risk, "本次会话已允许相同操作")

        for rule in self.rules:
            if rule.decision is not Decision.DENY and rule.matches(tool, args):
                return PolicyDecision(rule.decision, risk, rule.reason)

        return PolicyDecision(_mode_decision(self.mode, safety), risk)

    def remember(self, session_id: str, tool: str, args: Mapping[str, object]) -> None:
        """记住用户在本次会话中允许过的操作。"""
        self.allowlist.add(session_id, tool, args)


# --- 模式默认 ---

_MODE_DECISIONS: dict[ApprovalMode, dict[ToolSafety, Decision]] = {
    ApprovalMode.PLAN: {
        ToolSafety.WRITE: Decision.DENY,
        ToolSafety.EXEC: Decision.DENY,
    },
    ApprovalMode.DEFAULT: {
        ToolSafety.WRITE: Decision.ASK,
        ToolSafety.EXEC: Decision.ASK,
    },
    ApprovalMode.AUTO_EDIT: {
        ToolSafety.WRITE: Decision.ALLOW,
        ToolSafety.EXEC: Decision.ASK,
    },
    ApprovalMode.YOLO: {
        ToolSafety.WRITE: Decision.ALLOW,
        ToolSafety.EXEC: Decision.ALLOW,
    },
}


def _mode_decision(mode: ApprovalMode, safety: ToolSafety) -> Decision:
    if safety in (ToolSafety.READ, ToolSafety.ASK):
        return Decision.ALLOW
    return _MODE_DECISIONS[mode].get(safety, Decision.ASK)


# --- 风险与硬拒绝 ---

_DENY_EXECUTABLES = frozenset(
    {
        "sudo",
        "su",
        "doas",
        "shutdown",
        "reboot",
        "poweroff",
        "halt",
        "mkfs",
        "mkfs.ext4",
        "fdisk",
        "parted",
    }
)

_HIGH_RISK_EXECUTABLES = frozenset(
    {
        "rm",
        "mv",
        "dd",
        "chmod",
        "chown",
        "kill",
        "pkill",
        "killall",
        "curl",
        "wget",
        "ssh",
        "scp",
        "bash",
        "sh",
        "zsh",
        "powershell",
        "cmd",
    }
)

_PACKAGE_MANAGERS = frozenset(
    {"pip", "pip3", "uv", "npm", "pnpm", "yarn", "apt", "apt-get", "brew", "cargo"}
)

_ROOT_TARGETS = frozenset(
    {
        "",
        "~",
        "$HOME",
        "/etc",
        "/usr",
        "/bin",
        "/boot",
        "/var",
        "/root",
        "/home",
        "/opt",
        "/srv",
        "/tmp",
        "/mnt",
    }
)


def _risk(tool: str, args: Mapping[str, object], safety: ToolSafety) -> str:
    if safety in (ToolSafety.READ, ToolSafety.ASK):
        return "low"
    if safety is ToolSafety.WRITE:
        return "medium"
    return _command_risk(_argv(args))


def _command_risk(argv: Sequence[str]) -> str:
    if not argv:
        return "high"
    exe = _executable(argv[0])
    rest = list(argv[1:])
    if exe in _HIGH_RISK_EXECUTABLES:
        return "high"
    if exe == "git" and (
        "push" in rest or "clean" in rest or ("reset" in rest and "--hard" in rest)
    ):
        return "high"
    if exe in _PACKAGE_MANAGERS and any(
        option in {"install", "add", "remove", "uninstall", "upgrade", "sync"}
        for option in rest
    ):
        return "high"
    return "medium"


def _command_denial(argv: Sequence[str]) -> str | None:
    if not argv:
        return None
    exe = _executable(argv[0])
    if exe in _DENY_EXECUTABLES:
        return f"禁止执行高危命令：{exe}"
    if exe == "dd" and any(str(arg).startswith("of=/dev/") for arg in argv[1:]):
        return "禁止直接写入块设备"
    if exe == "rm" and _rm_destroys_root(argv):
        return "禁止递归删除根目录或系统目录"
    if (
        exe in {"chmod", "chown"}
        and _recursive(argv)
        and any(str(arg).rstrip("/") in {"", "~", "$HOME", "/"} for arg in argv[1:])
    ):
        return f"禁止对根目录递归执行 {exe}"
    if ":(){:|:&};:" in "".join(argv):
        return "禁止 fork 炸弹"
    return None


def _rm_destroys_root(argv: Sequence[str]) -> bool:
    if not _recursive(argv):
        return False
    for raw in argv[1:]:
        target = str(raw)
        if target.startswith("-"):
            continue
        normalized = target.rstrip("/")
        if normalized in _ROOT_TARGETS:
            return True
        # 一级系统目录（/home、/mnt/...）也视为危险
        if normalized.startswith("/") and normalized.count("/") <= 1:
            return True
    return False


def _recursive(argv: Sequence[str]) -> bool:
    for raw in argv[1:]:
        flag = str(raw)
        if flag == "--recursive":
            return True
        if (
            flag.startswith("-")
            and not flag.startswith("--")
            and "r" in flag[1:].lower()
        ):
            return True
    return False


def _argv(args: Mapping[str, object]) -> list[str]:
    value = args.get("argv")
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value]


def _executable(command: str) -> str:
    return command.replace("\\", "/").rsplit("/", 1)[-1]


# --- 规则与允许列表的匹配 ---


def _signature(tool: str, args: Mapping[str, object]) -> tuple[str, ...] | None:
    """会话允许的匹配键：执行命令按完整 argv，文件工具按路径。"""
    if tool == "run_command":
        argv = _argv(args)
        return ("run_command", *argv) if argv else None
    if tool in {"write_file", "edit_file"}:
        path = str(args.get("path", ""))
        return (tool, path) if path else None
    return None


def _match_path(path: str, pattern: str) -> bool:
    """与工作区检索一致：``*`` 不跨目录，``**`` 递归，不含 ``/`` 只匹配文件名。"""
    pattern = pattern.replace("\\", "/")
    if pattern in ("*", "**", "**/*"):
        return True
    if "/" not in pattern:
        return fnmatchcase(PurePosixPath(path).name, pattern)
    target = PurePosixPath(path)
    if target.match(pattern):
        return True
    return pattern.startswith("**/") and target.match(pattern[3:])
