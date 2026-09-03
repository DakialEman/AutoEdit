"""Arranque de AutoEdit: `python -m autoedit` o el ejecutable empaquetado.

Levanta el servidor local y abre el navegador. También expone algunos
subcomandos para trabajar desde la terminal sin interfaz.
"""

from __future__ import annotations

import argparse
import multiprocessing
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .config import SETTINGS, find_ffmpeg, frozen

    if frozen():
        # El ejecutable no lleva código fuente que vigilar.
        args.reload = False

    SETTINGS.host, SETTINGS.port = args.host, args.port
    SETTINGS.ensure_dirs()

    try:
        ffmpeg = find_ffmpeg()
    except RuntimeError as exc:
        print(f"\n  ✗ {exc}\n", file=sys.stderr)
        return 1

    url = f"http://{args.host}:{args.port}"
    print(
        f"\n  🎬  AutoEdit\n"
        f"      Interfaz  {url}\n"
        f"      Proyectos {SETTINGS.home}\n"
        f"      FFmpeg    {ffmpeg}\n"
    )
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    # Con recarga hace falta la ruta de importación; sin ella, pasar el objeto
    # directamente evita que el ejecutable vuelva a importarse a sí mismo.
    target: Any = "autoedit.app:app"
    if not args.reload:
        from .app import app as asgi_app

        target = asgi_app

    uvicorn.run(
        target,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )
    return 0


def _cli_edit(args: argparse.Namespace) -> int:
    """Monta un vídeo de principio a fin sin abrir la interfaz."""
    from . import editing, storage
    from .ai import planner, prompt as prompt_ai
    from .config import SETTINGS
    from .render import render_timeline

    project = storage.create_project(args.name or Path(args.input).name)
    added, errors = storage.import_any(project, [args.input])
    for error in errors:
        print(f"  ! {error}")
    if not added:
        print("No se ha podido importar nada.", file=sys.stderr)
        return 1
    print(f"  · {len(added)} archivo(s) importados")

    def progress(fraction: float, message: str = "") -> None:
        print(f"\r  · {message:<44} {fraction * 100:5.1f}%", end="", flush=True)

    storage.analyze_pending(project, on_progress=progress)
    print()

    result = prompt_ai.interpret(args.prompt or "", args.style, args.engine)
    project.prompt = args.prompt or ""
    project.style = result.style
    project.timeline = planner.build_timeline(project, result.style)
    editing.normalize(project, project.timeline)
    storage.save_project(project)

    summary = planner.summarize(project.timeline)
    print(f"  · Montaje: {summary['clips']} clips, {summary['duration']:.1f}s, "
          f"{summary['resolution']}")
    if result.understood:
        for item in result.understood:
            print(f"      ✓ {item}")

    destination = Path(args.output).expanduser() if args.output else (
        SETTINGS.exports_dir(project.id) / "video.mp4"
    )
    render = render_timeline(project, destination, on_progress=progress)
    print(f"\n  ✓ {render.path}  ({render.duration:.1f}s)")

    if args.capcut:
        from .export import export_capcut

        report = export_capcut(project, destination.parent, install=args.install_capcut)
        print(f"  ✓ Proyecto de CapCut: {report['folder']}")
        if report.get("installed_to"):
            print(f"      instalado en {report['installed_to']}")
    return 0


def _cli_doctor(_args: argparse.Namespace) -> int:
    """Comprueba que el entorno está listo."""
    from .config import SETTINGS, find_ffmpeg, find_ffprobe
    from .ffmpeg import has_filter
    from .render import font_diagnostics

    print("\n  AutoEdit · diagnóstico\n")
    try:
        print(f"  ✓ ffmpeg    {find_ffmpeg()}")
    except RuntimeError as exc:
        print(f"  ✗ ffmpeg    {exc}")
        return 1
    probe = find_ffprobe()
    print(f"  {'✓' if probe else '·'} ffprobe   {probe or 'no encontrado (se usará ffmpeg -i)'}")

    for name in ("xfade", "zoompan", "overlay", "amix", "sidechaincompress"):
        print(f"  {'✓' if has_filter(name) else '·'} filtro    {name}")

    fonts = font_diagnostics()
    print(f"  {'✓' if fonts['count'] else '✗'} fuentes   {fonts['count']} disponibles "
          f"({fonts['default'] or 'ninguna'})")
    print(f"  · carpeta   {SETTINGS.home}")

    from .ai.llm import available_engines

    print(f"  · prompts   {', '.join(available_engines())}")
    print()
    return 0


def _utf8_console() -> None:
    """Evita que un acento o un emoji tumben el programa.

    Con la salida redirigida a un archivo o a una tubería, Python no usa UTF-8
    sino la codificación regional del sistema —cp1252 en un Windows español—,
    donde un simple `✓` no existe y levanta UnicodeEncodeError. `replace` deja
    además una salida legible en las consolas antiguas en vez de reventar.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass  # Salida sustituida por otra cosa: no hay nada que ajustar.


def main(argv: list[str] | None = None) -> int:
    # PyInstaller relanza el propio ejecutable para crear procesos hijo.
    multiprocessing.freeze_support()
    _utf8_console()

    parser = argparse.ArgumentParser(prog="autoedit", description="Editor de vídeo automático y local")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="Abre la interfaz (por defecto)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--no-browser", action="store_true")
    serve.add_argument("--reload", action="store_true")
    serve.add_argument("--log-level", default="warning")
    serve.set_defaults(func=_serve)

    edit = sub.add_parser("edit", help="Monta un vídeo desde la terminal")
    edit.add_argument("input", help="Archivo o carpeta con el material")
    edit.add_argument("-p", "--prompt", default="", help="Cómo quieres el montaje")
    edit.add_argument("-s", "--style", default=None, help="Estilo base (dynamic, cinematic…)")
    edit.add_argument("-o", "--output", default=None, help="Ruta del MP4 de salida")
    edit.add_argument("-n", "--name", default="", help="Nombre del proyecto")
    edit.add_argument("--engine", default="heuristic", choices=["heuristic", "auto", "anthropic", "ollama"])
    edit.add_argument("--capcut", action="store_true", help="Exporta también un borrador de CapCut")
    edit.add_argument("--install-capcut", action="store_true", help="Cópialo a la carpeta de CapCut")
    edit.set_defaults(func=_cli_edit)

    doctor = sub.add_parser("doctor", help="Comprueba el entorno")
    doctor.set_defaults(func=_cli_doctor)

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        args = parser.parse_args(["serve", *(argv or [])])

    code = args.func(args)

    # Si alguien abrió el ejecutable con doble clic y algo falló, la ventana se
    # cerraría de golpe sin que le diera tiempo a leer el error.
    if code and _double_clicked():
        try:
            input("\n  Pulsa Intro para cerrar…")
        except (EOFError, KeyboardInterrupt):
            pass
    return code


def _double_clicked() -> bool:
    from .config import frozen

    return frozen() and len(sys.argv) == 1


if __name__ == "__main__":
    raise SystemExit(main())
