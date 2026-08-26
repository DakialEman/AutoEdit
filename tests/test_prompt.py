"""El intérprete de prompts."""

import pytest

from autoedit.ai.prompt import detect_preset, interpret_heuristic, _norm


@pytest.mark.parametrize(
    "prompt,expected",
    [
        ("algo para tiktok", "dynamic"),
        ("un montaje cinematografico", "cinematic"),
        ("vlog de mi dia", "vlog"),
        ("video de mi viaje a roma", "travel"),
        ("boda romantica con musica suave", "wedding"),
        ("trailer epico", "trailer"),
        ("montaje de skate", "sport"),
        ("presentacion de fotos", "slideshow"),
        ("entrevista a camara", "talking"),
        ("anuncio de mi producto", "promo"),
    ],
)
def test_detecta_el_estilo_base(prompt, expected):
    preset, _ = detect_preset(_norm(prompt))
    assert preset == expected


def test_la_pista_mas_temprana_gana():
    # «boda» va antes que «estetica»: manda el asunto, no el adjetivo.
    preset, _ = detect_preset(_norm("boda con un aire estetico"))
    assert preset == "wedding"


@pytest.mark.parametrize(
    "prompt,aspect",
    [
        ("vertical", "9:16"),
        ("horizontal para youtube", "16:9"),
        ("cuadrado", "1:1"),
        ("post de instagram", "4:5"),
    ],
)
def test_formato(prompt, aspect):
    assert interpret_heuristic(prompt).style.aspect == aspect


@pytest.mark.parametrize(
    "prompt,seconds",
    [
        ("de 30 segundos", 30),
        ("un video de 45s", 45),
        ("2 minutos", 120),
        ("1:30", 90),
        ("medio minuto", 30),
        ("minuto y medio", 90),
    ],
)
def test_duracion(prompt, seconds):
    assert interpret_heuristic(prompt).style.target_duration == pytest.approx(seconds)


def test_ritmo_rapido_acorta_los_clips():
    base = interpret_heuristic("")
    rapido = interpret_heuristic("muy rapido")
    assert rapido.style.target_clip < base.style.target_clip


def test_ritmo_lento_alarga_los_clips():
    base = interpret_heuristic("")
    lento = interpret_heuristic("lento y tranquilo")
    assert lento.style.target_clip > base.style.target_clip


def test_blanco_y_negro():
    assert interpret_heuristic("en blanco y negro").style.grade == "bw"


def test_sin_musica_desactiva_la_sincronia():
    style = interpret_heuristic("sin musica").style
    assert style.music_volume == 0.0
    assert style.beat_sync is False


def test_conservar_audio_original():
    style = interpret_heuristic("quiero que se escuche mi voz").style
    assert style.original_audio_volume == 1.0
    assert style.duck_music is True
    assert style.music_volume <= 0.3


def test_sin_transiciones():
    style = interpret_heuristic("cortes secos, sin transiciones").style
    assert style.transitions == ["cut"]
    assert style.transition_chance == 0.0


def test_titulo_entrecomillado_conserva_mayusculas():
    style = interpret_heuristic('con titulo "Verano 2026"').style
    assert style.text.intro_title is True
    assert style.text.intro_text == "Verano 2026"


def test_el_preset_explicito_manda_sobre_el_prompt():
    result = interpret_heuristic("algo para tiktok", base_preset="cinematic")
    assert result.base_preset == "cinematic"


def test_palabras_reconocidas_no_se_marcan_como_ignoradas():
    result = interpret_heuristic("vertical, rapido, blanco y negro, 20 segundos")
    assert result.ignored == []
    assert len(result.understood) >= 4


def test_palabras_desconocidas_si_se_reportan():
    result = interpret_heuristic("vertical con mi perro en la playa")
    assert "perro" in result.ignored


def test_prompt_vacio_devuelve_un_preset_intacto():
    result = interpret_heuristic("")
    assert result.style.id == "dynamic"
    assert result.understood == []


def test_los_presets_no_se_contaminan_entre_llamadas():
    first = interpret_heuristic("blanco y negro")
    second = interpret_heuristic("")
    assert first.style.grade == "bw"
    assert second.style.grade != "bw"
