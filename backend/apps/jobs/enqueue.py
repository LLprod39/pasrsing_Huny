from __future__ import annotations

from typing import Callable

from django.utils import timezone

from .models import Job, JobStatus, JobType
from .tasks import (
    synergy_login_job,
    synergy_process_material_job,
    synergy_solve_test_job,
    synergy_sync_courses_job,
    synergy_sync_full_job,
    synergy_sync_materials_job,
    synergy_sync_semesters_job,
)


def _task_for_type(job_type: str) -> Callable[[str], object] | None:
    mapping = {
        JobType.LOGIN: synergy_login_job,
        JobType.SYNC_SEMESTERS: synergy_sync_semesters_job,
        JobType.SYNC_COURSES: synergy_sync_courses_job,
        JobType.SYNC_MATERIALS: synergy_sync_materials_job,
        JobType.SYNC_FULL: synergy_sync_full_job,
        JobType.PROCESS_MATERIAL: synergy_process_material_job,
        JobType.SOLVE_TEST: synergy_solve_test_job,
    }
    return mapping.get(job_type)


def enqueue_job(job: Job) -> bool:
    """Best-effort enqueue.

    - On success: sets `celery_task_id`
    - On failure (broker down, etc): marks job FAILED with error
    """

    task = _task_for_type(job.type)
    if not task:
        job.status = JobStatus.FAILED
        job.message = "Enqueue failed"
        job.error = f"Unknown job type: {job.type}"
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "message", "error", "finished_at", "updated_at"])
        return False

    try:
        async_result = task.delay(str(job.id))
        job.celery_task_id = async_result.id
        job.save(update_fields=["celery_task_id", "updated_at"])
        return True
    except Exception as e:
        job.status = JobStatus.FAILED
        job.message = "Enqueue failed"
        job.error = f"{type(e).__name__}: {e}"
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "message", "error", "finished_at", "updated_at"])
        return False

