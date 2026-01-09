"""Модуль для обработки материалов (видео, PDF) с подтверждением"""
import time
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


class MaterialProcessor:
    """Класс для обработки материалов с подтверждением"""
    
    def __init__(self, driver: webdriver.Chrome):
        self.driver = driver
        self.wait = WebDriverWait(driver, Config.PAGE_LOAD_TIMEOUT)
    
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
            
            # Обработка видео
            if material_type == 'video':
                video_result = self._process_video(material)
                if video_result:
                    results['videos'] += 1
                    results['processed'] = True
            
            # Обработка PDF
            elif material_type == 'pdf':
                pdf_result = self._process_pdf(material)
                if pdf_result:
                    results['pdfs'] += 1
                    results['processed'] = True
            
            # Для других типов материалов просто подтверждаем просмотр
            else:
                time.sleep(Config.MIN_VIEW_TIME)
                results['processed'] = True

            # Подтверждение изучения (выполняется в самом конце)
            self.driver.switch_to.default_content()
            self.confirm_material_study()
            
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
                            video_processed = self._find_and_start_video(material)
                            
                            if video_processed:
                                logger.info(f"Видео найдено и обработано в iframe #{index}")
                                break
                            
                            # Если в этом iframe есть еще iframe, проверяем их (ВЛОЖЕННЫЕ IFRAME!)
                            nested_iframes = self.driver.find_elements(By.TAG_NAME, 'iframe')
                            if nested_iframes:
                                logger.info(f"В iframe #{index} найдено {len(nested_iframes)} вложенных iframe - проверяем их")
                                for nested_index in range(len(nested_iframes)):
                                    try:
                                        logger.info(f"Переключаемся на вложенный iframe #{nested_index}...")
                                        self.driver.switch_to.frame(nested_index)
                                        time.sleep(2)  # Даем время на загрузку вложенного iframe
                                        
                                        # Ищем видео во вложенном iframe
                                        video_processed = self._find_and_start_video(material)
                                        
                                        if video_processed:
                                            logger.info(f"✓ Видео найдено и обработано во вложенном iframe #{nested_index}")
                                            break
                                    except Exception as e_nested:
                                        logger.warning(f"Ошибка при обработке вложенного iframe #{nested_index}: {e_nested}")
                                    finally:
                                        # Возвращаемся к родительскому iframe
                                        try:
                                            self.driver.switch_to.parent_frame()
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
                video_processed = self._find_and_start_video(material)
            
            if video_processed:
                logger.info(f"Просмотр видео '{material['name']}' завершен.")
                return True
            else:
                logger.warning("Видео для просмотра не найдено.")
                # Даже если видео не найдено, ждем минимальное время
                time.sleep(Config.MIN_VIEW_TIME)
                return True
                
        except Exception as e:
            logger.error(f"Ошибка при обработке видео: {e}")
            return False
    
    def _find_and_start_video(self, material: Dict) -> Optional[object]:
        """Находит видео, запускает его и ждет полного просмотра"""
        PLACEHOLDER_VIDEO_SRC = "synergy_in.mp4"
        INTRO_DURATION = 5  # Длительность заставки в секундах
        
        try:
            # САМОЕ ВАЖНОЕ: Ищем и кликаем кнопку Play
            logger.info("Ищем кнопку Play...")
            time.sleep(3)  # Даем время на полную загрузку
            
            play_button_clicked = False
            
            # Пробуем найти кнопку Play - основной селектор
            try:
                logger.info("Ищем кнопку .vjs-big-play-button...")
                play_button = WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".vjs-big-play-button"))
                )
                
                # Проверяем что кнопка не скрыта
                classes = play_button.get_attribute('class') or ''
                is_hidden = 'vjs-hidden' in classes
                is_displayed = play_button.is_displayed()
                
                logger.info(f"Кнопка Play найдена! hidden={is_hidden}, displayed={is_displayed}, classes={classes}")
                
                if not is_hidden:
                    logger.info("Кликаем на кнопку Play через JavaScript...")
                    # Используем JavaScript click - самый надежный способ
                    self.driver.execute_script("arguments[0].click();", play_button)
                    play_button_clicked = True
                    logger.info("✓ Кнопка Play нажата!")
                    time.sleep(3)  # Даем время на запуск видео
                else:
                    logger.warning("Кнопка Play скрыта (vjs-hidden)")
                    
            except TimeoutException:
                logger.warning("Кнопка .vjs-big-play-button не найдена за 15 секунд")
            
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
                logger.warning("Кнопка Play не найдена, пробуем запустить видео напрямую через video.play()")
            
            # Ищем видео элементы
            video_players = self.driver.find_elements(By.CSS_SELECTOR, "div.video-js")
            video_elements = self.driver.find_elements(By.TAG_NAME, "video")
            
            logger.info(f"Найдено {len(video_players)} видеоплееров и {len(video_elements)} video элементов.")
            
            # Если кнопка не была нажата, пробуем запустить видео напрямую
            if not play_button_clicked and video_elements:
                logger.info("Кнопка Play не была нажата, пробуем запустить видео напрямую через video.play()...")
                for video_element in video_elements:
                    try:
                        video_id = video_element.get_attribute('id') or 'unknown'
                        logger.info(f"Пробуем запустить video элемент (id: {video_id})...")
                        
                        # Пробуем запустить видео
                        self.driver.execute_script("arguments[0].play();", video_element)
                        time.sleep(2)
                        
                        # Проверяем что видео запустилось
                        is_playing = self.driver.execute_script("return !arguments[0].paused;", video_element)
                        if is_playing:
                            logger.info("Видео запущено через video.play()")
                            play_button_clicked = True
                            break
                        else:
                            logger.warning("video.play() вызван, но видео не запустилось")
                    except Exception as e:
                        logger.warning(f"Ошибка при запуске video элемента: {e}")
            
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
                            time.sleep(INTRO_DURATION + duration_in_seconds)
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
                    
                    # Ждем когда видео начнет играть (появится класс vjs-playing)
                    try:
                        WebDriverWait(self.driver, 10).until(
                            lambda d: 'vjs-playing' in player.get_attribute('class')
                        )
                        logger.info("Видео запущено и воспроизводится")
                    except TimeoutException:
                        logger.warning("Видео не начало воспроизводиться, продолжаем...")
                    
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
                    
                    # Ждем просмотр: 5 секунд заставка + длительность видео
                    total_wait_time = INTRO_DURATION + duration_in_seconds
                    logger.info(f"Ожидаем просмотр видео: {INTRO_DURATION} сек заставка + {duration_in_seconds} сек видео = {total_wait_time} сек")
                    
                    # Ждем полное время просмотра
                    time.sleep(total_wait_time)
                    
                    logger.info(f"Просмотр видео '{material['name']}' завершен.")
                    return True

                except Exception as e_player:
                    logger.error(f"Ошибка при обработке плеера #{i + 1}: {e_player}")
                    continue
            
            return None
        except Exception as e:
            logger.error(f"Общая ошибка при поиске видео: {e}")
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
