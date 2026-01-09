"""Модуль для автоматического прохождения тестов"""
import time
import random
from typing import Dict, List, Optional
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from bs4 import BeautifulSoup
from config import Config
from logger import setup_logger

logger = setup_logger(__name__)


class TestSolver:
    """Класс для автоматического прохождения тестов"""
    
    def __init__(self, driver: webdriver.Chrome):
        self.driver = driver
        self.wait = WebDriverWait(driver, Config.PAGE_LOAD_TIMEOUT)
        self.strategy = Config.TEST_STRATEGY
    
    def solve_test(self, test_url: str, test_name: str) -> Dict:
        """Автоматическое прохождение теста"""
        results = {
            'solved': False,
            'score': None,
            'attempts': 0,
            'error': None
        }
        
        try:
            logger.info(f"Начинаем прохождение теста: {test_name}")
            self.driver.get(test_url)
            self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            time.sleep(3)
            
            # Проверяем, есть ли уже результаты теста
            if self._check_test_completed():
                logger.info(f"Тест '{test_name}' уже пройден")
                results['solved'] = True
                results['score'] = self._get_test_score()
                return results
            
            # Начинаем прохождение теста
            if not self._start_test():
                logger.error("Не удалось начать тест")
                results['error'] = "Не удалось начать тест"
                return results
            
            # Получаем вопросы
            questions = self._get_questions()
            logger.info(f"Найдено {len(questions)} вопросов")
            
            if not questions:
                logger.warning("Вопросы не найдены")
                results['error'] = "Вопросы не найдены"
                return results
            
            # Отвечаем на вопросы
            for i, question in enumerate(questions):
                logger.info(f"Отвечаем на вопрос {i + 1}/{len(questions)}")
                self._answer_question(question, i)
                time.sleep(1)  # Небольшая задержка между вопросами
            
            # Отправляем ответы
            if self._submit_test():
                logger.info("Тест отправлен")
                time.sleep(3)  # Ждем обработки результатов
                
                # Получаем результаты
                results['solved'] = True
                results['score'] = self._get_test_score()
                results['attempts'] = 1
                
                logger.info(f"Тест '{test_name}' пройден. Оценка: {results['score']}")
            else:
                logger.error("Не удалось отправить тест")
                results['error'] = "Не удалось отправить тест"
            
            return results
            
        except Exception as e:
            logger.error(f"Ошибка при прохождении теста '{test_name}': {e}")
            results['error'] = str(e)
            return results
    
    def _check_test_completed(self) -> bool:
        """Проверка, пройден ли уже тест"""
        try:
            # Ищем элементы, указывающие на завершенный тест
            completed_indicators = [
                "Результаты теста",
                "Тест пройден",
                "Оценка",
                "Попытка",
                "results",
                "completed"
            ]
            
            page_text = self.driver.page_source.lower()
            for indicator in completed_indicators:
                if indicator.lower() in page_text:
                    # Проверяем наличие таблицы результатов
                    results_table = self.driver.find_elements(By.CSS_SELECTOR, "table.table-list, .test-results, .results-table")
                    if results_table:
                        return True
            
            return False
        except:
            return False
    
    def _get_test_score(self) -> Optional[str]:
        """Получение оценки за тест"""
        try:
            # Ищем оценку в различных форматах
            score_selectors = [
                ".score",
                ".test-score",
                ".result-score",
                "td:contains('Оценка')",
                "td:contains('Балл')"
            ]
            
            for selector in score_selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for elem in elements:
                        text = elem.text.strip()
                        if text and any(char.isdigit() for char in text):
                            return text
                except:
                    continue
            
            # Пробуем найти в таблице результатов
            try:
                table = self.driver.find_element(By.CSS_SELECTOR, "table.table-list")
                rows = table.find_elements(By.TAG_NAME, "tr")
                for row in rows:
                    cells = row.find_elements(By.TAG_NAME, "td")
                    for cell in cells:
                        text = cell.text.strip()
                        if any(char.isdigit() for char in text) and ('%' in text or '/' in text):
                            return text
            except:
                pass
            
            return None
        except:
            return None
    
    def _start_test(self) -> bool:
        """Начало прохождения теста"""
        try:
            # Ищем кнопку "Начать тест", "Пройти тест" и т.д.
            start_buttons = [
                "button:contains('Начать')",
                "button:contains('Пройти')",
                "button:contains('Start')",
                ".start-test",
                "#start-test",
                "a:contains('Начать тест')"
            ]
            
            for selector in start_buttons:
                try:
                    buttons = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for button in buttons:
                        if button.is_displayed() and button.is_enabled():
                            button.click()
                            time.sleep(2)
                            logger.info("Тест начат")
                            return True
                except:
                    continue
            
            # Если кнопки не найдены, возможно тест уже начат
            logger.info("Кнопка начала теста не найдена, возможно тест уже начат")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка при начале теста: {e}")
            return False
    
    def _get_questions(self) -> List[Dict]:
        """Получение списка вопросов теста"""
        questions = []
        
        try:
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
            # Ищем различные форматы вопросов
            question_selectors = [
                ".question",
                ".test-question",
                ".question-item",
                "[data-question-id]",
                ".question-block"
            ]
            
            for selector in question_selectors:
                question_elements = soup.select(selector)
                if question_elements:
                    for i, q_elem in enumerate(question_elements):
                        question_text = q_elem.get_text(strip=True)
                        
                        # Ищем варианты ответов
                        answers = self._get_answers_from_element(q_elem)
                        
                        questions.append({
                            'index': i,
                            'text': question_text,
                            'element': q_elem,
                            'answers': answers
                        })
                    
                    if questions:
                        break
            
            # Если вопросы не найдены стандартными селекторами, ищем по структуре страницы
            if not questions:
                # Ищем все input[type="radio"] или input[type="checkbox"]
                radio_inputs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='radio'], input[type='checkbox']")
                if radio_inputs:
                    # Группируем по name или data-question-id
                    question_groups = {}
                    for inp in radio_inputs:
                        question_id = inp.get_attribute('name') or inp.get_attribute('data-question-id') or 'unknown'
                        if question_id not in question_groups:
                            question_groups[question_id] = []
                        question_groups[question_id].append(inp)
                    
                    for i, (q_id, inputs) in enumerate(question_groups.items()):
                        answers = []
                        for inp in inputs:
                            # Получаем текст ответа (обычно в label или рядом)
                            try:
                                label = self.driver.execute_script(
                                    "return arguments[0].labels && arguments[0].labels[0] ? arguments[0].labels[0].textContent : ''",
                                    inp
                                )
                                if not label:
                                    # Пробуем найти родительский элемент с текстом
                                    parent = inp.find_element(By.XPATH, "./..")
                                    label = parent.text.strip()
                                
                                answers.append({
                                    'input': inp,
                                    'text': label,
                                    'value': inp.get_attribute('value')
                                })
                            except:
                                pass
                        
                        questions.append({
                            'index': i,
                            'text': f"Вопрос {i + 1}",
                            'question_id': q_id,
                            'answers': answers
                        })
            
            logger.info(f"Найдено {len(questions)} вопросов")
            return questions
            
        except Exception as e:
            logger.error(f"Ошибка при получении вопросов: {e}")
            return []
    
    def _get_answers_from_element(self, question_element) -> List[Dict]:
        """Получение вариантов ответов из элемента вопроса"""
        answers = []
        
        try:
            # Ищем варианты ответов в элементе вопроса
            answer_elements = question_element.select(".answer, .option, label, input[type='radio'], input[type='checkbox']")
            
            for ans_elem in answer_elements:
                answer_text = ans_elem.get_text(strip=True)
                if answer_text:
                    answers.append({
                        'text': answer_text,
                        'element': ans_elem
                    })
            
            return answers
        except:
            return []
    
    def _answer_question(self, question: Dict, question_index: int):
        """Ответ на вопрос"""
        try:
            if self.strategy == 'random':
                self._answer_randomly(question)
            elif self.strategy == 'correct':
                self._answer_correctly(question)
            else:
                # По умолчанию случайный ответ
                self._answer_randomly(question)
                
        except Exception as e:
            logger.error(f"Ошибка при ответе на вопрос {question_index + 1}: {e}")
    
    def _answer_randomly(self, question: Dict):
        """Случайный ответ на вопрос"""
        try:
            answers = question.get('answers', [])
            if not answers:
                logger.warning("Варианты ответов не найдены")
                return
            
            # Если есть input элементы, кликаем на случайный
            if 'answers' in question and len(question['answers']) > 0:
                if 'input' in question['answers'][0]:
                    # Это input элементы
                    random_answer = random.choice(question['answers'])
                    input_elem = random_answer.get('input')
                    if input_elem:
                        self.driver.execute_script("arguments[0].click();", input_elem)
                        logger.info(f"Выбран случайный ответ: {random_answer.get('text', '')}")
                else:
                    # Это элементы с текстом
                    random_answer = random.choice(question['answers'])
                    elem = random_answer.get('element')
                    if elem:
                        # Пробуем найти связанный input
                        try:
                            input_elem = elem.find_element(By.CSS_SELECTOR, "input[type='radio'], input[type='checkbox']")
                            self.driver.execute_script("arguments[0].click();", input_elem)
                        except:
                            # Если input не найден, кликаем на сам элемент
                            self.driver.execute_script("arguments[0].click();", elem)
                        logger.info(f"Выбран случайный ответ: {random_answer.get('text', '')}")
            
        except Exception as e:
            logger.error(f"Ошибка при случайном ответе: {e}")
    
    def _answer_correctly(self, question: Dict):
        """Правильный ответ (если есть доступ к правильным ответам)"""
        # TODO: Реализовать логику получения правильных ответов
        # Пока используем случайный ответ
        logger.info("Режим 'correct' пока не реализован, используем случайный ответ")
        self._answer_randomly(question)
    
    def _submit_test(self) -> bool:
        """Отправка теста"""
        try:
            # Ищем кнопку отправки
            submit_selectors = [
                "button:contains('Отправить')",
                "button:contains('Завершить')",
                "button:contains('Submit')",
                "button:contains('Finish')",
                ".submit-test",
                "#submit-test",
                "input[type='submit']"
            ]
            
            for selector in submit_selectors:
                try:
                    buttons = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for button in buttons:
                        if button.is_displayed() and button.is_enabled():
                            button.click()
                            time.sleep(2)
                            logger.info("Тест отправлен")
                            return True
                except:
                    continue
            
            logger.warning("Кнопка отправки теста не найдена")
            return False
            
        except Exception as e:
            logger.error(f"Ошибка при отправке теста: {e}")
            return False
