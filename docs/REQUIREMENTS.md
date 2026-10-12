# codePilot 需求文档

> 版本：v0.3
> 日期：2026-10-11
> 定位：一个轻量级的「Claude Code 平替」——**本地原生桌面应用**，用自然语言驱动 AI 完成编码、调试与项目构建，直接操作本机真实代码。
> 技术基调：Python + **PySide6（原生桌面 GUI）** / **SQLite（嵌入式持久化）** / deepseek-chat（默认模型） / Agent 用 LangChain + LangGraph

---

## 1. 项目背景与目标

### 1.1 背景
Claude Code 是终端里的 AI 编码助手，能力强但门槛偏高（终端操作、配置复杂）。我们希望做一个**低配版**：保留核心的「对话 → 操作代码」闭环，降低使用门槛，用**原生桌面 GUI** 交互，直接读写用户本机的真实代码目录，并支持可切换的多种大模型后端。

### 1.2 目标
- 用户在**桌面应用**里用自然语言描述需求，codePilot 能**读代码、写代码、改代码**（作用于本机真实目录）。
- 能**执行命令**（跑测试、构建）并根据结果自我修正，实现基本 **Debug** 能力。
- 能根据描述**从零生成一个小项目的骨架**。
- 所有**写/改/执行操作需人工确认**，安全可控。
- 底层模型**可配置**，v1 默认对接 **deepseek-chat**（走 OpenAI 兼容接口），并保留 Claude / 本地模型（Ollama/vLLM）的适配位。
- **纯本地、单用户**：作为一个桌面应用安装运行，不需要浏览器、不需要服务器。

### 1.3 非目标
- 浏览器 / Web 形态（无前端 SPA、无 HTTP 服务）。
- 多用户 / 账号体系 / 权限管理。
- 云端部署、多租户、计费、容器沙箱。
- 复杂 IDE 级的代码补全、悬浮提示。

---

## 2. 用户与场景

### 2.1 目标用户
- 想体验 AI 编码但不想折腾终端配置的开发者。
- 需要在已有小项目里快速改代码、修 bug 的人。
- 想用本地/自建模型替代云端 API 的人。

### 2.2 核心用户故事
| 编号 | 故事 | 验收要点 |
|------|------|----------|
| US-1 | 我输入"帮我看看 `utils.py` 里为什么报错"，它读取文件并给出分析 | 能定位文件、读取内容、给出原因 |
| US-2 | 我描述"加一个 `/health` 接口"，它修改 `main.py` 并等我确认 | 生成 diff、确认后落盘 |
| US-3 | 我让它"跑一下测试并修复失败用例" | 能执行 `pytest`、读输出、改代码、重跑 |
| US-4 | 我描述"建一个 Flask TODO 应用"，它生成完整骨架 | 生成多个文件、目录结构合理 |
| US-5 | 我切换模型后端（如从 DeepSeek 换到 Claude/本地模型） | 不改业务代码，仅改配置即可切换 |

---

## 3. 功能需求

### 3.1 对话交互（FR-CHAT）
- FR-CHAT-1：**桌面 GUI** 提供对话输入框，支持多轮对话，保留上下文。
- FR-CHAT-2：AI 回复**流式输出**（边生成边显示），**UI 不阻塞**。
- FR-CHAT-3：展示 agent 的**思考/工具调用过程**（如"正在读取 a.py""正在执行命令"）。
- FR-CHAT-4：会话可新建、切换、查看历史，**历史持久化到本地 SQLite**。

### 3.2 文件操作（FR-FILE）
- FR-FILE-1：**读取**文件 / 列出目录（无需确认）。
- FR-FILE-2：**新建**文件、**修改**已有文件、**删除**文件。
- FR-FILE-3：所有写/改/删操作，界面弹出**确认卡片**，展示将执行的内容（新建）或 **diff**（修改），用户点「确认/拒绝」后才落盘。
- FR-FILE-4：操作限定在**该会话绑定的 workspace 目录**内，禁止越界访问（路径穿越防护）。
- FR-FILE-5：**workspace 为本地直连模式**——会话绑定用户指定的**本机已有目录**（如 `~/projects/myapp`），agent 直接读写该目录的真实文件；一个会话一个 workspace，多个会话可指向相同或不同目录。
- FR-FILE-6：Web 界面提供**目录选择器**，用户显式指定/确认要操作的本地目录；未显式绑定的目录不得访问。
- FR-FILE-7：写入前自动备份或可撤销（v1 至少支持"拒绝=不写"，撤销列为可选）。

### 3.3 命令执行（FR-EXEC）
- FR-EXEC-1：agent 可执行 shell 命令（如 `pytest`、`npm run build`、`python xx.py`）。
- FR-EXEC-2：命令在**该会话的 workspace 目录**下执行，带**超时**保护，输出（stdout/stderr）回传给模型。
- FR-EXEC-3：危险命令（`rm -rf`、`sudo`、网络下载等）需**额外确认**或列入黑名单。
- FR-EXEC-4：命令输出**按需流式**展示——短命令一次性返回，长命令（如构建、测试）实时推送日志到前端。

### 3.4 Debug 能力（FR-DEBUG）
- FR-DEBUG-1：用户粘贴报错/日志，agent 能定位相关代码并给出修复方案。
- FR-DEBUG-2：agent 可"执行 → 读输出 → 改代码 → 重跑"形成闭环，直到通过或达到重试上限。
- FR-DEBUG-3：最大迭代次数可配置（防止死循环），默认 `5` 次。

### 3.5 项目脚手架（FR-SCAFFOLD）
- FR-SCAFFOLD-1：用户描述目标项目，agent 规划目录结构与文件清单。
- FR-SCAFFOLD-2：生成多个文件，全部走 FR-FILE-3 的确认流程（可批量确认）。
- FR-SCAFFOLD-3：可选：生成后自动执行安装/启动命令验证（受 FR-EXEC 约束）。

### 3.6 模型配置（FR-MODEL）
- FR-MODEL-1：抽象统一的 **Provider 接口**，屏蔽不同厂商差异。
- FR-MODEL-2：**v1 默认对接 `deepseek-chat`**（OpenAI 兼容接口）；架构上预留 Anthropic Claude 与本地模型（Ollama/vLLM）的适配位。
- FR-MODEL-3：配置项包括：`base_url`、`api_key`、`model`、`max_tokens`、`temperature`，通过配置文件 / 环境变量设置。
- FR-MODEL-4：支持**工具调用（function calling / tool use）**；对不支持 tool use 的模型提供降级方案（如基于 JSON 约定的文本协议解析）。
- FR-MODEL-5：界面上可查看当前使用的模型，v1 允许在设置页切换。

---

## 4. 系统架构

### 4.1 总体架构
```
┌───────────────────────────────────────────┐
│        桌面 GUI (PySide6 原生窗口)          │
│  对话 / 确认卡片 / 文件树 / 终端 / 设置      │
└───────────────┬───────────────────────────┘
                │ 直接函数调用 + Qt Signal(事件)
┌───────────────▼───────────────────────────┐
│        codePilot 单进程 (统一事件循环)      │
│  ┌─────────────┐  ┌──────────────────────┐ │
│  │ Agent 引擎   │  │ 会话管理 / 确认服务   │ │
│  │ LangGraph   │  └──────────────────────┘ │
│  │ +LangChain  │                            │
│  └──────┬──────┘                            │
│         │ Tool 调用                         │
│  ┌──────▼───────────────────────────────┐  │
│  │ Tool 层: read / write / edit / exec   │  │
│  └──────┬───────────────────────────────┘  │
│         │                                   │
│  ┌──────▼───────────┐  ┌────────────────┐  │
│  │ Provider 抽象层   │  │ 本地工作区(直连) │  │
│  │ Claude/OpenAI/... │  │ 白名单/路径校验  │  │
│  └──────────────────┘  └────────────────┘  │
└───────────────────────────────────────────┘
        │直接读写              │执行/持久化
   ┌────▼─────┐          ┌─────▼──────┐
   │本机文件系统│          │本机子进程   │
   │(用户目录) │          │SQLite(codepilot.db)│
   └──────────┘          └────────────┘
```

### 4.2 模块划分
| 模块 | 职责 |
|------|------|
| 桌面 GUI (PySide6) | 对话视图、流式渲染、确认卡片、文件树、目录选择、终端输出、设置页 |
| 应用层 (Application) | 用例编排：会话/对话/确认，供 GUI 直接调用 |
| Agent 引擎 (LangChain+LangGraph) | 编排「模型 → 工具调用 → 观察结果 → 再调用」；多智能体子图 |
| Tool 层 | 具体工具实现（读写文件、执行命令），统一 schema |
| Provider 层 | 多模型后端适配，统一 tool-use 协议 |
| 本地工作区 | 绑定本机目录、路径白名单校验、写入前快照 |
| 持久化层 (SQLite) | 会话/消息/审批/checkpoint |
| 配置层 | 读取配置文件/环境变量，管理模型与运行参数 |

### 4.3 Agent 循环（核心流程）
```
用户输入
  → 组装上下文 (system prompt + 历史 + 工作目录信息)
  → 调用 Provider (带 tools schema)
  → 模型返回: 文本 / 工具调用
       ├─ 文本 → 流式推给前端
       └─ 工具调用 →
             ├─ read 类          → 直接执行，结果回传模型
             └─ write/exec 类    → 暂停，推确认卡片给前端
                                    → 用户确认 → 执行 → 结果回传模型
                                    → 用户拒绝 → 回传"已拒绝"给模型
  → 循环，直到无工具调用且模型给出最终答复
```

---

## 5. 接口设计（应用内服务 + 事件）

> 桌面应用无 HTTP/WebSocket。GUI 通过**直接调用应用层服务**触发用例，通过**事件总线 → Qt Signal** 接收后台事件。

### 5.1 应用层服务（GUI 直接调用，async）
| 服务 | 方法（示意） | 说明 |
|------|-------------|------|
| `SessionService` | `create(workspace_path)` / `list()` / `get(id)` / `rename()` / `archive()` | 会话管理 |
| `ChatService` | `send(session_id, text)` → 启动 Agent run | 发送消息 |
| `ConfirmService` | `approve(approval_id)` / `reject(approval_id)` | 确认/拒绝待执行操作 |
| `WorkspaceService` | `tree(session_id)` / `rollback(session_id)` | 文件树 / 回滚 |
| `ConfigService` | `get()` / `update(...)` | 模型与参数配置 |

### 5.2 应用事件（推送给 GUI，经事件总线转 Qt Signal）
| 事件 | 载荷 | 说明 |
|------|------|------|
| `token` | `data` | 流式文本增量 |
| `agent_state` | `agent`, `state` | 多智能体/状态机进度 |
| `tool_call` | `tool`, `args` | 工具调用开始 |
| `confirm_required` | `approval_id`, `tool`, `risk`, `preview` | 待确认（diff/命令） |
| `command_output` | `stream`, `chunk`, `truncated` | 命令实时输出 |
| `tool_result` | `approval_id`, `ok`, `output` | 工具执行结果 |
| `done` | `finish_reason` | 本轮结束 |

> 事件带单调递增 `seq` 保证 UI 有序渲染；长流程恢复由 LangGraph checkpoint 负责。

---

## 6. 数据结构（草案）

```python
class Message(BaseModel):
    role: Literal["user", "assistant", "tool"]
    content: str
    tool_calls: list[ToolCall] | None = None

class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict

class PendingAction(BaseModel):     # 待确认的写操作
    id: str
    tool: str
    preview: str                    # diff 或新文件内容
    status: Literal["pending","approved","rejected"]

class Session(BaseModel):
    id: str
    title: str
    workspace_path: str             # 会话绑定的本机目录（绝对路径）
    model: str
    created_at: datetime
```

### 6.1 数据库表（SQLite）
```sql
-- 会话表
CREATE TABLE sessions (
    id             TEXT PRIMARY KEY,     -- UUID
    title          TEXT NOT NULL,
    workspace_path TEXT NOT NULL,        -- 会话绑定的本机目录（绝对路径）
    model          TEXT NOT NULL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 消息表（含工具调用记录）
CREATE TABLE messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,           -- user / assistant / tool
    content     TEXT,
    tool_calls  TEXT,                    -- JSON：工具调用与结果
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_messages_session ON messages(session_id, id);
```

> ORM 用 SQLAlchemy 2.0 (async/aiosqlite) + Alembic 迁移；DB 文件 `~/.codepilot/codepilot.db`。

---

## 7. 技术选型

| 层 | 选型 | 说明 |
|----|------|------|
| 语言 | Python 3.11+ | 异步、类型、AI 生态 |
| GUI | **PySide6（Qt）+ qasync** | 原生桌面、跨平台；qasync 统一 asyncio 与 Qt 事件循环 |
| Agent | **LangChain（基础）+ LangGraph（编排）** | 状态图、多智能体、checkpoint、HITL、流式 |
| 持久化 | **SQLite + SQLAlchemy 2.0 + Alembic** | 嵌入式、零配置、随 App 分发 |
| 模型 | **openai SDK（默认 deepseek-chat）** + anthropic SDK（预留） | Provider 层封装统一协议 |
| 命令执行 | 标准库 `asyncio.create_subprocess_exec` | 本机执行，无 shell |
| 配置 | pydantic-settings + 本地配置文件 | 文件/环境变量优先 |
| 测试 | pytest / pytest-asyncio / pytest-qt | 单测/集成/GUI |
| 打包 | **PyInstaller**（或 Nuitka） | 生成 .exe/.app/AppImage，内置运行时 |

---

## 8. 安全要求

- SR-1：所有文件操作限定在 workspace 内，做**路径规范化校验**，防 `../` 穿越与软链接逃逸。
- SR-2：写/改/删、危险命令必须**人工确认**。
- SR-3：命令执行有**超时**和输出大小上限。
- SR-4：API key 只存后端，前端不暴露。
- SR-5：命令黑名单（如 `rm -rf /`、`sudo`、`mkfs` 等）默认拦截。
- SR-6：workspace 为**本机目录直连**——由用户在界面（目录选择器）显式指定目录，并在配置中维护**允许的根范围（allowlist）**；只允许在该范围内绑定，越界路径一律拒绝。每个会话绑定一个目录，会话间默认相互隔离。

---

## 9. 里程碑规划

| 阶段 | 内容 | 交付物 |
|------|------|--------|
| M1 | 桌面壳(PySide6)+SQLite 建模 + Provider 层 + 对话闭环（只读工具） | 能对话、能读本机文件、历史入库 |
| M2 | 写/改工具 + 确认卡片 + 事件流式（含目录选择/文件树/Diff） | 能确认后改本地文件 |
| M3 | 命令执行 + Debug 闭环（含按需流式日志/终端视图） | 能跑测试并自我修正 |
| M4 | 项目脚手架 + GUI 完善（会话管理/设置页） | 能生成小项目 |
| M5 | 打磨：写入前快照/回滚、打包分发（安装包） | v1.0 |

---

## 10. 已确认决策

1. 交互形态：**原生桌面 GUI（PySide6/Qt）**，非浏览器。
2. 持久化：**嵌入式 SQLite**（随 App 分发）。
3. 默认模型：**deepseek-chat**（OpenAI 兼容接口）；预留多后端适配位。
4. 工作区：**本地直连**——会话绑定用户本机已有目录，直接读写真实文件。
5. 命令输出：**按需流式**（长命令实时推送日志到终端视图）。
6. **仅本地运行**：单用户、单机桌面应用、无云端/多租户/浏览器形态。
7. Agent 实现：**LangChain（基础）+ LangGraph（编排）**。

### 遗留待定（进入设计阶段再定）
- 命令输出的实时日志与最终回传模型的内容是否需要区分（避免刷爆上下文）？（设计文档已默认：完整日志落盘、回传模型时截断。）
