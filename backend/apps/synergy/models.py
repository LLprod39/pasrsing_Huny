from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models

from .crypto import decrypt_str, encrypt_str


class SynergyCredential(models.Model):
    """Synergy-логин/пароль студента.

    Пароль будет храниться в зашифрованном виде (поле заменим в следующем шаге).
    """

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    student = models.OneToOneField("accounts.Student", on_delete=models.CASCADE, related_name="synergy_credential")
    login = models.CharField(max_length=255)
    password_encrypted = models.TextField(blank=True, default="")

    last_validated_at = models.DateTimeField(null=True, blank=True)

    def set_password(self, raw_password: str) -> None:
        raw_password = (raw_password or "").strip()
        if not raw_password:
            raise ValidationError("Password cannot be empty")
        self.password_encrypted = encrypt_str(raw_password)

    def get_password(self) -> str:
        if not self.password_encrypted:
            return ""
        return decrypt_str(self.password_encrypted)

    @property
    def has_password(self) -> bool:
        return bool(self.password_encrypted)

    def __str__(self) -> str:
        return f"SynergyCredential(student_id={self.student_id}, login={self.login})"


class Semester(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    student = models.ForeignKey("accounts.Student", on_delete=models.CASCADE, related_name="semesters")
    number = models.PositiveIntegerField()

    class Meta:
        unique_together = (("student", "number"),)

    def __str__(self) -> str:
        return f"{self.student_id}: semester {self.number}"


class Course(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    student = models.ForeignKey("accounts.Student", on_delete=models.CASCADE, related_name="courses")
    semester_number = models.PositiveIntegerField()

    name = models.CharField(max_length=500)
    url = models.URLField(max_length=2000)
    control_type = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        unique_together = (("student", "url"),)
        indexes = [
            models.Index(fields=["student", "semester_number"]),
        ]

    def __str__(self) -> str:
        return f"{self.student_id}: {self.name}"


class Material(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    student = models.ForeignKey("accounts.Student", on_delete=models.CASCADE, related_name="materials")
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="materials")

    name = models.CharField(max_length=500)
    url = models.URLField(max_length=2000, null=True, blank=True)
    type = models.CharField(max_length=64, blank=True, default="material")
    is_blocked = models.BooleanField(default=False)
    blocked_reason = models.CharField(max_length=500, blank=True, default="")
    section_path = models.CharField(max_length=1000, blank=True, default="")
    data_index = models.CharField(max_length=128, blank=True, default="")
    raw = models.JSONField(null=True, blank=True)

    last_processed_at = models.DateTimeField(null=True, blank=True)
    last_result = models.JSONField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["student", "type"]),
        ]

    def __str__(self) -> str:
        return f"{self.student_id}: {self.name}"

