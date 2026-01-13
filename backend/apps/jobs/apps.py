from __future__ import annotations

from django.apps import AppConfig


class JobsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.jobs"

    def ready(self) -> None:
        """Ensure Celery app is initialized in Django process.

        Without this, calling `.delay()` from Django may use the default Celery app
        (wrong broker), and jobs will sit in PENDING forever.
        """

        try:
            from synergy_backend.celery import app as celery_app
            celery_app.set_default()
        except Exception:
            # Don't break Django startup if Celery isn't configured yet.
            return

