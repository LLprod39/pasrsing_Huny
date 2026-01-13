from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from synergy_lms.config import Config
from synergy_lms.logger import setup_logger
from synergy_lms.lms.auth import AuthManager
from synergy_lms.lms.course_parser import CourseParser
from synergy_lms.lms.material_processor import MaterialProcessor
from synergy_lms.lms.test_solver import TestSolver
from synergy_lms.lms.task_manager import TaskManager

# Настройка логгера
logger = setup_logger("web_app")

app = FastAPI(title="Synergy LMS Parser Web UI")

# CORS config
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Глобальные объекты (синглтоны для сессии)
class GlobalState:
    def __init__(self) -> None:
        # Один общий lock на WebDriver для всех операций (Selenium не потокобезопасен)
        self.driver_lock = threading.RLock()

        self.auth_manager: Optional[AuthManager] = None
        self.course_parser: Optional[CourseParser] = None
        self.material_processor: Optional[MaterialProcessor] = None
        self.test_solver: Optional[TestSolver] = None
        self.task_manager: Optional[TaskManager] = None


state = GlobalState()

# Модели данных
class LoginRequest(BaseModel):
    # Если мы захотим передавать креденшелы с фронта, 
    # но пока берем из .env, так что можно оставить пустым или опциональным
    force_restart: bool = False


class MaterialProcessRequest(BaseModel):
    material_url: str
    material_name: str
    material_type: str
    course_url: Optional[str] = None # Added for context

class SettingsRequest(BaseModel):
    max_concurrent_tasks: int

# API Endpoints

@app.post("/api/login")
async def login(request: LoginRequest):
    """Авторизация и инициализация драйвера"""
    try:
        if request.force_restart:
            # Гарантированно закрываем старую сессию (если есть)
            try:
                if state.task_manager:
                    state.task_manager.close()
            except Exception:
                pass
            try:
                if state.auth_manager:
                    with state.driver_lock:
                        state.auth_manager.close()
            except Exception:
                pass

            state.auth_manager = None
            state.course_parser = None
            state.material_processor = None
            state.test_solver = None
            state.task_manager = None

        if not state.auth_manager:
            Config.validate()
            state.auth_manager = AuthManager()

        # Если драйвер ещё не создан/упал — создаём + логинимся
        with state.driver_lock:
            ok = state.auth_manager.login()
        if not ok:
            raise HTTPException(status_code=401, detail="Не удалось авторизоваться. Проверьте .env (LOGIN/PASSWORD)")
        
        # Инициализируем парсеры если их нет
        if not state.course_parser:
            state.course_parser = CourseParser(state.auth_manager.driver)
            state.material_processor = MaterialProcessor(state.auth_manager.driver)
            state.test_solver = TestSolver(state.auth_manager.driver)
            state.task_manager = TaskManager(
                state.auth_manager.driver,
                state.material_processor,
                state.test_solver,
                driver_lock=state.driver_lock,
            )

        return {"status": "success", "message": "Авторизация прошла успешно"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/semesters")
async def get_semesters():
    """Получение списка семестров"""
    if not state.course_parser:
         raise HTTPException(status_code=401, detail="Not initialized. Please login first.")
    
    try:
        with state.driver_lock:
            semesters = state.course_parser.get_available_semesters()
        return {"semesters": semesters}
    except Exception as e:
        logger.error(f"Error getting semesters: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/courses/{semester_id}")
async def get_courses(semester_id: int):
    """Получение курсов семестра"""
    if not state.course_parser:
         raise HTTPException(status_code=401, detail="Not initialized.")
    
    try:
        with state.driver_lock:
            courses = state.course_parser.get_semester_courses(semester_id)
        return {"courses": courses}
    except Exception as e:
        logger.error(f"Error getting courses: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/materials")
async def get_materials(course_url: str):
    """Получение материалов курса"""
    if not state.course_parser:
         raise HTTPException(status_code=401, detail="Not initialized.")
    
    try:
        with state.driver_lock:
            structured = state.course_parser.get_course_materials(course_url)
            flat = state.course_parser.flatten_materials(structured)
        # Добавляем course_url
        for item in flat:
            item['course_url'] = course_url
        return {"structured": structured, "flat": flat}
    except Exception as e:
        logger.error(f"Error getting materials: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/process_material")
async def process_material(request: MaterialProcessRequest):
    """Добавление задачи на обработку"""
    if not state.task_manager:
         raise HTTPException(status_code=401, detail="Not initialized.")
    
    try:
        material_data = {
            'name': request.material_name,
            'url': request.material_url,
            'type': request.material_type,
            'course_url': request.course_url
        }
        
        task_id = state.task_manager.add_task(material_data)
        return {"status": "queued", "task_id": task_id, "message": f"Added task: {request.material_name}"}
    except Exception as e:
        logger.error(f"Error creating task: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/settings")
async def update_settings(request: SettingsRequest):
    """Обновление настроек UI (например, max tabs)."""
    if not state.task_manager:
        raise HTTPException(status_code=401, detail="Not initialized.")
    try:
        state.task_manager.set_max_concurrent_tasks(request.max_concurrent_tasks)
        return {"status": "ok", "max_concurrent_tasks": state.task_manager.max_concurrent_tasks}
    except Exception as e:
        logger.error(f"Error updating settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/tasks")
async def get_tasks():
    """Получение статуса задач"""
    if not state.task_manager:
         return {"tasks": []}
    return {"tasks": state.task_manager.get_tasks()}

@app.post("/api/tasks/stop/{task_id}")
async def stop_task(task_id: str):
    """Остановка задачи"""
    if not state.task_manager:
         raise HTTPException(status_code=401, detail="Not initialized")
    
    state.task_manager.stop_task(task_id)
    return {"status": "stopped"}

@app.get("/api/logs")
async def get_logs():
    """Чтение последних логов"""
    log_file = Config.LOG_FILE or "parser.log"
    if os.path.exists(log_file):
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            # Вернем последние 100 строк
            return {"logs": lines[-100:]}
    return {"logs": []}


# Подключение статики в самом конце, чтобы не перекрывать API
STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

if __name__ == "__main__":
    uvicorn.run("synergy_lms.web.app:app", host="0.0.0.0", port=8000, reload=True)
