"""API HTTP y servidor de la interfaz.

Todo corre en local: el navegador es solo la interfaz, y el trabajo de verdad
(análisis, render, exportación) ocurre en este proceso, contra los archivos del
propio disco. No sale nada a internet salvo que actives un modelo en la nube.
"""

from __future__ import annotations

import mimetypes
import re
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import editing, storage
from .ai import planner, prompt as prompt_ai, styles
from .config import SETTINGS, find_ffmpeg, find_ffprobe
from .export import FORMATS, capcut, edl, fcpxml
from .jobs import JOBS
from .models import Asset, Project, StyleSpec, Timeline
from .render import font_diagnostics, render_timeline

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    SETTINGS.ensure_dirs()
    yield
    # Al cerrar, se cancela lo que siga renderizando en segundo plano.
    JOBS.shutdown()


app = FastAPI(title="AutoEdit", version="1.0.0", docs_url="/api/docs", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1", "http://localhost"],
    allow_origin_regex=r"http://(127\.0\.0\.1|localhost)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)

# Un candado por proyecto: evita que dos peticiones se pisen al guardar.
_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def _lock_for(project_id: str) -> threading.RLock:
    with _locks_guard:
        if project_id not in _locks:
            _locks[project_id] = threading.RLock()
        return _locks[project_id]


def _load(project_id: str) -> Project:
    try:
        return storage.load_project(project_id)
    except storage.StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _save(project: Project) -> Project:
    project.touch()
    storage.save_project(project)
    return project


def _project_payload(project: Project) -> dict:
    data = project.model_dump()
    data["summary"] = planner.summarize(project.timeline)
    data["problems"] = editing.validate(project, project.timeline)
    data["missing_files"] = [a.id for a in storage.missing_files(project)]
    return data


# --------------------------------------------------------------------------
# Estado general
# --------------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict:
    from .ai.llm import available_engines

    try:
        ffmpeg_path: Optional[str] = find_ffmpeg()
        ffmpeg_error = ""
    except RuntimeError as exc:
        ffmpeg_path, ffmpeg_error = None, str(exc)
    return {
        "ok": bool(ffmpeg_path),
        "ffmpeg": ffmpeg_path,
        "ffmpeg_error": ffmpeg_error,
        "ffprobe": find_ffprobe(),
        "home": str(SETTINGS.home),
        "fonts": font_diagnostics(),
        "prompt_engines": available_engines(),
        "prompt_engine": SETTINGS.prompt_engine,
        "capcut_drafts": str(capcut.find_capcut_drafts_dir() or ""),
        "formats": FORMATS,
    }


@app.get("/api/styles")
def get_styles() -> dict:
    return {"presets": styles.list_presets()}


@app.get("/api/fonts")
def get_fonts() -> dict:
    from .render import available_fonts

    return {"fonts": available_fonts()}


# --------------------------------------------------------------------------
# Proyectos
# --------------------------------------------------------------------------


class CreateProject(BaseModel):
    name: str = ""


@app.get("/api/projects")
def get_projects() -> dict:
    return {"projects": storage.list_projects()}


@app.post("/api/projects")
def post_project(body: CreateProject) -> dict:
    project = storage.create_project(body.name)
    return _project_payload(project)


@app.get("/api/projects/{project_id}")
def get_project(project_id: str) -> dict:
    return _project_payload(_load(project_id))


class PatchProject(BaseModel):
    name: Optional[str] = None
    prompt: Optional[str] = None
    style: Optional[dict] = None
    timeline: Optional[dict] = None
    # `assets` y `meta` permiten devolver el proyecto a un estado anterior,
    # que es lo que hace el botón «Deshacer» de la interfaz.
    assets: Optional[list[dict]] = None
    meta: Optional[dict] = None


@app.patch("/api/projects/{project_id}")
def patch_project(project_id: str, body: PatchProject) -> dict:
    with _lock_for(project_id):
        project = _load(project_id)
        if body.name is not None:
            project.name = body.name.strip() or project.name
        if body.prompt is not None:
            project.prompt = body.prompt
        if body.style is not None:
            merged = project.style.model_dump()
            merged.update(body.style)
            project.style = StyleSpec(**merged)
        if body.assets is not None:
            project.assets = [Asset.model_validate(a) for a in body.assets]
        if body.meta is not None:
            project.meta = dict(body.meta)
        if body.timeline is not None:
            project.timeline = Timeline.model_validate(body.timeline)
        # Los assets pueden haber cambiado, así que se revisa la línea de
        # tiempo aunque no llegue explícitamente.
        editing.normalize(project, project.timeline)
        return _project_payload(_save(project))


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str) -> dict:
    try:
        storage.delete_project(project_id)
    except storage.StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@app.post("/api/projects/{project_id}/duplicate")
def post_duplicate(project_id: str) -> dict:
    return _project_payload(storage.duplicate_project(project_id))


# --------------------------------------------------------------------------
# Material
# --------------------------------------------------------------------------


class ImportPaths(BaseModel):
    paths: list[str]
    copy_to_library: bool = False


@app.post("/api/projects/{project_id}/assets/path")
def post_assets_path(project_id: str, body: ImportPaths) -> dict:
    with _lock_for(project_id):
        project = _load(project_id)
        added, errors = storage.import_any(project, body.paths)
        _save(project)
    if added:
        _submit_analysis(project_id)
    return {"added": [a.model_dump() for a in added], "errors": errors,
            "project": _project_payload(_load(project_id))}


@app.post("/api/projects/{project_id}/assets/upload")
async def post_assets_upload(project_id: str, files: list[UploadFile]) -> dict:
    added, errors = [], []
    with _lock_for(project_id):
        project = _load(project_id)
        for upload in files:
            try:
                data = await upload.read()
                added.append(storage.import_bytes(project, upload.filename or "archivo", data))
            except storage.StorageError as exc:
                errors.append(f"{upload.filename}: {exc}")
            finally:
                await upload.close()
        _save(project)
    if added:
        _submit_analysis(project_id)
    return {"added": [a.model_dump() for a in added], "errors": errors,
            "project": _project_payload(_load(project_id))}


@app.delete("/api/projects/{project_id}/assets/{asset_id}")
def delete_asset(project_id: str, asset_id: str) -> dict:
    with _lock_for(project_id):
        project = _load(project_id)
        try:
            storage.remove_asset(project, asset_id)
        except storage.StorageError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        editing.normalize(project, project.timeline)
        return _project_payload(_save(project))


class AssetFlags(BaseModel):
    enabled: Optional[bool] = None
    tags: Optional[list[str]] = None


@app.patch("/api/projects/{project_id}/assets/{asset_id}")
def patch_asset(project_id: str, asset_id: str, body: AssetFlags) -> dict:
    with _lock_for(project_id):
        project = _load(project_id)
        asset = project.asset(asset_id)
        if asset is None:
            raise HTTPException(status_code=404, detail="Ese archivo no está en el proyecto")
        if body.enabled is not None:
            asset.enabled = body.enabled
        if body.tags is not None:
            asset.tags = body.tags
        return _project_payload(_save(project))


def _submit_analysis(project_id: str) -> str:
    """Lanza el análisis de los archivos nuevos en segundo plano."""

    def work(progress, cancel) -> dict:
        with _lock_for(project_id):
            project = storage.load_project(project_id)
            pending = [a for a in project.assets if not a.analysis.analyzed]
        analyzed = 0
        for i, asset in enumerate(pending):
            if cancel.is_set():
                break
            progress(i / max(1, len(pending)), f"Analizando {asset.name}")
            # El análisis es lento: se hace fuera del candado y luego se
            # vuelca sobre la versión más reciente del proyecto.
            fresh = storage.analyze_asset(
                Project(id=project_id, assets=[asset]), asset
            )
            with _lock_for(project_id):
                current = storage.load_project(project_id)
                target = current.asset(asset.id)
                if target is not None:
                    target.analysis = fresh.analysis
                    target.thumbnail = fresh.thumbnail or target.thumbnail
                    target.waveform = fresh.waveform or target.waveform
                    storage.save_project(current)
            analyzed += 1
        progress(1.0, f"{analyzed} archivo(s) analizados")
        return {"analyzed": analyzed}

    return JOBS.submit("analyze", work, project_id).id


@app.post("/api/projects/{project_id}/analyze")
def post_analyze(project_id: str, force: bool = Query(False)) -> dict:
    if force:
        with _lock_for(project_id):
            project = _load(project_id)
            for asset in project.assets:
                asset.analysis.analyzed = False
            _save(project)
    return {"job_id": _submit_analysis(project_id)}


@app.get("/api/projects/{project_id}/assets/{asset_id}/thumb")
def get_thumb(project_id: str, asset_id: str) -> Response:
    project = _load(project_id)
    asset = project.asset(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="No encontrado")
    if asset.thumbnail and Path(asset.thumbnail).exists():
        return FileResponse(asset.thumbnail, media_type="image/jpeg")
    if asset.kind == "image" and Path(asset.path).exists():
        return FileResponse(asset.path)
    raise HTTPException(status_code=404, detail="Sin miniatura todavía")


@app.get("/api/projects/{project_id}/assets/{asset_id}/media")
def get_media(project_id: str, asset_id: str, request: Request) -> Response:
    project = _load(project_id)
    asset = project.asset(asset_id)
    if asset is None or not Path(asset.path).exists():
        raise HTTPException(status_code=404, detail="Archivo no disponible")
    return _ranged_file(Path(asset.path), request)


# --------------------------------------------------------------------------
# Auto-edición
# --------------------------------------------------------------------------


class AutoEditBody(BaseModel):
    prompt: str = ""
    preset: Optional[str] = None
    engine: str = "heuristic"
    apply: bool = True


@app.post("/api/projects/{project_id}/interpret")
def post_interpret(project_id: str, body: AutoEditBody) -> dict:
    result = prompt_ai.interpret(body.prompt, body.preset, body.engine)
    return {
        "style": result.style.model_dump(),
        "base_preset": result.base_preset,
        "understood": result.understood,
        "ignored": result.ignored,
        "engine": result.engine,
    }


@app.post("/api/projects/{project_id}/autoedit")
def post_autoedit(project_id: str, body: AutoEditBody) -> dict:
    with _lock_for(project_id):
        project = _load(project_id)
        if not planner.visual_assets(project):
            raise HTTPException(
                status_code=400,
                detail="Primero importa algún vídeo o alguna foto.",
            )
        result = prompt_ai.interpret(body.prompt, body.preset, body.engine)
        project.prompt = body.prompt
        project.style = result.style
        project.timeline = planner.build_timeline(project, result.style)
        editing.normalize(project, project.timeline)
        payload = _project_payload(_save(project))
    payload["interpretation"] = {
        "understood": result.understood,
        "ignored": result.ignored,
        "engine": result.engine,
        "base_preset": result.base_preset,
    }
    return payload


@app.post("/api/projects/{project_id}/reshuffle")
def post_reshuffle(project_id: str, seed: Optional[int] = None) -> dict:
    with _lock_for(project_id):
        project = _load(project_id)
        if not planner.visual_assets(project):
            raise HTTPException(status_code=400, detail="No hay material que montar.")
        project.timeline = planner.reshuffle(project, seed)
        editing.normalize(project, project.timeline)
        return _project_payload(_save(project))


# --------------------------------------------------------------------------
# Edición manual
# --------------------------------------------------------------------------


class ClipUpdate(BaseModel):
    changes: dict[str, Any] = {}


class ClipMove(BaseModel):
    index: int


class ClipSplit(BaseModel):
    at: float


class ClipAdd(BaseModel):
    asset_id: str
    index: Optional[int] = None
    duration: Optional[float] = None


class TextBody(BaseModel):
    text: str = ""
    start: float = 0.0
    duration: float = 2.0
    style: Optional[dict] = None


class TextUpdate(BaseModel):
    changes: dict[str, Any] = {}


class MusicBody(BaseModel):
    asset_id: Optional[str] = None


def _edit(project_id: str, action) -> dict:
    with _lock_for(project_id):
        project = _load(project_id)
        try:
            action(project)
        except editing.EditError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _project_payload(_save(project))


@app.post("/api/projects/{project_id}/clips")
def post_clip(project_id: str, body: ClipAdd) -> dict:
    return _edit(
        project_id,
        lambda p: editing.add_clip(p, p.timeline, body.asset_id, body.index, body.duration),
    )


@app.patch("/api/projects/{project_id}/clips/{clip_id}")
def patch_clip(project_id: str, clip_id: str, body: ClipUpdate) -> dict:
    return _edit(project_id, lambda p: editing.update_clip(p, p.timeline, clip_id, body.changes))


@app.post("/api/projects/{project_id}/clips/{clip_id}/move")
def post_clip_move(project_id: str, clip_id: str, body: ClipMove) -> dict:
    return _edit(project_id, lambda p: editing.move_clip(p, p.timeline, clip_id, body.index))


@app.post("/api/projects/{project_id}/clips/{clip_id}/split")
def post_clip_split(project_id: str, clip_id: str, body: ClipSplit) -> dict:
    return _edit(project_id, lambda p: editing.split_clip(p, p.timeline, clip_id, body.at))


@app.post("/api/projects/{project_id}/clips/{clip_id}/duplicate")
def post_clip_duplicate(project_id: str, clip_id: str) -> dict:
    return _edit(project_id, lambda p: editing.duplicate_clip(p, p.timeline, clip_id))


@app.delete("/api/projects/{project_id}/clips/{clip_id}")
def delete_clip(project_id: str, clip_id: str) -> dict:
    return _edit(project_id, lambda p: editing.delete_clip(p, p.timeline, clip_id))


@app.post("/api/projects/{project_id}/clips/apply-all")
def post_apply_all(project_id: str, body: ClipUpdate) -> dict:
    return _edit(project_id, lambda p: editing.apply_to_all(p, p.timeline, body.changes))


@app.post("/api/projects/{project_id}/texts")
def post_text(project_id: str, body: TextBody) -> dict:
    return _edit(
        project_id,
        lambda p: editing.add_text(p.timeline, body.text, body.start, body.duration, body.style),
    )


@app.patch("/api/projects/{project_id}/texts/{text_id}")
def patch_text(project_id: str, text_id: str, body: TextUpdate) -> dict:
    return _edit(project_id, lambda p: editing.update_text(p.timeline, text_id, body.changes))


@app.delete("/api/projects/{project_id}/texts/{text_id}")
def delete_text(project_id: str, text_id: str) -> dict:
    return _edit(project_id, lambda p: editing.delete_text(p.timeline, text_id))


class TrackBody(BaseModel):
    name: str = ""


class TrackUpdate(BaseModel):
    changes: dict[str, Any] = {}


class AudioClipBody(BaseModel):
    asset_id: str
    start: float = 0.0


@app.post("/api/projects/{project_id}/tracks")
def post_track(project_id: str, body: TrackBody) -> dict:
    return _edit(project_id, lambda p: editing.add_audio_track(p.timeline, body.name))


@app.patch("/api/projects/{project_id}/tracks/{track_id}")
def patch_track(project_id: str, track_id: str, body: TrackUpdate) -> dict:
    return _edit(project_id, lambda p: editing.update_track(p.timeline, track_id, body.changes))


@app.delete("/api/projects/{project_id}/tracks/{track_id}")
def delete_track(project_id: str, track_id: str) -> dict:
    return _edit(project_id, lambda p: editing.remove_track(p.timeline, track_id))


@app.post("/api/projects/{project_id}/tracks/{track_id}/clips")
def post_track_clip(project_id: str, track_id: str, body: AudioClipBody) -> dict:
    return _edit(
        project_id,
        lambda p: editing.add_audio_clip(p, p.timeline, track_id, body.asset_id, body.start),
    )


@app.post("/api/projects/{project_id}/music")
def post_music(project_id: str, body: MusicBody) -> dict:
    return _edit(project_id, lambda p: editing.set_music(p, p.timeline, body.asset_id))


# --------------------------------------------------------------------------
# Render y exportación
# --------------------------------------------------------------------------


class RenderBody(BaseModel):
    preview: bool = False
    filename: str = ""


@app.post("/api/projects/{project_id}/render")
def post_render(project_id: str, body: RenderBody) -> dict:
    project = _load(project_id)
    problems = editing.validate(project, project.timeline)
    if problems:
        raise HTTPException(status_code=400, detail=problems[0])

    if body.preview:
        dest = SETTINGS.exports_dir(project_id) / "preview.mp4"
    else:
        name = body.filename or _safe_filename(project.name)
        dest = SETTINGS.exports_dir(project_id) / f"{name}.mp4"

    def work(progress, cancel) -> dict:
        current = storage.load_project(project_id)
        result = render_timeline(
            current, dest, preview=body.preview, on_progress=progress, cancel=cancel
        )
        if not body.preview:
            with _lock_for(project_id):
                latest = storage.load_project(project_id)
                storage.register_export(latest, "mp4", dest, note=f"{result.duration:.1f}s")
                storage.save_project(latest)
        return {
            "path": str(result.path),
            "url": f"/api/projects/{project_id}/file?path={result.path}",
            "duration": result.duration,
            "width": result.width,
            "height": result.height,
            "segments": result.segments,
            "reused": result.reused,
            "warnings": result.warnings,
            "preview": body.preview,
        }

    return {"job_id": JOBS.submit("preview" if body.preview else "render", work, project_id).id}


class ExportBody(BaseModel):
    format: str = "capcut"
    install: bool = False
    zip: bool = False


@app.post("/api/projects/{project_id}/export")
def post_export(project_id: str, body: ExportBody) -> dict:
    project = _load(project_id)
    problems = editing.validate(project, project.timeline)
    if problems and body.format != "project":
        raise HTTPException(status_code=400, detail=problems[0])

    exports = SETTINGS.exports_dir(project_id)
    exports.mkdir(parents=True, exist_ok=True)
    name = _safe_filename(project.name)

    def work(progress, cancel) -> dict:
        progress(0.15, "Preparando la exportación")
        current = storage.load_project(project_id)
        if body.format == "capcut":
            if body.zip:
                report = capcut.export_capcut_zip(current, exports / f"{name}_capcut.zip")
            else:
                report = capcut.export_capcut(current, exports, install=body.install)
            path = Path(report.get("zip") or report["folder"])
        elif body.format == "fcpxml":
            report = fcpxml.export_fcpxml(current, exports / f"{name}.fcpxml")
            path = Path(report["path"])
        elif body.format == "edl":
            report = edl.export_edl(current, exports / f"{name}.edl")
            path = Path(report["path"])
        elif body.format == "project":
            report = edl.export_project_json(current, exports / f"{name}.autoedit.json")
            path = Path(report["path"])
        elif body.format == "shotlist":
            path = exports / f"{name}_escaleta.md"
            path.write_text(edl.build_shotlist(current), "utf-8")
            report = {"path": str(path), "notes": []}
        else:
            raise ValueError(f"Formato desconocido: {body.format}")

        progress(0.9, "Registrando la exportación")
        with _lock_for(project_id):
            latest = storage.load_project(project_id)
            storage.register_export(latest, body.format, path)
            storage.save_project(latest)
        report["format"] = body.format
        report["download"] = (
            f"/api/projects/{project_id}/file?path={path}" if path.is_file() else None
        )
        return report

    return {"job_id": JOBS.submit(f"export:{body.format}", work, project_id).id}


@app.get("/api/projects/{project_id}/file")
def get_file(project_id: str, path: str, request: Request, download: bool = False) -> Response:
    """Sirve un archivo generado por el proyecto.

    Solo se permiten rutas dentro de la carpeta de trabajo de AutoEdit: la
    interfaz corre en un navegador y no queremos que una URL manipulada pueda
    leer cualquier cosa del disco.
    """
    target = Path(path).expanduser()
    try:
        target = target.resolve()
        target.relative_to(SETTINGS.home.resolve())
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=403, detail="Ruta fuera de la carpeta de AutoEdit") from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail="El archivo ya no está")
    if download:
        return FileResponse(target, filename=target.name)
    return _ranged_file(target, request)


@app.get("/api/projects/{project_id}/exports")
def get_exports(project_id: str) -> dict:
    project = _load(project_id)
    out = []
    for record in project.exports:
        path = Path(record.path)
        out.append({
            **record.model_dump(),
            "exists": path.exists(),
            "is_dir": path.is_dir(),
            "download": f"/api/projects/{project_id}/file?path={record.path}&download=true"
            if path.is_file() else None,
        })
    return {"exports": out}


# --------------------------------------------------------------------------
# Trabajos
# --------------------------------------------------------------------------


@app.get("/api/jobs")
def get_jobs(project_id: str = "", active: bool = False) -> dict:
    return {"jobs": [j.to_dict() for j in JOBS.list(project_id, active)]}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Ese trabajo ya no existe")
    return job.to_dict()


@app.post("/api/jobs/{job_id}/cancel")
def post_job_cancel(job_id: str) -> dict:
    return {"cancelled": JOBS.cancel(job_id)}


# --------------------------------------------------------------------------
# Utilidades del sistema de archivos (selector de la interfaz)
# --------------------------------------------------------------------------


@app.get("/api/browse")
def get_browse(path: str = "") -> dict:
    """Explorador sencillo para importar por ruta sin salir del navegador."""
    directory = Path(path).expanduser() if path else Path.home()
    if not directory.is_dir():
        directory = Path.home()
    entries = []
    try:
        for item in sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if item.name.startswith("."):
                continue
            is_media = item.suffix.lower() in storage.SUPPORTED_EXT
            if item.is_dir() or is_media:
                entries.append({
                    "name": item.name,
                    "path": str(item),
                    "is_dir": item.is_dir(),
                    "size": item.stat().st_size if item.is_file() else 0,
                })
    except PermissionError:
        raise HTTPException(status_code=403, detail="Sin permiso para leer esa carpeta")
    return {
        "path": str(directory),
        "parent": str(directory.parent) if directory.parent != directory else None,
        "entries": entries[:500],
    }


# --------------------------------------------------------------------------
# Interfaz
# --------------------------------------------------------------------------

if WEB_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> Response:
    html = WEB_DIR / "index.html"
    if not html.exists():
        return HTMLResponse("<h1>AutoEdit</h1><p>Falta la carpeta <code>web/</code>.</p>", 500)
    return HTMLResponse(html.read_text("utf-8"))


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


def _ranged_file(path: Path, request: Request) -> Response:
    """Sirve un archivo con soporte de `Range`, para que el vídeo se pueda buscar."""
    size = path.stat().st_size
    media_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    range_header = request.headers.get("range")
    if not range_header:
        return FileResponse(path, media_type=media_type)

    match = _RANGE_RE.match(range_header)
    if not match:
        return FileResponse(path, media_type=media_type)
    start = int(match.group(1)) if match.group(1) else 0
    end = int(match.group(2)) if match.group(2) else size - 1
    start, end = max(0, start), min(end, size - 1)
    if start > end:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})

    with path.open("rb") as handle:
        handle.seek(start)
        data = handle.read(end - start + 1)
    return Response(
        content=data,
        status_code=206,
        media_type=media_type,
        headers={
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(len(data)),
        },
    )


def _safe_filename(name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in " -_" else "_" for c in name).strip()
    return (cleaned or "autoedit").replace(" ", "_")[:60]


@app.exception_handler(ValueError)
def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})
