"""Motor de render: convierte una `Timeline` en un archivo de vídeo.

Estrategia en tres fases, pensada para que reeditar sea barato:

1. **Segmentos** — cada clip se normaliza por separado (encaje, efecto, color)
   a un MP4 con parámetros idénticos. El resultado se cachea por hash, así que
   tocar un clip solo vuelve a renderizar ese clip.
2. **Unión** — los clips seguidos por corte se pegan con el demuxer `concat`
   sin recodificar; los que llevan transición pasan por `xfade`.
3. **Acabado** — textos, mezcla de audio y fundidos globales en una sola
   pasada.

El audio no viaja dentro de los segmentos: se mezcla al final directamente
desde los archivos originales, colocando cada trozo con `adelay`. Así las
posiciones de la línea de tiempo se respetan al milisegundo.
"""

from __future__ import annotations

import hashlib
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .. import ffmpeg as ff
from ..config import SETTINGS
from ..models import Asset, Clip, Project, Timeline
from . import filters as fx
from .text import TextImage, prepare_texts

ProgressCb = Callable[[float, str], None]

AUDIO_FORMAT = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"
MAX_TEXT_OVERLAYS = 60


class RenderCancelled(RuntimeError):
    pass


@dataclass
class RenderResult:
    path: Path
    duration: float
    width: int
    height: int
    fps: int
    segments: int = 0
    reused: int = 0
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------


def canvas_size(timeline: Timeline, preview: bool) -> tuple[int, int]:
    if not preview:
        return fx.even(timeline.width), fx.even(timeline.height)
    target_h = min(SETTINGS.preview_height, timeline.height)
    scale = target_h / timeline.height
    return fx.even(timeline.width * scale), fx.even(target_h)


def _clip_key(asset: Asset, clip: Clip, width: int, height: int, fps: int) -> str:
    payload = "|".join(
        str(x)
        for x in (
            asset.path,
            asset.source_mtime,
            asset.size,
            round(clip.in_point, 4),
            round(clip.duration, 4),
            round(clip.speed, 4),
            clip.fit,
            clip.effect,
            round(clip.effect_amount, 3),
            clip.grade,
            clip.reverse,
            clip.mirror,
            round(clip.rotation, 2),
            sorted((clip.crop or {}).items()),
            width,
            height,
            fps,
            SETTINGS.render_crf,
        )
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:20]


def _encoder_args(fps: int, crf: Optional[int] = None) -> list[str]:
    return [
        "-c:v",
        "libx264",
        "-preset",
        SETTINGS.render_preset,
        "-crf",
        str(crf if crf is not None else SETTINGS.render_crf),
        "-pix_fmt",
        "yuv420p",
        "-x264-params",
        f"keyint={max(1, fps)}:min-keyint=1:scenecut=0",
        "-video_track_timescale",
        "90000",
        *(["-threads", str(SETTINGS.threads)] if SETTINGS.threads else []),
    ]


def _check(cancel: Optional[threading.Event]) -> None:
    if cancel is not None and cancel.is_set():
        raise RenderCancelled("Render cancelado")


# --------------------------------------------------------------------------
# Fase 1: segmentos normalizados
# --------------------------------------------------------------------------


def render_segment(
    asset: Asset,
    clip: Clip,
    width: int,
    height: int,
    fps: int,
    cache_dir: Path,
) -> tuple[Path, int, bool]:
    """Renderiza (o reutiliza) el segmento normalizado de un clip."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    frames = max(1, int(round(clip.duration * fps)))
    dest = cache_dir / f"seg_{_clip_key(asset, clip, width, height, fps)}.mp4"
    if dest.exists() and dest.stat().st_size > 0:
        return dest, frames, True

    args: list[str] = []
    if asset.kind == "image":
        args += ["-loop", "1", "-framerate", str(fps), "-t", f"{clip.duration + 0.2:.3f}"]
        args += ["-i", asset.path]
    else:
        source_duration = max(0.05, clip.duration * max(clip.speed, 0.01))
        args += ["-ss", f"{max(0.0, clip.in_point):.3f}", "-t", f"{source_duration:.3f}"]
        args += ["-i", asset.path]

    chain: list[str] = []
    if clip.reverse and asset.kind == "video":
        chain.append("reverse")
    if asset.kind == "video" and abs(clip.speed - 1.0) > 1e-3:
        chain.append(f"setpts=PTS/{clip.speed:.6f}")
    if clip.crop:
        c = clip.crop
        chain.append(
            "crop=w=iw*{w:.4f}:h=ih*{h:.4f}:x=iw*{x:.4f}:y=ih*{y:.4f}".format(
                w=max(0.05, float(c.get("w", 1.0))),
                h=max(0.05, float(c.get("h", 1.0))),
                x=max(0.0, float(c.get("x", 0.0))),
                y=max(0.0, float(c.get("y", 0.0))),
            )
        )
    if clip.mirror:
        chain.append("hflip")
    if abs(clip.rotation) > 0.5:
        chain.append(f"rotate={clip.rotation}*PI/180:fillcolor=black")

    # Con efecto de movimiento se renderiza con margen para poder hacer zoom
    # sin que se note la pérdida de resolución.
    if fx.needs_overscan(clip.effect):
        fit_w, fit_h = fx.even(width * fx.OVERSCAN), fx.even(height * fx.OVERSCAN)
    else:
        fit_w, fit_h = width, height
    chain.append(fx.fit_chain(clip.fit, fit_w, fit_h))
    chain.append(fx.motion_chain(clip.effect, width, height, frames, fps, clip.effect_amount))
    grade = fx.grade_chain(clip.grade)
    if grade:
        chain.append(grade)
    chain += [f"fps={fps}", "setsar=1", "format=yuv420p"]

    ff.run(
        [
            *args,
            "-an",
            "-sn",
            "-vf",
            fx.join(*chain),
            "-frames:v",
            str(frames),
            *_encoder_args(fps),
            str(dest),
        ],
        total_duration=clip.duration,
        timeout=1800,
    )
    return dest, frames, False


# --------------------------------------------------------------------------
# Fase 2: unión
# --------------------------------------------------------------------------


def _runs(clips: list[Clip]) -> list[list[int]]:
    """Agrupa índices de clips separados por cortes secos."""
    groups: list[list[int]] = []
    for i, clip in enumerate(clips):
        starts_new = i > 0 and clip.transition_in.kind != "cut" and clip.transition_in.duration > 0
        if i == 0 or starts_new:
            groups.append([i])
        else:
            groups[-1].append(i)
    return groups


def _concat_copy(paths: list[Path], dest: Path, fps: int) -> Path:
    """Pega segmentos sin recodificar; si falla, recodifica."""
    if len(paths) == 1:
        shutil.copyfile(paths[0], dest)
        return dest
    listfile = dest.with_suffix(".txt")
    ff.concat_list_file(paths, listfile)
    try:
        ff.run(["-f", "concat", "-safe", "0", "-i", str(listfile), "-c", "copy", str(dest)],
               timeout=1800)
    except ff.FFmpegError:
        ff.run(
            ["-f", "concat", "-safe", "0", "-i", str(listfile), *_encoder_args(fps), "-an", str(dest)],
            timeout=3600,
        )
    finally:
        listfile.unlink(missing_ok=True)
    return dest


def join_segments(
    segments: list[Path],
    frames: list[int],
    clips: list[Clip],
    fps: int,
    work_dir: Path,
    on_progress: Optional[ProgressCb] = None,
) -> tuple[Path, float]:
    """Une los segmentos aplicando las transiciones. Devuelve archivo y duración."""
    work_dir.mkdir(parents=True, exist_ok=True)
    groups = _runs(clips)

    run_files: list[Path] = []
    run_durations: list[float] = []
    for gi, group in enumerate(groups):
        paths = [segments[i] for i in group]
        duration = sum(frames[i] for i in group) / fps
        if len(paths) == 1:
            run_files.append(paths[0])
        else:
            dest = work_dir / f"run_{gi:04d}.mp4"
            run_files.append(_concat_copy(paths, dest, fps))
        run_durations.append(duration)

    if len(run_files) == 1:
        return run_files[0], run_durations[0]

    if on_progress:
        on_progress(0.0, "Aplicando transiciones")

    inputs: list[str] = []
    for path in run_files:
        inputs += ["-i", str(path)]

    graph: list[str] = []
    current = "0:v"
    acc = run_durations[0]
    for i in range(1, len(run_files)):
        first_clip = clips[groups[i][0]]
        d = max(0.05, min(first_clip.transition_in.duration, run_durations[i] - 0.02, acc - 0.02))
        offset = max(0.0, acc - d)
        label = f"vx{i}"
        graph.append(
            f"[{current}][{i}:v]xfade=transition={fx.xfade_name(first_clip.transition_in.kind)}"
            f":duration={d:.3f}:offset={offset:.3f}[{label}]"
        )
        current = label
        acc = offset + run_durations[i]

    dest = work_dir / "joined.mp4"
    ff.run(
        [
            *inputs,
            "-filter_complex",
            ";".join(graph),
            "-map",
            f"[{current}]",
            "-an",
            *_encoder_args(fps),
            str(dest),
        ],
        total_duration=acc,
        on_progress=on_progress,
        label="Aplicando transiciones",
        timeout=7200,
    )
    return dest, acc


# --------------------------------------------------------------------------
# Fase 3: audio
# --------------------------------------------------------------------------


def _atempo(speed: float) -> str:
    """`atempo` solo acepta 0.5..100; para valores menores se encadena."""
    if abs(speed - 1.0) < 1e-3:
        return ""
    parts: list[str] = []
    remaining = speed
    while remaining < 0.5:
        parts.append("atempo=0.5")
        remaining /= 0.5
    while remaining > 100:
        parts.append("atempo=100")
        remaining /= 100
    parts.append(f"atempo={remaining:.6f}")
    return ",".join(parts)


@dataclass
class AudioPiece:
    path: str
    seek: float
    take: float
    start: float
    duration: float
    volume: float
    speed: float
    is_music: bool


def collect_audio(project: Project, timeline: Timeline) -> list[AudioPiece]:
    pieces: list[AudioPiece] = []
    for track in timeline.tracks:
        if track.muted or track.kind == "text":
            continue
        is_music = track.kind == "music"
        for clip in track.sorted_clips():
            asset = project.asset(clip.asset_id)
            if asset is None or clip.duration <= 0.02:
                continue
            if asset.kind == "video" and not asset.has_audio:
                continue
            volume = clip.volume * track.volume
            if is_music:
                volume *= timeline.music_volume
            elif track.kind == "video":
                volume *= timeline.original_audio_volume
            if volume <= 0.001:
                continue
            pieces.append(
                AudioPiece(
                    path=asset.path,
                    seek=max(0.0, clip.in_point),
                    take=max(0.05, clip.duration * max(clip.speed, 0.01)),
                    start=max(0.0, clip.start),
                    duration=clip.duration,
                    volume=round(volume, 4),
                    speed=clip.speed,
                    is_music=is_music,
                )
            )
    return pieces


def build_audio_graph(
    pieces: list[AudioPiece], first_index: int, total: float, duck: bool
) -> tuple[list[str], list[str], Optional[str]]:
    """Construye entradas y filtros de audio. Devuelve (inputs, graph, label)."""
    if not pieces:
        return [], [], None

    inputs: list[str] = []
    graph: list[str] = []
    music_labels: list[str] = []
    voice_labels: list[str] = []

    for n, piece in enumerate(pieces):
        idx = first_index + n
        inputs += ["-ss", f"{piece.seek:.3f}", "-t", f"{piece.take:.3f}", "-i", piece.path]
        chain = [AUDIO_FORMAT]
        tempo = _atempo(piece.speed)
        if tempo:
            chain.append(tempo)
        chain.append(f"volume={piece.volume:.4f}")
        # Micro-fundidos: evitan los clics al empalmar trozos.
        fade = min(0.03, piece.duration / 3)
        chain.append(f"afade=t=in:st=0:d={fade:.3f}")
        chain.append(f"afade=t=out:st={max(0.0, piece.duration - fade):.3f}:d={fade:.3f}")
        chain.append(f"atrim=0:{piece.duration:.3f}")
        chain.append("asetpts=PTS-STARTPTS")
        if piece.start > 0.001:
            ms = int(round(piece.start * 1000))
            chain.append(f"adelay={ms}:all=1")
        label = f"a{n}"
        graph.append(f"[{idx}:a]{','.join(chain)}[{label}]")
        (music_labels if piece.is_music else voice_labels).append(label)

    ducked_music = music_labels
    if duck and music_labels and voice_labels and ff.has_filter("sidechaincompress"):
        # Bajamos la música automáticamente cuando suena el audio original.
        if len(voice_labels) > 1:
            graph.append(
                "".join(f"[{l}]" for l in voice_labels)
                + f"amix=inputs={len(voice_labels)}:duration=longest:normalize=0[voicemix]"
            )
            voice_source = "voicemix"
        else:
            voice_source = voice_labels[0]
        graph.append(f"[{voice_source}]asplit=2[voice_out][voice_sc]")
        if len(music_labels) > 1:
            graph.append(
                "".join(f"[{l}]" for l in music_labels)
                + f"amix=inputs={len(music_labels)}:duration=longest:normalize=0[musicmix]"
            )
            music_source = "musicmix"
        else:
            music_source = music_labels[0]
        graph.append(
            f"[{music_source}][voice_sc]sidechaincompress="
            "threshold=0.03:ratio=8:attack=15:release=350:makeup=1[musicduck]"
        )
        mix_labels = ["voice_out", "musicduck"]
    elif duck and music_labels and voice_labels:
        # Sin `sidechaincompress` aplicamos una reducción fija de la música.
        graph.append(
            "".join(f"[{l}]" for l in music_labels)
            + (
                f"amix=inputs={len(music_labels)}:duration=longest:normalize=0[musicmix]"
                if len(music_labels) > 1
                else "anull[musicmix]"
            )
        )
        graph.append("[musicmix]volume=0.45[musicduck]")
        mix_labels = voice_labels + ["musicduck"]
    else:
        mix_labels = voice_labels + ducked_music

    if len(mix_labels) == 1:
        graph.append(f"[{mix_labels[0]}]apad,atrim=0:{total:.3f},asetpts=PTS-STARTPTS[aout]")
    else:
        graph.append(
            "".join(f"[{l}]" for l in mix_labels)
            + f"amix=inputs={len(mix_labels)}:duration=longest:normalize=0,"
            f"apad,atrim=0:{total:.3f},asetpts=PTS-STARTPTS[aout]"
        )
    return inputs, graph, "aout"


# --------------------------------------------------------------------------
# Fase 3: vídeo final (textos y fundidos)
# --------------------------------------------------------------------------


def build_video_graph(
    texts: list[tuple[object, TextImage]], total: float, timeline: Timeline
) -> tuple[list[str], list[str], str]:
    inputs: list[str] = []
    graph: list[str] = []
    current = "0:v"

    fade_in, fade_out = timeline.fade_in, timeline.fade_out
    fade_parts: list[str] = []
    if fade_in > 0.01:
        fade_parts.append(f"fade=t=in:st=0:d={fade_in:.3f}")
    if fade_out > 0.01 and total > fade_out:
        fade_parts.append(f"fade=t=out:st={total - fade_out:.3f}:d={fade_out:.3f}")
    if fade_parts:
        graph.append(f"[{current}]{','.join(fade_parts)}[vbase]")
        current = "vbase"

    for n, (clip, image) in enumerate(texts):
        idx = 1 + n
        inputs += [
            "-loop",
            "1",
            "-framerate",
            str(timeline.fps),
            "-t",
            f"{total:.3f}",
            "-i",
            str(image.path),
        ]
        start = max(0.0, float(clip.start))  # type: ignore[attr-defined]
        end = min(total, start + float(clip.duration))  # type: ignore[attr-defined]
        anim = clip.style.animation  # type: ignore[attr-defined]
        ramp = min(0.45, max(0.08, (end - start) / 4))

        chain = ["format=rgba"]
        if anim != "none":
            chain.append(f"fade=t=in:st={start:.3f}:d={ramp:.3f}:alpha=1")
            chain.append(f"fade=t=out:st={max(start, end - ramp):.3f}:d={ramp:.3f}:alpha=1")
        label = f"tx{n}"
        graph.append(f"[{idx}:v]{','.join(chain)}[{label}]")

        x_expr = str(image.x)
        y_expr = str(image.y)
        if anim in ("slide_up", "pop"):
            travel = max(6, int(image.height * (0.5 if anim == "slide_up" else 0.18)))
            y_expr = f"{image.y}+{travel}*(1-min(1,max(0,(t-{start:.3f})/{ramp:.3f})))"

        enable = f":enable='between(t,{start:.3f},{end:.3f})'" if anim == "none" else ""
        out_label = f"vt{n}"
        graph.append(f"[{current}][{label}]overlay=x={x_expr}:y={y_expr}{enable}[{out_label}]")
        current = out_label

    if current == "0:v":
        graph.append("[0:v]null[vout]")
        current = "vout"
    return inputs, graph, current


# --------------------------------------------------------------------------
# Orquestación
# --------------------------------------------------------------------------


def render_timeline(
    project: Project,
    dest: Path,
    *,
    timeline: Optional[Timeline] = None,
    preview: bool = False,
    on_progress: Optional[ProgressCb] = None,
    cancel: Optional[threading.Event] = None,
) -> RenderResult:
    timeline = timeline or project.timeline
    video_track = timeline.track("video")
    clips = video_track.sorted_clips() if video_track else []
    if not clips:
        raise ValueError("La línea de tiempo no tiene clips de vídeo que renderizar.")

    width, height = canvas_size(timeline, preview)
    fps = timeline.fps
    SETTINGS.ensure_dirs(project.id)
    cache = SETTINGS.cache_dir(project.id) / f"{width}x{height}@{fps}"
    work = cache / "work"
    work.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []

    def progress(fraction: float, message: str) -> None:
        if on_progress:
            on_progress(max(0.0, min(1.0, fraction)), message)

    # --- 1. segmentos ---
    segments: list[Path] = []
    frames: list[int] = []
    reused = 0
    for i, clip in enumerate(clips):
        _check(cancel)
        asset = project.asset(clip.asset_id)
        if asset is None:
            raise ValueError(f"El clip {clip.id} apunta a un archivo que ya no está en el proyecto.")
        if not Path(asset.path).exists():
            raise ValueError(f"No se encuentra el archivo «{asset.name}» en {asset.path}")
        if asset.kind == "audio" or (asset.kind == "video" and not asset.has_video):
            raise ValueError(
                f"«{asset.name}» no contiene imagen, solo audio, así que no puede ir "
                "en la pista de vídeo. Quítalo del proyecto y vuelve a añadirlo: "
                "AutoEdit lo reconocerá como audio."
            )
        path, count, cached = render_segment(asset, clip, width, height, fps, cache)
        segments.append(path)
        frames.append(count)
        reused += 1 if cached else 0
        progress(0.05 + 0.55 * (i + 1) / len(clips), f"Preparando clip {i + 1} de {len(clips)}")

    # --- 2. unión ---
    _check(cancel)
    progress(0.62, "Uniendo clips")
    joined, total = join_segments(
        segments,
        frames,
        clips,
        fps,
        work,
        on_progress=lambda f, _m: progress(0.62 + 0.18 * f, "Aplicando transiciones"),
    )

    # --- 3. acabado ---
    _check(cancel)
    progress(0.82, "Añadiendo textos y audio")
    text_track = timeline.track("text")
    texts: list[tuple[object, TextImage]] = []
    if text_track and not text_track.hidden:
        prepared = prepare_texts(text_track.sorted_texts(), width, height, cache / "texts")
        if len(prepared) > MAX_TEXT_OVERLAYS:
            warnings.append(
                f"Solo se han compuesto los primeros {MAX_TEXT_OVERLAYS} textos de {len(prepared)}."
            )
            prepared = prepared[:MAX_TEXT_OVERLAYS]
        texts = list(prepared)  # type: ignore[arg-type]

    video_inputs, video_graph, video_label = build_video_graph(texts, total, timeline)
    pieces = collect_audio(project, timeline)
    audio_inputs, audio_graph, audio_label = build_audio_graph(
        pieces, 1 + len(texts), total, timeline.duck_music
    )

    dest.parent.mkdir(parents=True, exist_ok=True)
    args = ["-i", str(joined), *video_inputs, *audio_inputs]
    graph = video_graph + audio_graph
    args += ["-filter_complex", ";".join(graph)]
    args += ["-map", f"[{video_label}]"]
    if audio_label:
        args += ["-map", f"[{audio_label}]", "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
    else:
        args += ["-an"]
    args += ["-t", f"{total:.3f}", *_encoder_args(fps, crf=SETTINGS.render_crf + (4 if preview else 0))]
    args += ["-movflags", "+faststart", str(dest)]

    ff.run(
        args,
        total_duration=total,
        on_progress=lambda f, _m: progress(0.82 + 0.17 * f, "Renderizando vídeo"),
        timeout=14400,
    )
    progress(1.0, "Listo")

    # La caché de trabajo intermedia no hace falta conservarla.
    shutil.rmtree(work, ignore_errors=True)

    return RenderResult(
        path=dest,
        duration=round(total, 3),
        width=width,
        height=height,
        fps=fps,
        segments=len(segments),
        reused=reused,
        warnings=warnings,
    )
