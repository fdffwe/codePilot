"""应用事件 → Qt Signal 的桥。

订阅 EventBus，把领域/应用事件转成 Qt 信号；UI 只连信号，不碰原始事件。
见规范 §15。
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from codepilot.application.event_bus import EventBus
from codepilot.application.events import RunStarted
from codepilot.domain.entities import Approval
from codepilot.domain.events import (
    ApprovalRequiredEvent,
    ErrorEvent,
    MessageEvent,
    RunFinishedEvent,
    ToolCallEvent,
    ToolResultEvent,
)


class EventBridge(QObject):
    runStarted = Signal()
    messageReceived = Signal(str)
    toolCalled = Signal(str, str)  # name, arguments
    toolResult = Signal(str, bool)  # output, ok
    approvalRequested = Signal(object)  # Approval
    runFinished = Signal(int)
    errorOccurred = Signal(str)

    def __init__(self, bus: EventBus) -> None:
        super().__init__()
        bus.subscribe(self._on_event)

    def _on_event(self, event: object) -> None:
        if isinstance(event, RunStarted):
            self.runStarted.emit()
        elif isinstance(event, MessageEvent):
            if event.content:
                self.messageReceived.emit(event.content)
        elif isinstance(event, ToolCallEvent):
            self.toolCalled.emit(event.call.name, str(event.call.arguments))
        elif isinstance(event, ToolResultEvent):
            self.toolResult.emit(event.output, event.ok)
        elif isinstance(event, ApprovalRequiredEvent):
            self.approvalRequested.emit(event.approval)
        elif isinstance(event, RunFinishedEvent):
            self.runFinished.emit(event.iterations)
        elif isinstance(event, ErrorEvent):
            self.errorOccurred.emit(event.message)


__all__ = ["Approval", "EventBridge"]
