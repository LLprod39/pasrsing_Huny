from __future__ import annotations

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.jobs.models import Job, JobStatus, JobType
from apps.jobs.serializers import JobSerializer
from apps.jobs.enqueue import enqueue_job

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
        enqueue_job(job)
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
        enqueue_job(job)
        return Response(JobSerializer(job).data, status=status.HTTP_202_ACCEPTED)

