"""Модуль для парсинга курсов и материалов"""
import time
from typing import List, Dict, Optional
from urllib.parse import urljoin
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from bs4 import BeautifulSoup
from synergy_lms.config import Config
from synergy_lms.logger import setup_logger

logger = setup_logger(__name__)


class CourseParser:
    """Класс для парсинга курсов и материалов"""
    
    def __init__(self, driver: webdriver.Chrome):
        self.driver = driver
        self.wait = WebDriverWait(driver, Config.PAGE_LOAD_TIMEOUT)
        self.base_url = Config.BASE_URL
    
    def get_available_semesters(self) -> List[int]:
        """Получение списка доступных семестров"""
        try:
            logger.info("Получаем список доступных семестров...")
            if "student/up" not in self.driver.current_url:
                self.driver.get(f"{self.base_url}/student/up/")
            
            self.wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "tbody.semester")))
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
            semesters = []
            semester_tbodies = soup.select("tbody.semester")
            for tbody in semester_tbodies:
                class_list = tbody.get('class', [])
                for cls in class_list:
                    if cls.startswith('s'):
                        try:
                            semester_num = int(cls[1:])
                            if semester_num not in semesters:
                                semesters.append(semester_num)
                        except ValueError:
                            continue
            
            logger.info(f"Найдены семестры: {sorted(semesters)}")
            return sorted(semesters)
        except Exception as e:
            logger.error(f"Ошибка при получении списка семестров: {e}")
            return []
    
    def get_semester_courses(self, semester_number: int) -> List[Dict]:
        """Получение списка курсов для указанного семестра"""
        try:
            logger.info(f"Получаем курсы для {semester_number} семестра...")
            
            if "student/up" not in self.driver.current_url:
                self.driver.get(f"{self.base_url}/student/up/")
            
            semester_selector = f'tbody.semester.s{semester_number}'
            self.wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, semester_selector)))
            
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            semester_tbody = soup.select_one(semester_selector)
            if not semester_tbody:
                logger.error(f"Семестр {semester_number} не найден")
                return []
                
            courses = []
            discipline_rows = semester_tbody.find_all('tr', class_='discipl')
            
            for row in discipline_rows:
                try:
                    course_link = row.find('a', href=True)
                    if course_link:
                        course_name = course_link.get_text().strip()
                        course_url = urljoin(self.base_url, course_link['href'])
                        
                        control_type_td = row.find_all('td')[2] if len(row.find_all('td')) > 2 else None
                        control_type = control_type_td.get_text().strip() if control_type_td else "Неизвестно"
                        
                        courses.append({
                            'name': course_name,
                            'url': course_url,
                            'control_type': control_type
                        })
                        logger.info(f"Найден курс: {course_name} ({control_type})")
                        
                except Exception as e:
                    logger.error(f"Ошибка при обработке строки курса: {e}")
                    continue
                    
            logger.info(f"Найдено {len(courses)} курсов")
            return courses
            
        except Exception as e:
            logger.error(f"Ошибка при получении курсов: {e}")
            return []
    
    def get_course_materials(self, course_url: str) -> List[Dict]:
        """Получение учебных материалов курса в виде иерархической структуры"""
        try:
            logger.info(f"Получаем материалы курса: {course_url}")
            self.driver.get(course_url)
            self.wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "ul.sidebar")))

            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            structured_materials = []

            def parse_materials(element, level=0):
                materials = []
                for li in element.find_all('li', recursive=False):
                    div = li.find('div', recursive=False)
                    if not div:
                        continue
                    
                    link = div.find('a', recursive=False)
                    if not link:
                        continue

                    title_spans = link.find_all('span')
                    title = ' '.join(span.get_text(strip=True) for span in title_spans).strip()
                    
                    nested_ul = li.find('ul', recursive=False)
                    
                    if nested_ul:
                        materials.append({
                            'title': title,
                            'materials': parse_materials(nested_ul, level + 1),
                            'is_blocked': 'resourse_blocked' in link.get('class', [])
                        })
                    elif 'href' in link.attrs:
                        material_url = urljoin(self.base_url, link['href'])
                        
                        # Определяем тип материала
                        material_type = self._determine_material_type(title, material_url)
                        
                        materials.append({
                            'name': title,
                            'url': material_url,
                            'data_index': li.get('data-index'),
                            'is_blocked': False,
                            'type': material_type
                        })
                    elif 'resourse_blocked' in link.get('class', []):
                        reason = link.get('alt', 'Причина блокировки не указана')
                        logger.info(f"Найден заблокированный материал: {title} (Причина: {reason})")
                        materials.append({
                            'name': f"{title} [ЗАБЛОКИРОВАНО]",
                            'url': None,
                            'data_index': li.get('data-index'),
                            'is_blocked': True,
                            'reason': reason,
                            'type': 'blocked'
                        })
                
                return materials

            sidebar_ul = soup.select_one('ul.sidebar')
            if sidebar_ul:
                structured_materials = parse_materials(sidebar_ul)
                logger.info(f"Найдено {len(structured_materials)} корневых разделов/материалов.")

            return structured_materials

        except Exception as e:
            logger.error(f"Ошибка при получении материалов курса: {e}")
            return []
    
    def _determine_material_type(self, name: str, url: str) -> str:
        """Определение типа материала"""
        name_lower = name.lower()
        url_lower = url.lower()

        # Synergy LMS: видео-материалы часто открываются по /learning/view/<id>
        # (при этом в URL нет слова "video", а в названии может не быть "видео/лекция/урок")
        if '/learning/view/' in url_lower:
            return 'video'
        
        if any(keyword in name_lower for keyword in ['тест', 'test', 'аттестация', 'экзамен']):
            return 'test'
        elif 'test' in url_lower or '/event/view/' in url_lower:
            return 'test'
        elif any(keyword in name_lower for keyword in ['видео', 'лекция', 'урок']):
            return 'video'
        elif 'video' in url_lower:
            return 'video'
        elif any(keyword in name_lower for keyword in ['документ', 'материал', 'презентация', 'pdf']):
            return 'pdf'
        elif 'pdf' in url_lower or 'document' in url_lower:
            return 'pdf'
        else:
            return 'material'
    
    def flatten_materials(self, structured_materials: List[Dict]) -> List[Dict]:
        """Преобразование иерархической структуры материалов в плоский список"""
        flat_list = []
        
        def flatten_recursive(items):
            for item in items:
                if 'materials' in item:
                    flatten_recursive(item['materials'])
                elif 'url' in item and item.get('url') and not item.get('is_blocked'):
                    flat_list.append(item)
        
        flatten_recursive(structured_materials)
        return flat_list
