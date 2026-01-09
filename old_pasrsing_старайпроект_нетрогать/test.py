import json
import logging
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse, parse_qs
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import re
import os
import concurrent.futures

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.action_chains import ActionChains
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from tqdm import tqdm

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('synergy_parser.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def watch_video_simulation(video_url: str, duration: int, material_name: str, course_name: str, simulate_watching: bool = True):
    """
    Выполняется в фоновом потоке. Симулирует просмотр видео.
    """
    thread_name = f"Поток для '{material_name}'"
    try:
        logger.info(f"[{thread_name}] Начало фоновой задачи: симуляция просмотра.")
        
        # --- Опциональная логика симуляции просмотра ---
        if simulate_watching and duration > 0:
            logger.info(f"[{thread_name}] 🎬 Симулируем просмотр видео в течение {duration} секунд...")
            
            # Прогресс-бар для симуляции просмотра
            with tqdm(
                desc=f"[{thread_name}] Просмотр {material_name}",
                total=duration,
                unit='с',
                leave=False
            ) as watch_bar:
                for second in range(duration):
                    time.sleep(1)
                    watch_bar.update(1)
            
            logger.info(f"[{thread_name}] ✅ Симуляция просмотра для '{material_name}' завершена.")
        elif not simulate_watching:
            logger.info(f"[{thread_name}] ⏭️ Пропускаем симуляцию просмотра для '{material_name}'")
        
        return {'status': 'Success', 'material': material_name, 'watched': simulate_watching}

    except Exception as e:
        logger.error(f"[{thread_name}] ❌ Ошибка в фоновой задаче для '{material_name}': {e}")
        return {'status': 'Failed', 'material': material_name, 'error': str(e)}

@dataclass
class MaterialInfo:
    """Класс для хранения информации о материале"""
    name: str
    url: Optional[str]
    viewing_time: Optional[str] = None
    progress: Optional[str] = None
    is_blocked: bool = False
    level: int = 0
    data_index: Optional[str] = None
    type: str = 'material'
    timestamp: Optional[str] = None
    completion_status: Optional[str] = None
    test_results: Optional[dict] = None
    is_completed: bool = False

    def to_dict(self) -> Dict:
        result = asdict(self)
        # Убеждаемся, что test_results сериализуется правильно
        if self.test_results:
            result['test_results'] = self.test_results
        return result

@dataclass
class CourseInfo:
    """Класс для хранения информации о курсе"""
    name: str
    url: str
    control_type: str
    status: str
    materials_count: int = 0
    total_time: str = "00:00:00"
    completion_percentage: float = 0.0

class SynergyLMSOptimizedParser:
    def __init__(self, max_workers: int = 3, simulate_watching: bool = True, session_name: str = "main"):
        self.base_url = "https://lms.synergy.ru"
        self.credentials = {
            'username': 'Yulia_wer@mail.ru',
            'password': 'Gcb[jkjubz1'
        }
        self.max_workers = max_workers
        self.session = None
        self.driver = None
        self.wait = None
        self.cookies = None
        
        # Настройки режима работы
        self.simulate_watching = simulate_watching  # Симулировать ли просмотр видео
        
        # Настройки постоянной сессии
        self.session_name = session_name
        self.session_dir = os.path.abspath(os.path.join("chrome_sessions", session_name))
        self.is_authenticated = False
        
        # Создаем папку для сессии если её нет
        os.makedirs(self.session_dir, exist_ok=True)

        # Инициализация HTTP сессии с повторными попытками
        self._setup_session()

    def _setup_session(self):
        """Настройка HTTP сессии для быстрых запросов"""
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.3,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        # Заголовки для имитации браузера
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })

    def _setup_driver(self, force_new=False):
        """Настройка Selenium драйвера с поддержкой постоянной сессии"""
        if self.driver is None or force_new:
            if self.driver:
                try:
                    self.driver.quit()
                except:
                    pass
            
            options = webdriver.ChromeOptions()
            
            # Настройки для постоянной сессии
            options.add_argument(f"--user-data-dir={self.session_dir}")
            options.add_argument("--no-first-run")
            options.add_argument("--no-default-browser-check")
            options.add_argument("--disable-background-timer-throttling")
            options.add_argument("--disable-backgrounding-occluded-windows")
            options.add_argument("--disable-renderer-backgrounding")
            options.add_argument("--disable-features=TranslateUI")
            options.add_argument("--disable-ipc-flooding-protection")
            
            # Отключаем headless режим для лучшей совместимости с сессиями
            # options.add_argument("--headless")
            
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--disable-images")
            options.add_argument("--disable-extensions")
            options.add_argument("--disable-plugins")
            options.add_argument("--disable-background-networking")
            options.add_argument("--disable-background-timer-throttling")
            options.add_argument("--disable-renderer-backgrounding")
            options.add_argument("--disable-backgrounding-occluded-windows")
            options.add_argument("--disable-client-side-phishing-detection")
            options.add_argument("--disable-sync")
            options.add_argument("--disable-translate")
            options.add_argument("--hide-scrollbars")
            options.add_argument("--mute-audio")
            options.add_argument("--safebrowsing-disable-auto-update")
            options.add_argument("--ignore-certificate-errors")
            options.add_argument("--ignore-ssl-errors")
            options.add_argument("--ignore-certificate-errors-spki-list")
            options.add_argument("--ignore-certificate-errors-ssl-errors")
            options.add_argument("--disable-web-security")
            options.add_argument("--allow-running-insecure-content")
            
            # Автоматическое разрешение доступа к камере/микрофону
            options.add_argument("--use-fake-ui-for-media-stream")
            options.add_argument("--use-fake-device-for-media-stream")

            # Отключаем загрузку изображений и CSS для максимальной скорости
            prefs = {
                "profile.managed_default_content_settings.images": 2,
                "profile.default_content_setting_values.notifications": 2,
                "profile.managed_default_content_settings.stylesheets": 2,
                "profile.managed_default_content_settings.cookies": 1,
                "profile.managed_default_content_settings.javascript": 1,
                "profile.managed_default_content_settings.plugins": 1,
                "profile.managed_default_content_settings.popups": 2,
                "profile.managed_default_content_settings.geolocation": 2,
                # Разрешаем доступ к камере и микрофону
                "profile.managed_default_content_settings.media_stream": 1,
                "profile.managed_default_content_settings.media_stream_mic": 1,
                "profile.managed_default_content_settings.media_stream_camera": 1,
                "profile.managed_default_content_settings.protocol_handlers": 2,
                "profile.managed_default_content_settings.ppapi_broker": 2,
                "profile.managed_default_content_settings.automatic_downloads": 2,
                "profile.managed_default_content_settings.mixed_script": 2,
            }
            options.add_experimental_option("prefs", prefs)

            # Исправляем путь к ChromeDriver
            chromedriver_path = ChromeDriverManager().install()
            if chromedriver_path.endswith('THIRD_PARTY_NOTICES.chromedriver'):
                # Заменяем на правильный путь к chromedriver.exe
                chromedriver_path = chromedriver_path.replace('THIRD_PARTY_NOTICES.chromedriver', 'chromedriver.exe')
            
            self.driver = webdriver.Chrome(
                service=ChromeService(chromedriver_path),
                options=options
            )
            self.driver.set_page_load_timeout(10)  # Уменьшили с 15 до 10
            self.driver.implicitly_wait(3)  # Уменьшили с 5 до 3
            self.wait = WebDriverWait(self.driver, 5)  # Уменьшили с 10 до 5

    def close(self):
        """Закрытие ресурсов (но НЕ закрываем браузер для сохранения сессии)"""
        if self.session:
            self.session.close()
        # НЕ закрываем драйвер, чтобы сохранить сессию
        # if self.driver:
        #     self.driver.quit()
        #     self.driver = None

    def force_close(self):
        """Принудительное закрытие браузера"""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None

    def login(self) -> bool:
        """Быстрая авторизация без лишних проверок"""
        try:
            logger.info("Начинаем быструю авторизацию...")
            self._setup_driver()

            # Переходим на главную страницу
            self.driver.get(self.base_url)
            time.sleep(1)  # Минимальное ожидание
            
            # Быстрая проверка авторизации по URL
            current_url = self.driver.current_url
            if "lms.synergy.ru" in current_url and "/student/" in current_url:
                logger.info("Уже авторизованы - находимся на странице студента")
                self.is_authenticated = True
                self.cookies = self.driver.get_cookies()
                self._update_session_cookies()
                return True

            # Быстрая авторизация без ожидания поп-апа
            logger.info("Выполняем быструю авторизацию...")

            # Сразу ищем форму входа
            try:
                # Пытаемся найти форму входа напрямую
                username_input = self.wait.until(EC.visibility_of_element_located((By.ID, 'popupUsername')))
                username_input.clear()
                username_input.send_keys(self.credentials['username'])

                password_input = self.wait.until(EC.visibility_of_element_located((By.ID, 'popupPassword')))
                password_input.clear()
                password_input.send_keys(self.credentials['password'])

                login_button = self.wait.until(EC.element_to_be_clickable((By.ID, 'popupLoginBtn')))
                login_button.click()
                
            except TimeoutException:
                # Если форма не найдена, ищем кнопку входа и кликаем
                try:
                    login_button_popup = self.driver.find_element(By.XPATH, "//a[contains(text(), 'Войти')]")
                    login_button_popup.click()
                    time.sleep(1)
                    
                    username_input = self.wait.until(EC.visibility_of_element_located((By.ID, 'popupUsername')))
                    username_input.clear()
                    username_input.send_keys(self.credentials['username'])

                    password_input = self.wait.until(EC.visibility_of_element_located((By.ID, 'popupPassword')))
                    password_input.clear()
                    password_input.send_keys(self.credentials['password'])

                    login_button = self.wait.until(EC.element_to_be_clickable((By.ID, 'popupLoginBtn')))
                    login_button.click()
                except Exception as e:
                    logger.error(f"Ошибка при поиске формы входа: {e}")
                    return False

            # Быстрая проверка успешной авторизации
            time.sleep(2)  # Минимальное ожидание после входа
            
            # Проверяем по URL
            current_url = self.driver.current_url
            if "lms.synergy.ru" in current_url and "/student/" in current_url:
                self.is_authenticated = True
                self.cookies = self.driver.get_cookies()
                self._update_session_cookies()
                logger.info("Авторизация прошла успешно")
                return True
            
            # Дополнительная проверка по элементу user-name
            try:
                user_name_div = self.driver.find_element(By.CLASS_NAME, 'user-name')
                if user_name_div.text.strip():
                    self.is_authenticated = True
                    self.cookies = self.driver.get_cookies()
                    self._update_session_cookies()
                    logger.info(f"Авторизация прошла успешно: {user_name_div.text.strip()}")
                    return True
            except:
                pass

            logger.error("Не удалось авторизоваться")
            self.is_authenticated = False
            return False

        except Exception as e:
            logger.error(f"Ошибка во время авторизации: {str(e)}")
            self.is_authenticated = False
            return False

    def ensure_authenticated(self) -> bool:
        """Быстрая проверка и восстановление авторизации"""
        if not self.driver:
            self._setup_driver()
        
        try:
            # Быстрая проверка по URL
            current_url = self.driver.current_url
            
            # Если мы не на главной странице, переходим туда
            if "lms.synergy.ru" not in current_url:
                self.driver.get(self.base_url)
                time.sleep(1)  # Уменьшили время ожидания
            
            # Быстрая проверка авторизации по URL
            if "lms.synergy.ru" in current_url and "/student/" in current_url:
                self.is_authenticated = True
                self.cookies = self.driver.get_cookies()
                self._update_session_cookies()
                return True
            
            # Быстрая проверка по элементу user-name
            try:
                user_name_div = self.driver.find_element(By.CLASS_NAME, 'user-name')
                if user_name_div.text.strip():
                    self.is_authenticated = True
                    self.cookies = self.driver.get_cookies()
                    self._update_session_cookies()
                    return True
            except:
                pass
            
            # Если не авторизованы, выполняем быструю авторизацию
            logger.info("Сессия истекла, выполняем быструю авторизацию...")
            return self.login()
                
        except Exception as e:
            logger.error(f"Ошибка при проверке авторизации: {e}")
            return self.login()

    def _update_session_cookies(self):
        """Обновление cookies в HTTP сессии"""
        if self.cookies:
            for cookie in self.cookies:
                self.session.cookies.set(cookie['name'], cookie['value'])

    def is_logged_in(self) -> bool:
        """Быстрая проверка авторизации"""
        try:
            # Сначала быстрая проверка по URL
            current_url = self.driver.current_url
            if "lms.synergy.ru" in current_url and "/student/" in current_url:
                logger.info("Находимся на странице студента - авторизованы")
                return True
            
            # Быстрая проверка по элементу user-name без ожидания
            try:
                user_name_div = self.driver.find_element(By.CLASS_NAME, 'user-name')
                if user_name_div.text.strip():
                    logger.info(f"Авторизован как: {user_name_div.text.strip()}")
                    return True
            except:
                pass
            
            # Проверяем наличие кнопки входа
            try:
                login_button = self.driver.find_element(By.XPATH, "//a[contains(text(), 'Войти')]")
                logger.info("Найдена кнопка входа - не авторизованы")
                return False
            except:
                pass
            
            logger.info("Не на странице студента - не авторизованы")
            return False
        except Exception as e:
            logger.error(f"Ошибка при проверке авторизации: {e}")
            return False

    def _parse_time_duration(self, time_str: str) -> timedelta:
        """Парсинг времени в формате HH:MM:SS в timedelta"""
        try:
            if not time_str or time_str == "None":
                return timedelta(0)

            # Убираем лишние символы и приводим к стандартному формату
            clean_time = re.sub(r'[^\d:]', '', time_str)
            parts = clean_time.split(':')

            if len(parts) == 3:
                hours, minutes, seconds = map(int, parts)
                return timedelta(hours=hours, minutes=minutes, seconds=seconds)
            elif len(parts) == 2:
                minutes, seconds = map(int, parts)
                return timedelta(minutes=minutes, seconds=seconds)
            else:
                return timedelta(0)
        except:
            return timedelta(0)

    def _format_timedelta(self, td: timedelta) -> str:
        """Форматирование timedelta в строку HH:MM:SS"""
        total_seconds = int(td.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def _parse_duration_to_seconds(self, duration_str: str) -> int:
        """Парсит строку времени (ЧЧ:ММ:СС или ММ:СС) в секунды."""
        parts = duration_str.strip().split(':')
        seconds = 0
        try:
            if len(parts) == 3:  # HH:MM:SS
                seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 2:  # MM:SS
                seconds = int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 1: # SS
                seconds = int(parts[0])
            return seconds
        except (ValueError, IndexError):
            logger.error(f"Не удалось распознать длительность: '{duration_str}'")
            return 0

    def confirm_material_study(self) -> bool:
        """Подтверждение изучения материала"""
        try:
            confirm_button = self.wait.until(EC.element_to_be_clickable((By.ID, 'exitBtn')))
            if confirm_button and confirm_button.is_displayed():
                logger.info("Подтверждаем изучение материала...")
                self.driver.execute_script("arguments[0].click();", confirm_button)
                time.sleep(2)
                logger.info("Материал подтвержден")
                return True
            return False
        except Exception:
            logger.info("Кнопка подтверждения не найдена или не требуется.")
            return False

    def get_material_info_fast(self, material_url: str, use_selenium: bool = False) -> MaterialInfo:
        """
        Получение информации о материале.
        Использует быстрый HTTP запрос, если use_selenium=False.
        Использует Selenium для полной загрузки страницы, если use_selenium=True.
        """
        try:
            logger.debug(f"Получаем информацию о материале: {material_url} (Selenium: {use_selenium})")

            if not use_selenium:
                # Быстрый способ через HTTP, может не найти динамический контент
                try:
                    response = self.session.get(material_url, timeout=10)
                    if response.status_code == 200:
                        soup = BeautifulSoup(response.content, 'html.parser')
                        # Эта часть может не найти время, если оно грузится JS
                        viewing_time = soup.find('b', id='itemTotalTime')
                        progress = soup.find('div', class_='interest')
                        status_button = soup.find('a', id='exitBtn')
                        
                        return MaterialInfo(
                            name="",
                            url=material_url,
                            viewing_time=viewing_time.get_text().strip() if viewing_time else None,
                            progress=progress.get_text().strip() if progress else None,
                            completion_status=status_button.get_text().strip() if status_button else None,
                            timestamp=datetime.now().isoformat(),
                            is_completed=False
                        )
                except requests.exceptions.RequestException as e:
                    logger.warning(f"HTTP запрос для {material_url} не удался: {e}. Переключаемся на Selenium.")
            
            # Надежный, но медленный способ через Selenium
            self._setup_driver()
            self.driver.get(material_url)
            
            viewing_time = None
            progress = None
            completion_status = None

            try:
                # Явное ожидание появления элемента с временем
                time_element = self.wait.until(
                    EC.presence_of_element_located((By.ID, 'itemTotalTime'))
                )
                viewing_time = time_element.text.strip()
            except TimeoutException:
                logger.warning(f"Не удалось найти 'itemTotalTime' для {material_url} даже с Selenium.")

            # Поиск остальных элементов без жесткого ожидания
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            progress_element = soup.find('div', class_='interest')
            if progress_element:
                progress = progress_element.get_text().strip()
            
            status_button = soup.find('a', id='exitBtn')
            if status_button:
                completion_status = status_button.get_text().strip()

            return MaterialInfo(
                name="",
                url=material_url,
                viewing_time=viewing_time,
                progress=progress,
                completion_status=completion_status,
                timestamp=datetime.now().isoformat(),
                is_completed=False
            )

        except Exception as e:
            logger.error(f"Критическая ошибка при получении информации о материале {material_url}: {str(e)}")
            return MaterialInfo(name="", url=material_url, is_completed=False)

    def determine_material_type(self, material_name: str, material_url: str, page_content: str = "") -> str:
        """Определение типа материала на основе названия, URL и содержимого страницы"""
        material_name_lower = material_name.lower()
        material_url_lower = material_url.lower()
        
        # Определяем тесты
        if any(keyword in material_name_lower for keyword in ['тест', 'test', 'аттестация', 'экзамен']):
            return 'test'
        
        # Определяем по URL
        if '/assessments/' in material_url_lower or '/event/view/' in material_url_lower:
            return 'test'
        
        # Определяем по содержимому страницы
        if page_content:
            if any(keyword in page_content.lower() for keyword in ['тест', 'вопрос', 'ответ', 'player-discipline']):
                return 'test'
            elif any(keyword in page_content.lower() for keyword in ['video', 'player', 'mp4', 'webm']):
                return 'video'
            elif any(keyword in page_content.lower() for keyword in ['pdf', 'document']):
                return 'pdf'
        
        # Определяем по расширению файла
        if any(ext in material_url_lower for ext in ['.mp4', '.avi', '.mov', '.wmv']):
            return 'video'
        elif any(ext in material_url_lower for ext in ['.pdf']):
            return 'pdf'
        elif any(ext in material_url_lower for ext in ['.doc', '.docx', '.txt']):
            return 'document'
        
        # Определяем по названию
        if any(keyword in material_name_lower for keyword in ['видео', 'лекция', 'урок']):
            return 'video'
        elif any(keyword in material_name_lower for keyword in ['документ', 'материал', 'презентация']):
            return 'document'
        
        return 'unknown'

    def get_test_results(self, test_url: str) -> dict:
        """Получение результатов теста"""
        try:
            # Преобразуем URL теста в URL результатов
            results_url = test_url.replace('/event/view/', '/assessments/view/')
            
            # Загружаем страницу результатов
            self.driver.get(results_url)
            self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
            results = {}
            
            # Ищем таблицу с результатами
            table = soup.find('table', class_='table-list')
            if table:
                rows = table.find_all('tr')
                if len(rows) > 1:  # Есть данные
                    row = rows[1]  # Первая строка с данными
                    cells = row.find_all('td')
                    
                    if len(cells) >= 5:
                        results['attempts'] = cells[0].get_text(strip=True)
                        results['start_time'] = cells[1].get_text(strip=True)
                        results['duration'] = cells[2].get_text(strip=True)
                        results['score'] = cells[3].get_text(strip=True)
                        results['correct_answers'] = cells[4].get_text(strip=True)
            
            return results
            
        except Exception as e:
            logger.error(f"Ошибка при получении результатов теста {test_url}: {str(e)}")
            return {}

    def get_course_materials_optimized(self, course_url: str, include_viewing_time: bool = False) -> Tuple[List[MaterialInfo], str, str]:
        """Оптимизированное получение материалов курса и названия курса"""
        try:
            logger.info(f"Получаем материалы курса: {course_url} (с временем: {include_viewing_time})")
            
            # Проверяем и восстанавливаем авторизацию если нужно
            if not self.ensure_authenticated():
                logger.error("Не удалось авторизоваться")
                return [], "00:00:00", "Unknown Course"
            
            self.driver.get(course_url)
            self.wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "ul.sidebar")))

            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
            course_name_tag = soup.select_one("h1.m-0")
            course_name = course_name_tag.get_text(strip=True) if course_name_tag else "Unknown Course"

            materials = []
            total_time = timedelta(0)

            # Сначала просто собираем все материалы без времени
            def parse_structure(element, level=0, path_prefix=""):
                result = []
                for li in element.find_all('li', recursive=False):
                    div = li.find('div', recursive=False)
                    if not div: continue
                    link = div.find('a', recursive=False)
                    if not link: continue
                    title = ' '.join(span.get_text(strip=True) for span in link.find_all('span')).strip()
                    current_path = os.path.join(path_prefix, self._sanitize_filename(title))
                    nested_ul = li.find('ul', recursive=False)
                    if nested_ul:
                        result.extend(parse_structure(nested_ul, level + 1, current_path))
                    elif 'href' in link.attrs:
                        material_url = urljoin(self.base_url, link['href'])
                        
                        # Определяем тип материала
                        material_type = self.determine_material_type(title, material_url)
                        
                        # Создаем объект материала
                        material = MaterialInfo(
                            name=title, 
                            url=material_url, 
                            level=level,
                            data_index=li.get('data-index'), 
                            is_blocked=False, 
                            type=material_type,
                            is_completed=False
                        )
                        
                        # Если это тест, пытаемся получить результаты
                        if material_type == 'test':
                            try:
                                test_results = self.get_test_results(material_url)
                                if test_results:
                                    material.test_results = test_results
                                    material.is_completed = True
                            except Exception as e:
                                logger.warning(f"Не удалось получить результаты теста {title}: {e}")
                        
                        result.append(material)
                    else:
                        result.append(MaterialInfo(
                            name=f"{title} [ЗАБЛОКИРОВАНО]", 
                            url=None, 
                            level=level,
                            data_index=li.get('data-index'), 
                            is_blocked=True, 
                            type='unknown',
                            is_completed=False
                        ))
                return result

            sidebar_ul = soup.select_one('ul.sidebar')
            if sidebar_ul:
                materials = parse_structure(sidebar_ul)

            # Если нужно время, проходимся по материалам и получаем его
            if include_viewing_time:
                logger.info(f"Начинаем сбор времени для {len(materials)} материалов...")
                for material in tqdm(materials, desc="Сбор времени просмотра"):
                    if material.url and not material.is_blocked and material.type != 'test':
                        # Принудительно используем Selenium для надежности
                        info = self.get_material_info_fast(material.url, use_selenium=True)
                        material.viewing_time = info.viewing_time
                        material.progress = info.progress
                        material.completion_status = info.completion_status
                        if material.viewing_time:
                            total_time += self._parse_time_duration(material.viewing_time)
            
            total_time_str = self._format_timedelta(total_time)
            return materials, total_time_str, course_name

        except Exception as e:
            logger.error(f"Ошибка при получении материалов курса: {str(e)}")
            return [], "00:00:00", "Unknown Course"

    def get_course_materials_parallel(self, course_url: str) -> Tuple[List[MaterialInfo], str, str]:
        """Параллельное получение информации о материалах курса"""
        try:
            logger.info(f"Получаем материалы курса параллельно: {course_url}")

            # Проверяем и восстанавливаем авторизацию если нужно
            if not self.ensure_authenticated():
                logger.error("Не удалось авторизоваться")
                return [], "00:00:00", "Unknown Course"

            # Сначала получаем список материалов и название курса
            materials, _, course_name = self.get_course_materials_optimized(course_url, include_viewing_time=False)

            # Фильтруем только незаблокированные материалы
            unlocked_materials = [m for m in materials if not m.is_blocked and m.url]

            if not unlocked_materials:
                return materials, "00:00:00", course_name

            # Параллельно получаем информацию о времени просмотра
            def get_material_time(material):
                try:
                    # Принудительно используем Selenium для надежности
                    info = self.get_material_info_fast(material.url, use_selenium=True)
                    material.viewing_time = info.viewing_time
                    material.progress = info.progress
                    material.completion_status = info.completion_status
                    return material
                except Exception as e:
                    logger.error(f"Ошибка при получении времени для {material.url}: {str(e)}")
                    return material

            # Используем ThreadPoolExecutor для параллельной обработки
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                logger.info(f"Обрабатываем {len(unlocked_materials)} материалов в {self.max_workers} потоках")
                updated_materials = list(tqdm(executor.map(get_material_time, unlocked_materials), total=len(unlocked_materials), desc="Получение информации"))


            # Обновляем исходный список материалов
            material_dict = {m.url: m for m in updated_materials}
            for i, material in enumerate(materials):
                if material.url in material_dict:
                    materials[i] = material_dict[material.url]

            # Подсчитываем общее время
            total_time = timedelta(0)
            for material in materials:
                if material.viewing_time:
                    total_time += self._parse_time_duration(material.viewing_time)

            total_time_str = self._format_timedelta(total_time)
            return materials, total_time_str, course_name

        except Exception as e:
            logger.error(f"Ошибка при параллельном получении материалов: {str(e)}")
            return [], "00:00:00", "Unknown Course"

    def get_all_data_optimized(self) -> Dict:
        """Оптимизированное получение всех данных"""
        try:
            logger.info("Получаем данные о семестрах и курсах...")

            # Проверяем и восстанавливаем авторизацию если нужно
            if not self.ensure_authenticated():
                logger.error("Не удалось авторизоваться")
                return {"error": "Ошибка авторизации"}

            self.driver.get(f"{self.base_url}/student/up/")
            self.wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "tbody.semester")))

            soup = BeautifulSoup(self.driver.page_source, 'html.parser')

            data = {
                "timestamp": datetime.now().isoformat(),
                "semesters": {},
                "summary": {
                    "total_semesters": 0,
                    "total_courses": 0,
                    "total_time": "00:00:00"
                }
            }

            semester_tbodies = soup.select("tbody.semester")
            total_courses = 0
            total_time = timedelta(0)

            for tbody in semester_tbodies:
                semester_num = None
                class_list = tbody.get('class', [])

                for cls in class_list:
                    if cls.startswith('s') and cls[1:].isdigit():
                        semester_num = int(cls[1:])
                        break

                if semester_num is None:
                    continue

                logger.info(f"Обрабатываем семестр {semester_num}...")

                courses = []
                discipline_rows = tbody.find_all('tr', class_='discipl')

                for row in discipline_rows:
                    try:
                        course_link = row.find('a', href=True)
                        if course_link:
                            course_name = course_link.get_text().strip()
                            course_url = urljoin(self.base_url, course_link['href'])

                            tds = row.find_all('td')
                            control_type = tds[2].get_text().strip() if len(tds) > 2 else "Неизвестно"
                            status_td = tds[3] if len(tds) > 3 else None
                            status = status_td.get_text().strip() if status_td else "Неизвестно"

                            course_info = CourseInfo(
                                name=course_name,
                                url=course_url,
                                control_type=control_type,
                                status=status
                            )

                            courses.append(course_info)

                    except Exception as e:
                        logger.error(f"Ошибка при обработке курса: {str(e)}")
                        continue

                data["semesters"][semester_num] = {
                    "courses_count": len(courses),
                    "courses": [asdict(course) for course in courses]
                }

                total_courses += len(courses)
                logger.info(f"Найдено {len(courses)} курсов в семестре {semester_num}")

            data["summary"]["total_semesters"] = len(data["semesters"])
            data["summary"]["total_courses"] = total_courses
            data["summary"]["total_time"] = self._format_timedelta(total_time)

            return data

        except Exception as e:
            logger.error(f"Ошибка при получении данных: {str(e)}")
            return {"error": str(e)}

    def export_to_json(self, data: Dict, filename: str = None):
        """Экспорт данных в JSON с автоматическим именем файла"""
        try:
            if filename is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"synergy_data_{timestamp}.json"

            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)

            logger.info(f"Данные экспортированы в файл: {filename}")
            return filename

        except Exception as e:
            logger.error(f"Ошибка при экспорте в JSON: {str(e)}")
            return None

    def get_statistics(self, data: Dict) -> Dict:
        """Получение статистики по данным"""
        try:
            stats = {
                "total_semesters": len(data.get("semesters", {})),
                "total_courses": 0,
                "courses_by_status": {},
                "courses_by_control_type": {},
                "materials_stats": {
                    "total_materials": 0,
                    "blocked_materials": 0,
                    "total_viewing_time": "00:00:00"
                }
            }

            for semester_data in data.get("semesters", {}).values():
                courses = semester_data.get("courses", [])
                stats["total_courses"] += len(courses)

                for course in courses:
                    status = course.get("status", "Неизвестно")
                    control_type = course.get("control_type", "Неизвестно")

                    stats["courses_by_status"][status] = stats["courses_by_status"].get(status, 0) + 1
                    stats["courses_by_control_type"][control_type] = stats["courses_by_control_type"].get(control_type, 0) + 1

            return stats

        except Exception as e:
            logger.error(f"Ошибка при получении статистики: {str(e)}")
            return {}

    def _sanitize_filename(self, name: str) -> str:
        """Очистка имени файла от недопустимых символов"""
        name = re.sub(r'[\r\n]', ' ', name) # Заменяем переносы строк на пробелы
        return re.sub(r'[\\/*?:"<>|]', "_", name).strip()

    def _find_and_start_video_simulation(self, material_name: str, course_name: str, executor: ThreadPoolExecutor) -> Optional[Future]:
        """
        Находит видео, отправляет задачу на симуляцию просмотра в фоновый поток,
        и возвращает объект Future этой задачи.
        """
        PLACEHOLDER_VIDEO_SRC = "synergy_in.mp4"
        
        try:
            video_players = self.driver.find_elements(By.CSS_SELECTOR, "div.video-js")
            if not video_players:
                logger.info("Интерактивные видеоплееры 'video-js' не найдены.")
                return None

            logger.info(f"Найдено {len(video_players)} видеоплееров.")
            
            for i, player in enumerate(video_players):
                logger.info(f"Обрабатываем плеер #{i + 1}...")
                try:
                    video_element = player.find_element(By.TAG_NAME, 'video')
                    initial_src = video_element.get_attribute('src') or ""
                    logger.info(f"Начальный src видео: {initial_src}")

                    final_video_url = None
                    duration_in_seconds = 0

                    if initial_src and PLACEHOLDER_VIDEO_SRC not in initial_src:
                        logger.info("URL видео уже является корректным. Используем его.")
                        final_video_url = initial_src
                    else:
                        logger.info("Ожидаем, пока большая кнопка Play станет доступной...")
                        player_id = player.get_attribute('id')
                        if not player_id:
                            raise Exception("Видео-плеер не имеет атрибута ID, не удается точно найти кнопку Play.")

                        play_button = WebDriverWait(self.driver, 15).until(
                            EC.element_to_be_clickable((By.CSS_SELECTOR, f"#{player_id} .vjs-big-play-button"))
                        )
                        
                        logger.info("Нажимаем на большую кнопку Play для получения реальной ссылки.")
                        actions = ActionChains(self.driver)
                        actions.move_to_element(play_button).click().perform()
                        
                        wait = WebDriverWait(self.driver, 30)
                        wait.until(
                            lambda d: (video_element.get_attribute('src') or "") != initial_src and \
                                      PLACEHOLDER_VIDEO_SRC not in (video_element.get_attribute('src') or "")
                        )
                        final_video_url = video_element.get_attribute('src')
                        logger.info(f"Новый URL видео получен: {final_video_url}")

                    # Получаем длительность после того, как видео загрузилось
                    try:
                        WebDriverWait(self.driver, 20).until(
                            lambda d: d.execute_script("return arguments[0].readyState;", video_element) >= 1
                        )
                        time.sleep(1) # Пауза для обновления UI
                        player_id = player.get_attribute('id')
                        duration_element = self.driver.find_element(By.CSS_SELECTOR, f"#{player_id} .vjs-duration-display")
                        duration_str = duration_element.text.strip()
                        if not duration_str or duration_str in ["-:-", "0:00", ""]:
                             duration_str = self.driver.execute_script("return arguments[0].innerText;", duration_element).strip()
                        logger.info(f"Обнаружена длительность видео: {duration_str}")
                        duration_in_seconds = self._parse_duration_to_seconds(duration_str)
                    except Exception as e_dur:
                        logger.warning(f"Не удалось получить длительность видео: {e_dur}. Ожидание будет пропущено.")

                    if final_video_url:
                        logger.info(f"Отправляем задачу на симуляцию просмотра в фоновый поток для '{material_name}'.")
                        future = executor.submit(
                            watch_video_simulation,
                            final_video_url,
                            duration_in_seconds,
                            material_name,
                            course_name,
                            self.simulate_watching
                        )
                        
                        try:
                            pause_button = player.find_element(By.CSS_SELECTOR, '.vjs-play-control.vjs-playing')
                            self.driver.execute_script("arguments[0].click();", pause_button)
                        except Exception:
                            pass
                        
                        return future # Возвращаем Future

                except Exception as e_player:
                    logger.error(f"Ошибка при интерактивной обработке плеера #{i + 1}: {e_player}")
                    continue
            return None
        except Exception as e:
            logger.error(f"Общая ошибка при поиске видео: {e}")
            return None

    def process_material(self, material: MaterialInfo, course_name: str, executor: ThreadPoolExecutor) -> Dict:
        """Обработка отдельного учебного материала с поиском в iframe."""
        results = {'processed': False, 'videos': 0, 'pdfs': 0, 'task_future': None}
        try:
            logger.info(f"Обрабатываем материал: {material.name}")
            
            # Проверяем и восстанавливаем авторизацию если нужно
            if not self.ensure_authenticated():
                logger.error("Не удалось авторизоваться")
                return results
            
            self.driver.get(material.url)
            self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            time.sleep(3)

            video_future = None
            # 1. Поиск на основной странице
            logger.info("Ищем видео на основной странице...")
            video_future = self._find_and_start_video_simulation(material.name, course_name, executor)
            
            # 2. Если не найдено, ищем в iframes
            if not video_future:
                try:
                    iframes = self.driver.find_elements(By.TAG_NAME, 'iframe')
                    if iframes:
                        logger.info(f"Видео на основной странице не найдено. Найдено {len(iframes)} iframe. Проверяем их.")
                        for index in range(len(iframes)):
                            try:
                                self.driver.switch_to.frame(index)
                                logger.info(f"Анализируем iframe #{index}...")
                                time.sleep(2)
                                video_future = self._find_and_start_video_simulation(material.name, course_name, executor)
                                if video_future:
                                    break 
                            except Exception as e_frame:
                                logger.error(f"Ошибка при обработке iframe #{index}: {e_frame}")
                            finally:
                                self.driver.switch_to.default_content()
                except Exception as e:
                    logger.error(f"Ошибка при поиске iframes: {e}")
                finally:
                    self.driver.switch_to.default_content()

            if video_future:
                logger.info(f"Видео-задача для '{material.name}' запущена.")
                results['videos'] += 1
                
                # Ждем завершения, так как это симуляция
                logger.info(f"⏳ Ожидаем завершения симуляции для '{material.name}'...")
                task_result = video_future.result() 
                logger.info(f"✅ Фоновая задача для '{material.name}' завершена со статусом: {task_result.get('status')}")
            else:
                logger.info("Видео для просмотра не найдено ни на странице, ни в iframes.")

            # --- Подтверждение изучения (выполняется в самом конце) ---
            self.driver.switch_to.default_content()
            self.confirm_material_study()
            results['processed'] = True
            return results
            
        except Exception as e:
            logger.error(f"Критическая ошибка при обработке материала {material.name}: {str(e)}")
            return results
        finally:
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass


def main():
    """Основная функция с улучшенным интерфейсом"""
    # Настройки режима работы
    print("\n" + "="*60)
    print("НАСТРОЙКИ РЕЖИМА РАБОТЫ")
    print("="*60)
    
    # Выбор режима симуляции просмотра
    while True:
        simulate_choice = input("Симулировать просмотр видео? (y/n): ").strip().lower()
        if simulate_choice in ['y', 'n']:
            simulate_watching = simulate_choice == 'y'
            break
        print("Введите 'y' или 'n'")
    
    # Выбор количества потоков
    while True:
        try:
            max_workers = int(input("Количество параллельных потоков (1-10): ").strip())
            if 1 <= max_workers <= 10:
                break
            print("Введите число от 1 до 10")
        except ValueError:
            print("Введите корректное число")
    
    print(f"\n📋 Настройки:")
    print(f"   🎬 Симуляция просмотра: {'✅ Включена' if simulate_watching else '❌ Отключена'}")
    print(f"   🔄 Параллельных потоков: {max_workers}")
    
    parser = SynergyLMSOptimizedParser(
        max_workers=max_workers,
        simulate_watching=simulate_watching
    )

    try:
        # Авторизация
        if not parser.login():
            logger.error("Не удалось авторизоваться. Выход.")
            return

        print("\n" + "="*60)
        print("ОПТИМИЗИРОВАННЫЙ ПАРСЕР SYNERGY LMS v2.1 (NO DOWNLOAD)")
        print("="*60)
        print("1. Получить все семестры и курсы (быстро)")
        print("2. Получить материалы курса (без времени просмотра)")
        print("3. Получить материалы курса с временем (медленно)")
        print("4. Получить материалы курса параллельно (оптимально)")
        print("5. Получить информацию о конкретном материале")
        print("6. Получить статистику по данным")
        print("7. Выход")
        print("="*60)

        while True:
            try:
                choice = input("\nВыберите действие (1-7): ").strip()

                if choice == '1':
                    start_time = time.time()
                    logger.info("Получение всех данных...")
                    data = parser.get_all_data_optimized()

                    if "error" not in data:
                        elapsed = time.time() - start_time
                        print(f"\n✅ Данные получены за {elapsed:.2f} секунд")
                        print(f"📊 Статистика:")
                        print(f"   Семестров: {data['summary']['total_semesters']}")
                        print(f"   Курсов: {data['summary']['total_courses']}")

                        filename = parser.export_to_json(data)
                        if filename:
                            print(f"💾 Данные сохранены в файл: {filename}")
                    else:
                        print(f"❌ Ошибка: {data['error']}")

                elif choice in ['2', '3', '4']:
                    course_url = input("Введите URL курса: ").strip()
                    if course_url:
                        start_time = time.time()
                        
                        if choice == '2':
                            materials, total_time, course_name = parser.get_course_materials_optimized(course_url, include_viewing_time=False)
                        elif choice == '3':
                             print("⚠️  Внимание: Получение времени просмотра может занять много времени")
                             materials, total_time, course_name = parser.get_course_materials_optimized(course_url, include_viewing_time=True)
                        else: # choice == '4'
                            materials, total_time, course_name = parser.get_course_materials_parallel(course_url)

                        elapsed = time.time() - start_time

                        materials_data = {
                            "course_name": course_name,
                            "course_url": course_url,
                            "timestamp": datetime.now().isoformat(),
                            "materials_count": len(materials),
                            "total_time": total_time,
                            "materials": [m.to_dict() for m in materials],
                            "processing_time": f"{elapsed:.2f}s"
                        }

                        print(f"\n✅ Получено {len(materials)} материалов для курса '{course_name}' за {elapsed:.2f} секунд")
                        if total_time != "00:00:00":
                             print(f"⏱️  Общее время просмотра: {total_time}")
                        
                        filename = parser.export_to_json(materials_data, f"materials_{parser._sanitize_filename(course_name)}.json")
                        if filename:
                            print(f"💾 Данные сохранены в файл: {filename}")
                
                elif choice == '5':
                    material_url = input("Введите URL материала: ").strip()
                    if material_url:
                        # Принудительно используем Selenium для получения полной информации
                        material_info = parser.get_material_info_fast(material_url, use_selenium=True)

                        if material_info.url:
                            print(f"\nИнформация о материале:")
                            print(f"URL: {material_info.url}")
                            print(f"Время просмотра: {material_info.viewing_time}")
                            print(f"Прогресс: {material_info.progress}")
                            print(f"Статус: {material_info.completion_status}")
                            print(f"Время получения: {material_info.timestamp}")

                            filename = parser.export_to_json(material_info.to_dict())
                            if filename:
                                print(f"💾 Информация сохранена в файл: {filename}")
                        else:
                            print(f"❌ Ошибка при получении информации.")

                elif choice == '6':
                    # Этот пункт можно расширить, чтобы он работал с загруженным JSON
                    print("Функция статистики в разработке.")
                
                elif choice == '7':
                    break

                else:
                    print("Некорректный выбор. Введите число от 1 до 7.")

            except (KeyboardInterrupt, EOFError):
                print("\nВыход...")
                break
            except Exception as e:
                logger.error(f"Произошла ошибка в главном цикле: {str(e)}")

    except Exception as e:
        logger.critical(f"Критическая ошибка: {str(e)}")
    finally:
        parser.close()


if __name__ == "__main__":
    main()
