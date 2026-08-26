"""Interpretación del prompt con un modelo de lenguaje (opcional).

AutoEdit funciona sin esto: el intérprete de reglas de `prompt.py` es el motor
por defecto. Este módulo solo entra en juego si el usuario configura un modelo,
y si algo falla siempre se vuelve a las reglas — nunca se queda sin montaje.

Motores soportados:

* ``anthropic`` — API de Claude. Requiere ``pip install anthropic`` y una
  credencial (``ANTHROPIC_API_KEY`` o un perfil de ``ant auth login``).
* ``ollama``    — modelo local vía la API HTTP de Ollama. 100% offline.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Literal, Optional

from pydantic import BaseModel, Field

from ..config import SETTINGS
from ..models import PromptResult, StyleSpec
from .styles import PRESETS, get_preset

Pace = Literal["muy_lento", "lento", "medio", "rapido", "muy_rapido"]
Level = Literal["ninguna", "pocas", "muchas"]
FxLevel = Literal["ninguno", "sutil", "intenso"]


class StyleDirectives(BaseModel):
    """Salida estructurada del modelo.

    Deliberadamente pequeña y cerrada: el modelo elige entre opciones
    conocidas y nosotros las traducimos a un `StyleSpec` válido. Así una
    respuesta rara nunca puede romper el planificador.
    """

    base_preset: str = Field(description="Uno de: " + ", ".join(PRESETS))
    aspect: Literal["9:16", "16:9", "1:1", "4:5", "21:9"] = "9:16"
    pace: Pace = "medio"
    grade: Literal[
        "none", "cinematic", "teal_orange", "warm", "cold", "vintage", "vivid", "bw", "faded", "night"
    ] = "none"
    beat_sync: bool = True
    transitions: Level = "pocas"
    effects: FxLevel = "sutil"
    keep_original_audio: bool = False
    music_volume: float = 0.8
    target_duration_seconds: float = Field(0, description="0 = decidir automáticamente")
    order: Literal["chronological", "by_score", "energy_ramp", "shuffle"] = "by_score"
    intro_title: str = Field("", description="Título de apertura; cadena vacía si no procede")
    captions: bool = False
    summary: str = Field("", description="Una frase, en el idioma del usuario, explicando el montaje")


SYSTEM_PROMPT = """Eres el cerebro de un editor de vídeo automático.
Recibes la descripción de un usuario y devuelves los ajustes de montaje.
Reglas:
- Elige el `base_preset` que mejor encaje con la intención.
- No inventes un título si el usuario no pidió texto en pantalla.
- `music_volume` va de 0 (sin música) a 1.
- Si el usuario menciona una duración, conviértela a segundos.
- El `summary` va en el mismo idioma que el usuario, en una sola frase."""

PACE_FACTOR: dict[str, float] = {
    "muy_lento": 2.2,
    "lento": 1.5,
    "medio": 1.0,
    "rapido": 0.65,
    "muy_rapido": 0.42,
}


# --------------------------------------------------------------------------
# Selección de motor
# --------------------------------------------------------------------------


def available_engines() -> list[str]:
    engines = ["heuristic"]
    if _anthropic_ready():
        engines.append("anthropic")
    if _ollama_ready():
        engines.append("ollama")
    return engines


def _anthropic_ready() -> bool:
    import importlib.util

    if importlib.util.find_spec("anthropic") is None:
        return False
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    # `ant auth login` deja un perfil que el SDK lee solo.
    from pathlib import Path

    return (Path.home() / ".config" / "anthropic").exists()


def _ollama_ready() -> bool:
    try:
        with urllib.request.urlopen(f"{SETTINGS.ollama_url}/api/tags", timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        return False


def resolve_engine(requested: str) -> str:
    if requested in ("anthropic", "ollama", "heuristic"):
        return requested if requested == "heuristic" or requested in available_engines() else "heuristic"
    # "auto": preferimos lo local, y si no hay, la nube.
    engines = available_engines()
    for candidate in ("ollama", "anthropic"):
        if candidate in engines:
            return candidate
    return "heuristic"


# --------------------------------------------------------------------------
# Traducción de directivas a StyleSpec
# --------------------------------------------------------------------------


def directives_to_style(d: StyleDirectives) -> StyleSpec:
    preset_id = d.base_preset if d.base_preset in PRESETS else "dynamic"
    style = get_preset(preset_id)
    style.id = "custom"
    style.name = f"{PRESETS[preset_id].name} (IA)"
    style.aspect = d.aspect
    style.grade = d.grade
    style.beat_sync = d.beat_sync

    factor = PACE_FACTOR.get(d.pace, 1.0)
    style.min_clip = round(max(0.25, style.min_clip * factor), 3)
    style.max_clip = round(max(style.min_clip + 0.2, style.max_clip * factor), 3)
    style.target_clip = round(max(style.min_clip, min(style.max_clip, style.target_clip * factor)), 3)

    if d.transitions == "ninguna":
        style.transitions, style.transition_chance = ["cut"], 0.0
    elif d.transitions == "muchas":
        style.transitions = [t for t in style.transitions if t != "cut"] or ["dissolve", "fade"]
        style.transition_chance = 0.85
    else:
        style.transition_chance = min(style.transition_chance or 0.3, 0.4)

    if d.effects == "ninguno":
        style.effects, style.effect_chance = ["none"], 0.0
    elif d.effects == "intenso":
        style.effects = ["zoom_punch", "kenburns_in", "slow_drift"]
        style.effect_chance = 0.85
    else:
        style.effect_chance = min(style.effect_chance or 0.4, 0.5)

    style.original_audio_volume = 1.0 if d.keep_original_audio else 0.0
    style.music_volume = float(min(max(d.music_volume, 0.0), 1.0))
    style.order = d.order  # type: ignore[assignment]
    if d.target_duration_seconds and 3 <= d.target_duration_seconds <= 3600:
        style.target_duration = round(float(d.target_duration_seconds), 2)
    if d.intro_title.strip():
        style.text.intro_title = True
        style.text.intro_text = d.intro_title.strip()[:80]
    style.text.captions = d.captions
    return style


# --------------------------------------------------------------------------
# Motores
# --------------------------------------------------------------------------


def llm_interpret(prompt: str, fallback_style: StyleSpec, engine: str) -> Optional[PromptResult]:
    if engine == "anthropic":
        directives, note = _ask_anthropic(prompt)
    elif engine == "ollama":
        directives, note = _ask_ollama(prompt)
    else:
        return None
    if directives is None:
        return None
    style = directives_to_style(directives)
    understood = [directives.summary.strip()] if directives.summary.strip() else []
    if note:
        understood.append(note)
    return PromptResult(
        style=style,
        base_preset=directives.base_preset,
        understood=understood,
        engine=engine,
    )


def _ask_anthropic(prompt: str) -> tuple[Optional[StyleDirectives], str]:
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=SETTINGS.anthropic_model,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        output_format=StyleDirectives,
    )
    # Un rechazo del clasificador llega como respuesta 200: hay que mirarlo
    # antes de leer el contenido. Si pasa, volvemos a las reglas locales.
    if getattr(response, "stop_reason", None) == "refusal":
        return None, ""
    return response.parsed_output, ""


def _ask_ollama(prompt: str) -> tuple[Optional[StyleDirectives], str]:
    """Ollama no tiene SDK oficial de Anthropic; usamos su API HTTP directa."""
    schema = StyleDirectives.model_json_schema()
    payload = {
        "model": SETTINGS.ollama_model,
        "prompt": f"{SYSTEM_PROMPT}\n\nPetición del usuario:\n{prompt}",
        "format": schema,
        "stream": False,
        "options": {"temperature": 0.3},
    }
    req = urllib.request.Request(
        f"{SETTINGS.ollama_url}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None, ""
    raw = body.get("response") or ""
    try:
        return StyleDirectives.model_validate_json(raw), f"modelo local: {SETTINGS.ollama_model}"
    except Exception:
        return None, ""
