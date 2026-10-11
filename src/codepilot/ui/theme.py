"""界面主题：米白基调 + 赤陶强调色。

样式以 Python 字符串给出（非 ``.qss`` 资源文件），免去打包改造，且可单测。
在 ``app.py`` 创建主窗口之前调用 :func:`apply_theme`。见规范 §15。
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# --- 调色板（赤陶暖木）---
BG = "#F7F4EF"  # 米白背景
CARD = "#FFFFFF"  # 卡片/面板
BORDER = "#ECE7DE"  # 细边线
PRIMARY = "#C8794F"  # 赤陶主色
PRIMARY_SOFT = "#F0E0D4"  # 主色浅底（选中/悬停）
TEXT = "#3B3733"  # 暖灰正文
MUTED = "#8A8178"  # 次要文字
CODE_BG = "#2E2A27"  # 代码块深底
CODE_TEXT = "#EDE7DF"  # 代码文字
DANGER = "#B4544A"  # 拒绝/错误

RADIUS = 12  # 窗口圆角
RADIUS_SM = 8  # 控件圆角

_MONO = "JetBrains Mono, Cascadia Code, Consolas, DejaVu Sans Mono, monospace"


def build_stylesheet() -> str:
    """返回全局 QSS。"""
    return f"""
    QWidget {{
        color: {TEXT};
        font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
        font-size: 14px;
    }}

    /* --- 窗口根容器：圆角 + 细边线 --- */
    #Root {{
        background: {BG};
        border: 1px solid {BORDER};
        border-radius: {RADIUS}px;
    }}
    #Root[maximized="true"] {{
        border-radius: 0px;
        border: none;
    }}

    /* --- 标题栏 --- */
    #TitleBar {{ background: transparent; }}
    #TitleText {{ color: {TEXT}; font-size: 14px; font-weight: 600; }}
    #WinButton, #WinClose {{
        background: transparent;
        border: none;
        border-radius: 6px;
        color: {MUTED};
        font-size: 15px;
        min-width: 30px;
        min-height: 26px;
    }}
    #WinButton:hover {{ background: {PRIMARY_SOFT}; color: {TEXT}; }}
    #WinClose:hover {{ background: {DANGER}; color: #FFFFFF; }}

    /* --- 侧栏 --- */
    #Sidebar {{ background: transparent; }}
    #SidebarTitle {{ color: {MUTED}; font-size: 12px; font-weight: 600; }}

    #Sessions {{
        background: transparent;
        border: none;
        outline: none;
    }}
    #Sessions::item {{
        border-radius: {RADIUS_SM}px;
        padding: 6px 8px;
        margin: 2px 0;
        color: {TEXT};
    }}
    #Sessions::item:hover {{ background: {PRIMARY_SOFT}; }}
    #Sessions::item:selected {{ background: {PRIMARY}; color: #FFFFFF; }}

    /* --- 按钮 --- */
    #Primary {{
        background: {PRIMARY};
        color: #FFFFFF;
        border: none;
        border-radius: {RADIUS_SM}px;
        padding: 7px 14px;
        font-weight: 600;
    }}
    #Primary:hover {{ background: #B96B43; }}
    #Primary:disabled {{ background: #D9CFC4; color: #FFFFFF; }}

    #Ghost {{
        background: transparent;
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_SM}px;
        padding: 7px 14px;
    }}
    #Ghost:hover {{ background: {PRIMARY_SOFT}; border-color: {PRIMARY}; }}
    #Ghost:disabled {{ color: {MUTED}; }}

    #Danger {{
        background: transparent;
        color: {DANGER};
        border: 1px solid {DANGER};
        border-radius: {RADIUS_SM}px;
        padding: 7px 14px;
    }}
    #Danger:hover {{ background: {DANGER}; color: #FFFFFF; }}

    /* --- 输入框 --- */
    #ChatInput {{
        background: {CARD};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_SM}px;
        padding: 8px 12px;
        selection-background-color: {PRIMARY};
        selection-color: #FFFFFF;
    }}
    #ChatInput:focus {{ border-color: {PRIMARY}; }}

    /* --- 对话区 --- */
    #Transcript {{ background: transparent; border: none; }}
    #TranscriptWidget {{ background: transparent; }}

    #BubbleUser {{
        background: {PRIMARY};
        border-radius: 10px;
    }}
    #BubbleUser QLabel {{ color: #FFFFFF; }}
    #BubbleAssistant {{
        background: {CARD};
        border: 1px solid {BORDER};
        border-radius: 10px;
    }}
    #BubbleTool {{
        background: #F1ECE4;
        border: 1px solid {BORDER};
        border-radius: 10px;
    }}
    #BubbleError {{
        background: #FBEDEA;
        border: 1px solid {DANGER};
        border-radius: 10px;
    }}
    #BubbleError QLabel {{ color: {DANGER}; }}

    #CodeBlock {{
        background: {CODE_BG};
        color: {CODE_TEXT};
        border: none;
        border-radius: {RADIUS_SM}px;
        padding: 8px 10px;
        font-family: {_MONO};
        font-size: 13px;
        selection-background-color: {PRIMARY};
    }}

    /* --- 文件树 --- */
    #FileTree {{
        background: {CARD};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_SM}px;
        outline: none;
    }}
    #FileTree::item {{ padding: 4px 2px; border-radius: 6px; color: {TEXT}; }}
    #FileTree::item:hover {{ background: {PRIMARY_SOFT}; }}
    #FileTree::item:selected {{ background: {PRIMARY}; color: #FFFFFF; }}

    /* --- 确认卡片 --- */
    #ApprovalCard {{
        background: {CARD};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_SM}px;
    }}
    #ApprovalTitle {{ color: {PRIMARY}; font-weight: 600; }}
    #ApprovalPreview {{
        background: #FAF7F2;
        border: 1px solid {BORDER};
        border-radius: 6px;
        font-family: {_MONO};
        font-size: 13px;
    }}

    /* --- 滚动条 --- */
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{
        background: #D9CFC4; border-radius: 5px; min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {PRIMARY}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{
        background: #D9CFC4; border-radius: 5px; min-width: 30px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}

    /* --- 状态栏 --- */
    QStatusBar {{ background: transparent; color: {MUTED}; }}
    QStatusBar::item {{ border: none; }}

    /* --- 工具提示 --- */
    QToolTip {{
        background: {TEXT}; color: {BG};
        border: none; border-radius: 4px; padding: 4px 6px;
    }}
    """


def apply_palette(app: QApplication) -> None:
    """设置基础调色板，让原生控件（菜单、选择高亮等）与主题协调。"""
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG))
    palette.setColor(QPalette.ColorRole.Base, QColor(CARD))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(CARD))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(PRIMARY))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    app.setPalette(palette)


def apply_theme(app: QApplication) -> None:
    """应用调色板与样式表。"""
    apply_palette(app)
    app.setStyleSheet(build_stylesheet())
