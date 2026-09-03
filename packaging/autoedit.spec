# -*- mode: python ; coding: utf-8 -*-
"""Receta de PyInstaller para el ejecutable de AutoEdit.

Genera un único archivo que ya lleva dentro Python, la interfaz web y FFmpeg,
de modo que el usuario final no instala nada. Se construye con:

    python packaging/build.py

o, si prefieres llamar a PyInstaller a mano:

    pyinstaller packaging/autoedit.spec --noconfirm --clean
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parent

# Recursos que viajan dentro del ejecutable.
datas = [
    (str(ROOT / "web"), "web"),          # la interfaz
    *collect_data_files("imageio_ffmpeg"),  # el FFmpeg de repuesto
]

# uvicorn carga sus protocolos y bucles por nombre, en tiempo de ejecución, así
# que PyInstaller no puede verlos leyendo los imports.
hiddenimports = [
    *collect_submodules("uvicorn"),
    *collect_submodules("autoedit"),
    "anyio",
    "h11",
]
for optional in ("websockets", "httptools", "uvloop", "watchfiles"):
    try:
        __import__(optional)
    except ImportError:
        continue
    hiddenimports.extend(collect_submodules(optional))

# Bultos que no usamos y engordan el binario sin dar nada a cambio.
excludes = [
    "tkinter", "matplotlib", "scipy", "pandas", "IPython", "notebook",
    "pytest", "setuptools", "pip", "sqlite3", "test", "unittest",
]

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

icon = ROOT / "packaging" / "icon.icns" if sys.platform == "darwin" else ROOT / "packaging" / "icon.ico"

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="AutoEdit",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # Consola visible a propósito: ahí sale la dirección de la interfaz y los
    # errores de FFmpeg. Sin ella, un fallo al arrancar sería invisible.
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon) if icon.exists() else None,
)
