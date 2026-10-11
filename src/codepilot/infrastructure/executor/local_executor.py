"""本机子进程执行器（无 shell，超时杀进程组，输出上限，流式回调）。

安全（规范 §6/§16）：一律 ``create_subprocess_exec``（禁止 ``shell=True``）；
命令以独立进程组启动，超时对整组发 SIGKILL；输出超过上限即截断并标记。
"""

from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Sequence
from pathlib import Path

from codepilot.core.errors import ExecError, ValidationError
from codepilot.domain.entities import ExecResult
from codepilot.domain.ports import OutputCallback

_READ_SIZE = 65536
# 与 GNU timeout 一致：超时以 124 退出，便于上层识别
TIMEOUT_EXIT_CODE = 124


class LocalExecutor:
    """执行本机命令；不解释 shell 语法，argv 原样传参。"""

    def __init__(self, *, max_output_bytes: int = 1_000_000) -> None:
        self._max_output_bytes = max_output_bytes

    async def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        timeout_s: float,
        on_output: OutputCallback | None = None,
    ) -> ExecResult:
        if not argv:
            raise ValidationError("命令不能为空")

        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            raise ExecError(f"命令不存在：{argv[0]}") from exc
        except OSError as exc:
            raise ExecError(f"命令启动失败：{exc}") from exc

        out_chunks: list[str] = []
        err_chunks: list[str] = []
        total = 0
        truncated = False

        async def pump(
            reader: asyncio.StreamReader | None,
            name: str,
            sink: list[str],
        ) -> None:
            nonlocal total, truncated
            if reader is None:
                return
            while True:
                chunk = await reader.read(_READ_SIZE)
                if not chunk:
                    return
                remaining = self._max_output_bytes - total
                if remaining <= 0:
                    truncated = True
                    continue  # 继续排空管道，避免子进程阻塞
                piece = chunk[:remaining]
                if len(piece) < len(chunk):
                    truncated = True
                total += len(piece)
                text = piece.decode("utf-8", errors="replace")
                sink.append(text)
                if on_output is not None:
                    on_output(name, text)

        drained = asyncio.gather(
            pump(proc.stdout, "stdout", out_chunks),
            pump(proc.stderr, "stderr", err_chunks),
        )
        try:
            await asyncio.wait_for(drained, timeout=timeout_s)
            exit_code = await proc.wait()
        except TimeoutError:
            self._kill_group(proc)
            await proc.wait()
            err_chunks.append(f"\n[codePilot] 命令超时（>{timeout_s}s），已终止。")
            return ExecResult(
                exit_code=TIMEOUT_EXIT_CODE,
                stdout="".join(out_chunks),
                stderr="".join(err_chunks),
                truncated=truncated,
            )

        return ExecResult(
            exit_code=exit_code,
            stdout="".join(out_chunks),
            stderr="".join(err_chunks),
            truncated=truncated,
        )

    @staticmethod
    def _kill_group(proc: asyncio.subprocess.Process) -> None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            return
        except OSError:
            # 退化：进程组信息不可用时直接杀进程
            proc.kill()
