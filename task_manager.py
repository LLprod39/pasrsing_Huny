import time
import uuid
import logging
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
        self.message = "Initializing..."
        self.created_at = time.time()
        self.window_handle: Optional[str] = None
        self.error: Optional[str] = None
        self.last_update = time.time()
        self.type = material_data.get('type', 'material')

    def to_dict(self):
        return {
            "id": self.id,
            "material_name": self.material.get('name'),
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "error": self.error,
            "type": self.type
        }

class TaskManager:
    def __init__(self, driver: webdriver.Chrome, material_processor, test_solver):
        self.driver = driver
        self.material_processor = material_processor
        self.test_solver = test_solver
        self.tasks: Dict[str, Task] = {}
        self.active = True
        self.main_window_handle = driver.current_window_handle
        self.max_concurrent_tasks = 2  # Default to 2

    def set_max_concurrent_tasks(self, n: int):
        self.max_concurrent_tasks = max(1, min(n, 20)) # Safety bounds
        logger.info(f"Max concurrent tasks set to {self.max_concurrent_tasks}")

    def add_task(self, material_data: dict) -> str:
        task = Task(material_data)
        self.tasks[task.id] = task
        logger.info(f"Task created: {task.id} for {material_data.get('name')}")
        return task.id

    def stop_task(self, task_id: str):
        if task_id in self.tasks:
            task = self.tasks[task_id]
            if task.status in [TaskState.RUNNING, TaskState.PENDING]:
                task.status = TaskState.FAILED
                task.message = "Stopped by user"
                # Close window if exists
                if task.window_handle:
                    try:
                        self.driver.switch_to.window(task.window_handle)
                        self.driver.close()
                    except Exception:
                        pass
                    finally:
                        self.driver.switch_to.window(self.main_window_handle)

    def get_tasks(self) -> List[dict]:
        return [t.to_dict() for t in self.tasks.values()]

    def process_tick(self):
        """Called periodically to advance tasks"""
        if not self.tasks:
            return

        # 1. Count running tasks
        running_count = len([t for t in self.tasks.values() if t.status == TaskState.RUNNING])
        
        # 2. Check completions / updates for running tasks
        # We iterate a copy to avoid modification issues if we were removing (though we aren't here)
        running_tasks = [t for t in self.tasks.values() if t.status == TaskState.RUNNING]
        for task in running_tasks:
            self._update_task(task)

        # Re-count after updates (some might have finished)
        running_count = len([t for t in self.tasks.values() if t.status == TaskState.RUNNING])

        # 3. Start new tasks if slot available
        if running_count < self.max_concurrent_tasks:
            pending_tasks = [t for t in self.tasks.values() if t.status == TaskState.PENDING]
            # Sort by creation time to be fair? Default dict order is usually insertion order in Py3.7+
            
            slots_available = self.max_concurrent_tasks - running_count
            for i in range(min(slots_available, len(pending_tasks))):
                 task = pending_tasks[i]
                 self._start_task(task)

    def _start_task(self, task: Task):
        try:
            logger.info(f"Starting task {task.id}...")
            task.status = TaskState.RUNNING
            task.message = "Opening tab..."
            
            # Open new tab
            self.driver.switch_to.new_window('tab')
            task.window_handle = self.driver.current_window_handle
            
            # Delegate to processor start procedure
            if task.type == 'test':
                 # Tests might be blocking for now, or we need to refactor test solver too.
                 # For now, let's treat tests as blocking operations in a separate thread? 
                 # No, Selenium is not thread safe. 
                 # We will wrap test solver in a similar start/check logic later.
                 # For now, run synchronously (blocking other tabs temporarily)
                 task.message = "Solving test (blocking)..."
                 res = self.test_solver.solve_test(
                     task.material['url'],
                     task.material['name'],
                     course_url=task.material.get('course_url'),
                 )
                 if res.get('solved'):
                     task.status = TaskState.COMPLETED
                     task.progress = 100
                     task.message = f"Test passed. Score: {res.get('score')}"
                 else:
                     task.status = TaskState.FAILED
                     task.error = res.get('error')
                 
                 # Close tab
                 self.driver.close()
                 self.driver.switch_to.window(self.main_window_handle)
            else:
                # Material (Video/PDF)
                self.material_processor.start_material_processing(task.material, task)
                
        except Exception as e:
            logger.error(f"Failed to start task {task.id}: {e}", exc_info=True)
            task.status = TaskState.FAILED
            task.error = str(e)
            try:
                 if task.window_handle:
                    self.driver.close()
            except: pass
            self.driver.switch_to.window(self.main_window_handle)

    def _update_task(self, task: Task):
        try:
            # Switch to task window
            if not task.window_handle:
                return # Should not happen for running tasks
            
            # Check if window still exists
            if task.window_handle not in self.driver.window_handles:
                task.status = TaskState.FAILED
                task.error = "Window closed unexpectedly"
                return

            self.driver.switch_to.window(task.window_handle)
            
            # Delegate to processor check procedure
            done = self.material_processor.check_material_progress(task)
            
            if done:
                task.status = TaskState.COMPLETED
                task.progress = 100
                logger.info(f"Task {task.id} completed.")
                self.driver.close()
                self.driver.switch_to.window(self.main_window_handle)
                task.window_handle = None
                
        except Exception as e:
            logger.error(f"Error updating task {task.id}: {e}")
            task.last_update = time.time()
            # Don't fail immediately on transient errors, but maybe count them?
            pass
        finally:
            # Always try to switch back to avoid getting stuck in a closed window
            try:
                if self.driver.current_window_handle != self.main_window_handle:
                     # Stay in context or switch back?
                     # Ideally we should switch back to main only when needed, but for safety in single-threaded env:
                     self.driver.switch_to.window(self.main_window_handle)
            except:
                self.driver.switch_to.window(self.main_window_handle)
