"""Модуль для автоматического прохождения тестов"""
import os
import datetime
import time
import random
import re
from typing import Dict, List, Optional, Tuple
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from bs4 import BeautifulSoup
from synergy_lms.config import Config
from synergy_lms.logger import setup_logger
from synergy_lms.ai_providers import (
    AIChoiceRequest,
    AITextRequest,
    AIOrderRequest,
    AIMatchRequest,
    get_ai_provider,
)

logger = setup_logger(__name__)

_PHP_STATE_RE = re.compile(r"php\s*=\s*(\{[\s\S]*?\})\s*;")

class TestSolver:
    """Класс для автоматического прохождения тестов"""
    
    def __init__(self, driver: webdriver.Chrome):
        self.driver = driver
        self.wait = WebDriverWait(driver, Config.PAGE_LOAD_TIMEOUT)
        self.strategy = Config.TEST_STRATEGY
        self._test_frame_stack: List[int] = []
        self._ai_provider = None
        if self.strategy == "ai":
            try:
                self._ai_provider = get_ai_provider()
                # Быстрая проверка ключа/доступа, чтобы не падать на каждом вопросе
                self._warmup_ai_provider()
                logger.info(f"AI стратегия включена. Провайдер: {Config.AI_PROVIDER}")
            except Exception as e:
                logger.error(f"Не удалось инициализировать AI провайдера: {e}. Будет использоваться random.")
                self.strategy = "random"
                self._ai_provider = None

    def _warmup_ai_provider(self) -> None:
        """Делаем минимальный запрос к AI для раннего выявления неверного ключа/модели."""
        if not self._ai_provider:
            return
        try:
            _ = self._ai_provider.choose(
                AIChoiceRequest(
                    question="Проверка доступа. Выбери вариант 1.",
                    options=["OK", "NO"],
                    multi_select=False,
                )
            )
        except Exception as e:
            # Если ключ неверный, дальше смысла в AI нет — переключаемся на random
            msg = str(e)
            if "Incorrect API key" in msg or "invalid api key" in msg.lower():
                raise RuntimeError(
                    "AI не работает: неверный GROK_API_KEY. "
                    "Исправьте ключ в .env (GROK_API_KEY=...) и перезапустите."
                ) from e
            # Для остальных ошибок тоже фейлим ранним сообщением
            raise
    
    def solve_test(self, test_url: str, test_name: str, course_url: Optional[str] = None) -> Dict:
        """Автоматическое прохождение теста"""
        results = {
            'solved': False,
            'score': None,
            'attempts': 0,
            'error': None
        }
        
        try:
            logger.info(f"Начинаем прохождение теста: {test_name}")
            self._open_test(test_url=test_url, test_name=test_name, course_url=course_url)
            self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            time.sleep(3)

            # Часто перед тестом есть "идентификация/подтверждение" — без этого тест не появляется.
            self._pass_identification_if_needed()
            # Если идентификация не пройдена (страница всё ещё про камеру/согласие) — не пытаемся решать "тест"
            if self._is_identification_page():
                raise RuntimeError("Идентификация не пройдена: страница всё ещё в режиме камеры/согласия (doPhoto/doSave/startPlayerBtn).")
            
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

            # Выбираем лучший iframe/контекст, в котором реально живёт тестовый UI
            self._test_frame_stack = self._choose_best_test_frame()
            self._switch_to_frame_stack(self._test_frame_stack)
            
            # === Synergy assessments/training: один вопрос на страницу (form#player-assessments-form) ===
            if self._is_synergy_training_player():
                logger.info("Режим Synergy training player: решаем вопросы по одному на страницу")
                ok = self._solve_synergy_training_player()
                if not ok:
                    results["error"] = "Не удалось решить тест в режиме training player"
                    return results
                results["solved"] = True
                results["score"] = self._get_test_score()
                results["attempts"] = 1
                return results

            # Получаем вопросы
            questions = self._get_questions()
            logger.info(f"Найдено {len(questions)} вопросов")
            
            if not questions:
                logger.warning("Вопросы не найдены")
                self._dump_debug_html(prefix="no_questions")
                results['error'] = "Вопросы не найдены"
                return results
            
            # Отвечаем на вопросы
            for i, question in enumerate(questions):
                logger.info(f"Отвечаем на вопрос {i + 1}/{len(questions)}")
                self._switch_to_frame_stack(self._test_frame_stack)
                self._answer_question(question, i)
                time.sleep(1)  # Небольшая задержка между вопросами
            
            # Отправляем ответы
            self._switch_to_frame_stack(self._test_frame_stack)
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

    def _is_synergy_training_player(self) -> bool:
        """Детект режима /assessments/training/* где на странице один вопрос и форма player-assessments-form."""
        try:
            # У них обычно есть body.class assessments-training и #player form#player-assessments-form
            if self.driver.find_elements(By.CSS_SELECTOR, "form#player-assessments-form, #player form#player-assessments-form"):
                return True
        except Exception:
            pass
        try:
            html = (self.driver.page_source or "").lower()
            if "assessments/training" in html and "player-assessments-form" in html:
                return True
        except Exception:
            pass
        return False

    def _solve_synergy_training_player(self) -> bool:
        """Прохождение теста в режиме, где каждый вопрос — отдельная страница формы."""
        try:
            max_steps = 200
            for step in range(max_steps):
                self._switch_to_frame_stack(self._test_frame_stack)

                if self._check_test_completed():
                    return True

                # AJAX: страница может быть "оболочкой" с пустым #player — ждём пока появится форма вопроса
                if not self._wait_synergy_player_question_ready(timeout=12):
                    logger.warning("Synergy training: форма вопроса не появилась (возможно AJAX не успел/не сработал)")
                    self._dump_debug_html(prefix="synergy_training_player_not_ready")
                    return False

                qnum, qtotal = self._get_synergy_question_progress()
                q = self._extract_current_question_synergy()
                if not q:
                    logger.warning("Не удалось извлечь текущий вопрос (synergy training)")
                    self._dump_debug_html(prefix="synergy_training_no_question")
                    return False

                logger.info(f"Synergy training: вопрос {qnum}/{qtotal} тип={q.get('type')}")
                if (q.get("type") or "") == "unknown":
                    # чтобы можно было допилить обработку (dragdrop/order/нестандартные варианты)
                    self._dump_debug_html(prefix=f"synergy_training_unknown_q{qnum}")
                self._answer_question(q, max(0, qnum - 1))
                time.sleep(0.3)

                # После ответа — нажимаем "Ответить" (submit_send)
                before = qnum
                if not self._click_synergy_send_answer():
                    # Если нет "Ответить", попробуем "Сдать тест" (вдруг это последний экран)
                    if self._click_synergy_finish():
                        time.sleep(2)
                        return True
                    logger.warning("Кнопка 'Ответить' не найдена")
                    self._dump_debug_html(prefix="synergy_training_no_send_btn")
                    return False

                # Ждём перехода к следующему вопросу или результатов
                end = time.time() + 12
                while time.time() < end:
                    self._switch_to_frame_stack(self._test_frame_stack)
                    if self._check_test_completed():
                        return True
                    # Снова ждём, пока AJAX подгрузит новую форму
                    self._wait_synergy_player_question_ready(timeout=2)
                    now, _tot = self._get_synergy_question_progress()
                    if now != before:
                        break
                    time.sleep(0.5)

                # Если дошли до последнего вопроса — пробуем завершить
                if qtotal and qnum >= qtotal:
                    if self._click_synergy_finish():
                        time.sleep(3)
                        return True

            logger.warning("Synergy training: превышен лимит шагов")
            self._dump_debug_html(prefix="synergy_training_max_steps")
            return False
        except Exception as e:
            logger.error(f"Synergy training: ошибка: {e}")
            self._dump_debug_html(prefix="synergy_training_exception")
            return False

    def _wait_synergy_player_question_ready(self, timeout: int = 10) -> bool:
        """Ожидает появления формы текущего вопроса в training player (AJAX наполняет #player)."""
        try:
            self._switch_to_frame_stack(self._test_frame_stack)
        except Exception:
            pass
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "form#player-assessments-form"))
            )
            return True
        except Exception:
            pass
        # Иногда форма рендерится внутри #player, но селектор выше всё равно должен работать.
        # На всякий случай проверим, что #player не пустой.
        try:
            player = self.driver.find_elements(By.ID, "player")
            if player:
                inner = (player[0].get_attribute("innerHTML") or "").strip()
                if inner:
                    # есть контент, но форма могла быть не отрисована ещё — дадим короткую паузу
                    time.sleep(0.5)
                    return len(self.driver.find_elements(By.CSS_SELECTOR, "form#player-assessments-form")) > 0
        except Exception:
            pass
        return False

    def _get_synergy_question_progress(self) -> Tuple[int, int]:
        """Читает 'Вопрос N' и 'из M' из шапки."""
        n = 0
        total = 0
        try:
            el = self.driver.find_elements(By.CSS_SELECTOR, "span.player-questions")
            if el:
                txt = (el[0].text or "").strip()
                # "Вопрос 1"
                parts = [p for p in txt.split() if p.isdigit()]
                if parts:
                    n = int(parts[0])
        except Exception:
            pass
        try:
            el = self.driver.find_elements(By.CSS_SELECTOR, "span.test-sub-question")
            if el:
                txt = (el[0].text or "").strip()
                # "из 10"
                digits = [p for p in txt.split() if p.isdigit()]
                if digits:
                    total = int(digits[0])
        except Exception:
            pass
        # Fallback: php={"questionsCount":"10","item":1,...}
        if (not total) or (not n):
            try:
                st = self._get_synergy_php_state()
                if not total:
                    v = st.get("questionsCount")
                    if v is not None:
                        total = int(v)
                if not n:
                    v = st.get("item")
                    if v is not None:
                        n = int(v)
            except Exception:
                pass
        return n, total

    def _get_synergy_php_state(self) -> Dict:
        """Парсит inline js: php={...};"""
        try:
            html = self.driver.page_source or ""
            m = _PHP_STATE_RE.search(html)
            if not m:
                return {}
            import json
            obj = json.loads(m.group(1))
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}

    def _extract_current_question_synergy(self) -> Optional[Dict]:
        """Извлекает текущий вопрос и ответы из Synergy training player."""
        try:
            form = None
            forms = self.driver.find_elements(By.CSS_SELECTOR, "form#player-assessments-form")
            if forms:
                form = forms[0]
            if not form:
                return None

            # Текст вопроса
            q_text = ""
            try:
                q_el = self.driver.find_elements(By.CSS_SELECTOR, ".test-question-text-2")
                if q_el:
                    q_text = (q_el[0].text or "").strip()
            except Exception:
                pass
            q_text = q_text or "Вопрос"

            # Тип по php.questionType
            php_state = self._get_synergy_php_state()
            qtype = (php_state.get("questionType") or "").strip()

            # Текстовый ответ
            text_inputs = form.find_elements(By.CSS_SELECTOR, "textarea[name='answers'], input[type='text'][name='answers'], textarea, input[type='text']")
            if text_inputs and (qtype.lower() == "textentry" or qtype == ""):
                answers = [{"input": ti, "kind": "text"} for ti in text_inputs]
                return {"text": q_text, "type": "text", "answers": answers}

            # Выбор вариантов (radio/checkbox)
            choice_inputs = form.find_elements(By.CSS_SELECTOR, "input[type='radio'], input[type='checkbox']")
            if choice_inputs:
                answers = []
                for inp in choice_inputs:
                    label_txt = ""
                    try:
                        label_txt = self.driver.execute_script(
                            "return arguments[0].labels && arguments[0].labels[0] ? arguments[0].labels[0].textContent : ''",
                            inp,
                        ) or ""
                    except Exception:
                        label_txt = ""
                    if not label_txt:
                        try:
                            # часто label рядом
                            parent = inp.find_element(By.XPATH, "./..")
                            label_txt = (parent.text or "").strip()
                        except Exception:
                            label_txt = ""
                    answers.append({"input": inp, "text": (label_txt or "Вариант").strip(), "value": inp.get_attribute("value"), "kind": "choice"})
                return {"text": q_text, "type": "choice", "answers": answers}

            # Пока не видим ни текстовых полей, ни выбора — неизвестно
            return {"text": q_text, "type": "unknown", "answers": []}
        except Exception:
            return None

    def _click_synergy_send_answer(self) -> bool:
        """Жмёт кнопку 'Ответить' в форме (submit_send)."""
        try:
            # Селекторы из вашего HTML: input[name=submit_send].doSendBtn value="Ответить"
            btns = self.driver.find_elements(By.CSS_SELECTOR, "input[name='submit_send'].doSendBtn, input[name='submit_send'], .doSendBtn")
            for b in btns:
                try:
                    if b.is_displayed() and b.is_enabled():
                        self.driver.execute_script("arguments[0].click();", b)
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        # Фоллбэк по тексту/значению
        return self._click_by_text(["button", "a"], ["Ответить"])

    def _click_synergy_finish(self) -> bool:
        """Жмёт кнопку 'Сдать тест'."""
        try:
            btns = self.driver.find_elements(By.CSS_SELECTOR, "input.doFinishBtn, input[value*='Сдать']")
            for b in btns:
                try:
                    if b.is_displayed() and b.is_enabled():
                        self.driver.execute_script("arguments[0].click();", b)
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        return self._click_by_text(["button", "a"], ["Сдать тест", "Завершить тест", "Завершить"])

    def _open_test(self, test_url: str, test_name: str, course_url: Optional[str]) -> None:
        """Открыть тест. Если есть course_url — открываем тест кликом из курса (как в старом подходе)."""
        if course_url:
            try:
                logger.info(f"Открываем страницу курса для теста: {course_url}")
                self.driver.get(course_url)
                self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                time.sleep(2)

                def _try_click_xpath(xpath: str, label: str) -> bool:
                    try:
                        els = self.driver.find_elements(By.XPATH, xpath)
                        if not els:
                            logger.debug(f"Открытие теста: не найдено элементов ({label})")
                            return False
                        for el in els:
                            try:
                                self.driver.execute_script(
                                    "arguments[0].scrollIntoView({block:'center', inline:'nearest'});",
                                    el,
                                )
                                self.driver.execute_script("arguments[0].click();", el)
                                logger.info(f"Открытие теста: кликнули ({label})")
                                return True
                            except Exception:
                                continue
                        logger.debug(f"Открытие теста: элементы есть, но клик не удался ({label})")
                        return False
                    except Exception as e:
                        logger.debug(f"Открытие теста: ошибка при поиске ({label}): {e}")
                        return False

                # 1) Клик по ID из URL
                test_id = (test_url or "").split("/")[-1].split("?")[0]
                if test_id:
                    if _try_click_xpath(f"//a[contains(@href, '{test_id}')]", f"href содержит id={test_id}"):
                        time.sleep(2)
                        return

                # 2) Клик по полному URL (иногда href относительный, поэтому берём только хвост)
                if test_url:
                    tail = test_url.split("/")[-1].split("?")[0]
                    if tail and _try_click_xpath(f"//a[contains(@href, '{tail}')]", f"href содержит хвост url={tail}"):
                        time.sleep(2)
                        return
                    if _try_click_xpath(f"//a[contains(@href, '{test_url}')]", "href содержит полный url"):
                        time.sleep(2)
                        return

                # 3) Клик по названию (частичное)
                if test_name:
                    snippet = test_name[:40].replace("'", "")
                    if snippet and _try_click_xpath(f"//a[contains(., '{snippet}')]", f"текст ссылки содержит '{snippet}'"):
                        time.sleep(2)
                        return

                logger.info("Не удалось открыть тест кликом из курса — открываем URL напрямую")
            except Exception as e:
                logger.warning(f"Ошибка открытия теста из курса: {e}. Открываем URL напрямую.")

        self.driver.get(test_url)

    def _pass_identification_if_needed(self) -> None:
        """Проходит шаг(и) идентификации/подтверждения перед появлением теста."""
        # Если уже видим тестовые элементы — ничего не делаем
        if self._is_test_ui_present():
            return

        keywords = ["идентиф", "подтверд", "продолж", "далее", "соглас", "начать"]
        page = (self.driver.page_source or "").lower()
        if not any(k in page for k in keywords):
            return

        logger.info("Похоже, перед тестом есть шаг идентификации/подтверждения — пробуем пройти автоматически")
        
        # === ДЕТАЛЬНАЯ ДИАГНОСТИКА ===
        self._log_page_state("Начало идентификации")

        for attempt in range(6):
            # Специальный флоу "камера → подготовить снимок → пройти идентификацию → перейти к тесту"
            # Пробуем найти #doPhoto с увеличенным таймаутом (элемент может загружаться)
            logger.info(f"Идентификация: попытка {attempt + 1}/6 — ищем #doPhoto...")
            
            # Сначала пробуем найти в default_content
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass
            
            do_photo_found = False
            in_learning_frame = False
            
            # 1) Прямой поиск в default_content с ожиданием
            try:
                WebDriverWait(self.driver, 2).until(
                    EC.presence_of_element_located((By.ID, "doPhoto"))
                )
                do_photo_found = True
                logger.info("Идентификация: #doPhoto найден в default_content")
            except TimeoutException:
                logger.debug("Идентификация: #doPhoto НЕ найден в default_content")
            
            # 2) Явно переключаемся в iframe learningFrame (основной iframe LMS)
            if not do_photo_found:
                try:
                    self.driver.switch_to.default_content()
                    # Ждём появления iframe
                    learning_frame = WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((By.ID, "learningFrame"))
                    )
                    self.driver.switch_to.frame(learning_frame)
                    in_learning_frame = True
                    logger.info("Идентификация: переключились в iframe learningFrame")
                    
                    # Ждём загрузки контента внутри iframe
                    time.sleep(2)
                    
                    # Ищем doPhoto внутри iframe
                    try:
                        WebDriverWait(self.driver, 5).until(
                            EC.presence_of_element_located((By.ID, "doPhoto"))
                        )
                        do_photo_found = True
                        logger.info("Идентификация: #doPhoto найден внутри learningFrame")
                    except TimeoutException:
                        logger.info("Идентификация: #doPhoto НЕ найден внутри learningFrame")
                        # Логируем что есть внутри iframe
                        try:
                            html_snippet = self.driver.execute_script("return document.body ? document.body.innerHTML.substring(0, 500) : 'no body'")
                            logger.debug(f"[DEBUG] HTML внутри learningFrame: {html_snippet[:300]}...")
                        except Exception:
                            pass
                except Exception as e:
                    logger.debug(f"Идентификация: ошибка при переключении в learningFrame: {e}")
            
            # 3) Если всё ещё не найден — общий поиск по всем iframe
            if not do_photo_found:
                try:
                    self.driver.switch_to.default_content()
                except Exception:
                    pass
                frame_stack = self._find_element_any_frame(By.ID, "doPhoto", timeout=3)
                if frame_stack is not None:
                    do_photo_found = True
                    in_learning_frame = False  # будем использовать frame_stack
                    logger.info(f"Идентификация: #doPhoto найден во фрейме {frame_stack}")
                    self._switch_to_frame_stack(frame_stack)
            
            if do_photo_found:
                # Мы уже в нужном фрейме (learningFrame или из frame_stack)
                try:
                    # Кликаем напрямую, т.к. уже в нужном контексте
                    el = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable((By.ID, "doPhoto"))
                    )
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                    self.driver.execute_script("arguments[0].click();", el)
                    logger.info("Идентификация: Подготовить снимок (#doPhoto) — клик выполнен")
                    logger.info("[DEBUG] Успешно кликнули #doPhoto, ждём 2 сек...")
                except Exception as e:
                    logger.warning(f"Идентификация: не удалось кликнуть #doPhoto: {e}")
                    time.sleep(1)
                    continue
                    
                # ждём появления блока с фото (secondTable)
                time.sleep(2)
                
                # Логируем состояние после клика doPhoto
                self._log_page_state("После клика #doPhoto")
                
                # Отмечаем согласие — кастомный чекбокс! Кликаем по иконке внутри label.
                agree_result = self._click_agree_checkbox()
                logger.info(f"[DEBUG] Результат клика по чекбоксу: {agree_result}")
                time.sleep(1)
                
                # Логируем состояние после галочки
                self._log_page_state("После галочки согласия")
                
                # теперь должна появиться кнопка doSave ("Пройти идентификацию")
                # Кликаем напрямую в текущем контексте (мы на странице identcamera, без iframe)
                try:
                    do_save = WebDriverWait(self.driver, 10).until(
                        EC.element_to_be_clickable((By.ID, "doSave"))
                    )
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", do_save)
                    self.driver.execute_script("arguments[0].click();", do_save)
                    logger.info("Идентификация: Пройти идентификацию (#doSave) — клик выполнен")
                    logger.info("[DEBUG] Успешно кликнули #doSave, ждём 2 сек...")
                except Exception as e:
                    logger.warning(f"Идентификация: не удалось кликнуть #doSave: {e}")
                    self._log_page_state("Ошибка #doSave")
                    time.sleep(1)
                    continue
                    
                time.sleep(2)
                
                # Логируем состояние после doSave
                self._log_page_state("После клика #doSave")
                
                # и после этого становится доступной кнопка перейти к тесту
                # Она может появиться на той же странице или после редиректа
                try:
                    # Сначала ждём появления кнопки (может быть редирект)
                    start_btn = WebDriverWait(self.driver, 15).until(
                        EC.element_to_be_clickable((By.ID, "startPlayerBtn"))
                    )
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", start_btn)
                    self.driver.execute_script("arguments[0].click();", start_btn)
                    logger.info("Идентификация: Перейти к тесту (#startPlayerBtn) — клик выполнен")
                    logger.info("[DEBUG] Успешно кликнули #startPlayerBtn")
                except TimeoutException:
                    # Возможно кнопка в iframe или на другой странице
                    logger.info("Идентификация: #startPlayerBtn не найден в default_content, проверяем iframe...")
                    try:
                        self.driver.switch_to.default_content()
                        learning_frame = self.driver.find_elements(By.ID, "learningFrame")
                        if learning_frame:
                            self.driver.switch_to.frame(learning_frame[0])
                            start_btn = WebDriverWait(self.driver, 10).until(
                                EC.element_to_be_clickable((By.ID, "startPlayerBtn"))
                            )
                            self.driver.execute_script("arguments[0].click();", start_btn)
                            logger.info("Идентификация: Перейти к тесту (#startPlayerBtn) — клик в iframe")
                    except Exception as e2:
                        logger.warning(f"Идентификация: не удалось кликнуть #startPlayerBtn: {e2}")
                        self._log_page_state("Ошибка #startPlayerBtn")
                        time.sleep(1)
                        continue
                except Exception as e:
                    logger.warning(f"Идентификация: не удалось кликнуть #startPlayerBtn: {e}")
                    self._log_page_state("Ошибка #startPlayerBtn")
                    time.sleep(1)
                    continue
                    
                time.sleep(2)
                
                # После startPlayerBtn может появиться модальное окно с кнопкой "Перейти к тесту"
                self._click_modal_start_test()

                # После модалки ждём, что появится UI теста (или хотя бы inputs) в каком-то контексте
                try:
                    end = time.time() + 10
                    while time.time() < end:
                        if self._is_test_ui_present():
                            break
                        time.sleep(0.5)
                except Exception:
                    pass
                
                # после перехода к тесту цикл можно завершать
                logger.info("Идентификация: успешно пройдена")
                return
            else:
                logger.info("Идентификация: #doPhoto не найден, пробуем альтернативные кнопки...")
                self._log_page_state("doPhoto не найден")

            try:
                if self._click_if_present(
                    By.XPATH,
                    "/html/body/div[1]/div[7]/div[4]/table/tbody/tr[4]/td/a",
                    label="Идентификация: подтверждение снимка (XPath div[7]/div[4]/.../tr[4]/td/a)",
                ):
                    time.sleep(2)
                    continue
            except Exception:
                pass

            try:
                if self._click_if_present(By.ID, "startPlayerBtn", label="Идентификация: Перейти к тесту (#startPlayerBtn)"):
                    time.sleep(2)
                    continue
            except Exception:
                pass

            # Отмечаем возможные чекбоксы согласия
            try:
                checks = self.driver.find_elements(By.XPATH, "//input[@type='checkbox']")
                for c in checks:
                    try:
                        if c.is_displayed() and not c.is_selected():
                            self.driver.execute_script("arguments[0].click();", c)
                    except Exception:
                        continue
            except Exception:
                pass

            # Кликаем кнопки/ссылки по тексту (наиболее частые)
            clicked = (
                self._click_by_text(["button", "a"], ["Пройти идентификацию", "Идентификация", "Подтвердить личность"])
                or self._click_by_text(["button", "a"], ["Согласен", "Согласна", "Принять", "Подтвердить"])
                or self._click_by_text(["button", "a"], ["Продолжить", "Далее", "Перейти к тесту", "Начать"])
            )

            if clicked:
                time.sleep(2)
            else:
                # если ничего не нашли — выходим, чтобы не зависнуть
                return

        return

    def _click_agree_checkbox(self, stay_in_frame: bool = True) -> bool:
        """Клик по кастомному чекбоксу согласия (agreePhoto).
        
        На сайте чекбокс стилизован через <label><input id='agreePhoto'><i class='icon'>...</i>...</label>.
        Кликать нужно по иконке <i>, а не по скрытому input.
        
        Args:
            stay_in_frame: если True, не переключаем контекст (предполагаем что уже в нужном фрейме)
        """
        logger.info("[DEBUG agree] Начинаем клик по чекбоксу согласия...")
        
        # Если не в режиме "оставаться в фрейме", ищем элемент
        if not stay_in_frame:
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass
            
            # Пробуем найти и переключиться во фрейм, если элемент там
            frame_stack = self._find_element_any_frame(By.ID, "agreePhoto", timeout=5)
            if frame_stack:
                logger.info(f"[DEBUG agree] agreePhoto найден во фрейме {frame_stack}")
                self._switch_to_frame_stack(frame_stack)
        
        # Проверяем наличие элемента в текущем контексте
        try:
            els = self.driver.find_elements(By.ID, "agreePhoto")
            if els:
                logger.info(f"[DEBUG agree] agreePhoto найден, displayed={els[0].is_displayed()}")
            else:
                logger.info("[DEBUG agree] agreePhoto НЕ найден в текущем контексте!")
                return False
        except Exception as e:
            logger.info(f"[DEBUG agree] Ошибка поиска agreePhoto: {e}")
        
        # 1) Сначала проверяем — если чекбокс уже отмечен, ничего не делаем
        try:
            cb = self.driver.find_element(By.ID, "agreePhoto")
            is_sel = cb.is_selected()
            logger.info(f"[DEBUG agree] agreePhoto.is_selected() = {is_sel}")
            if is_sel:
                logger.info("Идентификация: согласие уже отмечено")
                return True
        except Exception as e:
            logger.info(f"[DEBUG agree] Ошибка проверки is_selected: {e}")
        
        # 2) Кликаем по иконке внутри label (XPath из пользовательского запроса)
        icon_xpaths = [
            "//*[@id='photo-tbl']/tbody/tr[3]/td/label/i",           # точный XPath от пользователя
            "//label[.//input[@id='agreePhoto']]/i",                 # универсальный: label содержащий input#agreePhoto -> i
            "//label[.//input[@id='agreePhoto']]//i[@class]",        # иконка с классом внутри label
            "//input[@id='agreePhoto']/following-sibling::i",        # i сразу после input
        ]
        for xpath in icon_xpaths:
            try:
                icons = self.driver.find_elements(By.XPATH, xpath)
                logger.debug(f"[DEBUG agree] XPath '{xpath}' нашёл {len(icons)} элементов")
                if icons:
                    icon = icons[0]
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", icon)
                    self.driver.execute_script("arguments[0].click();", icon)
                    logger.info(f"Идентификация: согласие (клик по иконке) — {xpath}")
                    return True
            except Exception as e:
                logger.debug(f"[DEBUG agree] Ошибка при клике по XPath '{xpath}': {e}")
                continue
        
        # 3) Кликаем по самому label
        try:
            labels = self.driver.find_elements(By.XPATH, "//label[.//input[@id='agreePhoto']]")
            logger.debug(f"[DEBUG agree] Найдено {len(labels)} label с agreePhoto внутри")
            if labels:
                self.driver.execute_script("arguments[0].click();", labels[0])
                logger.info("Идентификация: согласие (клик по label)")
                return True
        except Exception as e:
            logger.debug(f"[DEBUG agree] Ошибка клика по label: {e}")
        
        # 4) Фоллбэк: кликаем по input напрямую (на случай если стиль изменился)
        try:
            cb = self.driver.find_element(By.ID, "agreePhoto")
            if cb and not cb.is_selected():
                self.driver.execute_script("arguments[0].click();", cb)
                logger.info("Идентификация: согласие (клик по input#agreePhoto)")
                return True
        except Exception as e:
            logger.debug(f"[DEBUG agree] Ошибка клика по input: {e}")
        
        logger.warning("Идентификация: не удалось кликнуть по чекбоксу согласия")
        return False

    def _click_modal_start_test(self) -> bool:
        """Клик по кнопке 'Перейти к тесту' в модальном окне (mc-modal).
        
        Модальное окно появляется после идентификации с предупреждениями и кнопкой начала теста.
        """
        logger.info("[DEBUG modal] Проверяем наличие модального окна...")
        
        try:
            self.driver.switch_to.default_content()
        except Exception:
            pass
        
        # Ждём появления модального окна (до 5 сек)
        modal_selectors = [
            # По onclick
            "a[onclick*='startTesting']",
            # По классу кнопки
            ".mc-modal-button",
            ".mc-modal-testing-buttons a",
            # По полному пути
            "div.mc-modal-wrapper .mc-modal-testing-buttons a",
            # По тексту через XPath
        ]
        
        for selector in modal_selectors:
            try:
                btn = WebDriverWait(self.driver, 3).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                )
                if btn:
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                    self.driver.execute_script("arguments[0].click();", btn)
                    logger.info(f"Идентификация: Модальное окно — клик по '{selector}'")
                    time.sleep(2)
                    return True
            except TimeoutException:
                continue
            except Exception as e:
                logger.debug(f"[DEBUG modal] Ошибка при клике по '{selector}': {e}")
                continue
        
        # Пробуем XPath по тексту
        try:
            btn = self.driver.find_element(By.XPATH, "//a[contains(., 'Перейти к тесту')]")
            if btn and btn.is_displayed():
                self.driver.execute_script("arguments[0].click();", btn)
                logger.info("Идентификация: Модальное окно — клик по XPath 'Перейти к тесту'")
                time.sleep(2)
                return True
        except Exception:
            pass
        
        # Проверяем, может модальное окно в iframe
        try:
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            for i, frame in enumerate(iframes):
                try:
                    self.driver.switch_to.default_content()
                    self.driver.switch_to.frame(frame)
                    btn = self.driver.find_elements(By.CSS_SELECTOR, "a[onclick*='startTesting'], .mc-modal-button")
                    if btn:
                        self.driver.execute_script("arguments[0].click();", btn[0])
                        logger.info(f"Идентификация: Модальное окно — клик в iframe[{i}]")
                        time.sleep(2)
                        return True
                except Exception:
                    continue
                finally:
                    try:
                        self.driver.switch_to.default_content()
                    except Exception:
                        pass
        except Exception:
            pass
        
        logger.info("[DEBUG modal] Модальное окно не найдено или уже закрыто")
        return False

    def _log_page_state(self, context: str) -> None:
        """Логирует детальное состояние страницы для отладки идентификации."""
        try:
            self.driver.switch_to.default_content()
        except Exception:
            pass
        
        try:
            url = self.driver.current_url
            logger.info(f"[DEBUG {context}] URL: {url}")
        except Exception as e:
            logger.info(f"[DEBUG {context}] URL: ошибка получения - {e}")
        
        # Ищем ключевые элементы в default_content
        key_ids = ["doPhoto", "doSave", "agreePhoto", "startPlayerBtn", "video", "canvas", "photo-tbl", "secondTable"]
        found_in_default = []
        for eid in key_ids:
            try:
                els = self.driver.find_elements(By.ID, eid)
                if els:
                    el = els[0]
                    displayed = el.is_displayed() if el else False
                    tag = el.tag_name if el else "?"
                    found_in_default.append(f"{eid}(tag={tag}, displayed={displayed})")
            except Exception:
                pass
        
        if found_in_default:
            logger.info(f"[DEBUG {context}] Элементы в default_content: {', '.join(found_in_default)}")
        else:
            logger.info(f"[DEBUG {context}] Ключевые элементы в default_content НЕ найдены")
        
        # Список iframe
        try:
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            if iframes:
                iframe_info = []
                for i, f in enumerate(iframes):
                    try:
                        src = f.get_attribute("src") or "(no src)"
                        fid = f.get_attribute("id") or "(no id)"
                        iframe_info.append(f"[{i}] id={fid}, src={src[:80]}")
                    except Exception:
                        iframe_info.append(f"[{i}] (ошибка)")
                logger.info(f"[DEBUG {context}] Найдено {len(iframes)} iframe: {'; '.join(iframe_info)}")
            else:
                logger.info(f"[DEBUG {context}] iframe на странице НЕТ")
        except Exception as e:
            logger.info(f"[DEBUG {context}] Ошибка при поиске iframe: {e}")
        
        # Проверяем внутри каждого iframe
        for i in range(len(iframes) if 'iframes' in dir() else 0):
            try:
                self.driver.switch_to.default_content()
                self.driver.switch_to.frame(i)
                found_in_frame = []
                for eid in key_ids:
                    try:
                        els = self.driver.find_elements(By.ID, eid)
                        if els:
                            el = els[0]
                            displayed = el.is_displayed() if el else False
                            found_in_frame.append(f"{eid}(displayed={displayed})")
                    except Exception:
                        pass
                if found_in_frame:
                    logger.info(f"[DEBUG {context}] В iframe[{i}] найдены: {', '.join(found_in_frame)}")
            except Exception:
                pass
            finally:
                try:
                    self.driver.switch_to.default_content()
                except Exception:
                    pass

    def _is_identification_page(self) -> bool:
        """Детект страницы фото-идентификации, чтобы не путать её с тестом."""
        try:
            html = (self.driver.page_source or "").lower()
            if "сделайте удачную фотографию" in html:
                return True
        except Exception:
            pass
        # По ключевым элементам (в т.ч. внутри iframe)
        return (
            self._element_exists(By.ID, "doPhoto", any_frame=True)
            or self._element_exists(By.ID, "doSave", any_frame=True)
            or self._element_exists(By.ID, "agreePhoto", any_frame=True)
            or self._element_exists(By.ID, "startPlayerBtn", any_frame=True)
            or self._element_exists(By.ID, "video", any_frame=True)
            or self._element_exists(By.ID, "canvas", any_frame=True)
        )

    def _element_exists(self, by: By, locator: str, any_frame: bool = False) -> bool:
        try:
            if not any_frame:
                return len(self.driver.find_elements(by, locator)) > 0
            found = self._find_element_any_frame(by, locator, timeout=0)
            return found is not None
        except Exception:
            return False

    def _wait_and_click(self, by: By, locator: str, label: str, timeout: int = 10) -> None:
        """Подождать элемент и кликнуть (через JS). Бросает исключение при таймауте."""
        # Ищем элемент в default_content или внутри iframe
        found = self._find_element_any_frame(by, locator, timeout=timeout)
        if not found:
            raise TimeoutException(f"Не найден элемент для клика: {locator}")
        frame_stack = found
        self._switch_to_frame_stack(frame_stack)
        el = WebDriverWait(self.driver, timeout).until(EC.presence_of_element_located((by, locator)))
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        except Exception:
            pass
        try:
            # Если это checkbox — не "снимать" если уже выбран
            try:
                tag = (el.tag_name or "").lower()
                typ = (el.get_attribute("type") or "").lower()
                if tag == "input" and typ == "checkbox" and el.is_selected():
                    logger.info(label + " (уже отмечено)")
                    return
            except Exception:
                pass
            self.driver.execute_script("arguments[0].click();", el)
        except Exception:
            el.click()
        logger.info(label)

    def _switch_to_frame_stack(self, stack: List[int]) -> None:
        """Переключиться в нужную цепочку iframe (по индексам)."""
        self.driver.switch_to.default_content()
        for idx in stack:
            self.driver.switch_to.frame(idx)

    def _find_element_any_frame(self, by: By, locator: str, timeout: int = 0) -> Optional[List[int]]:
        """Найти, в каком iframe находится элемент. Возвращает список индексов (stack) или None.

        Ограничиваем глубину 2 (iframe + вложенный iframe), этого обычно достаточно для LMS.
        """
        end_time = time.time() + max(0, timeout)

        def _search_in_current(depth: int, stack: List[int]) -> Optional[List[int]]:
            try:
                if self.driver.find_elements(by, locator):
                    return list(stack)
            except Exception:
                pass
            if depth >= 2:
                return None
            try:
                frames = self.driver.find_elements(By.TAG_NAME, "iframe")
            except Exception:
                frames = []
            for i in range(len(frames)):
                try:
                    self.driver.switch_to.frame(i)
                    res = _search_in_current(depth + 1, stack + [i])
                    if res is not None:
                        return res
                except Exception:
                    pass
                finally:
                    try:
                        self.driver.switch_to.parent_frame()
                    except Exception:
                        try:
                            self.driver.switch_to.default_content()
                            for idx in stack:
                                self.driver.switch_to.frame(idx)
                        except Exception:
                            pass
            return None

        while True:
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass
            found = _search_in_current(0, [])
            if found is not None:
                return found
            if timeout <= 0 or time.time() >= end_time:
                return None
            time.sleep(0.3)

    def _click_if_present(self, by: By, locator: str, label: str) -> bool:
        """Безопасно кликает по элементу, если он есть и видим."""
        try:
            els = self.driver.find_elements(by, locator)
            if not els:
                return False
            for el in els:
                try:
                    if not el.is_displayed():
                        continue
                    # Если это чекбокс — кликаем только если не выбран
                    try:
                        tag = (el.tag_name or "").lower()
                        typ = (el.get_attribute("type") or "").lower()
                        if tag == "input" and typ == "checkbox":
                            if el.is_selected():
                                return True
                    except Exception:
                        pass
                    self.driver.execute_script(
                        "arguments[0].scrollIntoView({block:'center', inline:'nearest'});",
                        el,
                    )
                    self.driver.execute_script("arguments[0].click();", el)
                    logger.info(label)
                    return True
                except Exception:
                    continue
            return False
        except Exception:
            return False

    def _is_test_ui_present(self) -> bool:
        """Грубый детект: на странице уже есть вопросы/варианты."""
        try:
            if self.driver.find_elements(By.CSS_SELECTOR, "input[type='radio'], input[type='checkbox']"):
                return True
        except Exception:
            pass
        try:
            txt = (self.driver.page_source or "").lower()
            if "вопрос" in txt and ("radio" in txt or "checkbox" in txt):
                return True
        except Exception:
            pass
        return False

    def _click_by_text(self, tags: List[str], texts: List[str]) -> bool:
        """Клик по элементу (button/a) содержащему один из текстов. Selenium CSS :contains НЕ поддерживает."""
        # Пробуем в default_content и во всех iframe (глубина 2)
        stacks = self._iter_frame_stacks(max_depth=2)
        for stack in stacks:
            try:
                self._switch_to_frame_stack(stack)
            except Exception:
                continue
            for t in texts:
                # 1) button/a содержит текст
                for tag in tags:
                    try:
                        el = self.driver.find_element(By.XPATH, f"//{tag}[contains(normalize-space(.), '{t}')]")
                        if el and el.is_displayed() and el.is_enabled():
                            self.driver.execute_script("arguments[0].click();", el)
                            return True
                    except Exception:
                        pass
                # 2) input[type=submit/button] value содержит текст
                try:
                    el = self.driver.find_element(
                        By.XPATH,
                        f"//input[(@type='submit' or @type='button') and contains(@value, '{t}')]",
                    )
                    if el and el.is_displayed() and el.is_enabled():
                        self.driver.execute_script("arguments[0].click();", el)
                        return True
                except Exception:
                    pass
        return False

    def _iter_frame_stacks(self, max_depth: int = 2) -> List[List[int]]:
        """Все варианты переключения в iframe (default + глубина до max_depth)."""
        stacks: List[List[int]] = [[]]
        try:
            self.driver.switch_to.default_content()
            frames_lvl1 = self.driver.find_elements(By.TAG_NAME, "iframe")
        except Exception:
            frames_lvl1 = []

        for i in range(len(frames_lvl1)):
            stacks.append([i])
            if max_depth >= 2:
                try:
                    self.driver.switch_to.default_content()
                    self.driver.switch_to.frame(i)
                    frames_lvl2 = self.driver.find_elements(By.TAG_NAME, "iframe")
                except Exception:
                    frames_lvl2 = []
                finally:
                    try:
                        self.driver.switch_to.default_content()
                    except Exception:
                        pass
                for j in range(len(frames_lvl2)):
                    stacks.append([i, j])
        return stacks

    def _choose_best_test_frame(self) -> List[int]:
        """Выбирает iframe-контекст, где больше всего признаков теста (вопросы/варианты)."""
        best_stack: List[int] = []
        best_score = -1
        for stack in self._iter_frame_stacks(max_depth=2):
            try:
                self._switch_to_frame_stack(stack)
            except Exception:
                continue
            score = 0
            try:
                score += len(self.driver.find_elements(By.CSS_SELECTOR, "input[type='radio'], input[type='checkbox']")) * 3
            except Exception:
                pass
            try:
                html = (self.driver.page_source or "").lower()
                if "вопрос" in html:
                    score += 2
                if "test" in html or "quiz" in html:
                    score += 1
            except Exception:
                pass
            try:
                # доп. признак: есть контейнеры вопросов
                score += len(self.driver.find_elements(By.CSS_SELECTOR, ".question, .test-question, .question-item, [data-question-id]"))
            except Exception:
                pass
            if score > best_score:
                best_score = score
                best_stack = stack

        try:
            self.driver.switch_to.default_content()
        except Exception:
            pass
        logger.info(f"[DEBUG] Выбран контекст теста (iframe stack): {best_stack}, score={best_score}")
        return best_stack
    
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
            # В Selenium нет CSS :contains(), поэтому кликаем по тексту через XPath.
            if self._click_by_text(["button", "a"], ["Начать тест", "Пройти тест", "Начать", "Пройти", "Start", "Begin"]):
                time.sleep(2)
                logger.info("Тест начат")
                return True
            
            # Если кнопки не найдены, возможно тест уже начат
            logger.info("Кнопка начала теста не найдена, возможно тест уже начат")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка при начале теста: {e}")
            return False
    
    def _get_questions(self) -> List[Dict]:
        """Получение списка вопросов теста (расширенные селекторы и динамическая разметка)."""
        questions: List[Dict] = []

        try:
            # Держимся выбранного контекста теста
            self._switch_to_frame_stack(self._test_frame_stack)

            # 1) Ищем контейнеры вопросов через Selenium (чтобы видеть динамический DOM).
            container_selectors = [
                ".question", ".test-question", ".question-item", ".question-block",
                "[data-question-id]", ".mc-question", ".mc-quiz-question",
                ".quiz-question", ".question__container", ".question-content",
                ".mc-modal-question", ".mc-question-block", "form.question"
            ]

            containers = []
            for sel in container_selectors:
                try:
                    found = self.driver.find_elements(By.CSS_SELECTOR, sel)
                    if found:
                        containers.extend(found)
                except Exception:
                    continue

            # Удаляем дубликаты по id/тексту
            seen = set()
            unique_containers = []
            for el in containers:
                key = (el.get_attribute("id") or "") + (el.text or "")[:80]
                if key in seen:
                    continue
                seen.add(key)
                unique_containers.append(el)

            for i, el in enumerate(unique_containers):
                q_text = (el.text or "").strip()
                answers, q_type = self._extract_answers_from_web_element(el)
                questions.append({
                    "index": i,
                    "text": q_text if q_text else f"Вопрос {i + 1}",
                    "type": q_type,
                    "answers": answers,
                    "selenium_element": el,
                })

            # 2) Fallback: если ничего не нашли, группируем radio/checkbox по name.
            if not questions:
                radio_inputs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='radio'], input[type='checkbox']")
                if radio_inputs:
                    question_groups = {}
                    for inp in radio_inputs:
                        qid = inp.get_attribute('name') or inp.get_attribute('data-question-id') or 'unknown'
                        question_groups.setdefault(qid, []).append(inp)

                    for i, (q_id, inputs) in enumerate(question_groups.items()):
                        answers = []
                        for inp in inputs:
                            try:
                                label = self.driver.execute_script(
                                    "return arguments[0].labels && arguments[0].labels[0] ? arguments[0].labels[0].textContent : ''",
                                    inp
                                )
                                if not label:
                                    parent = inp.find_element(By.XPATH, "./..")
                                    label = parent.text.strip()
                                answers.append({
                                    "input": inp,
                                    "text": label,
                                    "value": inp.get_attribute("value"),
                                    "kind": "choice",
                                })
                            except Exception:
                                pass

                        questions.append({
                            "index": i,
                            "text": f"Вопрос {i + 1}",
                            "question_id": q_id,
                            "type": "choice",
                            "answers": answers,
                        })

            logger.info(f"Найдено {len(questions)} вопросов")
            return questions

        except Exception as e:
            logger.error(f"Ошибка при получении вопросов: {e}")
            return []

    def _extract_answers_from_web_element(self, question_el) -> (List[Dict], str):
        """Достаёт варианты ответа из Selenium-элемента вопроса, определяет тип вопроса."""
        answers: List[Dict] = []
        q_type = "choice"

        try:
            # 1) Варианты как radio/checkbox.
            choice_inputs = question_el.find_elements(By.CSS_SELECTOR, "input[type='radio'], input[type='checkbox']")
            if choice_inputs:
                for inp in choice_inputs:
                    try:
                        label = self.driver.execute_script(
                            "return arguments[0].labels && arguments[0].labels[0] ? arguments[0].labels[0].textContent : ''",
                            inp
                        ) or ""
                        if not label:
                            try:
                                parent = inp.find_element(By.XPATH, "./..")
                                label = parent.text.strip()
                            except Exception:
                                label = ""
                        answers.append({
                            "input": inp,
                            "text": label.strip() or "Вариант",
                            "value": inp.get_attribute("value"),
                            "kind": "choice",
                        })
                    except Exception:
                        continue
                return answers, "choice"

            # 2) Кнопки/дивы вариантов без input.
            button_opts = question_el.find_elements(By.CSS_SELECTOR, ".answer, .option, .variant, .mc-answer, .mc-option, button, label")
            clickable_opts = []
            for opt in button_opts:
                text = (opt.text or "").strip()
                if not text:
                    continue
                clickable_opts.append({
                    "element": opt,
                    "text": text,
                    "kind": "choice-click",
                })
            if clickable_opts:
                return clickable_opts, "choice-click"

            # 3) Текстовые поля.
            text_inputs = question_el.find_elements(By.CSS_SELECTOR, "input[type='text'], textarea")
            if text_inputs:
                answers = [{"input": ti, "kind": "text"} for ti in text_inputs]
                return answers, "text"

            # 4) Drag & drop / matching.
            drag_sources = question_el.find_elements(
                By.CSS_SELECTOR,
                "[draggable='true'], .drag, .draggable, .mc-drag, [data-answer-id], .ui-sortable-handle",
            )
            drop_targets = question_el.find_elements(By.CSS_SELECTOR, ".drop, .target, .mc-drop, .droppable, [data-target]")

            # 4a) matching: источники + явные цели
            if drag_sources and drop_targets:
                answers = [{"source": s, "text": (s.text or "").strip(), "kind": "drag-source"} for s in drag_sources]
                targets = [{"target": t, "text": (t.text or "").strip(), "kind": "drag-target"} for t in drop_targets]
                return answers + targets, "dragdrop"

            # 4b) order/sort: есть draggable элементы, но нет целей (нужно упорядочить внутри списка)
            if drag_sources and not drop_targets:
                answers = [{"item": s, "text": (s.text or "").strip(), "kind": "order-item"} for s in drag_sources]
                return answers, "order"

            # 5) Фолбэк: просто текст вопроса.
            q_type = "unknown"
            return answers, q_type

        except Exception:
            return answers, q_type
    
    def _answer_question(self, question: Dict, question_index: int):
        """Ответ на вопрос"""
        try:
            q_type = question.get("type") or "choice"

            if q_type == "text":
                self._answer_text_question(question)
                return

            if q_type == "dragdrop":
                self._answer_dragdrop_question(question)
                return

            if q_type == "order":
                self._answer_order_question(question)
                return

            # Все варианты выбора (radio/checkbox/кнопки)
            if self.strategy == 'random':
                self._answer_randomly(question)
            elif self.strategy == 'correct':
                self._answer_correctly(question)
            elif self.strategy == 'ai':
                self._answer_with_ai(question)
            else:
                # По умолчанию случайный ответ
                self._answer_randomly(question)
                
        except Exception as e:
            logger.error(f"Ошибка при ответе на вопрос {question_index + 1}: {e}")

    def _answer_with_ai(self, question: Dict):
        """Ответ на вопрос через AI (fallback на random при ошибке)."""
        try:
            if not self._ai_provider:
                logger.warning("AI провайдер не инициализирован, используем random")
                return self._answer_randomly(question)

            answers = question.get("answers", [])
            if not answers:
                logger.warning("Варианты ответов не найдены")
                return

            # Поддерживаем input и кликабельные элементы
            has_inputs = isinstance(answers, list) and len(answers) > 0 and isinstance(answers[0], dict) and "input" in answers[0]
            has_click = isinstance(answers, list) and len(answers) > 0 and isinstance(answers[0], dict) and "element" in answers[0]
            if not (has_inputs or has_click):
                logger.warning("AI режим поддержан только для вопросов с input или кликабельными вариантами. Используем random.")
                return self._answer_randomly(question)

            option_texts = [str(a.get("text") or "").strip() for a in answers]
            option_texts = [t if t else f"Вариант {i+1}" for i, t in enumerate(option_texts)]

            # Определяем режим выбора (radio/checkbox)
            multi = False
            try:
                if has_inputs:
                    input_type = (answers[0]["input"].get_attribute("type") or "").lower()
                    multi = input_type == "checkbox"
            except Exception:
                pass

            q_text = str(question.get("text") or "").strip()
            if not q_text or q_text.startswith("Вопрос "):
                # Часто в таком режиме вопроса нет текста — попробуем вытащить хоть что-то из DOM рядом
                try:
                    q_text = self.driver.execute_script("return document.body.innerText || ''")[:400]
                except Exception:
                    q_text = "Выберите правильный вариант."

            req = AIChoiceRequest(question=q_text, options=option_texts, multi_select=multi)
            resp = self._ai_provider.choose(req)
            if not resp.choices:
                logger.warning("AI не вернул choices, используем random")
                return self._answer_randomly(question)

            # Нормализуем choices (1-based → фильтруем диапазон)
            selected = []
            for c in resp.choices:
                try:
                    c_int = int(c)
                except Exception:
                    continue
                if 1 <= c_int <= len(answers):
                    selected.append(c_int)

            if not selected:
                logger.warning("AI вернул некорректные индексы, используем random")
                return self._answer_randomly(question)

            # Для radio берём первый
            if not multi:
                selected = [selected[0]]

            for idx in selected:
                ans = answers[idx - 1]
                inp = ans.get("input")
                el = ans.get("element")
                if inp:
                    self.driver.execute_script("arguments[0].click();", inp)
                elif el:
                    self.driver.execute_script("arguments[0].click();", el)
            logger.info(f"AI выбрал ответы: {selected}")

        except Exception as e:
            logger.error(f"Ошибка AI-ответа: {e}. Используем random.")
            return self._answer_randomly(question)
    
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
                    return

                if 'element' in question['answers'][0]:
                    # Это кликабельные элементы без input
                    random_answer = random.choice(question['answers'])
                    elem = random_answer.get('element')
                    if elem:
                        try:
                            input_elem = elem.find_element(By.CSS_SELECTOR, "input[type='radio'], input[type='checkbox']")
                            self.driver.execute_script("arguments[0].click();", input_elem)
                        except Exception:
                            self.driver.execute_script("arguments[0].click();", elem)
                        logger.info(f"Выбран случайный ответ: {random_answer.get('text', '')}")
                    return

                # Drag&drop
                drag_sources = [a for a in answers if a.get("kind") == "drag-source" and a.get("source")]
                drag_targets = [a for a in answers if a.get("kind") == "drag-target" and a.get("target")]
                if drag_sources and drag_targets:
                    src = random.choice(drag_sources)
                    tgt = random.choice(drag_targets)
                    try:
                        self._drag_and_drop(src.get("source"), tgt.get("target"))
                        logger.info("Выполнен случайный drag&drop")
                    except Exception as e:
                        logger.warning(f"Не удалось выполнить drag&drop: {e}")
                    return
            
        except Exception as e:
            logger.error(f"Ошибка при случайном ответе: {e}")

    def _answer_text_question(self, question: Dict):
        """Заполнение текстовых полей (простой автотекст)."""
        try:
            answers = question.get("answers", [])
            if not answers:
                logger.warning("Текстовые поля не найдены")
                return
            # AI-режим: просим тексты под количество полей
            fill_texts: List[str] = []
            if self.strategy == "ai" and self._ai_provider:
                q_text = str(question.get("text") or "").strip()
                if not q_text:
                    q_text = "Введите ответ в текстовое поле."
                try:
                    resp = self._ai_provider.text(AITextRequest(question=q_text, fields=len(answers)))
                    fill_texts = [t.strip() for t in (resp.texts or [])]
                except Exception as e:
                    logger.warning(f"AI text не удалось: {e}")

            if not fill_texts:
                fill_texts = ["Автоответ"] * len(answers)
            if len(fill_texts) < len(answers):
                fill_texts.extend(["Автоответ"] * (len(answers) - len(fill_texts)))

            for idx, ans in enumerate(answers):
                inp = ans.get("input")
                if not inp:
                    continue
                value = fill_texts[idx]
                try:
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", inp)
                except Exception:
                    pass
                try:
                    inp.clear()
                except Exception:
                    pass
                try:
                    inp.send_keys(value)
                except Exception:
                    try:
                        self.driver.execute_script("arguments[0].value = arguments[1];", inp, value)
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Ошибка при вводе текста: {e}")

    def _drag_and_drop(self, source, target):
        """Безопасный drag&drop через JS с фолбэком на ActionChains."""
        if not source or not target:
            return
        try:
            self.driver.execute_script(
                """
                const src = arguments[0];
                const tgt = arguments[1];
                const dataTransfer = new DataTransfer();
                src.dispatchEvent(new DragEvent('dragstart', {dataTransfer}));
                tgt.dispatchEvent(new DragEvent('drop', {dataTransfer}));
                src.dispatchEvent(new DragEvent('dragend', {dataTransfer}));
                """,
                source,
                target,
            )
        except Exception:
            try:
                from selenium.webdriver import ActionChains
                ActionChains(self.driver).drag_and_drop(source, target).perform()
            except Exception:
                raise

    def _answer_dragdrop_question(self, question: Dict):
        """Поддержка drag&drop: matching (AI/по порядку)."""
        try:
            answers = question.get("answers", [])
            src_entries = [a for a in answers if a.get("kind") == "drag-source" and a.get("source")]
            tgt_entries = [a for a in answers if a.get("kind") == "drag-target" and a.get("target")]
            sources = [a.get("source") for a in src_entries]
            targets = [a.get("target") for a in tgt_entries]

            if not sources or not targets:
                logger.warning("Drag&drop: не найдены источники или цели")
                return

            # AI: сопоставляем по текстам
            if self.strategy == "ai" and self._ai_provider:
                q_text = str(question.get("text") or "").strip() or "Сопоставьте элементы."
                left = [str(a.get("text") or "").strip() or f"Left {i+1}" for i, a in enumerate(src_entries)]
                right = [str(a.get("text") or "").strip() or f"Right {i+1}" for i, a in enumerate(tgt_entries)]
                try:
                    resp = self._ai_provider.match(AIMatchRequest(question=q_text, left_items=left, right_items=right))
                    if resp.pairs:
                        used_left = set()
                        for li, ri in resp.pairs:
                            if not (1 <= li <= len(sources) and 1 <= ri <= len(targets)):
                                continue
                            if li in used_left:
                                continue
                            used_left.add(li)
                            try:
                                self._drag_and_drop(sources[li - 1], targets[ri - 1])
                            except Exception as e:
                                logger.warning(f"Drag&drop (AI) пара не выполнена: {e}")
                        return
                except Exception as e:
                    logger.warning(f"Drag&drop (AI) не удалось: {e}")

            # Fallback: сопоставляем один к одному по порядку
            for idx, src in enumerate(sources):
                tgt = targets[idx] if idx < len(targets) else targets[-1]
                try:
                    self._drag_and_drop(src, tgt)
                except Exception as e:
                    logger.warning(f"Drag&drop пара не выполнена: {e}")
        except Exception as e:
            logger.error(f"Ошибка drag&drop ответа: {e}")

    def _answer_order_question(self, question: Dict):
        """Сортировка элементов (перетаскивание в нужном порядке)."""
        try:
            answers = question.get("answers", [])
            items = [a for a in answers if a.get("kind") == "order-item" and a.get("item")]
            if not items:
                logger.warning("Order: элементы для сортировки не найдены")
                return

            q_text = str(question.get("text") or "").strip() or "Расставьте элементы в правильном порядке."
            item_texts = [str(a.get("text") or "").strip() or f"Item {i+1}" for i, a in enumerate(items)]

            desired: List[int] = []
            if self.strategy == "ai" and self._ai_provider:
                try:
                    resp = self._ai_provider.order(AIOrderRequest(question=q_text, items=item_texts))
                    desired = [int(x) for x in (resp.order or [])]
                except Exception as e:
                    logger.warning(f"Order (AI) не удалось: {e}")

            # Fallback: оставить как есть
            if not desired:
                logger.info("Order: AI не дал порядок, оставляем текущий")
                return

            # Нормализация order
            desired = [x for x in desired if 1 <= x <= len(items)]
            if len(desired) != len(items):
                # дополняем теми, кого не хватило
                rest = [i for i in range(1, len(items) + 1) if i not in desired]
                desired.extend(rest)

            # Пробуем переставить: drag item onto item currently at target position.
            current_elems = [a.get("item") for a in items]
            for target_pos, src_index_1b in enumerate(desired, start=1):
                try:
                    src_el = current_elems[src_index_1b - 1]
                    dst_el = current_elems[target_pos - 1]
                    if src_el == dst_el:
                        continue
                    self._drag_and_drop(src_el, dst_el)
                    time.sleep(0.2)
                except Exception as e:
                    logger.warning(f"Order: не удалось переставить элемент на позицию {target_pos}: {e}")

        except Exception as e:
            logger.error(f"Ошибка order-ответа: {e}")

    def _dump_debug_html(self, prefix: str) -> None:
        """Сохраняет текущий HTML страницы для анализа разметки теста."""
        try:
            debug_dir = (getattr(Config, "DEBUG_HTML_DIR", "") or os.path.join("artifacts", "debug_html")).strip()
            os.makedirs(debug_dir, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            # dump default + все iframe (глубина 2), чтобы не потерять контент теста
            for stack in self._iter_frame_stacks(max_depth=2):
                try:
                    self._switch_to_frame_stack(stack)
                except Exception:
                    continue
                suffix = "root" if not stack else "frame_" + "_".join(str(x) for x in stack)
                name = os.path.join(debug_dir, f"{prefix}_{suffix}_{ts}.html")
                html = self.driver.page_source or ""
                with open(name, "w", encoding="utf-8") as f:
                    f.write(html)
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass
            logger.info(f"[DEBUG] HTML сохранён: {os.path.join(debug_dir, f'{prefix}_*_{ts}.html')}")
        except Exception as e:
            logger.debug(f"[DEBUG] Не удалось сохранить HTML: {e}")
    
    def _answer_correctly(self, question: Dict):
        """Правильный ответ (если есть доступ к правильным ответам)"""
        # TODO: Реализовать логику получения правильных ответов
        # Пока используем случайный ответ
        logger.info("Режим 'correct' пока не реализован, используем случайный ответ")
        self._answer_randomly(question)
    
    def _submit_test(self) -> bool:
        """Отправка теста"""
        try:
            # Ищем кнопку отправки (XPath по тексту + fallback на input submit)
            if self._click_by_text(
                ["button", "a"],
                [
                    "Отправить",
                    "Отправить ответы",
                    "Завершить",
                    "Завершить тест",
                    "Сдать",
                    "Сдать тест",
                    "Submit",
                    "Finish",
                    "Готово",
                    "Далее",
                ],
            ):
                time.sleep(2)
                logger.info("Тест отправлен")
                return True

            try:
                btns = self.driver.find_elements(By.CSS_SELECTOR, "input[type='submit']")
                for b in btns:
                    if b.is_displayed() and b.is_enabled():
                        self.driver.execute_script("arguments[0].click();", b)
                        time.sleep(2)
                        logger.info("Тест отправлен")
                        return True
            except Exception:
                pass

            # Фолбэк: пробуем submit формы напрямую
            try:
                submitted = self.driver.execute_script(
                    """
                    var f = document.querySelector('form');
                    if (f && typeof f.submit === 'function') { f.submit(); return true; }
                    return false;
                    """
                )
                if submitted:
                    time.sleep(2)
                    logger.info("Тест отправлен (через form.submit())")
                    return True
            except Exception:
                pass
            
            logger.warning("Кнопка отправки теста не найдена")
            return False
            
        except Exception as e:
            logger.error(f"Ошибка при отправке теста: {e}")
            return False
