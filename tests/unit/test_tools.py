"""工具层单元测试：schema 生成、元数据、执行与错误处理。"""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig

from codepilot.core.errors import DomainError
from codepilot.domain.enums import ToolSafety
from codepilot.infrastructure.agent.tools import (
    TOOLS,
    TOOLS_BY_NAME,
    RunCommandArgs,
    RunDeps,
    WriteFileArgs,
)
from codepilot.infrastructure.executor import LocalExecutor
from codepilot.infrastructure.workspace import LocalDirectWorkspace


def _config(root: Path) -> RunnableConfig:
    deps = RunDeps(
        workspace=LocalDirectWorkspace(root, allowlist=[root]),
        executor=LocalExecutor(),
        model=None,  # 工具执行不经模型，占位即可
        command_timeout_s=10,
    )
    return {"configurable": {"codepilot_deps": deps}}


def _call(name: str, args: dict, cid: str = "c1") -> dict:
    return {"name": name, "args": args, "id": cid, "type": "tool_call"}


async def _invoke(name: str, args: dict, root: Path) -> ToolMessage:
    return await TOOLS_BY_NAME[name].ainvoke(_call(name, args), _config(root))


# --- schema 与元数据 ---


def test_schemas_exclude_injected_config() -> None:
    for tool in TOOLS:
        props = tool.args_schema.model_json_schema()["properties"]
        assert "config" not in props


def test_metadata_carries_safety_risk_preview() -> None:
    for tool in TOOLS:
        md = tool.metadata or {}
        assert md["safety"] in set(ToolSafety)
        assert md["risk"] in {"low", "medium", "high"}
        assert callable(md["preview"])


def test_previews_render() -> None:
    write = TOOLS_BY_NAME["write_file"].metadata["preview"]
    assert write(WriteFileArgs(path="a.py", content="x=1")) == "写入 a.py：\nx=1"

    run = TOOLS_BY_NAME["run_command"].metadata["preview"]
    assert run(RunCommandArgs(argv=["ls", "-l"])) == "执行命令：ls -l"


def test_unknown_tool_not_registered() -> None:
    assert TOOLS_BY_NAME.get("nope") is None


# --- 执行 ---


async def test_read_file_executes(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    msg = await _invoke("read_file", {"path": "a.txt"}, tmp_path)
    assert msg.content == "hello"
    assert msg.name == "read_file"
    assert msg.tool_call_id == "c1"


async def test_write_file_writes_and_creates_parent(tmp_path: Path) -> None:
    msg = await _invoke(
        "write_file", {"path": "out/x.py", "content": "x=1\n"}, tmp_path
    )
    assert (tmp_path / "out" / "x.py").read_text(encoding="utf-8") == "x=1\n"
    assert "已写入" in msg.content


async def test_run_command_formats_output(tmp_path: Path) -> None:
    msg = await _invoke("run_command", {"argv": ["echo", "hi"]}, tmp_path)
    assert "exit=0" in msg.content
    assert "hi" in msg.content


# --- 错误处理 ---


async def test_invalid_args_return_error_message(tmp_path: Path) -> None:
    """参数校验失败应回传 error ToolMessage，而非抛出中断 run（P4）。"""
    msg = await _invoke("read_file", {}, tmp_path)  # 缺 path
    assert msg.status == "error"
    assert "参数校验失败" in msg.content


async def test_path_escape_raises_domain_error(tmp_path: Path) -> None:
    """工作区外路径应抛 DomainError，由图的 tools_node 兜底转成 error ToolMessage。"""
    with pytest.raises(DomainError):
        await _invoke("read_file", {"path": "../outside.txt"}, tmp_path)
