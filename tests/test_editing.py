"""Edición manual: invariantes de la línea de tiempo."""

import pytest

from autoedit import editing
from autoedit.models import Transition


def clips(project):
    return project.timeline.track("video").sorted_clips()


def assert_encadenado(project):
    """Tras cualquier operación los clips siguen pegados unos a otros."""
    lista = clips(project)
    assert lista[0].start == 0.0
    for previous, current in zip(lista, lista[1:]):
        overlap = current.transition_in.duration
        assert current.start == pytest.approx(previous.start + previous.duration - overlap, abs=0.01)
        assert current.transition_in.duration <= min(previous.duration, current.duration) / 3 + 1e-6


def test_el_montaje_generado_ya_cumple_el_invariante(edited):
    assert_encadenado(edited)


def test_mover_un_clip_lo_recoloca(edited):
    original = [c.id for c in clips(edited)]
    editing.move_clip(edited, edited.timeline, original[0], 3)
    nuevo = [c.id for c in clips(edited)]
    assert nuevo.index(original[0]) == 3
    assert sorted(nuevo) == sorted(original)
    assert_encadenado(edited)


def test_mover_al_final(edited):
    original = [c.id for c in clips(edited)]
    editing.move_clip(edited, edited.timeline, original[0], len(original) - 1)
    assert clips(edited)[-1].id == original[0]
    assert_encadenado(edited)


def test_partir_un_clip_conserva_la_duracion_total(edited):
    total = edited.timeline.duration
    objetivo = clips(edited)[2]
    duracion_original = objetivo.duration
    at = objetivo.start + objetivo.duration / 2
    primero, segundo = editing.split_clip(edited, edited.timeline, objetivo.id, at)
    assert primero.duration + segundo.duration == pytest.approx(duracion_original, abs=0.01)
    assert segundo.in_point == pytest.approx(primero.in_point + primero.duration * primero.speed, abs=0.01)
    assert edited.timeline.duration == pytest.approx(total, abs=0.02)
    assert_encadenado(edited)


def test_no_se_puede_partir_pegado_al_borde(edited):
    objetivo = clips(edited)[1]
    with pytest.raises(editing.EditError):
        editing.split_clip(edited, edited.timeline, objetivo.id, objetivo.start + 0.01)


def test_borrar_un_clip_acorta_el_montaje(edited):
    total = edited.timeline.duration
    objetivo = clips(edited)[1]
    editing.delete_clip(edited, edited.timeline, objetivo.id)
    assert objetivo.id not in [c.id for c in clips(edited)]
    assert edited.timeline.duration < total
    assert_encadenado(edited)


def test_un_clip_bloqueado_no_se_borra(edited):
    objetivo = clips(edited)[1]
    objetivo.locked = True
    with pytest.raises(editing.EditError):
        editing.delete_clip(edited, edited.timeline, objetivo.id)


def test_duplicar_un_clip(edited):
    objetivo = clips(edited)[0]
    copia = editing.duplicate_clip(edited, edited.timeline, objetivo.id)
    assert copia.id != objetivo.id
    assert copia.asset_id == objetivo.asset_id
    assert clips(edited)[1].id == copia.id
    assert_encadenado(edited)


def test_anadir_un_clip_desde_la_biblioteca(edited):
    asset = next(a for a in edited.assets if a.kind == "video")
    antes = len(clips(edited))
    editing.add_clip(edited, edited.timeline, asset.id, index=0)
    assert len(clips(edited)) == antes + 1
    assert clips(edited)[0].asset_id == asset.id
    assert_encadenado(edited)


def test_no_se_puede_anadir_audio_a_la_pista_de_video(edited):
    audio = next(a for a in edited.assets if a.kind == "audio")
    with pytest.raises(editing.EditError):
        editing.add_clip(edited, edited.timeline, audio.id)


def test_la_duracion_no_puede_exceder_el_material(edited):
    objetivo = clips(edited)[0]
    asset = edited.asset(objetivo.asset_id)
    if asset.kind != "video":
        pytest.skip("hace falta un clip de vídeo")
    editing.set_duration(edited, edited.timeline, objetivo.id, 9999)
    disponible = (asset.duration - objetivo.in_point) / objetivo.speed
    assert objetivo.duration <= disponible + 0.01


def test_el_punto_de_entrada_se_queda_dentro_del_material(edited):
    objetivo = next(c for c in clips(edited) if edited.asset(c.asset_id).kind == "video")
    asset = edited.asset(objetivo.asset_id)
    editing.set_in_point(edited, edited.timeline, objetivo.id, 9999)
    assert objetivo.in_point + objetivo.duration * objetivo.speed <= asset.duration + 0.01


def test_cambiar_la_transicion(edited):
    objetivo = clips(edited)[2]
    editing.update_clip(edited, edited.timeline, objetivo.id,
                        {"transition": {"kind": "dissolve", "duration": 0.5}})
    assert objetivo.transition_in.kind == "dissolve"
    assert_encadenado(edited)


def test_un_corte_seco_no_deja_duracion_residual(edited):
    objetivo = clips(edited)[2]
    editing.update_clip(edited, edited.timeline, objetivo.id, {"transition": {"kind": "cut"}})
    assert objetivo.transition_in.duration == 0.0


def test_aplicar_a_todos(edited):
    editing.apply_to_all(edited, edited.timeline, {"grade": "bw"})
    assert all(c.grade == "bw" for c in clips(edited))


def test_la_musica_sigue_a_la_duracion_del_video(edited):
    editing.delete_clip(edited, edited.timeline, clips(edited)[0].id)
    music = edited.timeline.track("music")
    assert music.clips[0].duration == pytest.approx(edited.timeline.duration, abs=0.05)


def test_textos(edited):
    texto = editing.add_text(edited.timeline, "Hola", 1.0, 2.0)
    assert texto.text == "Hola"
    editing.update_text(edited.timeline, texto.id, {"text": "Adiós", "style": {"size": 90}})
    assert texto.text == "Adiós"
    assert texto.style.size == 90
    editing.delete_text(edited.timeline, texto.id)
    with pytest.raises(editing.EditError):
        editing.update_text(edited.timeline, texto.id, {"text": "x"})


def test_cambiar_la_musica(edited):
    audio = next(a for a in edited.assets if a.kind == "audio")
    editing.set_music(edited, edited.timeline, audio.id)
    assert edited.meta["music_asset_id"] == audio.id
    editing.set_music(edited, edited.timeline, None)
    assert not edited.timeline.track("music").clips


def test_validar_detecta_una_linea_de_tiempo_vacia(project):
    problemas = editing.validate(project, project.timeline)
    assert problemas and "clip" in problemas[0].lower()


def test_una_transicion_gigante_se_recorta_sola(edited):
    objetivo = clips(edited)[2]
    objetivo.transition_in = Transition(kind="dissolve", duration=99)
    editing.normalize(edited, edited.timeline)
    assert_encadenado(edited)


# ── Pistas de audio ─────────────────────────────────────────


def test_se_pueden_apilar_varias_pistas_de_audio(edited):
    audio = next(a for a in edited.assets if a.kind == "audio")
    primera = editing.add_audio_track(edited.timeline, "Voz")
    segunda = editing.add_audio_track(edited.timeline)
    assert primera.id != segunda.id
    assert segunda.name == "Audio 2"

    editing.add_audio_clip(edited, edited.timeline, primera.id, audio.id, start=2.0)
    editing.add_audio_clip(edited, edited.timeline, segunda.id, audio.id, start=5.5)
    assert primera.clips[0].start == 2.0
    assert segunda.clips[0].start == 5.5


def test_las_pistas_nuevas_no_se_recolocan_solas(edited):
    """La música se ajusta al vídeo; lo que colocas tú se queda donde lo pongas."""
    audio = next(a for a in edited.assets if a.kind == "audio")
    track = editing.add_audio_track(edited.timeline)
    editing.add_audio_clip(edited, edited.timeline, track.id, audio.id, start=3.0)
    editing.normalize(edited, edited.timeline)
    assert track.clips[0].start == 3.0


def test_mover_un_audio_en_el_tiempo(edited):
    audio = next(a for a in edited.assets if a.kind == "audio")
    track = editing.add_audio_track(edited.timeline)
    clip = editing.add_audio_clip(edited, edited.timeline, track.id, audio.id, start=1.0)
    editing.update_clip(edited, edited.timeline, clip.id, {"start": 4.25})
    assert clip.start == 4.25


def test_un_clip_de_video_no_se_puede_mover_asi(edited):
    """La pista de vídeo va encadenada: su posición la calcula el relayout."""
    clip = clips(edited)[1]
    antes = clip.start
    editing.update_clip(edited, edited.timeline, clip.id, {"start": 99})
    assert clip.start == antes


def test_todas_las_pistas_llegan_a_la_mezcla(edited):
    from autoedit.render.renderer import collect_audio

    audio = next(a for a in edited.assets if a.kind == "audio")
    track = editing.add_audio_track(edited.timeline)
    editing.add_audio_clip(edited, edited.timeline, track.id, audio.id, start=1.5)

    piezas = collect_audio(edited, edited.timeline)
    assert len(piezas) >= 2
    assert any(p.is_music for p in piezas)
    assert any(not p.is_music and p.start == 1.5 for p in piezas)


def test_silenciar_una_pista_la_saca_de_la_mezcla(edited):
    from autoedit.render.renderer import collect_audio

    audio = next(a for a in edited.assets if a.kind == "audio")
    track = editing.add_audio_track(edited.timeline)
    editing.add_audio_clip(edited, edited.timeline, track.id, audio.id, start=1.0)
    assert len(collect_audio(edited, edited.timeline)) >= 2

    editing.update_track(edited.timeline, track.id, {"muted": True})
    assert not any(p.start == 1.0 and not p.is_music
                   for p in collect_audio(edited, edited.timeline))


def test_borrar_una_pista(edited):
    track = editing.add_audio_track(edited.timeline)
    editing.remove_track(edited.timeline, track.id)
    assert all(t.id != track.id for t in edited.timeline.tracks)


def test_la_pista_de_video_no_se_puede_borrar(edited):
    video = edited.timeline.track("video")
    with pytest.raises(editing.EditError):
        editing.remove_track(edited.timeline, video.id)


def test_no_se_puede_poner_un_video_sin_audio_en_una_pista_de_audio(edited):
    mudo = next(a for a in edited.assets if a.kind == "image")
    track = editing.add_audio_track(edited.timeline)
    with pytest.raises(editing.EditError):
        editing.add_audio_clip(edited, edited.timeline, track.id, mudo.id)
