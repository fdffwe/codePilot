"""路径安全校验的单测（规范 §16：所有文件操作必须经 paths.py）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from codepilot.core.errors import PermissionDeniedError
from codepilot.core.paths import (
    ensure_allowed,
    ensure_within,
    is_allowed,
    is_within,
)


def test_is_within_child(tmp_path: Path) -> None:
    root = tmp_path / "root"
    child = root / "a" / "b.txt"
    child.parent.mkdir(parents=True)
    child.write_text("x")
    assert is_within(child, root) is True


def test_is_within_is_reflexive(tmp_path: Path) -> None:
    assert is_within(tmp_path, tmp_path) is True


def test_is_within_rejects_outside(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "other" / "f.txt"
    root.mkdir()
    outside.parent.mkdir(parents=True)
    outside.write_text("x")
    assert is_within(outside, root) is False


def test_is_within_blocks_traversal(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "sub").mkdir()
    sneaky = root / "sub" / ".." / ".." / "escape.txt"
    assert is_within(sneaky, root) is False


def test_ensure_within_ok(tmp_path: Path) -> None:
    root = tmp_path / "root"
    f = root / "f.txt"
    root.mkdir()
    f.write_text("x")
    assert ensure_within(f, root) == f.resolve()


def test_ensure_within_raises(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(PermissionDeniedError):
        ensure_within(tmp_path / "outside.txt", root)


def test_is_allowed_multiple_roots(tmp_path: Path) -> None:
    r1 = tmp_path / "one"
    r2 = tmp_path / "two"
    r1.mkdir()
    (r2 / "child").mkdir(parents=True)
    assert is_allowed(r2 / "child", [r1, r2]) is True
    assert is_allowed(tmp_path / "nope", [r1, r2]) is False


def test_ensure_allowed_raises(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    with pytest.raises(PermissionDeniedError):
        ensure_allowed(tmp_path / "denied", [root])
