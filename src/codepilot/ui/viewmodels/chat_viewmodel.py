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
from codepilot.domain.approval import PERMISSIONS_RELATIVE_PATH, ApprovalMode
from codepilot.domain.entities import Question, Session

_PERMISSIONS_TEMPLATE = (
    '{\n  "permissions": {\n    "allow": [],\n    "ask": [],\n    "deny": []\n  }\n}\n'
)


class ChatViewModel(QObject):
    sessionsChanged = Signal(list)
    sessionOpened = Signal(object)  # Session
    historyLoaded = Signal(str, list)  # session_id, list[Message]
    errorOccurred = Signal(str)
    busyChanged = Signal(bool)
    approvalModeChanged = Signal(str)  # ApprovalMode.value
    workspaceEntriesLoaded = Signal(str, list)  # path, list[WorkspaceEntry]
    workspaceFileLoaded = Signal(str, str)  # path, content
    workspaceFileSaved = Signal(str)  # path
    permissionsLoaded = Signal(str, str)  # relative path, content

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
        self._spawn(self._load_history(session))

    def set_approval_mode(self, mode: str) -> None:
        try:
            self._service.set_approval_mode(ApprovalMode(mode))
        except (ValueError, DomainError) as exc:
            self.errorOccurred.emit(str(exc))
            return
        self.approvalModeChanged.emit(mode)

    def open_workspace_permissions(self) -> None:
        if self._current is None:
            self.errorOccurred.emit("请先新建或选择一个会话。")
            return
        self._spawn(self._load_permissions(self._current))

    def send(self, text: str) -> None:
        if self._current is None:
            self.errorOccurred.emit("请先新建或选择一个会话。")
            return
        if not text.strip():
            return
        self._spawn(self._send(text))

    def resolve_approval(
        self, approval_id: str, approved: bool, remember: bool = False
    ) -> None:
        self.resolve_approvals([approval_id], approved, remember)

    def resolve_approvals(
        self, approval_ids: list[str], approved: bool, remember: bool = False
    ) -> None:
        self._spawn(self._resolve(approval_ids, approved, remember))

    def answer_question(self, question: Question, text: str) -> None:
        self._spawn(self._answer_question(question, text))

    def list_workspace_dir(self, path: str = ".") -> None:
        if self._current is None:
            return
        self._spawn(self._list_workspace_dir(path))

    def read_workspace_file(self, path: str) -> None:
        if self._current is None:
            return
        self._spawn(self._read_workspace_file(path))

    def save_workspace_file(self, path: str, content: str) -> None:
        if self._current is None:
            return
        self._spawn(self._save_workspace_file(path, content))

    # --- 异步实现 ---

    async def _load_sessions(self) -> None:
        self.sessionsChanged.emit(await self._service.list_sessions())

    async def _load_history(self, session: Session) -> None:
        try:
            messages = await self._service.list_messages(session.id)
        except DomainError as exc:
            self.errorOccurred.emit(str(exc))
            return
        # 加载期间用户可能切到别的会话，过期结果直接丢弃
        if self._current is not None and self._current.id == session.id:
            self.historyLoaded.emit(session.id, messages)

    async def _load_permissions(self, session: Session) -> None:
        try:
            content = await self._service.read_workspace_permissions(session.id)
        except DomainError as exc:
            self.errorOccurred.emit(str(exc))
            return
        if self._current is None or self._current.id != session.id:
            return
        self.permissionsLoaded.emit(
            PERMISSIONS_RELATIVE_PATH, content.strip() or _PERMISSIONS_TEMPLATE
        )

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

    async def _resolve(
        self, approval_ids: list[str], approved: bool, remember: bool = False
    ) -> None:
        self.busyChanged.emit(True)
        try:
            await self._service.resolve_approvals(
                approval_ids, approved=approved, remember=remember
            )
        except DomainError as exc:
            self.errorOccurred.emit(str(exc))
        finally:
            self.busyChanged.emit(False)

    async def _answer_question(self, question: Question, text: str) -> None:
        self.busyChanged.emit(True)
        try:
            await self._service.answer_question(
                question.session_id, question.run_id, text
            )
        except DomainError as exc:
            self.errorOccurred.emit(str(exc))
        finally:
            self.busyChanged.emit(False)

    async def _list_workspace_dir(self, path: str) -> None:
        assert self._current is not None
        try:
            entries = await self._service.list_workspace_entries(self._current.id, path)
        except DomainError as exc:
            self.errorOccurred.emit(str(exc))
            return
        self.workspaceEntriesLoaded.emit(path, entries)

    async def _read_workspace_file(self, path: str) -> None:
        assert self._current is not None
        try:
            content = await self._service.read_workspace_file(self._current.id, path)
        except DomainError as exc:
            self.errorOccurred.emit(str(exc))
            return
        self.workspaceFileLoaded.emit(path, content)

    async def _save_workspace_file(self, path: str, content: str) -> None:
        assert self._current is not None
        try:
            await self._service.write_workspace_file(self._current.id, path, content)
        except DomainError as exc:
            self.errorOccurred.emit(str(exc))
            return
        self.workspaceFileSaved.emit(path)
