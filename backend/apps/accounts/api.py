from __future__ import annotations

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.jobs.models import Job, JobStatus, JobType
from apps.jobs.serializers import JobSerializer
from apps.jobs.enqueue import enqueue_job
from apps.synergy.models import Course, Material, Semester, SynergyCredential
from apps.synergy.serializers import (
    CourseSerializer,
    MaterialSerializer,
    SemesterSerializer,
    SynergyCredentialSerializer,
    SynergyCredentialUpsertSerializer,
)

from .models import Student
from .serializers import StudentSerializer


class StudentViewSet(viewsets.ModelViewSet):
    queryset = Student.objects.all().order_by("-id")
    serializer_class = StudentSerializer

    @action(detail=True, methods=["get", "put"], url_path="synergy-credential")
    def synergy_credential(self, request, pk=None):
        student = self.get_object()

        if request.method == "GET":
            cred = SynergyCredential.objects.filter(student=student).first()
            if not cred:
                return Response({"detail": "Not set"}, status=status.HTTP_404_NOT_FOUND)
            return Response(SynergyCredentialSerializer(cred).data)

        serializer = SynergyCredentialUpsertSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        login = serializer.validated_data["login"].strip()
        password = (serializer.validated_data.get("password") or "").strip()

        cred, _created = SynergyCredential.objects.get_or_create(student=student, defaults={"login": login})
        cred.login = login
        if password:
            cred.set_password(password)
        cred.save()

        return Response(SynergyCredentialSerializer(cred).data)

    @action(detail=True, methods=["post"], url_path="synergy-login")
    def synergy_login(self, request, pk=None):
        student = self.get_object()

        job = Job.objects.create(student=student, type=JobType.LOGIN, status=JobStatus.PENDING, params=None, result=None)
        enqueue_job(job)

        return Response(JobSerializer(job).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["post"], url_path="sync-semesters")
    def sync_semesters(self, request, pk=None):
        student = self.get_object()

        job = Job.objects.create(
            student=student, type=JobType.SYNC_SEMESTERS, status=JobStatus.PENDING, params=None, result=None
        )
        enqueue_job(job)

        return Response(JobSerializer(job).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["post"], url_path="sync-courses")
    def sync_courses(self, request, pk=None):
        student = self.get_object()
        try:
            semester_number = int(request.data.get("semester_number") or 0)
        except (TypeError, ValueError):
            semester_number = 0
        if semester_number <= 0:
            return Response({"detail": "semester_number is required"}, status=status.HTTP_400_BAD_REQUEST)

        job = Job.objects.create(
            student=student,
            type=JobType.SYNC_COURSES,
            status=JobStatus.PENDING,
            params={"semester_number": semester_number},
            result=None,
        )
        enqueue_job(job)
        return Response(JobSerializer(job).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["post"], url_path="sync-materials")
    def sync_materials(self, request, pk=None):
        student = self.get_object()
        try:
            course_id = int(request.data.get("course_id") or 0)
        except (TypeError, ValueError):
            course_id = 0
        if course_id <= 0:
            return Response({"detail": "course_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        job = Job.objects.create(
            student=student,
            type=JobType.SYNC_MATERIALS,
            status=JobStatus.PENDING,
            params={"course_id": course_id},
            result=None,
        )
        enqueue_job(job)
        return Response(JobSerializer(job).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["get"], url_path="semesters")
    def list_semesters(self, request, pk=None):
        student = self.get_object()
        qs = Semester.objects.filter(student=student).order_by("number")
        return Response(SemesterSerializer(qs, many=True).data)

    @action(detail=True, methods=["get"], url_path="courses")
    def list_courses(self, request, pk=None):
        student = self.get_object()
        semester_number = request.query_params.get("semester_number")
        qs = Course.objects.filter(student=student).order_by("semester_number", "name")
        if semester_number:
            try:
                qs = qs.filter(semester_number=int(semester_number))
            except (TypeError, ValueError):
                return Response({"detail": "semester_number must be int"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(CourseSerializer(qs, many=True).data)

    @action(detail=True, methods=["get"], url_path="materials")
    def list_materials(self, request, pk=None):
        student = self.get_object()
        course_id = request.query_params.get("course_id")
        qs = Material.objects.filter(student=student).order_by("course_id", "name")
        if course_id:
            try:
                qs = qs.filter(course_id=int(course_id))
            except (TypeError, ValueError):
                return Response({"detail": "course_id must be int"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(MaterialSerializer(qs, many=True).data)

