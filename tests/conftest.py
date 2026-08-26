"""Fixtures compartidas.

Casi todos los tests trabajan con un proyecto sintético: assets construidos a
mano, con su análisis ya relleno. Así se prueba la lógica de montaje, edición y
exportación sin depender de FFmpeg ni de archivos reales.
"""

from __future__ import annotations

import os
import tempfile

import pytest

# La configuración lee el entorno al importarse, así que se fija antes.
_TMP = tempfile.mkdtemp(prefix="autoedit-tests-")
os.environ.setdefault("AUTOEDIT_HOME", _TMP)

from autoedit.models import Asset, AssetAnalysis, Highlight, Project  # noqa: E402


def make_video(name: str, duration: float, width: int = 1920, height: int = 1080,
               has_audio: bool = True, score: float = 0.6) -> Asset:
    highlights = []
    step = max(2.0, duration / 5)
    t = 0.0
    while t + 2.0 <= duration:
        highlights.append(Highlight(start=round(t, 2), end=round(t + 2.0, 2), score=score))
        t += step
    return Asset(
        kind="video",
        path=f"/material/{name}",
        name=name,
        duration=duration,
        width=width,
        height=height,
        fps=30,
        has_audio=has_audio,
        has_video=True,
        size=1000,
        analysis=AssetAnalysis(
            analyzed=True,
            highlights=highlights,
            quality_score=score,
            motion=0.3,
            scenes=[],
        ),
    )


def make_image(name: str, width: int = 1600, height: int = 1200) -> Asset:
    return Asset(
        kind="image",
        path=f"/material/{name}",
        name=name,
        duration=0.0,
        width=width,
        height=height,
        has_video=True,
        size=500,
        analysis=AssetAnalysis(analyzed=True, quality_score=0.7),
    )


def make_music(name: str = "tema.mp3", duration: float = 60.0, bpm: float = 120.0) -> Asset:
    period = 60.0 / bpm
    beats = [round(i * period, 3) for i in range(int(duration / period))]
    return Asset(
        kind="audio",
        path=f"/material/{name}",
        name=name,
        duration=duration,
        has_audio=True,
        size=800,
        analysis=AssetAnalysis(
            analyzed=True,
            beats=beats,
            downbeats=beats[::4],
            tempo=bpm,
            quality_score=0.8,
        ),
    )


@pytest.fixture
def project() -> Project:
    """Proyecto con tres vídeos, dos fotos y una canción de 120 BPM."""
    p = Project(name="Proyecto de prueba")
    p.assets = [
        make_video("a.mp4", 30.0, score=0.8),
        make_video("b.mp4", 20.0, score=0.5),
        make_video("c.mp4", 12.0, has_audio=False, score=0.65),
        make_image("foto1.jpg"),
        make_image("foto2.png", 1080, 1920),
        make_music(),
    ]
    return p


@pytest.fixture
def edited(project):
    """Proyecto con una línea de tiempo ya generada."""
    from autoedit import editing
    from autoedit.ai import planner
    from autoedit.ai.styles import get_preset

    style = get_preset("dynamic")
    style.target_duration = 15.0
    project.style = style
    project.timeline = planner.build_timeline(project, style)
    editing.normalize(project, project.timeline)
    return project
