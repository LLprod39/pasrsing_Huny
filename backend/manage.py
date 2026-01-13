#!/usr/bin/env python
"""Django's command-line utility for administrative tasks.

Important: this repo has `synergy_lms/` at the repository root. When running:
  python backend/manage.py ...
Python won't automatically see the repo root on sys.path, so we add it here.
"""

import os
import sys
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "synergy_backend.settings")

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and available on your PYTHONPATH?"
            " Did you forget to install requirements?"
        ) from exc

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()

