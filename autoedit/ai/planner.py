"""Planificador: convierte material + estilo en una línea de tiempo.

Este es el auto-editor propiamente dicho. Decide cuántos cortes hay, dónde
caen, qué trozo de cada clip se usa y con qué efecto y transición.

Convenio importante sobre transiciones: un clip con `transition_in.duration = d`
**solapa** `d` segundos con el clip anterior (su `start` es `anterior.end - d`).
Así la duración del modelo coincide exactamente con la del vídeo renderizado y
los textos nunca se desincronizan.
"""

from __future__ import annotations

import math
import random
from typing import Optional

from ..analysis.media import best_segment
from ..models import (
    Asset,
    Clip,
    Project,
    StyleSpec,
    TextClip,
    Timeline,
    Track,
    Transition,
    resolution_for,
)

MIN_SEGMENT = 0.25


# --------------------------------------------------------------------------
# Selección de material
# --------------------------------------------------------------------------


def pick_music(project: Project) -> Optional[Asset]:
    """La pista musical: la marcada por el usuario o la más larga disponible."""
    audios = [a for a in project.assets_of("audio") if a.enabled]
    if not audios:
        return None
    preferred = project.meta.get("music_asset_id")
    for a in audios:
        if a.id == preferred:
            return a
    return max(audios, key=lambda a: a.duration)


def visual_assets(project: Project) -> list[Asset]:
    return [a for a in project.assets if a.enabled and a.kind in ("video", "image")]


def order_assets(assets: list[Asset], style: StyleSpec, rng: random.Random) -> list[Asset]:
    if style.order == "shuffle":
        out = list(assets)
        rng.shuffle(out)
        return out
    if style.order == "by_score":
        return sorted(assets, key=lambda a: (-a.analysis.quality_score, a.created_at))
    if style.order == "energy_ramp":
        # Lo más tranquilo primero, lo más movido al final.
        return sorted(assets, key=lambda a: (a.analysis.motion, a.analysis.quality_score))
    if style.order == "as_imported":
        return list(assets)
    return sorted(assets, key=lambda a: (a.source_mtime or a.created_at, a.name))


def slots_for(asset: Asset, style: StyleSpec) -> int:
    """Cuántas apariciones distintas admite un asset sin repetirse."""
    if asset.kind == "image":
        return 1
    unit = max(style.target_clip * 1.4, style.min_clip * 2)
    if unit <= 0:
        return 1
    return max(1, min(8, int(asset.duration // unit)))


# --------------------------------------------------------------------------
# Ritmo: duraciones de cada corte
# --------------------------------------------------------------------------


def _division_schedule(style: StyleSpec, progress: float) -> int:
    """Divisor de pulsos según lo avanzado que vaya el montaje."""
    base = max(1, style.beat_division)
    if not style.energy_ramp:
        return base
    if progress < 0.25:
        return min(16, base * 2)
    if progress > 0.7:
        return max(1, base // 2)
    return base


def beat_durations(
    beats: list[float],
    downbeats: list[float],
    style: StyleSpec,
    total: float,
    music_offset: float,
) -> list[float]:
    """Duraciones derivadas de la rejilla de pulsos de la música."""
    grid = [b - music_offset for b in beats if b >= music_offset]
    grid = [b for b in grid if b <= total + 2]
    if len(grid) < 3:
        return []
    # Arrancamos en un inicio de compás si hay uno cerca del principio.
    down = [d - music_offset for d in downbeats if d >= music_offset]
    start_at = 0.0
    for d in down:
        if d <= min(2.5, total * 0.15):
            start_at = d
        else:
            break
    grid = [b for b in grid if b >= start_at]
    if len(grid) < 3:
        return []

    durations: list[float] = []
    pos = 0
    elapsed = 0.0
    while pos < len(grid) - 1 and elapsed < total:
        division = _division_schedule(style, elapsed / total if total else 0.0)
        nxt = min(pos + division, len(grid) - 1)
        d = grid[nxt] - grid[pos]
        # Si el salto se queda corto o se pasa, ajustamos añadiendo/quitando pulsos.
        while d < style.min_clip and nxt < len(grid) - 1:
            nxt += 1
            d = grid[nxt] - grid[pos]
        while d > style.max_clip and nxt > pos + 1:
            nxt -= 1
            d = grid[nxt] - grid[pos]
        d = max(MIN_SEGMENT, round(d, 3))
        durations.append(d)
        elapsed += d
        pos = nxt
    return _trim_to_total(durations, total)


def free_durations(style: StyleSpec, total: float, rng: random.Random) -> list[float]:
    """Duraciones sin música: alrededor del objetivo, con variación natural."""
    durations: list[float] = []
    elapsed = 0.0
    while elapsed < total:
        progress = elapsed / total if total else 0.0
        target = style.target_clip
        if style.energy_ramp:
            # De largo a corto: el montaje se va acelerando.
            target = style.max_clip - (style.max_clip - style.min_clip) * progress
        d = rng.uniform(target * 0.78, target * 1.22)
        d = max(style.min_clip, min(style.max_clip, d))
        durations.append(round(d, 3))
        elapsed += d
    return _trim_to_total(durations, total)


def _trim_to_total(durations: list[float], total: float) -> list[float]:
    """Recorta la lista para que sume `total` sin dejar un clip ridículo."""
    if not durations:
        return durations
    acc = 0.0
    out: list[float] = []
    for d in durations:
        if acc + d <= total + 0.02:
            out.append(d)
            acc += d
        else:
            remainder = total - acc
            if remainder >= MIN_SEGMENT:
                out.append(round(remainder, 3))
                acc = total
            break
    if not out:
        out = [round(min(total, durations[0]), 3)]
    return out


# --------------------------------------------------------------------------
# Duración objetivo
# --------------------------------------------------------------------------


def estimate_total(
    assets: list[Asset], style: StyleSpec, music: Optional[Asset], music_offset: float = 0.0
) -> float:
    material = sum(slots_for(a, style) for a in assets) * style.target_clip
    if style.target_duration:
        total = style.target_duration
    elif music and style.music_volume > 0 and style.beat_sync:
        music_left = max(0.0, music.duration - music_offset)
        total = min(music_left, material) if material else music_left
    else:
        total = material
    if style.max_duration:
        total = min(total, style.max_duration)
    return round(max(style.min_clip, total), 3)


def music_start_offset(music: Optional[Asset], style: StyleSpec, total: float) -> float:
    """Dónde empezar la música.

    Si el tema tiene un "drop" claro y el montaje es corto, arrancamos un poco
    antes del subidón en vez de en la intro, que suele ser lo más flojo.
    """
    if not music or not style.beat_sync:
        return 0.0
    drop = music.analysis.motion  # el analizador guarda ahí el segundo del drop
    if drop and drop > 4.0 and music.duration - drop > total * 0.6:
        lead = min(2.0, drop * 0.25)
        offset = max(0.0, drop - lead)
        # Encajar con el pulso más cercano para no romper la rejilla.
        beats = music.analysis.downbeats or music.analysis.beats
        near = [b for b in beats if abs(b - offset) < 1.5]
        return round(min(near, key=lambda b: abs(b - offset)) if near else offset, 3)
    return 0.0


# --------------------------------------------------------------------------
# Construcción de la línea de tiempo
# --------------------------------------------------------------------------


def build_timeline(project: Project, style: Optional[StyleSpec] = None) -> Timeline:
    style = style or project.style
    rng = random.Random(style.seed or 20240)

    width, height = resolution_for(style.aspect)
    timeline = Timeline(
        width=width,
        height=height,
        fps=style.fps,
        music_volume=style.music_volume,
        original_audio_volume=style.original_audio_volume,
        duck_music=style.duck_music,
    )

    assets = visual_assets(project)
    music = pick_music(project)
    if not assets:
        # Sin material visual pero con música: al menos dejamos la pista puesta.
        if music:
            _add_music(timeline, music, style, min(music.duration, 30.0), 0.0)
        return timeline

    ordered = order_assets(assets, style, rng)
    total = estimate_total(ordered, style, music)
    offset = music_start_offset(music, style, total)
    if music:
        total = estimate_total(ordered, style, music, offset)

    clips = _build_clips(ordered, music, style, total, offset, rng)
    video = Track(kind="video", name="Vídeo", clips=clips)
    timeline.tracks.append(video)

    duration = video.duration
    if music:
        _add_music(timeline, music, style, duration, offset)
    _add_text(timeline, project, style, duration)
    return timeline


def _build_clips(
    ordered: list[Asset],
    music: Optional[Asset],
    style: StyleSpec,
    total: float,
    offset: float,
    rng: random.Random,
) -> list[Clip]:
    """Genera los clips hasta cubrir `total` **después** de las transiciones.

    Cada transición solapa dos clips, así que la suma de duraciones es mayor
    que la duración final. En vez de estimar esa pérdida, montamos y medimos:
    si el resultado se queda corto, se pide un poco más de material y se repite.
    """
    ceiling = total * 2.5
    request = total
    best: list[Clip] = []
    best_actual = -1.0
    for _ in range(6):
        durations: list[float] = []
        if music and style.beat_sync and music.analysis.beats:
            durations = beat_durations(
                music.analysis.beats, music.analysis.downbeats, style, request, offset
            )
        if not durations:
            durations = free_durations(style, request, rng)

        clips = _assign_clips(ordered, durations, style, random.Random(style.seed or 20240))
        _apply_transitions(clips, style, random.Random((style.seed or 20240) + 7))
        _layout(clips)
        actual = clips[-1].end if clips else 0.0

        if actual > best_actual + 0.01:
            best, best_actual = clips, actual
        elif request >= ceiling:
            # Ni pidiendo más material crece el montaje: no hay más que rascar.
            break
        if actual >= total - 0.08 or request >= ceiling:
            break
        request = round(min(request * max(1.08, total / max(actual, 0.1)), ceiling), 3)

    return _fit_total(best, total)


def _fit_total(clips: list[Clip], total: float) -> list[Clip]:
    """Recorta la cola sobrante para clavar la duración pedida."""
    if not clips or total <= 0:
        return clips
    kept: list[Clip] = []
    for clip in clips:
        if clip.start >= total - MIN_SEGMENT:
            break
        kept.append(clip)
    if not kept:
        kept = clips[:1]
    last = kept[-1]
    if last.end > total + 0.02:
        last.duration = round(max(MIN_SEGMENT, total - last.start), 3)
    # Acortar el último clip puede dejar su transición desproporcionada.
    _clamp_transitions(kept)
    _layout(kept)
    return kept


def _clamp_transitions(clips: list[Clip]) -> None:
    """Ninguna transición puede comerse más de un tercio de los clips que une."""
    for i, clip in enumerate(clips):
        if i == 0:
            clip.transition_in = Transition(kind="cut", duration=0.0)
            continue
        if clip.transition_in.duration <= 0:
            continue
        limit = math.floor(min(clips[i - 1].duration, clip.duration) / 3.0 * 1000) / 1000
        if clip.transition_in.duration > limit:
            duration = max(0.0, limit)
            if duration <= 0.02:
                clip.transition_in = Transition(kind="cut", duration=0.0)
            else:
                clip.transition_in.duration = duration


def _assign_clips(
    ordered: list[Asset], durations: list[float], style: StyleSpec, rng: random.Random
) -> list[Clip]:
    """Reparte los huecos entre los assets, sin repetir el mismo momento."""
    used: dict[str, list[tuple[float, float]]] = {a.id: [] for a in ordered}
    remaining = {a.id: slots_for(a, style) for a in ordered}
    clips: list[Clip] = []

    pool = list(ordered)
    # El punto de arranque depende de la semilla: es parte de lo que hace que
    # «rebarajar» dé un montaje distinto con el mismo material y el mismo estilo.
    idx = rng.randrange(len(pool)) if pool else 0
    for i, duration in enumerate(durations):
        # Buscamos el siguiente asset con hueco libre; si se agotan todos,
        # reiniciamos los contadores y reutilizamos material.
        asset = None
        for _ in range(len(pool)):
            candidate = pool[idx % len(pool)]
            idx += 1
            if remaining.get(candidate.id, 0) > 0:
                asset = candidate
                break
        if asset is None:
            remaining = {a.id: slots_for(a, style) for a in ordered}
            used = {a.id: [] for a in ordered}
            asset = pool[idx % len(pool)]
            idx += 1
        remaining[asset.id] = remaining.get(asset.id, 1) - 1

        clip = _make_clip(asset, duration, style, rng, used[asset.id], i)
        used[asset.id].append((clip.in_point, clip.in_point + clip.duration * clip.speed))
        clips.append(clip)
    return clips


def _make_clip(
    asset: Asset,
    duration: float,
    style: StyleSpec,
    rng: random.Random,
    used: list[tuple[float, float]],
    index: int,
) -> Clip:
    clip = Clip(
        asset_id=asset.id,
        duration=round(duration, 3),
        fit=style.fit,
        grade=style.grade,
        volume=style.original_audio_volume if asset.kind == "video" and asset.has_audio else 0.0,
    )

    if asset.kind == "video":
        usable = max(0.0, asset.duration)
        if usable <= duration + 0.05:
            clip.in_point = 0.0
            # Si el clip es más corto que el hueco, lo ralentizamos un poco
            # en vez de dejar un frame congelado al final.
            if usable > MIN_SEGMENT and usable < duration:
                clip.speed = round(max(0.5, usable / duration), 4)
        else:
            clip.in_point = (
                best_segment(asset, duration, used, variation=rng.random())
                if style.use_highlights
                else round(min(usable - duration, index * duration % max(usable - duration, 0.1)), 3)
            )
        pool = style.effects
    else:
        pool = style.image_effects

    chance = style.effect_chance if asset.kind == "video" else max(style.effect_chance, 0.9)
    if pool and rng.random() < chance:
        clip.effect = rng.choice(pool)
    return clip


def _apply_transitions(clips: list[Clip], style: StyleSpec, rng: random.Random) -> None:
    options = [t for t in style.transitions if t != "cut"]
    for i, clip in enumerate(clips):
        if i == 0 or not options or rng.random() >= style.transition_chance:
            clip.transition_in = Transition(kind="cut", duration=0.0)
            continue
        kind = rng.choice(options)
        # La transición no puede comerse más de un tercio de ninguno de
        # los dos clips que une.
        limit = math.floor(min(clips[i - 1].duration, clip.duration) / 3.0 * 1000) / 1000
        duration = min(style.transition_duration, max(0.08, limit))
        clip.transition_in = Transition(kind=kind, duration=duration)


def _layout(clips: list[Clip]) -> None:
    """Coloca los clips en la línea de tiempo respetando los solapes."""
    cursor = 0.0
    for i, clip in enumerate(clips):
        overlap = clip.transition_in.duration if i > 0 else 0.0
        clip.start = round(max(0.0, cursor - overlap), 3)
        cursor = round(clip.start + clip.duration, 3)


def _add_music(
    timeline: Timeline, music: Asset, style: StyleSpec, duration: float, offset: float
) -> None:
    if style.music_volume <= 0 or duration <= 0:
        return
    available = max(0.0, music.duration - offset)
    track = timeline.ensure_track("music", "Música")
    track.clips.append(
        Clip(
            asset_id=music.id,
            start=0.0,
            duration=round(min(duration, available) if available else duration, 3),
            in_point=round(offset, 3),
            volume=style.music_volume,
        )
    )


def _add_text(timeline: Timeline, project: Project, style: StyleSpec, duration: float) -> None:
    plan = style.text
    if not (plan.intro_title or plan.captions):
        return
    track = timeline.ensure_track("text", "Texto")

    if plan.intro_title:
        text = plan.intro_text.strip() or project.name.strip()
        # El nombre del proyecto solo sirve de título si parece un título.
        if text and len(text) >= 3 and not text.lower().startswith("proyecto"):
            track.texts.append(
                TextClip(
                    text=text,
                    start=0.2,
                    duration=round(min(2.6, max(1.2, duration * 0.18)), 3),
                    style=plan.style.model_copy(deep=True),
                )
            )
    if plan.outro_text.strip() and duration > 3:
        outro = plan.style.model_copy(deep=True)
        track.texts.append(
            TextClip(
                text=plan.outro_text.strip(),
                start=round(max(0.0, duration - 2.2), 3),
                duration=2.0,
                style=outro,
            )
        )
    if plan.captions:
        # Marcadores vacíos sobre cada clip: el usuario solo tiene que escribir.
        video = timeline.track("video")
        if video:
            caption_style = plan.style.model_copy(deep=True)
            caption_style.y = 0.82
            caption_style.size = max(36, int(caption_style.size * 0.62))
            for clip in video.sorted_clips():
                if clip.duration < 0.8:
                    continue
                track.texts.append(
                    TextClip(
                        text="",
                        start=clip.start,
                        duration=clip.duration,
                        style=caption_style.model_copy(deep=True),
                    )
                )


# --------------------------------------------------------------------------
# Regeneración parcial
# --------------------------------------------------------------------------


def reshuffle(project: Project, seed: Optional[int] = None) -> Timeline:
    """Vuelve a montar con el mismo estilo pero otra combinación.

    Solo cambia la semilla: con eso varían el orden de entrada del material,
    qué tramo se toma de cada vídeo y qué efectos y transiciones caen. El
    estilo, el formato y la duración se respetan.
    """
    style = project.style.model_copy(deep=True)
    new_seed = seed if seed is not None else random.randint(1, 10**6)
    if new_seed == style.seed:
        new_seed += 1
    style.seed = new_seed
    return build_timeline(project, style)


def summarize(timeline: Timeline) -> dict:
    video = timeline.track("video")
    clips = video.sorted_clips() if video else []
    text_track = timeline.track("text")
    transitions = sum(1 for c in clips if c.transition_in.kind != "cut")
    return {
        "duration": timeline.duration,
        "clips": len(clips),
        "transitions": transitions,
        "effects": sum(1 for c in clips if c.effect != "none"),
        "texts": len(text_track.texts) if text_track else 0,
        "avg_clip": round(sum(c.duration for c in clips) / len(clips), 2) if clips else 0.0,
        "has_music": bool(timeline.track("music") and timeline.track("music").clips),  # type: ignore[union-attr]
        "resolution": f"{timeline.width}x{timeline.height}",
        "fps": timeline.fps,
    }
