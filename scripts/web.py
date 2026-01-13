"""Запуск Web UI (FastAPI + StaticFiles)."""

import sys
from pathlib import Path

# Добавляем корневую директорию проекта в sys.path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import uvicorn


if __name__ == "__main__":
    uvicorn.run("synergy_lms.web.app:app", host="0.0.0.0", port=8000, reload=True)

