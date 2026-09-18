# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — đóng gói ứng dụng thành thư mục chạy độc lập (onedir).

Chạy trên Windows bằng ``build.bat`` hoặc trực tiếp::

    pyinstaller accounting_app.spec

Kết quả nằm ở ``dist/AccountingDocumentTool/``. CỐ Ý dùng chế độ **onedir**
(không phải ``--onefile``): ``config_loader.DEFAULT_CONFIG_DIR`` và đường dẫn
mặc định của database/log được tính từ vị trí file ``.py`` đang chạy, và khi
đóng gói onedir PyInstaller giữ nguyên bố cục thư mục (``config/`` nằm cạnh
``app/`` bên trong ``dist/AccountingDocumentTool/``) — vị trí đó CỐ ĐỊNH giữa
các lần chạy. Với ``--onefile``, PyInstaller giải nén ra một thư mục TẠM MỚI
mỗi lần khởi động ứng dụng, nghĩa là database SQLite và file log sẽ biến mất
sau khi đóng ứng dụng — không phù hợp cho một app cần lưu dữ liệu lâu dài.
"""

from __future__ import annotations

from pathlib import Path

block_cipher = None

_ROOT = Path.cwd()

a = Analysis(
    ["main.py"],
    pathex=[str(_ROOT)],
    binaries=[],
    datas=[
        ("config", "config"),
        ("assets", "assets"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AccountingDocumentTool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AccountingDocumentTool",
)
