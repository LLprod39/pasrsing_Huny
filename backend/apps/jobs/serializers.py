from __future__ import annotations

from rest_framework import serializers

from .models import Job


class JobSerializer(serializers.ModelSerializer):
    class Meta:
        model = Job
        fields = (
            "id",
            "student",
            "type",
            "status",
            "progress",
            "message",
            "error",
            "params",
            "result",
            "celery_task_id",
            "created_at",
            "started_at",
            "finished_at",
            "updated_at",
        )
        read_only_fields = fields

