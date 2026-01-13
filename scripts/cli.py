"""Запуск интерактивного CLI меню."""

import sys
from pathlib import Path

# Добавляем корневую директорию проекта в sys.path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from synergy_lms.cli.interactive_cli import main


if __name__ == "__main__":
    main()

