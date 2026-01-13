"""LMS automation modules (browser/session logic)."""

from synergy_lms.lms.auth import AuthManager
from synergy_lms.lms.course_parser import CourseParser
from synergy_lms.lms.gologin_manager import GologinManager
from synergy_lms.lms.material_processor import MaterialProcessor
from synergy_lms.lms.test_solver import TestSolver
from synergy_lms.lms.task_manager import TaskManager

__all__ = [
    "AuthManager",
    "CourseParser",
    "GologinManager",
    "MaterialProcessor",
    "TestSolver",
    "TaskManager",
]

