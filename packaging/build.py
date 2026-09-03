#!/usr/bin/env python3
"""Construye el ejecutable de AutoEdit para el sistema en el que se ejecuta.

    python packaging/build.py

Un ejecutable solo se puede construir desde su propio sistema: en Windows sale
el `.exe`, en macOS el binario de macOS y en Linux el de Linux. Para tenerlos
los tres sin tener las tres máquinas, están las GitHub Actions de
`.github/workflows/build.yml`.
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packaging" / "autoedit.spec"
DIST = ROOT / "dist"
BUILD = ROOT / "build"


def _target_name() -> str:
    """Nombre del binario final, con sistema y arquitectura."""
    system = {"darwin": "macos", "windows": "windows"}.get(
        platform.system().lower(), platform.system().lower()
    )
    machine = platform.machine().lower()
    machine = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64"}.get(machine, machine)
    suffix = ".exe" if sys.platform == "win32" else ""
    return f"AutoEdit-{system}-{machine}{suffix}"


def _ensure_requirements(auto_install: bool) -> None:
    missing = []
    for module, package in (
        ("PyInstaller", "pyinstaller"),
        ("fastapi", "fastapi"),
        ("uvicorn", "uvicorn[standard]"),
        ("numpy", "numpy"),
        ("PIL", "pillow"),
        ("imageio_ffmpeg", "imageio-ffmpeg"),
    ):
        try:
            __import__(module)
        except ImportError:
            missing.append(package)

    if not missing:
        return
    if not auto_install:
        print(f"  ✗ Faltan dependencias: {', '.join(missing)}", file=sys.stderr)
        print(f"    Instálalas con:  {Path(sys.executable).name} -m pip install "
              f"{' '.join(missing)}", file=sys.stderr)
        raise SystemExit(1)

    print(f"  · Instalando {', '.join(missing)}…")
    subprocess.run([sys.executable, "-m", "pip", "install", *missing], check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Construye el ejecutable de AutoEdit")
    parser.add_argument("--no-install", action="store_true",
                        help="No instalar dependencias que falten, solo avisar")
    parser.add_argument("--keep-build", action="store_true",
                        help="No borrar la carpeta intermedia build/")
    args = parser.parse_args()

    print(f"\n  🎬  Construyendo AutoEdit para {platform.system()} {platform.machine()}\n")

    if not (ROOT / "web" / "index.html").exists():
        print("  ✗ No encuentro web/index.html. ¿Estás en la raíz del repositorio?",
              file=sys.stderr)
        return 1

    _ensure_requirements(auto_install=not args.no_install)

    subprocess.run(
        [sys.executable, "-m", "PyInstaller", str(SPEC), "--noconfirm", "--clean",
         "--distpath", str(DIST), "--workpath", str(BUILD)],
        check=True,
        cwd=ROOT,
    )

    produced = DIST / ("AutoEdit.exe" if sys.platform == "win32" else "AutoEdit")
    if not produced.exists():
        print(f"  ✗ PyInstaller no dejó nada en {produced}", file=sys.stderr)
        return 1

    final = DIST / _target_name()
    if final != produced:
        final.unlink(missing_ok=True)
        produced.rename(final)
    if sys.platform != "win32":
        final.chmod(0o755)

    if not args.keep_build:
        shutil.rmtree(BUILD, ignore_errors=True)

    size = final.stat().st_size / (1024 * 1024)
    print(f"\n  ✓ {final}  ({size:.0f} MB)\n")
    print("    Pruébalo con:")
    print(f"      {final} doctor")
    print(f"      {final}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
