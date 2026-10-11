"""路径规范化与安全校验（跨平台）。

所有文件操作必须经过本模块，保证不越出授权目录。见规范 §16。
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from codepilot.core.errors import PermissionDeniedError


def expand(path: str | Path) -> Path:
    """展开 ~ 并解析为规范化绝对路径（解析软链接）。"""
    return Path(path).expanduser().resolve()


def is_within(child: str | Path, root: str | Path) -> bool:
    """判断 child 是否位于 root 之内（含相等）。"""
    try:
        expand(child).relative_to(expand(root))
    except ValueError:
        return False
    return True


def ensure_within(child: str | Path, root: str | Path) -> Path:
    """校验 child 在 root 内，返回规范化路径；否则抛 PermissionDeniedError。"""
    resolved = expand(child)
    if not is_within(resolved, root):
        raise PermissionDeniedError(f"路径越界：{resolved} 不在 {expand(root)} 之内")
    return resolved


def is_allowed(path: str | Path, allowlist: Iterable[str | Path]) -> bool:
    """判断 path 是否落在授权根部集合的任一之内。"""
    return any(is_within(path, root) for root in allowlist)


def ensure_allowed(path: str | Path, allowlist: Iterable[str | Path]) -> Path:
    """校验 path 在授权范围内，返回规范化路径；否则抛 PermissionDeniedError。"""
    resolved = expand(path)
    if not is_allowed(resolved, allowlist):
        raise PermissionDeniedError(f"路径未授权：{resolved}")
    return resolved
