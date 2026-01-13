from __future__ import annotations

import json

import stripe
from django.conf import settings
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Student

from .models import Payment, PaymentStatus, Plan, WebhookEvent
from .services import mark_payment_succeeded


class StripeCheckoutSessionCreateView(APIView):
    """Create Stripe Checkout Session for a student+plan.

    For now this endpoint is admin-only (operators can generate payment links).
    """

    permission_classes = [permissions.IsAdminUser]

    def post(self, request):
        student_id = request.data.get("student_id")
        plan_id = request.data.get("plan_id")

        try:
            student_id = int(student_id)
            plan_id = int(plan_id)
        except (TypeError, ValueError):
            return Response({"detail": "student_id and plan_id must be int"}, status=status.HTTP_400_BAD_REQUEST)

        student = Student.objects.get(id=student_id, is_active=True)
        plan = Plan.objects.get(id=plan_id, is_active=True)

        payment = Payment.objects.create(
            student=student,
            plan=plan,
            status=PaymentStatus.PENDING,
            amount_cents=plan.price_cents,
            currency=plan.currency,
            provider="stripe",
        )

        # If amount is 0, Stripe checkout isn't needed (and Stripe may reject 0-amount payments).
        if int(plan.price_cents or 0) == 0:
            sub = mark_payment_succeeded(payment, raw={"note": "zero_amount_auto_succeed"})
            return Response(
                {
                    "status": "succeeded",
                    "payment_id": payment.id,
                    "checkout_url": None,
                    "subscription_id": sub.id,
                }
            )

        if not settings.STRIPE_SECRET_KEY:
            return Response({"detail": "STRIPE_SECRET_KEY not configured"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        stripe.api_key = settings.STRIPE_SECRET_KEY

        line_items: list[dict] = []
        if plan.external_price_id:
            line_items = [{"price": plan.external_price_id, "quantity": 1}]
        else:
            line_items = [
                {
                    "price_data": {
                        "currency": plan.currency,
                        "product_data": {"name": plan.name},
                        "unit_amount": int(plan.price_cents),
                    },
                    "quantity": 1,
                }
            ]

        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=line_items,
            success_url=settings.STRIPE_SUCCESS_URL,
            cancel_url=settings.STRIPE_CANCEL_URL,
            metadata={"payment_id": str(payment.id), "student_id": str(student.id), "plan_id": str(plan.id)},
        )

        payment.provider_payment_id = session["id"]
        payment.raw = session
        payment.save(update_fields=["provider_payment_id", "raw", "updated_at"])

        return Response({"checkout_url": session.get("url"), "payment_id": payment.id})


class StripeWebhookView(APIView):
    """Stripe webhook endpoint.

    Must be public and must verify signature.
    """

    authentication_classes: list = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        if not settings.STRIPE_SECRET_KEY or not settings.STRIPE_WEBHOOK_SECRET:
            return Response({"detail": "Stripe webhook not configured"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        stripe.api_key = settings.STRIPE_SECRET_KEY

        payload = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
        except ValueError:
            return Response({"detail": "Invalid payload"}, status=status.HTTP_400_BAD_REQUEST)
        except stripe.error.SignatureVerificationError:
            return Response({"detail": "Invalid signature"}, status=status.HTTP_400_BAD_REQUEST)

        event_id = event.get("id")
        event_type = event.get("type", "")

        # Dedupe webhook events
        obj, created = WebhookEvent.objects.get_or_create(
            provider="stripe",
            event_id=event_id,
            defaults={"event_type": event_type, "payload": json.loads(payload.decode("utf-8"))},
        )
        if not created:
            return Response({"status": "ok"})

        # Process supported events
        if event_type == "checkout.session.completed":
            session = event["data"]["object"]

            payment_id = (session.get("metadata") or {}).get("payment_id")
            payment: Payment | None = None
            if payment_id:
                payment = Payment.objects.filter(id=payment_id, provider="stripe").first()
            if not payment:
                payment = Payment.objects.filter(provider="stripe", provider_payment_id=session.get("id")).first()
            if payment and payment.status != PaymentStatus.SUCCEEDED:
                mark_payment_succeeded(payment, raw=session)

        elif event_type in {"checkout.session.async_payment_failed"}:
            session = event["data"]["object"]
            payment = Payment.objects.filter(provider="stripe", provider_payment_id=session.get("id")).first()
            if payment and payment.status == PaymentStatus.PENDING:
                payment.status = PaymentStatus.FAILED
                payment.raw = session
                payment.save(update_fields=["status", "raw", "updated_at"])

        return Response({"status": "ok"})

