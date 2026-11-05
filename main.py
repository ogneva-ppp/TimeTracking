"""
main.py — демонстрация работы модуля учёта времени.
Запуск: python main.py
"""
from datetime import datetime, timedelta

from task_system import Priority, TaskManager
from time_tracker import TimeTracker, format_duration


class DemoClock:
    """Ускоренные часы для демонстрации, чтобы не ждать реальные часы."""

    def __init__(self):
        self.now = datetime.now().replace(microsecond=0)

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


def demonstrate_time_tracking():
    manager = TaskManager()
    clock = DemoClock()
    tracker = TimeTracker(manager, clock=clock)

    ivan = manager.create_user("Иван Петров", "ivan@company.com")
    maria = manager.create_user("Мария Сидорова", "maria@company.com")

    due = datetime.now() + timedelta(days=7)
    auth = manager.create_task("Разработать модуль аутентификации",
                               "Вход и регистрация", Priority.HIGH, due)
    api = manager.create_task("Разработать REST API", "Эндпоинты задач", Priority.MEDIUM, due)
    manager.assign_task(auth.task_id, ivan.user_id)
    manager.assign_task(api.task_id, maria.user_id)

    print("▶ Иван запускает таймер:", auth)
    tracker.start_timer(auth.task_id)
    clock.advance(hours=1, minutes=40)
    tracker.stop_timer(auth.task_id)
    print("■ Таймер остановлен, затрачено:", format_duration(tracker.get_total_time(auth.task_id)))

    print("▶ Мария запускает таймер:", api)
    tracker.start_timer(api.task_id)
    clock.advance(minutes=50)
    print("  (таймер ещё идёт) текущее время по задаче:",
          format_duration(tracker.get_total_time(api.task_id)))

    print("▶ Иван продолжает работу над аутентификацией")
    tracker.start_timer(auth.task_id)
    clock.advance(minutes=35)
    tracker.stop_timer(auth.task_id)
    tracker.stop_timer(api.task_id)

    print()
    print(tracker.format_report())

    tracker.save_report("time_report.json")
    tracker.save_to_file("time_entries.json")
    print("\nОтчёт сохранён в time_report.json, записи — в time_entries.json")


if __name__ == "__main__":
    demonstrate_time_tracking()
