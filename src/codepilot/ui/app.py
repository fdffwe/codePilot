"""应用启动：qasync 融合 asyncio 与 Qt 事件循环。

见 docs/TECHNICAL_DESIGN.md §3.3 线程/进程模型。
"""

from __future__ import annotations

import asyncio
import sys

import qasync
from PySide6.QtWidgets import QApplication

from codepilot.core.config import get_settings
from codepilot.core.logging import configure_logging, get_logger
from codepilot.ui.main_window import MainWindow


def run() -> int:
    """启动桌面应用，返回退出码。"""
    settings = get_settings()
    settings.ensure_dirs()
    configure_logging(settings.log_level, log_dir=settings.logs_dir)
    log = get_logger(__name__)

    app = QApplication(sys.argv)
    app.setApplicationName(settings.app_name)

    # 将 asyncio 事件循环与 Qt 事件循环合并
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow(settings)
    window.show()
    log.info("app_started", data_dir=str(settings.data_dir), model=settings.llm_model)

    with loop:
        loop.run_forever()
    log.info("app_stopped")
    return 0
