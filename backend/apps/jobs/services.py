from __future__ import annotations

from typing import Any, Optional

from django.utils import timezone

from .models import Job, JobStatus


def mark_running(job: Job, *, celery_task_id: str, message: str = "") -> None:
    job.status = JobStatus.RUNNING
    job.started_at = job.started_at or timezone.now()
    job.message = message or job.message
    job.progress = max(job.progress, 1)
    job.celery_task_id = celery_task_id
    job.save(update_fields=["status", "started_at", "message", "progress", "celery_task_id", "updated_at"])


def set_progress(job: Job, *, progress: int, message: str = "") -> None:
    job.progress = max(0, min(int(progress), 100))
    if message:
        job.message = message
    job.save(update_fields=["progress", "message", "updated_at"])


def mark_completed(job: Job, *, result: Optional[dict[str, Any]] = None, message: str = "Completed") -> None:
    job.status = JobStatus.COMPLETED
    job.progress = 100
    job.message = message
    job.finished_at = timezone.now()
    if result is not None:
        job.result = result
    job.save(update_fields=["status", "progress", "message", "finished_at", "result", "updated_at"])


def mark_failed(job: Job, *, error: str, message: str = "Failed") -> None:
    job.status = JobStatus.FAILED
    job.message = message
    job.error = error
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "message", "error", "finished_at", "updated_at"])

