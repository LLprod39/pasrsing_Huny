"""Synergy HUB - Удобный TUI для автоматизации LMS Synergy.

Запуск:
  python scripts/tui.py
"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.containers import Container, Horizontal, Vertical, VerticalScroll, Center
from textual.widgets import (
    Button, Footer, Header, Label, OptionList, 
    ProgressBar, RichLog, SelectionList, Static, Rule
)
from textual.widgets.option_list import Option
from textual.widgets.selection_list import Selection
from textual.binding import Binding
from textual import on


# ═══════════════════════════════════════════════════════════════
# BACKEND
# ═══════════════════════════════════════════════════════════════

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
        except:
            pass


class SynergyBackend:
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

    def _emit(self, type_: str, **payload: Any) -> None:
        self.evt_q.put(Evt(type_, payload))

    def _attach_ui_logging(self) -> None:
        handler = _QueueLogHandler(self.evt_q)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
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
            self._emit("assistant", text="⚠️ Сессия не запущена", level="warn")
            return False
        return True

    def _run_loop(self) -> None:
        self._attach_ui_logging()
        self._emit("assistant", text="🚀 Готов к работе", level="info")

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
                    self._emit("assistant", text="⏸️ Останавливаю...", level="warn")
            except Exception as e:
                self._emit("assistant", text=f"❌ Ошибка: {e}", level="error")

        try:
            if self.auth_manager:
                self.auth_manager.close()
        except:
            pass

    def _cmd_start(self) -> None:
        self._emit("assistant", text="🔄 Запускаю браузер...")
        from synergy_lms.config import Config
        from synergy_lms.lms.auth import AuthManager
        from synergy_lms.lms.course_parser import CourseParser
        from synergy_lms.lms.material_processor import MaterialProcessor
        from synergy_lms.lms.test_solver import TestSolver

        Config.validate()
        self.auth_manager = AuthManager()
        if not self.auth_manager.login():
            raise RuntimeError("Не удалось авторизоваться")

        self.course_parser = CourseParser(self.auth_manager.driver)
        self.material_processor = MaterialProcessor(self.auth_manager.driver)
        self.test_solver = TestSolver(self.auth_manager.driver)
        self.semesters = self.course_parser.get_available_semesters()
        
        if not self.semesters:
            raise RuntimeError("Семестры не найдены")

        self._emit("semesters", semesters=self.semesters)
        self._emit("assistant", text="✅ Авторизация успешна!", level="info")
        self._emit("step", step=1)

    def _cmd_select_semester(self, semester: int) -> None:
        if not self._require_ready():
            return
        self._emit("assistant", text=f"📚 Загружаю курсы...")
        self.courses = self.course_parser.get_semester_courses(semester)
        if not self.courses:
            self._emit("assistant", text="Курсы не найдены", level="warn")
            return
        self.current_course = None
        self.current_materials = []
        self._emit("courses", courses=self.courses, semester=semester)
        self._emit("step", step=2)
        self._emit("assistant", text=f"✅ Найдено {len(self.courses)} курсов")

    def _cmd_open_course(self, index: int) -> None:
        if not self._require_ready():
            return
        if index < 1 or index > len(self.courses):
            return
        self.current_course = self.courses[index - 1]
        self._emit("assistant", text=f"📖 Загружаю материалы...")

        structured = self.course_parser.get_course_materials(self.current_course["url"])
        flat = self.course_parser.flatten_materials(structured)
        for m in flat:
            m["course_url"] = self.current_course["url"]
        self.current_materials = flat
        self._emit("materials", materials=self.current_materials, course=self.current_course)
        self._emit("step", step=3)
        self._emit("assistant", text=f"✅ Загружено {len(flat)} материалов")

    def _cmd_pick_materials(self, spec: Union[str, List[int]]) -> None:
        if not self._require_ready() or not self.current_materials:
            return
        if isinstance(spec, list):
            self.selected_material_indices = [int(i) for i in spec if 1 <= int(i) <= len(self.current_materials)]
        else:
            spec = str(spec).strip().lower()
            if spec in ("all", "все"):
                self.selected_material_indices = list(range(1, len(self.current_materials) + 1))

    def _cmd_run(self) -> None:
        if not self._require_ready() or not self.selected_material_indices:
            return

        self._stop_run.clear()
        picked = [self.current_materials[i - 1] for i in self.selected_material_indices]
        self._emit("assistant", text=f"▶️ Обработка {len(picked)} материалов...")
        ok = fail = 0

        for idx, material in enumerate(picked, start=1):
            if self._stop_run.is_set():
                self._emit("assistant", text="⏹️ Остановлено", level="warn")
                break

            name = material.get("name", "Без названия")
            mtype = material.get("type", "material")
            self._emit("progress", current=idx, total=len(picked), name=name)

            try:
                if mtype == "test":
                    res = self.test_solver.solve_test(material["url"], name, course_url=material.get("course_url"))
                    if res.get("solved"):
                        ok += 1
                        self._emit("assistant", text=f"✅ {name[:40]}")
                    else:
                        fail += 1
                        self._emit("assistant", text=f"❌ {name[:40]}", level="error")
                else:
                    res = self.material_processor.process_material(material)
                    if res.get("processed"):
                        ok += 1
                        self._emit("assistant", text=f"✅ {name[:40]}")
                    else:
                        fail += 1
                        self._emit("assistant", text=f"❌ {name[:40]}", level="error")
            except Exception as e:
                fail += 1
                self._emit("assistant", text=f"❌ {name[:30]}", level="error")

        self._emit("done", ok=ok, fail=fail)
        self._emit("assistant", text=f"🏁 Готово! ✅{ok} ❌{fail}")


# ═══════════════════════════════════════════════════════════════
# WELCOME SCREEN - Красивый стартовый экран
# ═══════════════════════════════════════════════════════════════

class WelcomeScreen(Screen):
    CSS = """
    WelcomeScreen {
        align: center middle;
        background: #1a1b26;
    }
    
    #main-box {
        width: 70;
        height: auto;
        background: #24283b;
        border: double #7aa2f7;
        padding: 2 4;
    }
    
    #logo {
        color: #7aa2f7;
        text-align: center;
        width: 100%;
    }
    
    #title {
        color: #bb9af7;
        text-style: bold;
        text-align: center;
        width: 100%;
        margin: 1 0 2 0;
    }
    
    .info {
        color: #a9b1d6;
        margin: 0 4;
    }
    
    #start-btn {
        width: 100%;
        height: 3;
        margin-top: 2;
        background: #7aa2f7;
        color: #1a1b26;
        border: none;
    }
    
    #start-btn:hover {
        background: #9ece6a;
    }
    
    #hint {
        color: #565f89;
        text-align: center;
        width: 100%;
        margin-top: 1;
    }
    """
    
    BINDINGS = [Binding("enter", "start", "Запустить", priority=True), Binding("q", "quit", "Выход")]

    def compose(self) -> ComposeResult:
        with Vertical(id="main-box"):
            yield Static("""
    ███████╗██╗   ██╗███╗   ██╗███████╗██████╗  ██████╗██╗   ██╗
    ██╔════╝╚██╗ ██╔╝████╗  ██║██╔════╝██╔══██╗██╔════╝╚██╗ ██╔╝
    ███████╗ ╚████╔╝ ██╔██╗ ██║█████╗  ██████╔╝██║  ███╗╚████╔╝ 
    ╚════██║  ╚██╔╝  ██║╚██╗██║██╔══╝  ██╔══██╗██║   ██║ ╚██╔╝  
    ███████║   ██║   ██║ ╚████║███████╗██║  ██║╚██████╔╝  ██║   
    ╚══════╝   ╚═╝   ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝   ╚═╝   
            """, id="logo")
            
            yield Static("AUTOMATION HUB v2.0", id="title")
            yield Rule()
            yield Static("  ✦ Автоматическая авторизация в LMS", classes="info")
            yield Static("  ✦ Парсинг семестров и курсов", classes="info")
            yield Static("  ✦ AI-решение тестов (Gemini)", classes="info")
            yield Static("  ✦ Автопросмотр видеоматериалов", classes="info")
            yield Rule()
            yield Button("🚀  ЗАПУСТИТЬ СЕССИЮ", id="start-btn", variant="primary")
            yield Static("Нажмите Enter или кликните кнопку", id="hint")

    def action_start(self) -> None:
        self.app.start_session()

    @on(Button.Pressed, "#start-btn")
    def on_start(self) -> None:
        self.action_start()


# ═══════════════════════════════════════════════════════════════
# MAIN SCREEN - Понятный и удобный интерфейс
# ═══════════════════════════════════════════════════════════════

class MainScreen(Screen):
    """Главный экран с понятным пошаговым интерфейсом."""
    
    CSS = """
    MainScreen {
        background: #1a1b26;
    }
    
    Header {
        background: #24283b;
        color: #7aa2f7;
    }
    
    Footer {
        background: #24283b;
    }
    
    /* ===== MAIN LAYOUT ===== */
    #content {
        height: 1fr;
        padding: 1;
    }
    
    /* ===== LEFT COLUMN - Steps ===== */
    #left-col {
        width: 45;
        background: #24283b;
        border: solid #3b4261;
        padding: 1 2;
        margin-right: 1;
    }
    
    .step-box {
        height: auto;
        margin-bottom: 1;
        padding: 1;
        background: #1a1b26;
        border: solid #3b4261;
    }
    
    .step-box.active {
        border: solid #7aa2f7;
        background: #292e42;
    }
    
    .step-box.done {
        border: solid #9ece6a;
    }
    
    .step-title {
        color: #7aa2f7;
        text-style: bold;
        margin-bottom: 1;
    }
    
    .step-title.done {
        color: #9ece6a;
    }
    
    #sem-list {
        height: 6;
        background: #1f2335;
    }
    
    #course-list {
        height: 10;
        background: #1f2335;
    }
    
    /* ===== RIGHT COLUMN - Materials & Log ===== */
    #right-col {
        width: 1fr;
    }
    
    /* Materials panel */
    #materials-panel {
        height: 2fr;
        background: #24283b;
        border: solid #3b4261;
        padding: 1;
        margin-bottom: 1;
    }
    
    #mat-header {
        height: 5;
        margin-bottom: 1;
    }
    
    #mat-title {
        color: #bb9af7;
        text-style: bold;
    }
    
    #mat-hint {
        color: #565f89;
        margin-top: 1;
    }
    
    #progress-area {
        height: 3;
        margin: 1 0;
    }
    
    #progress-area.hidden {
        display: none;
    }
    
    #mat-list {
        height: 1fr;
        background: #1f2335;
        border: solid #3b4261;
    }
    
    #mat-list:focus {
        border: solid #7aa2f7;
    }
    
    /* Action buttons */
    #mat-actions {
        height: 5;
        padding: 1 0;
        align: left middle;
    }
    
    #mat-actions Button {
        min-width: 16;
        height: 3;
        margin-right: 1;
    }
    
    /* Log panel */
    #log-panel {
        height: 1fr;
        background: #24283b;
        border: solid #3b4261;
        padding: 1;
    }
    
    #log-title {
        color: #e0af68;
        text-style: bold;
        margin-bottom: 1;
    }
    
    #log-view {
        height: 1fr;
        background: #1f2335;
        border: none;
    }
    
    /* ===== Lists styling ===== */
    OptionList, SelectionList {
        background: #1f2335;
        border: solid #3b4261;
    }
    
    OptionList:focus, SelectionList:focus {
        border: solid #7aa2f7;
    }
    
    OptionList > .option-list--option-highlighted {
        background: #7aa2f7;
        color: #1a1b26;
    }
    
    /* ===== Buttons ===== */
    Button {
        background: #3b4261;
        color: #c0caf5;
        border: none;
    }
    
    Button:hover {
        background: #7aa2f7;
        color: #1a1b26;
    }
    
    Button.-success {
        background: #9ece6a;
        color: #1a1b26;
    }
    
    Button.-error {
        background: #f7768e;
        color: #1a1b26;
    }
    
    Button:disabled {
        opacity: 0.4;
    }
    
    /* ===== Progress ===== */
    ProgressBar > .bar--bar {
        color: #7aa2f7;
        background: #3b4261;
    }
    
    ProgressBar > .bar--complete {
        color: #9ece6a;
    }
    """
    
    BINDINGS = [
        Binding("r", "run", "Запустить", show=True),
        Binding("s", "stop", "Стоп", show=True),
        Binding("a", "select_all", "Выбрать всё", show=True),
        Binding("q", "quit", "Выход", show=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        
        with Horizontal(id="content"):
            # === LEFT: Steps ===
            with Vertical(id="left-col"):
                # Step 1: Semester
                with Vertical(id="step1", classes="step-box active"):
                    yield Static("① ВЫБЕРИТЕ СЕМЕСТР", id="step1-title", classes="step-title")
                    yield OptionList(id="sem-list")
                
                # Step 2: Course
                with Vertical(id="step2", classes="step-box"):
                    yield Static("② ВЫБЕРИТЕ КУРС", id="step2-title", classes="step-title")
                    yield OptionList(id="course-list")
            
            # === RIGHT: Materials & Log ===
            with Vertical(id="right-col"):
                # Materials
                with Vertical(id="materials-panel"):
                    with Vertical(id="mat-header"):
                        yield Static("③ МАТЕРИАЛЫ ДЛЯ ОБРАБОТКИ", id="mat-title")
                        yield Static("Отметьте нужные материалы и нажмите ЗАПУСТИТЬ", id="mat-hint")
                        with Vertical(id="progress-area", classes="hidden"):
                            yield ProgressBar(id="progress", total=100)
                    
                    yield SelectionList(id="mat-list")
                    
                    with Horizontal(id="mat-actions"):
                        yield Button("▶ ЗАПУСТИТЬ", id="btn-run", variant="success", disabled=True)
                        yield Button("⏹ СТОП", id="btn-stop", variant="error", disabled=True)
                        yield Button("☑ Выбрать всё", id="btn-all")
                        yield Button("✕ Очистить", id="btn-clear")
                
                # Log
                with Vertical(id="log-panel"):
                    yield Static("📋 ЖУРНАЛ СОБЫТИЙ", id="log-title")
                    yield RichLog(id="log-view", markup=True, wrap=True)
        
        yield Footer()

    def on_mount(self) -> None:
        self.log_msg("🚀 Система запущена. Ожидание авторизации...", "info")

    def log_msg(self, msg: str, level: str = "info"):
        try:
            log = self.query_one("#log-view", RichLog)
            time_str = datetime.now().strftime("%H:%M:%S")
            colors = {"info": "#7aa2f7", "success": "#9ece6a", "warning": "#e0af68", "error": "#f7768e"}
            c = colors.get(level, "#a9b1d6")
            log.write(f"[{c}]{time_str} │ {msg}[/]")
        except:
            pass

    def set_step(self, step: int):
        """Подсветить текущий шаг."""
        for i in [1, 2]:
            box = self.query_one(f"#step{i}")
            title = self.query_one(f"#step{i}-title")
            box.remove_class("active")
            box.remove_class("done")
            title.remove_class("done")
            if i < step:
                box.add_class("done")
                title.add_class("done")
            elif i == step:
                box.add_class("active")

    # === Event Handlers ===
    
    @on(OptionList.OptionSelected, "#sem-list")
    def on_semester(self, event: OptionList.OptionSelected):
        if event.option.id:
            self.log_msg(f"📅 Семестр {event.option.id} выбран", "info")
            self.app.send_command("select_semester", event.option.id)

    @on(OptionList.OptionSelected, "#course-list")
    def on_course(self, event: OptionList.OptionSelected):
        if event.option.id:
            self.log_msg(f"📚 Загрузка курса...", "info")
            self.app.send_command("open_course", event.option.id)

    @on(SelectionList.SelectedChanged, "#mat-list")
    def on_selection(self, event: SelectionList.SelectedChanged):
        count = len(event.selection_list.selected)
        btn = self.query_one("#btn-run", Button)
        btn.disabled = count == 0
        if count > 0:
            self.query_one("#mat-hint", Static).update(f"Выбрано: {count} материалов")
        else:
            self.query_one("#mat-hint", Static).update("Отметьте материалы для обработки")

    @on(Button.Pressed, "#btn-run")
    def on_run(self):
        self.action_run()

    @on(Button.Pressed, "#btn-stop")
    def on_stop(self):
        self.action_stop()

    @on(Button.Pressed, "#btn-all")
    def on_all(self):
        self.action_select_all()

    @on(Button.Pressed, "#btn-clear")
    def on_clear(self):
        self.query_one("#mat-list", SelectionList).deselect_all()

    # === Actions ===
    
    def action_run(self):
        sl = self.query_one("#mat-list", SelectionList)
        selected = list(sl.selected)
        if not selected:
            self.app.notify("⚠️ Выберите материалы!", severity="warning")
            return
        
        self.log_msg(f"▶ Запуск: {len(selected)} материалов", "success")
        self.query_one("#btn-run", Button).disabled = True
        self.query_one("#btn-stop", Button).disabled = False
        self.query_one("#progress-area").remove_class("hidden")
        
        pb = self.query_one("#progress", ProgressBar)
        pb.update(total=len(selected), progress=0)
        
        self.app.send_command("pick_materials", selected)
        self.app.send_command("run")

    def action_stop(self):
        self.log_msg("⏹ Остановка...", "warning")
        self.app.send_command("stop_run")

    def action_select_all(self):
        self.query_one("#mat-list", SelectionList).select_all()


# ═══════════════════════════════════════════════════════════════
# MAIN APP
# ═══════════════════════════════════════════════════════════════

class SynergyTUI(App):
    TITLE = "SYNERGY HUB"
    SUB_TITLE = "LMS Automation"
    
    CSS = """
    Screen { background: #1a1b26; color: #c0caf5; }
    Header { background: #24283b; color: #7aa2f7; }
    Footer { background: #24283b; }
    FooterKey > .footer-key--key { background: #7aa2f7; color: #1a1b26; }
    """
    
    BINDINGS = [Binding("q", "quit", "Выход"), Binding("?", "help", "Помощь")]
    MODES = {"welcome": WelcomeScreen, "main": MainScreen}

    def __init__(self) -> None:
        super().__init__()
        self._cmd_q: queue.Queue[Cmd] = queue.Queue()
        self._evt_q: queue.Queue[Evt] = queue.Queue()
        self._backend = SynergyBackend(self._cmd_q, self._evt_q)

    def on_mount(self) -> None:
        self.switch_mode("welcome")
        self._backend.start()
        self.set_interval(0.1, self._process_events)

    def start_session(self):
        self._cmd_q.put(Cmd("start", {}))
        self.notify("🚀 Запуск...", title="Synergy HUB")
        self.switch_mode("main")

    def send_command(self, cmd: str, payload: Any = None):
        if cmd == "select_semester":
            self._cmd_q.put(Cmd("select_semester", {"semester": payload}))
        elif cmd == "open_course":
            self._cmd_q.put(Cmd("open_course", {"index": payload}))
        elif cmd == "pick_materials":
            self._cmd_q.put(Cmd("pick_materials", {"spec": payload}))
        elif cmd == "run":
            self._cmd_q.put(Cmd("run", {}))
        elif cmd == "stop_run":
            self._cmd_q.put(Cmd("stop_run", {}))

    def _process_events(self) -> None:
        for _ in range(100):
            try:
                evt = self._evt_q.get_nowait()
            except queue.Empty:
                break
            self._handle_event(evt)

    def _handle_event(self, evt: Evt) -> None:
        if not isinstance(self.screen, MainScreen):
            return
        
        screen: MainScreen = self.screen
        
        try:
            if evt.type == "assistant":
                text = evt.payload.get("text", "")
                level = evt.payload.get("level", "info")
                screen.log_msg(text, level)
                
            elif evt.type == "step":
                step = evt.payload.get("step", 1)
                screen.set_step(step)
                
            elif evt.type == "semesters":
                semesters = evt.payload.get("semesters", [])
                ol = screen.query_one("#sem-list", OptionList)
                ol.clear_options()
                for s in semesters:
                    ol.add_option(Option(f"📅 Семестр {s}", id=str(s)))
                self.notify(f"✅ {len(semesters)} семестров")
                
            elif evt.type == "courses":
                courses = evt.payload.get("courses", [])
                ol = screen.query_one("#course-list", OptionList)
                ol.clear_options()
                for i, c in enumerate(courses, 1):
                    name = c.get("name", "")[:35]
                    ctrl = c.get("control_type", "")
                    icon = "📗" if "зач" in ctrl else "📕" if "экз" in ctrl else "📘"
                    ol.add_option(Option(f"{icon} {name}", id=str(i)))
                screen.log_msg(f"✅ {len(courses)} курсов загружено", "success")
                
            elif evt.type == "materials":
                materials = evt.payload.get("materials", [])
                sl = screen.query_one("#mat-list", SelectionList)
                sl.clear_options()
                for i, m in enumerate(materials, 1):
                    mtype = m.get("type", "")
                    icons = {"video": "🎬", "test": "📝", "lecture": "📄"}
                    icon = icons.get(mtype, "📋")
                    name = m.get("name", "")[:45]
                    sl.add_option(Selection(f"{icon} {name}", value=i))
                screen.log_msg(f"✅ {len(materials)} материалов", "success")
                self.notify(f"📚 {len(materials)} материалов загружено")
                
            elif evt.type == "progress":
                cur = evt.payload.get("current", 0)
                total = evt.payload.get("total", 1)
                name = evt.payload.get("name", "")[:35]
                pb = screen.query_one("#progress", ProgressBar)
                pb.update(progress=cur, total=total)
                screen.query_one("#mat-hint", Static).update(f"[{cur}/{total}] {name}...")
                
            elif evt.type == "done":
                ok = evt.payload.get("ok", 0)
                fail = evt.payload.get("fail", 0)
                screen.query_one("#btn-run", Button).disabled = False
                screen.query_one("#btn-stop", Button).disabled = True
                screen.query_one("#progress-area").add_class("hidden")
                screen.query_one("#mat-hint", Static).update("Готово! Выберите ещё или закройте")
                self.notify(f"✅ Готово! Успешно: {ok}, ошибок: {fail}", severity="success")
                
        except:
            pass

    def action_help(self):
        self.notify(
            "[r] Запустить\n[s] Стоп\n[a] Выбрать всё\n[q] Выход",
            title="Горячие клавиши", timeout=8
        )


if __name__ == "__main__":
    SynergyTUI().run()
