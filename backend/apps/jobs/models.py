from __future__ import annotations

import uuid

from django.db import models


class JobStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class JobType(models.TextChoices):
    LOGIN = "login", "Login"
    SYNC_SEMESTERS = "sync_semesters", "Sync semesters"
    SYNC_COURSES = "sync_courses", "Sync courses"
    SYNC_MATERIALS = "sync_materials", "Sync materials"
    SYNC_FULL = "sync_full", "Sync full (semesters/courses/materials)"
    PROCESS_MATERIAL = "process_material", "Process material"
    SOLVE_TEST = "solve_test", "Solve test"


class Job(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    student = models.ForeignKey("accounts.Student", on_delete=models.CASCADE, related_name="jobs")
    type = models.CharField(max_length=64, choices=JobType.choices)
    status = models.CharField(max_length=32, choices=JobStatus.choices, default=JobStatus.PENDING)

    progress = models.PositiveSmallIntegerField(default=0)
    message = models.CharField(max_length=500, blank=True, default="")
    error = models.TextField(blank=True, default="")

    params = models.JSONField(null=True, blank=True)
    result = models.JSONField(null=True, blank=True)

    celery_task_id = models.CharField(max_length=255, blank=True, default="", db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["student", "status"]),
            models.Index(fields=["type", "status"]),
        ]

    def __str__(self) -> str:
        return f"Job({self.type}, {self.status}, student={self.student_id})"

