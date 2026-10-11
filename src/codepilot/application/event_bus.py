"""应用事件总线（进程内发布/订阅）。

同步、非阻塞地分发事件；GUI 侧订阅后转成 Qt Signal。见规范 §15。
"""

from __future__ import annotations

from collections.abc import Callable

EventHandler = Callable[[object], None]


class EventBus:
    def __init__(self) -> None:
        self._handlers: list[EventHandler] = []

    def subscribe(self, handler: EventHandler) -> None:
        if handler not in self._handlers:
            self._handlers.append(handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        if handler in self._handlers:
            self._handlers.remove(handler)

    def publish(self, event: object) -> None:
        for handler in tuple(self._handlers):
            handler(event)
