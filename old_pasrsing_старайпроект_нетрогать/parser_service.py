"""
Parser Service - Integration layer between existing parser and database
"""
import logging
from typing import List, Dict, Optional
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from bs4 import BeautifulSoup
from config import ParserConfig, Credentials, BrowserOptions
from full_parser import FullSynergyParser

logger = logging.getLogger(__name__)


class ParserService:
    """Service for fetching data from Synergy LMS"""

    def __init__(self):
        self.config = ParserConfig()
        self.credentials = Credentials()
        self.driver: Optional[webdriver.Chrome] = None

    def _init_driver(self):
        """Initialize Chrome driver"""
        if not self.driver:
            options = BrowserOptions.get_chrome_options(self.config)

            try:
                # Пытаемся создать драйвер напрямую (Selenium Manager автоматически скачает нужный драйвер)
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
                    raise Exception(f"Could not initialize Chrome driver. Please install Chrome browser and ensure it's up to date. Error: {e2}")

    def _close_driver(self):
        """Close Chrome driver"""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None

    def _login(self):
        """Login to LMS"""
        try:
            self._init_driver()
            logger.info("Navigating to LMS...")
            self.driver.get(self.config.base_url)

            # Wait for login popup
            WebDriverWait(self.driver, 20).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "#popupLogin"))
            ).click()

            # Enter credentials
            username_field = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#popupUsername"))
            )
            username_field.clear()
            username_field.send_keys(self.credentials.username)

            password_field = self.driver.find_element(By.CSS_SELECTOR, "#popupPassword")
            password_field.clear()
            password_field.send_keys(self.credentials.password)

            # Click login button
            self.driver.find_element(By.CSS_SELECTOR, "#popupLoginBtn").click()

            # Wait for successful login
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".user-name"))
            )

            logger.info("Login successful")
            return True
        except Exception as e:
            logger.error(f"Login failed: {e}")
            self._close_driver()
            raise

    def fetch_semesters(self) -> List[Dict]:
        """Fetch all semesters from LMS"""
        try:
            self._login()

            # Navigate to UP (учебный план) page
            logger.info("Navigating to student UP page...")
            self.driver.get(f"{self.config.base_url}/student/up/")

            # Wait for semester tables to load
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "tbody.semester"))
            )

            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            semesters = []

            # Find all semester tbody elements
            semester_tbodies = soup.select("tbody.semester")
            logger.info(f"Found {len(semester_tbodies)} semester tbody elements")

            for tbody in semester_tbodies:
                class_list = tbody.get('class', [])
                for cls in class_list:
                    # Classes like "semester s1", "semester s2", etc.
                    if cls.startswith('s') and cls[1:].isdigit():
                        try:
                            semester_num = int(cls[1:])

                            # Check if already added
                            if not any(s.get('number') == semester_num for s in semesters):
                                semester_url = f"{self.config.base_url}/student/up/"

                                semesters.append({
                                    'name': f"Семестр {semester_num}",
                                    'url': semester_url,
                                    'number': semester_num,
                                    'status': 'active'
                                })
                                logger.info(f"Found semester: {semester_num}")
                        except ValueError:
                            continue

            # Sort by semester number
            semesters.sort(key=lambda x: x.get('number', 0))

            logger.info(f"Fetched {len(semesters)} semesters")
            return semesters
        except Exception as e:
            logger.error(f"Error fetching semesters: {e}")
            # Save page source for debugging
            try:
                with open("error_page_source.html", "w", encoding="utf-8") as f:
                    f.write(self.driver.page_source)
                logger.info("Page source saved to error_page_source.html")
            except:
                pass
            raise
        finally:
            self._close_driver()

    def fetch_courses(self, semester_number: int) -> List[Dict]:
        """Fetch courses for a specific semester by number"""
        try:
            self._login()

            # Navigate to UP page
            logger.info(f"Navigating to UP page for semester {semester_number}...")
            self.driver.get(f"{self.config.base_url}/student/up/")

            # Wait for specific semester tbody
            semester_selector = f'tbody.semester.s{semester_number}'
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, semester_selector))
            )

            soup = BeautifulSoup(self.driver.page_source, 'html.parser')

            # Find semester tbody
            semester_tbody = soup.select_one(semester_selector)
            if not semester_tbody:
                logger.error(f"Semester {semester_number} not found")
                return []

            courses = []
            # Find all discipline rows in this semester
            discipline_rows = semester_tbody.find_all('tr', class_='discipl')
            logger.info(f"Found {len(discipline_rows)} discipline rows")

            for row in discipline_rows:
                try:
                    # Find course link
                    course_link = row.find('a', href=True)
                    if not course_link:
                        continue

                    course_name = course_link.get_text(strip=True)
                    course_url = course_link['href']
                    if not course_url.startswith('http'):
                        from urllib.parse import urljoin
                        course_url = urljoin(self.config.base_url, course_url)

                    # Extract control type (usually 3rd td)
                    tds = row.find_all('td')
                    control_type = tds[2].get_text(strip=True) if len(tds) > 2 else "Неизвестно"

                    courses.append({
                        'name': course_name,
                        'url': course_url,
                        'control_type': control_type,
                        'status': 'open',
                        'materials_count': 0,
                        'total_time': None,
                        'completion_percentage': 0.0
                    })

                    logger.info(f"Found course: {course_name} ({control_type})")

                except Exception as e:
                    logger.error(f"Error parsing discipline row: {e}")
                    continue

            logger.info(f"Fetched {len(courses)} courses from semester {semester_number}")
            return courses
        except Exception as e:
            logger.error(f"Error fetching courses for semester {semester_number}: {e}")
            raise
        finally:
            self._close_driver()

    def fetch_materials(self, course_url: str) -> List[Dict]:
        """Fetch materials for a specific course"""
        try:
            self._login()
            self.driver.get(course_url)

            # Wait for sidebar materials
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "ul.sidebar, .materials-list"))
            )

            # Parse materials recursively
            materials = self._parse_materials_recursive()

            logger.info(f"Fetched {len(materials)} materials from {course_url}")
            return materials
        finally:
            self._close_driver()

    def _parse_materials_recursive(self, parent_element=None, level=0) -> List[Dict]:
        """Recursively parse materials from sidebar"""
        materials = []

        if parent_element is None:
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            parent_element = soup.select_one('ul.sidebar, .materials-list')

        if not parent_element:
            return materials

        # Find all direct li children
        for li in parent_element.find_all('li', recursive=False):
            try:
                # Check if it's a section with nested materials
                nested_ul = li.find('ul', recursive=False)

                # Get material info
                link = li.find('a', href=True)
                material_name = li.get_text(strip=True).split('\n')[0] if li.get_text() else "Unknown"

                # Check if blocked
                is_blocked = 'resourse_blocked' in li.get('class', [])

                # Get data-index
                data_index = li.get('data-index')

                # Determine type
                material_type = 'section' if nested_ul else 'material'
                if link and link.get('href'):
                    href = link.get('href', '')
                    if 'video' in href.lower():
                        material_type = 'video'
                    elif 'pdf' in href.lower() or 'document' in href.lower():
                        material_type = 'pdf'
                    elif 'test' in href.lower():
                        material_type = 'test'

                # Get viewing time and progress
                viewing_time = None
                progress = None
                time_elem = li.find(class_=lambda c: c and 'time' in c.lower())
                if time_elem:
                    viewing_time = time_elem.get_text(strip=True)

                progress_elem = li.find(class_=lambda c: c and 'progress' in c.lower())
                if progress_elem:
                    progress = progress_elem.get_text(strip=True)

                # Build material URL
                material_url = None
                if link:
                    material_url = link.get('href')
                    if material_url and not material_url.startswith('http'):
                        material_url = self.config.base_url + material_url

                material = {
                    'name': material_name,
                    'url': material_url,
                    'viewing_time': viewing_time,
                    'progress': progress,
                    'is_blocked': is_blocked,
                    'level': level,
                    'data_index': data_index,
                    'type': material_type,
                    'completion_status': None
                }

                materials.append(material)

                # Recursively parse nested materials
                if nested_ul:
                    nested_materials = self._parse_materials_recursive(nested_ul, level + 1)
                    materials.extend(nested_materials)

            except Exception as e:
                logger.error(f"Error parsing material: {e}")
                continue

        return materials

    def parse_all_data(self) -> Dict:
        """Парсит все данные: семестры, курсы и материалы за один раз"""
        try:
            full_parser = FullSynergyParser()
            return full_parser.parse_all_data()
        except Exception as e:
            logger.error(f"Error in full parsing: {e}")
            raise

    def sync_all_data_to_db(self) -> Dict:
        """Синхронизирует все данные с базой данных"""
        try:
            # Парсим все данные
            data = self.parse_all_data()
            
            # Здесь можно добавить логику сохранения в базу данных
            # Пока возвращаем данные для дальнейшей обработки
            return {
                'success': True,
                'data': data,
                'message': f"Successfully parsed {data['total_semesters']} semesters, {data['total_courses']} courses, {data['total_materials']} materials"
            }
        except Exception as e:
            logger.error(f"Error syncing all data: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def __del__(self):
        """Cleanup driver on deletion"""
        self._close_driver()
