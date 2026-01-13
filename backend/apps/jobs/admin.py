from __future__ import annotations

from django.contrib import admin
from django.utils import timezone

from unfold.admin import ModelAdmin

from .models import Job
from .models import JobStatus, JobType
from .tasks import (
    synergy_login_job,
    synergy_process_material_job,
    synergy_solve_test_job,
    synergy_sync_courses_job,
    synergy_sync_full_job,
    synergy_sync_materials_job,
    synergy_sync_semesters_job,
)


@admin.register(Job)
class JobAdmin(ModelAdmin):
    list_display = ("id", "type", "status", "student", "progress", "created_at", "started_at", "finished_at")
    list_filter = ("type", "status")
    list_filter_submit = True
    search_fields = ("id", "celery_task_id", "student__full_name", "student__email", "student__external_id")
    readonly_fields = ("id", "created_at", "updated_at", "started_at", "finished_at", "celery_task_id")
    list_select_related = ("student",)
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    actions = ("requeue_selected", "cancel_selected")

    def has_add_permission(self, request):
        # Prevent manual creation of jobs (these won't be enqueued and will sit in PENDING forever).
        return False

    @admin.action(description="Requeue выбранные jobs (поставить в Celery заново)")
    def requeue_selected(self, request, queryset):
        """Re-enqueue jobs to Celery based on their type.

        Useful when Redis/worker was down and you have PENDING jobs without celery_task_id.
        """

        type_to_task = {
            JobType.LOGIN: synergy_login_job,
            JobType.SYNC_SEMESTERS: synergy_sync_semesters_job,
            JobType.SYNC_COURSES: synergy_sync_courses_job,
            JobType.SYNC_MATERIALS: synergy_sync_materials_job,
            JobType.SYNC_FULL: synergy_sync_full_job,
            JobType.PROCESS_MATERIAL: synergy_process_material_job,
            JobType.SOLVE_TEST: synergy_solve_test_job,
        }

        queued = 0
        failed = 0
        for job in queryset:
            task = type_to_task.get(job.type)
            if not task:
                failed += 1
                continue
            try:
                async_result = task.delay(str(job.id))
                job.celery_task_id = async_result.id
                # keep status as pending; worker will mark RUNNING when it starts
                job.status = JobStatus.PENDING
                job.message = "Requeued"
                job.error = ""
                job.started_at = None
                job.finished_at = None
                job.progress = 0
                job.save(
                    update_fields=[
                        "celery_task_id",
                        "status",
                        "message",
                        "error",
                        "started_at",
                        "finished_at",
                        "progress",
                        "updated_at",
                    ]
                )
                queued += 1
            except Exception as e:
                job.status = JobStatus.FAILED
                job.error = f"Failed to enqueue: {e}"
                job.message = "Enqueue failed"
                job.finished_at = timezone.now()
                job.save(update_fields=["status", "error", "message", "finished_at", "updated_at"])
                failed += 1

        self.message_user(request, f"Queued: {queued}, failed: {failed}.")

    @admin.action(description="Cancel выбранные jobs")
    def cancel_selected(self, request, queryset):
        now = timezone.now()
        updated = queryset.exclude(status__in=[JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]).update(
            status=JobStatus.CANCELLED, message="Cancelled", finished_at=now, updated_at=now
        )
        self.message_user(request, f"Cancelled: {updated}.")

