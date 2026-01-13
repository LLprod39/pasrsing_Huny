from __future__ import annotations

from django.contrib import admin

from apps.jobs.models import Job, JobStatus, JobType
from apps.jobs.tasks import synergy_login_job, synergy_sync_semesters_job

from .models import Student


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("id", "full_name", "email", "phone", "external_id", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("full_name", "email", "phone", "external_id")
    actions = ("queue_synergy_login", "queue_sync_semesters")

    @admin.action(description="Synergy: проверить логин (создать Job)")
    def queue_synergy_login(self, request, queryset):
        created = 0
        for student in queryset:
            job = Job.objects.create(student=student, type=JobType.LOGIN, status=JobStatus.PENDING, params=None, result=None)
            async_result = synergy_login_job.delay(str(job.id))
            job.celery_task_id = async_result.id
            job.save(update_fields=["celery_task_id", "updated_at"])
            created += 1
        self.message_user(request, f"Queued {created} login job(s).")

    @admin.action(description="Synergy: синхронизировать семестры (создать Job)")
    def queue_sync_semesters(self, request, queryset):
        created = 0
        for student in queryset:
            job = Job.objects.create(
                student=student, type=JobType.SYNC_SEMESTERS, status=JobStatus.PENDING, params=None, result=None
            )
            async_result = synergy_sync_semesters_job.delay(str(job.id))
            job.celery_task_id = async_result.id
            job.save(update_fields=["celery_task_id", "updated_at"])
            created += 1
        self.message_user(request, f"Queued {created} sync_semesters job(s).")

