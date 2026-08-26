"""El planificador: ritmo, duración y uso del material."""

import pytest

from autoedit.ai import planner
from autoedit.ai.styles import PRESETS, get_preset
from autoedit.models import resolution_for


def video_clips(timeline):
    track = timeline.track("video")
    return track.sorted_clips() if track else []


def test_genera_una_linea_de_tiempo(project):
    timeline = planner.build_timeline(project, get_preset("dynamic"))
    assert video_clips(timeline)
    assert timeline.duration > 0


def test_respeta_la_duracion_objetivo(project):
    style = get_preset("dynamic")
    style.target_duration = 20.0
    timeline = planner.build_timeline(project, style)
    # Los cortes caen sobre pulsos, así que se admite un margen pequeño.
    assert timeline.duration == pytest.approx(20.0, abs=0.6)


def test_no_se_pasa_de_la_duracion_objetivo(project):
    style = get_preset("cinematic")
    style.target_duration = 12.0
    timeline = planner.build_timeline(project, style)
    assert timeline.duration <= 12.05


def test_el_formato_define_el_lienzo(project):
    for aspect in ("9:16", "16:9", "1:1"):
        style = get_preset("dynamic")
        style.aspect = aspect
        timeline = planner.build_timeline(project, style)
        assert (timeline.width, timeline.height) == resolution_for(aspect)


def test_los_clips_van_encadenados_sin_huecos(project):
    timeline = planner.build_timeline(project, get_preset("travel"))
    clips = video_clips(timeline)
    for previous, current in zip(clips, clips[1:]):
        overlap = current.transition_in.duration
        assert current.start == pytest.approx(previous.start + previous.duration - overlap, abs=0.01)


def test_una_transicion_nunca_se_come_un_tercio_del_clip(project):
    timeline = planner.build_timeline(project, get_preset("slideshow"))
    clips = video_clips(timeline)
    for previous, current in zip(clips, clips[1:]):
        limit = min(previous.duration, current.duration) / 3 + 1e-6
        assert current.transition_in.duration <= limit


def test_el_primer_clip_nunca_lleva_transicion(project):
    timeline = planner.build_timeline(project, get_preset("slideshow"))
    assert video_clips(timeline)[0].transition_in.kind == "cut"


def test_los_cortes_caen_sobre_los_pulsos(project):
    style = get_preset("beatsync")
    style.target_duration = 20.0
    timeline = planner.build_timeline(project, style)
    music = planner.pick_music(project)
    beats = set(round(b, 2) for b in music.analysis.beats)
    clips = video_clips(timeline)
    # Con beat sync la mayoría de los cortes debe coincidir con un pulso.
    aligned = sum(1 for c in clips[1:] if round(c.start + c.transition_in.duration, 2) in beats)
    assert aligned >= len(clips[1:]) * 0.7


def test_usa_todo_el_material_disponible(project):
    style = get_preset("slideshow")
    style.target_duration = 40.0
    timeline = planner.build_timeline(project, style)
    usados = {c.asset_id for c in video_clips(timeline)}
    disponibles = {a.id for a in planner.visual_assets(project)}
    assert usados == disponibles


def test_no_repite_el_mismo_tramo_mientras_quede_material(project):
    style = get_preset("dynamic")
    style.target_duration = 12.0
    timeline = planner.build_timeline(project, style)
    por_asset: dict[str, list[tuple[float, float]]] = {}
    for clip in video_clips(timeline):
        por_asset.setdefault(clip.asset_id, []).append(
            (clip.in_point, clip.in_point + clip.duration * clip.speed)
        )
    for tramos in por_asset.values():
        tramos.sort()
        for (_, fin), (inicio, _) in zip(tramos, tramos[1:]):
            assert inicio >= fin - 0.05


def test_las_fotos_siempre_llevan_movimiento(project):
    style = get_preset("slideshow")
    timeline = planner.build_timeline(project, style)
    fotos = {a.id for a in project.assets if a.kind == "image"}
    for clip in video_clips(timeline):
        if clip.asset_id in fotos:
            assert clip.effect != "none"


def test_la_musica_se_ajusta_a_la_duracion_del_video(project):
    timeline = planner.build_timeline(project, get_preset("dynamic"))
    music_track = timeline.track("music")
    assert music_track and music_track.clips
    assert music_track.clips[0].duration == pytest.approx(timeline.duration, abs=0.1)


def test_sin_musica_no_hay_pista_de_musica(project):
    project.assets = [a for a in project.assets if a.kind != "audio"]
    timeline = planner.build_timeline(project, get_preset("dynamic"))
    music_track = timeline.track("music")
    assert not (music_track and music_track.clips)


def test_sin_material_visual_no_falla(project):
    project.assets = [a for a in project.assets if a.kind == "audio"]
    timeline = planner.build_timeline(project, get_preset("dynamic"))
    assert video_clips(timeline) == []


def test_rebarajar_cambia_el_montaje(project):
    project.style = get_preset("dynamic")
    project.style.target_duration = 20.0
    first = planner.build_timeline(project, project.style)
    project.timeline = first
    second = planner.reshuffle(project, seed=999)
    firma = lambda tl: [(c.asset_id, round(c.in_point, 2)) for c in video_clips(tl)]
    assert firma(first) != firma(second)


@pytest.mark.parametrize("preset_id", list(PRESETS))
def test_todos_los_presets_producen_algo_valido(project, preset_id):
    timeline = planner.build_timeline(project, get_preset(preset_id))
    clips = video_clips(timeline)
    assert clips, preset_id
    assert timeline.duration > 0
    for clip in clips:
        assert clip.duration > 0
        assert clip.in_point >= 0


def test_el_resumen_cuadra_con_la_linea_de_tiempo(edited):
    summary = planner.summarize(edited.timeline)
    assert summary["clips"] == len(video_clips(edited.timeline))
    assert summary["duration"] == pytest.approx(edited.timeline.duration)
    assert summary["has_music"] is True
