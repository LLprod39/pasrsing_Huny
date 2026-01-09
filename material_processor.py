"""Модуль для обработки материалов (видео, PDF) с подтверждением"""
import time
import json
from typing import Dict, Optional
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from config import Config
from logger import setup_logger

logger = setup_logger(__name__)

# #region agent log
DEBUG_LOG_PATH = r"c:\testi\.cursor\debug.log"
# #endregion


class MaterialProcessor:
    """Класс для обработки материалов с подтверждением"""
    
    def __init__(self, driver: webdriver.Chrome):
        self.driver = driver
        self.wait = WebDriverWait(driver, Config.PAGE_LOAD_TIMEOUT)
    
    def _debug_log(self, location: str, message: str, data: dict = None, hypothesis_id: str = None):
        """Записывает отладочный лог в NDJSON формат"""
        # #region agent log
        try:
            import os
            log_dir = os.path.dirname(DEBUG_LOG_PATH)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)
            log_entry = {
                "sessionId": "debug-session",
                "runId": "run1",
                "timestamp": int(time.time() * 1000),
                "location": location,
                "message": message,
                "data": data or {},
                "hypothesisId": hypothesis_id
            }
            with open(DEBUG_LOG_PATH, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
                f.flush()
        except Exception as e:
            logger.debug(f"Ошибка записи debug лога: {e}")
        # #endregion
    
    def process_material(self, material: Dict) -> Dict:
        """Обработка отдельного учебного материала"""
        results = {'processed': False, 'videos': 0, 'pdfs': 0, 'error': None}
        
        try:
            logger.info(f"Обрабатываем материал: {material['name']}")
            
            # Для видео нужно открывать страницу курса, а не прямой URL материала
            # Потому что видео находится в iframe на странице курса
            material_url = material['url']
            material_type = material.get('type', 'material')
            
            if material_type == 'video' and '/learning/view/' in material_url:
                # Для видео открываем страницу курса, где видео находится в iframe
                if 'course_url' in material:
                    course_url = material['course_url']
                    logger.info(f"Открываем страницу курса для видео: {course_url}")
                    self.driver.get(course_url)
                    # Ждем загрузки страницы курса
                    self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                    time.sleep(2)
                    
                    # Теперь нужно найти и кликнуть на материал в списке, чтобы открыть iframe с видео
                    # Ищем ссылку на материал по его URL разными способами
                    material_clicked = False
                    
                    # Способ 1: Ищем по части URL материала
                    try:
                        material_id = material_url.split('/')[-1].split('?')[0]  # Получаем ID из URL
                        material_link = self.wait.until(
                            EC.element_to_be_clickable((By.XPATH, f"//a[contains(@href, '{material_id}')]"))
                        )
                        logger.info(f"Нашли ссылку на материал по ID {material_id}, кликаем...")
                        self.driver.execute_script("arguments[0].click();", material_link)
                        material_clicked = True
                        time.sleep(3)  # Ждем открытия iframe с видео
                    except TimeoutException:
                        logger.warning("Не удалось найти ссылку по ID материала")
                    
                    # Способ 2: Ищем по полному URL
                    if not material_clicked:
                        try:
                            material_link = self.wait.until(
                                EC.element_to_be_clickable((By.XPATH, f"//a[contains(@href, '{material_url}')]"))
                            )
                            logger.info("Нашли ссылку на материал по полному URL, кликаем...")
                            self.driver.execute_script("arguments[0].click();", material_link)
                            material_clicked = True
                            time.sleep(3)
                        except TimeoutException:
                            logger.warning("Не удалось найти ссылку по полному URL")
                    
                    # Способ 3: Ищем по названию материала
                    if not material_clicked:
                        try:
                            material_name = material.get('name', '')
                            if material_name:
                                material_link = self.wait.until(
                                    EC.element_to_be_clickable((By.XPATH, f"//a[contains(text(), '{material_name[:30]}')]"))
                                )
                                logger.info(f"Нашли ссылку на материал по названию '{material_name[:30]}', кликаем...")
                                self.driver.execute_script("arguments[0].click();", material_link)
                                material_clicked = True
                                time.sleep(3)
                        except TimeoutException:
                            logger.warning("Не удалось найти ссылку по названию материала")
                    
                    if not material_clicked:
                        logger.warning("Не удалось найти и кликнуть на материал в списке, пробуем найти iframe напрямую")
                else:
                    # Если course_url нет, пробуем открыть URL материала напрямую
                    logger.warning("course_url не найден, открываем URL материала напрямую")
                    self.driver.get(material_url)
            else:
                # Для других типов материалов открываем URL напрямую
                logger.info(f"Открываем URL материала: {material_url}")
                self.driver.get(material_url)
            
            self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            time.sleep(3)

            material_type = material.get('type', 'material')
            logger.info(f"Тип материала (до авто-детекта): {material_type}")

            # Считываем прогресс/уже просмотренное время (для пропуска повторного просмотра)
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass
            viewed_seconds = self._get_item_total_time_seconds()
            progress_percent = self._get_progress_percent()
            if viewed_seconds is not None:
                logger.info(f"Уже просмотрено (itemTotalTime): {viewed_seconds} сек")
            if progress_percent is not None:
                logger.info(f"Прогресс материала: {progress_percent}%")

            # Если уже 100% — можно пропустить, но для видео лучше перепроверять по времени/длительности.
            # (иначе бывают случаи: 100% отображается, но фактически недосмотрено несколько секунд).
            if progress_percent is not None and progress_percent >= 100:
                material_type_now = material.get('type', 'material')
                should_skip_by_progress = material_type_now != 'video'
                # Если тип не video, но на странице есть плеер — не пропускаем до проверки в _process_video.
                if material_type_now != 'video':
                    try:
                        if self._page_contains_video():
                            should_skip_by_progress = False
                    except Exception:
                        pass
                if should_skip_by_progress:
                    results['processed'] = True
                    logger.info("Материал уже 100% (по прогрессу) — пропускаем повторный просмотр")

            # Если материал не распознан как video по URL/названию, но на странице есть видеоплеер,
            # переключаемся на обработку видео (актуально для /lntools/mcresource/view/...).
            if not results.get('processed') and material_type not in ['video', 'pdf', 'test', 'blocked']:
                try:
                    has_video = self._page_contains_video()
                    logger.info(f"Авто-детект видео на странице: {has_video}")
                    if has_video:
                        logger.info("Обнаружен видеоплеер на странице — обрабатываем как видео")
                        material_type = 'video'
                except Exception as e_detect:
                    logger.debug(f"Не удалось выполнить авто-детект видео: {e_detect}")

            logger.info(f"Тип материала (после авто-детекта): {material_type}")
            
            # Обработка видео
            if not results.get('processed') and material_type == 'video':
                # #region agent log
                self._debug_log("material_processor.py:108", "Начинаем обработку видео", {
                    "material_name": material.get('name', 'unknown'),
                    "material_url": material.get('url', 'unknown')[:100],
                    "material_type": material_type
                }, "A")
                # #endregion
                video_result = self._process_video(material, viewed_seconds=viewed_seconds, progress_percent=progress_percent)
                # #region agent log
                self._debug_log("material_processor.py:111", "Результат обработки видео", {
                    "video_result": video_result,
                    "material_name": material.get('name', 'unknown')
                }, "A")
                # #endregion
                if video_result:
                    results['videos'] += 1
                    results['processed'] = True
                else:
                    results['error'] = "Видео не найдено/не удалось запустить для просмотра"
            
            # Обработка PDF
            elif material_type == 'pdf':
                pdf_result = self._process_pdf(material)
                if pdf_result:
                    results['pdfs'] += 1
                    results['processed'] = True
                else:
                    results['error'] = "Не удалось обработать PDF материал"
            
            # Для других типов материалов просто подтверждаем просмотр
            else:
                time.sleep(Config.MIN_VIEW_TIME)
                results['processed'] = True

            # Подтверждение изучения — только если реально обработали материал
            # (иначе мы "закрываем" видео, даже если Play не нажался/видео не найдено)
            if results.get('processed') and not results.get('error'):
                self.driver.switch_to.default_content()
                self.confirm_material_study()
            else:
                logger.warning("Пропускаем подтверждение материала: обработка не завершена успешно")
            
            return results
            
        except Exception as e:
            logger.error(f"Ошибка при обработке материала {material['name']}: {e}")
            results['error'] = str(e)
            return results
        finally:
            try:
                self.driver.switch_to.default_content()
            except:
                pass
    
    def _process_video(self, material: Dict) -> bool:
        """Обработка видео материала"""
        try:
            logger.info(f"Обрабатываем видео: {material['name']}")
            
            # Сначала ищем видео в iframes (видео обычно в iframe)
            video_processed = False
            try:
                iframes = self.driver.find_elements(By.TAG_NAME, 'iframe')
                if iframes:
                    logger.info(f"Найдено {len(iframes)} iframe. Проверяем их на наличие видео...")
                    for index in range(len(iframes)):
                        try:
                            logger.info(f"Переключаемся на iframe #{index}...")
                            iframe = iframes[index]
                            iframe_src = iframe.get_attribute('src') or ''
                            logger.info(f"Iframe #{index} src: {iframe_src[:100] if iframe_src else 'empty'}")
                            
                            self.driver.switch_to.frame(index)
                            time.sleep(2)  # Даем больше времени на загрузку содержимого iframe
                            
                            # Проверяем что мы в iframe - ищем элементы
                            try:
                                test_elements = self.driver.find_elements(By.TAG_NAME, "body")
                                logger.info(f"В iframe #{index} найдено body элементов: {len(test_elements)}")
                            except:
                                logger.warning(f"Не удалось получить доступ к содержимому iframe #{index}")
                            
                            # Пробуем найти видео в этом iframe
                            # #region agent log
                            self._debug_log("material_processor.py:175", "Поиск видео в iframe", {
                                "iframe_index": index,
                                "iframe_src": iframe_src[:100] if iframe_src else "empty"
                            }, "E")
                            # #endregion
                            video_processed = self._find_and_start_video(material)
                            
                            if video_processed:
                                logger.info(f"Видео найдено и обработано в iframe #{index}")
                                # #region agent log
                                self._debug_log("material_processor.py:178", "Видео обработано в iframe", {
                                    "iframe_index": index,
                                    "success": True
                                }, "E")
                                # #endregion
                                break
                            
                            # Если в этом iframe есть еще iframe, проверяем их (ВЛОЖЕННЫЕ IFRAME!)
                            nested_iframes = self.driver.find_elements(By.TAG_NAME, 'iframe')
                            if nested_iframes:
                                logger.info(f"В iframe #{index} найдено {len(nested_iframes)} вложенных iframe - проверяем их")
                                for nested_index in range(len(nested_iframes)):
                                    try:
                                        logger.info(f"Переключаемся на вложенный iframe #{nested_index}...")
                                        nested_iframe = nested_iframes[nested_index]
                                        nested_src = nested_iframe.get_attribute('src') or ''
                                        logger.info(f"Вложенный iframe #{nested_index} src: {nested_src[:100] if nested_src else 'empty'}")
                                        
                                        self.driver.switch_to.frame(nested_index)
                                        time.sleep(3)  # Даем больше времени на загрузку вложенного iframe
                                        
                                        # Проверяем что мы во вложенном iframe и ищем кнопку Play
                                        try:
                                            test_body = self.driver.find_elements(By.TAG_NAME, "body")
                                            logger.info(f"Во вложенном iframe #{nested_index} найдено body элементов: {len(test_body)}")
                                            
                                            # Ищем кнопку Play сразу во вложенном iframe для отладки
                                            play_buttons = self.driver.find_elements(By.CSS_SELECTOR, ".vjs-big-play-button")
                                            logger.info(f"Во вложенном iframe #{nested_index} найдено {len(play_buttons)} кнопок Play")
                                            if play_buttons:
                                                for pb_idx, pb in enumerate(play_buttons):
                                                    try:
                                                        pb_classes = pb.get_attribute('class') or ''
                                                        pb_hidden = 'vjs-hidden' in pb_classes
                                                        logger.info(f"  Кнопка Play #{pb_idx+1}: hidden={pb_hidden}, classes={pb_classes[:50]}")
                                                    except:
                                                        pass
                                        except Exception as e_check:
                                            logger.warning(f"Не удалось проверить содержимое вложенного iframe #{nested_index}: {e_check}")
                                        
                                        # Ищем видео во вложенном iframe
                                        video_processed = self._find_and_start_video(material)
                                        
                                        if video_processed:
                                            logger.info(f"✓ Видео найдено и обработано во вложенном iframe #{nested_index}")
                                            break
                                    except Exception as e_nested:
                                        logger.error(f"Ошибка при обработке вложенного iframe #{nested_index}: {e_nested}")
                                        import traceback
                                        logger.error(traceback.format_exc())
                                    finally:
                                        # Возвращаемся к родительскому iframe
                                        try:
                                            self.driver.switch_to.parent_frame()
                                            logger.info(f"Вернулись к родительскому iframe #{index}")
                                        except:
                                            pass
                            
                            if video_processed:
                                break
                                
                        except Exception as e_frame:
                            logger.warning(f"Ошибка при обработке iframe #{index}: {e_frame}")
                        finally:
                            self.driver.switch_to.default_content()
            except Exception as e:
                logger.error(f"Ошибка при поиске iframes: {e}")
            finally:
                self.driver.switch_to.default_content()
            
            # Если не нашли в iframe, ищем на основной странице
            if not video_processed:
                logger.info("Ищем видео на основной странице...")
                # #region agent log
                self._debug_log("material_processor.py:220", "Поиск видео на основной странице", {
                    "reason": "не найдено в iframe"
                }, "E")
                # #endregion
                video_processed = self._find_and_start_video(material)
            
            if video_processed:
                logger.info(f"Просмотр видео '{material['name']}' завершен.")
                return True
            else:
                logger.warning("Видео для просмотра не найдено.")
                return False
                
        except Exception as e:
            logger.error(f"Ошибка при обработке видео: {e}")
            return False

    def _process_video(self, material: Dict, viewed_seconds: Optional[int] = None, progress_percent: Optional[int] = None) -> bool:
        """Обработка видео материала (с учетом уже просмотренного времени)"""
        try:
            logger.info(f"Обрабатываем видео: {material['name']}")

            # ВАЖНО: длительность видео часто становится доступной только ПОСЛЕ запуска плеера
            # (до этого duration может быть 0/NaN/inf). Поэтому решение "досматривать или нет"
            # принимаем внутри _find_and_start_video(), после реального старта видео и получения duration.

            # Сначала ищем видео в iframes (видео обычно в iframe)
            video_processed = False
            try:
                iframes = self.driver.find_elements(By.TAG_NAME, 'iframe')
                if iframes:
                    logger.info(f"Найдено {len(iframes)} iframe. Проверяем их на наличие видео...")
                    for index in range(len(iframes)):
                        try:
                            logger.info(f"Переключаемся на iframe #{index}...")
                            iframe = iframes[index]
                            iframe_src = iframe.get_attribute('src') or ''
                            logger.info(f"Iframe #{index} src: {iframe_src[:100] if iframe_src else 'empty'}")

                            self.driver.switch_to.frame(index)
                            time.sleep(2)

                            # Пробуем найти видео в этом iframe
                            self._debug_log("material_processor.py:175", "Поиск видео в iframe", {
                                "iframe_index": index,
                                "iframe_src": iframe_src[:100] if iframe_src else "empty"
                            }, "E")

                            video_processed = self._find_and_start_video(material, viewed_seconds=viewed_seconds)

                            if video_processed:
                                logger.info(f"Видео найдено и обработано в iframe #{index}")
                                self._debug_log("material_processor.py:178", "Видео обработано в iframe", {
                                    "iframe_index": index,
                                    "success": True
                                }, "E")
                                break

                            # Вложенные iframe
                            nested_iframes = self.driver.find_elements(By.TAG_NAME, 'iframe')
                            if nested_iframes:
                                logger.info(f"В iframe #{index} найдено {len(nested_iframes)} вложенных iframe - проверяем их")
                                for nested_index in range(len(nested_iframes)):
                                    try:
                                        logger.info(f"Переключаемся на вложенный iframe #{nested_index}...")
                                        nested_iframe = nested_iframes[nested_index]
                                        nested_src = nested_iframe.get_attribute('src') or ''
                                        logger.info(f"Вложенный iframe #{nested_index} src: {nested_src[:100] if nested_src else 'empty'}")

                                        self.driver.switch_to.frame(nested_index)
                                        time.sleep(3)

                                        video_processed = self._find_and_start_video(material, viewed_seconds=viewed_seconds)
                                        if video_processed:
                                            logger.info(f"✓ Видео найдено и обработано во вложенном iframe #{nested_index}")
                                            break
                                    except Exception as e_nested:
                                        logger.error(f"Ошибка при обработке вложенного iframe #{nested_index}: {e_nested}")
                                    finally:
                                        try:
                                            self.driver.switch_to.parent_frame()
                                        except Exception:
                                            pass

                            if video_processed:
                                break
                        except Exception as e_frame:
                            logger.warning(f"Ошибка при обработке iframe #{index}: {e_frame}")
                        finally:
                            try:
                                self.driver.switch_to.default_content()
                            except Exception:
                                pass
            except Exception as e:
                logger.error(f"Ошибка при поиске iframes: {e}")
            finally:
                try:
                    self.driver.switch_to.default_content()
                except Exception:
                    pass

            # Если не нашли в iframe, ищем на основной странице
            if not video_processed:
                logger.info("Ищем видео на основной странице...")
                self._debug_log("material_processor.py:220", "Поиск видео на основной странице", {
                    "reason": "не найдено в iframe"
                }, "E")
                video_processed = self._find_and_start_video(material, viewed_seconds=viewed_seconds)

            if video_processed:
                logger.info(f"Просмотр видео '{material['name']}' завершен.")
                return True

            logger.warning("Видео для просмотра не найдено.")
            return False
        except Exception as e:
            logger.error(f"Ошибка при обработке видео: {e}")
            return False

    def _get_item_total_time_seconds(self) -> Optional[int]:
        """Считывает время просмотра из #itemTotalTime (формат HH:MM:SS или MM:SS)."""
        try:
            el = self.driver.find_element(By.ID, "itemTotalTime")
            raw = (el.text or "").strip()
            if not raw:
                raw = (self.driver.execute_script(
                    "return arguments[0].textContent || arguments[0].innerText || '';",
                    el
                ) or "").strip()
            if not raw:
                return None
            return self._parse_time_to_seconds(raw)
        except Exception:
            return None

    def _get_progress_percent(self) -> Optional[int]:
        """Считывает прогресс из блока .courseEducationProgress .interest strong (например '100%')."""
        selectors = [
            ".courseEducationProgress .interest strong",
            ".interest strong",
        ]
        for sel in selectors:
            try:
                el = self.driver.find_element(By.CSS_SELECTOR, sel)
                txt = (el.text or "").strip()
                if not txt:
                    txt = (self.driver.execute_script(
                        "return arguments[0].textContent || arguments[0].innerText || '';",
                        el
                    ) or "").strip()
                if not txt:
                    continue
                txt = txt.replace('%', '').strip()
                if txt.isdigit():
                    return int(txt)
            except Exception:
                continue
        return None

    def _parse_time_to_seconds(self, s: str) -> int:
        """Парсит 'HH:MM:SS' / 'MM:SS' / 'SS' в секунды."""
        parts = [p.strip() for p in s.strip().split(':') if p.strip()]
        if not parts:
            return 0
        try:
            nums = [int(p) for p in parts]
        except Exception:
            return 0
        if len(nums) == 3:
            return nums[0] * 3600 + nums[1] * 60 + nums[2]
        if len(nums) == 2:
            return nums[0] * 60 + nums[1]
        return nums[0]

    def _probe_video_duration_seconds(self) -> Optional[int]:
        """
        Пытается быстро получить длительность видео из <video>.duration без запуска просмотра.
        Возвращает первую валидную длительность (секунды).
        """
        # 1) На текущем уровне
        try:
            videos = self.driver.find_elements(By.TAG_NAME, "video")
            for v in videos:
                try:
                    dur = self.driver.execute_script("return arguments[0].duration;", v)
                    if dur and dur > 0 and dur != float("inf"):
                        return int(dur)
                except Exception:
                    continue
        except Exception:
            pass

        # 2) В iframe (если есть доступ)
        try:
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            for idx in range(len(iframes)):
                try:
                    self.driver.switch_to.default_content()
                    self.driver.switch_to.frame(idx)
                    time.sleep(0.2)
                    videos = self.driver.find_elements(By.TAG_NAME, "video")
                    for v in videos:
                        try:
                            dur = self.driver.execute_script("return arguments[0].duration;", v)
                            if dur and dur > 0 and dur != float("inf"):
                                return int(dur)
                        except Exception:
                            continue
                except Exception:
                    continue
                finally:
                    try:
                        self.driver.switch_to.default_content()
                    except Exception:
                        pass
        except Exception:
            pass

        return None

    def _page_contains_video(self) -> bool:
        """
        Быстрый детект наличия видео на текущей странице.
        Нужен для случаев, когда материал не помечен как video, но фактически содержит плеер.
        """
        # В текущем DOM
        try:
            if self.driver.find_elements(By.CSS_SELECTOR, "div.video-js, video, .vjs-big-play-button"):
                return True
        except Exception:
            pass

        # Проверяем iframe: сначала по src, затем (если возможно) заходим внутрь и ищем элементы плеера.
        try:
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            for fr in iframes:
                src = (fr.get_attribute("src") or "").lower()
                if not src:
                    src = ""
                if any(token in src for token in [
                    "video", "player", "kinescope", "youtube", "rutube", "vk.com/video",
                    "/learning/view/", "/lntools/"
                ]):
                    return True

            # Глубокая проверка: пробуем переключиться в iframe и найти элементы плеера
            for idx in range(len(iframes)):
                try:
                    self.driver.switch_to.default_content()
                    self.driver.switch_to.frame(idx)
                    time.sleep(0.2)
                    if self.driver.find_elements(By.CSS_SELECTOR, "div.video-js, video, .vjs-big-play-button"):
                        return True
                except Exception:
                    # кросс-домен/нет доступа/пустой iframe — пропускаем
                    continue
                finally:
                    try:
                        self.driver.switch_to.default_content()
                    except Exception:
                        pass
        except Exception:
            pass

        return False

    def _robust_click(self, element) -> bool:
        """Надежный клик по элементу (scroll -> ActionChains -> JS click + dispatch событий)."""
        try:
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block:'center', inline:'center'});",
                element
            )
            time.sleep(0.2)
        except Exception:
            pass

        # 1) Обычный клик Selenium/ActionChains (иногда нужен именно user-gesture)
        try:
            ActionChains(self.driver).move_to_element(element).pause(0.05).click(element).perform()
            return True
        except Exception:
            pass

        # 2) JS click (обходит перехваты Selenium)
        try:
            self.driver.execute_script("arguments[0].click();", element)
            return True
        except Exception:
            pass

        # 3) Dispatch mouse/pointer событий (некоторые плееры слушают именно их)
        try:
            self.driver.execute_script(
                """
                const el = arguments[0];
                const opts = {bubbles: true, cancelable: true, view: window};
                ['pointerdown','mousedown','pointerup','mouseup','click'].forEach((t) => {
                  try { el.dispatchEvent(new MouseEvent(t, opts)); } catch(e) {}
                });
                """,
                element
            )
            return True
        except Exception:
            return False

    def _force_start_video_playback(self) -> bool:
        """
        Если после клика Play видео осталось на паузе (autoplay/overlay),
        пробуем принудительно стартануть через video.play() и VideoJS API.
        """
        # 1) HTML5 video.play() + muted (часто требуется в браузерах)
        try:
            video_elements = self.driver.find_elements(By.TAG_NAME, "video")
            for video in video_elements:
                try:
                    self.driver.execute_script(
                        """
                        const v = arguments[0];
                        try { v.muted = true; } catch(e) {}
                        try { v.play(); } catch(e) {}
                        """,
                        video
                    )
                    time.sleep(0.5)
                    is_playing = self.driver.execute_script("return arguments[0] && !arguments[0].paused;", video)
                    if is_playing:
                        return True
                except Exception:
                    continue
        except Exception:
            pass

        # 2) VideoJS API (если доступен)
        try:
            started = self.driver.execute_script(
                """
                try {
                  if (!window.videojs) return false;
                  const players = (window.videojs.players) ? Object.values(window.videojs.players) : [];
                  let ok = false;
                  players.forEach((p) => {
                    try {
                      if (p && typeof p.muted === 'function') p.muted(true);
                      if (p && typeof p.play === 'function') p.play();
                      ok = true;
                    } catch(e) {}
                  });
                  return ok;
                } catch(e) { return false; }
                """
            )
            if started:
                time.sleep(0.5)
                # перепроверим по video.paused
                try:
                    vids = self.driver.find_elements(By.TAG_NAME, "video")
                    for v in vids:
                        try:
                            if self.driver.execute_script("return arguments[0] && !arguments[0].paused;", v):
                                return True
                        except Exception:
                            continue
                except Exception:
                    pass
        except Exception:
            pass

        return False
    
    def _find_and_start_video(
        self,
        material: Dict,
        viewed_seconds: Optional[int] = None,
        completion_tolerance_seconds: int = 5,
    ) -> Optional[object]:
        """Находит видео, запускает его и ждет полного просмотра"""
        PLACEHOLDER_VIDEO_SRC = "synergy_in.mp4"
        INTRO_DURATION = 5  # Длительность заставки в секундах
        
        try:
            # #region agent log
            try:
                current_url = self.driver.current_url
                page_title = self.driver.title
            except:
                current_url = "unknown"
                page_title = "unknown"
            self._debug_log("material_processor.py:236", "Вход в _find_and_start_video", {
                "material_name": material.get('name', 'unknown'),
                "current_url": current_url[:100],
                "page_title": page_title[:100]
            }, "A")
            # #endregion
            
            # САМОЕ ВАЖНОЕ: Ищем и кликаем кнопку Play
            logger.info("Ищем кнопку Play...")
            
            # Проверяем текущий контекст
            try:
                current_url = self.driver.current_url
                page_title = self.driver.title
                logger.info(f"Текущий контекст: URL={current_url[:100]}, Title={page_title[:50]}")
            except:
                pass
            
            time.sleep(3)  # Даем время на загрузку
            
            play_button_clicked = False
            play_button = None
            
            # Способ 1: По классу .vjs-big-play-button (САМЫЙ НАДЕЖНЫЙ из HTML!)
            try:
                logger.info("Ищем кнопку Play по классу .vjs-big-play-button...")
                play_button = WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".vjs-big-play-button"))
                )
                logger.info("✓ Кнопка Play найдена по классу .vjs-big-play-button!")
            except TimeoutException:
                logger.warning("Кнопка .vjs-big-play-button не найдена, пробуем другие способы...")
            
            # Способ 2: XPath от пользователя
            if not play_button:
                try:
                    logger.info("Ищем кнопку Play по XPath: /html/body/div[2]/div[1]/div/div/p/div/button")
                    play_button = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.XPATH, "/html/body/div[2]/div[1]/div/div/p/div/button"))
                    )
                    logger.info("✓ Кнопка Play найдена по XPath!")
                except TimeoutException:
                    logger.warning("Кнопка Play не найдена по XPath")
                    # Пробуем альтернативный XPath
                    try:
                        logger.info("Пробуем альтернативный XPath: //button[@class='vjs-big-play-button']")
                        play_button = WebDriverWait(self.driver, 5).until(
                            EC.presence_of_element_located((By.XPATH, "//button[@class='vjs-big-play-button']"))
                        )
                        logger.info("✓ Кнопка Play найдена по альтернативному XPath!")
                    except TimeoutException:
                        logger.warning("Альтернативный XPath тоже не сработал")
            
            # Способ 3: Ищем все кнопки с классом .vjs-big-play-button
            if not play_button:
                try:
                    logger.info("Ищем все кнопки с классом .vjs-big-play-button...")
                    all_play_buttons = self.driver.find_elements(By.CSS_SELECTOR, ".vjs-big-play-button")
                    logger.info(f"Найдено {len(all_play_buttons)} элементов с классом .vjs-big-play-button")
                    if all_play_buttons:
                        # Берем первую видимую кнопку
                        for btn in all_play_buttons:
                            try:
                                if btn.is_displayed() and 'vjs-hidden' not in (btn.get_attribute('class') or ''):
                                    play_button = btn
                                    logger.info("Используем первую видимую кнопку")
                                    break
                            except:
                                continue
                        if not play_button and all_play_buttons:
                            play_button = all_play_buttons[0]
                            logger.info("Используем первую найденную кнопку (даже если скрыта)")
                except Exception as e:
                    logger.warning(f"Ошибка при поиске всех кнопок: {e}")
            
            # Способ 3: Ищем по title "Play Video"
            if not play_button:
                try:
                    logger.info("Ищем кнопку по title 'Play Video'...")
                    play_button = WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((By.XPATH, "//button[@title='Play Video' or contains(@title, 'Play')]"))
                    )
                    logger.info("✓ Кнопка найдена по title!")
                except TimeoutException:
                    logger.warning("Кнопка по title не найдена")
            
            # Способ 4: Ищем button с текстом "Play Video"
            if not play_button:
                try:
                    logger.info("Ищем кнопку по тексту 'Play Video'...")
                    play_button = WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((By.XPATH, "//button[contains(text(), 'Play Video') or contains(., 'Play Video')]"))
                    )
                    logger.info("✓ Кнопка найдена по тексту!")
                except TimeoutException:
                    logger.warning("Кнопка по тексту не найдена")
            
            if play_button:
                
                # Проверяем что кнопка не скрыта
                classes = play_button.get_attribute('class') or ''
                is_hidden = 'vjs-hidden' in classes
                is_displayed = play_button.is_displayed()
                tag_name = play_button.tag_name
                text_content = play_button.text[:50] if play_button.text else ""
                
                logger.info(f"Кнопка Play найдена! hidden={is_hidden}, displayed={is_displayed}, classes={classes}")
                # #region agent log
                self._debug_log("material_processor.py:255", "Кнопка Play найдена", {
                    "found": True,
                    "is_hidden": is_hidden,
                    "is_displayed": is_displayed,
                    "classes": classes,
                    "tag_name": tag_name,
                    "text": text_content
                }, "A")
                # #endregion
                
                # Кликаем на кнопку Play (независимо от is_hidden, так как XPath точный)
                logger.info("Кликаем на кнопку Play (robust click: scroll+actions+js)...")
                # #region agent log
                self._debug_log("material_processor.py:260", "Попытка клика по кнопке Play", {
                    "method": "robust_click",
                    "xpath": "/html/body/div[2]/div[1]/div/div/p/div/button"
                }, "B")
                # #endregion
                play_button_clicked = self._robust_click(play_button)
                if play_button_clicked:
                    logger.info("✓ Кнопка Play нажата!")
                else:
                    logger.warning("⚠️ Не удалось кликнуть по кнопке Play напрямую")
                
                # Ждем заставку (5 секунд) - как указал пользователь
                logger.info(f"Ожидаем {INTRO_DURATION} секунд заставки...")
                time.sleep(INTRO_DURATION)
                logger.info("Заставка прошла, видео должно начаться")

                # Если после клика видео не стартовало (paused), пробуем принудительный запуск
                try:
                    vids = self.driver.find_elements(By.TAG_NAME, "video")
                    if vids:
                        any_playing = False
                        for v in vids:
                            try:
                                if self.driver.execute_script("return arguments[0] && !arguments[0].paused;", v):
                                    any_playing = True
                                    break
                            except Exception:
                                continue
                        if not any_playing:
                            logger.info("Видео после клика всё ещё на паузе — пробуем принудительный старт (muted play)")
                            self._force_start_video_playback()
                except Exception:
                    pass
                
                # #region agent log
                try:
                    video_elements = self.driver.find_elements(By.TAG_NAME, "video")
                    video_states = []
                    for vid in video_elements:
                        try:
                            is_playing = self.driver.execute_script("return !arguments[0].paused;", vid)
                            current_time = self.driver.execute_script("return arguments[0].currentTime;", vid)
                            video_states.append({"is_playing": is_playing, "current_time": current_time})
                        except:
                            pass
                    self._debug_log("material_processor.py:263", "Состояние видео после клика", {
                        "play_button_clicked": play_button_clicked,
                        "video_count": len(video_elements),
                        "video_states": video_states
                    }, "C")
                except:
                    self._debug_log("material_processor.py:263", "Состояние видео после клика", {
                        "play_button_clicked": play_button_clicked,
                        "error": "не удалось проверить состояние"
                    }, "C")
                # #endregion
                
                if is_hidden:
                    logger.warning("Кнопка Play скрыта (vjs-hidden)")
                    # #region agent log
                    self._debug_log("material_processor.py:265", "Кнопка Play скрыта", {
                        "reason": "vjs-hidden в классах"
                    }, "A")
                    # #endregion
            else:
                logger.warning("Кнопка Play не найдена ни одним из способов")
            
            # Если кнопка не найдена, пробуем другие селекторы
            if not play_button_clicked:
                logger.info("Пробуем найти кнопку Play другими способами...")
                alt_selectors = [
                    "button.vjs-big-play-button",
                    "button[title='Play Video']",
                    "button[title*='Play']"
                ]
                
                for selector in alt_selectors:
                    try:
                        btn = self.driver.find_element(By.CSS_SELECTOR, selector)
                        if btn:
                            logger.info(f"Найдена кнопка по селектору: {selector}")
                            self.driver.execute_script("arguments[0].click();", btn)
                            play_button_clicked = True
                            logger.info("✓ Кнопка Play нажата!")
                            time.sleep(3)
                            break
                    except:
                        continue
            
            if not play_button_clicked:
                logger.warning("Кнопка Play не найдена или не нажата, пробуем запустить видео напрямую через video.play()")
                # Выводим отладочную информацию
                try:
                    all_buttons = self.driver.find_elements(By.TAG_NAME, "button")
                    logger.info(f"Найдено {len(all_buttons)} кнопок на странице")
                    for i, btn in enumerate(all_buttons[:10]):  # Показываем первые 10
                        try:
                            btn_text = btn.text[:30] if btn.text else ""
                            btn_title = btn.get_attribute('title') or ""
                            btn_class = btn.get_attribute('class') or ""
                            logger.info(f"  Кнопка #{i+1}: text='{btn_text}', title='{btn_title}', class='{btn_class[:50]}'")
                        except:
                            pass
                except:
                    pass
            
            # Ищем видео элементы
            video_players = self.driver.find_elements(By.CSS_SELECTOR, "div.video-js")
            video_elements = self.driver.find_elements(By.TAG_NAME, "video")
            
            logger.info(f"Найдено {len(video_players)} видеоплееров и {len(video_elements)} video элементов.")
            # #region agent log
            self._debug_log("material_processor.py:299", "Поиск видео элементов", {
                "video_players_count": len(video_players),
                "video_elements_count": len(video_elements),
                "play_button_clicked": play_button_clicked
            }, "A")
            # #endregion
            
            # Если кнопка не была нажата, пробуем запустить видео напрямую
            if not play_button_clicked and video_elements:
                logger.info("Кнопка Play не была нажата, пробуем запустить видео напрямую через video.play()...")
                # #region agent log
                self._debug_log("material_processor.py:303", "Попытка запуска видео через video.play()", {
                    "reason": "кнопка Play не была нажата",
                    "video_elements_count": len(video_elements)
                }, "C")
                # #endregion
                for video_element in video_elements:
                    try:
                        video_id = video_element.get_attribute('id') or 'unknown'
                        logger.info(f"Пробуем запустить video элемент (id: {video_id})...")
                        
                        # Пробуем запустить видео
                        self.driver.execute_script("arguments[0].play();", video_element)
                        time.sleep(2)
                        
                        # Проверяем что видео запустилось
                        is_playing = self.driver.execute_script("return !arguments[0].paused;", video_element)
                        # #region agent log
                        self._debug_log("material_processor.py:315", "Результат video.play()", {
                            "video_id": video_id,
                            "is_playing": is_playing,
                            "method": "video.play()"
                        }, "C")
                        # #endregion
                        if is_playing:
                            logger.info("Видео запущено через video.play()")
                            play_button_clicked = True
                            break
                        else:
                            logger.warning("video.play() вызван, но видео не запустилось")
                    except Exception as e:
                        logger.warning(f"Ошибка при запуске video элемента: {e}")
                        # #region agent log
                        self._debug_log("material_processor.py:322", "Ошибка при video.play()", {
                            "error": str(e)[:200]
                        }, "C")
                        # #endregion
            
            # Если есть только video элементы без плеера, обрабатываем их
            if not video_players and video_elements and play_button_clicked:
                logger.info("Обрабатываем video элементы...")
                for video_element in video_elements:
                    try:
                        # Получаем длительность
                        duration = self.driver.execute_script("return arguments[0].duration;", video_element)
                        if duration and duration > 0:
                            duration_in_seconds = int(duration)
                            logger.info(f"Длительность видео: {duration_in_seconds} секунд")
                            # Заставка уже прошла после клика на Play, ждем только длительность
                            logger.info(f"Ожидаем просмотр видео: {duration_in_seconds} секунд (заставка уже прошла)")
                            time.sleep(duration_in_seconds)
                            logger.info(f"Просмотр видео '{material['name']}' завершен.")
                            return True
                    except Exception as e:
                        logger.warning(f"Ошибка при обработке video элемента: {e}")
            
            for i, player in enumerate(video_players):
                try:
                    player_id = player.get_attribute('id')
                    if not player_id:
                        continue
                    
                    video_element = player.find_element(By.TAG_NAME, 'video')
                    initial_src = video_element.get_attribute('src') or ""

                    # Запускаем видео (пробуем несколько способов в порядке надежности)
                    play_clicked = False
                    
                    # Способ 1: Прямой запуск через JavaScript video.play() (самый надежный)
                    try:
                        logger.info("Пробуем запустить видео через JavaScript video.play()...")
                        # Сначала пробуем просто play()
                        try:
                            self.driver.execute_script("arguments[0].play();", video_element)
                            time.sleep(2)
                            # Проверяем что видео запустилось
                            is_playing = self.driver.execute_script("return !arguments[0].paused;", video_element)
                            if is_playing:
                                logger.info("Видео запущено через video.play()")
                                play_clicked = True
                            else:
                                logger.warning("video.play() вызван, но видео не запустилось")
                        except Exception as e1:
                            logger.warning(f"Ошибка при простом video.play(): {e1}")
                            # Пробуем с Promise
                            try:
                                result = self.driver.execute_script("""
                                    var video = arguments[0];
                                    if (video && video.play) {
                                        var promise = video.play();
                                        if (promise) {
                                            promise.then(function() {
                                                return 'playing';
                                            }).catch(function(err) {
                                                return 'error: ' + err.message;
                                            });
                                        }
                                        return 'play_called';
                                    }
                                    return 'no_play_method';
                                """, video_element)
                                logger.info(f"Результат video.play() (Promise): {result}")
                                time.sleep(2)
                                play_clicked = True
                            except Exception as e2:
                                logger.warning(f"Ошибка при video.play() с Promise: {e2}")
                    except Exception as e:
                        logger.warning(f"Общая ошибка при video.play(): {e}")
                    
                    # Способ 2: Через VideoJS API
                    if not play_clicked:
                        try:
                            logger.info("Пробуем запустить через VideoJS API...")
                            self.driver.execute_script(f"""
                                try {{
                                    var player = videojs('{player_id}');
                                    if (player && typeof player.play === 'function') {{
                                        player.play();
                                        console.log('VideoJS play() вызван для {player_id}');
                                        return true;
                                    }}
                                }} catch(e) {{
                                    console.log('Ошибка VideoJS:', e);
                                }}
                                return false;
                            """)
                            time.sleep(2)
                            play_clicked = True
                        except Exception as e:
                            logger.warning(f"Ошибка VideoJS: {e}")
                    
                    # Способ 3: Через кнопку .vjs-big-play-button (ищем разными способами)
                    if not play_clicked:
                        play_button = None
                        # Пробуем найти кнопку разными селекторами
                        selectors = [
                            f"#{player_id} .vjs-big-play-button",
                            ".vjs-big-play-button",
                            "button.vjs-big-play-button",
                            f"#{player_id} button[title*='Play']",
                            "button[title*='Play Video']"
                        ]
                        
                        for selector in selectors:
                            try:
                                play_button = WebDriverWait(self.driver, 2).until(
                                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                                )
                                if play_button and play_button.is_displayed():
                                    logger.info(f"Находим кнопку Play по селектору: {selector}")
                                    break
                            except:
                                continue
                        
                        if play_button:
                            try:
                                logger.info("Кликаем на кнопку Play через JavaScript...")
                                self.driver.execute_script("arguments[0].click();", play_button)
                                time.sleep(2)
                                play_clicked = True
                            except Exception as e:
                                logger.warning(f"Не удалось кликнуть кнопку Play: {e}")
                        else:
                            logger.warning("Кнопка .vjs-big-play-button не найдена")
                    
                    # Способ 4: XPath от пользователя
                    if not play_clicked:
                        try:
                            play_button = WebDriverWait(self.driver, 3).until(
                                EC.presence_of_element_located((By.XPATH, '/html/body/div[2]/div[1]/div/div/p/div'))
                            )
                            logger.info("Находим кнопку по XPath, кликаем...")
                            self.driver.execute_script("arguments[0].click();", play_button)
                            time.sleep(2)
                            play_clicked = True
                        except Exception:
                            pass
                    
                    if not play_clicked:
                        logger.warning("Не удалось запустить видео автоматически, возможно требуется взаимодействие пользователя")
                        # #region agent log
                        self._debug_log("material_processor.py:463", "Не удалось запустить видео", {
                            "player_id": player_id,
                            "all_methods_failed": True
                        }, "D")
                        # #endregion
                    
                    # Ждем когда видео начнет играть (появится класс vjs-playing)
                    try:
                        # #region agent log
                        self._debug_log("material_processor.py:467", "Ожидание класса vjs-playing", {
                            "player_id": player_id,
                            "timeout": 10
                        }, "C")
                        # #endregion
                        WebDriverWait(self.driver, 10).until(
                            lambda d: 'vjs-playing' in player.get_attribute('class')
                        )
                        logger.info("Видео запущено и воспроизводится")
                        # #region agent log
                        self._debug_log("material_processor.py:470", "Видео воспроизводится", {
                            "player_id": player_id,
                            "status": "playing"
                        }, "C")
                        # #endregion
                    except TimeoutException:
                        logger.warning("Видео не начало воспроизводиться, продолжаем...")
                        # #region agent log
                        try:
                            player_class = player.get_attribute('class') or ''
                            is_playing_check = self.driver.execute_script("return !arguments[0].paused;", video_element)
                            self._debug_log("material_processor.py:472", "Видео не начало воспроизводиться", {
                                "player_id": player_id,
                                "player_class": player_class,
                                "video_paused": not is_playing_check,
                                "timeout": True
                            }, "C")
                        except:
                            self._debug_log("material_processor.py:472", "Видео не начало воспроизводиться", {
                                "player_id": player_id,
                                "timeout": True
                            }, "C")
                        # #endregion
                    
                    # Ждем загрузки реального URL видео (если был placeholder)
                    if PLACEHOLDER_VIDEO_SRC in initial_src:
                        try:
                            WebDriverWait(self.driver, 15).until(
                                lambda d: PLACEHOLDER_VIDEO_SRC not in (video_element.get_attribute('src') or "")
                            )
                            logger.info("Реальный URL видео загружен")
                        except TimeoutException:
                            logger.warning("Не удалось дождаться загрузки реального URL")
                    
                    # Получаем длительность видео (после запуска видео нужно подождать загрузки метаданных)
                    duration_in_seconds = 0
                    max_attempts = 15  # Увеличиваем количество попыток
                    
                    logger.info("Ожидаем загрузки метаданных видео для получения длительности...")
                    time.sleep(3)  # Даем время на загрузку метаданных видео
                    
                    for attempt in range(max_attempts):
                        try:
                            # Способ 1: Получаем длительность напрямую из video.duration (самый надежный)
                            duration_js = self.driver.execute_script(
                                "return arguments[0].duration;", video_element
                            )
                            if duration_js and duration_js > 0 and not (duration_js == float('inf') or str(duration_js) == 'nan'):
                                duration_in_seconds = int(duration_js)
                                logger.info(f"✓ Длительность получена из video.duration: {duration_in_seconds} сек ({self._seconds_to_time_str(duration_in_seconds)})")
                                break
                            
                            # Способ 2: Через VideoJS API
                            try:
                                videojs_duration = self.driver.execute_script(f"""
                                    try {{
                                        var player = videojs('{player_id}');
                                        if (player && player.duration && typeof player.duration === 'function') {{
                                            var dur = player.duration();
                                            if (dur && dur > 0 && !isNaN(dur) && isFinite(dur)) {{
                                                return dur;
                                            }}
                                        }}
                                    }} catch(e) {{
                                        return null;
                                    }}
                                    return null;
                                """)
                                if videojs_duration and videojs_duration > 0:
                                    duration_in_seconds = int(videojs_duration)
                                    logger.info(f"✓ Длительность получена через VideoJS API: {duration_in_seconds} сек ({self._seconds_to_time_str(duration_in_seconds)})")
                                    break
                            except Exception as e_vjs:
                                logger.debug(f"VideoJS API не сработал: {e_vjs}")
                            
                            # Способ 3: Из .vjs-duration-display (может быть не загружена сразу)
                            try:
                                duration_element = self.driver.find_element(By.CSS_SELECTOR, f"#{player_id} .vjs-duration-display")
                                duration_str = duration_element.text.strip()
                                
                                # Если длительность еще не загружена, пробуем получить через JS
                                if not duration_str or duration_str in ["-:-", "0:00", "", "0:00"]:
                                    duration_str = self.driver.execute_script(
                                        "return arguments[0].textContent || arguments[0].innerText || '';", 
                                        duration_element
                                    ).strip()
                                
                                if duration_str and duration_str not in ["-:-", "0:00", ""]:
                                    parsed_duration = self._parse_duration_to_seconds(duration_str)
                                    if parsed_duration > 0:
                                        duration_in_seconds = parsed_duration
                                        logger.info(f"✓ Длительность получена из .vjs-duration-display: {duration_str} ({duration_in_seconds} сек)")
                                        break
                            except Exception as e_display:
                                logger.debug(f".vjs-duration-display не найден: {e_display}")
                            
                            # Если длительность еще не получена, ждем и пробуем снова
                            if attempt < max_attempts - 1:
                                time.sleep(1)
                                continue
                                
                        except Exception as e:
                            logger.debug(f"Попытка {attempt + 1}/{max_attempts} получить длительность: {e}")
                            if attempt < max_attempts - 1:
                                time.sleep(1)
                                continue
                    
                    if duration_in_seconds == 0:
                        logger.warning("Не удалось получить длительность видео, используем минимальное время")
                        duration_in_seconds = Config.MIN_VIEW_TIME
                    
                    # Решение "досматривать или подтверждать" принимаем ТОЛЬКО после реального запуска видео
                    # и получения duration (см. требование: сначала запустить видео, потом сравнить).
                    if duration_in_seconds and duration_in_seconds > 0 and viewed_seconds is not None:
                        tol = max(0, int(completion_tolerance_seconds))
                        if viewed_seconds >= max(0, duration_in_seconds - tol):
                            logger.info(
                                f"Видео уже досмотрено по времени: viewed={viewed_seconds}s >= duration={duration_in_seconds}s - tol={tol}s — пропускаем просмотр"
                            )
                            return True

                        remaining = max(0, duration_in_seconds - viewed_seconds)
                        # небольшой буфер, чтобы система точно засчитала завершение
                        remaining_with_buffer = min(duration_in_seconds, remaining + 2)
                        logger.info(
                            f"Досматриваем видео: duration={duration_in_seconds}s, viewed={viewed_seconds}s, осталось={remaining_with_buffer}s (включая буфер)"
                        )
                        time.sleep(remaining_with_buffer)
                    else:
                        # fallback: если не удалось корректно сравнить — смотрим полную длительность
                        logger.info(f"Ожидаем просмотр видео: {duration_in_seconds} секунд (заставка уже прошла)")
                        time.sleep(duration_in_seconds)
                    
                    logger.info(f"Просмотр видео '{material['name']}' завершен.")
                    return True

                except Exception as e_player:
                    logger.error(f"Ошибка при обработке плеера #{i + 1}: {e_player}")
                    continue
            
            return None
        except Exception as e:
            logger.error(f"Общая ошибка при поиске видео: {e}")
            # #region agent log
            self._debug_log("material_processor.py:577", "Ошибка в _find_and_start_video", {
                "error": str(e)[:200],
                "material_name": material.get('name', 'unknown')
            }, "A")
            # #endregion
            return None
    
    def _process_pdf(self, material: Dict) -> bool:
        """Обработка PDF материала"""
        try:
            logger.info(f"Обрабатываем PDF: {material['name']}")
            # Для PDF просто ждем минимальное время просмотра
            time.sleep(Config.MIN_VIEW_TIME)
            return True
        except Exception as e:
            logger.error(f"Ошибка при обработке PDF: {e}")
            return False
    
    def _seconds_to_time_str(self, seconds: int) -> str:
        """Преобразует секунды в формат MM:SS или HH:MM:SS"""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes:02d}:{secs:02d}"
    
    def _parse_duration_to_seconds(self, duration_str: str) -> int:
        """Парсит строку времени (ЧЧ:ММ:СС или ММ:СС) в секунды"""
        parts = duration_str.strip().split(':')
        seconds = 0
        try:
            if len(parts) == 3:  # HH:MM:SS
                seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 2:  # MM:SS
                seconds = int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 1:  # SS
                seconds = int(parts[0])
            return max(seconds, Config.MIN_VIEW_TIME)  # Минимум MIN_VIEW_TIME
        except (ValueError, IndexError):
            logger.error(f"Не удалось распознать длительность: '{duration_str}'")
            return Config.MIN_VIEW_TIME
    
    def confirm_material_study(self) -> bool:
        """Подтверждение изучения материала"""
        try:
            # Новый (из HTML): #closeForMobile = "Подтвердить изучение материала"
            try:
                btn = WebDriverWait(self.driver, 2).until(
                    EC.presence_of_element_located((By.ID, "closeForMobile"))
                )
                if btn and btn.is_displayed():
                    logger.info("Подтверждаем изучение материала (через closeForMobile)...")
                    self._robust_click(btn)
                    time.sleep(1)
                    logger.info("Материал подтвержден")
                    return True
            except Exception:
                pass

            # Пробуем найти кнопку по XPath
            confirm_button = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, '/html/body/div[4]/div/div[2]/div/dl/dd[1]/div[1]/a'))
            )
            if confirm_button and confirm_button.is_displayed():
                logger.info("Подтверждаем изучение материала...")
                self.driver.execute_script("arguments[0].click();", confirm_button)
                time.sleep(1)
                logger.info("Материал подтвержден")
                return True
            return False
        except TimeoutException:
            # Если XPath не сработал, пробуем старый способ
            try:
                confirm_button = WebDriverWait(self.driver, 2).until(
                    EC.element_to_be_clickable((By.ID, 'exitBtn'))
                )
                if confirm_button and confirm_button.is_displayed():
                    logger.info("Подтверждаем изучение материала (через exitBtn)...")
                    self.driver.execute_script("arguments[0].click();", confirm_button)
                    time.sleep(1)
                    logger.info("Материал подтвержден")
                    return True
            except:
                pass
            logger.info("Кнопка подтверждения не найдена или не требуется.")
            return False
        except Exception as e:
            logger.warning(f"Ошибка при подтверждении материала: {e}")
            return False
