from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from typing import Dict, List, Optional

from selenium import webdriver

logger = logging.getLogger("task_manager")


class TaskState:
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Task:
    def __init__(self, material_data: dict):
        self.id = str(uuid.uuid4())
        self.material = material_data
        self.status = TaskState.PENDING
        self.progress = 0
        self.message = "Queued"
        self.created_at = time.time()
        self.window_handle: Optional[str] = None
        self.error: Optional[str] = None
        self.last_update = time.time()
        self.type = material_data.get("type", "material")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "material_name": self.material.get("name"),
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "error": self.error,
            "type": self.type,
        }


class TaskManager:
    """Очередь задач для Web UI.

    Selenium/WebDriver не потокобезопасен, поэтому:
    - задачи выполняются последовательно в одном воркер-треде
    - доступ к driver защищён общим lock'ом (можно шарить с API эндпоинтами)
    """

    def __init__(
        self,
        driver: webdriver.Chrome,
        material_processor,
        test_solver,
        *,
        driver_lock: Optional[threading.RLock] = None,
    ):
        self.driver = driver
        self.material_processor = material_processor
        self.test_solver = test_solver

        self._driver_lock = driver_lock or threading.RLock()
        self._tasks_lock = threading.RLock()
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._stop = threading.Event()

        self.tasks: Dict[str, Task] = {}
        self.max_concurrent_tasks = 1  # Selenium: безопасный дефолт (реально выполняем по 1)

        # фиксируем "главное" окно (если оно пропадёт — будем фолбэчиться на первое доступное)
        try:
            self.main_window_handle = driver.current_window_handle
        except Exception:
            self.main_window_handle = None

        self._worker = threading.Thread(target=self._worker_loop, name="synergy-task-worker", daemon=True)
        self._worker.start()

    @property
    def driver_lock(self) -> threading.RLock:
        return self._driver_lock

    def set_max_concurrent_tasks(self, n: int) -> None:
        # Сейчас выполняем по 1 задаче (Selenium). Значение храним, чтобы UI не падал.
        self.max_concurrent_tasks = max(1, min(int(n), 20))
        logger.info(f"Max concurrent tasks set to {self.max_concurrent_tasks} (effective=1)")

    def add_task(self, material_data: dict) -> str:
        task = Task(material_data)
        with self._tasks_lock:
            self.tasks[task.id] = task
        self._queue.put(task.id)
        logger.info(f"Task queued: {task.id} for {material_data.get('name')}")
        return task.id

    def stop_task(self, task_id: str) -> None:
        """Best-effort остановка.

        Для PENDING — гарантированно.
        Для RUNNING — помечаем как FAILED (текущую Selenium-операцию прервать безопасно нельзя).
        """
        with self._tasks_lock:
            task = self.tasks.get(task_id)
            if not task:
                return
            if task.status == TaskState.PENDING:
                task.status = TaskState.FAILED
                task.message = "Stopped by user (before start)"
                task.last_update = time.time()
                return
            if task.status == TaskState.RUNNING:
                task.status = TaskState.FAILED
                task.message = "Stop requested (will finish current step)"
                task.last_update = time.time()

    def get_tasks(self) -> List[dict]:
        with self._tasks_lock:
            return [t.to_dict() for t in self.tasks.values()]

    def close(self) -> None:
        self._stop.set()

    # ===== Worker internals =====

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                task_id = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            with self._tasks_lock:
                task = self.tasks.get(task_id)
                if not task or task.status != TaskState.PENDING:
                    continue
                task.status = TaskState.RUNNING
                task.message = "Running..."
                task.progress = 0
                task.last_update = time.time()

            try:
                self._run_task(task)
            except Exception as e:
                logger.error(f"Task failed {task_id}: {e}", exc_info=True)
                with self._tasks_lock:
                    task.status = TaskState.FAILED
                    task.error = str(e)
                    task.message = "Failed"
                    task.last_update = time.time()

    def _safe_switch_to_main(self) -> None:
        if self.main_window_handle and self.main_window_handle in self.driver.window_handles:
            self.driver.switch_to.window(self.main_window_handle)
            return
        # fallback
        handles = self.driver.window_handles
        if handles:
            self.main_window_handle = handles[0]
            self.driver.switch_to.window(self.main_window_handle)

    def _open_new_tab(self) -> str:
        try:
            self.driver.switch_to.new_window("tab")
        except Exception:
            self.driver.execute_script("window.open('about:blank','_blank');")
            self.driver.switch_to.window(self.driver.window_handles[-1])
        return self.driver.current_window_handle

    def _run_task(self, task: Task) -> None:
        # Все действия с driver — строго под lock
        with self._driver_lock:
            self._safe_switch_to_main()
            task.window_handle = self._open_new_tab()

            try:
                if task.type == "test":
                    with self._tasks_lock:
                        task.message = "Solving test..."
                        task.last_update = time.time()

                    res = self.test_solver.solve_test(
                        task.material["url"],
                        task.material.get("name", ""),
                        course_url=task.material.get("course_url"),
                    )
                    if res.get("solved"):
                        with self._tasks_lock:
                            task.status = TaskState.COMPLETED
                            task.progress = 100
                            task.message = f"Test passed. Score: {res.get('score')}"
                            task.last_update = time.time()
                    else:
                        with self._tasks_lock:
                            task.status = TaskState.FAILED
                            task.error = res.get("error")
                            task.message = "Test failed"
                            task.last_update = time.time()
                else:
                    with self._tasks_lock:
                        task.message = "Processing material..."
                        task.last_update = time.time()

                    res = self.material_processor.process_material(task.material)
                    if res.get("processed"):
                        with self._tasks_lock:
                            task.status = TaskState.COMPLETED
                            task.progress = 100
                            task.message = "Completed"
                            task.last_update = time.time()
                    else:
                        with self._tasks_lock:
                            task.status = TaskState.FAILED
                            task.error = res.get("error")
                            task.message = "Failed"
                            task.last_update = time.time()
            finally:
                # закрываем вкладку задачи и возвращаемся в главное окно
                try:
                    if task.window_handle and task.window_handle in self.driver.window_handles:
                        self.driver.switch_to.window(task.window_handle)
                        self.driver.close()
                except Exception:
                    pass
                finally:
                    try:
                        self._safe_switch_to_main()
                    except Exception:
                        pass
                task.window_handle = None
