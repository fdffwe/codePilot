"""命令执行器端口。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from codepilot.domain.entities import ExecResult

# 流式输出回调：``(stream, chunk)``，stream ∈ {"stdout", "stderr"}
OutputCallback = Callable[[str, str], None]


@runtime_checkable
class Executor(Protocol):
    """本机子进程执行器（无 shell，超时，输出上限）。"""

    async def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        timeout_s: float,
        on_output: OutputCallback | None = None,
    ) -> ExecResult: ...
