"""Agent 工具集：读写/列目录/执行命令。

工具函数体不直接碰文件/命令，一律经 Workspace/Executor 端口（规范 §10）。
每个工具带 safety 元数据；非只读工具在执行前需人工确认。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.runnables import Runnable
from pydantic import BaseModel, Field

from codepilot.domain.enums import ToolSafety
from codepilot.domain.ports import Executor, WorkspaceProvider


@dataclass(slots=True)
class RunDeps:
    """一次 run 的运行时依赖（经 config 注入节点，不进 checkpoint 状态）。"""

    workspace: WorkspaceProvider
    executor: Executor
    # 已 bind_tools 的可运行体；框架边界，用 Runnable[Any, Any] 承接
    model: Runnable[Any, Any]
    command_timeout_s: float
    max_iterations: int


# --- 工具参数模型（供模型生成参数 + 校验）---


class ReadFileArgs(BaseModel):
    path: str = Field(description="相对工作区根目录的文件路径")


class ListDirArgs(BaseModel):
    path: str = Field(default=".", description="相对工作区根目录的目录路径")


class WriteFileArgs(BaseModel):
    path: str = Field(description="相对工作区根目录的文件路径")
    content: str = Field(description="写入的完整文件内容")


class RunCommandArgs(BaseModel):
    argv: list[str] = Field(
        description="命令及其参数，逐项给出（不经过 shell，不解释管道/重定向）"
    )


# --- 具体实现（经端口）---


async def _read_file(deps: RunDeps, args: ReadFileArgs) -> str:
    return await deps.workspace.read_text(args.path)


async def _list_dir(deps: RunDeps, args: ListDirArgs) -> str:
    entries = await deps.workspace.list_dir(args.path)
    return "\n".join(entries)


async def _write_file(deps: RunDeps, args: WriteFileArgs) -> str:
    await deps.workspace.write_text(args.path, args.content)
    return f"已写入 {args.path}（{len(args.content)} 字符）"


async def _run_command(deps: RunDeps, args: RunCommandArgs) -> str:
    result = await deps.executor.run(
        args.argv, cwd=deps.workspace.root, timeout_s=deps.command_timeout_s
    )
    parts = [f"exit={result.exit_code}"]
    if result.stdout:
        parts.append(f"stdout:\n{result.stdout}")
    if result.stderr:
        parts.append(f"stderr:\n{result.stderr}")
    if result.truncated:
        parts.append("（输出已截断）")
    return "\n".join(parts)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    safety: ToolSafety
    description: str
    args_model: type[BaseModel]
    run: Callable[[RunDeps, Any], Awaitable[str]]
    preview: Callable[[Any], str]

    def schema(self) -> dict[str, Any]:
        """OpenAI 工具格式（ChatOpenAI.bind_tools 可直接消费）。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_model.model_json_schema(),
            },
        }

    @property
    def risk(self) -> str:
        return {
            ToolSafety.READ: "low",
            ToolSafety.WRITE: "medium",
            ToolSafety.EXEC: "high",
        }[self.safety]


def _write_preview(args: WriteFileArgs) -> str:
    return f"写入 {args.path}：\n{args.content}"


def _run_preview(args: RunCommandArgs) -> str:
    return "执行命令：" + " ".join(args.argv)


TOOL_SPECS: dict[str, ToolSpec] = {
    "read_file": ToolSpec(
        name="read_file",
        safety=ToolSafety.READ,
        description="读取工作区内某个文本文件的内容。",
        args_model=ReadFileArgs,
        run=_read_file,
        preview=lambda args: f"读取 {args.path}",
    ),
    "list_dir": ToolSpec(
        name="list_dir",
        safety=ToolSafety.READ,
        description="列出工作区内某目录下的条目名称（非递归）。",
        args_model=ListDirArgs,
        run=_list_dir,
        preview=lambda args: f"列出目录 {args.path}",
    ),
    "write_file": ToolSpec(
        name="write_file",
        safety=ToolSafety.WRITE,
        description="将内容写入工作区内的文件（覆盖写，父目录自动创建）。",
        args_model=WriteFileArgs,
        run=_write_file,
        preview=_write_preview,
    ),
    "run_command": ToolSpec(
        name="run_command",
        safety=ToolSafety.EXEC,
        description="在工作区根目录执行一条命令并返回输出。argv 逐项给出，不经 shell。",
        args_model=RunCommandArgs,
        run=_run_command,
        preview=_run_preview,
    ),
}


def tool_schemas() -> list[dict[str, Any]]:
    return [spec.schema() for spec in TOOL_SPECS.values()]
