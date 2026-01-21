from __future__ import annotations

from django.db import models


class Plan(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    is_active = models.BooleanField(default=True)

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")

    currency = models.CharField(max_length=16, default="usd")
    price_cents = models.PositiveIntegerField(default=0)
    duration_days = models.PositiveIntegerField(default=30)

    courses_limit = models.PositiveIntegerField(default=0, help_text="Maximum number of courses/lessons (e.g. Philosophy, Math) that can be processed (0 = unlimited)")
    semesters_limit = models.PositiveIntegerField(default=0, help_text="Maximum number of semesters that can be parsed (0 = unlimited)")
    materials_limit = models.PositiveIntegerField(default=0, help_text="Maximum number of materials that can be processed (0 = unlimited)")
    tests_limit = models.PositiveIntegerField(default=0, help_text="Maximum number of tests that can be solved (0 = unlimited)")

    semesters_enabled = models.BooleanField(default=True, help_text="Allow parsing semesters in this plan")
    courses_enabled = models.BooleanField(default=True, help_text="Allow processing courses/lessons in this plan")
    materials_enabled = models.BooleanField(default=True, help_text="Allow processing materials in this plan")
    tests_enabled = models.BooleanField(default=True, help_text="Allow solving tests in this plan")

    # For Stripe/other providers mapping (optional)
    external_price_id = models.CharField(max_length=255, blank=True, default="")
    metadata = models.JSONField(null=True, blank=True)

    def __str__(self) -> str:
        return self.name


class SubscriptionStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    CANCELLED = "cancelled", "Cancelled"
    EXPIRED = "expired", "Expired"


class Subscription(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    student = models.ForeignKey("accounts.Student", on_delete=models.CASCADE, related_name="subscriptions")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")

    status = models.CharField(max_length=32, choices=SubscriptionStatus.choices, default=SubscriptionStatus.ACTIVE)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()

    # Optional: limit access to selected semesters (if empty => all)
    allowed_semester_numbers = models.JSONField(null=True, blank=True)

    semesters_used = models.PositiveIntegerField(default=0)
    courses_used = models.PositiveIntegerField(default=0)
    materials_used = models.PositiveIntegerField(default=0)
    tests_used = models.PositiveIntegerField(default=0)

    external_subscription_id = models.CharField(max_length=255, blank=True, default="")

    def __str__(self) -> str:
        return f"{self.student_id}: {self.plan.name} ({self.status})"


class PaymentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    REFUNDED = "refunded", "Refunded"


class Payment(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    student = models.ForeignKey("accounts.Student", on_delete=models.CASCADE, related_name="payments")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="payments")

    status = models.CharField(max_length=32, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)
    amount_cents = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=16, default="usd")

    provider = models.CharField(max_length=64, blank=True, default="manual")
    provider_payment_id = models.CharField(max_length=255, blank=True, default="", db_index=True)
    raw = models.JSONField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.student_id}: {self.amount_cents}{self.currency} ({self.status})"


class WebhookEvent(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)

    provider = models.CharField(max_length=64)
    event_id = models.CharField(max_length=255, db_index=True)
    event_type = models.CharField(max_length=255, blank=True, default="")
    payload = models.JSONField()

    class Meta:
        unique_together = (("provider", "event_id"),)

    def __str__(self) -> str:
        return f"{self.provider}:{self.event_id}"

