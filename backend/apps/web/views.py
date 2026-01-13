from __future__ import annotations

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.accounts.models import Student
from apps.billing.models import Payment, Plan, Subscription, SubscriptionStatus
from apps.billing.services import has_access
from apps.jobs.models import Job, JobStatus
from apps.jobs.models import JobType
from apps.jobs.tasks import (
    synergy_login_job,
    synergy_process_material_job,
    synergy_solve_test_job,
    synergy_sync_courses_job,
    synergy_sync_materials_job,
    synergy_sync_semesters_job,
)
from apps.synergy.models import Course, Material, Semester
from apps.synergy.models import SynergyCredential

from .forms import (
    CourseSelectForm,
    MaterialsActionForm,
    SemesterSelectForm,
    StudentLoginForm,
    StudentRegisterForm,
    SynergyCredentialWebForm,
)


def get_student_from_session(request: HttpRequest) -> Student | None:
    """Получить студента из сессии (если авторизован)."""
    student_id = request.session.get("student_id")
    if student_id:
        try:
            return Student.objects.get(pk=student_id, is_active=True)
        except Student.DoesNotExist:
            request.session.pop("student_id", None)
    return None


def require_student_login(view_func):
    """Декоратор для проверки авторизации студента."""

    def wrapper(request: HttpRequest, *args, **kwargs):
        student = get_student_from_session(request)
        if not student:
            return redirect("web:login")
        request.student = student
        return view_func(request, *args, **kwargs)

    return wrapper


def require_active_subscription(view_func):
    """Декоратор: доступ к функционалу парсинга только при активной подписке."""

    def wrapper(request: HttpRequest, *args, **kwargs):
        student = getattr(request, "student", None) or get_student_from_session(request)
        if not student:
            return redirect("web:login")
        request.student = student

        if not has_access(student.id):
            messages.warning(request, "Нужна активная подписка, чтобы пользоваться автоматизацией.")
            return redirect("web:plans")
        return view_func(request, *args, **kwargs)

    return wrapper


def _active_subscription(student: Student) -> Subscription | None:
    now = timezone.now()
    return (
        Subscription.objects.filter(student=student, status=SubscriptionStatus.ACTIVE, starts_at__lte=now, ends_at__gt=now)
        .select_related("plan")
        .order_by("-ends_at")
        .first()
    )


def _allowed_semesters(student: Student) -> list[int] | None:
    """Return list of allowed semester numbers, or None if unlimited."""
    sub = _active_subscription(student)
    if not sub:
        return []
    allowed = sub.allowed_semester_numbers
    if not allowed:
        return None
    out: list[int] = []
    for x in allowed:
        try:
            out.append(int(x))
        except Exception:
            continue
    return sorted(set(out))


def _require_synergy_creds(student: Student) -> SynergyCredential | None:
    cred = SynergyCredential.objects.filter(student=student).first()
    if not cred:
        return None
    if not (cred.login or "").strip():
        return None
    if not cred.has_password:
        return None
    return cred


def index(request: HttpRequest) -> HttpResponse:
    """Главная страница (публичная)."""
    student = get_student_from_session(request)
    context = {
        "student": student,
        "plans": Plan.objects.filter(is_active=True).order_by("price_cents"),
    }
    return render(request, "web/index.html", context)


def login_view(request: HttpRequest) -> HttpResponse:
    """Страница входа для студентов."""
    if request.method == "POST":
        form = StudentLoginForm(request.POST)
        if form.is_valid():
            student = form.get_student()
            if student:
                request.session["student_id"] = student.pk
                messages.success(request, f"Добро пожаловать, {student.full_name or student.email}!")
                return redirect("web:dashboard")
            else:
                messages.error(request, "Студент не найден или неактивен")
    else:
        form = StudentLoginForm()

    return render(request, "web/login.html", {"form": form})


def register_view(request: HttpRequest) -> HttpResponse:
    """Страница регистрации нового студента."""
    if request.method == "POST":
        form = StudentRegisterForm(request.POST)
        if form.is_valid():
            student = form.save(commit=False)
            student.is_active = True
            student.save()
            request.session["student_id"] = student.pk
            messages.success(request, f"Регистрация успешна! Добро пожаловать, {student.full_name or student.email}!")
            return redirect("web:dashboard")
    else:
        form = StudentRegisterForm()

    return render(request, "web/register.html", {"form": form})


def logout_view(request: HttpRequest) -> HttpResponse:
    """Выход из системы."""
    request.session.pop("student_id", None)
    messages.info(request, "Вы вышли из системы")
    return redirect("web:index")


@require_student_login
def dashboard(request: HttpRequest) -> HttpResponse:
    """Личный кабинет студента."""
    student: Student = request.student

    # Активная подписка
    active_subscription = (
        Subscription.objects.filter(
            student=student, status=SubscriptionStatus.ACTIVE, ends_at__gt=timezone.now()
        )
        .order_by("-ends_at")
        .first()
    )

    # Последние jobs
    recent_jobs = Job.objects.filter(student=student).order_by("-created_at")[:10]

    # Статистика
    stats = {
        "semesters_count": Semester.objects.filter(student=student).count(),
        "courses_count": Course.objects.filter(student=student).count(),
        "materials_count": Material.objects.filter(student=student).count(),
        "pending_jobs": Job.objects.filter(student=student, status__in=[JobStatus.PENDING, JobStatus.RUNNING]).count(),
    }

    context = {
        "student": student,
        "active_subscription": active_subscription,
        "recent_jobs": recent_jobs,
        "stats": stats,
    }
    return render(request, "web/dashboard.html", context)


@require_student_login
def profile(request: HttpRequest) -> HttpResponse:
    """Профиль студента (редактирование)."""
    student: Student = request.student

    if request.method == "POST":
        full_name = request.POST.get("full_name", "").strip()
        email = request.POST.get("email", "").strip()
        phone = request.POST.get("phone", "").strip()

        if full_name:
            student.full_name = full_name
        if email and email != student.email:
            if Student.objects.filter(email__iexact=email).exclude(pk=student.pk).exists():
                messages.error(request, "Email уже используется другим студентом")
            else:
                student.email = email
        if phone:
            student.phone = phone

        student.save(update_fields=["full_name", "email", "phone", "updated_at"])
        messages.success(request, "Профиль обновлён")

    return render(request, "web/profile.html", {"student": student})


@require_student_login
def subscriptions(request: HttpRequest) -> HttpResponse:
    """Список подписок студента."""
    student: Student = request.student
    subscriptions_list = Subscription.objects.filter(student=student).order_by("-created_at")
    context = {
        "student": student,
        "subscriptions": subscriptions_list,
    }
    return render(request, "web/subscriptions.html", context)


@require_student_login
def payments(request: HttpRequest) -> HttpResponse:
    """История платежей студента."""
    student: Student = request.student
    payments_list = Payment.objects.filter(student=student).order_by("-created_at")
    context = {
        "student": student,
        "payments": payments_list,
    }
    return render(request, "web/payments.html", context)


@require_student_login
def plans(request: HttpRequest) -> HttpResponse:
    """Страница выбора тарифа/плана."""
    student: Student = request.student
    plans_list = Plan.objects.filter(is_active=True).order_by("price_cents")
    context = {
        "student": student,
        "plans": plans_list,
    }
    return render(request, "web/plans.html", context)


@require_student_login
def jobs(request: HttpRequest) -> HttpResponse:
    """Список jobs (задач синхронизации) студента."""
    student: Student = request.student
    jobs_list = Job.objects.filter(student=student).order_by("-created_at")
    context = {
        "student": student,
        "jobs": jobs_list,
    }
    return render(request, "web/jobs.html", context)


@require_student_login
@require_active_subscription
def synergy_setup(request: HttpRequest) -> HttpResponse:
    """Студент вводит Synergy логин/пароль (сохраняем зашифрованно)."""
    student: Student = request.student
    cred = SynergyCredential.objects.filter(student=student).first()

    if request.method == "POST":
        form = SynergyCredentialWebForm(request.POST)
        if form.is_valid():
            form.save_for_student(student=student)
            messages.success(request, "Synergy логин/пароль сохранены.")
            # Optionally enqueue login check
            job = Job.objects.create(student=student, type=JobType.LOGIN, status=JobStatus.PENDING, params=None, result=None)
            async_result = synergy_login_job.delay(str(job.id))
            job.celery_task_id = async_result.id
            job.save(update_fields=["celery_task_id", "updated_at"])
            return redirect("web:flow_semesters")
    else:
        form = SynergyCredentialWebForm(initial={"login": getattr(cred, "login", "")})

    return render(request, "web/synergy_setup.html", {"student": student, "form": form, "cred": cred})


@require_student_login
@require_active_subscription
def flow_semesters(request: HttpRequest) -> HttpResponse:
    """Шаг 1: синхронизировать и выбрать семестр (только доступные по подписке)."""
    student: Student = request.student
    if not _require_synergy_creds(student):
        messages.info(request, "Сначала укажите логин/пароль Synergy.")
        return redirect("web:synergy_setup")

    allowed = _allowed_semesters(student)  # None => unlimited

    # sync button
    if request.method == "POST" and request.POST.get("action") == "sync":
        job = Job.objects.create(student=student, type=JobType.SYNC_SEMESTERS, status=JobStatus.PENDING, params=None, result=None)
        async_result = synergy_sync_semesters_job.delay(str(job.id))
        job.celery_task_id = async_result.id
        job.save(update_fields=["celery_task_id", "updated_at"])
        messages.success(request, "Задача синхронизации семестров поставлена. Обновите страницу через минуту.")
        return redirect("web:flow_semesters")

    semesters_qs = Semester.objects.filter(student=student).order_by("number")
    if allowed is not None:
        semesters_qs = semesters_qs.filter(number__in=allowed)
        # If subscription is for exactly 1 semester => auto-select it and lock later steps
        if len(allowed) == 1:
            request.session["selected_semester_number"] = allowed[0]

    semesters = list(semesters_qs.values_list("number", flat=True))
    selected = request.session.get("selected_semester_number")

    if request.method == "POST" and request.POST.get("action") == "select":
        try:
            semester_number = int(request.POST.get("semester_number") or 0)
        except Exception:
            semester_number = 0
        if semester_number <= 0:
            messages.error(request, "Выберите семестр.")
        elif allowed is not None and semester_number not in allowed:
            messages.error(request, "Этот семестр недоступен по вашей подписке.")
        else:
            request.session["selected_semester_number"] = semester_number
            messages.success(request, f"Выбран семестр {semester_number}.")
            return redirect("web:flow_courses")

    context = {
        "student": student,
        "allowed": allowed,
        "semesters": semesters,
        "selected": selected,
        "locked_single": (allowed is not None and len(allowed) == 1),
    }
    return render(request, "web/flow_semesters.html", context)


@require_student_login
@require_active_subscription
def flow_courses(request: HttpRequest) -> HttpResponse:
    """Шаг 2: синхронизировать и выбрать курс для выбранного семестра."""
    student: Student = request.student
    if not _require_synergy_creds(student):
        return redirect("web:synergy_setup")

    allowed = _allowed_semesters(student)
    try:
        semester_number = int(request.session.get("selected_semester_number") or 0)
    except Exception:
        semester_number = 0
    if semester_number <= 0:
        messages.info(request, "Сначала выберите семестр.")
        return redirect("web:flow_semesters")
    if allowed is not None and semester_number not in allowed:
        messages.error(request, "Этот семестр недоступен по вашей подписке.")
        return redirect("web:flow_semesters")

    if request.method == "POST" and request.POST.get("action") == "sync":
        job = Job.objects.create(
            student=student,
            type=JobType.SYNC_COURSES,
            status=JobStatus.PENDING,
            params={"semester_number": semester_number},
            result=None,
        )
        async_result = synergy_sync_courses_job.delay(str(job.id))
        job.celery_task_id = async_result.id
        job.save(update_fields=["celery_task_id", "updated_at"])
        messages.success(request, "Задача синхронизации курсов поставлена. Обновите страницу через минуту.")
        return redirect("web:flow_courses")

    courses = list(Course.objects.filter(student=student, semester_number=semester_number).order_by("name"))
    selected_course_id = request.session.get("selected_course_id")

    if request.method == "POST" and request.POST.get("action") == "select":
        try:
            course_id = int(request.POST.get("course_id") or 0)
        except Exception:
            course_id = 0
        if course_id <= 0 or not Course.objects.filter(id=course_id, student=student, semester_number=semester_number).exists():
            messages.error(request, "Выберите корректный курс.")
        else:
            request.session["selected_course_id"] = course_id
            messages.success(request, "Курс выбран.")
            return redirect("web:flow_materials")

    return render(
        request,
        "web/flow_courses.html",
        {"student": student, "semester_number": semester_number, "courses": courses, "selected_course_id": selected_course_id},
    )


@require_student_login
@require_active_subscription
def flow_materials(request: HttpRequest) -> HttpResponse:
    """Шаг 3: синх материалов и запуск задач 'как в CLI' (выборочно/авто)."""
    student: Student = request.student
    if not _require_synergy_creds(student):
        return redirect("web:synergy_setup")

    try:
        course_id = int(request.session.get("selected_course_id") or 0)
    except Exception:
        course_id = 0
    if course_id <= 0:
        messages.info(request, "Сначала выберите курс.")
        return redirect("web:flow_courses")

    course = Course.objects.filter(id=course_id, student=student).first()
    if not course:
        messages.error(request, "Курс не найден.")
        request.session.pop("selected_course_id", None)
        return redirect("web:flow_courses")

    if request.method == "POST" and request.POST.get("action") == "sync":
        job = Job.objects.create(
            student=student,
            type=JobType.SYNC_MATERIALS,
            status=JobStatus.PENDING,
            params={"course_id": course.id},
            result=None,
        )
        async_result = synergy_sync_materials_job.delay(str(job.id))
        job.celery_task_id = async_result.id
        job.save(update_fields=["celery_task_id", "updated_at"])
        messages.success(request, "Задача синхронизации материалов поставлена. Обновите страницу через минуту.")
        return redirect("web:flow_materials")

    materials_qs = Material.objects.filter(student=student, course=course).order_by("type", "name")
    materials = list(materials_qs)

    choices = [(str(m.id), f"[{m.type}] {m.name}") for m in materials if not m.is_blocked and m.url]
    form = MaterialsActionForm(request.POST or None, choices=choices)

    def _queue_jobs(ids: list[int], *, kind: str) -> int:
        created = 0
        for mid in ids:
            if kind == "process":
                jt = JobType.PROCESS_MATERIAL
                task = synergy_process_material_job
            else:
                jt = JobType.SOLVE_TEST
                task = synergy_solve_test_job
            job = Job.objects.create(student=student, type=jt, status=JobStatus.PENDING, params={"material_id": mid}, result=None)
            async_result = task.delay(str(job.id))
            job.celery_task_id = async_result.id
            job.save(update_fields=["celery_task_id", "updated_at"])
            created += 1
        return created

    if request.method == "POST" and request.POST.get("action") in {"process_selected", "solve_selected", "auto_all"}:
        selected_ids = []
        if request.POST.get("action") == "auto_all":
            # auto: tests -> solve, others -> process
            to_process = [m.id for m in materials if (not m.is_blocked and m.url and (m.type or "").lower() != "test")]
            to_solve = [m.id for m in materials if (not m.is_blocked and m.url and (m.type or "").lower() == "test")]
            created = _queue_jobs(to_process, kind="process") + _queue_jobs(to_solve, kind="solve")
            messages.success(request, f"Авто-очередь создана: {created} задач.")
            return redirect("web:jobs")

        if form.is_valid():
            selected_ids = [int(x) for x in (form.cleaned_data.get("material_ids") or [])]
        if not selected_ids:
            messages.error(request, "Выберите материалы.")
        else:
            if request.POST.get("action") == "process_selected":
                created = _queue_jobs(selected_ids, kind="process")
                messages.success(request, f"Поставлено задач на обработку: {created}.")
            else:
                created = _queue_jobs(selected_ids, kind="solve")
                messages.success(request, f"Поставлено задач на тесты: {created}.")
            return redirect("web:jobs")

    return render(
        request,
        "web/flow_materials.html",
        {"student": student, "course": course, "materials": materials, "form": form},
    )
