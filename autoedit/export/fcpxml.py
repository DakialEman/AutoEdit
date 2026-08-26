"""Exportación a FCPXML: DaVinci Resolve, Premiere Pro y Final Cut Pro.

A diferencia del borrador de CapCut, FCPXML **sí** es un formato documentado y
estable, así que este es el camino recomendado cuando el destino es un editor
de escritorio. Se exporta la secuencia con sus cortes, recortes, velocidades y
la pista de música; los textos van como marcadores para no depender de efectos
propietarios de cada programa.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from xml.sax.saxutils import quoteattr

from ..models import Project, Timeline
from .common import FlatTimeline, flatten, to_frames


def _time(seconds: float, fps: int) -> str:
    """FCPXML exige tiempos racionales alineados al fotograma."""
    return f"{to_frames(seconds, fps)}/{fps}s"


def _uri(path: str) -> str:
    return Path(path).resolve().as_uri()


def build_fcpxml(flat: FlatTimeline, name: str) -> str:
    fps = flat.fps
    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!DOCTYPE fcpxml>",
        '<fcpxml version="1.9">',
        "  <resources>",
        f'    <format id="r0" name="AutoEditFormat" frameDuration="1/{fps}s" '
        f'width="{flat.width}" height="{flat.height}" colorSpace="1-1-1 (Rec. 709)"/>',
    ]

    # Un recurso por archivo, reutilizado por todos los clips que lo usan.
    resource_ids: dict[str, str] = {}
    for index, asset in enumerate(flat.assets, start=1):
        rid = f"r{index}"
        resource_ids[asset.id] = rid
        duration = asset.duration if asset.duration > 0 else 3600.0
        has_video = "1" if asset.kind in ("video", "image") else "0"
        has_audio = "1" if asset.has_audio or asset.kind == "audio" else "0"
        extra = ' format="r0"' if asset.kind in ("video", "image") else ""
        lines.append(
            f'    <asset id="{rid}" name={quoteattr(asset.name)} start="0s" '
            f'duration="{_time(duration, fps)}" hasVideo="{has_video}" '
            f'hasAudio="{has_audio}" audioSources="{1 if has_audio == "1" else 0}" '
            f'audioChannels="2"{extra}>'
        )
        lines.append(f'      <media-rep kind="original-media" src={quoteattr(_uri(asset.path))}/>')
        lines.append("    </asset>")

    lines += [
        "  </resources>",
        "  <library>",
        '    <event name="AutoEdit">',
        f"      <project name={quoteattr(name)}>",
        f'        <sequence format="r0" duration="{_time(flat.duration, fps)}" '
        'tcStart="0s" tcFormat="NDF" audioLayout="stereo" audioRate="48k">',
        "          <spine>",
    ]

    for clip in flat.video:
        rid = resource_ids.get(clip.asset.id)
        if not rid:
            continue
        attrs = [
            f'ref="{rid}"',
            f"name={quoteattr(clip.asset.name)}",
            f'offset="{_time(clip.timeline_start, fps)}"',
            f'duration="{_time(clip.timeline_duration, fps)}"',
        ]
        if clip.asset.kind != "image":
            attrs.append(f'start="{_time(clip.source_start, fps)}"')
        tag = "video" if clip.asset.kind == "image" else "asset-clip"
        lines.append(f"            <{tag} {' '.join(attrs)}>")
        if abs(clip.speed - 1.0) > 1e-3:
            source_end = clip.source_start + clip.source_duration
            lines.append(
                f'              <timeMap><timept time="0s" value="{_time(clip.source_start, fps)}"/>'
                f'<timept time="{_time(clip.timeline_duration, fps)}" '
                f'value="{_time(source_end, fps)}"/></timeMap>'
            )
        if clip.volume < 0.999:
            lines.append(f'              <adjust-volume amount="{_db(clip.volume)}dB"/>')
        lines.append(f"            </{tag}>")

    # La música va en un carril inferior (lane negativo) anclado al primer clip.
    for clip in flat.audio:
        rid = resource_ids.get(clip.asset.id)
        if not rid:
            continue
        lines.append(
            f'            <asset-clip ref="{rid}" lane="-1" name={quoteattr(clip.asset.name)} '
            f'offset="{_time(clip.timeline_start, fps)}" '
            f'duration="{_time(clip.timeline_duration, fps)}" '
            f'start="{_time(clip.source_start, fps)}" audioRole="music">'
        )
        if clip.volume < 0.999:
            lines.append(f'              <adjust-volume amount="{_db(clip.volume)}dB"/>')
        lines.append("            </asset-clip>")

    lines.append("          </spine>")
    for text in flat.texts:
        lines.append(
            f'          <marker start="{_time(text.start, fps)}" '
            f'duration="{_time(max(text.duration, 1.0 / fps), fps)}" '
            f"value={quoteattr(text.text)}/>"
        )
    lines += [
        "        </sequence>",
        "      </project>",
        "    </event>",
        "  </library>",
        "</fcpxml>",
    ]
    return "\n".join(lines) + "\n"


def _db(volume: float) -> str:
    import math

    if volume <= 0.0001:
        return "-96"
    return f"{20 * math.log10(volume):.1f}"


def export_fcpxml(project: Project, dest: Path, timeline: Optional[Timeline] = None) -> dict:
    flat = flatten(project, timeline)
    if not flat.video:
        raise ValueError("No hay nada que exportar: la línea de tiempo está vacía.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(build_fcpxml(flat, project.name), "utf-8")
    return {
        "path": str(dest),
        "clips": len(flat.video),
        "duration": flat.duration,
        "notes": list(flat.notes)
        + ["Los textos se exportan como marcadores; los efectos y el color no viajan en FCPXML."],
    }
