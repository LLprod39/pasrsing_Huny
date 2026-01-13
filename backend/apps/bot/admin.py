from __future__ import annotations

from django.contrib import admin

from .models import BotConfig


@admin.register(BotConfig)
class BotConfigAdmin(admin.ModelAdmin):
    list_display = ("id", "key", "updated_at")
    search_fields = ("key",)

