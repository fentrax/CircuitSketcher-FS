# -*- mode: python ; coding: utf-8 -*-
# Onedir-Build: EXE + DLLs + Symbole + Assets als echte Dateien im Ordner.
# Vorteil gegenueber Onefile: der Symbol-Editor speichert direkt in den
# (beschreibbaren) Installationsordner - Aenderungen bleiben erhalten.

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('symbols', 'symbols'), ('assets', 'assets'), ('LICENSE', '.')],
    hiddenimports=['PyQt5.QtSvg'],
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
    name='SchaltungsZeichner',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/favicon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SchaltungsZeichner',
)
