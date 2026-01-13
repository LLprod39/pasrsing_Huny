from __future__ import annotations

from django.contrib import admin

from .models import Payment, Plan, Subscription, WebhookEvent


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "price_cents", "currency", "duration_days", "is_active", "updated_at")
    list_filter = ("is_active", "currency")
    search_fields = ("name", "external_price_id")


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("id", "student", "plan", "status", "starts_at", "ends_at", "updated_at")
    list_filter = ("status", "plan")
    search_fields = ("student__full_name", "student__email", "external_subscription_id")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "student", "plan", "status", "amount_cents", "currency", "provider", "created_at")
    list_filter = ("status", "provider", "currency")
    search_fields = ("provider_payment_id", "student__full_name", "student__email")


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ("id", "provider", "event_id", "event_type", "created_at")
    list_filter = ("provider", "event_type")
    search_fields = ("event_id",)
    readonly_fields = ("provider", "event_id", "event_type", "payload", "created_at")

