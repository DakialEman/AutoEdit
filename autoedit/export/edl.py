"""Exportación a EDL (CMX 3600) y a la lista de decisiones nativa.

El EDL es el mínimo común denominador: lo lee prácticamente cualquier sistema de
edición, aunque solo transporta cortes y tiempos. El JSON nativo, en cambio,
lleva absolutamente todo (efectos, color, textos, análisis) y sirve para
archivar el proyecto o moverlo a otro equipo con AutoEdit.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ..models import Project, Timeline
from .common import flatten, timecode


def build_edl(project: Project, timeline: Optional[Timeline] = None) -> str:
    flat = flatten(project, timeline)
    fps = flat.fps
    title = project.name.upper()[:70] or "AUTOEDIT"
    lines = [f"TITLE: {title}", "FCM: NON-DROP FRAME", ""]

    for index, clip in enumerate(flat.video, start=1):
        source_in = timecode(clip.source_start, fps)
        source_out = timecode(clip.source_start + clip.source_duration, fps)
        record_in = timecode(clip.timeline_start, fps)
        record_out = timecode(clip.timeline_end, fps)
        lines.append(
            f"{index:03d}  AX       V     C        "
            f"{source_in} {source_out} {record_in} {record_out}"
        )
        lines.append(f"* FROM CLIP NAME: {clip.asset.name}")
        if abs(clip.speed - 1.0) > 1e-3:
            lines.append(f"* MOTION EFFECT AT {round(clip.speed * 100)}%")
        if clip.original_transition != "cut":
            lines.append(
                f"* TRANSITION IN AUTOEDIT: {clip.original_transition} "
                f"({clip.original_transition_duration:.2f}s)"
            )
        lines.append("")

    for index, clip in enumerate(flat.audio, start=len(flat.video) + 1):
        source_in = timecode(clip.source_start, fps)
        source_out = timecode(clip.source_start + clip.source_duration, fps)
        record_in = timecode(clip.timeline_start, fps)
        record_out = timecode(clip.timeline_end, fps)
        lines.append(
            f"{index:03d}  AX       A     C        "
            f"{source_in} {source_out} {record_in} {record_out}"
        )
        lines.append(f"* FROM CLIP NAME: {clip.asset.name}")
        lines.append("")
    return "\n".join(lines)


def export_edl(project: Project, dest: Path, timeline: Optional[Timeline] = None) -> dict:
    flat = flatten(project, timeline)
    if not flat.video:
        raise ValueError("No hay nada que exportar: la línea de tiempo está vacía.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(build_edl(project, timeline), "utf-8")
    return {
        "path": str(dest),
        "clips": len(flat.video),
        "duration": flat.duration,
        "notes": list(flat.notes) + ["El EDL solo transporta cortes y tiempos."],
    }


def export_project_json(project: Project, dest: Path) -> dict:
    """Guarda el proyecto completo, para archivarlo o abrirlo en otro equipo."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(project.model_dump_json(indent=2), "utf-8")
    return {
        "path": str(dest),
        "assets": len(project.assets),
        "duration": project.timeline.duration,
        "notes": [
            "Este archivo lleva el proyecto entero. Los medios se referencian por "
            "ruta: cópialos también si te llevas el proyecto a otro equipo."
        ],
    }


def import_project_json(data: str | bytes) -> Project:
    payload = json.loads(data)
    project = Project.model_validate(payload)
    # Al importar generamos un id nuevo para no pisar un proyecto existente.
    project.id = Project().id
    return project


def build_shotlist(project: Project, timeline: Optional[Timeline] = None) -> str:
    """Escaleta legible: útil para revisar el montaje antes de renderizar."""
    flat = flatten(project, timeline)
    rows = [
        f"# {project.name}",
        "",
        f"Duración: {flat.duration:.2f}s · {len(flat.video)} clips · "
        f"{flat.width}x{flat.height} @ {flat.fps}fps",
        "",
        "| # | Inicio | Dur. | Archivo | Desde | Efecto | Transición |",
        "|---|--------|------|---------|-------|--------|------------|",
    ]
    for i, clip in enumerate(flat.video, start=1):
        rows.append(
            f"| {i} | {clip.timeline_start:.2f}s | {clip.timeline_duration:.2f}s | "
            f"{clip.asset.name} | {clip.source_start:.2f}s | {clip.effect} | "
            f"{clip.original_transition} |"
        )
    if flat.texts:
        rows += ["", "## Textos", ""]
        for text in flat.texts:
            rows.append(f"- **{text.start:.2f}s** ({text.duration:.2f}s): {text.text}")
    if flat.audio:
        rows += ["", "## Audio", ""]
        for clip in flat.audio:
            rows.append(
                f"- {clip.asset.name} desde {clip.source_start:.2f}s, "
                f"volumen {clip.volume:.2f}"
            )
    return "\n".join(rows) + "\n"
