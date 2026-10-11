"""OpenAI 兼容端点的模型工厂（DeepSeek 等）。

密钥以明文仅在内存中传递，不落盘/不进日志。见规范 §9。
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr


class OpenAIChatModelFactory:
    def __init__(self, *, base_url: str, api_key: SecretStr) -> None:
        self._base_url = base_url
        self._api_key = api_key

    def __call__(self, model: str) -> BaseChatModel:
        return ChatOpenAI(
            model=model,
            base_url=self._base_url,
            api_key=self._api_key,
            streaming=True,
        )
