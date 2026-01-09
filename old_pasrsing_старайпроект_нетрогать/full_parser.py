"""
Полный парсер Synergy LMS - парсит все семестры, курсы и материалы за один раз
"""
import os
import re
import json
import logging
import time
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from bs4 import BeautifulSoup
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import ParserConfig, Credentials, BrowserOptions

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class FullSynergyParser:
    """Полный парсер Synergy LMS - парсит все данные за один раз"""
    
    def __init__(self):
        self.config = ParserConfig()
        self.credentials = Credentials()
        self.driver: Optional[webdriver.Chrome] = None
        self.download_folder = os.path.abspath("downloaded_materials")
        os.makedirs(self.download_folder, exist_ok=True)
        
    def _init_driver(self):
        """Инициализация Chrome драйвера"""
        if not self.driver:
            options = BrowserOptions.get_chrome_options(self.config)
            
            try:
                # Пробуем создать драйвер напрямую (Selenium Manager)
                self.driver = webdriver.Chrome(options=options)
                self.driver.implicitly_wait(10)
                logger.info("Chrome driver initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Chrome driver: {e}")
                # Fallback: пробуем через webdriver-manager
                try:
                    from selenium.webdriver.chrome.service import Service
                    from webdriver_manager.chrome import ChromeDriverManager

                    driver_path = ChromeDriverManager().install()
                    logger.info(f"Using ChromeDriver from: {driver_path}")
                    service = Service(driver_path)
                    self.driver = webdriver.Chrome(service=service, options=options)
                    self.driver.implicitly_wait(10)
                except Exception as e2:
                    logger.error(f"Fallback also failed: {e2}")
                    raise Exception(f"Could not initialize Chrome driver. Error: {e2}")

    def _close_driver(self):
        """Закрытие драйвера"""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None

    def _login(self):
        """Авторизация в LMS"""
        try:
            self._init_driver()
            logger.info("Navigating to LMS...")
            self.driver.get(self.config.base_url)

            # Ждем попап авторизации
            WebDriverWait(self.driver, 20).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "#popupLogin"))
            ).click()

            # Вводим данные
            username_field = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#popupUsername"))
            )
            username_field.clear()
            username_field.send_keys(self.credentials.username)

            password_field = self.driver.find_element(By.CSS_SELECTOR, "#popupPassword")
            password_field.clear()
            password_field.send_keys(self.credentials.password)

            # Нажимаем кнопку входа
            self.driver.find_element(By.CSS_SELECTOR, "#popupLoginBtn").click()

            # Ждем успешной авторизации
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".user-name"))
            )

            logger.info("Login successful")
            return True
        except Exception as e:
            logger.error(f"Login failed: {e}")
            self._close_driver()
            raise

    def parse_all_data(self) -> Dict:
        """Парсит все данные: семестры, курсы и материалы"""
        try:
            self._login()
            
            # Переходим на страницу учебного плана
            logger.info("Navigating to student UP page...")
            self.driver.get(f"{self.config.base_url}/student/up/")

            # Ждем загрузки таблиц семестров
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "tbody.semester"))
            )

            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
            # Парсим семестры
            semesters_data = self._parse_semesters(soup)
            logger.info(f"Found {len(semesters_data)} semesters")

            # Парсим курсы для каждого семестра
            for semester in semesters_data:
                logger.info(f"Parsing courses for semester {semester['number']}...")
                semester['courses'] = self._parse_courses_for_semester(semester['number'])
                logger.info(f"Found {len(semester['courses'])} courses in semester {semester['number']}")

            # Парсим материалы для каждого курса
            for semester in semesters_data:
                for course in semester['courses']:
                    logger.info(f"Parsing materials for course: {course['name']}")
                    course['materials'] = self._parse_course_materials(course['url'])
                    logger.info(f"Found {len(course['materials'])} materials in course: {course['name']}")

            return {
                'semesters': semesters_data,
                'total_semesters': len(semesters_data),
                'total_courses': sum(len(s['courses']) for s in semesters_data),
                'total_materials': sum(len(c['materials']) for s in semesters_data for c in s['courses']),
                'parsed_at': datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"Error parsing all data: {e}")
            # Сохраняем исходный код страницы для отладки
            try:
                with open("error_page_source.html", "w", encoding="utf-8") as f:
                    f.write(self.driver.page_source)
                logger.info("Page source saved to error_page_source.html")
            except:
                pass
            raise
        finally:
            self._close_driver()

    def _parse_semesters(self, soup: BeautifulSoup) -> List[Dict]:
        """Парсит семестры из страницы"""
        semesters = []
        
        # Находим все tbody с классом semester
        semester_tbodies = soup.select("tbody.semester")
        logger.info(f"Found {len(semester_tbodies)} semester tbody elements")

        for tbody in semester_tbodies:
            class_list = tbody.get('class', [])
            for cls in class_list:
                # Классы типа "semester s1", "semester s2" и т.д.
                if cls.startswith('s') and cls[1:].isdigit():
                    try:
                        semester_num = int(cls[1:])
                        
                        # Проверяем, не добавлен ли уже
                        if not any(s.get('number') == semester_num for s in semesters):
                            semester_url = f"{self.config.base_url}/student/up/"

                            semesters.append({
                                'name': f"Семестр {semester_num}",
                                'url': semester_url,
                                'number': semester_num,
                                'status': 'active',
                                'courses': []  # Будет заполнено позже
                            })
                            logger.info(f"Found semester: {semester_num}")
                    except ValueError:
                        continue

        # Сортируем по номеру семестра
        semesters.sort(key=lambda x: x.get('number', 0))
        return semesters

    def _parse_courses_for_semester(self, semester_number: int) -> List[Dict]:
        """Парсит курсы для конкретного семестра"""
        try:
            # Переходим на страницу учебного плана
            self.driver.get(f"{self.config.base_url}/student/up/")

            # Ждем конкретный семестр
            semester_selector = f'tbody.semester.s{semester_number}'
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, semester_selector))
            )

            soup = BeautifulSoup(self.driver.page_source, 'html.parser')

            # Находим tbody семестра
            semester_tbody = soup.select_one(semester_selector)
            if not semester_tbody:
                logger.error(f"Semester {semester_number} not found")
                return []

            courses = []
            # Находим все строки дисциплин в этом семестре
            discipline_rows = semester_tbody.find_all('tr', class_='discipl')
            logger.info(f"Found {len(discipline_rows)} discipline rows")

            for row in discipline_rows:
                try:
                    # Находим ссылку на курс
                    course_link = row.find('a', href=True)
                    if not course_link:
                        continue

                    course_name = course_link.get_text(strip=True)
                    course_url = course_link['href']
                    if not course_url.startswith('http'):
                        course_url = urljoin(self.config.base_url, course_url)

                    # Извлекаем тип контроля (обычно 3-й td)
                    tds = row.find_all('td')
                    control_type = tds[2].get_text(strip=True) if len(tds) > 2 else "Неизвестно"

                    # Извлекаем статус курса
                    status = "open"
                    if 'closed' in row.get('class', []):
                        status = "closed"

                    courses.append({
                        'name': course_name,
                        'url': course_url,
                        'control_type': control_type,
                        'status': status,
                        'materials_count': 0,  # Будет обновлено при парсинге материалов
                        'total_time': None,
                        'completion_percentage': 0.0,
                        'materials': []  # Будет заполнено позже
                    })

                    logger.info(f"Found course: {course_name} ({control_type}) - {status}")

                except Exception as e:
                    logger.error(f"Error parsing discipline row: {e}")
                    continue

            return courses

        except Exception as e:
            logger.error(f"Error parsing courses for semester {semester_number}: {e}")
            return []

    def _parse_course_materials(self, course_url: str) -> List[Dict]:
        """Парсит материалы для конкретного курса"""
        try:
            self.driver.get(course_url)

            # Ждем загрузки материалов в сайдбаре
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "ul.sidebar, .materials-list"))
            )

            # Парсим материалы рекурсивно
            materials = self._parse_materials_recursive()

            logger.info(f"Fetched {len(materials)} materials from {course_url}")
            return materials

        except Exception as e:
            logger.error(f"Error parsing materials for course {course_url}: {e}")
            return []

    def _parse_materials_recursive(self, parent_element=None, level=0) -> List[Dict]:
        """Рекурсивно парсит материалы из сайдбара"""
        materials = []

        if parent_element is None:
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            parent_element = soup.select_one('ul.sidebar, .materials-list')

        if not parent_element:
            return materials

        # Находим все прямые дочерние li
        for li in parent_element.find_all('li', recursive=False):
            try:
                # Проверяем, является ли это разделом с вложенными материалами
                nested_ul = li.find('ul', recursive=False)

                # Получаем информацию о материале
                link = li.find('a', href=True)
                material_name = li.get_text(strip=True).split('\n')[0] if li.get_text() else "Unknown"

                # Проверяем, заблокирован ли материал
                is_blocked = 'resourse_blocked' in li.get('class', [])

                # Получаем data-index
                data_index = li.get('data-index')

                # Определяем тип материала
                material_type = 'section' if nested_ul else 'material'
                if link and link.get('href'):
                    href = link.get('href', '')
                    if 'video' in href.lower():
                        material_type = 'video'
                    elif 'pdf' in href.lower() or 'document' in href.lower():
                        material_type = 'pdf'
                    elif 'test' in href.lower():
                        material_type = 'test'

                # Получаем время просмотра и прогресс
                viewing_time = None
                progress = None
                completion_status = None
                
                # Ищем элементы с информацией о времени и прогрессе
                time_elem = li.find(class_=lambda c: c and 'time' in c.lower())
                if time_elem:
                    viewing_time = time_elem.get_text(strip=True)

                progress_elem = li.find(class_=lambda c: c and 'progress' in c.lower())
                if progress_elem:
                    progress = progress_elem.get_text(strip=True)

                # Ищем статус завершения
                status_elem = li.find(class_=lambda c: c and ('complete' in c.lower() or 'done' in c.lower()))
                if status_elem:
                    completion_status = status_elem.get_text(strip=True)

                # Строим URL материала
                material_url = None
                if link:
                    material_url = link.get('href')
                    if material_url and not material_url.startswith('http'):
                        material_url = self.config.base_url + material_url

                # Определяем длительность для видео
                duration_seconds = None
                if material_type == 'video' and material_url:
                    duration_seconds = self._get_video_duration(material_url)

                material = {
                    'name': material_name,
                    'url': material_url,
                    'viewing_time': viewing_time,
                    'progress': progress,
                    'is_blocked': is_blocked,
                    'level': level,
                    'data_index': data_index,
                    'type': material_type,
                    'completion_status': completion_status,
                    'duration_seconds': duration_seconds,
                    'is_completed': completion_status and 'complete' in completion_status.lower()
                }

                materials.append(material)

                # Рекурсивно парсим вложенные материалы
                if nested_ul:
                    nested_materials = self._parse_materials_recursive(nested_ul, level + 1)
                    materials.extend(nested_materials)

            except Exception as e:
                logger.error(f"Error parsing material: {e}")
                continue

        return materials

    def _get_video_duration(self, video_url: str) -> Optional[int]:
        """Получает длительность видео в секундах"""
        try:
            # Переходим на страницу видео
            self.driver.get(video_url)
            
            # Ждем загрузки видеоплеера
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".video-js, .vjs-duration-display"))
            )
            
            # Ищем элемент с длительностью
            duration_elem = self.driver.find_element(By.CSS_SELECTOR, ".vjs-duration-display")
            if duration_elem:
                duration_text = duration_elem.text
                return self._parse_duration_to_seconds(duration_text)
                
        except Exception as e:
            logger.debug(f"Could not get video duration for {video_url}: {e}")
            
        return None

    def _parse_duration_to_seconds(self, duration_str: str) -> int:
        """Парсит строку длительности в секунды"""
        try:
            # Формат: "HH:MM:SS" или "MM:SS"
            parts = duration_str.split(':')
            if len(parts) == 3:  # HH:MM:SS
                hours, minutes, seconds = map(int, parts)
                return hours * 3600 + minutes * 60 + seconds
            elif len(parts) == 2:  # MM:SS
                minutes, seconds = map(int, parts)
                return minutes * 60 + seconds
            else:
                return 0
        except:
            return 0

    def save_to_json(self, data: Dict, filename: Optional[str] = None) -> str:
        """Сохраняет данные в JSON файл"""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"synergy_full_data_{timestamp}.json"
        
        filepath = os.path.join(os.getcwd(), filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Data saved to: {filepath}")
        return filepath

    def __del__(self):
        """Очистка драйвера при удалении"""
        self._close_driver()


def main():
    """Основная функция для тестирования парсера"""
    parser = FullSynergyParser()
    
    try:
        logger.info("Starting full parsing...")
        data = parser.parse_all_data()
        
        logger.info(f"Parsing completed!")
        logger.info(f"Total semesters: {data['total_semesters']}")
        logger.info(f"Total courses: {data['total_courses']}")
        logger.info(f"Total materials: {data['total_materials']}")
        
        # Сохраняем в JSON
        filepath = parser.save_to_json(data)
        print(f"\nData saved to: {filepath}")
        
    except Exception as e:
        logger.error(f"Parsing failed: {e}")
        raise


if __name__ == "__main__":
    main()

