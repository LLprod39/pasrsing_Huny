"""Полноэкранный CLI/TUI в стиле "чат-клиента" для парсера LMS Synergy.

Запуск:
  python synergy_tui.py
"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Union

from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Header, Input, OptionList, RichLog, SelectionList, Static
from textual.widgets.option_list import Option
from textual.widgets.selection_list import Selection


# ---------------------------
# Back-end worker (Selenium) — живёт в отдельном потоке
# ---------------------------


@dataclass(frozen=True)
class Cmd:
    type: str
    payload: Dict[str, Any]


@dataclass(frozen=True)
class Evt:
    type: str
    payload: Dict[str, Any]


class _QueueLogHandler(logging.Handler):
    def __init__(self, out_q: "queue.Queue[Evt]"):
        super().__init__()
        self._out_q = out_q

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self._out_q.put(Evt("log", {"text": msg}))
        except Exception:
            # Никогда не падаем из логгера
            pass


class SynergyBackend:
    """Один поток, который последовательно выполняет команды UI и общается событиями."""

    def __init__(self, cmd_q: "queue.Queue[Cmd]", evt_q: "queue.Queue[Evt]"):
        self.cmd_q = cmd_q
        self.evt_q = evt_q
        self._stop_all = threading.Event()
        self._stop_run = threading.Event()

        self.auth_manager = None
        self.course_parser = None
        self.material_processor = None
        self.test_solver = None

        self.semesters: List[int] = []
        self.courses: List[Dict[str, Any]] = []
        self.current_course: Optional[Dict[str, Any]] = None
        self.current_materials: List[Dict[str, Any]] = []
        self.selected_material_indices: List[int] = []

    def start(self) -> None:
        t = threading.Thread(target=self._run_loop, name="synergy-backend", daemon=True)
        t.start()

    def stop(self) -> None:
        self._stop_all.set()
        self.cmd_q.put(Cmd("shutdown", {}))

    def _emit(self, type_: str, **payload: Any) -> None:
        self.evt_q.put(Evt(type_, payload))

    def _attach_ui_logging(self) -> None:
        """Убираем "живой" вывод в консоль и добавляем лог-поток в UI."""
        handler = _QueueLogHandler(self.evt_q)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

        # Удаляем StreamHandler'ы у всех логгеров, чтобы не ломать полноэкранный UI.
        root = logging.getLogger()
        for h in list(root.handlers):
            if isinstance(h, logging.StreamHandler):
                root.removeHandler(h)
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)

        for logger_name in list(logging.Logger.manager.loggerDict.keys()):
            lg = logging.getLogger(logger_name)
            for h in list(lg.handlers):
                if isinstance(h, logging.StreamHandler):
                    lg.removeHandler(h)
            lg.addHandler(handler)
            lg.setLevel(logging.DEBUG)

    def _require_ready(self) -> bool:
        if not (self.auth_manager and self.course_parser and self.material_processor and self.test_solver):
            self._emit(
                "assistant",
                text="Сессия не запущена. Сначала выполните `/start`.",
                level="warn",
            )
            return False
        return True

    def _run_loop(self) -> None:
        self._attach_ui_logging()
        self._emit(
            "assistant",
            text=(
                "Готово.\n"
                "Выбор стрелками: семестр → курс → материалы.\n"
                "Хоткеи: `s` старт, `r` запуск, `x` стоп, `a` выбрать всё, `q` выход.\n"
                "Текстовые команды тоже работают: `/start`, `/sem N`, `/open I`, `/pick all|1,2`, `/run`, `/stop`, `/status`, `/exit`."
            ),
        )

        while not self._stop_all.is_set():
            try:
                cmd = self.cmd_q.get(timeout=0.2)
            except queue.Empty:
                continue

            if cmd.type == "shutdown":
                break

            try:
                if cmd.type == "start":
                    self._cmd_start()
                elif cmd.type == "select_semester":
                    self._cmd_select_semester(int(cmd.payload["semester"]))
                elif cmd.type == "open_course":
                    self._cmd_open_course(int(cmd.payload["index"]))
                elif cmd.type == "pick_materials":
                    self._cmd_pick_materials(cmd.payload["spec"])
                elif cmd.type == "run":
                    self._cmd_run()
                elif cmd.type == "stop_run":
                    self._stop_run.set()
                    self._emit("assistant", text="Ок, останавливаю после текущего шага…", level="warn")
                elif cmd.type == "status":
                    self._cmd_status()
            except Exception as e:
                self._emit("assistant", text=f"Ошибка: {e}", level="error")

        # shutdown
        try:
            if self.auth_manager:
                self.auth_manager.close()
        except Exception:
            pass
        self._emit("assistant", text="Сессия закрыта.", level="info")

    def _cmd_start(self) -> None:
        self._emit("assistant", text="Запускаю сессию: проверка `.env`, старт браузера, логин…")

        from config import Config
        from auth import AuthManager
        from course_parser import CourseParser
        from material_processor import MaterialProcessor
        from test_solver import TestSolver

        Config.validate()
        self.auth_manager = AuthManager()
        if not self.auth_manager.login():
            raise RuntimeError("Не удалось авторизоваться. Проверьте LOGIN/PASSWORD в `.env`.")

        self.course_parser = CourseParser(self.auth_manager.driver)
        self.material_processor = MaterialProcessor(self.auth_manager.driver)
        self.test_solver = TestSolver(self.auth_manager.driver)

        self.semesters = self.course_parser.get_available_semesters()
        if not self.semesters:
            raise RuntimeError("Не нашёл доступных семестров.")

        self._emit("semesters", semesters=self.semesters)
        self._emit("assistant", text="Авторизация успешна. Выберите семестр командой `/sem <N>`.")

    def _cmd_select_semester(self, semester: int) -> None:
        if not self._require_ready():
            return
        self._emit("assistant", text=f"Загружаю курсы для семестра {semester}…")
        self.courses = self.course_parser.get_semester_courses(semester)
        if not self.courses:
            self._emit("assistant", text="Курсы не найдены.", level="warn")
            return
        self.current_course = None
        self.current_materials = []
        self.selected_material_indices = []
        self._emit("courses", courses=self.courses, semester=semester)
        self._emit("assistant", text="Откройте курс: `/open <I>`.")

    def _cmd_open_course(self, index: int) -> None:
        if not self._require_ready():
            return
        if index < 1 or index > len(self.courses):
            self._emit("assistant", text="Некорректный номер курса.", level="warn")
            return
        self.current_course = self.courses[index - 1]
        self._emit("assistant", text=f"Открываю курс: {self.current_course['name']}…")

        structured = self.course_parser.get_course_materials(self.current_course["url"])
        flat = self.course_parser.flatten_materials(structured)
        for m in flat:
            m["course_url"] = self.current_course["url"]
        self.current_materials = flat
        self.selected_material_indices = []
        self._emit("materials", materials=self.current_materials, course=self.current_course)
        self._emit("assistant", text="Выберите материалы: `/pick all` или `/pick 1,2,3`, затем `/run`.")

    def _cmd_pick_materials(self, spec: Union[str, List[int]]) -> None:
        if not self._require_ready():
            return
        if not self.current_materials:
            self._emit("assistant", text="Сначала откройте курс: `/open <I>`.", level="warn")
            return

        if isinstance(spec, list):
            self.selected_material_indices = [int(i) for i in spec if 1 <= int(i) <= len(self.current_materials)]
        else:
            spec = str(spec).strip().lower()
            if spec in ("all", "все"):
                self.selected_material_indices = list(range(1, len(self.current_materials) + 1))
            else:
                items: List[int] = []
                for part in spec.split(","):
                    part = part.strip()
                    if not part:
                        continue
                    items.append(int(part))
                self.selected_material_indices = [i for i in items if 1 <= i <= len(self.current_materials)]

        if not self.selected_material_indices:
            self._emit("assistant", text="Ничего не выбрано (проверьте номера).", level="warn")
            return

        picked = [self.current_materials[i - 1] for i in self.selected_material_indices]
        self._emit("picked", picked=picked)
        self._emit("assistant", text=f"Выбрано материалов: {len(picked)}. Запуск: `/run`.")

    def _cmd_run(self) -> None:
        if not self._require_ready():
            return
        if not self.current_course or not self.current_materials:
            self._emit("assistant", text="Сначала выберите курс и материалы.", level="warn")
            return
        if not self.selected_material_indices:
            self._emit("assistant", text="Сначала выберите материалы: `/pick ...`.", level="warn")
            return

        self._stop_run.clear()
        picked = [self.current_materials[i - 1] for i in self.selected_material_indices]

        self._emit("assistant", text=f"Старт обработки: {len(picked)} материалов. `/stop` — остановка.")
        ok = 0
        fail = 0

        for idx, material in enumerate(picked, start=1):
            if self._stop_run.is_set():
                self._emit("assistant", text="Остановлено пользователем.", level="warn")
                break

            name = material.get("name", "Без названия")
            mtype = material.get("type", "material")
            self._emit("progress", current=idx, total=len(picked), name=name, type=mtype)

            try:
                if mtype == "test":
                    res = self.test_solver.solve_test(material["url"], name, course_url=material.get("course_url"))
                    if res.get("solved"):
                        ok += 1
                        self._emit("assistant", text=f"✅ Тест пройден: {name} (оценка: {res.get('score')})")
                    else:
                        fail += 1
                        self._emit("assistant", text=f"❌ Тест: {name} — {res.get('error')}", level="error")
                else:
                    res = self.material_processor.process_material(material)
                    if res.get("processed"):
                        ok += 1
                        self._emit("assistant", text=f"✅ Материал обработан: {name}")
                    else:
                        fail += 1
                        self._emit("assistant", text=f"❌ Материал: {name} — {res.get('error')}", level="error")
            except Exception as e:
                fail += 1
                self._emit("assistant", text=f"❌ Ошибка: {name} — {e}", level="error")

        self._emit("assistant", text=f"Готово. Успешно: {ok}, ошибки: {fail}.")

    def _cmd_status(self) -> None:
        ready = bool(self.auth_manager and self.auth_manager.driver)
        self._emit(
            "status",
            ready=ready,
            semesters=self.semesters,
            courses=len(self.courses),
            current_course=(self.current_course or {}).get("name"),
            materials=len(self.current_materials),
            picked=len(self.selected_material_indices),
        )


# ---------------------------
# Textual UI
# ---------------------------


class SynergyTUI(App):
    TITLE = "Synergy CLI"
    SUB_TITLE = "TUI (чат-интерфейс)"

    BINDINGS = [
        ("s", "start", "Старт"),
        ("r", "run", "Запуск"),
        ("x", "stop", "Стоп"),
        ("a", "select_all", "Выбрать всё"),
        ("q", "quit", "Выход"),
        ("tab", "focus_next", "Фокус далее"),
        ("shift+tab", "focus_previous", "Фокус назад"),
    ]

    CSS = """
    Screen {
        background: #0b1020;
    }

    #main {
        height: 1fr;
    }

    #left {
        width: 2fr;
        height: 1fr;
    }

    #selectors {
        height: 18;
        border: round #2f3b66;
        background: #0b1020;
        padding: 0 1;
    }

    #selector_title {
        height: 1;
        color: #a8b3ff;
    }

    #semesters, #courses, #materials {
        height: 1fr;
        border: round #2f3b66;
        background: #0b1020;
    }

    #chat {
        height: 1fr;
        border: round #2f3b66;
        background: #0b1020;
    }

    #logs {
        width: 1fr;
        border: round #2f3b66;
        background: #0b1020;
    }

    #input_box {
        height: auto;
        border: round #2f3b66;
        background: #0b1020;
    }

    Input {
        background: #0b1020;
        color: #e8ecff;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._cmd_q: "queue.Queue[Cmd]" = queue.Queue()
        self._evt_q: "queue.Queue[Evt]" = queue.Queue()
        self._backend = SynergyBackend(self._cmd_q, self._evt_q)
        self._materials_loaded = False

    status_line: reactive[str] = reactive(
        "↑↓ Enter: выбрать • Space: отметить материал • s: старт • r: запуск • x: стоп • a: всё • q: выход"
    )

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main"):
            with Vertical(id="left"):
                with Vertical(id="selectors"):
                    yield Static("", id="selector_title")
                    with Horizontal():
                        yield OptionList(id="semesters")
                        yield OptionList(id="courses")
                        yield SelectionList(id="materials")
                yield RichLog(id="chat", wrap=True, highlight=True, markup=True, auto_scroll=True)
            yield RichLog(id="logs", wrap=True, highlight=False, markup=False, auto_scroll=True)
        with Vertical(id="input_box"):
            yield Input(placeholder="Введите команду (/help, /start, /sem 1, /open 1, /pick all, /run, /stop, /exit)…", id="input")
        yield Footer()

    def on_mount(self) -> None:
        self._backend.start()
        self.set_interval(0.1, self._drain_events)
        self.query_one("#selector_title", Static).update(self.status_line)
        self.query_one("#semesters", OptionList).focus()

    def _chat(self) -> RichLog:
        return self.query_one("#chat", RichLog)

    def _logs(self) -> RichLog:
        return self.query_one("#logs", RichLog)

    def _post_user(self, text: str) -> None:
        self._chat().write(Panel(Text(text, style="bold #e8ecff"), title="Вы", border_style="#485aa3"))

    def _post_assistant(self, text: str, level: str = "info") -> None:
        styles = {"info": "#a8b3ff", "warn": "yellow", "error": "red"}
        title = {"info": "Synergy", "warn": "Synergy • Внимание", "error": "Synergy • Ошибка"}.get(level, "Synergy")
        self._chat().write(Panel(Text(text, style=styles.get(level, "#a8b3ff")), title=title, border_style="#2f3b66"))

    def _post_table(self, title: str, rows: Sequence[Sequence[str]], headers: Sequence[str]) -> None:
        table = Table(title=title, show_lines=False, header_style="bold #e8ecff")
        for h in headers:
            table.add_column(h, overflow="fold")
        for r in rows:
            table.add_row(*r)
        self._chat().write(Panel(table, border_style="#2f3b66"))

    def _drain_events(self) -> None:
        drained = 0
        while drained < 200:
            try:
                evt = self._evt_q.get_nowait()
            except queue.Empty:
                break
            drained += 1
            self._handle_evt(evt)

    def _handle_evt(self, evt: Evt) -> None:
        if evt.type == "assistant":
            self._post_assistant(evt.payload.get("text", ""), level=evt.payload.get("level", "info"))
            return
        if evt.type == "log":
            self._logs().write(evt.payload.get("text", ""))
            return
        if evt.type == "semesters":
            semesters = evt.payload.get("semesters", [])
            sem_list = self.query_one("#semesters", OptionList)
            sem_list.clear_options()
            for s in semesters:
                sem_list.add_option(Option(f"Семестр {s}", id=str(s)))
            # Мягкая подсказка в чат
            self._post_assistant("Выберите семестр (↑↓ и Enter).")
            return
        if evt.type == "courses":
            courses = evt.payload.get("courses", [])
            course_list = self.query_one("#courses", OptionList)
            course_list.clear_options()
            for i, c in enumerate(courses, start=1):
                name = str(c.get("name", ""))
                ctl = str(c.get("control_type", ""))
                course_list.add_option(Option(f"{i}. {name} ({ctl})", id=str(i)))
            self._post_assistant("Выберите курс (↑↓ и Enter).")
            return
        if evt.type == "materials":
            materials = evt.payload.get("materials", [])
            mat_list = self.query_one("#materials", SelectionList)
            mat_list.clear_options()
            for i, m in enumerate(materials, start=1):
                mtype = str(m.get("type", "material"))
                name = str(m.get("name", ""))
                icon = "📹" if mtype == "video" else "📝" if mtype == "test" else "📄"
                mat_list.add_option(Selection(f"{i}. {icon} {name}", value=i))
            self._materials_loaded = True
            self._post_assistant("Отметьте материалы Space (мультивыбор), затем нажмите `r` для запуска. `a` — выбрать всё.")
            return
        if evt.type == "picked":
            picked = evt.payload.get("picked", [])
            self._post_assistant(f"Выбрано материалов: {len(picked)}.")
            return
        if evt.type == "progress":
            cur = evt.payload.get("current")
            total = evt.payload.get("total")
            name = evt.payload.get("name", "")
            mtype = evt.payload.get("type", "")
            self.sub_title = f"В работе: {cur}/{total} • {mtype} • {name}"
            return
        if evt.type == "status":
            rows = [
                ["Готовность", "да" if evt.payload.get("ready") else "нет"],
                ["Семестры", ", ".join(map(str, evt.payload.get("semesters") or []))],
                ["Курсы", str(evt.payload.get("courses", 0))],
                ["Текущий курс", str(evt.payload.get("current_course") or "-")],
                ["Материалы", str(evt.payload.get("materials", 0))],
                ["Выбрано", str(evt.payload.get("picked", 0))],
            ]
            self._post_table("Статус", rows, headers=["Поле", "Значение"])
            return

    def on_input_submitted(self, event: Input.Submitted) -> None:
        raw = (event.value or "").strip()
        if not raw:
            return
        event.input.value = ""

        self._post_user(raw)

        if raw in ("/exit", "exit", "quit", "q"):
            self._cmd_q.put(Cmd("shutdown", {}))
            self._backend.stop()
            self.exit()
            return

        if raw in ("/help", "help", "?"):
            self._post_assistant(
                "Команды: `/start`, `/sem <N>`, `/open <I>`, `/pick all|1,2`, `/run`, `/stop`, `/status`, `/exit`."
            )
            return

        if raw == "/start":
            self._cmd_q.put(Cmd("start", {}))
            return

        if raw.startswith("/sem "):
            sem = raw.split(maxsplit=1)[1].strip()
            self._cmd_q.put(Cmd("select_semester", {"semester": sem}))
            return

        if raw.startswith("/open "):
            idx = raw.split(maxsplit=1)[1].strip()
            self._cmd_q.put(Cmd("open_course", {"index": idx}))
            return

        if raw.startswith("/pick "):
            spec = raw.split(maxsplit=1)[1].strip()
            self._cmd_q.put(Cmd("pick_materials", {"spec": spec}))
            return

        if raw == "/run":
            self._cmd_q.put(Cmd("run", {}))
            return

        if raw == "/stop":
            self._cmd_q.put(Cmd("stop_run", {}))
            return

        if raw == "/status":
            self._cmd_q.put(Cmd("status", {}))
            return

        self._post_assistant(f"Не понял команду: `{escape(raw)}`. `/help` — список команд.", level="warn")

    # ---------------------------
    # Arrow-driven UX (хоткеи + выбор Enter/Space)
    # ---------------------------

    def action_start(self) -> None:
        self._cmd_q.put(Cmd("start", {}))

    def action_stop(self) -> None:
        self._cmd_q.put(Cmd("stop_run", {}))

    def action_run(self) -> None:
        if not self._materials_loaded:
            self._post_assistant("Сначала выберите семестр и курс.", level="warn")
            return
        mat_list = self.query_one("#materials", SelectionList)
        selected = list(mat_list.selected)
        if not selected:
            self._post_assistant("Ничего не выбрано. Отметьте материалы Space или нажмите `a`.", level="warn")
            return
        self._cmd_q.put(Cmd("pick_materials", {"spec": selected}))
        self._cmd_q.put(Cmd("run", {}))

    def action_select_all(self) -> None:
        if not self._materials_loaded:
            return
        mat_list = self.query_one("#materials", SelectionList)
        mat_list.select_all()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        widget_id = getattr(event.option_list, "id", None)
        opt_id = getattr(event.option, "id", None)
        if not opt_id:
            return
        if widget_id == "semesters":
            self._cmd_q.put(Cmd("select_semester", {"semester": opt_id}))
            self.query_one("#courses", OptionList).focus()
        elif widget_id == "courses":
            self._cmd_q.put(Cmd("open_course", {"index": opt_id}))
            self.query_one("#materials", SelectionList).focus()

    def on_selection_list_selected_changed(self, event: SelectionList.SelectedChanged) -> None:
        try:
            self.sub_title = f"Выбрано материалов: {len(event.selection_list.selected)}"
        except Exception:
            pass


if __name__ == "__main__":
    SynergyTUI().run()

