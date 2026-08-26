"""Rasterizado de los textos en pantalla.

En vez de `drawtext` (que no está en todos los builds de FFmpeg y da poco
control tipográfico) dibujamos cada texto con Pillow sobre un PNG transparente
del tamaño del lienzo y lo componemos con `overlay`. El resultado es idéntico
en cualquier plataforma y permite sombras, contornos, cajas y saltos de línea.
"""

from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from ..config import SETTINGS
from ..models import TextClip, TextStyle

# Fuentes que se buscan por orden si el usuario no indica una.
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
]

_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def available_fonts() -> list[dict]:
    """Fuentes que el usuario puede elegir en la interfaz."""
    found: list[dict] = []
    seen: set[str] = set()
    for path in list(SETTINGS.fonts_dir.glob("*.ttf")) + list(SETTINGS.fonts_dir.glob("*.otf")):
        if path.name not in seen:
            seen.add(path.name)
            found.append({"name": path.stem, "path": str(path)})
    for candidate in _FONT_CANDIDATES:
        p = Path(candidate)
        if p.exists() and p.name not in seen:
            seen.add(p.name)
            found.append({"name": p.stem, "path": str(p)})
    return found


def default_font_path() -> Optional[str]:
    fonts = available_fonts()
    return fonts[0]["path"] if fonts else None


def load_font(path: Optional[str], size: int) -> ImageFont.FreeTypeFont:
    size = max(8, int(size))
    resolved = path if path and Path(path).exists() else default_font_path()
    key = (resolved or "__default__", size)
    if key in _font_cache:
        return _font_cache[key]
    try:
        font = ImageFont.truetype(resolved, size) if resolved else ImageFont.load_default(size)
    except Exception:
        font = ImageFont.load_default(size)
    _font_cache[key] = font
    return font


def _rgba(color: str, default_alpha: int = 255) -> tuple[int, int, int, int]:
    c = (color or "#FFFFFF").strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) == 6:
        c += f"{default_alpha:02X}"
    if len(c) != 8:
        return (255, 255, 255, default_alpha)
    try:
        return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), int(c[6:8], 16))
    except ValueError:
        return (255, 255, 255, default_alpha)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if draw.textlength(candidate, font=font) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def style_key(text: str, style: TextStyle, width: int, height: int) -> str:
    payload = f"{text}|{style.model_dump_json()}|{width}x{height}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


@dataclass
class TextImage:
    """PNG recortado a la caja del texto, más su posición en el lienzo."""

    path: Path
    x: int
    y: int
    width: int
    height: int


def render_text_png(
    text: str, style: TextStyle, width: int, height: int, dest_dir: Path
) -> Optional[TextImage]:
    """Dibuja el texto y lo recorta a su caja útil.

    Recortar importa: en el render final cada texto es un stream de vídeo con
    canal alfa, y componer 20 imágenes del tamaño del lienzo sale carísimo
    comparado con componer 20 rectángulos pequeños.
    """
    content = (text or "").strip()
    if not content:
        return None
    if style.uppercase:
        content = content.upper()

    dest_dir.mkdir(parents=True, exist_ok=True)
    key = style_key(content, style, width, height)
    dest = dest_dir / f"text_{key}.png"
    meta_path = dest_dir / f"text_{key}.json"
    if dest.exists() and meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text("utf-8"))
            return TextImage(dest, meta["x"], meta["y"], meta["width"], meta["height"])
        except Exception:
            pass

    # El tamaño de la fuente se define para un lienzo de 1080 px de alto.
    size = max(10, int(style.size * height / 1080))
    font = load_font(style.font or None, size)

    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    max_width = int(width * 0.86)
    lines = _wrap(draw, content, font, max_width)
    line_height = int(size * 1.22)
    block_height = line_height * len(lines)

    fill = _rgba(style.color)
    stroke_fill = _rgba(style.stroke_color)
    stroke_width = max(0, int(style.stroke * size / 64))

    block_width = max((int(draw.textlength(l, font=font)) for l in lines), default=0)
    cx = int(style.x * width)
    cy = int(style.y * height)
    top = cy - block_height // 2

    if style.box and block_width:
        pad_x, pad_y = int(size * 0.42), int(size * 0.28)
        left = _line_left(cx, block_width, style.align)
        draw.rounded_rectangle(
            [
                left - pad_x,
                top - pad_y,
                left + block_width + pad_x,
                top + block_height + pad_y,
            ],
            radius=int(size * 0.22),
            fill=_rgba(style.box_color, 170),
        )

    for i, line in enumerate(lines):
        line_width = int(draw.textlength(line, font=font))
        x = _line_left(cx, line_width, style.align)
        y = top + i * line_height
        if style.shadow:
            offset = max(1, int(size * 0.05))
            draw.text((x + offset, y + offset), line, font=font, fill=(0, 0, 0, 130))
        draw.text(
            (x, y),
            line,
            font=font,
            fill=fill,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill if stroke_width else None,
        )

    bbox = canvas.getbbox()
    if bbox is None:
        return None
    # Un par de píxeles de margen para no cortar sombras ni contornos.
    pad = 2
    left = max(0, bbox[0] - pad)
    top_px = max(0, bbox[1] - pad)
    right = min(width, bbox[2] + pad)
    bottom = min(height, bbox[3] + pad)
    # H.264 y `overlay` se llevan mejor con dimensiones pares.
    if (right - left) % 2:
        right = min(width, right + 1) if right < width else right - 1
    if (bottom - top_px) % 2:
        bottom = min(height, bottom + 1) if bottom < height else bottom - 1

    cropped = canvas.crop((left, top_px, right, bottom))
    cropped.save(dest, "PNG")
    image = TextImage(dest, left, top_px, cropped.width, cropped.height)
    meta_path.write_text(
        json.dumps({"x": left, "y": top_px, "width": cropped.width, "height": cropped.height}),
        "utf-8",
    )
    return image


def _line_left(center_x: int, line_width: int, align: str) -> int:
    if align == "left":
        return center_x
    if align == "right":
        return center_x - line_width
    return center_x - line_width // 2


def prepare_texts(
    clips: list[TextClip], width: int, height: int, dest_dir: Path
) -> list[tuple[TextClip, TextImage]]:
    """Rasteriza todos los textos con contenido y descarta los vacíos."""
    prepared: list[tuple[TextClip, TextImage]] = []
    for clip in clips:
        image = render_text_png(clip.text, clip.style, width, height, dest_dir)
        if image is not None:
            prepared.append((clip, image))
    return prepared


def font_diagnostics() -> dict:
    fonts = available_fonts()
    return {
        "platform": platform.system(),
        "count": len(fonts),
        "default": fonts[0]["path"] if fonts else None,
        "user_dir": str(SETTINGS.fonts_dir),
    }
