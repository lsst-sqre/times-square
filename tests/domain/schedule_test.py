"""Tests for the schedule and schedulerule domains."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from dateutil.rrule import rruleset
from freezegun import freeze_time

from timessquare.domain.schedule import RunSchedule
from timessquare.domain.schedulerule import (
    ScheduleRules,
    ensure_timezone_aware,
)


@freeze_time("2020-01-01 00:00:00", tz_offset=0)
def test_schedule_rules_weekly() -> None:
    """Test the basic functionality of the RunSchedule class."""
    schedule_json = json.dumps(
        [
            {
                "freq": "weekly",
                "weekday": [{"day": "monday"}],
                "hour": "1",
                "minute": "30",
            }
        ]
    )
    schedule = RunSchedule(schedule_json, enabled=True)

    assert schedule.enabled is True
    assert isinstance(schedule.rules, ScheduleRules)
    assert isinstance(schedule.rruleset, rruleset)

    next_run = schedule.next(datetime(2025, 1, 2, 0, 0, tzinfo=UTC))
    # 2025-01-06 01:30:00 is the next Monday after 2025-01-02 00:00:00
    assert next_run == datetime(2025, 1, 6, 1, 30, tzinfo=UTC)


def test_schedule_rules_empty() -> None:
    """Test the RunSchedule class with an empty schedule."""
    schedule_json = json.dumps([])
    schedule = RunSchedule(schedule_json, enabled=False)

    assert schedule.enabled is False
    assert isinstance(schedule.rules, ScheduleRules)
    assert isinstance(schedule.rruleset, rruleset)

    next_run = schedule.next(datetime(2025, 1, 2, 0, 0, tzinfo=UTC))
    assert next_run is None  # No rules means no next run


def test_schedule_json_roundtrip() -> None:
    """Test that the schedule can be serialized and deserialized."""
    schedule_json = json.dumps(
        [
            {
                "freq": "weekly",
                "weekday": [{"day": "monday"}],
                "hour": "1",
                "minute": "30",
            }
        ]
    )
    schedule = RunSchedule(schedule_json, enabled=True)

    # Serialize to JSON
    serialized = schedule.rules.serialize_to_json()
    assert isinstance(serialized, str)

    # Deserialize from JSON
    deserialized_schedule = RunSchedule(serialized, enabled=True)
    assert deserialized_schedule.rules == schedule.rules
    assert deserialized_schedule.enabled is True
    assert isinstance(deserialized_schedule.rules, ScheduleRules)
    assert isinstance(deserialized_schedule.rruleset, rruleset)


@freeze_time("2020-01-01 00:00:00", tz_offset=0)
def test_schedule_rules_weekday_scalar() -> None:
    """Test the RunSchedule class with single weekday rather thnan ByWeekday
    object.
    """
    schedule_json = json.dumps(
        [
            {
                "freq": "weekly",
                "weekday": "tuesday",  # Single weekday as a string
                "hour": "2",
                "minute": "15",
            }
        ]
    )
    schedule = RunSchedule(schedule_json, enabled=True)

    assert schedule.enabled is True
    assert isinstance(schedule.rules, ScheduleRules)
    assert isinstance(schedule.rruleset, rruleset)

    next_run = schedule.next(datetime(2025, 1, 2, 0, 0, tzinfo=UTC))
    # 2025-01-07 02:15:00 is the next Tuesday after 2025-01-02 00:00:00
    assert next_run == datetime(2025, 1, 7, 2, 15, tzinfo=UTC)


@freeze_time("2020-01-01 00:00:00", tz_offset=0)
def test_schedule_from_start() -> None:
    """Test the RunSchedule class with a date-based schedule."""
    schedule_json = json.dumps(
        [
            {
                "start": "2025-01-01T03:00",  # Specific date
                "freq": "daily",
            }
        ]
    )
    schedule = RunSchedule(schedule_json, enabled=True)

    assert schedule.enabled is True
    assert isinstance(schedule.rules, ScheduleRules)
    assert isinstance(schedule.rruleset, rruleset)

    next_run = schedule.next(datetime(2025, 1, 2, 0, 0, tzinfo=UTC))
    # Note that the start is forced as UTC
    assert next_run == datetime(2025, 1, 2, 3, 0, tzinfo=UTC)


@freeze_time("2020-01-01 00:00:00", tz_offset=0)
def test_schedule_with_fixed_date() -> None:
    """Test the RunSchedule class with a fixed date."""
    schedule_json = json.dumps(
        [
            {
                "date": "2025-01-07T03:00",  # Specific date
            }
        ]
    )
    schedule = RunSchedule(schedule_json, enabled=True)

    assert schedule.enabled is True
    assert isinstance(schedule.rules, ScheduleRules)
    assert isinstance(schedule.rruleset, rruleset)

    next_run = schedule.next(datetime(2025, 1, 1, 0, 0, tzinfo=UTC))
    # Note that the start is forced as UTC
    assert next_run == datetime(2025, 1, 7, 3, 0, tzinfo=UTC)


@freeze_time("2020-06-05 19:45:00", tz_offset=0)
def test_schedule_by_minute() -> None:
    schedule_json = json.dumps(
        [
            {
                "freq": "minutely",
                "minute": list(range(0, 60, 5)),  # every 5 minutes
                "hour": None,  # No specific hour
            }
        ]
    )
    schedule = RunSchedule(schedule_json, enabled=True)

    assert schedule.enabled is True
    assert isinstance(schedule.rules, ScheduleRules)
    assert isinstance(schedule.rruleset, rruleset)

    next_run = schedule.next(datetime(2025, 6, 5, 19, 45, tzinfo=UTC))
    # Note that the start is forced as UTC
    assert next_run == datetime(2025, 6, 5, 19, 50, tzinfo=UTC)


@freeze_time("2026-04-11 00:00:00", tz_offset=0)
def test_schedule_from_date_with_count_json_roundtrip() -> None:
    """A from-date rule bounded by ``count`` (and therefore with no ``end``)
    must survive a serialize/deserialize round trip.

    ``ScheduleRules.serialize_to_json`` dumps with ``exclude_none=False``, so
    the unset ``end`` is persisted as an explicit ``null``. Re-parsing that
    stored form must not raise (DM-55467).
    """
    schedule_json = json.dumps(
        [
            {
                "start": "2025-12-01T14:00:00Z",
                "freq": "weekly",
                "interval": 2,
                "count": 300,
            }
        ]
    )
    schedule = RunSchedule(schedule_json, enabled=True)

    # Serialize the way the page store persists the schedule.
    serialized = schedule.rules.serialize_to_json()
    assert '"end":null' in serialized.replace(" ", "")

    # Re-parsing the persisted form is what runs on every schedule_runs tick.
    deserialized_schedule = RunSchedule(serialized, enabled=True)
    assert isinstance(deserialized_schedule.rules, ScheduleRules)
    assert isinstance(deserialized_schedule.rruleset, rruleset)

    next_run = deserialized_schedule.next(
        datetime(2026, 4, 11, 0, 0, tzinfo=UTC)
    )
    # The recurrence starts Monday 2025-12-01 and repeats every two weeks;
    # 2026-04-20 is the first occurrence after 2026-04-11.
    assert next_run == datetime(2026, 4, 20, 14, 0, tzinfo=UTC)
    assert next_run == schedule.next(datetime(2026, 4, 11, 0, 0, tzinfo=UTC))


def test_ensure_timezone_aware_passes_none_through() -> None:
    """The timezone-aware validator returns ``None`` unchanged."""
    assert ensure_timezone_aware(None) is None


def test_ensure_timezone_aware_normalizes_naive_datetime() -> None:
    """The timezone-aware validator assumes UTC for naive datetimes."""
    naive = datetime(2025, 12, 1, 14, 0)  # noqa: DTZ001
    assert ensure_timezone_aware(naive) == datetime(
        2025, 12, 1, 14, 0, tzinfo=UTC
    )


def test_ensure_timezone_aware_preserves_aware_datetime() -> None:
    """The timezone-aware validator leaves aware datetimes untouched."""
    aware = datetime(2025, 12, 1, 14, 0, tzinfo=UTC)
    assert ensure_timezone_aware(aware) is aware
