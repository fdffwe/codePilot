# codePilot 开发规范

> 版本：v0.1
> 日期：2026-10-11
> 关联：`docs/TECHNICAL_DESIGN.md`、`docs/ENGINEERING_PLAN.md`
> 适用：单人开发，但按"未来可加人/可加严"的标准书写。

---

## 1. 总则

1. **架构约束优先于风格偏好**：分层与依赖方向是硬规则（见 §2），其余是可讨论的风格。
2. **显式优于隐式**：类型、依赖、错误、配置都写清楚。
3. **让测试容易**：任何不好测的写法，通常也意味着设计有问题。
4. **小步提交**：一次提交一件事，可独立理解与回滚。
5. **规范可以演进**：本条规范本身随项目成长调整（走 ADR/文档更新）。

---

## 2. 目录与分层规范（硬规则）

```
src/codepilot/
  core/            # 配置/日志/错误/路径/DI（横切）
  domain/          # ★ 纯逻辑，无框架 import
    entities.py · enums.py · ports/
  application/     # 用例编排，只依赖 domain
  infrastructure/  # 框架与 IO 实现
    agent/ db/ providers/ workspace/ executor/
  ui/              # ★ Presentation (PySide6)
```

**依赖方向（单向，禁止反向/环）**
```
ui ─▶ application ─▶ domain ◀─ infrastructure(实现 ports)
                        ▲
              infrastructure 实现 domain 定义的端口
```

**硬性禁止**
- `domain/` **不得** import：`langchain`、`langgraph`、`sqlalchemy`、`PySide6`、`httpx`、任何具体 IO。
- `application/` **不得** import 框架/具体的 infrastructure 实现（只能依赖 `domain/ports` 抽象）。
- `ui/` **不得**直接 import `infrastructure/`（只通过 `application`）。
- 业务逻辑**不得**写在 GUI Widget 里（见 §15）。
- 跨层调用必须经过明确的端口/服务，不得"穿透式"访问。

> 建议用 `import-linter`（未来门禁）固化以上规则；当前靠自律 + 自查清单。

---

## 3. 命名规范（Python）

| 对象 | 规范 | 示例 |
|------|------|------|
| 模块/包 | 小写下划线 | `local_executor.py` |
| 类 | 大驼峰 | `LocalDirectWorkspace` |
| 函数/变量 | 小写下划线 | `resolve_within_workspace()` |
| 常量 | 全大写下划线 | `DEFAULT_TIMEOUT_S` |
| 私有 | 前缀下划线 | `_internal_cache` |
| 类型别名 | 大驼峰 | `SessionId = str` |
| 枚举 | 大驼峰类 + 大写成员 | `class ToolSafety: READ=...` |
| 端口（接口） | 名词/`Protocol` | `AgentOrchestrator`, `WorkspaceProvider` |
| 适配器实现 | 前缀技术名 | `OpenAIProvider`, `LocalExecutor` |

- **布尔**用 `is_/has_/should_` 前缀：`is_truncated`。
- **异步**函数正常命名（不加后缀）；不要 `async_get` 这类冗余前缀。
- **单位**入名：`timeout_s`、`max_bytes`、`poll_interval_ms`。

---

## 4. 类型与文档

- **强制类型注解**：函数签名（参数 + 返回）、公开属性、端口定义。局部变量可推断则省略。
- **不使用 `Any`** 除非万不得已；必要时注释原因。
- `mypy` 从宽松起步，**核心域（domain/application）尽量严**。
- **Docstring**：公开 API 用简洁 docstring（一行摘要 + 必要时参数/返回/异常）；内部函数若逻辑自明则不必写。
- **注释**只解释"为什么"，不解释"是什么"；不复述代码。

---

## 5. 代码风格

- 格式化 **black**（默认 88 列）；lint **ruff**。
- import 顺序：标准库 → 第三方 → 本项目（ruff-isort 规则）。
- 命名/结构可读优先；**避免过早抽象**（三行重复 > 生造抽象）。
- **不写无用代码**：不预留没人用的参数、不搞投机性扩展点。
- 删除死代码，不用"注释掉保留"。

---

## 6. 异步与并发规范

- **所有 IO 必须 `async`**：网络、文件、DB、子进程。
- **禁止在事件循环里做阻塞调用**（`time.sleep`、同步 `requests`、阻塞 `subprocess.run`、CPU 重活）。
  - 阻塞不可避免时用 `run_in_executor`/`QThreadPool` 卸载。
- **子进程一律**：`asyncio.create_subprocess_exec(*argv, cwd=..., ...)`
  - **禁止 `shell=True`**（安全 + 注入）。
  - 必须设**超时**与**输出上限**；超时后 kill 进程组。
- **DB 会话**用 async session；不要跨协程共享同一 session。
- 后台任务用 `asyncio.Task` 并**持有引用**（防被 GC）；退出时正确取消。

---

## 7. 错误处理规范

- 用统一异常层级（`core/errors.py`）：
  ```python
  DomainError → NotFoundError / ValidationError / PermissionDenied / ProviderError / ExecError
  ```
- **禁止裸 `except:`** 与 `except Exception: pass`。捕获要具体，且**要么处理要么明确转译**。
- **边界转译**：基础设施异常（如 httpx/OSError）在边界转成 `DomainError`，不泄漏到上层。
- **用户可见消息**友好、不含堆栈；**细节只进日志**。
- 失败要**可预期**：同一输入，失败行为一致。

---

## 8. 日志规范

- 用 `structlog`；**结构化字段**，不要拼字符串。
- 关键上下文统一带上：`session_id` / `run_id` / `event_id`（有则带）。
- 级别：`debug` 细节、`info` 里程碑（会话创建、run 起止、工具调用）、`warning` 可恢复异常、`error` 失败。
- **禁止记录**：API Key、令牌、用户敏感内容明文（日志脱敏）。
- 日志落 `~/.codepilot/logs/`（轮转）；命令完整输出单独落盘便于排查。

---

## 9. 配置与密钥

- 用 `pydantic-settings`；来源优先级：环境变量 > 用户配置文件（`~/.codepilot/config.toml`）> 默认值。
- 密钥字段用 `SecretStr`；**不得**硬编码、不得入库、不得出现在日志/UI 明文。
- 新增配置项必须：给默认值 + 更新文档 + 加校验。
- 路径类配置（如 `workspace_allowlist`）需规范化处理（见 §16）。

---

## 10. LangChain / LangGraph 使用规范（框架治理）

> 目标：**用好框架，同时把框架风险关在盒子里。**

**位置与边界**
- 框架代码**只能**出现在 `infrastructure/agent/`。
- `domain`/`application`/`ui` **禁止** import 框架；只用 `domain/ports/agent.py::AgentOrchestrator`。
- 与领域对象之间**必须**经映射层转换（domain `Message/ToolCall` ↔ LangChain `BaseMessage`）；不把框架类型当"通用货币"到处传。

**版本与依赖**
- 精确 pin（`uv` 锁）；升级框架版本必须：跑测试 + Evals，单独提交，便于回滚。
- 不直接依赖框架的"内部/私有" API。

**图（LangGraph）约定**
- State 用显式 `TypedDict`（如 `AgentState`）；字段命名清晰；合并逻辑用 reducer。
- 节点命名与职责单一（`plan`/`act`/`tool`/`review`…）；条件边逻辑集中可读。
- **HITL**：`safety != read` 的工具在**执行节点前** `interrupt()`；恢复用 `Command(resume=...)`；审批记录落 `approvals`。
- **持久化**：用 SQLite checkpointer；`thread_id = run_id`；副作用带幂等键。
- **流式**：由 `astream_events` 统一转成应用事件（`events.py`），**不把框架事件对象泄漏**到上层。

**工具（LangChain）约定**
- 用 `@tool`/`StructuredTool`；**必须**带 `safety` 元数据（`read/write/exec`）。
- 工具函数体**不得**直接操作文件/命令；**必须**经 `Workspace`/`Executor` 端口。
- 工具参数用 Pydantic/显式 schema 校验；文档字符串写清用途与参数。

**测试**
- 用 LangChain `FakeChatModel` + stub 工具；测试**不触网**、确定性。

---

## 11. 测试规范

- 测试目录镜像源码结构：`tests/{unit,integration,gui}/{...}`。
- 命名：`test_<行为>_<条件>_<期望>`。
- **单测**：纯逻辑、快速、无 IO（用 Fake/内存实现）。
- **集成**：DB / 文件系统 / 子进程（可分文件系统沙箱临时目录）。
- **GUI**：用 `pytest-qt` 测 ViewModel 与关键交互。
- **LLM 一律 Fake**：CI 离线、确定性。
- 每个 bug 修复**先写复现测试**（防回归）。
- 核心域（`domain`/`application`）优先覆盖；轻量门禁阶段不设硬阈值，但**新增逻辑应有测试**。

---

## 12. Git 规范（Trunk-based + Conventional Commits）

**分支**
- `main` 始终可运行；**短命分支**：`feat/<slug>`、`fix/<slug>`、`chore/<slug>`、`docs/<slug>`、`refactor/<slug>`。
- 合并前 `rebase main`，保持线性；合并用 **squash**。

**提交信息**（Conventional Commits）
```
<type>(<scope>): <subject>

<body 可选>

<footer 可选>
```
- `type`：`feat` `fix` `docs` `refactor` `test` `chore` `perf` `build` `ci`。
- `scope` 建议用模块名：`agent` `workspace` `executor` `ui` `db` `config`。
- `subject`：祈使句、小写、不加句号、≤ 72 字符。
- 示例：
  - `feat(workspace): bind session to local directory with allowlist check`
  - `fix(executor): kill process group on command timeout`
  - `refactor(agent): move langgraph nodes behind orchestrator port`

**提交纪律**
- **原子**：一次提交一件事；不混入无关改动。
- **不要提交**：密钥、`~/.codepilot` 数据、构建产物、IDE 本地配置（靠 `.gitignore`）。
- 大改动拆成可独立回滚的多提交。

---

## 13. 依赖管理

- 用 `uv` 管理；锁文件入库。
- 新增依赖需：确实必要 + 维护活跃 + 许可兼容；**优先标准库**。
- 框架类大依赖（LangChain/LangGraph）变更要**单独提交**并记录理由。
- 定期（未来门禁）跑依赖安全扫描。

---

## 14. 数据库与迁移规范

- ORM：SQLAlchemy 2.0 声明式；模型集中在 `infrastructure/db/orm/`。
- **所有 schema 变更走 Alembic 迁移**，禁止手改库。
- 迁移**单向可升级**；涉及破坏性变更考虑 expand/contract。
- 表/列命名：`snake_case`；主键、时间字段（`created_at`/`updated_at`）统一。
- 查询走 Repository；**不在 UI/应用层写裸 SQL**。

---

## 15. GUI（PySide6）规范

- **View 与 ViewModel 分离**：Widget 只做渲染与用户输入；状态与逻辑放 ViewModel。
- **业务逻辑不得写进 Widget**；Widget 通过 ViewModel 调用 `application` 服务。
- **绝不在 UI 线程阻塞**：耗时工作交给异步任务；结果经 **Qt Signal**（队列连接）回主线程更新。
- 信号命名：`<名词><过去式>`，如 `messageReceived`、`commandOutputChunk`、`approvalRequested`。
- 后台线程 → UI 只用 Signal，**不跨线程碰 Widget**。
- 资源生命周期：`QObject` 父子关系管理；协程任务持有引用并在关闭时取消。
- 长列表/长文本用虚拟化或分块，避免卡顿（如终端输出）。

---

## 16. 安全编码规范（硬规则）

- **路径操作必须**经 `core/paths.py`：`resolve()` 后校验在 workspace 内；拒绝 `..`、绝对路径逃逸、软链逃逸；**不跟随越界软链**。
- **写/改/删/执行必须人工确认**；确认前不动盘。
- **命令**：无 `shell=True`；超时 + 输出上限；黑名单命令拒绝或二次确认。
- **写入前快照**（默认开启），保证可回滚。
- **密钥**：`SecretStr`，不入库、不进日志、不显示明文。
- 出现"绕过安全闸门"的临时代码，**必须在提交前移除**。

---

## 17. 文件与路径规范

- 一律用 `pathlib.Path`，不用字符串拼路径。
- 跨平台：统一走 `core/paths.py` 规范化（大小写、分隔符、符号链接、`~` 展开）。
- 用户数据统一放 `~/.codepilot/`（`config.toml` / `codepilot.db` / `logs/` / `backups/`）。

---

## 18. 文档规范

- `README.md`：是什么、怎么装、怎么跑、截图。
- `docs/`：需求、设计、工程规划、开发规范、ADR。
- **ADR**：重大决策（架构/依赖/取舍）追加到 TDD §ADR 表，含"决策/备选/理由"。
- 契约变更（数据模型/事件/端口）**必须**同步更新文档。
- 面向用户的变更记入 `CHANGELOG`（P5 起）。

---

## 19. 门禁现状与升级路径

| 项 | 现状（轻量） | 升级（未来） |
|----|--------------|--------------|
| 格式/lint | 本地 ruff+black | pre-commit 强制 + CI |
| 类型 | mypy 宽松（核心域严格） | mypy strict |
| 测试 | 本地 pytest，新增逻辑需测 | CI 跑 + 覆盖率阈值 |
| 依赖安全 | 手动 | pip-audit / Trivy |
| Evals | 无 | P3 起纳入门禁 |

---

## 20. 提交前自查清单

- [ ] 遵循分层与依赖方向，无越层/反向 import
- [ ] 无阻塞事件循环的调用；子进程无 `shell=True`
- [ ] 路径经 `paths.py` 校验；无绕过确认/快照
- [ ] 无密钥/敏感信息入库或进日志
- [ ] 框架代码只在 `infrastructure/agent/`，领域/UI 未 import 框架
- [ ] 逻辑未写进 Widget 层
- [ ] 有对应测试；`ruff`/`black`/`mypy`/`pytest` 通过
- [ ] 提交信息符合 Conventional Commits、原子、无无关改动
