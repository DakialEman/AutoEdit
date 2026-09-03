#!/usr/bin/env python3
"""Comprueba que el ejecutable recién construido de verdad arranca.

Un binario que se genera sin errores puede fallar igualmente al ejecutarse, si
PyInstaller se dejó fuera algún módulo que solo se importa en tiempo de
ejecución. Esto lo caza antes de publicar nada:

    python packaging/smoke_test.py
"""

from __future__ import annotations

import platform
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def _utf8_console() -> None:
    """La consola de Windows no habla UTF-8 cuando la salida va a una tubería."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass

PORT = 8799


def _binary() -> Path:
    candidates = sorted((ROOT / "dist").glob("AutoEdit-*"))
    candidates = [c for c in candidates if c.is_file()]
    if not candidates:
        print("  ✗ No hay ningún ejecutable en dist/. Ejecuta antes packaging/build.py",
              file=sys.stderr)
        raise SystemExit(1)
    return candidates[0]


def _check_doctor(exe: Path) -> None:
    print("  · doctor…")
    result = subprocess.run([str(exe), "doctor"], capture_output=True, text=True, timeout=300)
    salida = result.stdout + result.stderr
    print("\n".join(f"      {line}" for line in salida.strip().splitlines()))
    if result.returncode != 0:
        raise SystemExit(f"  ✗ `doctor` devolvió {result.returncode}")
    if "ffmpeg" not in salida.lower():
        raise SystemExit("  ✗ `doctor` no encontró FFmpeg")


def _check_serve(exe: Path) -> None:
    print(f"  · servidor en el puerto {PORT}…")
    proceso = subprocess.Popen(
        [str(exe), "serve", "--port", str(PORT), "--no-browser"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        url = f"http://127.0.0.1:{PORT}/"
        limite = time.time() + 120
        cuerpo = ""
        while time.time() < limite:
            if proceso.poll() is not None:
                raise SystemExit(f"  ✗ El servidor se cerró solo:\n{proceso.communicate()[0]}")
            try:
                with urllib.request.urlopen(url, timeout=5) as respuesta:
                    cuerpo = respuesta.read().decode("utf-8", "replace")
                break
            except (urllib.error.URLError, OSError):
                time.sleep(1)
        else:
            raise SystemExit("  ✗ El servidor no respondió a tiempo")

        if "autoedit" not in cuerpo.lower():
            raise SystemExit(f"  ✗ La página no parece la interfaz:\n{cuerpo[:300]}")
        print(f"      interfaz servida ({len(cuerpo)} bytes)")

        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/styles", timeout=10) as r:
            estilos = r.read().decode("utf-8", "replace")
        if "presets" not in estilos:
            raise SystemExit(f"  ✗ La API no responde bien:\n{estilos[:300]}")
        print("      API viva")
    finally:
        proceso.terminate()
        try:
            proceso.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proceso.kill()


def main() -> int:
    _utf8_console()
    exe = _binary()
    print(f"\n  🎬  Probando {exe.name} en {platform.system()} {platform.machine()}\n")
    _check_doctor(exe)
    _check_serve(exe)
    print("\n  ✓ El ejecutable arranca, sirve la interfaz y responde a la API\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
