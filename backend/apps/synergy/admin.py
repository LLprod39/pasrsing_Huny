from __future__ import annotations

from django.contrib import admin

from apps.jobs.models import Job, JobStatus, JobType
from apps.jobs.tasks import (
    synergy_process_material_job,
    synergy_solve_test_job,
    synergy_sync_courses_job,
    synergy_sync_materials_job,
)

from .forms import SynergyCredentialForm
from .models import Course, Material, Semester, SynergyCredential


@admin.register(SynergyCredential)
class SynergyCredentialAdmin(admin.ModelAdmin):
    form = SynergyCredentialForm
    list_display = ("id", "student", "login", "has_password", "last_validated_at", "updated_at")
    search_fields = ("login", "student__full_name", "student__email", "student__external_id")


@admin.register(Semester)
class SemesterAdmin(admin.ModelAdmin):
    list_display = ("id", "student", "number", "updated_at")
    list_filter = ("number",)
    search_fields = ("student__full_name", "student__email", "student__external_id")
    actions = ("queue_sync_courses",)

    @admin.action(description="Synergy: синхронизировать курсы (для выбранных семестров)")
    def queue_sync_courses(self, request, queryset):
        created = 0
        for semester in queryset.select_related("student"):
            job = Job.objects.create(
                student=semester.student,
                type=JobType.SYNC_COURSES,
                status=JobStatus.PENDING,
                params={"semester_number": semester.number},
                result=None,
            )
            async_result = synergy_sync_courses_job.delay(str(job.id))
            job.celery_task_id = async_result.id
            job.save(update_fields=["celery_task_id", "updated_at"])
            created += 1
        self.message_user(request, f"Queued {created} sync_courses job(s).")


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("id", "student", "semester_number", "name", "control_type", "updated_at")
    list_filter = ("semester_number", "control_type")
    search_fields = ("name", "url", "student__full_name", "student__email")
    actions = ("queue_sync_materials",)

    @admin.action(description="Synergy: синхронизировать материалы (для выбранных курсов)")
    def queue_sync_materials(self, request, queryset):
        created = 0
        for course in queryset.select_related("student"):
            job = Job.objects.create(
                student=course.student,
                type=JobType.SYNC_MATERIALS,
                status=JobStatus.PENDING,
                params={"course_id": course.id},
                result=None,
            )
            async_result = synergy_sync_materials_job.delay(str(job.id))
            job.celery_task_id = async_result.id
            job.save(update_fields=["celery_task_id", "updated_at"])
            created += 1
        self.message_user(request, f"Queued {created} sync_materials job(s).")


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ("id", "student", "course", "type", "name", "is_blocked", "last_processed_at", "updated_at")
    list_filter = ("type", "is_blocked")
    search_fields = ("name", "url", "course__name", "student__full_name", "student__email")
    actions = ("queue_process_material", "queue_solve_test")

    @admin.action(description="Synergy: обработать материал (создать Job)")
    def queue_process_material(self, request, queryset):
        created = 0
        skipped = 0
        for m in queryset.select_related("student"):
            if m.is_blocked or not m.url:
                skipped += 1
                continue
            job = Job.objects.create(
                student=m.student, type=JobType.PROCESS_MATERIAL, status=JobStatus.PENDING, params={"material_id": m.id}
            )
            async_result = synergy_process_material_job.delay(str(job.id))
            job.celery_task_id = async_result.id
            job.save(update_fields=["celery_task_id", "updated_at"])
            created += 1
        self.message_user(request, f"Queued {created} process_material job(s). Skipped: {skipped}.")

    @admin.action(description="Synergy: решить тест (создать Job)")
    def queue_solve_test(self, request, queryset):
        created = 0
        skipped = 0
        for m in queryset.select_related("student"):
            if m.is_blocked or not m.url:
                skipped += 1
                continue
            # Optional heuristic: only allow for test materials.
            if (m.type or "").lower() != "test":
                skipped += 1
                continue
            job = Job.objects.create(
                student=m.student, type=JobType.SOLVE_TEST, status=JobStatus.PENDING, params={"material_id": m.id}
            )
            async_result = synergy_solve_test_job.delay(str(job.id))
            job.celery_task_id = async_result.id
            job.save(update_fields=["celery_task_id", "updated_at"])
            created += 1
        self.message_user(request, f"Queued {created} solve_test job(s). Skipped: {skipped}.")

