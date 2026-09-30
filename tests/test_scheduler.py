"""Tests for WeeklyScheduler."""

import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from holy_energy_weekly_connection.exceptions import ConfigurationError
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
    assert sched.cron_expression == "30 9 * * 1"


def test_scheduler_invalid_time_fallback() -> None:
    sched = WeeklyScheduler(
        task=lambda: None,
        day_of_week="vendredi",
        time_str="invalid_time",
    )
    assert sched.target_day == 4
    assert sched.target_hour == 8
    assert sched.target_minute == 0
    assert sched.cron_expression == "0 8 * * 5"


def test_scheduler_custom_cron_valid() -> None:
    sched = WeeklyScheduler(
        task=lambda: None,
        cron_expression="0 14 * * 3",
        timezone_str="Europe/Paris",
    )
    assert sched.cron_expression == "0 14 * * 3"

    now = datetime(2026, 9, 30, 10, 0, tzinfo=ZoneInfo("Europe/Paris"))  # Wednesday
    next_run = sched.get_next_run(now)
    assert next_run == datetime(2026, 9, 30, 14, 0, tzinfo=ZoneInfo("Europe/Paris"))


def test_scheduler_custom_cron_invalid() -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        WeeklyScheduler(
            task=lambda: None,
            cron_expression="not a valid cron expression",
        )
    assert "Expression cron invalide" in str(exc_info.value)


def test_scheduler_stop_instantaneous() -> None:
    executed = []

    def sample_task() -> None:
        executed.append(True)

    sched = WeeklyScheduler(
        task=sample_task,
        cron_expression="0 0 1 1 *",  # Far in future
        run_immediately=False,
    )

    thread = threading.Thread(target=sched.start)
    t0 = time.time()
    thread.start()

    time.sleep(0.05)
    sched.stop()
    thread.join(timeout=2.0)

    elapsed = time.time() - t0
    assert not thread.is_alive()
    assert elapsed < 1.0
