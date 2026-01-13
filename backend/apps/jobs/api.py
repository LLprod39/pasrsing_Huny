from __future__ import annotations

from celery.result import AsyncResult
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Job, JobStatus
from .serializers import JobSerializer


class JobViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Job.objects.select_related("student").all().order_by("-created_at")
    serializer_class = JobSerializer

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        job = self.get_object()
        if job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            return Response(JobSerializer(job).data)

        job.status = JobStatus.CANCELLED
        job.message = "Cancelled"
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "message", "finished_at", "updated_at"])

        # Best-effort: revoke if still pending (won't safely stop Selenium if already running).
        if job.celery_task_id:
            try:
                AsyncResult(job.celery_task_id).revoke(terminate=False)
            except Exception:
                pass

        return Response(JobSerializer(job).data, status=status.HTTP_200_OK)

