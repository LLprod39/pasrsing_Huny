"""Модуль авторизации на LMS Synergy"""
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from config import Config
from logger import setup_logger
from gologin_manager import GologinManager

logger = setup_logger(__name__)


class AuthManager:
    """Класс для управления авторизацией"""
    
    def __init__(self, driver: webdriver.Chrome = None):
        self.driver = driver
        self.gologin = GologinManager()
        self.is_authenticated = False
    
    def create_driver(self, use_gologin: bool = True) -> webdriver.Chrome:
        """Создать WebDriver с опциональной поддержкой Gologin"""
        options = webdriver.ChromeOptions()
        
        # Проверяем наличие валидных данных Gologin
        has_gologin = (use_gologin and 
                      self.gologin.api_token and 
                      self.gologin.api_token.strip() and
                      self.gologin.api_token not in ["", "your_gologin_api_token"] and
                      self.gologin.profile_id and
                      self.gologin.profile_id.strip() and
                      self.gologin.profile_id not in ["", "your_profile_id"])
        
        if has_gologin:
            # Используем Gologin
            profile_data = self.gologin.start_profile()
            if profile_data and profile_data.get('ws_endpoint'):
                options.add_experimental_option("debuggerAddress", profile_data['ws_endpoint'])
                logger.info("Используется Gologin профиль")
            else:
                logger.warning("Не удалось подключиться к Gologin, используется обычный браузер")
                has_gologin = False
        
        if not has_gologin:
            # Обычный браузер с опциями для обхода детекции
            options.add_argument('--disable-blink-features=AutomationControlled')
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--no-sandbox')
            # Убираем признаки автоматизации
            options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

            # Как в старом проекте: авто-разрешения для камеры/микрофона (нужно для идентификации перед тестами)
            if Config.ALLOW_MEDIA_STREAM:
                options.add_argument("--use-fake-ui-for-media-stream")
                options.add_argument("--use-fake-device-for-media-stream")
                prefs = {
                    "profile.managed_default_content_settings.media_stream": 1,
                    "profile.managed_default_content_settings.media_stream_mic": 1,
                    "profile.managed_default_content_settings.media_stream_camera": 1,
                    "profile.default_content_setting_values.media_stream": 1,
                    "profile.default_content_setting_values.media_stream_mic": 1,
                    "profile.default_content_setting_values.media_stream_camera": 1,
                }
                options.add_experimental_option("prefs", prefs)
        
        try:
            driver = webdriver.Chrome(options=options)
            driver.set_page_load_timeout(Config.PAGE_LOAD_TIMEOUT)
            logger.info("WebDriver создан успешно")
            return driver
        except Exception as e:
            logger.error(f"Ошибка при создании WebDriver: {e}")
            raise
    
    def login(self) -> bool:
        """Выполнить авторизацию на сайте"""
        if not self.driver:
            self.driver = self.create_driver()
        
        try:
            logger.info(f"Открываем страницу авторизации: {Config.LOGIN_URL}")
            self.driver.get(Config.LOGIN_URL)
            
            # Ждем появления полей формы (быстрое ожидание)
            wait = WebDriverWait(self.driver, 10)
            
            # Ожидаем появления поп-апа и кликаем на кнопку входа (если есть) - без задержек
            try:
                login_button_popup = WebDriverWait(self.driver, 2).until(
                    EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), 'Войти')]"))
                )
                login_button_popup.click()
            except TimeoutException:
                pass  # Поп-ап не появился, продолжаем
            
            # Ожидаем появления формы входа и полей одновременно
            wait.until(EC.presence_of_element_located((By.ID, 'popupUsername')))
            
            # Находим поля сразу и вводим данные без задержек
            username_input = self.driver.find_element(By.ID, 'popupUsername')
            password_input = self.driver.find_element(By.ID, 'popupPassword')
            login_button = self.driver.find_element(By.ID, 'popupLoginBtn')
            
            # Вводим данные быстро
            username_input.clear()
            username_input.send_keys(Config.LOGIN)
            password_input.clear()
            password_input.send_keys(Config.PASSWORD)
            
            # Сразу нажимаем кнопку входа
            login_button.click()
            logger.info("Авторизация отправлена")
            
            # Ждем перехода на другую страницу или появления элементов после авторизации
            time.sleep(3)
            
            # Проверяем успешность авторизации
            # Если URL изменился или появились элементы личного кабинета - авторизация успешна
            current_url = self.driver.current_url
            logger.info(f"Текущий URL после авторизации: {current_url}")
            
            # Проверяем успешность авторизации по наличию элемента user-name
            try:
                user_name_div = wait.until(EC.visibility_of_element_located((By.CLASS_NAME, 'user-name')))
                logger.info(f"Авторизован как: {user_name_div.text.strip()}")
                self.is_authenticated = True
                return True
            except TimeoutException:
                # Если форма авторизации все еще видна - авторизация не удалась
                login_form = self.driver.find_elements(By.NAME, "popupUsername")
                if login_form:
                    logger.error("Авторизация не удалась. Проверьте логин и пароль.")
                    self.is_authenticated = False
                    return False
                else:
                    # Возможно авторизация прошла, но элемент user-name не найден
                    self.is_authenticated = True
                    logger.info("Авторизация успешна (элемент user-name не найден, но форма авторизации исчезла)")
                    return True
                    
        except TimeoutException as e:
            logger.error(f"Таймаут при авторизации: {e}")
            return False
        except Exception as e:
            logger.error(f"Ошибка при авторизации: {e}")
            return False
    
    def is_logged_in(self) -> bool:
        """Проверить, авторизован ли пользователь"""
        if not self.driver:
            return False
        
        try:
            # Проверяем наличие элементов авторизации
            # Если форма авторизации отсутствует - значит авторизованы
            login_form = self.driver.find_elements(By.NAME, "popupUsername")
            return len(login_form) == 0 and self.is_authenticated
        except:
            return self.is_authenticated
    
    def logout(self):
        """Выйти из системы"""
        # TODO: Реализовать выход
        pass
    
    def close(self):
        """Закрыть браузер"""
        if self.driver:
            self.driver.quit()
            logger.info("Браузер закрыт")
        
        # Останавливаем Gologin профиль если использовался
        if self.gologin.api_token:
            self.gologin.stop_profile()
