"""Interpretación del prompt del usuario.

Por defecto funciona 100% offline: un intérprete de reglas que entiende español
e inglés y traduce la descripción a un `StyleSpec`. Si el usuario configura un
modelo (Anthropic u Ollama local), `interpret()` lo usa primero y cae en las
reglas si algo falla — nunca deja al usuario sin montaje.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Callable, Optional

from ..models import PromptResult, StyleSpec
from .styles import PRESETS, get_preset

Mutator = Callable[[StyleSpec], None]


def _norm(text: str) -> str:
    """Minúsculas sin acentos, para comparar sin sorpresas."""
    lowered = (text or "").lower()
    decomposed = unicodedata.normalize("NFD", lowered)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def _has(text: str, *words: str) -> bool:
    return any(re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", text) for w in words)


# --------------------------------------------------------------------------
# Detección del preset base
# --------------------------------------------------------------------------

PRESET_HINTS: dict[str, list[str]] = {
    "beatsync": ["beat sync", "beatsync", "al ritmo exacto", "cada beat", "cada pulso", "on beat"],
    "cinematic": ["cinematografico", "cinematografica", "cinematica", "cinematico", "cine", "cinematic", "pelicula", "film look", "epico", "epica", "epic"],
    "vlog": ["vlog", "diario", "daily", "blog", "mi dia", "day in my life", "rutina"],
    "travel": ["viaje", "travel", "vacaciones", "turismo", "roadtrip", "road trip", "aventura", "trip"],
    "slideshow": ["slideshow", "presentacion de fotos", "recuerdos", "album", "fotos antiguas", "memories", "diapositivas"],
    "trailer": ["trailer", "traila", "teaser", "avance"],
    "aesthetic": ["estetico", "estetica", "aesthetic", "chill", "lofi", "lo-fi", "ensoñador", "dreamy", "tumblr"],
    "sport": ["deporte", "deportivo", "deportiva", "accion", "action", "gym", "workout", "skate", "surf", "futbol", "highlights deportivos", "adrenalina"],
    "wedding": ["boda", "wedding", "casamiento", "novios", "romantico", "romantica", "aniversario", "romantic"],
    "talking": ["podcast", "entrevista", "hablando", "talking head", "a camara", "tutorial", "explicacion", "curso"],
    "promo": ["promo", "producto", "anuncio", "publicidad", "marca", "ad", "comercial", "ecommerce", "venta"],
    "dynamic": ["tiktok", "reel", "reels", "shorts", "dinamico", "dinamica", "energetico", "energetica", "viral", "dynamic"],
}


def detect_preset(text: str) -> tuple[str, list[str]]:
    """Elige el estilo base a partir de las pistas del prompt.

    Gana la pista que aparece **antes** en la frase, no la primera del
    diccionario: la gente empieza diciendo de qué va el vídeo («boda romántica
    con música suave»), así que lo que va delante manda. A igualdad de
    posición, gana la pista más larga por ser la más específica.
    """
    best: tuple[int, int, str, str] | None = None
    for preset_id, hints in PRESET_HINTS.items():
        for hint in hints:
            position = text.find(_norm(hint))
            if position < 0:
                continue
            candidate = (position, -len(hint), preset_id, hint)
            if best is None or candidate < best:
                best = candidate
    if best is None:
        return "dynamic", []
    _, _, preset_id, hint = best
    return preset_id, [f"estilo base «{PRESETS[preset_id].name}» (por «{hint}»)"]


# --------------------------------------------------------------------------
# Reglas de ajuste
# --------------------------------------------------------------------------


_NEGATIONS = ("sin ", "no ", "nada de ", "quita ", "quitar ")


class Rule:
    def __init__(self, label: str, words: list[str], apply: Mutator):
        self.label = label
        self.words = words
        self.apply = apply

    def matches(self, text: str) -> bool:
        return any(_mentions(text, word) for word in self.words)


def _mentions(text: str, word: str) -> bool:
    """¿Aparece `word` en el texto sin una negación delante?

    Hace falta porque las reglas se buscan por subcadena: sin esto, «sin
    transiciones» activaría a la vez la regla de quitarlas y la de ponerlas.
    Si la propia palabra ya empieza por una negación, se busca tal cual.
    """
    negated_word = word.startswith(_NEGATIONS)
    start = 0
    while True:
        position = text.find(word, start)
        if position < 0:
            return False
        if negated_word:
            return True
        prefix = text[max(0, position - 12): position]
        if not any(prefix.endswith(negation) for negation in _NEGATIONS):
            return True
        start = position + 1


def _set_aspect(aspect: str) -> Mutator:
    def _apply(s: StyleSpec) -> None:
        s.aspect = aspect

    return _apply


def _set_grade(grade: str) -> Mutator:
    def _apply(s: StyleSpec) -> None:
        s.grade = grade

    return _apply


def _scale_pace(factor: float) -> Mutator:
    def _apply(s: StyleSpec) -> None:
        s.min_clip = round(max(0.25, s.min_clip * factor), 3)
        s.max_clip = round(max(s.min_clip + 0.2, s.max_clip * factor), 3)
        s.target_clip = round(max(s.min_clip, min(s.max_clip, s.target_clip * factor)), 3)
        if factor < 1 and s.beat_division > 1:
            s.beat_division = max(1, s.beat_division // 2)
        elif factor > 1:
            s.beat_division = min(8, s.beat_division * 2)

    return _apply


def _no_transitions(s: StyleSpec) -> None:
    s.transitions = ["cut"]
    s.transition_chance = 0.0


def _more_transitions(s: StyleSpec) -> None:
    if s.transitions == ["cut"]:
        s.transitions = ["dissolve", "fade", "slideleft"]
    else:
        s.transitions = [t for t in s.transitions if t != "cut"] or ["dissolve"]
    s.transition_chance = max(0.75, s.transition_chance)


def _no_effects(s: StyleSpec) -> None:
    s.effects = ["none"]
    s.effect_chance = 0.0
    s.image_effects = ["none"]


def _more_effects(s: StyleSpec) -> None:
    s.effects = ["zoom_punch", "kenburns_in", "slow_drift"]
    s.effect_chance = max(0.8, s.effect_chance)


RULES: list[Rule] = [
    # --- formato ------------------------------------------------------
    Rule("formato vertical 9:16", ["vertical", "9:16", "9x16", "tiktok", "reel", "shorts", "historia", "story", "movil"], _set_aspect("9:16")),
    Rule("formato horizontal 16:9", ["horizontal", "16:9", "16x9", "youtube", "apaisado", "panoramico", "widescreen", "tele"], _set_aspect("16:9")),
    Rule("formato cuadrado 1:1", ["cuadrado", "1:1", "square"], _set_aspect("1:1")),
    Rule("formato 4:5", ["4:5", "4x5", "post de instagram", "feed"], _set_aspect("4:5")),
    Rule("formato ultrapanorámico 21:9", ["21:9", "cinemascope", "ultrapanoramico"], _set_aspect("21:9")),
    # --- ritmo --------------------------------------------------------
    Rule("ritmo más rápido", ["rapido", "rapida", "veloz", "acelerado", "acelerada", "frenetico", "frenetica", "fast", "quick", "agil", "trepidante", "nervioso"], _scale_pace(0.55)),
    Rule("ritmo más lento", ["lento", "lenta", "pausado", "pausada", "tranquilo", "tranquila", "calmado", "calmada", "relajado", "relajada", "slow", "calm", "suave y lento", "contemplativo"], _scale_pace(1.7)),
    # --- color --------------------------------------------------------
    Rule("blanco y negro", ["blanco y negro", "byn", "b&w", "black and white", "monocromo", "monochrome", "gris"], _set_grade("bw")),
    Rule("look vintage", ["vintage", "retro", "antiguo", "super 8", "super8", "vhs", "años 80", "anos 80", "noventero", "old school"], _set_grade("vintage")),
    Rule("tonos cálidos", ["calido", "calida", "dorado", "atardecer", "golden hour", "warm", "verano"], _set_grade("warm")),
    Rule("tonos fríos", ["frio", "fria", "azulado", "cold", "invierno", "gelido"], _set_grade("cold")),
    Rule("color vivo y saturado", ["saturado", "saturada", "colorido", "colorida", "vibrante", "vivo", "viva", "vivid", "punchy", "pop"], _set_grade("vivid")),
    Rule("look de cine", ["look de cine", "color de cine", "teal", "naranja y azul", "cinematic color"], _set_grade("teal_orange")),
    Rule("look nocturno", ["nocturno", "de noche", "night", "oscuro", "dark"], _set_grade("night")),
    Rule("look lavado/pastel", ["lavado", "lavada", "apagado", "apagada", "pastel", "desaturado", "desaturada", "faded", "matte", "mate"], _set_grade("faded")),
    Rule("sin corrección de color", ["sin filtro", "sin filtros", "color natural", "sin correccion", "tal cual", "natural"], _set_grade("none")),
    # --- transiciones y efectos ---------------------------------------
    Rule("solo cortes secos", ["sin transiciones", "cortes secos", "hard cut", "hard cuts", "sin efectos de transicion", "corte seco"], _no_transitions),
    Rule("más transiciones", ["con transiciones", "transiciones", "fundidos", "encadenados", "crossfade", "disolvencias", "smooth transitions"], _more_transitions),
    Rule("sin efectos de movimiento", ["sin efectos", "sin zoom", "sin movimiento", "estatico", "no effects", "quieto"], _no_effects),
    Rule("con efectos de movimiento", ["con zoom", "con efectos", "zooms", "movimiento de camara", "ken burns", "kenburns", "punch in"], _more_effects),
    Rule("con temblor de cámara", ["shake", "temblor", "vibracion", "camara en mano"], lambda s: (s.effects.append("shake"), setattr(s, "effect_chance", max(0.6, s.effect_chance)))),  # type: ignore[func-returns-value]
]


# --------------------------------------------------------------------------
# Reglas que necesitan más contexto
# --------------------------------------------------------------------------


NO_MUSIC = ["sin musica", "no music", "sin cancion"]
KEEP_AUDIO = ["conserva el audio", "mantener el audio", "audio original", "con mi voz",
              "mi voz", "que se escuche", "keep audio", "original audio", "con sonido", "con audio"]
MUTE_AUDIO = ["sin audio original", "silencia", "mutear", "mute", "solo musica", "sin sonido ambiente"]
BEAT_ON = ["al ritmo", "sincronizado con la musica", "beat", "on beat", "a tiempo", "sincronizar"]
BEAT_OFF = ["sin sincronizar", "sin ritmo", "no beat"]

NO_TEXT = ["sin texto", "sin titulos", "sin subtitulos", "no text", "sin letras"]
WITH_TITLE = ["con titulo", "con titulos", "con texto", "titular", "with titles", "rotulo", "rotulos"]
WITH_CAPTIONS = ["subtitulos", "captions", "subtitulado"]

ORDER_CHRONO = ["cronologico", "en orden", "por fecha", "chronological", "orden de grabacion"]
ORDER_SHUFFLE = ["aleatorio", "random", "desordenado", "shuffle", "mezclado"]
ORDER_BEST = ["mejores momentos", "highlights", "lo mejor", "best moments", "resumen"]
ORDER_RAMP = ["que suba", "in crescendo", "crescendo", "va subiendo", "build up", "buildup",
              "de menos a mas", "clímax", "climax"]
USE_ALL = ["usa todo", "todo el material", "sin recortar", "todos los clips", "use everything"]

# Palabras que la regla de duración consume junto al número.
TIME_WORDS = ["segundo", "segundos", "seg", "segs", "second", "seconds", "sec", "secs",
              "minuto", "minutos", "min", "mins", "minute", "minutes", "medio", "duracion",
              "dura", "duran", "largo", "corto"]


def _apply_audio_rules(text: str, style: StyleSpec, understood: list[str]) -> None:
    if any(_mentions(text, w) for w in NO_MUSIC):
        style.music_volume = 0.0
        style.beat_sync = False
        understood.append("sin música")
    if any(_mentions(text, w) for w in KEEP_AUDIO):
        style.original_audio_volume = 1.0
        style.duck_music = True
        style.music_volume = min(style.music_volume, 0.3)
        understood.append("mantiene el audio original")
    if any(_mentions(text, w) for w in MUTE_AUDIO):
        style.original_audio_volume = 0.0
        understood.append("solo música (sin audio original)")
    if any(_mentions(text, w) for w in BEAT_ON):
        style.beat_sync = True
        understood.append("cortes sincronizados con la música")
    if any(_mentions(text, w) for w in BEAT_OFF):
        style.beat_sync = False
        understood.append("sin sincronía con la música")


def _apply_text_rules(text: str, style: StyleSpec, understood: list[str], raw: str = "") -> None:
    if any(_mentions(text, w) for w in NO_TEXT):
        style.text.intro_title = False
        style.text.captions = False
        understood.append("sin textos en pantalla")
        return
    if any(_mentions(text, w) for w in WITH_TITLE):
        style.text.intro_title = True
        understood.append("con títulos en pantalla")
    if any(_mentions(text, w) for w in WITH_CAPTIONS):
        style.text.captions = True
        understood.append("con subtítulos (marcadores de texto por clip)")

    # Texto entrecomillado = título literal. Se busca sobre el prompt original,
    # no sobre el normalizado, para conservar mayúsculas y acentos.
    quoted = re.findall(r"[\"“']([^\"”']{2,60})[\"”']", raw or text)
    if quoted:
        style.text.intro_title = True
        style.text.intro_text = quoted[0].strip()
        understood.append(f"título: «{style.text.intro_text}»")


def _apply_order_rules(text: str, style: StyleSpec, understood: list[str]) -> None:
    if any(_mentions(text, w) for w in ORDER_CHRONO):
        style.order = "chronological"
        understood.append("orden cronológico")
    elif any(_mentions(text, w) for w in ORDER_SHUFFLE):
        style.order = "shuffle"
        understood.append("orden aleatorio")
    elif any(_mentions(text, w) for w in ORDER_BEST):
        style.order = "by_score"
        style.use_highlights = True
        understood.append("solo los mejores momentos")
    if any(_mentions(text, w) for w in ORDER_RAMP):
        style.order = "energy_ramp"
        style.energy_ramp = True
        understood.append("energía en crescendo")
    if any(_mentions(text, w) for w in USE_ALL):
        style.use_highlights = False
        style.target_duration = None
        understood.append("usa todo el material")


_DUR_PATTERNS: list[tuple[re.Pattern, Callable[[re.Match], float]]] = [
    (re.compile(r"(\d+)\s*[:.](\d{2})\s*(?:min|minutos?)?"), lambda m: int(m.group(1)) * 60 + int(m.group(2))),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:minutos?|minute?s?|mins?\b|min\b|m\b)"), lambda m: float(m.group(1).replace(",", ".")) * 60),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:segundos?|seconds?|secs?\b|seg\b|s\b)"), lambda m: float(m.group(1).replace(",", "."))),
]


def _apply_duration_rules(text: str, style: StyleSpec, understood: list[str]) -> None:
    if "medio minuto" in text:
        style.target_duration = 30.0
        understood.append("duración ~30 s")
        return
    if any(_mentions(text, w) for w in ["minuto y medio", "minuto y media"]):
        style.target_duration = 90.0
        understood.append("duración ~1:30")
        return
    for pattern, convert in _DUR_PATTERNS:
        m = pattern.search(text)
        if m:
            value = convert(m)
            if 3 <= value <= 3600:
                style.target_duration = round(value, 2)
                understood.append(f"duración objetivo ~{_fmt(value)}")
                return


def _fmt(seconds: float) -> str:
    if seconds < 60:
        return f"{int(round(seconds))} s"
    m, s = divmod(int(round(seconds)), 60)
    return f"{m}:{s:02d}"


# --------------------------------------------------------------------------
# API pública
# --------------------------------------------------------------------------


def interpret_heuristic(prompt: str, base_preset: Optional[str] = None) -> PromptResult:
    """Traduce el prompt a un `StyleSpec` usando solo reglas locales."""
    text = _norm(prompt)
    understood: list[str] = []

    if base_preset:
        preset_id = base_preset
    else:
        preset_id, hints = detect_preset(text)
        understood.extend(hints)

    style = get_preset(preset_id)
    style.id = "custom" if prompt.strip() else preset_id
    if prompt.strip():
        style.name = f"{PRESETS[preset_id].name} (a medida)"

    for rule in RULES:
        if rule.matches(text):
            rule.apply(style)
            understood.append(rule.label)

    _apply_audio_rules(text, style, understood)
    _apply_text_rules(text, style, understood, raw=prompt)
    _apply_order_rules(text, style, understood)
    _apply_duration_rules(text, style, understood)

    # Coherencia final.
    style.min_clip = max(0.25, min(style.min_clip, style.max_clip))
    style.target_clip = max(style.min_clip, min(style.target_clip, style.max_clip))
    style.transitions = list(dict.fromkeys(style.transitions)) or ["cut"]
    style.effects = list(dict.fromkeys(style.effects)) or ["none"]

    ignored = _leftover_words(text, understood)
    return PromptResult(
        style=style,
        base_preset=preset_id,
        understood=understood,
        ignored=ignored,
        engine="heuristic",
    )


_STOPWORDS = set(
    """de la el los las un una unos unas y o que con para por en a al del me mi mis
    quiero hazme haz montaje video vídeo clips clip fotos foto musica música tema
    make me create a an the with of for my and to please porfa porfavor edit edita
    editar corta cortar pon poner ponle sea que quede quiero un poco mas más muy
    todo todos toda todas este esta esto ese esa eso""".split()
)


def _vocabulary() -> set[str]:
    """Todas las palabras que alguna regla puede reconocer.

    Se construye una vez a partir de las propias listas de reglas, para que
    añadir un sinónimo nuevo no deje de golpe un falso «sin aplicar».
    """
    cached = globals().get("_VOCAB_CACHE")
    if cached is not None:
        return cached
    phrases: list[str] = []
    phrases += sum(PRESET_HINTS.values(), [])
    phrases += sum((rule.words for rule in RULES), [])
    phrases += (
        NO_MUSIC + KEEP_AUDIO + MUTE_AUDIO + BEAT_ON + BEAT_OFF
        + NO_TEXT + WITH_TITLE + WITH_CAPTIONS
        + ORDER_CHRONO + ORDER_SHUFFLE + ORDER_BEST + ORDER_RAMP + USE_ALL
        + TIME_WORDS
    )
    vocab = set()
    for phrase in phrases:
        vocab.update(re.findall(r"[a-z]+", _norm(phrase)))
    globals()["_VOCAB_CACHE"] = vocab
    return vocab


def _leftover_words(text: str, understood: list[str]) -> list[str]:
    """Palabras significativas que ninguna regla reconoció.

    Se lo enseñamos al usuario para que sepa qué parte del prompt no se aplicó,
    en vez de fingir que lo entendimos todo.
    """
    if not understood:
        return []
    words = [w for w in re.findall(r"[a-z]{4,}", text) if w not in _STOPWORDS]
    known = set(re.findall(r"[a-z]+", _norm(" ".join(understood))))
    vocab = _vocabulary()
    leftover = [w for w in dict.fromkeys(words) if w not in known and w not in vocab]
    return leftover[:8]


def interpret(prompt: str, base_preset: Optional[str] = None, engine: str = "auto") -> PromptResult:
    """Interpreta el prompt con el mejor motor disponible.

    `engine`: "heuristic" (offline), "anthropic", "ollama" o "auto" (usa un
    modelo si está configurado y, si falla, vuelve a las reglas).
    """
    fallback = interpret_heuristic(prompt, base_preset)
    if not prompt.strip() or engine == "heuristic":
        return fallback

    from .llm import llm_interpret, resolve_engine

    chosen = resolve_engine(engine)
    if chosen == "heuristic":
        return fallback
    try:
        result = llm_interpret(prompt, fallback.style, chosen)
        if result is not None:
            return result
    except Exception:
        pass
    return fallback
