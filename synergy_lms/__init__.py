"""Synergy LMS automation toolkit.

Пакет содержит:
- core: конфиг и логирование
- lms: автоматизация (auth, парсинг курсов, обработка материалов, решение тестов)
- ai_providers: провайдеры AI (grok/gemini) для стратегии TEST_STRATEGY=ai
- web: FastAPI Web UI
- cli: CLI/TUI точки входа
"""

__all__ = ["config", "logger", "lms", "ai_providers", "web", "cli"]

