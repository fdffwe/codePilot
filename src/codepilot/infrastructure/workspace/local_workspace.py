"""本地直连工作区：绑定本机目录，所有读写经路径校验。

安全闸门（规范 §16）：根目录须在授权白名单内；任何子路径解析后必须仍在根内，
拒绝 ``..`` 逃逸与软链越界。IO 异常在边界转译为领域异常。
"""

from __future__ import annotations

import asyncio
import fnmatch
import os
import re
from collections.abc import Iterable, Iterator
from pathlib import Path, PurePosixPath

from codepilot.core.errors import (
    DomainError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from codepilot.core.paths import ensure_allowed, ensure_within
from codepilot.domain.entities import (
    GlobResult,
    GrepMatch,
    GrepResult,
    WorkspaceEntry,
)

# 检索时默认跳过的目录：版本库/依赖/构建产物，避免慢且无意义。
_IGNORED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "build",
    }
)
_MAX_SEARCH_FILE_BYTES = 1_000_000
_BINARY_SNIFF_BYTES = 8192
_MAX_MATCH_LINE_CHARS = 2000


def _matches(rel: str, pattern: str) -> bool:
    """按“相对搜索起点”的路径匹配通配模式。

    - ``*``/``?`` 不跨目录；``**`` 递归；``**/*.py`` 也匹配起点下的直接文件。
    - 不含 ``/`` 的模式只匹配直接子项（与 shell glob 一致）。
    """
    pattern = pattern.replace("\\", "/")
    if pattern in ("**", "**/*"):
        return True
    if "/" not in pattern:
        return "/" not in rel and fnmatch.fnmatchcase(PurePosixPath(rel).name, pattern)
    target = PurePosixPath(rel)
    if target.match(pattern):
        return True
    return pattern.startswith("**/") and target.match(pattern[3:])


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
        except UnicodeDecodeError as exc:
            raise ValidationError(
                f"文件不是 UTF-8 文本（可能是二进制）：{target}"
            ) from exc
        except IsADirectoryError as exc:
            raise ValidationError(f"路径是目录而非文件：{target}") from exc
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

    async def edit_text(
        self, path: str, old: str, new: str, *, replace_all: bool = False
    ) -> int:
        """精确字符串替换（不做空白/换行归一化），返回替换处数。"""
        if not old:
            raise ValidationError("待替换内容不能为空")
        if old == new:
            raise ValidationError("新旧内容相同，无需编辑")
        content = await self.read_text(path)
        count = content.count(old)
        if count == 0:
            raise ValidationError(f"未找到待替换内容：{old[:80]!r}")
        if count > 1 and not replace_all:
            raise ValidationError(
                f"待替换内容出现 {count} 次；请补充上下文使其唯一，"
                "或设置 replace_all=true 全部替换"
            )
        updated = content.replace(old, new, -1 if replace_all else 1)
        await self.write_text(path, updated)
        return count if replace_all else 1

    async def list_dir(self, path: str = ".") -> list[str]:
        target = self.resolve(path)
        if not target.is_dir():
            raise NotFoundError(f"目录不存在：{target}")
        try:
            return sorted(entry.name for entry in target.iterdir())
        except OSError as exc:
            raise DomainError(f"列目录失败：{target}") from exc

    async def list_entries(self, path: str = ".") -> list[WorkspaceEntry]:
        target = self.resolve(path)
        if not target.is_dir():
            raise NotFoundError(f"目录不存在：{target}")
        base = Path(path)
        try:
            entries = [
                WorkspaceEntry(
                    name=entry.name,
                    path=(base / entry.name).as_posix(),
                    is_dir=entry.is_dir(),
                )
                for entry in target.iterdir()
            ]
        except OSError as exc:
            raise DomainError(f"列目录失败：{target}") from exc
        # 目录优先，其次按名称（忽略大小写）排序
        entries.sort(key=lambda e: (not e.is_dir, e.name.casefold()))
        return entries

    async def glob(
        self, pattern: str, path: str = ".", *, max_results: int = 200
    ) -> GlobResult:
        """按通配模式查找文件；返回工作区相对路径，按字典序排序。"""
        if not pattern.strip():
            raise ValidationError("通配模式不能为空")
        base = self.resolve(path)
        if not base.exists():
            raise NotFoundError(f"路径不存在：{base}")
        return await asyncio.to_thread(self._glob_sync, base, pattern, max_results)

    async def grep(
        self,
        pattern: str,
        path: str = ".",
        *,
        glob: str | None = None,
        case_sensitive: bool = True,
        max_results: int = 100,
    ) -> GrepResult:
        """按正则搜索文本内容；跳过二进制、超大与不可读文件。"""
        if not pattern:
            raise ValidationError("搜索模式不能为空")
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(pattern, flags)
        except re.error as exc:
            raise ValidationError(f"无效的正则表达式：{exc}") from exc
        base = self.resolve(path)
        if not base.exists():
            raise NotFoundError(f"路径不存在：{base}")
        matches, truncated, skipped = await asyncio.to_thread(
            self._grep_sync, base, regex, glob, max_results
        )
        return GrepResult(matches=tuple(matches), truncated=truncated, skipped=skipped)

    # --- 检索内部实现（在线程中执行，避免阻塞事件循环）---

    def _iter_files(self, base: Path) -> Iterator[Path]:
        """遍历 base 下的普通文件；剪掉忽略目录与符号链接。"""
        if base.is_file():
            yield base
            return
        for root, dirs, files in os.walk(base, followlinks=False):
            dirs[:] = sorted(
                d
                for d in dirs
                if d not in _IGNORED_DIRS and not (Path(root) / d).is_symlink()
            )
            for name in sorted(files):
                candidate = Path(root) / name
                if not candidate.is_symlink():
                    yield candidate

    @staticmethod
    def _rel_to_base(file: Path, base: Path) -> str:
        """返回相对搜索起点的路径；起点是文件时用其文件名。"""
        return base.name if base.is_file() else file.relative_to(base).as_posix()

    def _glob_sync(self, base: Path, pattern: str, max_results: int) -> GlobResult:
        paths: list[str] = []
        for file in self._iter_files(base):
            if _matches(self._rel_to_base(file, base), pattern):
                paths.append(file.relative_to(self.root).as_posix())
        paths.sort()
        total = len(paths)
        return GlobResult(
            paths=tuple(paths[:max_results]),
            total=total,
            truncated=total > max_results,
        )

    def _grep_sync(
        self,
        base: Path,
        regex: re.Pattern[str],
        pattern_glob: str | None,
        max_results: int,
    ) -> tuple[list[GrepMatch], bool, int]:
        matches: list[GrepMatch] = []
        skipped = 0
        for file in self._iter_files(base):
            rel = file.relative_to(self.root).as_posix()
            if pattern_glob is not None and not _matches(
                self._rel_to_base(file, base), pattern_glob
            ):
                continue
            text = self._read_for_search(file)
            if text is None:
                skipped += 1
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if not regex.search(line):
                    continue
                if len(line) > _MAX_MATCH_LINE_CHARS:
                    line = (
                        line[:_MAX_MATCH_LINE_CHARS]
                        + f"…（本行已截断，原长 {len(line)} 字符）"
                    )
                matches.append(GrepMatch(path=rel, line=lineno, text=line))
                if len(matches) > max_results:
                    return matches[:max_results], True, skipped
        return matches, False, skipped

    @staticmethod
    def _read_for_search(path: Path) -> str | None:
        """读取待搜索文本；二进制/超大/不可读返回 None。"""
        try:
            if path.stat().st_size > _MAX_SEARCH_FILE_BYTES:
                return None
            data = path.read_bytes()
        except OSError:
            return None
        if b"\x00" in data[:_BINARY_SNIFF_BYTES]:
            return None
        return data.decode("utf-8", errors="replace")
