"""Tests for WeeklyScheduler."""

from holy_energy_weekly_connection.scheduler import WeeklyScheduler


def test_scheduler_day_and_time_parsing() -> None:
    called = []

    def sample_task() -> None:
        called.append(True)

    sched = WeeklyScheduler(
        task=sample_task,
        day_of_week="lundi",
        time_str="09:30",
        timezone_str="Europe/Paris",
        run_immediately=False,
    )

    assert sched.target_day == 0
    assert sched.target_hour == 9
    assert sched.target_minute == 30
    assert sched.tz.key == "Europe/Paris"


def test_scheduler_invalid_time_fallback() -> None:
    sched = WeeklyScheduler(
        task=lambda: None,
        day_of_week="vendredi",
        time_str="invalid_time",
    )
    assert sched.target_day == 4
    assert sched.target_hour == 8
    assert sched.target_minute == 0
