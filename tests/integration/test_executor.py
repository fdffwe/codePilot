"""LocalExecutor 集成测试（本机子进程）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from codepilot.core.errors import ExecError, ValidationError
from codepilot.infrastructure.executor import LocalExecutor


async def test_run_captures_stdout(tmp_path: Path) -> None:
    result = await LocalExecutor().run(
        [sys.executable, "-c", "print('hello')"], cwd=tmp_path, timeout_s=10
    )
    assert result.ok
    assert "hello" in result.stdout
    assert not result.truncated


async def test_nonzero_exit_code(tmp_path: Path) -> None:
    result = await LocalExecutor().run(
        [sys.executable, "-c", "raise SystemExit(3)"], cwd=tmp_path, timeout_s=10
    )
    assert result.exit_code == 3
    assert not result.ok


async def test_timeout_kills_process_group(tmp_path: Path) -> None:
    result = await LocalExecutor().run(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        cwd=tmp_path,
        timeout_s=0.3,
    )
    assert result.exit_code == 124
    assert "超时" in result.stderr


async def test_output_is_truncated_to_cap(tmp_path: Path) -> None:
    result = await LocalExecutor(max_output_bytes=100).run(
        [sys.executable, "-c", "print('x' * 10000)"], cwd=tmp_path, timeout_s=10
    )
    assert result.truncated
    assert len(result.stdout) <= 100


async def test_on_output_callback_receives_chunks(tmp_path: Path) -> None:
    seen: list[tuple[str, str]] = []
    await LocalExecutor().run(
        [sys.executable, "-u", "-c", "print('a')"],
        cwd=tmp_path,
        timeout_s=10,
        on_output=lambda name, text: seen.append((name, text)),
    )
    assert any(name == "stdout" and "a" in text for name, text in seen)


async def test_missing_command_raises_exec_error(tmp_path: Path) -> None:
    with pytest.raises(ExecError):
        await LocalExecutor().run(
            ["definitely-not-a-real-cmd-xyz"], cwd=tmp_path, timeout_s=5
        )


async def test_empty_argv_raises_validation_error(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        await LocalExecutor().run([], cwd=tmp_path, timeout_s=5)
