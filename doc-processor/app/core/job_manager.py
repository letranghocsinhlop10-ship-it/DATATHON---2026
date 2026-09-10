"""In-memory job tracker for the demo UI.

A "job" is one run of the pipeline over an input folder, executed on a
background thread so the HTTP request that starts it returns
immediately and the UI can poll for progress. This is intentionally
simple (a process-local dict, no persistence/queue) — plenty for a
single-user demo tool; swap for a real task queue if this ever needs to
serve multiple concurrent users reliably.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.core.logging_config import get_logger
from app.models.schema import DocumentSet, JobSummary
from app.pipeline import run_pipeline

log = get_logger("job_manager")


@dataclass
class JobState:
    id: str
    input_dir: str
    output_dir: str
    status: str = "pending"  # pending | running | done | error
    processed: int = 0
    total: int = 0
    stage: str = ""
    error: Optional[str] = None
    document_sets: list[DocumentSet] = field(default_factory=list)
    summary: Optional[JobSummary] = None


_jobs: dict[str, JobState] = {}
_lock = threading.Lock()


def create_job(input_dir: str, output_dir: str) -> JobState:
    job = JobState(id=str(uuid.uuid4()), input_dir=input_dir, output_dir=output_dir)
    with _lock:
        _jobs[job.id] = job
    thread = threading.Thread(target=_run_job, args=(job,), daemon=True)
    thread.start()
    return job


def get_job(job_id: str) -> Optional[JobState]:
    return _jobs.get(job_id)


def list_jobs() -> list[JobState]:
    return list(_jobs.values())


def _run_job(job: JobState) -> None:
    job.status = "running"
    try:
        if not Path(job.input_dir).is_dir():
            raise FileNotFoundError(f"Không tìm thấy thư mục input: {job.input_dir}")

        def progress_cb(done: int, total: int, stage: str) -> None:
            job.processed = done
            job.total = total
            job.stage = stage

        document_sets, summary = run_pipeline(job.input_dir, job.output_dir, progress_cb)
        job.document_sets = document_sets
        job.summary = summary
        job.status = "done"
    except Exception as exc:  # pragma: no cover - surfaced to the UI instead
        log.exception("Job %s thất bại", job.id)
        job.status = "error"
        job.error = str(exc)
