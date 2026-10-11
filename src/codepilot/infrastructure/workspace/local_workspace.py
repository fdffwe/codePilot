"""本地直连工作区：绑定本机目录，所有读写经路径校验。

安全闸门（规范 §16）：根目录须在授权白名单内；任何子路径解析后必须仍在根内，
拒绝 ``..`` 逃逸与软链越界。IO 异常在边界转译为领域异常。
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from codepilot.core.errors import DomainError, NotFoundError, PermissionDeniedError
from codepilot.core.paths import ensure_allowed, ensure_within


class LocalDirectWorkspace:
    """绑定一个本机目录的直连工作区。"""

    def __init__(
        self,
        root: str | Path,
        *,
        allowlist: Iterable[str | Path],
    ) -> None:
        self.root: Path = ensure_allowed(root, allowlist)

    def resolve(self, path: str) -> Path:
        """把工作区内的相对/绝对路径解析为规范绝对路径；越界抛异常。"""
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        return ensure_within(candidate, self.root)

    async def read_text(self, path: str) -> str:
        target = self.resolve(path)
        try:
            return target.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise NotFoundError(f"文件不存在：{target}") from exc
        except PermissionError as exc:
            raise PermissionDeniedError(f"无读取权限：{target}") from exc
        except OSError as exc:
            raise DomainError(f"读取失败：{target}") from exc

    async def write_text(self, path: str, content: str) -> None:
        target = self.resolve(path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except PermissionError as exc:
            raise PermissionDeniedError(f"无写入权限：{target}") from exc
        except OSError as exc:
            raise DomainError(f"写入失败：{target}") from exc

    async def list_dir(self, path: str = ".") -> list[str]:
        target = self.resolve(path)
        if not target.is_dir():
            raise NotFoundError(f"目录不存在：{target}")
        try:
            return sorted(entry.name for entry in target.iterdir())
        except OSError as exc:
            raise DomainError(f"列目录失败：{target}") from exc
