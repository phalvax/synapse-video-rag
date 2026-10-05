"""Suivi des jobs d'ingestion (upload -> transcription -> réindexation).

ponytail: dict en mémoire + un thread par job. Convient à la démo (un backend, un upload à
la fois en pratique) ; passer à une vraie file (RQ/Celery) si plusieurs workers ou une reprise
après crash deviennent nécessaires.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

Status = Literal["queued", "transcribing", "indexing", "done", "failed", "duplicate"]


@dataclass
class Job:
    id: str
    status: Status = "queued"
    video_id: str | None = None
    error: str | None = None
    duplicate_of: str | None = None  # quasi-doublon : l'enregistrement qui contient déjà ce contenu
    similarity: float | None = None  # part du nouveau transcript déjà présente (0 à 1)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def create_job() -> Job:
    job = Job(id=uuid.uuid4().hex[:12])
    with _lock:
        _jobs[job.id] = job
    return job


def get_job(job_id: str) -> Job | None:
    with _lock:
        return _jobs.get(job_id)


def update_job(job_id: str, **fields: object) -> None:
    with _lock:
        job = _jobs[job_id]
        for k, v in fields.items():
            setattr(job, k, v)
        job.updated_at = time.time()


def run_in_background(job_id: str, fn: Callable[..., None], *args: object) -> None:
    def _run() -> None:
        try:
            fn(*args)
        except Exception as exc:  # noqa: BLE001 — le job échoué doit rester consultable
            update_job(job_id, status="failed", error=str(exc)[:500])

    threading.Thread(target=_run, daemon=True).start()
