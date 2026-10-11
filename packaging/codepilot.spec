# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置。

用法：
    uv run pyinstaller packaging/codepilot.spec --noconfirm

产物：dist/codepilot/（one-dir，启动快）。跨平台需在各自平台构建。
"""

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("qasync")

a = Analysis(  # noqa: F821
    ["../src/codepilot/__main__.py"],
    pathex=["../src"],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="codepilot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI 应用，不弹控制台窗口
    disable_windowed_traceback=False,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="codepilot",
)
