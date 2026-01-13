# Скрипт быстрого запуска Django backend (Windows PowerShell)

Write-Host "=== Запуск Django Backend ===" -ForegroundColor Green

# Проверка .env
if (-not (Test-Path "..\.env")) {
    Write-Host "ОШИБКА: Файл .env не найден!" -ForegroundColor Red
    Write-Host "Скопируйте env_template.txt в .env и заполните необходимые переменные." -ForegroundColor Yellow
    exit 1
}

# Проверка миграций
Write-Host "`n[1/4] Проверка миграций..." -ForegroundColor Cyan
python manage.py migrate --check 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Применяю миграции..." -ForegroundColor Yellow
    python manage.py migrate
}

# Проверка суперпользователя
Write-Host "[2/4] Проверка суперпользователя..." -ForegroundColor Cyan
$superuser_count = python manage.py shell -c "from django.contrib.auth import get_user_model; print(get_user_model().objects.filter(is_superuser=True).count())" 2>&1 | Select-Object -Last 1
if ($superuser_count -eq "0") {
    Write-Host "Суперпользователь не найден. Создайте его командой:" -ForegroundColor Yellow
    Write-Host "  python manage.py createsuperuser" -ForegroundColor White
    Write-Host "`nПродолжить без суперпользователя? (y/n): " -NoNewline -ForegroundColor Yellow
    $response = Read-Host
    if ($response -ne "y") {
        exit 0
    }
}

# Проверка Redis (опционально)
Write-Host "[3/4] Проверка Redis..." -ForegroundColor Cyan
try {
    $redis_test = python -c "import redis; r=redis.Redis.from_url('redis://localhost:6379/0'); r.ping(); print('OK')" 2>&1
    if ($redis_test -match "OK") {
        Write-Host "Redis доступен" -ForegroundColor Green
    } else {
        Write-Host "Redis недоступен. Celery worker может не работать." -ForegroundColor Yellow
        Write-Host "Установите Redis или используйте SQLite брокер." -ForegroundColor Yellow
    }
} catch {
    Write-Host "Redis недоступен. Celery worker может не работать." -ForegroundColor Yellow
}

# Запуск сервера
Write-Host "[4/4] Запуск Django сервера..." -ForegroundColor Cyan
Write-Host "`n=== Сервер запущен ===" -ForegroundColor Green
Write-Host "Admin: http://localhost:8000/admin/" -ForegroundColor White
Write-Host "API Docs: http://localhost:8000/api/v1/docs/" -ForegroundColor White
Write-Host "`nДля остановки нажмите Ctrl+C`n" -ForegroundColor Yellow

python manage.py runserver 0.0.0.0:8000
