"""Análisis visual de vídeos e imágenes.

La idea es sencilla: en vez de tirar de modelos pesados, decodificamos el vídeo
a miniaturas en escala de grises (48x27 a 4 fps) y sacamos de ahí métricas
baratas pero muy informativas — movimiento, nitidez, exposición y cortes de
escena. Con eso el planificador ya puede elegir los mejores tramos.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

import numpy as np

from .. import ffmpeg as ff
from ..config import find_ffmpeg
from ..models import Asset, AssetAnalysis, Highlight

SAMPLE_FPS = 4.0
SAMPLE_W, SAMPLE_H = 48, 27


# --------------------------------------------------------------------------
# Muestreo de frames
# --------------------------------------------------------------------------


def sample_frames(path: str, fps: float = SAMPLE_FPS, max_seconds: float = 1800.0) -> np.ndarray:
    """Devuelve un array (N, H, W) float32 en 0..1 con frames en gris."""
    cmd = [
        find_ffmpeg(),
        "-hide_banner",
        "-nostdin",
        "-v",
        "error",
        "-t",
        str(max_seconds),
        "-i",
        path,
        "-an",
        "-sn",
        "-vf",
        f"fps={fps},scale={SAMPLE_W}:{SAMPLE_H}:flags=bilinear,format=gray",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=900)
    raw = proc.stdout
    frame_size = SAMPLE_W * SAMPLE_H
    count = len(raw) // frame_size
    if count == 0:
        return np.zeros((0, SAMPLE_H, SAMPLE_W), dtype=np.float32)
    arr = np.frombuffer(raw[: count * frame_size], dtype=np.uint8)
    return arr.reshape(count, SAMPLE_H, SAMPLE_W).astype(np.float32) / 255.0


# --------------------------------------------------------------------------
# Métricas por frame
# --------------------------------------------------------------------------


def _sharpness(frames: np.ndarray) -> np.ndarray:
    """Energía de gradiente: aproxima el enfoque/detalle de cada frame."""
    if frames.size == 0:
        return np.zeros(0, dtype=np.float32)
    gx = np.diff(frames, axis=2)
    gy = np.diff(frames, axis=1)
    return (np.abs(gx).mean(axis=(1, 2)) + np.abs(gy).mean(axis=(1, 2))).astype(np.float32)


def _motion(frames: np.ndarray) -> np.ndarray:
    """Diferencia media entre frames consecutivos."""
    if len(frames) < 2:
        return np.zeros(len(frames), dtype=np.float32)
    diff = np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2))
    return np.concatenate([diff[:1], diff]).astype(np.float32)


def _normalize(x: np.ndarray) -> np.ndarray:
    if x.size == 0:
        return x
    lo, hi = float(np.percentile(x, 5)), float(np.percentile(x, 95))
    if hi - lo < 1e-6:
        return np.full_like(x, 0.5)
    return np.clip((x - lo) / (hi - lo), 0.0, 1.0)


def _smooth(x: np.ndarray, win: int) -> np.ndarray:
    if x.size == 0 or win <= 1:
        return x
    win = min(win, max(1, len(x)))
    kernel = np.ones(win, dtype=np.float32) / win
    return np.convolve(x, kernel, mode="same")


# --------------------------------------------------------------------------
# Cortes de escena
# --------------------------------------------------------------------------


def detect_scenes(frames: np.ndarray, fps: float = SAMPLE_FPS, threshold: float = 0.18) -> list[float]:
    """Detecta cortes a partir del salto de contenido entre frames."""
    if len(frames) < 3:
        return []
    flat = frames.reshape(len(frames), -1)
    diff = np.abs(np.diff(flat, axis=0)).mean(axis=1)
    scenes: list[float] = []
    last = -1e9
    for i, d in enumerate(diff):
        t = (i + 1) / fps
        if d > threshold and t - last > 0.75:
            scenes.append(round(float(t), 3))
            last = t
    return scenes


# --------------------------------------------------------------------------
# Puntuación y momentos destacados
# --------------------------------------------------------------------------


def score_curve(frames: np.ndarray) -> np.ndarray:
    """Curva de "interés" por frame, en 0..1.

    Premia detalle y movimiento moderado; castiga frames quemados, negros o
    con movimiento brusco (típico de una cámara que se está recolocando).
    """
    if frames.size == 0:
        return np.zeros(0, dtype=np.float32)
    brightness = frames.mean(axis=(1, 2))
    contrast = frames.std(axis=(1, 2))
    sharp = _normalize(_sharpness(frames))
    motion_raw = _motion(frames)
    motion = _normalize(motion_raw)

    # Exposición: 0.45 es el punto dulce; los extremos penalizan.
    exposure = 1.0 - np.clip(np.abs(brightness - 0.45) / 0.45, 0.0, 1.0)
    # Movimiento: una curva en campana centrada en ~0.35 de movimiento normalizado.
    motion_pref = np.exp(-((motion - 0.35) ** 2) / (2 * 0.28**2))

    score = (
        0.34 * sharp
        + 0.26 * motion_pref
        + 0.22 * exposure
        + 0.18 * _normalize(contrast)
    )
    # Frames casi negros no sirven para nada.
    score = np.where(brightness < 0.04, 0.0, score)
    score = np.where(brightness > 0.97, score * 0.3, score)
    return _smooth(score.astype(np.float32), 5)


def find_highlights(
    curve: np.ndarray,
    fps: float = SAMPLE_FPS,
    window: float = 2.5,
    max_count: int = 12,
    min_gap: float = 1.0,
) -> list[Highlight]:
    """Selecciona los mejores tramos de `window` segundos sin solaparse."""
    if curve.size == 0:
        return []
    win_frames = max(1, int(round(window * fps)))
    if len(curve) <= win_frames:
        return [
            Highlight(
                start=0.0,
                end=round(len(curve) / fps, 3),
                score=float(curve.mean()),
                reason="clip completo",
            )
        ]
    kernel = np.ones(win_frames, dtype=np.float32) / win_frames
    windowed = np.convolve(curve, kernel, mode="valid")
    order = np.argsort(windowed)[::-1]
    chosen: list[Highlight] = []
    for idx in order:
        start = float(idx) / fps
        end = start + window
        if any(not (end <= h.start - min_gap or start >= h.end + min_gap) for h in chosen):
            continue
        chosen.append(
            Highlight(
                start=round(start, 3),
                end=round(end, 3),
                score=round(float(windowed[idx]), 4),
                reason="alta puntuación visual",
            )
        )
        if len(chosen) >= max_count:
            break
    chosen.sort(key=lambda h: h.start)
    return chosen


# --------------------------------------------------------------------------
# Miniaturas
# --------------------------------------------------------------------------


def make_thumbnail(asset: Asset, dest_dir: Path, height: int = 320) -> Optional[str]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{asset.id}.jpg"
    try:
        if asset.kind == "image":
            ff.run(
                ["-i", asset.path, "-vf", f"scale=-2:{height}", "-frames:v", "1", str(dest)],
                timeout=120,
            )
        elif asset.kind == "video":
            seek = max(0.0, min(asset.duration * 0.15, max(0.0, asset.duration - 0.2)))
            ff.run(
                [
                    "-ss",
                    f"{seek:.3f}",
                    "-i",
                    asset.path,
                    "-vf",
                    f"scale=-2:{height}",
                    "-frames:v",
                    "1",
                    str(dest),
                ],
                timeout=180,
            )
        else:
            return None
    except Exception:
        return None
    return str(dest) if dest.exists() else None


def make_filmstrip(asset: Asset, dest_dir: Path, count: int = 10, height: int = 90) -> Optional[str]:
    """Tira de fotogramas para pintar el clip en la línea de tiempo."""
    if asset.kind != "video" or asset.duration <= 0:
        return None
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{asset.id}_strip.jpg"
    rate = max(count / asset.duration, 0.01)
    try:
        ff.run(
            [
                "-i",
                asset.path,
                "-vf",
                f"fps={rate:.6f},scale=-2:{height},tile={count}x1",
                "-frames:v",
                "1",
                str(dest),
            ],
            timeout=300,
        )
    except Exception:
        return None
    return str(dest) if dest.exists() else None


# --------------------------------------------------------------------------
# Entrada principal
# --------------------------------------------------------------------------


def analyze_visual(asset: Asset) -> AssetAnalysis:
    """Analiza un vídeo o una imagen y devuelve su `AssetAnalysis`."""
    analysis = AssetAnalysis(analyzed=True)
    try:
        if asset.kind == "image":
            frames = _sample_image(asset.path)
            if frames.size:
                analysis.brightness = float(frames.mean())
                analysis.motion = 0.0
                sharp = float(_sharpness(frames)[0])
                # Escala empírica: 0.10 de energía de gradiente ya es una foto nítida.
                analysis.quality_score = float(np.clip(sharp / 0.10, 0.0, 1.0))
            return analysis

        frames = sample_frames(asset.path)
        if frames.size == 0:
            analysis.error = "No se pudieron decodificar fotogramas"
            analysis.quality_score = 0.4
            return analysis

        curve = score_curve(frames)
        analysis.scenes = detect_scenes(frames)
        analysis.highlights = find_highlights(curve, window=_highlight_window(asset.duration))
        analysis.energy_curve = [round(float(v), 4) for v in _downsample(curve, 200)]
        analysis.brightness = float(frames.mean())
        analysis.motion = float(_motion(frames).mean())
        analysis.quality_score = float(np.clip(curve.mean(), 0.0, 1.0))
    except Exception as exc:  # pragma: no cover - depende del archivo
        analysis.error = str(exc)[:400]
        analysis.quality_score = 0.4
    return analysis


def _highlight_window(duration: float) -> float:
    if duration <= 4:
        return max(0.8, duration * 0.6)
    if duration <= 15:
        return 2.0
    if duration <= 60:
        return 2.5
    return 3.5


def _sample_image(path: str) -> np.ndarray:
    cmd = [
        find_ffmpeg(),
        "-hide_banner",
        "-nostdin",
        "-v",
        "error",
        "-i",
        path,
        "-vf",
        f"scale={SAMPLE_W}:{SAMPLE_H},format=gray",
        "-frames:v",
        "1",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=120)
    size = SAMPLE_W * SAMPLE_H
    if len(proc.stdout) < size:
        return np.zeros((0, SAMPLE_H, SAMPLE_W), dtype=np.float32)
    arr = np.frombuffer(proc.stdout[:size], dtype=np.uint8)
    return arr.reshape(1, SAMPLE_H, SAMPLE_W).astype(np.float32) / 255.0


def _downsample(x: np.ndarray, n: int) -> np.ndarray:
    if x.size <= n or x.size == 0:
        return x
    idx = np.linspace(0, len(x) - 1, n)
    return np.interp(idx, np.arange(len(x)), x)


def best_segment(
    asset: Asset,
    duration: float,
    avoid: Optional[list[tuple[float, float]]] = None,
    variation: float = 0.0,
) -> float:
    """Punto de entrada recomendado para tomar `duration` segundos del asset.

    Prioriza los momentos destacados y evita los tramos ya usados (`avoid`).
    Si todos los destacados están pillados, barre el resto del clip antes de
    rendirse: repetir el mismo par de segundos dos veces canta muchísimo.
    `variation` (0..1) desplaza la preferencia entre los mejores candidatos,
    que es lo que hace que «rebarajar» dé un montaje distinto.
    """
    avoid = avoid or []
    if asset.duration <= duration:
        return 0.0
    limit = asset.duration - duration

    def free(start: float) -> bool:
        end = start + duration
        return all(end <= a + 0.01 or start >= b - 0.01 for a, b in avoid)

    candidates: list[tuple[float, float]] = []
    for h in asset.analysis.highlights:
        center = (h.start + h.end) / 2
        candidates.append((h.score, max(0.0, min(center - duration / 2, limit))))

    if candidates:
        candidates.sort(reverse=True)
        # Rotamos entre los mejores para que dos montajes seguidos no sean iguales.
        top = max(1, min(3, len(candidates)))
        offset = int(variation * top) % top
        ordered = candidates[offset:] + candidates[:offset]
        for _, start in ordered:
            if free(start):
                return round(start, 3)

    # Barrido regular por si los destacados no dan más de sí.
    step = max(duration, 0.5)
    sweep_start = (variation * step) % max(step, 0.001)
    position = sweep_start
    while position <= limit:
        if free(position):
            return round(position, 3)
        position += step

    if candidates:
        return round(candidates[0][1], 3)
    # Sin análisis ni hueco libre: evitar el arranque, que suele ser lo peor.
    return round(max(0.0, min(asset.duration * 0.12, limit)), 3)


def waveform(path: str, buckets: int = 400) -> list[float]:
    """RMS normalizado por tramos, para pintar la onda en la UI."""
    from .audio import decode_pcm

    try:
        samples, sr = decode_pcm(path)
    except Exception:
        return []
    if samples.size == 0:
        return []
    n = min(buckets, max(1, len(samples) // 128))
    chunks = np.array_split(samples, n)
    rms = np.array([float(np.sqrt(np.mean(c.astype(np.float64) ** 2))) for c in chunks])
    peak = rms.max() or 1.0
    return [round(float(v / peak), 4) for v in rms]


def probe_to_asset(path: str | Path, kind_hint: Optional[str] = None) -> Asset:
    """Sondea un archivo del disco y construye el `Asset` correspondiente."""
    p = Path(path)
    info = ff.probe(p)
    kind = kind_hint or _guess_kind(p, info)
    stat = p.stat() if p.exists() else None
    asset = Asset(
        kind=kind,  # type: ignore[arg-type]
        path=str(p.resolve()),
        name=p.name,
        size=stat.st_size if stat else 0,
        source_mtime=stat.st_mtime if stat else 0.0,
        duration=0.0 if kind == "image" else round(info.duration, 3),
        width=info.display_width,
        height=info.display_height,
        fps=round(info.fps, 3),
        has_audio=info.has_audio,
        has_video=info.has_video,
        codec=info.codec,
    )
    return asset


IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic", ".heif", ".tif", ".tiff", ".avif"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".aiff"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mpg", ".mpeg", ".wmv", ".3gp", ".mts"}


def _guess_kind(path: Path, info: ff.MediaInfo) -> str:
    ext = path.suffix.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in VIDEO_EXT:
        return "video"
    if info.has_video and info.duration > 0.05:
        return "video"
    if info.has_video:
        return "image"
    return "audio"
