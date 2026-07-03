# -*- mode: python ; coding: utf-8 -*-
# Spec di build per YGO Toolbox (eseguibile onefile, finestra senza console).
#
# Nota: i moduli funzionali sono scoperti a runtime (pkgutil), quindi PyInstaller
# non li vede con l'analisi statica. Li includiamo via collect_submodules; serve
# SPECPATH su sys.path perché collect_submodules importi i NOSTRI pacchetti.
import os
import sys
sys.path.insert(0, SPECPATH)
from PyInstaller.utils.hooks import collect_submodules

hidden = collect_submodules('modules') + collect_submodules('core')

a = Analysis(
    ['main.py'],
    pathex=[SPECPATH],
    binaries=[],
    datas=[(os.path.join(SPECPATH, 'assets', 'icon.ico'), 'assets'),
           (os.path.join(SPECPATH, 'assets', 'fonts'), os.path.join('assets', 'fonts'))],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='YGO Toolbox',
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
    icon=os.path.join(SPECPATH, 'assets', 'icon.ico'),
    version=os.path.join(SPECPATH, 'version_info.txt'),
)
