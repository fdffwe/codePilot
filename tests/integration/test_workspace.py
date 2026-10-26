"""LocalDirectWorkspace 集成测试。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from codepilot.core.errors import (
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
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


async def test_read_binary_raises_validation(tmp_path: Path) -> None:
    (tmp_path / "bin.dat").write_bytes(b"\xff\xfe\x00")
    with pytest.raises(ValidationError):
        await _workspace(tmp_path).read_text("bin.dat")


async def test_read_directory_raises_validation(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    with pytest.raises(ValidationError):
        await _workspace(tmp_path).read_text("sub")


async def test_edit_replaces_unique_occurrence(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    await ws.write_text("mod.py", "x = 1\ny = 2\n")
    assert await ws.edit_text("mod.py", "x = 1", "x = 42") == 1
    assert await ws.read_text("mod.py") == "x = 42\ny = 2\n"


async def test_edit_missing_text_raises_validation(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    await ws.write_text("mod.py", "x = 1\n")
    with pytest.raises(ValidationError):
        await ws.edit_text("mod.py", "nope", "y = 2")
    assert await ws.read_text("mod.py") == "x = 1\n"


async def test_edit_ambiguous_requires_replace_all(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    await ws.write_text("mod.py", "a\na\n")
    with pytest.raises(ValidationError):
        await ws.edit_text("mod.py", "a", "b")
    assert await ws.edit_text("mod.py", "a", "b", replace_all=True) == 2
    assert await ws.read_text("mod.py") == "b\nb\n"


async def test_edit_empty_old_text_rejected(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    await ws.write_text("mod.py", "x = 1\n")
    with pytest.raises(ValidationError):
        await ws.edit_text("mod.py", "", "y")


async def test_edit_missing_file_raises_not_found(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    with pytest.raises(NotFoundError):
        await ws.edit_text("nope.py", "a", "b")


async def test_edit_path_escape_is_rejected(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    with pytest.raises(PermissionDeniedError):
        await ws.edit_text("../outside.txt", "a", "b")


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


# --- glob ---


async def test_glob_matches_recursive_and_skips_ignored(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    for rel in (
        "a.py",
        "src/b.py",
        "src/deep/c.py",
        "node_modules/x.py",
        ".git/y.py",
        "README.md",
    ):
        await ws.write_text(rel, "")

    result = await ws.glob("**/*.py")

    assert result.paths == ("a.py", "src/b.py", "src/deep/c.py")
    assert result.total == 3
    assert not result.truncated


async def test_glob_truncates_and_reports_total(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    for name in ("a.py", "b.py", "c.py"):
        await ws.write_text(name, "")

    result = await ws.glob("*.py", max_results=2)

    assert len(result.paths) == 2
    assert result.total == 3
    assert result.truncated


async def test_glob_skips_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.py").write_text("secret", encoding="utf-8")
    try:
        os.symlink(outside / "secret.py", root / "link.py")
        os.symlink(outside, root / "linkdir")
    except OSError:
        pytest.skip("当前平台不支持创建符号链接")

    result = await _workspace(root).glob("**/*.py")

    assert result.paths == ()


async def test_glob_empty_pattern_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        await _workspace(tmp_path).glob("  ")


async def test_glob_pattern_without_slash_is_not_recursive(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    await ws.write_text("a.py", "")
    await ws.write_text("src/b.py", "")

    result = await ws.glob("*.py")

    assert result.paths == ("a.py",)


async def test_glob_scopes_to_search_path(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    await ws.write_text("a.py", "")
    await ws.write_text("src/b.py", "")
    await ws.write_text("src/deep/c.py", "")

    result = await ws.glob("**/*.py", path="src")

    # 模式相对搜索起点匹配，返回路径仍相对工作区根
    assert result.paths == ("src/b.py", "src/deep/c.py")


async def test_search_missing_path_raises(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    with pytest.raises(NotFoundError):
        await ws.glob("**/*.py", path="nope")
    with pytest.raises(NotFoundError):
        await ws.grep("x", path="nope")


# --- grep ---


async def test_grep_returns_path_line_and_text(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    await ws.write_text("src/a.py", "x = 1\nneedle = 2\n")
    await ws.write_text("b.py", "needle\n")

    result = await ws.grep("needle")

    assert [(m.path, m.line, m.text) for m in result.matches] == [
        ("b.py", 1, "needle"),
        ("src/a.py", 2, "needle = 2"),
    ]
    assert not result.truncated


async def test_grep_respects_glob_and_ignored_dirs(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    await ws.write_text("a.py", "needle\n")
    await ws.write_text("a.txt", "needle\n")
    await ws.write_text("node_modules/x.py", "needle\n")

    result = await ws.grep("needle", glob="**/*.py")

    assert [m.path for m in result.matches] == ["a.py"]


async def test_grep_invalid_regex_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        await _workspace(tmp_path).grep("[")


async def test_grep_skips_binary_and_reports_count(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    (tmp_path / "bin.dat").write_bytes(b"needle\x00rest")
    await ws.write_text("text.txt", "needle\n")

    result = await ws.grep("needle")

    assert [m.path for m in result.matches] == ["text.txt"]
    assert result.skipped == 1


async def test_grep_truncates(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    await ws.write_text("a.txt", "\n".join(f"needle {i}" for i in range(5)))

    result = await ws.grep("needle", max_results=2)

    assert len(result.matches) == 2
    assert result.truncated
