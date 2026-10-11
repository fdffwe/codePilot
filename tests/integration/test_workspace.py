"""LocalDirectWorkspace 集成测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from codepilot.core.errors import NotFoundError, PermissionDeniedError
from codepilot.infrastructure.workspace import LocalDirectWorkspace


def _workspace(root: Path) -> LocalDirectWorkspace:
    return LocalDirectWorkspace(root, allowlist=[root])


async def test_root_outside_allowlist_is_rejected(tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(PermissionDeniedError):
        LocalDirectWorkspace(tmp_path, allowlist=[other])


async def test_write_then_read_roundtrip(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    await ws.write_text("pkg/mod.py", "x = 1\n")
    assert (tmp_path / "pkg" / "mod.py").read_text(encoding="utf-8") == "x = 1\n"
    assert await ws.read_text("pkg/mod.py") == "x = 1\n"


async def test_read_missing_file_raises_not_found(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    with pytest.raises(NotFoundError):
        await ws.read_text("nope.py")


async def test_path_escape_is_rejected(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    with pytest.raises(PermissionDeniedError):
        ws.resolve("../outside.txt")
    with pytest.raises(PermissionDeniedError):
        await ws.write_text("../outside.txt", "boom")


async def test_list_dir_sorted(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    await ws.write_text("b.py", "")
    await ws.write_text("a.py", "")
    assert await ws.list_dir(".") == ["a.py", "b.py"]


async def test_list_entries_reports_is_dir_and_sorts_dirs_first(
    tmp_path: Path,
) -> None:
    ws = _workspace(tmp_path)
    await ws.write_text("b.py", "")
    await ws.write_text("src/main.py", "")
    entries = await ws.list_entries(".")
    assert [(e.name, e.is_dir) for e in entries] == [("src", True), ("b.py", False)]
    assert entries[0].path == "src"


async def test_list_entries_nested_path(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    await ws.write_text("src/main.py", "")
    entries = await ws.list_entries("src")
    assert [(e.name, e.path, e.is_dir) for e in entries] == [
        ("main.py", "src/main.py", False)
    ]


async def test_list_entries_missing_dir_raises(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    with pytest.raises(NotFoundError):
        await ws.list_entries("nope")
