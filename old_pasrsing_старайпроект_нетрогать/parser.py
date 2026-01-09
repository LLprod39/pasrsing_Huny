import os
import re
import json
import logging
import time
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse, parse_qs

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.action_chains import ActionChains
from bs4 import BeautifulSoup
import concurrent.futures
from concurrent.futures import Future

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def watch_video_simulation(video_url: str, duration: int, material_name: str, course_name: str):
    """
    Выполняется в фоновом потоке. Симулирует просмотр видео.
    """
    thread_name = f"Поток для '{material_name}'"
    try:
        logger.info(f"[{thread_name}] Начало фоновой задачи: симуляция просмотра.")
        
        # --- Логика симуляции просмотра ---
        if duration > 0:
            logger.info(f"[{thread_name}] Симулируем просмотр видео в течение {duration} секунд...")
            time.sleep(duration)
            logger.info(f"[{thread_name}] Симуляция просмотра для '{material_name}' завершена.")
        else:
            logger.info(f"[{thread_name}] Длительность 0 или не определена, симуляция пропускается.")
        
        return {'status': 'Success', 'material': material_name}

    except Exception as e:
        logger.error(f"[{thread_name}] Ошибка в фоновой задаче для '{material_name}': {e}")
        return {'status': 'Failed', 'material': material_name, 'error': str(e)}


class SynergyLMSParser:
    def __init__(self):
        self.base_url = "https://lms.synergy.ru"
        self.credentials = {
            'username': 'Yulia_wer@mail.ru',
            'password': 'Gcb[jkjubz1'
        }
        
        # Настройка Selenium
        options = webdriver.ChromeOptions()
        # options.add_argument("--headless") # Уберите эту строку, чтобы видеть браузер
        options.add_argument("--start-maximized")
        
        # Исправляем путь к ChromeDriver
        chromedriver_path = ChromeDriverManager().install()
        if chromedriver_path.endswith('THIRD_PARTY_NOTICES.chromedriver'):
            # Заменяем на правильный путь к chromedriver.exe
            chromedriver_path = chromedriver_path.replace('THIRD_PARTY_NOTICES.chromedriver', 'chromedriver.exe')
        
        self.driver = webdriver.Chrome(service=ChromeService(chromedriver_path), options=options)
        self.wait = WebDriverWait(self.driver, 20)

    def close(self):
        """Закрытие браузера"""
        if self.driver:
            self.driver.quit()
            
    def login(self) -> bool:
        """Авторизация в системе LMS"""
        try:
            logger.info("Начинаем авторизацию...")
            self.driver.get(self.base_url)

            # Ожидаем появления поп-апа и кликаем на кнопку входа
            try:
                login_button_popup = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), 'Войти')]")))
                login_button_popup.click()
                logger.info("Нажали на кнопку 'Войти' в поп-апе.")
            except:
                logger.info("Поп-ап для входа не появился, возможно, мы уже на странице входа.")

            # Ожидаем появления формы входа
            self.wait.until(EC.visibility_of_element_located((By.ID, 'popupLogin')))
            
            # Вводим логин
            username_input = self.wait.until(EC.visibility_of_element_located((By.ID, 'popupUsername')))
            username_input.click()
            username_input.clear()
            username_input.send_keys(self.credentials['username'])
            logger.info(f"Введен логин: {self.credentials['username']}")
            
            # Вводим пароль
            password_input = self.wait.until(EC.visibility_of_element_located((By.ID, 'popupPassword')))
            password_input.click()
            password_input.clear()
            password_input.send_keys(self.credentials['password'])
            logger.info("Введен пароль.")
            
            # Нажимаем кнопку "ВОЙТИ"
            login_button = self.wait.until(EC.element_to_be_clickable((By.ID, 'popupLoginBtn')))
            login_button.click()
            logger.info("Нажата кнопка 'ВОЙТИ'.")
            
            # Ждем подтверждения авторизации
            if self.is_logged_in():
                logger.info("Авторизация прошла успешно.")
                return True
            else:
                logger.error("Не удалось авторизоваться. Проверьте учетные данные и селекторы.")
                return False
                
        except Exception as e:
            logger.error(f"Ошибка во время автоматической авторизации: {str(e)}")
            return False
            
    def is_logged_in(self) -> bool:
        """Проверка успешной авторизации"""
        try:
            user_name_div = self.wait.until(EC.visibility_of_element_located((By.CLASS_NAME, 'user-name')))
            logger.info(f"Авторизован как: {user_name_div.text.strip()}")
            return True
        except:
            return False

    def get_available_semesters(self) -> List[int]:
        """Получение списка доступных семестров."""
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
            
            # Переходим на страницу с учебным планом, если еще не там
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
                    logger.error(f"Ошибка при обработке строки курса: {str(e)}")
                    continue
                    
            logger.info(f"Найдено {len(courses)} курсов")
            return courses
            
        except Exception as e:
            logger.error(f"Ошибка при получении курсов: {str(e)}")
            return []
            
    def get_course_materials(self, course_url: str) -> List[Dict]:
        """Получение учебных материалов курса в виде иерархической структуры."""
        try:
            logger.info(f"Получаем материалы курса: {course_url}")
            self.driver.get(course_url)
            self.wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "ul.sidebar")))

            soup = BeautifulSoup(self.driver.page_source, 'html.parser')

            structured_materials = []

            def parse_materials(element, level=0):
                materials = []
                # Ищем дочерние `li` непосредственно внутри текущего `ul`
                for li in element.find_all('li', recursive=False):
                    # Находим ссылку и заголовок внутри `div`
                    div = li.find('div', recursive=False)
                    if not div: continue
                    
                    link = div.find('a', recursive=False)
                    if not link: continue

                    # Получаем все тексты из спанов и объединяем
                    title_spans = link.find_all('span')
                    title = ' '.join(span.get_text(strip=True) for span in title_spans).strip()
                    
                    # Проверяем, есть ли вложенный список `ul`
                    nested_ul = li.find('ul', recursive=False)
                    
                    if nested_ul:
                        # Это раздел, рекурсивно парсим его материалы
                        materials.append({
                            'title': title,
                            'materials': parse_materials(nested_ul, level + 1),
                            'is_blocked': 'resourse_blocked' in link.get('class', [])
                        })
                    elif 'href' in link.attrs:
                        # Это конечный материал
                        material_url = urljoin(self.base_url, link['href'])
                        materials.append({
                            'name': title,
                            'url': material_url,
                            'data_index': li.get('data-index'),
                            'is_blocked': False
                        })
                    elif 'resourse_blocked' in link.get('class', []):
                        # Это заблокированный материал без ссылки
                        reason = link.get('alt', 'Причина блокировки не указана')
                        logger.info(f"Найден заблокированный материал: {title} (Причина: {reason})")
                        materials.append({
                            'name': f"{title} [ЗАБЛОКИРОВАНО]",
                            'url': None,
                            'data_index': li.get('data-index'),
                            'is_blocked': True,
                            'reason': reason
                        })
                    else:
                        # Это заголовок без ссылки, который не является заблокированным ресурсом
                        logger.info(f"Пропускаем заголовок без ссылки: {title}")
                return materials

            # Начинаем парсинг с корневого `ul.sidebar`
            sidebar_ul = soup.select_one('ul.sidebar')
            if sidebar_ul:
                structured_materials = parse_materials(sidebar_ul)
                logger.info(f"Найдено {len(structured_materials)} корневых разделов/материалов.")

            return structured_materials

        except Exception as e:
            logger.error(f"Ошибка при получении материалов курса: {str(e)}")
            with open("error_page_source.html", "w", encoding="utf-8") as f:
                f.write(self.driver.page_source)
            logger.info("Исходный код страницы с ошибкой сохранен в 'error_page_source.html'")
            return []
            
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

    def _find_and_start_video_simulation(self, material_name: str, course_name: str, executor: concurrent.futures.ThreadPoolExecutor) -> Optional[Future]:
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
                            course_name
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

    def process_material(self, material: Dict, course_name: str, executor: concurrent.futures.ThreadPoolExecutor) -> Dict:
        """Обработка отдельного учебного материала с поиском в iframe."""
        results = {'processed': False, 'videos': 0, 'pdfs': 0, 'task_future': None}
        try:
            logger.info(f"Обрабатываем материал: {material['name']}")
            self.driver.get(material['url'])
            self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            time.sleep(3)

            video_future = None
            # 1. Поиск на основной странице
            logger.info("Ищем видео на основной странице...")
            video_future = self._find_and_start_video_simulation(material['name'], course_name, executor)
            
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
                                video_future = self._find_and_start_video_simulation(material['name'], course_name, executor)
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
                logger.info(f"Видео-задача для '{material['name']}' запущена. Ожидаем завершения...")
                results['videos'] += 1
                # Ожидаем завершения фоновой задачи
                task_result = video_future.result() 
                logger.info(f"Фоновая задача для '{material['name']}' завершена со статусом: {task_result.get('status')}")
            else:
                logger.info("Видео для просмотра не найдено ни на странице, ни в iframes.")

            # --- Подтверждение изучения (выполняется в самом конце) ---
            self.driver.switch_to.default_content()
            self.confirm_material_study()
            results['processed'] = True
            return results
            
        except Exception as e:
            logger.error(f"Критическая ошибка при обработке материала {material['name']}: {str(e)}")
            return results
        finally:
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass
            
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
            
    def process_selected_materials(self, materials_to_process: List[Dict], course_name: str, executor: concurrent.futures.ThreadPoolExecutor) -> Dict:
        """Обработка выбранных материалов из курса."""
        results = {
            'total_materials': len(materials_to_process),
            'processed_materials': 0,
            'tasks_submitted': 0,
            'downloaded_pdfs': 0,
            'errors': []
        }
        
        for material in materials_to_process:
            try:
                material_result = self.process_material(material, course_name, executor)
                if material_result['processed']:
                    results['processed_materials'] += 1
                    results['tasks_submitted'] += material_result['videos']
                    results['downloaded_pdfs'] += material_result['pdfs']
            except Exception as e:
                error_msg = f"Ошибка при обработке материала {material['name']}: {str(e)}"
                results['errors'].append(error_msg)
                logger.error(error_msg)
                
        return results

    def process_courses_in_tabs(self, courses: List[Dict]) -> List[Dict]:
        """Обработка списка курсов, открывая каждый в новой вкладке."""
        main_window_handle = self.driver.current_window_handle
        all_results = []

        for course in courses:
            logger.info(f"\n{'='*20} Начинаем обработку курса: {course['name']} {'='*20}")
            initial_handles = set(self.driver.window_handles)
            
            try:
                # 1. Открываем URL курса в новой вкладке и переключаемся на нее
                logger.info(f"Открываем новую вкладку для курса '{course['name']}'...")
                self.driver.execute_script("window.open(arguments[0], '_blank');", course['url'])
                
                WebDriverWait(self.driver, 10).until(EC.number_of_windows_to_be(len(initial_handles) + 1))
                new_handles = set(self.driver.window_handles)
                new_tab_handle = (new_handles - initial_handles).pop()
                self.driver.switch_to.window(new_tab_handle)

                # 2. Получаем материалы курса
                logger.info("Получаем материалы курса...")
                structured_materials = self.get_course_materials(self.driver.current_url)

                flat_materials_list = []
                def flatten(materials):
                    for item in materials:
                        if 'materials' in item:
                            flatten(item['materials'])
                        elif not item.get('is_blocked'):
                            if item.get('url') and not any(x['url'] == item['url'] for x in flat_materials_list if x.get('url')):
                                flat_materials_list.append(item)
                
                flatten(structured_materials)

                if not flat_materials_list:
                    warn_msg = "В курсе нет доступных материалов для обработки."
                    logger.warning(warn_msg)
                    all_results.append({'course': course['name'], 'status': 'No Materials', 'error': warn_msg})
                    continue # Переходим к следующему курсу

                # 3. Выбор материалов пользователем
                print("\n" + "=" * 60)
                print(f">>> МАТЕРИАЛЫ КУРСА: {course['name']} <<<")
                for i, material in enumerate(flat_materials_list):
                    print(f"  {i + 1}. {material['name']}")
                print("  - введите 'все' для обработки всех материалов")
                print("  - введите 'назад' для возврата к выбору курса")
                print("=" * 60 + "\n")

                materials_to_process = []
                while True:
                    try:
                        choice_str = input(f">>> Введите номера материалов для '{course['name']}' (через запятую, 'все' или 'назад'): ")
                        choice_str = choice_str.strip().lower()

                        if choice_str == 'назад':
                            materials_to_process = []
                            break
                        
                        if choice_str == 'все':
                            materials_to_process = flat_materials_list
                            break

                        choices = [int(c.strip()) for c in choice_str.split(',')]
                        temp_materials = []
                        valid = True
                        for c in choices:
                            if 1 <= c <= len(flat_materials_list):
                                temp_materials.append(flat_materials_list[c - 1])
                            else:
                                print(f"Ошибка: Номер {c} некорректен.")
                                valid = False
                                break
                        if valid and temp_materials:
                            materials_to_process = temp_materials
                            break
                    except (ValueError, EOFError, KeyboardInterrupt):
                        print("\nНеверный ввод или отмена.")
                        continue
                
                if not materials_to_process:
                    logger.info(f"Пропускаем курс '{course['name']}' по выбору пользователя.")
                    # Не добавляем результат, просто переходим к следующему курсу
                else:
                    # 4. Запуск обработки выбранных материалов
                    # Подсчитываем количество доступных материалов для создания нужного количества потоков
                    available_materials_count = len([m for m in materials_to_process if not m.get('is_blocked') and m.get('url')])
                    thread_count = max(1, min(available_materials_count, 20))  # Минимум 1, максимум 20
                    
                    logger.info(f">>> Найдено {available_materials_count} доступных материалов")
                    logger.info(f">>> Создаем {thread_count} потоков для обработки")
                    logger.info(f">>> Начинаем параллельную обработку...")
                    
                    logger.info(f"Начинаем обработку {len(materials_to_process)} выбранных материалов...")
                    
                    # Создаем executor с нужным количеством потоков для этого курса
                    with concurrent.futures.ThreadPoolExecutor(max_workers=thread_count) as course_executor:
                        results = self.process_selected_materials(materials_to_process, course['name'], course_executor)
                        results['course'] = course['name']
                        results['status'] = 'Tasks Submitted'
                        results['threads_used'] = thread_count
                        all_results.append(results)

            except Exception as e:
                error_msg = f"Ошибка при обработке курса {course['name']}: {e}"
                logger.error(error_msg, exc_info=True)
                all_results.append({'course': course['name'], 'status': 'Failed', 'error': str(e)})
            finally:
                # 5. Закрываем текущую вкладку и возвращаемся на основную
                if len(self.driver.window_handles) > 1 and self.driver.current_window_handle != main_window_handle:
                    logger.info(f"Закрываем вкладку курса '{course['name']}'...")
                    self.driver.close()
                
                self.driver.switch_to.window(main_window_handle)
                logger.info(f"Вернулись на основную вкладку.")
        
        return all_results


def main():
    """Основная функция для запуска парсера"""
    parser = SynergyLMSParser()
    
    try:
        # 1. Авторизация
        if not parser.login():
            logger.error("Не удалось авторизоваться. Выход.")
            return

        while True:  # Главный цикл программы
            # 2. Выбор семестра
            available_semesters = parser.get_available_semesters()
            if not available_semesters:
                logger.error("Не удалось найти доступные семестры. Выход.")
                break

            print("\n" + "=" * 60)
            print(">>> ДОСТУПНЫЕ СЕМЕСТРЫ <<<")
            for sem in available_semesters:
                print(f"  - Семестр {sem}")
            print("  - введите 'выход' для завершения работы")
            print("  - введите 'статус' для проверки фоновых задач")
            print("=" * 60 + "\n")

            chosen_semester = None
            while chosen_semester is None:
                try:
                    choice = input(">>> Введите номер семестра (или 'выход'/'статус'): ")
                    if choice.strip().lower() in ['выход', 'exit', 'q']:
                        # Ждем завершения всех фоновых задач перед выходом
                        logger.info("Завершение работы... Ожидание окончания всех фоновых задач.")
                        # executor._threads очищается при выходе из with, поэтому просто выходим
                        return
                    if choice.strip().lower() == 'статус':
                        # Эта опция пока не реализована, но можно добавить в будущем
                        logger.info("Проверка статуса пока не реализована.")
                        continue
                    if not choice:
                        print("Ввод не может быть пустым. Попробуйте еще раз.")
                        continue
                    choice_int = int(choice)
                    if choice_int in available_semesters:
                        chosen_semester = choice_int
                    else:
                        print(f"Ошибка: Семестр {choice_int} не найден. Попробуйте еще раз.")
                except ValueError:
                    print("Ошибка: Введите корректное число.")
                except (EOFError, KeyboardInterrupt):
                    print("\nОтмена операции. Выход.")
                    return

            # 3. Выбор курсов для обработки
            courses = parser.get_semester_courses(chosen_semester)
            if not courses:
                logger.warning(f"В семестре {chosen_semester} не найдено курсов.")
                continue

            print("\n" + "=" * 60)
            print(f">>> КУРСЫ В СЕМЕСТРЕ {chosen_semester} <<<")
            for i, course in enumerate(courses):
                print(f"  {i + 1}. {course['name']} ({course['control_type']})")
            print("  - введите 'назад' для возврата к выбору семестра")
            print("=" * 60 + "\n")

            courses_to_process = []
            while True:
                try:
                    choice_str = input(f">>> Введите номера курсов (через запятую, 'все' или 'назад'): ")
                    choice_str = choice_str.strip().lower()

                    if choice_str == 'назад':
                        courses_to_process = []
                        break
                    
                    if choice_str == 'все':
                        courses_to_process = courses
                        break

                    choices = [int(c.strip()) for c in choice_str.split(',')]
                    temp_courses = []
                    valid = True
                    for c in choices:
                        if 1 <= c <= len(courses):
                            temp_courses.append(courses[c - 1])
                        else:
                            print(f"Ошибка: Номер {c} некорректен.")
                            valid = False
                            break
                    if valid and temp_courses:
                        courses_to_process = temp_courses
                        break
                except (ValueError, EOFError, KeyboardInterrupt):
                    print("\nНеверный ввод или отмена.")
                    continue
            
            if not courses_to_process:
                continue

            # 4. Обработка выбранных курсов
            parser.process_courses_in_tabs(courses_to_process)

    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
    finally:
        parser.close()


if __name__ == "__main__":
    main()
