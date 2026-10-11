"""事件总线单测。"""

from __future__ import annotations

from codepilot.application.event_bus import EventBus


def test_publish_reaches_subscribers() -> None:
    bus = EventBus()
    seen: list[object] = []
    bus.subscribe(seen.append)
    bus.publish("hello")
    assert seen == ["hello"]


def test_unsubscribe_stops_delivery() -> None:
    bus = EventBus()
    seen: list[object] = []
    handler = seen.append
    bus.subscribe(handler)
    bus.unsubscribe(handler)
    bus.publish("x")
    assert seen == []


def test_subscribe_is_idempotent() -> None:
    bus = EventBus()
    seen: list[object] = []
    bus.subscribe(seen.append)
    bus.subscribe(seen.append)
    bus.publish("x")
    assert seen == ["x"]
