from __future__ import annotations

from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.accounts.models import Student
from apps.billing.models import Payment, PaymentStatus, Subscription, SubscriptionStatus
from apps.jobs.models import Job, JobStatus, JobType
from apps.jobs.enqueue import enqueue_job
from apps.synergy.models import Material


@staff_member_required
def admin_dashboard(request):
    """Кастомный dashboard для админ панели."""
    now = timezone.now()

    # Статистика пользователей
    total_students = Student.objects.count()
    active_students = Student.objects.filter(is_active=True).count()
    students_with_creds = Student.objects.filter(synergy_credential__isnull=False).distinct().count()
    active_subscriptions = Subscription.objects.filter(
        status=SubscriptionStatus.ACTIVE, starts_at__lte=now, ends_at__gt=now
    ).count()

    # Статистика задач
    total_jobs = Job.objects.count()
    pending_jobs = Job.objects.filter(status=JobStatus.PENDING).count()
    running_jobs = Job.objects.filter(status=JobStatus.RUNNING).count()
    completed_jobs = Job.objects.filter(status=JobStatus.COMPLETED).count()
    failed_jobs = Job.objects.filter(status=JobStatus.FAILED).count()

    # Статистика материалов
    total_materials = Material.objects.count()
    test_materials = Material.objects.filter(type__iexact="test").count()
    blocked_materials = Material.objects.filter(is_blocked=True).count()
    processed_materials = Material.objects.exclude(last_processed_at__isnull=True).count()

    # Статистика по типам задач
    jobs_by_type = (
        Job.objects.values("type")
        .annotate(count=Count("id"))
        .order_by("-count")
    )

    # Последняя активность
    recent_jobs = Job.objects.select_related("student").order_by("-created_at")[:10]
    recent_students = Student.objects.order_by("-created_at")[:5]
    recent_completed_tests = (
        Job.objects.filter(type=JobType.SOLVE_TEST, status=JobStatus.COMPLETED)
        .select_related("student")
        .order_by("-finished_at")[:5]
    )

    # Активные задачи по студентам
    active_jobs_by_student = (
        Job.objects.filter(status__in=[JobStatus.PENDING, JobStatus.RUNNING])
        .values("student__full_name", "student__email", "student_id")
        .annotate(count=Count("id"))
        .order_by("-count")[:10]
    )

    # Статистика платежей
    total_payments = Payment.objects.count()
    successful_payments = Payment.objects.filter(status=PaymentStatus.SUCCEEDED).count()
    pending_payments = Payment.objects.filter(status=PaymentStatus.PENDING).count()

    context = {
        "total_students": total_students,
        "active_students": active_students,
        "students_with_creds": students_with_creds,
        "active_subscriptions": active_subscriptions,
        "total_jobs": total_jobs,
        "pending_jobs": pending_jobs,
        "running_jobs": running_jobs,
        "completed_jobs": completed_jobs,
        "failed_jobs": failed_jobs,
        "total_materials": total_materials,
        "test_materials": test_materials,
        "blocked_materials": blocked_materials,
        "processed_materials": processed_materials,
        "jobs_by_type": jobs_by_type,
        "recent_jobs": recent_jobs,
        "recent_students": recent_students,
        "recent_completed_tests": recent_completed_tests,
        "active_jobs_by_student": active_jobs_by_student,
        "total_payments": total_payments,
        "successful_payments": successful_payments,
        "pending_payments": pending_payments,
    }

    return render(request, "admin/dashboard.html", context)


@staff_member_required
@require_http_methods(["GET", "POST"])
def bulk_tests_view(request):
    """Массовый запуск тестов для нескольких студентов."""
    if request.method == "POST":
        student_ids = request.POST.getlist("student_ids")
        if not student_ids:
            messages.error(request, "Выберите хотя бы одного студента.")
            return redirect("bulk_tests")

        created = 0
        skipped = 0
        for student_id in student_ids:
            try:
                student = Student.objects.get(id=student_id)
                test_materials = Material.objects.filter(
                    student=student, type__iexact="test", is_blocked=False
                ).exclude(url__isnull=True).exclude(url="")
                for material in test_materials:
                    job = Job.objects.create(
                        student=student,
                        type=JobType.SOLVE_TEST,
                        status=JobStatus.PENDING,
                        params={"material_id": material.id},
                        result=None,
                    )
                    if enqueue_job(job):
                        created += 1
                    else:
                        skipped += 1
            except Student.DoesNotExist:
                skipped += 1

        messages.success(
            request,
            f"Создано задач на решение тестов: {created}. Пропущено: {skipped}.",
        )
        return redirect("bulk_tests")

    # GET request - показать форму
    students = Student.objects.filter(is_active=True).order_by("full_name", "email")
    students_with_tests = []
    for student in students:
        test_count = Material.objects.filter(
            student=student, type__iexact="test", is_blocked=False
        ).exclude(url__isnull=True).exclude(url="").count()
        if test_count > 0:
            students_with_tests.append({
                "student": student,
                "test_count": test_count,
            })

    context = {
        "students_with_tests": students_with_tests,
    }
    return render(request, "admin/bulk_operations/bulk_tests.html", context)


@staff_member_required
def monitor_progress_view(request):
    """Мониторинг прогресса выполнения задач."""
    # Активные задачи
    active_jobs = Job.objects.filter(
        status__in=[JobStatus.PENDING, JobStatus.RUNNING]
    ).select_related("student").order_by("-created_at")[:50]

    # Статистика по статусам
    stats = {
        "pending": Job.objects.filter(status=JobStatus.PENDING).count(),
        "running": Job.objects.filter(status=JobStatus.RUNNING).count(),
        "completed_today": Job.objects.filter(
            status=JobStatus.COMPLETED, finished_at__date=timezone.now().date()
        ).count(),
        "failed_today": Job.objects.filter(
            status=JobStatus.FAILED, finished_at__date=timezone.now().date()
        ).count(),
    }

    # Задачи по типам
    jobs_by_type = (
        Job.objects.filter(status__in=[JobStatus.PENDING, JobStatus.RUNNING])
        .values("type")
        .annotate(count=Count("id"))
        .order_by("-count")
    )

    context = {
        "active_jobs": active_jobs,
        "stats": stats,
        "jobs_by_type": jobs_by_type,
    }
    return render(request, "admin/bulk_operations/monitor_progress.html", context)


@staff_member_required
def student_materials_view(request, student_id):
    """Удобный просмотр всех материалов студента."""
    student = get_object_or_404(Student, id=student_id)

    # Материалы по курсам
    courses = student.courses.all().prefetch_related("materials")
    courses_with_materials = []
    for course in courses:
        materials = course.materials.filter(student=student).order_by("type", "name")
        courses_with_materials.append({
            "course": course,
            "materials": materials,
            "test_count": materials.filter(type__iexact="test").count(),
            "processed_count": materials.exclude(last_processed_at__isnull=True).count(),
        })

    # Статистика
    total_materials = Material.objects.filter(student=student).count()
    test_materials = Material.objects.filter(student=student, type__iexact="test").count()
    processed_materials = Material.objects.filter(
        student=student
    ).exclude(last_processed_at__isnull=True).count()
    blocked_materials = Material.objects.filter(student=student, is_blocked=True).count()

    context = {
        "student": student,
        "courses_with_materials": courses_with_materials,
        "total_materials": total_materials,
        "test_materials": test_materials,
        "processed_materials": processed_materials,
        "blocked_materials": blocked_materials,
    }
    return render(request, "admin/bulk_operations/student_materials.html", context)


@staff_member_required
def job_status_api(request, job_id):
    """API для получения статуса задачи (для AJAX)."""
    job = get_object_or_404(Job, id=job_id)
    return JsonResponse({
        "id": str(job.id),
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "error": job.error,
    })
