# -*- mode: python ; coding: utf-8 -*-
"""Сборка одного Evolution.exe: uv run pyinstaller --noconfirm --clean evolution.spec"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

spec_dir = Path(SPECPATH)

datas, binaries, hiddenimports = collect_all("pygame")
evo_d, evo_b, evo_h = collect_all("evolution")
datas += evo_d
binaries += evo_b
hiddenimports += evo_h

a = Analysis(
    [str(spec_dir / "packaging" / "run_game.py")],
    pathex=[str(spec_dir / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    a.binaries,
    a.datas,
    [],
    name="Evolution",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
