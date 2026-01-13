from __future__ import annotations

from django.contrib import admin
from django.utils import timezone

from unfold.admin import ModelAdmin, StackedInline, TabularInline

from apps.jobs.models import Job, JobStatus, JobType
from apps.jobs.tasks import synergy_login_job, synergy_sync_semesters_job
from apps.synergy.forms import SynergyCredentialInlineForm
from apps.synergy.models import SynergyCredential
from apps.billing.models import Payment, Subscription

from .models import Student


class SynergyCredentialInline(StackedInline):
    model = SynergyCredential
    form = SynergyCredentialInlineForm
    extra = 0
    can_delete = False
    verbose_name_plural = "Synergy креды"


class SubscriptionInline(TabularInline):
    model = Subscription
    extra = 0
    autocomplete_fields = ("plan",)
    fields = ("plan", "status", "starts_at", "ends_at", "allowed_semester_numbers")
    show_change_link = True
    verbose_name_plural = "Подписки"


class PaymentInline(TabularInline):
    model = Payment
    extra = 0
    fields = ("status", "amount_cents", "currency", "provider", "provider_payment_id", "created_at")
    readonly_fields = fields
    show_change_link = True
    verbose_name_plural = "Платежи"

    def has_add_permission(self, request, obj=None):
        return False


class JobInline(TabularInline):
    model = Job
    extra = 0
    fields = ("type", "status", "progress", "message", "created_at")
    readonly_fields = fields
    show_change_link = True
    verbose_name_plural = "Последние jobs"

    def has_add_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.order_by("-created_at")[:20]


@admin.register(Student)
class StudentAdmin(ModelAdmin):
    list_display = (
        "id",
        "full_name",
        "email",
        "external_id",
        "is_active",
        "has_synergy_creds",
        "synergy_last_validated_at",
        "subscription_summary",
        "created_at",
    )
    list_filter = ("is_active",)
    list_filter_submit = True
    search_fields = ("full_name", "email", "phone", "external_id")
    actions = ("queue_synergy_login", "queue_sync_semesters")
    inlines = (SynergyCredentialInline, SubscriptionInline, PaymentInline, JobInline)

    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Студент", {"fields": ("is_active", "full_name", "external_id")}),
        ("Контакты", {"fields": ("email", "phone")}),
        ("Системное", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description="Synergy креды", boolean=True)
    def has_synergy_creds(self, obj: Student) -> bool:
        cred = getattr(obj, "synergy_credential", None)
        return bool(cred and (cred.login or "").strip() and cred.has_password)

    @admin.display(description="Synergy проверка")
    def synergy_last_validated_at(self, obj: Student):
        cred = getattr(obj, "synergy_credential", None)
        return getattr(cred, "last_validated_at", None) if cred else None

    @admin.display(description="Подписка")
    def subscription_summary(self, obj: Student) -> str:
        now = timezone.now()
        sub = (
            obj.subscriptions.filter(status="active", starts_at__lte=now, ends_at__gt=now)
            .select_related("plan")
            .order_by("-ends_at")
            .first()
        )
        if not sub:
            return "-"
        return f"{sub.plan.name} до {sub.ends_at:%Y-%m-%d}"

    @admin.action(description="Synergy: проверить логин (создать Job)")
    def queue_synergy_login(self, request, queryset):
        created = 0
        for student in queryset:
            job = Job.objects.create(
                student=student, type=JobType.LOGIN, status=JobStatus.PENDING, params=None, result=None
            )
            async_result = synergy_login_job.delay(str(job.id))
            job.celery_task_id = async_result.id
            job.save(update_fields=["celery_task_id", "updated_at"])
            created += 1
        self.message_user(request, f"Queued {created} login job(s).")

    @admin.action(description="Synergy: синхронизировать семестры (создать Job)")
    def queue_sync_semesters(self, request, queryset):
        created = 0
        for student in queryset:
            job = Job.objects.create(
                student=student, type=JobType.SYNC_SEMESTERS, status=JobStatus.PENDING, params=None, result=None
            )
            async_result = synergy_sync_semesters_job.delay(str(job.id))
            job.celery_task_id = async_result.id
            job.save(update_fields=["celery_task_id", "updated_at"])
            created += 1
        self.message_user(request, f"Queued {created} sync_semesters job(s).")

