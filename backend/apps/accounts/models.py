from __future__ import annotations

from django.db import models


class Student(models.Model):
    """Профиль студента (пользователь бота).

    Админы/операторы живут в стандартной Django-модели User и входят через /admin/.
    """

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    is_active = models.BooleanField(default=True)

    full_name = models.CharField(max_length=255, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    phone = models.CharField(max_length=50, blank=True, default="")

    # Например Telegram user id / chat id (если нужен бот)
    external_id = models.CharField(max_length=128, blank=True, default="", db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["external_id"]),
            models.Index(fields=["email"]),
        ]

    def __str__(self) -> str:
        return self.full_name or self.email or f"Student#{self.pk}"

