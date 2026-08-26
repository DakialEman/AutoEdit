"""Análisis musical: pulsos, tempo, energía y "drop".

Todo se calcula en local con NumPy a partir del PCM que nos entrega FFmpeg, sin
librerías de audio pesadas. Es suficiente para sincronizar cortes con la música,
que es el 90% de lo que hace falta en un montaje corto.
"""

from __future__ import annotations

import subprocess
from typing import Optional

import numpy as np

from ..config import find_ffmpeg
from ..models import AssetAnalysis

SR = 22050
N_FFT = 1024
HOP = 256                     # ~86 análisis por segundo
FRAME_RATE = SR / HOP


# --------------------------------------------------------------------------
# Decodificación
# --------------------------------------------------------------------------


def decode_pcm(path: str, sr: int = SR, max_seconds: float = 1200.0) -> tuple[np.ndarray, int]:
    """Decodifica a mono float32 en -1..1."""
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
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sr),
        "-f",
        "s16le",
        "-acodec",
        "pcm_s16le",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=900)
    if not proc.stdout:
        return np.zeros(0, dtype=np.float32), sr
    data = np.frombuffer(proc.stdout, dtype="<i2").astype(np.float32) / 32768.0
    return data, sr


# --------------------------------------------------------------------------
# Espectro y envolvente de onsets
# --------------------------------------------------------------------------


def _stft_magnitude(x: np.ndarray, n_fft: int = N_FFT, hop: int = HOP) -> np.ndarray:
    if len(x) < n_fft:
        x = np.pad(x, (0, n_fft - len(x)))
    n_frames = 1 + (len(x) - n_fft) // hop
    if n_frames <= 0:
        return np.zeros((0, n_fft // 2 + 1), dtype=np.float32)
    idx = np.arange(n_fft)[None, :] + hop * np.arange(n_frames)[:, None]
    frames = x[idx] * np.hanning(n_fft).astype(np.float32)
    return np.abs(np.fft.rfft(frames, axis=1)).astype(np.float32)


def _log_bands(mag: np.ndarray, n_bands: int = 40) -> np.ndarray:
    """Agrupa los bins de la FFT en bandas log, tipo mel simplificado."""
    if mag.size == 0:
        return mag
    n_bins = mag.shape[1]
    edges = np.unique(
        np.geomspace(1, n_bins, n_bands + 1).astype(int).clip(1, n_bins)
    )
    bands = [mag[:, a:b].mean(axis=1) for a, b in zip(edges[:-1], edges[1:]) if b > a]
    if not bands:
        return mag
    return np.stack(bands, axis=1)


def onset_envelope(x: np.ndarray) -> np.ndarray:
    """Flujo espectral rectificado: sube cuando aparece energía nueva."""
    mag = _stft_magnitude(x)
    if mag.size == 0:
        return np.zeros(0, dtype=np.float32)
    bands = np.log1p(_log_bands(mag) * 20.0)
    diff = np.diff(bands, axis=0)
    flux = np.maximum(diff, 0.0).sum(axis=1)
    flux = np.concatenate([[0.0], flux]).astype(np.float32)
    # Resta de la media móvil: elimina la deriva y deja los picos.
    baseline = _moving_average(flux, int(FRAME_RATE * 0.35))
    env = np.maximum(flux - baseline, 0.0)
    peak = env.max()
    return (env / peak).astype(np.float32) if peak > 0 else env


def _moving_average(x: np.ndarray, win: int) -> np.ndarray:
    win = max(1, min(win, len(x)))
    if win <= 1:
        return x
    kernel = np.ones(win, dtype=np.float32) / win
    return np.convolve(x, kernel, mode="same")


# --------------------------------------------------------------------------
# Tempo y pulsos
# --------------------------------------------------------------------------


def estimate_tempo(env: np.ndarray, bpm_min: float = 60.0, bpm_max: float = 200.0) -> float:
    """Tempo por autocorrelación de la envolvente de onsets."""
    if env.size < int(FRAME_RATE * 4):
        return 0.0
    centered = env - env.mean()
    corr = np.correlate(centered, centered, mode="full")[len(centered) - 1:]
    lag_min = int(FRAME_RATE * 60.0 / bpm_max)
    lag_max = min(int(FRAME_RATE * 60.0 / bpm_min), len(corr) - 1)
    if lag_max <= lag_min:
        return 0.0
    window = corr[lag_min:lag_max].copy()
    # Ligero sesgo hacia 120 BPM: evita elegir el doble o la mitad del tempo.
    lags = np.arange(lag_min, lag_max)
    bpms = 60.0 * FRAME_RATE / lags
    window *= np.exp(-0.5 * (np.log2(bpms / 120.0) / 0.9) ** 2)
    best = int(np.argmax(window)) + lag_min
    return round(float(60.0 * FRAME_RATE / best), 2)


def track_beats(env: np.ndarray, tempo: float) -> list[float]:
    """Rejilla de pulsos ajustada a los picos reales de la envolvente."""
    if tempo <= 0 or env.size == 0:
        return []
    period = 60.0 / tempo * FRAME_RATE
    if period < 2:
        return []
    # Fase: probamos todos los desfases posibles dentro de un periodo.
    n_period = int(round(period))
    scores = []
    for phase in range(n_period):
        idx = np.arange(phase, len(env), period).astype(int)
        idx = idx[idx < len(env)]
        scores.append(env[idx].sum() if idx.size else 0.0)
    phase = int(np.argmax(scores)) if scores else 0

    beats: list[float] = []
    pos = float(phase)
    tolerance = period * 0.14
    while pos < len(env):
        lo = max(0, int(pos - tolerance))
        hi = min(len(env), int(pos + tolerance) + 1)
        if hi > lo:
            local = int(np.argmax(env[lo:hi])) + lo
            # Solo nos movemos si hay un pico de verdad; si no, mantenemos la rejilla.
            snapped = local if env[local] > 0.12 else int(round(pos))
        else:
            snapped = int(round(pos))
        beats.append(round(snapped / FRAME_RATE, 3))
        pos = snapped + period
    # Deduplicar y ordenar.
    out: list[float] = []
    for b in beats:
        if not out or b - out[-1] > 0.05:
            out.append(b)
    return out


def energy_curve(x: np.ndarray, resolution: float = 0.25) -> np.ndarray:
    """RMS normalizado cada `resolution` segundos."""
    if x.size == 0:
        return np.zeros(0, dtype=np.float32)
    win = max(1, int(SR * resolution))
    n = len(x) // win
    if n == 0:
        return np.array([float(np.sqrt(np.mean(x**2)))], dtype=np.float32)
    trimmed = x[: n * win].reshape(n, win)
    rms = np.sqrt((trimmed.astype(np.float64) ** 2).mean(axis=1)).astype(np.float32)
    peak = rms.max() or 1.0
    return rms / peak


def find_drop(energy: np.ndarray, resolution: float = 0.25) -> Optional[float]:
    """Segundo en el que la música pega el mayor subidón de energía."""
    if energy.size < 8:
        return None
    smooth = _moving_average(energy, 4)
    # Comparamos cada punto con la media de los ~3 s previos.
    look = max(1, int(3.0 / resolution))
    best_idx, best_jump = -1, 0.0
    for i in range(look, len(smooth)):
        prev = smooth[max(0, i - look): i].mean()
        jump = float(smooth[i] - prev)
        if jump > best_jump:
            best_idx, best_jump = i, jump
    if best_idx < 0 or best_jump < 0.12:
        return None
    return round(best_idx * resolution, 2)


# --------------------------------------------------------------------------
# Entrada principal
# --------------------------------------------------------------------------


def analyze_audio(path: str) -> AssetAnalysis:
    analysis = AssetAnalysis(analyzed=True)
    try:
        x, _ = decode_pcm(path)
        if x.size == 0:
            analysis.error = "No se pudo decodificar el audio"
            return analysis
        env = onset_envelope(x)
        tempo = estimate_tempo(env)
        beats = track_beats(env, tempo)
        energy = energy_curve(x)

        analysis.tempo = tempo
        analysis.beats = beats
        analysis.downbeats = _downbeats(beats, env)
        analysis.energy_curve = [round(float(v), 4) for v in _resample(energy, 300)]
        analysis.quality_score = float(np.clip(np.sqrt(np.mean(x**2)) * 4, 0.0, 1.0))
        drop = find_drop(energy)
        if drop is not None:
            analysis.highlights = []
            analysis.motion = drop  # reutilizamos el campo para guardar el drop
    except Exception as exc:  # pragma: no cover
        analysis.error = str(exc)[:400]
    return analysis


def _downbeats(beats: list[float], env: np.ndarray, bar: int = 4) -> list[float]:
    """Elige qué pulso abre el compás: el que acumula más energía cada 4."""
    if len(beats) < bar * 2 or env.size == 0:
        return beats[::bar] if beats else []
    best_offset, best_score = 0, -1.0
    for offset in range(bar):
        idx = [int(beats[i] * FRAME_RATE) for i in range(offset, len(beats), bar)]
        idx = [i for i in idx if 0 <= i < len(env)]
        score = float(np.sum(env[idx])) if idx else 0.0
        if score > best_score:
            best_offset, best_score = offset, score
    return beats[best_offset::bar]


def _resample(x: np.ndarray, n: int) -> np.ndarray:
    if x.size <= n or x.size == 0:
        return x
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)


def beats_in_range(beats: list[float], start: float, end: float) -> list[float]:
    return [b for b in beats if start <= b <= end]


def cut_points(
    beats: list[float],
    downbeats: list[float],
    division: int,
    total: float,
    fallback_interval: float,
    offset: float = 0.0,
) -> list[float]:
    """Puntos de corte para el montaje.

    Con música usamos la rejilla de pulsos (cada `division` pulsos); sin música,
    un intervalo fijo. Siempre devuelve una lista creciente que empieza en 0.
    """
    if beats and division > 0:
        grid = beats[:: max(1, division)]
        # Preferimos empezar en un inicio de compás si cae pronto.
        if downbeats:
            early = [d for d in downbeats if d <= min(2.0, total * 0.1)]
            if early:
                start_at = early[-1]
                grid = [b for b in grid if b >= start_at]
        points = [round(max(0.0, b - offset), 3) for b in grid if b - offset <= total]
        points = [p for p in points if p >= 0]
        if points and points[0] > 0.05:
            points.insert(0, 0.0)
        if len(points) >= 2:
            return points
    interval = max(0.3, fallback_interval)
    n = max(1, int(total // interval))
    return [round(i * interval, 3) for i in range(n + 1)]
