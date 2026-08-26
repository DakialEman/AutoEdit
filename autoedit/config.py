"""Configuración y rutas de trabajo.

AutoEdit es local: todo (proyectos, caché, exportaciones) vive en el disco del
usuario, bajo `AUTOEDIT_HOME` (por defecto `~/AutoEdit`).
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path


def _default_home() -> Path:
    env = os.environ.get("AUTOEDIT_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / "AutoEdit"


@dataclass
class Settings:
    home: Path = field(default_factory=_default_home)
    host: str = os.environ.get("AUTOEDIT_HOST", "127.0.0.1")
    port: int = int(os.environ.get("AUTOEDIT_PORT", "8765"))
    # Calidad de render
    preview_height: int = int(os.environ.get("AUTOEDIT_PREVIEW_HEIGHT", "640"))
    render_crf: int = int(os.environ.get("AUTOEDIT_CRF", "20"))
    render_preset: str = os.environ.get("AUTOEDIT_PRESET", "veryfast")
    threads: int = int(os.environ.get("AUTOEDIT_THREADS", "0"))
    # Motor de prompts: heuristic | anthropic | ollama
    prompt_engine: str = os.environ.get("AUTOEDIT_PROMPT_ENGINE", "auto")
    ollama_url: str = os.environ.get("AUTOEDIT_OLLAMA_URL", "http://127.0.0.1:11434")
    ollama_model: str = os.environ.get("AUTOEDIT_OLLAMA_MODEL", "llama3.1")
    anthropic_model: str = os.environ.get("AUTOEDIT_ANTHROPIC_MODEL", "claude-opus-5")

    # -- rutas ------------------------------------------------------------

    @property
    def projects_dir(self) -> Path:
        return self.home / "projects"

    @property
    def media_dir(self) -> Path:
        return self.home / "media"

    @property
    def fonts_dir(self) -> Path:
        return self.home / "fonts"

    def project_dir(self, project_id: str) -> Path:
        return self.projects_dir / project_id

    def project_file(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "project.json"

    def cache_dir(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "cache"

    def thumbs_dir(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "thumbs"

    def exports_dir(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "exports"

    def ensure_dirs(self, project_id: str | None = None) -> None:
        for d in (self.projects_dir, self.media_dir, self.fonts_dir):
            d.mkdir(parents=True, exist_ok=True)
        if project_id:
            for d in (
                self.project_dir(project_id),
                self.cache_dir(project_id),
                self.thumbs_dir(project_id),
                self.exports_dir(project_id),
            ):
                d.mkdir(parents=True, exist_ok=True)

    # -- preferencias persistentes ---------------------------------------

    @property
    def prefs_file(self) -> Path:
        return self.home / "settings.json"

    def load_prefs(self) -> dict:
        try:
            return json.loads(self.prefs_file.read_text("utf-8"))
        except Exception:
            return {}

    def save_prefs(self, data: dict) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self.prefs_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")


SETTINGS = Settings()


# --------------------------------------------------------------------------
# Localización de binarios de FFmpeg
# --------------------------------------------------------------------------


def _from_imageio() -> str | None:
    try:
        import imageio_ffmpeg  # type: ignore

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        return exe if exe and Path(exe).exists() else None
    except Exception:
        return None


def find_ffmpeg() -> str:
    """Devuelve la ruta a `ffmpeg`.

    Orden: variable de entorno, PATH del sistema, binario incluido en
    `imageio-ffmpeg`. Así el usuario no necesita instalar nada a mano, pero un
    FFmpeg del sistema (normalmente con más códecs) tiene prioridad.
    """
    env = os.environ.get("AUTOEDIT_FFMPEG")
    if env and Path(env).exists():
        return env
    which = shutil.which("ffmpeg")
    if which:
        return which
    bundled = _from_imageio()
    if bundled:
        return bundled
    raise RuntimeError(
        "No se encontró FFmpeg. Instálalo (https://ffmpeg.org) o ejecuta "
        "`pip install imageio-ffmpeg`, o define AUTOEDIT_FFMPEG=/ruta/a/ffmpeg."
    )


def find_ffprobe() -> str | None:
    """Devuelve la ruta a `ffprobe` si existe.

    No es obligatorio: el analizador tiene un camino alternativo que parsea la
    salida de `ffmpeg -i`, porque los builds portables de FFmpeg a veces vienen
    sin ffprobe.
    """
    env = os.environ.get("AUTOEDIT_FFPROBE")
    if env and Path(env).exists():
        return env
    which = shutil.which("ffprobe")
    if which:
        return which
    ff = None
    try:
        ff = find_ffmpeg()
    except RuntimeError:
        return None
    candidate = Path(ff).with_name("ffprobe" + Path(ff).suffix)
    return str(candidate) if candidate.exists() else None
