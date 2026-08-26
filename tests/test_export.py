"""Exportadores: CapCut, FCPXML, EDL y proyecto nativo."""

import json
import xml.etree.ElementTree as ET

import pytest

from autoedit.export import capcut, edl, fcpxml
from autoedit.export.common import flatten, to_microseconds


# ── Aplanado ────────────────────────────────────────────────


def test_el_aplanado_elimina_los_solapes(edited):
    flat = flatten(edited)
    for previous, current in zip(flat.video, flat.video[1:]):
        assert current.timeline_start == pytest.approx(previous.timeline_end, abs=0.01)


def test_el_aplanado_conserva_la_duracion_total(edited):
    flat = flatten(edited)
    assert flat.duration == pytest.approx(edited.timeline.duration, abs=0.05)


def test_al_aplanar_una_transicion_se_recorta_la_cabecera(edited):
    flat = flatten(edited)
    con_transicion = [c for c in flat.video if c.original_transition_duration > 0]
    if not con_transicion:
        pytest.skip("este montaje no tiene transiciones")
    for clip in con_transicion:
        assert clip.original_transition != "cut"
        assert clip.timeline_duration > 0


def test_el_aplanado_avisa_de_las_transiciones_perdidas(edited):
    flat = flatten(edited)
    if any(c.original_transition_duration > 0 for c in flat.video):
        assert flat.notes


# ── CapCut ──────────────────────────────────────────────────


def test_borrador_de_capcut_completo(edited, tmp_path):
    report = capcut.export_capcut(edited, tmp_path)
    folder = tmp_path / report["folder"].split("/")[-1]
    assert (folder / "draft_content.json").exists()
    assert (folder / "draft_meta_info.json").exists()
    assert (folder / "AUTOEDIT.md").exists()

    content = json.loads((folder / "draft_content.json").read_text("utf-8"))
    assert content["canvas_config"]["width"] == edited.timeline.width
    assert content["canvas_config"]["height"] == edited.timeline.height
    assert content["fps"] == float(edited.timeline.fps)
    assert content["duration"] == to_microseconds(flatten(edited).duration)


def test_capcut_tiene_una_pista_por_tipo(edited, tmp_path):
    report = capcut.export_capcut(edited, tmp_path)
    content = json.loads((__import__("pathlib").Path(report["folder"]) / "draft_content.json").read_text("utf-8"))
    tipos = [t["type"] for t in content["tracks"]]
    assert tipos[0] == "video"
    assert "audio" in tipos


def test_los_segmentos_de_capcut_no_se_solapan(edited, tmp_path):
    from pathlib import Path

    report = capcut.export_capcut(edited, tmp_path)
    content = json.loads((Path(report["folder"]) / "draft_content.json").read_text("utf-8"))
    for track in content["tracks"]:
        rangos = sorted(
            (s["target_timerange"]["start"], s["target_timerange"]["duration"])
            for s in track["segments"]
        )
        for (start_a, dur_a), (start_b, _) in zip(rangos, rangos[1:]):
            assert start_a + dur_a <= start_b + 1, track["type"]


def test_cada_segmento_referencia_un_material_existente(edited, tmp_path):
    from pathlib import Path

    report = capcut.export_capcut(edited, tmp_path)
    content = json.loads((Path(report["folder"]) / "draft_content.json").read_text("utf-8"))
    materiales = set()
    for grupo in content["materials"].values():
        for item in grupo:
            if isinstance(item, dict) and "id" in item:
                materiales.add(item["id"])
    for track in content["tracks"]:
        for segment in track["segments"]:
            assert segment["material_id"] in materiales
            for ref in segment["extra_material_refs"]:
                assert ref in materiales


def test_capcut_usa_rutas_absolutas(edited, tmp_path):
    from pathlib import Path

    report = capcut.export_capcut(edited, tmp_path)
    content = json.loads((Path(report["folder"]) / "draft_content.json").read_text("utf-8"))
    for material in content["materials"]["videos"] + content["materials"]["audios"]:
        assert material["path"].startswith("/") or ":" in material["path"][:3]


def test_capcut_en_zip(edited, tmp_path):
    import zipfile

    destino = tmp_path / "proyecto.zip"
    report = capcut.export_capcut_zip(edited, destino)
    assert destino.exists()
    with zipfile.ZipFile(destino) as zf:
        nombres = "\n".join(zf.namelist())
    assert "draft_content.json" in nombres
    assert report["clips"] > 0


def test_capcut_falla_con_una_linea_de_tiempo_vacia(project, tmp_path):
    with pytest.raises(ValueError):
        capcut.export_capcut(project, tmp_path)


# ── FCPXML ──────────────────────────────────────────────────


def test_fcpxml_es_xml_valido(edited, tmp_path):
    destino = tmp_path / "montaje.fcpxml"
    fcpxml.export_fcpxml(edited, destino)
    root = ET.parse(destino).getroot()
    assert root.tag == "fcpxml"
    assert root.get("version") == "1.9"


def test_fcpxml_declara_todos_los_recursos(edited, tmp_path):
    destino = tmp_path / "montaje.fcpxml"
    fcpxml.export_fcpxml(edited, destino)
    root = ET.parse(destino).getroot()
    recursos = {a.get("id") for a in root.findall(".//asset")}
    spine = root.find(".//spine")
    for clip in spine:
        ref = clip.get("ref")
        if ref:
            assert ref in recursos


def test_fcpxml_usa_tiempos_racionales(edited, tmp_path):
    destino = tmp_path / "montaje.fcpxml"
    fcpxml.export_fcpxml(edited, destino)
    root = ET.parse(destino).getroot()
    fps = edited.timeline.fps
    for clip in root.find(".//spine"):
        offset = clip.get("offset")
        assert offset.endswith("s")
        assert offset.split("/")[-1] == f"{fps}s"


def test_fcpxml_escapa_los_nombres(edited, tmp_path):
    edited.assets[0].name = 'raro & "peligroso" <name>'
    destino = tmp_path / "montaje.fcpxml"
    fcpxml.export_fcpxml(edited, destino)
    ET.parse(destino)  # basta con que parsee


# ── EDL y proyecto ──────────────────────────────────────────


def test_edl_tiene_una_entrada_por_clip(edited, tmp_path):
    destino = tmp_path / "montaje.edl"
    edl.export_edl(edited, destino)
    texto = destino.read_text("utf-8")
    flat = flatten(edited)
    assert texto.startswith("TITLE:")
    assert texto.count("FROM CLIP NAME") == len(flat.video) + len(flat.audio)


def test_los_timecodes_del_edl_son_validos(edited, tmp_path):
    import re

    destino = tmp_path / "montaje.edl"
    edl.export_edl(edited, destino)
    fps = edited.timeline.fps
    for match in re.finditer(r"(\d{2}):(\d{2}):(\d{2}):(\d{2})", destino.read_text("utf-8")):
        _, minutos, segundos, frames = (int(g) for g in match.groups())
        assert minutos < 60 and segundos < 60 and frames < fps


def test_ida_y_vuelta_del_proyecto(edited, tmp_path):
    destino = tmp_path / "proyecto.autoedit.json"
    edl.export_project_json(edited, destino)
    recuperado = edl.import_project_json(destino.read_text("utf-8"))
    assert recuperado.id != edited.id          # id nuevo para no pisar el original
    assert recuperado.name == edited.name
    assert len(recuperado.assets) == len(edited.assets)
    assert recuperado.timeline.duration == pytest.approx(edited.timeline.duration)


def test_escaleta(edited):
    texto = edl.build_shotlist(edited)
    assert edited.name in texto
    assert "| # |" in texto
