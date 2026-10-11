"""结构化日志配置（structlog ↔ stdlib logging 桥接）。见规范 §8。

通过 stdlib 的 handler 落地，保证「控制台 + 文件（轮转）」同时生效，
且第三方库（logging）日志也走同一渲染器。
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

import structlog


def configure_logging(
    level: str = "INFO",
    *,
    log_dir: Path | None = None,
    json_output: bool = False,
) -> None:
    """配置日志：开发彩色、生产 JSON；可选落本地文件（轮转）。"""
    level_num = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    def make_formatter(*, colors: bool) -> structlog.stdlib.ProcessorFormatter:
        renderer: structlog.types.Processor = (
            structlog.processors.JSONRenderer()
            if json_output
            else structlog.dev.ConsoleRenderer(colors=colors)
        )
        return structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                renderer,
            ],
        )

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(make_formatter(colors=sys.stderr.isatty() and not json_output))
    handlers: list[logging.Handler] = [console]
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "codepilot.log",
            maxBytes=5_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(make_formatter(colors=False))
        handlers.append(file_handler)

    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(level_num)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level_num),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "codepilot") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
