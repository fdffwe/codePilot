"""工作区端口。"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from codepilot.domain.entities import WorkspaceEntry


@runtime_checkable
class WorkspaceProvider(Protocol):
    """本地直连工作区：绑定一个本机目录，读写均受路径校验保护。"""

    root: Path

    def resolve(self, path: str) -> Path:
        """把工作区内的相对/绝对路径解析为规范绝对路径。

        越出 ``root`` 抛 :class:`~codepilot.core.errors.PermissionDeniedError`。
        """

    async def read_text(self, path: str) -> str: ...

    async def write_text(self, path: str, content: str) -> None: ...

    async def edit_text(
        self, path: str, old: str, new: str, *, replace_all: bool = False
    ) -> int:
        """精确字符串替换，返回替换处数。

        ``old`` 为空、未匹配或（``replace_all=False`` 时）不唯一，抛
        :class:`~codepilot.core.errors.ValidationError`。
        """

    async def list_dir(self, path: str = ".") -> list[str]: ...

    async def list_entries(self, path: str = ".") -> list[WorkspaceEntry]: ...
