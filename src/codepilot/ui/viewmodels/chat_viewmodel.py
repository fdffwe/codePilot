"""对话视图模型：把 ChatService 的异步用例暴露给界面。

Widget 只调用本类的方法并连其信号；业务逻辑不在 Widget 里。见规范 §15。
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from PySide6.QtCore import QObject, Signal

from codepilot.application.chat_service import ChatService
from codepilot.core.errors import DomainError
from codepilot.domain.entities import Session


class ChatViewModel(QObject):
    sessionsChanged = Signal(list)
    sessionOpened = Signal(object)  # Session
    errorOccurred = Signal(str)
    busyChanged = Signal(bool)

    def __init__(self, service: ChatService) -> None:
        super().__init__()
        self._service = service
        self._current: Session | None = None
        self._tasks: set[asyncio.Task[Any]] = set()

    @property
    def current(self) -> Session | None:
        return self._current

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def load_sessions(self) -> None:
        self._spawn(self._load_sessions())

    def create_session(self, workspace_path: str) -> None:
        self._spawn(self._create_session(workspace_path))

    def open_session(self, session: Session) -> None:
        self._current = session
        self.sessionOpened.emit(session)

    def send(self, text: str) -> None:
        if self._current is None:
            self.errorOccurred.emit("请先新建或选择一个会话。")
            return
        if not text.strip():
            return
        self._spawn(self._send(text))

    def resolve_approval(self, approval_id: str, approved: bool) -> None:
        self._spawn(self._resolve(approval_id, approved))

    # --- 异步实现 ---

    async def _load_sessions(self) -> None:
        self.sessionsChanged.emit(await self._service.list_sessions())

    async def _create_session(self, workspace_path: str) -> None:
        try:
            session = await self._service.create_session(workspace_path=workspace_path)
        except DomainError as exc:
            self.errorOccurred.emit(str(exc))
            return
        self._current = session
        self.sessionOpened.emit(session)
        self.sessionsChanged.emit(await self._service.list_sessions())

    async def _send(self, text: str) -> None:
        assert self._current is not None
        self.busyChanged.emit(True)
        try:
            await self._service.send(self._current.id, text)
        except DomainError as exc:
            self.errorOccurred.emit(str(exc))
        finally:
            self.busyChanged.emit(False)

    async def _resolve(self, approval_id: str, approved: bool) -> None:
        self.busyChanged.emit(True)
        try:
            await self._service.resolve_approval(approval_id, approved=approved)
        except DomainError as exc:
            self.errorOccurred.emit(str(exc))
        finally:
            self.busyChanged.emit(False)
