from __future__ import annotations

from django.contrib import admin

from unfold.admin import ModelAdmin

from .models import Job


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

