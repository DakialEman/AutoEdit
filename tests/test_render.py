"""Prueba de integración: material real, FFmpeg real, MP4 real.

Es la única suite que necesita FFmpeg. Genera su propio material con
`lavfi`, así que no depende de archivos externos. Se salta sola si no hay
FFmpeg disponible.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from autoedit import editing, storage
from autoedit.ai import planner
from autoedit.ai.styles import get_preset
from autoedit.config import find_ffmpeg
from autoedit.export import capcut
from autoedit.render import render_timeline

try:
    FFMPEG = find_ffmpeg()
except RuntimeError:
    FFMPEG = None

pytestmark = pytest.mark.skipif(FFMPEG is None, reason="hace falta FFmpeg")


def _run(args: list[str]) -> None:
    subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-y", *args],
                   check=True, timeout=300)


@pytest.fixture(scope="module")
def material(tmp_path_factory) -> Path:
    """Un par de vídeos, una foto y una pista con pulso claro."""
    directory = tmp_path_factory.mktemp("material")
    _run(["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=6",
          "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
          "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
          str(directory / "uno.mp4")])
    _run(["-f", "lavfi", "-i", "smptebars=size=360x640:rate=25:duration=5",
          "-c:v", "libx264", "-pix_fmt", "yuv420p", str(directory / "dos.mp4")])
    _run(["-f", "lavfi", "-i", "color=c=orange:size=800x600", "-frames:v", "1",
          str(directory / "foto.jpg")])
    _run(["-f", "lavfi",
          "-i", "aevalsrc='0.8*sin(2*PI*180*t)*exp(-9*mod(t,0.5))':d=20:s=44100",
          "-c:a", "libmp3lame", str(directory / "tema.mp3")])
    return directory


@pytest.fixture(scope="module")
def montado(material):
    project = storage.create_project("Integración")
    added, errors = storage.import_any(project, [str(material)])
    assert not errors and len(added) == 4
    storage.analyze_pending(project)

    style = get_preset("dynamic")
    style.target_duration = 6.0
    style.aspect = "9:16"
    project.style = style
    project.timeline = planner.build_timeline(project, style)
    editing.normalize(project, project.timeline)
    storage.save_project(project)
    return project


def probe(path: Path):
    from autoedit.ffmpeg import probe as _probe

    return _probe(path)


# ── Análisis ────────────────────────────────────────────────


def test_el_analisis_rellena_los_datos(montado):
    videos = [a for a in montado.assets if a.kind == "video"]
    assert videos
    for asset in videos:
        assert asset.duration > 0
        assert asset.width > 0 and asset.height > 0
        assert asset.analysis.analyzed
        assert asset.thumbnail and Path(asset.thumbnail).exists()

    music = next(a for a in montado.assets if a.kind == "audio")
    assert music.analysis.tempo > 0
    assert len(music.analysis.beats) > 10
    assert music.waveform


def test_detecta_el_audio_de_los_videos(montado):
    con_audio = {a.name: a.has_audio for a in montado.assets if a.kind == "video"}
    assert con_audio["uno.mp4"] is True
    assert con_audio["dos.mp4"] is False


# ── Render ──────────────────────────────────────────────────


@pytest.fixture(scope="module")
def renderizado(montado, tmp_path_factory):
    destino = tmp_path_factory.mktemp("salida") / "video.mp4"
    result = render_timeline(montado, destino, preview=True)
    return result


def test_el_render_produce_un_mp4_valido(renderizado):
    assert renderizado.path.exists()
    assert renderizado.path.stat().st_size > 5000
    info = probe(renderizado.path)
    assert info.has_video
    assert info.has_audio          # la música tiene que llegar al archivo


def test_la_duracion_del_archivo_coincide_con_la_linea_de_tiempo(montado, renderizado):
    info = probe(renderizado.path)
    assert info.duration == pytest.approx(montado.timeline.duration, abs=0.25)


def test_el_lienzo_respeta_el_formato_vertical(renderizado):
    info = probe(renderizado.path)
    assert info.display_height > info.display_width


def test_la_cache_se_reutiliza_en_el_segundo_render(montado, tmp_path):
    storage.clear_cache(montado.id)
    primero = render_timeline(montado, tmp_path / "a.mp4", preview=True)
    assert primero.reused == 0                       # caché vacía
    segundo = render_timeline(montado, tmp_path / "b.mp4", preview=True)
    assert segundo.segments == primero.segments
    assert segundo.reused == segundo.segments        # nada que reprocesar


def test_cambiar_un_clip_solo_reprocesa_ese_clip(montado, tmp_path):
    render_timeline(montado, tmp_path / "base.mp4", preview=True)
    clip = montado.timeline.track("video").clips[0]
    editing.update_clip(montado, montado.timeline, clip.id, {"grade": "bw"})
    result = render_timeline(montado, tmp_path / "cambiado.mp4", preview=True)
    assert result.reused == result.segments - 1


def test_los_textos_se_componen(montado, tmp_path):
    editing.add_text(montado.timeline, "HOLA", 0.3, 2.0)
    result = render_timeline(montado, tmp_path / "con-texto.mp4", preview=True)
    assert result.path.exists()
    assert probe(result.path).has_video


def test_renderizar_sin_clips_falla_con_un_mensaje_claro(montado, tmp_path):
    vacio = montado.model_copy(deep=True)
    vacio.timeline.tracks = []
    with pytest.raises(ValueError, match="clips"):
        render_timeline(vacio, tmp_path / "vacio.mp4")


def test_un_archivo_que_ya_no_esta_da_un_error_util(montado, tmp_path):
    roto = montado.model_copy(deep=True)
    roto.assets[0].path = "/material/desaparecido.mp4"
    clip = roto.timeline.track("video").clips[0]
    clip.asset_id = roto.assets[0].id
    with pytest.raises(ValueError, match="No se encuentra"):
        render_timeline(roto, tmp_path / "roto.mp4")


# ── Exportación con material real ───────────────────────────


def test_el_borrador_de_capcut_apunta_a_archivos_que_existen(montado, tmp_path):
    import json

    report = capcut.export_capcut(montado, tmp_path)
    content = json.loads((Path(report["folder"]) / "draft_content.json").read_text("utf-8"))
    assert report["missing"] == []
    for material in content["materials"]["videos"] + content["materials"]["audios"]:
        assert Path(material["path"]).exists()
