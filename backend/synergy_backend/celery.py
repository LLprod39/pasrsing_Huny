from __future__ import annotations

import os
from pathlib import Path
import sys

from celery import Celery


def _ensure_repo_root_on_path() -> None:
    repo_root = Path(__file__).resolve().parent.parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


_ensure_repo_root_on_path()
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "synergy_backend.settings")

app = Celery("synergy_backend")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Make this Celery app the default one used by shared_task()/delay()
app.set_default()
