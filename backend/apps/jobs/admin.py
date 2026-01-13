from __future__ import annotations

from django.contrib import admin

from .models import Job


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ("id", "type", "status", "student", "progress", "created_at", "started_at", "finished_at")
    list_filter = ("type", "status")
    search_fields = ("id", "celery_task_id", "student__full_name", "student__email", "student__external_id")
    readonly_fields = ("id", "created_at", "updated_at", "started_at", "finished_at", "celery_task_id")

