"""Arranque desde la línea de comandos.

El objetivo de estos tests es la salida por consola, no el montaje: lo que se
imprime al arrancar lleva emojis y símbolos (`🎬`, `✓`, `✗`) que no existen en
las codificaciones regionales de Windows.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(*args: str, encoding: str | None = None) -> subprocess.CompletedProcess[bytes]:
    entorno = dict(os.environ)
    if encoding:
        entorno["PYTHONIOENCODING"] = encoding
    return subprocess.run(
        [sys.executable, "-m", "autoedit", *args],
        cwd=ROOT, env=entorno, capture_output=True, timeout=300,
    )


def test_doctor_no_revienta_con_una_codificacion_regional():
    """El caso de Windows: salida a una tubería, codificación cp1252.

    Python solo usa UTF-8 en la consola de Windows cuando está conectado a una
    de verdad. En cuanto la salida se redirige a un archivo o a una tubería
    —cualquier CI, o un `AutoEdit.exe doctor > log.txt`— pasa a la codificación
    de la región, y ahí `🎬` no se puede representar. Se reproduce en cualquier
    sistema forzando esa codificación.
    """
    resultado = _run("doctor", encoding="cp1252")
    salida = (resultado.stdout + resultado.stderr).decode("utf-8", "replace")

    assert "UnicodeEncodeError" not in salida, salida
    assert "Traceback" not in salida, salida
    # `doctor` devuelve 1 si no encuentra FFmpeg, y eso aquí da igual: lo que se
    # comprueba es que llegó a imprimir su diagnóstico sin romperse.
    assert resultado.returncode in (0, 1), salida
    assert "ffmpeg" in salida.lower(), salida


def test_la_ayuda_se_imprime():
    resultado = _run("--help")
    assert resultado.returncode == 0
    assert b"autoedit" in resultado.stdout.lower()
