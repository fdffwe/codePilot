"""确定性测试替身：按脚本返回 AI 消息，不触网。

脚本耗尽后循环复用最后一条，避免测试因轮次误差失败。见规范 §11。
"""

from __future__ import annotations

from collections.abc import Iterable

from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage


class FakeChatModelFactory:
    def __init__(self, responses: Iterable[AIMessage]) -> None:
        self._responses = list(responses)

    def __call__(self, model: str) -> BaseChatModel:
        return FakeMessagesListChatModel(responses=list(self._responses))
