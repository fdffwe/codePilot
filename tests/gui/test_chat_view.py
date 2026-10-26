"""对话视图测试：消息追加与切换会话时的清空。"""

from __future__ import annotations

from codepilot.ui.views.chat_view import ChatView


def test_add_message_removes_empty_hint(qtbot) -> None:
    view = ChatView()
    qtbot.addWidget(view)

    view.add_message("我", "你好")

    assert view._hint is None


def test_clear_restores_empty_state(qtbot) -> None:
    view = ChatView()
    qtbot.addWidget(view)
    view.add_message("我", "一")
    view.add_message("助手", "二")

    view.clear()

    assert view._hint is not None
    # 前导 stretch + 提示 + 尾部 stretch
    assert view._messages.count() == 3


def test_clear_then_add_message_works(qtbot) -> None:
    view = ChatView()
    qtbot.addWidget(view)
    view.add_message("我", "旧消息")

    view.clear()
    view.add_message("助手", "新消息")

    assert view._hint is None
    # 一个气泡 + 尾部 stretch
    assert view._messages.count() == 2
