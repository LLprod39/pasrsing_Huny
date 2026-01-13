# Скрипт запуска Celery Worker (Windows PowerShell)

Write-Host "=== Запуск Celery Worker ===" -ForegroundColor Green

# Проверка Redis
Write-Host "Проверка Redis..." -ForegroundColor Cyan
try {
    $redis_test = python -c "import redis; r=redis.Redis.from_url('redis://localhost:6379/0'); r.ping(); print('OK')" 2>&1
    if ($redis_test -notmatch "OK") {
        Write-Host "ОШИБКА: Redis недоступен!" -ForegroundColor Red
        Write-Host "Убедитесь, что Redis запущен на localhost:6379" -ForegroundColor Yellow
        exit 1
    }
    Write-Host "Redis доступен" -ForegroundColor Green
} catch {
    Write-Host "ОШИБКА: Не удалось подключиться к Redis!" -ForegroundColor Red
    Write-Host "Установите и запустите Redis, или измените CELERY_BROKER_URL в .env" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "Запуск Celery Worker (solo pool для Windows)..." -ForegroundColor Cyan
Write-Host "Для остановки нажмите Ctrl+C" -ForegroundColor Yellow
Write-Host ""

python -m celery -A synergy_backend worker -l info -P solo
