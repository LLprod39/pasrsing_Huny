from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


# ===== Paths =====
BACKEND_DIR = Path(__file__).resolve().parent.parent  # .../backend
REPO_ROOT = BACKEND_DIR.parent  # repo root (contains synergy_lms/)

# Load `.env` automatically (same repo behavior as the parser scripts).
# This fixes common dev issues where DJANGO_DEBUG etc. are present in `.env`
# but not exported into the process environment.
load_dotenv(dotenv_path=str(REPO_ROOT / '.env'), override=False)
load_dotenv(dotenv_path=str(BACKEND_DIR / '.env'), override=False)


# ===== Core settings =====
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-secret-key-change-me")
DEBUG = os.environ.get("DJANGO_DEBUG", "0").strip() in {"1", "true", "True", "TRUE", "yes", "YES"}

ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",") if h.strip()]

TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "UTC")
USE_TZ = True

LANGUAGE_CODE = os.environ.get("DJANGO_LANGUAGE_CODE", "ru-ru")


# ===== Apps =====
INSTALLED_APPS = [
    # Admin UI theme (must be before django.contrib.admin)
    "unfold",
    # Django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "corsheaders",
    "rest_framework",
    "rest_framework_simplejwt",
    "drf_spectacular",
    # Local apps
    "apps.accounts",
    "apps.synergy",
    "apps.jobs",
    "apps.billing",
    "apps.bot",
]


MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "synergy_backend.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [str(BACKEND_DIR / "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "synergy_backend.wsgi.application"
ASGI_APPLICATION = "synergy_backend.asgi.application"


# ===== Database =====
# Prefer DATABASE_URL for Postgres in production, fallback to sqlite for local dev.
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if DATABASE_URL:
    import dj_database_url

    DATABASES = {"default": dj_database_url.parse(DATABASE_URL, conn_max_age=600)}
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": str(BACKEND_DIR / "db.sqlite3")}}


# ===== Auth / Password validation =====
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# ===== Static =====
STATIC_URL = "/static/"
STATIC_ROOT = str(BACKEND_DIR / "staticfiles")


# ===== CORS =====
CORS_ALLOW_ALL_ORIGINS = os.environ.get("CORS_ALLOW_ALL_ORIGINS", "1").strip() in {"1", "true", "True", "yes", "YES"}


# ===== DRF =====
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAdminUser",),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Synergy Backend API",
    "DESCRIPTION": "Django/DRF API for Synergy LMS automation + admin panel.",
    "VERSION": "1.0.0",
}


# ===== Celery =====
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE


# ===== Security / encryption =====
# Used later for encrypting per-student Synergy passwords.
# For production set a stable value; for local dev we can derive if missing.
CREDENTIAL_ENCRYPTION_KEY = os.environ.get("CREDENTIAL_ENCRYPTION_KEY", "").strip()



# ===== Admin UI (Unfold) =====
UNFOLD = {
    "SITE_TITLE": "Synergy Admin",
    "SITE_HEADER": "Synergy Bot",
    "SITE_SYMBOL": "smart_toy",
    "SITE_SUBHEADER": "Студенты • доступы • синхронизация • платежи",
    "SITE_URL": "/admin/",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "SIDEBAR": {
        "show_search": True,
        "command_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "title": "Основное",
                "separator": False,
                "collapsible": False,
                "items": [
                    {"title": "Студенты", "icon": "school", "link": "/admin/accounts/student/"},
                    {
                        "title": "Jobs",
                        "icon": "playlist_add_check",
                        "link": "/admin/jobs/job/",
                        "badge": "synergy_backend.unfold_badges.pending_jobs_badge",
                        "badge_variant": "warning",
                        "badge_style": "solid",
                    },
                ],
            },
            {
                "title": "Synergy LMS",
                "separator": True,
                "collapsible": True,
                "items": [
                    {"title": "Креды Synergy", "icon": "key", "link": "/admin/synergy/synergycredential/"},
                    {"title": "Семестры", "icon": "calendar_month", "link": "/admin/synergy/semester/"},
                    {"title": "Курсы", "icon": "menu_book", "link": "/admin/synergy/course/"},
                    {"title": "Материалы", "icon": "description", "link": "/admin/synergy/material/"},
                ],
            },
            {
                "title": "Billing",
                "separator": True,
                "collapsible": True,
                "items": [
                    {"title": "Планы", "icon": "sell", "link": "/admin/billing/plan/"},
                    {"title": "Подписки", "icon": "verified", "link": "/admin/billing/subscription/"},
                    {"title": "Платежи", "icon": "payments", "link": "/admin/billing/payment/"},
                    {"title": "Webhooks", "icon": "webhook", "link": "/admin/billing/webhookevent/"},
                ],
            },
            {
                "title": "Настройки",
                "separator": True,
                "collapsible": True,
                "items": [
                    {"title": "Настройки бота", "icon": "smart_toy", "link": "/admin/bot/botconfig/"},
                ],
            },
        ],
    },
}
