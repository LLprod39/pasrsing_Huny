from __future__ import annotations

from django.db import models


class BotConfig(models.Model):
    """Глобальные настройки бота (тексты, флаги, лимиты)."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    key = models.CharField(max_length=255, unique=True)
    value = models.JSONField(null=True, blank=True)

    def __str__(self) -> str:
        return self.key

