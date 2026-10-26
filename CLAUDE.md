# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概览

codePilot 是**本地单机原生桌面** AI 编码助手（PySide6 + SQLite），形态对标 Claude Code：用户在 GUI 里绑定一个本机目录，用自然语言驱动 AI 读写该目录的真实文件、执行本机命令，写/执行前强制人工确认。**单进程、单用户、无 HTTP/服务端/多租户**。

权威文档在 `docs/`：`REQUIREMENTS.md`（需求）、`TECHNICAL_DESIGN.md`（架构与 ADR，§16 决策表）、`ENGINEERING_PLAN.md`（P0–P5 里程碑与技术债）、`DEVELOPMENT_GUIDELINES.md`（**硬性规范，改动前必读**）、`TOOL_LAYER_ANALYSIS.md`（工具层设计与演进分析）。文档为中文，代码注释/提交信息也用中文。

## 常用命令

```bash
uv sync                                   # 创建 venv 并安装依赖（含 dev 组）
uv run codepilot                          # 启动桌面应用

uv run ruff check .                       # lint
uv run black .                            # 格式化（--check 只校验）
uv run mypy                               # 类型检查（只查 src，见 pyproject）
uv run pytest                             # 全部测试

uv run pytest tests/unit/test_paths.py                   # 单个文件
uv run pytest tests/unit/test_paths.py::test_x -k name   # 单个用例
uv run pytest tests/integration                          # 单个目录

# 数据库迁移（应用启动时会自动 upgrade 到 head，手工操作时用）
uv run alembic revision --autogenerate -m "..."   # 生成迁移
uv run alembic upgrade head

uv run pyinstaller packaging/codepilot.spec --noconfirm   # 打包到 dist/
```

首次运行需在仓库根建 `.env` 并写入 `CODEPILOT_LLM_API_KEY=...`（缺失时 `build_container` 直接抛错、应用弹窗退出）。模型与地址可用 `CODEPILOT_LLM_MODEL` / `CODEPILOT_LLM_BASE_URL` 覆盖，默认 `deepseek-chat` + `https://api.deepseek.com`。

运行时数据（SQLite 库、LangGraph checkpoints、日志）默认在 `~/.codepilot/`，可用 `CODEPILOT_DATA_DIR` 改；排查持久化/恢复问题先看这里。数据库迁移在 `migrations/versions/`，应用启动时自动 `upgrade head`。

`tests/conftest.py` 在导入 Qt 前把 `QT_QPA_PLATFORM=offscreen`，GUI 测试可无头运行。

## 架构（分层 + 端口-适配器）

```
ui ─▶ application ─▶ domain ◀─ infrastructure（实现 domain 的 ports）
```

**依赖方向是硬规则，禁止反向或环**（规范 §2）：

- `domain/`：纯逻辑 + `ports/` 抽象。**禁止** import `langchain`/`langgraph`/`sqlalchemy`/`PySide6`/`httpx` 或任何具体 IO。
- `application/`：用例编排，只依赖 `domain`（通过 `domain/ports`），不得 import 具体 infrastructure。
- `infrastructure/`：框架与 IO 的唯一落点（`agent/ db/ providers/ workspace/ executor/`）。
- `ui/`：PySide6 渲染，**不得**直接 import `infrastructure`，只走 `application`。
- `core/`：横切（config/logging/errors/paths/di）。

**组合根是 `core/di.py::build_container`**：这是唯一允许同时 import 各层的地方，负责跑 Alembic 迁移、建 DB engine、checkpointer、provider、orchestrator、repositories，装配出 `ChatService` + `EventBus`。测试注入 Fake 依赖。

### 关键数据流

1. **GUI → 用例**：`ui/viewmodels/chat_viewmodel.py` 持有 `ChatService`，用 `asyncio.ensure_future` 拉起协程并把结果转成 Qt Signal；Widget 只连信号、不写业务逻辑。
2. **用例 → Agent**：`application/chat_service.py` 调 `AgentOrchestrator.stream()`，逐条消费领域事件 `domain/events.py`（`Message/ToolCall/ToolResult/ApprovalRequired/ApprovalsRequired/QuestionRequired/RunFinished/Error`），落库消息与审批（提问不落库）。
3. **框架隔离**：`infrastructure/agent/orchestrator.py`（`LangGraphOrchestrator`）实现 `AgentOrchestrator` 端口，把 LangGraph 的 `astream(updates)` 转译成领域事件，框架类型不外泄（映射层 `mappers.py`）。
4. **事件回 UI**：`application/event_bus.py`（同步进程内总线）→ `ui/bridge.py::EventBridge` 把事件转成 Qt Signal；`ui/app.py` 用 **qasync** 融合 asyncio 与 Qt 事件循环。总线上有两类事件：Agent 事件（`domain/events.py`）与应用编排事件（`application/events.py`，如 `SessionCreated/RunStarted`）。
5. **GUI 组成**：`ui/main_window.py` 只装配视图与转发，不写业务；布局为 `TitleBar + SessionSidebar + ActivityBar + MainTabs`（文件树 / 代码编辑器 / 对话）+ `Toast`。`ui/viewmodels/chat_viewmodel.py` 是唯一调用 `ChatService` 并暴露 Qt Signal 的入口。

### Agent 引擎（仅存在于 `infrastructure/agent/`）

- `graph.py`：**单个 StateGraph**，`agent → prepare → approval(自环) → execute → agent`。`prepare` 按策略把调用分成直接执行/待审批/待回答/失败；`approval` 节点**每次只调用一次 `interrupt()`**，连续多个待审批调用合并为一批一次确认（提问会截断批次并逐个处理），通过条件边自环推进 `cursor`，审批阶段不产生副作用；`execute` 在全部交互结束后按原顺序统一执行。循环由 `tool_calls` 与 `max_iterations` 控制。
- **HITL**：写/执行工具先经 `domain/approval.py` 的 `ApprovalPolicy` 决策（模式 `plan/default/auto-edit/yolo`，配置项 `CODEPILOT_APPROVAL_MODE`）：只读与命中允许规则/会话允许的调用直接放行，硬拒绝高危命令（`sudo`、`rm -rf /`、写块设备等），其余进入 `approval` 节点：单个调用发 `ApprovalRequiredEvent`，连续多个合并为一批发 `ApprovalsRequiredEvent`，一次 `interrupt({...})` 确认整批。`ChatService.resolve_approval(s)` → `orchestrator.resume` 用 `Command(resume=approved)` 恢复，`remember=True` 时把相同操作加入会话允许列表；`ask_user` 与审批共用同一个交互队列。`ask_user`（safety=`ASK`）同样 `interrupt`，用户回答经 `ChatService.answer_question` → `orchestrator.answer` 以 `Command(resume=text)` 恢复；问题不持久化。检查点用 SQLite，`thread_id = run_id`。
- `tools.py`：LangChain `StructuredTool` 集合 `TOOLS`（`read_file/list_dir/glob/grep/write_file/edit_file/ask_user/run_command`），`safety`/`risk`/`preview` 挂在 `tool.metadata`。**工具函数体不直接碰文件/命令**，一律经 `WorkspaceProvider` / `Executor` 端口；检索（`glob`/`grep`）在 workspace 适配器内用 `asyncio.to_thread` 遍历，默认忽略 `.git`/`node_modules`/构建目录并跳过符号链接。
- 一次 run 的运行时依赖走 `RunDeps`，经 LangGraph `config["configurable"]` 注入节点，**不进 checkpoint 状态**。

## 需要遵守的项目不变量

- **所有 IO 必须 `async`**；不得在事件循环里阻塞（`time.sleep`、同步 subprocess、`requests`）。UI 线程只做渲染。
- **子进程一律 `asyncio.create_subprocess_exec(*argv)`，禁止 `shell=True`**；必须带超时 + 输出上限 + 超时杀进程组（见 `local_executor.py`）。
- **所有文件路径必须经 `core/paths.py`**（`expand`/`ensure_within`/`ensure_allowed`）校验在 workspace 内；拒绝 `..`、绝对路径逃逸、软链越界。`LocalDirectWorkspace` 是唯一 workspace 实现（本地直连）。
- **写/改/删/执行在确认前不落盘**；越权抛 `PermissionDeniedError`。
- 统一异常层级 `core/errors.py`（`DomainError → NotFound/Validation/PermissionDenied/Provider/Exec`）；基础设施异常在边界转译，不泄漏到上层；用户可见消息不含堆栈。
- 日志用 `structlog`（结构化字段，带 `session_id`/`run_id`）；**密钥绝不入库/进日志**。
- 配置用 `pydantic-settings`（`core/config.py`），前缀 `CODEPILOT_`，来源：环境变量 > `.env` > 默认值；密钥用 `SecretStr`。**API Key 只放 `.env`（已 gitignore），绝不硬编码或提交**。

## 测试布局

`tests/{unit,integration,gui}/` 镜像源码结构：

- **unit**：纯逻辑、无 IO（Fake/内存实现）。
- **integration**：SQLite、文件系统沙箱、子进程、orchestrator（`test_e2e_p1.py` 是 P1 主链路端到端）。
- **gui**：`pytest-qt` 测 ViewModel 与关键交互（offscreen）。

**LLM 测试一律用 `infrastructure/providers/fake.py` 的 Fake 替身，离线、确定性**——不触网。`pytest-asyncio` 用 `asyncio_mode = "auto"`，异步测试无需显式 `@pytest.mark.asyncio`。修 bug 先写复现测试。

## 提交约定（Conventional Commits）

`<type>(<scope>): <subject>`，type ∈ `feat|fix|docs|refactor|test|chore|perf|build|ci`；scope 用模块名（`agent|workspace|executor|ui|db|config`）。Trunk-based，短命分支 + rebase，一次提交一件事。提交前跑 `ruff`/`black`/`mypy`/`pytest` 全绿（规范 §20 自查清单）。
