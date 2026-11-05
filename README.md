# Модуль учёта времени для системы управления задачами

Практическое задание к лекции №5 «Этапы разработки программного продукта».

## Структура проекта

| Файл | Назначение | Этап ЖЦ (по лекции) |
|---|---|---|
| `task_system.py` | Существующая система задач: `Priority`, `Status`, `User`, `Task`, `TaskManager` | 2.2 Проектирование |
| `time_tracker.py` | **Модуль учёта времени**: `TimeTracker`, `TimeEntry`, исключения, `format_duration` | 2.3 Реализация |
| `test_time_tracker.py` | 27 модульных тестов (unittest, совместимы с pytest) | 2.4 Тестирование |
| `main.py` | Демонстрация работы модуля | — |
| `requirements.txt` | Необязательные зависимости для тестов и покрытия | 2.5 Внедрение |

Сам модуль использует только стандартную библиотеку Python (3.8+).

## Соответствие требованиям

1. **Старт/остановка таймера** — `start_timer(task_id, user_id=None)`, `stop_timer(task_id)`,
   `stop_all()`, `is_running()`, `get_active_timers()`. Повторный старт и стоп без старта
   вызывают `TimerAlreadyRunningError` / `TimerNotRunningError`.
2. **Учёт общего времени** — `get_total_time(task_id)` и `get_user_total_time(user_id)`;
   учитывается и идущий таймер. Можно задать период `start`/`end`.
   Есть `add_manual_entry()`, если таймер забыли включить.
3. **Отчёты** — `generate_report(start, end)` возвращает словарь (итог, по задачам, по
   исполнителям), `format_report()` — текст для консоли, `save_report()` — JSON-файл.
   Отрезки, частично попавшие в период, учитываются только своей частью.
4. **Интеграция** — трекер принимает `TaskManager`, проверяет существование задач и
   пользователей, по умолчанию записывает время на исполнителя задачи, переводит задачу
   из *To Do* в *In Progress* и не даёт трекать завершённые (*Done*) задачи.

Дополнительно: сохранение и загрузка записей (`save_to_file` / `load_from_file`).

## Пример использования

```python
from datetime import datetime, timedelta
from task_system import TaskManager, Priority
from time_tracker import TimeTracker, format_duration

manager = TaskManager()
user = manager.create_user("Иван Петров", "ivan@company.com")
task = manager.create_task("REST API", "Эндпоинты", Priority.HIGH,
                           datetime.now() + timedelta(days=7))

tracker = TimeTracker(manager)
tracker.start_timer(task.task_id, user.user_id)
# ... работа ...
tracker.stop_timer(task.task_id)

print(format_duration(tracker.get_total_time(task.task_id)))
print(tracker.format_report())
```

## Запуск

```bash
python main.py                    # демонстрация
python -m unittest -v             # тесты
python -m pytest -v               # тесты через pytest (pip install pytest)
python -m pytest --cov=time_tracker --cov-report=term-missing   # покрытие
```

## Тестирование

Время в тестах подменяется управляемыми часами `FakeClock` (параметр `clock` у
`TimeTracker`), поэтому тесты мгновенные и детерминированные.
Результат: 27 тестов, все проходят; покрытие `time_tracker.py` — 99%.
