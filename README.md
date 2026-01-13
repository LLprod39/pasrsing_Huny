# Synergy LMS Automation

Автоматизация LMS Synergy: авторизация, парсинг семестров/курсов, автопросмотр материалов и автопрохождение тестов (random/AI).  
Есть **CLI меню**, **полноэкранный TUI** и **Web UI**.

> Важно: папка `old_pasrsing_старайпроект_нетрогать` — это старый проект. Он сохранён как есть и не используется текущим кодом.

## Быстрый старт

### Установка

1) Установите зависимости:

```bash
pip install -r requirements.txt
```

2) (Опционально) Установите пакет в режиме разработки для удобства импортов:

```bash
pip install -e .
```

**Примечание:** Скрипты в `scripts/` работают и без установки пакета, так как они автоматически добавляют корневую директорию проекта в `sys.path`.

3) Создайте `.env` из шаблона:

- Windows:

```bash
copy env_template.txt .env
```

- Linux/macOS:

```bash
cp env_template.txt .env
```

4) Заполните `.env` минимум:
- `LOGIN`
- `PASSWORD`

### Запуск

- Интерактивное CLI меню:

```bash
python scripts/cli.py
```

- Полноэкранный TUI (Textual):

```bash
python scripts/tui.py
```

- Web UI (FastAPI + статика):

```bash
python scripts/web.py
```

Откройте в браузере: `http://127.0.0.1:8000`

- Самопроверка AI-провайдера (choice/text/order/match):

```bash
python scripts/ai_selftest.py
```

## Конфигурация (.env)

Шаблон — в `env_template.txt`.

### Обязательные

- `LOGIN`: логин/email от LMS Synergy
- `PASSWORD`: пароль от LMS Synergy

### Gologin (опционально)

- `GOLOGIN_API_TOKEN`
- `GOLOGIN_PROFILE_ID`

Если Gologin не настроен — используется обычный Chrome с анти-детект опциями.

### Тесты

- `TEST_STRATEGY`: `random` | `ai`
- `MAX_TEST_ATTEMPTS`: по умолчанию `3`

### AI (если `TEST_STRATEGY=ai`)

- `AI_PROVIDER`: `grok` | `gemini`
- `AI_TIMEOUT_SECONDS`: таймаут запросов к AI

Grok (xAI):
- `GROK_API_KEY`
- `GROK_MODEL`
- `GROK_BASE_URL` (по умолчанию `https://api.x.ai/v1`)

Gemini (Google):
- `GEMINI_API_KEY`
- `GEMINI_MODEL`

### Логи и отладка

- `LOG_LEVEL`: `DEBUG|INFO|WARNING|ERROR`
- `LOG_FILE`: по умолчанию `logs/parser.log`
- `DEBUG_HTML_DIR`: куда сохранять HTML-дампы (по умолчанию `artifacts/debug_html`)
- `DEBUG_NDJSON_LOG`: отладочный NDJSON лог (по умолчанию `logs/agent_debug.ndjson`)

## Архитектура и структура проекта

Код проекта разложен по пакетам, чтобы его было проще расширять:

```
synergy_lms/                 # основной Python-пакет
  config.py                  # Config (загрузка .env)
  logger.py                  # setup_logger + файл логов
  lms/                       # Selenium-автоматизация LMS
    auth.py
    gologin_manager.py
    course_parser.py
    material_processor.py
    test_solver.py
    task_manager.py          # очередь задач для Web UI
  ai_providers/              # AI провайдеры (grok/gemini) + registry
  cli/                       # CLI/TUI entrypoints (логика запуска)
  web/                       # FastAPI app + статика
    app.py
    static/
scripts/                     # удобные команды запуска (python scripts/...)
docs/                        # документация (например, план разработки)
logs/                        # runtime логи (gitignored)
artifacts/                   # артефакты/дампы (gitignored)
data/                        # данные/fixtures (по желанию)
old_pasrsing_старайпроект_нетрогать/  # старый проект (не трогать)
```

## Заметки по Web UI

- Web UI общается с API по `/api/*` и отдаёт статику на `/`.
- В `task_manager.py` задачи выполняются последовательно (Selenium/WebDriver не потокобезопасен).

## Безопасность

- Файл `.env` уже в `.gitignore` — **не коммитьте** логины/пароли/ключи.

## Дисклеймер

Инструмент предназначен для образовательных целей. Используйте ответственно и в рамках правил LMS Synergy.
