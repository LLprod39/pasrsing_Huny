"""Конфигурация проекта (загрузка из `.env` / переменных окружения)."""

from __future__ import annotations

import os

from dotenv import load_dotenv

# Загружаем переменные из .env (ищется вверх по дереву от cwd)
load_dotenv()


class Config:
    """Класс для хранения конфигурации."""

    # Данные авторизации (только из .env / env — никаких захардкоженных кредов)
    LOGIN = os.getenv("LOGIN", "").strip()
    PASSWORD = os.getenv("PASSWORD", "").strip()

    # Gologin настройки
    GOLOGIN_API_TOKEN = os.getenv("GOLOGIN_API_TOKEN", "").strip()
    GOLOGIN_PROFILE_ID = os.getenv("GOLOGIN_PROFILE_ID", "").strip()
    GOLOGIN_PROFILE_PATH = os.getenv("GOLOGIN_PROFILE_PATH", "").strip()

    # Настройки парсера
    MIN_VIEW_TIME = int(os.getenv("MIN_VIEW_TIME", "30"))
    SCROLL_DELAY = float(os.getenv("SCROLL_DELAY", "2"))
    PAGE_LOAD_TIMEOUT = int(os.getenv("PAGE_LOAD_TIMEOUT", "30"))

    # Медиа-разрешения (нужно для идентификации/камеры перед тестами)
    ALLOW_MEDIA_STREAM = os.getenv("ALLOW_MEDIA_STREAM", "1").strip() not in [
        "0",
        "false",
        "False",
        "no",
        "NO",
    ]

    # Настройки тестов
    TEST_STRATEGY = os.getenv("TEST_STRATEGY", "random").strip().lower()  # random, correct, ai
    MAX_TEST_ATTEMPTS = int(os.getenv("MAX_TEST_ATTEMPTS", "3"))

    # AI (для TEST_STRATEGY=ai)
    AI_PROVIDER = os.getenv("AI_PROVIDER", "grok").strip().lower()  # grok, gemini, ...
    AI_TIMEOUT_SECONDS = int(os.getenv("AI_TIMEOUT_SECONDS", "60"))

    GROK_API_KEY = os.getenv("GROK_API_KEY", "").strip()
    GROK_MODEL = os.getenv("GROK_MODEL", "grok-4-1-fast-reasoning").strip()
    GROK_BASE_URL = os.getenv("GROK_BASE_URL", "https://api.x.ai/v1").strip()

    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview").strip()

    # Артефакты/отладка
    ARTIFACTS_DIR = os.getenv("ARTIFACTS_DIR", "artifacts").strip() or "artifacts"
    DEBUG_HTML_DIR = os.getenv("DEBUG_HTML_DIR", os.path.join(ARTIFACTS_DIR, "debug_html")).strip()
    DEBUG_NDJSON_LOG = os.getenv("DEBUG_NDJSON_LOG", os.path.join("logs", "agent_debug.ndjson")).strip()

    # Логирование
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    LOG_FILE = os.getenv("LOG_FILE", os.path.join("logs", "parser.log")).strip()

    # URL сайта
    BASE_URL = "https://lms.synergy.ru"
    LOGIN_URL = f"{BASE_URL}/"
    LOGIN_POST_URL = f"{BASE_URL}/user/login"

    @classmethod
    def validate(cls) -> None:
        """Проверка наличия обязательных параметров."""
        if not cls.LOGIN or cls.LOGIN in {"your_email@example.com"}:
            raise ValueError("LOGIN должен быть указан в .env (LOGIN=...)")
        if not cls.PASSWORD or cls.PASSWORD in {"your_password"}:
            raise ValueError("PASSWORD должен быть указан в .env (PASSWORD=...)")

        if not cls.GOLOGIN_API_TOKEN and not cls.GOLOGIN_PROFILE_PATH:
            print("Предупреждение: Gologin не настроен. Будет использован обычный браузер.")
