"""Análisis musical: tempo, pulsos y energía.

Se prueba con señales sintéticas generadas en NumPy, sin tocar FFmpeg: lo que
se valida es el algoritmo, no la decodificación.
"""

import numpy as np
import pytest

from autoedit.analysis import audio


def click_track(bpm: float, seconds: float = 20.0, sr: int = audio.SR) -> np.ndarray:
    """Metrónomo: un golpe corto y seco en cada pulso."""
    t = np.arange(int(seconds * sr)) / sr
    period = 60.0 / bpm
    phase = np.mod(t, period)
    envelope = np.exp(-phase * 45.0)
    tone = np.sin(2 * np.pi * 180 * t) * 0.8 + np.sin(2 * np.pi * 90 * t) * 0.4
    return (tone * envelope).astype(np.float32)


@pytest.mark.parametrize("bpm", [90.0, 100.0, 120.0, 140.0])
def test_estima_el_tempo(bpm):
    env = audio.onset_envelope(click_track(bpm))
    estimated = audio.estimate_tempo(env)
    # Se admite confundir el tempo con su doble o su mitad, como cualquier
    # detector: lo importante es que la rejilla case con la música.
    ratios = [estimated / bpm, estimated / (bpm * 2), estimated / (bpm / 2)]
    assert any(abs(r - 1.0) < 0.06 for r in ratios), f"{bpm} -> {estimated}"


def test_los_pulsos_caen_sobre_los_golpes():
    bpm = 120.0
    signal = click_track(bpm, seconds=16.0)
    env = audio.onset_envelope(signal)
    tempo = audio.estimate_tempo(env)
    beats = audio.track_beats(env, tempo)
    assert len(beats) > 10

    period = 60.0 / bpm
    errores = []
    for beat in beats:
        distancia = abs(beat - round(beat / period) * period)
        errores.append(min(distancia, period - distancia))
    # La mediana del error debe quedar muy por debajo de medio pulso.
    assert float(np.median(errores)) < period * 0.12


def test_los_pulsos_van_en_orden_y_sin_duplicados():
    env = audio.onset_envelope(click_track(128.0))
    beats = audio.track_beats(env, audio.estimate_tempo(env))
    assert beats == sorted(beats)
    assert all(b - a > 0.05 for a, b in zip(beats, beats[1:]))


def test_sin_señal_no_hay_tempo():
    silencio = np.zeros(audio.SR * 5, dtype=np.float32)
    env = audio.onset_envelope(silencio)
    assert audio.estimate_tempo(env) == 0.0 or audio.track_beats(env, 0.0) == []


def test_audio_muy_corto_no_revienta():
    env = audio.onset_envelope(np.zeros(100, dtype=np.float32))
    assert audio.estimate_tempo(env) == 0.0
    assert audio.track_beats(env, 120.0) == [] or isinstance(audio.track_beats(env, 120.0), list)


def test_la_curva_de_energia_esta_normalizada():
    signal = click_track(120.0)
    curve = audio.energy_curve(signal)
    assert curve.size > 0
    assert 0.0 <= float(curve.min()) <= float(curve.max()) <= 1.0
    assert float(curve.max()) == pytest.approx(1.0)


def test_detecta_el_subidon():
    quiet = click_track(120.0, seconds=8.0) * 0.15
    loud = click_track(120.0, seconds=8.0)
    signal = np.concatenate([quiet, loud])
    drop = audio.find_drop(audio.energy_curve(signal))
    assert drop is not None
    assert 7.0 < drop < 10.5


def test_sin_subidon_devuelve_none():
    plano = click_track(120.0, seconds=16.0)
    assert audio.find_drop(audio.energy_curve(plano)) is None


# ── Puntos de corte ─────────────────────────────────────────


def test_los_cortes_usan_la_rejilla_de_pulsos():
    beats = [round(i * 0.5, 3) for i in range(40)]
    points = audio.cut_points(beats, beats[::4], division=2, total=10.0,
                              fallback_interval=2.0)
    assert points[0] == 0.0
    assert points == sorted(points)
    assert all(p in beats or p == 0.0 for p in points)


def test_sin_pulsos_se_usa_el_intervalo_fijo():
    points = audio.cut_points([], [], division=2, total=10.0, fallback_interval=2.5)
    assert points == [0.0, 2.5, 5.0, 7.5, 10.0]


def test_los_cortes_no_se_pasan_del_total():
    beats = [round(i * 0.5, 3) for i in range(100)]
    points = audio.cut_points(beats, [], division=1, total=6.0, fallback_interval=1.0)
    assert max(points) <= 6.0
