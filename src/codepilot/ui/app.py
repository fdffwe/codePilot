"""应用启动：qasync 融合 asyncio 与 Qt 事件循环。

装配顺序：先起 Qt+asyncio 合并循环，再异步构建组合根（含 DB 迁移、checkpointer），
最后把 EventBus 桥成 Qt 信号并挂到主窗口。见 docs/TECHNICAL_DESIGN.md §3.3。
"""

from __future__ import annotations

import asyncio
import sys

import qasync
from PySide6.QtWidgets import QApplication, QMessageBox

from codepilot.core.config import Settings, get_settings
from codepilot.core.di import build_container
from codepilot.core.logging import configure_logging, get_logger
from codepilot.ui import theme
from codepilot.ui.bridge import EventBridge
from codepilot.ui.input_method import configure_input_method
from codepilot.ui.main_window import MainWindow
from codepilot.ui.viewmodels import ChatViewModel


async def _bootstrap(settings: Settings, app: QApplication) -> None:
    """在已运行的合并循环里构建容器并显示窗口，直到窗口关闭。

    关闭窗口时不立刻让 Qt 退出：先跑完容器清理（异步），再显式 ``app.quit()``，
    避免 Qt 事件循环在异步清理完成前停止，导致 ``run_until_complete`` 抛错。
    """
    log = get_logger(__name__)
    app.setQuitOnLastWindowClosed(False)
    try:
        async with build_container(settings) as container:
            bridge = EventBridge(container.bus)
            viewmodel = ChatViewModel(container.chat_service)
            window = MainWindow(settings, viewmodel, bridge)
            window.show()
            log.info(
                "app_started", data_dir=str(settings.data_dir), model=settings.llm_model
            )

            closed: asyncio.Future[None] = asyncio.get_running_loop().create_future()

            def _on_closed() -> None:
                if not closed.done():
                    closed.set_result(None)

            window.closed.connect(_on_closed)
            await closed
    except Exception as exc:  # 组合根失败（如缺 API Key / 迁移失败）
        log.exception("bootstrap_failed")
        QMessageBox.critical(None, "启动失败", str(exc))
        app.quit()
        return
    log.info("app_stopped")
    app.quit()


def run() -> int:
    """启动桌面应用，返回退出码。"""
    # 必须在 QApplication 之前决定 QPA 平台与输入法模块
    configure_input_method()
    settings = get_settings()
    settings.ensure_dirs()
    configure_logging(settings.log_level, log_dir=settings.logs_dir)

    app = QApplication(sys.argv)
    app.setApplicationName(settings.app_name)
    theme.apply_theme(app)

    # 将 asyncio 事件循环与 Qt 事件循环合并
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    with loop:
        loop.run_until_complete(_bootstrap(settings, app))
    return 0
