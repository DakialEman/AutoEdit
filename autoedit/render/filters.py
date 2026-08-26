"""Construcción de cadenas de filtros de FFmpeg.

Tres bloques independientes que luego se concatenan: encaje en el lienzo,
efecto de movimiento y corrección de color.
"""

from __future__ import annotations

import math

# --------------------------------------------------------------------------
# Encaje en el lienzo
# --------------------------------------------------------------------------


def fit_chain(fit: str, width: int, height: int) -> str:
    """Adapta cualquier fuente al lienzo destino."""
    if fit == "contain":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
        )
    if fit == "blur_pad":
        # Fondo desenfocado con el propio clip: rellena sin barras negras.
        return (
            "split=2[__bg][__fg];"
            f"[__bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},gblur=sigma={max(8, height // 40)},"
            "eq=brightness=-0.12:saturation=0.7[__bgo];"
            f"[__fg]scale={width}:{height}:force_original_aspect_ratio=decrease[__fgo];"
            "[__bgo][__fgo]overlay=(W-w)/2:(H-h)/2"
        )
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height}"
    )


# --------------------------------------------------------------------------
# Efectos de movimiento
# --------------------------------------------------------------------------

# Cuánto margen extra se renderiza para poder hacer zoom sin perder nitidez.
OVERSCAN = 1.3


def needs_overscan(effect: str) -> bool:
    return effect not in ("none", "")


def motion_chain(
    effect: str, width: int, height: int, frames: int, fps: int, amount: float = 1.0
) -> str:
    """Devuelve un filtro `zoompan` que anima el encuadre.

    Se trabaja con `on` (número de fotograma de salida) y un total conocido,
    así el movimiento es idéntico en la vista previa y en el render final.
    """
    if effect in ("none", "") or frames <= 1:
        return f"scale={width}:{height}"

    n = max(1, frames - 1)
    a = max(0.1, min(2.0, amount))
    common = f":d=1:s={width}x{height}:fps={fps}"
    cx = "iw/2-(iw/zoom/2)"
    cy = "ih/2-(ih/zoom/2)"

    if effect == "kenburns_in":
        z = f"1+{0.14 * a:.4f}*on/{n}"
        return f"zoompan=z='{z}':x='{cx}':y='{cy}'{common}"
    if effect == "kenburns_out":
        z = f"{1 + 0.14 * a:.4f}-{0.14 * a:.4f}*on/{n}"
        return f"zoompan=z='{z}':x='{cx}':y='{cy}'{common}"
    if effect in ("kenburns_left", "kenburns_right"):
        z = f"{1 + 0.10 * a:.4f}"
        span = "(iw-iw/zoom)"
        prog = f"on/{n}"
        x = f"{span}*{prog}" if effect == "kenburns_right" else f"{span}*(1-{prog})"
        return f"zoompan=z='{z}':x='{x}':y='{cy}'{common}"
    if effect == "zoom_punch":
        # Entra con un golpe de zoom y se asienta en el primer cuarto de segundo.
        settle = max(1, int(fps * 0.28))
        z = f"1+{0.16 * a:.4f}*(1-min(1,on/{settle}))"
        return f"zoompan=z='{z}':x='{cx}':y='{cy}'{common}"
    if effect == "shake":
        amp = 6 * a
        z = f"{1 + 0.06 * a:.4f}"
        x = f"{cx}+{amp:.2f}*sin(on/2.7)"
        y = f"{cy}+{amp * 0.8:.2f}*cos(on/3.4)"
        return f"zoompan=z='{z}':x='{x}':y='{y}'{common}"
    if effect == "slow_drift":
        z = f"{1 + 0.07 * a:.4f}"
        x = f"(iw-iw/zoom)*(0.5+0.5*sin(on/{max(1, n)}*1.2))"
        return f"zoompan=z='{z}':x='{x}':y='{cy}'{common}"
    if effect == "flash":
        return f"scale={width}:{height}"
    return f"scale={width}:{height}"


# --------------------------------------------------------------------------
# Corrección de color
# --------------------------------------------------------------------------

GRADE_CHAINS: dict[str, str] = {
    "none": "",
    "cinematic": "curves=preset=medium_contrast,eq=saturation=0.94:contrast=1.05,"
                 "colorbalance=rs=-0.04:bs=0.06",
    "teal_orange": "colorbalance=rs=0.08:bs=-0.06:rm=0.03:bm=0.02:rh=-0.06:bh=0.10,"
                   "eq=saturation=1.10:contrast=1.06",
    "warm": "colorbalance=rs=0.09:bs=-0.07:rm=0.05:bm=-0.04,eq=saturation=1.06:contrast=1.02",
    "cold": "colorbalance=rs=-0.07:bs=0.10:bm=0.04,eq=saturation=0.97:contrast=1.04",
    "vintage": "curves=all='0/0.08 0.5/0.5 1/0.92',"
               "colorbalance=rs=0.06:gs=0.02:bs=-0.05,eq=saturation=0.82:contrast=0.96",
    "vivid": "eq=saturation=1.32:contrast=1.10,unsharp=5:5:0.6",
    "bw": "hue=s=0,eq=contrast=1.12:brightness=0.01",
    "faded": "curves=all='0/0.10 0.5/0.52 1/0.93',eq=saturation=0.80:contrast=0.92",
    "night": "eq=brightness=-0.06:contrast=1.14:saturation=0.88,colorbalance=bs=0.10:bm=0.04",
}


def grade_chain(grade: str) -> str:
    return GRADE_CHAINS.get(grade or "none", "")


# --------------------------------------------------------------------------
# Transiciones
# --------------------------------------------------------------------------

# Nuestros nombres -> nombres reales del filtro `xfade`.
XFADE_MAP: dict[str, str] = {
    "fade": "fade",
    "dissolve": "dissolve",
    "fadeblack": "fadeblack",
    "fadewhite": "fadewhite",
    "flash": "fadewhite",
    "slideleft": "slideleft",
    "slideright": "slideright",
    "slideup": "slideup",
    "slidedown": "slidedown",
    "wipeleft": "wipeleft",
    "wiperight": "wiperight",
    "circleopen": "circleopen",
    "circleclose": "circleclose",
    "radial": "radial",
    "pixelize": "pixelize",
    "zoomin": "zoomin",
    "smoothleft": "smoothleft",
    "smoothright": "smoothright",
    "hblur": "hblur",
}


def xfade_name(kind: str) -> str:
    return XFADE_MAP.get(kind, "fade")


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------


def even(value: float) -> int:
    """FFmpeg y H.264 exigen dimensiones pares."""
    return max(2, int(math.ceil(value / 2) * 2))


def join(*chains: str) -> str:
    parts = [c.strip().strip(",") for c in chains if c and c.strip().strip(",")]
    return ",".join(parts)
