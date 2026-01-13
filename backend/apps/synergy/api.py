from __future__ import annotations

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.jobs.models import Job, JobStatus, JobType
from apps.jobs.serializers import JobSerializer
from apps.jobs.tasks import synergy_process_material_job, synergy_solve_test_job

from .models import Material
from .serializers import MaterialSerializer


class MaterialViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Material.objects.select_related("student", "course").all().order_by("-updated_at")
    serializer_class = MaterialSerializer

    @action(detail=True, methods=["post"], url_path="process")
    def process(self, request, pk=None):
        material = self.get_object()
        job = Job.objects.create(
            student=material.student,
            type=JobType.PROCESS_MATERIAL,
            status=JobStatus.PENDING,
            params={"material_id": material.id},
            result=None,
        )
        async_result = synergy_process_material_job.delay(str(job.id))
        job.celery_task_id = async_result.id
        job.save(update_fields=["celery_task_id", "updated_at"])
        return Response(JobSerializer(job).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["post"], url_path="solve_test")
    def solve_test(self, request, pk=None):
        material = self.get_object()
        job = Job.objects.create(
            student=material.student,
            type=JobType.SOLVE_TEST,
            status=JobStatus.PENDING,
            params={"material_id": material.id},
            result=None,
        )
        async_result = synergy_solve_test_job.delay(str(job.id))
        job.celery_task_id = async_result.id
        job.save(update_fields=["celery_task_id", "updated_at"])
        return Response(JobSerializer(job).data, status=status.HTTP_202_ACCEPTED)

