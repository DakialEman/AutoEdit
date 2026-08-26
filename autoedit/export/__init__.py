"""Exportadores: CapCut, FCPXML, EDL y proyecto nativo."""

from .capcut import export_capcut, export_capcut_zip, find_capcut_drafts_dir
from .common import flatten
from .edl import build_shotlist, export_edl, export_project_json, import_project_json
from .fcpxml import export_fcpxml

FORMATS = [
    {
        "id": "mp4",
        "name": "Vídeo MP4",
        "emoji": "🎬",
        "description": "El vídeo final, listo para subir.",
        "editable": False,
    },
    {
        "id": "capcut",
        "name": "Proyecto de CapCut",
        "emoji": "✂️",
        "description": "Borrador editable que se abre en CapCut. Formato no oficial.",
        "editable": True,
    },
    {
        "id": "fcpxml",
        "name": "FCPXML",
        "emoji": "🎞️",
        "description": "Para DaVinci Resolve, Premiere Pro y Final Cut Pro.",
        "editable": True,
    },
    {
        "id": "edl",
        "name": "EDL (CMX 3600)",
        "emoji": "📄",
        "description": "Lista de cortes universal. Solo tiempos.",
        "editable": True,
    },
    {
        "id": "project",
        "name": "Proyecto AutoEdit",
        "emoji": "💾",
        "description": "Copia completa del proyecto, con efectos y análisis.",
        "editable": True,
    },
    {
        "id": "shotlist",
        "name": "Escaleta",
        "emoji": "📋",
        "description": "Resumen legible del montaje en Markdown.",
        "editable": False,
    },
]

__all__ = [
    "FORMATS",
    "build_shotlist",
    "export_capcut",
    "export_capcut_zip",
    "export_edl",
    "export_fcpxml",
    "export_project_json",
    "find_capcut_drafts_dir",
    "flatten",
    "import_project_json",
]
