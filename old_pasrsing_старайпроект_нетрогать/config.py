"""
Конфигурационный файл для Synergy LMS Parser
Централизованное управление настройками проекта
"""

import os
from dataclasses import dataclass
from typing import Optional

@dataclass
class ParserConfig:
    """Конфигурация парсера"""

    # Основные настройки
    base_url: str = "https://lms.synergy.ru"
    BASE_URL: str = "https://lms.synergy.ru"
    MAX_WORKERS: int = 5
    REQUEST_TIMEOUT: int = 30
    PAGE_LOAD_TIMEOUT: int = 15
    IMPLICIT_WAIT: int = 5
    
    # Настройки браузера
    HEADLESS_MODE: bool = False  # Отключаем headless для работы с камерой
    DISABLE_IMAGES: bool = True
    DISABLE_CSS: bool = True
    DISABLE_EXTENSIONS: bool = True
    
    # Настройки логирования
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "synergy_parser.log"
    LOG_FORMAT: str = "%(asctime)s - %(levelname)s - %(message)s"
    
    # Настройки скачивания
    DOWNLOAD_FOLDER: str = "downloaded_materials"
    CHUNK_SIZE: int = 8192
    DOWNLOAD_TIMEOUT: int = 120
    
    # Настройки экспорта
    EXPORT_FORMAT: str = "json"
    EXPORT_ENCODING: str = "utf-8"
    
    # Настройки повторных попыток
    MAX_RETRIES: int = 3
    RETRY_DELAY: float = 0.3
    
    # Настройки сессии
    USER_AGENT: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    
    def __post_init__(self):
        """Инициализация после создания объекта"""
        # Создаем необходимые директории
        os.makedirs(self.DOWNLOAD_FOLDER, exist_ok=True)
        os.makedirs("logs", exist_ok=True)
        os.makedirs("chrome_sessions", exist_ok=True)

@dataclass
class Credentials:
    """Учетные данные для авторизации"""
    username: str = "Yulia_wer@mail.ru"
    password: str = "Gcb[jkjubz1"
    
    def validate(self) -> bool:
        """Проверка корректности учетных данных"""
        return bool(self.username and self.password)

class BrowserOptions:
    """Настройки браузера"""

    @staticmethod
    def get_chrome_options(config: Optional[ParserConfig] = None):
        """Получение опций для Chrome"""
        from selenium.webdriver.chrome.options import Options as ChromeOptions

        if config is None:
            config = parser_config

        options = ChromeOptions()

        if config.HEADLESS_MODE:
            options.add_argument("--headless")

        arguments = [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-extensions",
            "--disable-plugins",
            "--disable-background-networking",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
            "--disable-backgrounding-occluded-windows",
            "--disable-client-side-phishing-detection",
            "--disable-sync",
            "--disable-translate",
            "--hide-scrollbars",
            "--mute-audio",
            "--no-first-run",
            "--safebrowsing-disable-auto-update",
            "--ignore-certificate-errors",
            "--ignore-ssl-errors",
            "--disable-web-security",
            "--allow-running-insecure-content",
            # Автоматическое разрешение доступа к камере/микрофону
            "--use-fake-ui-for-media-stream",
            "--use-fake-device-for-media-stream",
            "--disable-logging",
            "--disable-default-apps",
            f"user-agent={config.USER_AGENT}"
        ]

        for arg in arguments:
            options.add_argument(arg)

        # Добавляем preferences
        prefs = BrowserOptions.get_chrome_prefs(config)
        options.add_experimental_option("prefs", prefs)

        # Добавляем user data dir для сохранения сессии
        user_data_dir = os.path.join(os.getcwd(), "chrome_sessions", "web_automation_session")
        os.makedirs(user_data_dir, exist_ok=True)
        options.add_argument(f"--user-data-dir={user_data_dir}")

        return options

    @staticmethod
    def get_chrome_prefs(config: Optional[ParserConfig] = None) -> dict:
        """Получение настроек Chrome"""
        if config is None:
            config = parser_config

        prefs = {
            "profile.managed_default_content_settings.images": 2 if config.DISABLE_IMAGES else 1,
            "profile.default_content_setting_values.notifications": 2,
            "profile.managed_default_content_settings.stylesheets": 2 if config.DISABLE_CSS else 1,
            "profile.managed_default_content_settings.cookies": 1,
            "profile.managed_default_content_settings.javascript": 1,
            "profile.managed_default_content_settings.plugins": 1,
            "profile.managed_default_content_settings.popups": 2,
            "profile.managed_default_content_settings.geolocation": 2,
            # Разрешаем доступ к камере и микрофону
            "profile.managed_default_content_settings.media_stream": 1,
            "profile.managed_default_content_settings.media_stream_mic": 1,
            "profile.managed_default_content_settings.media_stream_camera": 1,
            # Автоматическое разрешение доступа к медиа
            "profile.default_content_setting_values.media_stream": 1,
            "profile.default_content_setting_values.media_stream_mic": 1,
            "profile.default_content_setting_values.media_stream_camera": 1,
            # Дополнительные оптимизации для скорости
            "profile.default_content_settings.popups": 0,
            "profile.managed_default_content_settings.protocol_handlers": 2,
            "profile.managed_default_content_settings.ppapi_broker": 2,
            "profile.managed_default_content_settings.automatic_downloads": 1,
            "profile.managed_default_content_settings.mixed_script": 1,
        }
        
        return prefs

# Глобальные экземпляры конфигурации должны создаваться ПОСЛЕ определения классов
parser_config = None
credentials = None

def _init_globals():
    """Инициализация глобальных переменных"""
    global parser_config, credentials
    if parser_config is None:
        parser_config = ParserConfig()
    if credentials is None:
        credentials = Credentials()

# Инициализация при импорте
_init_globals()

# Функции для работы с конфигурацией
def get_config() -> ParserConfig:
    """Получение конфигурации парсера"""
    _init_globals()
    return parser_config

def get_credentials() -> Credentials:
    """Получение учетных данных"""
    _init_globals()
    return credentials

def update_config(**kwargs):
    """Обновление конфигурации"""
    for key, value in kwargs.items():
        if hasattr(parser_config, key):
            setattr(parser_config, key, value)

def validate_config() -> bool:
    """Проверка корректности конфигурации"""
    return credentials.validate()
