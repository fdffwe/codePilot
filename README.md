# codePilot

本地原生桌面 AI 编码助手 —— 形态对标 Claude Code，通过桌面 GUI 用自然语言驱动 AI **读写你本机的真实代码**、执行命令、调试排错、搭建项目。

> 纯本地、单用户、单机运行。不做浏览器 / 云端 / 多租户。

## 状态

**P1 基础闭环**（进行中）：领域层与端口、SQLite 持久化（含迁移）、LangGraph Agent 引擎、
本地工作区与执行器、写/执行前人工确认、最小 GUI 与事件桥。P0 底座（分层骨架、工具链、
qasync + Qt 空窗口、打包配置）已完成。

## 技术栈

| 层 | 选型 |
|----|------|
| 语言 | Python 3.11+ |
| GUI | PySide6（Qt）+ qasync |
| Agent | LangChain（基础）+ LangGraph（编排） |
| 持久化 | SQLite + SQLAlchemy 2.0 + Alembic |
| 模型 | 默认 deepseek-v4-flash（OpenAI 兼容），可切换 |
| 打包 | PyInstaller |

## 快速开始

```bash
# 安装 uv：https://docs.astral.sh/uv/
uv sync                 # 创建虚拟环境并安装依赖
uv run codepilot        # 启动桌面应用
```

## 开发

```bash
uv run ruff check .     # lint
uv run black --check .  # 格式检查
uv run mypy             # 类型检查
uv run pytest           # 测试
```

## 架构

```
ui ─▶ application ─▶ domain ◀─ infrastructure（实现 ports）
```

- `domain/`：纯逻辑 + 端口，**禁止**依赖框架/IO
- `application/`：用例编排
- `infrastructure/`：LangChain/LangGraph、DB、工作区、执行器等实现
- `ui/`：PySide6 界面，不含业务逻辑

## 文档

- [需求文档](docs/REQUIREMENTS.md)
- [技术设计](docs/TECHNICAL_DESIGN.md)
- [工程规划](docs/ENGINEERING_PLAN.md)
- [开发规范](docs/DEVELOPMENT_GUIDELINES.md)
