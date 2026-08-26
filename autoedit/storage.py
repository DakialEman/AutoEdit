"""Persistencia local: proyectos y biblioteca de material.

Un proyecto es un único `project.json` dentro de su carpeta. Nada de bases de
datos: se puede copiar, versionar o mandar por correo, y sigue funcionando.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Iterable

from .analysis import media
from .analysis.audio import analyze_audio
from .config import SETTINGS
from .models import Asset, Project

SUPPORTED_EXT = media.IMAGE_EXT | media.AUDIO_EXT | media.VIDEO_EXT


class StorageError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Proyectos
# --------------------------------------------------------------------------


def list_projects() -> list[dict]:
    SETTINGS.ensure_dirs()
    out: list[dict] = []
    for directory in SETTINGS.projects_dir.iterdir():
        if not directory.is_dir():
            continue
        file = directory / "project.json"
        if not file.exists():
            continue
        try:
            data = json.loads(file.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        timeline = data.get("timeline") or {}
        clips = sum(len(t.get("clips") or []) for t in timeline.get("tracks") or [])
        out.append(
            {
                "id": data.get("id", directory.name),
                "name": data.get("name", directory.name),
                "created_at": data.get("created_at", 0),
                "updated_at": data.get("updated_at", 0),
                "assets": len(data.get("assets") or []),
                "clips": clips,
                "style": (data.get("style") or {}).get("name", ""),
                "prompt": data.get("prompt", ""),
            }
        )
    out.sort(key=lambda p: p["updated_at"], reverse=True)
    return out


def create_project(name: str = "") -> Project:
    project = Project(name=(name or "").strip() or f"Proyecto {time.strftime('%d/%m %H:%M')}")
    SETTINGS.ensure_dirs(project.id)
    save_project(project)
    return project


def load_project(project_id: str) -> Project:
    file = SETTINGS.project_file(project_id)
    if not file.exists():
        raise StorageError(f"No existe el proyecto {project_id}")
    try:
        data = json.loads(file.read_text("utf-8"))
    except json.JSONDecodeError as exc:
        raise StorageError(f"El proyecto {project_id} está corrupto: {exc}") from exc
    return Project.model_validate(data)


def save_project(project: Project) -> Path:
    """Guarda de forma atómica: se escribe a un temporal y se reemplaza."""
    SETTINGS.ensure_dirs(project.id)
    project.updated_at = time.time()
    file = SETTINGS.project_file(project.id)
    tmp = file.with_suffix(".json.tmp")
    tmp.write_text(project.model_dump_json(indent=2), "utf-8")
    os.replace(tmp, file)
    return file


def delete_project(project_id: str, remove_files: bool = True) -> None:
    directory = SETTINGS.project_dir(project_id)
    if not directory.exists():
        raise StorageError(f"No existe el proyecto {project_id}")
    if remove_files:
        shutil.rmtree(directory, ignore_errors=True)


def duplicate_project(project_id: str, name: str = "") -> Project:
    original = load_project(project_id)
    copy = original.model_copy(deep=True)
    copy.id = Project().id
    copy.name = name or f"{original.name} (copia)"
    copy.created_at = time.time()
    copy.exports = []
    save_project(copy)
    return copy


# --------------------------------------------------------------------------
# Importación de material
# --------------------------------------------------------------------------


def _unique_name(directory: Path, filename: str) -> Path:
    stem, suffix = Path(filename).stem, Path(filename).suffix
    candidate = directory / f"{stem}{suffix}"
    n = 1
    while candidate.exists():
        candidate = directory / f"{stem}_{n}{suffix}"
        n += 1
    return candidate


def import_file(project: Project, path: str | Path, copy: bool = False) -> Asset:
    """Añade un archivo del disco al proyecto (por referencia o copiándolo)."""
    source = Path(path).expanduser()
    if not source.exists() or not source.is_file():
        raise StorageError(f"No existe el archivo {source}")
    if source.suffix.lower() not in SUPPORTED_EXT:
        raise StorageError(f"Formato no soportado: {source.suffix or source.name}")

    if copy:
        SETTINGS.media_dir.mkdir(parents=True, exist_ok=True)
        destination = _unique_name(SETTINGS.media_dir, source.name)
        shutil.copy2(source, destination)
        source = destination

    resolved = str(source.resolve())
    for existing in project.assets:
        if existing.path == resolved:
            return existing

    asset = media.probe_to_asset(source)
    project.assets.append(asset)
    return asset


def import_bytes(project: Project, filename: str, data: bytes) -> Asset:
    """Guarda un archivo subido desde el navegador en la biblioteca local."""
    if Path(filename).suffix.lower() not in SUPPORTED_EXT:
        raise StorageError(f"Formato no soportado: {Path(filename).suffix or filename}")
    SETTINGS.media_dir.mkdir(parents=True, exist_ok=True)
    destination = _unique_name(SETTINGS.media_dir, Path(filename).name)
    destination.write_bytes(data)
    return import_file(project, destination, copy=False)


def import_folder(project: Project, folder: str | Path, recursive: bool = True) -> list[Asset]:
    directory = Path(folder).expanduser()
    if not directory.is_dir():
        raise StorageError(f"No es una carpeta: {directory}")
    pattern = "**/*" if recursive else "*"
    added: list[Asset] = []
    for path in sorted(directory.glob(pattern)):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXT:
            try:
                added.append(import_file(project, path))
            except StorageError:
                continue
    return added


def import_any(project: Project, paths: Iterable[str]) -> tuple[list[Asset], list[str]]:
    """Importa archivos y/o carpetas, devolviendo también los errores."""
    added: list[Asset] = []
    errors: list[str] = []
    for raw in paths:
        path = Path(raw).expanduser()
        try:
            if path.is_dir():
                added.extend(import_folder(project, path))
            else:
                added.append(import_file(project, path))
        except StorageError as exc:
            errors.append(str(exc))
    return added, errors


def remove_asset(project: Project, asset_id: str) -> None:
    asset = project.asset(asset_id)
    if asset is None:
        raise StorageError("Ese archivo no está en el proyecto")
    project.assets = [a for a in project.assets if a.id != asset_id]
    for track in project.timeline.tracks:
        track.clips = [c for c in track.clips if c.asset_id != asset_id]
    if project.meta.get("music_asset_id") == asset_id:
        project.meta.pop("music_asset_id", None)


# --------------------------------------------------------------------------
# Análisis
# --------------------------------------------------------------------------


def analyze_asset(project: Project, asset: Asset, thumbnails: bool = True) -> Asset:
    """Analiza un asset y genera sus miniaturas. Idempotente."""
    thumbs = SETTINGS.thumbs_dir(project.id)
    if asset.kind == "audio":
        asset.analysis = analyze_audio(asset.path)
        if not asset.waveform:
            asset.waveform = media.waveform(asset.path)
    else:
        asset.analysis = media.analyze_visual(asset)
    if thumbnails and not asset.thumbnail:
        asset.thumbnail = media.make_thumbnail(asset, thumbs)
    return asset


def analyze_pending(
    project: Project, on_progress=None, thumbnails: bool = True
) -> list[Asset]:
    """Analiza todos los assets que aún no lo estén."""
    pending = [a for a in project.assets if not a.analysis.analyzed]
    for i, asset in enumerate(pending):
        analyze_asset(project, asset, thumbnails=thumbnails)
        if on_progress:
            on_progress((i + 1) / len(pending), f"Analizando {asset.name}")
    return pending


def refresh_asset(project: Project, asset_id: str) -> Asset:
    """Vuelve a sondear y analizar un archivo (por si cambió en el disco)."""
    asset = project.asset(asset_id)
    if asset is None:
        raise StorageError("Ese archivo no está en el proyecto")
    fresh = media.probe_to_asset(asset.path, asset.kind)
    asset.duration = fresh.duration
    asset.width, asset.height = fresh.width, fresh.height
    asset.fps = fresh.fps
    asset.has_audio, asset.has_video = fresh.has_audio, fresh.has_video
    asset.size, asset.source_mtime = fresh.size, fresh.source_mtime
    asset.thumbnail = None
    analyze_asset(project, asset)
    return asset


def missing_files(project: Project) -> list[Asset]:
    return [a for a in project.assets if not Path(a.path).exists()]


def clear_cache(project_id: str) -> int:
    """Vacía la caché de render. Devuelve los bytes liberados."""
    cache = SETTINGS.cache_dir(project_id)
    if not cache.exists():
        return 0
    freed = sum(f.stat().st_size for f in cache.rglob("*") if f.is_file())
    shutil.rmtree(cache, ignore_errors=True)
    cache.mkdir(parents=True, exist_ok=True)
    return freed


def register_export(project: Project, kind: str, path: Path, note: str = "") -> None:
    from .models import ExportRecord

    project.exports.insert(
        0,
        ExportRecord(
            kind=kind,
            path=str(path),
            size=path.stat().st_size if path.exists() and path.is_file() else 0,
            note=note,
        ),
    )
    del project.exports[20:]
