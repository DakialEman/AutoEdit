"""Modelo de datos de AutoEdit.

Todo el estado de un proyecto vive en un único documento JSON (`Project`).
El motor de auto-edición produce un `Timeline`; el usuario lo modifica desde la
UI; el renderer y los exportadores consumen ese mismo `Timeline`.  Mantener una
sola representación es lo que permite que "auto-editar", "editar a mano" y
"exportar a CapCut" hablen el mismo idioma.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------
# Tipos base
# --------------------------------------------------------------------------

AssetKind = Literal["video", "image", "audio"]
TrackKind = Literal["video", "overlay", "text", "music", "voice", "sfx"]
FitMode = Literal["cover", "contain", "blur_pad"]
ClipOrder = Literal["chronological", "by_score", "energy_ramp", "shuffle", "as_imported"]

TRANSITIONS = [
    "cut",
    "fade",
    "fadeblack",
    "fadewhite",
    "dissolve",
    "slideleft",
    "slideright",
    "slideup",
    "slidedown",
    "wipeleft",
    "wiperight",
    "circleopen",
    "circleclose",
    "radial",
    "pixelize",
    "zoomin",
    "smoothleft",
    "smoothright",
    "hblur",
]

EFFECTS = [
    "none",
    "kenburns_in",
    "kenburns_out",
    "kenburns_left",
    "kenburns_right",
    "zoom_punch",
    "shake",
    "flash",
    "slow_drift",
]

GRADES = [
    "none",
    "cinematic",
    "teal_orange",
    "warm",
    "cold",
    "vintage",
    "vivid",
    "bw",
    "faded",
    "night",
]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# --------------------------------------------------------------------------
# Assets
# --------------------------------------------------------------------------


class Highlight(BaseModel):
    """Un tramo interesante dentro de un vídeo, con su puntuación."""

    start: float
    end: float
    score: float = 0.0
    reason: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


class AssetAnalysis(BaseModel):
    """Resultado del análisis automático de un asset."""

    analyzed: bool = False
    scenes: list[float] = Field(default_factory=list)
    highlights: list[Highlight] = Field(default_factory=list)
    beats: list[float] = Field(default_factory=list)
    downbeats: list[float] = Field(default_factory=list)
    tempo: float = 0.0
    energy_curve: list[float] = Field(default_factory=list)
    brightness: float = 0.0
    motion: float = 0.0
    quality_score: float = 0.5
    error: str = ""


class Asset(BaseModel):
    id: str = Field(default_factory=lambda: new_id("as"))
    kind: AssetKind
    path: str
    name: str
    size: int = 0
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    has_audio: bool = False
    has_video: bool = False
    codec: str = ""
    created_at: float = Field(default_factory=time.time)
    source_mtime: float = 0.0
    thumbnail: Optional[str] = None
    waveform: list[float] = Field(default_factory=list)
    analysis: AssetAnalysis = Field(default_factory=AssetAnalysis)
    tags: list[str] = Field(default_factory=list)
    # El usuario puede excluir un asset del auto-montaje sin borrarlo.
    enabled: bool = True

    @property
    def aspect(self) -> float:
        if self.height:
            return self.width / self.height
        return 16 / 9


# --------------------------------------------------------------------------
# Timeline
# --------------------------------------------------------------------------


class Transition(BaseModel):
    kind: str = "cut"
    duration: float = 0.0


class TextStyle(BaseModel):
    font: str = ""            # ruta a .ttf; vacío = fuente por defecto
    size: int = 64            # relativo a un canvas de 1080 de alto
    color: str = "#FFFFFF"
    stroke_color: str = "#000000"
    stroke: int = 0
    box: bool = False
    box_color: str = "#000000AA"
    align: Literal["left", "center", "right"] = "center"
    # Posición normalizada 0..1 sobre el canvas.
    x: float = 0.5
    y: float = 0.85
    animation: Literal["none", "fade", "pop", "slide_up", "typewriter"] = "fade"
    uppercase: bool = False
    shadow: bool = True


class Clip(BaseModel):
    """Un fragmento visual o de audio colocado en la línea de tiempo."""

    id: str = Field(default_factory=lambda: new_id("cl"))
    asset_id: str
    start: float = 0.0          # posición en la timeline (s)
    duration: float = 1.0       # duración en la timeline (s)
    in_point: float = 0.0       # punto de entrada en el material original (s)
    speed: float = 1.0
    volume: float = 1.0
    opacity: float = 1.0
    fit: FitMode = "cover"
    effect: str = "none"
    effect_amount: float = 1.0
    grade: str = "none"
    transition_in: Transition = Field(default_factory=Transition)
    reverse: bool = False
    mirror: bool = False
    rotation: float = 0.0
    # Recorte manual del encuadre, en fracciones del frame original.
    crop: Optional[dict[str, float]] = None
    locked: bool = False
    note: str = ""

    @property
    def end(self) -> float:
        return self.start + self.duration

    @property
    def source_out(self) -> float:
        return self.in_point + self.duration * self.speed


class TextClip(BaseModel):
    id: str = Field(default_factory=lambda: new_id("tx"))
    text: str = ""
    start: float = 0.0
    duration: float = 2.0
    style: TextStyle = Field(default_factory=TextStyle)
    locked: bool = False

    @property
    def end(self) -> float:
        return self.start + self.duration


class Track(BaseModel):
    id: str = Field(default_factory=lambda: new_id("tk"))
    kind: TrackKind = "video"
    name: str = ""
    clips: list[Clip] = Field(default_factory=list)
    texts: list[TextClip] = Field(default_factory=list)
    muted: bool = False
    hidden: bool = False
    volume: float = 1.0

    def sorted_clips(self) -> list[Clip]:
        return sorted(self.clips, key=lambda c: c.start)

    def sorted_texts(self) -> list[TextClip]:
        return sorted(self.texts, key=lambda t: t.start)

    @property
    def duration(self) -> float:
        ends = [c.end for c in self.clips] + [t.end for t in self.texts]
        return max(ends) if ends else 0.0


class Timeline(BaseModel):
    width: int = 1080
    height: int = 1920
    fps: int = 30
    tracks: list[Track] = Field(default_factory=list)
    music_volume: float = 0.65
    original_audio_volume: float = 1.0
    duck_music: bool = True
    fade_out: float = 0.6
    fade_in: float = 0.3

    # -- utilidades -------------------------------------------------------

    def track(self, kind: TrackKind) -> Optional[Track]:
        for t in self.tracks:
            if t.kind == kind:
                return t
        return None

    def ensure_track(self, kind: TrackKind, name: str = "") -> Track:
        t = self.track(kind)
        if t is None:
            t = Track(kind=kind, name=name or kind)
            self.tracks.append(t)
        return t

    def find_clip(self, clip_id: str) -> tuple[Optional[Track], Optional[Clip]]:
        for t in self.tracks:
            for c in t.clips:
                if c.id == clip_id:
                    return t, c
        return None, None

    def find_text(self, text_id: str) -> tuple[Optional[Track], Optional[TextClip]]:
        for t in self.tracks:
            for tx in t.texts:
                if tx.id == text_id:
                    return t, tx
        return None, None

    @property
    def duration(self) -> float:
        """Duración total, ignorando la música (que se recorta al vídeo)."""
        ends: list[float] = []
        for t in self.tracks:
            if t.kind in ("music",):
                continue
            ends.extend(c.end for c in t.clips)
            ends.extend(tx.end for tx in t.texts)
        return round(max(ends), 3) if ends else 0.0

    @property
    def aspect_label(self) -> str:
        return aspect_label(self.width, self.height)


# --------------------------------------------------------------------------
# Estilo / prompt
# --------------------------------------------------------------------------


class TextPlan(BaseModel):
    intro_title: bool = False
    intro_text: str = ""
    outro_text: str = ""
    captions: bool = False
    style: TextStyle = Field(default_factory=TextStyle)


class StyleSpec(BaseModel):
    """Descripción declarativa de *cómo* debe montarse el vídeo.

    Es el punto de encuentro entre los presets, el prompt del usuario y el
    planificador. Todo lo que el auto-editor decide sale de aquí.
    """

    id: str = "custom"
    name: str = "Personalizado"
    description: str = ""
    emoji: str = "🎬"

    aspect: str = "9:16"
    fps: int = 30

    # Ritmo
    min_clip: float = 1.2
    max_clip: float = 4.0
    target_clip: float = 2.2
    beat_sync: bool = True
    beat_division: int = 2          # cortar cada N pulsos
    energy_ramp: bool = False       # acelerar hacia el final

    # Aspecto visual
    transitions: list[str] = Field(default_factory=lambda: ["cut"])
    transition_chance: float = 0.0
    transition_duration: float = 0.4
    effects: list[str] = Field(default_factory=lambda: ["none"])
    effect_chance: float = 0.0
    image_effects: list[str] = Field(default_factory=lambda: ["kenburns_in"])
    grade: str = "none"
    fit: FitMode = "cover"

    # Audio
    music_volume: float = 0.7
    original_audio_volume: float = 0.0
    duck_music: bool = True

    # Estructura
    order: ClipOrder = "by_score"
    target_duration: Optional[float] = None   # None = usar todo el material
    max_duration: Optional[float] = None
    use_highlights: bool = True
    text: TextPlan = Field(default_factory=TextPlan)

    seed: int = 0


class PromptResult(BaseModel):
    """Lo que devuelve el intérprete de prompts."""

    style: StyleSpec
    base_preset: str = "dynamic"
    understood: list[str] = Field(default_factory=list)
    ignored: list[str] = Field(default_factory=list)
    engine: str = "heuristic"


# --------------------------------------------------------------------------
# Proyecto
# --------------------------------------------------------------------------


class ExportRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ex"))
    kind: str = "mp4"
    path: str = ""
    created_at: float = Field(default_factory=time.time)
    size: int = 0
    note: str = ""


class Project(BaseModel):
    id: str = Field(default_factory=lambda: new_id("pr"))
    name: str = "Proyecto sin título"
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    version: int = 1
    prompt: str = ""
    style: StyleSpec = Field(default_factory=StyleSpec)
    assets: list[Asset] = Field(default_factory=list)
    timeline: Timeline = Field(default_factory=Timeline)
    exports: list[ExportRecord] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)

    def asset(self, asset_id: str) -> Optional[Asset]:
        for a in self.assets:
            if a.id == asset_id:
                return a
        return None

    def assets_of(self, kind: AssetKind) -> list[Asset]:
        return [a for a in self.assets if a.kind == kind]

    def touch(self) -> None:
        self.updated_at = time.time()
        self.version += 1


# --------------------------------------------------------------------------
# Helpers de relación de aspecto
# --------------------------------------------------------------------------

ASPECT_PRESETS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
    "4:3": (1440, 1080),
    "21:9": (2560, 1080),
}


def resolution_for(aspect: str, height_hint: int = 0) -> tuple[int, int]:
    w, h = ASPECT_PRESETS.get(aspect, ASPECT_PRESETS["9:16"])
    if height_hint and height_hint != h:
        scale = height_hint / h
        w, h = int(round(w * scale / 2) * 2), int(round(h * scale / 2) * 2)
    return w, h


def aspect_label(width: int, height: int) -> str:
    if not width or not height:
        return "9:16"
    ratio = width / height
    best, best_diff = "9:16", 1e9
    for label, (w, h) in ASPECT_PRESETS.items():
        diff = abs(ratio - w / h)
        if diff < best_diff:
            best, best_diff = label, diff
    return best
