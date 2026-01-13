from __future__ import annotations

from rest_framework import serializers

from .models import Course, Material, Semester, SynergyCredential


class SynergyCredentialSerializer(serializers.ModelSerializer):
    """Read-only serializer for Synergy credentials (never returns password)."""

    has_password = serializers.BooleanField(read_only=True)

    class Meta:
        model = SynergyCredential
        fields = ("id", "student", "login", "has_password", "last_validated_at", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at", "has_password", "last_validated_at")


class SynergyCredentialUpsertSerializer(serializers.Serializer):
    login = serializers.CharField(max_length=255)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)


class SemesterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Semester
        fields = ("id", "student", "number", "created_at", "updated_at")
        read_only_fields = fields


class CourseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = ("id", "student", "semester_number", "name", "url", "control_type", "created_at", "updated_at")
        read_only_fields = fields


class MaterialSerializer(serializers.ModelSerializer):
    class Meta:
        model = Material
        fields = (
            "id",
            "student",
            "course",
            "name",
            "url",
            "type",
            "is_blocked",
            "data_index",
            "last_processed_at",
            "last_result",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

