"""
Automation Service - Background task execution for material automation
"""
import logging
import threading
import time
from datetime import datetime
from typing import Optional
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from config import ParserConfig, Credentials, BrowserOptions
from models import db, Material, Course, AutomationTask

logger = logging.getLogger(__name__)


class AutomationService:
    """Service for automating material viewing and completion"""

    def __init__(self):
        self.config = ParserConfig()
        self.credentials = Credentials()
        self.active_tasks = {}  # task_id -> thread
        self.cancelled_tasks = set()

    def watch_video(self, task_id: int, material: Material):
        """Start video watching in background thread"""
        thread = threading.Thread(
            target=self._watch_video_worker,
            args=(task_id, material),
            daemon=True
        )
        self.active_tasks[task_id] = thread
        thread.start()

    def confirm_material(self, task_id: int, material: Material):
        """Confirm material completion in background thread"""
        thread = threading.Thread(
            target=self._confirm_material_worker,
            args=(task_id, material),
            daemon=True
        )
        self.active_tasks[task_id] = thread
        thread.start()

    def complete_course(self, task_id: int, course: Course):
        """Auto-complete all materials in course"""
        thread = threading.Thread(
            target=self._complete_course_worker,
            args=(task_id, course),
            daemon=True
        )
        self.active_tasks[task_id] = thread
        thread.start()

    def cancel_task(self, task_id: int):
        """Cancel a running task"""
        self.cancelled_tasks.add(task_id)

    def _is_cancelled(self, task_id: int) -> bool:
        """Check if task is cancelled"""
        return task_id in self.cancelled_tasks

    def _update_task_status(self, task_id: int, status: str, progress: float = None, error: str = None):
        """Update task status in database"""
        from app import app
        with app.app_context():
            task = AutomationTask.query.get(task_id)
            if task:
                task.status = status
                if progress is not None:
                    task.progress = progress
                if error:
                    task.error_message = error
                if status == 'running' and not task.started_at:
                    task.started_at = datetime.utcnow()
                if status in ['completed', 'failed', 'cancelled']:
                    task.completed_at = datetime.utcnow()
                db.session.commit()

    def _watch_video_worker(self, task_id: int, material: Material):
        """Worker thread for watching video"""
        driver = None
        try:
            self._update_task_status(task_id, 'running', 0)

            if self._is_cancelled(task_id):
                self._update_task_status(task_id, 'cancelled')
                return

            # Initialize driver
            from config import ParserConfig
            config = ParserConfig()
            options = BrowserOptions.get_chrome_options(config)

            try:
                # Используем Selenium Manager (встроенный в Selenium 4.6+)
                driver = webdriver.Chrome(options=options)
                logger.info("Chrome driver initialized")
            except Exception as e:
                logger.error(f"Failed to initialize Chrome: {e}")
                # Fallback через webdriver-manager
                from selenium.webdriver.chrome.service import Service
                from webdriver_manager.chrome import ChromeDriverManager
                service = Service(ChromeDriverManager().install())
                driver = webdriver.Chrome(service=service, options=options)

            # Login
            self._login(driver)

            if self._is_cancelled(task_id):
                self._update_task_status(task_id, 'cancelled')
                return

            # Navigate to material
            logger.info(f"Navigating to material: {material.url}")
            driver.get(material.url)

            self._update_task_status(task_id, 'running', 20)

            # Wait for video player
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".video-js, video"))
            )

            if self._is_cancelled(task_id):
                self._update_task_status(task_id, 'cancelled')
                return

            # Click play button
            try:
                play_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, ".vjs-big-play-button"))
                )
                play_button.click()
                logger.info("Clicked play button")
            except TimeoutException:
                logger.warning("Play button not found, video might auto-play")

            self._update_task_status(task_id, 'running', 30)

            # Get video duration
            duration_seconds = material.duration_seconds
            if not duration_seconds:
                try:
                    time.sleep(2)  # Wait for duration to load
                    duration_elem = driver.find_element(By.CSS_SELECTOR, ".vjs-duration-display")
                    duration_text = duration_elem.text
                    duration_seconds = self._parse_duration_to_seconds(duration_text)
                    logger.info(f"Video duration: {duration_seconds} seconds")

                    # Update material with duration
                    from app import app
                    with app.app_context():
                        mat = Material.query.get(material.id)
                        if mat:
                            mat.duration_seconds = duration_seconds
                            db.session.commit()
                except Exception as e:
                    logger.error(f"Could not get video duration: {e}")
                    duration_seconds = 300  # Default 5 minutes

            if self._is_cancelled(task_id):
                self._update_task_status(task_id, 'cancelled')
                return

            # Wait for video to "play" (simulate watching)
            logger.info(f"Waiting {duration_seconds} seconds for video to complete...")
            sleep_interval = 5
            elapsed = 0

            while elapsed < duration_seconds:
                if self._is_cancelled(task_id):
                    self._update_task_status(task_id, 'cancelled')
                    return

                time.sleep(sleep_interval)
                elapsed += sleep_interval
                progress = 30 + (elapsed / duration_seconds) * 60  # 30% to 90%
                self._update_task_status(task_id, 'running', progress)

            # Confirm material after watching
            self._confirm_material_on_page(driver)

            self._update_task_status(task_id, 'running', 95)

            # Update material as completed
            from app import app
            with app.app_context():
                mat = Material.query.get(material.id)
                if mat:
                    mat.is_completed = True
                    mat.progress = "100%"
                    db.session.commit()

            self._update_task_status(task_id, 'completed', 100)
            logger.info(f"Video watching completed for material {material.id}")

        except Exception as e:
            logger.error(f"Error watching video: {e}")
            self._update_task_status(task_id, 'failed', error=str(e))
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
            if task_id in self.active_tasks:
                del self.active_tasks[task_id]

    def _confirm_material_worker(self, task_id: int, material: Material):
        """Worker thread for confirming material"""
        driver = None
        try:
            self._update_task_status(task_id, 'running', 0)

            if self._is_cancelled(task_id):
                self._update_task_status(task_id, 'cancelled')
                return

            # Initialize driver
            from config import ParserConfig
            config = ParserConfig()
            options = BrowserOptions.get_chrome_options(config)

            try:
                # Используем Selenium Manager (встроенный в Selenium 4.6+)
                driver = webdriver.Chrome(options=options)
                logger.info("Chrome driver initialized")
            except Exception as e:
                logger.error(f"Failed to initialize Chrome: {e}")
                # Fallback через webdriver-manager
                from selenium.webdriver.chrome.service import Service
                from webdriver_manager.chrome import ChromeDriverManager
                service = Service(ChromeDriverManager().install())
                driver = webdriver.Chrome(service=service, options=options)

            # Login
            self._login(driver)

            if self._is_cancelled(task_id):
                self._update_task_status(task_id, 'cancelled')
                return

            # Navigate to material
            driver.get(material.url)
            self._update_task_status(task_id, 'running', 50)

            # Confirm material
            self._confirm_material_on_page(driver)

            # Update material as completed
            from app import app
            with app.app_context():
                mat = Material.query.get(material.id)
                if mat:
                    mat.is_completed = True
                    db.session.commit()

            self._update_task_status(task_id, 'completed', 100)
            logger.info(f"Material confirmed: {material.id}")

        except Exception as e:
            logger.error(f"Error confirming material: {e}")
            self._update_task_status(task_id, 'failed', error=str(e))
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
            if task_id in self.active_tasks:
                del self.active_tasks[task_id]

    def _complete_course_worker(self, task_id: int, course: Course):
        """Worker thread for completing entire course"""
        driver = None
        try:
            self._update_task_status(task_id, 'running', 0)

            from app import app
            with app.app_context():
                materials = Material.query.filter_by(
                    course_id=course.id,
                    is_blocked=False,
                    type='video'
                ).all()

                total_materials = len(materials)

                if total_materials == 0:
                    self._update_task_status(task_id, 'completed', 100)
                    return

            # Initialize driver once for all materials
            from config import ParserConfig
            config = ParserConfig()
            options = BrowserOptions.get_chrome_options(config)

            try:
                # Используем Selenium Manager (встроенный в Selenium 4.6+)
                driver = webdriver.Chrome(options=options)
                logger.info("Chrome driver initialized for course completion")
            except Exception as e:
                logger.error(f"Failed to initialize Chrome: {e}")
                # Fallback через webdriver-manager
                from selenium.webdriver.chrome.service import Service
                from webdriver_manager.chrome import ChromeDriverManager
                service = Service(ChromeDriverManager().install())
                driver = webdriver.Chrome(service=service, options=options)

            # Login once
            self._login(driver)

            # Process each material
            for idx, material in enumerate(materials):
                if self._is_cancelled(task_id):
                    self._update_task_status(task_id, 'cancelled')
                    return

                logger.info(f"Processing material {idx + 1}/{total_materials}: {material.name}")

                try:
                    # Navigate to material
                    driver.get(material.url)

                    # If video, watch it
                    if material.type == 'video':
                        self._watch_video_on_page(driver, material)

                    # Confirm material
                    self._confirm_material_on_page(driver)

                    # Update material
                    with app.app_context():
                        mat = Material.query.get(material.id)
                        if mat:
                            mat.is_completed = True
                            db.session.commit()

                except Exception as e:
                    logger.error(f"Error processing material {material.id}: {e}")

                # Update progress
                progress = ((idx + 1) / total_materials) * 100
                self._update_task_status(task_id, 'running', progress)

            self._update_task_status(task_id, 'completed', 100)
            logger.info(f"Course completion finished: {course.id}")

        except Exception as e:
            logger.error(f"Error completing course: {e}")
            self._update_task_status(task_id, 'failed', error=str(e))
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
            if task_id in self.active_tasks:
                del self.active_tasks[task_id]

    def _login(self, driver: webdriver.Chrome):
        """Login to LMS"""
        logger.info("Logging in to LMS...")
        driver.get(self.config.base_url)

        # Wait for login popup
        WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "#popupLogin"))
        ).click()

        # Enter credentials
        username_field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#popupUsername"))
        )
        username_field.clear()
        username_field.send_keys(self.credentials.username)

        password_field = driver.find_element(By.CSS_SELECTOR, "#popupPassword")
        password_field.clear()
        password_field.send_keys(self.credentials.password)

        # Click login
        driver.find_element(By.CSS_SELECTOR, "#popupLoginBtn").click()

        # Wait for successful login
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".user-name"))
        )
        logger.info("Login successful")

    def _watch_video_on_page(self, driver: webdriver.Chrome, material: Material):
        """Watch video on current page"""
        # Wait for video player
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".video-js, video"))
        )

        # Click play
        try:
            play_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, ".vjs-big-play-button"))
            )
            play_button.click()
        except TimeoutException:
            pass

        # Get duration and wait
        duration_seconds = material.duration_seconds or 60
        logger.info(f"Waiting {duration_seconds} seconds for video...")
        time.sleep(min(duration_seconds, 300))  # Cap at 5 minutes for safety

    def _confirm_material_on_page(self, driver: webdriver.Chrome):
        """Confirm material completion on current page"""
        try:
            # Look for exit/confirm button
            exit_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "#exitBtn, .confirm-btn, .complete-btn"))
            )
            exit_button.click()
            logger.info("Clicked confirmation button")
            time.sleep(2)
        except TimeoutException:
            logger.warning("Confirmation button not found")

    def _parse_duration_to_seconds(self, duration_str: str) -> int:
        """Parse duration string (HH:MM:SS or MM:SS) to seconds"""
        try:
            parts = duration_str.strip().split(':')
            if len(parts) == 3:  # HH:MM:SS
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 2:  # MM:SS
                return int(parts[0]) * 60 + int(parts[1])
            else:
                return 0
        except Exception as e:
            logger.error(f"Error parsing duration '{duration_str}': {e}")
            return 0
