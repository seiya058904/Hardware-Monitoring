# -*- mode: python ; coding: utf-8 -*-

import hashlib
from pathlib import Path


PROJECT_ROOT = Path(SPECPATH)
EXPECTED_HASHES = {
    PROJECT_ROOT / 'tools' / 'PresentMon' / 'PresentMon.exe': '364E5D98D4D134BD54DD25C22ED2CA2F4883F8BC3ED6502BEE0C151E3436D30',
    PROJECT_ROOT / '_internal' / 'libs' / 'LibreHardwareMonitorLib.dll': 'A0F2728F1734C236A9D02D9E25A88BC4F8CB7BD1FAFF1770726BEB7AF06BF8DC',
}


for path, expected in EXPECTED_HASHES.items():
    if not path.exists():
        raise FileNotFoundError(f'Missing pinned build input: {path}')
    actual = hashlib.sha256(path.read_bytes()).hexdigest().upper()
    if actual != expected:
        raise RuntimeError(f'Hash mismatch for {path}: expected {expected}, got {actual}')


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[('_internal/libs', 'libs'), ('_internal/app.ico', '.'), ('tools', 'tools')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Hardware Monitoring',
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
    icon=['_internal\\app.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Hardware Monitoring',
)
