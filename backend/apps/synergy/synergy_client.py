from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from synergy_lms.lms.auth import AuthManager
from synergy_lms.lms.course_parser import CourseParser


class SynergyLoginError(RuntimeError):
    pass


@dataclass
class SeleniumSynergyClient:
    """Thin OOP wrapper around the existing `synergy_lms` Selenium classes.

    This class is intended to be used inside Celery workers (no HTTP request context).
    """

    use_gologin: bool = False
    auth: Optional[AuthManager] = None
    course_parser: Optional[CourseParser] = None

    def __enter__(self) -> "SeleniumSynergyClient":
        self.auth = AuthManager()
        # Avoid Gologin by default for per-student runs.
        self.auth.driver = self.auth.create_driver(use_gologin=self.use_gologin)
        self.course_parser = CourseParser(self.auth.driver)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if self.auth:
                self.auth.close()
        finally:
            self.auth = None
            self.course_parser = None

    @property
    def driver(self):
        if not self.auth or not self.auth.driver:
            raise RuntimeError("Driver not initialized")
        return self.auth.driver

    def login(self, *, login: str, password: str) -> None:
        if not self.auth:
            raise RuntimeError("Client not initialized (use as a context manager)")
        ok = self.auth.login(login=login, password=password)
        if not ok:
            raise SynergyLoginError("Synergy login failed (invalid credentials or page changed)")

    def get_semesters(self) -> list[int]:
        if not self.course_parser:
            raise RuntimeError("Client not initialized (use as a context manager)")
        return list(self.course_parser.get_available_semesters())

    def get_courses(self, semester_number: int) -> list[dict]:
        if not self.course_parser:
            raise RuntimeError("Client not initialized (use as a context manager)")
        return list(self.course_parser.get_semester_courses(int(semester_number)))

    def get_course_materials(self, course_url: str) -> tuple[list[dict], list[dict]]:
        """Return (structured, flat) materials."""
        if not self.course_parser:
            raise RuntimeError("Client not initialized (use as a context manager)")
        structured = list(self.course_parser.get_course_materials(course_url))
        flat = list(self.course_parser.flatten_materials(structured))
        return structured, flat

