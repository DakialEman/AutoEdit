"""La API HTTP, contra el servidor real en memoria."""

import pytest
from fastapi.testclient import TestClient

from autoedit.app import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def project_id(client):
    response = client.post("/api/projects", json={"name": "API"})
    assert response.status_code == 200
    return response.json()["id"]


def test_estado(client):
    data = client.get("/api/health").json()
    assert "ffmpeg" in data
    assert "heuristic" in data["prompt_engines"]
    assert any(f["id"] == "capcut" for f in data["formats"])


def test_estilos(client):
    presets = client.get("/api/styles").json()["presets"]
    assert len(presets) >= 10
    assert all({"id", "name", "description"} <= set(p) for p in presets)


def test_ciclo_de_vida_de_un_proyecto(client):
    created = client.post("/api/projects", json={"name": "Temporal"}).json()
    pid = created["id"]
    assert created["name"] == "Temporal"

    listed = client.get("/api/projects").json()["projects"]
    assert any(p["id"] == pid for p in listed)

    renamed = client.patch(f"/api/projects/{pid}", json={"name": "Renombrado"}).json()
    assert renamed["name"] == "Renombrado"

    copy = client.post(f"/api/projects/{pid}/duplicate").json()
    assert copy["id"] != pid
    assert "copia" in copy["name"]

    assert client.delete(f"/api/projects/{pid}").status_code == 200
    assert client.get(f"/api/projects/{pid}").status_code == 404


def test_proyecto_inexistente(client):
    assert client.get("/api/projects/pr_nope").status_code == 404


def test_interpretar_un_prompt(client, project_id):
    data = client.post(
        f"/api/projects/{project_id}/interpret",
        json={"prompt": "vertical, rapido, blanco y negro, 20 segundos"},
    ).json()
    assert data["style"]["aspect"] == "9:16"
    assert data["style"]["grade"] == "bw"
    assert data["style"]["target_duration"] == 20
    assert data["engine"] == "heuristic"
    assert len(data["understood"]) >= 3


def test_auto_editar_sin_material_da_error_claro(client, project_id):
    response = client.post(f"/api/projects/{project_id}/autoedit", json={"prompt": "algo"})
    assert response.status_code == 400
    assert "importa" in response.json()["detail"].lower()


def test_importar_una_ruta_inexistente(client, project_id):
    data = client.post(
        f"/api/projects/{project_id}/assets/path", json={"paths": ["/no/existe.mp4"]}
    ).json()
    assert data["added"] == []
    assert data["errors"]


def test_formato_no_soportado(client, project_id, tmp_path):
    archivo = tmp_path / "documento.txt"
    archivo.write_text("hola")
    data = client.post(
        f"/api/projects/{project_id}/assets/path", json={"paths": [str(archivo)]}
    ).json()
    assert data["added"] == []
    assert "no soportado" in data["errors"][0].lower()


def test_el_explorador_lista_carpetas(client, tmp_path):
    (tmp_path / "subcarpeta").mkdir()
    data = client.get("/api/browse", params={"path": str(tmp_path)}).json()
    assert data["path"] == str(tmp_path)
    assert any(e["name"] == "subcarpeta" and e["is_dir"] for e in data["entries"])


def test_no_se_puede_servir_un_archivo_de_fuera(client, project_id):
    response = client.get(
        f"/api/projects/{project_id}/file", params={"path": "/etc/passwd"}
    )
    assert response.status_code == 403


def test_renderizar_sin_clips_da_error(client, project_id):
    response = client.post(f"/api/projects/{project_id}/render", json={"preview": True})
    assert response.status_code == 400


def test_un_trabajo_inexistente_da_404(client):
    assert client.get("/api/jobs/job_nope").status_code == 404


def test_edicion_sobre_una_linea_de_tiempo_vacia(client, project_id):
    response = client.patch(f"/api/projects/{project_id}/clips/cl_nope", json={"changes": {}})
    assert response.status_code == 400
    assert "existe" in response.json()["detail"].lower()


def test_los_textos_se_crean_y_se_borran(client, project_id):
    created = client.post(
        f"/api/projects/{project_id}/texts",
        json={"text": "Hola", "start": 0.5, "duration": 2.0},
    ).json()
    textos = [t for tr in created["timeline"]["tracks"] if tr["kind"] == "text" for t in tr["texts"]]
    assert len(textos) == 1
    text_id = textos[0]["id"]

    updated = client.patch(
        f"/api/projects/{project_id}/texts/{text_id}",
        json={"changes": {"text": "Adiós", "style": {"size": 100}}},
    ).json()
    texto = [t for tr in updated["timeline"]["tracks"] if tr["kind"] == "text" for t in tr["texts"]][0]
    assert texto["text"] == "Adiós"
    assert texto["style"]["size"] == 100

    deleted = client.delete(f"/api/projects/{project_id}/texts/{text_id}").json()
    assert not [t for tr in deleted["timeline"]["tracks"] if tr["kind"] == "text" for t in tr["texts"]]


def test_ajustes_generales_de_la_linea_de_tiempo(client, project_id):
    project = client.get(f"/api/projects/{project_id}").json()
    timeline = project["timeline"]
    timeline["music_volume"] = 0.33
    timeline["duck_music"] = False
    updated = client.patch(f"/api/projects/{project_id}", json={"timeline": timeline}).json()
    assert updated["timeline"]["music_volume"] == pytest.approx(0.33)
    assert updated["timeline"]["duck_music"] is False


def test_el_proyecto_trae_resumen_y_problemas(client, project_id):
    data = client.get(f"/api/projects/{project_id}").json()
    assert "summary" in data and "problems" in data
    assert data["problems"], "un proyecto vacío debe reportar que no hay clips"


def test_la_interfaz_se_sirve(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "AutoEdit" in response.text
