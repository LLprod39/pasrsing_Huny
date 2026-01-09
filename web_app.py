import logging
import asyncio
from typing import List, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import os

from config import Config
from auth import AuthManager
from course_parser import CourseParser
from material_processor import MaterialProcessor
from test_solver import TestSolver
from task_manager import TaskManager  # NEW
from logger import setup_logger

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
    auth_manager: Optional[AuthManager] = None
    course_parser: Optional[CourseParser] = None
    material_processor: Optional[MaterialProcessor] = None
    test_solver: Optional[TestSolver] = None
    task_manager: Optional[TaskManager] = None # NEW
    
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
        if state.auth_manager and request.force_restart:
            if state.auth_manager.driver:
                state.auth_manager.close()
            state.auth_manager = None
            state.task_manager = None

        if not state.auth_manager:
            Config.validate()
            state.auth_manager = AuthManager()
            
        if not state.auth_manager.driver: # Если драйвер упал или еще не создан
             if not state.auth_manager.login():
                 if not state.auth_manager.login():
                    raise HTTPException(status_code=401, detail="Не удалось авторизоваться. Проверьте .env")
        
        # Инициализируем парсеры если их нет
        if not state.course_parser:
            state.course_parser = CourseParser(state.auth_manager.driver)
            state.material_processor = MaterialProcessor(state.auth_manager.driver)
            state.test_solver = TestSolver(state.auth_manager.driver)
            state.task_manager = TaskManager(state.auth_manager.driver, state.material_processor, state.test_solver) # NEW

        return {"status": "success", "message": "Авторизация прошла успешно"}
    except Exception as e:
        logger.error(f"Login error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/semesters")
async def get_semesters():
    """Получение списка семестров"""
    if not state.course_parser:
         raise HTTPException(status_code=401, detail="Not initialized. Please login first.")
    
    try:
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

@app.get("/api/tasks")
async def get_tasks():
    """Получение статуса задач"""
    if not state.task_manager:
         return {"tasks": []}
    
    # Process tick to update tasks
    state.task_manager.process_tick()
    
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
    log_file = "parser.log" 
    if os.path.exists(log_file):
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            # Вернем последние 100 строк
            return {"logs": lines[-100:]}
    return {"logs": []}


# Подключение статики в самом конце, чтобы не перекрывать API
if os.path.exists("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    uvicorn.run("web_app:app", host="0.0.0.0", port=8000, reload=True)
