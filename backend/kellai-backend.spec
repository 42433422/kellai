# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules, copy_metadata
from pathlib import Path
import runpy
import shutil

build_info = runpy.run_path(str(Path(SPECPATH) / "build_identity.py"))["write_build_info"]()


a = Analysis(
    ['kellai_backend_entry.py'],
    pathex=[],
    binaries=[],
    datas=copy_metadata("keyring") + copy_metadata("kellai") + [(str(build_info), "app")],
    hiddenimports=collect_submodules("keyring.backends"),
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
    name='kellai-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

shutil.copyfile(build_info, Path(DISTPATH) / "build-info.json")
