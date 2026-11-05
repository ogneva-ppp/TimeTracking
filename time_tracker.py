"""
time_tracker.py — модуль учёта времени для системы управления задачами.

Возможности:
    1. Старт / остановка таймера для задачи   -> start_timer(), stop_timer()
    2. Учёт общего затраченного времени        -> get_total_time(), get_user_total_time()
    3. Генерация отчётов по времени            -> generate_report(), save_report()
    4. Интеграция с TaskManager из task_system -> проверка задач/пользователей,
                                                  автоперевод задачи в In Progress

Пример:
    manager = TaskManager()
    tracker = TimeTracker(manager)
    tracker.start_timer(task.task_id, user.user_id)
    ...
    tracker.stop_timer(task.task_id)
    print(format_duration(tracker.get_total_time(task.task_id)))
"""
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

from task_system import Status, TaskManager


# --------------------------------------------------------------------------- #
#  Исключения
# --------------------------------------------------------------------------- #
class TimeTrackerError(Exception):
    """Базовое исключение модуля учёта времени."""


class TaskNotFoundError(TimeTrackerError):
    """Задача с указанным id не существует."""


class UserNotFoundError(TimeTrackerError):
    """Пользователь с указанным id не существует."""


class TimerAlreadyRunningError(TimeTrackerError):
    """Попытка запустить таймер, который уже запущен."""


class TimerNotRunningError(TimeTrackerError):
    """Попытка остановить таймер, который не запущен."""


# --------------------------------------------------------------------------- #
#  Вспомогательные функции
# --------------------------------------------------------------------------- #
def format_duration(duration: timedelta) -> str:
    """Форматирует длительность в вид ЧЧ:ММ:СС (часы могут быть > 24)."""
    total = int(duration.total_seconds())
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


# --------------------------------------------------------------------------- #
#  Модель записи времени
# --------------------------------------------------------------------------- #
@dataclass
class TimeEntry:
    """Один отрезок работы над задачей."""
    entry_id: int
    task_id: int
    start_time: datetime
    user_id: Optional[int] = None
    end_time: Optional[datetime] = None
    note: str = ""

    @property
    def is_running(self) -> bool:
        return self.end_time is None

    def duration(self, now: Optional[datetime] = None) -> timedelta:
        """Длительность записи. Для активной записи считается до момента now."""
        end = self.end_time or now or datetime.now()
        return max(end - self.start_time, timedelta(0))

    def duration_in_period(self, start: Optional[datetime], end: Optional[datetime],
                           now: Optional[datetime] = None) -> timedelta:
        """Часть длительности, попадающая в период [start, end]."""
        entry_end = self.end_time or now or datetime.now()
        left = max(self.start_time, start) if start else self.start_time
        right = min(entry_end, end) if end else entry_end
        return max(right - left, timedelta(0))

    def to_dict(self) -> dict:
        return {
            "entry_id": self.entry_id,
            "task_id": self.task_id,
            "user_id": self.user_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TimeEntry":
        return cls(
            entry_id=data["entry_id"],
            task_id=data["task_id"],
            user_id=data.get("user_id"),
            start_time=datetime.fromisoformat(data["start_time"]),
            end_time=datetime.fromisoformat(data["end_time"]) if data.get("end_time") else None,
            note=data.get("note", ""),
        )


# --------------------------------------------------------------------------- #
#  Трекер времени
# --------------------------------------------------------------------------- #
@dataclass
class TimeTracker:
    """
    Учёт времени по задачам TaskManager.

    clock — функция, возвращающая текущее время. По умолчанию datetime.now,
    в тестах подменяется, чтобы не ждать реальные секунды.
    """
    task_manager: TaskManager
    clock: Callable[[], datetime] = datetime.now
    entries: List[TimeEntry] = field(default_factory=list)
    _active: Dict[int, TimeEntry] = field(default_factory=dict, repr=False)
    _next_entry_id: int = field(default=1, repr=False)

    # ---------------------- проверки (интеграция) ------------------------- #
    def _check_task(self, task_id: int):
        task = self.task_manager.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(f"Задача с id={task_id} не найдена")
        return task

    def _check_user(self, user_id: Optional[int]) -> None:
        if user_id is not None and self.task_manager.get_user(user_id) is None:
            raise UserNotFoundError(f"Пользователь с id={user_id} не найден")

    # ---------------------- 1. старт / стоп ------------------------------- #
    def start_timer(self, task_id: int, user_id: Optional[int] = None,
                    note: str = "") -> TimeEntry:
        """
        Запускает таймер для задачи.

        Если user_id не передан, берётся исполнитель задачи (если он есть).
        Задача в статусе To Do автоматически переводится в In Progress.
        """
        task = self._check_task(task_id)
        if task.status == Status.DONE:
            raise TimeTrackerError(f"Задача '{task.title}' уже завершена")
        if task_id in self._active:
            raise TimerAlreadyRunningError(f"Таймер для задачи id={task_id} уже запущен")

        if user_id is None and task.assignee is not None:
            user_id = task.assignee.user_id
        self._check_user(user_id)

        entry = TimeEntry(self._next_entry_id, task_id, self.clock(), user_id, note=note)
        self._next_entry_id += 1
        self.entries.append(entry)
        self._active[task_id] = entry

        if task.status == Status.TODO:
            task.update_status(Status.IN_PROGRESS)
        return entry

    def stop_timer(self, task_id: int) -> TimeEntry:
        """Останавливает таймер задачи и возвращает завершённую запись."""
        self._check_task(task_id)
        entry = self._active.pop(task_id, None)
        if entry is None:
            raise TimerNotRunningError(f"Таймер для задачи id={task_id} не запущен")
        entry.end_time = self.clock()
        return entry

    def stop_all(self) -> List[TimeEntry]:
        """Останавливает все активные таймеры (например, при выходе из программы)."""
        return [self.stop_timer(task_id) for task_id in list(self._active)]

    def is_running(self, task_id: int) -> bool:
        return task_id in self._active

    def get_active_timers(self) -> List[TimeEntry]:
        return list(self._active.values())

    def add_manual_entry(self, task_id: int, start_time: datetime, end_time: datetime,
                         user_id: Optional[int] = None, note: str = "") -> TimeEntry:
        """Ручное добавление отрезка (если забыли включить таймер)."""
        self._check_task(task_id)
        self._check_user(user_id)
        if end_time <= start_time:
            raise ValueError("Время окончания должно быть позже времени начала")
        entry = TimeEntry(self._next_entry_id, task_id, start_time, user_id, end_time, note)
        self._next_entry_id += 1
        self.entries.append(entry)
        return entry

    # ---------------------- 2. учёт общего времени ------------------------ #
    def get_entries(self, task_id: Optional[int] = None, user_id: Optional[int] = None,
                    start: Optional[datetime] = None,
                    end: Optional[datetime] = None) -> List[TimeEntry]:
        """Записи с фильтрами по задаче, пользователю и периоду."""
        now = self.clock()
        result = []
        for e in self.entries:
            if task_id is not None and e.task_id != task_id:
                continue
            if user_id is not None and e.user_id != user_id:
                continue
            if (start or end) and e.duration_in_period(start, end, now) == timedelta(0):
                continue
            result.append(e)
        return result

    def _sum(self, entries: List[TimeEntry], start=None, end=None) -> timedelta:
        now = self.clock()
        return sum((e.duration_in_period(start, end, now) for e in entries), timedelta(0))

    def get_total_time(self, task_id: int, start: Optional[datetime] = None,
                       end: Optional[datetime] = None) -> timedelta:
        """Общее время по задаче (включая текущий запущенный отрезок)."""
        self._check_task(task_id)
        return self._sum(self.get_entries(task_id=task_id), start, end)

    def get_user_total_time(self, user_id: int, start: Optional[datetime] = None,
                            end: Optional[datetime] = None) -> timedelta:
        """Общее время, затраченное пользователем."""
        self._check_user(user_id)
        return self._sum(self.get_entries(user_id=user_id), start, end)

    # ---------------------- 3. отчёты ------------------------------------- #
    def generate_report(self, start: Optional[datetime] = None,
                        end: Optional[datetime] = None) -> dict:
        """
        Отчёт по времени за период (по умолчанию — за всё время).
        Отрезки, частично попадающие в период, учитываются только своей частью.
        """
        now = self.clock()
        entries = self.get_entries(start=start, end=end)

        by_task: Dict[int, timedelta] = {}
        by_user: Dict[Optional[int], timedelta] = {}
        for e in entries:
            d = e.duration_in_period(start, end, now)
            by_task[e.task_id] = by_task.get(e.task_id, timedelta(0)) + d
            by_user[e.user_id] = by_user.get(e.user_id, timedelta(0)) + d

        total = sum(by_task.values(), timedelta(0))

        tasks_section = []
        for task_id, d in sorted(by_task.items(), key=lambda kv: kv[1], reverse=True):
            task = self.task_manager.get_task(task_id)
            tasks_section.append({
                "task_id": task_id,
                "title": task.title,
                "status": task.status.value,
                "priority": task.priority.name,
                "seconds": int(d.total_seconds()),
                "time": format_duration(d),
            })

        users_section = []
        for user_id, d in sorted(by_user.items(), key=lambda kv: kv[1], reverse=True):
            user = self.task_manager.get_user(user_id) if user_id is not None else None
            users_section.append({
                "user_id": user_id,
                "name": user.name if user else "Не указан",
                "seconds": int(d.total_seconds()),
                "time": format_duration(d),
            })

        return {
            "period_start": start.isoformat() if start else None,
            "period_end": end.isoformat() if end else None,
            "total_seconds": int(total.total_seconds()),
            "total_time": format_duration(total),
            "entries_count": len(entries),
            "active_timers": len(self._active),
            "by_task": tasks_section,
            "by_user": users_section,
            "report_generated_at": now.isoformat(),
        }

    def format_report(self, report: Optional[dict] = None) -> str:
        """Текстовое представление отчёта для вывода в консоль."""
        report = report or self.generate_report()
        lines = ["Отчёт по затраченному времени",
                 f"Всего: {report['total_time']} (записей: {report['entries_count']}, "
                 f"активных таймеров: {report['active_timers']})",
                 "", "По задачам:"]
        lines += [f"  - {t['title']} [{t['status']}, {t['priority']}]: {t['time']}"
                  for t in report["by_task"]] or ["  нет данных"]
        lines += ["", "По исполнителям:"]
        lines += [f"  - {u['name']}: {u['time']}" for u in report["by_user"]] or ["  нет данных"]
        return "\n".join(lines)

    def save_report(self, filename: str, start: Optional[datetime] = None,
                    end: Optional[datetime] = None) -> dict:
        report = self.generate_report(start, end)
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        return report

    # ---------------------- сохранение / загрузка ------------------------- #
    def save_to_file(self, filename: str) -> None:
        """Сохраняет все записи времени в JSON."""
        with open(filename, "w", encoding="utf-8") as f:
            json.dump([e.to_dict() for e in self.entries], f, ensure_ascii=False, indent=2)

    def load_from_file(self, filename: str) -> None:
        """Загружает записи из JSON (активные записи снова становятся таймерами)."""
        with open(filename, encoding="utf-8") as f:
            data = json.load(f)
        self.entries = [TimeEntry.from_dict(d) for d in data]
        self._active = {e.task_id: e for e in self.entries if e.is_running}
        self._next_entry_id = max((e.entry_id for e in self.entries), default=0) + 1
