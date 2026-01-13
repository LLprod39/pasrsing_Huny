from __future__ import annotations

from apps.jobs.models import Job, JobStatus


def pending_jobs_badge(request) -> str:
    """Badge counter for the admin sidebar (pending + running jobs)."""

    count = Job.objects.filter(status__in=[JobStatus.PENDING, JobStatus.RUNNING]).count()
    return str(count) if count else ""

