"""Agent 工具集：读写/列目录/执行命令/向用户提问。

工具以 LangChain ``StructuredTool`` 定义，schema 由 ``args_schema`` 自动生成；
``safety`` / ``risk`` / ``preview`` 等元数据挂在 ``tool.metadata`` 上（非只读工具
在执行前需人工确认）。工具函数体不直接碰文件/命令，一律经 Workspace/Executor
端口（规范 §10）；一次 run 的运行时依赖经 ``config`` 注入，不进 checkpoint。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, cast

from langchain_core.messages import ToolMessage
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_core.tools import InjectedToolArg, StructuredTool
from pydantic import BaseModel, Field, ValidationError

from codepilot.core.errors import DomainError
from codepilot.domain.enums import ToolSafety
from codepilot.domain.ports import Executor, WorkspaceProvider

RISK_BY_SAFETY: dict[ToolSafety, str] = {
    ToolSafety.READ: "low",
    ToolSafety.ASK: "low",
    ToolSafety.WRITE: "medium",
    ToolSafety.EXEC: "high",
}


@dataclass(slots=True)
class RunDeps:
    """一次 run 的运行时依赖（经 config 注入节点与工具，不进 checkpoint 状态）。"""

    workspace: WorkspaceProvider
    executor: Executor
    # 已 bind_tools 的可运行体；框架边界，用 Runnable[Any, Any] 承接
    model: Runnable[Any, Any]
    command_timeout_s: float
    # tool_call_id → 已执行结果。interrupt 恢复会重放整个 tools_node，
    # 用它跳过已落盘的副作用；同一 RunDeps 跨 resume 复用，故进程内有效。
    done: dict[str, ToolMessage] = field(default_factory=dict)


def _deps(config: RunnableConfig) -> RunDeps:
    """从 run config 取出运行时依赖。"""
    return cast(RunDeps, config["configurable"]["codepilot_deps"])


def _fmt_validation_error(error: ValidationError) -> str:
    """把参数校验失败转成可回传模型的错误文本（不中断 run）。"""
    return f"参数校验失败：{error}"


# --- 工具参数模型（供模型生成参数 + 校验）---


class ReadFileArgs(BaseModel):
    path: str = Field(description="相对工作区根目录的文件路径")


class ListDirArgs(BaseModel):
    path: str = Field(default=".", description="相对工作区根目录的目录路径")


class GlobArgs(BaseModel):
    pattern: str = Field(
        description="通配模式，匹配工作区相对路径，如 '**/*.py'、'src/**/*.ts'"
    )
    path: str = Field(default=".", description="搜索起始目录，相对工作区根目录")
    max_results: int = Field(default=200, ge=1, le=1000, description="最多返回的文件数")


class GrepArgs(BaseModel):
    pattern: str = Field(description="Python 正则表达式，逐行匹配文件内容")
    path: str = Field(default=".", description="搜索起始目录或文件")
    glob: str | None = Field(
        default=None, description="只搜索匹配该通配模式的文件，如 '**/*.py'"
    )
    case_sensitive: bool = Field(default=True, description="是否区分大小写")
    max_results: int = Field(
        default=100, ge=1, le=500, description="最多返回的匹配行数"
    )


class WriteFileArgs(BaseModel):
    path: str = Field(description="相对工作区根目录的文件路径")
    content: str = Field(description="写入的完整文件内容")


class EditFileArgs(BaseModel):
    path: str = Field(description="相对工作区根目录的文件路径")
    old_string: str = Field(description="待替换的原文本，须与文件内容精确匹配")
    new_string: str = Field(description="替换后的新文本")
    replace_all: bool = Field(
        default=False,
        description="是否替换全部匹配；默认 false，此时原文须在文件中唯一",
    )


class AskUserArgs(BaseModel):
    question: str = Field(
        description="要向用户澄清的问题；仅在信息缺失或需求存在歧义时使用，不要臆测"
    )
    options: list[str] = Field(
        default_factory=list,
        description="供用户快速选择的候选答案；为空则只提供自由输入",
    )


class RunCommandArgs(BaseModel):
    argv: list[str] = Field(
        description="命令及其参数，逐项给出（不经过 shell，不解释管道/重定向）"
    )


# --- 具体实现（经端口）---


async def _read_file(
    path: str, config: Annotated[RunnableConfig, InjectedToolArg]
) -> str:
    return await _deps(config).workspace.read_text(path)


async def _list_dir(
    path: str, config: Annotated[RunnableConfig, InjectedToolArg]
) -> str:
    entries = await _deps(config).workspace.list_dir(path)
    return "\n".join(entries)


async def _glob(
    pattern: str,
    path: str,
    max_results: int,
    config: Annotated[RunnableConfig, InjectedToolArg],
) -> str:
    result = await _deps(config).workspace.glob(pattern, path, max_results=max_results)
    if not result.paths:
        return f"未找到匹配 {pattern!r} 的文件。"
    lines = list(result.paths)
    if result.truncated:
        lines.append(
            f"[已显示前 {len(result.paths)} 个文件，共 {result.total} 个；"
            "请缩小 pattern 或 path]"
        )
    return "\n".join(lines)


async def _grep(
    pattern: str,
    path: str,
    glob: str | None,
    case_sensitive: bool,
    max_results: int,
    config: Annotated[RunnableConfig, InjectedToolArg],
) -> str:
    result = await _deps(config).workspace.grep(
        pattern,
        path,
        glob=glob,
        case_sensitive=case_sensitive,
        max_results=max_results,
    )
    notes: list[str] = []
    if result.truncated:
        notes.append(
            f"[已显示前 {len(result.matches)} 条匹配，可能还有更多；"
            "请缩小 pattern/path/glob]"
        )
    if result.skipped:
        notes.append(f"[已跳过 {result.skipped} 个二进制/超大/不可读文件]")
    if not result.matches:
        body = f"未找到匹配 {pattern!r} 的内容。"
    else:
        body = "\n".join(
            f"{match.path}:{match.line}: {match.text}" for match in result.matches
        )
    return "\n".join([body, *notes])


async def _write_file(
    path: str, content: str, config: Annotated[RunnableConfig, InjectedToolArg]
) -> str:
    await _deps(config).workspace.write_text(path, content)
    return f"已写入 {path}（{len(content)} 字符）"


async def _edit_file(
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool,
    config: Annotated[RunnableConfig, InjectedToolArg],
) -> str:
    count = await _deps(config).workspace.edit_text(
        path, old_string, new_string, replace_all=replace_all
    )
    return f"已编辑 {path}（替换 {count} 处）"


async def _ask_user(
    question: str,
    options: list[str],
    config: Annotated[RunnableConfig, InjectedToolArg],
) -> str:
    # 正常路径由 tools_node 拦截并 interrupt()，不会走到这里
    raise DomainError("ask_user 必须由工具节点的 interrupt 处理")


async def _run_command(
    argv: list[str], config: Annotated[RunnableConfig, InjectedToolArg]
) -> str:
    deps = _deps(config)
    result = await deps.executor.run(
        argv, cwd=deps.workspace.root, timeout_s=deps.command_timeout_s
    )
    parts = [f"exit={result.exit_code}"]
    if result.stdout:
        parts.append(f"stdout:\n{result.stdout}")
    if result.stderr:
        parts.append(f"stderr:\n{result.stderr}")
    if result.truncated:
        parts.append("（输出已截断）")
    return "\n".join(parts)


# --- 预览渲染（进审批卡片）---


def _read_preview(args: ReadFileArgs) -> str:
    return f"读取 {args.path}"


def _list_preview(args: ListDirArgs) -> str:
    return f"列出目录 {args.path}"


def _glob_preview(args: GlobArgs) -> str:
    return f"查找文件：{args.pattern}（在 {args.path} 下）"


def _grep_preview(args: GrepArgs) -> str:
    scope = f"，文件过滤 {args.glob}" if args.glob else ""
    return f"搜索内容：{args.pattern}（在 {args.path} 下{scope}）"


def _write_preview(args: WriteFileArgs) -> str:
    return f"写入 {args.path}：\n{args.content}"


def _edit_preview(args: EditFileArgs) -> str:
    return f"编辑 {args.path}：\n- {args.old_string}\n+ {args.new_string}"


def _ask_preview(args: AskUserArgs) -> str:
    return f"询问用户：{args.question}"


def _run_preview(args: RunCommandArgs) -> str:
    return "执行命令：" + " ".join(args.argv)


# --- 工具定义（LangChain StructuredTool）---

Preview = Callable[[Any], str]


def _make_tool(
    *,
    coroutine: Callable[..., Awaitable[str]],
    name: str,
    description: str,
    args_schema: type[BaseModel],
    safety: ToolSafety,
    preview: Preview,
) -> StructuredTool:
    """构建工具：schema 来自 args_schema，元数据（safety/risk/preview）挂 metadata。"""
    return StructuredTool.from_function(
        coroutine=coroutine,
        name=name,
        description=description,
        args_schema=args_schema,
        metadata={
            "safety": safety,
            "risk": RISK_BY_SAFETY[safety],
            "preview": preview,
        },
        handle_validation_error=_fmt_validation_error,
    )


read_file = _make_tool(
    coroutine=_read_file,
    name="read_file",
    description="读取工作区内某个文本文件的内容。",
    args_schema=ReadFileArgs,
    safety=ToolSafety.READ,
    preview=_read_preview,
)

list_dir = _make_tool(
    coroutine=_list_dir,
    name="list_dir",
    description="列出工作区内某目录下的条目名称（非递归）。",
    args_schema=ListDirArgs,
    safety=ToolSafety.READ,
    preview=_list_preview,
)

glob_files = _make_tool(
    coroutine=_glob,
    name="glob",
    description=(
        "按通配模式查找工作区内的文件，返回工作区相对路径。"
        "pattern 支持 '**' 递归，如 '**/*.py'、'src/**/*.ts'；"
        "默认跳过 .git、node_modules、构建产物等目录。"
        "用于先定位文件，再配合 read_file/grep 查看内容。"
    ),
    args_schema=GlobArgs,
    safety=ToolSafety.READ,
    preview=_glob_preview,
)

grep = _make_tool(
    coroutine=_grep,
    name="grep",
    description=(
        "用正则表达式逐行搜索工作区内的文本文件，返回 '路径:行号: 内容'。"
        "可用 glob 参数限定文件类型（如 '**/*.py'）；"
        "默认跳过 .git、node_modules、二进制与超大文件。"
        "结果超限时会显式提示截断，可缩小 pattern/path/glob 后重试。"
    ),
    args_schema=GrepArgs,
    safety=ToolSafety.READ,
    preview=_grep_preview,
)

write_file = _make_tool(
    coroutine=_write_file,
    name="write_file",
    description="将内容写入工作区内的文件（覆盖写，父目录自动创建）。",
    args_schema=WriteFileArgs,
    safety=ToolSafety.WRITE,
    preview=_write_preview,
)

edit_file = _make_tool(
    coroutine=_edit_file,
    name="edit_file",
    description=(
        "对工作区内的文件做精确字符串替换，无需重写整个文件。"
        "默认要求 old_string 唯一；替换全部匹配时设置 replace_all=true。"
    ),
    args_schema=EditFileArgs,
    safety=ToolSafety.WRITE,
    preview=_edit_preview,
)

ask_user = _make_tool(
    coroutine=_ask_user,
    name="ask_user",
    description=(
        "当需求不明确、缺少关键信息或存在多种合理做法时，向用户提问澄清，"
        "不要自行臆测。可提供候选选项；调用后 run 会暂停直到用户回答，"
        "用户的回答会作为本工具的结果返回。"
    ),
    args_schema=AskUserArgs,
    safety=ToolSafety.ASK,
    preview=_ask_preview,
)

run_command = _make_tool(
    coroutine=_run_command,
    name="run_command",
    description="在工作区根目录执行一条命令并返回输出。argv 逐项给出，不经 shell。",
    args_schema=RunCommandArgs,
    safety=ToolSafety.EXEC,
    preview=_run_preview,
)


TOOLS: list[StructuredTool] = [
    read_file,
    list_dir,
    glob_files,
    grep,
    write_file,
    edit_file,
    ask_user,
    run_command,
]
TOOLS_BY_NAME: dict[str, StructuredTool] = {tool.name: tool for tool in TOOLS}
