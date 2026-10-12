# codePilot 技术设计文档（TDD）

> 版本：v3.0（目标态架构 / Target Architecture）
> 日期：2026-10-11
> 关联：`docs/REQUIREMENTS.md`
> 定位：**本地自托管、单用户、原生桌面 GUI 的 AI 编码助手**——形态对标 Claude Code，操作对象是**用户本机的真实代码目录**。
> 关于"企业级"：本文的"企业级"指**工程标准**（分层、端口隔离、测试、可观测、迁移、版本治理），而非云端多租户 SaaS。系统**仅在本地单机运行**，是**桌面应用**，不对公网提供服务。

---

## 1. 目标与范围

### 1.1 系统是什么
- 用户在本机安装并打开 codePilot **桌面应用**（原生 GUI 窗口，非浏览器）。
- 用户在应用里**指定一个本机目录**，用自然语言与 agent 对话。
- agent 通过 LLM（默认 `deepseek-chat`）**读写该目录真实文件、执行本机命令**（跑测试/构建），并在**写/改/执行前请求用户确认**。
- 会话/消息/审批记录存**本地 SQLite**；文件操作直接作用于本机文件系统。

### 1.2 明确不做（Non-Goals）
- **无浏览器 / Web 形态**（无前端 SPA、无 HTTP 服务、无 WebSocket、无 CORS）。
- **无云端部署**、无多租户、无账号/SSO、无计费。
- **无容器级沙箱**（在本机执行，安全靠"白名单 + 确认 + 黑名单 + 快照"）。
- 无多区域/灾备、无 K8s、无消息队列。

### 1.3 "企业级"在本项目的落点
| 维度 | 落实 |
|------|------|
| 分层与解耦 | 端口-适配器；框架/IO 不渗入领域层；GUI 只依赖 application 层 |
| 可测试 | 依赖注入 + Fake 模型；核心逻辑与 GUI 解耦，可无头测试 |
| 可维护 | 类型完备（mypy）、Lint 门禁、版本锁定 |
| 可观测 | 结构化日志（本地文件）；可选 OTel |
| 数据安全 | Alembic 迁移、写入前快照/回滚 |
| 安全 | 目录白名单、人工确认、命令黑名单、密钥隔离 |
| 可分发 | 跨平台安装包 + Python 运行时内置 |

---

## 2. 质量属性

| 属性 | 目标 |
|------|------|
| 安全（首要） | 只能在授权目录内操作；写/执行必确认；危险命令拦截 |
| 正确性 | 文件改动可预期、可回滚；命令结果准确回传 |
| 响应性 | **UI 永不阻塞**：耗时工作在后台事件循环；流式输出；长命令实时日志 |
| 可维护性 | 分层清晰、GUI 与逻辑解耦、可单测 |
| 可恢复性 | 崩溃不丢会话；写入前快照可回滚 |
| 可移植 | Windows / macOS / Linux 可运行、可打包 |

> 本地单用户桌面应用，**不需要** 99.9% 可用性、跨区容灾等云端 SLO。

---

## 3. 总体架构

### 3.1 运行形态（单进程桌面应用）
```
┌────────────────────────────────────────────────────────────────┐
│  codePilot Desktop Process                                      │
│                                                                 │
│  ┌───────────────────────────┐   Qt Signals / 事件桥             │
│  │  Presentation (PySide6)    │◀─────────────────────────────┐  │
│  │  MainWindow / ChatView /   │                              │  │
│  │  DiffView / FileTree /     │  调用(直接函数调用, 异步)       │  │
│  │  TerminalView / Settings   │──────────────────────────┐   │  │
│  └───────────────────────────┘                          │   │  │
│                                                          ▼   │  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Application 层 (用例服务: Session/Chat/Confirm)          │  │
│  ├──────────────────────────────────────────────────────────┤  │
│  │  Domain 层 (Entities + Ports; 无框架依赖)                 │  │
│  ├──────────────────────────────────────────────────────────┤  │
│  │  Infrastructure                                          │  │
│  │   Agent(LangChain+LangGraph) · Repos(SQLAlchemy/aiosqlite)│  │
│  │   Workspace(LocalDirect FS) · Executor(subprocess)        │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  统一 asyncio 事件循环（qasync 与 Qt 事件循环合一）              │
└────────────────────────────────────────────────────────────────┘
        │直接读写                     │执行                    │调用
        ▼                             ▼                        ▼
  本机文件系统(用户目录)        本机子进程             LLM API(DeepSeek/…)
                                 本地 SQLite(codepilot.db)
```
**要点**：**单进程、单事件循环**（qasync 把 asyncio 与 Qt 主循环合并）；GUI 通过 Qt Signal 接收后台事件，通过直接函数调用（await）触发用例；无任何网络服务。

### 3.2 内部分层（模块化单体）
```
Presentation  (PySide6: 窗口/视图/ViewModel)   ← 只依赖 Application
Application   (用例编排: SessionService/ChatService/ConfirmService)
Domain        (Entities + Ports; 纯逻辑, 无框架)
Infrastructure(LangChain/LangGraph · SQLAlchemy/aiosqlite · LocalWorkspace · LocalExecutor · Providers)
```
- 依赖单向向下；领域层只依赖 `domain/ports` 抽象。
- **关键**：Presentation 层**不 import** LangChain/LangGraph/SQLAlchemy；只调用 Application 接口。

### 3.3 进程与线程模型
- **一个进程 + 一个 asyncio 事件循环**（`qasync` 将其与 Qt 事件循环融合）。
- 所有耗时操作（LLM 调用、文件 IO、子进程、DB）均为 `async`，在事件循环上并发执行，**不阻塞 UI**。
- 后台任务（Agent run）以 `asyncio.Task` 运行；通过 **Qt Signal（队列连接）** 把增量事件投递到 UI 线程更新界面。
- 纯 CPU 密集若出现，可用 `QThreadPool`/`run_in_executor` 卸载；常规场景不需要。

---

## 4. 技术栈

### 4.1 应用与后端（Python）
| 组件 | 选型 | 理由 |
|------|------|------|
| 语言 | Python 3.11+ | 异步、类型、AI 生态 |
| **GUI** | **PySide6（Qt for Python）** | 原生控件、成熟、跨平台、LGPL |
| GUI 与异步整合 | **qasync** | 让 asyncio 与 Qt 事件循环合一，UI 不阻塞 |
| **Agent 编排** | **LangGraph** + `langgraph-checkpoint-sqlite` | 状态图、多智能体、checkpoint、HITL、流式 |
| **Agent 基础** | **LangChain**（`langchain-core`/`langchain-openai`/`langchain-anthropic`） | 模型、消息、工具、解析、检索、记忆 |
| LLM Provider | openai SDK（默认 DeepSeek 兼容）/ anthropic | 多后端，经抽象隔离 |
| ORM/迁移 | SQLAlchemy 2.0 (async) + Alembic | 类型完备、迁移 |
| **DB** | **SQLite**（`aiosqlite`，WAL 模式） | 嵌入式、零配置、随 App 分发 |
| 子进程 | `asyncio.create_subprocess_exec`（标准库） | 本机执行命令，无 shell |
| 文件监听（可选） | watchdog | 检测外部改动 |
| 结构化日志 | structlog | 日志落本地文件 |
| 可观测（可选） | OpenTelemetry SDK | 本地 trace |
| 依赖管理 | uv | 锁文件 |
| 测试 | pytest / pytest-asyncio / pytest-qt | 单测/集成/GUI；LangChain `FakeChatModel` |
| 质量 | ruff / mypy / black | Lint/类型/格式化 |
| **打包** | **PyInstaller**（或 Nuitka） | 生成 .exe/.app/AppImage，内置运行时 |

### 4.2 GUI 组件选型（PySide6）
| 需求 | 方案 |
|------|------|
| 主窗口/布局 | `QMainWindow` + Dock 布局（左侧文件树、中部对话、底部终端） |
| 对话/富文本 | `QTextBrowser`/`QTextDocument`（Markdown 渲染）或自绘 `QListView` |
| Diff 展示 | `difflib` 生成 + `QSyntaxHighlighter` 着色（或内嵌 Scintilla） |
| 代码浏览 | `QPlainTextEdit` + 行号 / `QScintilla` |
| 终端/命令输出 | `QProcess`（非交互子进程）输出到只读 `QPlainTextEdit` |
| 文件树 | `QTreeView` + `QFileSystemModel`（限 workspace） |
| 目录选择 | `QFileDialog.getExistingDirectory`（限白名单根） |
| 设置页 | `QDialog` + 表单控件 |
| 提示/确认 | 自定义确认卡片（展示 diff/命令）+ `QMessageBox` |

> 说明：命令为**非交互**执行，终端视图是**只读输出日志**，无需完整 PTY。

### 4.3 打包 / 分发
| 项 | 选型 |
|----|------|
| 打包工具 | PyInstaller（one-dir 优先，启动快）/ Nuitka（可选） |
| 目标产物 | Windows `.exe` / macOS `.app`(可选签名公证) / Linux AppImage |
| 构建 | CI 各平台分别构建（matrix） |
| 自动更新（可选） | 轻量 updater（检查版本 + 下载替换） |

---

## 5. 核心（非 GUI）详细设计

### 5.1 目录结构
```
codepilot/
├── pyproject.toml
├── alembic/versions/
├── src/codepilot/
│   ├── __main__.py             # 入口：qasync 启动 Qt app
│   ├── core/
│   │   ├── config.py           # Settings（pydantic-settings）
│   │   ├── logging.py          # structlog → 本地文件
│   │   ├── errors.py           # 领域异常
│   │   ├── paths.py            # 路径规范化/白名单校验（跨平台）
│   │   └── di.py               # 依赖装配（应用级容器）
│   ├── domain/
│   │   ├── entities.py
│   │   ├── enums.py
│   │   ├── events.py           # Agent 运行时事件（无框架）
│   │   └── ports/              # workspace / executor / repositories / agent
│   ├── application/
│   │   ├── session_service.py
│   │   ├── chat_service.py
│   │   ├── confirm_service.py
│   │   ├── context_manager.py
│   │   └── events.py           # 应用事件（供 GUI 订阅）
│   ├── infrastructure/
│   │   ├── agent/              # ★ LangChain + LangGraph（唯一 import 框架处）
│   │   │   ├── graph.py · nodes/ · tools_adapter.py
│   │   │   ├── model_adapter.py · checkpointer.py · events.py
│   │   ├── db/                 # engine/orm/repositories (SQLAlchemy+aiosqlite)
│   │   ├── providers/          # openai_provider.py / anthropic_provider.py
│   │   ├── workspace/          # local_workspace.py（白名单+快照）
│   │   └── executor/           # local_executor.py（subprocess）
│   └── ui/                     # ★ Presentation (PySide6)
│       ├── app.py              # QApplication 装配 + di 注入
│       ├── main_window.py
│       ├── views/              # chat/diff/file_tree/terminal/settings
│       ├── viewmodels/         # 状态与事件桥(QObject + Signals)
│       └── bridge.py           # 应用事件 → Qt Signal 的桥接
└── tests/{unit,integration,gui}/
```

### 5.2 依赖注入与装配
- 应用级 `Container`（`core/di.py`）构造 Repository/Provider/Workspace/Executor/ToolRegistry/AgentEngine，注入 Application 服务；Application 服务注入 ViewModel。
- 领域层只依赖 `domain/ports`；测试注入 Fake（`FakeChatModel`（注入 agent 引擎）/内存 Repo），**可无 GUI 测试**。

### 5.3 配置
- `pydantic-settings`：环境变量 > 用户配置文件（`~/.codepilot/config.toml`）> 默认值。
- 关键项：`workspace_allowlist`、`llm_provider/base_url/api_key/model`、`command_timeout_s`、`agent_max_iterations`、`db_path`、`log_level`。
- 敏感项（`llm_api_key`）用 `SecretStr`，存本地配置，日志脱敏，**不出现在 UI 明文**。

### 5.4 异步与执行
- 统一事件循环（qasync）；DB async（aiosqlite，SQLite 开 **WAL** 提升并发读）。
- 命令执行：`asyncio.create_subprocess_exec(*argv, cwd=workspace)`（**无 shell**），超时 + 输出上限 + 进程组 kill，输出增量回调 → GUI。
- Agent run 为后台 `asyncio.Task`；崩溃恢复依赖 LangGraph checkpointer（§6.3）。

### 5.5 错误处理
```python
class DomainError(Exception): code; message
class NotFoundError(DomainError)
class ValidationError(DomainError)
class PermissionDenied(DomainError)   # 越界/黑名单
class ProviderError(DomainError)      # LLM 上游
class ExecError(DomainError)          # 命令/IO
```
- Application 边界捕获并转换为用户可读消息；GUI 统一提示（状态栏/对话框），细节仅入日志。

---

## 6. Agent 引擎（LangChain + LangGraph）

> 选型（ADR-8）：**LangChain = 基础能力**；**LangGraph = 编排**。框架仅存在于 `infrastructure/agent/`，GUI 与领域层不感知。

### 6.1 分工
| 能力 | 构件 |
|------|------|
| 模型 | `ChatOpenAI`（默认 DeepSeek 兼容）/ `ChatAnthropic` |
| 消息/内容 | `HumanMessage`/`AIMessage`/`ToolMessage` |
| 工具 | `@tool`/`StructuredTool`（附 `safety` 元数据） |
| 解析 | `with_structured_output` |
| 记忆 | State `messages` + LangGraph `Store` |
| 编排 | `StateGraph` / 条件边 / 子图 |
| 多智能体 | supervisor + 子图 handoff |
| 持久化 | `Checkpointer`（SQLite/SqliteSaver） |
| HITL | `interrupt()` + `Command(resume=...)` |
| 流式 | `astream_events` / `stream_mode` |

### 6.2 多智能体编排（LangGraph 子图）
```
 Supervisor Graph (State: messages/plan/scratchpad/approval; Checkpointer=SQLite)
   ├── Planner  subgraph  → 计划 DAG，可 re-plan
   ├── Coder    subgraph  → 写/改文件（经工具→执行器）
   ├── Debugger subgraph  → 执行→读输出→改→重跑闭环
   └── Reviewer subgraph  → run_tests/静态检查，独立校验
                 │
                 ▼
      ToolRegistry → LocalExecutor / LocalWorkspace（本机）
```
- 子智能体通过共享 State 的 `messages`/`scratchpad` 交换产物（黑板）。
- Reviewer 不通过则回边到 Coder/Debugger，质量闭环。
- `AgentState`（TypedDict）承载 `plan`/`artifacts`/`risk`/`approval`，reducer 控制合并。

### 6.3 Durable（LangGraph Checkpointer）
- 用 SQLite checkpointer，**逐节点持久化**；`thread_id = run_id`；崩溃后从最近 checkpoint 恢复。
- 副作用（写文件/跑命令）带**幂等键**（`tool_call_id`），重放不重复生效。
- **HITL**：`safety != read` 的工具在节点内 `interrupt()` 暂停并落盘；用户确认后 `Command(resume={"approved": bool})` 恢复；运行时可 `astream` 观测。

### 6.4 状态机（映射为图的节点/边）
```
IDLE → PLANNING ⇄ RE_PLANNING
        ├→ (read 工具)        → EXECUTING → OBSERVING ┐
        ├→ (write/exec 工具)  → AWAITING_CONFIRM ─────┤  ← interrupt() 点
        │                          ├ approved → EXECUTING
        │                          └ rejected → OBSERVING
        └──────────────── OBSERVING ◀──────────────────┘  (边回 planner/agent)
                         └→ REVIEWING → COMPLETED / FAILED / CANCELLED
```

### 6.5 工具（LangChain Tool）
- 用 LangChain `@tool`/`StructuredTool` 定义，附元数据：`safety`(`read/write/exec`)、风险级别。
- **执行归口**：工具函数体**不直接碰文件/命令**，而调用 `Workspace`/`Executor` 端口。
- 内置工具：

| 类别 | 工具 | safety |
|------|------|--------|
| 只读 | `list_dir` `read_file` `grep` `glob` | read |
| 写 | `write_file` `edit_file` `delete_file` `apply_patch` | write |
| 执行 | `run_command` `run_tests` `build` | exec |
| 检索 | `code_search`（本地索引，可选） | read |

### 6.6 上下文与记忆
- 分层记忆：会话 `messages`（短时）+ LangGraph `Store`（长期）+ 工作区索引（可选）。
- 预算治理：动态分配、自动摘要（`trim_messages`/摘要链）、长输出外置 + lazy 读取。
- 去重：`tool_call_id` 唯一。

### 6.7 框架隔离
- 双向映射：domain `Message/ToolCall` ↔ LangChain `BaseMessage`；LangGraph 事件 ↔ 应用事件（供 GUI）。
- 依赖注入：GUI/Application 依赖 `domain/ports/agent.py::AgentOrchestrator`；实现为 `infrastructure/agent`。
- LLM Provider（`ChatModelFactory`）与 Tool 属**基础设施内部接缝**（`infrastructure/providers`、`infrastructure/agent`），不作为领域端口暴露。
- **Presentation / Domain / Application 均不 import `langchain/langgraph`**。

### 6.8 依赖与版本治理
- 精确 pin（uv lock）；升级需过测试门禁。
- 调用收敛到 `infrastructure/agent/`，框架变更单点适配。
- 可观测：LangChain `CallbackHandler` → 结构化日志/OTel。
- 测试：`FakeChatModel` + stub 工具，离线可跑。

---

## 7. 工作区与文件系统（本地直连）

### 7.1 实现
- **`LocalDirectWorkspace`（唯一实现）**：绑定用户本机一个**已有目录**，直接读写真实文件。
- 一个会话绑定一个目录；多个会话可指向相同或不同目录。

### 7.2 安全约束
1. **目录白名单**：`Settings.workspace_allowlist` 定义允许绑定的根集合；只能绑定其内路径。
2. **路径校验**：每次操作 `Path.resolve()` 后校验仍在 workspace 内，拒绝 `..`、绝对路径逃逸、软链逃逸。
3. **不跟随越界软链**；越权请求 → `PermissionDenied`。

### 7.3 写入安全与快照
- **写/改/删强制人工确认**；确认前不改盘。
- **操作前快照（默认开启）**：写入前备份受影响文件（影子目录 `~/.codepilot/backups/<session>/<ts>/` 或 git stash），支持**一键回滚**。
- 新建文件在拒绝时**不产生任何文件**。

### 7.4 文件树与监听
- 文件树由 `QFileSystemModel` 呈现，根限定为 workspace。
- 可选 watchdog 监听外部改动，提示"文件已被外部修改"，避免覆盖用户实时编辑。

---

## 8. 命令执行（本机）

- 以 workspace 为 `cwd`，`create_subprocess_exec(*argv)`，**无 shell**（防注入）。
- **硬超时**（默认 120s，可配）+ 输出上限（默认 1MB，超出截断标记）。
- **危险命令黑名单**：`rm -rf /`、`sudo`、`mkfs`、`dd`、`shutdown`、外呼下载等；命中拒绝或强制二次确认。
- **用户确认**：`exec` 前弹确认卡片（完整命令 + cwd）。
- **流式输出**：短命令一次性返回；长命令实时追加到终端视图。
- **回传模型**：超长输出截断（头尾保留 + "已截断 N 行"），完整日志落本地文件。

---

## 9. 数据设计

### 9.1 存储
| 存储 | 用途 |
|------|------|
| SQLite（`~/.codepilot/codepilot.db`，WAL） | 会话、消息、审批、LangGraph checkpoint |
| 本地文件系统 | `~/.codepilot/backups/`（快照）、`~/.codepilot/logs/` |

### 9.2 核心表
```sql
CREATE TABLE sessions (
    id             TEXT PRIMARY KEY,         -- UUID
    title          TEXT NOT NULL,
    workspace_path TEXT NOT NULL,            -- 本机绝对路径
    provider       TEXT NOT NULL,
    model          TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'active',
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,               -- system/user/assistant/tool
    content     TEXT,
    tool_calls  TEXT,                        -- JSON
    token_usage TEXT,                        -- JSON
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_messages_session ON messages(session_id, id);

CREATE TABLE approvals (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    run_id      TEXT NOT NULL,               -- = LangGraph thread_id
    tool        TEXT NOT NULL,
    payload     TEXT NOT NULL,               -- JSON
    preview     TEXT NOT NULL,               -- diff / 新内容
    risk        TEXT NOT NULL,               -- low/medium/high
    status      TEXT NOT NULL,               -- pending/approved/rejected/expired
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at TEXT
);
CREATE INDEX idx_approvals_pending ON approvals(session_id, status);
```
> 单用户单进程；SQLite WAL 满足并发读；LangGraph checkpoint 同库（或独立表/文件）。

---

## 10. GUI 设计（PySide6）

### 10.1 主窗口布局
```
┌───────────────────────────────────────────────────────────────┐
│ Menu/Toolbar: 新建会话 · 选择目录 · 模型设置 · 回滚             │
├──────────────┬────────────────────────────────────────────────┤
│ 会话列表     │  对话视图 (ChatView)                            │
│ +            │   · 用户/助手消息 (Markdown 渲染)                │
│ 文件树       │   · 工具步骤卡 (正在读/写/执行)                  │
│ (workspace)  │   · 确认卡片 (diff / 命令 + 确认/拒绝)           │
│              │   · 输入框 + 发送                                │
├──────────────┴────────────────────────────────────────────────┤
│ 终端/输出 (TerminalView): 命令流式日志                          │
└───────────────────────────────────────────────────────────────┘
│ 状态栏: 当前模型 · 工作目录 · 连接/运行状态                     │
```

### 10.2 事件模型（替代 WebSocket）
- Infrastructure/Application 通过 **应用事件总线**（`application/events.py`，asyncio 队列）发布领域事件：`token`、`agent_state`、`tool_call`、`confirm_required`、`command_output`、`tool_result`、`done`。
- `ui/bridge.py` 在 **Qt 主线程**把事件转为 **Qt Signal**（队列连接保证线程安全），ViewModel/Widget 订阅更新。
- 事件带 `seq`（单调递增）保证 UI 内有序应用；长流程断点恢复由 LangGraph checkpoint 负责，UI 侧无需复杂回放。

### 10.3 关键交互
- **选择目录**：新建会话时 `QFileDialog` 选择本机目录（限白名单根）。
- **流式渲染**：`token` 增量追加；`agent_state` 驱动多智能体视图；`tool_call` 步骤卡。
- **审批**：`confirm_required` → 确认卡片展示 diff/命令 + 风险等级 → 确认/拒绝 → `ConfirmService` 恢复 LangGraph。
- **终端**：`command_output` 追加，超长滚动窗口。
- **回滚**：菜单/按钮触发 `ConfirmService.rollback(session)`。
- **响应性**：所有网络/IO 在事件循环异步执行，**UI 线程只做渲染**。

### 10.4 可测试性
- ViewModel 与 Widget 解耦，ViewModel 可无 GUI 单测；GUI 交互用 `pytest-qt`。

---

## 11. 安全（本地桌面场景）

| 面向 | 措施 |
|------|------|
| 目录范围 | 白名单限制可绑定根；路径 resolve 后校验；拒越界/软链逃逸 |
| 文件写改 | 写/改/删强制确认；操作前快照可回滚 |
| 命令 | 参数化（无 shell）；黑名单；执行前确认；超时+输出上限 |
| 密钥 | `llm_api_key` 仅本地配置（SecretStr），不入库、不展示明文、日志脱敏 |
| 依赖 | 依赖锁定 + CI 扫描 |
| 审计（轻） | 工具调用与审批记录入库；操作日志本地留存 |

---

## 12. 可观测性

- **日志**：structlog → `~/.codepilot/logs/`（轮转）；字段含 `session_id`/`run_id`/`event_id`。
- **追踪（可选）**：OTel 贯穿 Application→Agent→Provider→Executor。
- **诊断**：命令完整输出落盘；崩溃可生成诊断包。

---

## 13. 测试

| 层 | 范围 | 工具 |
|----|------|------|
| 单元 | 领域逻辑、路径校验、ContextManager、工具参数 | pytest（核心域 ≥90%） |
| 集成 | Repository↔SQLite、Workspace 文件操作、Executor 子进程、Provider 适配 | pytest |
| GUI | ViewModel 逻辑、关键交互 | pytest-qt |
| 端到端 | 建会话→选目录→发消息→确认→改文件→跑命令（无头/离屏） | pytest + FakeChatModel |
| 静态 | 类型与风格 | mypy / ruff |

- CI 中 LLM 一律用 LangChain `FakeChatModel`，**离线可跑**、确定性。

---

## 14. 打包与分发

- **PyInstaller**（one-dir 优先）：打包 `src/codepilot` + PySide6 插件 + 依赖，内置 Python 运行时；无需用户装 Python。
- 产物：Windows `.exe`、macOS `.app`（可选签名/公证）、Linux AppImage。
- **CI**：GitHub Actions matrix（各平台构建 + 冒烟测试）。
- **首次运行**：创建 `~/.codepilot/`（db/logs/backups）、执行 Alembic 迁移、引导配置模型 API Key 与 workspace 白名单。
- **自动更新（可选）**：启动检查版本 → 下载 → 替换重启。

---

## 15. 里程碑

| 阶段 | 交付 | 目标态子集 |
|------|------|-----------|
| P1 基础闭环 | 桌面壳 + SQLite + LangGraph 单图 + 工具/模型；目录选择；只读+写改+确认；命令执行 | Presentation / Agent(单图) / Executor / Workspace |
| P2 体验完善 | Provider 配置切换、流式命令日志、文件树、Diff 视图、终端视图 | Provider / GUI 事件流 |
| P3 质量闭环 | Debugger/Reviewer 子图、Reviewer 自检、Evals | 多智能体 |
| P4 恢复与安全 | 快照回滚、黑名单完善、checkpoint 恢复、外部改动监听 | Snapshot / Durable |
| P5 分发与智能（可选） | 打包安装包/自动更新、本地索引/RAG | Packaging / Code Intelligence |

---

## 16. 关键设计决策（ADR）

| ID | 决策 | 备选 | 理由 |
|----|------|------|------|
| ADR-1 | 分层 + 端口适配 | 脚本式 | 可测试、可替换、契约稳定 |
| ADR-2 | **单进程桌面应用（无 HTTP/WS/服务端）** | 浏览器+本地服务 | 原生桌面形态；复杂度更低 |
| ADR-3 | **workspace 本地直连**（唯一实现） | 沙箱物化 | 对标 Claude Code：直接操作本机真实目录 |
| ADR-4 | 写/改/删/执行强制人工确认 | 全自动 | 本机无沙箱，安全底线 |
| ADR-5 | 命令参数化执行（无 shell） | shell=True | 防注入 |
| ADR-6 | **GUI 事件用 Qt Signal（qasync 统一事件循环）** | 独立 WS/IPC | 单进程内原生桥接，UI 不阻塞 |
| ADR-7 | 写入前快照可回滚 | 无备份 | 直连模式的核心安全网 |
| ADR-8 | **Agent 用 LangChain（基础）+ LangGraph（编排）**，端口隔离 | 自研编排 | 复用状态图/checkpoint/HITL/流式；框架风险由端口+锁版本控制 |
| ADR-9 | LangGraph Checkpointer 持久化（SQLite） | 纯内存 | 崩溃可恢复、审批可等待 |
| ADR-10 | **SQLite（嵌入式）** | PostgreSQL | 桌面零配置、随 App 分发 |

---

## 17. 主要风险
| 风险 | 缓解 |
|------|------|
| 本机无沙箱，误改/误删用户代码 | 强制确认 + 写入前快照 + 命令黑名单 + 路径白名单 |
| UI 阻塞 | 全异步 + qasync 单循环 + UI 线程只渲染 |
| LLM 输出不稳定 | Reviewer 自检 + Evals + 重试/降级 |
| 框架 churn（LangChain/LangGraph） | 精确锁版本 + 升级过门禁 + 调用收敛单点 |
| 长命令卡死 | 硬超时 + 进程组 kill + 输出上限 |
| 跨平台打包差异（Qt 插件/路径） | CI 各平台构建 + 冒烟测试；统一 `paths.py` |
| SQLite 并发写限制 | 单用户单进程；WAL；写操作串行化 |
