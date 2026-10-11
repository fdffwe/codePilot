"""pytest 全局配置。

在导入 Qt 之前把平台设为 offscreen，保证无显示环境（CI/无头）也能跑 GUI 测试。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
