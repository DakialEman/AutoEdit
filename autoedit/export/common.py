"""Aplanado de la línea de tiempo para los formatos de intercambio.

Internamente los clips **solapan** entre sí cuando hay una transición. Ningún
editor externo (CapCut, Premiere, Resolve) admite solapes dentro de una misma
pista, así que antes de exportar hay que aplanar.

La conversión recorta la cabecera del clip que llevaba transición justo por la
duración del solape. El corte pasa a ser seco, pero **la duración total y todos
los tiempos siguen siendo exactos**, que es lo que importa para no perder la
sincronía con la música.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..models import Asset, Project, TextClip, Timeline


@dataclass
class FlatClip:
    """Un clip sin solapes, listo para exportar."""

    asset: Asset
    timeline_start: float
    timeline_duration: float
    source_start: float
    source_duration: float
    speed: float = 1.0
    volume: float = 1.0
    effect: str = "none"
    grade: str = "none"
    mirror: bool = False
    rotation: float = 0.0
    # Transición que había en el montaje original (informativa: se pierde al aplanar).
    original_transition: str = "cut"
    original_transition_duration: float = 0.0

    @property
    def timeline_end(self) -> float:
        return self.timeline_start + self.timeline_duration


@dataclass
class FlatTimeline:
    width: int
    height: int
    fps: int
    duration: float
    video: list[FlatClip] = field(default_factory=list)
    audio: list[FlatClip] = field(default_factory=list)
    texts: list[TextClip] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def assets(self) -> list[Asset]:
        seen: dict[str, Asset] = {}
        for clip in self.video + self.audio:
            seen.setdefault(clip.asset.id, clip.asset)
        return list(seen.values())


def flatten(project: Project, timeline: Optional[Timeline] = None) -> FlatTimeline:
    timeline = timeline or project.timeline
    flat = FlatTimeline(
        width=timeline.width,
        height=timeline.height,
        fps=timeline.fps,
        duration=timeline.duration,
    )

    video_track = timeline.track("video")
    cursor = 0.0
    trimmed = 0
    if video_track and not video_track.hidden:
        clips = video_track.sorted_clips()
        for i, clip in enumerate(clips):
            asset = project.asset(clip.asset_id)
            if asset is None:
                continue
            overlap = clip.transition_in.duration if i > 0 else 0.0
            duration = round(clip.duration - overlap, 3)
            source_start = round(clip.in_point + overlap * clip.speed, 3)
            if duration <= 0.02:
                # La transición se comía el clip entero: lo dejamos al mínimo.
                duration = round(max(0.04, clip.duration), 3)
                source_start = clip.in_point
            if overlap > 0:
                trimmed += 1
            flat.video.append(
                FlatClip(
                    asset=asset,
                    timeline_start=round(cursor, 3),
                    timeline_duration=duration,
                    source_start=source_start,
                    source_duration=round(duration * clip.speed, 3),
                    speed=clip.speed,
                    volume=round(clip.volume * video_track.volume * timeline.original_audio_volume, 4),
                    effect=clip.effect,
                    grade=clip.grade,
                    mirror=clip.mirror,
                    rotation=clip.rotation,
                    original_transition=clip.transition_in.kind,
                    original_transition_duration=overlap,
                )
            )
            cursor = round(cursor + duration, 3)

    flat.duration = round(cursor, 3) or timeline.duration

    music_track = timeline.track("music")
    if music_track and not music_track.muted:
        for clip in music_track.sorted_clips():
            asset = project.asset(clip.asset_id)
            if asset is None:
                continue
            duration = round(min(clip.duration, flat.duration - clip.start), 3)
            if duration <= 0.02:
                continue
            flat.audio.append(
                FlatClip(
                    asset=asset,
                    timeline_start=round(clip.start, 3),
                    timeline_duration=duration,
                    source_start=round(clip.in_point, 3),
                    source_duration=round(duration * clip.speed, 3),
                    speed=clip.speed,
                    volume=round(clip.volume * music_track.volume * timeline.music_volume, 4),
                )
            )

    text_track = timeline.track("text")
    if text_track and not text_track.hidden:
        flat.texts = [t for t in text_track.sorted_texts() if t.text.strip()]

    if trimmed:
        flat.notes.append(
            f"{trimmed} transición(es) se han convertido en corte seco: los editores "
            "externos no admiten clips solapados. Los tiempos son exactos."
        )
    return flat


def missing_sources(flat: FlatTimeline) -> list[str]:
    return [a.path for a in flat.assets if not Path(a.path).exists()]


def to_microseconds(seconds: float) -> int:
    return int(round(max(0.0, seconds) * 1_000_000))


def to_frames(seconds: float, fps: int) -> int:
    return int(round(max(0.0, seconds) * fps))


def timecode(seconds: float, fps: int) -> str:
    """Timecode SMPTE no-drop `HH:MM:SS:FF`."""
    total = to_frames(seconds, fps)
    frames = total % fps
    total //= fps
    return f"{total // 3600:02d}:{(total // 60) % 60:02d}:{total % 60:02d}:{frames:02d}"
