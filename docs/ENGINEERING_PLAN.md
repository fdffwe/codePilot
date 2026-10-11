# codePilot 工程规划

> 版本：v0.1
> 日期：2026-10-11
> 关联：`docs/REQUIREMENTS.md`、`docs/TECHNICAL_DESIGN.md`、`docs/DEVELOPMENT_GUIDELINES.md`
> 前提：**单人开发**、**Trunk-based + Conventional Commits**、**轻量门禁（后续可加严）**、本地原生桌面应用。

---

## 1. 规划原则

1. **纵向切片优先**：每个阶段交付一个**可运行、可演示的闭环**，而不是"横向铺完所有层、最后一刻才通"。
2. **先打通再打磨**：先让"对话→读文件→改文件→跑命令"端到端能跑，再补多智能体、快照、打包。
3. **架构不退让，范围可裁剪**：分层/端口/LangGraph 编排从第一天就位（对齐目标态）；但功能范围可按阶段收放。
4. **单人节奏**：以"每次提交独立可回滚"为单位推进；避免大爆炸式重构。
5. **先验证高风险点**：把技术不确定的先做 Spike（§5），避免到后期才发现跑不通。

---

## 2. 交付路线（阶段总览）

对齐 `TECHNICAL_DESIGN.md` §15 的里程碑：

| 阶段 | 主题 | 核心产出 |
|------|------|----------|
| **P0** | 工程底座 | 仓库骨架 + 工具链 + 可打包的"空窗口" |
| **P1** | 基础闭环 | 目录绑定 → 对话 → 读文件 → 改文件(确认) → 跑命令 |
| **P2** | 体验完善 | 流式、Diff 视图、文件树、终端视图、模型切换 |
| **P3** | 质量闭环 | 多智能体(Planner/Coder/Debugger/Reviewer) + 自检 + Evals |
| **P4** | 恢复与安全 | 快照回滚、命令黑名单完善、checkpoint 恢复、外部改动监听 |
| **P5** | 分发与智能 | 打包安装包/自动更新、（可选）本地索引/RAG |

> P0 是为单人开发专门加的"脚手架阶段"，确保从第一行代码起就满足工程规范。

---

## 3. 阶段拆解与工作流（Workstreams）

### P0 工程底座
**目标**：有骨架、有门禁、能跑起一个 PySide6 空窗口、能打包。
- WS-0.1 初始化仓库：目录结构（§5.1）、`pyproject.toml`、`.gitignore`、`.editorconfig`
- WS-0.2 工具链：uv 依赖、ruff/black/mypy 配置、pre-commit（可选）
- WS-0.3 应用入口：`qasync` 启动 Qt，事件循环打通
- WS-0.4 打包冒烟：PyInstaller 打出空窗口 AppImage/exe
- WS-0.5 文档：README + docs/ 就位

**验收（DoD）**：`uv run codepilot` 打开空窗口；`pyinstaller` 产出可运行的包；lint/类型通过。

### P1 基础闭环
**目标**：端到端跑通"选目录 → 对话 → 读 → 改(确认) → 执行"。
- WS-1.1 领域层：Entities + Events + Ports（Session/Message/ToolCall/Approval；Workspace/Executor/Repository/AgentOrchestrator）
- WS-1.2 持久化：SQLAlchemy(async)+aiosqlite、Alembic 初始迁移、Repository 实现
- WS-1.3 Provider：openai 兼容（DeepSeek）适配 + `FakeChatModel` 测试替身
- WS-1.4 Agent 引擎：LangGraph 单图（agent ↔ tools 循环）+ LangChain 工具
- WS-1.5 工作区：`LocalDirectWorkspace`（白名单 + 路径校验）
- WS-1.6 执行器：`LocalExecutor`（无 shell、超时、输出上限、流式回调）
- WS-1.7 确认服务：`Approval` + LangGraph `interrupt()`/`Command(resume)`
- WS-1.8 GUI 最小集：会话列表 + 对话视图 + 目录选择 + 确认卡片 + 终端输出
- WS-1.9 事件桥：应用事件总线 → Qt Signal

**验收（DoD）**：能新建会话、绑定目录、让 agent 读一个文件、生成一次修改并确认落盘、跑一次 `pytest`/`echo` 并看到输出。

### P2 体验完善
- WS-2.1 流式渲染（token 增量、工具步骤卡）
- WS-2.2 Diff 视图（写/改确认卡片高亮）
- WS-2.3 文件树（QFileSystemModel，限 workspace）
- WS-2.4 终端视图完善（长命令实时日志、虚拟滚动）
- WS-2.5 设置页（模型/参数/白名单）、配置持久化
- WS-2.6 Provider 切换（Claude / 本地模型适配位打通）

**验收**：长命令实时输出不卡 UI；写改前看到清晰 diff；可切换模型后端。

### P3 质量闭环
- WS-3.1 LangGraph 子图：Planner / Coder / Debugger / Reviewer
- WS-3.2 Supervisor 路由 + 黑板 State
- WS-3.3 Reviewer 自检（run_tests/静态检查）+ 回边
- WS-3.4 多智能体视图（GUI 展示计划与执行）
- WS-3.5 Evals harness（固定用例集 + 阈值）

**验收**：给它一个失败测试，能"执行→定位→改→重跑"直到通过或达上限；Evals 可回归。

### P4 恢复与安全
- WS-4.1 写入前快照 + 一键回滚
- WS-4.2 命令黑名单完善 + 危险命令二次确认
- WS-4.3 LangGraph checkpoint 持久化 + 崩溃恢复验证
- WS-4.4 外部改动监听（watchdog）+ 冲突提示
- WS-4.5 幂等键全链路校验（重放不重复副作用）

**验收**：杀进程后会话可恢复；误改可一键回滚；危险命令被拦截。

### P5 分发与智能（可选）
- WS-5.1 PyInstaller 各平台打包 + 首次运行引导（建目录/迁移/填 Key）
- WS-5.2 自动更新（可选）
- WS-5.3（可选）本地索引/符号检索/RAG

**验收**：干净机器上安装即可运行，无需装 Python。

---

## 4. 定义完成（Definition of Done）

**单个任务 DoD**
- [ ] 代码符合 `DEVELOPMENT_GUIDELINES.md`
- [ ] 有对应测试（单测；关键路径有集成测试）
- [ ] `ruff` / `black` / `mypy` 通过
- [ ] 涉及 UI 的：手动点过一遍，关键交互正常
- [ ] 涉及契约/结构的：更新对应文档
- [ ] 一次 Conventional Commit 提交，可独立回滚

**阶段 DoD**
- [ ] 该阶段所有 WS 完成
- [ ] 端到端演示脚本可跑通
- [ ] 更新 README/文档
- [ ] 已知问题登记进技术债（§9）

---

## 5. 高风险点与 Spike（先做验证）

单人开发最怕"做到一半发现跑不通"，以下先做最小验证（Spike），成功后再进正式阶段：

| Spike | 验证内容 | 风险 | 时机 |
|-------|----------|------|------|
| S1 qasync + Qt | asyncio 与 Qt 事件循环融合，后台任务不卡 UI | 高 | P0 |
| S2 PyInstaller + PySide6 | 打包后 Qt 插件/资源正常 | 高 | P0 |
| S3 LangGraph interrupt + checkpointer | 用 SQLite checkpointer，`interrupt()` 后 resume 生效 | 高 | P1 |
| S4 子进程流式 | `create_subprocess_exec` 增量读 stdout/stderr 不卡死 | 中 | P1 |
| S5 LangChain 工具 + DeepSeek tool-calling | 兼容接口下工具调用格式正确 | 中 | P1 |
| S6 Qt 大文本渲染 | 长输出/长对话不卡（虚拟化/分块） | 中 | P2 |

> Spike 产出为**一次性验证代码**，不进主干；结论回填到 TDD/本计划。

---

## 6. 单人开发流程（Trunk-based 适配）

```
main ──●────●──────●───────●──────▶ (始终可运行)
        \  featshort  /
         \__ 1 个提交/提交组 __/
```

**日常循环**
1. 从 `main` 切短命分支：`feat/<slug>` / `fix/<slug>` / `chore/<slug>`
2. 小步提交（Conventional Commits）
3. 自测 + 本地门禁（lint/类型/测试）
4. 合并前 `rebase main`（保持线性历史）；**squash 合并**回 `main`
5. `main` 始终可运行；合并即"发布"（桌面应用无灰度需求）

**单人下的"自助评审"清单**（合并前自问）
- [ ] 这个改动是否最小、是否夹带了无关修改？
- [ ] 依赖方向有没有被破坏（外层依赖内层）？
- [ ] 有没有把逻辑写进了 GUI 层？
- [ ] 有没有引入阻塞调用（阻塞 UI 事件循环）？
- [ ] 有没有绕过安全闸门（未校验路径 / `shell=True` / 未确认就写）？

---

## 7. 环境与工具

| 项 | 选型 |
|----|------|
| Python | 3.11+（建议 3.12） |
| 依赖/虚拟环境 | `uv`（`uv sync` / `uv run`） |
| Lint/格式化 | ruff + black |
| 类型 | mypy |
| 测试 | pytest / pytest-asyncio / pytest-qt |
| 提交钩子 | pre-commit（可选，见 §8） |
| 打包 | PyInstaller |
| 版本控制 | Git（Trunk-based） |

**起步命令（示意）**
```bash
uv sync
uv run ruff check . && uv run black --check . && uv run mypy src
uv run pytest
uv run codepilot        # 启动桌面应用
```

---

## 8. 质量门禁：现状与升级路径

**现状（轻量）**：本地跑 lint + 单测；不强制覆盖率阈值与严格 mypy。
**升级路径（当项目变大/加人时逐条开启）**：
1. pre-commit 强制 ruff/black/mypy（本地拦截）
2. CI：PR 上跑 lint/类型/测试
3. 覆盖率阈值（核心域 ≥ 90%）
4. mypy `strict`
5. 依赖安全扫描（`pip-audit`/Trivy）
6. Evals 门禁（P3 起）

> 目标不是"现在就全上"，而是**结构支持随时加严**，避免后期补票成本。

---

## 9. 技术债与风险登记册

**技术债登记**（发现即记，阶段性清偿）

| 编号 | 描述 | 来源阶段 | 计划 |
|------|------|----------|------|
| TD-1 | 事件 `seq` 回放暂未实现，仅保序 | P1 | P4 |
| TD-2 | 编排器 `_runs`/`_seq` 为进程内存态，崩溃后 run 上下文丢失（checkpoint 已落盘，恢复流程未接） | P1 | P4 |
| TD-3 | GUI 未消费 `TokenEvent`，助手输出按整条消息渲染（无流式） | P1 | P2 |
| TD-4 | 确认卡片仅显示纯文本预览，未做结构化 Diff 高亮 | P1 | P2 |
| TD-5 | 切换会话只重置当前指针，未回填历史消息到对话视图 | P1 | P2 |
| TD-6 | 会话/消息列表无分页，长历史一次性加载 | P1 | P2 |

**风险登记册**

| 风险 | 影响 | 概率 | 缓解 | 触发条件 |
|------|------|------|------|----------|
| qasync/Qt 集成踩坑 | 高 | 中 | Spike S1 先行 | P0 |
| PyInstaller 打包 Qt 失败 | 高 | 中 | Spike S2 + CI 各平台 | P0 |
| LangGraph 版本 API 变动 | 中 | 中 | 锁版本 + 端口隔离 | 升级时 |
| Agent 误改用户代码 | 高 | 中 | 确认 + 快照 + 黑名单 | P1/P4 |
| 长输出卡 UI | 中 | 中 | 虚拟化 + 分块渲染 | P2 |
| SQLite 写并发 | 低 | 低 | 单进程 + WAL + 写串行 | — |

---

## 10. 阶段检查清单（Checklist 模板）

每个阶段结束时对照：

- [ ] 阶段目标达成、可演示
- [ ] 所有 WS 完成且过 DoD
- [ ] 相关 Spike 结论已回填文档
- [ ] 文档更新（README/TDD/本计划）
- [ ] 技术债登记更新
- [ ] `main` 绿色：lint/类型/测试全过

---

## 11. 未来扩展点（预留，不在当前范围）
- 质量门禁全面加严（CI + 覆盖率 + strict mypy + 安全扫描）
- 本地代码索引 / RAG（P5 可选）
- 插件化工具生态
- 多显示器/主题/无障碍打磨
- 多平台签名与自动更新
