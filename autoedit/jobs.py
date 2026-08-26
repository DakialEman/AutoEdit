"""Trabajos en segundo plano (análisis, render, exportación).

Analizar y renderizar tarda; la interfaz no puede quedarse bloqueada. Cada
tarea larga se envía aquí, se ejecuta en un hilo aparte y publica su progreso
para que la interfaz lo consulte.
"""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

JobFn = Callable[[Callable[[float, str], None], threading.Event], Any]


@dataclass
class Job:
    id: str
    kind: str
    project_id: str = ""
    status: str = "queued"          # queued | running | done | error | cancelled
    progress: float = 0.0
    message: str = "En cola"
    result: Any = None
    error: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    finished_at: float = 0.0
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "project_id": self.project_id,
            "status": self.status,
            "progress": round(self.progress, 4),
            "message": self.message,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed": round((self.finished_at or time.time()) - (self.started_at or self.created_at), 1),
        }


class JobManager:
    def __init__(self, workers: int = 2):
        # FFmpeg ya usa todos los núcleos: lanzar muchos trabajos a la vez
        # solo consigue que todos vayan lentos.
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="autoedit")
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def submit(self, kind: str, fn: JobFn, project_id: str = "") -> Job:
        job = Job(id=f"job_{uuid.uuid4().hex[:12]}", kind=kind, project_id=project_id)
        with self._lock:
            self._jobs[job.id] = job
            self._prune_locked()
        self._pool.submit(self._run, job, fn)
        return job

    def _run(self, job: Job, fn: JobFn) -> None:
        if job.cancel_event.is_set():
            job.status, job.message = "cancelled", "Cancelado antes de empezar"
            job.finished_at = time.time()
            return
        job.status, job.started_at, job.message = "running", time.time(), "Empezando"

        def progress(fraction: float, message: str = "") -> None:
            job.progress = max(0.0, min(1.0, float(fraction)))
            if message:
                job.message = message

        try:
            job.result = fn(progress, job.cancel_event)
            if job.cancel_event.is_set():
                job.status, job.message = "cancelled", "Cancelado"
            else:
                job.status, job.progress, job.message = "done", 1.0, "Listo"
        except Exception as exc:
            if job.cancel_event.is_set():
                job.status, job.message = "cancelled", "Cancelado"
            else:
                job.status = "error"
                job.error = str(exc)
                job.message = _short(str(exc))
                traceback.print_exc()
        finally:
            job.finished_at = time.time()

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def list(self, project_id: str = "", active_only: bool = False) -> list[Job]:
        with self._lock:
            jobs = list(self._jobs.values())
        if project_id:
            jobs = [j for j in jobs if j.project_id == project_id]
        if active_only:
            jobs = [j for j in jobs if j.status in ("queued", "running")]
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.status in ("done", "error", "cancelled"):
            return False
        job.cancel_event.set()
        job.message = "Cancelando…"
        return True

    def _prune_locked(self, keep: int = 60) -> None:
        finished = [j for j in self._jobs.values() if j.status in ("done", "error", "cancelled")]
        if len(finished) <= keep:
            return
        finished.sort(key=lambda j: j.finished_at)
        for job in finished[: len(finished) - keep]:
            self._jobs.pop(job.id, None)

    def shutdown(self) -> None:
        for job in self.list(active_only=True):
            job.cancel_event.set()
        self._pool.shutdown(wait=False, cancel_futures=True)


def _short(message: str, limit: int = 220) -> str:
    text = " ".join(message.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


JOBS = JobManager()
