"""
test_time_tracker.py — модульные тесты модуля учёта времени.

Время подменяется «фальшивыми часами» (FakeClock), поэтому тесты
выполняются мгновенно и дают точные, предсказуемые результаты.

Запуск:  python -m unittest -v      или      python -m pytest -v
"""
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from task_system import Priority, Status, TaskManager
from time_tracker import (TaskNotFoundError, TimeTracker, TimeTrackerError,
                          TimerAlreadyRunningError, TimerNotRunningError,
                          UserNotFoundError, format_duration)


class FakeClock:
    """Управляемые часы: время меняется только через advance()."""

    def __init__(self, start: datetime):
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


class TimeTrackerTestBase(unittest.TestCase):
    def setUp(self):
        """Настройка тестовой среды"""
        self.clock = FakeClock(datetime(2026, 1, 1, 9, 0, 0))
        self.manager = TaskManager()
        self.user = self.manager.create_user("Иван Петров", "ivan@company.com")
        self.user2 = self.manager.create_user("Мария Сидорова", "maria@company.com")
        due = datetime(2026, 2, 1)
        self.task = self.manager.create_task("Модуль аутентификации", "Вход и регистрация",
                                             Priority.HIGH, due)
        self.task2 = self.manager.create_task("REST API", "Эндпоинты", Priority.MEDIUM, due)
        self.tracker = TimeTracker(self.manager, clock=self.clock)


class TestStartStop(TimeTrackerTestBase):
    """Требование 1: старт/остановка таймера"""

    def test_start_timer_creates_running_entry(self):
        entry = self.tracker.start_timer(self.task.task_id, self.user.user_id)
        self.assertTrue(entry.is_running)
        self.assertTrue(self.tracker.is_running(self.task.task_id))
        self.assertEqual(entry.start_time, self.clock.now)

    def test_stop_timer_closes_entry(self):
        self.tracker.start_timer(self.task.task_id, self.user.user_id)
        self.clock.advance(minutes=30)
        entry = self.tracker.stop_timer(self.task.task_id)
        self.assertFalse(entry.is_running)
        self.assertFalse(self.tracker.is_running(self.task.task_id))
        self.assertEqual(entry.duration(), timedelta(minutes=30))

    def test_double_start_raises(self):
        self.tracker.start_timer(self.task.task_id)
        with self.assertRaises(TimerAlreadyRunningError):
            self.tracker.start_timer(self.task.task_id)

    def test_stop_without_start_raises(self):
        with self.assertRaises(TimerNotRunningError):
            self.tracker.stop_timer(self.task.task_id)

    def test_timers_for_different_tasks_are_independent(self):
        self.tracker.start_timer(self.task.task_id)
        self.tracker.start_timer(self.task2.task_id)
        self.assertEqual(len(self.tracker.get_active_timers()), 2)
        self.tracker.stop_timer(self.task.task_id)
        self.assertTrue(self.tracker.is_running(self.task2.task_id))

    def test_stop_all(self):
        self.tracker.start_timer(self.task.task_id)
        self.tracker.start_timer(self.task2.task_id)
        stopped = self.tracker.stop_all()
        self.assertEqual(len(stopped), 2)
        self.assertEqual(self.tracker.get_active_timers(), [])

    def test_restart_after_stop(self):
        self.tracker.start_timer(self.task.task_id)
        self.tracker.stop_timer(self.task.task_id)
        self.tracker.start_timer(self.task.task_id)
        self.assertEqual(len(self.tracker.get_entries(task_id=self.task.task_id)), 2)


class TestTotalTime(TimeTrackerTestBase):
    """Требование 2: учёт общего затраченного времени"""

    def test_total_time_sums_sessions(self):
        for minutes in (30, 45, 15):
            self.tracker.start_timer(self.task.task_id)
            self.clock.advance(minutes=minutes)
            self.tracker.stop_timer(self.task.task_id)
            self.clock.advance(hours=1)  # перерыв не учитывается
        self.assertEqual(self.tracker.get_total_time(self.task.task_id), timedelta(minutes=90))

    def test_total_time_includes_running_timer(self):
        self.tracker.start_timer(self.task.task_id)
        self.clock.advance(minutes=20)
        self.assertEqual(self.tracker.get_total_time(self.task.task_id), timedelta(minutes=20))

    def test_total_time_zero_for_new_task(self):
        self.assertEqual(self.tracker.get_total_time(self.task.task_id), timedelta(0))

    def test_user_total_time(self):
        self.tracker.start_timer(self.task.task_id, self.user.user_id)
        self.tracker.start_timer(self.task2.task_id, self.user2.user_id)
        self.clock.advance(hours=1)
        self.tracker.stop_timer(self.task.task_id)
        self.clock.advance(hours=1)
        self.tracker.stop_timer(self.task2.task_id)
        self.assertEqual(self.tracker.get_user_total_time(self.user.user_id), timedelta(hours=1))
        self.assertEqual(self.tracker.get_user_total_time(self.user2.user_id), timedelta(hours=2))

    def test_manual_entry(self):
        start = datetime(2026, 1, 1, 10, 0)
        self.tracker.add_manual_entry(self.task.task_id, start, start + timedelta(hours=2),
                                      self.user.user_id, "забыл включить таймер")
        self.assertEqual(self.tracker.get_total_time(self.task.task_id), timedelta(hours=2))

    def test_manual_entry_invalid_interval(self):
        start = datetime(2026, 1, 1, 10, 0)
        with self.assertRaises(ValueError):
            self.tracker.add_manual_entry(self.task.task_id, start, start)

    def test_total_time_in_period_counts_only_overlap(self):
        start = datetime(2026, 1, 1, 10, 0)
        self.tracker.add_manual_entry(self.task.task_id, start, start + timedelta(hours=4))
        period = self.tracker.get_total_time(self.task.task_id,
                                             start=start + timedelta(hours=1),
                                             end=start + timedelta(hours=2))
        self.assertEqual(period, timedelta(hours=1))


class TestReports(TimeTrackerTestBase):
    """Требование 3: генерация отчётов"""

    def _fill(self):
        self.tracker.start_timer(self.task.task_id, self.user.user_id)
        self.clock.advance(hours=2)
        self.tracker.stop_timer(self.task.task_id)
        self.tracker.start_timer(self.task2.task_id, self.user2.user_id)
        self.clock.advance(minutes=30)
        self.tracker.stop_timer(self.task2.task_id)

    def test_report_totals(self):
        self._fill()
        report = self.tracker.generate_report()
        self.assertEqual(report["total_seconds"], int(timedelta(hours=2, minutes=30).total_seconds()))
        self.assertEqual(report["total_time"], "02:30:00")
        self.assertEqual(report["entries_count"], 2)

    def test_report_by_task_sorted_desc(self):
        self._fill()
        by_task = self.tracker.generate_report()["by_task"]
        self.assertEqual(by_task[0]["title"], "Модуль аутентификации")
        self.assertEqual(by_task[0]["time"], "02:00:00")
        self.assertEqual(by_task[1]["time"], "00:30:00")

    def test_report_by_user(self):
        self._fill()
        by_user = {u["name"]: u["time"] for u in self.tracker.generate_report()["by_user"]}
        self.assertEqual(by_user, {"Иван Петров": "02:00:00", "Мария Сидорова": "00:30:00"})

    def test_report_for_period(self):
        self._fill()  # 09:00–11:00 task, 11:00–11:30 task2
        report = self.tracker.generate_report(start=datetime(2026, 1, 1, 10, 0),
                                              end=datetime(2026, 1, 1, 11, 15))
        self.assertEqual(report["total_time"], "01:15:00")

    def test_empty_report(self):
        report = self.tracker.generate_report()
        self.assertEqual(report["total_seconds"], 0)
        self.assertEqual(report["by_task"], [])

    def test_format_report_text(self):
        self._fill()
        text = self.tracker.format_report()
        self.assertIn("Всего: 02:30:00", text)
        self.assertIn("Иван Петров", text)

    def test_save_report_and_entries_roundtrip(self):
        self._fill()
        self.tracker.start_timer(self.task.task_id)  # активный таймер тоже сохраняется
        with tempfile.TemporaryDirectory() as tmp:
            report_path = os.path.join(tmp, "report.json")
            data_path = os.path.join(tmp, "entries.json")
            self.tracker.save_report(report_path)
            self.assertTrue(os.path.exists(report_path))

            self.tracker.save_to_file(data_path)
            restored = TimeTracker(self.manager, clock=self.clock)
            restored.load_from_file(data_path)
            self.assertEqual(len(restored.entries), 3)
            self.assertTrue(restored.is_running(self.task.task_id))
            self.assertEqual(restored.get_total_time(self.task2.task_id), timedelta(minutes=30))

    def test_format_duration(self):
        self.assertEqual(format_duration(timedelta(seconds=0)), "00:00:00")
        self.assertEqual(format_duration(timedelta(hours=26, minutes=5, seconds=7)), "26:05:07")


class TestIntegration(TimeTrackerTestBase):
    """Требование 4: интеграция с системой задач"""

    def test_unknown_task_raises(self):
        with self.assertRaises(TaskNotFoundError):
            self.tracker.start_timer(999)
        with self.assertRaises(TaskNotFoundError):
            self.tracker.get_total_time(999)

    def test_unknown_user_raises(self):
        with self.assertRaises(UserNotFoundError):
            self.tracker.start_timer(self.task.task_id, user_id=999)

    def test_start_moves_task_to_in_progress(self):
        self.assertEqual(self.task.status, Status.TODO)
        self.tracker.start_timer(self.task.task_id)
        self.assertEqual(self.task.status, Status.IN_PROGRESS)

    def test_assignee_used_by_default(self):
        self.manager.assign_task(self.task.task_id, self.user2.user_id)
        entry = self.tracker.start_timer(self.task.task_id)
        self.assertEqual(entry.user_id, self.user2.user_id)

    def test_cannot_track_done_task(self):
        self.task.update_status(Status.DONE)
        with self.assertRaises(TimeTrackerError):
            self.tracker.start_timer(self.task.task_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
