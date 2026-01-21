"""Модуль для загрузки конфигурации из .env файла"""
import os
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()


class Config:
    """Класс для хранения конфигурации"""
    
    # Данные авторизации (из .env или значения по умолчанию из старого проекта)
    LOGIN = os.getenv('LOGIN', '').strip()
    PASSWORD = os.getenv('PASSWORD', '').strip()
    
    # Если в .env пустые значения или значения по умолчанию, используем данные из старого проекта
    if not LOGIN or LOGIN in ['', 'your_email@example.com']:
        LOGIN = 'Yulia_wer@mail.ru'
    if not PASSWORD or PASSWORD in ['', 'your_password']:
        PASSWORD = 'Gcb[jkjubz1'
    
    # Gologin настройки
    GOLOGIN_API_TOKEN = os.getenv('GOLOGIN_API_TOKEN', '')
    GOLOGIN_PROFILE_ID = os.getenv('GOLOGIN_PROFILE_ID', '')
    GOLOGIN_PROFILE_PATH = os.getenv('GOLOGIN_PROFILE_PATH', '')
    
    # Настройки парсера
    MIN_VIEW_TIME = int(os.getenv('MIN_VIEW_TIME', '30'))
    SCROLL_DELAY = float(os.getenv('SCROLL_DELAY', '2'))
    PAGE_LOAD_TIMEOUT = int(os.getenv('PAGE_LOAD_TIMEOUT', '30'))

    # Медиа-разрешения (нужно для идентификации/камеры перед тестами)
    # В старом проекте это было включено по умолчанию.
    ALLOW_MEDIA_STREAM = os.getenv("ALLOW_MEDIA_STREAM", "1").strip() not in ["0", "false", "False", "no", "NO"]
    
    # Настройки тестов
    TEST_STRATEGY = os.getenv('TEST_STRATEGY', 'random')  # random, correct, ai
    MAX_TEST_ATTEMPTS = int(os.getenv('MAX_TEST_ATTEMPTS', '3'))

    # AI (для TEST_STRATEGY=ai)
    AI_PROVIDER = os.getenv("AI_PROVIDER", "grok")  # grok, gemini, ...
    AI_TIMEOUT_SECONDS = int(os.getenv("AI_TIMEOUT_SECONDS", "60"))

    GROK_API_KEY = os.getenv("GROK_API_KEY", "").strip()
    GROK_MODEL = os.getenv("GROK_MODEL", "grok-4-1-fast-reasoning").strip()
    GROK_BASE_URL = os.getenv("GROK_BASE_URL", "https://api.x.ai/v1").strip()
    
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview").strip()
    
    # Логирование
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FILE = os.getenv('LOG_FILE', 'parser.log')
    
    # URL сайта
    BASE_URL = 'https://lms.synergy.ru'
    LOGIN_URL = f'{BASE_URL}/'
    LOGIN_POST_URL = f'{BASE_URL}/user/login'
    
    @classmethod
    def validate(cls):
        """Проверка наличия обязательных параметров"""
        if not cls.LOGIN or not cls.PASSWORD:
            raise ValueError("LOGIN и PASSWORD должны быть указаны в .env файле")
        
        if not cls.GOLOGIN_API_TOKEN and not cls.GOLOGIN_PROFILE_PATH:
            print("Предупреждение: Gologin не настроен. Будет использован обычный браузер.")
