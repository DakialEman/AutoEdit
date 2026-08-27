"""Operaciones de edición manual sobre la línea de tiempo.

El auto-editor propone; aquí el usuario dispone. Todas las funciones trabajan
sobre el mismo `Timeline` que produce el planificador, así que cualquier cambio
manual se refleja igual en el render y en la exportación a CapCut.

Regla invariante: tras cualquier operación se llama a `relayout()`, que recoloca
los clips en cadena respetando el solape de cada transición.
"""

from __future__ import annotations

import math
from typing import Optional

from .models import (
    Clip,
    Project,
    TextClip,
    TextStyle,
    Timeline,
    Track,
    Transition,
    new_id,
)

MIN_CLIP = 0.1


class EditError(ValueError):
    """Error de una operación de edición, con mensaje apto para la interfaz."""


# --------------------------------------------------------------------------
# Recolocación
# --------------------------------------------------------------------------


def relayout(track: Track) -> None:
    """Recoloca los clips en cadena, respetando el solape de las transiciones.

    El orden **de la lista** es el que manda, no el campo `start`: cuando el
    usuario acaba de mover un clip, sus tiempos todavía son los de antes y
    reordenar por ellos desharía el movimiento. Al salir de aquí los `start`
    vuelven a ser crecientes.
    """
    clips = track.clips
    cursor = 0.0
    for i, clip in enumerate(clips):
        if i == 0:
            clip.transition_in = Transition(kind="cut", duration=0.0)
            overlap = 0.0
        else:
            overlap = clip.transition_in.duration
            # Una transición no puede comerse más de un tercio de sus dos clips.
            limit = _floor3(min(clips[i - 1].duration, clip.duration) / 3.0)
            if overlap > limit:
                overlap = max(0.0, limit)
                if overlap <= 0.02:
                    clip.transition_in = Transition(kind="cut", duration=0.0)
                    overlap = 0.0
                else:
                    clip.transition_in.duration = overlap
        clip.start = round(max(0.0, cursor - overlap), 3)
        cursor = round(clip.start + clip.duration, 3)


def _floor3(value: float) -> float:
    """Redondea hacia abajo a milisegundos: un límite nunca debe superarse."""
    return math.floor(value * 1000) / 1000


def sync_music(project: Project, timeline: Timeline) -> None:
    """Ajusta la pista de música a la duración actual del vídeo."""
    music_track = timeline.track("music")
    if not music_track or not music_track.clips:
        return
    total = timeline.duration
    for clip in music_track.clips:
        asset = project.asset(clip.asset_id)
        available = max(0.0, (asset.duration - clip.in_point)) if asset else total
        clip.start = 0.0
        clip.duration = round(min(total, available) if available else total, 3)


def normalize(project: Project, timeline: Timeline) -> None:
    video = timeline.track("video")
    if video:
        relayout(video)
    sync_music(project, timeline)


# --------------------------------------------------------------------------
# Clips de vídeo
# --------------------------------------------------------------------------


def _video_track(timeline: Timeline) -> Track:
    track = timeline.track("video")
    if track is None:
        raise EditError("El proyecto todavía no tiene pista de vídeo.")
    return track


def _require_clip(timeline: Timeline, clip_id: str) -> tuple[Track, Clip]:
    track, clip = timeline.find_clip(clip_id)
    if track is None or clip is None:
        raise EditError("Ese clip ya no existe.")
    return track, clip


def move_clip(project: Project, timeline: Timeline, clip_id: str, new_index: int) -> Clip:
    track = _video_track(timeline)
    clips = track.clips
    match = next((c for c in clips if c.id == clip_id), None)
    if match is None:
        raise EditError("Ese clip ya no existe.")
    clips.remove(match)
    new_index = max(0, min(new_index, len(clips)))
    clips.insert(new_index, match)
    track.clips = clips
    normalize(project, timeline)
    return match


def set_duration(project: Project, timeline: Timeline, clip_id: str, duration: float) -> Clip:
    track, clip = _require_clip(timeline, clip_id)
    if clip.locked:
        raise EditError("El clip está bloqueado.")
    duration = max(MIN_CLIP, round(float(duration), 3))
    asset = project.asset(clip.asset_id)
    if asset and asset.kind == "video" and asset.duration > 0:
        # No podemos pedir más material del que hay a partir del punto de entrada.
        available = (asset.duration - clip.in_point) / max(clip.speed, 0.01)
        duration = min(duration, round(max(MIN_CLIP, available), 3))
    clip.duration = duration
    normalize(project, timeline)
    return clip


def set_in_point(project: Project, timeline: Timeline, clip_id: str, in_point: float) -> Clip:
    track, clip = _require_clip(timeline, clip_id)
    asset = project.asset(clip.asset_id)
    in_point = max(0.0, round(float(in_point), 3))
    if asset and asset.kind == "video" and asset.duration > 0:
        max_in = max(0.0, asset.duration - clip.duration * clip.speed)
        in_point = min(in_point, round(max_in, 3))
    clip.in_point = in_point
    normalize(project, timeline)
    return clip


def split_clip(project: Project, timeline: Timeline, clip_id: str, at: float) -> tuple[Clip, Clip]:
    """Parte un clip en dos por un instante absoluto de la línea de tiempo."""
    track, clip = _require_clip(timeline, clip_id)
    offset = round(float(at) - clip.start, 3)
    if offset <= MIN_CLIP or offset >= clip.duration - MIN_CLIP:
        raise EditError("El punto de corte queda demasiado cerca del borde del clip.")

    second = clip.model_copy(deep=True)
    second.id = new_id("cl")
    second.in_point = round(clip.in_point + offset * clip.speed, 3)
    second.duration = round(clip.duration - offset, 3)
    second.transition_in = Transition(kind="cut", duration=0.0)
    clip.duration = round(offset, 3)

    track.clips.insert(track.clips.index(clip) + 1, second)
    normalize(project, timeline)
    return clip, second


def delete_clip(project: Project, timeline: Timeline, clip_id: str) -> None:
    track, clip = _require_clip(timeline, clip_id)
    if clip.locked:
        raise EditError("El clip está bloqueado.")
    track.clips = [c for c in track.clips if c.id != clip_id]
    normalize(project, timeline)


def duplicate_clip(project: Project, timeline: Timeline, clip_id: str) -> Clip:
    track, clip = _require_clip(timeline, clip_id)
    copy = clip.model_copy(deep=True)
    copy.id = new_id("cl")
    track.clips.insert(track.clips.index(clip) + 1, copy)
    normalize(project, timeline)
    return copy


def add_clip(
    project: Project,
    timeline: Timeline,
    asset_id: str,
    index: Optional[int] = None,
    duration: Optional[float] = None,
) -> Clip:
    asset = project.asset(asset_id)
    if asset is None:
        raise EditError("Ese archivo no está en el proyecto.")
    if asset.kind == "audio":
        raise EditError("Los audios van en la pista de música, no en la de vídeo.")

    track = timeline.ensure_track("video", "Vídeo")
    default = duration or project.style.target_clip or 2.0
    if asset.kind == "video" and asset.duration > 0:
        default = min(default, asset.duration)
    clip = Clip(
        asset_id=asset_id,
        duration=round(max(MIN_CLIP, default), 3),
        fit=project.style.fit,
        grade=project.style.grade,
        volume=project.style.original_audio_volume if asset.has_audio else 0.0,
        effect=project.style.image_effects[0] if asset.kind == "image" and project.style.image_effects else "none",
    )
    position = len(track.clips) if index is None else max(0, min(index, len(track.clips)))
    track.clips.insert(position, clip)
    normalize(project, timeline)
    return clip


def update_clip(project: Project, timeline: Timeline, clip_id: str, changes: dict) -> Clip:
    """Aplica cambios sueltos (efecto, color, volumen, transición…)."""
    track, clip = _require_clip(timeline, clip_id)
    simple = {
        "speed", "volume", "opacity", "fit", "effect", "effect_amount", "grade",
        "reverse", "mirror", "rotation", "locked", "note", "crop",
    }
    for key, value in changes.items():
        if key in simple:
            setattr(clip, key, value)
        elif key == "transition":
            kind = (value or {}).get("kind", "cut")
            seconds = float((value or {}).get("duration", 0.4) or 0.0)
            clip.transition_in = Transition(
                kind=kind, duration=0.0 if kind == "cut" else round(max(0.05, seconds), 3)
            )
        elif key == "duration":
            set_duration(project, timeline, clip_id, float(value))
        elif key == "in_point":
            set_in_point(project, timeline, clip_id, float(value))
    if clip.speed <= 0.05:
        clip.speed = 0.05
    normalize(project, timeline)
    return clip


def apply_to_all(project: Project, timeline: Timeline, changes: dict) -> int:
    """Aplica un cambio a todos los clips de vídeo (p. ej. cambiar el color)."""
    track = _video_track(timeline)
    count = 0
    for clip in list(track.clips):
        if clip.locked:
            continue
        update_clip(project, timeline, clip.id, changes)
        count += 1
    return count


# --------------------------------------------------------------------------
# Textos
# --------------------------------------------------------------------------


def add_text(
    timeline: Timeline, text: str, start: float, duration: float, style: Optional[dict] = None
) -> TextClip:
    track = timeline.ensure_track("text", "Texto")
    clip = TextClip(
        text=text,
        start=round(max(0.0, start), 3),
        duration=round(max(0.3, duration), 3),
        style=TextStyle(**style) if style else TextStyle(),
    )
    track.texts.append(clip)
    return clip


def update_text(timeline: Timeline, text_id: str, changes: dict) -> TextClip:
    track, clip = timeline.find_text(text_id)
    if track is None or clip is None:
        raise EditError("Ese texto ya no existe.")
    if "text" in changes:
        clip.text = str(changes["text"])
    if "start" in changes:
        clip.start = round(max(0.0, float(changes["start"])), 3)
    if "duration" in changes:
        clip.duration = round(max(0.3, float(changes["duration"])), 3)
    if "style" in changes and isinstance(changes["style"], dict):
        merged = clip.style.model_dump()
        merged.update(changes["style"])
        clip.style = TextStyle(**merged)
    return clip


def delete_text(timeline: Timeline, text_id: str) -> None:
    track, clip = timeline.find_text(text_id)
    if track is None or clip is None:
        raise EditError("Ese texto ya no existe.")
    track.texts = [t for t in track.texts if t.id != text_id]


# --------------------------------------------------------------------------
# Música
# --------------------------------------------------------------------------


def set_music(project: Project, timeline: Timeline, asset_id: Optional[str]) -> None:
    track = timeline.ensure_track("music", "Música")
    track.clips = []
    if not asset_id:
        project.meta.pop("music_asset_id", None)
        return
    asset = project.asset(asset_id)
    if asset is None or asset.kind != "audio":
        raise EditError("Ese archivo no es una pista de audio del proyecto.")
    project.meta["music_asset_id"] = asset_id
    track.clips.append(
        Clip(
            asset_id=asset_id,
            start=0.0,
            duration=round(min(timeline.duration or asset.duration, asset.duration), 3),
            volume=1.0,
        )
    )
    sync_music(project, timeline)


def set_track_flag(timeline: Timeline, kind: str, muted: Optional[bool], hidden: Optional[bool]) -> Track:
    track = timeline.track(kind)  # type: ignore[arg-type]
    if track is None:
        raise EditError("Esa pista no existe.")
    if muted is not None:
        track.muted = bool(muted)
    if hidden is not None:
        track.hidden = bool(hidden)
    return track


# --------------------------------------------------------------------------
# Validación
# --------------------------------------------------------------------------


def validate(project: Project, timeline: Timeline) -> list[str]:
    """Comprueba lo que impediría renderizar y lo explica en cristiano."""
    problems: list[str] = []
    video = timeline.track("video")
    if not video or not video.clips:
        problems.append("No hay ningún clip en la pista de vídeo.")
        return problems

    from pathlib import Path

    missing: set[str] = set()
    for track in timeline.tracks:
        for clip in track.clips:
            asset = project.asset(clip.asset_id)
            if asset is None:
                problems.append("Un clip apunta a un archivo que ya no está en el proyecto.")
                continue
            if asset.path not in missing and not Path(asset.path).exists():
                missing.add(asset.path)
                problems.append(f"No se encuentra el archivo «{asset.name}».")
            if clip.duration < MIN_CLIP:
                problems.append(f"El clip de «{asset.name}» es demasiado corto.")
            if track.kind in ("video", "overlay") and asset.kind == "audio":
                problems.append(
                    f"«{asset.name}» no tiene imagen (es solo audio) y está en la pista "
                    "de vídeo. Quítalo del proyecto y vuelve a añadirlo: se colocará "
                    "como música."
                )
    if timeline.duration <= 0:
        problems.append("La duración total es cero.")
    return problems
