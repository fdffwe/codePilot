# codePilot 工具层分析报告

> 版本：v0.1
> 日期：2026-10-12
> 关联：`docs/TECHNICAL_DESIGN.md`（§6.5 工具、§8 命令执行、§6.3 幂等）、`docs/DEVELOPMENT_GUIDELINES.md`（§10 框架治理、§11 测试、§16 安全）
> 目的：在动手优化工具层前，盘点现状、问题与差距，作为后续改造的基线。

---

## 1. 范围界定

"工具层"在本项目有两个层面，本报告覆盖两者：

- **Agent Tool 层（核心）**：AI 可调用的能力，即 `tools.py` 注册的 5 个工具。
- **工具依赖的端口/适配器**：工具背后真正干活的 `WorkspaceProvider`、`Executor`，以及模型接缝 `ChatModelFactory`。

---

## 2. 模块清单

| 文件 | 职责 | 关键位置 |
|------|------|----------|
| `infrastructure/agent/tools.py` | 工具定义、参数模型、实现（LangChain `StructuredTool`） | `_make_tool`、`TOOLS` |
| `infrastructure/agent/graph.py` | `agent↔tools` 单图；工具执行与 `interrupt()` 审批 | `tools_node`（L36） |
| `infrastructure/agent/orchestrator.py` | 把图事件转成领域事件；注入 `RunDeps` | `_node_events`（L173） |
| `infrastructure/agent/mappers.py` | domain `Message` ↔ LangChain 消息 | `from_ai_message`（L31） |
| `domain/ports/workspace.py` | 工作区端口（read/write/list） | — |
| `infrastructure/workspace/local_workspace.py` | 本地直连实现 + 路径闸门 | `resolve`（L28） |
| `domain/ports/executor.py` | 命令执行端口 | — |
| `infrastructure/executor/local_executor.py` | `create_subprocess_exec`、超时、截断 | `run`（L30） |
| `infrastructure/providers/{base,fake,openai_factory}.py` | 模型工厂（真实/Fake） | — |

**数据流**：模型返回 `tool_calls` → `graph.tools_node` 按 `TOOL_SPECS` 校验参数 → 非只读先 `interrupt()` → `spec.run(deps, args)` → 经 `Workspace`/`Executor` 端口执行 → 结果包成 `ToolMessage` 回灌 → `orchestrator` 转译成 `ToolCallEvent`/`ToolResultEvent` → `ChatService` 落库并广播。

---

> **进展（2026-10-24）**：P4（校验失败回传 error ToolMessage）、P5（改用 `StructuredTool`）、P9（工具单测）已修复；工具集已补 `edit_file` 与用户沟通工具 `ask_user`（提问时 run 暂停，回答后继续；问题不落库）。UI 增加审批/提问/结束/出错的浮层与任务栏提醒。
>
> **进展（2026-10-26）**：P1 的检索缺口已补 `glob`/`grep`（只读；`glob` 按通配模式返回工作区相对路径，`grep` 按正则返回 `路径:行号: 内容`；默认忽略 `.git`/`node_modules`/构建目录，跳过符号链接与二进制/超大文件，超限时显式提示截断）。P2 已按 `tool_call_id` 缓存执行结果，修复 interrupt 重放的副作用重复。审批层新增 `domain/approval.py`：按工具/参数决策 allow/ask/deny，支持 `plan/default/auto-edit/yolo` 模式、显式规则、会话允许列表与高危命令硬拒绝；P7 的风险分级已部分落地（命令风险与硬拒绝）。图结构改为 `prepare → approval(自环) → execute`，每个节点只保留一次 `interrupt()`，消除了循环内多次中断导致的 O(n²) 重放，且审批阶段不产生副作用；用户确认次数仍为逐个，批量确认尚未做。以下问题清单与差距表保留原始基线描述。

## 3. 当前工具清单（6 个）

| 工具 | safety | risk | 参数 | 实现 |
|------|--------|------|------|------|
| `read_file` | READ | low | `path` | `workspace.read_text` |
| `list_dir` | READ | low | `path="."` | `workspace.list_dir` |
| `write_file` | WRITE | medium | `path`, `content` | `workspace.write_text`（整文件覆盖） |
| `edit_file` | WRITE | medium | `path`, `old_string`, `new_string`, `replace_all=false` | `workspace.edit_text`（精确字符串替换） |
| `ask_user` | ASK | low | `question`, `options=[]` | 无 IO；`tools_node` 以 `interrupt()` 暂停等待回答 |
| `run_command` | EXEC | high | `argv: list[str]` | `executor.run` |

**优点**：路径安全闸门扎实（`resolve` + `ensure_within` 拒越界/软链，`local_workspace.py:28-33`）；执行器无 `shell=True`、超时杀进程组、输出上限（`local_executor.py:42-117`）——这两处是全项目质量最高的部分。

---

## 4. 问题清单（按严重度）

### 高严重度

**P1 — 工具能力不足，缺 `grep`/`glob`**（`edit_file`、`ask_user` 已补）
TDD §6.5 规划了 12 个工具。`edit_file` 已实现精确字符串替换（唯一匹配，或 `replace_all`），不再需要整文件重写；`ask_user` 让模型在信息不足时主动澄清。当前仍缺 `grep`/`glob`：agent 探索代码只能 `list_dir`+逐个 `read_file`，效率极低。

**P2 — 无幂等保护，`interrupt` 重放可能重复执行副作用**
LangGraph 的 `interrupt()`（`graph.py`）会让节点从开头重跑。`tools_node` 在循环里对**多个非只读调用逐个 interrupt**，这是已知反模式（resume 值按顺序匹配，易错位），且规范 §10/§6.3 明确要求"副作用带幂等键 `tool_call_id`，重放不重复生效"——当前**无任何已执行集合**，重放即重复写盘/跑命令。`ask_user` 会放大该问题（同一批次中排在提问之前的工具每次回答都会重跑）；目前仅靠 `_pending_kind` 防止 resume 类型错配，未做幂等。

**P3 — 工具结果无大小控制，会撑爆上下文**
`read_file`/`run_command` 输出原样塞进 `ToolMessage`（`tools.py:57-68, 71-82`），只有 Executor 层 1MB 硬截断，无 token 预算/行数限制/外置。读大文件或长命令输出后，下一轮 LLM 调用会超上下文或花费巨大。TDD §6.6/§8 要求"长输出外置 + lazy 读取"。

### 中严重度

**P4 — 参数校验失败会终止整个 run**
`graph.py:53` 的 `spec.args_model.model_validate(...)` 在 `try` 之外，Pydantic 校验失败会冒泡出节点 → 被 `orchestrator._translate` 捕成 `ErrorEvent` 终止 run（`orchestrator.py:157`）。正确做法是把校验错误作为 error `ToolMessage` 回给模型自纠。

**P5 — 手写 OpenAI schema，绕过 LangChain 工具抽象**
`ToolSpec.schema()`（`tools.py:94-103`）手写 `{"type":"function",...}`，`bind_tools(tool_schemas())` 消费原始 dict。规范 §10 明确要求"用 `@tool`/`StructuredTool`"。当前自建机制能跑，但放弃了 LangChain 的 schema 转换/校验一致性，且 Pydantic v2 的 `$defs`/`anyOf` 与 OpenAI 格式在复杂参数（可选/枚举/嵌套）时可能不兼容。

**P6 — `read_file` 无行号、无分页**
`read_text` 返回全文单一字符串（`local_workspace.py:35`）。Claude Code 的 Read 带行号便于后续精确定位编辑；无 `offset`/`limit` 则大文件不可用，为将来 `edit_file` 也埋了障碍。

**P7 — 命令黑名单缺失，EXEC 与 WRITE 确认无差别**
TDD §8 / 规范 §16 要求危险命令（`rm -rf /`、`sudo`、`mkfs`…）拒绝或二次确认（P4 计划）。当前任何 argv 只需一次确认；`run_command` 的 preview 只是 `join(argv)`（`tools.py:118`），无命令语义分析。`risk` 由 safety 硬编码映射（`tools.py:105-111`），无法区分 `echo` 与 `rm -rf`。

### 低严重度

**P8 — resume 值类型脆弱**：`graph.py:63` 用 `if not decision` 判定，只支持 bool。将来若做"编辑后批准"需重构协议。

**P9 — 工具层无单元测试**：有 orchestrator 集成测试（`test_orchestrator.py`）覆盖 read/write/审批/拒绝/迭代上限，但**没有针对单个 `ToolSpec`** 的 schema 生成、`preview`、参数边界测试（规范 §11 明确要求"工具参数"单测）；`_run_command` 的组装逻辑也无测试。

**P10 — resume 后工具名可能为空**：`orchestrator._node_events` 在 resume 时 `pending` 已清空（`orchestrator.py:207`），回退到 `getattr(msg,"name","")`，`ToolMessage.name` 常为 `None` → `ToolResultEvent.call.name` 为空，UI 显示异常。

**P11 — preview 无脱敏/长度控制**：`_write_preview` 回显全文，同时进审批卡片和 `approvals.preview` 入库。

---

## 5. 与设计目标的差距

| 目标（TDD §6.5） | 现状 |
|------------------|------|
| `list_dir` `read_file` `grep` `glob` | ✅ ✅ ❌ ❌ |
| `write_file` `edit_file` `delete_file` `apply_patch` | ✅ ✅ ❌ ❌ |
| `run_command` `run_tests` `build` | ✅ ❌ ❌ |
| 用户沟通（主动澄清） | ✅ `ask_user` |
| 工具带 `safety` 元数据 | ✅ 有 |
| 工具经端口（不直接碰 IO） | ✅ 做到了 |
| 用 LangChain `@tool`/`StructuredTool` | ✅ 已改用 `StructuredTool` |
| 副作用幂等键 | ❌ 缺失 |
| 长输出外置 | ❌ 缺失 |
| 命令黑名单 | ❌ 缺失 |

---

## 6. 优化建议方向（优先级排序）

1. **补齐核心工具**：`edit_file`（基于 old/new 或 patch，配 diff preview）> `grep`/`glob` > `read_file` 加行号/分页。这是收益最大的改动。
2. **加固执行路径**：幂等键（记录已完成的 `tool_call_id`）+ 参数校验失败转 error ToolMessage + 结果按行数/token 截断。
3. **重构审批模型**：把"逐个 interrupt"改成"收集本轮所有待批准调用，一次性审批"，并细化 risk（区分危险命令）。
4. **向 LangChain 抽象收敛**：评估用 `StructuredTool` 替换手写 schema（注意保持 safety 元数据与端口调用约束）。
5. **补测试**：为每个 `ToolSpec` 加单元测试（schema/preview/参数边界/幂等）。

---

## 7. 结论

工具层的**底座（路径安全、无 shell 执行）质量很好**，但**工具集广度与执行健壮性**是当前主要短板——缺 `edit_file`/检索类工具、无幂等、无输出预算控制、校验失败即崩 run。建议第一优先补 `edit_file` + 检索工具并加固幂等与截断。
