"""应用事件（供 GUI 订阅）。

Agent 运行时事件见 ``domain/events.py``；此处是应用层的编排通知。
"""

from __future__ import annotations

from dataclasses import dataclass

from codepilot.domain.entities import Session


@dataclass(frozen=True, slots=True)
class RunStarted:
    run_id: str
    session_id: str


@dataclass(frozen=True, slots=True)
class RunFailed:
    run_id: str
    message: str


@dataclass(frozen=True, slots=True)
class SessionCreated:
    session: Session
