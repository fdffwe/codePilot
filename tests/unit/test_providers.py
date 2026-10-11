"""Provider 单测（不触网）。"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from codepilot.infrastructure.providers import (
    ChatModelFactory,
    FakeChatModelFactory,
    OpenAIChatModelFactory,
)


def test_openai_factory_builds_chatopenai_with_model() -> None:
    factory = OpenAIChatModelFactory(
        base_url="https://api.deepseek.com", api_key=SecretStr("sk-test")
    )
    model = factory("deepseek-v4-flash")
    assert isinstance(model, ChatOpenAI)
    name = getattr(model, "model_name", None) or model.model
    assert name == "deepseek-v4-flash"


async def test_fake_factory_returns_scripted_message() -> None:
    factory = FakeChatModelFactory([AIMessage("hello")])
    model = factory("any")
    result = await model.ainvoke([HumanMessage("hi")])
    assert result.content == "hello"


async def test_fake_factory_supports_tool_calls() -> None:
    factory = FakeChatModelFactory(
        [
            AIMessage(
                content="", tool_calls=[{"name": "read_file", "args": {}, "id": "c1"}]
            )
        ]
    )
    model = factory("any")
    result = await model.ainvoke([HumanMessage("read something")])
    assert result.tool_calls
    assert result.tool_calls[0]["name"] == "read_file"


def test_factories_satisfy_protocol() -> None:
    assert isinstance(
        OpenAIChatModelFactory(base_url="x", api_key=SecretStr("y")), ChatModelFactory
    )
    assert isinstance(FakeChatModelFactory([]), ChatModelFactory)
