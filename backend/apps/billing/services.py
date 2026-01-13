from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from django.db import transaction
from django.utils import timezone

from .models import Payment, PaymentStatus, Plan, Subscription, SubscriptionStatus


@dataclass(frozen=True)
class AccessGrant:
    starts_at: timezone.datetime
    ends_at: timezone.datetime
    allowed_semester_numbers: Optional[list[int]] = None


@transaction.atomic
def mark_payment_succeeded(payment: Payment, *, raw: dict | None = None) -> Subscription:
    """Mark payment as succeeded and create/extend subscription."""
    payment.status = PaymentStatus.SUCCEEDED
    if raw is not None:
        payment.raw = raw
    payment.save(update_fields=["status", "raw", "updated_at"])

    plan: Plan = payment.plan
    now = timezone.now()
    allowed = None
    if isinstance(plan.metadata, dict):
        maybe = plan.metadata.get("allowed_semester_numbers")
        if isinstance(maybe, list):
            # Best-effort normalize to ints
            allowed = []
            for x in maybe:
                try:
                    allowed.append(int(x))
                except Exception:
                    continue

    # Extend active subscription if exists; else create new
    active = (
        Subscription.objects.filter(student=payment.student, status=SubscriptionStatus.ACTIVE, ends_at__gt=now)
        .order_by("-ends_at")
        .first()
    )
    if active:
        active.ends_at = active.ends_at + timedelta(days=plan.duration_days)
        active.updated_at = now
        active.save(update_fields=["ends_at", "updated_at"])
        return active

    sub = Subscription.objects.create(
        student=payment.student,
        plan=plan,
        status=SubscriptionStatus.ACTIVE,
        starts_at=now,
        ends_at=now + timedelta(days=plan.duration_days),
        allowed_semester_numbers=allowed,
        external_subscription_id="",
    )
    return sub


def has_access(student_id: int, *, semester_number: Optional[int] = None) -> bool:
    """Check if student has an active subscription (and optionally access to a semester)."""
    now = timezone.now()
    subs = Subscription.objects.filter(
        student_id=student_id, status=SubscriptionStatus.ACTIVE, starts_at__lte=now, ends_at__gt=now
    ).order_by("-ends_at")

    if semester_number is None:
        return subs.exists()

    for sub in subs:
        allowed = sub.allowed_semester_numbers
        if not allowed:
            return True
        try:
            if int(semester_number) in [int(x) for x in allowed]:
                return True
        except Exception:
            continue
    return False

