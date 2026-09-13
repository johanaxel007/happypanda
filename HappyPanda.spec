# -*- mode: python ; coding: utf-8 -*-
import os
import shutil

from PyInstaller.building.api import COLLECT, EXE, PYZ
from PyInstaller.building.build_main import Analysis
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringTable,
    StringStruct,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

# --- Version generation ---
# Read version from VS.txt
try:
    with open('VS.txt', 'r') as f:
        version_string = f.read().strip()

    # PyInstaller requires a tuple of four integers for filevers and prodvers
    version_parts = version_string.split('.')
    while len(version_parts) < 4:
        version_parts.append(
            '0'  # Pad with zeros if necessary (e.g., 1.6.2 becomes 1.6.2.0)
        )

    version_tuple = tuple(map(int, version_parts))

except Exception as e:
    print(f'Warning: Could not read VS.txt. Defaulting to version 0.0.0.0. Error: {e}')
    version_string = '0.0.0.0'
    version_tuple = (0, 0, 0, 0)

# Dynamically create the version information object
version_info = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=version_tuple,
        prodvers=version_tuple,
        mask=0x3F,
        flags=0x0,
        OS=0x40004,
        fileType=0x1,
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    '040904B0',
                    [
                        StringStruct('CompanyName', 'Pewpews'),
                        StringStruct('FileDescription', 'Happypanda Manga Manager'),
                        StringStruct('FileVersion', version_string),
                        StringStruct('InternalName', 'HappyPanda'),
                        StringStruct('LegalCopyright', '© Pewpews. All rights reserved.'),
                        StringStruct('OriginalFilename', 'HappyPanda.exe'),
                        StringStruct('ProductName', 'HappyPanda'),
                        StringStruct('ProductVersion', version_string),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct('Translation', [1033, 1200])]),
    ],
)

block_cipher = None

# --- pyInstaller setup ---
a = Analysis(
    ['version\\main.py'],
    pathex=[],
    binaries=[],
    datas=[('res', 'res')],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    noarchive=False,
    optimize=1,
    hiddenimports=['PyQt6.sip'],
    excludes=[
        'pytest',
        'doctest',
        'tkinter',
        'PyQt6.QtWebEngineWidgets',
        'PyQt6.QtQuick',
        'PyQt6.QtMultimedia',
        'PyQt6.QtTest',
        'PyQt6.QtSql',
        'PyQt6.QtNfc',
        'PyQt6.QtBluetooth',
        'PyQt6.QtPositioning',
        'PyQt6.QtLocation',
        'PyQt6.QtSensors',
        'PyQt6.QtWebChannel',
        'PyQt6.QtWebSockets',
        'PyQt6.QtXmlPatterns',
    ],
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='HappyPanda',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='res/happypanda.ico',
    version=version_info,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='HappyPanda',
)

# --- Move res folder to the root directory ---
# Path to the newly created distribution directory
dist_path = os.path.join(SPECPATH, 'dist', 'HappyPanda')

# Path to the source 'res' folder inside '_internal'
source_res_path = os.path.join(dist_path, '_internal', 'res')

# Path to the desired destination for the 'res' folder
dest_res_path = os.path.join(dist_path, 'res')

# Move the 'res' folder
if os.path.exists(source_res_path):
    print(f"Moving '{source_res_path}' to '{dest_res_path}'")
    shutil.move(source_res_path, dest_res_path)
    print("Move complete.")
else:
    print(f"Warning: '{source_res_path}' not found. Skipping move operation.")
