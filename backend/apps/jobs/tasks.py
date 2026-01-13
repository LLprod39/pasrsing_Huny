from __future__ import annotations

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.synergy.models import Course, Material, Semester, SynergyCredential
from apps.synergy.synergy_client import SeleniumSynergyClient, SynergyLoginError

from synergy_lms.lms.material_processor import MaterialProcessor
from synergy_lms.lms.test_solver import TestSolver

from .models import Job, JobStatus, JobType
from .services import mark_completed, mark_failed, mark_running, set_progress


def _get_job_for_update(job_id: str) -> Job:
    # Lock row to avoid concurrent updates from retries/duplicates.
    return Job.objects.select_related("student").select_for_update().get(id=job_id)


def _get_student_credentials(student_id: int) -> tuple[str, str]:
    cred = SynergyCredential.objects.select_related("student").get(student_id=student_id)
    login = (cred.login or "").strip()
    password = (cred.get_password() or "").strip()
    return login, password


@shared_task(bind=True, autoretry_for=(), retry_backoff=False)
def synergy_login_job(self, job_id: str) -> dict:
    """Validate per-student Synergy credentials by doing a real login."""
    with transaction.atomic():
        job = _get_job_for_update(job_id)
        if job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            return {"status": job.status, "job_id": str(job.id)}
        if job.type != JobType.LOGIN:
            mark_failed(job, error=f"Job type mismatch: expected {JobType.LOGIN}, got {job.type}")
            return {"status": job.status, "job_id": str(job.id)}
        mark_running(job, celery_task_id=self.request.id, message="Logging in to Synergy...")

    try:
        login, password = _get_student_credentials(job.student_id)
        if not login or not password:
            raise ValueError("Student Synergy credentials are missing (login/password)")

        set_progress(job, progress=10, message="Starting browser...")
        with SeleniumSynergyClient(use_gologin=False) as client:
            set_progress(job, progress=40, message="Authorizing...")
            client.login(login=login, password=password)

        SynergyCredential.objects.filter(student_id=job.student_id).update(last_validated_at=timezone.now())
        mark_completed(job, result={"ok": True}, message="Synergy login OK")
        return {"status": JobStatus.COMPLETED, "job_id": str(job.id), "ok": True}
    except SynergyLoginError as e:
        mark_failed(job, error=str(e), message="Synergy login failed")
        return {"status": JobStatus.FAILED, "job_id": str(job.id), "ok": False, "error": str(e)}
    except Exception as e:
        mark_failed(job, error=str(e))
        return {"status": JobStatus.FAILED, "job_id": str(job.id), "ok": False, "error": str(e)}


@shared_task(bind=True, autoretry_for=(), retry_backoff=False)
def synergy_sync_semesters_job(self, job_id: str) -> dict:
    """Login and sync available semesters into DB for a student."""
    with transaction.atomic():
        job = _get_job_for_update(job_id)
        if job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            return {"status": job.status, "job_id": str(job.id)}
        if job.type != JobType.SYNC_SEMESTERS:
            mark_failed(job, error=f"Job type mismatch: expected {JobType.SYNC_SEMESTERS}, got {job.type}")
            return {"status": job.status, "job_id": str(job.id)}
        mark_running(job, celery_task_id=self.request.id, message="Syncing semesters...")

    try:
        login, password = _get_student_credentials(job.student_id)
        if not login or not password:
            raise ValueError("Student Synergy credentials are missing (login/password)")

        set_progress(job, progress=10, message="Starting browser...")
        with SeleniumSynergyClient(use_gologin=False) as client:
            set_progress(job, progress=35, message="Authorizing...")
            client.login(login=login, password=password)

            set_progress(job, progress=65, message="Fetching semesters...")
            numbers = client.get_semesters()

        # Upsert semesters (simple: add missing; keep existing).
        set_progress(job, progress=85, message="Saving semesters...")
        Semester.objects.bulk_create(
            [Semester(student_id=job.student_id, number=n) for n in numbers],
            ignore_conflicts=True,
        )

        SynergyCredential.objects.filter(student_id=job.student_id).update(last_validated_at=timezone.now())
        mark_completed(job, result={"semesters": numbers, "count": len(numbers)}, message="Semesters synced")
        return {"status": JobStatus.COMPLETED, "job_id": str(job.id), "count": len(numbers)}
    except SynergyLoginError as e:
        mark_failed(job, error=str(e), message="Synergy login failed")
        return {"status": JobStatus.FAILED, "job_id": str(job.id), "error": str(e)}
    except Exception as e:
        mark_failed(job, error=str(e))
        return {"status": JobStatus.FAILED, "job_id": str(job.id), "error": str(e)}


@shared_task(bind=True, autoretry_for=(), retry_backoff=False)
def synergy_sync_courses_job(self, job_id: str) -> dict:
    """Login and sync courses for a given semester_number (provided in job.params)."""
    with transaction.atomic():
        job = _get_job_for_update(job_id)
        if job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            return {"status": job.status, "job_id": str(job.id)}
        if job.type != JobType.SYNC_COURSES:
            mark_failed(job, error=f"Job type mismatch: expected {JobType.SYNC_COURSES}, got {job.type}")
            return {"status": job.status, "job_id": str(job.id)}
        mark_running(job, celery_task_id=self.request.id, message="Syncing courses...")

    try:
        semester_number = int((job.params or {}).get("semester_number") or 0)
        if semester_number <= 0:
            raise ValueError("Missing job.params.semester_number")

        login, password = _get_student_credentials(job.student_id)
        if not login or not password:
            raise ValueError("Student Synergy credentials are missing (login/password)")

        set_progress(job, progress=10, message="Starting browser...")
        with SeleniumSynergyClient(use_gologin=False) as client:
            set_progress(job, progress=30, message="Authorizing...")
            client.login(login=login, password=password)

            set_progress(job, progress=60, message=f"Fetching courses for semester {semester_number}...")
            courses = client.get_courses(semester_number)

        set_progress(job, progress=85, message="Saving courses...")
        saved = 0
        for c in courses:
            url = (c.get("url") or "").strip()
            if not url:
                continue
            Course.objects.update_or_create(
                student_id=job.student_id,
                url=url,
                defaults={
                    "semester_number": semester_number,
                    "name": (c.get("name") or "").strip(),
                    "control_type": (c.get("control_type") or "").strip(),
                },
            )
            saved += 1

        SynergyCredential.objects.filter(student_id=job.student_id).update(last_validated_at=timezone.now())
        mark_completed(job, result={"semester_number": semester_number, "count": saved}, message="Courses synced")
        return {"status": JobStatus.COMPLETED, "job_id": str(job.id), "count": saved}
    except SynergyLoginError as e:
        mark_failed(job, error=str(e), message="Synergy login failed")
        return {"status": JobStatus.FAILED, "job_id": str(job.id), "error": str(e)}
    except Exception as e:
        mark_failed(job, error=str(e))
        return {"status": JobStatus.FAILED, "job_id": str(job.id), "error": str(e)}


def _iter_leaf_materials(structured: list[dict]) -> list[dict]:
    out: list[dict] = []

    def walk(items: list[dict]) -> None:
        for item in items:
            if isinstance(item, dict) and "materials" in item:
                walk(item.get("materials") or [])
                continue
            if isinstance(item, dict) and "name" in item:
                out.append(item)

    walk(structured)
    return out


def _iter_material_leaves_with_path(structured: list[dict]) -> list[dict]:
    """Flatten materials tree with section path and blocked reason."""
    out: list[dict] = []

    def walk(items: list[dict], path: list[str]) -> None:
        for item in items:
            if not isinstance(item, dict):
                continue
            # Section node
            if "materials" in item:
                title = (item.get("title") or "").strip()
                next_path = path + ([title] if title else [])
                walk(item.get("materials") or [], next_path)
                continue
            # Leaf node
            if "name" in item:
                out.append(
                    {
                        **item,
                        "section_path": " / ".join([p for p in path if p]),
                        "blocked_reason": (item.get("reason") or "").strip(),
                    }
                )

    walk(structured, [])
    return out


@shared_task(bind=True, autoretry_for=(), retry_backoff=False)
def synergy_sync_materials_job(self, job_id: str) -> dict:
    """Login and sync materials for a given course_id (provided in job.params)."""
    with transaction.atomic():
        job = _get_job_for_update(job_id)
        if job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            return {"status": job.status, "job_id": str(job.id)}
        if job.type != JobType.SYNC_MATERIALS:
            mark_failed(job, error=f"Job type mismatch: expected {JobType.SYNC_MATERIALS}, got {job.type}")
            return {"status": job.status, "job_id": str(job.id)}
        mark_running(job, celery_task_id=self.request.id, message="Syncing materials...")

    try:
        course_id = int((job.params or {}).get("course_id") or 0)
        if course_id <= 0:
            raise ValueError("Missing job.params.course_id")

        course = Course.objects.get(id=course_id, student_id=job.student_id)

        login, password = _get_student_credentials(job.student_id)
        if not login or not password:
            raise ValueError("Student Synergy credentials are missing (login/password)")

        set_progress(job, progress=10, message="Starting browser...")
        with SeleniumSynergyClient(use_gologin=False) as client:
            set_progress(job, progress=30, message="Authorizing...")
            client.login(login=login, password=password)

            set_progress(job, progress=60, message="Fetching materials...")
            structured, _flat = client.get_course_materials(course.url)

        leaf = _iter_material_leaves_with_path(structured)
        set_progress(job, progress=85, message="Saving materials...")

        saved = 0
        for m in leaf:
            name = (m.get("name") or "").strip()
            url = (m.get("url") or "").strip() or None
            mat_type = (m.get("type") or "material").strip()
            is_blocked = bool(m.get("is_blocked"))
            data_index = (m.get("data_index") or "").strip()
            section_path = (m.get("section_path") or "").strip()
            blocked_reason = (m.get("blocked_reason") or "").strip()

            if url:
                Material.objects.update_or_create(
                    student_id=job.student_id,
                    course_id=course.id,
                    url=url,
                    defaults={
                        "name": name,
                        "type": mat_type,
                        "is_blocked": is_blocked,
                        "data_index": data_index,
                        "section_path": section_path,
                        "blocked_reason": blocked_reason,
                        "raw": m,
                    },
                )
            else:
                Material.objects.update_or_create(
                    student_id=job.student_id,
                    course_id=course.id,
                    name=name,
                    data_index=data_index,
                    defaults={
                        "url": None,
                        "type": mat_type,
                        "is_blocked": True,
                        "section_path": section_path,
                        "blocked_reason": blocked_reason or "Blocked",
                        "raw": m,
                    },
                )
            saved += 1

        SynergyCredential.objects.filter(student_id=job.student_id).update(last_validated_at=timezone.now())
        mark_completed(job, result={"course_id": course_id, "count": saved}, message="Materials synced")
        return {"status": JobStatus.COMPLETED, "job_id": str(job.id), "count": saved}
    except SynergyLoginError as e:
        mark_failed(job, error=str(e), message="Synergy login failed")
        return {"status": JobStatus.FAILED, "job_id": str(job.id), "error": str(e)}


@shared_task(bind=True, autoretry_for=(), retry_backoff=False)
def synergy_sync_full_job(self, job_id: str) -> dict:
    """One-shot sync: semesters -> courses -> materials.

    Optional:
      job.params.allowed_semesters: list[int] | null
    """
    with transaction.atomic():
        job = _get_job_for_update(job_id)
        if job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            return {"status": job.status, "job_id": str(job.id)}
        if job.type != JobType.SYNC_FULL:
            mark_failed(job, error=f"Job type mismatch: expected {JobType.SYNC_FULL}, got {job.type}")
            return {"status": job.status, "job_id": str(job.id)}
        mark_running(job, celery_task_id=self.request.id, message="Syncing everything...")

    try:
        allowed = (job.params or {}).get("allowed_semesters")
        if allowed is not None:
            allowed = [int(x) for x in allowed]

        login, password = _get_student_credentials(job.student_id)
        if not login or not password:
            raise ValueError("Student Synergy credentials are missing (login/password)")

        set_progress(job, progress=5, message="Starting browser...")
        with SeleniumSynergyClient(use_gologin=False) as client:
            set_progress(job, progress=10, message="Authorizing...")
            client.login(login=login, password=password)

            set_progress(job, progress=20, message="Fetching semesters...")
            semesters = client.get_semesters()
            if allowed is not None:
                semesters = [s for s in semesters if s in allowed]

            Semester.objects.bulk_create(
                [Semester(student_id=job.student_id, number=n) for n in semesters],
                ignore_conflicts=True,
            )

            total_courses = 0
            total_materials = 0
            for idx, sem in enumerate(semesters):
                set_progress(job, progress=25 + int(25 * (idx / max(1, len(semesters)))), message=f"Courses: semester {sem}...")
                courses = client.get_courses(sem)
                saved_courses = []
                for c in courses:
                    url = (c.get("url") or "").strip()
                    if not url:
                        continue
                    obj, _ = Course.objects.update_or_create(
                        student_id=job.student_id,
                        url=url,
                        defaults={
                            "semester_number": sem,
                            "name": (c.get("name") or "").strip(),
                            "control_type": (c.get("control_type") or "").strip(),
                        },
                    )
                    saved_courses.append(obj)
                total_courses += len(saved_courses)

                for cidx, course in enumerate(saved_courses):
                    set_progress(
                        job,
                        progress=50 + int(45 * ((idx + (cidx / max(1, len(saved_courses)))) / max(1, len(semesters)))),
                        message=f"Materials: {course.name[:40]}...",
                    )
                    structured, _flat = client.get_course_materials(course.url)
                    leaf = _iter_material_leaves_with_path(structured)

                    for m in leaf:
                        name = (m.get("name") or "").strip()
                        url = (m.get("url") or "").strip() or None
                        mat_type = (m.get("type") or "material").strip()
                        is_blocked = bool(m.get("is_blocked"))
                        data_index = (m.get("data_index") or "").strip()
                        section_path = (m.get("section_path") or "").strip()
                        blocked_reason = (m.get("blocked_reason") or "").strip()

                        if url:
                            Material.objects.update_or_create(
                                student_id=job.student_id,
                                course_id=course.id,
                                url=url,
                                defaults={
                                    "name": name,
                                    "type": mat_type,
                                    "is_blocked": is_blocked,
                                    "data_index": data_index,
                                    "section_path": section_path,
                                    "blocked_reason": blocked_reason,
                                    "raw": m,
                                },
                            )
                        else:
                            Material.objects.update_or_create(
                                student_id=job.student_id,
                                course_id=course.id,
                                name=name,
                                data_index=data_index,
                                defaults={
                                    "url": None,
                                    "type": mat_type,
                                    "is_blocked": True,
                                    "section_path": section_path,
                                    "blocked_reason": blocked_reason or "Blocked",
                                    "raw": m,
                                },
                            )
                    total_materials += len(leaf)

        now = timezone.now()
        SynergyCredential.objects.filter(student_id=job.student_id).update(last_validated_at=now)
        mark_completed(
            job,
            result={"semesters": semesters, "courses_count": total_courses, "materials_count": total_materials},
            message="Full sync completed",
        )
        return {"status": JobStatus.COMPLETED, "job_id": str(job.id)}
    except SynergyLoginError as e:
        mark_failed(job, error=str(e), message="Synergy login failed")
        return {"status": JobStatus.FAILED, "job_id": str(job.id), "error": str(e)}
    except Exception as e:
        mark_failed(job, error=str(e))
        return {"status": JobStatus.FAILED, "job_id": str(job.id), "error": str(e)}
    except Exception as e:
        mark_failed(job, error=str(e))
        return {"status": JobStatus.FAILED, "job_id": str(job.id), "error": str(e)}


@shared_task(bind=True, autoretry_for=(), retry_backoff=False)
def synergy_process_material_job(self, job_id: str) -> dict:
    """Process a single material using existing `synergy_lms` logic.

    Expects: job.params.material_id
    """
    with transaction.atomic():
        job = _get_job_for_update(job_id)
        if job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            return {"status": job.status, "job_id": str(job.id)}
        if job.type != JobType.PROCESS_MATERIAL:
            mark_failed(job, error=f"Job type mismatch: expected {JobType.PROCESS_MATERIAL}, got {job.type}")
            return {"status": job.status, "job_id": str(job.id)}
        mark_running(job, celery_task_id=self.request.id, message="Processing material...")

    try:
        material_id = int((job.params or {}).get("material_id") or 0)
        if material_id <= 0:
            raise ValueError("Missing job.params.material_id")

        material = Material.objects.select_related("course", "student").get(id=material_id)
        if material.student_id != job.student_id:
            raise ValueError("Material belongs to a different student")
        if material.is_blocked or not material.url:
            raise ValueError("Material is blocked or has no URL")

        login, password = _get_student_credentials(job.student_id)
        if not login or not password:
            raise ValueError("Student Synergy credentials are missing (login/password)")

        set_progress(job, progress=10, message="Starting browser...")
        with SeleniumSynergyClient(use_gologin=False) as client:
            set_progress(job, progress=30, message="Authorizing...")
            client.login(login=login, password=password)

            set_progress(job, progress=60, message="Processing material in Synergy...")
            processor = MaterialProcessor(client.driver)
            res = processor.process_material(
                {
                    "name": material.name,
                    "url": material.url,
                    "type": material.type,
                    "course_url": material.course.url,
                }
            )

        now = timezone.now()
        Material.objects.filter(id=material.id).update(last_processed_at=now, last_result=res, updated_at=now)
        SynergyCredential.objects.filter(student_id=job.student_id).update(last_validated_at=now)

        mark_completed(job, result=res, message="Material processed")
        return {"status": JobStatus.COMPLETED, "job_id": str(job.id), "material_id": material_id}
    except SynergyLoginError as e:
        mark_failed(job, error=str(e), message="Synergy login failed")
        return {"status": JobStatus.FAILED, "job_id": str(job.id), "error": str(e)}
    except Exception as e:
        mark_failed(job, error=str(e))
        return {"status": JobStatus.FAILED, "job_id": str(job.id), "error": str(e)}


@shared_task(bind=True, autoretry_for=(), retry_backoff=False)
def synergy_solve_test_job(self, job_id: str) -> dict:
    """Solve a test material using existing `synergy_lms` logic.

    Expects: job.params.material_id
    """
    with transaction.atomic():
        job = _get_job_for_update(job_id)
        if job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            return {"status": job.status, "job_id": str(job.id)}
        if job.type != JobType.SOLVE_TEST:
            mark_failed(job, error=f"Job type mismatch: expected {JobType.SOLVE_TEST}, got {job.type}")
            return {"status": job.status, "job_id": str(job.id)}
        mark_running(job, celery_task_id=self.request.id, message="Solving test...")

    try:
        material_id = int((job.params or {}).get("material_id") or 0)
        if material_id <= 0:
            raise ValueError("Missing job.params.material_id")

        material = Material.objects.select_related("course", "student").get(id=material_id)
        if material.student_id != job.student_id:
            raise ValueError("Material belongs to a different student")
        if material.is_blocked or not material.url:
            raise ValueError("Material is blocked or has no URL")

        login, password = _get_student_credentials(job.student_id)
        if not login or not password:
            raise ValueError("Student Synergy credentials are missing (login/password)")

        set_progress(job, progress=10, message="Starting browser...")
        with SeleniumSynergyClient(use_gologin=False) as client:
            set_progress(job, progress=30, message="Authorizing...")
            client.login(login=login, password=password)

            set_progress(job, progress=60, message="Solving test in Synergy...")
            solver = TestSolver(client.driver)
            res = solver.solve_test(material.url, material.name, course_url=material.course.url)

        now = timezone.now()
        Material.objects.filter(id=material.id).update(last_processed_at=now, last_result=res, updated_at=now)
        SynergyCredential.objects.filter(student_id=job.student_id).update(last_validated_at=now)

        mark_completed(job, result=res, message="Test solved")
        return {"status": JobStatus.COMPLETED, "job_id": str(job.id), "material_id": material_id}
    except SynergyLoginError as e:
        mark_failed(job, error=str(e), message="Synergy login failed")
        return {"status": JobStatus.FAILED, "job_id": str(job.id), "error": str(e)}
    except Exception as e:
        mark_failed(job, error=str(e))
        return {"status": JobStatus.FAILED, "job_id": str(job.id), "error": str(e)}

