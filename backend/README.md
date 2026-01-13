# Django Backend - Инструкция по запуску

## Быстрый старт

### 1. Установка зависимостей

Убедитесь, что все зависимости установлены:

```bash
pip install -r requirements.txt
```

### 2. Настройка .env

Скопируйте шаблон и заполните:

```bash
# Windows
copy ..\env_template.txt ..\.env

# Linux/macOS
cp ../env_template.txt ../.env
```

**Минимально необходимые переменные для запуска:**

```env
# Django
DJANGO_SECRET_KEY=ваш-секретный-ключ-минимум-50-символов
DJANGO_DEBUG=1
DJANGO_ALLOWED_HOSTS=*

# Celery/Redis (если используете)
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# Шифрование паролей студентов (обязательно!)
CREDENTIAL_ENCRYPTION_KEY=ваш-ключ-шифрования-минимум-32-символа

# Для парсинга Synergy (если тестируете)
LOGIN=ваш_email@example.com
PASSWORD=ваш_пароль
```

**Генерация ключей:**

```python
# В Python shell:
import secrets
import base64

# Для DJANGO_SECRET_KEY
print(secrets.token_urlsafe(50))

# Для CREDENTIAL_ENCRYPTION_KEY (нужен base64-ключ для Fernet)
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
```

### 3. Применение миграций

```bash
cd backend
python manage.py migrate
```

### 4. Создание суперпользователя (для доступа в админку)

```bash
python manage.py createsuperuser
```

Введите username, email и пароль.

### 5. Запуск Django сервера

```bash
python manage.py runserver 0.0.0.0:8000
```

Откройте в браузере:
- **Admin панель**: http://localhost:8000/admin/
- **API Swagger**: http://localhost:8000/api/v1/docs/

### 6. Запуск Celery Worker (для фоновых задач)

**Важно:** Celery worker нужен для выполнения Selenium-задач (логин, синхронизация, обработка материалов, тесты).

#### Windows (используем `solo` pool, т.к. `prefork` не работает):

```bash
cd backend
celery -A synergy_backend worker -l info -P solo
```

#### Linux/macOS:

```bash
cd backend
celery -A synergy_backend worker -l info
```

#### С Redis (если Redis запущен):

Убедитесь, что Redis запущен:

```bash
# Windows (если установлен через Chocolatey или вручную)
redis-server

# Linux
sudo systemctl start redis
# или
redis-server

# macOS (Homebrew)
brew services start redis
```

Если Redis не установлен, можно использовать SQLite как брокер (не рекомендуется для продакшена):

```env
CELERY_BROKER_URL=db+sqlite:///celery_broker.sqlite
CELERY_RESULT_BACKEND=db+sqlite:///celery_result.sqlite
```

Но для этого нужно установить `kombu[sqlite]`:

```bash
pip install kombu[sqlite]
```

### 7. Проверка работы

1. Откройте http://localhost:8000/admin/
2. Войдите с учетными данными суперпользователя
3. Создайте студента: **Accounts → Students → Add Student**
4. Добавьте Synergy-креды: **Synergy → Synergy Credentials → Add**
5. Запустите синхронизацию через админку или API

## API Endpoints

### Swagger UI
- http://localhost:8000/api/v1/docs/

### Основные эндпоинты:

- `GET /api/v1/students/` - список студентов
- `POST /api/v1/students/` - создать студента
- `GET /api/v1/students/{id}/` - детали студента
- `PUT /api/v1/students/{id}/synergy-credential/` - обновить креды Synergy

- `POST /api/v1/students/{id}/synergy-login/` - запустить job логина
- `POST /api/v1/students/{id}/sync-semesters/` - синхронизировать семестры
- `POST /api/v1/students/{id}/sync-courses/` - синхронизировать курсы
- `POST /api/v1/students/{id}/sync-materials/` - синхронизировать материалы

- `POST /api/v1/materials/{id}/process/` - обработать материал
- `POST /api/v1/materials/{id}/solve_test/` - решить тест

- `GET /api/v1/jobs/` - список jobs
- `GET /api/v1/jobs/{id}/` - статус job
- `POST /api/v1/jobs/{id}/cancel/` - отменить job

## Структура проекта

```
backend/
├── manage.py
├── synergy_backend/      # Django project settings
│   ├── settings.py
│   ├── urls.py
│   ├── api_urls.py       # API routes
│   └── celery.py         # Celery config
└── apps/
    ├── accounts/         # Студенты
    ├── synergy/          # Synergy LMS интеграция
    ├── jobs/             # Celery tasks
    ├── billing/          # Платежи (Stripe)
    └── bot/              # Настройки бота
```

## Troubleshooting

### Ошибка "No module named 'synergy_lms'"

Убедитесь, что вы в корне проекта (где есть `synergy_lms/`), и что пакет установлен:

```bash
pip install -e .
```

### Celery worker не запускается

- Проверьте, что Redis запущен: `redis-cli ping` (должен ответить `PONG`)
- Или используйте SQLite брокер (см. выше)

### Ошибка шифрования паролей

Убедитесь, что `CREDENTIAL_ENCRYPTION_KEY` задан в `.env` и это валидный Fernet-ключ (base64, 44 символа).

### Selenium не работает

- Убедитесь, что Chrome/Chromium установлен
- Проверьте, что `webdriver-manager` может скачать драйвер
- Для Windows может потребоваться `chromedriver.exe` в PATH

## Production

Для продакшена:

1. Установите `DJANGO_DEBUG=0`
2. Укажите конкретные хосты в `DJANGO_ALLOWED_HOSTS`
3. Используйте PostgreSQL вместо SQLite
4. Настройте статику: `python manage.py collectstatic`
5. Используйте WSGI сервер (gunicorn/uwsgi) вместо `runserver`
6. Настройте HTTPS
7. Используйте Redis для Celery (обязательно)
